"""
Pancreatic OAR Segmentation Tool
==============================
Segments surrounding Organs At Risk (OAR) near the pancreas using nnU-Net.
Returns pancreas, arteries, and veins as OAR structures (excluding the tumor).
"""

import sys
import os
import logging
import tempfile
import shutil
import subprocess
import signal
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
import SimpleITK as sitk
from typing import Dict


logger = logging.getLogger(__name__)


PANCREATIC_NNUNET_LABELS = {
    1: ("pancreatic_tumor", False),
    2: ("artery", True),
    3: ("vein", True),
    4: ("pancreas", True),
    5: ("unknown_5", False),
    6: ("unknown_6", False),
}


class PancreaticOARTool(BaseTool):
    """
    Tool for segmenting pancreatic Organs At Risk (OAR) using nnU-Net.

    The nnU-Net pancreatic model produces multiple labels:
    - Label 1: Pancreatic Tumor (CTV, excluded from OAR)
    - Label 2: Artery (OAR)
    - Label 3: Vein (OAR)
    - Label 4: Pancreas (OAR - the organ itself)
    - Label 5, 6: Unknown structures (excluded)

    This tool returns labels 2, 3, 4 as OAR structures.
    """

    @property
    def name(self) -> str:
        return "pancreatic_oar"

    @property
    def description(self) -> str:
        return (
            "Segment pancreatic Organs At Risk (OAR) using nnU-Net. "
            "Returns surrounding tissues (artery, vein, pancreas) as OAR structures, excluding tumor. "
            "The output multi-label mask contains: artery (label 2), vein (label 3), pancreas (label 4). "
            "Requires pre-trained nnU-Net model in plans/seg/pancreatic_tumor/."
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
                "dose_constraints": {
                    "type": "object",
                    "description": "Dose constraints per OAR name, e.g. {'artery': 120.0, 'vein': 120.0, 'pancreas': 50.0} in Gy",
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
        dose_constraints = kwargs.get("dose_constraints", {})
        fast_mode = kwargs.get("fast_mode", False)

        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            raise ValueError("Either 'image' or 'image_path' must be provided")

        try:
            oar_array = self._nnunet_pancreatic_oar(image, fast_mode)
            method = "nnunet"
        except Exception as e:
            logger.warning(f"nnU-Net pancreatic OAR failed: {e}, returning empty OAR mask")
            oar_array = np.zeros(sitk.GetArrayFromImage(image).shape, dtype=np.float64)
            method = "empty_mask"

        spacing = image.GetSpacing()
        voxel_volume_mm3 = float(spacing[0] * spacing[1] * spacing[2])

        unique_labels = np.unique(oar_array[oar_array > 0])
        organ_volumes = {}
        organ_counts = {}

        for label in unique_labels:
            label_int = int(label)
            if label_int in PANCREATIC_NNUNET_LABELS:
                organ_name, is_oar = PANCREATIC_NNUNET_LABELS[label_int]
                if is_oar:
                    count = int(np.sum(oar_array == label_int))
                    organ_counts[organ_name] = count
                    organ_volumes[organ_name] = count * voxel_volume_mm3

        oar_mask = sitk.GetImageFromArray(oar_array)
        oar_mask.CopyInformation(image)

        num_organs = len(organ_volumes)
        # Keep the numeric label ontology with the result so the unified
        # wrapper can expose model names without guessing from label IDs.
        organ_names = {
            label_id: PANCREATIC_NNUNET_LABELS[label_id][0]
            for label_id in organ_counts
            if label_id in PANCREATIC_NNUNET_LABELS
        }
        return ToolResult(
            success=True,
            data=oar_mask,
            message=f"Pancreatic OAR segmentation completed using {method}. Found {num_organs} OAR(s).",
            metadata={
                "oar_mask": oar_mask,
                "oar_array": oar_array,
                "organ_volumes": organ_volumes,
                "organ_counts": organ_counts,
                "organ_names": organ_names,
                "dose_constraints": dose_constraints,
                "method": method,
                "oar_source": "nnunet_pancreatic",
                "oar_is_full": False,
            },
        )

    def _nnunet_pancreatic_oar(self, image: sitk.Image, fast_mode: bool):
        module_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        base_results_dir = os.path.join(module_dir, "plans", "seg", "pancreatic_tumor")

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

            from plans.device_manager import get_device as _get_device

            device_str = str(_get_device(caller=__name__))
            cmd.extend(["-device", device_str])

            logger.info(f"Running nnU-Net pancreatic OAR: {' '.join(cmd)}")

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
                start_new_session=(os.name == "posix"),
            )

            timeout_s = int(os.getenv("BRACHYBOT_NNUNET_TIMEOUT_SEC", "300"))
            try:
                output, _ = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.kill()
                try:
                    output, _ = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    output, _ = proc.communicate()
                raise RuntimeError(f"nnU-Net timed out after {timeout_s}s")

            output_lines = deque(maxlen=80)
            for line in (output or "").splitlines():
                stripped = line.strip()
                if stripped:
                    output_lines.append(stripped)
                    logger.debug(stripped)

            if proc.returncode != 0:
                tail = "\n".join(output_lines)
                raise RuntimeError(f"nnU-Net failed with return code {proc.returncode}. Last output: {tail}")

            output_files = [f for f in os.listdir(output_folder) if f.endswith(".nii.gz")]
            if not output_files:
                raise RuntimeError("nnU-Net produced no output files")

            output_nifti_path = os.path.join(output_folder, output_files[0])
            output_sitk = sitk.ReadImage(output_nifti_path)

            output_array = sitk.GetArrayFromImage(output_sitk)

            oar_array = np.zeros_like(output_array, dtype=np.float64)
            for label_int, (organ_name, is_oar) in PANCREATIC_NNUNET_LABELS.items():
                if is_oar:
                    oar_array[output_array == label_int] = label_int

            return oar_array

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
        for var in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "PYTHONHOME", "LD_LIBRARY_PATH"):
            env.pop(var, None)
        return env
