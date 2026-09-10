"""
nnUNet Pancreatic Tumor Segmentation
=====================================
Pancreatic tumor segmentation using nnUNet v2.
Based on Zhiyuan repo approach (Dataset005_Pancreas).

Weight placement:
    BrachyBot/VoCo/pancreatic_tumor/Dataset005_Pancreas/
        nnUNetTrainer__nnUNetPlans__3d_fullres/
            fold_0/
                checkpoint_final.pth
            plans.json
            dataset.json
"""

import os
import shutil
import subprocess
import tempfile
import logging
from collections.abc import Mapping
from typing import Dict

import numpy as np
import SimpleITK as sitk

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Label mapping for PDAC (Pancreatic Ductal Adenocarcinoma) segmentation
# Matches Zhiyuan/BrachyPlan.py nnUNet Dataset005_Pancreas convention:
# 0=bg, 1=tumor(PDAC), 2=artery, 3=vein, 4=pancreas, 5=unknown, 6=unknown
LABEL_MAP = {
    0: ("background", False),
    1: ("pancreatic tumor", True),
    2: ("artery", False),
    3: ("vein", False),
    4: ("pancreas", False),
    5: ("unknown_5", False),
    6: ("unknown_6", False),
}


class NNUNetPancreaticTumorTool(BaseTool):
    """Segment pancreatic tumors using nnUNet v2 (Dataset005_Pancreas)."""

    MODEL_DIR = os.environ.get(
        "NNUNET_PANCREATIC_MODEL",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "VoCo", "pancreatic_tumor"),
    )

    @property
    def name(self) -> str:
        return "nnunet_pancreatic_tumor"

    @property
    def description(self) -> str:
        return "Segment pancreatic tumors using nnUNet v2 (Dataset005_Pancreas, 7 classes)."

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {"type": "object", "description": "SimpleITK Image of CT scan"},
                "image_path": {"type": "string", "description": "Path to CT image file"},
                "fast_mode": {"type": "boolean", "default": False},
            },
            "required": [],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "mask": {"type": "object"},
                "mask_array": {"type": "array"},
                "label_counts": {"type": "object"},
            },
        }

    @staticmethod
    def _coerce_prediction_array(value) -> np.ndarray:
        """Convert supported nnUNet result wrappers into one 3-D label array.

        nnUNet releases and local wrappers have returned an ndarray, a mapping
        containing the ndarray, or a tuple/list carrying the segmentation next
        to auxiliary logits/probabilities. Only the discrete 3-D segmentation
        is accepted; auxiliary arrays are never sent to the clinical pipeline.
        """

        def _validate(candidate):
            array = np.asarray(candidate)
            if array.ndim == 4 and array.shape[0] == 1:
                array = array[0]
            elif array.ndim == 4 and array.shape[-1] == 1:
                array = array[..., 0]
            if array.ndim != 3:
                raise ValueError(
                    f"expected a 3-D label array, got ndim={array.ndim}"
                )
            if not (
                np.issubdtype(array.dtype, np.number)
                or np.issubdtype(array.dtype, np.bool_)
            ):
                raise TypeError(f"expected numeric labels, got dtype={array.dtype}")
            if not np.all(np.isfinite(array)):
                raise ValueError("label array contains non-finite values")
            if np.any(array < 0) or np.any(array != np.floor(array)):
                raise ValueError("label array contains non-discrete values")
            max_label = int(array.max()) if array.size else 0
            dtype = np.uint16 if max_label > np.iinfo(np.uint8).max else np.uint8
            return np.ascontiguousarray(array.astype(dtype, copy=False))

        if isinstance(value, Mapping):
            # Prefer named segmentation fields, but skip empty/invalid fields
            # so a wrapper with segmentation=None and prediction=array remains usable.
            errors = []
            for key in ("segmentation", "prediction", "label_array", "result", "data"):
                if key not in value or value[key] is None:
                    continue
                try:
                    return NNUNetPancreaticTumorTool._coerce_prediction_array(value[key])
                except (TypeError, ValueError) as exc:
                    errors.append(f"{key}: {exc}")
            raise ValueError(
                "mapping did not contain a valid 3-D segmentation"
                + (f" ({'; '.join(errors)[:240]})" if errors else "")
            )

        if isinstance(value, (list, tuple)):
            if not value:
                raise ValueError("empty list/tuple cannot be a segmentation")
            # A regular nested Python list may itself be a valid 3-D array.
            try:
                return _validate(value)
            except (TypeError, ValueError):
                pass
            # A tuple such as (segmentation, logits) or a list of candidate
            # containers is handled by selecting the first valid discrete mask.
            errors = []
            for index, item in enumerate(value):
                try:
                    return NNUNetPancreaticTumorTool._coerce_prediction_array(item)
                except (TypeError, ValueError) as exc:
                    errors.append(f"{index}: {exc}")
            raise ValueError(
                "list/tuple did not contain a valid 3-D segmentation"
                + (f" ({'; '.join(errors)[:240]})" if errors else "")
            )

        return _validate(value)

    def _execute(self, **kwargs) -> ToolResult:
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        fast_mode = kwargs.get("fast_mode", False)

        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            return ToolResult(success=False, error="Either 'image' or 'image_path' must be provided")

        # Check model directory
        config_dir = os.path.join(self.MODEL_DIR, "Dataset005_Pancreas", "nnUNetTrainer__nnUNetPlans__3d_fullres")
        if not os.path.exists(config_dir):
            return ToolResult(
                success=False,
                error=f"Model directory not found: {config_dir}\n"
                      f"Please download nnUNet weights and place them at:\n"
                      f"  BrachyBot/VoCo/pancreatic_tumor/Dataset005_Pancreas/\n"
                      f"      nnUNetTrainer__nnUNetPlans__3d_fullres/\n"
                      f"          fold_0/checkpoint_final.pth\n"
                      f"          plans.json\n"
                      f"          dataset.json",
            )

        plans_json = os.path.join(config_dir, "plans.json")
        if not os.path.exists(plans_json):
            return ToolResult(success=False, error=f"plans.json not found: {plans_json}")

        # Copy dataset.json if needed
        dataset_json = os.path.join(config_dir, "dataset.json")
        if not os.path.exists(dataset_json):
            dataset_json_src = os.path.join(self.MODEL_DIR, "Dataset005_Pancreas", "dataset.json")
            if os.path.exists(dataset_json_src):
                shutil.copy2(dataset_json_src, dataset_json)

        try:
            result_array = self._run_nnunet_inference(image, config_dir, fast_mode)
            result_array = self._coerce_prediction_array(result_array)
        except (AttributeError, TypeError, KeyError, ValueError) as exc:
            logger.exception("nnUNet returned an invalid pancreatic label result")
            return ToolResult(
                success=False,
                error="nnUNet returned an invalid pancreatic label result.",
                metadata={
                    "ctv_contract_error": True,
                    "error_code": "CTV_PREDICTION_CONTRACT",
                    "exception_type": type(exc).__name__,
                    "nnunet_output_type": type(locals().get("result_array")).__name__,
                },
            )
        except Exception:
            logger.exception("nnUNet inference failed for pancreatic CTV")
            return ToolResult(
                success=False,
                error="nnUNet inference failed while producing the pancreatic CTV.",
                metadata={
                    "ctv_inference_error": True,
                    "error_code": "CTV_INFERENCE_ERROR",
                },
            )

        # Build label counts
        label_counts = {}
        for lid in np.unique(result_array):
            if lid > 0:
                name = LABEL_MAP.get(lid, (f"label_{lid}", True))[0]
                label_counts[name] = int(np.sum(result_array == lid))

        # Compute per-label volumes and centroids for LLM analysis
        spacing = image.GetSpacing()
        voxel_vol = spacing[0] * spacing[1] * spacing[2]
        label_stats = {}
        for lid in np.unique(result_array):
            if lid > 0:
                name = LABEL_MAP.get(lid, (f"label_{lid}", True))[0]
                vox_count = int(np.sum(result_array == lid))
                vol_mm3 = vox_count * voxel_vol
                z, y, x = np.where(result_array == lid)
                centroid_arr = [float(z.mean()), float(y.mean()), float(x.mean())]
                origin = image.GetOrigin()
                direction = image.GetDirection()
                centroid_world = [
                    origin[0] + direction[0]*centroid_arr[2]*spacing[0] + direction[1]*centroid_arr[1]*spacing[1] + direction[2]*centroid_arr[0]*spacing[2],
                    origin[1] + direction[3]*centroid_arr[2]*spacing[0] + direction[4]*centroid_arr[1]*spacing[1] + direction[5]*centroid_arr[0]*spacing[2],
                    origin[2] + direction[6]*centroid_arr[2]*spacing[0] + direction[7]*centroid_arr[1]*spacing[1] + direction[8]*centroid_arr[0]*spacing[2],
                ]
                label_stats[name] = {
                    "label_id": int(lid),
                    "voxel_count": vox_count,
                    "volume_mm3": round(vol_mm3, 1),
                    "volume_cm3": round(vol_mm3 / 1000, 2),
                    "centroid_world": [round(c, 1) for c in centroid_world],
                }

        # CTV = only label 1 (tumor)
        ctv_array = (result_array == 1).astype(np.uint8)
        ctv_mask = sitk.GetImageFromArray(ctv_array)
        ctv_mask.CopyInformation(image)

        # OAR = label 2 (artery) + label 3 (vein) — non-traversable
        oar_array = np.zeros_like(result_array, dtype=np.uint8)
        oar_array[result_array == 2] = 1  # artery
        oar_array[result_array == 3] = 2  # vein
        oar_mask = sitk.GetImageFromArray(oar_array)
        oar_mask.CopyInformation(image)

        ctv_voxel_count = int(np.sum(ctv_array > 0))
        ctv_volume = ctv_voxel_count * voxel_vol

        return ToolResult(
            success=True,
            data=ctv_array,
            message=f"nnUNet done. CTV(tumor): {ctv_voxel_count} vox ({ctv_volume/1000:.1f}cm³). OAR: artery={int(np.sum(oar_array==1))}, vein={int(np.sum(oar_array==2))}",
            metadata={
                "ctv_mask": ctv_mask,
                "ctv_array": ctv_array,
                "ctv_volume_mm3": float(ctv_volume),
                "ctv_voxel_count": ctv_voxel_count,
                "oar_mask": oar_mask,
                "oar_array": oar_array,
                "label_counts": label_counts,
                "label_map": {lid: name for lid, (name, _) in LABEL_MAP.items()},
                "label_stats": label_stats,
                "organ_names": {1: "artery", 2: "vein"},
                # Full multi-label array for data tree (0=bg, 1=tumor, 2=artery, 3=vein, 4=pancreas, 5=unknown_5, 6=unknown_6)
                "full_label_array": result_array.astype(np.uint8),
            },
        )

    def _run_nnunet_inference(self, image: sitk.Image, config_dir: str, fast_mode: bool) -> np.ndarray:
        """Run nnUNet v2 inference using Python API."""
        import gc
        from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor

        # Set environment variables BEFORE importing torch
        os.environ["nnUNet_results"] = self.MODEL_DIR
        os.environ["nnUNet_raw"] = self.MODEL_DIR
        os.environ["nnUNet_preprocessed"] = os.path.join(self.MODEL_DIR, "nnUNet_preprocessed")
        os.environ["nnUNet_n_proc_DA"] = "0"
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["MKL_NUM_THREADS"] = "1"

        # Select a concrete torch device without mutating process-global
        # CUDA_VISIBLE_DEVICES. OAR segmentation binds only its own subprocess;
        # changing the parent environment here could redirect a concurrent OAR
        # worker or another Session to the wrong GPU.
        from plans.device_manager import DeviceManager
        _dm = DeviceManager.instance()
        _chosen_gpu = "cuda:0"
        _n_gpus = 0
        _gpu_session = None
        if _dm.cuda_available():
            _n_gpus = _dm.device_count()
            # nnUNetPredictor owns one torch device. The legacy all-GPU option
            # therefore retains its established cuda:0 behavior without
            # changing visibility for the rest of the server process.
            if os.environ.get("NNUNET_USE_ALL_GPUS", "").lower() in ("1", "true", "yes"):
                _gpu_session = _dm.acquire_session(
                    caller=self.__class__.__name__, prefer="0"
                )
            else:
                _gpu_session = _dm.acquire_session(caller=self.__class__.__name__)
            _chosen_gpu = _gpu_session.__enter__().device_str

        import torch

        # Create device object
        if _n_gpus > 0:
            device = torch.device(_chosen_gpu)
            logger.info(f"nnUNet using {_chosen_gpu} (managed by DeviceManager); "
                        f"{_n_gpus} total GPU(s) visible: {_dm.device_names()}")
        else:
            device = torch.device("cpu")
            logger.info("No GPU available, using CPU")

        predictor = None
        try:
            predictor = nnUNetPredictor(
                tile_step_size=0.5,
                use_gaussian=True,
                use_mirroring=not fast_mode,
                device=device,
                verbose=False,
                verbose_preprocessing=False,
                allow_tqdm=False,
            )

            logger.info("Initializing nnUNet predictor...")
            predictor.initialize_from_trained_model_folder(config_dir, use_folds=(0,))

            # Get image array: (D, H, W) -> (1, D, H, W)
            arr = sitk.GetArrayFromImage(image).astype(np.float32)
            arr = arr[np.newaxis]  # Add channel dimension

            # Create properties dict
            properties = {
                "spacing": image.GetSpacing()[::-1],  # z, y, x
                # Origin and direction remain physical metadata in x/y/z
                # coordinates. Reversing the flat 3x3 direction matrix would
                # corrupt rotated acquisitions.
                "origin": image.GetOrigin(),
                "direction": image.GetDirection(),
            }

            logger.info(f"Running nnUNet inference on shape {arr.shape}...")
            result = predictor.predict_single_npy_array(arr, properties, None, None, False)
            result_array = self._coerce_prediction_array(result)

            logger.info(
                "nnUNet output shape: %s, unique values: %s",
                result_array.shape,
                np.unique(result_array),
            )
            return result_array
        finally:
            # Free GPU memory and release the standard DeviceManager lease.
            del predictor
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("GPU memory freed")
            if _gpu_session is not None:
                _gpu_session.__exit__(None, None, None)
                logger.info(f"Released GPU lease for {_chosen_gpu}")
