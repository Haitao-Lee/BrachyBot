"""Optional Microsoft BiomedParse v2 CT CTV adapter.

BiomedParse v2 is a text-guided research foundation model, not a
site-specific clinically validated CTV model.  The adapter is deliberately
opt-in: the official checkout, its isolated dependencies, and its checkpoint
must be supplied by deployment configuration.  The pancreatic production
nnU-Net path is not routed through this module.
"""

from __future__ import annotations

import os
import sys
import threading
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import SimpleITK as sitk

from tool_factory import BaseTool, ToolResult


BIOMEDPARSE_REPOSITORY = "https://github.com/microsoft/BiomedParse/tree/v2"
BIOMEDPARSE_MODEL_URL = (
    "https://huggingface.co/microsoft/BiomedParse/resolve/main/biomedparse_v2.ckpt"
)


# These prompts are the CT lesion/anatomy phrases documented by the official
# v2 project.  They produce candidate masks, not a clinical contour approval.
SITE_SPECS: Dict[str, Dict[str, Any]] = {
    "biomedparse_liver_tumor": {
        "site": "liver",
        "prompt": "liver tumors",
        "window": (400.0, 40.0),
        "label": "liver tumor",
    },
    "biomedparse_kidney_lesion": {
        "site": "kidney",
        "prompt": "kidney lesion",
        "window": (400.0, 40.0),
        "label": "kidney lesion",
    },
    "biomedparse_lung_lesion": {
        "site": "lung",
        "prompt": "lung lesion",
        "window": (1500.0, -160.0),
        "label": "lung lesion",
    },
    "biomedparse_colon_primary": {
        "site": "colon",
        "prompt": "colon cancer primary",
        "window": (400.0, 40.0),
        "label": "colon cancer primary",
    },
    "biomedparse_head_neck_cancer": {
        "site": "head_neck",
        "prompt": "head and neck cancer",
        "window": (400.0, 40.0),
        "label": "head and neck cancer",
    },
}


# Official BiomedParse imports are intentionally kept out of module import
# time.  This keeps the normal BrachyBot environment lightweight and ensures
# an unavailable optional model returns a clear, actionable result.
_RUNTIME_LOCK = threading.RLock()
_RUNTIME_CACHE: Dict[Tuple[str, str], Tuple[Any, ...]] = {}


def _validation_registry_path() -> Path:
    configured = os.environ.get("BRACHYBOT_RUNTIME_DIR")
    runtime_root = (
        Path(configured).expanduser().resolve()
        if configured
        else Path(__file__).resolve().parents[2] / ".runtime"
    )
    return runtime_root / "model_validation" / "biomedparse_v2.json"


def _validation_records() -> Dict[str, Dict[str, Any]]:
    path = _validation_registry_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _record_successful_validation(
    tumor_type: str,
    *,
    image: sitk.Image,
    mask: sitk.Image,
    voxel_count: int,
) -> None:
    """Persist technical-chain evidence; this never implies clinical validity."""
    records = _validation_records()
    records[tumor_type] = {
        "technical_call_chain_passed": True,
        "space_alignment_passed": (
            tuple(mask.GetSize()) == tuple(image.GetSize())
            and tuple(mask.GetSpacing()) == tuple(image.GetSpacing())
            and tuple(mask.GetOrigin()) == tuple(image.GetOrigin())
            and tuple(mask.GetDirection()) == tuple(image.GetDirection())
        ),
        "result_save_path_passed": False,
        "data_tree_viewer_passed": False,
        "voxel_count": int(voxel_count),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "clinical_case_validation": False,
    }
    path = _validation_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="biomedparse-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def record_pipeline_validation(tumor_type: str, **flags: bool) -> None:
    """Advance only observed integration stages for one research tumor type."""
    if tumor_type not in SITE_SPECS:
        return
    records = _validation_records()
    record = dict(records.get(tumor_type, {}))
    for key in ("result_save_path_passed", "data_tree_viewer_passed"):
        if key in flags:
            record[key] = bool(flags[key])
    record["checked_at"] = datetime.now(timezone.utc).isoformat()
    record.setdefault("clinical_case_validation", False)
    records[tumor_type] = record
    path = _validation_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="biomedparse-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _repo_root() -> Optional[Path]:
    configured = os.environ.get("BIOMEDPARSE_ROOT") or os.environ.get("BIOMEDPARSE_V2_ROOT")
    if not configured:
        return None
    return Path(configured).expanduser().resolve()


