"""Owned synthetic volumes and inert workers; no supplied inference or GPU probes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, asdict, replace
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time
from uuid import uuid4

import numpy as np
import pytest
import SimpleITK as sitk

from tool_factory.seed_seg import SeedSegmentationTool
from tool_factory.seed_seg.seedfinder_adapter import (
    CODE_FILES, PreparedSeedFinderRun, SeedFinderAdapter, SeedFinderArtifact, SeedFinderDetectionResult,
    SeedFinderProvenance, SeedFinderModelContract, sha256_file,
)
from utils.cancellation import OperationCancelled, cancellation_scope
from utils.implant_reconstruction import (
    AxisDiagnostics, ImageGeometry, ImageReference, ObservationReview, ReconstructionDeadlineExceeded,
    SeedAxisReconstruction, SeedDetection, SeedObservation, seed_presentation,
)
from web.implant_service import (
    IMPLANT_MEMORY_KEY, ImplantInput, ImplantReviewAuthorization, ImplantReviewRequest,
    ImplantScope, ImplantService, ImplantServiceError, LeasedSeedFinderRunner, SeedFinderRuntimeConfig,
    _file_lock,
)


class Memory:
    def __init__(self, sid):
        self.session_id = sid
        self._lock = threading.RLock()
        self.values = {"seed_plan": {"planned_count": 99, "directions": [[0, 0, 1]]},
                       "ct_path": "unrelated-mounted-image", "dose_distribution_gy": "preserved-baseline"}
        self.writes = 0
        self.fail_next_store = False

    def retrieve(self, name, default=None):
        with self._lock:
            return self.values.get(name, default)

    def store(self, name, value):
        with self._lock:
            if self.fail_next_store:
                self.fail_next_store = False
                raise RuntimeError("synthetic crash after disk commit before memory publication")
            self.values[name] = value
            self.writes += 1


@pytest.fixture
def owned(tmp_path):
    workspace = tmp_path / "owned-workspace"
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True)
    bundle = tmp_path / "configured-bundle"
    (bundle / "models").mkdir(parents=True)
    for name in CODE_FILES:
        (bundle / name).write_text("# inert worker fixture; never imported or executed\n")
    (bundle / "models" / "best_autoencoder.pth").write_bytes(b"never-loaded-test-weights")
    image = sitk.GetImageFromArray(np.full((16, 18, 20), -500, dtype=np.float32))
    image.SetSpacing((0.7, 1.1, 1.4))
    image.SetOrigin((-17, 32, 11))
    image.SetDirection((0, 0, 1, 1, 0, 0, 0, 1, 0))
    ct = inputs / "owned_scan.nii.gz"
    sitk.WriteImage(image, str(ct))
    image = sitk.ReadImage(str(ct))
    sid, tp = uuid4().hex, uuid4().hex
    reference = ImageReference(sid, tp, uuid4().hex, 3, sha256_file(ct), ImageGeometry.from_image(image))
    scope = ImplantScope("owner-a", sid, tp, str(workspace))
    source = ImplantInput(reference, str(ct), str(inputs), uuid4().hex)
    runtime = SeedFinderRuntimeConfig(str(bundle), sys.executable)
    return scope, source, runtime, Memory(sid)


class Workers:
    def __init__(self):
        self.events = []
        self.lease_active = self.lock_active = False
        self.calls = 0
        self.empty = False
        self.fail = False
        self.autoaccept = False
        self.after_run = None
        self.barrier = None
        self.last_request = None
        self.leased_device = None

    @contextmanager
    def lease(self, *, caller, prefer):
        self.events.append(("lease-enter", prefer))
        self.lease_active = True
        try:
            yield SimpleNamespace(device_str=self.leased_device or ("cpu" if prefer == "cpu" else "cuda:" + prefer))
        finally:
            self.lease_active = False
            self.events.append(("lease-exit", prefer))

    @contextmanager
    def lock(self, device, *, cancelled, deadline):
        assert self.lease_active
        self.events.append(("lock-enter", device))
        self.lock_active = True
        try:
            yield
        finally:
            self.lock_active = False
            self.events.append(("lock-exit", device))

    def adapter(self, runner):
        workers = self

        class InertAdapter:
            def prepare(self, request, *, cancelled=None):
                assert not workers.lease_active and not workers.lock_active
                assert request.model_contract == SeedFinderModelContract.for_supplied_bundle(request.model_contract.bundle_dir)
                workers.last_request = request
                workers.events.append(("prepare", request.device))

            def run(self, request, *, cancelled=None, execution_guard=None):
                assert workers.lease_active and workers.lock_active and execution_guard is not None
                workers.events.append(("run", request.device))
                workers.calls += 1
                if workers.fail:
                    raise RuntimeError("synthetic detector failure")
                original = sitk.ReadImage(request.ct_path)
                array = np.zeros(original.GetSize()[::-1], dtype=np.uint8)
                indices = [] if workers.empty else [(4, 6, 7), (12, 8, 10)]
                for index in indices:
                    array[index[::-1]] = 1
                mask = sitk.GetImageFromArray(array)
                mask.CopyInformation(original)
                components = sitk.ConnectedComponent(mask, True)
                output = Path(request.output_dir)
                output.mkdir()
                mask_path = output / "native.nii.gz"
                sitk.WriteImage(mask, str(mask_path))
                csv_path, json_path, stl_path = (output / name for name in ("points.csv", "points.json", "model.stl"))
                csv_path.write_text("synthetic typed worker result\n")
                json_path.write_text("{}")
                stl_path.write_bytes(b"inert worker result; not rendered")
                artifacts = tuple(SeedFinderArtifact(role, str(path), sha256_file(path)) for role, path in (
                    ("native_mask", mask_path), ("positions_csv", csv_path),
                    ("markups_json", json_path), ("particle_model", stl_path)))
                detections = tuple(SeedDetection(str(i), original.TransformIndexToPhysicalPoint(index), (i + 1,),
                                                  association_status="associated") for i, index in enumerate(indices))
                provenance = SeedFinderProvenance(request.model_contract.contract_id,
                                                  request.model_contract.model_sha256, request.model_contract.code_sha256,
                                                  "synthetic worker", "a" * 64, request.image_ref.image_sha256,
                                                  request.image_ref.geometry.signature, request.device, request.sw_batch_size)
                result = SeedFinderDetectionResult(request.image_ref, detections, artifacts, provenance, mask, components,
                                                   original, native_orientation_contract=request.model_contract)
                if workers.after_run:
                    workers.after_run()
                if workers.barrier:
                    workers.barrier.wait(timeout=5)
                return result

            def reconstruct(self, detected, **kwargs):
                # Verify that the service delegates selection to the supplied
                # adapter default rather than supplying preop axes/a replacement.
                assert "provider" not in kwargs
                assert workers.lease_active and workers.lock_active
                observations = tuple(SeedObservation(
                    observation_id=uuid4().hex, detection_id=d.detection_id,
                    center_lps_mm=d.center_lps_mm, axis_lps=(1, 0, 0), axis_source="provider_estimate",
                    local_diagnostics=AxisDiagnostics(flags=("synthetic_provider_requires_review",)),
                    component_ids=d.component_ids, candidate_line_ids=(),
                    diagnostics=("supplied_XY_plane_constraint_requires_review",),
                    presentation=seed_presentation("review_needed", True),
                    center_uncertainty_mm=d.center_uncertainty_mm, component_association_status=d.association_status,
                    dimensions=kwargs["dimensions"],
                    review_status="accepted" if workers.autoaccept else "review_needed",
                    reviewer_id="fake-auto-reviewer" if workers.autoaccept else None,
                    review_evidence="fake-auto-evidence" if workers.autoaccept else None,
                ) for d in detected.detections)
                return SeedAxisReconstruction(uuid4().hex, uuid4().hex, 1, detected.image_ref, observations, (),
                                              kwargs["profile"], "supplied-seedfinder-xy-deposition",
                                              dict(detected.native_orientation_contract.code_sha256)[CODE_FILES[2]])

        return InertAdapter()


def service_for(owned, workers=None, **kwargs):
    scope, source, runtime, memory = owned
    workers = workers or Workers()
    service = ImplantService(scope, memory, runtime=runtime, adapter_factory=workers.adapter,
                             lease_factory=workers.lease, device_lock_factory=workers.lock, **kwargs)
    return service, workers


def reconstruct(service, source, **kwargs):
    return service.reconstruct(source, request_id=uuid4().hex, **kwargs)


def review_request(scope, source, receipt, *, statuses=("accepted", "rejected"), coverage="complete"):
    revision = receipt["record"]["reconstruction"]
    authorization = ImplantReviewAuthorization(scope.owner_id, source.image_ref, revision["revision_id"], "reader-a")
    decisions = tuple(ObservationReview(str(i), status, "independent phantom review") for i, status in enumerate(statuses))
    return ImplantReviewRequest(authorization, decisions, coverage, "synthetic full-FOV assessment" if coverage else None)


def test_tool_reconstruct_returns_review_required_and_exact_image_identity(owned):
    scope, source, _, memory = owned
    service, workers = service_for(owned)
    result = SeedSegmentationTool(service).execute(action="reconstruct", implant_input=source, request_id=uuid4().hex)
    assert result.success, result.error
    metadata = result.metadata
    assert metadata["review_required"] and not metadata["baseline_accepted"]
    assert metadata["image_sha256"] == source.image_ref.image_sha256
    assert metadata["captured_image_ref"] == json.loads(json.dumps(asdict(source.image_ref)))
    reconstruction = SeedAxisReconstruction.from_dict(metadata["implanted_seed_reconstruction"])
    with pytest.raises(FrozenInstanceError):
        reconstruction.observations[0].axis_lps = (0, 0, 1)
    assert len(reconstruction.observations) == 2  # Existing plan has 99 seeds.
    assert all(x.axis_lps == (1, 0, 0) for x in reconstruction.observations)
    assert workers.events == [("prepare", "cpu"), ("lease-enter", "cpu"), ("lock-enter", "cpu"),
                              ("run", "cpu"), ("lock-exit", "cpu"), ("lease-exit", "cpu")]
    assert IMPLANT_MEMORY_KEY == "implanted_seed_reconstruction"
    stored = memory.retrieve(IMPLANT_MEMORY_KEY)["by_timepoint"][scope.timepoint_id]["current"]
    assert stored["reconstruction"] == metadata["implanted_seed_reconstruction"]
    assert stored["counts"] == {"detected_count": 2, "accepted_count": 0, "review_needed_count": 2, "excluded_count": 0}
    assert memory.retrieve("seed_plan")["planned_count"] == 99
    assert memory.retrieve("ct_path") == "unrelated-mounted-image"
    assert memory.retrieve("dose_distribution_gy") == "preserved-baseline"


def test_original_grid_mask_and_native_artifacts_are_durable_and_hash_checked(owned):
    service, _ = service_for(owned)
    receipt = reconstruct(service, owned[1])
    record = receipt["record"]
    assert len(record["artifacts"]) == 5
    mask = next(x for x in record["artifacts"] if x["role"] == "original_grid_mask")
    path = Path(owned[0].workspace_root) / mask["path"]
    image = sitk.ReadImage(str(path))
    assert ImageGeometry.from_image(image) == owned[1].image_ref.geometry
    assert np.count_nonzero(sitk.GetArrayFromImage(image)) == 2
    assert sha256_file(path) == mask["sha256"]
    path.write_bytes(b"changed")
    with pytest.raises(ImplantServiceError, match="artifact changed"):
        service.get()


def test_review_is_a_new_revision_with_separate_counts_and_no_baseline_approval(owned):
    scope, source, _, _ = owned
    service, _ = service_for(owned)
    initial = reconstruct(service, source)
    old_revision = initial["record"]["reconstruction"]
    reviewed = service.review(review_request(scope, source, initial))
    new_revision = reviewed["record"]["reconstruction"]
    assert new_revision["revision"] == 2
    assert new_revision["parent_revision_id"] == old_revision["revision_id"]
    assert reviewed["record"]["counts"] == {"detected_count": 2, "accepted_count": 1, "review_needed_count": 0, "excluded_count": 1}
    assert new_revision["review_status"] == "accepted"
    assert not reviewed["clinical_use_ready"]
    assert reviewed["record"]["dependency_invalidation"]["applied"] is False
    assert old_revision["observations"][0]["review_status"] == "review_needed"
    historical = service.get(revision_id=old_revision["revision_id"])
    assert not historical["is_current"]
    assert service.memory.retrieve(IMPLANT_MEMORY_KEY)["by_timepoint"][scope.timepoint_id]["current"]["reconstruction"] == new_revision


def test_human_center_correction_keeps_history_and_clears_unmeasured_axis(owned):
    scope, source, _, _ = owned
    service, _ = service_for(owned)
    initial = reconstruct(service, source)
    authorization = review_request(scope, source, initial, statuses=()).authorization
    decision = ObservationReview("0", "review_needed", "center revised from image", corrected_center_lps_mm=(1, 2, 3))
    reviewed = service.review(ImplantReviewRequest(authorization, (decision,)))
    new = reviewed["record"]["reconstruction"]["observations"][0]
    assert new["center_lps_mm"] == [1.0, 2.0, 3.0]
    assert new["axis_lps"] is None
    assert initial["record"]["reconstruction"]["observations"][0]["center_lps_mm"] != (1, 2, 3)


def test_review_tool_rejects_forged_json_authorization(owned):
    service, workers = service_for(owned)
    initial = reconstruct(service, owned[1])
    result = SeedSegmentationTool(service).execute(action="review_reconstruction", review_request={
        "reviewer_id": "model", "status": "accepted", "expected_revision_id": initial["current_revision_id"]})
    assert not result.success
    assert result.metadata["code"] == "implant_review_authorization_required"
    assert service.get()["current_revision_id"] == initial["current_revision_id"]
    assert workers.calls == 1


@pytest.mark.parametrize("field", ["owner_id", "timepoint_id", "image_id"])
def test_foreign_review_scope_or_image_is_rejected(owned, field):
    scope, source, _, _ = owned
    service, _ = service_for(owned)
    receipt = reconstruct(service, source)
    request = review_request(scope, source, receipt)
    auth = request.authorization
    auth = replace(auth, owner_id="other-owner") if field == "owner_id" else replace(
        auth, image_ref=replace(auth.image_ref, **{field: uuid4().hex}))
    with pytest.raises(ImplantServiceError):
        service.review(replace(request, authorization=auth))
    assert service.get()["current_revision_id"] == receipt["current_revision_id"]


def test_complete_coverage_requires_explicit_review_evidence(owned):
    service, _ = service_for(owned)
    receipt = reconstruct(service, owned[1])
    auth = review_request(owned[0], owned[1], receipt).authorization
    with pytest.raises(ImplantServiceError, match="coverage"):
        ImplantReviewRequest(auth, (), coverage_status="complete")


def test_stale_review_cannot_overwrite_a_newer_revision(owned):
    service, _ = service_for(owned)
    receipt = reconstruct(service, owned[1])
    request = review_request(owned[0], owned[1], receipt)
    current = service.review(request)
    with pytest.raises(ImplantServiceError, match="observations changed"):
        service.review(request)
    assert service.get()["current_revision_id"] == current["current_revision_id"]


def test_cached_completed_request_is_idempotent_and_never_reruns_the_model(owned):
    service, workers = service_for(owned)
    request_id = uuid4().hex
    first = service.reconstruct(owned[1], request_id=request_id)
    second = service.reconstruct(owned[1], request_id=request_id)
    assert first == second
    assert workers.calls == 1
    assert len(service.memory.retrieve(IMPLANT_MEMORY_KEY)["by_timepoint"][owned[0].timepoint_id]["history"]) == 1


def test_cached_old_job_does_not_replace_a_subsequent_review(owned):
    service, workers = service_for(owned)
    request_id = uuid4().hex
    first = service.reconstruct(owned[1], request_id=request_id)
    latest = service.review(review_request(owned[0], owned[1], first))
    cached = service.reconstruct(owned[1], request_id=request_id)
    assert not cached["is_current"]
    assert cached["current_revision_id"] == latest["current_revision_id"]
    assert workers.calls == 1


def test_request_uuid_cannot_be_reused_with_changed_inputs(owned):
    service, _ = service_for(owned)
    request_id = uuid4().hex
    service.reconstruct(owned[1], request_id=request_id)
    different = replace(owned[1], preoperative_timepoint_id=uuid4().hex)
    with pytest.raises(ImplantServiceError, match="different image/configuration"):
        service.reconstruct(different, request_id=request_id)


def test_get_hydrates_a_new_memory_after_restart_without_inference_assets(owned, monkeypatch):
    service, workers = service_for(owned)
    first = reconstruct(service, owned[1])
    new_memory = Memory(owned[0].session_id)
    restored = ImplantService(owned[0], new_memory)
    monkeypatch.setenv("BRACHYBOT_SEEDFINDER_BUNDLE", "")
    monkeypatch.setenv("BRACHYBOT_SEEDFINDER_PYTHON", "")
    monkeypatch.setenv("BRACHYBOT_SEEDFINDER_DEVICE", "invalid-worker-config")
    result = restored.get()
    assert result["current_revision_id"] == first["current_revision_id"]
    assert new_memory.retrieve(IMPLANT_MEMORY_KEY)["by_timepoint"][owned[0].timepoint_id]["current"] == first["record"]
    assert workers.calls == 1
    restored.get()
    assert new_memory.writes == 1


def test_disk_commit_survives_a_crash_before_memory_publication(owned):
    service, workers = service_for(owned)
    owned[3].fail_next_store = True
    with pytest.raises(RuntimeError, match="synthetic crash"):
        reconstruct(service, owned[1])
    index = json.loads((service.root / "index.json").read_text())
    assert index["current"] is not None
    assert next(iter(index["jobs"].values()))["status"] == "completed"
    new_memory = Memory(owned[0].session_id)
    restored = ImplantService(owned[0], new_memory)
    assert restored.get()["current_revision_id"] == index["current"]["revision_id"]
    assert workers.calls == 1


def test_metadata_publication_failure_leaves_previous_revision_current(owned, monkeypatch):
    service, _ = service_for(owned)
    initial = reconstruct(service, owned[1])
    atomic = service._atomic_json

    def fail_new_revision(path, value):
        if path.parent.name == "revisions":
            raise OSError("synthetic storage failure")
        return atomic(path, value)

    monkeypatch.setattr(service, "_atomic_json", fail_new_revision)
    with pytest.raises(OSError, match="storage failure"):
        service.review(review_request(owned[0], owned[1], initial))
    assert service.get()["current_revision_id"] == initial["current_revision_id"]


def test_crash_after_revision_write_before_head_write_keeps_old_head(owned, monkeypatch):
    service, _ = service_for(owned)
    initial = reconstruct(service, owned[1])
    atomic = service._atomic_json

    def fail_head(path, value):
        if path.name == "index.json":
            raise OSError("synthetic crash before atomic head publication")
        return atomic(path, value)

    monkeypatch.setattr(service, "_atomic_json", fail_head)
    with pytest.raises(OSError, match="head publication"):
        service.review(review_request(owned[0], owned[1], initial))
    assert service.get()["current_revision_id"] == initial["current_revision_id"]
    assert len(list((service.root / "revisions").glob("*.json"))) == 2


def test_actual_agent_memory_persistence_protocol_receives_the_scoped_catalog(owned):
    from agent_runtime.core import AgentMemory
    from web.workspace_store import _safe_json

    memory = AgentMemory(session_id=owned[0].session_id)
    reasons = []
    memory.set_persistence_callback(reasons.append)
    service, _ = service_for((owned[0], owned[1], owned[2], memory))
    receipt = reconstruct(service, owned[1])
    stored = memory.retrieve(IMPLANT_MEMORY_KEY)
    assert stored["by_timepoint"][owned[0].timepoint_id]["current"] == receipt["record"]
    assert _safe_json(stored) == stored
    assert reasons == ["memory.store:implanted_seed_reconstruction"]
    assert memory._planning_versions[IMPLANT_MEMORY_KEY] == 1


def test_real_adapter_pin_validation_fails_before_acquiring_a_device(owned):
    workers = Workers()
    # Real prepare reads inert fixture bytes, rejects the supplied pins and
    # never imports or executes those files or reads a model state_dict.
    service = ImplantService(owned[0], owned[3], runtime=owned[2], adapter_factory=SeedFinderAdapter,
                             lease_factory=workers.lease, device_lock_factory=workers.lock)
    with pytest.raises(ImplantServiceError, match="pinned source/model") as error:
        reconstruct(service, owned[1])
    assert error.value.code == "seedfinder_validation_failed"
    assert not workers.events
    assert json.loads((service.root / "index.json").read_text())["current"] is None


def test_failed_job_never_publishes_and_requires_a_new_request(owned):
    service, workers = service_for(owned)
    workers.fail = True
    request_id = uuid4().hex
    with pytest.raises(RuntimeError, match="detector failure"):
        service.reconstruct(owned[1], request_id=request_id)
    index = json.loads((service.root / "index.json").read_text())
    assert index["current"] is None and index["jobs"][request_id]["status"] == "failed"
    workers.fail = False
    with pytest.raises(ImplantServiceError, match="new explicit request"):
        service.reconstruct(owned[1], request_id=request_id)
    assert workers.calls == 1
    assert not workers.lease_active and not workers.lock_active


def test_abandoned_running_job_is_marked_interrupted_without_auto_rerun(owned):
    service, workers = service_for(owned)
    request_id = uuid4().hex
    service.reconstruct(owned[1], request_id=request_id)
    index = json.loads((service.root / "index.json").read_text())
    index["jobs"][request_id]["status"] = "running"
    service._atomic_json(service.root / "index.json", index)
    with pytest.raises(ImplantServiceError, match="new explicit request"):
        service.reconstruct(owned[1], request_id=request_id)
    assert json.loads((service.root / "index.json").read_text())["jobs"][request_id]["status"] == "interrupted"
    assert workers.calls == 1


def test_uninstalled_linux_bundle_returns_actionable_error_before_any_work(owned):
    scope, source, runtime, memory = owned
    missing = replace(runtime, bundle_dir=str(Path(runtime.bundle_dir) / "not-installed"))
    service = ImplantService(scope, memory, runtime=missing)
    result = SeedSegmentationTool(service).execute(action="reconstruct", implant_input=source, request_id=uuid4().hex)
    assert not result.success and result.metadata["code"] == "seedfinder_not_configured"
    assert "BRACHYBOT_SEEDFINDER_BUNDLE" in result.error and "BRACHYBOT_SEEDFINDER_PYTHON" in result.error
    assert not service.root.exists()
    assert not memory.retrieve(IMPLANT_MEMORY_KEY)


def test_cpu_fallback_cannot_violate_a_cuda_device_lease(owned, monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    scope, source, runtime, memory = owned
    workers = Workers()
    workers.leased_device = "cpu"
    service = ImplantService(scope, memory, runtime=replace(runtime, device="cuda:1"),
                             adapter_factory=workers.adapter, lease_factory=workers.lease, device_lock_factory=workers.lock)
    with pytest.raises(ImplantServiceError, match="could not be leased"):
        reconstruct(service, source)
    assert workers.calls == 0
    assert not workers.lock_active and not workers.lease_active


def test_cuda_child_selection_does_not_change_global_environment(owned, monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    captured = []

    class Runner:
        def execute(self, prepared, *, cancelled=None):
            captured.append(prepared.command)
            return 0

    prepared = SimpleNamespace(command=(sys.executable, "-B", "/owned/pinned/test_single_ct.py", "--device", "cuda"))
    # Use the actual immutable prepared record for dataclasses.replace.
    request = SimpleNamespace()
    prepared = PreparedSeedFinderRun(request, prepared.command, None, "scan", "scan_CT.nii.gz")
    LeasedSeedFinderRunner(Runner(), "cuda:1").execute(prepared)
    assert captured[0][:3] == (sys.executable, "-B", "-c")
    assert captured[0][4:] == ("1", "/owned/pinned/test_single_ct.py", "--device", "cuda")
    assert "CUDA_VISIBLE_DEVICES" not in os.environ


def test_ambiguous_parent_cuda_namespace_fails_closed(owned, monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1,0")
    service = ImplantService(owned[0], owned[3], runtime=replace(owned[2], device="cuda:1"))
    with pytest.raises(ImplantServiceError, match="unmasked CUDA"):
        reconstruct(service, owned[1])
    assert not service.root.exists()


def test_two_timepoints_share_memory_without_overwriting_each_other(owned):
    service_a, _ = service_for(owned)
    result_a = reconstruct(service_a, owned[1])
    scope_b = replace(owned[0], timepoint_id=uuid4().hex)
    input_b = replace(owned[1], image_ref=replace(owned[1].image_ref, timepoint_id=scope_b.timepoint_id))
    service_b, _ = service_for((scope_b, input_b, owned[2], owned[3]))
    result_b = reconstruct(service_b, input_b)
    entries = owned[3].retrieve(IMPLANT_MEMORY_KEY)["by_timepoint"]
    assert entries[owned[0].timepoint_id]["current"] == result_a["record"]
    assert entries[scope_b.timepoint_id]["current"] == result_b["record"]
    assert service_a.root != service_b.root


def test_concurrent_reconstructions_use_cas_and_publish_only_one_head(owned):
    # Each call uses an independent inert worker/lease, as distinct processes
    # would; publication races at the shared durable journal boundary.
    barrier = threading.Barrier(2)
    first, second = Workers(), Workers()
    first.barrier = second.barrier = barrier
    service_a, _ = service_for(owned, first)
    service_b, _ = service_for(owned, second)

    def run(service):
        try:
            return reconstruct(service, owned[1])
        except ImplantServiceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, (service_a, service_b)))
    assert sum(isinstance(x, dict) for x in results) == 1
    assert "implant_revision_conflict" in results
    index = json.loads((service_a.root / "index.json").read_text())
    assert len(index["history"]) == 1
    assert sorted(x["status"] for x in index["jobs"].values()) == ["completed", "failed"]


def test_image_fence_is_rechecked_before_publication(owned):
    current = True
    workers = Workers()

    def change_image():
        nonlocal current
        current = False

    workers.after_run = change_image
    service, _ = service_for(owned, workers, image_fence=lambda reference: current)
    with pytest.raises(ImplantServiceError, match="no longer current"):
        reconstruct(service, owned[1])
    assert json.loads((service.root / "index.json").read_text())["current"] is None


def test_detection_provider_cannot_autoaccept(owned):
    service, workers = service_for(owned)
    workers.autoaccept = True
    with pytest.raises(ImplantServiceError, match="cannot approve"):
        reconstruct(service, owned[1])
    assert json.loads((service.root / "index.json").read_text())["current"] is None


def test_zero_detections_are_review_needed_and_not_an_empty_accepted_baseline(owned):
    service, workers = service_for(owned)
    workers.empty = True
    record = reconstruct(service, owned[1])["record"]
    assert record["counts"]["detected_count"] == 0
    assert record["reconstruction"]["coverage_status"] == "unknown"
    assert record["reconstruction"]["review_status"] == "review_needed"
    assert not record["clinical_use_ready"]


def test_cancelled_tool_releases_both_guards_and_does_not_publish(owned):
    service, workers = service_for(owned)
    cancelled = False

    def cancel():
        nonlocal cancelled
        cancelled = True

    workers.after_run = cancel
    with cancellation_scope(lambda: cancelled), pytest.raises(OperationCancelled):
        SeedSegmentationTool(service).execute(action="reconstruct", implant_input=owned[1], request_id=uuid4().hex)
    assert not workers.lease_active and not workers.lock_active
    assert json.loads((service.root / "index.json").read_text())["current"] is None


def test_expired_deadline_never_reserves_a_job_or_device(owned):
    service, workers = service_for(owned)
    with pytest.raises(ReconstructionDeadlineExceeded):
        reconstruct(service, owned[1], deadline=time.monotonic() - 1)
    assert not service.root.exists() and workers.calls == 0


def test_file_lock_wait_is_cancellable_and_bounded_by_deadline(owned):
    path = Path(owned[0].workspace_root) / "synthetic-lock"
    with _file_lock(path):
        with pytest.raises(ReconstructionDeadlineExceeded):
            with _file_lock(path, deadline=time.monotonic() + 0.05):
                pytest.fail("Contended lock must not be acquired")


def test_storage_and_job_limits_fail_before_publication(owned):
    scope, source, runtime, memory = owned
    service, _ = service_for((scope, source, replace(runtime, max_storage_bytes=16), memory))
    with pytest.raises(ImplantServiceError, match="storage limit"):
        reconstruct(service, source)
    assert not memory.retrieve(IMPLANT_MEMORY_KEY)
    separate_scope = replace(scope, timepoint_id=uuid4().hex)
    separate_source = replace(source, image_ref=replace(source.image_ref, timepoint_id=separate_scope.timepoint_id))
    other, workers = service_for((separate_scope, separate_source, replace(runtime, max_jobs=1), memory))
    result = reconstruct(other, separate_source)
    locks = set((other.root / "jobs").glob("*.lock"))
    with pytest.raises(ImplantServiceError, match="journal is full"):
        reconstruct(other, separate_source, expected_revision_id=result["current_revision_id"])
    assert workers.calls == 1 and set((other.root / "jobs").glob("*.lock")) == locks


def test_foreign_ct_source_and_legacy_arguments_do_not_silently_fall_back(owned, tmp_path):
    service, workers = service_for(owned)
    source = replace(owned[1], ct_path=str(tmp_path / "outside.nii.gz"))
    with pytest.raises(ImplantServiceError, match="owned case root"):
        reconstruct(service, source)
    result = SeedSegmentationTool(service).execute(method="seedfinder", implant_input=owned[1],
                                                  request_id=uuid4().hex, planned_seeds=[[1, 2, 3]])
    assert not result.success and result.metadata["code"] == "invalid_implant_arguments"
    assert workers.calls == 0


def test_legacy_single_timepoint_threshold_behavior_is_preserved():
    array = np.zeros((8, 8, 8), dtype=np.int16)
    array[3, 4, 2:5] = 3000
    image = sitk.GetImageFromArray(array)
    image.SetSpacing((2, 3, 5))
    image.SetOrigin((10, 20, 30))
    result = SeedSegmentationTool().execute(image=image, gaussian_sigma=0, planned_seeds=[([16, 32, 45], [0, 0, 1])])
    assert result.success
    assert result.metadata["num_detected"] == 1
    assert result.data[0]["physical_position"] == [16, 32, 45]
    assert result.metadata["deviation_stats"]["num_matched"] == 1
    assert "implanted_seed_reconstruction" not in result.metadata


def test_tool_schema_hides_owned_objects_and_human_authorization_from_model():
    from agent_runtime.core import ToolRegistry
    schema = SeedSegmentationTool().input_schema["properties"]
    public = ToolRegistry._llm_properties(schema)
    assert "implant_service" not in public and "implant_input" not in public and "review_request" not in public
    assert "action" in public and "request_id" in public
