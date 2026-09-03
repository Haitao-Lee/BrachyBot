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
import signal
import threading
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
import numpy as np
import SimpleITK as sitk
from typing import Dict, Iterable, List, Optional, Tuple


logger = logging.getLogger(__name__)

# TotalSegmentator launches its own worker processes and can consume most of a
# GPU. Running several copies concurrently on one workstation caused each copy
# to make little progress until all of them reached the five-minute timeout.
# Keep the expensive subprocess single-flight; unrelated UI, chat, viewer and
# session operations remain concurrent.
_TOTALSEG_EXECUTION_LOCK = threading.Lock()


def _align_segmentation_to_reference(segmentation_path: str, reference_image: sitk.Image) -> np.ndarray:
    """Return labels resampled into the exact input CT grid.

    TotalSegmentator writes NIfTI output with an affine/canonical orientation.
    A raw nibabel array transpose preserves values but can discard that affine
    relationship, leaving a plausible-looking yet spatially displaced mask.
    Nearest-neighbour resampling through SimpleITK preserves label IDs and
    returns the unambiguous (Z, Y, X) array used by the planner.
    """
    label_image = sitk.ReadImage(segmentation_path)
    aligned = sitk.Resample(
        label_image,
        reference_image,
        sitk.Transform(),
        sitk.sitkNearestNeighbor,
        0,
        sitk.sitkUInt16,
    )
    return sitk.GetArrayFromImage(aligned).astype(np.int32, copy=False)


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


def _normalise_organ_filter_token(value: object) -> str:
    """Return a stable token for an OAR name supplied by a user or an LLM."""
    return re.sub(r"[\s\-]+", "_", str(value or "").strip().lower())


def _build_totalseg_organ_filter_aliases() -> Dict[str, Tuple[str, ...]]:
    """Build the supported named-structure vocabulary from the label map.

    The canonical TotalSegmentator labels remain the source of truth.  The
    aliases merely let the conversational layer preserve a user's explicit
    Chinese/English anatomy scope without having to maintain a second label
    ontology.  Group aliases deliberately expand only to their documented
    canonical members (for example ``kidney`` -> left + right kidney).
    """
    known = set(TOTALSEG_LABEL_MAPPING.values())
    aliases: Dict[str, Tuple[str, ...]] = {}

    def add(targets: Iterable[str], *names: str) -> None:
        resolved = tuple(name for name in targets if name in known)
        if not resolved:
            return
        for name in names:
            token = _normalise_organ_filter_token(name)
            if token:
                aliases[token] = resolved

    # Every canonical TotalSegmentator name is accepted in both underscore
    # and space-separated form. This keeps future label-map additions usable
    # without changing the conversation router.
    for canonical in sorted(known):
        add((canonical,), canonical, canonical.replace("_", " "))

    lungs = tuple(name for name in known if name.startswith("lung_"))
    ribs = tuple(name for name in known if name.startswith("rib_"))
    vertebrae = tuple(name for name in known if name.startswith("vertebrae_"))
    kidneys = tuple(name for name in ("kidney_left", "kidney_right") if name in known)
    adrenal_glands = tuple(
        name for name in ("adrenal_gland_left", "adrenal_gland_right") if name in known
    )

    add(("liver",), "hepatic", "liver", "肝", "肝脏")
    add(("pancreas",), "pancreatic", "pancreas", "胰", "胰腺")
    add(kidneys, "kidney", "kidneys", "renal", "肾", "肾脏", "双肾")
    add(("kidney_left",), "left kidney", "left renal", "左肾", "左肾脏")
    add(("kidney_right",), "right kidney", "right renal", "右肾", "右肾脏")
    add(lungs, "lung", "lungs", "pulmonary", "肺", "肺脏", "双肺")
    add(
        tuple(name for name in lungs if name.endswith("_left")),
        "left lung", "左肺",
    )
    add(
        tuple(name for name in lungs if name.endswith("_right")),
        "right lung", "右肺",
    )
    add(("spleen",), "spleen", "脾", "脾脏")
    add(("stomach",), "stomach", "胃", "胃部")
    add(("gallbladder",), "gallbladder", "胆囊")
    add(("small_bowel",), "small bowel", "small intestine", "小肠")
    add(("duodenum",), "duodenum", "十二指肠")
    add(("colon",), "colon", "large bowel", "large intestine", "结肠", "大肠")
    add(("heart",), "heart", "cardiac", "心", "心脏")
    add(("aorta",), "aorta", "主动脉")
    add(("spinal_cord",), "spinal cord", "脊髓")
    add(("prostate",), "prostate", "前列腺")
    add(("urinary_bladder",), "urinary bladder", "bladder", "膀胱")
    add(("esophagus",), "esophagus", "oesophagus", "食管")
    add(("trachea",), "trachea", "气管")
    add(("thyroid_gland",), "thyroid", "thyroid gland", "甲状腺")
    add(("brain",), "brain", "脑", "大脑")
    add(("skull",), "skull", "颅骨")
    add(("inferior_vena_cava",), "inferior vena cava", "ivc", "下腔静脉")
    add(("superior_vena_cava",), "superior vena cava", "svc", "上腔静脉")
    add(
        ("portal_vein_and_splenic_vein",),
        "portal vein", "splenic vein", "portal and splenic vein", "门静脉", "脾静脉",
    )
    add(adrenal_glands, "adrenal", "adrenal gland", "肾上腺")
    add(("adrenal_gland_left",), "left adrenal", "left adrenal gland", "左肾上腺")
    add(("adrenal_gland_right",), "right adrenal", "right adrenal gland", "右肾上腺")
    add(vertebrae, "vertebra", "vertebrae", "spine", "脊椎", "椎体")
    add(ribs, "rib", "ribs", "肋骨")
    return aliases