def _checkpoint_path(root: Optional[Path]) -> Path:
    configured = os.environ.get("BIOMEDPARSE_V2_CHECKPOINT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (root / "biomedparse_v2.ckpt").resolve() if root else Path()


def _availability() -> Dict[str, Any]:
    root = _repo_root()
    checkpoint = _checkpoint_path(root)
    missing = []
    if not root or not root.is_dir():
        missing.append("BIOMEDPARSE_ROOT")
    elif not (root / "configs" / "model").is_dir():
        missing.append("BiomedParse v2 configs/model")
    elif not (root / "inference.py").is_file() or not (root / "utils.py").is_file():
        missing.append("BiomedParse v2 inference.py/utils.py")
    if not checkpoint or not checkpoint.is_file():
        missing.append("BIOMEDPARSE_V2_CHECKPOINT")
    return {
        "available": not missing,
        "repository": BIOMEDPARSE_REPOSITORY,
        "model_url": BIOMEDPARSE_MODEL_URL,
        "root": str(root) if root else None,
        "checkpoint": str(checkpoint) if checkpoint else None,
        "missing": missing,
        "research_only": True,
        "clinical_validation_status": "not_established",
    }


def _normalise_ct(array: np.ndarray, window: Tuple[float, float]) -> np.ndarray:
    """Apply the official v2 CT windowing contract and return values in [0, 255]."""
    width, level = window
    low = float(level) - float(width) / 2.0
    high = float(level) + float(width) / 2.0
    values = np.nan_to_num(
        np.asarray(array, dtype=np.float32),
        nan=low,
        posinf=high,
        neginf=low,
    )
    return (np.clip(values, low, high) - low) * (255.0 / (high - low))


def _load_runtime(root: Path, checkpoint: Path) -> Tuple[Any, ...]:
    """Load the official model lazily and cache it by checkout/checkpoint pair."""
    cache_key = (str(root), str(checkpoint))
    with _RUNTIME_LOCK:
        if cache_key in _RUNTIME_CACHE:
            return _RUNTIME_CACHE[cache_key]
        if not root.is_dir():
            raise RuntimeError(
                "BiomedParse v2 is not installed. Set BIOMEDPARSE_ROOT to the "
                "official BiomedParse v2 checkout."
            )
        if not checkpoint.is_file():
            raise RuntimeError(
                "BiomedParse v2 weights are unavailable. Set "
                "BIOMEDPARSE_V2_CHECKPOINT or place biomedparse_v2.ckpt at the "
                f"configured checkout ({root})."
            )

        root_text = str(root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        try:
            import hydra
            from hydra import compose
            from hydra.core.global_hydra import GlobalHydra
            import torch
            from inference import merge_multiclass_masks, postprocess
            from utils import process_input, process_output
        except ImportError as exc:
            raise RuntimeError(
                "BiomedParse v2 dependencies are not installed. Install the pinned "
                "requirements from the official v2 repository in its isolated environment."
            ) from exc

        try:
            # Hydra is process-global.  Serializing initialization prevents a
            # concurrent optional-model request from corrupting another request.
            GlobalHydra.instance().clear()
            with hydra.initialize_config_dir(
                config_dir=str(root / "configs" / "model"),
                job_name="brachybot_biomedparse_v2",
                version_base=None,
            ):
                cfg = compose(config_name="biomedparse_3D")
            model = hydra.utils.instantiate(cfg, _convert_="object")
            model.load_pretrained(str(checkpoint))
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model = model.to(device).eval()
        except Exception as exc:
            raise RuntimeError(f"BiomedParse v2 model initialization failed: {exc}") from exc

        runtime = (
            model,
            device,
            process_input,
            process_output,
            postprocess,
            merge_multiclass_masks,
            torch,
        )
        _RUNTIME_CACHE[cache_key] = runtime
        return runtime


class BiomedParseV2CTVTool(BaseTool):
    """Generate research CTV candidates from BiomedParse v2 CT inference."""

    @property
    def name(self) -> str:
        return "biomedparse_v2_ctv"

    @property
    def description(self) -> str:
        return (
            "Research-only text-guided CT tumor/lesion candidate segmentation using "
            "Microsoft BiomedParse v2. Supports selected liver, kidney, lung, colon, "
            "and head/neck prompts. The official checkout and checkpoint must be "
            "installed explicitly; this is not a validated clinical CTV model."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "x-server-injected": True},
                "image_path": {"type": "string"},
                "tumor_type": {"type": "string", "enum": sorted(SITE_SPECS)},
                "slice_batch_size": {"type": "integer", "minimum": 1, "default": 4},
            },
            "required": ["tumor_type"],
        }

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ctv_mask": {"type": "object"},
                "ctv_array": {"type": "array"},
                "ctv_volume_mm3": {"type": "number"},
                "ctv_voxel_count": {"type": "integer"},
                "tumor_type_used": {"type": "string"},
                "research_only": {"type": "boolean"},
            },
        }

    def _execute(self, **kwargs: Any) -> ToolResult:
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        tumor_type = str(kwargs.get("tumor_type") or "").strip().lower()
        spec = SITE_SPECS.get(tumor_type)
        if spec is None:
            return ToolResult(
                success=False,
                error=f"Unsupported BiomedParse v2 CTV type: {tumor_type}",
                metadata={"supported_types": sorted(SITE_SPECS), "research_only": True},
            )
        if image is None and image_path:
            try:
                image = sitk.ReadImage(str(image_path))
            except Exception as exc:
                return ToolResult(success=False, error=f"Unable to read CT image: {exc}")
        if image is None:
            return ToolResult(success=False, error="Either image or image_path must be provided")

        availability = _availability()
        if not availability["available"]:
            return ToolResult(
                success=False,
                error="BiomedParse v2 is not ready: " + ", ".join(availability["missing"]),
                metadata=availability,
            )

        root = _repo_root()
        if root is None:  # guarded by _availability; keeps the type contract explicit
            raise RuntimeError("BIOMEDPARSE_ROOT is not configured")
        checkpoint = _checkpoint_path(root)
        try:
            lpi_image = sitk.DICOMOrient(image, "LPI")
            runtime = _load_runtime(root, checkpoint)
            model, device, process_input, process_output, postprocess, merge_masks, torch = runtime
            import torch.nn.functional as F

            with _RUNTIME_LOCK, torch.inference_mode():
                normalised = _normalise_ct(sitk.GetArrayFromImage(lpi_image), spec["window"])
                prepared, pad_width, padded_size, valid_axis = process_input(normalised, 512)
                prepared = prepared.to(device).int()
                output = model(
                    {"image": prepared.unsqueeze(0), "text": [spec["prompt"]]},
                    mode="eval",
                    slice_batch_size=max(1, int(kwargs.get("slice_batch_size") or 4)),
                )
                predictions = output["predictions"]
                mask_logits = predictions["pred_gmasks"]
                mask_logits = F.interpolate(
                    mask_logits,
                    size=(512, 512),
                    mode="bicubic",
                    align_corners=False,
                    antialias=True,
                )
                masks = postprocess(mask_logits, predictions["object_existence"])
                mask_volume = merge_masks(masks, [1])
                mask_volume = process_output(mask_volume, pad_width, padded_size, valid_axis)
                existence = predictions["object_existence"].sigmoid()
                confidence = float(existence.max().detach().cpu().item())
                mask_array = np.asarray(mask_volume, dtype=np.uint8)

                # Release request-local references before returning the array;
                # the model itself remains cached for later requests.
                del prepared, output, predictions, mask_logits, masks, mask_volume

            mask_array = (mask_array > 0).astype(np.uint8, copy=False)
            voxel_count = int(np.count_nonzero(mask_array))
            if voxel_count <= 0:
                return ToolResult(
                    success=False,
                    error=(
                        "BiomedParse v2 returned an empty candidate mask. Review the CT "
                        "window/prompt and provide a clinician-approved CTV mask instead."
                    ),
                    metadata={
                        **availability,
                        "tumor_type_used": tumor_type,
                        "text_prompt": spec["prompt"],
                        "object_existence_confidence": confidence,
                    },
                )

            ctv_mask = sitk.GetImageFromArray(mask_array)
            ctv_mask.CopyInformation(lpi_image)
            spacing = ctv_mask.GetSpacing()
            volume_mm3 = float(voxel_count * spacing[0] * spacing[1] * spacing[2])
            _record_successful_validation(
                tumor_type,
                image=lpi_image,
                mask=ctv_mask,
                voxel_count=voxel_count,
            )
            metadata = {
                **availability,
                "ctv_mask": ctv_mask,
                "ctv_array": mask_array,
                "ctv_volume_mm3": volume_mm3,
                "ctv_voxel_count": voxel_count,
                "tumor_type_used": tumor_type,
                "ctv_source": "biomedparse_v2_research_candidate",
                "label_grid_orientation": "LPI",
                "label_map": {1: spec["label"]},
                "text_prompt": spec["prompt"],
                "object_existence_confidence": confidence,
                "model_name": "BiomedParse v2",
            }
            return ToolResult(
                success=True,
                data=mask_array,
                message=(
                    f"BiomedParse v2 produced a research candidate CTV for {spec['site']} "
                    f"({volume_mm3:.1f} mm3); clinician contour review is required."
                ),
                metadata=metadata,
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"BiomedParse v2 inference failed: {exc}",
                metadata={**availability, "tumor_type_used": tumor_type},
            )


__all__ = [
    "BIOMEDPARSE_MODEL_URL",
    "BIOMEDPARSE_REPOSITORY",
    "BiomedParseV2CTVTool",
    "SITE_SPECS",
    "_validation_records",
    "record_pipeline_validation",
]
