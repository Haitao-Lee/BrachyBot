"""Dedicated two-stage nnUNet v2 cascade CTV adapters.

The liver and kidney tumor models are trained as local five-fold cascades:

    CT -> organ segmentation -> organ bbox + 30 mm -> tumor segmentation
       -> paste-back to the original CT grid

The vendor/deployment scripts already implement the validated inference
procedure.  This adapter owns the application boundary around those scripts:
model/runtime discovery, GPU leasing, single-worker serialization, bounded
subprocess execution, output validation, and physical-grid alignment.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import SimpleITK as sitk

from tool_factory import BaseTool, ToolResult


logger = logging.getLogger(__name__)


# The supplied cascades load two five-fold ensembles at the same time.  Keep a
# process-wide lock so two browser requests cannot load ten predictors onto
# the same GPU concurrently and turn a valid plan into an OOM.
_CASCADE_EXECUTION_LOCK = threading.Lock()


CASCADE_SITE_SPECS: Dict[str, Dict[str, object]] = {
    "liver": {
        "tumor_type": "nnunet_liver_tumor",
        "label": "liver tumor",
        "script": "<workspace>/prostate_lesion_seg/cascade_infer_v2.py",
        "model_root": "<workspace>/prostate_lesion_seg/trained_models/liver_cancer_seg",
        "stage1": "stage1_liver",
        "stage2": "stage2_tumor",
        "model_validation": {
            "dataset_dice": 0.755,
            "case_mean_dice": 0.611,
            "precision": 0.83,
            "recall": 0.69,
            "validation_protocol": "5-fold cross-validation, full-space Dice",
        },
    },
    "kidney": {
        "tumor_type": "nnunet_kidney_tumor",
        "label": "kidney tumor",
        "script": "<workspace>/kidney_tumor_seg/cascade_infer_kidney.py",
        "model_root": "<workspace>/kidney_tumor_seg/trained_models/kidney_cancer_seg",
        "stage1": "stage1_kidney",
        "stage2": "stage2_tumor",
        "model_validation": {
            "dataset_dice": 0.857,
            "case_mean_dice": 0.822,
            "precision": 0.81,
            "recall": 0.90,
            "validation_protocol": "5-fold cross-validation, full-space Dice; case_00223 excluded during training",
        },
    },
}


def _env_path(site: str, key: str, default: str) -> Path:
    value = os.environ.get(f"BRACHYBOT_{site.upper()}_CASCADE_{key}")
    return Path(value or default).expanduser()


def cascade_python_executable() -> Path:
    """Return the interpreter requested for the external nnUNet runtime."""

    return Path(
        os.environ.get("BRACHYBOT_CASCADE_PYTHON", "/opt/miniconda3/bin/python")
    ).expanduser()


def cascade_folds(*, fast: bool = False) -> str:
    """Return the fold ensemble requested for a cascade invocation.

    The supplied models were validated as five-fold ensembles, so that is the
    quality-preserving default. An explicit fast request may use a single fold
    for interactive previews or troubleshooting; it is never selected
    implicitly by the production planner.
    """

    default = "0" if fast else "0,1,2,3,4"
    value = os.environ.get(
        "BRACHYBOT_CASCADE_FAST_FOLDS" if fast else "BRACHYBOT_CASCADE_FOLDS",
        default,
    )
    folds = []
    for token in str(value).split(","):
        token = token.strip()
        if token.isdigit() and token not in folds:
            folds.append(token)
    return ",".join(folds) or default


def cascade_tile_step_size(*, fast: bool = False) -> float:
    """Return nnU-Net tile step tuning for this invocation.

    0.5 is the validated default. Fast mode can use a larger step and
    therefore fewer overlapping tiles, while remaining explicit and
    reversible through environment variables.
    """

    name = (
        "BRACHYBOT_CASCADE_FAST_TILE_STEP_SIZE"
        if fast
        else "BRACHYBOT_CASCADE_TILE_STEP_SIZE"
    )
    default = 0.75 if fast else 0.5
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(1.0, max(0.25, value))


def cascade_preprocess_workers() -> int:
    """Return a bounded CPU worker count for nnU-Net preprocessing/export."""

    try:
        value = int(os.environ.get("BRACHYBOT_CASCADE_PREPROCESS_WORKERS", "2"))
    except (TypeError, ValueError):
        value = 2
    return min(4, max(1, value))


def _site_spec(site: str) -> Dict[str, object]:
    try:
        return CASCADE_SITE_SPECS[str(site).strip().lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported nnUNet cascade site: {site}") from exc


def _resolved_spec(site: str) -> Dict[str, object]:
    spec = dict(_site_spec(site))
    spec["script_path"] = _env_path(site, "SCRIPT", str(spec["script"]))
    spec["model_root_path"] = _env_path(site, "MODEL_ROOT", str(spec["model_root"]))
    return spec


def _checkpoint_for_fold(folder: Path) -> Optional[Path]:
    for name in ("checkpoint_final.pth", "checkpoint_best.pth"):
        candidate = folder / name
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def cascade_availability(site: Optional[str] = None) -> Dict[str, object]:
    """Probe scripts, weights, five folds, and the configured Python runtime."""

    sites = [str(site).strip().lower()] if site else list(CASCADE_SITE_SPECS)
    result: Dict[str, object] = {}
    python_path = cascade_python_executable()
    for current_site in sites:
        spec = _resolved_spec(current_site)
        missing = []
        script_path = Path(spec["script_path"])
        model_root = Path(spec["model_root_path"])
        if not python_path.is_file() or not os.access(python_path, os.X_OK):
            missing.append(f"cascade Python executable: {python_path}")
        if not script_path.is_file():
            missing.append(f"cascade script: {script_path}")
        for stage_key in ("stage1", "stage2"):
            stage = model_root / str(spec[stage_key])
            if not stage.is_dir():
                missing.append(f"model stage: {stage}")
                continue
            for filename in ("plans.json", "dataset.json"):
                if not (stage / filename).is_file():
                    missing.append(f"model metadata: {stage / filename}")
            folds = sorted(
                path for path in stage.glob("fold_*") if path.is_dir()
            )
            if len(folds) < 5:
                missing.append(f"five-fold ensemble in {stage} (found {len(folds)})")
            for fold in folds:
                if _checkpoint_for_fold(fold) is None:
                    missing.append(f"checkpoint in {fold}")
        result[current_site] = {
            "site": current_site,
            "tumor_type": spec["tumor_type"],
            "script": str(script_path),
            "model_root": str(model_root),
            "python": str(python_path),
            "available": not missing,
            "missing": missing,
            "folds": 5,
            "requires_gpu": True,
            "model_validation": dict(spec.get("model_validation") or {}),
        }
    return result if site is None else result.get(str(site).strip().lower(), {})


class NNUNetCascadeTumorTool(BaseTool):
    """Base adapter for one of the supplied liver/kidney cascade scripts."""

    SITE = ""

    @property
    def spec(self) -> Dict[str, object]:
        return _resolved_spec(self.SITE)

    @property
    def name(self) -> str:
        return str(self.spec["tumor_type"])

    @property
    def description(self) -> str:
        label = str(self.spec["label"])
        return (
            f"Segment {label} CTV from CT using the installed two-stage nnUNet v2 "
            "five-fold cascade: organ localization, 30 mm bbox crop, tumor "
            "segmentation, and full-CT paste-back. The binary mask requires "
            "clinical contour review before planning."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {
                    "type": "object",
                    "description": "Server-injected SimpleITK CT image",
                    "x-server-injected": True,
                },
                "image_path": {
                    "type": "string",
                    "description": "Path to a 3D CT image (.nii or .nii.gz)",
                },
                "target_value": {
                    "type": "number",
                    "default": 1,
                    "description": "Compatibility field; cascade output is normalized to binary 1",
                },
                "fast_mode": {
                    "type": "boolean",
                    "default": False,
                    "description": "Explicit preview mode: one fold and a larger tile step; production defaults to the validated five-fold ensemble",
                },
            },
            "required": [],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "ctv_mask": {"type": "object"},
                "ctv_array": {"type": "array"},
                "ctv_volume_mm3": {"type": "number"},
                "ctv_voxel_count": {"type": "integer"},
                "tumor_type_used": {"type": "string"},
                "ctv_source": {"type": "string"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        fast_mode = bool(kwargs.get("fast_mode", False))
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        if image is None and image_path:
            try:
                image = sitk.ReadImage(str(image_path))
            except Exception as exc:
                return self._failure(f"Unable to read the CT for {self.name}: {exc}", "ct_read_failed")
        if image is None:
            return self._failure(
                "Either 'image' or 'image_path' must be provided for cascade CTV segmentation.",
                "ct_missing",
            )
        if not isinstance(image, sitk.Image) or image.GetDimension() != 3:
            return self._failure(
                f"The {self.SITE} nnUNet cascade requires a 3D CT volume; "
                f"received dimension {getattr(image, 'GetDimension', lambda: '?')()}.",
                "ct_not_3d",
            )

        availability = cascade_availability(self.SITE)
        if not availability.get("available"):
            missing = "; ".join(str(value) for value in availability.get("missing", []))
            return self._failure(
                f"The {self.SITE} nnUNet cascade is not available in this runtime. "
                f"Missing: {missing or 'unknown resource'}.",
                "cascade_model_unavailable",
                availability=availability,
            )

        queue_timeout = _positive_int_env("BRACHYBOT_CASCADE_QUEUE_TIMEOUT_SEC", 900)
        if not _CASCADE_EXECUTION_LOCK.acquire(timeout=queue_timeout):
            return self._failure(
                f"The {self.SITE} nnUNet cascade is busy with another GPU inference. "
                f"The request waited {queue_timeout}s; retry after the active case finishes.",
                "cascade_gpu_busy",
                availability=availability,
            )
        try:
            from plans.device_manager import device_session

            preferred_gpu = os.environ.get("BRACHYBOT_CASCADE_GPU") or None
            try:
                with device_session(
                    caller=f"nnunet_cascade_{self.SITE}",
                    prefer=preferred_gpu,
                ) as lease:
                    device = str(lease.device_str)
                    if not device.startswith("cuda"):
                        return self._failure(
                            f"The {self.SITE} nnUNet cascade requires an NVIDIA CUDA GPU "
                            "with the trained runtime; no CUDA device is available.",
                            "cascade_gpu_required",
                            availability=availability,
                        )
                    gpu_index = device.split(":", 1)[1] if ":" in device else "0"
                    return self._run_cascade(
                        image,
                        gpu_index=gpu_index,
                        availability=availability,
                        fast_mode=fast_mode,
                    )
            except Exception as exc:
                logger.exception("nnUNet %s cascade failed", self.SITE)
                return self._failure(
                    f"The {self.SITE} nnUNet cascade failed during local inference: {exc}",
                    "cascade_inference_failed",
                    availability=availability,
                )
        finally:
            _CASCADE_EXECUTION_LOCK.release()

    def _run_cascade(
        self,
        image: sitk.Image,
        *,
        gpu_index: str,
        availability: Dict[str, object],
        fast_mode: bool = False,
    ) -> ToolResult:
        spec = self.spec
        temp_dir = Path(tempfile.mkdtemp(prefix=f"brachybot-nnunet-{self.SITE}-"))
        input_dir = temp_dir / "input"
        output_dir = temp_dir / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        case_id = f"case_{uuid.uuid4().hex}"
        input_path = input_dir / f"{case_id}_0000.nii.gz"
        output_path = output_dir / f"{case_id}.nii.gz"
        proc: Optional[subprocess.Popen] = None
        try:
            # The input is written with its original SimpleITK geometry.  The
            # deployment scripts paste the stage-2 crop back onto this exact
            # grid; the parent CTV adapter performs a final LPI alignment.
            sitk.WriteImage(image, str(input_path), useCompression=True)
            python_path = str(availability["python"])
            command = [
                python_path,
                str(availability["script"]),
                "--input", str(input_dir),
                "--output", str(output_dir),
                "--gpu", str(gpu_index),
                "--model_root", str(availability["model_root"]),
                "--folds", cascade_folds(fast=fast_mode),
                "--tile_step_size", str(cascade_tile_step_size(fast=fast_mode)),
                "--workers", str(cascade_preprocess_workers()),
            ]
            env = self._clean_subprocess_env()
            env["PYTHONUNBUFFERED"] = "1"
            env["OMP_NUM_THREADS"] = "1"
            env["MKL_NUM_THREADS"] = "1"
            env["nnUNet_n_proc_DA"] = "0"
            # Reduce framework startup and CPU scheduling overhead without
            # changing trained weights or the default five-fold ensemble.
            env["CUDA_MODULE_LOADING"] = "LAZY"
            env["TORCH_CUDNN_V8_API_ENABLED"] = "1"
            logger.info(
                "Running %s nnUNet cascade on cuda:%s: %s",
                self.SITE,
                gpu_index,
                " ".join(command),
            )
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                start_new_session=(os.name == "posix"),
            )
            timeout_s = _positive_int_env("BRACHYBOT_CASCADE_TIMEOUT_SEC", 900)
            try:
                output, _ = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self._terminate_subprocess_group(proc)
                try:
                    output, _ = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    output = ""
                raise RuntimeError(
                    f"inference timed out after {timeout_s}s; "
                    f"last output: {self._tail_output(output, 12)}"
                )
            tail = self._tail_output(output, 40)
            for line in tail:
                logger.debug("[nnUNet %s cascade] %s", self.SITE, line)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"cascade process exited with code {proc.returncode}; "
                    f"last output: {' | '.join(tail[-12:]) or '(no output)'}"
                )
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                candidates = sorted(
                    path for path in output_dir.glob("*.nii*") if path.is_file()
                )
                if len(candidates) == 1:
                    output_path = candidates[0]
                else:
                    raise RuntimeError(
                        f"cascade completed without a unique full-space mask; "
                        f"outputs: {[path.name for path in candidates] or '(none)'}"
                    )

            predicted = sitk.ReadImage(str(output_path))
            if predicted.GetDimension() != 3:
                raise RuntimeError(
                    f"cascade output is not 3D (dimension {predicted.GetDimension()})"
                )
            from tool_factory.segmentation_alignment import align_label_image_to_reference

            aligned = align_label_image_to_reference(predicted, image, "LPI")
            mask_array = (sitk.GetArrayFromImage(aligned) > 0).astype(np.uint8)
            mask = sitk.GetImageFromArray(mask_array)
            mask.CopyInformation(aligned)
            voxel_count = int(np.count_nonzero(mask_array))
            spacing = mask.GetSpacing()
            volume_mm3 = float(voxel_count * spacing[0] * spacing[1] * spacing[2])
            source = f"nnunet_cascade_{self.SITE}"
            metadata = {
                "ctv_mask": mask,
                "ctv_array": mask_array,
                "ctv_volume_mm3": volume_mm3,
                "ctv_voxel_count": voxel_count,
                "tumor_type_used": str(spec["tumor_type"]),
                "ctv_source": source,
                "model_name": f"nnUNet v2 {self.SITE} tumor two-stage cascade",
                "repository": str(Path(str(spec["script_path"])).parent),
                "cascade_script": str(spec["script_path"]),
                "model_root": str(spec["model_root_path"]),
                "segmentation_task": f"{self.SITE}_organ_to_tumor_cascade",
                "segmentation_label": f"{self.SITE}_tumor",
                "source_labels_exposed": [f"{self.SITE}_tumor"],
                "label_counts": {1: voxel_count},
                "label_map": {1: f"{self.SITE} tumor"},
                "target_semantics": f"{self.SITE}_tumor_ctv_only",
                "cascade_folds": 5,
                "cascade_margin_mm": 30.0,
                "cascade_threshold": 0.5,
                "output_orientation": "LPI",
                "cascade_folds_used": cascade_folds(fast=fast_mode),
                "cascade_tile_step_size": cascade_tile_step_size(fast=fast_mode),
                "cascade_preprocess_workers": cascade_preprocess_workers(),
                "cascade_fast_mode": fast_mode,
                "cascade_gpu": f"cuda:{gpu_index}",
                "model_validation": dict(spec.get("model_validation") or {}),
                "cascade_organ_empty": voxel_count == 0,
            }
            return ToolResult(
                success=True,
                data=mask_array,
                message=(
                    f"nnUNet {self.SITE} tumor cascade completed: "
                    f"{voxel_count} tumor voxels ({volume_mm3:.1f} mm3)."
                ),
                metadata=metadata,
            )
        finally:
            if proc is not None and proc.poll() is None:
                self._terminate_subprocess_group(proc)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _failure(self, error: str, code: str, *, availability: Optional[Dict[str, object]] = None) -> ToolResult:
        spec = self.spec
        metadata = {
            "ctv_source": f"nnunet_cascade_{self.SITE}",
            "tumor_type_used": str(spec["tumor_type"]),
            "cascade_script": str(spec["script_path"]),
            "model_root": str(spec["model_root_path"]),
            "code": code,
            "requires_clinician_review": True,
        }
        if availability is not None:
            metadata["cascade_availability"] = availability
        return ToolResult(success=False, error=error, metadata=metadata)

    @staticmethod
    def _clean_subprocess_env() -> dict:
        env = os.environ.copy()
        for var in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "PYTHONHOME"):
            env.pop(var, None)
        return env

    @staticmethod
    def _tail_output(output: str, max_lines: int) -> list[str]:
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()][-max_lines:]

    @staticmethod
    def _terminate_subprocess_group(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            except Exception:
                proc.terminate()
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            except Exception:
                proc.kill()
        else:
            proc.kill()
        proc.wait()


class NNUNetLiverTumorTool(NNUNetCascadeTumorTool):
    SITE = "liver"


class NNUNetKidneyTumorTool(NNUNetCascadeTumorTool):
    SITE = "kidney"


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


__all__ = [
    "CASCADE_SITE_SPECS",
    "NNUNetCascadeTumorTool",
    "NNUNetLiverTumorTool",
    "NNUNetKidneyTumorTool",
    "cascade_availability",
    "cascade_python_executable",
    "cascade_preprocess_workers",
]