TOTALSEG_ORGAN_FILTER_ALIASES = _build_totalseg_organ_filter_aliases()
TOTALSEG_SUPPORTED_ORGAN_NAMES = frozenset(TOTALSEG_LABEL_MAPPING.values())


def normalize_totalseg_organ_filter(organ_filter: object) -> Optional[List[str]]:
    """Resolve a requested OAR subset to canonical TotalSegmentator names.

    ``None`` means a full OAR result. An explicit but unknown value is an
    error instead of silently falling back to all organs; broadening a
    focused segmentation request is clinically and UX-wise unsafe.
    """
    if organ_filter is None:
        return None
    if isinstance(organ_filter, str):
        values = [part.strip() for part in organ_filter.split(",") if part.strip()]
    elif isinstance(organ_filter, (list, tuple, set, frozenset)):
        values = [str(value).strip() for value in organ_filter if str(value).strip()]
    else:
        raise ValueError("organ_filter must be a string or a list of organ names")
    if not values:
        raise ValueError("organ_filter must name at least one structure when provided")

    resolved: List[str] = []
    unknown: List[str] = []
    for value in values:
        token = _normalise_organ_filter_token(value)
        targets = TOTALSEG_ORGAN_FILTER_ALIASES.get(token)
        if not targets:
            unknown.append(value)
            continue
        for target in targets:
            if target not in resolved:
                resolved.append(target)
    if unknown:
        raise ValueError(
            "Unsupported TotalSegmentator organ_filter value(s): "
            + ", ".join(unknown)
        )
    return resolved


