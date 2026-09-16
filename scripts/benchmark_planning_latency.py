"""Replay saved planning inputs without writing a Session or invoking UI hooks.

Run sequential baseline/current processes under the same environment. The
baseline restores only the frozen pre-optimization hot functions, NOT a whole
historical application. Output contains hashes/metrics, never CT or mask arrays.
No GPU jobs are stopped or reassigned. This still consumes CPU/GPU resources.
"""
import argparse
import copy
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np
import SimpleITK as sitk
from plans import utilizations, geometry
from plans.dose_pre import inference
from tool_factory.seed_plan import planning_pipeline


class DetachedMemory:
    def __init__(self, values, ui_state):
        self.planning_results = values
        self.patient_data = {}
        self.ui_state = ui_state

    def retrieve(self, key, default=None):
        return self.planning_results.get(key, default)

    def store(self, key, value, **kwargs):
        self.planning_results[key] = value

    def delete(self, key):
        self.planning_results.pop(key, None)


def fingerprint(value):
    digest = hashlib.sha256()

    def visit(v):
        if isinstance(v, np.ndarray):
            digest.update(str((v.shape, v.dtype.str)).encode())
            digest.update(np.ascontiguousarray(v).tobytes())
        elif isinstance(v, dict):
            for key in sorted(v):
                digest.update(str(key).encode())
                visit(v[key])
        elif isinstance(v, (list, tuple)):
            for item in v:
                visit(item)
        elif isinstance(v, np.generic):
            visit(v.item())
        else:
            digest.update(repr(v).encode())

    visit(value)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variant', choices=['baseline', 'current'], default='current')
    parser.add_argument('--mode', choices=['rule_based', 'rl'], default='rule_based')
    parser.add_argument('--deterministic', action='store_true',
                        help='Validation only: pin CUDA algorithm selection in this replay process')
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    output = args.output.resolve()
    # Never allow the replay output to replace source Session artifacts.
    if output.is_relative_to(workspace):
        parser.error('--output must be outside the source workspace')
    if output.exists():
        parser.error('--output already exists; choose a fresh filename')

    if args.deterministic:
        # Do not change the application's normal GPU/TF32 policy. Pin only
        # this standalone replay so autotuning cannot obscure CPU equivalence.
        import torch
        os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
        torch.manual_seed(915)
        torch.use_deterministic_algorithms(True)
        original_configure = inference._configure_cuda_inference

        def configure(device):
            original_configure(device)
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True

        inference._configure_cuda_inference = configure

    if args.variant == 'baseline':
        frozen = json.loads((REPO / 'tests/latency_reference.json').read_text())
        from scripts.latency_dependency_guard import verify_dependencies
        verify_dependencies(REPO, frozen)
        for module in [utilizations, geometry, inference, planning_pipeline]:
            for source in frozen['functions'][module.__name__.split('.')[-1]].values():
                exec(compile(source, '<latency-baseline>', 'exec'), module.__dict__)

    from web.workspace_store import _decode_artifacts
    started = time.perf_counter()
    source = (workspace / 'snapshot.json').read_bytes()
    snapshot = json.loads(source)
    raw = snapshot['agent']['planning_results']
    keys = [
        'ct_path', 'ctv_array', 'ctv_mask', 'ctv_binary_array', 'ctv_label_map',
        'ctv_source', 'oar_array', 'organ_names', 'structure_overrides',
        'structure_catalog', 'embedded_obstacle_label_ids', 'obstacle_label_ids',
        'obstacle_label_source', 'ct_source_meta', 'ctv_volume_mm3',
    ]
    values = {key: _decode_artifacts(raw[key], workspace) for key in keys if key in raw}
    agent = SimpleNamespace(
        memory=DetachedMemory(values, copy.deepcopy(snapshot['agent'].get('ui_state', {}))),
        config=copy.deepcopy(snapshot['agent']['config']),
    )
    config = copy.deepcopy(agent.config)
    config.update(raw['plan_config']['planning_parameters'])
    if raw['plan_config'].get('seed_info'):
        config['seed_info'] = raw['plan_config']['seed_info']
    tool = planning_pipeline.PlanningPipelineTool()
    ct = tool._load_ct({'ct_image_path': values['ct_path']}, agent)
    ctv = tool._load_ctv({}, agent, ct)
    oar = tool._load_oar({}, agent, ct)
    oar, _ = planning_pipeline._merge_embedded_hard_obstacles(oar, agent)
    direction = planning_pipeline._resolve_ref_direc('auto', ct, ctv, agent)
    loaded = time.perf_counter()
    np.random.seed(915)
    def progress(stage, status, content=None):
        print(json.dumps({'stage': stage, 'status': status, 'content': content}), flush=True)

    result = tool._run_full_pipeline(
        ct, ctv, oar, direction, args.mode, config, agent, step_callback=progress,
    )
    finished = time.perf_counter()
    memory = agent.memory
    result_keys = [
        'trajectories', 'refined_trajectories', 'seed_plan_serialized',
        'verified_needle_geometry', 'dose_distribution', 'dose_distribution_gy',
        'dose_metrics', 'algorithm_plan_dvh_data',
    ]
    summary = {
        'variant': args.variant, 'success': result.success, 'error': result.error,
        'deterministic_validation': args.deterministic,
        'snapshot_sha256': hashlib.sha256(source).hexdigest(),
        'inputs_sha256': fingerprint([
            sitk.GetArrayViewFromImage(ct), ct.GetOrigin(), ct.GetSpacing(),
            ct.GetDirection(), ctv, oar, direction, config,
        ]),
        'load_seconds': loaded - started,
        'pipeline_seconds': finished - loaded,
        'substep_timings': result.metadata.get('substep_timings'),
        'latency_profile': result.metadata.get('latency_profile'),
        'hashes': {key: fingerprint(memory.retrieve(key)) for key in result_keys if memory.retrieve(key) is not None},
        'total_seeds': memory.retrieve('total_seeds'),
        'num_trajectories': memory.retrieve('num_trajectories'),
        'metrics': {key: (memory.retrieve('dose_metrics') or {}).get(key) for key in ['v100', 'v150', 'v200', 'd90']},
        'coverage_repair_status': memory.retrieve('coverage_repair_status'),
        'planning_latency_budget_status': memory.retrieve('planning_latency_budget_status'),
    }
    from scripts.latency_comparison import equivalence_eligibility
    summary['same_result_claim_eligibility'] = equivalence_eligibility(summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        json.dump(summary, handle, indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if result.success else 1


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
