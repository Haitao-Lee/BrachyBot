"""Thin owned-path adapter for the supplied SeedFinder inference bundle.

No model imports, deserialization or inference occur at module import, prepare,
or artifact loading. ``run`` is an explicit execution boundary. The caller must
capture account/Session/timepoint ownership, pin trusted bundle/model hashes,
and hold the application's device lease AND cross-process GPU lock for a CUDA
run. NIfTI CT is required here; DICOM conversion belongs to the owned image
ingestion boundary. The supplied 1 x 1 x 5 mm trained preprocessing is untouched.

Failed/cancelled outputs remain staged in the new owned output directory. They
must never be published as accepted observations by the integration layer.
"""

from __future__ import annotations

import ast
from contextlib import nullcontext
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import csv
from typing import ContextManager, Optional, Protocol

import numpy as np
import SimpleITK as sitk

from utils.implant_reconstruction import (
    CancelCheck, ImageGeometry, ImageReference, OrientationProfile,
    PhysicalPCAOrientationProvider, SeedAxisReconstruction, SeedDetection,
    SeedDimensions, SeedOrientationProvider, check_execution,
    reconstruct_original_grid_mask,
)

CODE_FILES = ("test_single_ct.py", "autoencoder_inference.py", "seed_pipeline_deepdec_roi.py")
# Pins for the user-supplied bundle inspected on 2026-10-10. Constructing a
# contract from these constants does not approve newly observed file contents.
SUPPLIED_CODE_SHA256 = (
    ("test_single_ct.py", "bdb0db1202f3cbca8e20c254f74aa8abb989adf687c78796fb59e16db173bfd0"),
    ("autoencoder_inference.py", "7a0d2a21391a14ff9115a10dd23d49d2068f3271b49da646da5f8f5cb07a287e"),
    ("seed_pipeline_deepdec_roi.py", "1e04cd50170e000a2240011d5679097c624ce5af58ecb2019ff801716eb91dbf"),
)
SUPPLIED_MODEL_SHA256 = "561e905d06b5423273554a539ebc65e2fabaf484f1761d6311e17f38e7b6707b"
PREPROCESSING_CONTRACT = (
    "supplied-test_single_ct-v1:MONAI-Spacingd-bilinear-xyz(1,1,5);"
    "clip-HU[-1000,2000]-to[0,1];C-H-W-D-to-C-D-H-W;"
    "Corruptiond-HU600-dilate3-fill(3,9,9)-lowHU(-300,150);"
    "sliding-window(32,128,128)-overlap0.25-gaussian;"
    "supplied-DeepDec-ROI-defaults;binary-native-mask;CSV-LPS-mm;"
    "Markups-Fiducial-orientation-is-not-seed-axis"
)


