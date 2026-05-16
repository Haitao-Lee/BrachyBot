"""
TotalSegmentator OAR Segmentation Tool
====================================
Segments all Organs At Risk (OAR) from CT images using TotalSegmentator.
"""

import sys
import os
import logging
import tempfile
import shutil
import subprocess
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
import SimpleITK as sitk
import nibabel as nib
from typing import Dict


logger = logging.getLogger(__name__)


TOTALSEG_LABEL_MAPPING = {
    1: "body",
    2: "kidney_right",
    3: "kidney_left",
    4: "liver",
    5: "pancreas",
    6: "spleen",
    7: "stomach",
    8: "adrenal_gland_right",
    9: "adrenal_gland_left",
    10: "aorta",
    11: "posterior_vena_cava",
    12: "portal_vein",
    13: "small_bowel",
    14: "urinary_bladder",
    15: "femur_left",
    16: "femur_right",
    17: "hip_left",
    18: "hip_right",
    19: "spinal_cord",
    20: "gluteus_maximus_left",
    21: "gluteus_maximus_right",
    22: "gluteus_medius_left",
    23: "gluteus_medius_right",
    24: "gluteus_minimus_left",
    25: "gluteus_minimus_right",
    26: "colon",
    27: "duodenum",
    28: "intestine",
    29: "rectum",
    30: "brain",
    31: "heart",
    32: "trachea",
    33: "lung_left",
    34: "lung_right",
    35: "pleura",
    36: "prostate",
    37: "thyroid_gland",
    38: "scapula_left",
    39: "scapula_right",
    40: "clavicula_left",
    41: "clavicula_right",
    42: "humerus_left",
    43: "humerus_right",
    44: "sternum",
    45: "rib",
    46: "sacrum",
    47: "costal_cartilage",
    48: "skin",
}


class TotalSegmentatorOARTool(BaseTool):
    """
    Tool for segmenting all Organs At Risk (OAR) from CT images using TotalSegmentator.

    Uses TotalSegmentator's 'total' task to generate comprehensive multi-organ segmentation.
    Returns a multi-label mask where each label represents a different organ.
    Dose constraints can be optionally provided for each organ.
    """

    @property
    def name(self) -> str:
        return "totalsegmentator_oar"

    @property
    def description(self) -> str:
        return (
            "Segment all Organs At Risk (OAR) from CT images using TotalSegmentator. "
            "Returns a multi-label mask where different integer values represent different organs. "
            "Supports 40+ anatomical structures including liver, kidneys, pancreas, heart, lungs, etc. "
            "Optional dose constraints can be provided for each organ label."
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
                "organ_filter": {
                    "type": "array",
                    "description": "List of organ names to include (default: all organs). E.g. ['liver', 'kidney_right', 'pancreas']",
                    "items": {"type": "string"},
                },
                "dose_constraints": {
                    "type": "object",
                    "description": "Dose constraints per organ name, e.g. {'liver': 30.0, 'kidney_right': 20.0} in Gy",
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
                "oar_mask": {
                    "type": "object",
                    "description": "SimpleITK Image of the OAR multi-label mask",
                },
                "oar_array": {
                    "type": "object",
                    "description": "NumPy array of the OAR mask",
                },
                "organ_volumes": {
                    "type": "object",
                    "description": "Dictionary mapping organ name -> volume in mm³",
                },
                "organ_counts": {
                    "type": "object",
                    "description": "Dictionary mapping organ name -> voxel count",
                },
                "dose_constraints": {
                    "type": "object",
                    "description": "Dose constraints per organ name in Gy",
                },
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        organ_filter = kwargs.get("organ_filter")
        dose_constraints = kwargs.get("dose_constraints", {})
        fast_mode = kwargs.get("fast_mode", False)

        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            raise ValueError("Either 'image' or 'image_path' must be provided")

        try:
            oar_array, method = self._totalsegmentator_segmentation(image, organ_filter, fast_mode)
        except Exception as e:
            logger.warning(f"TotalSegmentator failed: {e}, returning empty OAR mask")
            oar_array = np.zeros(sitk.GetArrayFromImage(image).shape, dtype=np.float64)
            method = "empty_mask"

        spacing = image.GetSpacing()
        voxel_volume_mm3 = float(spacing[0] * spacing[1] * spacing[2])

        unique_labels = np.unique(oar_array[oar_array > 0])
        organ_volumes = {}
        organ_counts = {}

        for label in unique_labels:
            label_int = int(label)
            organ_name = TOTALSEG_LABEL_MAPPING.get(label_int, f"label_{label_int}")
            count = int(np.sum(oar_array == label_int))
            organ_counts[organ_name] = count
            organ_volumes[organ_name] = count * voxel_volume_mm3

        oar_mask = sitk.GetImageFromArray(oar_array)
        oar_mask.CopyInformation(image)

        num_organs = len(organ_volumes)
        return ToolResult(
            success=True,
            data=oar_mask,
            message=f"OAR segmentation completed using {method}. Found {num_organs} organ(s).",
            metadata={
                "oar_mask": oar_mask,
                "oar_array": oar_array,
                "organ_volumes": organ_volumes,
                "organ_counts": organ_counts,
                "dose_constraints": dose_constraints,
                "method": method,
            },
        )

    def _totalsegmentator_segmentation(
        self, image: sitk.Image, organ_filter: list, fast_mode: bool
    ):
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
                "--task", "total",
                "--device", device_str,
            ]
            if fast_mode:
                cmd.append("--fast")

            logger.info(f"Running TotalSegmentator OAR: {' '.join(cmd)}")

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

            result_file = os.path.join(output_dir, "segmentations.nii.gz")
            if not os.path.exists(result_file):
                raise RuntimeError(f"TotalSegmentator output not found: {result_file}")

            seg_img = nib.load(result_file)
            seg_data = seg_img.get_fdata()

            oar_array = np.zeros_like(seg_data, dtype=np.float64)

            if organ_filter is not None:
                organ_filter_lower = [o.lower() for o in organ_filter]
                for label_int, organ_name in TOTALSEG_LABEL_MAPPING.items():
                    if organ_name.lower() in organ_filter_lower:
                        oar_array[seg_data == label_int] = label_int
            else:
                oar_array[seg_data > 0] = seg_data[seg_data > 0]

            return oar_array, "totalsegmentator"

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _get_clean_subprocess_env(self) -> dict:
        env = os.environ.copy()
        for var in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE"):
            env.pop(var, None)
        return env
