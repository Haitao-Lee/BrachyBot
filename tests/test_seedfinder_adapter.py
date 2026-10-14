"""No SeedFinder/model execution: owned synthetic files and fake process runners."""

from dataclasses import replace
import csv
import json
import os
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import pytest
import SimpleITK as sitk

from tool_factory.seed_seg.seedfinder_adapter import (
    CODE_FILES, PREPROCESSING_CONTRACT, SeedFinderAdapter, SeedFinderModelContract,
    SeedFinderRequest, SubprocessSeedFinderRunner, SUPPLIED_CODE_SHA256, SUPPLIED_MODEL_SHA256, sha256_file,
)
from utils.implant_reconstruction import (
    ImageGeometry, ImageReference, PhysicalPCAOrientationProvider,
    ReconstructionCancelled, ReconstructionDeadlineExceeded,
)


@pytest.fixture
def owned_request(tmp_path):
    inputs, runtime, bundle = (tmp_path / name for name in ("input-owner", "runtime-owner", "trusted-bundle"))
    for directory in (inputs, runtime, bundle):
        directory.mkdir()
    # Pinned inert stand-ins exercise the adapter contract without torch imports.
    (bundle / CODE_FILES[0]).write_text(
        'def load_model(path):\n    raw = torch.load(path, map_location="cpu", weights_only=True)\n'
        '    model.load_state_dict(raw, strict=True)\n',
        encoding="utf-8")
    for filename in CODE_FILES[1:]:
        (bundle / filename).write_text("# inert test fixture; never imported\n", encoding="utf-8")
    model = bundle / "weights.pth"
    model.write_bytes(b"opaque-test-weights-never-deserialized")
    image = sitk.GetImageFromArray(np.full((32, 32, 32), -500, dtype=np.float32))
    image.SetSpacing((0.5, 0.5, 0.5))
    image.SetOrigin((-30, 43, 11))
    image.SetDirection((0, 0, 1, 1, 0, 0, 0, 1, 0))
    ct = inputs / "scan_resampled.nii.gz"
    sitk.WriteImage(image, str(ct))
    reference = ImageReference("session-owned", "intra-owned", "ct-owned", 2, sha256_file(ct),
                               ImageGeometry.from_image(image))
    contract = SeedFinderModelContract(str(bundle), str(model), sha256_file(model),
                                      tuple((name, sha256_file(bundle / name)) for name in CODE_FILES))
    return SeedFinderRequest(reference, str(ct), str(inputs), str(runtime), str(runtime / "job-output"),
                             sys.executable, contract)


