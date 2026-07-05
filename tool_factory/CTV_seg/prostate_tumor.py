"""
Prostate target segmentation tool.

This tool may return a whole-prostate target volume for prostate brachytherapy
workflows. It is not a lesion-level prostate tumor segmentation model.
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
from typing import Dict


logger = logging.getLogger(__name__)


class ProstateTumorSegmentationTool(BaseTool):
    """
    Tool for segmenting a whole-prostate target from medical images.

    Uses TotalSegmentator's prostate task when available. The resulting mask is
    a gland/target mask, not an intraprostatic lesion segmentation.
    """

    @property
    def name(self) -> str:
        return "prostate_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Segment the whole-prostate target from CT/MRI images when a "
            "prostate-gland CTV is clinically intended. This is not a "
            "lesion-level prostate tumor segmentation model."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "image": {
                    "type": "object",
                    "description": "SimpleITK Image object of the CT/MRI scan",
                },
                "image_path": {
                    "type": "string",
                    "description": "Path to the image file (.nii, .nii.gz, .mhd)",
                },
                "target_value": {
                    "type": "number",
                    "description": "Value to assign to target voxels (default: 1)",
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
                    "description": "SimpleITK Image of the prostate target mask",
                },
                "ctv_array": {
                    "type": "object",
                    "description": "NumPy array of the prostate target mask",
                },
                "ctv_volume_mm3": {
                    "type": "number",
                    "description": "Total target volume in cubic millimeters",
                },
                "ctv_voxel_count": {
                    "type": "integer",
                    "description": "Number of voxels in the prostate target mask",
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
            logger.warning(f"TotalSegmentator prostate target segmentation failed: {e}")
            return ToolResult(
                success=False,
                error=(
                    "Prostate target segmentation requires a working TotalSegmentator prostate "
                    f"task or a user-provided label_path. Cause: {e}"
                ),
                metadata={
                    "target_semantics": "whole_prostate_target_not_lesion",
                    "site": "prostate",
                },
            )

        spacing = image.GetSpacing()
        voxel_volume_mm3 = float(spacing[0] * spacing[1] * spacing[2])
        ctv_voxel_count = int(np.sum(ctv_array == target_value))
        ctv_volume_mm3 = ctv_voxel_count * voxel_volume_mm3
        if ctv_voxel_count <= 0:
            return ToolResult(
                success=False,
                error="Prostate target segmentation returned an empty mask.",
                metadata={
                    "target_semantics": "whole_prostate_target_not_lesion",
                    "site": "prostate",
                    "method": method,
                },
            )

        return ToolResult(
            success=True,
            data=ctv_mask,
            message=f"Prostate target segmentation completed using {method}. Found {ctv_voxel_count} target voxels ({ctv_volume_mm3:.1f} mm3).",
            metadata={
                "ctv_mask": ctv_mask,
                "ctv_array": ctv_array,
                "ctv_volume_mm3": ctv_volume_mm3,
                "ctv_voxel_count": ctv_voxel_count,
                "method": method,
                "target_value": target_value,
                "target_semantics": "whole_prostate_target_not_lesion",
            },
        )

    def _totalsegmentator_segmentation(self, image: sitk.Image, target_value: float, fast_mode: bool):
        ts_exe = shutil.which("TotalSegmentator")
        if ts_exe is None:
            raise RuntimeError("TotalSegmentator not found in PATH")

        temp_dir = tempfile.mkdtemp()
        try:
            input_file = os.path.join(temp_dir, "input.nii.gz")
            output_dir = os.path.join(temp_dir, "segmentation")

            sitk.WriteImage(image, input_file)

            from plans.device_manager import get_device as _get_device


            # Totalsegmentator uses "gpu"/"cpu" strings; map our device


            _dev = str(_get_device(caller=__name__))


            device_str = "gpu" if _dev.startswith("cuda") else _dev

            cmd = [
                ts_exe,
                "-i", input_file,
                "-o", output_dir,
                "--task", "prostate",
                "--device", device_str,
            ]
            if fast_mode:
                cmd.append("--fast")

            logger.info(f"Running TotalSegmentator prostate: {' '.join(cmd)}")

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

            result_file = os.path.join(output_dir, "prostate.nii.gz")
            if not os.path.exists(result_file):
                result_file = os.path.join(output_dir, "segmentations.nii.gz")

            if not os.path.exists(result_file):
                raise RuntimeError(f"TotalSegmentator prostate output not found")

            import nibabel as nib
            seg_img = nib.load(result_file)
            seg_data = seg_img.get_fdata()

            tumor_array = np.zeros_like(seg_data, dtype=np.float64)
            tumor_array[seg_data > 0] = target_value

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
