"""SAT3D-backed interactive CTV candidate segmentation.

The official SAT3D checkout and checkpoints intentionally live outside this
repository.  BrachyBot invokes them in an isolated worker process so the web
server does not retain a 24 GB-class model or contaminate its Python runtime.

SAT3D is a point-prompted research model. Its output is a candidate contour
that must be reviewed by a qualified clinician before planning. It is kept as
an explicit interactive tool, not an automatic site-specific dispatcher:
without at least one positive point, a shared cross-site model has no semantic
signal identifying which tumor the user intends to segment.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import SimpleITK as sitk

from tool_factory import BaseTool, ToolResult


SAT3D_REPOSITORY = "https://github.com/himashi92/SAT3D"
SAT3D_PINNED_COMMIT = "e85cbf4b2e17c09b34b36369c4eca29e98321b4b"
SAT3D_ARTIFACT_DOI = "https://doi.org/10.6084/m9.figshare.30155497"
SAT3D_MODEL_URL = "https://ndownloader.figshare.com/files/58060666"
SAT3D_CRITIC_URL = "https://ndownloader.figshare.com/files/58060657"
SAT3D_MODEL_MD5 = "a5e59c357e01a4f9bda20564114bbd8a"
SAT3D_CRITIC_MD5 = "867286a0cf792693608509d0131834dc"


# Dataset names describe the published training/evaluation evidence, not a
# clinical indication.  OOD entries remain selectable only with an explicit
# compatible modality and are clearly marked in provenance.
SITE_SPECS: Dict[str, Dict[str, Any]] = {
    "sat3d_liver_tumor": {
        "site": "liver",
        "label": "liver tumor",
        "modalities": ("ct", "cta"),
        "evidence": "in_distribution",
        "datasets": ("MSD Hepatic", "LiTS"),
    },
    "sat3d_kidney_tumor": {
        "site": "kidney",
        "label": "kidney tumor",
        "modalities": ("ct", "cta"),
        "evidence": "in_distribution",
        "datasets": ("KiTS 2023", "KiPA 2022"),
    },
    "sat3d_lung_tumor": {
        "site": "lung",
        "label": "lung tumor",
        "modalities": ("ct",),
        "evidence": "in_distribution",
        "datasets": ("MSD Lung",),
    },
    "sat3d_colon_tumor": {
        "site": "colon",
        "label": "colon tumor",
        "modalities": ("ct",),
        "evidence": "in_distribution",
        "datasets": ("MSD Colon",),
    },
    "sat3d_head_neck_tumor": {
        "site": "head_neck",
        "label": "head and neck tumor",
        "modalities": ("mri", "t1", "t1ce", "t2", "ct"),
        "evidence": "mixed_in_distribution_and_ood",
        "datasets": ("HNTS-MRG 2024 MRI", "HECKTOR 2022 CT (OOD)"),
        "ood_modalities": ("ct",),
    },
    "sat3d_prostate_tumor": {
        "site": "prostate",
        "label": "prostate tumor",
        "modalities": ("mri", "t2", "t2w"),
        "evidence": "out_of_distribution",
        "datasets": ("Prostate158 T2w MRI (OOD)",),
    },
}


_INFERENCE_LOCK = threading.Lock()
_AVAILABILITY_CACHE: Dict[Tuple[str, ...], Dict[str, Any]] = {}


def _path_signature(path: Path) -> str:
    try:
        stat = path.stat()
        return f"{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        return "missing"


def _default_root() -> Path:
    # .../BrachyBot/tool_factory/CTV_seg/sat3d.py -> .../brachyplan/SAT3D
    return Path(__file__).resolve().parents[3] / "SAT3D"


def _root() -> Path:
    return Path(os.environ.get("SAT3D_ROOT", str(_default_root()))).expanduser().resolve()


def _runtime_python(root: Optional[Path] = None) -> Path:
    root = root or _root()
    configured = os.environ.get("SAT3D_RUNTIME_PYTHON")
    if configured:
        # Do not resolve a virtual-environment Python symlink.  On POSIX the
        # executable in ``.venv/bin`` commonly points at the base interpreter;
        # resolving it bypasses the adjacent pyvenv.cfg and silently loses the
        # SAT3D-only dependencies installed in that environment.
        return Path(os.path.abspath(os.path.expanduser(configured)))
    candidate = root / ".venv" / "bin" / "python"
    return candidate if candidate.is_file() else Path(sys.executable).resolve()


def _checkpoint(root: Optional[Path] = None) -> Path:
    root = root or _root()
    return Path(
        os.environ.get(
            "SAT3D_MODEL_CHECKPOINT",
            str(root / "weights" / "sam_model_dice_best.pth"),
        )
    ).expanduser().resolve()


def _critic_checkpoint(root: Optional[Path] = None) -> Path:
    root = root or _root()
    return Path(
        os.environ.get(
            "SAT3D_CRITIC_CHECKPOINT",
            str(root / "weights" / "critic_dice_best.pth"),
        )
    ).expanduser().resolve()


def _md5(path: Path) -> str:
    digest = hashlib.md5()  # nosec B324 - upstream artifact identity, not security
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _availability(*, verify_checksums: bool = False) -> Dict[str, Any]:
    root = _root()
    python = _runtime_python(root)
    model = _checkpoint(root)
    critic = _critic_checkpoint(root)
    cache_key = (
        str(root),
        str(python),
        str(model),
        str(critic),
        _path_signature(root / ".git" / "HEAD"),
        _path_signature(model),
        _path_signature(critic),
        str(bool(verify_checksums)),
    )
    cached = _AVAILABILITY_CACHE.get(cache_key)
    if cached is not None and not verify_checksums:
        return dict(cached)

    missing: List[str] = []
    actual_commit: Optional[str] = None
    if not (root / ".git").is_dir():
        missing.append("official SAT3D checkout (SAT3D_ROOT)")
    else:
        try:
            git_result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            actual_commit = (git_result.stdout or "").strip()
            if git_result.returncode != 0 or not actual_commit:
                missing.append("SAT3D source commit probe")
            elif actual_commit != SAT3D_PINNED_COMMIT:
                missing.append(
                    f"SAT3D source commit mismatch ({actual_commit}; expected {SAT3D_PINNED_COMMIT})"
                )
        except Exception:
            missing.append("SAT3D source commit probe")
    if not (root / "segment_anything_with_swin_conf" / "modeling").is_dir():
        missing.append("SAT3D model source")
    if not (root / "SAT3D-slicer" / "sat3D" / "sat3DLib" / "utils_monai_bts.py").is_file():
        missing.append("SAT3D sliding-window implementation")
    if not python.is_file():
        missing.append("SAT3D Python runtime (SAT3D_RUNTIME_PYTHON)")
    if not model.is_file():
        missing.append("SAT3D model checkpoint")
    if not critic.is_file():
        missing.append("SAT3D critic checkpoint")

    checksum_status: Dict[str, Optional[str]] = {"model": None, "critic": None}
    if verify_checksums and model.is_file():
        checksum_status["model"] = _md5(model)
        if checksum_status["model"] != SAT3D_MODEL_MD5:
            missing.append("SAT3D model checkpoint checksum mismatch")
    if verify_checksums and critic.is_file():
        checksum_status["critic"] = _md5(critic)
        if checksum_status["critic"] != SAT3D_CRITIC_MD5:
            missing.append("SAT3D critic checkpoint checksum mismatch")

    runtime_probe: Dict[str, Any] = {}
    if not missing:
        probe = (
            "import importlib.util,json,sys;"
            "mods=['torch','monai','torchio','SimpleITK','scipy'];"
            "missing=[m for m in mods if importlib.util.find_spec(m) is None];"
            "print(json.dumps({'python':sys.executable,'missing_modules':missing}));"
            "raise SystemExit(1 if missing else 0)"
        )
        try:
            completed = subprocess.run(
                [str(python), "-c", probe],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            payload = json.loads((completed.stdout or "{}").strip().splitlines()[-1])
            runtime_probe = payload
            if completed.returncode != 0:
                modules = ", ".join(payload.get("missing_modules") or [])
                missing.append(f"SAT3D runtime dependencies ({modules or 'probe failed'})")
        except Exception as exc:
            runtime_probe = {"probe_error": str(exc)}
            missing.append("SAT3D runtime dependency probe")

    result = {
        "available": not missing,
        "repository": SAT3D_REPOSITORY,
        "pinned_commit": SAT3D_PINNED_COMMIT,
        "actual_commit": actual_commit,
        "artifact_doi": SAT3D_ARTIFACT_DOI,
        "root": str(root),
        "runtime_python": str(python),
        "checkpoint": str(model),
        "critic_checkpoint": str(critic),
        "checkpoint_md5": SAT3D_MODEL_MD5,
        "critic_checkpoint_md5": SAT3D_CRITIC_MD5,
        "checksum_status": checksum_status,
        "runtime_probe": runtime_probe,
        "missing": missing,
    }
    if not verify_checksums:
        _AVAILABILITY_CACHE[cache_key] = dict(result)
    return result


def _normalise_modality(value: Any) -> str:
    raw = str(value or "ct").strip().casefold().replace("-", "").replace("_", "")
    aliases = {
        "computedtomography": "ct",
        "computedtomographyangiography": "cta",
        "mr": "mri",
        "magneticresonance": "mri",
        "t2weighted": "t2w",
        "t2weightedmri": "t2w",
        "contrastct": "ct",
        "cect": "ct",
    }
    return aliases.get(raw, raw)


def _coerce_point(point: Any) -> Tuple[float, float, float]:
    if isinstance(point, dict):
        values = (point.get("x"), point.get("y"), point.get("z"))
    elif isinstance(point, Sequence) and not isinstance(point, (str, bytes)):
        values = tuple(point[:3])
    else:
        raise ValueError(f"Invalid SAT3D point: {point!r}")
    if len(values) != 3 or not all(value is not None for value in values):
        raise ValueError(f"SAT3D point must contain exactly three coordinates: {point!r}")
    coords = tuple(float(value) for value in values)
    if not np.all(np.isfinite(coords)):
        raise ValueError(f"SAT3D point contains a non-finite coordinate: {point!r}")
    return coords


def _points_to_zyx(
    values: Optional[Iterable[Any]],
    *,
    coordinate_system: str,
    image: sitk.Image,
) -> List[List[int]]:
    shape = tuple(reversed(image.GetSize()))  # D,H,W
    converted: List[List[int]] = []
    for raw in values or []:
        a, b, c = _coerce_point(raw)
        if coordinate_system == "voxel_zyx":
            z, y, x = a, b, c
        elif coordinate_system == "voxel_xyz":
            x, y, z = a, b, c
        elif coordinate_system in {"physical_lps", "world_lps"}:
            x, y, z = image.TransformPhysicalPointToContinuousIndex((a, b, c))
        else:
            raise ValueError(
                "point_coordinate_system must be voxel_zyx, voxel_xyz, or physical_lps"
            )
        point = [int(round(z)), int(round(y)), int(round(x))]
        if any(point[axis] < 0 or point[axis] >= shape[axis] for axis in range(3)):
            raise ValueError(f"SAT3D point {point} is outside image shape {shape}")
        if point not in converted:
            converted.append(point)
    return converted


class SAT3DCTVTool(BaseTool):
    """Run the official SAT3D model with explicit point prompts."""

    def __init__(self, default_tumor_type: Optional[str] = None):
        self.default_tumor_type = default_tumor_type

    @property
    def name(self) -> str:
        return "sat3d_ctv_segmentation"

    @property
    def description(self) -> str:
        return (
            "Generate a review-required SAT3D tumor CTV candidate from a 3D volume. "
            "At least one positive voxel point prompt is required; negative points "
            "may be added to exclude false regions."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "x-server-injected": True},
                "image_path": {"type": "string"},
                "tumor_type": {"type": "string", "enum": sorted(SITE_SPECS)},
                "image_modality": {"type": "string", "default": "CT"},
                "positive_points": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "array"},
                },
                "negative_points": {"type": "array", "items": {"type": "array"}},
                "point_coordinate_system": {
                    "type": "string",
                    "enum": ["voxel_zyx", "voxel_xyz", "physical_lps"],
                    "default": "voxel_zyx",
                },
                "volume_index": {"type": "integer", "default": 0, "description": "Volume to extract from a 4D single-modality file"},
                "allow_out_of_distribution": {"type": "boolean", "default": False},
            },
            "required": (
                ["positive_points"]
                if self.default_tumor_type
                else ["tumor_type", "positive_points"]
            ),
        }

    @property
    def output_schema(self) -> dict:
        return {"type": "object", "properties": {"ctv_array": {"type": "array"}}}

    def _execute(self, **kwargs: Any) -> ToolResult:
        tumor_type = str(kwargs.get("tumor_type") or self.default_tumor_type or "").strip()
        spec = SITE_SPECS.get(tumor_type)
        if spec is None:
            return ToolResult(
                success=False,
                error=f"Unsupported SAT3D tumor_type '{tumor_type}'.",
                metadata={
                    "code": "unsupported_sat3d_tumor_type",
                    "supported_tumor_types": sorted(SITE_SPECS),
                },
            )

        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        try:
            if image is None and image_path:
                image = sitk.ReadImage(str(image_path))
        except Exception as exc:
            return ToolResult(success=False, error=f"Unable to read SAT3D input volume: {exc}")
        if image is None:
            return ToolResult(
                success=False,
                error="SAT3D requires image or image_path",
                metadata={"code": "sat3d_image_required"},
            )
        try:
            volume_index = int(kwargs.get("volume_index", 0))
        except (TypeError, ValueError):
            return ToolResult(
                success=False,
                error="SAT3D volume_index must be a non-negative integer.",
                metadata={"code": "invalid_sat3d_volume_index"},
            )
        if volume_index < 0 or (image.GetDimension() == 3 and volume_index != 0):
            return ToolResult(
                success=False,
                error=(
                    "SAT3D volume_index must be 0 for a 3D image."
                    if image.GetDimension() == 3
                    else "SAT3D volume_index must be a non-negative integer."
                ),
                metadata={"code": "invalid_sat3d_volume_index"},
            )
        if image.GetDimension() == 4:
            fourth_size = int(image.GetSize()[3])
            if volume_index < 0 or volume_index >= fourth_size:
                return ToolResult(
                    success=False,
                    error=f"SAT3D volume_index {volume_index} is outside 4D size {fourth_size}.",
                    metadata={"code": "invalid_sat3d_volume_index"},
                )
            image = sitk.Extract(
                image,
                [int(value) for value in image.GetSize()[:3]] + [0],
                [0, 0, 0, volume_index],
            )
        if image.GetDimension() != 3:
            return ToolResult(
                success=False,
                error=f"SAT3D requires one 3D volume; received {image.GetDimension()}D input.",
                metadata={"code": "sat3d_requires_3d_volume"},
            )
        image = sitk.DICOMOrient(image, "LPI")

        modality = _normalise_modality(kwargs.get("image_modality"))
        allowed = tuple(spec.get("modalities") or ())
        if modality not in allowed:
            return ToolResult(
                success=False,
                error=(
                    f"SAT3D {spec['site']} segmentation does not accept modality "
                    f"'{modality}' for this route. Select one of {list(allowed)} or "
                    "provide a reviewed manual CTV mask."
                ),
                metadata={
                    "code": "sat3d_modality_mismatch",
                    "tumor_type_used": tumor_type,
                    "image_modality": modality,
                    "supported_modalities": list(allowed),
                },
            )

        coordinate_system = str(
            kwargs.get("point_coordinate_system") or "voxel_zyx"
        ).strip().casefold()
        try:
            positive = _points_to_zyx(
                kwargs.get("positive_points"),
                coordinate_system=coordinate_system,
                image=image,
            )
            negative = _points_to_zyx(
                kwargs.get("negative_points"),
                coordinate_system=coordinate_system,
                image=image,
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                metadata={"code": "invalid_sat3d_prompt", "tumor_type_used": tumor_type},
            )
        if not positive:
            return ToolResult(
                success=False,
                error=(
                    "SAT3D is an interactive point-prompted model and requires at least "
                    "one positive point inside the intended tumor. Use BiomedParse v2 "
                    "for supported automatic text-guided CTV tasks."
                ),
                metadata={
                    "code": "sat3d_positive_prompt_required",
                    "tumor_type_used": tumor_type,
                    "ctv_source": "sat3d_interactive",
                },
            )
        overlap = {tuple(point) for point in positive} & {tuple(point) for point in negative}
        if overlap:
            return ToolResult(
                success=False,
                error=f"SAT3D points cannot be both positive and negative: {sorted(overlap)}",
                metadata={"code": "conflicting_sat3d_prompt", "tumor_type_used": tumor_type},
            )

        # Inference is the mutation boundary for the active clinical CTV.
        # Validate the required interaction contract first so a zero-prompt
        # request fails immediately instead of hashing two large checkpoints.
        # Only a valid point-guided request needs the full deployment check.
        availability = _availability(verify_checksums=True)
        if not availability.get("available"):
            return ToolResult(
                success=False,
                error=(
                    "SAT3D is not ready in this runtime: "
                    + "; ".join(availability.get("missing") or ["unknown deployment error"])
                    + ". Run scripts/install_sat3d.py and restart the server with the "
                    "SAT3D_* environment variables."
                ),
                metadata={
                    "code": "sat3d_unavailable",
                    "tumor_type_used": tumor_type,
                    "ctv_source": "sat3d_interactive",
                    "sat3d_availability": availability,
                },
            )

        worker = Path(__file__).resolve().parents[2] / "scripts" / "sat3d_worker.py"
        if not worker.is_file():
            return ToolResult(
                success=False,
                error=f"SAT3D worker is missing: {worker}",
                metadata={"code": "sat3d_worker_missing", "worker": str(worker)},
            )

        try:
            with tempfile.TemporaryDirectory(prefix="brachybot-sat3d-") as tmp:
                tmp_root = Path(tmp)
                input_file = tmp_root / "input.nii.gz"
                output_file = tmp_root / "mask.nii.gz"
                metadata_file = tmp_root / "metadata.json"
                points_file = tmp_root / "points.json"
                sitk.WriteImage(image, str(input_file), True)
                points_file.write_text(
                    json.dumps({"positive": positive, "negative": negative}),
                    encoding="utf-8",
                )
                command = [
                    availability["runtime_python"],
                    str(worker),
                    "--root", availability["root"],
                    "--model", availability["checkpoint"],
                    "--critic", availability["critic_checkpoint"],
                    "--input", str(input_file),
                    "--output", str(output_file),
                    "--metadata", str(metadata_file),
                    "--points", str(points_file),
                    "--device", str(os.environ.get("SAT3D_DEVICE", "cuda:0")),
                ]
                with _INFERENCE_LOCK:
                    completed = subprocess.run(
                        command,
                        cwd=availability["root"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=float(os.environ.get("SAT3D_INFERENCE_TIMEOUT", "1800")),
                    )
                if completed.returncode != 0:
                    detail = (completed.stderr or completed.stdout or "").strip()[-6000:]
                    raise RuntimeError(
                        f"SAT3D worker exited with code {completed.returncode}: {detail}"
                    )
                if not output_file.is_file() or not metadata_file.is_file():
                    raise RuntimeError("SAT3D worker did not create its mask and metadata")
                mask = sitk.ReadImage(str(output_file), sitk.sitkUInt8)
                mask.CopyInformation(image)
                mask_array = np.ascontiguousarray(sitk.GetArrayFromImage(mask), dtype=np.uint8)
                worker_meta = json.loads(metadata_file.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error="SAT3D inference timed out; no CTV was replaced.",
                metadata={"code": "sat3d_timeout", "tumor_type_used": tumor_type},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"SAT3D inference failed: {exc}",
                metadata={
                    "code": "sat3d_inference_failed",
                    "tumor_type_used": tumor_type,
                    "ctv_source": "sat3d",
                },
            )

        voxel_count = int(np.count_nonzero(mask_array))
        if voxel_count <= 0:
            return ToolResult(
                success=False,
                error=(
                    "SAT3D completed but produced an empty candidate. Add at least one "
                    "positive point inside the tumor and try again, or provide a reviewed mask."
                ),
                metadata={
                    "code": "sat3d_empty_mask",
                    "tumor_type_used": tumor_type,
                    "ctv_source": "sat3d",
                    "sat3d_prompt_mode": "point_guided",
                },
            )

        is_ood = modality in tuple(spec.get("ood_modalities") or ()) or spec.get("evidence") == "out_of_distribution"
        metadata = {
            "ctv_mask": mask,
            "ctv_array": mask_array,
            "ctv_voxel_count": voxel_count,
            "tumor_type_used": tumor_type,
            "requested_tumor_type": tumor_type,
            "ctv_source": "sat3d",
            "model_name": "SAT3D",
            "repository": SAT3D_REPOSITORY,
            "model_url": SAT3D_MODEL_URL,
            "artifact_doi": SAT3D_ARTIFACT_DOI,
            "sat3d_commit": SAT3D_PINNED_COMMIT,
            "checkpoint": availability["checkpoint"],
            "checkpoint_md5": SAT3D_MODEL_MD5,
            "critic_checkpoint": availability["critic_checkpoint"],
            "critic_checkpoint_md5": SAT3D_CRITIC_MD5,
            "image_modality": modality,
            "volume_index": volume_index,
            "sat3d_site": spec["site"],
            "sat3d_datasets": list(spec.get("datasets") or ()),
            "sat3d_evidence": spec.get("evidence"),
            "sat3d_out_of_distribution": bool(is_ood),
            "sat3d_prompt_mode": "point_guided",
            "sat3d_positive_points_zyx": positive,
            "sat3d_negative_points_zyx": negative,
            "sat3d_requires_clinician_review": True,
            "target_semantics": "review_required_tumor_candidate",
            "label_map": {1: spec["label"]},
            "worker_metadata": worker_meta,
        }
        return ToolResult(
            success=True,
            data=mask_array,
            message=(
                f"SAT3D generated a {spec['label']} candidate ({voxel_count} voxels). "
                "Clinical contour review is required before planning."
            ),
            metadata=metadata,
        )


__all__ = [
    "SAT3DCTVTool",
    "SITE_SPECS",
    "SAT3D_REPOSITORY",
    "SAT3D_PINNED_COMMIT",
    "SAT3D_MODEL_URL",
    "SAT3D_MODEL_MD5",
    "SAT3D_CRITIC_URL",
    "SAT3D_CRITIC_MD5",
    "_availability",
]
