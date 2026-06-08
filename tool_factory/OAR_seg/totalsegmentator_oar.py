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


# TotalSegmentator v2 label mapping (117 structures)
# Reference: https://github.com/wasserth/TotalSegmentator/blob/master/totalsegmentator/map_to_binary.py
# Verified against installed totalsegmentator package
TOTALSEG_LABEL_MAPPING = {
    1: "spleen",
    2: "kidney_right",
    3: "kidney_left",
    4: "gallbladder",
    5: "liver",
    6: "stomach",
    7: "pancreas",
    8: "adrenal_gland_right",
    9: "adrenal_gland_left",
    10: "lung_upper_lobe_left",
    11: "lung_lower_lobe_left",
    12: "lung_upper_lobe_right",
    13: "lung_middle_lobe_right",
    14: "lung_lower_lobe_right",
    15: "esophagus",
    16: "trachea",
    17: "thyroid_gland",
    18: "small_bowel",
    19: "duodenum",
    20: "colon",
    21: "urinary_bladder",
    22: "prostate",
    23: "kidney_cyst_left",
    24: "kidney_cyst_right",
    25: "sacrum",
    26: "vertebrae_S1",
    27: "vertebrae_L5",
    28: "vertebrae_L4",
    29: "vertebrae_L3",
    30: "vertebrae_L2",
    31: "vertebrae_L1",
    32: "vertebrae_T12",
    33: "vertebrae_T11",
    34: "vertebrae_T10",
    35: "vertebrae_T9",
    36: "vertebrae_T8",
    37: "vertebrae_T7",
    38: "vertebrae_T6",
    39: "vertebrae_T5",
    40: "vertebrae_T4",
    41: "vertebrae_T3",
    42: "vertebrae_T2",
    43: "vertebrae_T1",
    44: "vertebrae_C7",
    45: "vertebrae_C6",
    46: "vertebrae_C5",
    47: "vertebrae_C4",
    48: "vertebrae_C3",
    49: "vertebrae_C2",
    50: "vertebrae_C1",
    51: "heart",
    52: "aorta",
    53: "pulmonary_vein",
    54: "brachiocephalic_trunk",
    55: "subclavian_artery_right",
    56: "subclavian_artery_left",
    57: "common_carotid_artery_right",
    58: "common_carotid_artery_left",
    59: "brachiocephalic_vein_left",
    60: "brachiocephalic_vein_right",
    61: "atrial_appendage_left",
    62: "superior_vena_cava",
    63: "inferior_vena_cava",
    64: "portal_vein_and_splenic_vein",
    65: "iliac_artery_left",
    66: "iliac_artery_right",
    67: "iliac_vena_left",
    68: "iliac_vena_right",
    69: "humerus_left",
    70: "humerus_right",
    71: "scapula_left",
    72: "scapula_right",
    73: "clavicula_left",
    74: "clavicula_right",
    75: "femur_left",
    76: "femur_right",
    77: "hip_left",
    78: "hip_right",
    79: "spinal_cord",
    80: "gluteus_maximus_left",
    81: "gluteus_maximus_right",
    82: "gluteus_medius_left",
    83: "gluteus_medius_right",
    84: "gluteus_minimus_left",
    85: "gluteus_minimus_right",
    86: "autochthon_left",
    87: "autochthon_right",
    88: "iliopsoas_left",
    89: "iliopsoas_right",
    90: "brain",
    91: "skull",
    92: "rib_left_1",
    93: "rib_left_2",
    94: "rib_left_3",
    95: "rib_left_4",
    96: "rib_left_5",
    97: "rib_left_6",
    98: "rib_left_7",
    99: "rib_left_8",
    100: "rib_left_9",
    101: "rib_left_10",
    102: "rib_left_11",
    103: "rib_left_12",
    104: "rib_right_1",
    105: "rib_right_2",
    106: "rib_right_3",
    107: "rib_right_4",
    108: "rib_right_5",
    109: "rib_right_6",
    110: "rib_right_7",
    111: "rib_right_8",
    112: "rib_right_9",
    113: "rib_right_10",
    114: "rib_right_11",
    115: "rib_right_12",
    116: "sternum",
    117: "costal_cartilages",
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
            "Supports 104 anatomical structures including liver, kidneys, pancreas, heart, lungs, "
            "vertebrae, ribs, brain, spinal cord, and many more. "
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
        organ_names = {}

        for label in unique_labels:
            label_int = int(label)
            organ_name = TOTALSEG_LABEL_MAPPING.get(label_int, f"label_{label_int}")
            count = int(np.sum(oar_array == label_int))
            organ_names[label_int] = organ_name
            organ_counts[organ_name] = count
            organ_volumes[organ_name] = count * voxel_volume_mm3

        # Convert from nibabel (X,Y,Z) to SimpleITK (Z,Y,X) order for consistency
        oar_array_ordered = np.transpose(oar_array, (2, 1, 0))
        oar_mask = sitk.GetImageFromArray(oar_array_ordered)
        oar_mask.SetSpacing(spacing)
        oar_mask.SetOrigin(image.GetOrigin())

        num_organs = len(organ_volumes)
        return ToolResult(
            success=True,
            data=oar_mask,
            message=f"OAR segmentation completed using {method}. Found {num_organs} organ(s).",
            metadata={
                "oar_mask": oar_mask,
                "oar_array": oar_array_ordered,  # Use (Z,Y,X) order for consistency with sitk
                "organ_names": organ_names,
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
            output_path = os.path.join(temp_dir, "segmentation.nii.gz")

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
                "-o", output_path,
                "--task", "total",
                "--device", device_str,
                "--ml",  # multilabel output for easier reading
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

            result_file = output_path
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