def _valid_hash(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def sha256_file(path: Path, *, cancelled: CancelCheck = None, deadline: Optional[float] = None,
                max_bytes: int = 4_000_000_000) -> str:
    if path.stat().st_size > max_bytes:
        raise ValueError("Artifact exceeds the configured byte limit")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            check_execution(cancelled, deadline)
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _absolute(value: str, *, strict: bool = True) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Owned and configured paths must be absolute")
    return path.resolve(strict=strict)


def _inside(path: Path, root: Path) -> None:
    if path == root or not path.is_relative_to(root):
        raise ValueError("Path must be strictly inside its captured owned root")


@dataclass(frozen=True)
class SeedFinderModelContract:
    bundle_dir: str
    model_path: str
    model_sha256: str
    code_sha256: tuple[tuple[str, str], ...]
    contract_id: str = "supplied-seedfinder-smr-ae-v1"
    artifact_schema: str = "legacy_ct_v1"

    def __post_init__(self):
        hashes = tuple(tuple(x) for x in self.code_sha256)
        object.__setattr__(self, "code_sha256", hashes)
        if not self.contract_id or not _valid_hash(self.model_sha256):
            raise ValueError("A trusted model contract and pinned model hash are required")
        if (len(hashes) != len(CODE_FILES) or {x[0] for x in hashes} != set(CODE_FILES) or
                any(not _valid_hash(x[1]) for x in hashes)):
            raise ValueError("Pin exactly all three supplied inference source files")
        if self.artifact_schema not in {"legacy_ct_v1", "native_model_v2"}:
            raise ValueError("Unsupported supplied artifact schema")

    @classmethod
    def for_supplied_bundle(cls, bundle_dir: str) -> "SeedFinderModelContract":
        """Use reviewed byte pins; ``prepare`` verifies every file before execution."""
        bundle = Path(bundle_dir)
        if not bundle.is_absolute():
            raise ValueError("Configured bundle path must be absolute")
        return cls(str(bundle), str(bundle / "models" / "best_autoencoder.pth"),
                   SUPPLIED_MODEL_SHA256, SUPPLIED_CODE_SHA256,
                   contract_id="supplied-seedfinder-smr-ae-v2", artifact_schema="native_model_v2")


@dataclass(frozen=True)
class SeedFinderRequest:
    image_ref: ImageReference
    ct_path: str
    owned_input_root: str
    owned_runtime_root: str
    output_dir: str
    python_executable: str
    model_contract: SeedFinderModelContract
    device: str = "cpu"
    sw_batch_size: int = 1
    deadline_monotonic: Optional[float] = None
    max_image_voxels: int = 256_000_000
    max_artifact_bytes: int = 4_000_000_000
    max_text_bytes: int = 8_000_000
    max_model_bytes: int = 256_000_000
    max_detections: int = 1024
    association_radius_mm: float = 2.0
    association_ambiguity_mm: float = 0.2
    export_consistency_tolerance_mm: float = 0.05

    def __post_init__(self):
        if self.device not in ("cpu", "cuda", "mps"):
            raise ValueError("Use an explicit device; auto device selection is not allowed")
        for name in ("sw_batch_size", "max_image_voxels", "max_artifact_bytes", "max_text_bytes", "max_model_bytes", "max_detections"):
            value = getattr(self, name)
            if int(value) != value or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("association_radius_mm", "association_ambiguity_mm", "export_consistency_tolerance_mm"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite")


@dataclass(frozen=True)
class SeedFinderProvenance:
    contract_id: str
    model_sha256: str
    code_sha256: tuple[tuple[str, str], ...]
    preprocessing_contract: str
    preprocessing_sha256: str
    image_sha256: str
    grid_signature: str
    device: str
    sw_batch_size: int
    weights_loading: str = "torch.load(weights_only=True);strict-state-dict"
    adapter_version: str = "1.0.0"


@dataclass(frozen=True)
class PreparedSeedFinderRun:
    request: SeedFinderRequest
    command: tuple[str, ...]
    provenance: SeedFinderProvenance
    case_name: str
    ct_output_name: str


@dataclass(frozen=True)
class SeedFinderArtifact:
    role: str
    path: str
    sha256: str


@dataclass(frozen=True)
class SeedFinderDetectionResult:
    """Typed detections/provenance plus ephemeral images (not persisted revision records)."""
    image_ref: ImageReference
    detections: tuple[SeedDetection, ...]
    artifacts: tuple[SeedFinderArtifact, ...]
    provenance: SeedFinderProvenance
    original_grid_mask: sitk.Image
    native_component_labels: sitk.Image
    original_ct: sitk.Image
    coverage_status: str = "unknown"
    review_status: str = "review_needed"
    diagnostics: tuple[str, ...] = (
        "native_export_is_binary_component_ids_reconstructed",
        "markups_orientation_ignored",
        "scan_coverage_not_established_by_inference_success",
    )
    native_orientation_contract: Optional[SeedFinderModelContract] = None


class SeedFinderProcessRunner(Protocol):
    def execute(self, prepared: PreparedSeedFinderRun, *, cancelled: CancelCheck = None) -> int: ...


class SubprocessSeedFinderRunner:
    """Shell-free invocation with cancellable process lifetime and owned temp paths."""

    @staticmethod
    def _stop(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=2)
        except ProcessLookupError:
            process.wait(timeout=2)

    def execute(self, prepared: PreparedSeedFinderRun, *, cancelled: CancelCheck = None) -> int:
        request = prepared.request
        check_execution(cancelled, request.deadline_monotonic)
        with tempfile.TemporaryDirectory(prefix="seedfinder-job-", dir=request.owned_runtime_root) as temporary:
            environment = os.environ.copy()
            for name in ("PYTHONPATH", "PYTHONHOME"):
                environment.pop(name, None)
            environment.update(TMPDIR=temporary, TMP=temporary, TEMP=temporary,
                               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
            options = {"start_new_session": True} if os.name == "posix" else {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
            # The supplied pipeline logs CT paths. Suppress console output rather
            # than retaining patient-related text or filling an unbounded pipe.
            process = subprocess.Popen(prepared.command, cwd=request.owned_runtime_root,
                                       env=environment, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
            try:
                while process.poll() is None:
                    check_execution(cancelled, request.deadline_monotonic)
                    time.sleep(0.05)
                check_execution(cancelled, request.deadline_monotonic)
                return process.returncode
            finally:
                self._stop(process)


def _check_safe_loader(source: str) -> None:
    """Static check of the pinned supplied entry point; never execute its imports."""
    tree = ast.parse(source)
    loads = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and
             isinstance(node.func, ast.Attribute) and node.func.attr == "load" and
             isinstance(node.func.value, ast.Name) and node.func.value.id == "torch"]
    if not loads or any(not any(keyword.arg == "weights_only" and
                               isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                               for keyword in node.keywords) for node in loads):
        raise ValueError("Supplied model loader must explicitly use weights_only=True")
    state_loads = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and
                   isinstance(node.func, ast.Attribute) and node.func.attr == "load_state_dict"]
    if not state_loads or any(not any(keyword.arg == "strict" and isinstance(keyword.value, ast.Constant)
                                     and keyword.value.value is True for keyword in node.keywords)
                              for node in state_loads):
        raise ValueError("Supplied model loader must explicitly load a strict state_dict")


def _case_name(ct: Path) -> str:
    name = ct.name[:-7] if ct.name.lower().endswith(".nii.gz") else ct.name[:-4]
    for suffix in ("_resampled", "_reconstruction", "_difference"):
        if name.lower().endswith(suffix):
            name = name[:-len(suffix)]
            break
    if not name or name in (".", ".."):
        raise ValueError("CT filename must have a nonempty case stem")
    return name


class SeedFinderAdapter:
    """Server-owned configuration only: owned roots are not client authorization."""

    def __init__(self, runner: Optional[SeedFinderProcessRunner] = None):
        self.runner = runner or SubprocessSeedFinderRunner()

    def prepare(self, request: SeedFinderRequest, *, cancelled: CancelCheck = None) -> PreparedSeedFinderRun:
        """Read-only validation. A missing/changed pin fails before any execution."""
        deadline = request.deadline_monotonic
        check_execution(cancelled, deadline)
        input_root = _absolute(request.owned_input_root)
        runtime_root = _absolute(request.owned_runtime_root)
        if not input_root.is_dir() or not runtime_root.is_dir():
            raise ValueError("Captured owned roots must be directories")
        ct = _absolute(request.ct_path)
        _inside(ct, input_root)
        if not ct.is_file() or not ct.name.lower().endswith((".nii", ".nii.gz")):
            raise ValueError("Adapter requires an owned NIfTI CT file")
        output = _absolute(request.output_dir, strict=False)
        _inside(output, runtime_root)
        if output.exists() or not output.parent.is_dir():
            raise ValueError("Use a new output directory with an existing owned parent")
        if ct.is_relative_to(output):
            raise ValueError("Output must not contain the input CT")
        python = _absolute(request.python_executable)
        bundle = _absolute(request.model_contract.bundle_dir)
        model = _absolute(request.model_contract.model_path)
        if not python.is_file() or not bundle.is_dir() or not model.is_file():
            raise ValueError("Configured interpreter, bundle and model must exist")
        if runtime_root.is_relative_to(bundle) or output.is_relative_to(bundle):
            raise ValueError("Runtime/output paths must not modify the supplied bundle")
        pinned = dict(request.model_contract.code_sha256)
        source_hashes = []
        for filename in CODE_FILES:
            path = _absolute(str(bundle / filename))
            _inside(path, bundle)
            if not path.is_file():
                raise ValueError("Missing supplied source file")
            digest = sha256_file(path, cancelled=cancelled, deadline=deadline, max_bytes=2_000_000)
            if digest != pinned[filename]:
                raise ValueError("Supplied source hash does not match the trusted contract")
            source_hashes.append((filename, digest))
        _check_safe_loader((bundle / CODE_FILES[0]).read_text(encoding="utf-8-sig"))
        model_hash = sha256_file(model, cancelled=cancelled, deadline=deadline,
                                 max_bytes=request.max_artifact_bytes)
        if model_hash != request.model_contract.model_sha256:
            raise ValueError("Model hash does not match the trusted contract")
        ct_hash = sha256_file(ct, cancelled=cancelled, deadline=deadline, max_bytes=request.max_artifact_bytes)
        if ct_hash != request.image_ref.image_sha256:
            raise ValueError("CT hash does not match the captured image revision")
        reader = sitk.ImageFileReader()
        reader.SetFileName(str(ct))
        reader.ReadImageInformation()
        if reader.GetDimension() != 3 or math.prod(reader.GetSize()) > request.max_image_voxels:
            raise ValueError("CT image dimensionality/size exceeds the supported contract")
        image = reader.Execute()
        if not request.image_ref.geometry.agrees_with(image):
            raise ValueError("CT geometry does not match the captured image revision")
        check_execution(cancelled, deadline)
        normalized = replace(request, ct_path=str(ct), owned_input_root=str(input_root),
                             owned_runtime_root=str(runtime_root), output_dir=str(output),
                             python_executable=str(python), model_contract=replace(
                                 request.model_contract, bundle_dir=str(bundle), model_path=str(model)))
        name = _case_name(ct)
        native_runner = Path(__file__).with_name('native_runner.py').resolve(strict=True)
        if request.model_contract.artifact_schema == 'native_model_v2':
            source_hashes.append(('brachybot_native_runner.py', sha256_file(native_runner, max_bytes=100_000)))
        suffix = ".nii.gz" if ct.name.lower().endswith(".nii.gz") else ".nii"
        preprocessing_hash = hashlib.sha256(json.dumps(
            {"source_files": source_hashes, "contract": PREPROCESSING_CONTRACT},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        provenance = SeedFinderProvenance(request.model_contract.contract_id, model_hash,
                                          tuple(source_hashes), PREPROCESSING_CONTRACT,
                                          preprocessing_hash, ct_hash, request.image_ref.geometry.signature,
                                          request.device, request.sw_batch_size)
        entry_command = (str(native_runner), '--native-entry', str(bundle / CODE_FILES[0])) if request.model_contract.artifact_schema == 'native_model_v2' else (str(bundle / CODE_FILES[0]),)
        return PreparedSeedFinderRun(normalized, (
            str(python), "-B", *entry_command, "--ct", str(ct), "--output", str(output),
            "--weights", str(model), "--device", request.device, "--sw-batch-size", str(request.sw_batch_size)),
            provenance, name, name + "_CT" + suffix)

    def run(self, request: SeedFinderRequest, *, cancelled: CancelCheck = None,
            execution_guard: Optional[ContextManager] = None) -> SeedFinderDetectionResult:
        """Execute only when explicitly called; no service/GPU orchestration is hidden here."""
        if request.device != "cpu" and execution_guard is None:
            raise ValueError("Accelerator inference requires a held device lease and cross-process lock")
        with execution_guard if execution_guard is not None else nullcontext():
            prepared = self.prepare(request, cancelled=cancelled)
            check_execution(cancelled, request.deadline_monotonic)
            # Exclusive directory creation prevents accidental overwrite and parallel reuse.
            Path(prepared.request.output_dir).mkdir(exist_ok=False)
            code = self.runner.execute(prepared, cancelled=cancelled)
            check_execution(cancelled, request.deadline_monotonic)
            if code != 0:
                raise RuntimeError(f"SeedFinder exited with status {code}; staged output is unpublishable")
            return self.load_outputs(prepared, cancelled=cancelled)

    def load_outputs(self, prepared: PreparedSeedFinderRun, *, cancelled: CancelCheck = None) -> SeedFinderDetectionResult:
        """Validate staged artifacts without invoking any supplied code or model."""
        request, deadline = prepared.request, prepared.request.deadline_monotonic
        check_execution(cancelled, deadline)
        root = _absolute(request.output_dir)
        _inside(root, _absolute(request.owned_runtime_root))
        names = {
            "ct": prepared.ct_output_name,
            "native_mask": prepared.case_name + "_particle_labels.nii.gz",
            "positions_csv": prepared.case_name + "_particle_positions.csv",
            "markups_json": prepared.case_name + "_particle_positions.json",
        }
        if request.model_contract.artifact_schema == "native_model_v2":
            names.pop("ct")
            names["particle_model"] = prepared.case_name + "_particle_model.stl"
            from tool_factory.seed_seg.native_runner import EMPTY_SUFFIX
            if (root / (prepared.case_name + EMPTY_SUFFIX)).exists():
                names.pop('particle_model')
                names['native_empty_receipt'] = prepared.case_name + EMPTY_SUFFIX
        if {x.name for x in root.iterdir()} != set(names.values()):
            raise ValueError("SeedFinder output must contain exactly the four declared artifacts")
        paths, artifacts = {}, []
        for role, name in names.items():
            raw = root / name
            if raw.is_symlink() or not raw.is_file():
                raise ValueError("Output artifacts must be regular files, not symlinks")
            path = raw.resolve(strict=True)
            _inside(path, root)
            digest = sha256_file(path, cancelled=cancelled, deadline=deadline,
                                 max_bytes=request.max_text_bytes if role in ("positions_csv", "markups_json", "native_empty_receipt")
                                 else request.max_model_bytes if role == "particle_model"
                                 else request.max_artifact_bytes)
            paths[role] = path
            artifacts.append(SeedFinderArtifact(role, str(path), digest))
        if request.model_contract.artifact_schema == "legacy_ct_v1":
            if artifacts[0].sha256 != request.image_ref.image_sha256:
                raise ValueError("SeedFinder source CT copy differs from the captured input")
        else:
            # The updated bundle returns mask/CSV/JSON/STL, not a CT copy.
            # Re-read only the captured owned input, never guess an output CT.
            paths["ct"] = _absolute(request.ct_path)
            _inside(paths["ct"], _absolute(request.owned_input_root))
            if sha256_file(paths["ct"], cancelled=cancelled, deadline=deadline,
                           max_bytes=request.max_artifact_bytes) != request.image_ref.image_sha256:
                raise ValueError("The captured CT changed while SeedFinder was running")
            if 'native_empty_receipt' in paths:
                from tool_factory.seed_seg.native_runner import empty_export_receipt
                expected = empty_export_receipt(root, prepared.case_name, max_voxels=request.max_image_voxels)
                if json.loads(paths['native_empty_receipt'].read_text(encoding='utf-8')) != expected:
                    raise ValueError('Native empty receipt disagrees with actual mask/CSV/Markups artifacts')
            else:
                from web.surgical_guide import parse_stl
                vertices, faces = parse_stl(paths["particle_model"].read_bytes())
                if not np.isfinite(vertices).all():
                    raise ValueError("The particle model contains nonfinite geometry")
        images = {}
        for role in ("ct", "native_mask"):
            reader = sitk.ImageFileReader()
            reader.SetFileName(str(paths[role]))
            reader.ReadImageInformation()
            if reader.GetDimension() != 3 or math.prod(reader.GetSize()) > request.max_image_voxels:
                raise ValueError("Output image exceeds the supported grid limit")
            images[role] = reader.Execute()
            ImageGeometry.from_image(images[role])
        ct, mask = images["ct"], images["native_mask"]
        if not request.image_ref.geometry.agrees_with(ct):
            raise ValueError("SeedFinder original CT geometry changed")
        binary = sitk.GetArrayViewFromImage(mask)
        if not np.all((binary == 0) | (binary == 1)):
            raise ValueError("Supplied final mask must be binary; do not infer detector labels from it")
        components = sitk.ConnectedComponent(sitk.Cast(mask, sitk.sitkUInt8), True)
        geometry = ImageGeometry.from_image(mask)
        with paths["positions_csv"].open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["id", "cz_vox", "cy_vox", "cx_vox", "x_mm", "y_mm", "z_mm"]:
                raise ValueError("Unexpected supplied CSV schema")
            detections = []
            seen = set()
            rounded_native_centers = 0
            for row in reader:
                check_execution(cancelled, deadline)
                if len(detections) >= request.max_detections:
                    raise ValueError("Detection export exceeds the configured limit")
                identity = row["id"]
                if not identity or identity in seen or None in row:
                    raise ValueError("Detection CSV identities must be unique and rows complete")
                seen.add(identity)
                point = np.asarray([float(row[k]) for k in ("x_mm", "y_mm", "z_mm")])
                voxel = np.asarray([float(row[k]) for k in ("cx_vox", "cy_vox", "cz_vox")])
                if not np.isfinite(point).all() or not np.isfinite(voxel).all():
                    raise ValueError("Detection coordinates must be finite")
                if np.linalg.norm(geometry.points_from_xyz(voxel) - point) > request.export_consistency_tolerance_mm:
                    # The pinned updated native exporter retains its fractional
                    # component centroid in cz/cy/cx, but some supplied branches
                    # use TransformIndexToPhysicalPoint(int(round(...))) for
                    # x/y/z. Preserve that reported physical center. Check the
                    # exact documented rounding convention, not a larger error
                    # tolerance, guessed spacing, or an ad-hoc axis flip.
                    rounded = np.asarray([int(round(value)) for value in voxel])
                    if request.model_contract.artifact_schema != "native_model_v2" or np.linalg.norm(
                            geometry.points_from_xyz(rounded) - point) > request.export_consistency_tolerance_mm:
                        raise ValueError("CSV voxel and physical coordinates disagree with the native grid")
                    rounded_native_centers += 1
                if np.any(voxel < -0.5) or np.any(voxel > np.asarray(geometry.size_xyz) - 0.5):
                    raise ValueError("Detection lies outside the native result grid")
                original_xyz = request.image_ref.geometry.xyz_from_points(point)
                if np.any(original_xyz < -0.5) or np.any(original_xyz > np.asarray(ct.GetSize()) - 0.5):
                    raise ValueError("Detection lies outside the original CT")
                ids, status = _associate_component(point, components, geometry, request)
                detections.append(SeedDetection(identity, tuple(point), ids,
                                                 center_uncertainty_mm=float(np.linalg.norm(mask.GetSpacing()) / math.sqrt(12)),
                                                 association_status=status))
        markups = json.loads(paths["markups_json"].read_text(encoding="utf-8-sig"))
        entries = markups.get("markups", [])
        if (len(entries) != 1 or entries[0].get("type") != "Fiducial" or
                entries[0].get("coordinateSystem") != "LPS" or entries[0].get("coordinateUnits") != "mm"):
            raise ValueError("Supplied Markups export must explicitly declare LPS millimeters")
        points = entries[0].get("controlPoints", [])
        if len(points) != len(detections):
            raise ValueError("CSV and Markups detection counts disagree")
        for item, detection in zip(points, detections):
            point = np.asarray(item.get("position", []), dtype=float)
            if (point.shape != (3,) or not np.isfinite(point).all() or
                    item.get("positionStatus") != "defined" or np.linalg.norm(
                        point - detection.center_lps_mm) > request.export_consistency_tolerance_mm):
                raise ValueError("CSV and Markups physical centers disagree")
        if not detections and np.any(binary):
            raise ValueError("Nonempty segmentation with zero exported centers requires provider review")
        original_mask = reconstruct_original_grid_mask(mask, ct, max_voxels=request.max_image_voxels)
        check_execution(cancelled, deadline)
        diagnostics = SeedFinderDetectionResult.__dataclass_fields__["diagnostics"].default
        if rounded_native_centers:
            diagnostics += ("supplied_fractional_csv_centroid_physical_point_uses_exact_rounded_native_index",)
        if not detections:
            diagnostics += ("zero_detections_does_not_prove_zero_implant",)
        if any(d.association_status != "associated" for d in detections):
            diagnostics += ("component_point_association_requires_review",)
        if np.any(binary) and not np.any(sitk.GetArrayViewFromImage(original_mask)):
            diagnostics += ("native_foreground_lost_on_original_grid",)
        native_contract = None
        if request.model_contract.artifact_schema == "native_model_v2":
            native_contract = request.model_contract
            diagnostics += ("supplied_axis_used_for_STL_not_exported_in_CSV_or_Markups",
                            "supplied_axis_provider_requires_XY_plane_assumption_review")
        return SeedFinderDetectionResult(request.image_ref, tuple(detections), tuple(artifacts),
                                         prepared.provenance, original_mask, components, ct,
                                         diagnostics=diagnostics, native_orientation_contract=native_contract)

    def reconstruct(self, detected: SeedFinderDetectionResult, *,
                    provider: Optional[SeedOrientationProvider] = None,
                    profile: OrientationProfile = OrientationProfile(),
                    dimensions: Optional[SeedDimensions] = None,
                    cancelled: CancelCheck = None, deadline: Optional[float] = None) -> SeedAxisReconstruction:
        """Replaceable orientation backend with a checked physical/identity contract."""
        if provider is None and detected.native_orientation_contract is not None:
            from tool_factory.seed_seg.supplied_orientation import SuppliedXYOrientationProvider
            provider = SuppliedXYOrientationProvider(detected.native_orientation_contract)
        provider = provider or PhysicalPCAOrientationProvider()
        result = provider.estimate_seed_axes(detected.image_ref, detected.original_ct, detected.detections,
                                            detected.native_component_labels, profile=profile,
                                            dimensions=dimensions, coverage_status=detected.coverage_status,
                                            cancelled=cancelled, deadline=deadline)
        if not isinstance(result, SeedAxisReconstruction) or result.image_ref != detected.image_ref:
            raise ValueError("Orientation provider returned a foreign image revision")
        if result.provider_id != provider.provider_id or result.provider_version != provider.provider_version:
            raise ValueError("Orientation provider provenance must match the selected provider")
        expected = {x.detection_id: x.center_lps_mm for x in detected.detections}
        actual = {x.detection_id: x.center_lps_mm for x in result.observations}
        if expected != actual or result.profile != profile or result.review_status != "review_needed":
            raise ValueError("Orientation provider must preserve detected centers/profile and require review")
        if any(x.review_status != "review_needed" for x in result.observations):
            raise ValueError("Replacement orientation providers cannot accept their own observations")
        components = {x.detection_id: x.component_ids for x in detected.detections}
        uncertainty = {x.detection_id: (x.center_uncertainty_mm, x.association_status) for x in detected.detections}
        if any(x.component_ids != components[x.detection_id] or x.physical_seed_id is not None or
               x.dimensions != dimensions or (x.center_uncertainty_mm, x.component_association_status) !=
               uncertainty[x.detection_id] for x in result.observations):
            raise ValueError("Orientation providers must preserve components/source and cannot assign physical seed identities")
        return replace(result, detector_provenance=tuple(sorted((
            ("detector", "supplied-seedfinder"),
            ("model_sha256", detected.provenance.model_sha256),
            ("preprocessing_sha256", detected.provenance.preprocessing_sha256),
            ("contract_id", detected.provenance.contract_id),
            ("input_sha256", detected.provenance.image_sha256),
            ("artifact_signature", hashlib.sha256(json.dumps(
                [asdict(x) for x in detected.artifacts], sort_keys=True).encode()).hexdigest()),
        ))))


def _associate_component(point: np.ndarray, labels: sitk.Image, geometry: ImageGeometry,
                         request: SeedFinderRequest):
    xyz = geometry.xyz_from_points(point)
    radius = request.association_radius_mm / np.asarray(geometry.spacing_xyz)
    low = np.maximum(np.floor(xyz - radius).astype(int), 0)
    high = np.minimum(np.ceil(xyz + radius).astype(int) + 1, np.asarray(geometry.size_xyz))
    if math.prod(int(x) for x in high - low) > 200_000:
        raise ValueError("Component association neighborhood exceeds the bounded ROI limit")
    array = sitk.GetArrayViewFromImage(labels)[tuple(slice(int(a), int(b)) for a, b in zip(low[::-1], high[::-1]))]
    indices = np.argwhere(array > 0)
    if not len(indices):
        return (), "unassociated"
    physical = geometry.points_from_xyz(indices[:, ::-1] + low)
    distances = np.linalg.norm(physical - point, axis=1)
    ids = array[tuple(indices.T)]
    components, inverse = np.unique(ids, return_inverse=True)
    minima = np.full(len(components), np.inf)
    np.minimum.at(minima, inverse, distances)
    nearest = {}
    for component, distance in zip(components, minima):
        distance = float(distance)
        if distance <= request.association_radius_mm:
            nearest[int(component)] = distance
    if not nearest:
        return (), "unassociated"
    best = min(nearest.values())
    candidates = tuple(sorted(key for key, distance in nearest.items()
                              if distance - best <= request.association_ambiguity_mm))
    return candidates, "associated" if len(candidates) == 1 else "ambiguous"
