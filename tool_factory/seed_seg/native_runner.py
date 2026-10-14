"""Run the pinned supplied inference, normalizing only its verified empty export.

The supplied pipeline deliberately creates no particle STL for an empty set,
but its final CLI renames that nonexistent file. No fake STL or detector output
is substituted here. Other inference/export errors remain process failures.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

EMPTY_SUFFIX = '_verified_empty_result.json'


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def empty_export_receipt(output, name, *, max_voxels=128_000_000):
    import numpy as np
    import SimpleITK as sitk
    output = Path(output)
    paths = {role: output / (name + suffix) for role, suffix in
             [('native_mask', '_particle_labels.nii.gz'), ('positions_csv', '_particle_positions.csv'),
              ('markups_json', '_particle_positions.json')]}
    if any(path.is_symlink() or not path.is_file() for path in paths.values()):
        raise ValueError('Empty export requires three real regular native artifacts')
    with paths['positions_csv'].open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ['id', 'cz_vox', 'cy_vox', 'cx_vox', 'x_mm', 'y_mm', 'z_mm'] or next(reader, None) is not None:
            raise ValueError('Empty export CSV must use the native schema and contain no centers')
    if paths['markups_json'].stat().st_size > 1_000_000:
        raise ValueError('Empty native Markups exceeds the bounded record size')
    markups = json.loads(paths['markups_json'].read_text(encoding='utf-8-sig'))
    if (not isinstance(markups, dict) or len(markups.get('markups', [])) != 1
            or markups['markups'][0].get('type') != 'Fiducial'
            or markups['markups'][0].get('coordinateSystem') != 'LPS'
            or markups['markups'][0].get('coordinateUnits') != 'mm'
            or markups['markups'][0].get('controlPoints') != []):
        raise ValueError('Empty native Markups must contain an explicitly empty LPS point set')
    reader = sitk.ImageFileReader()
    reader.SetFileName(str(paths['native_mask']))
    reader.ReadImageInformation()
    if reader.GetDimension() != 3 or math.prod(reader.GetSize()) > max_voxels:
        raise ValueError('Empty native mask exceeds the bounded grid')
    image = reader.Execute()
    if np.any(sitk.GetArrayViewFromImage(image)):
        raise ValueError('Empty native export has foreground voxels')
    return {'schema_version': 1, 'seed_count': 0, 'particle_model': None,
            'export_state': 'verified_empty_native_artifacts', 'clinical_use_ready': False,
            'zero_detections_proves_zero_implant': False,
            'artifact_sha256': {role: file_hash(path) for role, path in paths.items()}}


def run_native(module, ct, output, *, weights, device, sw_batch_size):
    name = module.case_name(Path(ct))
    try:
        return module._run_inference(ct, output, weights_value=weights, device_name=device,
                                     sw_batch_size=sw_batch_size)
    except FileNotFoundError as exc:
        # Only the documented last rename, after inference and all other real
        # exports, is eligible. Missing weights, inputs or any intermediate
        # artifact must never become a successful empty result.
        expected = Path(output) / (name + '_difference_seeds_model.stl')
        if Path(str(exc.filename or '')).absolute() != expected.absolute():
            raise
        names = {name + suffix for suffix in ['_particle_labels.nii.gz', '_particle_positions.csv', '_particle_positions.json']}
        if {path.name for path in Path(output).iterdir()} != names:
            raise
        receipt = empty_export_receipt(output, name)
        (Path(output) / (name + EMPTY_SUFFIX)).write_text(json.dumps(receipt, sort_keys=True, allow_nan=False), encoding='utf-8')
        return {'case': name, 'seed_count': 0, 'model': None, 'review_required': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-entry', required=True)
    parser.add_argument('--ct', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--weights', required=True)
    parser.add_argument('--device', required=True)
    parser.add_argument('--sw-batch-size', type=int, required=True)
    args = parser.parse_args()
    entry = Path(args.native_entry).resolve(strict=True)
    sys.path.insert(0, str(entry.parent))
    spec = importlib.util.spec_from_file_location('brachybot_pinned_seedfinder_entry', entry)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    result = run_native(module, args.ct, args.output, weights=args.weights, device=args.device, sw_batch_size=args.sw_batch_size)
    print(json.dumps({'seed_count': result['seed_count'], 'empty_model_not_applicable': result.get('model') is None}))


if __name__ == '__main__':
    main()
