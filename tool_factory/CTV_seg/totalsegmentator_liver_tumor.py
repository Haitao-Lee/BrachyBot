"""TotalSegmentator liver-tumor CTV segmentation.

This adapter deliberately exposes only the ``liver_tumor`` output from
TotalSegmentator's ``liver_vessels`` CT task.  The task also computes a liver
vessel mask internally, but that mask is discarded here so the CTV contract
cannot accidentally turn an anatomical structure into a treatment target.
"""

from __future__ import annotations

import logging
import os
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import SimpleITK as sitk

from tool_factory import BaseTool, ToolResult

from .totalsegmentator_runtime import find_totalsegmentator_executable


logger = logging.getLogger(__name__)


class TotalSegmentatorLiverTumorTool(BaseTool):
    """Run the real TotalSegmentator liver-vessels task and keep only tumor."""

    TASK = "liver_vessels"
    OUTPUT_LABEL = "liver_tumor"

    @property
    def name(self) -> str:
        return "totalsegmentator_liver_tumor"

    @property
    def description(self) -> str:
        return (
            "Segment liver tumor CTV from CT with TotalSegmentator's "
            "liver_vessels task. Only the liver_tumor output is exposed; "
            "liver and vessel outputs are discarded."
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
                    "description": "Path to the CT image (.nii or .nii.gz)",
                },
                "fast_mode": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Compatibility flag; the liver_vessels task does not "
                        "support TotalSegmentator fast mode and always uses its "
                        "native full-resolution inference."
                    ),
                },
                "target_value": {
                    "type": "number",
                    "default": 1,
                    "description": "Foreground value in the returned binary CTV mask",
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
        image = kwargs.get("image")
        image_path = kwargs.get("image_path")
        target_value = kwargs.get("target_value", 1)
        fast_mode = bool(kwargs.get("fast_mode", False))

        if image is None and image_path:
            try:
                image = sitk.ReadImage(str(image_path))
            except Exception as exc:
                return ToolResult(
                    success=False,
                    error=f"Unable to read the CT image for TotalSegmentator: {exc}",
                )
        if image is None:
            return ToolResult(
                success=False,
                error="Either 'image' or 'image_path' must be provided.",
            )

        try:
            tumor_array = self._run_totalsegmentator(
                image,
                fast_mode=fast_mode,
            )
        except Exception as exc:
            logger.exception("TotalSegmentator liver tumor segmentation failed")
            return ToolResult(
                success=False,
                error=f"TotalSegmentator liver tumor segmentation failed: {exc}",
                metadata={
                    "ctv_source": "totalsegmentator",
                    "tumor_type_used": self.name,
                    "total_segmentator_task": self.TASK,
                    "total_segmentator_label": self.OUTPUT_LABEL,
                },
            )

        mask_array = (np.asarray(tumor_array) > 0).astype(np.uint8)
        voxel_count = int(np.count_nonzero(mask_array))
        if voxel_count <= 0:
            return ToolResult(
                success=False,
                error=(
                    "TotalSegmentator completed the liver_vessels task but "
                    "did not find a liver_tumor label in this CT. This is an "
                    "empty result, not a BiomedParse fallback."
                ),
                metadata={
                    "ctv_source": "totalsegmentator",
                    "tumor_type_used": self.name,
                    "total_segmentator_task": self.TASK,
                    "total_segmentator_label": self.OUTPUT_LABEL,
                    "label_counts": {self.OUTPUT_LABEL: 0},
                },
            )

        ctv_mask = sitk.GetImageFromArray(
            (mask_array * int(target_value)).astype(np.uint8)
        )
        ctv_mask.CopyInformation(image)
        spacing = image.GetSpacing()
        volume_mm3 = float(voxel_count * spacing[0] * spacing[1] * spacing[2])

        return ToolResult(
            success=True,
            data=mask_array,
            message=(
                "TotalSegmentator liver tumor CTV completed "
                f"({volume_mm3:.1f} mm3)."
            ),
            metadata={
                "ctv_mask": ctv_mask,
                "ctv_array": mask_array,
                "ctv_volume_mm3": volume_mm3,
                "ctv_voxel_count": voxel_count,
                "tumor_type_used": self.name,
                "ctv_source": "totalsegmentator",
                "model_name": "TotalSegmentator liver_vessels",
                "repository": "https://github.com/wasserth/TotalSegmentator",
                "total_segmentator_task": self.TASK,
                "total_segmentator_label": self.OUTPUT_LABEL,
                "segmentation_task": self.TASK,
                "segmentation_label": self.OUTPUT_LABEL,
                "source_labels_exposed": [self.OUTPUT_LABEL],
                "label_counts": {self.OUTPUT_LABEL: voxel_count},
                "label_map": {1: self.OUTPUT_LABEL},
                "target_semantics": "liver_tumor_ctv_only",
            },
        )

    def _run_totalsegmentator(self, image: sitk.Image, *, fast_mode: bool) -> np.ndarray:
        """Run one bounded subprocess and restore the tumor mask to CT space."""
        ts_exe = find_totalsegmentator_executable()
        if ts_exe is None:
            raise RuntimeError(
                "TotalSegmentator is not installed or not on PATH. "
                f"Current Python: {sys.executable}. "
                "Install with: pip install totalsegmentator==2.13.0"
            )

        # OAR and liver-vessel inference share one GPU worker. Reusing the
        # existing lock prevents two TotalSegmentator jobs from exhausting
        # CUDA memory when the user starts a planning chain concurrently.
        from tool_factory.OAR_seg.totalsegmentator_oar import (
            _TOTALSEG_EXECUTION_LOCK,
            _align_segmentation_to_reference,
        )

        wait_timeout_s = int(os.getenv("BRACHYBOT_TOTALSEG_QUEUE_TIMEOUT_SEC", "900"))
        if not _TOTALSEG_EXECUTION_LOCK.acquire(timeout=max(1, wait_timeout_s)):
            raise RuntimeError(
                "TotalSegmentator liver tumor segmentation could not acquire "
                f"the GPU worker within {wait_timeout_s}s."
            )

        try:
            from plans.device_manager import device_session

            with device_session(caller=__name__) as lease:
                return self._run_locked(
                    image,
                    str(lease.device_str),
                    fast_mode=fast_mode,
                    executable=ts_exe,
                    align_segmentation_to_reference=_align_segmentation_to_reference,
                )
        finally:
            _TOTALSEG_EXECUTION_LOCK.release()

    def _run_locked(
        self,
        image: sitk.Image,
        managed_device: str,
        *,
        fast_mode: bool,
        executable: str,
        align_segmentation_to_reference,
    ) -> np.ndarray:
        temp_dir = Path(tempfile.mkdtemp(prefix="brachybot-ts-liver-"))
        proc: Optional[subprocess.Popen] = None
        try:
            input_path = temp_dir / "input.nii.gz"
            output_dir = temp_dir / "segmentations"
            output_dir.mkdir()
            sitk.WriteImage(image, str(input_path))

            env = self._get_clean_subprocess_env()
            if managed_device.startswith("cuda:"):
                env["CUDA_VISIBLE_DEVICES"] = managed_device.split(":", 1)[1]
                device_arg = "gpu"
            elif managed_device == "cuda":
                device_arg = "gpu"
            else:
                device_arg = "cpu"

            # Do not use --ml here. The individual-output form makes the
            # semantic boundary explicit: only liver_tumor.nii.gz is read;
            # liver and vessel files never enter the CTV result.
            command = [
                executable,
                "-i", str(input_path),
                "-o", str(output_dir),
                "--task", self.TASK,
                "--device", device_arg,
            ]
            # TotalSegmentator 2.13.0 explicitly rejects --fast for the
            # liver_vessels task. Keep the compatibility input accepted by the
            # shared CTV interface, but never turn it into an invalid command.
            if fast_mode:
                logger.info(
                    "Ignoring fast_mode for TotalSegmentator liver_vessels; "
                    "this task requires its native full-resolution path."
                )

            logger.info("Running TotalSegmentator liver tumor task: %s", " ".join(command))
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                start_new_session=(os.name == "posix"),
            )
            timeout_s = int(os.getenv("BRACHYBOT_TOTALSEG_TIMEOUT_SEC", "900"))
            try:
                output, _ = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self._terminate_subprocess_group(proc)
                try:
                    output, _ = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    output = ""
                raise RuntimeError(
                    f"TotalSegmentator timed out after {timeout_s}s. "
                    f"Last output: {self._tail_output(output, 8)}"
                )

            output_lines = self._tail_output(output, 40)
            for line in output_lines:
                logger.debug("[TotalSegmentator liver_vessels] %s", line)
            if proc.returncode != 0:
                tail = "\n".join(output_lines[-12:]) or "(no output)"
                raise RuntimeError(
                    f"TotalSegmentator exited with code {proc.returncode}.\n{tail}"
                )

            tumor_path = self._find_tumor_output(output_dir)
            if tumor_path is None:
                produced = sorted(str(path.name) for path in output_dir.glob("*.nii*"))
                raise RuntimeError(
                    "TotalSegmentator did not produce liver_tumor.nii.gz. "
                    f"Produced files: {produced or '(none)'}"
                )

            # TotalSegmentator writes canonical NIfTI files. The shared
            # nearest-neighbour alignment restores the original CT grid and
            # physical coordinates before the CTV wrapper converts to LPI.
            return align_segmentation_to_reference(str(tumor_path), image)
        finally:
            if proc is not None and proc.poll() is None:
                self._terminate_subprocess_group(proc)
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _find_tumor_output(output_dir: Path) -> Optional[Path]:
        candidates = (
            output_dir / "liver_tumor.nii.gz",
            output_dir / "liver_tumor.nii",
        )
        for candidate in candidates:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        for candidate in output_dir.rglob("*.nii*"):
            if candidate.stem.casefold().replace(".nii", "") == "liver_tumor":
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate
        return None

    @staticmethod
    def _tail_output(output: str, max_lines: int) -> list[str]:
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()][-max_lines:]

    @staticmethod
    def _get_clean_subprocess_env() -> dict:
        env = os.environ.copy()
        for var in (
            "PYTHONPATH",
            "PYTHONSTARTUP",
            "PYTHONEXECUTABLE",
            "PYTHONHOME",
            "LD_LIBRARY_PATH",
        ):
            env.pop(var, None)
        return env

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


__all__ = ["TotalSegmentatorLiverTumorTool"]