def write_outputs(prepared, *, empty=False):
    request = prepared.request
    output = Path(request.output_dir)
    output.mkdir(exist_ok=True)
    shutil.copyfile(request.ct_path, output / prepared.ct_output_name)
    original = sitk.ReadImage(request.ct_path)
    array = np.zeros((14, 14, 14), dtype=np.uint8)
    if not empty:
        array[3, 4, 2:7] = 1
    mask = sitk.GetImageFromArray(array)
    mask.SetSpacing((1, 1, 1))
    mask.SetOrigin(original.GetOrigin())
    mask.SetDirection(original.GetDirection())
    sitk.WriteImage(mask, str(output / (prepared.case_name + "_particle_labels.nii.gz")))
    points = [] if empty else [mask.TransformContinuousIndexToPhysicalPoint(index) for index in ((3, 4, 3), (5, 4, 3))]
    csv_path = output / (prepared.case_name + "_particle_positions.csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "cz_vox", "cy_vox", "cx_vox", "x_mm", "y_mm", "z_mm"])
        for i, point in enumerate(points):
            writer.writerow([f"7.{i + 1}", 3, 4, 3 + i * 2, *point])
    document = {"markups": [{"type": "Fiducial", "coordinateSystem": "LPS", "coordinateUnits": "mm",
                             "controlPoints": [{"position": point, "positionStatus": "defined",
                                                "orientation": [1, 0, 0, 0, 1, 0, 0, 0, 1]}
                                               for point in points]}]}
    (output / (prepared.case_name + "_particle_positions.json")).write_text(json.dumps(document), encoding="utf-8")
    return points


class SyntheticRunner:
    def __init__(self, *, empty=False, status=0):
        self.calls = []
        self.empty = empty
        self.status = status

    def execute(self, prepared, *, cancelled=None):
        self.calls.append(prepared)
        write_outputs(prepared, empty=self.empty)
        return self.status


def test_prepare_is_read_only_shell_free_and_preserves_supplied_training_contract(owned_request):
    runner = SyntheticRunner()
    prepared = SeedFinderAdapter(runner).prepare(owned_request)
    assert not runner.calls
    assert not Path(owned_request.output_dir).exists()
    assert prepared.command == (
        str(Path(sys.executable).resolve()), "-B", str(Path(owned_request.model_contract.bundle_dir) / CODE_FILES[0]),
        "--ct", owned_request.ct_path, "--output", owned_request.output_dir,
        "--weights", owned_request.model_contract.model_path, "--device", "cpu", "--sw-batch-size", "1")
    assert prepared.case_name == "scan"
    assert prepared.ct_output_name == "scan_CT.nii.gz"
    assert prepared.provenance.preprocessing_contract == PREPROCESSING_CONTRACT
    assert "xyz(1,1,5)" in prepared.provenance.preprocessing_contract
    assert prepared.provenance.model_sha256 == owned_request.model_contract.model_sha256
    assert len(prepared.provenance.preprocessing_sha256) == 64


def test_supplied_bundle_contract_uses_reviewed_pins_without_self_approving_files(owned_request):
    contract = SeedFinderModelContract.for_supplied_bundle(owned_request.model_contract.bundle_dir)
    assert contract.code_sha256 == SUPPLIED_CODE_SHA256
    assert contract.model_sha256 == SUPPLIED_MODEL_SHA256
    assert contract.model_path.endswith("models/best_autoencoder.pth")
    assert contract.artifact_schema == "native_model_v2"
    with pytest.raises(ValueError, match="absolute"):
        SeedFinderModelContract.for_supplied_bundle("relative-bundle")


class UpdatedSyntheticRunner:
    def execute(self, prepared, *, cancelled=None):
        write_outputs(prepared)
        output = Path(prepared.request.output_dir)
        (output / prepared.ct_output_name).unlink()
        # A closed tetrahedron tests structural STL parsing, not clinical geometry.
        from web.surgical_guide import mesh_to_ascii_stl
        vertices = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
        faces = np.asarray([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=int)
        (output / (prepared.case_name + "_particle_model.stl")).write_bytes(mesh_to_ascii_stl(vertices, faces))
        return 0


def test_native_verified_zero_has_no_fake_stl_and_still_requires_coverage_review(owned_request):
    from tool_factory.seed_seg.native_runner import EMPTY_SUFFIX, empty_export_receipt
    class NativeZeroRunner:
        def execute(self, prepared, *, cancelled=None):
            write_outputs(prepared, empty=True)
            output = Path(prepared.request.output_dir)
            (output / prepared.ct_output_name).unlink()
            receipt = empty_export_receipt(output, prepared.case_name)
            (output / (prepared.case_name + EMPTY_SUFFIX)).write_text(json.dumps(receipt), encoding='utf-8')
            return 0
    request = updated_request(owned_request)
    detected = SeedFinderAdapter(NativeZeroRunner()).run(request)
    assert detected.detections == ()
    assert {row.role for row in detected.artifacts} == {'native_mask', 'positions_csv', 'markups_json', 'native_empty_receipt'}
    assert not list(Path(request.output_dir).glob('*.stl'))
    assert 'zero_detections_does_not_prove_zero_implant' in detected.diagnostics


def test_native_empty_compatibility_refuses_inference_failures_or_nonempty_exports(owned_request):
    from types import SimpleNamespace
    from tool_factory.seed_seg.native_runner import run_native, EMPTY_SUFFIX
    request = updated_request(owned_request)
    prepared = SeedFinderAdapter().prepare(request)
    output = Path(request.output_dir)
    write_outputs(prepared)
    (output / prepared.ct_output_name).unlink()
    args = dict(weights=request.model_contract.model_path, device='cpu', sw_batch_size=1)
    def missing_weights(*values, **kwargs):
        raise FileNotFoundError(2, 'missing weights', request.model_contract.model_path)
    module = SimpleNamespace(case_name=lambda path: prepared.case_name, _run_inference=missing_weights)
    with pytest.raises(FileNotFoundError):
        run_native(module, request.ct_path, output, **args)
    def missing_model(*values, **kwargs):
        raise FileNotFoundError(2, 'native zero STL rename', str(output / (prepared.case_name + '_difference_seeds_model.stl')))
    module._run_inference = missing_model
    with pytest.raises(ValueError, match='contain no centers'):
        run_native(module, request.ct_path, output, **args)
    assert not (output / (prepared.case_name + EMPTY_SUFFIX)).exists()


def updated_request(request):
    bundle = Path(request.model_contract.bundle_dir)
    code = (
        "import numpy as np\n"
        "def cluster_needles_xy_plane(points, z_eps=2.0, xy_eps=5.0):\n"
        "    assert z_eps == 2.0 and xy_eps == 5.0\n"
        "    return np.tile([1., 0., 0.], (len(points), 1)), np.arange(len(points))\n"
    )
    (bundle / "seed_pipeline_deepdec_roi.py").write_text(code, encoding="utf-8")
    contract = replace(request.model_contract, artifact_schema="native_model_v2",
                       code_sha256=tuple((name, sha256_file(bundle / name)) for name in CODE_FILES))
    return replace(request, model_contract=contract)


def test_updated_four_artifact_contract_reuses_native_direction_code(owned_request):
    request = updated_request(owned_request)
    adapter = SeedFinderAdapter(UpdatedSyntheticRunner())
    detected = adapter.run(request)
    assert {a.role for a in detected.artifacts} == {"native_mask", "positions_csv", "markups_json", "particle_model"}
    assert not (Path(request.output_dir) / "scan_CT.nii.gz").exists()
    assert ImageGeometry.from_image(detected.original_ct) == request.image_ref.geometry
    reconstructed = adapter.reconstruct(detected)
    assert reconstructed.provider_id == "supplied-seedfinder-xy-deposition"
    assert [s.center_lps_mm for s in reconstructed.observations] == [s.center_lps_mm for s in detected.detections]
    assert all(s.axis_lps == (1., 0., 0.) and s.axis_source == "provider_estimate" for s in reconstructed.observations)
    assert all("supplied_global_direction_fallback_for_singleton" in s.diagnostics for s in reconstructed.observations)
    assert reconstructed.review_status == "review_needed" and not reconstructed.dose_input_ready
    assert all(s.dimensions is None and s.presentation.glyph == "point_halo" for s in reconstructed.observations)


def test_updated_import_refuses_changed_source_ct(owned_request):
    request = updated_request(owned_request)
    adapter = SeedFinderAdapter(UpdatedSyntheticRunner())
    prepared = adapter.prepare(request)
    adapter.runner.execute(prepared)
    Path(request.ct_path).write_bytes(b"changed-after-submit")
    with pytest.raises(ValueError, match="captured CT changed"):
        adapter.load_outputs(prepared)


def test_pinned_native_fractional_centroid_uses_exact_rounded_physical_export(owned_request):
    request = updated_request(owned_request)
    adapter = SeedFinderAdapter(UpdatedSyntheticRunner())
    prepared = adapter.prepare(request)
    adapter.runner.execute(prepared)
    path = Path(request.output_dir) / (prepared.case_name + "_particle_positions.csv")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["cx_vox"] = str(float(row["cx_vox"]) + .35)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    detected = adapter.load_outputs(prepared)
    assert len(detected.detections) == 2
    assert "supplied_fractional_csv_centroid_physical_point_uses_exact_rounded_native_index" in detected.diagnostics
    # An arbitrary discrepancy still fails the original tolerance; do not
    # substitute the fractional point or increase the tolerance to fit it.
    rows[0]["x_mm"] = str(float(rows[0]["x_mm"]) + 2.0)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    with pytest.raises(ValueError, match="physical coordinates disagree"):
        adapter.load_outputs(prepared)


def test_updated_provider_refuses_changed_code_and_never_silently_falls_back(owned_request):
    request = updated_request(owned_request)
    adapter = SeedFinderAdapter(UpdatedSyntheticRunner())
    detected = adapter.run(request)
    Path(request.model_contract.bundle_dir, "seed_pipeline_deepdec_roi.py").write_text("# changed", encoding="utf-8")
    with pytest.raises(ValueError, match="source changed"):
        adapter.reconstruct(detected)


def test_updated_model_artifact_has_its_own_resource_limit(owned_request):
    request = replace(updated_request(owned_request), max_model_bytes=10)
    with pytest.raises(ValueError, match="byte limit"):
        SeedFinderAdapter(UpdatedSyntheticRunner()).run(request)


def test_synthetic_output_import_preserves_lps_and_shared_component_associations(owned_request):
    runner = SyntheticRunner()
    result = SeedFinderAdapter(runner).run(owned_request)
    assert len(runner.calls) == 1
    assert len(result.detections) == 2
    mask = result.native_component_labels
    expected = [mask.TransformContinuousIndexToPhysicalPoint(index) for index in ((3, 4, 3), (5, 4, 3))]
    assert [d.center_lps_mm for d in result.detections] == expected
    assert [d.detection_id for d in result.detections] == ["7.1", "7.2"]
    assert all(d.component_ids == (1,) and d.association_status == "associated" for d in result.detections)
    assert result.review_status == "review_needed" and result.coverage_status == "unknown"
    assert "markups_orientation_ignored" in result.diagnostics
    assert ImageGeometry.from_image(result.original_grid_mask) == owned_request.image_ref.geometry
    assert len(result.artifacts) == 4
    for artifact in result.artifacts:
        assert sha256_file(Path(artifact.path)) == artifact.sha256
    # Geometry is independently evaluated in original index space.
    for center in expected:
        index = result.original_grid_mask.TransformPhysicalPointToIndex(center)
        assert result.original_grid_mask[index] == 1


def test_reconstruction_has_replaceable_provider_and_detector_provenance(owned_request):
    adapter = SeedFinderAdapter(SyntheticRunner())
    detected = adapter.run(owned_request)
    reconstructed = adapter.reconstruct(detected)
    assert [s.center_lps_mm for s in reconstructed.observations] == [d.center_lps_mm for d in detected.detections]
    assert all(s.axis_lps is None for s in reconstructed.observations)
    provenance = dict(reconstructed.detector_provenance)
    assert provenance["model_sha256"] == owned_request.model_contract.model_sha256
    assert provenance["input_sha256"] == owned_request.image_ref.image_sha256

    class SuppliedReplacement(PhysicalPCAOrientationProvider):
        provider_id = "replacement-test-provider"
        provider_version = "0.2"

    alternate = adapter.reconstruct(detected, provider=SuppliedReplacement())
    assert alternate.provider_id == "replacement-test-provider"
    assert alternate.provider_version == "0.2"


def test_provider_cannot_snap_or_move_detected_centers(owned_request):
    adapter = SeedFinderAdapter(SyntheticRunner())
    detected = adapter.run(owned_request)

    class MovingProvider(PhysicalPCAOrientationProvider):
        def estimate_seed_axes(self, *args, **kwargs):
            result = super().estimate_seed_axes(*args, **kwargs)
            return replace(result, observations=(replace(result.observations[0], center_lps_mm=(0, 0, 0)),
                                                  result.observations[1]))

    with pytest.raises(ValueError, match="preserve detected centers"):
        adapter.reconstruct(detected, provider=MovingProvider())


def test_empty_results_are_review_needed_and_do_not_certify_coverage(owned_request):
    result = SeedFinderAdapter(SyntheticRunner(empty=True)).run(owned_request)
    assert result.detections == ()
    assert "zero_detections_does_not_prove_zero_implant" in result.diagnostics
    assert result.coverage_status == "unknown"
    assert not sitk.GetArrayFromImage(result.original_grid_mask).any()


def test_ambiguous_component_mapping_remains_explicit(owned_request):
    adapter, prepared = staged(owned_request)
    root = Path(owned_request.output_dir)
    path = root / "scan_particle_labels.nii.gz"
    mask = sitk.ReadImage(str(path))
    array = np.zeros((14, 14, 14), dtype=np.uint8)
    array[3, 3, 3] = 1
    array[3, 5, 3] = 1
    revised = sitk.GetImageFromArray(array)
    revised.CopyInformation(mask)
    sitk.WriteImage(revised, str(path))
    result = adapter.load_outputs(prepared)
    assert result.detections[0].component_ids == (1, 2)
    assert result.detections[0].association_status == "ambiguous"
    assert result.review_status == "review_needed"
    assert "component_point_association_requires_review" in result.diagnostics


@pytest.mark.parametrize("field", ["model_sha256", "code_sha256"])
def test_changed_model_or_code_pins_fail_before_process_execution(owned_request, field):
    runner = SyntheticRunner()
    contract = owned_request.model_contract
    if field == "model_sha256":
        contract = replace(contract, model_sha256="f" * 64)
    else:
        contract = replace(contract, code_sha256=((CODE_FILES[0], "f" * 64),) + contract.code_sha256[1:])
    with pytest.raises(ValueError, match="hash"):
        SeedFinderAdapter(runner).run(replace(owned_request, model_contract=contract))
    assert not runner.calls
    assert not Path(owned_request.output_dir).exists()


def test_missing_model_pin_and_unsafe_loader_fail_closed(owned_request):
    with pytest.raises(ValueError, match="pinned"):
        replace(owned_request.model_contract, model_sha256="")
    entry = Path(owned_request.model_contract.bundle_dir) / CODE_FILES[0]
    entry.write_text('raw = torch.load("anything", weights_only=False)\n', encoding="utf-8")
    contract = replace(owned_request.model_contract, code_sha256=tuple(
        (name, sha256_file(Path(owned_request.model_contract.bundle_dir) / name)) for name in CODE_FILES))
    with pytest.raises(ValueError, match="weights_only"):
        SeedFinderAdapter().prepare(replace(owned_request, model_contract=contract))


def test_changed_ct_revision_and_geometry_fail_closed(owned_request):
    with pytest.raises(ValueError, match="CT hash"):
        SeedFinderAdapter().prepare(replace(owned_request, image_ref=replace(owned_request.image_ref, image_sha256="f" * 64)))
    geometry = replace(owned_request.image_ref.geometry, origin_lps_mm=(0, 0, 0))
    with pytest.raises(ValueError, match="geometry"):
        SeedFinderAdapter().prepare(replace(owned_request, image_ref=replace(owned_request.image_ref, geometry=geometry)))


@pytest.mark.parametrize("target", ["outside", "root", "existing", "relative", "bundle"])
def test_output_must_be_new_leaf_under_owned_runtime(owned_request, tmp_path, target):
    output = {
        "outside": str(tmp_path / "output"), "root": owned_request.owned_runtime_root,
        "existing": owned_request.output_dir, "relative": "output",
        "bundle": str(Path(owned_request.model_contract.bundle_dir) / "output"),
    }[target]
    if target == "existing":
        Path(output).mkdir()
    with pytest.raises(ValueError):
        SeedFinderAdapter().prepare(replace(owned_request, output_dir=output))


def test_symlink_cannot_escape_owned_input_root(owned_request, tmp_path):
    outside = tmp_path / "external.nii.gz"
    shutil.copyfile(owned_request.ct_path, outside)
    link = Path(owned_request.owned_input_root) / "link.nii.gz"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks unavailable in this test environment")
    with pytest.raises(ValueError, match="owned root"):
        SeedFinderAdapter().prepare(replace(owned_request, ct_path=str(link)))


def test_runtime_cannot_be_the_bundle_writable_area(owned_request):
    bundle = owned_request.model_contract.bundle_dir
    with pytest.raises(ValueError, match="supplied bundle"):
        SeedFinderAdapter().prepare(replace(owned_request, owned_runtime_root=bundle,
                                           output_dir=str(Path(bundle) / "job-output")))


def test_accelerator_runs_require_an_explicit_execution_guard(owned_request):
    runner = SyntheticRunner()
    with pytest.raises(ValueError, match="lease"):
        SeedFinderAdapter(runner).run(replace(owned_request, device="cuda"))
    assert not runner.calls
    with pytest.raises(ValueError, match="explicit device"):
        replace(owned_request, device="auto")


def test_pre_cancelled_or_expired_run_never_executes(owned_request):
    runner = SyntheticRunner()
    adapter = SeedFinderAdapter(runner)
    with pytest.raises(ReconstructionCancelled):
        adapter.run(owned_request, cancelled=lambda: True)
    with pytest.raises(ReconstructionDeadlineExceeded):
        adapter.run(replace(owned_request, deadline_monotonic=time.monotonic() - 1))
    assert not runner.calls


def test_failed_process_leaves_only_unpublished_owned_staging(owned_request):
    with pytest.raises(RuntimeError, match="unpublishable"):
        SeedFinderAdapter(SyntheticRunner(status=7)).run(owned_request)
    assert Path(owned_request.output_dir).is_dir()
    with pytest.raises(ValueError, match="new output"):
        SeedFinderAdapter(SyntheticRunner()).run(owned_request)


def test_midrun_cancellation_prevents_artifact_publication(owned_request):
    cancelled = False

    class CancellingRunner(SyntheticRunner):
        def execute(self, prepared, **kwargs):
            nonlocal cancelled
            status = super().execute(prepared, **kwargs)
            cancelled = True
            return status

    with pytest.raises(ReconstructionCancelled):
        SeedFinderAdapter(CancellingRunner()).run(owned_request, cancelled=lambda: cancelled)
    assert Path(owned_request.output_dir).is_dir()


def staged(owned_request):
    adapter = SeedFinderAdapter()
    prepared = adapter.prepare(owned_request)
    write_outputs(prepared)
    return adapter, prepared


@pytest.mark.parametrize("corruption", ["extra", "missing", "ct", "nonbinary", "csv_position", "csv_id",
                                        "json_ras", "json_position", "json_count", "zero_points"])
def test_corrupt_artifacts_cannot_be_imported(owned_request, corruption):
    adapter, prepared = staged(owned_request)
    root = Path(owned_request.output_dir)
    csv_path = root / "scan_particle_positions.csv"
    json_path = root / "scan_particle_positions.json"
    if corruption == "extra":
        (root / "unexpected").write_text("test")
    elif corruption == "missing":
        json_path.unlink()
    elif corruption == "ct":
        (root / prepared.ct_output_name).write_bytes(b"changed-input")
    elif corruption == "nonbinary":
        path = root / "scan_particle_labels.nii.gz"
        image = sitk.ReadImage(str(path))
        image[3, 4, 3] = 2
        sitk.WriteImage(image, str(path))
    elif corruption in ("csv_position", "csv_id", "zero_points"):
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        if corruption == "csv_position":
            rows[1][4] = "999"
        elif corruption == "csv_id":
            rows[2][0] = rows[1][0]
        else:
            rows = rows[:1]
            doc = json.loads(json_path.read_text())
            doc["markups"][0]["controlPoints"] = []
            json_path.write_text(json.dumps(doc))
        with csv_path.open("w", newline="") as handle:
            csv.writer(handle).writerows(rows)
    else:
        doc = json.loads(json_path.read_text())
        markup = doc["markups"][0]
        if corruption == "json_ras":
            markup["coordinateSystem"] = "RAS"
        elif corruption == "json_position":
            markup["controlPoints"][0]["position"][0] += 1
        elif corruption == "json_count":
            markup["controlPoints"].pop()
        json_path.write_text(json.dumps(doc))
    with pytest.raises((ValueError, RuntimeError)):
        adapter.load_outputs(prepared)


def test_output_symlink_cannot_substitute_an_artifact(owned_request, tmp_path):
    adapter, prepared = staged(owned_request)
    path = Path(owned_request.output_dir) / "scan_particle_positions.json"
    external = tmp_path / "external.json"
    shutil.copyfile(path, external)
    path.unlink()
    try:
        path.symlink_to(external)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError, match="symlinks"):
        adapter.load_outputs(prepared)


def test_export_and_image_resource_limits_are_enforced(owned_request):
    with pytest.raises(ValueError, match="size"):
        SeedFinderAdapter().prepare(replace(owned_request, max_image_voxels=10))
    adapter, prepared = staged(owned_request)
    prepared = replace(prepared, request=replace(prepared.request, max_text_bytes=8))
    with pytest.raises(ValueError, match="byte limit"):
        adapter.load_outputs(prepared)


def test_process_runner_uses_owned_temp_and_terminates_on_cancellation(owned_request, monkeypatch):
    import tool_factory.seed_seg.seedfinder_adapter as module

    prepared = SeedFinderAdapter().prepare(owned_request)
    state = {"started": False, "terminated": False}
    captured = {}

    class Process:
        pid = 92345
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            state["terminated"] = True
            self.returncode = -15
            return self.returncode

        def terminate(self):
            state["terminated"] = True

    def popen(command, **options):
        captured.update(command=command, options=options)
        state["started"] = True
        assert Path(options["env"]["TMPDIR"]).is_relative_to(Path(owned_request.owned_runtime_root))
        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module.os, "killpg", lambda *args: None, raising=False)
    with pytest.raises(ReconstructionCancelled):
        SubprocessSeedFinderRunner().execute(prepared, cancelled=lambda: state["started"])
    assert state["terminated"]
    options = captured["options"]
    assert options["cwd"] == owned_request.owned_runtime_root
    assert "shell" not in options
    assert "PYTHONPATH" not in options["env"]
    assert options["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert not Path(options["env"]["TMPDIR"]).exists()
