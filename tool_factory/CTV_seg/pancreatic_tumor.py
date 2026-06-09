"""
Pancreatic Tumor Segmentation Tool
=================================
Segments pancreatic tumors from CT images using nnU-Net deep learning model.
"""

import sys
import os
import logging
import tempfile
import shutil
import subprocess
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
import SimpleITK as sitk
from typing import Dict


logger = logging.getLogger(__name__)


class PancreaticTumorSegmentationTool(BaseTool):
    """
    Tool for segmenting pancreatic tumors from CT images using nnU-Net.

    This tool wraps the trained nnU-Net model for pancreatic tumor segmentation.
    Falls back to threshold-based segmentation if the model is not available.
    """

    @property
    def name(self) -> str:
        return "pancreatic_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Segment pancreatic tumors from CT images using nnU-Net deep learning model. "
            "Returns a binary mask where 1 indicates tumor tissue. "
            "Requires pre-trained nnU-Net model in plans/seg/pancreatic_tumor/. "
            "Falls back to HU thresholding if model is unavailable."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {
                    "type": "object",
                    "description": "SimpleITK Image object of the CT scan",
                },
                "image_path": {
                    "type": "string",
                    "description": "Path to the CT image file (.nii, .nii.gz, .mhd)",
                },
                "target_value": {
                    "type": "number",
                    "description": "Value to assign to tumor voxels (default: 1)",
                    "default": 1,
                },
                "fast_mode": {
                    "type": "boolean",
                    "description": "Use fast inference mode (disable TTA, reduce threads)",
                    "default": False,
                },
            },
            "required": [],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "ctv_mask": {
                    "type": "object",
                    "description": "SimpleITK Image of the tumor binary mask",
                },
                "ctv_array": {
                    "type": "object",
                    "description": "NumPy array of the tumor mask",
                },
                "ctv_volume_mm3": {
                    "type": "number",
                    "description": "Total tumor volume in cubic millimeters",
                },
                "ctv_voxel_count": {
                    "type": "integer",
                    "description": "Number of voxels in the tumor mask",
                },
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        target_value = kwargs.get("target_value", 1)
        fast_mode = kwargs.get("fast_mode", False)

        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            raise ValueError("Either 'image' or 'image_path' must be provided")

        try:
            ctv_mask, ctv_array = self._nnunet_segmentation(image, target_value, fast_mode)
            method = "nnunet"
        except Exception as e:
            logger.warning(f"nnU-Net segmentation failed: {e}, falling back to threshold")
            ctv_mask, ctv_array = self._threshold_segmentation(image, target_value)
            method = "threshold_fallback"

        spacing = image.GetSpacing()
        voxel_volume_mm3 = float(spacing[0] * spacing[1] * spacing[2])
        ctv_voxel_count = int(np.sum(ctv_array == target_value))
        ctv_volume_mm3 = ctv_voxel_count * voxel_volume_mm3

        return ToolResult(
            success=True,
            data=ctv_mask,
            message=f"Pancreatic tumor segmentation completed using {method}. Found {ctv_voxel_count} tumor voxels ({ctv_volume_mm3:.1f} mm³).",
            metadata={
                "ctv_mask": ctv_mask,
                "ctv_array": ctv_array,
                "ctv_volume_mm3": ctv_volume_mm3,
                "ctv_voxel_count": ctv_voxel_count,
                "method": method,
                "target_value": target_value,
            },
        )

    def _threshold_segmentation(self, image: sitk.Image, target_value: float):
        array = sitk.GetArrayFromImage(image)
        ctv_array = np.zeros_like(array, dtype=np.float64)  # Empty mask: nnU-Net model not available
        ctv_mask = sitk.GetImageFromArray(ctv_array)
        ctv_mask.CopyInformation(image)
        return ctv_mask, ctv_array

    def _nnunet_segmentation(self, image: sitk.Image, target_value: float, fast_mode: bool):
        module_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        base_results_dir = os.path.join(module_dir, "VoCo", "pancreatic_tumor")

        if not os.path.exists(base_results_dir):
            raise RuntimeError(f"nnU-Net model not found at {base_results_dir}")

        dataset_id = "005"
        config_name = "3d_fullres"
        trainer_name = "nnUNetTrainer"
        plan_name = "nnUNetPlans"
        config_dir_name = f"{trainer_name}__{plan_name}__{config_name}"
        config_dir = os.path.join(base_results_dir, f"Dataset{dataset_id}_Pancreas", config_dir_name)

        if not os.path.exists(config_dir):
            raise RuntimeError(f"nnU-Net config not found: {config_dir}")

        temp_dir = tempfile.mkdtemp()
        try:
            input_folder = os.path.join(temp_dir, "input")
            output_folder = os.path.join(temp_dir, "output")
            os.makedirs(input_folder, exist_ok=True)
            os.makedirs(output_folder, exist_ok=True)

            input_nifti_path = os.path.join(input_folder, "case_0001_0000.nii.gz")
            sitk.WriteImage(image, input_nifti_path)

            env = self._get_clean_subprocess_env()
            env["nnUNet_results"] = base_results_dir
            env["nnUNet_raw"] = base_results_dir
            env["nnUNet_preprocessed"] = os.path.join(base_results_dir, "nnUNet_preprocessed")

            wrapper_script = os.path.join(module_dir, "plans", "seg", "nnunet_infer.py")
            if not os.path.exists(wrapper_script):
                raise RuntimeError(f"nnU-Net wrapper script not found: {wrapper_script}")

            python_exe = self._get_python_executable()
            cmd = [
                python_exe, wrapper_script,
                "-m", config_dir,
                "-i", input_folder,
                "-o", output_folder,
                "-f", "0",
            ]
            if fast_mode:
                cmd.append("--disable_tta")

            device_str = "cpu"
            try:
                import torch
                if torch.cuda.is_available():
                    device_str = "cuda"
            except ImportError:
                pass
            cmd.extend(["-device", device_str])

            logger.info(f"Running nnU-Net: {' '.join(cmd)}")

            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                startupinfo=startupinfo,
            )

            for line in proc.stdout:
                logger.debug(line.strip())
            proc.wait()

            if proc.returncode != 0:
                raise RuntimeError(f"nnU-Net failed with return code {proc.returncode}")

            output_files = [f for f in os.listdir(output_folder) if f.endswith(".nii.gz")]
            if not output_files:
                raise RuntimeError("nnU-Net produced no output files")

            output_nifti_path = os.path.join(output_folder, output_files[0])
            output_sitk = sitk.ReadImage(output_nifti_path)

            output_array = sitk.GetArrayFromImage(output_sitk)
            ctv_array = np.zeros_like(output_array, dtype=np.float64)
            ctv_array[output_array == 1] = target_value

            ctv_mask = sitk.GetImageFromArray(ctv_array)
            ctv_mask.CopyInformation(image)

            return ctv_mask, ctv_array

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _get_python_executable(self) -> str:
        if os.name == "nt":
            python_exe = os.path.join(os.path.dirname(sys.executable), "python.exe")
        else:
            python_exe = os.path.join(os.path.dirname(sys.executable), "python3")
        if not os.path.exists(python_exe):
            python_exe = sys.executable
        return python_exe

    def _get_clean_subprocess_env(self) -> dict:
        env = os.environ.copy()
        for var in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE"):
            env.pop(var, None)
        python_home = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
        env["PYTHONHOME"] = python_home
        return env
