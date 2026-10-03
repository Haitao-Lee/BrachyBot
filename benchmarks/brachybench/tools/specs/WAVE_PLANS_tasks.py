"""Track-A expansion wave: the ``plans/*`` brachytherapy planning capabilities.

Self-verify without touching any shared file::

    python tools/build_expansion.py --spec tools/specs/WAVE_PLANS_tasks.py --prove --dry-run

Owned capabilities (registry ``capabilities/registry.yaml`` -> ``path``):

* ``plans:core``          plans/core.py            (F,E,R)
* ``plans:utilizations``  plans/utilizations.py    (F,E,I)
* ``plans:geometry``      plans/geometry.py        (F,E,S)
* ``plans:reinforcement`` plans/reinforcement.py   (F,E,R)
* ``plans:coverage_repair`` plans/coverage_repair.py (F,E,R)
* ``plans:brachy_plan``   plans/brachy_plan_v2.py  (F,E,R)
* ``plans:device_manager`` plans/device_manager.py (F,E,R,A)
* ``plans:planning_preview`` plans/planning_preview.py (F,E,R,A)
* ``plans:reward_metrics`` plans/reward_metrics.py (F,E)
* ``plans:rl_status``     plans/rl_status.py       (F,E,A)
* ``plans:guide_geometry`` plans/guide_geometry.py (F,E,S)
* ``plans:performance``   plans/performance.py     (F,A)

Every entry is deterministic data for a **program** oracle (no judge).  The
positive observation replays the correct pipeline behaviour; the negative is a
real engineering defect (voxel/world leak, endpoint false positive, rejected
repair mutating the accepted plan, OOM mislabelled, bore out of tolerance,
NaN telemetry persisted, ...).  Discriminating data lives in ``obs_*`` only --
never in the fixture.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# fixtures (case families already shipped; hashes back-filled by the builder)
# ---------------------------------------------------------------------------

FIX: Dict[str, Dict[str, str]] = {
    "prostate": {
        "case_family": "synth/prostate_s02_full_pipeline",
        "setup_script": "fixtures/setup/prostate_s02_full_pipeline.py",
        "initial_state_hash": "sha256:pending",
    },
    "pancreas": {
        "case_family": "synth/pancreas_p03_pipeline",
        "setup_script": "fixtures/setup/pancreas_p03_pipeline.py",
        "initial_state_hash": "sha256:pending",
    },
    "liver": {
        "case_family": "synth/pancreas_p03_pipeline",
        "setup_script": "fixtures/setup/pancreas_p03_pipeline.py",
        "initial_state_hash": "sha256:pending",
    },
    "lung": {
        "case_family": "synth/pancreas_p03_seeds_3",
        "setup_script": "fixtures/setup/pancreas_p03_seeds_3.py",
        "initial_state_hash": "sha256:pending",
    },
    "recovery": {
        "case_family": "synth/recovery_case",
        "setup_script": "fixtures/setup/recovery_case.py",
        "initial_state_hash": "sha256:pending",
    },
    "security": {
        "case_family": "synth/security_sandbox",
        "setup_script": "fixtures/setup/security_sandbox.py",
        "initial_state_hash": "sha256:pending",
    },
    "interop": {
        "case_family": "synth/interop_case",
        "setup_script": "fixtures/setup/interop_case.py",
        "initial_state_hash": "sha256:pending",
    },
}

# ---------------------------------------------------------------------------
# real clinical / geometry parameter tables
# ---------------------------------------------------------------------------

#: origin / spacing / prescription / seed economy per clinical site
ANATOMY: Dict[str, Dict[str, Any]] = {
    "prostate": {"origin": [-120.5, -120.5, -140.0], "spacing": [1.0, 1.0, 1.0],
                 "rx_gy": 145.0, "seeds": 64, "needles": 16, "nuclide": "I-125",
                 "activity_u": 0.4},
    "pancreas": {"origin": [-98.2, -140.0, -120.5], "spacing": [0.977, 0.977, 1.25],
                 "rx_gy": 35.0, "seeds": 48, "needles": 14, "nuclide": "I-125",
                 "activity_u": 0.5},
    "liver": {"origin": [45.2, -210.0, -88.0], "spacing": [0.703, 0.703, 1.0],
              "rx_gy": 120.0, "seeds": 80, "needles": 20, "nuclide": "Yb-169",
              "activity_u": 0.6},
    "lung": {"origin": [-180.0, -180.0, -220.0], "spacing": [0.683, 0.683, 1.0],
             "rx_gy": 110.0, "seeds": 56, "needles": 12, "nuclide": "I-125",
             "activity_u": 0.45},
}

DIR_I = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
DIR_ROT_Z = [0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
DIR_MIRROR_X = [-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
DIR_SCALED2 = [2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0]

#: array-order (z,y,x) seed chains per site (real spacing ~7 mm I-125 strands)
SEEDS: Dict[str, List[List[float]]] = {
    "prostate": [[12.0, 24.0, 30.0], [12.0, 24.0, 37.0],
                 [26.0, 24.0, 30.0], [26.0, 24.0, 37.0]],
    "pancreas": [[40.0, 50.0, 60.0], [40.0, 57.0, 60.0],
                 [40.0, 64.0, 60.0], [55.0, 50.0, 60.0]],
    "liver": [[70.0, 80.0, 90.0], [70.0, 87.0, 90.0],
              [70.0, 94.0, 90.0], [90.0, 80.0, 90.0]],
    "lung": [[30.0, 60.0, 110.0], [30.0, 67.0, 110.0],
             [45.0, 60.0, 110.0], [45.0, 67.0, 110.0]],
}

CONSTRAINT = {
    "coord_roundtrip": "none",
    "seed_geometry_fidelity": "none",
    "hard_constraint": "postcondition",
    "acceptable_set_hit": "postcondition",
    "guide_geometry_tol": "postcondition",
    "interference_fp": "none",
    "param_binding": "none",
    "error_contract": "none",
    "state_invariant": "postcondition",
    "receipt_complete": "postcondition",
    "idempotency": "postcondition",
    "semantic_equivalence": "none",
}

TASKS: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# entry builders
# ---------------------------------------------------------------------------

def _task(tid: str, cap: str, dims: str, check: str, construct: str,
          intent: str, derived: str, *, fixture: str = "prostate",
          contrast: Optional[str] = None, seed: int = 0,
          oracle_extra: Optional[Dict[str, Any]] = None,
          text: Optional[str] = None, lang: str = "en",
          mode: str = "single_turn", audit: bool = False,
          group: str = "G-CT", difficulty: str = "medium",
          power: str = "primary", intent_class: str = "imperative",
          turns: Optional[List[Dict[str, str]]] = None,
          n_runs: int = 5, wall: int = 60, tool_calls: int = 6) -> Dict[str, Any]:
    oracle: Dict[str, Any] = {
        "kind": "program", "check": check,
        "constraint_class": CONSTRAINT.get(check, "none"),
        "expect": None, "tolerance": None, "assist_only": False,
        "independent_check": True, "evidence_keys": [], "gold": None,
    }
    if oracle_extra:
        oracle.update(oracle_extra)
    if turns is None:
        turns = [{"role": "user", "text": text or intent, "lang": lang}]
    cf = contrast or f"{cap}/{construct}"
    return {
        "schema_version": "1.0",
        "id": tid,
        "track": "A",
        "layers": ["L3", "L4"],
        "comparability": ["alpha", "beta"],
        "construct": construct,
        "cost_class": "state_only",
        "power_role": power,
        "clinical_intent": intent,
        "fixture": dict(FIX[fixture]),
        "unit": {"kind": "task_scenario", "group_type": group,
                 "contrast_family_id": cf},
        "protocol": {
            "mode": mode,
            "turns": [dict(t) for t in turns],
            "ui_counterpart": None,
            "budget": {"wall_clock_s": wall, "turns": len(turns),
                       "tool_calls": tool_calls},
            "allowed_intermediates": [],
            "audit_required": audit,
            "n_runs": n_runs,
        },
        "oracle": oracle,
        "scoring": {"primary_metric": f"{check}_pass", "gate_refs": [],
                    "weight": 1.0, "difficulty_target": difficulty},
        "anti_gaming": {
            "paraphrase_group": f"{tid}-P01", "hidden": False,
            "generation_seed": seed, "canary_class": None,
            "behavioral_probes": [], "contrast_family_id": cf,
        },
        "provenance": {
            "source": "audit_derived", "derived_from": derived,
            "guideline_ref": None, "reviewers": ["auto"],
            "authored_on": "2026-10-01", "deprecated": None,
        },
    }


def _cov(cap: str, dims: str, check: str, tid: str) -> Dict[str, Any]:
    refs = [f"oracle:{check}", f"task:{tid}"] if check != "pred" else [f"task:{tid}"]
    return {cap: {d: list(refs) for d in dims}}


def _gen(tid: str, cap: str, dims: str, check: str, construct: str,
         intent: str, derived: str, pos: Dict[str, Any], neg: Dict[str, Any],
         **kw: Any) -> Dict[str, Any]:
    t = _task(tid, cap, dims, check, construct, intent, derived, **kw)
    return {
        "task": t,
        "obs_pos": {
            "sut_id": "BrachyBot-replay",
            "intent_class": kw.get("intent_class", "imperative"),
            "partial_status": "COMPLETED",
            "oracle_inputs": {check: pos},
            "_comment": f"CI replay for {tid}: correct engineering outcome.",
        },
        "obs_neg": {"oracle_inputs": {check: neg}},
        "coverage": _cov(cap, dims, check, tid),
    }


def _pred(tid: str, cap: str, dims: str, predicate: str, construct: str,
          intent: str, derived: str, pos_state: Dict[str, Any],
          neg_state: Dict[str, Any], **kw: Any) -> Dict[str, Any]:
    oracle_extra = dict(kw.pop("oracle_extra", {}) or {})
    oracle_extra["predicate"] = predicate
    t = _task(tid, cap, dims, "pred", construct, intent, derived,
              oracle_extra=oracle_extra, **kw)
    return {
        "task": t,
        "obs_pos": {
            "sut_id": "BrachyBot-replay",
            "intent_class": kw.get("intent_class", "imperative"),
            "partial_status": "COMPLETED",
            "terminal_state": pos_state,
        },
        "obs_neg": {"terminal_state": neg_state},
        "coverage": _cov(cap, dims, "pred", tid),
    }


# ---------------------------------------------------------------------------
# shared payload helpers
# ---------------------------------------------------------------------------

def _seeds(site: str, prefix: str = "s") -> List[Dict[str, Any]]:
    pts, act = SEEDS[site], ANATOMY[site]["activity_u"]
    return [{"id": f"{prefix}{i + 1}", "traj": f"t{i // 2 + 1}",
             "pos_mm": list(p), "activity_u": act} for i, p in enumerate(pts)]


def _plan(site: str, *, coverage: float = 0.94, clearance: float = 3.0,
          spacing_mm: float = 8.0, n_seeds: int = 4,
          oar: Optional[Dict[str, Any]] = None,
          oar_limits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = ANATOMY[site]
    trajs = [
        {"id": "t1", "entry": [10.0, 20.0, 10.0], "clearance_mm": clearance},
        {"id": "t2", "entry": [10.0 + spacing_mm, 20.0, 10.0],
         "clearance_mm": clearance},
    ]
    seeds = _seeds(site)[:n_seeds]
    plan: Dict[str, Any] = {
        "seeds": seeds,
        "trajectories": trajs,
        "coverage": {"ctv": coverage},
    }
    if oar is not None:
        plan["oar_metrics"] = oar
    if oar_limits is not None:
        plan["limits"] = oar_limits
    return plan


def _rc(items: List[Any]):
    """Receipt chain byte-identical to ``oracles/recovery.py`` ReceiptComplete."""
    prev = "0" * 64
    ms: List[Dict[str, Any]] = []
    rs: List[Dict[str, Any]] = []
    for op, payload in items:
        body = json.dumps({"op_id": op, "payload": payload, "prev": prev},
                          sort_keys=True, separators=(",", ":"), default=str)
        h = hashlib.sha256(body.encode("utf-8")).hexdigest()
        ms.append({"op_id": op, "payload": payload})
        rs.append({"op_id": op, "status": "completed", "hash": h, "prev_hash": prev})
        prev = h
    return ms, rs


# ===========================================================================
# plans:core -- plans/core.py (F,E,R)
# ===========================================================================

def gen_core() -> None:
    n = 0
    prof = [
        ("prostate", [0.0, 0.0, 0.0]),
        ("pancreas", [-98.2, -140.0, -120.5]),
        ("liver", [45.2, -210.0, -88.0]),
        ("lung", [-180.0, -180.0, -220.0]),
    ]
    # --- coord_roundtrip: conversion on EVERY return path (core.py:32-116) ---
    samples = [[12.0, 24.0, 30.0], [12.0, 24.0, 38.0], [26.0, 24.0, 34.0]]
    for i, (site, origin) in enumerate(prof):
        for variant in range(2):
            n += 1
            tid = f"PLAN-CORE-{n:03d}"
            spacing = ANATOMY[site]["spacing"]
            if variant == 0:
                neg = {"samples": samples, "origin": origin, "spacing": spacing,
                       "direction": DIR_SCALED2}
                neg_intent = "A non-orthogonal direction matrix (scaled 2x) must be rejected before reaching the dose engine."
            else:
                neg = {"samples": samples, "origin": origin, "spacing": spacing,
                       "direction": DIR_MIRROR_X}
                neg_intent = "A left-handed reflection direction matrix must be flagged illegal; no silent conversion."
            TASKS.append(_gen(
                tid, "plans:core", "FR", "coord_roundtrip",
                "seed_plan_world_conversion_every_return_path",
                f"{site} plans must convert voxel coordinates to patient world coordinates on early-return paths too.",
                "plans/core.py:32-116 seed_plan_to_world_coordinates; oracles/coord_roundtrip.py:31-45,48-158",
                {"samples": samples, "origin": origin, "spacing": spacing,
                 "direction": DIR_I},
                neg, fixture=site, seed=1100 + n, contrast="plans/core/world_conversion",
                difficulty="hard"))
            if variant == 0:
                # store the negative intent as a paraphrase-visible variant
                TASKS[-1]["task"]["clinical_intent"] = (
                    f"{site} plan leaks voxel coordinates on early return; world-coordinate conversion must cover every return path."
                )

    # header-consistency variants (same conversion, two headers)
    for i, (site, origin) in enumerate(prof):
        n += 1
        tid = f"PLAN-CORE-{n:03d}"
        spacing = ANATOMY[site]["spacing"]
        hdr_a = {"origin": origin, "spacing": spacing, "direction": DIR_I}
        if i % 2 == 0:
            hdr_b = {"origin": [origin[0] + 0.5, origin[1], origin[2]],
                     "spacing": spacing, "direction": DIR_I}
            intent = f"{site} world-coordinate header origin differs from the planning grid origin by 0.5mm and must be flagged inconsistent."
        else:
            hdr_b = {"origin": origin,
                     "spacing": [s * 1.001 for s in spacing], "direction": DIR_I}
            intent = f"{site} world-coordinate header spacing is inconsistent and must be flagged inconsistent."
        TASKS.append(_gen(
            tid, "plans:core", "FER", "coord_roundtrip",
            "seed_plan_header_consistency",
            intent,
            "plans/core.py:32-116 (world geometry contract); oracles/coord_roundtrip.py:115-144",
            {"samples": samples, "origin": origin, "spacing": spacing,
             "direction": DIR_I, "header_a": hdr_a, "header_b": hdr_a},
            {"samples": samples, "origin": origin, "spacing": spacing,
             "direction": DIR_I, "header_a": hdr_a, "header_b": hdr_b},
            fixture=site, seed=1200 + n, contrast="plans/core/header_consistency"))

    # --- seed_geometry_fidelity: engine seeds must equal cws seeds -----------
    for site in ANATOMY:
        base = _seeds(site)
        for v in range(4):
            n += 1
            tid = f"PLAN-CORE-{n:03d}"
            eng = copy.deepcopy(base)
            if v == 0:
                eng[0]["pos_mm"][0] += 0.5
                intent = f"{site} engine seed placement drifts 0.5mm from the plan (voxel coordinates not converted)."
            elif v == 1:
                eng = eng[:-1]
                intent = f"{site} engine received one fewer seed; the id set must match exactly."
            elif v == 2:
                eng[1]["activity_u"] = round(ANATOMY[site]["activity_u"] + 0.05, 4)
                intent = f"{site} seed activity was altered; the geometry-fidelity check must detect the parameter mismatch."
            else:
                eng[0]["pos_mm"] = eng[0]["pos_mm"][:2]
                intent = f"{site} engine seed coordinates were reduced to 2-D; the rank mismatch must be rejected."
            TASKS.append(_gen(
                tid, "plans:core", "FE", "seed_geometry_fidelity",
                "engine_seed_geometry_matches_cws",
                intent,
                "plans/core.py:32-116 (seed_plan_to_world_coordinates); oracles/geom.py:25-86",
                {"engine_seeds": copy.deepcopy(base), "cws_seeds": copy.deepcopy(base)},
                {"engine_seeds": eng, "cws_seeds": copy.deepcopy(base)},
                fixture=site, seed=1300 + n,
                contrast="plans/core/seed_geometry_fidelity",
                difficulty="hard" if v == 3 else "medium"))

    # --- state_invariant: early return / failure leaves state intact ---------
    for i in range(8):
        n += 1
        tid = f"PLAN-CORE-{n:03d}"
        site = list(ANATOMY)[i % 4]
        before = {"plan": {"status": "ready", "seeds": _seeds(site),
                           "planning_version": 3},
                  "dose": {"computed": False},
                  "ui": {"version_fence": {"state_seq": i}}}
        after = copy.deepcopy(before)
        if i % 2 == 0:
            intent = f"{site} the plan must retain its frozen initial state on early return and must not write seeds partway."
        else:
            intent = f"{site} the plan must not be partially modified when optimization fails mid-round."
        TASKS.append(_gen(
            tid, "plans:core", "FER", "state_invariant",
            "early_return_leaves_plan_intact",
            intent,
            "plans/core.py:32-116 early-return conversion; oracles/recovery.py:68-121",
            {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
            {"before": copy.deepcopy(before),
             "after": {**copy.deepcopy(after),
                       "plan": {**after["plan"], "status": "final"}}},
            fixture=site, seed=1400 + n,
            contrast="plans/core/failure_state_intact"))

    # --- error_contract: malformed seed records surface a typed envelope -----
    for i in range(8):
        n += 1
        tid = f"PLAN-CORE-{n:03d}"
        if i % 2 == 0:
            code = "INVALID_SEED_RECORD"
            msg = "seed record is missing position or direction"
            retry = False
            intent = "A seed record missing position/direction must return a structured error, not be silently skipped."
            neg = {"errors": [{"code": code, "message": msg, "retryable": True,
                               "op_id": f"op_seed_{i}"}]}
        else:
            code = "TIMEOUT"
            msg = "dose preview deadline while converting seed coordinates"
            retry = True
            intent = "A coordinate-conversion timeout must be marked as a retryable error."
            neg = {"errors": [{"code": code, "message": msg, "retryable": False,
                               "op_id": f"op_seed_{i}"}]}
        pos = {"errors": [{"code": code, "message": msg, "retryable": retry,
                           "op_id": f"op_seed_{i}"}]}
        TASKS.append(_gen(
            tid, "plans:core", "ER", "error_contract",
            "seed_conversion_error_envelope",
            intent,
            "plans/core.py:56-95 (ValueError on missing/short position); oracles/recovery.py:19-65",
            pos, neg, fixture="recovery", seed=1500 + n,
            contrast="plans/core/conversion_error_envelope"))

    # --- semantic_equivalence: sampler / conversion determinism --------------
    for i in range(6):
        n += 1
        tid = f"PLAN-CORE-{n:03d}"
        site = list(ANATOMY)[i % 4]
        a = {"conclusion": "seeds_converted",
             "recommendation": "use_world_seeds",
             "numbers": {"n_seeds": 4, "origin_z": ANATOMY[site]["origin"][2],
                         "planning_version": 3}}
        b = copy.deepcopy(a)
        neg = copy.deepcopy(a)
        neg["numbers"]["n_seeds"] = 3
        TASKS.append(_gen(
            tid, "plans:core", "FE", "semantic_equivalence",
            "planner_seed_conversion_reproducible",
            f"{site} planning the same input twice must yield the same world-coordinate seed set and count.",
            "plans/core.py:119-144 sample_spatial_trajectories (deterministic FPS); oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(b)},
            {"run_a": a, "run_b": neg}, fixture=site, seed=1600 + n,
            contrast="plans/core/seed_determinism"))

    # --- hard_constraint: candidate/plan geometry limits ---------------------
    neg_variants = [
        lambda p: {**p, "trajectories": [
            {"id": "t1", "entry": [10.0, 20.0, 10.0], "clearance_mm": 3.0},
            {"id": "t2", "entry": [13.0, 20.0, 10.0], "clearance_mm": 3.0}]},
        lambda p: {**p, "trajectories": [
            {"id": "t1", "entry": [10.0, 20.0, 10.0], "clearance_mm": 1.2},
            {"id": "t2", "entry": [18.0, 20.0, 10.0], "clearance_mm": 3.0}]},
        lambda p: {**p, "coverage": {"ctv": 0.85}},
    ]
    for i in range(6):
        n += 1
        tid = f"PLAN-CORE-{n:03d}"
        site = list(ANATOMY)[i % 4]
        good = _plan(site)
        bad = neg_variants[i % 3](_plan(site))
        TASKS.append(_gen(
            tid, "plans:core", "FE", "hard_constraint",
            "candidate_plan_meets_hard_limits",
            f"{site} a candidate plan must satisfy the needle-spacing / endpoint-clearance / CTV-coverage hard constraints.",
            "plans/core.py:206-468 init_plan (cone-grid candidates); oracles/geom.py:168-243",
            {"plan": good}, {"plan": bad}, fixture=site, seed=1700 + n,
            contrast="plans/core/hard_limits"))

    # --- acceptable_set_hit: set-valued plan quality -------------------------
    for i in range(6):
        n += 1
        tid = f"PLAN-CORE-{n:03d}"
        site = list(ANATOMY)[i % 4]
        good = _plan(site)
        ok_expert = {"family_id": "AE_family_1", "acceptable": True,
                     "kappa": 0.91, "ac1": 0.88}
        if i % 2 == 0:
            neg = {"plan": good, "acceptable_families": [],
                   "expert_membership": {"family_id": "AE_family_2",
                                         "acceptable": False,
                                         "kappa": 0.71, "ac1": 0.68}}
            intent = f"{site} a plan that meets the hard constraints but falls outside the acceptable set must not be counted as qualified."
            TASKS.append(_gen(
                tid, "plans:core", "FE", "acceptable_set_hit",
                "plan_hits_acceptable_family",
                intent,
                "plans/core.py:469-791 optimal_plan (set-valued selection); oracles/geom.py:246-317",
                {"plan": good, "acceptable_families": [],
                 "expert_membership": ok_expert},
                neg, fixture=site, seed=1800 + n,
                contrast="plans/core/acceptable_set"))
        else:
            TASKS.append(_gen(
                tid, "plans:core", "FE", "acceptable_set_hit",
                "plan_hits_acceptable_family",
                f"{site} an under-covered plan must still clear the O1 hard constraints even if it hits an expert family.",
                "plans/core.py:469-791; oracles/geom.py:267-276 (O1 layer first)",
                {"plan": _plan(site), "acceptable_families": [],
                 "expert_membership": ok_expert},
                {"plan": _plan(site, coverage=0.82), "acceptable_families": [],
                 "expert_membership": ok_expert},
                fixture=site, seed=1800 + n,
                contrast="plans/core/acceptable_set"))


# ===========================================================================
# plans:utilizations -- plans/utilizations.py (F,E,I)
# ===========================================================================

def gen_util() -> None:
    n = 0
    prof = list(ANATOMY)
    samples = [[10.0, 20.0, 30.0], [10.0, 20.0, 38.0], [24.0, 20.0, 30.0]]
    # --- coord_roundtrip: position_transform / direction_transform (I dim) ---
    for i, site in enumerate(prof):
        for v in range(3):
            n += 1
            tid = f"PLAN-UTIL-{n:03d}"
            origin = ANATOMY[site]["origin"]
            spacing = ANATOMY[site]["spacing"]
            pos = {"samples": samples, "origin": origin, "spacing": spacing,
                   "direction": DIR_I}
            if v == 0:
                neg = {"samples": samples, "origin": origin, "spacing": spacing,
                       "direction": DIR_MIRROR_X}
                intent = f"{site} position_transform must use a right-handed direction matrix; a reflection matrix is illegal."
            elif v == 1:
                neg = {"samples": samples, "origin": origin, "spacing": spacing,
                       "direction": DIR_SCALED2}
                intent = f"{site} the direction matrix is scaled; a non-orthogonal matrix must be rejected."
            else:
                neg = {"samples": samples, "origin": origin, "spacing": spacing,
                       "direction": DIR_I,
                       "header_a": {"origin": origin, "spacing": spacing,
                                    "direction": DIR_I},
                       "header_b": {"origin": [origin[0] + 0.25, origin[1], origin[2]],
                                    "spacing": spacing, "direction": DIR_I}}
                intent = f"{site} the two world-coordinate headers have different origins; the interoperability round trip must flag them inconsistent."
            TASKS.append(_gen(
                tid, "plans:utilizations", "FI", "coord_roundtrip",
                "voxel_world_transform_roundtrip",
                intent,
                "plans/utilizations.py:217-272 position_transform/direction_transform; plans/geometry.py:14-48",
                pos, neg, fixture=site, seed=2100 + n,
                contrast="plans/utilizations/coord_roundtrip"))

    # --- param_binding: dose / volume units & metric scope -------------------
    binds = [
        ("bladder", "D2cc", 75.0, "Gy", 75.0),
        ("rectum", "D2cc", 65.0, "Gy", 65.0),
        ("ctv", "D90", 145.0, "Gy", 145.0),
        ("ctv", "D100", 130.0, "Gy", 130.0),
        ("ctv", "V100", 91.2, "%", 91.2),
        ("urethra", "V150", 30.0, "%", 30.0),
        ("rectum", "V200", 15.0, "%", 15.0),
        ("bladder", "D2cc", 7500.0, "cGy", 75.0),
        ("ctv", "D90", 145000.0, "mGy", 145.0),
        ("urethra", "D2cc", 120.0, "Gy(RBE)", 120.0),
        ("prostate", "V100", 97.5, "percent", 97.5),
        ("ctv", "D90", 128.0, "Gy", 128.0),
    ]
    for i, (tgt, met, val, unit, gy) in enumerate(binds):
        n += 1
        tid = f"PLAN-UTIL-{n:03d}"
        pos = {"bindings": [{"target": tgt, "metric": met, "value": val,
                             "unit": unit, "bound_target": tgt,
                             "bound_metric": met, "value_gy": gy}]}
        if i % 4 == 0:
            neg = {"bindings": [{"target": tgt, "metric": met, "value": val,
                                 "unit": unit, "bound_target": "rectum",
                                 "bound_metric": met, "value_gy": gy}]}
            intent = "A multi-target dose request must bind values to the correct organ; no cross-wiring."
        elif i % 4 == 1:
            neg = {"bindings": [{"target": tgt, "metric": met, "value": val,
                                 "unit": unit, "bound_target": tgt,
                                 "bound_metric": "V100", "value_gy": gy}]}
            intent = "D90/D2cc and V100 must not be confused; the metric scope must be correct."
        elif i % 4 == 2:
            neg = {"bindings": [{"target": tgt, "metric": met, "value": val,
                                 "unit": "cGy", "bound_target": tgt,
                                 "bound_metric": met, "value_gy": val}]}
            intent = "cGy/mGy must be converted to Gy and must not be used as Gy verbatim."
        else:
            neg = {"bindings": [{"target": tgt, "metric": "V100", "value": val,
                                 "unit": "Gy", "bound_target": tgt,
                                 "bound_metric": "V100", "value_gy": None}]}
            intent = "V-type metrics are volume percentages; writing Gy is a dimensional confusion and must fail."
        TASKS.append(_gen(
            tid, "plans:utilizations", "FE", "param_binding",
            "dose_metric_unit_binding",
            intent,
            "plans/utilizations.py (dose value binding); oracles/geom.py:501-568",
            pos, neg, fixture="prostate", seed=2200 + n,
            contrast="plans/utilizations/param_binding",
            difficulty="hard" if i % 4 == 3 else "medium"))

    # --- seed_geometry_fidelity: PCA reference direction anchors seed chain ---
    for i in range(10):
        n += 1
        tid = f"PLAN-UTIL-{n:03d}"
        site = prof[i % 4]
        base = _seeds(site)
        eng = copy.deepcopy(base)
        if i % 3 == 0:
            eng[-1]["pos_mm"][1] += 0.2
            intent = f"{site} the seed chain drifts after the PCA reference direction is deflected and must be detected."
        elif i % 3 == 1:
            eng[0]["traj"] = "tX"
            intent = f"{site} a seed's needle-tract label was altered; geometry fidelity must detect it."
        else:
            eng = eng[:-1]
            intent = f"{site} the engine received fewer seeds on the PCA chain."
        TASKS.append(_gen(
            tid, "plans:utilizations", "FE", "seed_geometry_fidelity",
            "pca_reference_seed_chain_fidelity",
            intent,
            "plans/utilizations.py:289-324 get_reference_direction (PCA); oracles/geom.py:25-86",
            {"engine_seeds": copy.deepcopy(base), "cws_seeds": copy.deepcopy(base)},
            {"engine_seeds": eng, "cws_seeds": copy.deepcopy(base)},
            fixture=site, seed=2300 + n,
            contrast="plans/utilizations/pca_seed_chain"))

    # --- error_contract: cone / PCA / direction input validation -------------
    for i in range(10):
        n += 1
        tid = f"PLAN-UTIL-{n:03d}"
        if i % 2 == 0:
            pos = {"errors": [{"code": "INVALID_CONE_AXIS",
                               "message": "dire must be a non-zero finite 3-D vector",
                               "retryable": False, "op_id": f"op_cone_{i}"}]}
            neg = {"errors": [{"code": "INVALID_CONE_AXIS",
                               "message": "dire must be a non-zero finite 3-D vector",
                               "retryable": True, "op_id": f"op_cone_{i}"}]}
            intent = "An illegal cone-candidate axis (zero vector) must return a non-retryable structured error."
        elif i % 2 == 1:
            pos = {"errors": [{"code": "TARGET_MISSING",
                               "message": "No target area in your input array",
                               "retryable": False, "op_id": f"op_pca_{i}"}]}
            neg = {"errors": [{"code": "TARGET_MISSING",
                               "message": "", "retryable": False,
                               "op_id": f"op_pca_{i}"}]}
            intent = "The error message must not be empty when the target region for the PCA reference direction is missing."
        TASKS.append(_gen(
            tid, "plans:utilizations", "E", "error_contract",
            "cone_pca_input_validation",
            intent,
            "plans/utilizations.py:858-864 get_cone axis validation; :313 PCA assert; oracles/recovery.py:19-65",
            pos, neg, fixture="recovery", seed=2400 + n,
            contrast="plans/utilizations/input_validation"))

    # --- hard_constraint: parallel needle spacing policy ---------------------
    for i in range(8):
        n += 1
        tid = f"PLAN-UTIL-{n:03d}"
        site = prof[i % 4]
        good = _plan(site, spacing_mm=8.0)
        if i % 2 == 0:
            bad = _plan(site, spacing_mm=2.0)
            intent = "A candidate must be rejected when near-parallel needle center distance is below the guide bore diameter."
        else:
            bad = _plan(site, clearance=1.0)
            intent = "A candidate tract must be rejected when needle endpoint clearance is insufficient."
        TASKS.append(_gen(
            tid, "plans:utilizations", "FE", "hard_constraint",
            "parallel_spacing_safety",
            intent,
            "plans/utilizations.py:3471-3534 get_trajectory_spacing_safety_mask; oracles/geom.py:204-221",
            {"plan": good}, {"plan": bad}, fixture=site, seed=2500 + n,
            contrast="plans/utilizations/parallel_spacing"))

    # --- semantic_equivalence: deterministic cone / PCA ----------------------
    for i in range(8):
        n += 1
        tid = f"PLAN-UTIL-{n:03d}"
        site = prof[i % 4]
        a = {"conclusion": "cone_generated",
             "recommendation": "sample_directions",
             "numbers": {"n_candidates": 1 + 3 * 6, "half_angle_deg": 15.0,
                         "sectors": 6}}
        neg_b = copy.deepcopy(a)
        neg_b["numbers"]["n_candidates"] = 7
        TASKS.append(_gen(
            tid, "plans:utilizations", "FE", "semantic_equivalence",
            "cone_candidate_generation_deterministic",
            f"{site} the cone-candidate set for the same axis / half-angle must be identical across runs (at least 6 sectors around the circumference).",
            "plans/utilizations.py:840-908 get_cone; oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture=site, seed=2600 + n,
            contrast="plans/utilizations/cone_determinism"))


# ===========================================================================
# plans:geometry -- plans/geometry.py (F,E,S)
# ===========================================================================

def _inter_pairs(site: str):
    """Return (endpoint_only_pair, crossing_pair) for a clinical site."""
    ox, oy, oz = ANATOMY[site]["origin"]
    base = [ox + 40.0, oy + 40.0, oz + 40.0]
    # two parallel needles 12 mm apart -> closest pair at segment starts
    endpoint = {
        "id": "pair_endpoint",
        "s": [list(base), [base[0] + 60.0, base[1], base[2]]],
        "t": [[base[0], base[1] + 12.0, base[2]],
              [base[0] + 60.0, base[1] + 12.0, base[2]]],
    }
    # a genuine interior crossing
    crossing = {
        "id": "pair_crossing",
        "s": [list(base), [base[0] + 60.0, base[1], base[2]]],
        "t": [[base[0] + 30.0, base[1] - 20.0, base[2]],
              [base[0] + 30.0, base[1] + 20.0, base[2]]],
    }
    return endpoint, crossing


def gen_geo() -> None:
    n = 0
    # --- interference_fp: endpoint contact is NOT overlap (S) ----------------
    for i, site in enumerate(list(ANATOMY)):
        endpoint, crossing = _inter_pairs(site)
        for v in range(4):
            n += 1
            tid = f"PLAN-GEO-{n:03d}"
            ep = copy.deepcopy(endpoint); ep["id"] = f"ep{v}"
            cr = copy.deepcopy(crossing); cr["id"] = f"cr{v}"
            if v % 2 == 0:
                pos_preds = [{**ep, "predicted_risk": "none"},
                             {**cr, "predicted_risk": "overlap"}]
                # false positive: call the endpoint contact an overlap
                neg_preds = [{**ep, "predicted_risk": "overlap"},
                             {**cr, "predicted_risk": "overlap"}]
                intent = f"{site} endpoint contact (u≈0) is not a physical overlap; the classifier must not falsely report overlap."
            else:
                pos_preds = [{**ep, "predicted_risk": "none"}]
                neg_preds = [{**ep, "predicted_risk": "warning"}]
                intent = f"{site} a tract with only endpoint contact must not be given a warning and must be judged interference-free."
            TASKS.append(_gen(
                tid, "plans:geometry", "FS", "interference_fp",
                "endpoint_contact_not_interference",
                intent,
                "plans/geometry.py:1323-1393 ray_min_distance; oracles/geom.py:394-498",
                {"predictions": pos_preds}, {"predictions": neg_preds},
                fixture=site, seed=3100 + n,
                contrast="plans/geometry/interference_fp",
                difficulty="hard"))

    # --- hard_constraint: needle spacing / clearance / OAR -------------------
    for i in range(14):
        n += 1
        tid = f"PLAN-GEO-{n:03d}"
        site = list(ANATOMY)[i % 4]
        good = _plan(site)
        v = i % 5
        if v == 0:
            bad = _plan(site, spacing_mm=3.5)
            intent = "A needle center distance of 3.5mm is below the 5mm hard constraint and must be rejected."
        elif v == 1:
            bad = _plan(site, clearance=1.5)
            intent = "Needle endpoint clearance of 1.5mm is below the 2mm hard constraint."
        elif v == 2:
            bad = _plan(site, coverage=0.86)
            intent = "CTV coverage of 86% is below the 90% hard constraint."
        elif v == 3:
            bad = _plan(site, oar={"rectum": {"D2cc": 82.0}})
            intent = "Rectum D2cc of 82Gy exceeds the 75Gy hard limit."
        else:
            base = _plan(site)
            base["seeds"] = base["seeds"] * 60
            bad = base
            intent = "The seed count exceeds the hard cap; the geometric plan must not pass."
        limits = {}
        if v == 3:
            limits = {"oar_limits": {"rectum": {"metric": "D2cc",
                                                 "limit": 75.0}}}
        TASKS.append(_gen(
            tid, "plans:geometry", "FES", "hard_constraint",
            "needle_clearance_and_oar_limits",
            intent,
            "plans/geometry.py:1235-1275 line_to_line_distance; oracles/geom.py:168-243",
            {"plan": good, "limits": limits},
            {"plan": bad, "limits": limits}, fixture=site, seed=3200 + n,
            contrast="plans/geometry/hard_limits"))

    # --- seed_geometry_fidelity: ray start/direction geometry ----------------
    for i in range(10):
        n += 1
        tid = f"PLAN-GEO-{n:03d}"
        site = list(ANATOMY)[i % 4]
        base = _seeds(site)
        eng = copy.deepcopy(base)
        if i % 2 == 0:
            eng[0]["pos_mm"][2] += 1e-3
            intent = "A ray origin drift of 1e-3mm from the plan already exceeds the geometric tolerance."
        else:
            eng[0]["activity_u"] = 0.99
            intent = "The ray-origin seed activity does not match; geometry fidelity must detect it."
        TASKS.append(_gen(
            tid, "plans:geometry", "FE", "seed_geometry_fidelity",
            "ray_origin_geometry_fidelity",
            intent,
            "plans/geometry.py:256-405 ray_tracing; oracles/geom.py:25-86",
            {"engine_seeds": copy.deepcopy(base), "cws_seeds": copy.deepcopy(base)},
            {"engine_seeds": eng, "cws_seeds": copy.deepcopy(base)},
            fixture=site, seed=3300 + n,
            contrast="plans/geometry/ray_geometry"))

    # --- coord_roundtrip: geometry.voxel_to_world ----------------------------
    samples = [[5.0, 6.0, 7.0], [15.0, 16.0, 17.0]]
    for i, site in enumerate(list(ANATOMY)):
        for v in range(2):
            n += 1
            tid = f"PLAN-GEO-{n:03d}"
            origin = ANATOMY[site]["origin"]
            spacing = ANATOMY[site]["spacing"]
            pos = {"samples": samples, "origin": origin, "spacing": spacing,
                   "direction": DIR_I}
            if v == 0:
                neg = {"samples": samples, "origin": origin, "spacing": spacing,
                       "direction": DIR_MIRROR_X}
                intent = "voxel_to_world must preserve a right-handed system; a reflection matrix is illegal."
            else:
                neg = {"samples": samples, "origin": origin, "spacing": spacing,
                       "direction": DIR_I,
                       "header_a": {"origin": origin, "spacing": spacing,
                                    "direction": DIR_I},
                       "header_b": {"origin": [origin[0] + 0.25, origin[1],
                                              origin[2]],
                                    "spacing": spacing, "direction": DIR_I}}
                intent = "The two voxel/world coordinate headers have different origins; the interoperability round trip must detect it."
            TASKS.append(_gen(
                tid, "plans:geometry", "FE", "coord_roundtrip",
                "voxel_to_world_geometry",
                intent,
                "plans/geometry.py:14-48 voxel_to_world; oracles/coord_roundtrip.py:48-158",
                pos, neg, fixture=site, seed=3400 + n,
                contrast="plans/geometry/voxel_world"))

    # --- error_contract: zero normals / degenerate rays ----------------------
    for i in range(10):
        n += 1
        tid = f"PLAN-GEO-{n:03d}"
        if i % 2 == 0:
            pos = {"errors": [{"code": "DEGENERATE_NORMAL",
                               "message": "zero normal cannot advance the voxel walk",
                               "retryable": False, "op_id": f"op_ray_{i}"}]}
            neg = {"errors": [{"code": "DEGENERATE_NORMAL",
                               "message": "zero normal cannot advance the voxel walk",
                               "retryable": True, "op_id": f"op_ray_{i}"}]}
            intent = "A zero-normal ray must return a non-retryable error."
        else:
            pos = {"errors": [{"code": "RAY_DEGENERATE",
                               "message": "Direction vectors must be non-zero",
                               "retryable": False, "op_id": f"op_ray_{i}"}]}
            neg = {"errors": [{"code": "RAY_DEGENERATE", "message": "",
                               "retryable": False, "op_id": f"op_ray_{i}"}]}
            intent = "The zero-direction-vector error in collinear distance computation must have a non-empty message."
        TASKS.append(_gen(
            tid, "plans:geometry", "E", "error_contract",
            "degenerate_ray_error_envelope",
            intent,
            "plans/geometry.py:548-565 is_ray_blocked; :1258-1259 zero direction; oracles/recovery.py:19-65",
            pos, neg, fixture="recovery", seed=3500 + n,
            contrast="plans/geometry/ray_errors"))


# ===========================================================================
# plans:reinforcement -- plans/reinforcement.py (F,E,R)
# ===========================================================================

def gen_reinf() -> None:
    n = 0
    # --- state_invariant: failed/interrupted RL leaves state intact ----------
    for i in range(14):
        n += 1
        tid = f"PLAN-REINF-{n:03d}"
        site = list(ANATOMY)[i % 4]
        before = {"plan": {"status": "ready", "seeds": _seeds(site),
                           "planning_version": 5, "receipts": []},
                  "dose": {"computed": False}}
        after = copy.deepcopy(before)
        if i % 2 == 0:
            intent = f"{site} RL must leave the plan unchanged when interrupted by wall_clock_budget."
        else:
            intent = f"{site} RL must not leave a partial needle tract after raising internal_exception."
        TASKS.append(_gen(
            tid, "plans:reinforcement", "FER", "state_invariant",
            "rl_interrupt_leaves_state_intact",
            intent,
            "plans/reinforcement.py:1538-2303 reinforcement_planning deadline paths; oracles/recovery.py:68-121",
            {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
            {"before": copy.deepcopy(before),
             "after": {**copy.deepcopy(after),
                       "plan": {**after["plan"], "seeds": _seeds(site)[:1]}}},
            fixture=site, seed=4100 + n,
            contrast="plans/reinforcement/interrupt_state_intact"))

    # --- error_contract: RL stop/failure vocabulary --------------------------
    codes = [
        ("TIMEOUT", "dose inference deadline reached", True),
        ("OOM_RETRY", "cuda OOM during policy forward", True),
        ("BUSY", "policy net busy on another request", True),
        ("INVALID_GEOMETRY", "plan contains a dose map with wrong grid", False),
        ("UNAVAILABLE", "dose model unavailable", True),
        ("NETWORK", "dose service connection reset", True),
    ]
    for i in range(12):
        n += 1
        tid = f"PLAN-REINF-{n:03d}"
        code, msg, retry = codes[i % len(codes)]
        pos = {"errors": [{"code": code, "message": msg, "retryable": retry,
                           "op_id": f"op_rl_{i}"}]}
        if i % 2 == 0:
            neg = {"errors": [{"code": code, "message": msg,
                               "retryable": not retry, "op_id": f"op_rl_{i}"}]}
            intent = f"The retryable flag for RL error {code} must be consistent with the error code."
        else:
            neg = {"errors": [{"code": code, "message": "", "retryable": retry,
                               "op_id": f"op_rl_{i}"}]}
            intent = f"RL error {code} must carry a non-empty message."
        TASKS.append(_gen(
            tid, "plans:reinforcement", "ER", "error_contract",
            "rl_error_vocabulary",
            intent,
            "plans/reinforcement.py:2300-2307 internal_exception/status; oracles/recovery.py:26-65",
            pos, neg, fixture="recovery", seed=4200 + n,
            contrast="plans/reinforcement/error_vocabulary"))

    # --- receipt_complete: RL mutations are receipted ------------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-REINF-{n:03d}"
        site = list(ANATOMY)[i % 4]
        ms, rs = _rc([
            ("op_rl_init", {"site": site, "candidate_cap": 500}),
            ("op_place_needle", {"needle": 1, "spacing_mm": 8.0}),
            ("op_place_seed", {"seed": "s1", "activity_u": ANATOMY[site]["activity_u"]}),
        ])
        if i % 2 == 0:
            neg_ms = copy.deepcopy(ms)
            neg_ms[1]["payload"] = {"needle": 2, "spacing_mm": 8.0}
            neg = {"mutations": neg_ms, "receipts": copy.deepcopy(rs)}
            intent = f"{site} the receipt hash must not match when an RL mutation payload is altered."
        else:
            neg = {"mutations": copy.deepcopy(ms),
                   "receipts": [copy.deepcopy(rs[0]), copy.deepcopy(rs[2])]}
            intent = f"{site} RL must be judged as having an incomplete receipt chain when a state-change receipt is missing."
        TASKS.append(_gen(
            tid, "plans:reinforcement", "FR", "receipt_complete",
            "rl_mutation_receipt_chain",
            intent,
            "plans/reinforcement.py:1192-1221 construct_plan_over_candidates; oracles/recovery.py:124-177",
            {"mutations": ms, "receipts": rs}, neg,
            fixture=site, seed=4300 + n, contrast="plans/reinforcement/receipts"))

    # --- semantic_equivalence: deterministic RL selection --------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-REINF-{n:03d}"
        site = list(ANATOMY)[i % 4]
        a = {"conclusion": "plan_constructed",
             "recommendation": "accept_rl_plan",
             "numbers": {"seeds": 4, "needles": 2,
                         "coverage": 0.93, "objective": 2.93}}
        neg_b = copy.deepcopy(a)
        neg_b["numbers"]["objective"] = 2.10
        TASKS.append(_gen(
            tid, "plans:reinforcement", "FE", "semantic_equivalence",
            "rl_plan_reproducible",
            f"{site} plans built by RL from the same candidate pool and budget must yield the same seed/needle counts and objective value.",
            "plans/reinforcement.py:1102-1172 evaluate_plan_objective/plan_cost_counts; oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture=site, seed=4400 + n,
            contrast="plans/reinforcement/determinism"))

    # --- hard_constraint: RL plan limits -------------------------------------
    for i in range(8):
        n += 1
        tid = f"PLAN-REINF-{n:03d}"
        site = list(ANATOMY)[i % 4]
        good = _plan(site)
        if i % 2 == 0:
            bad = _plan(site, spacing_mm=3.0)
            intent = "An RL plan with needle spacing below the 5mm hard constraint must not be accepted during construction."
        else:
            bad = _plan(site, coverage=0.88)
            intent = "The RL plan's CTV coverage fails the hard constraint."
        TASKS.append(_gen(
            tid, "plans:reinforcement", "FE", "hard_constraint",
            "rl_plan_hard_limits",
            intent,
            "plans/reinforcement.py:1261-1420 sequential safety filter; oracles/geom.py:168-243",
            {"plan": good}, {"plan": bad}, fixture=site, seed=4500 + n,
            contrast="plans/reinforcement/hard_limits"))


# ===========================================================================
# plans:coverage_repair -- plans/coverage_repair.py (F,E,R)
# ===========================================================================

def gen_repair() -> None:
    n = 0
    # --- state_invariant: copy-on-reject must not mutate the accepted plan ---
    for i in range(16):
        n += 1
        tid = f"PLAN-REPAIR-{n:03d}"
        site = list(ANATOMY)[i % 4]
        seeded = _seeds(site)
        before = {"plan": {"status": "ready", "seeds": copy.deepcopy(seeded),
                           "coverage": {"ctv": 0.87}},
                  "dose": {"computed": True}}
        after = copy.deepcopy(before)
        if i % 2 == 0:
            intent = f"{site} a rejected repair (no_safe_positive_gain) must not modify the accepted plan."
        else:
            intent = f"{site} a repair timeout (time_budget) must roll back to the pre-repair seed set."
        TASKS.append(_gen(
            tid, "plans:coverage_repair", "FER", "state_invariant",
            "repair_copy_on_reject",
            intent,
            "plans/coverage_repair.py:28-51,145-159 copy-on-reject + stop_reason; oracles/recovery.py:68-121",
            {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
            {"before": copy.deepcopy(before),
             "after": {**copy.deepcopy(after),
                       "plan": {**after["plan"],
                                "seeds": _seeds(site) + [{"id": "sX",
                                                          "pos_mm": [0.0, 0.0, 0.0]}]}}},
            fixture=site, seed=5100 + n,
            contrast="plans/coverage_repair/copy_on_reject",
            difficulty="hard"))

    # --- semantic_equivalence: stop_reason determinism -----------------------
    stops = ["target_reached", "time_budget", "no_residual",
             "no_safe_positive_gain", "round_budget", "disabled_or_empty"]
    for i in range(14):
        n += 1
        tid = f"PLAN-REPAIR-{n:03d}"
        site = list(ANATOMY)[i % 4]
        stop = stops[i % len(stops)]
        a = {"conclusion": stop,
             "recommendation": "return_plan" if stop != "disabled_or_empty"
             else "return_original",
             "numbers": {"initial_coverage": 0.87, "final_coverage": 0.93,
                         "trials": 12, "added_seeds": 3}}
        if i % 2 == 0:
            neg_b = copy.deepcopy(a)
            neg_b["conclusion"] = "internal_exception"
            intent = f"{site} when repair reaches the target, stop_reason must be target_reached, not an internal exception."
        else:
            neg_b = copy.deepcopy(a)
            neg_b["numbers"]["final_coverage"] = 0.99
            intent = f"{site} final coverage must be identical under the same repair budget and must not be tampered with."
        TASKS.append(_gen(
            tid, "plans:coverage_repair", "FE", "semantic_equivalence",
            "repair_stop_reason_deterministic",
            intent,
            "plans/coverage_repair.py:47-63,160-163 stop_reason contract; oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture=site, seed=5200 + n,
            contrast="plans/coverage_repair/stop_reason"))

    # --- idempotency: re-running a converged repair is a no-op ---------------
    for i in range(10):
        n += 1
        tid = f"PLAN-REPAIR-{n:03d}"
        site = list(ANATOMY)[i % 4]
        state = {"plan": {"status": "ready", "seeds": _seeds(site),
                          "coverage": {"ctv": 0.93},
                          "receipts": [{"op_id": "op_repair"}]},
                 "ui": {"version_fence": {"state_seq": 2}}}
        if i % 2 == 0:
            neg = copy.deepcopy(state)
            neg["plan"]["coverage"]["ctv"] = 0.87
            intent = f"{site} re-running a converged repair must be idempotent and must not lower coverage."
        else:
            neg = copy.deepcopy(state)
            neg["plan"]["status"] = "final"
            intent = f"{site} the plan status must not advance when the repair has not yet changed the plan."
        TASKS.append(_gen(
            tid, "plans:coverage_repair", "FR", "idempotency",
            "repair_converged_is_noop",
            intent,
            "plans/coverage_repair.py:49-51 target_reached early return; oracles/recovery.py:180-214",
            {"states": [copy.deepcopy(state), copy.deepcopy(state)]},
            {"states": [copy.deepcopy(state), neg]},
            fixture=site, seed=5300 + n,
            contrast="plans/coverage_repair/idempotent"))

    # --- error_contract: repair failure envelopes ----------------------------
    for i in range(8):
        n += 1
        tid = f"PLAN-REPAIR-{n:03d}"
        pos = {"errors": [{"code": "REPAIR_NO_TARGET",
                           "message": "no target voxels; repair disabled",
                           "retryable": False, "op_id": f"op_repair_{i}"}]}
        if i % 2 == 0:
            neg = {"errors": [{"code": "REPAIR_NO_TARGET",
                               "message": "no target voxels; repair disabled",
                               "retryable": True, "op_id": f"op_repair_{i}"}]}
            intent = "A repair failure with no target voxels must be marked non-retryable."
        else:
            neg = {"errors": [{"code": "REPAIR_NO_TARGET", "message": "",
                               "retryable": False, "op_id": f"op_repair_{i}"}]}
            intent = "A repair failure must carry a structured non-empty message."
        TASKS.append(_gen(
            tid, "plans:coverage_repair", "ER", "error_contract",
            "repair_error_envelope",
            intent,
            "plans/coverage_repair.py:49-51 disabled_or_empty; oracles/recovery.py:19-65",
            pos, neg, fixture="recovery", seed=5400 + n,
            contrast="plans/coverage_repair/error_envelope"))

    # --- hard_constraint: repaired plan must still satisfy limits ------------
    for i in range(8):
        n += 1
        tid = f"PLAN-REPAIR-{n:03d}"
        site = list(ANATOMY)[i % 4]
        good = _plan(site, coverage=0.93)
        if i % 2 == 0:
            bad = _plan(site, clearance=1.0, coverage=0.93)
            intent = "A repair that pushes endpoint clearance below 2mm must be rejected."
        else:
            bad = _plan(site, spacing_mm=2.5, coverage=0.93)
            intent = "A repair whose new tract has insufficient near-parallel spacing to existing needles must be rejected."
        TASKS.append(_gen(
            tid, "plans:coverage_repair", "FE", "hard_constraint",
            "repair_preserves_hard_limits",
            intent,
            "plans/coverage_repair.py:130 validate(trajectory, others); oracles/geom.py:168-243",
            {"plan": good}, {"plan": bad}, fixture=site, seed=5500 + n,
            contrast="plans/coverage_repair/hard_limits"))


# ===========================================================================
# plans:brachy_plan -- plans/brachy_plan_v2.py (F,E,R)
# ===========================================================================

def gen_brachy() -> None:
    n = 0
    # --- state_invariant: pipeline failure leaves workspace intact -----------
    for i in range(14):
        n += 1
        tid = f"PLAN-BRACHY-{n:03d}"
        site = list(ANATOMY)[i % 4]
        before = {"case": {"id": f"{site}_case", "ct": {"loaded": True}},
                  "plan": {"status": "ready", "seeds": _seeds(site)},
                  "dose": {"computed": False}}
        after = copy.deepcopy(before)
        if i % 2 == 0:
            intent = f"{site} the planning state must remain at its initial state when dose normalization raises."
        else:
            intent = f"{site} a partial dose must not be written when optimal_plan fails."
        TASKS.append(_gen(
            tid, "plans:brachy_plan", "FER", "state_invariant",
            "pipeline_failure_leaves_workspace_intact",
            intent,
            "plans/brachy_plan_v2.py:56-64,157-172 (every failure raises); oracles/recovery.py:68-121",
            {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
            {"before": copy.deepcopy(before),
             "after": {**copy.deepcopy(after),
                       "dose": {"computed": True, "sum_array_id": "half"}}},
            fixture=site, seed=6100 + n,
            contrast="plans/brachy_plan/failure_state_intact"))

    # --- error_contract: pipeline error envelopes ----------------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-BRACHY-{n:03d}"
        if i % 3 == 0:
            pos = {"errors": [{"code": "TIMEOUT",
                               "message": "DoseUNet deadline during planning",
                               "retryable": True, "op_id": f"op_plan_{i}"}]}
            neg = {"errors": [{"code": "TIMEOUT",
                               "message": "DoseUNet deadline during planning",
                               "retryable": False, "op_id": f"op_plan_{i}"}]}
            intent = "A DoseUNet timeout must be marked retryable."
        elif i % 3 == 1:
            pos = {"errors": [{"code": "INVALID_DOSE_IMAGE",
                               "message": "dose_image is not a SimpleITK image",
                               "retryable": False, "op_id": f"op_plan_{i}"}]}
            neg = {"errors": [{"code": "INVALID_DOSE_IMAGE", "message": "",
                               "retryable": False, "op_id": f"op_plan_{i}"}]}
            intent = "A planning input type error must return a non-empty structured message."
        else:
            pos = {"errors": [{"code": "NO_TARGET_VOXELS",
                               "message": "radiation volume has no target voxels",
                               "retryable": False, "op_id": f"op_plan_{i}"}]}
            neg = {"errors": [{"code": "NO_TARGET_VOXELS",
                               "message": "radiation volume has no target voxels",
                               "retryable": True, "op_id": f"op_plan_{i}"}]}
            intent = "Missing target voxels is a non-retryable input error."
        TASKS.append(_gen(
            tid, "plans:brachy_plan", "ER", "error_contract",
            "pipeline_error_envelope",
            intent,
            "plans/brachy_plan_v2.py:34-172 brachy_plan; oracles/recovery.py:19-65",
            pos, neg, fixture="recovery", seed=6200 + n,
            contrast="plans/brachy_plan/error_envelope"))

    # --- hard_constraint: output plan limits ---------------------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-BRACHY-{n:03d}"
        site = list(ANATOMY)[i % 4]
        good = _plan(site)
        v = i % 3
        if v == 0:
            bad = _plan(site, coverage=0.87)
            intent = f"{site} the planning output's CTV coverage fails the hard constraint."
        elif v == 1:
            bad = _plan(site, spacing_mm=3.0)
            intent = f"{site} the planning output's needle spacing is below the hard constraint."
        else:
            bad = _plan(site, clearance=1.4)
            intent = f"{site} the planning output's endpoint clearance fails the hard constraint."
        TASKS.append(_gen(
            tid, "plans:brachy_plan", "FE", "hard_constraint",
            "pipeline_output_hard_limits",
            intent,
            "plans/brachy_plan_v2.py:160-172 sum_array + plan_res contract; oracles/geom.py:168-243",
            {"plan": good}, {"plan": bad}, fixture=site, seed=6300 + n,
            contrast="plans/brachy_plan/output_limits"))

    # --- acceptable_set_hit: output plan acceptable family -------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-BRACHY-{n:03d}"
        site = list(ANATOMY)[i % 4]
        good = _plan(site)
        if i % 2 == 0:
            neg = {"plan": good, "acceptable_families": [],
                   "expert_membership": {"family_id": "AE_family_7",
                                         "acceptable": False,
                                         "kappa": 0.66, "ac1": 0.64}}
            intent = f"{site} a plan that meets the hard constraints but is judged unacceptable by experts must not count as qualified."
        else:
            neg = {"plan": _plan(site, coverage=0.84), "acceptable_families": [],
                   "expert_membership": {"family_id": "AE_family_7",
                                         "acceptable": True, "kappa": 0.9,
                                         "ac1": 0.88}}
            intent = f"{site} a low-coverage plan must still clear the hard constraints even if it is within an acceptable family."
        TASKS.append(_gen(
            tid, "plans:brachy_plan", "FE", "acceptable_set_hit",
            "pipeline_output_acceptable_set",
            intent,
            "plans/brachy_plan_v2.py:175-325 brachy_plan_rf; oracles/geom.py:246-317",
            {"plan": good, "acceptable_families": [],
             "expert_membership": {"family_id": "AE_family_7",
                                   "acceptable": True, "kappa": 0.9, "ac1": 0.88}},
            neg, fixture=site, seed=6400 + n,
            contrast="plans/brachy_plan/acceptable_set"))

    # --- semantic_equivalence: deterministic plan result ---------------------
    for i in range(8):
        n += 1
        tid = f"PLAN-BRACHY-{n:03d}"
        site = list(ANATOMY)[i % 4]
        a = {"conclusion": "plan_produced",
             "recommendation": "finalize",
             "numbers": {"seed_count": 4, "needle_count": 2,
                         "sum_array_max": 2.4}}
        neg_b = copy.deepcopy(a)
        neg_b["numbers"]["seed_count"] = 5
        TASKS.append(_gen(
            tid, "plans:brachy_plan", "FE", "semantic_equivalence",
            "pipeline_result_reproducible",
            f"{site} repeated runs on the same input must yield identical needle/seed counts and dose sum.",
            "plans/brachy_plan_v2.py:160-172 deterministic accumulation; oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture=site, seed=6500 + n,
            contrast="plans/brachy_plan/determinism"))


# ===========================================================================
# plans:device_manager -- plans/device_manager.py (F,E,R,A)
# ===========================================================================

def gen_device() -> None:
    n = 0
    # --- error_contract: GPU/OOM failure vocabulary --------------------------
    errs = [
        ("OOM_RETRY", "cuda:0 out of memory; retrying next device", True),
        ("TIMEOUT", "nvidia-smi probe timed out", True),
        ("UNAVAILABLE", "no CUDA device visible; using CPU", True),
        ("BUSY", "device lease queue full", True),
        ("NETWORK", "pynvml init failed over network share", True),
        ("UNKNOWN_DEVICE", "GPU 7 requested but not available; using cpu", False),
    ]
    for i in range(16):
        n += 1
        tid = f"PLAN-DEV-{n:03d}"
        code, msg, retry = errs[i % len(errs)]
        pos = {"errors": [{"code": code, "message": msg, "retryable": retry,
                           "op_id": f"op_dev_{i}"}]}
        if i % 2 == 0:
            neg = {"errors": [{"code": code, "message": msg,
                               "retryable": not retry, "op_id": f"op_dev_{i}"}]}
            intent = f"The retryable flag for device error {code} must match the error code semantics."
        else:
            neg = {"errors": [{"code": code, "message": "", "retryable": retry,
                               "op_id": f"op_dev_{i}"}]}
            intent = f"Device error {code} must carry a structured message."
        TASKS.append(_gen(
            tid, "plans:device_manager", "ER", "error_contract",
            "device_oom_error_envelope",
            intent,
            "plans/device_manager.py:437-461 handle_oom; oracles/recovery.py:29 RETRYABLE_CODES",
            pos, neg, fixture="security", seed=7100 + n,
            contrast="plans/device_manager/error_envelope"))

    # --- receipt_complete: device lease audit chain (A) ----------------------
    for i in range(14):
        n += 1
        tid = f"PLAN-DEV-{n:03d}"
        ms, rs = _rc([
            ("op_acquire", {"caller": "ctv_seg", "device": "cuda:1",
                            "free_mb": 20480}),
            ("op_forward", {"caller": "ctv_seg", "device": "cuda:1"}),
            ("op_release", {"caller": "ctv_seg", "device": "cuda:1"}),
        ])
        if i % 2 == 0:
            neg = {"mutations": copy.deepcopy(ms),
                   "receipts": [copy.deepcopy(rs[0]), copy.deepcopy(rs[2])]}
            intent = "Releasing a device lease must leave a complete receipt chain."
        else:
            bad = copy.deepcopy(ms)
            bad[0]["payload"] = {"caller": "oar_seg", "device": "cuda:1",
                                 "free_mb": 20480}
            neg = {"mutations": bad, "receipts": copy.deepcopy(rs)}
            intent = "The receipt hash must not match when the device-lease payload is altered."
        TASKS.append(_gen(
            tid, "plans:device_manager", "FRA", "receipt_complete",
            "device_lease_receipt_chain",
            intent,
            "plans/device_manager.py:368-405 acquire_session/release lease bookkeeping; oracles/recovery.py:124-177",
            {"mutations": ms, "receipts": rs}, neg,
            fixture="security", seed=7200 + n, audit=True,
            contrast="plans/device_manager/lease_receipts"))

    # --- idempotency: cached device selection --------------------------------
    for i in range(10):
        n += 1
        tid = f"PLAN-DEV-{n:03d}"
        state = {"preferred": {"ctv_seg": "cuda:1", "oar_seg": "cuda:0"},
                 "active_leases": 1, "cuda_available": True, "device_count": 2}
        s2 = copy.deepcopy(state)
        s2["active_leases"] = 2
        if i % 2 == 0:
            neg = copy.deepcopy(state)
            neg["preferred"]["ctv_seg"] = "cuda:0"
            intent = "Repeated acquire by the same caller must reuse the cached device and must not change the preference."
        else:
            neg = copy.deepcopy(state)
            neg["cuda_available"] = False
            intent = "Repeated acquire must not flip the cuda_available state."
        TASKS.append(_gen(
            tid, "plans:device_manager", "FR", "idempotency",
            "device_choice_cached_idempotent",
            intent,
            "plans/device_manager.py:328-366 preferred cache; oracles/recovery.py:180-214",
            {"states": [copy.deepcopy(state), copy.deepcopy(s2)],
             "ignore_paths": ["active_leases"]},
            {"states": [copy.deepcopy(state), neg],
             "ignore_paths": ["active_leases"]},
            fixture="security", seed=7300 + n,
            contrast="plans/device_manager/cached_choice"))

    # --- semantic_equivalence: device scoring decision -----------------------
    for i in range(10):
        n += 1
        tid = f"PLAN-DEV-{n:03d}"
        a = {"conclusion": "device_selected",
             "recommendation": "use_cuda:1",
             "numbers": {"free_mb": 20480, "util_pct": 5, "active_leases": 0}}
        neg_b = copy.deepcopy(a)
        neg_b["recommendation"] = "use_cuda:0"
        TASKS.append(_gen(
            tid, "plans:device_manager", "FE", "semantic_equivalence",
            "device_scoring_reproducible",
            "Under the same GPU-state snapshot, device scoring must select the same card with the largest free memory.",
            "plans/device_manager.py:407-435 _auto_pick (free_mem dominates); oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture="security", seed=7400 + n,
            contrast="plans/device_manager/scoring"))

    # --- state_invariant: OOM fallback purity --------------------------------
    for i in range(6):
        n += 1
        tid = f"PLAN-DEV-{n:03d}"
        before = {"preferred": {"ctv_seg": "cuda:0"}, "active_leases": 0,
                  "device_count": 2}
        after = copy.deepcopy(before)
        if i % 2 == 0:
            neg = {**copy.deepcopy(after),
                   "preferred": {"ctv_seg": "cuda:0", "oar_seg": "cpu"}}
            intent = "An OOM fallback for one caller must not contaminate another caller's preferred device."
        else:
            neg = {**copy.deepcopy(after), "device_count": 0}
            intent = "An OOM fallback must not overwrite the device count."
        TASKS.append(_gen(
            tid, "plans:device_manager", "FR", "state_invariant",
            "oom_fallback_isolated",
            intent,
            "plans/device_manager.py:437-461 handle_oom only mutates one caller; oracles/recovery.py:68-121",
            {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
            {"before": copy.deepcopy(before), "after": neg},
            fixture="security", seed=7500 + n,
            contrast="plans/device_manager/oom_isolation"))


# ===========================================================================
# plans:planning_preview -- plans/planning_preview.py (F,E,R,A)
# ===========================================================================

def gen_preview() -> None:
    n = 0
    # --- semantic_equivalence: bounded frame determinism ---------------------
    for i in range(16):
        n += 1
        tid = f"PLAN-PREVIEW-{n:03d}"
        site = list(ANATOMY)[i % 4]
        a = {"conclusion": "frame_bounded",
             "recommendation": "emit_preview",
             "numbers": {"trajectories": 64, "needles": 32, "seeds": 256,
                         "close_points": 256, "schema_version": 1}}
        if i % 2 == 0:
            neg_b = copy.deepcopy(a)
            neg_b["numbers"]["trajectories"] = 65
            intent = f"{site} preview geometry must be truncated at the MAX_PREVIEW cap and must not exceed 64 trajectories."
        else:
            neg_b = copy.deepcopy(a)
            neg_b["numbers"]["seeds"] = 512
            intent = f"{site} the preview seed count must be truncated to 256 to avoid oversized SSE frames."
        TASKS.append(_gen(
            tid, "plans:planning_preview", "FE", "semantic_equivalence",
            "preview_frame_bounded_deterministic",
            intent,
            "plans/planning_preview.py:20-23,57-131 _bounded_geometry caps; oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture=site, seed=8100 + n,
            contrast="plans/planning_preview/bounded_frames"))

    # --- state_invariant: preview is a non-persistent side channel -----------
    for i in range(16):
        n += 1
        tid = f"PLAN-PREVIEW-{n:03d}"
        before = {"plan": {"status": "running", "seeds": [], "revision": 4},
                  "workspace": {"dirty": True}}
        after = copy.deepcopy(before)
        if i % 2 == 0:
            neg = {**copy.deepcopy(after),
                   "workspace": {"dirty": False, "persisted_preview": True}}
            intent = "Preview frames are ephemeral observations and must never be persisted into the workspace."
        else:
            neg = {**copy.deepcopy(after),
                   "plan": {"status": "final", "seeds": [], "revision": 4}}
            intent = "Emitting a preview must not advance the plan status."
        TASKS.append(_gen(
            tid, "plans:planning_preview", "FR", "state_invariant",
            "preview_not_persisted",
            intent,
            "plans/planning_preview.py:1-7,159-177 (ephemeral/editable/persistent flags); oracles/recovery.py:68-121",
            {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
            {"before": copy.deepcopy(before), "after": neg},
            fixture="recovery", seed=8200 + n,
            contrast="plans/planning_preview/non_persistent",
            difficulty="hard"))

    # --- receipt_complete: emitter lifecycle audit (A) -----------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-PREVIEW-{n:03d}"
        ms, rs = _rc([
            ("op_preview_start", {"sequence": 1, "stage": "initial_plan",
                                  "ephemeral": True}),
            ("op_preview_frame", {"sequence": 2, "trajectories": 12}),
            ("op_preview_cleanup", {"sequence": 3, "reason": "finished"}),
        ])
        if i % 2 == 0:
            neg = {"mutations": copy.deepcopy(ms),
                   "receipts": [copy.deepcopy(rs[0]), copy.deepcopy(rs[1])]}
            intent = "All preview lifecycle events must have receipts, including cleanup."
        else:
            bad = copy.deepcopy(ms)
            bad[1]["payload"] = {"sequence": 2, "trajectories": 999}
            neg = {"mutations": bad, "receipts": copy.deepcopy(rs)}
            intent = "The receipt hash must not match when a preview-frame payload is altered."
        TASKS.append(_gen(
            tid, "plans:planning_preview", "FRA", "receipt_complete",
            "preview_lifecycle_receipts",
            intent,
            "plans/planning_preview.py:159-226 emitter start/frame/complete/cleanup; oracles/recovery.py:124-177",
            {"mutations": ms, "receipts": rs}, neg, fixture="recovery",
            seed=8300 + n, audit=True,
            contrast="plans/planning_preview/lifecycle_receipts"))

    # --- idempotency: repeated safe_preview is a no-op -----------------------
    for i in range(6):
        n += 1
        tid = f"PLAN-PREVIEW-{n:03d}"
        state = {"preview": {"sequence": 3, "closed": False},
                 "plan": {"status": "running"},
                 "ui": {"version_fence": {"state_seq": 9}}}
        if i % 2 == 0:
            neg = copy.deepcopy(state)
            neg["plan"]["status"] = "final"
            intent = "Repeated safe_preview on the same already-sent frame must not change plan.status."
            ignore = ["preview.sequence"]
        else:
            neg = copy.deepcopy(state)
            neg["plan"] = {"status": "final"}
            intent = "Repeated preview calls must not change plan.status."
            ignore = ["preview.sequence"]
        TASKS.append(_gen(
            tid, "plans:planning_preview", "FR", "idempotency",
            "preview_repeat_noop",
            intent,
            "plans/planning_preview.py:26-35 safe_preview side channel; oracles/recovery.py:180-214",
            {"states": [copy.deepcopy(state),
                        {**copy.deepcopy(state),
                         "preview": {"sequence": 4, "closed": False}}],
             "ignore_paths": ignore},
            {"states": [copy.deepcopy(state), neg], "ignore_paths": ignore},
            fixture="recovery", seed=8400 + n,
            contrast="plans/planning_preview/idempotent"))

    # --- error_contract: emitter validation ----------------------------------
    for i in range(6):
        n += 1
        tid = f"PLAN-PREVIEW-{n:03d}"
        pos = {"errors": [{"code": "PREVIEW_CALLBACK_FAILED",
                           "message": "observer callback raised; preview skipped",
                           "retryable": False, "op_id": f"op_prev_{i}"}]}
        if i % 2 == 0:
            neg = {"errors": [{"code": "PREVIEW_CALLBACK_FAILED",
                               "message": "observer callback raised; preview skipped",
                               "retryable": True, "op_id": f"op_prev_{i}"}]}
            intent = "A preview callback failure is an observation-layer error and must be marked non-retryable without terminating planning."
        else:
            neg = {"errors": [{"code": "PREVIEW_CALLBACK_FAILED", "message": "",
                               "retryable": False, "op_id": f"op_prev_{i}"}]}
            intent = "A preview callback failure must carry a structured message."
        TASKS.append(_gen(
            tid, "plans:planning_preview", "ER", "error_contract",
            "preview_error_envelope",
            intent,
            "plans/planning_preview.py:30-35 safe_preview swallows observer failure; oracles/recovery.py:19-65",
            pos, neg, fixture="recovery", seed=8500 + n,
            contrast="plans/planning_preview/error_envelope"))


# ===========================================================================
# plans:reward_metrics -- plans/reward_metrics.py (F,E)
# ===========================================================================

def gen_reward() -> None:
    n = 0
    # --- hard_constraint: coverage dominance over seed/needle economy --------
    for i in range(20):
        n += 1
        tid = f"PLAN-REWARD-{n:03d}"
        site = list(ANATOMY)[i % 4]
        target = 0.90
        # a plan that meets the target beats any plan below it, no matter the cost
        good = _plan(site, coverage=0.93, n_seeds=4)
        if i % 2 == 0:
            bad = _plan(site, coverage=0.89, n_seeds=4)
            intent = (f"{site} a plan with 89% coverage < 90% target must be eliminated even if it saves seeds"
                      " (coverage-first dominance).")
        else:
            bad = _plan(site, coverage=0.85, spacing_mm=8.0)
            intent = (f"{site} a below-target plan must not be mistakenly selected for OAR/seed economy.")
        TASKS.append(_gen(
            tid, "plans:reward_metrics", "FE", "hard_constraint",
            "coverage_target_dominance",
            intent,
            "plans/reward_metrics.py:19-32 TARGET_DOMINANCE / PRE_TARGET_COST_SCALE; :40-83 plan_objective",
            {"plan": good, "limits": {"min_coverage": target}},
            {"plan": bad, "limits": {"min_coverage": target}},
            fixture=site, seed=9100 + n,
            contrast="plans/reward_metrics/coverage_dominance"))

    # --- acceptable_set_hit: set-valued selection inside target band ---------
    for i in range(16):
        n += 1
        tid = f"PLAN-REWARD-{n:03d}"
        site = list(ANATOMY)[i % 4]
        good = _plan(site, coverage=0.93, n_seeds=4,
                     oar={"rectum": {"D2cc": 60.0}})
        if i % 2 == 0:
            neg = {"plan": good, "acceptable_families": [],
                   "expert_membership": {"family_id": "AE_family_9",
                                         "acceptable": False, "kappa": 0.7,
                                         "ac1": 0.67}}
            intent = f"{site} a target-meeting plan may still fall outside the acceptable set; the selector must recognize this."
        else:
            neg = {"plan": _plan(site, coverage=0.88), "acceptable_families": [],
                   "expert_membership": {"family_id": "AE_family_9",
                                         "acceptable": True, "kappa": 0.9,
                                         "ac1": 0.88}}
            intent = f"{site} the selector must not choose a below-target plan even if it hits an acceptable family."
        TASKS.append(_gen(
            tid, "plans:reward_metrics", "FE", "acceptable_set_hit",
            "objective_set_valued_selection",
            intent,
            "plans/reward_metrics.py:40-83 scalar objective; oracles/geom.py:246-317",
            {"plan": good, "acceptable_families": [],
             "expert_membership": {"family_id": "AE_family_9",
                                   "acceptable": True, "kappa": 0.9, "ac1": 0.88}},
            neg, fixture=site, seed=9200 + n,
            contrast="plans/reward_metrics/set_valued"))

    # --- pred: selected plan is final and has seeds --------------------------
    for i in range(8):
        n += 1
        tid = f"PLAN-REWARD-{n:03d}"
        site = list(ANATOMY)[i % 4]
        if i % 2 == 0:
            pos = {"plan": {"status": "final", "seeds": _seeds(site)}}
            neg = {"plan": {"status": "draft", "seeds": _seeds(site)}}
            intent = "The plan selected and submitted after reward maximization must have status final."
            pred = "plan_is_final"
        else:
            pos = {"plan": {"status": "final", "seeds": _seeds(site)}}
            neg = {"plan": {"status": "final", "seeds": []}}
            intent = "The selected plan must contain at least one seed."
            pred = "plan_has_seeds"
        TASKS.append(_pred(
            tid, "plans:reward_metrics", "FE", pred,
            "selected_plan_committed",
            intent,
            "plans/reward_metrics.py:40-83 plan_objective selection; oracles/predicates.py:59-66",
            pos, neg, fixture=site, seed=9300 + n,
            contrast="plans/reward_metrics/selected_plan"))

    # --- semantic_equivalence: deterministic objective resolution -------------
    for i in range(12):
        n += 1
        tid = f"PLAN-REWARD-{n:03d}"
        site = list(ANATOMY)[i % 4]
        a = {"conclusion": "plan_selected",
             "recommendation": "P_high_coverage",
             "numbers": {"coverage": 0.93, "seeds": 4, "needles": 2,
                         "objective": 2.9288}}
        neg_b = copy.deepcopy(a)
        neg_b["numbers"]["objective"] = 0.9288
        TASKS.append(_gen(
            tid, "plans:reward_metrics", "FE", "semantic_equivalence",
            "objective_resolution_reproducible",
            f"{site} the objective ranking and selection of the same candidate plans must be identical across runs.",
            "plans/reward_metrics.py:35-83 pure objective; oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture=site, seed=9400 + n,
            contrast="plans/reward_metrics/objective_determinism"))


# ===========================================================================
# plans:rl_status -- plans/rl_status.py (F,E,A)
# ===========================================================================

def gen_rl() -> None:
    n = 0
    # --- semantic_equivalence: JSON-safe deterministic telemetry -------------
    for i in range(20):
        n += 1
        tid = f"PLAN-RL-{n:03d}"
        site = list(ANATOMY)[i % 4]
        tc = ANATOMY[site]["rx_gy"] / 160.0
        a = {"conclusion": "completed",
             "recommendation": "target_reached",
             "numbers": {"target_coverage": round(tc, 4),
                         "best_coverage": 0.945, "episodes_completed": 12,
                         "actions_taken": 37, "dose_cache_hits": 21}}
        if i % 2 == 0:
            neg_b = copy.deepcopy(a)
            neg_b["numbers"]["best_coverage"] = 0.812
            intent = f"{site} re-rendering the status snapshot of the same RL run must give the same best_coverage."
        else:
            neg_b = copy.deepcopy(a)
            neg_b["conclusion"] = "interrupted"
            intent = f"{site} a run that reaches the target must have execution stay completed, not appear interrupted."
        TASKS.append(_gen(
            tid, "plans:rl_status", "FE", "semantic_equivalence",
            "rl_status_snapshot_deterministic",
            intent,
            "plans/rl_status.py:34-58 new_rl_status (JSON-safe defaults); oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture=site, seed=10100 + n,
            contrast="plans/rl_status/snapshot_determinism"))

    # --- error_contract: NaN / malformed telemetry ---------------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-RL-{n:03d}"
        if i % 3 == 0:
            pos = {"errors": [{"code": "INVALID_TARGET",
                               "message": "target_coverage is non-finite; defaulted",
                               "retryable": False, "op_id": f"op_status_{i}"}]}
            neg = {"errors": [{"code": "INVALID_TARGET",
                               "message": "target_coverage is non-finite; defaulted",
                               "retryable": True, "op_id": f"op_status_{i}"}]}
            intent = "A NaN RL target value must fall back and return a non-retryable alert."
        elif i % 3 == 1:
            pos = {"errors": [{"code": "STATUS_SCHEMA",
                               "message": "unknown execution value; mapped to failed",
                               "retryable": False, "op_id": f"op_status_{i}"}]}
            neg = {"errors": [{"code": "STATUS_SCHEMA", "message": "",
                               "retryable": False, "op_id": f"op_status_{i}"}]}
            intent = "A failed mapping of an unknown execution value must carry a non-empty message."
        else:
            pos = {"errors": [{"code": "OOM_RETRY",
                               "message": "policy forward OOM; retrying",
                               "retryable": True, "op_id": f"op_status_{i}"}]}
            neg = {"errors": [{"code": "OOM_RETRY",
                               "message": "policy forward OOM; retrying",
                               "retryable": False, "op_id": f"op_status_{i}"}]}
            intent = "An RL policy-forward OOM must be marked retryable."
        TASKS.append(_gen(
            tid, "plans:rl_status", "E", "error_contract",
            "rl_status_validation_envelope",
            intent,
            "plans/rl_status.py:61-99 update_best/set_outcome NaN rejection; oracles/recovery.py:19-65",
            pos, neg, fixture="recovery", seed=10200 + n,
            contrast="plans/rl_status/validation"))

    # --- idempotency: update_best is monotone & idempotent -------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-RL-{n:03d}"
        site = list(ANATOMY)[i % 4]
        state = {"best_coverage": 0.945, "best_reward": 2.945,
                 "episodes_completed": 12,
                 "plan": {"receipts": []},
                 "ui": {"version_fence": {"state_seq": 4}}}
        if i % 2 == 0:
            neg = copy.deepcopy(state)
            neg["best_coverage"] = 0.812
            intent = "The best must not regress on repeated update_best with the same coverage (idempotent)."
        else:
            neg = copy.deepcopy(state)
            neg["best_reward"] = float("nan") if False else None
            neg["best_reward"] = None
            intent = "Writing the same best_reward repeatedly must not clear it (idempotent)."
        TASKS.append(_gen(
            tid, "plans:rl_status", "FE", "idempotency",
            "update_best_idempotent",
            intent,
            "plans/rl_status.py:61-83 update_best max/monotone; oracles/recovery.py:180-214",
            {"states": [copy.deepcopy(state), copy.deepcopy(state)]},
            {"states": [copy.deepcopy(state), neg]},
            fixture=site, seed=10300 + n,
            contrast="plans/rl_status/update_best_idempotent"))

    # --- receipt_complete: RL status transition audit (A) --------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-RL-{n:03d}"
        ms, rs = _rc([
            ("op_rl_start", {"target_coverage": 0.9, "schema_version": 1}),
            ("op_rl_update", {"episode": 5, "best_coverage": 0.91}),
            ("op_rl_finish", {"execution": "completed", "stop_reason": "target_reached"}),
        ])
        if i % 2 == 0:
            neg = {"mutations": copy.deepcopy(ms),
                   "receipts": [copy.deepcopy(rs[0]), copy.deepcopy(rs[2])]}
            intent = "Every RL state transition must have a receipt; a missing update receipt makes the chain incomplete."
        else:
            bad = copy.deepcopy(ms)
            bad[2]["payload"] = {"execution": "failed", "stop_reason": "internal_exception"}
            neg = {"mutations": bad, "receipts": copy.deepcopy(rs)}
            intent = "The receipt hash must not match when the RL finish-transition payload is altered."
        TASKS.append(_gen(
            tid, "plans:rl_status", "FA", "receipt_complete",
            "rl_status_transition_receipts",
            intent,
            "plans/rl_status.py:86-138 set_outcome/finish_rl_status; oracles/recovery.py:124-177",
            {"mutations": ms, "receipts": rs}, neg, fixture="recovery",
            seed=10400 + n, audit=True,
            contrast="plans/rl_status/transition_receipts"))


# ===========================================================================
# plans:guide_geometry -- plans/guide_geometry.py (F,E,S)
# ===========================================================================

def _gholes(count: int, diameter: float = 2.6) -> List[Dict[str, Any]]:
    holes = []
    for i in range(count):
        x = -30.0 + (i % 6) * 12.0
        y = -30.0 + (i // 6) * 12.0
        holes.append({"entry_mm": [x, y, 0.0], "axis": [0.0, 0.0, 1.0],
                      "diameter_mm": diameter})
    return holes


def gen_guide() -> None:
    n = 0
    # --- guide_geometry_tol: hole position/axis/diameter/wall ----------------
    hole_counts = {"prostate": 16, "pancreas": 14, "liver": 20, "lung": 12}
    for i in range(24):
        n += 1
        tid = f"PLAN-GUIDE-{n:03d}"
        site = list(ANATOMY)[i % 4]
        cnt = hole_counts[site]
        designed = {"holes": _gholes(cnt), "thickness_mm": 5.0}
        built = copy.deepcopy(designed)
        v = i % 5
        if v == 0:
            built["holes"][0]["entry_mm"][0] += 0.5
            intent = f"{site} guide hole position deviates 0.5mm, exceeding the 0.3mm manufacturing tolerance."
        elif v == 1:
            import math as _m
            a = _m.radians(5.0)
            built["holes"][1]["axis"] = [_m.sin(a), 0.0, _m.cos(a)]
            intent = f"{site} guide hole axis is deflected 5°, exceeding the 2° tolerance."
        elif v == 2:
            built["holes"][2]["diameter_mm"] = 2.9
            intent = f"{site} guide bore diameter of 2.9mm deviates from the 2.6mm design by more than 0.1mm."
        elif v == 3:
            built["thickness_mm"] = 5.5
            intent = f"{site} guide wall thickness deviates 0.5mm, exceeding the 0.2mm tolerance."
        else:
            built["holes"] = built["holes"][:-1]
            intent = f"{site} the actual guide hole count does not match the design hole count."
        TASKS.append(_gen(
            tid, "plans:guide_geometry", "FES", "guide_geometry_tol",
            "guide_hole_manufacturing_tolerance",
            intent,
            "plans/guide_geometry.py:17-22 default bore 2.6mm; oracles/geom.py:320-391",
            {"built": copy.deepcopy(designed), "designed": copy.deepcopy(designed)},
            {"built": built, "designed": designed},
            fixture=site, seed=11100 + n,
            contrast="plans/guide_geometry/hole_tolerance",
            difficulty="hard",
            oracle_extra=None))

    # --- error_contract: invalid guide geometry inputs -----------------------
    for i in range(16):
        n += 1
        tid = f"PLAN-GUIDE-{n:03d}"
        if i % 4 == 0:
            pos = {"errors": [{"code": "INVALID_CHANNEL_RADIUS",
                               "message": "channel_radius_mm must be a positive finite number",
                               "retryable": False, "op_id": f"op_guide_{i}"}]}
            neg = {"errors": [{"code": "INVALID_CHANNEL_RADIUS",
                               "message": "channel_radius_mm must be a positive finite number",
                               "retryable": True, "op_id": f"op_guide_{i}"}]}
            intent = "A non-positive guide channel radius must report a non-retryable error."
        elif i % 4 == 1:
            pos = {"errors": [{"code": "INVALID_BORE_MARGIN",
                               "message": "bore_margin_mm must be a finite non-negative number",
                               "retryable": False, "op_id": f"op_guide_{i}"}]}
            neg = {"errors": [{"code": "INVALID_BORE_MARGIN", "message": "",
                               "retryable": False, "op_id": f"op_guide_{i}"}]}
            intent = "The error message must not be empty when the bore margin is illegal."
        elif i % 4 == 2:
            pos = {"errors": [{"code": "INVALID_MIN_DISTANCE",
                               "message": "parallel_min_distance_mm must be a positive finite number",
                               "retryable": False, "op_id": f"op_guide_{i}"}]}
            neg = {"errors": [{"code": "INVALID_MIN_DISTANCE",
                               "message": "parallel_min_distance_mm must be a positive finite number",
                               "retryable": True, "op_id": f"op_guide_{i}"}]}
            intent = "An illegal near-parallel minimum distance must be non-retryable."
        else:
            pos = {"errors": [{"code": "INVALID_ANGLE_TOLERANCE",
                               "message": "parallel_angle_tolerance_deg must be in the range [0, 90)",
                               "retryable": False, "op_id": f"op_guide_{i}"}]}
            neg = {"errors": [{"code": "INVALID_ANGLE_TOLERANCE", "message": "",
                               "retryable": False, "op_id": f"op_guide_{i}"}]}
            intent = "An out-of-range parallel-judgement angle tolerance must return a non-empty structured message."
        TASKS.append(_gen(
            tid, "plans:guide_geometry", "E", "error_contract",
            "guide_geometry_input_validation",
            intent,
            "plans/guide_geometry.py:25-74 ValueError validation; oracles/recovery.py:19-65",
            pos, neg, fixture="recovery", seed=11200 + n,
            contrast="plans/guide_geometry/input_validation"))

    # --- hard_constraint: parallel needle min distance >= bore diameter ------
    for i in range(10):
        n += 1
        tid = f"PLAN-GUIDE-{n:03d}"
        site = list(ANATOMY)[i % 4]
        good = _plan(site, spacing_mm=6.0)
        if i % 2 == 0:
            bad = _plan(site, spacing_mm=1.5)
            intent = f"{site} a near-parallel needle center distance of 1.5mm is smaller than the 2.6mm guide bore diameter and must be rejected."
        else:
            bad = _plan(site, spacing_mm=5.0)  # fine geometrically, but clearance bad
            bad["trajectories"][0]["clearance_mm"] = 0.5
            intent = f"{site} the tract clearance is below the guide minimum distance and must be rejected."
        TASKS.append(_gen(
            tid, "plans:guide_geometry", "FS", "hard_constraint",
            "guide_parallel_min_distance",
            intent,
            "plans/guide_geometry.py:44-59 resolve_parallel_needle_min_distance_mm; oracles/geom.py:168-243",
            {"plan": good, "limits": {"min_spacing_mm": 2.6,
                                      "min_endpoint_clearance_mm": 2.0}},
            {"plan": bad, "limits": {"min_spacing_mm": 2.6,
                                     "min_endpoint_clearance_mm": 2.0}},
            fixture=site, seed=11300 + n,
            contrast="plans/guide_geometry/parallel_min_distance"))

    # --- semantic_equivalence: deterministic bore diameter -------------------
    for i in range(6):
        n += 1
        tid = f"PLAN-GUIDE-{n:03d}"
        a = {"conclusion": "bore_resolved",
             "recommendation": "use_2.6mm",
             "numbers": {"channel_radius_mm": 0.9, "bore_margin_mm": 0.4,
                         "diameter_mm": 2.6}}
        neg_b = copy.deepcopy(a)
        neg_b["numbers"]["diameter_mm"] = 2.0
        TASKS.append(_gen(
            tid, "plans:guide_geometry", "FE", "semantic_equivalence",
            "guide_bore_deterministic",
            "The default guide bore diameter = 2*(channel radius + bore margin) = 2.6mm and must be reproducible.",
            "plans/guide_geometry.py:17-41 guide_primary_bore_diameter_mm; oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture="prostate", seed=11400 + n,
            contrast="plans/guide_geometry/bore_determinism"))


# ===========================================================================
# plans:performance -- plans/performance.py (F,A)
# ===========================================================================

def gen_perf() -> None:
    n = 0
    # --- state_invariant: profiling retains no patient arrays/model state ----
    for i in range(18):
        n += 1
        tid = f"PLAN-PERF-{n:03d}"
        before = {"plan": {"status": "running", "revision": 7},
                  "patient": {"ct_array": None, "model_state": None},
                  "profile_ctx": {"active": False}}
        after = copy.deepcopy(before)
        if i % 2 == 0:
            neg = {**copy.deepcopy(after),
                   "patient": {"ct_array": "retained", "model_state": None}}
            intent = "The patient CT array must not be retained after the timing context exits."
        else:
            neg = {**copy.deepcopy(after), "profile_ctx": {"active": True}}
            intent = "The ContextVar must be reset after collecting latency and must not linger."
        TASKS.append(_gen(
            tid, "plans:performance", "F", "state_invariant",
            "latency_profiling_retains_nothing",
            intent,
            "plans/performance.py:1-8,51-91 collect_planning_latency contextvar reset; oracles/recovery.py:68-121",
            {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
            {"before": copy.deepcopy(before), "after": neg},
            fixture="recovery", seed=12100 + n,
            contrast="plans/performance/no_retention"))

    # --- receipt_complete: latency profile audit artifact (A) ----------------
    for i in range(16):
        n += 1
        tid = f"PLAN-PERF-{n:03d}"
        ms, rs = _rc([
            ("op_profile_start", {"request_id": f"req_{i}", "wall_clock_s": 60}),
            ("op_profile_nested", {"name": "candidate_generation", "calls": 1}),
            ("op_profile_end", {"total_seconds": 1.234, "threads_end": 8}),
        ])
        if i % 2 == 0:
            neg = {"mutations": copy.deepcopy(ms),
                   "receipts": [copy.deepcopy(rs[0]), copy.deepcopy(rs[1])]}
            intent = "The start/nested/end of a latency profile must all have receipts."
        else:
            bad = copy.deepcopy(ms)
            bad[2]["payload"] = {"total_seconds": 9.999, "threads_end": 8}
            neg = {"mutations": bad, "receipts": copy.deepcopy(rs)}
            intent = "The receipt hash must not match when the latency-profile end payload is altered."
        TASKS.append(_gen(
            tid, "plans:performance", "FA", "receipt_complete",
            "latency_profile_receipts",
            intent,
            "plans/performance.py:27-48 record_timing; :66-80 metadata['latency_profile']; oracles/recovery.py:124-177",
            {"mutations": ms, "receipts": rs}, neg, fixture="recovery",
            seed=12200 + n, audit=True,
            contrast="plans/performance/profile_receipts"))

    # --- idempotency: repeated profiling of same op --------------------------
    for i in range(12):
        n += 1
        tid = f"PLAN-PERF-{n:03d}"
        state = {"profile": {"total_seconds": 1.234,
                             "nested_timings": {"candidate_generation":
                                                {"calls": 1, "seconds": 0.5}},
                             "contention": {"threads_start": 4, "threads_end": 4}},
                 "plan": {"receipts": []},
                 "ui": {"version_fence": {"state_seq": 1}}}
        if i % 2 == 0:
            neg = copy.deepcopy(state)
            neg["profile"]["total_seconds"] = 2.468
            intent = "Repeated latency collection for the same request must give the same total duration (without summing nested rows)."
        else:
            neg = copy.deepcopy(state)
            neg["profile"]["nested_timings"]["candidate_generation"]["calls"] = 2
            intent = "Nested timing rows must not be accumulated repeatedly through repeated collection."
        TASKS.append(_gen(
            tid, "plans:performance", "F", "idempotency",
            "latency_profile_idempotent",
            intent,
            "plans/performance.py:1-4 (nested rows must not be summed); oracles/recovery.py:180-214",
            {"states": [copy.deepcopy(state), copy.deepcopy(state)]},
            {"states": [copy.deepcopy(state), neg]},
            fixture="recovery", seed=12300 + n,
            contrast="plans/performance/profile_idempotent"))

    # --- semantic_equivalence: profile shape / keys stable -------------------
    for i in range(10):
        n += 1
        tid = f"PLAN-PERF-{n:03d}"
        a = {"conclusion": "profile_collected",
             "recommendation": "attach_to_metadata",
             "numbers": {"total_seconds": 1.234, "n_nested": 4,
                         "avg_parallelism": 0.82}}
        neg_b = copy.deepcopy(a)
        neg_b["numbers"]["n_nested"] = 2
        TASKS.append(_gen(
            tid, "plans:performance", "FE", "semantic_equivalence",
            "latency_profile_schema_stable",
            "The latency profile of the same decision sequence must contain the same number of nested timing entries.",
            "plans/performance.py:51-91 collect_planning_latency; oracles/artifacts.py:342-382",
            {"run_a": a, "run_b": copy.deepcopy(a)},
            {"run_a": a, "run_b": neg_b}, fixture="recovery", seed=12400 + n,
            contrast="plans/performance/profile_shape"))


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------

for _genfn in (
    gen_core, gen_util, gen_geo, gen_reinf, gen_repair, gen_brachy,
    gen_device, gen_preview, gen_reward, gen_rl, gen_guide, gen_perf,
):
    _genfn()

__all__ = ["TASKS"]
