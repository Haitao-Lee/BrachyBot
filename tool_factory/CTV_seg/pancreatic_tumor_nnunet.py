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
    1: ("tumor", True),
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
        except Exception as e:
            return ToolResult(success=False, error=f"nnUNet inference failed: {str(e)}")

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
            },
        )

    def _run_nnunet_inference(self, image: sitk.Image, config_dir: str, fast_mode: bool) -> np.ndarray:
        """Run nnUNet v2 inference using Python API."""
        import gc
        import torch
        from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor

        # Set environment variables
        os.environ["nnUNet_results"] = self.MODEL_DIR
        os.environ["nnUNet_raw"] = self.MODEL_DIR
        os.environ["nnUNet_preprocessed"] = os.path.join(self.MODEL_DIR, "nnUNet_preprocessed")
        os.environ["nnUNet_n_proc_DA"] = "0"
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["MKL_NUM_THREADS"] = "1"

        # Auto-detect device: use all available GPUs, fallback to CPU
        if torch.cuda.is_available():
            n_gpus = torch.cuda.device_count()
            device = torch.device("cuda")
            os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in range(n_gpus))
            logger.info(f"Using {n_gpus} GPU(s): {[torch.cuda.get_device_name(i) for i in range(n_gpus)]}")
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
                "origin": image.GetOrigin()[::-1],
                "direction": image.GetDirection()[::-1],
            }

            logger.info(f"Running nnUNet inference on shape {arr.shape}...")
            result = predictor.predict_single_npy_array(arr, properties, None, None, False)

            logger.info(f"nnUNet output shape: {result.shape}, unique values: {np.unique(result)}")
            return result.astype(np.uint8)
        finally:
            # Free GPU memory
            del predictor
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("GPU memory freed")
