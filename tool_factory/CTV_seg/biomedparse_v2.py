"""Optional Microsoft BiomedParse v2 CT CTV adapter.

BiomedParse v2 is a text-guided research foundation model, not a
site-specific clinically validated CTV model.  The adapter is deliberately
opt-in: the official checkout, its isolated dependencies, and its checkpoint
must be supplied by deployment configuration.  The pancreatic production
nnU-Net path is not routed through this module.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import json
import tempfile
import hashlib
import re
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
BIOMEDPARSE_TEXT_ASSETS_REPOSITORY = "openai/clip-vit-base-patch32"
_TEXT_ASSET_FILES = (
    "config.json",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
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
_RUNTIME_CACHE: Dict[Tuple[str, str, str], Tuple[Any, ...]] = {}
_AVAILABILITY_CACHE: Dict[Tuple[str, ...], Dict[str, Any]] = {}


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
    if configured:
        return Path(configured).expanduser().resolve()

    project_root = Path(__file__).resolve().parents[2]
    candidates = (
        project_root / "vendor" / "BiomedParse",
        project_root.parent / "BiomedParse",
        project_root / "models" / "ctv" / "biomedparse_v2" / "runtime",
    )
    return next((path.resolve() for path in candidates if path.is_dir()), None)


def _default_checkpoint_path() -> Path:
    """Return the repository-local deployment path for the optional weights.

    The checkpoint is intentionally ignored by Git because it is a large,
    gated binary. Keeping one stable path still lets the model catalog,
    setup script, and runtime adapter agree on where a locally authenticated
    download belongs.
    """
    return (
        Path(__file__).resolve().parents[2]
        / "models"
        / "ctv"
        / "biomedparse_v2"
        / "biomedparse_v2.ckpt"
    ).resolve()


def _checkpoint_path(root: Optional[Path]) -> Path:
    configured = os.environ.get("BIOMEDPARSE_V2_CHECKPOINT")
    if configured:
        return Path(configured).expanduser().resolve()
    # Prefer the explicit isolated checkout when it contains the default
    # filename; otherwise use BrachyBot's stable deployment path. This keeps
    # the official runtime separate from the application while allowing the
    # weight file to be shared by all supported tumor prompts.
    if root:
        checkout_path = (root / "biomedparse_v2.ckpt").resolve()
        if checkout_path.is_file():
            return checkout_path
    return _default_checkpoint_path()


def _default_text_assets_path() -> Path:
    """Return the offline CLIP tokenizer directory used by BiomedParse v2."""
    return (
        Path(__file__).resolve().parents[2]
        / "models"
        / "ctv"
        / "biomedparse_v2"
        / "clip-vit-base-patch32"
    ).resolve()


def _text_assets_path(root: Optional[Path]) -> Path:
    configured = os.environ.get("BIOMEDPARSE_V2_TEXT_ASSETS")
    if configured:
        return Path(configured).expanduser().resolve()
    if root:
        checkout_path = (root / "clip-vit-base-patch32").resolve()
        if checkout_path.is_dir():
            return checkout_path
    return _default_text_assets_path()


def _missing_text_assets(path: Path) -> list[str]:
    return [name for name in _TEXT_ASSET_FILES if not (path / name).is_file()]


def _runtime_python(root: Optional[Path]) -> Optional[Path]:
    configured = os.environ.get("BIOMEDPARSE_V2_PYTHON")
    if configured:
        # Do not resolve the final symlink. POSIX virtual environments commonly
        # expose ``.venv/bin/python`` as a symlink to the system interpreter;
        # executing the resolved target bypasses pyvenv.cfg and loses every
        # package installed in the isolated environment.
        return Path(os.path.abspath(os.fspath(Path(configured).expanduser())))
    if root:
        candidates = (
            root / ".venv" / "bin" / "python",
            root / "venv" / "bin" / "python",
            root / ".venv" / "Scripts" / "python.exe",
            root / "venv" / "Scripts" / "python.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return Path(os.path.abspath(os.fspath(candidate)))
    return Path(sys.executable).resolve() if sys.executable else None


def _probe_runtime(
    python_path: Path,
    root: Path,
    checkpoint: Path,
    text_assets: Path,
) -> Dict[str, Any]:
    """Cheaply verify the isolated inference imports without loading weights."""
    cache_key = (
        str(python_path),
        str(root),
        str(checkpoint),
        str(text_assets),
    )
    cached = _AVAILABILITY_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    probe = (
        "import importlib.util,json,sys;"
        f"sys.path.insert(0,{str(root)!r});"
        "names=['torch','hydra','detectron2','transformers','open_clip','timm',"
        "'safetensors','inference','utils'];"
        "missing=[name for name in names if importlib.util.find_spec(name) is None];"
        "print(json.dumps({'missing_modules':missing,'python':sys.executable}))"
    )
    result: Dict[str, Any]
    try:
        completed = subprocess.run(
            [str(python_path), "-c", probe],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("BIOMEDPARSE_V2_PROBE_TIMEOUT", "8")),
        )
        payload = {}
        if completed.stdout.strip():
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
        missing_modules = list(payload.get("missing_modules") or [])
        result = {
            "ready": completed.returncode == 0 and not missing_modules,
            "missing_modules": missing_modules,
            "python": payload.get("python") or str(python_path),
            "probe_error": (
                completed.stderr.strip()[-1200:]
                if completed.returncode != 0
                else ""
            ),
        }
    except Exception as exc:
        result = {
            "ready": False,
            "missing_modules": [],
            "python": str(python_path),
            "probe_error": str(exc),
        }
    _AVAILABILITY_CACHE[cache_key] = dict(result)
    return result


def _availability() -> Dict[str, Any]:
    root = _repo_root()
    checkpoint = _checkpoint_path(root)
    text_assets = _text_assets_path(root)
    runtime_python = _runtime_python(root)
    missing = []
    if not root or not root.is_dir():
        missing.append(
            "BiomedParse v2 checkout (set BIOMEDPARSE_ROOT or install the sibling checkout)"
        )
    elif not (root / "configs" / "model").is_dir():
        missing.append("BiomedParse v2 configs/model")
    elif not (root / "inference.py").is_file() or not (root / "utils.py").is_file():
        missing.append("BiomedParse v2 inference.py/utils.py")
    if not checkpoint or not checkpoint.is_file():
        missing.append("BIOMEDPARSE_V2_CHECKPOINT")
    missing_text_assets = _missing_text_assets(text_assets)
    if missing_text_assets:
        missing.append(
            "BiomedParse v2 CLIP tokenizer assets "
            f"({', '.join(missing_text_assets)})"
        )
    if not runtime_python or not runtime_python.is_file():
        missing.append("BiomedParse v2 Python runtime")

    runtime_probe: Dict[str, Any] = {}
    if not missing and root and runtime_python:
        runtime_probe = _probe_runtime(
            runtime_python,
            root,
            checkpoint,
            text_assets,
        )
        if not runtime_probe.get("ready"):
            modules = ", ".join(runtime_probe.get("missing_modules") or [])
            missing.append(
                f"BiomedParse v2 runtime dependencies ({modules})"
                if modules
                else "BiomedParse v2 runtime dependency probe"
            )
    return {
        "available": not missing,
        "repository": BIOMEDPARSE_REPOSITORY,
        "model_url": BIOMEDPARSE_MODEL_URL,
        "root": str(root) if root else None,
        "checkpoint": str(checkpoint) if checkpoint else None,
        "text_assets": str(text_assets),
        "runtime_python": str(runtime_python) if runtime_python else None,
        "runtime_mode": (
            "in_process"
            if runtime_python and Path(runtime_python).resolve() == Path(sys.executable).resolve()
            else "isolated_process"
        ),
        "runtime_probe": runtime_probe,
        "missing": missing,
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


def _load_runtime(
    root: Path,
    checkpoint: Path,
    text_assets: Optional[Path] = None,
) -> Tuple[Any, ...]:
    """Load the official model lazily and cache it by checkout/checkpoint pair."""
    text_assets = (text_assets or _text_assets_path(root)).resolve()
    cache_key = (str(root), str(checkpoint), str(text_assets))
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
                f"repository deployment path ({_default_checkpoint_path()})."
            )
        missing_text_assets = _missing_text_assets(text_assets)
        if missing_text_assets:
            raise RuntimeError(
                "BiomedParse v2 CLIP tokenizer assets are unavailable: "
                + ", ".join(missing_text_assets)
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
            cfg.sem_seg_head.predictor.language_encoder.tokenizer.pretrained_model_name_or_path = (
                str(text_assets)
            )
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


def _run_external_inference(
    *,
    normalised: np.ndarray,
    root: Path,
    checkpoint: Path,
    text_assets: Path,
    runtime_python: Path,
    prompt: str,
    slice_batch_size: int,
) -> Tuple[np.ndarray, float]:
    """Run the official Python 3.10 stack without contaminating the web runtime."""
    worker = Path(__file__).resolve().parents[2] / "scripts" / "biomedparse_v2_worker.py"
    if not worker.is_file():
        raise RuntimeError(f"BiomedParse v2 worker is missing: {worker}")

    with tempfile.TemporaryDirectory(prefix="brachybot-biomedparse-") as temp_dir:
        temp_root = Path(temp_dir)
        input_path = temp_root / "input.npy"
        output_path = temp_root / "mask.npy"
        metadata_path = temp_root / "metadata.json"
        np.save(input_path, np.asarray(normalised, dtype=np.float32), allow_pickle=False)
        command = [
            str(runtime_python),
            str(worker),
            "--root",
            str(root),
            "--checkpoint",
            str(checkpoint),
            "--text-assets",
            str(text_assets),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--metadata",
            str(metadata_path),
            "--prompt",
            prompt,
            "--slice-batch-size",
            str(max(1, int(slice_batch_size))),
        ]
        completed = subprocess.run(
            command,
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("BIOMEDPARSE_V2_INFERENCE_TIMEOUT", "1800")),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-4000:]
            raise RuntimeError(
                f"isolated inference exited with code {completed.returncode}: {detail}"
            )
        if not output_path.is_file() or not metadata_path.is_file():
            raise RuntimeError("isolated inference did not produce its mask and metadata")
        mask_array = np.load(output_path, allow_pickle=False)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return np.asarray(mask_array, dtype=np.uint8), float(
            metadata.get("object_existence_confidence", 0.0)
        )


def _run_prompt_inference(
    image: sitk.Image,
    *,
    prompt: str,
    window: Tuple[float, float] = (400.0, 40.0),
    slice_batch_size: int = 4,
) -> Tuple[Dict[str, Any], sitk.Image, np.ndarray, float]:
    """Run one text-guided BiomedParse inference on the canonical LPI grid.

    Both the site-specific CTV adapter and the open segmentation tool use this
    function. Keeping orientation, windowing, isolated-runtime selection, and
    output conversion in one place prevents a generic mask from silently using
    a different coordinate system than a CTV mask.
    """
    availability = _availability()
    if not availability["available"]:
        raise RuntimeError(
            "BiomedParse v2 is not ready: "
            + ", ".join(availability.get("missing") or [])
        )

    root = _repo_root()
    if root is None:
        raise RuntimeError("BIOMEDPARSE_ROOT is not configured")
    checkpoint = _checkpoint_path(root)
    text_assets = _text_assets_path(root)
    lpi_image = sitk.DICOMOrient(image, "LPI")
    normalised = _normalise_ct(
        sitk.GetArrayFromImage(lpi_image),
        window,
    )
    runtime_python_text = availability.get("runtime_python")
    # Do not resolve a POSIX virtualenv symlink; the target interpreter would
    # lose the isolated environment and its BiomedParse dependencies.
    runtime_python = (
        Path(runtime_python_text)
        if runtime_python_text
        else Path(sys.executable).resolve()
    )
    batch_size = max(1, int(slice_batch_size or 4))
    if runtime_python != Path(sys.executable).resolve():
        mask_array, confidence = _run_external_inference(
            normalised=normalised,
            root=root,
            checkpoint=checkpoint,
            text_assets=text_assets,
            runtime_python=runtime_python,
            prompt=prompt,
            slice_batch_size=batch_size,
        )
    else:
        runtime = _load_runtime(root, checkpoint, text_assets)
        (
            model,
            device,
            process_input,
            process_output,
            postprocess,
            merge_masks,
            torch,
        ) = runtime
        import torch.nn.functional as F

        with _RUNTIME_LOCK, torch.inference_mode():
            prepared, pad_width, padded_size, valid_axis = process_input(
                normalised,
                512,
            )
            prepared = prepared.to(device).int()
            output = model(
                {"image": prepared.unsqueeze(0), "text": [prompt]},
                mode="eval",
                slice_batch_size=batch_size,
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
            mask_volume = process_output(
                mask_volume,
                pad_width,
                padded_size,
                valid_axis,
            )
            existence = predictions["object_existence"].sigmoid()
            confidence = float(existence.max().detach().cpu().item())
            mask_array = np.asarray(mask_volume, dtype=np.uint8)

            # Release request-local tensors while retaining the cached model.
            del prepared, output, predictions, mask_logits, masks, mask_volume

    return availability, lpi_image, (np.asarray(mask_array) > 0).astype(np.uint8), confidence


class BiomedParseV2GenericSegmentationTool(BaseTool):
    """Segment an explicitly requested anatomy with the open v2 text prompt.

    This tool is intentionally separate from ``ctv_segmentation`` and
    ``oar_segmentation``. A free-form anatomy request is stored as an ordinary
    displayable mask and never becomes a treatment target or an OAR by guess.
    """

    @property
    def name(self) -> str:
        return "biomedparse_segmentation"

    @property
    def description(self) -> str:
        return (
            "Open text-guided anatomy segmentation with the optional BiomedParse v2 "
            "runtime. Use for an explicitly requested anatomy such as liver, pancreas "
            "or shoulder joint when the request is not CTV or OAR segmentation. "
            "The result is a reviewable mask and is not automatically assigned as a clinical contour."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image": {
                    "type": "object",
                    "description": "Server-injected SimpleITK Image of the CT scan",
                    "x-server-injected": True,
                },
                "image_path": {"type": "string"},
                "target": {
                    "type": "string",
                    "description": "The anatomy to segment, for example liver or shoulder joint",
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional text prompt; defaults to target",
                },
                "slice_batch_size": {"type": "integer", "minimum": 1, "default": 4},
            },
            "required": ["target"],
        }

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mask": {"type": "array"},
                "mask_id": {"type": "string"},
                "voxel_count": {"type": "integer"},
                "volume_mm3": {"type": "number"},
            },
        }

    def _execute(self, **kwargs: Any) -> ToolResult:
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        target = str(kwargs.get("target") or "").strip()
        prompt = str(kwargs.get("prompt") or target).strip()
        prompt = re.sub(r"\s+", " ", prompt)[:160]
        if not target or not prompt:
            return ToolResult(
                success=False,
                error="An explicit anatomy target is required for open segmentation.",
                metadata={"clarification_required": True},
            )
        prompt_lower = prompt.lower()
        if re.search(
            r"\b(?:ctv|oar|clinical target volume|organs? at risk)\b|"
            r"\u9776\u533a|\u5371\u53ca\u5668\u5b98",
            prompt_lower,
        ):
            return ToolResult(
                success=False,
                error=(
                    "CTV and OAR requests must use their dedicated segmentation tools; "
                    "open BiomedParse segmentation does not assign clinical structure type."
                ),
                metadata={"use_specific_tool": True, "target": target},
            )
        if image is None and image_path:
            try:
                image = sitk.ReadImage(str(image_path))
            except Exception as exc:
                return ToolResult(success=False, error=f"Unable to read CT image: {exc}")
        if image is None:
            return ToolResult(
                success=False,
                error="No CT image is loaded for open BiomedParse segmentation.",
            )

        availability: Dict[str, Any] = {}
        try:
            availability, lpi_image, mask_array, confidence = _run_prompt_inference(
                image,
                prompt=prompt,
                window=(400.0, 40.0),
                slice_batch_size=max(1, int(kwargs.get("slice_batch_size") or 4)),
            )
            voxel_count = int(np.count_nonzero(mask_array))
            if voxel_count <= 0:
                return ToolResult(
                    success=False,
                    error=(
                        f"BiomedParse v2 completed inference but found no '{target}' "
                        "in the current CT. Verify the scan coverage or use a manual mask."
                    ),
                    metadata={
                        **availability,
                        "target": target,
                        "text_prompt": prompt,
                        "object_existence_confidence": confidence,
                    },
                )

            spacing = tuple(float(value) for value in lpi_image.GetSpacing())
            volume_mm3 = float(voxel_count * spacing[0] * spacing[1] * spacing[2])
            source_key = f"{image_path or 'memory'}|{target}|{prompt}"
            mask_id = "mask_bp_" + hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:16]
            generic_mask = {
                "mask_id": mask_id,
                "object_id": f"mask:{mask_id}",
                "data_tree_node_id": mask_id,
                "target": target,
                "label": target,
                "name": target,
                "source": "biomedparse_v2",
                "kind": "generic_segmentation",
                "text_prompt": prompt,
                "shape": list(mask_array.shape),
                "spacing": list(spacing),
                "origin": list(lpi_image.GetOrigin()),
                "direction": list(lpi_image.GetDirection()),
                "voxel_count": voxel_count,
                "volume_mm3": volume_mm3,
                "object_existence_confidence": confidence,
                "model_name": "BiomedParse v2",
                "data_version": datetime.now(timezone.utc).isoformat(),
            }
            metadata = {
                **availability,
                "generic_mask": generic_mask,
                "mask_id": mask_id,
                "voxel_count": voxel_count,
                "volume_mm3": volume_mm3,
                "target": target,
                "text_prompt": prompt,
                "object_existence_confidence": confidence,
                "model_name": "BiomedParse v2",
            }
            return ToolResult(
                success=True,
                data=mask_array,
                message=(
                    f"BiomedParse v2 produced a mask for '{target}' "
                    f"({volume_mm3:.1f} mm3). It was added to the Data Tree for review; "
                    "it was not classified as CTV or OAR."
                ),
                metadata=metadata,
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"BiomedParse v2 could not segment '{target}': {exc}",
                metadata={**availability, "target": target, "text_prompt": prompt},
            )


class BiomedParseV2CTVTool(BaseTool):
    """Generate research CTV candidates from BiomedParse v2 CT inference."""

    @property
    def name(self) -> str:
        return "biomedparse_v2_ctv"

    @property
    def description(self) -> str:
        return (
        "Text-guided CT tumor/lesion candidate segmentation for research workflows using "
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
                metadata={"supported_types": sorted(SITE_SPECS)},
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
        text_assets = _text_assets_path(root)
        try:
            lpi_image = sitk.DICOMOrient(image, "LPI")
            normalised = _normalise_ct(
                sitk.GetArrayFromImage(lpi_image),
                spec["window"],
            )
            runtime_python_text = availability.get("runtime_python")
            # Do NOT resolve symlinks here: POSIX venvs expose .venv/bin/python
            # as a symlink, and resolving it bypasses pyvenv.cfg, losing every
            # package installed in the isolated environment (numpy, torch, ...).
            runtime_python = (
                Path(runtime_python_text)
                if runtime_python_text
                else Path(sys.executable).resolve()
            )
            if runtime_python != Path(sys.executable).resolve():
                mask_array, confidence = _run_external_inference(
                    normalised=normalised,
                    root=root,
                    checkpoint=checkpoint,
                    text_assets=text_assets,
                    runtime_python=runtime_python,
                    prompt=spec["prompt"],
                    slice_batch_size=max(1, int(kwargs.get("slice_batch_size") or 4)),
                )
            else:
                runtime = _load_runtime(root, checkpoint, text_assets)
                (
                    model,
                    device,
                    process_input,
                    process_output,
                    postprocess,
                    merge_masks,
                    torch,
                ) = runtime
                import torch.nn.functional as F

                with _RUNTIME_LOCK, torch.inference_mode():
                    prepared, pad_width, padded_size, valid_axis = process_input(
                        normalised,
                        512,
                    )
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
                    mask_volume = process_output(
                        mask_volume,
                        pad_width,
                        padded_size,
                        valid_axis,
                    )
                    existence = predictions["object_existence"].sigmoid()
                    confidence = float(existence.max().detach().cpu().item())
                    mask_array = np.asarray(mask_volume, dtype=np.uint8)

                    # Release request-local references before returning the
                    # array; the in-process model remains cached.
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
                "ctv_source": "biomedparse_v2",
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
                    f"BiomedParse v2 produced a CTV candidate for {spec['site']} "
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
    "BiomedParseV2GenericSegmentationTool",
    "BiomedParseV2CTVTool",
    "SITE_SPECS",
    "_validation_records",
    "record_pipeline_validation",
]
