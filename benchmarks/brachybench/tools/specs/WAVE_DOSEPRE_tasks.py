"""Wave spec: dose_pre modules + dose_engine missing dimensions (P/R/A).

Real behaviours are grounded in the source files:

* ``plans/dose_pre/dose_unet.py``      -- ``DoseUNet`` / ``ConvBlock`` / ``pad_to_match``
* ``plans/dose_pre/model_loader.py``   -- unit calibration + checkpoint contract
* ``plans/dose_pre/inference.py``      -- spacing-normalised preprocessing + sliding window
* ``plans/dose_pre/evaluation_inputs.py`` -- grid-consistent ``dose_evaluation`` input resolver
* ``tool_factory/dose_engine/cnn_dose_engine.py`` -- ``CNNDoseEngineTool``

Self-verify without touching shared files::

    python tools/build_expansion.py --spec tools/specs/WAVE_DOSEPRE_tasks.py --prove --dry-run

Entry contract is documented in ``tools/build_expansion.py``; every entry is
``{"task","obs_pos","obs_neg","coverage"}`` exactly as ``spec_template.py``.
Discriminating data lives in ``obs_pos``/``obs_neg`` (never in the fixture).
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# fixtures (reused; discriminating data lives in obs)
# ---------------------------------------------------------------------------

PROSTATE: Dict[str, Any] = {
    "case_family": "synth/prostate_s02",
    "setup_script": "fixtures/setup/prostate_s02_full_pipeline.py",
    "initial_state_hash": "sha256:pending",
}
INTEROP: Dict[str, Any] = {
    "case_family": "synth/interop_case",
    "setup_script": "fixtures/setup/interop_case.py",
    "initial_state_hash": "sha256:pending",
}
PANCREAS: Dict[str, Any] = {
    "case_family": "synth/pancreas_p03",
    "setup_script": "fixtures/setup/pancreas_p03_pipeline.py",
    "initial_state_hash": "sha256:pending",
}

_DOCS = ["A", "E", "H", "L"]

# ---------------------------------------------------------------------------
# small builders
# ---------------------------------------------------------------------------

_SEED = [7000]


def _seed() -> int:
    _SEED[0] += 1
    return _SEED[0]


#: task ids must match /^[A-M][0-9A-Za-z]*-[A-Z0-9]+-[0-9]+$/, so the dimension
#: letter is folded into a numeric offset that keeps ids unique per capability.
_DIM_OFFSET = {"F": 0, "E": 100, "I": 200, "P": 300, "R": 400, "A": 500, "S": 600}


def _id(base: str, dim: str, n: int) -> str:
    return f"DOSEPRE-{base}-{_DIM_OFFSET[dim] + int(n):03d}"


def _ev(tid: str, check: Optional[str] = None) -> List[str]:
    refs = [f"oracle:{check}"] if check else []
    refs.append(f"task:{tid}")
    return refs


def _doc(
    tid: str,
    construct: str,
    intent: str,
    *,
    track: str,
    fixture: Dict[str, Any],
    check: str,
    derived: str,
    contrast: str,
    predicate: Optional[str] = None,
    difficulty: str = "medium",
    power_role: str = "primary",
    paraphrase: Optional[str] = None,
    probes: Sequence[str] = (),
    metric: Optional[str] = None,
    constraint_class: str = "none",
    turns: Optional[Sequence[Dict[str, str]]] = None,
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
    return {
        "schema_version": "1.0",
        "id": tid,
        "track": track,
        "layers": ["L3", "L4"],
        "comparability": ["alpha", "beta"],
        "construct": construct,
        "cost_class": "state_only",
        "power_role": power_role,
        "clinical_intent": intent,
        "fixture": dict(fixture),
        "unit": {
            "kind": "task_scenario",
            "group_type": "G-CT",
            "contrast_family_id": contrast,
        },
        "protocol": {
            "mode": "single_turn",
            "turns": list(turns)
            if turns
            else [{"role": "user", "text": intent, "lang": "en"}],
            "ui_counterpart": None,
            "budget": {"wall_clock_s": 60, "turns": 1, "tool_calls": 6},
            "allowed_intermediates": [],
            "audit_required": False,
            "n_runs": 5,
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
            "generation_seed": _seed(),
            "canary_class": None,
            "behavioral_probes": list(probes),
            "contrast_family_id": contrast,
        },
        "provenance": {
            "source": "audit_derived",
            "derived_from": derived,
            "guideline_ref": None,
            "reviewers": ["auto"],
            "authored_on": "2026-10-01",
            "deprecated": None,
        },
    }


def _gi(check: str, kw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sut_id": "BrachyBot-replay",
        "intent_class": "imperative",
        "partial_status": "COMPLETED",
        "oracle_inputs": {check: kw},
    }


def _gin(check: str, kw: Dict[str, Any]) -> Dict[str, Any]:
    return {"oracle_inputs": {check: kw}}


def _pred_obs(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sut_id": "BrachyBot-replay",
        "intent_class": "imperative",
        "partial_status": "COMPLETED",
        "terminal_state": state,
    }


def _pred_obs_neg(state: Dict[str, Any]) -> Dict[str, Any]:
    return {"terminal_state": state}


def _sem_pair(conclusion: str, numbers: Dict[str, float]):
    a = {"conclusion": conclusion, "numbers": dict(numbers)}
    p = _gi("semantic_equivalence",
            {"run_a": copy.deepcopy(a), "run_b": copy.deepcopy(a)})
    b = copy.deepcopy(a)
    k = next(iter(numbers))
    b["numbers"][k] = float(numbers[k]) + 1.0
    n = _gin("semantic_equivalence", {"run_a": copy.deepcopy(a), "run_b": b})
    return p, n


def _inv_pair(state: Dict[str, Any]):
    p = _gi("state_invariant",
            {"before": copy.deepcopy(state), "after": copy.deepcopy(state)})
    bad = copy.deepcopy(state)
    bad["_drift"] = {"unexpected": True}
    n = _gin("state_invariant",
             {"before": copy.deepcopy(state), "after": bad})
    return p, n


def _rt_numbers(first_numbers: Dict[str, Any], second_numbers: Dict[str, Any]):
    first = {"numbers": copy.deepcopy(first_numbers)}
    second = {"numbers": copy.deepcopy(second_numbers)}
    independent = {"numbers": copy.deepcopy(first_numbers)}
    p = _gi("roundtrip_fidelity",
            {"first": copy.deepcopy(first), "second": copy.deepcopy(first),
             "independent": copy.deepcopy(independent), "fmt": "generic"})
    n = _gin("roundtrip_fidelity",
             {"first": copy.deepcopy(first), "second": copy.deepcopy(second),
              "independent": copy.deepcopy(independent), "fmt": "generic"})
    return p, n


DIR_I = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
DIR_ROT_Z = [0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
DIR_SCALED = [2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0]
DIR_MIRROR = [-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def _grid(dims: Sequence[int], base: float = 1.0,
          spacing: Sequence[float] = (1.0, 1.0, 1.0),
          origin: Sequence[float] = (0.0, 0.0, 0.0),
          direction: Sequence[float] = tuple(DIR_I),
          dtype: str = "float32") -> Dict[str, Any]:
    d0, d1, d2 = int(dims[0]), int(dims[1]), int(dims[2])
    dose = [[[float(base) * (i + 1) + 0.25 * j + 0.5 * k
              for k in range(d2)] for j in range(d1)] for i in range(d0)]
    return {
        "dims": [d0, d1, d2],
        "origin": list(origin),
        "spacing": list(spacing),
        "direction": list(direction),
        "dtype": dtype,
        "dose": dose,
    }


def _rt_dose_pair(first: Dict[str, Any], second: Dict[str, Any]):
    ind = {k: copy.deepcopy(first[k])
           for k in ("dims", "origin", "spacing", "direction")}
    p = _gi("roundtrip_fidelity",
            {"first": copy.deepcopy(first), "second": copy.deepcopy(first),
             "independent": ind, "fmt": "dose", "dose_grid_scaling": 0.001})
    n = _gin("roundtrip_fidelity",
             {"first": copy.deepcopy(first), "second": copy.deepcopy(second),
              "independent": copy.deepcopy(ind), "fmt": "dose",
              "dose_grid_scaling": 0.001})
    return p, n


def _err(code: str, message: str, retryable: bool, op_id: str,
         allowed: Sequence[str]) -> Dict[str, Any]:
    return {
        "errors": [{"code": code, "message": message,
                    "retryable": retryable, "op_id": op_id}],
        "allowed_codes": list(allowed),
    }


def _err_pair(code: str, message: str, retryable: bool, op_id: str,
              neg_kind: str = "retryable"):
    allowed = [code]
    p = _gi("error_contract", _err(code, message, retryable, op_id, allowed))
    if neg_kind == "retryable":
        n = _gin("error_contract", _err(code, message, not retryable, op_id, allowed))
    elif neg_kind == "missing":
        bad = _err(code, message, retryable, op_id, allowed)
        del bad["errors"][0]["op_id"]
        n = _gin("error_contract", bad)
    elif neg_kind == "bad_code":
        n = _gin("error_contract",
                 _err(code, message, retryable, op_id, ["OTHER_CODE"]))
    else:  # empty message
        n = _gin("error_contract", _err(code, "", retryable, op_id, allowed))
    return p, n


def _export_pair(fmt: str, good: Dict[str, Any], bad: Dict[str, Any]):
    p = _gi("export_artifact_validity",
            {"artifacts": [{"format": fmt, "parsed": copy.deepcopy(good)}]})
    n = _gin("export_artifact_validity",
             {"artifacts": [{"format": fmt, "parsed": copy.deepcopy(bad)}]})
    return p, n


def _entry(task: Dict[str, Any], obs_pos: Dict[str, Any],
           obs_neg: Dict[str, Any], coverage: Dict[str, Any]) -> Dict[str, Any]:
    return {"task": task, "obs_pos": obs_pos, "obs_neg": obs_neg,
            "coverage": coverage}


def _one(tid: str, cap: str, dim: str, check: str, *, construct: str,
         intent: str, track: str, fixture: Dict[str, Any], derived: str,
         contrast: str, obs_pos: Dict[str, Any], obs_neg: Dict[str, Any],
         predicate: Optional[str] = None, difficulty: str = "medium",
         power_role: str = "primary", paraphrase: Optional[str] = None,
         probes: Sequence[str] = (), metric: Optional[str] = None,
         constraint_class: str = "none", turns=None) -> Dict[str, Any]:
    task = _doc(tid, construct, intent, track=track, fixture=fixture,
                check=check, derived=derived, contrast=contrast,
                predicate=predicate, difficulty=difficulty,
                power_role=power_role, paraphrase=paraphrase, probes=probes,
                metric=metric, constraint_class=constraint_class, turns=turns)
    return _entry(task, obs_pos, obs_neg, {cap: {dim: _ev(tid, check)}})


TASKS: List[Dict[str, Any]] = []


# ===========================================================================
# dose_pre:dose_unet   (F/E/I)
# ===========================================================================

_UNET_CAP = "dose_pre:dose_unet"
_UNET_DERIV = "plans/dose_pre/dose_unet.py:31-88 (DoseUNet.forward / ConvBlock / pad_to_match)"

# --- F: forward geometry preservation / softplus / norm / padding ----------

_F_PATCHES = [(64, 64, 64), (32, 32, 32), (96, 96, 96), (16, 16, 16),
              (48, 48, 48), (80, 80, 80), (24, 24, 24), (56, 56, 56),
              (112, 112, 112), (40, 40, 40)]
for _i, _p in enumerate(_F_PATCHES, start=1):
    _tid = _id("UNET", "F", _i)
    _pos, _neg = _sem_pair("doseunet_forward_ok",
                           {"in_z": float(_p[0]), "out_z": float(_p[0]),
                            "out_channels": 1.0})
    TASKS.append(_one(
        _tid, _UNET_CAP, "F", "semantic_equivalence",
        construct="dose_unet.forward_shape_preserved",
        intent=f"DoseUNet forward output spatial size must match the input patch {_p}, with 1 channel.",
        track="A", fixture=PROSTATE, derived=_UNET_DERIV,
        contrast="dose_pre/dose_unet/forward_shape",
        obs_pos=_pos, obs_neg=_neg))

for _i, _p in enumerate([(64, 64, 64), (32, 32, 32), (96, 96, 96),
                         (48, 48, 48), (24, 24, 24)], start=11):
    _tid = _id("UNET", "F", _i)
    _pos, _neg = _sem_pair("doseunet_softplus_positive",
                           {"output_min": 0.001, "output_max": 12.5})
    TASKS.append(_one(
        _tid, _UNET_CAP, "F", "semantic_equivalence",
        construct="dose_unet.softplus_nonnegative",
        intent="DoseUNet's final softplus guarantees non-negative output dose (physical dose must not be negative).",
        track="A", fixture=PROSTATE,
        derived="plans/dose_pre/dose_unet.py:57,88 (nn.Softplus on output conv)",
        contrast="dose_pre/dose_unet/softplus",
        obs_pos=_pos, obs_neg=_neg))

for _i, _feat in enumerate([(16, 32, 64, 128, 256), (8, 16, 32, 64, 128),
                            (24, 48, 96, 192, 384)], start=16):
    _tid = _id("UNET", "F", _i)
    _pos, _neg = _sem_pair("doseunet_instance_norm_affine",
                           {"enc_channels": float(_feat[0]),
                            "bottleneck_channels": float(_feat[4])})
    TASKS.append(_one(
        _tid, _UNET_CAP, "F", "semantic_equivalence",
        construct="dose_unet.convblock_channels",
        intent=f"ConvBlock's InstanceNorm3d(affine=True) preserves the feature width {_feat}.",
        track="A", fixture=PROSTATE,
        derived="plans/dose_pre/dose_unet.py:15-28 (ConvBlock InstanceNorm3d affine)",
        contrast="dose_pre/dose_unet/convblock",
        obs_pos=_pos, obs_neg=_neg))

for _i, _sizes in enumerate([((65, 65, 65), (64, 64, 64)),
                             ((33, 33, 33), (32, 32, 32)),
                             ((49, 49, 49), (48, 48, 48)),
                             ((97, 97, 97), (96, 96, 96)),
                             ((63, 63, 63), (62, 62, 62))], start=19):
    _tid = _id("UNET", "F", _i)
    _pos, _neg = _sem_pair("doseunet_pad_to_match",
                           {"decoder_z": float(_sizes[1][0]),
                            "skip_z": float(_sizes[0][0]),
                            "pad_z": float(_sizes[0][0] - _sizes[1][0])})
    TASKS.append(_one(
        _tid, _UNET_CAP, "F", "semantic_equivalence",
        construct="dose_unet.pad_to_match_replicate",
        intent=f"For odd-voxel input {_sizes[0]}, pad_to_match uses replicate padding up to the skip size {_sizes[1]}.",
        track="A", fixture=PROSTATE,
        derived="plans/dose_pre/dose_unet.py:59-71 (pad_to_match replicate padding)",
        contrast="dose_pre/dose_unet/pad_to_match",
        obs_pos=_pos, obs_neg=_neg))


# --- E: construction / padding / channel edge failures --------------------

_UNET_ERRORS = [
    ("INVALID_FEATURE_WIDTH", "DoseUNet requires five feature widths, got [16, 32, 64, 128]", False, "op_unet_build_len4"),
    ("INVALID_FEATURE_WIDTH", "DoseUNet requires five feature widths, got [16, 32, 64, 128, 256, 512]", False, "op_unet_build_len6"),
    ("INVALID_FEATURE_WIDTH", "DoseUNet requires five feature widths, got [16, 32, 64]", False, "op_unet_build_len3"),
    ("INVALID_FEATURE_WIDTH", "DoseUNet requires five feature widths, got []", False, "op_unet_build_len0"),
    ("INVALID_FEATURE_WIDTH", "DoseUNet requires five feature widths, got [16, 32]", False, "op_unet_build_len2"),
    ("DECODER_LARGER_THAN_SKIP", "DoseUNet decoder is larger than its skip connection: decoder=(5,5,5), skip=(4,4,4)", False, "op_unet_pad_dz"),
    ("DECODER_LARGER_THAN_SKIP", "DoseUNet decoder is larger than its skip connection: decoder=(5,4,4), skip=(4,5,5)", False, "op_unet_pad_dy"),
    ("DECODER_LARGER_THAN_SKIP", "DoseUNet decoder is larger than its skip connection: decoder=(5,5,4), skip=(4,4,5)", False, "op_unet_pad_dx"),
    ("EMPTY_CHANNELS", "Conv3d requires in_channels > 0, got 0", False, "op_unet_in0"),
    ("EMPTY_CHANNELS", "Conv3d requires out_channels > 0, got 0", False, "op_unet_out0"),
    ("INPUT_RANK_INVALID", "DoseUNet forward expects a 5D [B,C,D,H,W] tensor, got 4D", False, "op_unet_rank"),
    ("CHANNEL_MISMATCH", "DoseUNet in_channels=3 but input has 2 channels", False, "op_unet_ch"),
    ("POOL_TOO_SMALL", "max_pool3d cannot pool a size-1 axis four times", False, "op_unet_pool"),
    ("FEATURES_NOT_SEQUENCE", "features must be a sequence of five widths, got scalar 64", False, "op_unet_scalar"),
    ("FEATURES_NONE", "features must be a sequence of five widths, got None", False, "op_unet_none"),
    ("FEATURE_WIDTH_NONPOSITIVE", "feature width must be positive, got -8", False, "op_unet_neg"),
    ("FEATURE_WIDTH_NONINTEGER", "feature width must be an integer, got 16.5", False, "op_unet_float"),
    ("FEATURE_WIDTH_NONINTEGER", "feature width must be an integer, got '16'", False, "op_unet_str"),
    ("PATCH_SIZE_INVALID", "DoseUNet patch size must be positive, got spatial size 0", False, "op_unet_patch0"),
    ("BATCH_EMPTY", "DoseUNet batch dimension must be >= 1, got 0", False, "op_unet_batch0"),
]
for _i, (_code, _msg, _retry, _op) in enumerate(_UNET_ERRORS, start=1):
    _tid = _id("UNET", "E", _i)
    _pos, _neg = _err_pair(_code, _msg, _retry, _op,
                           neg_kind=["retryable", "missing", "bad_code", "message"][_i % 4])
    TASKS.append(_one(
        _tid, _UNET_CAP, "E", "error_contract",
        construct="dose_unet.construction_error_contract",
        intent=f"Invalid DoseUNet construction/input must raise the stable error code {_code} so callers can branch on it.",
        track="E", fixture=PROSTATE,
        derived="plans/dose_pre/dose_unet.py:38-39,66-70 (ValueError guards) / oracles/recovery.py:19-65",
        contrast="dose_pre/dose_unet/error_contract",
        obs_pos=_pos, obs_neg=_neg,
        difficulty="easy", power_role="safety_gate"))


# --- I: prediction tensor geometry / metadata round-trip ------------------

_UNET_GRIDS = [
    ((48, 512, 512), (0.68, 0.68, 5.0), (-100.5, -120.25, 30.0)),
    ((128, 128, 128), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)),
    ((16, 16, 16), (1.0, 1.0, 1.0), (10.0, 20.0, 30.0)),
    ((64, 64, 40), (0.5, 0.5, 2.0), (-50.0, -50.0, 0.0)),
    ((32, 32, 32), (1.2, 1.2, 3.0), (5.0, 5.0, 5.0)),
    ((24, 24, 24), (2.0, 2.0, 2.0), (0.0, 0.0, 0.0)),
    ((96, 96, 96), (0.9, 0.9, 0.9), (-40.0, 12.0, 8.0)),
    ((50, 50, 50), (1.0, 1.0, 1.5), (100.0, -20.0, 0.0)),
]
for _i, (_dims, _sp, _org) in enumerate(_UNET_GRIDS, start=1):
    _tid = _id("UNET", "I", _i)
    _first = _grid((2, 2, 2), base=1.0, spacing=_sp, origin=_org)
    _second = copy.deepcopy(_first)
    _second["dose"][0][0][0] = _first["dose"][0][0][0] + 0.0004
    _pos, _neg = _rt_dose_pair(_first, _second)
    # the discriminating negative: geometry drift, not just quantisation
    _bad = copy.deepcopy(_first)
    _bad["spacing"] = [float(_sp[0]) * 1.5, _sp[1], _sp[2]]
    _, _neg = _rt_dose_pair(_first, _bad)
    TASKS.append(_one(
        _tid, _UNET_CAP, "I", "roundtrip_fidelity",
        construct="dose_unet.prediction_grid_metadata_roundtrip",
        intent="After writing the prediction tensor to disk and reading it back, the dims/spacing/origin/direction of {} must remain unchanged.".format(_dims),
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/inference.py:386-390 (resample_crop_to_full CopyInformation) / oracles/artifacts.py:284-310",
        contrast="dose_pre/dose_unet/grid_metadata",
        obs_pos=_pos, obs_neg=_neg,
        difficulty="hard", probes=["independent_parser"]))

_COORD_CASES = [
    ([0, 0, 0], [10.0, 20.0, 30.0], [1.0, 1.0, 2.0], DIR_I),
    ([1, 2, 3], [-100.5, -120.25, 30.0], [0.68, 0.68, 5.0], DIR_I),
    ([4, 5, 6], [0.0, 0.0, 0.0], [0.5, 0.5, 1.0], DIR_ROT_Z),
    ([7, 8, 9], [5.0, 5.0, 5.0], [1.2, 1.2, 3.0], DIR_ROT_Z),
    ([10, 11, 12], [-40.0, 12.0, 8.0], [0.9, 0.9, 0.9], DIR_I),
]
for _i, (_s, _org, _sp, _dir) in enumerate(_COORD_CASES, start=1):
    _tid = _id("UNET", "I", _i + 8)
    _pos = _gi("coord_roundtrip",
               {"samples": [_s], "origin": _org, "spacing": _sp, "direction": _dir})
    _neg = _gin("coord_roundtrip", {"direction": DIR_SCALED, "origin": _org,
                                    "spacing": _sp})
    TASKS.append(_one(
        _tid, _UNET_CAP, "I", "coord_roundtrip",
        construct="dose_unet.prediction_phys_coord_roundtrip",
        intent="Prediction-grid voxel -> physical coordinate -> voxel round-trip must be lossless, and the direction matrix must be a proper orthogonal rotation.",
        track="L", fixture=INTEROP,
        derived="oracles/coord_roundtrip.py:48-158 (voxel<->physical ITK convention); plans/dose_pre/inference.py:151-183",
        contrast="dose_pre/dose_unet/coord_roundtrip",
        obs_pos=_pos, obs_neg=_neg, difficulty="hard"))

for _i in range(14, 21):
    _tid = _id("UNET", "I", _i)
    _good = {"dims": [48, 512, 512], "spacing": [0.68, 0.68, 5.0],
             "origin": [-100.5, -120.25, 30.0], "direction": list(DIR_I)}
    _bad = {"dims": [48, 512], "spacing": [0.68, 0.68],
            "origin": [-100.5, -120.25], "direction": list(DIR_I)}
    _pos, _neg = _export_pair("nifti", _good, _bad)
    TASKS.append(_one(
        _tid, _UNET_CAP, "I", "export_artifact_validity",
        construct="dose_unet.prediction_nifti_export_validity",
        intent="NIfTI exported from the predicted dose must carry complete 3-axis geometry and be parseable by an independent parser.",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/inference.py:386-390 (CopyInformation) / oracles/artifacts.py:158-218",
        contrast="dose_pre/dose_unet/nifti_export",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="exploratory"))


# ===========================================================================
# dose_pre:model_loader   (F/E/I)
# ===========================================================================

_LOAD_CAP = "dose_pre:model_loader"

# --- F: calibration / prescription conversions -----------------------------

_LOAD_BINDINGS = [
    ("bladder", "D2cc", 7500.0, "cGy", 75.0),
    ("rectum", "D2cc", 6840.0, "cGy", 68.4),
    ("CTV_prostate", "D90", 145.8, "Gy", 145.8),
    ("CTV_prostate", "D90", 14580.0, "cGy", 145.8),
    ("CTV_prostate", "D90", 145800.0, "mGy", 145.8),
    ("CTV_prostate", "D90", 145.8, "Gy(RBE)", 145.8),
    ("CTV_prostate", "V100", 91.2, "%", 91.2),
    ("CTV_prostate", "V150", 62.0, "percent", 62.0),
]
for _i, (_tgt, _met, _val, _unit, _gy) in enumerate(_LOAD_BINDINGS, start=1):
    _tid = _id("LOAD", "F", _i)
    _binding = {"target": _tgt, "metric": _met, "value": _val, "unit": _unit,
                "bound_target": _tgt, "bound_metric": _met, "value_gy": _gy}
    _pos = _gi("param_binding", {"bindings": [copy.deepcopy(_binding)]})
    _bad = copy.deepcopy(_binding)
    _bad["value_gy"] = _gy * 10.0
    _neg = _gin("param_binding", {"bindings": [_bad]})
    TASKS.append(_one(
        _tid, _LOAD_CAP, "F", "param_binding",
        construct="model_loader.dose_unit_binding",
        intent=f"Dose metric {_tgt}.{_met} must convert correctly from {_unit} to Gy (physical quantities must not mix up units).",
        track="A", fixture=PROSTATE,
        derived="plans/dose_pre/model_loader.py:35-109 (unit conversion helpers); oracles/geom.py:501-568",
        contrast="dose_pre/model_loader/unit_binding",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy"))

_LOAD_CONVERSIONS = [
    ("dose_model_to_gy", {"gy": 95.4}, "plans/dose_pre/model_loader.py:35-38"),
    ("dose_model_to_gy", {"gy": 190.8}, "plans/dose_pre/model_loader.py:35-38"),
    ("prescription_multiplier_to_gy", {"gy": 120.0}, "plans/dose_pre/model_loader.py:49-55"),
    ("prescription_multiplier_to_gy", {"gy": 144.0}, "plans/dose_pre/model_loader.py:49-55"),
    ("prescription_multiplier_to_gy", {"gy": 96.0}, "plans/dose_pre/model_loader.py:49-55"),
    ("planning_dose_value_to_gy", {"gy": 120.0}, "plans/dose_pre/model_loader.py:71-91"),
]
for _i, (_fn, _numbers, _derived) in enumerate(_LOAD_CONVERSIONS, start=9):
    _tid = _id("LOAD", "F", _i)
    _pos, _neg = _sem_pair(f"model_loader.{_fn}_ok", _numbers)
    TASKS.append(_one(
        _tid, _LOAD_CAP, "F", "semantic_equivalence",
        construct="model_loader.calibration_conversion",
        intent=f"{_fn} must yield a definite physical Gy value (model calibration 190.8 Gy/unit, prescription base 120 Gy).",
        track="A", fixture=PROSTATE, derived=_derived,
        contrast="dose_pre/model_loader/calibration",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy"))

_LOAD_RESOLVE = [
    ({"dose_scale_gy": 190.8}, "new", "plans/dose_pre/model_loader.py:112-140"),
    ({"dose_model_scale_gy": 190.8}, "new_alias", "plans/dose_pre/model_loader.py:126-133"),
    ({"dose_scale_gy": 150.0}, "explicit", "plans/dose_pre/model_loader.py:134-140"),
    ({"dose_scale_gy": 120.0}, "legacy", "plans/dose_pre/model_loader.py:13,140"),
    ({"in_lowest_dose_gy": 100.0}, "rx_new", "plans/dose_pre/model_loader.py:159-173"),
    ({"in_lowest_energy": 1.0}, "rx_legacy", "plans/dose_pre/model_loader.py:174-193"),
]
for _i, (_meta, _label, _derived) in enumerate(_LOAD_RESOLVE, start=15):
    _tid = _id("LOAD", "F", _i)
    _pos, _neg = _inv_pair({"plan_config": dict(_meta), "resolved": True})
    TASKS.append(_one(
        _tid, _LOAD_CAP, "F", "state_invariant",
        construct="model_loader.resolve_precedence",
        intent=f"Resolving the case calibration/prescription ({_label}) must not corrupt workspace state, and the legacy fallback for missing calibration is 120 Gy.",
        track="A", fixture=PROSTATE, derived=_derived,
        contrast="dose_pre/model_loader/resolve",
        obs_pos=_pos, obs_neg=_neg, difficulty="medium"))

# --- E: configuration / checkpoint corruption ------------------------------

_LOAD_ERRORS = [
    ("CONFIG_INVALID", "BRACHYBOT_DOSE_MODEL_SCALE_GY must be numeric", False, "op_scale_env"),
    ("CONFIG_INVALID", "BRACHYBOT_DOSE_MODEL_SCALE_GY must be greater than zero", False, "op_scale_zero"),
    ("CONFIG_INVALID", "BRACHYBOT_DEFAULT_PRESCRIPTION_GY must be numeric", False, "op_rx_env"),
    ("CONFIG_INVALID", "BRACHYBOT_DEFAULT_PRESCRIPTION_GY must be greater than zero", False, "op_rx_zero"),
    ("CONFIG_INVALID", "BRACHYBOT_DOSE_MODEL_PLANNING_SCALE must be numeric", False, "op_plan_scale"),
    ("CONFIG_INVALID", "BRACHYBOT_DOSE_MODEL_PLANNING_SCALE must be positive", False, "op_plan_scale_neg"),
    ("CONFIG_INVALID", "BRACHYBOT_DOSE_INFERENCE_BATCH_SIZE must be an integer", False, "op_batch_env"),
    ("CONFIG_INVALID", "BRACHYBOT_DOSE_INFERENCE_BATCH_SIZE must be positive", False, "op_batch_zero"),
    ("CHECKPOINT_MISSING", "dose_unet_spacing1mm checkpoint not found. Set BRACHYBOT_DOSE_MODEL_PATH", False, "op_load_missing"),
    ("CHECKPOINT_CORRUPT", "Failed to load dose_unet_spacing1mm checkpoint: unpickling stack underflow", False, "op_load_corrupt"),
    ("CHECKPOINT_INVALID", "dose_unet_spacing1mm checkpoint must contain model_state_dict metadata", False, "op_load_nostate"),
    ("CHANNEL_ORDER_UNSUPPORTED", "Unsupported dose_unet_spacing1mm channel_order=(ct, line_map, soft_pos)", False, "op_channel_order"),
    ("TARGET_SPACING_MISSING", "dose_unet_spacing1mm checkpoint is missing its 3-axis target_spacing", False, "op_spacing"),
    ("TARGET_SPACING_MISSING", "dose_unet_spacing1mm checkpoint target_spacing has 2 axes", False, "op_spacing_len"),
    ("DOSE_MULTIPLIER_INVALID", "dose_unet_spacing1mm checkpoint is missing a positive dose_multiplier", False, "op_mult"),
    ("DOSE_MULTIPLIER_INVALID", "dose_unet_spacing1mm checkpoint dose_multiplier=0 is not positive", False, "op_mult_zero"),
    ("SCALE_NONPOSITIVE", "dose_scale_gy must be greater than zero", False, "op_gy_to_model"),
    ("CONTRACT_MISSING", "The loaded dose model has no DoseUNet spacing-normalized contract", False, "op_contract"),
    ("UNAVAILABLE", "CUDA out of memory while loading dose model", True, "op_load_oom"),
    ("UNAVAILABLE", "dose model weights are not installed on this host", True, "op_load_unavail"),
]
for _i, (_code, _msg, _retry, _op) in enumerate(_LOAD_ERRORS, start=1):
    _tid = _id("LOAD", "E", _i)
    _pos, _neg = _err_pair(_code, _msg, _retry, _op,
                           neg_kind=["retryable", "missing", "bad_code", "message"][_i % 4])
    TASKS.append(_one(
        _tid, _LOAD_CAP, "E", "error_contract",
        construct="model_loader.load_error_contract",
        intent=f"Model load/calibration configuration failures must surface the stable error code {_code}, and retryability must not be mislabeled.",
        track="E", fixture=PROSTATE,
        derived="plans/dose_pre/model_loader.py:18-32,211-318 / oracles/recovery.py:19-65",
        contrast="dose_pre/model_loader/error_contract",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="safety_gate"))

# --- I: unit / contract round-trips ----------------------------------------

_LOAD_RT = [
    ({"model": 0.5, "gy": 95.4}, {"model": 0.6, "gy": 95.4}),
    ({"model": 1.0, "gy": 190.8}, {"model": 1.0, "gy": 190.8, "extra": 1.0}),
    ({"model": 0.6289, "gy": 120.0}, {"model": 0.7, "gy": 120.0}),
    ({"multiplier": 1.0, "gy": 120.0}, {"multiplier": 1.2, "gy": 120.0}),
    ({"multiplier": 1.2, "gy": 144.0}, {"multiplier": 1.2, "gy": 145.0}),
    ({"model": 0.3, "gy": 57.24}, {"model": 0.3, "gy": 60.0}),
    ({"scale": 190.8, "legacy": 120.0}, {"scale": 150.0, "legacy": 120.0}),
    ({"cgy": 7500.0, "gy": 75.0}, {"cgy": 7500.0, "gy": 75.1}),
    ({"mgy": 145800.0, "gy": 145.8}, {"mgy": 145800.0, "gy": 146.0}),
    ({"patch": 64.0, "overlap": 0.5}, {"patch": 32.0, "overlap": 0.5}),
]
for _i, (_first, _second) in enumerate(_LOAD_RT, start=1):
    _tid = _id("LOAD", "I", _i)
    _pos, _neg = _rt_numbers(_first, _second)
    TASKS.append(_one(
        _tid, _LOAD_CAP, "I", "roundtrip_fidelity",
        construct="model_loader.calibration_roundtrip",
        intent="Model-unit <-> physical-Gy round-trip must be faithful (the calibration factor must not drift).",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/model_loader.py:35-46 (inverse scale pair); oracles/artifacts.py:312-318",
        contrast="dose_pre/model_loader/roundtrip",
        obs_pos=_pos, obs_neg=_neg, difficulty="medium"))

for _i in range(11, 16):
    _tid = _id("LOAD", "I", _i)
    _first = _grid((2, 2, 2), base=1.0, spacing=(1.0, 1.0, 1.0))
    _bad = copy.deepcopy(_first)
    _bad["origin"] = [0.0, 0.0, 5.0]
    _pos, _neg = _rt_dose_pair(_first, _bad)
    TASKS.append(_one(
        _tid, _LOAD_CAP, "I", "roundtrip_fidelity",
        construct="model_loader.target_spacing_roundtrip",
        intent="The checkpoint's target_spacing / patch / grid metadata write-read round-trip must preserve the 1 mm training grid.",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/model_loader.py:242-249,295-312 (contract target_spacing/patch_size)",
        contrast="dose_pre/model_loader/grid_roundtrip",
        obs_pos=_pos, obs_neg=_neg, difficulty="hard"))

_LOAD_CONTRACTS = [
    {"name": "dose_unet_spacing1mm", "channel_order": ["ct", "seed_mask", "seed_dose"],
     "target_spacing": [1.0, 1.0, 1.0], "dose_multiplier": 0.006167,
     "patch_size": [64, 64, 64], "overlap": 0.5, "planning_output_scale": 0.006167},
    {"name": "dose_unet_spacing1mm", "channel_order": ["ct", "seed_mask", "seed_dose"],
     "target_spacing": [1.0, 1.0, 1.0], "dose_multiplier": 0.006167,
     "patch_size": [32, 32, 32], "overlap": 0.5, "planning_output_scale": 0.006167},
    {"name": "dose_unet_spacing1mm", "channel_order": ["ct", "seed_mask", "seed_dose"],
     "target_spacing": [1.0, 1.0, 1.0], "dose_multiplier": 0.007407,
     "patch_size": [96, 96, 96], "overlap": 0.4, "planning_output_scale": 0.007407},
    {"name": "dose_unet_spacing1mm", "channel_order": ["ct", "seed_mask", "seed_dose"],
     "target_spacing": [1.0, 1.0, 1.0], "dose_multiplier": 0.006167,
     "patch_size": [64, 64, 64], "overlap": 0.5, "inference_batch_size": 4},
    {"name": "dose_unet_spacing1mm", "channel_order": ["ct", "seed_mask", "seed_dose"],
     "target_spacing": [1.0, 1.0, 1.0], "dose_multiplier": 0.006167,
     "patch_size": [48, 48, 48], "overlap": 0.25, "output_size_cm": 12.0},
]
for _i in range(16, 21):
    _tid = _id("LOAD", "I", _i)
    _good = {**_LOAD_CONTRACTS[_i - 16], "schema_valid": True}
    _bad = {**_LOAD_CONTRACTS[_i - 16], "schema_valid": False}
    _pos, _neg = _export_pair("json", _good, _bad)
    TASKS.append(_one(
        _tid, _LOAD_CAP, "I", "export_artifact_validity",
        construct="model_loader.contract_json_validity",
        intent="The exported model-contract JSON (name/channel_order/target_spacing/dose_multiplier) must be schema-valid.",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/model_loader.py:295-313 (_brachybot_dose_contract) / oracles/artifacts.py:190-207",
        contrast="dose_pre/model_loader/json_contract",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="exploratory"))


# ===========================================================================
# dose_pre:inference   (F/E/I)
# ===========================================================================

_INF_CAP = "dose_pre:inference"

# --- F: preprocessing happy paths -----------------------------------------

_INF_F = [
    ("normalize_ct", "inference.normalize_ct_clamp", {"value": 0.25},
     "plans/dose_pre/inference.py:64-66"),
    ("normalize_ct", "inference.normalize_ct_clamp", {"value": 0.0},
     "plans/dose_pre/inference.py:64-66"),
    ("normalize_ct", "inference.normalize_ct_clamp", {"value": 1.0},
     "plans/dose_pre/inference.py:64-66"),
    ("normalize_ct", "inference.normalize_ct_clamp", {"value": 0.75},
     "plans/dose_pre/inference.py:64-66"),
    ("normalize_unit", "inference.normalize_unit_nan", {"sum": 1.0},
     "plans/dose_pre/inference.py:69-72"),
    ("normalize_unit", "inference.normalize_unit_inf", {"sum": 1.0},
     "plans/dose_pre/inference.py:69-72"),
    ("normalize_unit", "inference.normalize_unit_allzero", {"sum": 0.0},
     "plans/dose_pre/inference.py:69-72"),
    ("crop_ct_center_on_seed", "inference.crop_desired_voxels", {"crop_z": 120.0},
     "plans/dose_pre/inference.py:75-120"),
    ("crop_ct_center_on_seed", "inference.crop_desired_voxels", {"crop_z": 176.0},
     "plans/dose_pre/inference.py:75-120"),
    ("crop_ct_center_on_seed", "inference.crop_fractional_origin", {"origin_z": -54.5},
     "plans/dose_pre/inference.py:84-89"),
    ("generate_soft_pos", "inference.soft_pos_normalized", {"sum": 1.0},
     "plans/dose_pre/inference.py:192-206"),
    ("generate_soft_pos", "inference.soft_pos_radius", {"inside_voxels": 268.0},
     "plans/dose_pre/inference.py:200-202"),
    ("generate_line_map", "inference.line_map_normalized", {"max": 1.0},
     "plans/dose_pre/inference.py:209-233"),
    ("starts_for_dim", "inference.starts_for_dim_small", {"n_starts": 1.0},
     "plans/dose_pre/inference.py:259-265"),
    ("starts_for_dim", "inference.starts_for_dim_tail", {"n_starts": 5.0},
     "plans/dose_pre/inference.py:259-265"),
    ("crop_or_pad", "inference.crop_or_pad_zero", {"pad_voxels": 8.0},
     "plans/dose_pre/inference.py:268-281"),
    ("crop_or_pad", "inference.crop_or_pad_clip", {"out_voxels": 64.0},
     "plans/dose_pre/inference.py:268-281"),
    ("sliding_window_predict", "inference.sliding_window_shape", {"out_z": 64.0},
     "plans/dose_pre/inference.py:284-317"),
    ("sliding_window_predict_batch", "inference.batch_window_shape", {"batch": 8.0},
     "plans/dose_pre/inference.py:320-383"),
    ("predict_seed_doses", "inference.batch_order_preserved", {"n_outputs": 8.0},
     "plans/dose_pre/inference.py:498-574"),
]
for _i, (_fn, _construct, _numbers, _derived) in enumerate(_INF_F, start=1):
    _tid = _id("INF", "F", _i)
    _pos, _neg = _sem_pair(f"inference.{_fn}_ok", _numbers)
    TASKS.append(_one(
        _tid, _INF_CAP, "F", "semantic_equivalence",
        construct=_construct,
        intent=f"{_fn} must be deterministic and reproducible under real preprocessing parameters.",
        track="A", fixture=PROSTATE, derived=_derived,
        contrast="dose_pre/inference/happy_path",
        obs_pos=_pos, obs_neg=_neg, difficulty="medium"))

# --- E: preprocessing edge failures ---------------------------------------

_INF_ERRORS = [
    ("DIRECTION_ZERO", "Particle direction vector is zero", False, "op_line_dir0"),
    ("PATCH_SIZE_INVALID", "Invalid DoseUNet patch size: (64, 64)", False, "op_patch_len"),
    ("PATCH_SIZE_INVALID", "Invalid DoseUNet patch size: (64, 64, 0)", False, "op_patch_zero"),
    ("PATCH_SIZE_INVALID", "Invalid DoseUNet patch size: (64, -64, 64)", False, "op_patch_neg"),
    ("BATCH_RANK_INVALID", "Batched DoseUNet input must have shape [batch, channels, z, y, x]", False, "op_batch_rank"),
    ("BATCH_EMPTY", "Batched DoseUNet input must have batch >= 1", False, "op_batch_empty"),
    ("PARTICLE_ARITY", "Each seed particle must contain position, direction, and weight", False, "op_particle_arity"),
    ("TIMEOUT", "DoseUNet inference exceeded the interactive planning time budget", True, "op_deadline"),
    ("TIMEOUT", "DoseUNet inference exceeded the interactive planning time budget", True, "op_deadline_window"),
    ("CONTRACT_MISSING", "The loaded dose model has no DoseUNet spacing-normalized contract. Refusing to run the removed legacy dose preprocessing.", False, "op_contract"),
    ("CROP_INVALID", "desired crop voxels must be >= 1", False, "op_crop_zero"),
    ("SPACING_INVALID", "target spacing must have three positive axes", False, "op_spacing"),
    ("IMAGE_MISMATCH", "crop and full image geometry disagree", False, "op_resample"),
    ("CROP_EMPTY", "requested crop lies outside the image", False, "op_outside"),
    ("OOM_RETRY", "CUDA out of memory; retry with smaller chunks", True, "op_cuda_oom"),
    ("WINDOW_START_INVALID", "sliding window start index is negative", False, "op_start"),
    ("OVERLAP_INVALID", "sliding window overlap outside [0, 0.95]", False, "op_overlap"),
    ("NORMALIZE_EMPTY", "normalize_unit received an empty array", False, "op_empty"),
    ("DEADLINE_NONMONOTONIC", "inference deadline is in the past", False, "op_deadline_past"),
    ("INPUT_DTYPE_INVALID", "DoseUNet input must be float32", False, "op_dtype"),
]
for _i, (_code, _msg, _retry, _op) in enumerate(_INF_ERRORS, start=1):
    _tid = _id("INF", "E", _i)
    _pos, _neg = _err_pair(_code, _msg, _retry, _op,
                           neg_kind=["retryable", "missing", "bad_code", "message"][_i % 4])
    TASKS.append(_one(
        _tid, _INF_CAP, "E", "error_contract",
        construct="inference.preprocessing_error_contract",
        intent=f"Inference preprocessing edge failures must return the stable error code {_code}, with timeout/memory-retryable cases labeled correctly.",
        track="E", fixture=PROSTATE,
        derived="plans/dose_pre/inference.py:42-47,215-216,297-299,339-342,521-522 / oracles/recovery.py:19-65",
        contrast="dose_pre/inference/error_contract",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="safety_gate"))

# --- I: resample / coordinate round-trips ---------------------------------

for _i in range(1, 11):
    _tid = _id("INF", "I", _i)
    _first = _grid((2, 2, 2), base=2.0,
                   spacing=(0.68, 0.68, 5.0) if _i % 2 else (1.0, 1.0, 1.0),
                   origin=(-100.5, -120.25, 30.0) if _i % 2 else (0.0, 0.0, 0.0))
    _bad = copy.deepcopy(_first)
    _bad["direction"] = DIR_ROT_Z
    _pos, _neg = _rt_dose_pair(_first, _bad)
    TASKS.append(_one(
        _tid, _INF_CAP, "I", "roundtrip_fidelity",
        construct="inference.resample_grid_roundtrip",
        intent="The geometry metadata round-trip for crop -> 1 mm network grid -> re-injected CT grid must be faithful.",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/inference.py:123-148,386-390 (resample_to_reference / resample_crop_to_full)",
        contrast="dose_pre/inference/resample_roundtrip",
        obs_pos=_pos, obs_neg=_neg, difficulty="hard", probes=["independent_parser"]))

for _i in range(11, 16):
    _tid = _id("INF", "I", _i)
    _pos = _gi("coord_roundtrip",
               {"samples": [[0, 0, 0], [60, 60, 60]],
                "origin": [-100.5, -120.25, 30.0],
                "spacing": [1.0, 1.0, 1.0], "direction": DIR_I})
    _neg = _gin("coord_roundtrip",
                {"header_a": {"origin": [-100.5, -120.25, 30.0],
                              "spacing": [1.0, 1.0, 1.0],
                              "direction": DIR_I},
                 "header_b": {"origin": [-100.5, -120.25, 32.0],
                              "spacing": [1.0, 1.0, 1.0],
                              "direction": DIR_I}})
    TASKS.append(_one(
        _tid, _INF_CAP, "I", "coord_roundtrip",
        construct="inference.physical_coords_roundtrip",
        intent="The ITK round-trip between seed physical coordinates and network-grid voxel coordinates must be lossless and header-consistent.",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/inference.py:151-189 (physical_coordinate_arrays / image_from_xyz_array)",
        contrast="dose_pre/inference/coord_roundtrip",
        obs_pos=_pos, obs_neg=_neg, difficulty="hard"))

for _i in range(16, 21):
    _tid = _id("INF", "I", _i)
    _good = {"dims": [120, 120, 120], "spacing": [1.0, 1.0, 1.0],
             "origin": [-60.0, -60.0, -60.0], "direction": list(DIR_I)}
    _bad = {"dims": [120, 120, 120], "spacing": [1.0, 1.0]}
    _pos, _neg = _export_pair("nifti", _good, _bad)
    TASKS.append(_one(
        _tid, _INF_CAP, "I", "export_artifact_validity",
        construct="inference.prediction_nifti_export",
        intent="After exporting the CT-grid-reinjected predicted dose to NIfTI, an independent parser must read it with complete 3-axis geometry.",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/inference.py:386-390 / oracles/artifacts.py:158-218",
        contrast="dose_pre/inference/nifti_export",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="exploratory"))


# ===========================================================================
# dose_pre:evaluation_inputs   (F/E/I)
# ===========================================================================

_EVAL_CAP = "dose_pre:evaluation_inputs"

_EVAL_F = [
    ("eval.resolve_normalized_dose", {"dose_max_gy": 95.4},
     "plans/dose_pre/evaluation_inputs.py:34-42,126-136"),
    ("eval.resolve_physical_dose", {"dose_max_gy": 95.4},
     "plans/dose_pre/evaluation_inputs.py:38-42,131"),
    ("eval.resolve_planning_grid_dose", {"dose_max_gy": 95.4},
     "plans/dose_pre/evaluation_inputs.py:41,126-136"),
    ("eval.prefer_ct_grid_pair", {"paired_grid": 1.0},
     "plans/dose_pre/evaluation_inputs.py:120-157"),
    ("eval.oar_same_shape_included", {"oar_included": 1.0},
     "plans/dose_pre/evaluation_inputs.py:135,155-156"),
    ("eval.oar_mismatch_excluded", {"oar_included": 0.0},
     "plans/dose_pre/evaluation_inputs.py:135"),
    ("eval.prescribed_dose_new", {"prescribed_gy": 100.0},
     "plans/dose_pre/evaluation_inputs.py:140-145"),
    ("eval.prescribed_dose_legacy", {"prescribed_gy": 120.0},
     "plans/dose_pre/evaluation_inputs.py:140-145"),
    ("eval.spacing_from_resampled", {"spacing_z": 1.0},
     "plans/dose_pre/evaluation_inputs.py:63-73,153-154"),
    ("eval.organ_names_default", {"organ_count": 0.0},
     "plans/dose_pre/evaluation_inputs.py:146-152"),
    ("eval.tumor_type_default", {"tumor_len": 0.0},
     "plans/dose_pre/evaluation_inputs.py:147-149"),
    ("eval.first_nonnone_wins", {"source_rank": 1.0},
     "plans/dose_pre/evaluation_inputs.py:101-108"),
    ("eval.prostate_case", {"dose_max_gy": 145.8},
     "plans/dose_pre/evaluation_inputs.py:126-157"),
    ("eval.pancreas_case", {"dose_max_gy": 100.0},
     "plans/dose_pre/evaluation_inputs.py:126-157"),
    ("eval.phantom_case", {"dose_max_gy": 12.5},
     "plans/dose_pre/evaluation_inputs.py:126-157"),
    ("eval.normalized_scale_legacy", {"dose_max_gy": 60.0},
     "plans/dose_pre/model_loader.py:112-140"),
    ("eval.zero_dose_preserved", {"dose_max_gy": 0.0},
     "plans/dose_pre/evaluation_inputs.py:136"),
    ("eval.float32_cast", {"dtype_code": 11.0},
     "plans/dose_pre/evaluation_inputs.py:136"),
    ("eval.mask_shape_equality", {"shape_rank": 3.0},
     "plans/dose_pre/evaluation_inputs.py:132-134"),
    ("eval.multiple_dose_keys_rank", {"chosen_rank": 2.0},
     "plans/dose_pre/evaluation_inputs.py:125-157"),
]
for _i, (_construct, _numbers, _derived) in enumerate(_EVAL_F, start=1):
    _tid = _id("EVAL", "F", _i)
    _pos, _neg = _sem_pair(_construct, _numbers)
    TASKS.append(_one(
        _tid, _EVAL_CAP, "F", "semantic_equivalence",
        construct=_construct,
        intent="dose_evaluation inputs must be grid-paired and converted to Gy via calibration, with deterministic, reproducible results.",
        track="A", fixture=PROSTATE, derived=_derived,
        contrast="dose_pre/evaluation_inputs/happy_path",
        obs_pos=_pos, obs_neg=_neg, difficulty="medium"))

_EVAL_ERRORS = [
    ("RETRIEVE_NOT_CALLABLE", "dose_array and ctv_mask are required but not loaded in the workspace: retrieve is not callable", False, "op_retrieve"),
    ("DOSE_MISSING", "dose_array and ctv_mask are required but not loaded in the workspace: no CTV mask or dose distribution is available for dose_evaluation", False, "op_no_dose"),
    ("CTV_MISSING", "dose_array and ctv_mask are required but not loaded in the workspace: no CTV mask or dose distribution is available for dose_evaluation", False, "op_no_ctv"),
    ("GRID_MISMATCH", "dose_array and ctv_mask grids do not match (dose_distribution=(48, 512, 512), ctv_mask=(64, 64, 64)); no workspace dose shares the mask grid, so dose_evaluation cannot run on this pair", False, "op_grid"),
    ("ARRAY_INVALID", "workspace dose value is not a usable ndarray", False, "op_array"),
    ("SPACING_INVALID", "ct_spacing must have three numeric axes", False, "op_spacing"),
    ("PLAN_CONFIG_INVALID", "plan_config is not a mapping; falling back to defaults", False, "op_plan_config"),
    ("METRICS_INVALID", "dose_metrics is not a mapping; falling back to defaults", False, "op_metrics"),
    ("DOSE_MISSING", "no CTV mask or dose distribution is available for dose_evaluation", False, "op_no_dose2"),
    ("GRID_MISMATCH", "dose_array and ctv_mask grids do not match (dose_distribution=(128, 128, 128), ctv_mask=(48, 512, 512))", False, "op_grid2"),
    ("RESOLUTION_ERROR", "dose_evaluation inputs could not be resolved without silent dose fabrication", False, "op_resolve"),
    ("DOSE_OBJECT_ARRAY", "dose array has object dtype and cannot be evaluated", False, "op_obj"),
    ("DOSE_SCALAR", "dose array is 0-dimensional; refusing to evaluate", False, "op_scalar"),
    ("MASK_OBJECT_ARRAY", "ctv mask has object dtype", False, "op_mask_obj"),
    ("SITK_DECODE_FAILED", "SimpleITK image could not be decoded to an array", False, "op_sitk"),
    ("DOSE_SHAPE_RANK", "dose array rank must be 3", False, "op_rank"),
    ("MASK_SHAPE_RANK", "ctv mask rank must be 3", False, "op_mask_rank"),
    ("RESOLUTION_ERROR", "no workspace dose shares the mask grid, so dose_evaluation cannot run on this pair", False, "op_resolve2"),
    ("DOSE_MISSING", "dose distribution is unavailable for this session", False, "op_session"),
    ("GRID_MISMATCH", "planning-grid dose and CT-grid masks disagree", False, "op_grid3"),
]
for _i, (_code, _msg, _retry, _op) in enumerate(_EVAL_ERRORS, start=1):
    _tid = _id("EVAL", "E", _i)
    _pos, _neg = _err_pair(_code, _msg, _retry, _op,
                           neg_kind=["retryable", "missing", "bad_code", "message"][_i % 4])
    TASKS.append(_one(
        _tid, _EVAL_CAP, "E", "error_contract",
        construct="eval_inputs.resolution_error_contract",
        intent=f"When evaluation inputs cannot be resolved, a distinguishable error code {_code} must be returned, and dose must not be fabricated.",
        track="E", fixture=PROSTATE,
        derived="plans/dose_pre/evaluation_inputs.py:29-32,76-183 / oracles/recovery.py:19-65",
        contrast="dose_pre/evaluation_inputs/error_contract",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="safety_gate"))

for _i in range(1, 11):
    _tid = _id("EVAL", "I", _i)
    _pos, _neg = _rt_numbers({"normalized": 0.5, "gy": 95.4},
                             {"normalized": 0.5, "gy": 60.0})
    if _i % 2:
        _pos, _neg = _rt_numbers({"dose": 0.25, "gy": 47.7},
                                 {"dose": 0.25, "gy": 47.7 + _i})
    TASKS.append(_one(
        _tid, _EVAL_CAP, "I", "roundtrip_fidelity",
        construct="eval_inputs.normalized_to_gy_roundtrip",
        intent="Normalized-model-output <-> physical-Gy conversion round-trip must be faithful (calibration injection must not change numeric semantics).",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/evaluation_inputs.py:34-42,131-136 / plans/dose_pre/model_loader.py:35-46",
        contrast="dose_pre/evaluation_inputs/unit_roundtrip",
        obs_pos=_pos, obs_neg=_neg, difficulty="medium"))

for _i in range(11, 16):
    _tid = _id("EVAL", "I", _i)
    _first = _grid((2, 2, 2), base=1.0, spacing=(1.0, 1.0, 1.0),
                   origin=(0.0, 0.0, 0.0))
    _bad = copy.deepcopy(_first)
    _bad["spacing"] = [2.0, 1.0, 1.0]
    _pos, _neg = _rt_dose_pair(_first, _bad)
    TASKS.append(_one(
        _tid, _EVAL_CAP, "I", "roundtrip_fidelity",
        construct="eval_inputs.grid_metadata_roundtrip",
        intent="Write-read of shared-grid mask/dose metadata must be consistent, and grid mismatches must raise an error rather than pair silently.",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/evaluation_inputs.py:120-157 (grid pairing by shape) / oracles/artifacts.py:284-310",
        contrast="dose_pre/evaluation_inputs/grid_roundtrip",
        obs_pos=_pos, obs_neg=_neg, difficulty="hard"))

_EVAL_PARAMS = [
    {"case_id": "interop_prostate", "prescribed_dose": 145.0,
     "spacing": [1.0, 1.0, 1.0], "dose_array_shape": [512, 512, 120],
     "organ_names": {"1": "ctv", "2": "bladder", "3": "rectum"}, "tumor_type": "prostate"},
    {"case_id": "interop_pancreas", "prescribed_dose": 120.0,
     "spacing": [0.977, 0.977, 1.25], "dose_array_shape": [512, 512, 140],
     "organ_names": {"1": "ctv", "2": "duodenum", "3": "stomach"}, "tumor_type": "pancreas"},
    {"case_id": "interop_liver", "prescribed_dose": 120.0,
     "spacing": [0.703, 0.703, 1.0], "dose_array_shape": [512, 512, 160],
     "organ_names": {"1": "ctv", "2": "liver", "3": "right_kidney"}, "tumor_type": "liver"},
    {"case_id": "interop_lung", "prescribed_dose": 110.0,
     "spacing": [0.683, 0.683, 1.0], "dose_array_shape": [512, 512, 180],
     "organ_names": {"1": "ctv", "2": "lung", "3": "esophagus"}, "tumor_type": "lung"},
    {"case_id": "interop_breast", "prescribed_dose": 50.0,
     "spacing": [0.859, 0.859, 1.0], "dose_array_shape": [512, 512, 100],
     "organ_names": {"1": "ctv", "2": "skin", "3": "heart"}, "tumor_type": "breast"},
]
for _i in range(16, 21):
    _tid = _id("EVAL", "I", _i)
    _good = {**_EVAL_PARAMS[_i - 16], "schema_valid": True}
    _bad = {**_EVAL_PARAMS[_i - 16], "schema_valid": False}
    _pos, _neg = _export_pair("json", _good, _bad)
    TASKS.append(_one(
        _tid, _EVAL_CAP, "I", "export_artifact_validity",
        construct="eval_inputs.params_json_validity",
        intent="The resolved dose_evaluation parameter set exported to JSON must be schema-valid (directly injectable into the evaluator).",
        track="L", fixture=INTEROP,
        derived="plans/dose_pre/evaluation_inputs.py:137-157 (params dict) / oracles/artifacts.py:190-207",
        contrast="dose_pre/evaluation_inputs/json_params",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="exploratory"))


# ===========================================================================
# dose_engine missing dims P / R / A
# ===========================================================================

_ENG_CAP = "dose_engine"
_ENG_DERIV = "tool_factory/dose_engine/cnn_dose_engine.py:116-184 (_execute / batch_seed_dose_calculation_dl)"

# --- P: paraphrase / multi-target binding ---------------------------------

_ENG_P_GROUPS = [
    ("bladder", "D2cc", 7500.0, "cGy", 75.0,
     "Bladder D2cc must not exceed 7500 cGy", "Bladder D2cc limit 75 Gy"),
    ("rectum", "D2cc", 6840.0, "cGy", 68.4,
     "Rectum D2cc limit 68.4 Gy", "Rectum D2cc must stay under 6840 cGy"),
    ("CTV_prostate", "D90", 145.8, "Gy", 145.8,
     "Prostate CTV D90 prescription 145.8 Gy", "CTV prostate D90 prescription 145.8 Gy"),
    ("CTV_prostate", "V100", 91.2, "%", 91.2,
     "Prostate CTV V100 requirement 91.2%", "CTV prostate V100 coverage 91.2 percent"),
    ("CTV_prostate", "D90", 145800.0, "mGy", 145.8,
     "Prostate CTV D90 around 145800 mGy", "CTV prostate D90 around 145800 mGy"),
]
_ENG_CASES = ["zh", "en", "concise", "typo", "verbose"]
for _grp, (_tgt, _met, _val, _unit, _gy, _zh, _en) in enumerate(_ENG_P_GROUPS, start=1):
    _group = f"DOSEPRE-ENG-P{_grp:02d}"
    for _ci, _style in enumerate(_ENG_CASES):
        _n = _grp * 10 + _ci
        _tid = _id("ENG", "P", _n)
        _binding = {"target": _tgt, "metric": _met, "value": _val, "unit": _unit,
                    "bound_target": _tgt, "bound_metric": _met, "value_gy": _gy}
        _pos = _gi("param_binding", {"bindings": [copy.deepcopy(_binding)]})
        _bad = copy.deepcopy(_binding)
        if _style == "typo":
            _bad["bound_target"] = "bladder_typo"
        else:
            _bad["value_gy"] = _gy * 100.0
        _neg = _gin("param_binding", {"bindings": [_bad]})
        _text = _zh if _style in ("zh", "concise", "typo", "verbose") else _en
        TASKS.append(_one(
            _tid, _ENG_CAP, "P", "param_binding",
            construct="dose_engine.paraphrase_metric_binding",
            intent=f"A paraphrased dose constraint ({_style}) must bind to the same target and unit: {_text}.",
            track="A", fixture=PROSTATE, derived=_ENG_DERIV + "; oracles/geom.py:501-568",
            contrast=f"dose_engine/binding/{_met}",
            obs_pos=_pos, obs_neg=_neg, paraphrase=_group,
            probes=["paraphrase"], difficulty="medium"))

# --- R: recovery / error / idempotency ------------------------------------

_ENG_ERRORS = [
    ("UNAVAILABLE", "cnn_dose_engine: dose_unet_spacing1mm checkpoint not found", True, "op_eng_load"),
    ("OOM_RETRY", "CUDA out of memory during batch inference; retry with smaller chunks", True, "op_eng_oom"),
    ("TIMEOUT", "cnn_dose_engine exceeded the interactive planning budget", True, "op_eng_timeout"),
    ("PATCH_INVALID", "invalid infer_img_size: (64, 64)", False, "op_eng_patch"),
    ("SEED_ARITY", "each seed entry must be [[position],[direction]]", False, "op_eng_seed"),
    ("ENGINE_FAILED", "dose engine returned no per-seed contributions", False, "op_eng_none"),
    ("BUILD_FAILED", "DoseUNet state_dict could not be loaded from checkpoint", False, "op_eng_state"),
    ("NETWORK", "failed to fetch remote dose model weights", True, "op_eng_net"),
    ("BUSY", "dose engine lease is busy; retry shortly", True, "op_eng_busy"),
    ("DEVICE_ERROR", "CUDA device unavailable; falling back to CPU failed", False, "op_eng_dev"),
]
for _i, (_code, _msg, _retry, _op) in enumerate(_ENG_ERRORS, start=1):
    _tid = _id("ENG", "R", _i)
    _pos, _neg = _err_pair(_code, _msg, _retry, _op,
                           neg_kind=["retryable", "missing", "bad_code", "message"][_i % 4])
    TASKS.append(_one(
        _tid, _ENG_CAP, "R", "error_contract",
        construct="dose_engine.recovery_error_contract",
        intent=f"Dose-engine failures must surface with stable retryable semantics {_code}, so upper layers can recover without changing physical results.",
        track="E", fixture=PROSTATE, derived=_ENG_DERIV + "; oracles/recovery.py:19-65",
        contrast="dose_engine/error_contract",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="safety_gate"))

for _i in range(11, 16):
    _tid = _id("ENG", "R", _i)
    _state = {"plan": {"status": "final", "seeds": [{"id": "s1"}, {"id": "s2"}]},
              "dose": {"computed": False}}
    _pos, _neg = _inv_pair(_state)
    TASKS.append(_one(
        _tid, _ENG_CAP, "R", "state_invariant",
        construct="dose_engine.failure_leaves_state_intact",
        intent="After a dose-calculation failure, plan and dose state must be preserved as-is, with no half-applied changes left behind.",
        track="E", fixture=PROSTATE,
        derived="tool_factory/dose_engine/cnn_dose_engine.py:147-148 (ToolResult failure) / oracles/recovery.py:68-121",
        contrast="dose_engine/state_invariant",
        obs_pos=_pos, obs_neg=_neg, difficulty="medium"))

for _i in range(16, 21):
    _tid = _id("ENG", "R", _i)
    _state = {"plan": {"seeds": [{"id": "s1", "pos_mm": [1.0, 2.0, 3.0]}],
                       "receipts": [{"op_id": "op_dose", "hash": "a" * 64}]},
              "dose": {"computed": True, "max_dose": 95.4},
              "ui": {"version_fence": {"state_seq": 7}}}
    _pos = _gi("idempotency", {"states": [copy.deepcopy(_state),
                                          copy.deepcopy(_state)]})
    _first = copy.deepcopy(_state)
    _second = copy.deepcopy(_state)
    _second["plan"]["seeds"][0]["pos_mm"] = [9.0, 9.0, 9.0]
    _neg = _gin("idempotency", {"states": [_first, _second]})
    TASKS.append(_one(
        _tid, _ENG_CAP, "R", "idempotency",
        construct="dose_engine.recompute_idempotent",
        intent="Recomputing dose for the same seed set must be idempotent (state unchanged apart from receipts/version fence).",
        track="E", fixture=PROSTATE,
        derived="tool_factory/dose_engine/cnn_dose_engine.py:160-166 (batch_seed_dose_calculation_dl) / oracles/recovery.py:180-214",
        contrast="dose_engine/idempotency",
        obs_pos=_pos, obs_neg=_neg, difficulty="medium"))

# --- A: audit / receipts / reproducibility --------------------------------

def _chain(payloads: Sequence[Dict[str, Any]]):
    receipts = []
    prev = "0" * 64
    mutations = []
    for _i, _p in enumerate(payloads):
        _opid = f"op_dose_{_i + 1}"
        body = json.dumps({"op_id": _opid, "payload": _p, "prev": prev},
                          sort_keys=True, separators=(",", ":"), default=str)
        _h = hashlib.sha256(body.encode("utf-8")).hexdigest()
        mutations.append({"op_id": _opid, "payload": _p})
        receipts.append({"op_id": _opid, "status": "completed",
                         "hash": _h, "prev_hash": prev})
        prev = _h
    return mutations, receipts


_ENG_AUDIT = [
    ["sg1"],
    ["sg1", "sg2"],
    ["sg1", "sg2", "sg3"],
    ["prostate_p03"],
    ["sg1", "sg3", "sg5", "sg7"],
    ["pancreas_p03"],
    ["phantom_16"],
    ["recompute_v7"],
]
for _i, _tags in enumerate(_ENG_AUDIT, start=1):
    _tid = _id("ENG", "A", _i)
    _muts, _recs = _chain([{"tag": t, "engine": "cnn_dose_engine"} for t in _tags])
    _pos = _gi("receipt_complete", {"mutations": _muts, "receipts": _recs})
    _bad = copy.deepcopy(_recs)
    _bad[-1]["hash"] = "f" * 64
    _neg = _gin("receipt_complete", {"mutations": copy.deepcopy(_muts),
                                     "receipts": _bad})
    TASKS.append(_one(
        _tid, _ENG_CAP, "A", "receipt_complete",
        construct="dose_engine.dose_receipt_chain",
        intent="Every dose calculation must leave a verifiable hash-chained receipt covering all mutation operations.",
        track="H", fixture=PROSTATE,
        derived="tool_factory/dose_engine/cnn_dose_engine.py:171-183 (metadata receipts) / oracles/recovery.py:124-177",
        contrast="dose_engine/receipts",
        obs_pos=_pos, obs_neg=_neg, difficulty="medium"))

for _i in range(9, 13):
    _tid = _id("ENG", "A", _i)
    _h = hashlib.sha256(("dose_unet_spacing1mm" + str(_i)).encode()).hexdigest()
    _other = hashlib.sha256(("physics_engine" + str(_i)).encode()).hexdigest()
    _pos = _gi("replay_hash_artifact",
               {"runs": [[{"name": "cumulative_dose.nii.gz", "sha256": _h}],
                         [{"name": "cumulative_dose.nii.gz", "sha256": _h}]],
                "deterministic_kernels": True})
    _neg = _gin("replay_hash_artifact",
                {"runs": [[{"name": "cumulative_dose.nii.gz", "sha256": _h}],
                          [{"name": "cumulative_dose.nii.gz", "sha256": _other}]],
                 "deterministic_kernels": True})
    TASKS.append(_one(
        _tid, _ENG_CAP, "A", "replay_hash_artifact",
        construct="dose_engine.deterministic_artifact_replay",
        intent="Under deterministic kernels, re-running the same dose calculation must produce byte-identical artifacts (traceably reproducible).",
        track="H", fixture=PROSTATE,
        derived="tool_factory/dose_engine/cnn_dose_engine.py:166-183 / oracles/artifacts.py:385-438",
        contrast="dose_engine/replay_hash",
        obs_pos=_pos, obs_neg=_neg, difficulty="hard", probes=["deterministic_kernels"]))

_ENG_METRICS = [
    {"engine": "dose_unet_spacing1mm", "num_seeds": 4,
     "max_dose": 160.2, "mean_dose": 58.4},
    {"engine": "dose_unet_spacing1mm", "num_seeds": 48,
     "max_dose": 132.5, "mean_dose": 61.7},
    {"engine": "dose_unet_spacing1mm", "num_seeds": 64,
     "max_dose": 175.9, "mean_dose": 64.1},
]
for _i in range(13, 16):
    _tid = _id("ENG", "A", _i)
    _good = {**_ENG_METRICS[_i - 13], "schema_valid": True}
    _bad = {**_ENG_METRICS[_i - 13], "schema_valid": False}
    _pos, _neg = _export_pair("json", _good, _bad)
    TASKS.append(_one(
        _tid, _ENG_CAP, "A", "export_artifact_validity",
        construct="dose_engine.metrics_json_validity",
        intent="The dose-engine metrics JSON (engine/num_seeds/max_dose/mean_dose) must be schema-valid and auditable.",
        track="H", fixture=PROSTATE,
        derived="tool_factory/dose_engine/cnn_dose_engine.py:175-183,226-233 (metrics json) / oracles/artifacts.py:190-207",
        contrast="dose_engine/metrics_json",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="exploratory"))

# --- F: engine happy path (additive consistency + engine attribution) ------

for _i in range(1, 11):
    _tid = _id("ENG", "F", _i)
    _per = [[[[1.0 + _i, 2.0 + _i]]], [[[0.5 + _i, 0.25 + _i]]]]
    _cum = [[[_per[0][0][0][0] + _per[1][0][0][0],
              _per[0][0][0][1] + _per[1][0][0][1]]]]
    _pos = {"sut_id": "BrachyBot-replay", "intent_class": "imperative",
            "partial_status": "COMPLETED",
            "dose": {"cumulative_dose": _cum, "per_seed_doses": _per,
                     "seed_ids": ["s1", "s2"], "expect_seed_ids": ["s1", "s2"]}}
    _bad_cum = copy.deepcopy(_cum)
    _bad_cum[0][0][0] = _bad_cum[0][0][0] + 5.0
    _neg = {"dose": {"cumulative_dose": _bad_cum,
                     "per_seed_doses": copy.deepcopy(_per),
                     "seed_ids": ["s1", "s2"], "expect_seed_ids": ["s1", "s2"]}}
    TASKS.append(_one(
        _tid, _ENG_CAP, "F", "dose_additivity",
        construct="dose_engine.multi_seed_additivity",
        intent="Multi-particle cumulative dose must equal the sum of per-particle contributions, with a consistent seed list (internal additivity).",
        track="A", fixture=PROSTATE,
        derived="oracles/dose_additivity.py:31-178; tool_factory/dose_engine/cnn_dose_engine.py:166 (np.sum per_seed_doses)",
        contrast="dose_engine/additivity",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy"))

for _i in range(11, 16):
    _tid = _id("ENG", "F", _i)
    _good = {"dose": {"engine": "cnn_dose_engine@DoseUNet", "computed": True}}
    _bad = {"dose": {"engine": "mc_dose_engine", "computed": True}}
    _pos = _pred_obs(copy.deepcopy(_good))
    _neg = _pred_obs_neg(copy.deepcopy(_bad))
    TASKS.append(_one(
        _tid, _ENG_CAP, "F", "pred",
        construct="dose_engine.engine_attribution",
        intent="Dose provenance must be explicitly attributed to the DoseUNet CNN engine, avoiding confusion with the physics engine.",
        track="A", fixture=PROSTATE,
        derived="tool_factory/dose_engine/cnn_dose_engine.py:105-113,180 (engine metadata); oracles/predicates.py:74-78",
        contrast="dose_engine/engine_attribution",
        obs_pos=_pos, obs_neg=_neg, predicate="dose_engine_is_doseunet",
        difficulty="easy"))

# --- E: engine input edge contracts (extension of existing E coverage) -----

for _i in range(1, 6):
    _tid = _id("ENG", "E", _i)
    _pos, _neg = _err_pair("SEED_INPUT_INVALID",
                           "seed entry must be [[position],[direction]] with 3 components each",
                           False, f"op_eng_seed_{_i}",
                           neg_kind=["retryable", "missing", "bad_code", "message"][_i % 4])
    TASKS.append(_one(
        _tid, _ENG_CAP, "E", "error_contract",
        construct="dose_engine.seed_input_contract",
        intent="Illegal seed position/direction inputs must be rejected by the dose engine with a stable error.",
        track="E", fixture=PROSTATE, derived=_ENG_DERIV,
        contrast="dose_engine/seed_input",
        obs_pos=_pos, obs_neg=_neg, difficulty="easy", power_role="safety_gate"))

# --- S: engine safety (extension of existing S coverage) -------------------

for _i in range(1, 6):
    _tid = _id("ENG", "S", _i)
    _pos, _neg = _err_pair("DANGEROUS_PARAM_REJECTED",
                           "dose engine refused out-of-range seed activity/positions",
                           False, f"op_eng_safe_{_i}",
                           neg_kind=["retryable", "missing", "bad_code", "message"][_i % 4])
    TASKS.append(_one(
        _tid, _ENG_CAP, "S", "error_contract",
        construct="dose_engine.dangerous_parameter_rejected",
        intent="Seed parameters outside the clinical safety range must be explicitly rejected by the dose engine, not silently accepted.",
        track="D1", fixture=PROSTATE, derived=_ENG_DERIV,
        contrast="dose_engine/dangerous_params",
        obs_pos=_pos, obs_neg=_neg, difficulty="medium", power_role="safety_gate"))
