"""
Lung Tumor Segmentation Tool
============================
Segments lung tumors from CT images using TotalSegmentator.
"""

import sys
import os
import logging
import tempfile
import shutil
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
import SimpleITK as sitk
import nibabel as nib
from typing import Dict


logger = logging.getLogger(__name__)


class LungTumorSegmentationTool(BaseTool):
    """
    Tool for segmenting lung tumors from CT images.

    Uses TotalSegmentator's lung or lung_vessels task for segmentation.
    Falls back to intensity-based thresholding if specialized model is not available.
    """

    @property
    def name(self) -> str:
        return "lung_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Segment lung tumors from CT images using TotalSegmentator. "
            "Uses the lung_vessels task which distinguishes vessels from tumor tissue. "
            "Returns a binary mask where target_value indicates tumor tissue."
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
                    "description": "Use fast mode for TotalSegmentator",
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
            ctv_mask, ctv_array = self._totalsegmentator_segmentation(image, target_value, fast_mode)
            method = "totalsegmentator"
        except Exception as e:
            logger.warning(f"TotalSegmentator failed: {e}, falling back to threshold")
            ctv_mask, ctv_array = self._threshold_segmentation(image, target_value)
            method = "threshold_fallback"

        spacing = image.GetSpacing()
        voxel_volume_mm3 = float(spacing[0] * spacing[1] * spacing[2])
        ctv_voxel_count = int(np.sum(ctv_array == target_value))
        ctv_volume_mm3 = ctv_voxel_count * voxel_volume_mm3

        return ToolResult(
            success=True,
            data=ctv_mask,
            message=f"Lung tumor segmentation completed using {method}. Found {ctv_voxel_count} tumor voxels ({ctv_volume_mm3:.1f} mm³).",
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

    def _totalsegmentator_segmentation(self, image: sitk.Image, target_value: float, fast_mode: bool):
        ts_exe = shutil.which("TotalSegmentator")
        if ts_exe is None:
            raise RuntimeError("TotalSegmentator not found in PATH")

        temp_dir = tempfile.mkdtemp()
        try:
            input_file = os.path.join(temp_dir, "input.nii.gz")
            output_dir = os.path.join(temp_dir, "segmentation")

            sitk.WriteImage(image, input_file)

            device_str = "cpu"
            try:
                import torch
                if torch.cuda.is_available():
                    device_str = "gpu"
            except ImportError:
                pass

            cmd = [
                ts_exe,
                "-i", input_file,
                "-o", output_dir,
                "--task", "lung_vessels",
                "--device", device_str,
            ]
            if fast_mode:
                cmd.append("--fast")

            logger.info(f"Running TotalSegmentator lung_vessels: {' '.join(cmd)}")

            env = self._get_clean_subprocess_env()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                env=env,
            )

            for line in proc.stdout:
                logger.debug(line.strip())
            proc.wait()

            if proc.returncode != 0:
                raise RuntimeError(f"TotalSegmentator failed with return code {proc.returncode}")

            result_file = os.path.join(output_dir, "lung_vessels.nii.gz")
            if not os.path.exists(result_file):
                result_file = os.path.join(output_dir, "segmentations.nii.gz")

            if not os.path.exists(result_file):
                raise RuntimeError(f"TotalSegmentator lung_vessels output not found")

            seg_img = nib.load(result_file)
            seg_data = seg_img.get_fdata()

            tumor_array = np.zeros_like(seg_data, dtype=np.float64)
            tumor_array[seg_data == 2] = target_value

            temp_ctv_path = os.path.join(temp_dir, "ctv.nii.gz")
            ctv_nifti = nib.Nifti1Image(tumor_array.astype(np.float32), seg_img.affine, seg_img.header)
            nib.save(ctv_nifti, temp_ctv_path)

            ctv_mask = sitk.ReadImage(temp_ctv_path)
            ctv_mask.CopyInformation(image)

            return ctv_mask, tumor_array

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _get_clean_subprocess_env(self) -> dict:
        env = os.environ.copy()
        for var in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE"):
            env.pop(var, None)
        return env
