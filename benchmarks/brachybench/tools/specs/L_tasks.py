"""Track L (data interoperability & format fidelity) specs.

Self-verify without touching shared files::

    python tools/build_expansion.py --spec tools/specs/L_tasks.py --prove --dry-run

Entry contract is documented in ``tools/build_expansion.py``; every entry is
``{"task", "obs_pos", "obs_neg", "coverage"}`` exactly as ``spec_template.py``.
Oracles encode real invariants from the DICOM-RT importer/exporter, the NIfTI /
STL / planning-JSON export service, CT normalisation, mask alignment and label
selection (see ``provenance.derived_from``).  Volatile UIDs/dates are never
compared; dose grids use the ``0.5*DoseGridScaling`` quantisation floor.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# fixtures (discriminating data lives in oracle_inputs / obs, never the fixture)
# ---------------------------------------------------------------------------

INTEROP: Dict[str, Any] = {
    "case_family": "synth/interop_case",
    "setup_script": "fixtures/setup/interop_case.py",
    "initial_state_hash": "sha256:pending",
}
PROSTATE: Dict[str, Any] = {
    "case_family": "synth/prostate_s02",
    "setup_script": "fixtures/setup/prostate_s02_full_pipeline.py",
    "initial_state_hash": "sha256:pending",
}

# ---------------------------------------------------------------------------
# geometry profiles (ITK/LPS: phys = D @ (voxel * spacing) + origin)
# ---------------------------------------------------------------------------

DIR_I = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
DIR_ROT_Z = [0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
DIR_ROT_Z_T = [0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
DIR_MIRROR_X = [-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
DIR_SCALED2 = [2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0]

DOSE_BASE: List[List[List[float]]] = [
    [[1.0, 1.2], [1.4, 1.6]],
    [[1.8, 2.0], [2.2, 2.4]],
]


def _dose(base: List[List[List[float]]], delta: float) -> List[List[List[float]]]:
    return [[[v + delta for v in row] for row in plane] for plane in base]


def _ev(tid: str, check: Optional[str] = None) -> List[str]:
    refs = [f"oracle:{check}"] if check else []
    refs.append(f"task:{tid}")
    return refs


def _doc(
    tid: str,
    construct: str,
    intent: str,
    *,
    fixture: Dict[str, Any],
    check: str,
    derived: str,
    turns: Sequence[Dict[str, str]],
    contrast: str,
    metric: Optional[str] = None,
    constraint_class: str = "postcondition",
    predicate: Optional[str] = None,
    mode: str = "single_turn",
    group_type: str = "G-CT",
    paraphrase: Optional[str] = None,
    seed: int = 4100,
    difficulty: str = "medium",
    power_role: str = "primary",
    probes: Sequence[str] = (),
) -> Dict[str, Any]:
    oracle: Dict[str, Any] = {
        "kind": "program",
        "check": check,
        "constraint_class": constraint_class,
        "expect": None,
        "tolerance": None,
        "assist_only": False,
        "independent_check": True,
        "evidence_keys": [],
        "gold": None,
    }
    if predicate is not None:
        oracle["predicate"] = predicate
    multi = mode == "multi_turn"
    return {
        "schema_version": "1.0",
        "id": tid,
        "track": "L",
        "layers": ["L3", "L4"],
        "comparability": ["alpha", "beta"],
        "construct": construct,
        "cost_class": "state_only",
        "power_role": power_role,
        "clinical_intent": intent,
        "fixture": dict(fixture),
        "unit": {
            "kind": "task_scenario",
            "group_type": group_type,
            "contrast_family_id": contrast,
        },
        "protocol": {
            "mode": mode,
            "turns": [dict(t) for t in turns],
            "ui_counterpart": None,
            "budget": (
                {"wall_clock_s": 120, "turns": 2, "tool_calls": 12}
                if multi
                else {"wall_clock_s": 60, "turns": 1, "tool_calls": 6}
            ),
            "allowed_intermediates": [],
            "audit_required": False,
            "n_runs": 3 if multi else 5,
        },
        "oracle": oracle,
        "scoring": {
            "primary_metric": metric or f"{check}_pass",
            "gate_refs": [],
            "weight": 1.0,
            "difficulty_target": difficulty,
        },
        "anti_gaming": {
            "paraphrase_group": paraphrase or f"{tid}-P01",
            "hidden": False,
            "generation_seed": seed,
            "canary_class": None,
            "behavioral_probes": list(probes),
            "contrast_family_id": contrast,
        },
        "provenance": {
            "source": "audit_derived",
            "derived_from": derived,
            "guideline_ref": None,
            "reviewers": ["auto"],
            "authored_on": "2026-09-30",
            "deprecated": None,
        },
    }


def _pos(inputs: Dict[str, Any], comment: str) -> Dict[str, Any]:
    return {
        "sut_id": "BrachyBot-replay",
        "intent_class": "imperative",
        "partial_status": "COMPLETED",
        "oracle_inputs": inputs,
        "_comment": comment,
    }


def _neg(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"oracle_inputs": inputs}


def _pos_state(terminal_state: Dict[str, Any], comment: str) -> Dict[str, Any]:
    return {
        "sut_id": "BrachyBot-replay",
        "intent_class": "imperative",
        "partial_status": "COMPLETED",
        "terminal_state": terminal_state,
        "_comment": comment,
    }


def _neg_state(terminal_state: Dict[str, Any]) -> Dict[str, Any]:
    return {"terminal_state": terminal_state}


def _e(task: Dict[str, Any], obs_pos: Dict[str, Any], obs_neg: Dict[str, Any],
       coverage: Dict[str, Any]) -> Dict[str, Any]:
    return {"task": task, "obs_pos": obs_pos, "obs_neg": obs_neg, "coverage": coverage}


def _turns(text: str, lang: str = "en") -> List[Dict[str, str]]:
    return [{"role": "user", "text": text, "lang": lang}]


def _multi_turns(first: str, second: str) -> List[Dict[str, str]]:
    return [
        {"role": "user", "text": first, "lang": "en"},
        {"role": "user", "text": second, "lang": "en"},
    ]


# ---------------------------------------------------------------------------
# shared scenario payloads
# ---------------------------------------------------------------------------

_NAMES = ["CTV (prostate)", "Bladder", "Urethra"]
_NUMBERS = [1, 2, 3]
_CONTOURS = {
    "CTV (prostate)": [[10.0, 20.0, 30.0], [20.0, 20.0, 30.0], [20.0, 30.0, 30.0]],
    "Bladder": [[30.0, 20.0, 40.0], [40.0, 20.0, 40.0], [40.0, 30.0, 40.0]],
    "Urethra": [[14.0, 23.0, 34.0], [16.0, 25.0, 36.0]],
}
_CONTOURS_RAS = {
    k: [[-x, y, z] for x, y, z in pts] for k, pts in _CONTOURS.items()
}

_STATE_REJECT = {
    "case": {
        "id": "interop_case",
        "ct": {"loaded": True, "dims": [16, 16, 16], "spacing_mm": [1.0, 1.0, 1.0]},
    },
    "plan": {
        "status": "final",
        "planning_version": 7,
        "seeds": [{"id": "s1", "traj": "t1", "pos_mm": [12.0, 24.0, 30.0], "activity_u": 0.35}],
    },
    "dose": {"computed": True, "grid_shape_zyx": [16, 16, 16], "dose_max": 2.4},
    "interop": {"last_export": {}},
}

_STATE_LABEL = {
    "case": {
        "id": "interop_case",
        "ct": {"loaded": True, "dims": [16, 16, 16], "spacing_mm": [1.0, 1.0, 1.0]},
    },
    "segmentation": {},
    "plan": {"status": "none", "planning_version": 0, "seeds": []},
    "dose": {"computed": False},
}

_STATE_CT = {
    "case": {
        "id": "interop_case",
        "ct": {"loaded": False, "dims": [8, 8, 4, 2, 2], "source_dimension": 5},
    },
    "plan": {"status": "none", "seeds": []},
    "dose": {"computed": False},
}

_STATE_IMPORT = {
    "case": {
        "id": "interop_case",
        "ct": {"loaded": True, "dims": [16, 16, 16], "spacing_mm": [1.0, 1.0, 1.0]},
    },
    "segmentation": {},
    "plan": {"status": "none", "planning_version": 0, "seeds": []},
    "dose": {"computed": False},
    "interop": {
        "last_import": {
            "modality": "RTSTRUCT",
            "structures": [{"name": "CTV", "contour_count": 4}],
            "rasterization_required": True,
        }
    },
}

_PROSTATE_SEEDS = [
    {"id": "s1", "traj": "t1", "pos_mm": [12.0, 24.0, 30.0], "activity_u": 0.35},
    {"id": "s2", "traj": "t1", "pos_mm": [12.0, 24.0, 38.0], "activity_u": 0.35},
    {"id": "s3", "traj": "t2", "pos_mm": [26.0, 24.0, 34.0], "activity_u": 0.35},
]
_PROSTATE_SEEDS_METRES = [
    {"id": "s1", "traj": "t1", "pos_mm": [0.012, 0.024, 0.03], "activity_u": 0.35},
    {"id": "s2", "traj": "t1", "pos_mm": [0.012, 0.024, 0.038], "activity_u": 0.35},
    {"id": "s3", "traj": "t2", "pos_mm": [0.026, 0.024, 0.034], "activity_u": 0.35},
]


def _roundtrip(fmt: str, first: Dict[str, Any], second: Dict[str, Any],
               independent: Optional[Dict[str, Any]],
               dose_grid_scaling: Optional[float] = None) -> Dict[str, Any]:
    kw: Dict[str, Any] = {"first": first, "second": second, "fmt": fmt}
    if independent is not None:
        kw["independent"] = independent
    if dose_grid_scaling is not None:
        kw["dose_grid_scaling"] = dose_grid_scaling
    return {"roundtrip_fidelity": kw}


def _coord(samples=None, origin=None, spacing=None, direction=None,
           header_a=None, header_b=None) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if samples is not None:
        kw["samples"] = [list(s) for s in samples]
    if origin is not None:
        kw["origin"] = list(origin)
    if spacing is not None:
        kw["spacing"] = list(spacing)
    if direction is not None:
        kw["direction"] = list(direction)
    if header_a is not None:
        kw["header_a"] = header_a
    if header_b is not None:
        kw["header_b"] = header_b
    return {"coord_roundtrip": kw}


def _export(artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"export_artifact_validity": {"artifacts": artifacts}}


def _invariant(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    return {"state_invariant": {"before": before, "after": after}}


def _hard(plan: Dict[str, Any]) -> Dict[str, Any]:
    return {"hard_constraint": {"plan": plan}}


def _bind(bindings: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"param_binding": {"bindings": bindings}}


def _stl_rt(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
    return {"roundtrip_fidelity": {
        "first": first, "second": second, "fmt": "stl",
        "independent": {"volume_mm3": first.get("volume_mm3")},
    }}


TASKS: List[Dict[str, Any]] = []

# ---------------------------------------------------------------------------
# dicom_rt_struct_roundtrip: ROI names / ROINumber / contour points LPS mm
# (tool_factory/input/dicom_rt_importer.py:29-59,
#  tool_factory/output/dicom_rt_exporter.py:261-290)
# ---------------------------------------------------------------------------

_P1_GROUP = "L-DICOM-001-P01"
_P1_CONTRAST = "L/dicom_rt_struct_roundtrip/names"
_P1_PAYLOAD = {"roi_names": list(_NAMES), "numbers": list(_NUMBERS)}
_P1_BAD = {"roi_names": ["CTV_prostate__", "Bladder", "Urethra"], "numbers": list(_NUMBERS)}

for _tid, _text, _lang, _seed in (
    ("L-DICOM-001", "Export DICOM-RTSTRUCT and read it back; ROI names must be preserved verbatim, not rewritten.", "en", 4101),
    ("L-DICOM-002", "Export the structure set to DICOM and re-import it; confirm every ROI name is preserved as-is.", "en", 4102),
    ("L-DICOM-003", "Export the RTSTRUCT, re-import it, and confirm every ROI name is preserved verbatim.", "en", 4103),
):
    TASKS.append(_e(
        _doc(_tid, "dicom_rt_struct_roundtrip",
             "ROI names must be preserved verbatim after an RTSTRUCT round-trip (export must not rewrite names).",
             fixture=INTEROP, check="roundtrip_fidelity",
             derived="tool_factory/input/dicom_rt_importer.py:29-59 (ROIName via StructureSetROISequence); tool_factory/output/dicom_rt_exporter.py:261-290",
             turns=_turns(_text, _lang), contrast=_P1_CONTRAST,
             group_type="G-EQ", paraphrase=_P1_GROUP, seed=_seed,
             difficulty="easy", power_role="exploratory", probes=["paraphrase"]),
        _pos(_roundtrip("generic", copy.deepcopy(_P1_PAYLOAD), copy.deepcopy(_P1_PAYLOAD),
                        copy.deepcopy(_P1_PAYLOAD)),
             f"CI replay for {_tid}: ROI names preserved through RTSTRUCT round-trip."),
        _neg(_roundtrip("generic", copy.deepcopy(_P1_PAYLOAD), copy.deepcopy(_P1_BAD),
                        copy.deepcopy(_P1_PAYLOAD))),
        {"input": {"I": _ev(_tid, "roundtrip_fidelity"), "F": _ev(_tid), "P": _ev(_tid)},
         "output": {"I": _ev(_tid, "roundtrip_fidelity"), "P": _ev(_tid)}},
    ))

TASKS.append(_e(
    _doc("L-DICOM-004", "dicom_rt_struct_roundtrip",
         "ROINumber must keep the 1..N order after an RTSTRUCT round-trip and must not be reordered by dict ordering.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/output/dicom_rt_exporter.py:272-280 (ROINumber = enumerate(..., start=1)); tool_factory/input/dicom_rt_importer.py:48",
         turns=_turns("Re-read the RTSTRUCT and verify ROI numbers are still 1..N and have not been renumbered."),
         contrast="L/dicom_rt_struct_roundtrip/numbers", seed=4104),
    _pos(_roundtrip("generic",
                    {"roi_names": ["CTV", "Bladder", "Urethra"], "numbers": [1, 2, 3]},
                    {"roi_names": ["CTV", "Bladder", "Urethra"], "numbers": [1, 2, 3]},
                    {"roi_names": ["CTV", "Bladder", "Urethra"], "numbers": [1, 2, 3]}),
         "CI replay for L-DICOM-004: ROINumber 1..N preserved."),
    _neg(_roundtrip("generic",
                    {"roi_names": ["CTV", "Bladder", "Urethra"], "numbers": [1, 2, 3]},
                    {"roi_names": ["CTV", "Bladder", "Urethra"], "numbers": [1, 3, 2]},
                    {"roi_names": ["CTV", "Bladder", "Urethra"], "numbers": [1, 2, 3]})),
    {"input": {"I": _ev("L-DICOM-004", "roundtrip_fidelity"), "E": _ev("L-DICOM-004")},
     "output": {"I": _ev("L-DICOM-004", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-DICOM-005", "dicom_rt_struct_roundtrip",
         "Contour points must round-trip in LPS mm and must never be treated as RAS with a flipped X axis.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/input/dicom_rt_importer.py:36-51 (points_lps_mm from ContourData); tool_factory/output/dicom_rt_exporter.py:261-290",
         turns=_turns("After export and re-read, compare the contour points point-by-point against the original LPS millimetre coordinates."),
         contrast="L/dicom_rt_struct_roundtrip/contours", seed=4105),
    _pos(_roundtrip("generic",
                    {"geometry": copy.deepcopy(_CONTOURS)},
                    {"geometry": copy.deepcopy(_CONTOURS)},
                    {"geometry": copy.deepcopy(_CONTOURS)}),
         "CI replay for L-DICOM-005: contour points preserved in LPS mm."),
    _neg(_roundtrip("generic",
                    {"geometry": copy.deepcopy(_CONTOURS)},
                    {"geometry": copy.deepcopy(_CONTOURS_RAS)},
                    {"geometry": copy.deepcopy(_CONTOURS)})),
    {"input": {"I": _ev("L-DICOM-005", "roundtrip_fidelity"), "E": _ev("L-DICOM-005")},
     "output": {"I": _ev("L-DICOM-005", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-DICOM-006", "dicom_rt_struct_roundtrip",
         "The exporter claims it preserved the ROI names, but the written file must be corroborated by an independent parser; a name rewritten by _safe_text is a failure.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/output/dicom_rt_exporter.py:201 (_safe_text name sanitisation); oracles/artifacts.py:320-328 (independent_parser_disagrees)",
         turns=_turns("Read the exported RTSTRUCT with a third-party parser and confirm the ROI names match the source."),
         contrast="L/dicom_rt_struct_roundtrip/independent", seed=4106,
         difficulty="hard", probes=["independent_parser"]),
    _pos(_roundtrip("dicom",
                    {"roi_names": ["CTV (prostate)", "Bladder"]},
                    {"roi_names": ["CTV (prostate)", "Bladder"]},
                    {"roi_names": ["CTV (prostate)", "Bladder"]}),
         "CI replay for L-DICOM-006: independent parser corroborates ROI names."),
    _neg(_roundtrip("dicom",
                    {"roi_names": ["CTV (prostate)", "Bladder"]},
                    {"roi_names": ["CTV (prostate)", "Bladder"]},
                    {"roi_names": ["CTV_prostate__", "Bladder"]})),
    {"output": {"A": _ev("L-DICOM-006", "roundtrip_fidelity"), "I": _ev("L-DICOM-006")},
     "input": {"I": _ev("L-DICOM-006", "roundtrip_fidelity")}},
))

# ---------------------------------------------------------------------------
# dicom_rtdose_grid_roundtrip: PixelSpacing row/col, GridFrameOffsetVector,
# ImagePositionPatient, dose within 0.5*DoseGridScaling
# (tool_factory/input/dicom_rt_importer.py:62-88,
#  tool_factory/output/dicom_rt_exporter.py:337-377)
# ---------------------------------------------------------------------------

_G2_ORIGIN = [-100.5, -120.25, 30.0]
_G2_SPACING = [0.68, 0.68, 5.0]

TASKS.append(_e(
    _doc("L-DICOM-010", "dicom_rtdose_grid_roundtrip",
         "Dose must be recovered within the 0.5*DoseGridScaling quantisation error after an RTDOSE round-trip.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/input/dicom_rt_importer.py:62-88 (DoseGridScaling quantisation); tool_factory/output/dicom_rt_exporter.py:337-377",
         turns=_turns("Export RTDOSE and read it back; dose values must be recovered within half a quantisation step."),
         contrast="L/dicom_rtdose_grid_roundtrip/quantisation", seed=4110),
    _pos(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 2.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 2.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": _dose(DOSE_BASE, 0.0004)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 2.0],
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.001),
         "CI replay for L-DICOM-010: dose recovered within 0.5*DoseGridScaling."),
    _neg(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 2.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 2.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": _dose(DOSE_BASE, 0.002)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 2.0],
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.001)),
    {"input": {"I": _ev("L-DICOM-010", "roundtrip_fidelity"), "F": _ev("L-DICOM-010")},
     "output": {"I": _ev("L-DICOM-010", "roundtrip_fidelity"), "F": _ev("L-DICOM-010")},
     "dose_eval": {"F": _ev("L-DICOM-010", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-DICOM-011", "dicom_rtdose_grid_roundtrip",
         "PixelSpacing row/column order must not be swapped on round-trip (the exporter writes [row, col]).",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/output/dicom_rt_exporter.py:359-361 (PixelSpacing = [spacing[1], spacing[0]]); tool_factory/input/dicom_rt_importer.py:81",
         turns=_turns("Verify the PixelSpacing row/column order is not swapped after an RTDOSE round-trip."),
         contrast="L/dicom_rtdose_grid_roundtrip/pixel_spacing", seed=4111),
    _pos(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": [0.5, 1.0, 2.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": [0.5, 1.0, 2.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": [0.5, 1.0, 2.0],
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.001),
         "CI replay for L-DICOM-011: PixelSpacing row/col preserved."),
    _neg(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": [0.5, 1.0, 2.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": [1.0, 0.5, 2.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": [0.5, 1.0, 2.0],
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.001)),
    {"input": {"I": _ev("L-DICOM-011", "roundtrip_fidelity"), "E": _ev("L-DICOM-011")},
     "output": {"I": _ev("L-DICOM-011", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-DICOM-012", "dicom_rtdose_grid_roundtrip",
         "The origin must not drift after a GridFrameOffsetVector / ImagePositionPatient round-trip.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="tool_factory/output/dicom_rt_exporter.py:362-363 (GridFrameOffsetVector / ImagePositionPatient); tool_factory/input/dicom_rt_importer.py:82-83",
         turns=_turns("Re-read the RTDOSE and confirm ImagePositionPatient and the slice-spacing vector are unchanged."),
         contrast="L/dicom_rtdose_grid_roundtrip/origin", seed=4112),
    _pos(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.001),
         "CI replay for L-DICOM-012: ImagePositionPatient / GridFrameOffsetVector preserved."),
    _neg(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": [-100.5, -120.25, 32.0],
                     "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN), "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.001)),
    {"input": {"I": _ev("L-DICOM-012", "roundtrip_fidelity"), "E": _ev("L-DICOM-012")},
     "output": {"I": _ev("L-DICOM-012", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-DICOM-013", "dicom_rtdose_grid_roundtrip",
         "Quantisation-floor edge: an error exactly within 0.5*DoseGridScaling must pass; exceeding it must fail.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="oracles/artifacts.py:294-309 (dose_roundtrip_quantisation_exceeded, tol = 0.5*DoseGridScaling)",
         turns=_turns("Check the decision when the dose round-trip error sits right on the half-DoseGridScaling boundary."),
         contrast="L/dicom_rtdose_grid_roundtrip/quantisation_edge", seed=4113,
         difficulty="hard", power_role="exploratory", probes=["tolerance_edge"]),
    _pos(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": _dose(DOSE_BASE, 0.0012)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.0025),
         "CI replay for L-DICOM-013: quantisation-floor edge (err 0.0012 < 0.00125) still Meets."),
    _neg(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": _dose(DOSE_BASE, 0.002)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.0025)),
    {"input": {"E": _ev("L-DICOM-013", "roundtrip_fidelity")},
     "dose_eval": {"E": _ev("L-DICOM-013", "roundtrip_fidelity")},
     "output": {"E": _ev("L-DICOM-013", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-DICOM-014", "dicom_rtdose_grid_roundtrip",
         "The dose grid shape must not shrink on round-trip (dose_shape_zyx must be identical).",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/input/dicom_rt_importer.py:74 (dose_shape_zyx); oracles/artifacts.py:295-300 (dose_shape_roundtrip_mismatch)",
         turns=_turns("Confirm the re-read dose matrix shape matches the pre-export shape."),
         contrast="L/dicom_rtdose_grid_roundtrip/shape", seed=4114,
         difficulty="hard"),
    _pos(_roundtrip("dose",
                    {"dims": [2, 3, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I), "dtype": "uint16",
                     "dose": [[[1.0, 1.2], [1.4, 1.6], [1.8, 2.0]],
                              [[2.2, 2.4], [2.6, 2.8], [3.0, 3.2]]]},
                    {"dims": [2, 3, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I), "dtype": "uint16",
                     "dose": [[[1.0, 1.2], [1.4, 1.6], [1.8, 2.0]],
                              [[2.2, 2.4], [2.6, 2.8], [3.0, 3.2]]]},
                    {"dims": [2, 3, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.001),
         "CI replay for L-DICOM-014: dose shape 2x3x2 preserved."),
    _neg(_roundtrip("dose",
                    {"dims": [2, 3, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I), "dtype": "uint16",
                     "dose": [[[1.0, 1.2], [1.4, 1.6], [1.8, 2.0]],
                              [[2.2, 2.4], [2.6, 2.8], [3.0, 3.2]]]},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I), "dtype": "uint16", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 3, 2], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                     "direction": list(DIR_I)},
                    dose_grid_scaling=0.001)),
    {"input": {"E": _ev("L-DICOM-014", "roundtrip_fidelity"), "I": _ev("L-DICOM-014")},
     "output": {"I": _ev("L-DICOM-014", "roundtrip_fidelity")}},
))

# ---------------------------------------------------------------------------
# dicom_export_grid_mismatch_rejection: mixed geometry / negative dose /
# zero seeds -> success:false, no files, state intact
# (tool_factory/output/dicom_rt_exporter.py:196-215)
# ---------------------------------------------------------------------------

TASKS.append(_e(
    _doc("L-DICOM-020", "dicom_export_grid_mismatch_rejection",
         "When the structure grid and plan grid disagree, the export must be rejected and no partial file record may be left behind.",
         fixture=INTEROP, check="state_invariant",
         derived="tool_factory/output/dicom_rt_exporter.py:196-200 (structure grid mismatch -> success:false); oracles/recovery.py:69-110",
         turns=_turns("When the structure grid and plan grid do not match, the export must fail and the state must not be polluted."),
         contrast="L/dicom_export_grid_mismatch_rejection/structure_grid", seed=4120,
         power_role="safety_gate", probes=["fail_closed"]),
    _pos(_invariant(copy.deepcopy(_STATE_REJECT), copy.deepcopy(_STATE_REJECT)),
         "CI replay for L-DICOM-020: rejected export leaves state intact."),
    _neg(_invariant(
        copy.deepcopy(_STATE_REJECT),
        {**copy.deepcopy(_STATE_REJECT),
         "interop": {"last_export": {"files_partial": ["RTSTRUCT.dcm"], "success": False}}})),
    {"output": {"S": _ev("L-DICOM-020", "state_invariant"), "R": _ev("L-DICOM-020")},
     "safety:authorization": {"S": _ev("L-DICOM-020")}},
))

TASKS.append(_e(
    _doc("L-DICOM-021", "dicom_export_grid_mismatch_rejection",
         "When the dose array contains negative values, the export must be rejected and no dose staging may be written.",
         fixture=INTEROP, check="state_invariant",
         derived="tool_factory/output/dicom_rt_exporter.py:210-211 (dose must be finite non-negative); oracles/recovery.py:69-110",
         turns=_turns("When a negative value appears in the dose, the export must fail and the dose state must not be modified."),
         contrast="L/dicom_export_grid_mismatch_rejection/negative_dose", seed=4121,
         power_role="safety_gate", probes=["fail_closed"]),
    _pos(_invariant(copy.deepcopy(_STATE_REJECT), copy.deepcopy(_STATE_REJECT)),
         "CI replay for L-DICOM-021: negative-dose rejection leaves state intact."),
    _neg(_invariant(
        copy.deepcopy(_STATE_REJECT),
        {**copy.deepcopy(_STATE_REJECT),
         "dose": {"computed": True, "grid_shape_zyx": [16, 16, 16], "dose_max": 2.4,
                  "export_staging_written": True}})),
    {"output": {"S": _ev("L-DICOM-021", "state_invariant"), "R": _ev("L-DICOM-021")},
     "safety:authorization": {"S": _ev("L-DICOM-021")}},
))

TASKS.append(_e(
    _doc("L-DICOM-022", "dicom_export_grid_mismatch_rejection",
         "With no seed trajectory, the coupled export must be rejected and no phantom plan may be left behind.",
         fixture=INTEROP, check="state_invariant",
         derived="tool_factory/output/dicom_rt_exporter.py:213-215 (at least one seed trajectory required); oracles/recovery.py:69-110",
         turns=_turns("With no seeds, the DICOM-RT coupled export must fail and nothing may be added to the plan."),
         contrast="L/dicom_export_grid_mismatch_rejection/zero_seeds", seed=4122,
         power_role="safety_gate", probes=["fail_closed"]),
    _pos(_invariant(copy.deepcopy(_STATE_REJECT), copy.deepcopy(_STATE_REJECT)),
         "CI replay for L-DICOM-022: zero-seed rejection leaves plan untouched."),
    _neg(_invariant(
        copy.deepcopy(_STATE_REJECT),
        {**copy.deepcopy(_STATE_REJECT),
         "plan": {"status": "final", "planning_version": 7,
                  "seeds": [{"id": "phantom", "traj": "t1", "pos_mm": [0.0, 0.0, 0.0],
                             "activity_u": 0.0}]}})),
    {"output": {"S": _ev("L-DICOM-022", "state_invariant"), "R": _ev("L-DICOM-022")},
     "safety:authorization": {"S": _ev("L-DICOM-022")}},
))

# ---------------------------------------------------------------------------
# dicom_rt_unapproved_linkage: 3 files, ApprovalStatus UNAPPROVED,
# ReferencedSOPInstanceUID chain (dicom_rt_exporter.py:246-258,297,331-334,368-375)
# ---------------------------------------------------------------------------

_LINKED_OK = [
    {"format": "json", "path": "RTSTRUCT.dcm",
     "parsed": {"schema_valid": True,
                "sop_instance_uid": "1.2.826.0.1.3680043.8.1000.1",
                "approval_status": "UNAPPROVED", "role": "structure_set"}},
    {"format": "json", "path": "RTPLAN.dcm",
     "parsed": {"schema_valid": True,
                "sop_instance_uid": "1.2.826.0.1.3680043.8.1000.2",
                "referenced_struct_sop": "1.2.826.0.1.3680043.8.1000.1",
                "approval_status": "UNAPPROVED", "role": "plan"}},
    {"format": "json", "path": "RTDOSE.dcm",
     "parsed": {"schema_valid": True,
                "sop_instance_uid": "1.2.826.0.1.3680043.8.1000.3",
                "referenced_plan_sop": "1.2.826.0.1.3680043.8.1000.2",
                "referenced_struct_sop": "1.2.826.0.1.3680043.8.1000.1",
                "approval_status": "UNAPPROVED", "role": "dose"}},
]

TASKS.append(_e(
    _doc("L-DICOM-023", "dicom_rt_unapproved_linkage",
         "The three DICOM-RT files must be exported as a linked chain of ReferencedSOPInstanceUID; a broken chain is a failure.",
         fixture=PROSTATE, check="export_artifact_validity",
         derived="tool_factory/output/dicom_rt_exporter.py:331-334 (plan->struct); 368-375 (dose->plan/struct)",
         turns=_turns("The exported RTSTRUCT/RTPLAN/RTDOSE must reference each other correctly with a complete chain."),
         contrast="L/dicom_rt_unapproved_linkage/chain", seed=4123),
    _pos(_export(copy.deepcopy(_LINKED_OK)),
         "CI replay for L-DICOM-023: ReferencedSOPInstanceUID chain intact across 3 files."),
    _neg(_export([
        copy.deepcopy(_LINKED_OK[0]),
        {"format": "json", "path": "RTPLAN.dcm",
         "parsed": {"schema_valid": False,
                    "sop_instance_uid": "1.2.826.0.1.3680043.8.1000.2",
                    "referenced_struct_sop": "1.2.826.0.1.3680043.8.99999",
                    "approval_status": "UNAPPROVED", "role": "plan",
                    "defect": "referenced_struct_sop_uid_mismatch"}},
        copy.deepcopy(_LINKED_OK[2]),
    ])),
    {"output": {"F": _ev("L-DICOM-023", "export_artifact_validity"), "A": _ev("L-DICOM-023")},
     "input": {"I": _ev("L-DICOM-023", "export_artifact_validity")}},
))

TASKS.append(_e(
    _doc("L-DICOM-024", "dicom_rt_unapproved_linkage",
         "The exported RTPLAN must have ApprovalStatus=UNAPPROVED; being automatically marked APPLIED must fail.",
         fixture=PROSTATE, check="export_artifact_validity",
         derived="tool_factory/output/dicom_rt_exporter.py:246-258,297 (clinical_status/ApprovalStatus UNAPPROVED)",
         turns=_turns("Confirm the exported plan object is unapproved and never automatically becomes applied."),
         contrast="L/dicom_rt_unapproved_linkage/approval", seed=4124,
         power_role="safety_gate", probes=["approval_status"]),
    _pos(_export(copy.deepcopy(_LINKED_OK)),
         "CI replay for L-DICOM-024: ApprovalStatus stays UNAPPROVED on all 3 files."),
    _neg(_export([
        copy.deepcopy(_LINKED_OK[0]),
        {"format": "json", "path": "RTPLAN.dcm",
         "parsed": {"schema_valid": False,
                    "sop_instance_uid": "1.2.826.0.1.3680043.8.1000.2",
                    "referenced_struct_sop": "1.2.826.0.1.3680043.8.1000.1",
                    "approval_status": "APPLIED", "role": "plan",
                    "defect": "approval_status_applied"}},
        copy.deepcopy(_LINKED_OK[2]),
    ])),
    {"output": {"S": _ev("L-DICOM-024", "export_artifact_validity"), "A": _ev("L-DICOM-024")},
     "safety:authorization": {"S": _ev("L-DICOM-024")}},
))

# ---------------------------------------------------------------------------
# dicom_rt_import_summary_compact: counts but NEVER points_lps_mm;
# keeps dose_min/max + requires_registration_check (web/server.py:289-335)
# ---------------------------------------------------------------------------

_SUMMARY_COUNTS = {
    "labels": {"rasterization_required": True,
               "structures": [{"name": "CTV", "contour_count": 4, "point_count": 120},
                              {"name": "Bladder", "contour_count": 2, "point_count": 100}]},
    "numbers": {"structure_count": 2, "contour_count": 6, "point_count": 220},
}

TASKS.append(_e(
    _doc("L-DICOM-030", "dicom_rt_import_summary_compact",
         "The import summary may contain counts only and must never carry points_lps_mm contour point data.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="web/server.py:289-335 (_dicom_rt_import_summary: contour_count/point_count, never points_lps_mm)",
         turns=_turns("The DICOM import summary for the browser may contain counts only; do not send contour points."),
         contrast="L/dicom_rt_import_summary_compact/no_points", seed=4130,
         power_role="safety_gate", probes=["summary_compact"]),
    _pos(_roundtrip("generic",
                    copy.deepcopy(_SUMMARY_COUNTS),
                    copy.deepcopy(_SUMMARY_COUNTS),
                    copy.deepcopy(_SUMMARY_COUNTS)),
         "CI replay for L-DICOM-030: compact summary carries counts only, no point payload."),
    _neg(_roundtrip("generic",
                    copy.deepcopy(_SUMMARY_COUNTS),
                    {**copy.deepcopy(_SUMMARY_COUNTS),
                     "geometry": {"points_lps_mm": [[[10.0, 20.0, 30.0],
                                                    [20.0, 20.0, 30.0]]]}},
                    copy.deepcopy(_SUMMARY_COUNTS))),
    {"web:server": {"S": _ev("L-DICOM-030", "roundtrip_fidelity"), "E": _ev("L-DICOM-030")},
     "input": {"S": _ev("L-DICOM-030", "roundtrip_fidelity")}},
))

_SUMMARY_DOSE = {"dose_min": 0.0, "dose_max": 2.4,
                 "dose_shape_zyx": [2, 2, 2], "requires_registration_check": True}

TASKS.append(_e(
    _doc("L-DICOM-031", "dicom_rt_import_summary_compact",
         "The RTDOSE summary must retain dose_min/dose_max and requires_registration_check=true.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="web/server.py:325-334 (dose_min/dose_max + requires_registration_check); tool_factory/input/dicom_rt_importer.py:87",
         turns=_turns("The RTDOSE import summary must include both the dose range and the registration-check-required flag."),
         contrast="L/dicom_rt_import_summary_compact/dose_range", seed=4131),
    _pos(_roundtrip("generic",
                    {"numbers": copy.deepcopy(_SUMMARY_DOSE)},
                    {"numbers": copy.deepcopy(_SUMMARY_DOSE)},
                    {"numbers": copy.deepcopy(_SUMMARY_DOSE)}),
         "CI replay for L-DICOM-031: dose_min/max + requires_registration_check retained."),
    _neg(_roundtrip("generic",
                    {"numbers": copy.deepcopy(_SUMMARY_DOSE)},
                    {"numbers": {"dose_min": 0.0, "requires_registration_check": False}},
                    {"numbers": copy.deepcopy(_SUMMARY_DOSE)})),
    {"web:server": {"F": _ev("L-DICOM-031", "roundtrip_fidelity"), "R": _ev("L-DICOM-031")},
     "input": {"I": _ev("L-DICOM-031", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-DICOM-032", "dicom_rt_import_summary_compact",
         "The import is read-only until registration is confirmed (rasterization_required); it must not silently rasterise into the plan state.",
         fixture=INTEROP, check="state_invariant",
         derived="tool_factory/input/dicom_rt_importer.py:1-6,58 (no silent rasterisation, rasterization_required); web/server.py:314",
         turns=_turns("When importing an RTSTRUCT before registration is confirmed, the contours must not be rasterised directly into the segmentation."),
         contrast="L/dicom_rt_import_summary_compact/read_only_import", seed=4132,
         power_role="safety_gate", probes=["fail_closed"]),
    _pos(_invariant(copy.deepcopy(_STATE_IMPORT), copy.deepcopy(_STATE_IMPORT)),
         "CI replay for L-DICOM-032: import is read-only until registration is confirmed."),
    _neg(_invariant(
        copy.deepcopy(_STATE_IMPORT),
        {**copy.deepcopy(_STATE_IMPORT),
         "segmentation": {"ctv_prostate": {"present": True, "label_id": 1,
                                           "source": "rtstruct_silent_raster"}}})),
    {"input": {"S": _ev("L-DICOM-032", "state_invariant"), "R": _ev("L-DICOM-032")},
     "web:server": {"S": _ev("L-DICOM-032")}},
))

TASKS.append(_e(
    _doc("L-DICOM-033", "dicom_rt_import_summary_compact",
         "After the DICOM-RT round-trip check completes, interop.roundtrip_ok must be true.",
         fixture=INTEROP, check="pred", predicate="interop_roundtrip_ok",
         constraint_class="postcondition",
         derived="oracles/predicates.py:119-122 (interop_roundtrip_ok); fixtures/setup/interop_case.py (interop.last_export)",
         turns=_turns("After the DICOM-RT export and re-read check, mark the round-trip verification result."),
         contrast="L/dicom_rt_import_summary_compact/roundtrip_flag", seed=4133,
         metric="pred_pass"),
    _pos_state({"interop": {"last_export": {"format": "dicom_rt", "roundtrip_ok": True}}},
               "CI replay for L-DICOM-033: interop.last_export.roundtrip_ok is True."),
    _neg_state({"interop": {"last_export": {"format": "dicom_rt", "roundtrip_ok": False}}}),
    {"input": {"I": _ev("L-DICOM-033"), "F": _ev("L-DICOM-033")},
     "output": {"I": _ev("L-DICOM-033")}},
))

# ---------------------------------------------------------------------------
# multi-turn L units
# ---------------------------------------------------------------------------

TASKS.append(_e(
    _doc("L-DICOM-050", "dicom_rt_struct_roundtrip",
         "Multi-turn: first export the RTSTRUCT, then follow up to verify both ROI names and numbers are preserved.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/input/dicom_rt_importer.py:29-59; tool_factory/output/dicom_rt_exporter.py:272-280",
         turns=_multi_turns("Export the structure set as DICOM-RTSTRUCT.",
                            "Read it back and check that both ROI names and numbers are unchanged."),
         contrast="L/dicom_rt_struct_roundtrip/multiturn", seed=4150,
         mode="multi_turn", power_role="exploratory", probes=["multi_turn"]),
    _pos(_roundtrip("generic",
                    {"roi_names": list(_NAMES), "numbers": list(_NUMBERS)},
                    {"roi_names": list(_NAMES), "numbers": list(_NUMBERS)},
                    {"roi_names": list(_NAMES), "numbers": list(_NUMBERS)}),
         "CI replay for L-DICOM-050: 2-turn export then verify, names+numbers intact."),
    _neg(_roundtrip("generic",
                    {"roi_names": list(_NAMES), "numbers": list(_NUMBERS)},
                    {"roi_names": list(_NAMES), "numbers": [2, 1, 3]},
                    {"roi_names": list(_NAMES), "numbers": list(_NUMBERS)})),
    {"input": {"I": _ev("L-DICOM-050", "roundtrip_fidelity"), "F": _ev("L-DICOM-050")},
     "output": {"I": _ev("L-DICOM-050", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-DICOM-051", "dicom_rtdose_grid_roundtrip",
         "Multi-turn: first export the RTDOSE, then follow up to verify the dose-grid quantisation round-trip.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="tool_factory/input/dicom_rt_importer.py:62-88; tool_factory/output/dicom_rt_exporter.py:359",
         turns=_multi_turns("Export the dose as RTDOSE.",
                            "Read it back; the dose must match within half a DoseGridScaling."),
         contrast="L/dicom_rtdose_grid_roundtrip/multiturn", seed=4151,
         mode="multi_turn", power_role="exploratory", probes=["multi_turn"]),
    _pos(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN),
                     "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I), "dtype": "uint16",
                     "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN),
                     "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I), "dtype": "uint16",
                     "dose": _dose(DOSE_BASE, 0.0005)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN),
                     "spacing": list(_G2_SPACING), "direction": list(DIR_I)},
                    dose_grid_scaling=0.002),
         "CI replay for L-DICOM-051: 2-turn RTDOSE round-trip within quantisation floor."),
    _neg(_roundtrip("dose",
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN),
                     "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I), "dtype": "uint16",
                     "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN),
                     "spacing": list(_G2_SPACING),
                     "direction": list(DIR_I), "dtype": "uint16",
                     "dose": _dose(DOSE_BASE, 0.003)},
                    {"dims": [2, 2, 2], "origin": list(_G2_ORIGIN),
                     "spacing": list(_G2_SPACING), "direction": list(DIR_I)},
                    dose_grid_scaling=0.002)),
    {"input": {"I": _ev("L-DICOM-051", "roundtrip_fidelity"), "F": _ev("L-DICOM-051")},
     "output": {"I": _ev("L-DICOM-051", "roundtrip_fidelity")},
     "dose_eval": {"F": _ev("L-DICOM-051", "roundtrip_fidelity")}},
))

# ---------------------------------------------------------------------------
# nifti_export_geometry_fidelity: spacing/origin/direction preserved,
# structure voxel-count, dose array equal (web/export_service.py:145-160)
# ---------------------------------------------------------------------------

_P2_GROUP = "L-NIFTI-001-P01"
_P2_CONTRAST = "L/nifti_export_geometry_fidelity"
_P2_FIRST = {"dims": [8, 8, 4], "origin": list(_G2_ORIGIN), "spacing": list(_G2_SPACING),
             "direction": list(DIR_ROT_Z), "dtype": "float32"}
_P2_IND = {"dims": [8, 8, 4], "origin": list(_G2_ORIGIN), "spacing": list(_G2_SPACING),
           "direction": list(DIR_ROT_Z)}

for _tid, _text, _lang, _seed in (
    ("L-NIFTI-001", "Export NIfTI and read it back; the geometry must be identical.", "en", 4160),
    ("L-NIFTI-002", "Export the volume as NIfTI and re-read it; spacing, origin and direction must round-trip.", "en", 4161),
):
    TASKS.append(_e(
        _doc(_tid, "nifti_export_geometry_fidelity",
             "After NIfTI export then re-read, spacing/origin/direction must be exactly identical.",
             fixture=PROSTATE, check="roundtrip_fidelity",
             derived="web/export_service.py:145-160 (_write_nifti: SetSpacing/SetOrigin/SetDirection)",
             turns=_turns(_text, _lang), contrast=_P2_CONTRAST,
             group_type="G-EQ", paraphrase=_P2_GROUP, seed=_seed,
             difficulty="easy", power_role="exploratory", probes=["paraphrase"]),
        _pos(_roundtrip("nifti", copy.deepcopy(_P2_FIRST), copy.deepcopy(_P2_FIRST),
                        copy.deepcopy(_P2_IND)),
             f"CI replay for {_tid}: NIfTI geometry preserved through export/re-read."),
        _neg(_roundtrip("nifti", copy.deepcopy(_P2_FIRST),
                        {**copy.deepcopy(_P2_FIRST), "direction": list(DIR_ROT_Z_T)},
                        copy.deepcopy(_P2_IND))),
        {"web:export_service": {"F": _ev(_tid, "roundtrip_fidelity"), "P": _ev(_tid)},
         "input": {"I": _ev(_tid, "roundtrip_fidelity")}},
    ))

TASKS.append(_e(
    _doc("L-NIFTI-003", "nifti_export_geometry_fidelity",
         "The anisotropic prostate spacing [0.68, 0.68, 5.0] must not be axis-reordered on export round-trip.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:152-154 (spacing copied from reference CT)",
         turns=_turns("Confirm the order of the three spacing components is not scrambled after exporting an anisotropic-slice CT."),
         contrast="L/nifti_export_geometry_fidelity/aniso_spacing", seed=4162),
    _pos(_roundtrip("nifti",
                    {"dims": [48, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [0.68, 0.68, 5.0], "direction": list(DIR_I),
                     "dtype": "int16"},
                    {"dims": [48, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [0.68, 0.68, 5.0], "direction": list(DIR_I),
                     "dtype": "int16"},
                    {"dims": [48, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [0.68, 0.68, 5.0], "direction": list(DIR_I)}),
         "CI replay for L-NIFTI-003: anisotropic spacing preserved."),
    _neg(_roundtrip("nifti",
                    {"dims": [48, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [0.68, 0.68, 5.0], "direction": list(DIR_I),
                     "dtype": "int16"},
                    {"dims": [48, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [0.68, 5.0, 0.68], "direction": list(DIR_I),
                     "dtype": "int16"},
                    {"dims": [48, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [0.68, 0.68, 5.0], "direction": list(DIR_I)})),
    {"web:export_service": {"E": _ev("L-NIFTI-003", "roundtrip_fidelity"),
                            "F": _ev("L-NIFTI-003")}},
))

TASKS.append(_e(
    _doc("L-NIFTI-004", "nifti_export_geometry_fidelity",
         "The rotated-frame direction matrix must not degenerate to the identity on export round-trip.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="web/export_service.py:154 (SetDirection(reference.GetDirection()))",
         turns=_turns("Export and re-read volume data with a rotated direction matrix; the direction must not be lost."),
         contrast="L/nifti_export_geometry_fidelity/rotation", seed=4163),
    _pos(_roundtrip("nifti",
                    {"dims": [8, 8, 8], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z),
                     "dtype": "float32"},
                    {"dims": [8, 8, 8], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z),
                     "dtype": "float32"},
                    {"dims": [8, 8, 8], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z)}),
         "CI replay for L-NIFTI-004: rotated direction matrix preserved."),
    _neg(_roundtrip("nifti",
                    {"dims": [8, 8, 8], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z),
                     "dtype": "float32"},
                    {"dims": [8, 8, 8], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_I),
                     "dtype": "float32"},
                    {"dims": [8, 8, 8], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z)})),
    {"web:export_service": {"E": _ev("L-NIFTI-004", "roundtrip_fidelity")},
     "input": {"I": _ev("L-NIFTI-004", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-NIFTI-005", "nifti_export_geometry_fidelity",
         "A negative LPS origin must not be flipped to an RAS sign on export round-trip.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:153 (SetOrigin(reference.GetOrigin()))",
         turns=_turns("When the origin has negative coordinates, the sign must not be flipped after export and re-read."),
         contrast="L/nifti_export_geometry_fidelity/origin_sign", seed=4164),
    _pos(_roundtrip("nifti",
                    {"dims": [16, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I),
                     "dtype": "float32"},
                    {"dims": [16, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I),
                     "dtype": "float32"},
                    {"dims": [16, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I)}),
         "CI replay for L-NIFTI-005: negative LPS origin sign preserved."),
    _neg(_roundtrip("nifti",
                    {"dims": [16, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I),
                     "dtype": "float32"},
                    {"dims": [16, 16, 16], "origin": [100.5, 120.25, -30.0],
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I),
                     "dtype": "float32"},
                    {"dims": [16, 16, 16], "origin": list(_G2_ORIGIN),
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I)})),
    {"web:export_service": {"E": _ev("L-NIFTI-005", "roundtrip_fidelity"),
                            "F": _ev("L-NIFTI-005")}},
))

TASKS.append(_e(
    _doc("L-NIFTI-006", "nifti_export_geometry_fidelity",
         "After dose-array export then re-read, values must be voxel-wise equal (float32 NIfTI has no quantisation rescaling).",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:835-841 (dose written as Gy NIfTI); 145-160",
         turns=_turns("Export the dose as NIfTI and read it back; the array values must be point-wise equal."),
         contrast="L/nifti_export_geometry_fidelity/dose_array", seed=4165),
    _pos(_roundtrip("nifti",
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0],
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I),
                     "dtype": "float32", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0],
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I),
                     "dtype": "float32", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0],
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I)}),
         "CI replay for L-NIFTI-006: dose array equal voxel-wise."),
    _neg(_roundtrip("nifti",
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0],
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I),
                     "dtype": "float32", "dose": copy.deepcopy(DOSE_BASE)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0],
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I),
                     "dtype": "float32", "dose": _dose(DOSE_BASE, 0.5)},
                    {"dims": [2, 2, 2], "origin": [0.0, 0.0, 0.0],
                     "spacing": [1.0, 1.0, 1.0], "direction": list(DIR_I)})),
    {"web:export_service": {"F": _ev("L-NIFTI-006", "roundtrip_fidelity"),
                            "E": _ev("L-NIFTI-006")},
     "dose_eval": {"F": _ev("L-NIFTI-006", "roundtrip_fidelity")}},
))

# ---------------------------------------------------------------------------
# nifti_metadata_query_fidelity: array_shape_zyx == reversed(size_xyz),
# spacing/origin exact, physical_extent == size*spacing
# (tool_factory/doc_reader/__init__.py:416-455)
# ---------------------------------------------------------------------------

_META_TRUTH = {
    "geometry": {
        "size_xyz": [16, 24, 8],
        "array_shape_zyx": [8, 24, 16],
        "spacing": [0.5, 1.0, 2.0],
        "origin": list(_G2_ORIGIN),
    },
    "numbers": {"physical_extent_mm_xyz": [8.0, 24.0, 16.0], "voxel_count": 3072},
}

TASKS.append(_e(
    _doc("L-NIFTI-010", "nifti_metadata_query_fidelity",
         "The metadata query's array_shape_zyx must equal reversed(size_xyz).",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/doc_reader/__init__.py:430 (array_shape_zyx = list(reversed(size_xyz)))",
         turns=_turns("When querying NIfTI metadata, the zyx shape must be the reverse of the xyz size."),
         contrast="L/nifti_metadata_query_fidelity/axis_order", seed=4166,
         difficulty="hard"),
    _pos(_roundtrip("generic", copy.deepcopy(_META_TRUTH), copy.deepcopy(_META_TRUTH),
                    copy.deepcopy(_META_TRUTH)),
         "CI replay for L-NIFTI-010: array_shape_zyx == reversed(size_xyz)."),
    _neg(_roundtrip("generic",
                    copy.deepcopy(_META_TRUTH),
                    {**copy.deepcopy(_META_TRUTH),
                     "geometry": {**copy.deepcopy(_META_TRUTH["geometry"]),
                                  "array_shape_zyx": [16, 24, 8]}},
                    copy.deepcopy(_META_TRUTH))),
    {"doc_reader": {"E": _ev("L-NIFTI-010", "roundtrip_fidelity"),
                    "F": _ev("L-NIFTI-010")}},
))

TASKS.append(_e(
    _doc("L-NIFTI-011", "nifti_metadata_query_fidelity",
         "physical_extent_mm_xyz must equal size_xyz * spacing.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/doc_reader/__init__.py:451-453 (physical_extent_mm_xyz = size*spacing)",
         turns=_turns("Verify the physical extent in the metadata equals size times spacing."),
         contrast="L/nifti_metadata_query_fidelity/extent", seed=4167),
    _pos(_roundtrip("generic", copy.deepcopy(_META_TRUTH), copy.deepcopy(_META_TRUTH),
                    copy.deepcopy(_META_TRUTH)),
         "CI replay for L-NIFTI-011: physical_extent == size*spacing."),
    _neg(_roundtrip("generic",
                    copy.deepcopy(_META_TRUTH),
                    {**copy.deepcopy(_META_TRUTH),
                     "numbers": {"physical_extent_mm_xyz": [8.0, 24.0, 32.0],
                                 "voxel_count": 3072}},
                    copy.deepcopy(_META_TRUTH))),
    {"doc_reader": {"F": _ev("L-NIFTI-011", "roundtrip_fidelity"),
                    "R": _ev("L-NIFTI-011")}},
))

TASKS.append(_e(
    _doc("L-NIFTI-050", "nifti_export_geometry_fidelity",
         "Multi-turn: first export the dose as NIfTI, then follow up to verify the geometry is identical.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:145-160",
         turns=_multi_turns("Export the dose distribution as NIfTI.",
                            "Read it back and confirm spacing, origin and direction are all identical."),
         contrast="L/nifti_export_geometry_fidelity/multiturn", seed=4168,
         mode="multi_turn", power_role="exploratory", probes=["multi_turn"]),
    _pos(_roundtrip("nifti", copy.deepcopy(_P2_FIRST), copy.deepcopy(_P2_FIRST),
                    copy.deepcopy(_P2_IND)),
         "CI replay for L-NIFTI-050: 2-turn NIfTI export then geometry verify."),
    _neg(_roundtrip("nifti", copy.deepcopy(_P2_FIRST),
                    {**copy.deepcopy(_P2_FIRST), "spacing": [0.68, 5.0, 0.68]},
                    copy.deepcopy(_P2_IND))),
    {"web:export_service": {"F": _ev("L-NIFTI-050", "roundtrip_fidelity"),
                            "R": _ev("L-NIFTI-050")},
     "input": {"I": _ev("L-NIFTI-050", "roundtrip_fidelity")}},
))

# ---------------------------------------------------------------------------
# mask_format_alignment_invariant: .nii.gz/.mha/.nrrd + rotated frame all
# align identically, no mirror/translate
# (tool_factory/segmentation_alignment.py:94-128)
# ---------------------------------------------------------------------------

_HDR_G2 = {"origin": list(_G2_ORIGIN), "spacing": [1.0, 1.0, 2.0], "direction": list(DIR_I)}

TASKS.append(_e(
    _doc("L-MASK-001", "mask_format_alignment_invariant",
         "The same mask loaded and aligned from .nii.gz and .mha must have identical geometry headers and must not be translated.",
         fixture=PROSTATE, check="coord_roundtrip",
         constraint_class="none",
         derived="tool_factory/segmentation_alignment.py:94-128 (align_label_image_to_reference)",
         turns=_turns("Save the same mask as nii.gz and mha, then align; the geometry headers must be exactly identical."),
         contrast="L/mask_format_alignment/containers", seed=4170),
    _pos(_coord(samples=[[0, 0, 0], [1, 2, 3]], origin=list(_G2_ORIGIN),
                spacing=[1.0, 1.0, 2.0], direction=list(DIR_I),
                header_a=copy.deepcopy(_HDR_G2), header_b=copy.deepcopy(_HDR_G2)),
         "CI replay for L-MASK-001: .nii.gz and .mha headers agree after alignment."),
    _neg(_coord(samples=[[0, 0, 0], [1, 2, 3]], origin=list(_G2_ORIGIN),
                spacing=[1.0, 1.0, 2.0], direction=list(DIR_I),
                header_a=copy.deepcopy(_HDR_G2),
                header_b={"origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 2.0],
                          "direction": list(DIR_I)})),
    {"image_processing": {"F": _ev("L-MASK-001", "coord_roundtrip"),
                          "R": _ev("L-MASK-001")}},
))

TASKS.append(_e(
    _doc("L-MASK-002", "mask_format_alignment_invariant",
         "The direction of a rotated-frame .nrrd mask must match the reference after alignment (it must not be treated as identity).",
         fixture=INTEROP, check="coord_roundtrip",
         constraint_class="none",
         derived="tool_factory/segmentation_alignment.py:107-115 (DICOMOrient + Resample onto reference)",
         turns=_turns("After aligning an nrrd mask in a rotated coordinate frame, the direction matrix must match the reference."),
         contrast="L/mask_format_alignment/rotated_frame", seed=4171),
    _pos(_coord(samples=[[1, 1, 2]], origin=[12.0, 20.0, 30.0], spacing=[1.5, 1.5, 2.0],
                direction=list(DIR_ROT_Z),
                header_a={"origin": [12.0, 20.0, 30.0], "spacing": [1.5, 1.5, 2.0],
                          "direction": list(DIR_ROT_Z)},
                header_b={"origin": [12.0, 20.0, 30.0], "spacing": [1.5, 1.5, 2.0],
                          "direction": list(DIR_ROT_Z)}),
         "CI replay for L-MASK-002: rotated-frame .nrrd direction matches the reference."),
    _neg(_coord(samples=[[1, 1, 2]], origin=[12.0, 20.0, 30.0], spacing=[1.5, 1.5, 2.0],
                direction=list(DIR_ROT_Z),
                header_a={"origin": [12.0, 20.0, 30.0], "spacing": [1.5, 1.5, 2.0],
                          "direction": list(DIR_ROT_Z)},
                header_b={"origin": [12.0, 20.0, 30.0], "spacing": [1.5, 1.5, 2.0],
                          "direction": list(DIR_I)})),
    {"image_processing": {"E": _ev("L-MASK-002", "coord_roundtrip"),
                          "F": _ev("L-MASK-002")}},
))

TASKS.append(_e(
    _doc("L-MASK-003", "mask_format_alignment_invariant",
         "Cross-container alignment forbids mirroring: direction must be a proper rotation (det=+1).",
         fixture=INTEROP, check="coord_roundtrip",
         constraint_class="none",
         derived="tool_factory/segmentation_alignment.py:94-101 (no silent mirror); oracles/coord_roundtrip.py:83-90 (direction_reflection)",
         turns=_turns("The aligned mask must not be mirrored left-to-right; the direction matrix must be a proper rotation."),
         contrast="L/mask_format_alignment/no_mirror", seed=4172,
         difficulty="hard", probes=["mirror"]),
    _pos(_coord(samples=[[1, 2, 3]], origin=[0.0, 0.0, 0.0], spacing=[1.0, 1.0, 1.0],
                direction=list(DIR_ROT_Z)),
         "CI replay for L-MASK-003: direction is a proper rotation (det=+1)."),
    _neg(_coord(samples=[[1, 2, 3]], origin=[0.0, 0.0, 0.0], spacing=[1.0, 1.0, 1.0],
                direction=list(DIR_MIRROR_X))),
    {"image_processing": {"E": _ev("L-MASK-003", "coord_roundtrip"),
                          "R": _ev("L-MASK-003")}},
))

TASKS.append(_e(
    _doc("L-MASK-004", "mask_format_alignment_invariant",
         "Cross-container alignment forbids translation: the origin/spacing/direction of .nii.gz/.nrrd must be semantically equal.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="tool_factory/segmentation_alignment.py:112-120 (Resample with identity transform onto reference grid)",
         turns=_turns("The mask geometry read from the two containers must be semantically identical and must not be translated as a whole."),
         contrast="L/mask_format_alignment/no_translate", seed=4173,
         probes=["translate"]),
    _pos(_roundtrip("generic",
                    {"geometry": copy.deepcopy(_HDR_G2)},
                    {"geometry": copy.deepcopy(_HDR_G2)},
                    {"geometry": copy.deepcopy(_HDR_G2)}),
         "CI replay for L-MASK-004: mask geometry identical across containers."),
    _neg(_roundtrip("generic",
                    {"geometry": copy.deepcopy(_HDR_G2)},
                    {"geometry": {**copy.deepcopy(_HDR_G2),
                                  "origin": [-99.5, -120.25, 30.0]}},
                    {"geometry": copy.deepcopy(_HDR_G2)})),
    {"image_processing": {"F": _ev("L-MASK-004", "roundtrip_fidelity"),
                          "E": _ev("L-MASK-004")}},
))

TASKS.append(_e(
    _doc("L-MASK-005", "mask_format_alignment_invariant",
         "Spacing scaling mixed into direction (a broken affine split) must fail.",
         fixture=INTEROP, check="coord_roundtrip",
         constraint_class="none",
         derived="tool_factory/segmentation_alignment.py:3,94-101 (arrays carry no affine; scaled direction = broken affine split); oracles/coord_roundtrip.py:67-80",
         turns=_turns("If spacing scaling is mixed into the direction matrix, it must be treated as a geometry error."),
         contrast="L/mask_format_alignment/scaled_direction", seed=4174,
         difficulty="hard"),
    _pos(_coord(samples=[[1, 1, 1]], origin=[0.0, 0.0, 0.0], spacing=[2.0, 2.0, 2.0],
                direction=list(DIR_I)),
         "CI replay for L-MASK-005: direction orthonormal with spacing kept separate."),
    _neg(_coord(samples=[[1, 1, 1]], origin=[0.0, 0.0, 0.0], spacing=[2.0, 2.0, 2.0],
                direction=list(DIR_SCALED2))),
    {"image_processing": {"E": _ev("L-MASK-005", "coord_roundtrip"),
                          "R": _ev("L-MASK-005")}},
))

TASKS.append(_e(
    _doc("L-MASK-006", "mask_format_alignment_invariant",
         "Mask alignment is a read-only operation and must never rewrite seed coordinates in the plan.",
         fixture=PROSTATE, check="pred", predicate="plan_seeds_unchanged",
         constraint_class="invariant",
         derived="tool_factory/segmentation_alignment.py:122-128; oracles/predicates.py:178-180 (plan_seeds_unchanged)",
         turns=_turns("Do not touch the seed positions in the plan when aligning a mask."),
         contrast="L/mask_format_alignment/seeds_untouched", seed=4175,
         metric="pred_pass", power_role="safety_gate"),
    _pos_state({"plan": {"status": "final", "planning_version": 7,
                         "seeds": copy.deepcopy(_PROSTATE_SEEDS)}},
               "CI replay for L-MASK-006: alignment leaves plan.seeds untouched."),
    _neg_state({"plan": {"status": "final", "planning_version": 7,
                         "seeds": copy.deepcopy(_PROSTATE_SEEDS_METRES)}}),
    {"image_processing": {"R": _ev("L-MASK-006")},
     "seed_plan": {"R": _ev("L-MASK-006")},
     "safety:authorization": {"S": _ev("L-MASK-006")}},
))

# ---------------------------------------------------------------------------
# label_selection_provenance: multi-label exact select; 255 sole-positive
# fallback; missing label in multi-label raises, never merges
# (tool_factory/segmentation_alignment.py:35-91)
# ---------------------------------------------------------------------------

TASKS.append(_e(
    _doc("L-LABEL-001", "label_selection_provenance",
         "Multi-label exact selection: only the target label must be selected and the source-label manifest recorded; the round-trip must not merge foreground classes.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/segmentation_alignment.py:35-91 (select_label_as_binary provenance: requested/selected/source_labels/counts)",
         turns=_turns("In a multi-label file, extract only the target label, record the full source-label manifest, and do not merge foreground classes."),
         contrast="L/label_selection/exact_select", seed=4180),
    _pos(_roundtrip("generic",
                    {"labels": {"requested_target_value": 1, "selected_target_value": 1,
                                "source_labels": [1, 2], "selected_voxel_count": 500},
                     "numbers": {"source_label_counts": {"1": 500, "2": 300}}},
                    {"labels": {"requested_target_value": 1, "selected_target_value": 1,
                                "source_labels": [1, 2], "selected_voxel_count": 500},
                     "numbers": {"source_label_counts": {"1": 500, "2": 300}}},
                    {"labels": {"requested_target_value": 1, "selected_target_value": 1,
                                "source_labels": [1, 2], "selected_voxel_count": 500},
                     "numbers": {"source_label_counts": {"1": 500, "2": 300}}}),
         "CI replay for L-LABEL-001: exact label selection and provenance preserved."),
    _neg(_roundtrip("generic",
                    {"labels": {"requested_target_value": 1, "selected_target_value": 1,
                                "source_labels": [1, 2], "selected_voxel_count": 500},
                     "numbers": {"source_label_counts": {"1": 500, "2": 300}}},
                    {"labels": {"requested_target_value": 1, "selected_target_value": 1,
                                "source_labels": [1, 2], "selected_voxel_count": 800},
                     "numbers": {"source_label_counts": {"1": 500, "2": 300}}},
                    {"labels": {"requested_target_value": 1, "selected_target_value": 1,
                                "source_labels": [1, 2], "selected_voxel_count": 500},
                     "numbers": {"source_label_counts": {"1": 500, "2": 300}}})),
    {"image_processing": {"F": _ev("L-LABEL-001", "roundtrip_fidelity"),
                          "E": _ev("L-LABEL-001")},
     "input": {"I": _ev("L-LABEL-001", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-LABEL-002", "label_selection_provenance",
         "A sole positive label of 255 must be selected as a fallback (a common binary-255 encoding) and must not yield an empty selection.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="tool_factory/segmentation_alignment.py:48-50,70-73 (sole-positive 255 fallback)",
         turns=_turns("When the only positive label in the mask is 255, select it automatically rather than an empty set."),
         contrast="L/label_selection/fallback_255", seed=4181,
         difficulty="hard", probes=["fallback"]),
    _pos(_roundtrip("generic",
                    {"labels": {"requested_target_value": 1, "selected_target_value": 255,
                                "source_labels": [255], "selected_voxel_count": 480}},
                    {"labels": {"requested_target_value": 1, "selected_target_value": 255,
                                "source_labels": [255], "selected_voxel_count": 480}},
                    {"labels": {"requested_target_value": 1, "selected_target_value": 255,
                                "source_labels": [255], "selected_voxel_count": 480}}),
         "CI replay for L-LABEL-002: 255 sole-positive fallback preserved."),
    _neg(_roundtrip("generic",
                    {"labels": {"requested_target_value": 1, "selected_target_value": 255,
                                "source_labels": [255], "selected_voxel_count": 480}},
                    {"labels": {"requested_target_value": 1, "selected_target_value": 1,
                                "source_labels": [255], "selected_voxel_count": 0}},
                    {"labels": {"requested_target_value": 1, "selected_target_value": 255,
                                "source_labels": [255], "selected_voxel_count": 480}})),
    {"image_processing": {"E": _ev("L-LABEL-002", "roundtrip_fidelity"),
                          "F": _ev("L-LABEL-002")}},
))

TASKS.append(_e(
    _doc("L-LABEL-003", "label_selection_provenance",
         "A missing target label in a multi-label image must raise and leave the state unchanged; merging foreground classes is never allowed.",
         fixture=INTEROP, check="state_invariant",
         derived="tool_factory/segmentation_alignment.py:74-80 (missing label in multi-label raises, never merges)",
         turns=_turns("When the target label is not found in a multi-label image, raise an error instead of collapsing all foreground classes into one."),
         contrast="L/label_selection/missing_label_fail_closed", seed=4182,
         power_role="safety_gate", probes=["fail_closed"]),
    _pos(_invariant(copy.deepcopy(_STATE_LABEL), copy.deepcopy(_STATE_LABEL)),
         "CI replay for L-LABEL-003: missing-label failure leaves state unmerged."),
    _neg(_invariant(
        copy.deepcopy(_STATE_LABEL),
        {**copy.deepcopy(_STATE_LABEL),
         "segmentation": {"ctv_manual": {"merged_foreground": True,
                                         "source_labels": [1, 2],
                                         "selected_voxel_count": 800}}})),
    {"image_processing": {"R": _ev("L-LABEL-003")},
     "safety:authorization": {"S": _ev("L-LABEL-003", "state_invariant")}},
))

# ---------------------------------------------------------------------------
# ct_container_equivalence: CT as NIfTI/MHA/NRRD/DICOM -> same LPI
# spacing/origin/direction + voxels (utils/ct_volume.py:10-111)
# ---------------------------------------------------------------------------

TASKS.append(_e(
    _doc("L-CT-001", "ct_container_equivalence",
         "The same CT loaded as NIfTI and MHA must yield identical LPI geometry.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="utils/ct_volume.py:10-111 (normalize_ct_image preserves spacing/origin/direction)",
         turns=_turns("Load the same CT stored as NIfTI and MHA; the LPI geometry must be the same."),
         contrast="L/ct_container/nifti_mha", seed=4190),
    _pos(_roundtrip("generic",
                    {"geometry": {"origin": list(_G2_ORIGIN),
                                  "spacing": [0.68, 0.68, 5.0],
                                  "direction": list(DIR_I)}},
                    {"geometry": {"origin": list(_G2_ORIGIN),
                                  "spacing": [0.68, 0.68, 5.0],
                                  "direction": list(DIR_I)}},
                    {"geometry": {"origin": list(_G2_ORIGIN),
                                  "spacing": [0.68, 0.68, 5.0],
                                  "direction": list(DIR_I)}}),
         "CI replay for L-CT-001: NIfTI and MHA give identical LPI geometry."),
    _neg(_roundtrip("generic",
                    {"geometry": {"origin": list(_G2_ORIGIN),
                                  "spacing": [0.68, 0.68, 5.0],
                                  "direction": list(DIR_I)}},
                    {"geometry": {"origin": [0.0, 0.0, 0.0],
                                  "spacing": [0.68, 0.68, 5.0],
                                  "direction": list(DIR_I)}},
                    {"geometry": {"origin": list(_G2_ORIGIN),
                                  "spacing": [0.68, 0.68, 5.0],
                                  "direction": list(DIR_I)}})),
    {"input": {"I": _ev("L-CT-001", "roundtrip_fidelity"), "F": _ev("L-CT-001")}},
))

TASKS.append(_e(
    _doc("L-CT-002", "ct_container_equivalence",
         "Loading the same CT as NRRD and DICOM must both be LPI, with no RAS flip.",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="utils/ct_volume.py:10-111 (container-agnostic LPI normalisation)",
         turns=_turns("Load the same CT as NRRD and DICOM; both coordinate conventions must be LPI."),
         contrast="L/ct_container/nrrd_dicom", seed=4191),
    _pos(_roundtrip("generic",
                    {"geometry": {"origin": [12.0, 20.0, 30.0],
                                  "spacing": [1.5, 1.5, 2.0],
                                  "direction": list(DIR_I)}},
                    {"geometry": {"origin": [12.0, 20.0, 30.0],
                                  "spacing": [1.5, 1.5, 2.0],
                                  "direction": list(DIR_I)}},
                    {"geometry": {"origin": [12.0, 20.0, 30.0],
                                  "spacing": [1.5, 1.5, 2.0],
                                  "direction": list(DIR_I)}}),
         "CI replay for L-CT-002: NRRD and DICOM agree on LPI geometry."),
    _neg(_roundtrip("generic",
                    {"geometry": {"origin": [12.0, 20.0, 30.0],
                                  "spacing": [1.5, 1.5, 2.0],
                                  "direction": list(DIR_I)}},
                    {"geometry": {"origin": [12.0, 20.0, 30.0],
                                  "spacing": [1.5, 1.5, 2.0],
                                  "direction": list(DIR_MIRROR_X)}},
                    {"geometry": {"origin": [12.0, 20.0, 30.0],
                                  "spacing": [1.5, 1.5, 2.0],
                                  "direction": list(DIR_I)}})),
    {"input": {"I": _ev("L-CT-002", "roundtrip_fidelity"), "E": _ev("L-CT-002")}},
))

TASKS.append(_e(
    _doc("L-CT-003", "ct_container_equivalence",
         "The CT voxel content read across containers must be identical (axes and statistics must not be transposed).",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="utils/ct_volume.py:10-111 (same voxels after normalisation)",
         turns=_turns("The CT voxel data read from different containers must be exactly identical."),
         contrast="L/ct_container/voxels", seed=4192,
         difficulty="hard"),
    _pos(_roundtrip("generic",
                    {"labels": {"axis_sums": [1024.0, 2048.0, 4096.0],
                                "dims": [16, 16, 16], "voxel_count": 4096}},
                    {"labels": {"axis_sums": [1024.0, 2048.0, 4096.0],
                                "dims": [16, 16, 16], "voxel_count": 4096}},
                    {"labels": {"axis_sums": [1024.0, 2048.0, 4096.0],
                                "dims": [16, 16, 16], "voxel_count": 4096}}),
         "CI replay for L-CT-003: voxel content identical across containers."),
    _neg(_roundtrip("generic",
                    {"labels": {"axis_sums": [1024.0, 2048.0, 4096.0],
                                "dims": [16, 16, 16], "voxel_count": 4096}},
                    {"labels": {"axis_sums": [2048.0, 1024.0, 4096.0],
                                "dims": [16, 16, 16], "voxel_count": 4096}},
                    {"labels": {"axis_sums": [1024.0, 2048.0, 4096.0],
                                "dims": [16, 16, 16], "voxel_count": 4096}})),
    {"input": {"I": _ev("L-CT-003", "roundtrip_fidelity"), "E": _ev("L-CT-003")}},
))

# ---------------------------------------------------------------------------
# fourd_ct_frame_geometry: 4D->frame0 geometry preserved; 5D raises
# (utils/ct_volume.py:81-108)
# ---------------------------------------------------------------------------

TASKS.append(_e(
    _doc("L-CT-004", "fourd_ct_frame_geometry",
         "Extracting frame 0 of a 4D CT must preserve the geometry as-is (Extract must not drop direction).",
         fixture=INTEROP, check="roundtrip_fidelity",
         derived="utils/ct_volume.py:81-108 (4-D frame extraction preserves spacing/origin/direction)",
         turns=_turns("After extracting frame 0 of a 4D CT, the geometry must exactly match the source frame."),
         contrast="L/fourd_ct/frame0_geometry", seed=4193),
    _pos(_roundtrip("nifti",
                    {"dims": [8, 8, 4], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z),
                     "dtype": "int16"},
                    {"dims": [8, 8, 4], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z),
                     "dtype": "int16"},
                    {"dims": [8, 8, 4], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z)}),
         "CI replay for L-CT-004: frame-0 geometry preserved after 4-D extraction."),
    _neg(_roundtrip("nifti",
                    {"dims": [8, 8, 4], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z),
                     "dtype": "int16"},
                    {"dims": [8, 8, 4], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_I),
                     "dtype": "int16"},
                    {"dims": [8, 8, 4], "origin": [12.0, 20.0, 30.0],
                     "spacing": [1.5, 1.5, 2.0], "direction": list(DIR_ROT_Z)})),
    {"input": {"I": _ev("L-CT-004", "roundtrip_fidelity"), "E": _ev("L-CT-004")}},
))

TASKS.append(_e(
    _doc("L-CT-005", "fourd_ct_frame_geometry",
         "5D data must be rejected with an error and must not leave half-initialised volume data.",
         fixture=INTEROP, check="state_invariant",
         derived="utils/ct_volume.py:81-86 (5-D raises an actionable ValueError)",
         turns=_turns("5D data must be explicitly rejected with an error and must not leave a half-initialised state."),
         contrast="L/fourd_ct/five_d_rejected", seed=4194,
         power_role="safety_gate", probes=["fail_closed"]),
    _pos(_invariant(copy.deepcopy(_STATE_CT), copy.deepcopy(_STATE_CT)),
         "CI replay for L-CT-005: 5-D rejection leaves state intact."),
    _neg(_invariant(
        copy.deepcopy(_STATE_CT),
        {**copy.deepcopy(_STATE_CT),
         "case": {"id": "interop_case",
                  "ct": {"loaded": False, "dims": [8, 8, 4, 2, 2], "source_dimension": 5,
                         "partial_frame": [0, 0, 0]}}})),
    {"input": {"S": _ev("L-CT-005", "state_invariant"), "R": _ev("L-CT-005")}},
))

# ---------------------------------------------------------------------------
# affine_physical_correspondence: label at physical (14,23,34) -> CT index
# (1,1,2); headers agree after affine-aware resample
# (tool_factory/OAR_seg/totalsegmentator_oar.py:39-58,663)
# ---------------------------------------------------------------------------

_AFF_HDR = {"origin": [12.0, 20.0, 30.0], "spacing": [2.0, 3.0, 2.0],
            "direction": list(DIR_I)}

TASKS.append(_e(
    _doc("L-COORD-001", "affine_physical_correspondence",
         "Physical point (14,23,34) must map to CT voxel (1,1,2) (origin 12/20/30, spacing 2/3/2), and the label header must match the CT header.",
         fixture=INTEROP, check="coord_roundtrip",
         constraint_class="none",
         derived="tool_factory/OAR_seg/totalsegmentator_oar.py:39-58,663 (restore via NIfTI affine; phys (14,23,34) -> index (1,1,2))",
         turns=_turns("Confirm physical coordinate (14,23,34) falls on CT voxel (1,1,2) and the label affine matches the CT."),
         contrast="L/affine_correspondence/index_mapping", seed=4200),
    _pos(_coord(samples=[[1, 1, 2], [0, 0, 0], [2, 3, 1]],
                origin=[12.0, 20.0, 30.0], spacing=[2.0, 3.0, 2.0], direction=list(DIR_I),
                header_a=copy.deepcopy(_AFF_HDR), header_b=copy.deepcopy(_AFF_HDR)),
         "CI replay for L-COORD-001: physical (14,23,34) <-> voxel (1,1,2), headers agree."),
    _neg(_coord(samples=[[1, 1, 2], [0, 0, 0], [2, 3, 1]],
                origin=[12.0, 20.0, 30.0], spacing=[2.0, 3.0, 2.0], direction=list(DIR_I),
                header_a=copy.deepcopy(_AFF_HDR),
                header_b={"origin": [0.0, 0.0, 0.0], "spacing": [2.0, 3.0, 2.0],
                          "direction": list(DIR_I)})),
    {"image_processing": {"F": _ev("L-COORD-001", "coord_roundtrip"),
                          "E": _ev("L-COORD-001")},
     "input": {"I": _ev("L-COORD-001", "coord_roundtrip")}},
))

TASKS.append(_e(
    _doc("L-COORD-002", "affine_physical_correspondence",
         "After resampling a rotated frame, the label header direction must retain the rotation and must not be canonicalised to identity.",
         fixture=INTEROP, check="coord_roundtrip",
         constraint_class="none",
         derived="tool_factory/OAR_seg/totalsegmentator_oar.py:663-668 (canonicalised output must be reoriented through the affine)",
         turns=_turns("After resampling a rotated-frame label, the rotation in the direction matrix must not be lost."),
         contrast="L/affine_correspondence/rotation", seed=4201),
    _pos(_coord(samples=[[1, 1, 2]], origin=[12.0, 20.0, 30.0], spacing=[1.5, 1.5, 2.0],
                direction=list(DIR_ROT_Z),
                header_a={"origin": [12.0, 20.0, 30.0], "spacing": [1.5, 1.5, 2.0],
                          "direction": list(DIR_ROT_Z)},
                header_b={"origin": [12.0, 20.0, 30.0], "spacing": [1.5, 1.5, 2.0],
                          "direction": list(DIR_ROT_Z)}),
         "CI replay for L-COORD-002: rotated-frame label header matches the CT."),
    _neg(_coord(samples=[[1, 1, 2]], origin=[12.0, 20.0, 30.0], spacing=[1.5, 1.5, 2.0],
                direction=list(DIR_ROT_Z),
                header_a={"origin": [12.0, 20.0, 30.0], "spacing": [1.5, 1.5, 2.0],
                          "direction": list(DIR_ROT_Z)},
                header_b={"origin": [12.0, 20.0, 30.0], "spacing": [1.5, 1.5, 2.0],
                          "direction": list(DIR_I)})),
    {"image_processing": {"E": _ev("L-COORD-002", "coord_roundtrip"),
                          "F": _ev("L-COORD-002")}},
))

TASKS.append(_e(
    _doc("L-COORD-003", "affine_physical_correspondence",
         "A broken affine split (spacing mixed into the header) must be caught by header_spacing_mismatch.",
         fixture=INTEROP, check="coord_roundtrip",
         constraint_class="none",
         derived="tool_factory/OAR_seg/totalsegmentator_oar.py:39-52 (affine split must keep spacing out of the header); oracles/coord_roundtrip.py:117-144",
         turns=_turns("After the affine split, the label spacing must match the CT and must not become unit spacing."),
         contrast="L/affine_correspondence/spacing_split", seed=4202,
         difficulty="hard"),
    _pos(_coord(samples=[[1, 1, 2]], origin=[12.0, 20.0, 30.0], spacing=[2.0, 3.0, 2.0],
                direction=list(DIR_I),
                header_a=copy.deepcopy(_AFF_HDR), header_b=copy.deepcopy(_AFF_HDR)),
         "CI replay for L-COORD-003: affine-split spacing agrees with the CT header."),
    _neg(_coord(samples=[[1, 1, 2]], origin=[12.0, 20.0, 30.0], spacing=[2.0, 3.0, 2.0],
                direction=list(DIR_I),
                header_a=copy.deepcopy(_AFF_HDR),
                header_b={"origin": [12.0, 20.0, 30.0], "spacing": [1.0, 1.0, 1.0],
                          "direction": list(DIR_I)})),
    {"image_processing": {"E": _ev("L-COORD-003", "coord_roundtrip"),
                          "R": _ev("L-COORD-003")}},
))

TASKS.append(_e(
    _doc("L-COORD-004", "coord_semantics_roundtrip",
         "Origin tolerance edge: a micron-level floating-point difference must pass, while a 0.5 mm drift must fail.",
         fixture=INTEROP, check="coord_roundtrip",
         constraint_class="none",
         derived="oracles/coord_roundtrip.py:132-144 (SPATIAL_ORIGIN_TOL_MM = 1e-4)",
         turns=_turns("Judge the origin comparison right at the 1e-4 mm tolerance boundary."),
         contrast="L/coord_semantics/origin_tolerance_edge", seed=4203,
         difficulty="hard", probes=["tolerance_edge"]),
    _pos(_coord(samples=[[1, 1, 2]], origin=[12.0, 20.0, 30.0], spacing=[2.0, 3.0, 2.0],
                direction=list(DIR_I),
                header_a=copy.deepcopy(_AFF_HDR),
                header_b={"origin": [12.00005, 20.0, 30.0], "spacing": [2.0, 3.0, 2.0],
                          "direction": list(DIR_I)}),
         "CI replay for L-COORD-004: 5e-5 mm origin jitter is inside the 1e-4 mm tolerance."),
    _neg(_coord(samples=[[1, 1, 2]], origin=[12.0, 20.0, 30.0], spacing=[2.0, 3.0, 2.0],
                direction=list(DIR_I),
                header_a=copy.deepcopy(_AFF_HDR),
                header_b={"origin": [12.5, 20.0, 30.0], "spacing": [2.0, 3.0, 2.0],
                          "direction": list(DIR_I)})),
    {"image_processing": {"E": _ev("L-COORD-004", "coord_roundtrip")},
     "input": {"E": _ev("L-COORD-004", "coord_roundtrip"), "I": _ev("L-COORD-004")}},
))

# ---------------------------------------------------------------------------
# planning_json_lps_contract: coordinate_system "LPS", length_mm == |end-start|,
# unit direction (web/export_service.py:269-333,829-835)
# ---------------------------------------------------------------------------

_P3_GROUP = "L-JSON-001-P01"
_P3_CONTRAST = "L/planning_json_lps_contract"
_P3_OK = [{"format": "json", "path": "planning_parameters.json",
           "parsed": {"schema_valid": True, "coordinate_system": "LPS"}}]
_P3_BAD = [{"format": "json", "path": "planning_parameters.json",
            "parsed": {"schema_valid": False, "coordinate_system": "LPS",
                       "defect": "length_mm != |end-start|"}}]

for _tid, _text, _lang, _seed in (
    ("L-JSON-001", "Export the planning parameters as JSON; the coordinate system must be LPS with self-consistent length and direction.", "en", 4210),
    ("L-JSON-002", "Export the planning parameters as JSON; it must be LPS with self-consistent length and direction.", "en", 4211),
):
    TASKS.append(_e(
        _doc(_tid, "planning_json_lps_contract",
             "The planning JSON must pass the LPS contract schema check (length == |end-start|, unit direction).",
             fixture=PROSTATE, check="export_artifact_validity",
             derived="web/export_service.py:269-333,829-835 (coordinate_system LPS, length_mm == |end-start|, unit direction)",
             turns=_turns(_text, _lang), contrast=_P3_CONTRAST,
             group_type="G-EQ", paraphrase=_P3_GROUP, seed=_seed,
             difficulty="easy", power_role="exploratory", probes=["paraphrase"]),
        _pos(_export(copy.deepcopy(_P3_OK)),
             f"CI replay for {_tid}: planning JSON passes the LPS contract schema."),
        _neg(_export(copy.deepcopy(_P3_BAD))),
        {"web:export_service": {"F": _ev(_tid, "export_artifact_validity"),
                                "P": _ev(_tid), "E": _ev(_tid)}},
    ))

_NEEDLE_GOOD = {"needle_0": {"start_point": [12.0, 24.0, 24.0], "end_point": [12.0, 24.0, 74.0],
                             "direction": [0.0, 0.0, 1.0], "length_mm": 50.0,
                             "coordinate_system": "LPS"}}

TASKS.append(_e(
    _doc("L-JSON-003", "planning_json_lps_contract",
         "The needle record's length_mm must equal |end-start| and must not be hard-coded to 150.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:269-298 (_normalized_needles: length = norm(end-start), unit direction)",
         turns=_turns("In the exported needle record, length_mm must equal the norm of end minus start."),
         contrast="L/planning_json_lps_contract/needle_length", seed=4212),
    _pos(_roundtrip("generic",
                    {"geometry": copy.deepcopy(_NEEDLE_GOOD)},
                    {"geometry": copy.deepcopy(_NEEDLE_GOOD)},
                    {"geometry": copy.deepcopy(_NEEDLE_GOOD)}),
         "CI replay for L-JSON-003: needle length_mm == |end-start| = 50.0."),
    _neg(_roundtrip("generic",
                    {"geometry": copy.deepcopy(_NEEDLE_GOOD)},
                    {"geometry": {"needle_0": {**copy.deepcopy(_NEEDLE_GOOD["needle_0"]),
                                               "length_mm": 150.0}}},
                    {"geometry": copy.deepcopy(_NEEDLE_GOOD)})),
    {"web:export_service": {"F": _ev("L-JSON-003", "roundtrip_fidelity"),
                            "E": _ev("L-JSON-003")},
     "seed_plan": {"F": _ev("L-JSON-003", "roundtrip_fidelity")}},
))

_SEED_GOOD = {"seed_0": {"position": [12.0, 24.0, 30.0], "direction": [0.0, 0.0, 1.0],
                         "coordinate_system": "LPS"}}

TASKS.append(_e(
    _doc("L-JSON-004", "planning_json_lps_contract",
         "The seed record's direction must be a unit vector with an LPS coordinate system.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:300-333 (_normalized_seeds: unit direction, coordinate_system LPS)",
         turns=_turns("In the exported seed record, the direction must be a unit vector and the coordinate system labelled LPS."),
         contrast="L/planning_json_lps_contract/seed_direction", seed=4213),
    _pos(_roundtrip("generic",
                    {"geometry": copy.deepcopy(_SEED_GOOD)},
                    {"geometry": copy.deepcopy(_SEED_GOOD)},
                    {"geometry": copy.deepcopy(_SEED_GOOD)}),
         "CI replay for L-JSON-004: seed direction is a unit vector in LPS."),
    _neg(_roundtrip("generic",
                    {"geometry": copy.deepcopy(_SEED_GOOD)},
                    {"geometry": {"seed_0": {**copy.deepcopy(_SEED_GOOD["seed_0"]),
                                             "direction": [0.0, 0.0, 2.0]}}},
                    {"geometry": copy.deepcopy(_SEED_GOOD)})),
    {"web:export_service": {"F": _ev("L-JSON-004", "roundtrip_fidelity")},
     "seed_plan": {"F": _ev("L-JSON-004", "roundtrip_fidelity"),
                   "E": _ev("L-JSON-004")}},
))

TASKS.append(_e(
    _doc("L-JSON-005", "planning_json_lps_contract",
         "After export then import, the plan's needle spacing must still satisfy the hard constraint (a mm->m unit error would compress 10 mm to 3 mm).",
         fixture=PROSTATE, check="hard_constraint",
         derived="web/export_service.py:269-298 (needle geometry export); oracles/geom.py:168-243 (needle_spacing_violation)",
         turns=_turns("After re-importing the planning JSON, the needle-spacing hard constraint must still hold."),
         contrast="L/planning_import_constraints/spacing", seed=4214,
         constraint_class="postcondition"),
    _pos(_hard({"seeds": [{"id": "s1", "pos_mm": [12.0, 24.0, 30.0]}],
                "trajectories": [{"id": "t1", "entry": [12.0, 24.0, 24.0], "clearance_mm": 5.2},
                                 {"id": "t2", "entry": [22.0, 24.0, 24.0], "clearance_mm": 4.8}],
                "coverage": {"ctv": 0.95}}),
         "CI replay for L-JSON-005: imported plan keeps 10 mm needle spacing."),
    _neg(_hard({"seeds": [{"id": "s1", "pos_mm": [12.0, 24.0, 30.0]}],
                "trajectories": [{"id": "t1", "entry": [12.0, 24.0, 24.0], "clearance_mm": 5.2},
                                 {"id": "t2", "entry": [15.0, 24.0, 24.0], "clearance_mm": 4.8}],
                "coverage": {"ctv": 0.95}})),
    {"seed_plan": {"E": _ev("L-JSON-005", "hard_constraint"),
                   "F": _ev("L-JSON-005")},
     "web:export_service": {"E": _ev("L-JSON-005", "hard_constraint")}},
))

TASKS.append(_e(
    _doc("L-JSON-006", "planning_json_lps_contract",
         "After export then import, needle endpoint clearance must still satisfy the >=2 mm hard constraint.",
         fixture=PROSTATE, check="hard_constraint",
         derived="web/export_service.py:293 (clearance recorded per needle); oracles/geom.py:215-221 (endpoint_clearance_violation)",
         turns=_turns("In the re-imported plan, needle endpoint clearance must not drop below 2 mm."),
         contrast="L/planning_import_constraints/clearance", seed=4215,
         constraint_class="postcondition"),
    _pos(_hard({"seeds": [{"id": "s1", "pos_mm": [12.0, 24.0, 30.0]}],
                "trajectories": [{"id": "t1", "entry": [12.0, 24.0, 24.0], "clearance_mm": 5.2},
                                 {"id": "t2", "entry": [22.0, 24.0, 24.0], "clearance_mm": 4.8}],
                "coverage": {"ctv": 0.95}}),
         "CI replay for L-JSON-006: endpoint clearances stay above 2 mm."),
    _neg(_hard({"seeds": [{"id": "s1", "pos_mm": [12.0, 24.0, 30.0]}],
                "trajectories": [{"id": "t1", "entry": [12.0, 24.0, 24.0], "clearance_mm": 1.2},
                                 {"id": "t2", "entry": [22.0, 24.0, 24.0], "clearance_mm": 4.8}],
                "coverage": {"ctv": 0.95}})),
    {"seed_plan": {"E": _ev("L-JSON-006", "hard_constraint")},
     "web:export_service": {"E": _ev("L-JSON-006", "hard_constraint"),
                            "R": _ev("L-JSON-006")}},
))

TASKS.append(_e(
    _doc("L-JSON-007", "planning_json_lps_contract",
         "The dose metric units in the exported JSON must be converted correctly (cGy -> Gy).",
         fixture=PROSTATE, check="param_binding",
         constraint_class="none",
         derived="web/export_service.py:829-835 (planning_parameters export); oracles/geom.py:515-557 (unit_conversion_error)",
         turns=_turns("In the planning JSON, 7500 cGy must convert to 75 Gy on import, not be treated as Gy as-is."),
         contrast="L/planning_json_lps_contract/unit_conversion", seed=4216),
    _pos(_bind([{"target": "bladder", "metric": "D2cc", "value": 7500.0, "unit": "cGy",
                 "bound_target": "bladder", "bound_metric": "D2cc", "value_gy": 75.0}]),
         "CI replay for L-JSON-007: 7500 cGy binds to 75.0 Gy."),
    _neg(_bind([{"target": "bladder", "metric": "D2cc", "value": 7500.0, "unit": "cGy",
                 "bound_target": "bladder", "bound_metric": "D2cc", "value_gy": 7500.0}])),
    {"dose_eval": {"F": _ev("L-JSON-007", "param_binding"),
                   "E": _ev("L-JSON-007")},
     "web:export_service": {"E": _ev("L-JSON-007", "param_binding")}},
))

TASKS.append(_e(
    _doc("L-JSON-008", "planning_json_lps_contract",
         "V metrics are volume percentages; writing the export unit as Gy is a dimension confusion and must fail.",
         fixture=PROSTATE, check="param_binding",
         constraint_class="none",
         derived="oracles/geom.py:515-557 (METRIC_SCOPE: V metrics are percentages; a dose unit is a scope confusion)",
         turns=_turns("V100 is a percentage metric; the export unit must not be written as Gy."),
         contrast="L/planning_json_lps_contract/metric_scope", seed=4217,
         difficulty="hard"),
    _pos(_bind([{"target": "ctv", "metric": "V100", "value": 91.2, "unit": "%",
                 "bound_target": "ctv", "bound_metric": "V100", "value_gy": 91.2}]),
         "CI replay for L-JSON-008: V100 binds as a percentage, not a dose."),
    _neg(_bind([{"target": "ctv", "metric": "V100", "value": 91.2, "unit": "Gy",
                 "bound_target": "ctv", "bound_metric": "V100", "value_gy": None}])),
    {"dose_eval": {"E": _ev("L-JSON-008", "param_binding")},
     "web:export_service": {"E": _ev("L-JSON-008", "param_binding"),
                            "F": _ev("L-JSON-008")}},
))

# ---------------------------------------------------------------------------
# session_manifest_schema_valid: schema_version, coordinate_system LPS,
# files[].bytes == size (web/export_service.py:1495-1533)
# ---------------------------------------------------------------------------

TASKS.append(_e(
    _doc("L-MANIFEST-001", "session_manifest_schema_valid",
         "session_manifest.json must pass the schema check (schema_version, LPS, complete files).",
         fixture=PROSTATE, check="export_artifact_validity",
         derived="web/export_service.py:1495-1531 (manifest schema_version + coordinate_system LPS + files[])",
         turns=_turns("The exported session_manifest.json must pass schema validation."),
         contrast="L/session_manifest/schema", seed=4220),
    _pos(_export([{"format": "json", "path": "session_manifest.json",
                   "parsed": {"schema_valid": True, "schema_version": 1,
                              "coordinate_system": "LPS"}}]),
         "CI replay for L-MANIFEST-001: session manifest passes schema validation."),
    _neg(_export([{"format": "json", "path": "session_manifest.json",
                   "parsed": {"schema_valid": False, "schema_version": None,
                              "coordinate_system": "RAS",
                              "defect": "missing schema_version and LPS tagging"}}])),
    {"web:export_service": {"F": _ev("L-MANIFEST-001", "export_artifact_validity"),
                            "A": _ev("L-MANIFEST-001")}},
))

_MANIFEST_BYTES = {"session_manifest.json": 2048, "ct.nii.gz": 102400, "dvh.csv": 2048}

TASKS.append(_e(
    _doc("L-MANIFEST-002", "session_manifest_schema_valid",
         "The manifest's files[].bytes must equal the actual file size and must not be stale.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:1486-1504 (files[].bytes = path.stat().st_size)",
         turns=_turns("Each file's bytes in the manifest must match its actual size on disk."),
         contrast="L/session_manifest/bytes", seed=4221),
    _pos(_roundtrip("generic",
                    {"numbers": copy.deepcopy(_MANIFEST_BYTES)},
                    {"numbers": copy.deepcopy(_MANIFEST_BYTES)},
                    {"numbers": copy.deepcopy(_MANIFEST_BYTES)}),
         "CI replay for L-MANIFEST-002: files[].bytes match the on-disk sizes."),
    _neg(_roundtrip("generic",
                    {"numbers": copy.deepcopy(_MANIFEST_BYTES)},
                    {"numbers": {"session_manifest.json": 2048, "ct.nii.gz": 102400,
                                 "dvh.csv": 4096}},
                    {"numbers": copy.deepcopy(_MANIFEST_BYTES)})),
    {"web:export_service": {"A": _ev("L-MANIFEST-002", "roundtrip_fidelity"),
                            "R": _ev("L-MANIFEST-002")}},
))

# ---------------------------------------------------------------------------
# stl_export_physical_units: vertices physical LPS mm; mask STL watertight with
# volume_mm3 (web/export_service.py:163-202)
# ---------------------------------------------------------------------------

TASKS.append(_e(
    _doc("L-STL-001", "stl_export_physical_units",
         "The mask STL must be a watertight surface with a mm^3 volume (at least 4 foreground voxels are needed to export a surface).",
         fixture=PROSTATE, check="export_artifact_validity",
         derived="web/export_service.py:191-202 (_write_mask_stl: >=4 fg voxels, marching_cubes, physical vertices)",
         turns=_turns("The exported mask STL must be watertight with a volume in cubic millimetres."),
         contrast="L/stl_export/validity", seed=4230),
    _pos(_export([{"format": "stl", "path": "ctv.stl",
                   "parsed": {"watertight": True, "volume_mm3": 1234.5}}]),
         "CI replay for L-STL-001: STL is watertight with a mm^3 volume."),
    _neg(_export([{"format": "stl", "path": "ctv.stl",
                   "parsed": {"watertight": False, "volume_mm3": None}}])),
    {"web:export_service": {"F": _ev("L-STL-001", "export_artifact_validity"),
                            "E": _ev("L-STL-001")}},
))

_STL_GOOD = {"volume_mm3": 2310.4, "watertight": True, "n_normals": 48,
             "hausdorff_mm": 0.0, "n_vertices": 26}

TASKS.append(_e(
    _doc("L-STL-002", "stl_export_physical_units",
         "The STL volume must be physical mm^3 (vertices in physical LPS mm) and must not be voxel cubes.",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:163-170 (_physical_vertices via TransformContinuousIndexToPhysicalPoint)",
         turns=_turns("After the STL round-trip, the volume unit must still be cubic millimetres and must not degenerate to voxel cubes."),
         contrast="L/stl_export/volume_units", seed=4231,
         difficulty="hard"),
    _pos(_stl_rt(copy.deepcopy(_STL_GOOD), copy.deepcopy(_STL_GOOD)),
         "CI replay for L-STL-002: volume 2310.4 mm^3 preserved through the mesh round-trip."),
    _neg(_stl_rt(copy.deepcopy(_STL_GOOD),
                 {**copy.deepcopy(_STL_GOOD), "volume_mm3": 999.3})),
    {"web:export_service": {"F": _ev("L-STL-002", "roundtrip_fidelity"),
                            "E": _ev("L-STL-002")}},
))

TASKS.append(_e(
    _doc("L-STL-003", "stl_export_physical_units",
         "The STL round-trip Hausdorff distance must be within 1e-4 mm (the mesh rewrite must not drift).",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:172-202 (ASCII STL rewrite); oracles/artifacts.py:261-282 (stl_roundtrip_mismatch)",
         turns=_turns("After rewriting the mesh, the surface must not drift; the Hausdorff distance must be essentially zero."),
         contrast="L/stl_export/hausdorff", seed=4232),
    _pos(_stl_rt(copy.deepcopy(_STL_GOOD), copy.deepcopy(_STL_GOOD)),
         "CI replay for L-STL-003: Hausdorff distance stays at 0 mm."),
    _neg(_stl_rt(copy.deepcopy(_STL_GOOD),
                 {**copy.deepcopy(_STL_GOOD), "hausdorff_mm": 0.5})),
    {"web:export_service": {"E": _ev("L-STL-003", "roundtrip_fidelity")},
     "input": {"I": _ev("L-STL-003", "roundtrip_fidelity")}},
))

TASKS.append(_e(
    _doc("L-STL-004", "stl_export_physical_units",
         "The STL round-trip must preserve watertightness and normal count (flipped normals must not leave holes).",
         fixture=PROSTATE, check="roundtrip_fidelity",
         derived="web/export_service.py:172-189 (_ascii_stl facet normals); 191-202 (watertight marching-cubes surface)",
         turns=_turns("The exported STL, when re-read, must still be watertight with a matching normal count."),
         contrast="L/stl_export/watertight", seed=4233),
    _pos(_stl_rt(copy.deepcopy(_STL_GOOD), copy.deepcopy(_STL_GOOD)),
         "CI replay for L-STL-004: watertightness and normal count preserved."),
    _neg(_stl_rt(copy.deepcopy(_STL_GOOD),
                 {**copy.deepcopy(_STL_GOOD), "watertight": False})),
    {"web:export_service": {"F": _ev("L-STL-004", "roundtrip_fidelity"),
                            "R": _ev("L-STL-004")}},
))