def extract_totalseg_organ_filter_from_text(text: object) -> List[str]:
    """Return named TotalSegmentator structures explicitly mentioned in text.

    This is an entity-resolution helper, not an action router: it never
    decides whether to run OAR segmentation. It is used only to prevent a
    chosen OAR tool call from persisting structures outside a named request.
    """
    raw_text = str(text or "").strip().lower()
    if not raw_text:
        return []
    compact = _normalise_organ_filter_token(raw_text)
    resolved: List[str] = []
    selected = set()
    generic_groups = {
        "kidney", "kidneys", "renal", "肾", "肾脏", "双肾",
        "lung", "lungs", "pulmonary", "肺", "肺脏", "双肺",
        "adrenal", "adrenal_gland", "肾上腺",
    }

    # Longer aliases win ("left kidney" before "kidney"). Re-check each
    # candidate against both source text and normalized text so Chinese and
    # punctuated English requests are handled consistently.
    for alias, targets in sorted(
        TOTALSEG_ORGAN_FILTER_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if alias.isascii() and any(char.isalpha() for char in alias):
            source_match = re.search(
                rf"(?<![a-z0-9]){re.escape(alias.replace('_', ' '))}(?![a-z0-9])",
                raw_text,
            )
            match = bool(source_match) or alias in compact
        else:
            match = alias in raw_text or alias in compact
        if not match:
            continue
        if alias in generic_groups and any(target in selected for target in targets):
            continue
        for target in targets:
            if target not in selected:
                selected.add(target)
                resolved.append(target)
    return resolved


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
        raw_organ_filter = kwargs.get("organ_filter")
        dose_constraints = kwargs.get("dose_constraints", {})
        fast_mode = kwargs.get("fast_mode", False)

        try:
            organ_filter = normalize_totalseg_organ_filter(raw_organ_filter)
        except ValueError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                message=f"OAR segmentation rejected: {exc}",
                metadata={
                    "oar_is_full": False,
                    "requested_organs": raw_organ_filter,
                    "oar_scope": "focused",
                },
            )

        if image is None and image_path is not None:
            image = sitk.ReadImage(image_path)
        elif image is None:
            raise ValueError("Either 'image' or 'image_path' must be provided")

        try:
            oar_array, method = self._totalsegmentator_segmentation(image, organ_filter, fast_mode)
        except Exception as e:
            logger.error(f"TotalSegmentator failed: {e}")
            return ToolResult(
                success=False,
                error=f"TotalSegmentator failed: {e}",
                message=f"OAR segmentation failed: {e}",
            )

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

        # _align_segmentation_to_reference already returns SimpleITK's array
        # order (Z, Y, X), so a second transpose would reintroduce a spatial
        # mismatch between the OAR labels and the CT used for planning.
        oar_array_ordered = oar_array
        oar_mask = sitk.GetImageFromArray(oar_array_ordered.astype(np.uint16))
        oar_mask.CopyInformation(image)

        num_organs = len(organ_volumes)
        is_full_oar = organ_filter is None
        scope = "full" if is_full_oar else "focused"
        return ToolResult(
            success=True,
            data=oar_mask,
            message=(
                f"OAR segmentation completed using {method}. Found {num_organs} organ(s)."
                if is_full_oar
                else (
                    f"Focused OAR segmentation completed using {method}. "
                    f"Retained {num_organs} requested organ(s): {', '.join(organ_filter)}."
                )
            ),
            metadata={
                "oar_mask": oar_mask,
                "oar_array": oar_array_ordered,  # Use (Z,Y,X) order for consistency with sitk
                "organ_names": organ_names,
                "organ_volumes": organ_volumes,
                "organ_counts": organ_counts,
                "dose_constraints": dose_constraints,
                "method": method,
                "oar_source": "totalsegmentator",
                "oar_is_full": is_full_oar,
                "oar_scope": scope,
                "requested_organs": list(organ_filter or []),
            },
        )

    def _totalsegmentator_segmentation(
        self, image: sitk.Image, organ_filter: list, fast_mode: bool
    ):
        wait_timeout_s = int(os.getenv("BRACHYBOT_TOTALSEG_QUEUE_TIMEOUT_SEC", "900"))
        acquired = _TOTALSEG_EXECUTION_LOCK.acquire(timeout=max(1, wait_timeout_s))
        if not acquired:
            raise RuntimeError(
                "OAR segmentation could not acquire the GPU worker before "
                f"the {wait_timeout_s}s queue timeout."
            )
        try:
            from plans.device_manager import device_session

            # Hold and release the lease for the complete subprocess lifetime.
            # The previous get_device() call leaked active lease counters.
            with device_session(caller=__name__) as lease:
                return self._totalsegmentator_segmentation_locked(
                    image,
                    organ_filter,
                    fast_mode,
                    str(lease.device_str),
                )
        finally:
            _TOTALSEG_EXECUTION_LOCK.release()

    def _totalsegmentator_segmentation_locked(
        self,
        image: sitk.Image,
        organ_filter: list,
        fast_mode: bool,
        managed_device: str,
    ):
        # --- Preflight: verify TotalSegmentator is available ---
        ts_exe = shutil.which("TotalSegmentator")
        if ts_exe is None:
            raise RuntimeError(
                "TotalSegmentator not found in PATH. "
                f"Current Python: {sys.executable}. "
                "Install with: pip install totalsegmentator==2.13.0"
            )

        temp_dir = tempfile.mkdtemp()
        try:
            input_file = os.path.join(temp_dir, "input.nii.gz")
            output_path = os.path.join(temp_dir, "segmentation.nii.gz")

            sitk.WriteImage(image, input_file)

            _dev = managed_device
            logger.info(f"OAR segmentation using device: {_dev}")

            # Build device flags for TotalSegmentator.
            # When CUDA_VISIBLE_DEVICES is set, the subprocess sees only
            # one GPU renumbered as 0 — so we MUST pass "gpu" or "gpu:0",
            # NOT the original index.  Passing "gpu:1" when only 1 GPU
            # is visible causes an out-of-range crash.
            env = self._get_clean_subprocess_env()
            if _dev.startswith("cuda:"):
                gpu_idx = _dev.split(":")[1]
                env["CUDA_VISIBLE_DEVICES"] = gpu_idx
                device_str = "gpu"  # subprocess sees this as gpu:0
                logger.info(f"CUDA_VISIBLE_DEVICES={gpu_idx}, --device gpu")
            elif _dev == "cuda":
                device_str = "gpu"
            else:
                device_str = "cpu"

            cmd = [
                ts_exe,
                "-i", input_file,
                "-o", output_path,
                "--task", "total",
                "--device", device_str,
                "--ml",
            ]
            if fast_mode:
                cmd.append("--fast")

            logger.info(f"Running TotalSegmentator OAR: {' '.join(cmd)}")

            # Five minutes was shorter than legitimate cold-start inference on
            # the deployment GPU. Concurrency is controlled above, so a longer
            # bounded timeout no longer permits several jobs to pile up.
            timeout_s = int(os.getenv("BRACHYBOT_TOTALSEG_TIMEOUT_SEC", "900"))

            # Capture stdout+stderr with communicate(timeout=...).  Do not
            # iterate over proc.stdout directly: TotalSegmentator can spawn
            # children that keep the pipe open after the parent exits, which
            # otherwise prevents the timeout from ever being reached.
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                start_new_session=(os.name == "posix"),
            )

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
                    f"Last output: {self._tail_output(output, 5)}"
                )

            _output_lines = self._tail_output(output, 50)
            for stripped in _output_lines:
                logger.debug(stripped)

            if proc.returncode != 0:
                tail = "\n".join(_output_lines[-15:]) if _output_lines else "(no output)"
                raise RuntimeError(
                    f"TotalSegmentator failed (exit code {proc.returncode}). "
                    f"Command: {' '.join(cmd)}\nLast output:\n{tail}"
                )

            if not os.path.exists(output_path):
                raise RuntimeError(
                    f"TotalSegmentator output not found: {output_path}. "
                    f"Last output: {_output_lines[-5:] if _output_lines else '(none)'}"
                )

            # Restore the output through its NIfTI affine. A raw nibabel
            # transpose is unsafe because TotalSegmentator may canonicalize
            # the output orientation independently of the input CT.
            seg_data = _align_segmentation_to_reference(output_path, image)

            oar_array = np.zeros_like(seg_data, dtype=np.int32)

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

    def _terminate_subprocess_group(self, proc: subprocess.Popen) -> None:
        """Terminate TotalSegmentator and any child workers it spawned."""
        if proc.poll() is not None:
            return

        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            except Exception as exc:
                logger.warning(f"Failed to SIGTERM TotalSegmentator process group: {exc}")
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
            except Exception as exc:
                logger.warning(f"Failed to SIGKILL TotalSegmentator process group: {exc}")
                proc.kill()
        else:
            proc.kill()
        proc.wait()

    def _tail_output(self, output: str, max_lines: int) -> list:
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()][-max_lines:]

    def _get_clean_subprocess_env(self) -> dict:
        env = os.environ.copy()
        # Keep PATH so the resolved TotalSegmentator executable can find its
        # environment, but remove Python/library variables that commonly leak
        # from the host process into the subprocess.
        for var in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "PYTHONHOME", "LD_LIBRARY_PATH"):
            env.pop(var, None)
        return env
