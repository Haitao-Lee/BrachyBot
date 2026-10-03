"""Track-A **deepened** expansion wave: the ``plans/*`` brachytherapy planning
capabilities (second pass, ``PLAN2-*`` ids).

Complements ``WAVE_PLANS_tasks.py`` (``PLAN-*``) with additional *real* source
behaviours and real-case parameterisation, grounded in ``file:line``.  Every
entry is deterministic data for a **program** oracle (no LLM judge): the
positive observation replays the correct engineering outcome; the negative is a
real defect (drifted seed, wrong unit, endpoint false positive, rejected repair
mutating the accepted plan, tampered receipt chain, OOM mislabelled, stale
cached device, truncated preview, NaN telemetry, ...).  Discriminating data
lives in ``obs_*`` only -- never in the fixture.

Self-verify without touching any shared file::

    python tools/build_expansion.py --spec tools/specs/W2_PLANS_tasks.py --prove --dry-run

Owned capabilities (registry ``capabilities/registry.yaml`` -> ``path``):

* ``plans:core``            plans/core.py            (F,E,R)
* ``plans:utilizations``    plans/utilizations.py    (F,E,I)
* ``plans:geometry``        plans/geometry.py        (F,E,S)
* ``plans:reinforcement``   plans/reinforcement.py   (F,E,R)
* ``plans:coverage_repair`` plans/coverage_repair.py (F,E,R)
* ``plans:brachy_plan``     plans/brachy_plan_v2.py  (F,E,R)
* ``plans:device_manager``  plans/device_manager.py  (F,E,R,A)
* ``plans:planning_preview`` plans/planning_preview.py (F,E,R,A)
* ``plans:reward_metrics``  plans/reward_metrics.py  (F,E)
* ``plans:rl_status``       plans/rl_status.py       (F,E,A)
* ``plans:guide_geometry``  plans/guide_geometry.py  (F,E,S)
* ``plans:performance``     plans/performance.py     (F,A)
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Optional

TASKS: List[Dict[str, Any]] = []

# ---------------------------------------------------------------------------
# fixtures (reuse shipped case families; hash back-filled by the builder)
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
        "case_family": "synth/pancreas_p03_seeds_3",
        "setup_script": "fixtures/setup/pancreas_p03_seeds_3.py",
        "initial_state_hash": "sha256:pending",
    },
    "lung": {
        "case_family": "synth/pancreas_p03_seeds_3",
        "setup_script": "fixtures/setup/pancreas_p03_seeds_3.py",
        "initial_state_hash": "sha256:pending",
    },
    "breast": {
        "case_family": "synth/pancreas_p03_pipeline",
        "setup_script": "fixtures/setup/pancreas_p03_pipeline.py",
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

SITES = ["prostate", "pancreas", "liver", "lung", "breast"]

#: real clinical / physics parameter table (site -> prostate LDR, pancreas LDR,
#: liver Yb-169, lung I-125, breast APBI).
SITE: Dict[str, Dict[str, Any]] = {
    "prostate": {"origin": [-120.5, -120.5, -140.0], "spacing": [1.0, 1.0, 1.0],
                 "rx_gy": 145.0, "needles": 16, "nuclide": "I-125",
                 "activity_u": 0.4, "coverage": 0.98},
    "pancreas": {"origin": [-98.2, -140.0, -120.5], "spacing": [0.977, 0.977, 1.25],
                 "rx_gy": 35.0, "needles": 14, "nuclide": "I-125",
                 "activity_u": 0.5, "coverage": 0.95},
    "liver": {"origin": [45.2, -210.0, -88.0], "spacing": [0.703, 0.703, 1.0],
              "rx_gy": 120.0, "needles": 20, "nuclide": "Yb-169",
              "activity_u": 0.6, "coverage": 0.90},
    "lung": {"origin": [-180.0, -180.0, -220.0], "spacing": [0.683, 0.683, 1.0],
             "rx_gy": 110.0, "needles": 12, "nuclide": "I-125",
             "activity_u": 0.45, "coverage": 0.90},
    "breast": {"origin": [12.0, -96.0, -64.0], "spacing": [0.859, 0.859, 1.0],
               "rx_gy": 50.0, "needles": 18, "nuclide": "I-125",
               "activity_u": 0.4, "coverage": 0.90},
}

DIR_I = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
DIR_ROT_Z = [0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
DIR_MIRROR_X = [-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
DIR_SCALED2 = [2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0]

#: array-order (z,y,x) seed chains (real ~7 mm I-125 strand spacing).
SEEDS: Dict[str, List[List[float]]] = {
    "prostate": [[12.0, 24.0, 30.0], [12.0, 24.0, 37.0], [26.0, 24.0, 30.0],
                 [26.0, 24.0, 37.0], [12.0, 40.0, 30.0], [26.0, 40.0, 37.0]],
    "pancreas": [[40.0, 50.0, 60.0], [40.0, 57.0, 60.0], [55.0, 50.0, 60.0],
                 [55.0, 57.0, 60.0], [40.0, 64.0, 60.0], [55.0, 64.0, 60.0]],
    "liver": [[70.0, 80.0, 90.0], [70.0, 87.0, 90.0], [90.0, 80.0, 90.0],
              [90.0, 87.0, 90.0], [70.0, 94.0, 90.0], [90.0, 94.0, 90.0]],
    "lung": [[30.0, 60.0, 110.0], [30.0, 67.0, 110.0], [45.0, 60.0, 110.0],
             [45.0, 67.0, 110.0], [30.0, 74.0, 110.0], [45.0, 74.0, 110.0]],
    "breast": [[35.0, 45.0, 80.0], [35.0, 52.0, 80.0], [50.0, 45.0, 80.0],
               [50.0, 52.0, 80.0], [35.0, 59.0, 80.0], [50.0, 59.0, 80.0]],
}

#: constraint class per oracle id (mirrors oracles/*.py registrations).
CC = {
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
    "pred": "postcondition",
}

#: codes the error_contract oracle treats as retryable (oracles/recovery.py:29).
RETRYABLE = {"TIMEOUT", "UNAVAILABLE", "BUSY", "NETWORK", "OOM_RETRY"}

# ---------------------------------------------------------------------------
# entry builders
# ---------------------------------------------------------------------------


def _cov(cap: str, dims: str, check: str, tid: str) -> Dict[str, Any]:
    refs = [f"task:{tid}"] if check == "pred" else [f"oracle:{check}", f"task:{tid}"]
    return {cap: {d: list(refs) for d in dims}}


def _mk(tid: str, cap: str, dims: str, check: str, construct: str, intent: str,
        derived: str, pos: Dict[str, Any], neg: Dict[str, Any], *,
        fixture: str = "prostate", contrast: Optional[str] = None, seed: int = 0,
        difficulty: str = "medium", power: str = "primary", group: str = "G-CT",
        mode: str = "single_turn", turns: Optional[List[Dict[str, str]]] = None,
        audit: bool = False, n_runs: int = 5, wall: int = 60, tool_calls: int = 6,
        intent_class: str = "imperative", oracle_extra: Optional[Dict[str, Any]] = None,
        predicate: Optional[str] = None, pgroup: Optional[str] = None) -> Dict[str, Any]:
    oracle: Dict[str, Any] = {
        "kind": "program", "check": check,
        "constraint_class": CC.get(check, "none"),
        "expect": None, "tolerance": None, "assist_only": False,
        "independent_check": True, "evidence_keys": [], "gold": None,
    }
    if predicate:
        oracle["predicate"] = predicate
    if oracle_extra:
        oracle.update(oracle_extra)
    if turns is None:
        turns = [{"role": "user", "text": intent, "lang": "en"}]
    cf = contrast or f"{cap}/{construct}"
    task = {
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
            "paraphrase_group": pgroup or f"{tid}-P01", "hidden": False,
            "generation_seed": seed, "canary_class": None,
            "behavioral_probes": [], "contrast_family_id": cf,
        },
        "provenance": {
            "source": "audit_derived", "derived_from": derived,
            "guideline_ref": None, "reviewers": ["auto"],
            "authored_on": "2026-10-01", "deprecated": None,
        },
    }
    if check == "pred":
        obs_pos = {"sut_id": "BrachyBot-replay", "intent_class": intent_class,
                   "partial_status": "COMPLETED", "terminal_state": pos}
        obs_neg = {"terminal_state": neg}
    else:
        obs_pos = {"sut_id": "BrachyBot-replay", "intent_class": intent_class,
                   "partial_status": "COMPLETED",
                   "oracle_inputs": {check: pos},
                   "_comment": f"CI replay for {tid}: correct engineering outcome."}
        obs_neg = {"oracle_inputs": {check: neg}}
    return {"task": task, "obs_pos": obs_pos, "obs_neg": obs_neg,
            "coverage": _cov(cap, dims, check, tid)}


class _Gen:
    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.n = 0

    def tid(self) -> str:
        self.n += 1
        return f"PLAN2-{self.topic}-{self.n:03d}"

    def add(self, cap: str, dims: str, check: str, construct: str, intent: str,
            derived: str, pos: Dict[str, Any], neg: Dict[str, Any],
            **kw: Any) -> Dict[str, Any]:
        entry = _mk(self.tid(), cap, dims, check, construct, intent, derived,
                    pos, neg, **kw)
        TASKS.append(entry)
        return entry

    def para(self, cap: str, dims: str, check: str, construct: str,
             intents: List[str], derived: str, pos: Dict[str, Any],
             neg: Dict[str, Any], **kw: Any) -> None:
        group = f"PLAN2-{self.topic}-{self.n + 1:03d}-P01"
        for text in intents:
            entry = _mk(self.tid(), cap, dims, check, construct, text, derived,
                        pos, neg, group="G-EQ", pgroup=group, **kw)
            TASKS.append(entry)

    def ctx(self, cap: str, dims: str, check: str, construct: str,
            intents: List[str], derived: str, pos: Dict[str, Any],
            neg: Dict[str, Any], **kw: Any) -> None:
        turns = [{"role": "user", "text": intents[0], "lang": "en"}]
        for text in intents[1:]:
            turns.append({"role": "assistant", "text": "Noted, continuing.", "lang": "en"})
            turns.append({"role": "user", "text": text, "lang": "en"})
        entry = _mk(self.tid(), cap, dims, check, construct, intents[-1],
                    derived, pos, neg, group="G-CTX", mode="multi_turn",
                    turns=turns, **kw)
        TASKS.append(entry)


# ---------------------------------------------------------------------------
# shared payload helpers
# ---------------------------------------------------------------------------


def _seeds(site: str, n: int = 6, prefix: str = "s") -> List[Dict[str, Any]]:
    act = SITE[site]["activity_u"]
    return [{"id": f"{prefix}{i + 1}", "traj": f"t{i // 2 + 1}",
             "pos_mm": list(p), "activity_u": act}
            for i, p in enumerate(SEEDS[site][:n])]


def _trajs(n: int = 3, spacing_mm: float = 8.0, clearance: float = 3.0,
           base: Optional[List[float]] = None) -> List[Dict[str, Any]]:
    start = base or [10.0, 20.0, 10.0]
    return [{"id": f"t{i + 1}",
             "entry": [start[0] + i * spacing_mm, start[1], start[2]],
             "clearance_mm": clearance} for i in range(n)]


def _plan(site: str, *, coverage: Optional[float] = None, clearance: float = 3.0,
          spacing_mm: float = 8.0, n_seeds: int = 6, n_needles: int = 3,
          oar: Optional[Dict[str, Any]] = None,
          limits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cov = SITE[site]["coverage"] if coverage is None else coverage
    plan: Dict[str, Any] = {
        "seeds": _seeds(site, n_seeds),
        "trajectories": _trajs(n_needles, spacing_mm, clearance),
        "coverage": {"ctv": cov},
    }
    if oar is not None:
        plan["oar_metrics"] = oar
    if limits is not None:
        plan["limits"] = limits
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


def _run(conclusion: str, recommendation: str,
         numbers: Dict[str, Any], refusal: Optional[str] = None) -> Dict[str, Any]:
    return {"conclusion": conclusion, "recommendation": recommendation,
            "refusal": refusal, "numbers": numbers}


def _state(plan_status: str = "ready", seeds: Optional[list] = None,
           rx_gy: float = 145.0, computed: bool = False) -> Dict[str, Any]:
    return {"plan": {"status": plan_status, "seeds": seeds or []},
            "dose": {"computed": computed, "rx_gy": rx_gy},
            "ui": {"version_fence": {"state_seq": 1}}}


def _err(code: str, retryable: bool, op_id: str, message: str = "planning op failed"):
    return {"code": code, "message": message, "retryable": retryable, "op_id": op_id}


# ===========================================================================
# plans:core -- plans/core.py (F,E,R)
# ===========================================================================


def gen_core() -> None:
    g = _Gen("CORE")
    samples = [[12.0, 24.0, 30.0], [12.0, 24.0, 38.0], [26.0, 24.0, 34.0]]
    # 1) voxel->world conversion on every return path (core.py:32-116)
    for site in SITES:
        o, sp = SITE[site]["origin"], SITE[site]["spacing"]
        g.add("plans:core", "FER", "coord_roundtrip",
              "seed_plan_world_conversion_anisotropic",
              f"{site} plan must convert voxel coordinates to patient world coordinates using an orthonormal direction matrix; anisotropic spacing must not distort.",
              "plans/core.py:32-116 seed_plan_to_world_coordinates; oracles/coord_roundtrip.py:53-113",
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_I},
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_SCALED2},
              fixture=site, seed=2100 + g.n, contrast="plans/core/world_conversion")
    # 2) header consistency between planning grid and world frame
    for i, site in enumerate(SITES):
        o, sp = SITE[site]["origin"], SITE[site]["spacing"]
        hdr = {"origin": o, "spacing": sp, "direction": DIR_I}
        if i % 2 == 0:
            bad = {"origin": [o[0] + 0.5, o[1], o[2]], "spacing": sp, "direction": DIR_I}
            intent = f"{site} world header origin differs from the planning grid origin by 0.5mm; must be judged inconsistent and rejected."
        else:
            bad = {"origin": o, "spacing": [s * 1.001 for s in sp], "direction": DIR_I}
            intent = f"{site} world header spacing relative error 1e-3 exceeds the limit; must be judged inconsistent."
        g.add("plans:core", "FER", "coord_roundtrip",
              "seed_plan_header_consistency",
              intent,
              "plans/core.py:47-116 (world contract); oracles/coord_roundtrip.py:115-144",
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_I,
               "header_a": hdr, "header_b": hdr},
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_I,
               "header_a": hdr, "header_b": bad},
              fixture=site, seed=2110 + g.n, contrast="plans/core/header_consistency")
    # 3) engine seeds must equal cws seeds (core.py:766-789)
    variants = [
        ("drift", "engine seed positions drift 0.5mm from the plan (voxel/world not converted)."),
        ("drop", "engine receives one seed too few; the id set must match exactly."),
        ("activity", "seed activity was rewritten; the geometry-fidelity check must detect the parameter mismatch."),
        ("rank", "engine seed coordinates are reduced to 2D; the coordinate-rank mismatch must be rejected."),
        ("traj", "a seed's owning trajectory id was rewritten; traj parameters must match exactly."),
    ]
    for site in ("prostate", "pancreas"):
        base = _seeds(site)
        for v, intent in variants:
            eng = copy.deepcopy(base)
            if v == "drift":
                eng[0]["pos_mm"][0] += 0.5
            elif v == "drop":
                eng = eng[:-1]
            elif v == "activity":
                eng[1]["activity_u"] = round(SITE[site]["activity_u"] + 0.05, 4)
            elif v == "rank":
                eng[0]["pos_mm"] = eng[0]["pos_mm"][:2]
            else:
                eng[2]["traj"] = "t9"
            g.add("plans:core", "FE", "seed_geometry_fidelity",
                  "engine_seed_geometry_matches_cws",
                  f"{site} {intent}",
                  "plans/core.py:766-789 seed_plan_to_world_coordinates final; oracles/geom.py:25-86",
                  {"engine_seeds": copy.deepcopy(base), "cws_seeds": copy.deepcopy(base)},
                  {"engine_seeds": eng, "cws_seeds": copy.deepcopy(base)},
                  fixture=site, seed=2120 + g.n,
                  contrast="plans/core/seed_geometry_fidelity",
                  difficulty="hard" if v == "rank" else "medium")
    # 4) early return / failure leaves state intact (core.py:487-587)
    for i, site in enumerate(SITES):
        before = _state("ready", _seeds(site, 3), SITE[site]["rx_gy"], False)
        after = copy.deepcopy(before)
        g.add("plans:core", "FER", "state_invariant",
              "early_return_leaves_plan_intact",
              f"{site} optimization early return (no candidates/timeout) must not partially write seeds.",
              "plans/core.py:523-587 optimal_plan early return; oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": after},
              {"before": copy.deepcopy(before),
               "after": {**after, "plan": {**after["plan"], "status": "final"}}},
              fixture=site, seed=2130 + g.n,
              contrast="plans/core/failure_state_intact")
    # 5) typed error envelope for malformed seed records (core.py:52-95)
    g.add("plans:core", "ER", "error_contract", "seed_conversion_error_envelope",
          "seed records missing position/direction must return a structured error, not be silently skipped.",
          "plans/core.py:52-95 ValueError on missing/short seed; oracles/recovery.py:19-65",
          {"errors": [_err("INVALID_SEED_RECORD", False, "op_seed_1")]},
          {"errors": [_err("INVALID_SEED_RECORD", True, "op_seed_1")]},
          fixture="recovery", seed=2140 + g.n, contrast="plans/core/error_envelope")
    g.add("plans:core", "ER", "error_contract", "dose_image_missing_envelope",
          "when dose_image is missing and world coordinates cannot be converted, a non-retryable MISSING_DOSE_IMAGE must be returned.",
          "plans/core.py:49-50 dose_image required; oracles/recovery.py:19-65",
          {"errors": [_err("MISSING_DOSE_IMAGE", False, "op_world_conv")]},
          {"errors": [{"code": "MISSING_DOSE_IMAGE", "message": "", "retryable": False,
                       "op_id": "op_world_conv"}]},
          fixture="recovery", seed=2141 + g.n, contrast="plans/core/error_envelope")
    # 6) deterministic FPS / anchor sampler (core.py:119-202)
    for i, site in enumerate(SITES):
        a = _run("candidate_subset", "use_surface_covering",
                 {"n_candidates": 64, "rx_gy": SITE[site]["rx_gy"],
                  "n_directions": 24})
        g.para("plans:core", "FER", "semantic_equivalence",
               "sampler_determinism",
               [f"{site} two samplings of the same input must yield a bitwise-identical candidate trajectory set.",
                f"{site} repeated candidate sampling must not change the direction distribution due to input order.",
                f"repeat candidate sampling for {site}: identical retained set."],
               "plans/core.py:119-144 sample_spatial_trajectories; oracles/artifacts.py:349-382",
               {"run_a": a, "run_b": copy.deepcopy(a)},
               {"run_a": a, "run_b": _run("candidate_subset", "use_surface_covering",
                                          {"n_candidates": 64, "rx_gy": SITE[site]["rx_gy"],
                                           "n_directions": 23})},
               fixture=site, seed=2150 + g.n, contrast="plans/core/sampler_determinism")
        break
    # 7) hard constraint: candidate geometry limits (oracles/geom.py:181-243)
    negs = [
        ({"clearance": 1.2, "coverage": None}, "endpoint clearance 1.2mm is below the 2.0mm hard floor."),
        ({"clearance": None, "coverage": 0.85}, "CTV coverage 0.85 is below the 0.90 hard floor."),
        ({"clearance": None, "coverage": None, "spacing_mm": 3.0}, "needle spacing 3.0mm is below the 5.0mm hard floor."),
    ]
    for i, (variant, why) in enumerate(negs):
        site = SITES[i % len(SITES)]
        good = _plan(site)
        if variant.get("spacing_mm") == 3.0:
            bad = _plan(site, spacing_mm=3.0)
        else:
            bad = _plan(site, clearance=variant["clearance"] or 3.0,
                        coverage=variant["coverage"])
        g.add("plans:core", "FE", "hard_constraint", "candidate_plan_meets_hard_limits",
              f"{site} a candidate plan violating a hard constraint ({why}) must be rejected.",
              "plans/core.py:206-468 init_plan; oracles/geom.py:181-243",
              {"plan": good}, {"plan": bad}, fixture=site, seed=2160 + g.n,
              contrast="plans/core/hard_limits")
    # 8) OAR hard limits (rectum/urethra/bladder D2cc/D0.1cc)
    site = "prostate"
    limits = {"oar_limits": {"rectum": {"metric": "D2cc", "limit": 75.0},
                             "urethra": {"metric": "D0.1cc", "limit": 200.0}}}
    good = _plan(site, oar={"rectum": {"D2cc": 68.4}, "urethra": {"D0.1cc": 183.0}},
                 limits=limits)
    bad = _plan(site, oar={"rectum": {"D2cc": 80.1}, "urethra": {"D0.1cc": 183.0}},
                limits=limits)
    g.add("plans:core", "FE", "hard_constraint", "prostate_oar_d2cc_limit",
          "prostate plan rectum D2cc 80.1Gy exceeds the 75Gy hard limit and must be judged non-compliant.",
          "plans/core.py:469-789 optimal_plan; fixture prostate_s02 oar D2cc; oracles/geom.py:229-235",
          {"plan": good, "limits": limits}, {"plan": bad, "limits": limits},
          fixture="prostate", seed=2170 + g.n, contrast="plans/core/oar_limits")
    g.add("plans:core", "FE", "hard_constraint", "seed_count_budget",
          "a plan exceeding the 200-seed cap must be judged non-compliant.",
          "plans/core.py:469-789; oracles/geom.py:188,200-202 (max_seeds)",
          {"plan": _plan(site)}, {"plan": {**_plan(site), "seeds": _seeds(site) * 40}},
          fixture="prostate", seed=2171 + g.n, contrast="plans/core/seed_budget")
    # 9) acceptable set: O1 then O4 family membership (oracles/geom.py:246-317)
    for i, site in enumerate(SITES):
        good = _plan(site)
        if i % 2 == 0:
            neg = {"plan": good, "acceptable_families": [],
                   "expert_membership": {"family_id": "AE_family_2",
                                         "acceptable": False, "kappa": 0.71,
                                         "ac1": 0.68}}
            intent = f"{site} plan satisfies O1 hard constraints but experts judge it outside the acceptable set."
        else:
            neg = {"plan": _plan(site, coverage=0.82), "acceptable_families": [],
                   "expert_membership": {"family_id": "AE_family_1",
                                         "acceptable": True, "kappa": 0.9,
                                         "ac1": 0.87}}
            intent = f"{site} coverage 0.82 fails O1; an expert family hit must not mark it compliant either."
        g.add("plans:core", "FE", "acceptable_set_hit", "plan_hits_acceptable_family",
              intent,
              "plans/core.py:469-791 optimal_plan; oracles/geom.py:246-317",
              {"plan": good, "acceptable_families": [],
               "expert_membership": {"family_id": "AE_family_1", "acceptable": True,
                                     "kappa": 0.9, "ac1": 0.87}},
              neg, fixture=site, seed=2180 + g.n,
              contrast="plans/core/acceptable_set")
    # 10) multi-turn G-CTX: iterative replan
    g.ctx("plans:core", "FER", "semantic_equivalence", "iterative_replan_equivalence",
          ["Add one more trajectory to the prostate plan.", "Then lower the prescription from 145Gy to 120Gy and re-optimize."],
          "plans/core.py:469-789 optimal_plan multi-stage; oracles/artifacts.py:349-382",
          {"run_a": _run("replan", "accept", {"rx_gy": 120.0, "n_needles": 17}),
           "run_b": _run("replan", "accept", {"rx_gy": 120.0, "n_needles": 17})},
          {"run_a": _run("replan", "accept", {"rx_gy": 120.0, "n_needles": 17}),
           "run_b": _run("replan", "accept", {"rx_gy": 145.0, "n_needles": 17})},
          fixture="prostate", seed=2190 + g.n)
    # 11) anchor-covering sampler fallback when anchors exceed the budget
    for site in SITES[:2]:
        a = _run("anchor_sampler", "fallback_spatial",
                 {"n_anchors": 80, "limit": 64, "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:core", "FER", "semantic_equivalence", "anchor_sampler_budget_fallback",
              f"{site} when the anchor count exceeds the budget, sampling must fall back to spatially uniform sampling and remain reproducible.",
              "plans/core.py:147-202 sample_anchor_covering_trajectories",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("anchor_sampler", "fallback_spatial",
                                         {"n_anchors": 80, "limit": 48,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2191 + g.n, contrast="plans/core/anchor_sampler")
    # 12) entry body mask shape mismatch is a typed error
    g.add("plans:core", "ER", "error_contract", "entry_body_mask_shape_error",
          "entry_body_mask shape mismatch with radiation_volume must return a non-retryable structured error.",
          "plans/core.py:272-277 ValueError entry_body_mask shape; oracles/recovery.py:19-65",
          {"errors": [_err("ENTRY_MASK_SHAPE_MISMATCH", False, "op_init_plan")]},
          {"errors": [_err("ENTRY_MASK_SHAPE_MISMATCH", True, "op_init_plan")]},
          fixture="recovery", seed=2192 + g.n, contrast="plans/core/error_envelope")
    # 13) stage-2/3 fallback retains the better plan
    for i, site in enumerate(SITES[:3]):
        before = _state("final", _seeds(site, 4), SITE[site]["rx_gy"], True)
        g.add("plans:core", "FER", "state_invariant", "stage_fallback_keeps_best",
              f"{site} stage 2/3 fallback must not overwrite a better plan with a worse seed set.",
              "plans/core.py:649-672,762-765 optimal_plan fallback; oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
              {"before": copy.deepcopy(before),
               "after": {**before, "plan": {**before["plan"], "seeds": _seeds(site, 3)}}},
              fixture=site, seed=2193 + g.n, contrast="plans/core/stage_fallback")
    # 14) exact seed-dose cache telemetry
    for i, site in enumerate(SITES[:2]):
        a = _run("seed_dose_cache", "report",
                 {"hits": 41, "misses": 7, "entries": 48, "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:core", "FE", "semantic_equivalence", "seed_dose_cache_telemetry",
              f"{site} exact seed-dose cache hit/miss counts must be reproducible.",
              "plans/core.py:782-788 dose_context cache stats; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("seed_dose_cache", "report",
                                         {"hits": 41, "misses": 8, "entries": 48,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2194 + g.n, contrast="plans/core/cache_telemetry")
    # 15) G-EQ paraphrase pack: engine seed geometry
    g.para("plans:core", "FE", "seed_geometry_fidelity", "engine_seed_geometry_paraphrase",
           ["The seeds received by the engine must exactly match those in the plan.",
            "Seed coordinates handed to the dose engine must not drift at all.",
            "seeds handed to the dose engine must exactly match the plan."],
           "plans/core.py:766-789; oracles/geom.py:25-86",
           {"engine_seeds": _seeds("prostate"), "cws_seeds": _seeds("prostate")},
           {"engine_seeds": [{**_seeds("prostate")[0], "pos_mm": [12.5, 24.0, 30.0]}]
            + _seeds("prostate")[1:], "cws_seeds": _seeds("prostate")},
           fixture="prostate", seed=2195 + g.n)


# ===========================================================================
# plans:utilizations -- plans/utilizations.py (F,E,I)
# ===========================================================================


def gen_util() -> None:
    g = _Gen("UTIL")
    samples = [[10.0, 20.0, 30.0], [10.0, 20.0, 38.0], [24.0, 20.0, 30.0]]
    # 1) position/direction transform roundtrip (utilizations.py:217-272)
    for i, site in enumerate(SITES):
        o, sp = SITE[site]["origin"], SITE[site]["spacing"]
        e = g.add("plans:utilizations", "FI", "coord_roundtrip",
                  "voxel_world_transform_roundtrip",
                  f"{site} position/direction_transform must remain consistent on round-trip in a right-handed frame.",
                  "plans/utilizations.py:217-272 position_transform/direction_transform; "
                  "plans/geometry.py:14-48",
                  {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_I},
                  {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_MIRROR_X},
                  fixture=site, seed=2200 + g.n,
                  contrast="plans/utilizations/world_roundtrip")
        e["task"]["power_role"] = "primary"
        g.add("plans:utilizations", "FI", "coord_roundtrip",
              "voxel_world_transform_roundtrip",
              f"{site} when the direction matrix is scaled 2x, direction_transform must reject it.",
              "plans/utilizations.py:243-272 direction_transform; oracles/coord_roundtrip.py:67-90",
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_I},
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_SCALED2},
              fixture=site, seed=2201 + g.n,
              contrast="plans/utilizations/world_roundtrip")
    # 2) get_planning_volume_array: CTV priority over OAR (utilizations.py:565-613)
    for site in SITES:
        a = _run("label_volume", "use_ctv_priority",
                 {"target_voxels": 18000, "obstacle_voxels": 4200,
                  "background_voxels": 900000, "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:utilizations", "FI", "semantic_equivalence",
              "planning_volume_ctv_priority",
              f"{site} OAR must not overwrite CTV in the planning volume; target voxel count must remain stable.",
              "plans/utilizations.py:565-613 get_planning_volume_array (CTV takes priority)",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("label_volume", "use_ctv_priority",
                                         {"target_voxels": 13800, "obstacle_voxels": 8400,
                                          "background_voxels": 900000,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2210 + g.n,
              contrast="plans/utilizations/volume_priority")
    # 3) normalize_dose_array linear mapping (utilizations.py:186-214)
    for i, site in enumerate(SITES):
        rx = SITE[site]["rx_gy"]
        g.add("plans:utilizations", "FI", "semantic_equivalence",
              "dose_normalization_linearity",
              f"{site} normalize_dose_array must map linearly as (v-min)*(scale/(max-min)) and be consistent across runs.",
              "plans/utilizations.py:186-214 normalize_dose_array",
              {"run_a": _run("normalized", "scale_255", {"scale": 255.0, "vmax": rx, "vmin": 0.0,
                                                         "sample_at_rx": 255.0}),
               "run_b": _run("normalized", "scale_255", {"scale": 255.0, "vmax": rx, "vmin": 0.0,
                                                         "sample_at_rx": 255.0})},
              {"run_a": _run("normalized", "scale_255", {"scale": 255.0, "vmax": rx, "vmin": 0.0,
                                                         "sample_at_rx": 255.0}),
               "run_b": _run("normalized", "scale_255", {"scale": 255.0, "vmax": rx, "vmin": 0.0,
                                                         "sample_at_rx": 300.0})},
              fixture=site, seed=2220 + g.n,
              contrast="plans/utilizations/normalization")
    # 4) ras_direction_to_voxel preserves unit length / axis order
    for i, site in enumerate(SITES):
        sp = SITE[site]["spacing"]
        g.add("plans:utilizations", "FI", "coord_roundtrip",
              "ras_direction_to_voxel_axes",
              f"{site} ras_direction_to_voxel must divide by spacing and reverse axis order to [k,j,i].",
              "plans/utilizations.py:531-549 ras_direction_to_voxel",
              {"samples": samples, "origin": SITE[site]["origin"], "spacing": sp,
               "direction": DIR_I},
              {"samples": samples, "origin": SITE[site]["origin"],
               "spacing": [sp[0], sp[1], sp[2]],
               "direction": DIR_MIRROR_X},
              fixture=site, seed=2230 + g.n,
              contrast="plans/utilizations/ras_direction")
    # 5) constraint_bounds / from_seeds_to_x bind seed fields (param_binding)
    base = [{"target": "seed", "metric": "D90", "value": 145.0, "unit": "Gy",
             "bound_target": "seed", "bound_metric": "D90", "value_gy": 145.0},
            {"target": "rectum", "metric": "D2cc", "value": 7500.0, "unit": "cGy",
             "bound_target": "rectum", "bound_metric": "D2cc", "value_gy": 75.0},
            {"target": "urethra", "metric": "V100", "value": 92.0, "unit": "%",
             "bound_target": "urethra", "bound_metric": "V100", "value_gy": 92.0}]
    g.add("plans:utilizations", "FI", "param_binding", "dose_metric_unit_binding",
          "prescription/OAR doses must bind to their own target and metric; cGy must convert to Gy, and V metrics use percentages.",
          "plans/utilizations.py:1427-1537 constraint_bounds/from_seeds_to_x; "
          "oracles/geom.py:501-568",
          {"bindings": copy.deepcopy(base)},
          {"bindings": [dict(base[0]),
                        {**base[1], "bound_target": "bladder"},
                        dict(base[2])]},
          fixture="prostate", seed=2240 + g.n, contrast="plans/utilizations/metric_binding")
    g.add("plans:utilizations", "FI", "param_binding", "v_metric_scope_confusion",
          "V100 is a volume percentage; incorrectly converting it as Gy must be judged a metric-scope confusion.",
          "plans/utilizations.py:1427-1537; oracles/geom.py:520-557 (METRIC_SCOPE)",
          {"bindings": [{"target": "ctv", "metric": "V100", "value": 91.2, "unit": "%",
                         "bound_target": "ctv", "bound_metric": "V100", "value_gy": 91.2}]},
          {"bindings": [{"target": "ctv", "metric": "V100", "value": 91.2, "unit": "Gy",
                         "bound_target": "ctv", "bound_metric": "V100", "value_gy": 0.912}]},
          fixture="prostate", seed=2241 + g.n, contrast="plans/utilizations/metric_binding")
    # 6) error contract for invalid inputs
    for i, code in enumerate(["INVALID_IMAGE", "NO_TARGET_AREA", "RESAMPLE_FAILED",
                              "TIMEOUT"]):
        retr = code in RETRYABLE
        g.add("plans:utilizations", "EI", "error_contract", "util_error_envelope",
              f"{code} must be returned in a stable error envelope with retryable matching actual retryability.",
              "plans/utilizations.py:289-324 (No target area), 616-668 (resample); "
              "oracles/recovery.py:19-65",
              {"errors": [_err(code, retr, f"op_util_{i}")]},
              {"errors": [_err(code, not retr, f"op_util_{i}")]},
              fixture="recovery", seed=2250 + g.n, contrast="plans/utilizations/error_envelope")
    # 7) G-EQ paraphrase pack: transform intent
    g.para("plans:utilizations", "FI", "coord_roundtrip", "transform_axes_paraphrase",
           ["Convert the voxel point to world coordinates (LPS).",
            "Convert the planning-grid voxel coordinates to patient physical coordinates.",
            "convert the voxel position to world/LPS coordinates."],
           "plans/utilizations.py:217-272",
           {"samples": samples, "origin": SITE["prostate"]["origin"],
            "spacing": SITE["prostate"]["spacing"], "direction": DIR_I},
           {"samples": samples, "origin": SITE["prostate"]["origin"],
            "spacing": SITE["prostate"]["spacing"], "direction": DIR_MIRROR_X},
           fixture="prostate", seed=2260 + g.n)
    # 8) lowest / highest dose seed index (utilizations.py:1303-1384)
    for kind in ("lowest", "highest"):
        a = _run(f"seed_index:{kind}", "select", {"index": 2, "n_seeds": 40,
                                                  "rx_gy": 145.0})
        g.add("plans:utilizations", "FI", "semantic_equivalence", "seed_index_selection",
              f"{kind} dose-seed index selection must be reproducible and stable.",
              "plans/utilizations.py:1303-1384 get_lowest/highest_pos_index",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run(f"seed_index:{kind}", "select",
                                         {"index": 3, "n_seeds": 40, "rx_gy": 145.0})},
              fixture="prostate", seed=2261 + g.n, contrast="plans/utilizations/seed_index")
    # 9) remove_elements_by_indices set semantics (utilizations.py:1387-1402)
    a = _run("remove_indices", "set_removal", {"n_in": 40, "n_removed": 3, "n_out": 37})
    g.add("plans:utilizations", "FI", "semantic_equivalence", "remove_indices_semantics",
          "Removal by index must use set semantics for deduplication, leaving a stable remaining element count.",
          "plans/utilizations.py:1387-1402 remove_elements_by_indices",
          {"run_a": a, "run_b": copy.deepcopy(a)},
          {"run_a": a, "run_b": _run("remove_indices", "set_removal",
                                     {"n_in": 40, "n_removed": 3, "n_out": 38})},
          fixture="prostate", seed=2262 + g.n, contrast="plans/utilizations/remove_indices")
    # 10) resample preserves direction / origin (utilizations.py:616-668)
    for site in SITES[:2]:
        o, sp = SITE[site]["origin"], SITE[site]["spacing"]
        hdr = {"origin": o, "spacing": sp, "direction": DIR_I}
        g.add("plans:utilizations", "FI", "coord_roundtrip", "resample_geometry_preserved",
              f"{site} ImageResample_size must preserve direction/origin with consistent geometry round-trip.",
              "plans/utilizations.py:616-668 ImageResample_size; oracles/coord_roundtrip.py:115-144",
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_I,
               "header_a": hdr, "header_b": hdr},
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_I,
               "header_a": hdr,
               "header_b": {"origin": [o[0] + 0.25, o[1], o[2]], "spacing": sp,
                            "direction": DIR_I}},
              fixture=site, seed=2263 + g.n, contrast="plans/utilizations/resample")
    # 11) cone direction sampling (utilizations.py:840-910)
    for i, site in enumerate(SITES[:2]):
        a = _run("cone_sampling", "directions",
                 {"half_angle_deg": 30.0, "n_rings": 5, "n_dirs": 61,
                  "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:utilizations", "FI", "semantic_equivalence", "cone_direction_sampling",
              f"{site} cone-direction sampling count and order must be reproducible.",
              "plans/utilizations.py:840-910 get_cone; plans/core.py:279-282",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("cone_sampling", "directions",
                                         {"half_angle_deg": 30.0, "n_rings": 5,
                                          "n_dirs": 60, "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2264 + g.n, contrast="plans/utilizations/cone_sampling")
    # 12) dose metric binding for seed optimisation vector
    g.add("plans:utilizations", "FI", "param_binding", "optimizer_dose_binding",
          "When D90 in the optimization vector is given in cGy, it must convert to Gy and bind to the seed metric.",
          "plans/utilizations.py:1475-1537 from_seeds_to_x/update_seeds; oracles/geom.py:501-568",
          {"bindings": [{"target": "seed", "metric": "D90", "value": 14500.0,
                         "unit": "cGy", "bound_target": "seed",
                         "bound_metric": "D90", "value_gy": 145.0}]},
          {"bindings": [{"target": "seed", "metric": "D90", "value": 14500.0,
                         "unit": "cGy", "bound_target": "seed",
                         "bound_metric": "D100", "value_gy": 145.0}]},
          fixture="prostate", seed=2265 + g.n, contrast="plans/utilizations/metric_binding")
    # 13) G-EQ paraphrase pack: normalization intent
    g.para("plans:utilizations", "FI", "semantic_equivalence", "normalization_paraphrase",
           ["Normalize the dose to the 0-255 range.",
            "Linearly stretch CT/dose to 255 using the window [0,145].",
            "linearly window the dose to the 0-255 range."],
           "plans/utilizations.py:186-214 normalize_dose_array",
           {"run_a": _run("normalize", "scale_255", {"scale": 255.0, "vmax": 145.0}),
            "run_b": _run("normalize", "scale_255", {"scale": 255.0, "vmax": 145.0})},
           {"run_a": _run("normalize", "scale_255", {"scale": 255.0, "vmax": 145.0}),
            "run_b": _run("normalize", "scale_255", {"scale": 255.0, "vmax": 140.0})},
           fixture="prostate", seed=2266 + g.n)


# ===========================================================================
# plans:geometry -- plans/geometry.py (F,E,S)
# ===========================================================================


def gen_geo() -> None:
    g = _Gen("GEO")
    samples = [[10.0, 20.0, 30.0], [10.0, 20.0, 38.0], [24.0, 20.0, 30.0]]
    # 1) voxel_to_world direction transform (geometry.py:14-48)
    for i, site in enumerate(SITES):
        o, sp = SITE[site]["origin"], SITE[site]["spacing"]
        g.add("plans:geometry", "FS", "coord_roundtrip", "voxel_to_world_axis_order",
              f"{site} voxel_to_world must convert correctly using spacing/origin/direction under right-handed constraints.",
              "plans/geometry.py:14-48 voxel_to_world; oracles/coord_roundtrip.py:31-45",
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_I},
              {"samples": samples, "origin": o, "spacing": sp, "direction": DIR_MIRROR_X},
              fixture=site, seed=2300 + g.n, contrast="plans/geometry/voxel_to_world")
    # 2) interference endpoint false positives (geometry.py:1235-1414; oracles/geom.py:394-470)
    cross = {"id": "cross_1", "s": [[0.0, 0.0, -1.0], [0.0, 0.0, 1.0]],
             "t": [[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0]], "predicted_risk": "overlap"}
    endpoint = {"id": "end_1", "s": [[0.0, 0.0, 0.0], [0.0, 0.0, 10.0]],
                "t": [[0.0, 0.0, 10.0], [5.0, 0.0, 10.0]], "predicted_risk": "none"}
    g.add("plans:geometry", "FS", "interference_fp", "endpoint_contact_not_overlap",
          "seed segments touching only at endpoints (actual clearance 4.5-5.0mm) must not be judged a physical overlap.",
          "plans/geometry.py:1235-1414 line_to_line_distance; oracles/geom.py:394-470",
          {"predictions": [copy.deepcopy(cross), copy.deepcopy(endpoint)]},
          {"predictions": [copy.deepcopy(cross),
                           {**endpoint, "predicted_risk": "overlap"}]},
          fixture="prostate", seed=2310 + g.n, contrast="plans/geometry/interference_fp")
    # 6 endpoint cases across sites
    for i, site in enumerate(SITES):
        s0 = [0.0, 0.0, 0.0]
        s1 = [0.0, 0.0, 10.0 + (i % 2) * 5.0]
        t0 = list(s1)
        t1 = [5.0 + i, 0.0, s1[2]]
        warnings = {**endpoint, "id": f"end_{site}",
                    "s": [s0, s1], "t": [t0, t1], "predicted_risk": "none"}
        g.add("plans:geometry", "FS", "interference_fp", "endpoint_contact_site_case",
              f"{site} trajectory endpoint-contact cases must not report a physical overlap (audit found 4.5-5.0mm endpoint false positives).",
              "plans/geometry.py:1278-1414 ray_min_distance/min_distance_to_lines; "
              "oracles/geom.py:421-449",
              {"predictions": [copy.deepcopy(warnings)]},
              {"predictions": [{**warnings, "predicted_risk": "warning"}]},
              fixture=site, seed=2320 + g.n, contrast="plans/geometry/interference_fp")
    # 3) hard constraint: parallel needle spacing (oracles/geom.py:204-214)
    for i, site in enumerate(SITES):
        good = _plan(site, spacing_mm=8.0)
        bad = _plan(site, spacing_mm=3.0)
        g.add("plans:geometry", "FS", "hard_constraint", "parallel_needle_min_spacing",
              f"{site} near-parallel trajectory center distance 3.0mm is below the guide-bore 2.6mm safety floor.",
              "plans/geometry.py:1235-1323 line_to_line_distance; plans/guide_geometry.py:19-21; "
              "oracles/geom.py:204-214",
              {"plan": good}, {"plan": bad}, fixture=site, seed=2330 + g.n,
              contrast="plans/geometry/needle_spacing")
    # 4) guide geometry holes (oracles/geom.py:320-379)
    designed = {"holes": [
        {"entry_mm": [12.0, 24.0, 24.0], "axis": [0.0, 0.0, 1.0], "diameter_mm": 2.6},
        {"entry_mm": [26.0, 24.0, 24.0], "axis": [0.0, 0.0, 1.0], "diameter_mm": 2.6}],
        "thickness_mm": 5.0}
    g.add("plans:geometry", "FS", "guide_geometry_tol", "guide_hole_manufacturing_tol",
          "guide template hole position/axis/diameter/wall thickness must be within manufacturing tolerances (0.3mm/2°/0.1mm/0.2mm).",
          "plans/geometry.py:1002-1049 get_cylinder_polydata; plans/guide_geometry.py; "
          "oracles/geom.py:320-379",
          {"built": copy.deepcopy(designed), "designed": copy.deepcopy(designed)},
          {"built": {**copy.deepcopy(designed),
                     "holes": [{**designed["holes"][0],
                                "entry_mm": [12.6, 24.0, 24.0]},
                               designed["holes"][1]]},
           "designed": copy.deepcopy(designed)},
          fixture="prostate", seed=2340 + g.n, contrast="plans/geometry/guide_tol")
    g.add("plans:geometry", "FS", "guide_geometry_tol", "guide_wall_thickness_tol",
          "guide template wall-thickness deviation 0.5mm exceeds the 0.2mm manufacturing tolerance.",
          "plans/guide_geometry.py:17-21; oracles/geom.py:366-371",
          {"built": copy.deepcopy(designed), "designed": copy.deepcopy(designed)},
          {"built": {**copy.deepcopy(designed), "thickness_mm": 5.5},
           "designed": copy.deepcopy(designed)},
          fixture="prostate", seed=2341 + g.n, contrast="plans/geometry/guide_tol")
    # 5) semantic equivalence for distance helpers (geometry.py:1235-1414)
    for i, site in enumerate(SITES[:3]):
        d = {"distance_mm": 8.0, "u": 0.5, "v": 0.5, "rx_gy": SITE[site]["rx_gy"]}
        g.add("plans:geometry", "FS", "semantic_equivalence", "distance_helper_determinism",
              f"{site} determinism of segment closest-distance computation (identical input yields identical closest-point parameters).",
              "plans/geometry.py:1235-1414 line_to_line_distance/ray_to_ray_distance; "
              "oracles/artifacts.py:349-382",
              {"run_a": _run("distance", "no_overlap", dict(d)),
               "run_b": _run("distance", "no_overlap", dict(d))},
              {"run_a": _run("distance", "no_overlap", dict(d)),
               "run_b": _run("distance", "no_overlap", {**d, "distance_mm": 4.9})},
              fixture=site, seed=2350 + g.n, contrast="plans/geometry/distance_determinism")
    # 6) error contract for degenerate geometry
    for i, code in enumerate(["DEGENERATE_SEGMENT", "EMPTY_MASK", "NON_FINITE_POINT",
                              "SHAPE_MISMATCH", "BUSY"]):
        retr = code in RETRYABLE
        g.add("plans:geometry", "ES", "error_contract", "geometry_error_envelope",
              f"{code} degenerate geometry must return a structured error with retryable labelled correctly.",
              "plans/geometry.py:540-706 are_collinear/is_ray_blocked; oracles/recovery.py:19-65",
              {"errors": [_err(code, retr, f"op_geo_{i}")]},
              {"errors": [_err(code, not retr, f"op_geo_{i}")]},
              fixture="recovery", seed=2360 + g.n, contrast="plans/geometry/error_envelope")
    # 7) geometric primitive determinism (geometry.py:410-761)
    for name, fn in [("are_collinear", "geometry.py:540-547"),
                     ("angle_between_vectors", "geometry.py:410-447"),
                     ("projection_length", "geometry.py:1174-1211"),
                     ("top_k", "geometry.py:1488-1519")]:
        for i in range(2):
            val = 12.0 + i
            a = _run(name, "compute", {"result": val, "n": 40})
            g.add("plans:geometry", "FS", "semantic_equivalence", f"{name}_determinism",
                  f"{name}  geometric result must be reproducible.",
                  f"plans/geometry.py {fn}; oracles/artifacts.py:349-382",
                  {"run_a": a, "run_b": copy.deepcopy(a)},
                  {"run_a": a, "run_b": _run(name, "compute",
                                             {"result": val + 0.5, "n": 40})},
                  fixture="prostate", seed=2370 + g.n,
                  contrast=f"plans/geometry/{name}")
    # 8) ray blocking against obstacle label (geometry.py:548-705)
    for i, site in enumerate(SITES):
        a = _run("ray_blocked", "occlusion",
                 {"obstacle_value": 2, "blocked": 1, "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:geometry", "FS", "semantic_equivalence", "ray_blocked_determinism",
              f"{site} ray occlusion by OAR/obstacle determination must be reproducible.",
              "plans/geometry.py:548-705 is_ray_blocked; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("ray_blocked", "occlusion",
                                         {"obstacle_value": 2, "blocked": 0,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2380 + g.n, contrast="plans/geometry/ray_blocked")
    # 9) perpendicular cylinder guide axis (geometry.py:1002-1069)
    designed = {"holes": [
        {"entry_mm": [12.0, 24.0, 24.0], "axis": [0.0, 0.0, 1.0], "diameter_mm": 2.6},
        {"entry_mm": [26.0, 24.0, 24.0], "axis": [0.0, 0.0, 1.0], "diameter_mm": 2.6}],
        "thickness_mm": 5.0}
    g.add("plans:geometry", "FS", "guide_geometry_tol", "cylinder_hole_count",
          "a guide template hole-count mismatch must be judged a manufacturing deviation.",
          "plans/geometry.py:1002-1049 get_cylinder_polydata; oracles/geom.py:343-345",
          {"built": copy.deepcopy(designed), "designed": copy.deepcopy(designed)},
          {"built": {**copy.deepcopy(designed), "holes": designed["holes"][:1]},
           "designed": copy.deepcopy(designed)},
          fixture="prostate", seed=2390 + g.n, contrast="plans/geometry/cylinder_holes")
    # 10) G-EQ paraphrase pack: interference endpoint
    g.para("plans:geometry", "FS", "interference_fp", "interference_paraphrase",
           ["Two seeds touching only at endpoints do not count as overlapping.",
            "Endpoint contact is not a physical overlap; do not report a false positive.",
            "endpoint-only contact is not a physical overlap."],
           "plans/geometry.py:1278-1414; oracles/geom.py:394-470",
           {"predictions": [{"id": "e", "s": [[0.0, 0.0, 0.0], [0.0, 0.0, 10.0]],
                             "t": [[0.0, 0.0, 10.0], [5.0, 0.0, 10.0]],
                             "predicted_risk": "none"}]},
           {"predictions": [{"id": "e", "s": [[0.0, 0.0, 0.0], [0.0, 0.0, 10.0]],
                             "t": [[0.0, 0.0, 10.0], [5.0, 0.0, 10.0]],
                             "predicted_risk": "overlap"}]},
           fixture="prostate", seed=2391 + g.n)
    # 11) more geometry error codes
    for i, code in enumerate(["CONVEX_HULL_EMPTY", "GRADIENT_UNDEFINED", "NETWORK"]):
        retr = code in RETRYABLE
        g.add("plans:geometry", "ES", "error_contract", "geometry_error_envelope",
              f"{code} must return a structured error with retryable consistent.",
              "plans/geometry.py:706-854 hull/gradient; oracles/recovery.py:19-65",
              {"errors": [_err(code, retr, f"op_geo2_{i}")]},
              {"errors": [_err(code, not retr, f"op_geo2_{i}")]},
              fixture="recovery", seed=2392 + g.n, contrast="plans/geometry/error_envelope")


# ===========================================================================
# plans:reinforcement -- plans/reinforcement.py (F,E,R)
# ===========================================================================


def gen_reinf() -> None:
    g = _Gen("REINF")
    # 1) rejected/expired RL steps leave the plan intact (reinforcement.py:1227-1364)
    for i, site in enumerate(SITES):
        before = _state("ready", _seeds(site, 4), SITE[site]["rx_gy"], False)
        g.add("plans:reinforcement", "FR", "state_invariant", "rl_expired_keeps_plan",
              f"{site} RL construction returning an empty plan at deadline expiry must not leave partial seeds.",
              "plans/reinforcement.py:1227-1232,1364 construct_plan_over_candidates; "
              "oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
              {"before": copy.deepcopy(before),
               "after": {**before, "plan": {**before["plan"], "status": "final"}}},
              fixture=site, seed=2400 + g.n, contrast="plans/reinforcement/expired_state")
    # 2) objective reproducibility (reinforcement.py:1102-1151)
    for i, site in enumerate(SITES):
        a = _run("rl_objective", "select_best", {"objective": 2.812, "coverage": 0.93,
                                                 "seeds": 40, "needles": 8,
                                                 "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:reinforcement", "FR", "semantic_equivalence", "rl_objective_reproducible",
              f"{site} the final objective value and coverage of the same RL plan must be reproducible.",
              "plans/reinforcement.py:1102-1151 evaluate_plan_objective; "
              "oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("rl_objective", "select_best",
                                         {"objective": 2.512, "coverage": 0.93, "seeds": 40,
                                          "needles": 8, "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2410 + g.n, contrast="plans/reinforcement/objective_determinism")
    # 3) dose-map geometry mismatch must error (reinforcement.py:1124-1127)
    for i in range(3):
        g.add("plans:reinforcement", "ER", "error_contract", "rl_dose_geometry_error",
              "When the dose-map geometry in an RL plan is inconsistent with the planning grid, a structured error must be reported.",
              "plans/reinforcement.py:1124-1127 ValueError geometry differs; "
              "oracles/recovery.py:19-65",
              {"errors": [_err("RL_DOSE_GEOMETRY_MISMATCH", False, f"op_rl_{i}")]},
              {"errors": [_err("RL_DOSE_GEOMETRY_MISMATCH", True, f"op_rl_{i}")]},
              fixture="recovery", seed=2420 + g.n, contrast="plans/reinforcement/geometry_error")
    # 4) plan_cost_counts fallback to dose maps (reinforcement.py:1154-1172)
    for i, site in enumerate(SITES):
        a = _run("plan_cost", "count", {"seeds": 40, "needles": 8,
                                        "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:reinforcement", "FR", "semantic_equivalence", "plan_cost_counts_fallback",
              f"{site} trajectories with an empty seed list must fall back to counting by dose map; cost statistics must match the live set.",
              "plans/reinforcement.py:1154-1172 plan_cost_counts; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("plan_cost", "count",
                                         {"seeds": 38, "needles": 7,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2430 + g.n, contrast="plans/reinforcement/cost_counts")
    # 5) hard constraint after consolidation never lowers rank (reinforcement.py:1367-1432)
    for i, site in enumerate(SITES):
        g.add("plans:reinforcement", "FE", "hard_constraint", "consolidated_plan_limits",
              f"{site} after trajectory consolidation the plan must still satisfy coverage and needle-spacing hard constraints.",
              "plans/reinforcement.py:1367-1432 consolidate_plan_needles; oracles/geom.py:181-243",
              {"plan": _plan(site, coverage=0.98, n_needles=6)},
              {"plan": _plan(site, coverage=0.84, n_needles=6)},
              fixture=site, seed=2440 + g.n, contrast="plans/reinforcement/consolidation")
    # 6) receipts for RL mutations
    ms, rs = _rc([("op_rl_construct", {"needles": 8, "seeds": 40}),
                  ("op_rl_consolidate", {"removed": 1, "readded": 3})])
    g.add("plans:reinforcement", "FR", "receipt_complete", "rl_mutation_receipts",
          "Every change from RL construction and consolidation must have a receipt verifiable via a hash chain.",
          "plans/reinforcement.py:1192-1364; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": rs[:-1] + [{**rs[-1], "hash": "deadbeef" * 8}]},
          fixture="prostate", seed=2450 + g.n, contrast="plans/reinforcement/receipts")
    bad_ms, bad_rs = _rc([("op_rl_construct", {"needles": 8})])
    g.add("plans:reinforcement", "FR", "receipt_complete", "rl_mutation_receipt_chain",
          "A broken prev_hash in the receipt chain must be judged an incomplete audit.",
          "plans/reinforcement.py:1192-1364; oracles/recovery.py:156-159",
          {"mutations": copy.deepcopy(bad_ms), "receipts": copy.deepcopy(bad_rs)},
          {"mutations": copy.deepcopy(bad_ms),
           "receipts": [{**bad_rs[0], "prev_hash": "f" * 64}]},
          fixture="prostate", seed=2451 + g.n, contrast="plans/reinforcement/receipts")
    # 7) idempotent re-run
    s = _state("final", _seeds("prostate"), 145.0, True)
    g.add("plans:reinforcement", "FR", "idempotency", "rl_rerun_idempotent",
          "Re-running the same RL planning request must not change the accepted plan (only receipts/version fence may change).",
          "plans/reinforcement.py:1538-1612 reinforcement_planning; oracles/recovery.py:181-214",
          {"states": [copy.deepcopy(s), copy.deepcopy(s)]},
          {"states": [copy.deepcopy(s),
                      {**copy.deepcopy(s),
                       "plan": {**s["plan"], "status": "ready"}}]},
          fixture="prostate", seed=2460 + g.n, contrast="plans/reinforcement/idempotency")
    # 8) G-CTX multi-turn RL tuning
    g.ctx("plans:reinforcement", "FR", "semantic_equivalence", "rl_turn_determinism",
          ["Run RL planning with a target coverage of 0.95.", "Raise the target coverage to 0.97 and run again."],
          "plans/reinforcement.py:1538-1612; oracles/artifacts.py:349-382",
          {"run_a": _run("rl_plan", "accept", {"target_coverage": 0.97, "needles": 9}),
           "run_b": _run("rl_plan", "accept", {"target_coverage": 0.97, "needles": 9})},
          {"run_a": _run("rl_plan", "accept", {"target_coverage": 0.97, "needles": 9}),
           "run_b": _run("rl_plan", "accept", {"target_coverage": 0.95, "needles": 9})},
          fixture="prostate", seed=2470 + g.n)
    # 9) empty candidate pool returns no plan without mutating state
    for i, site in enumerate(SITES[:2]):
        before = _state("ready", [], SITE[site]["rx_gy"], False)
        g.add("plans:reinforcement", "FR", "state_invariant", "empty_candidates_no_plan",
              f"{site} when the candidate set is empty, RL construction returns an empty plan and writes no state.",
              "plans/reinforcement.py:1224-1228 construct_plan_over_candidates; "
              "oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
              {"before": copy.deepcopy(before),
               "after": {**before, "plan": {**before["plan"], "status": "final"}}},
              fixture=site, seed=2471 + g.n, contrast="plans/reinforcement/empty_candidates")
    # 10) empty target grid yields -inf objective
    for i, site in enumerate(SITES[:2]):
        a = _run("rl_objective", "empty_target", {"objective": -1.0e9, "coverage": 0.0,
                                                  "target_voxels": 0,
                                                  "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:reinforcement", "FR", "semantic_equivalence", "empty_target_objective",
              f"{site} when the target is empty the objective must be the -inf sentinel with coverage 0.",
              "plans/reinforcement.py:1130-1133 evaluate_plan_objective; "
              "oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("rl_objective", "empty_target",
                                         {"objective": -1.0e9, "coverage": 0.0,
                                          "target_voxels": 1,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2472 + g.n, contrast="plans/reinforcement/empty_target")
    # 11) OAR protection in marginal reward (reinforcement.py:331-450)
    for i, site in enumerate(SITES[:3]):
        a = _run("marginal_reward", "protect_oar",
                 {"reward": 0.041, "oar_delta": 0.0, "protect_OAR": 1,
                  "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:reinforcement", "FR", "semantic_equivalence", "marginal_reward_oar",
              f"{site} marginal reward while protecting OARs must be reproducible.",
              "plans/reinforcement.py:331-450 SeedPlacementReward.forward; "
              "oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("marginal_reward", "protect_oar",
                                         {"reward": 0.041, "oar_delta": 0.02,
                                          "protect_OAR": 1,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2473 + g.n, contrast="plans/reinforcement/marginal_reward")
    # 12) parallel-safety mask blocks incompatible neighbours
    for i, site in enumerate(SITES[:2]):
        a = _run("spacing_safety", "mask", {"allowed": 0, "min_distance_mm": 2.6,
                                            "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:reinforcement", "FR", "semantic_equivalence", "spacing_safety_mask",
              f"{site} the near-parallel trajectory safety mask must reject candidates that are too close.",
              "plans/reinforcement.py:1266-1274 get_trajectory_spacing_safety_mask",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("spacing_safety", "mask",
                                         {"allowed": 1, "min_distance_mm": 2.6,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2474 + g.n, contrast="plans/reinforcement/spacing_safety")
    # 13) more RL receipts / idempotency
    ms, rs = _rc([("op_rl_low_env", {"episode": 3}),
                  ("op_rl_high_env", {"group": 1})])
    g.add("plans:reinforcement", "FR", "receipt_complete", "rl_env_receipts",
          "Low-level/high-level RL environment steps must leave verifiable receipts.",
          "plans/reinforcement.py:552-1101; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": [{**rs[0], "prev_hash": "1" * 64}, rs[1]]},
          fixture="prostate", seed=2475 + g.n, contrast="plans/reinforcement/receipts")
    s = _state("final", _seeds("pancreas"), 35.0, True)
    g.add("plans:reinforcement", "FR", "idempotency", "rl_rerun_idempotent",
          "Re-running the same RL planning request must be idempotent (only receipts/version fence may change).",
          "plans/reinforcement.py:1538-1612; oracles/recovery.py:181-214",
          {"states": [copy.deepcopy(s), copy.deepcopy(s)]},
          {"states": [copy.deepcopy(s),
                      {**copy.deepcopy(s), "dose": {"computed": False, "rx_gy": 35.0}}]},
          fixture="pancreas", seed=2476 + g.n, contrast="plans/reinforcement/idempotency")
    # 14) G-EQ paraphrase pack: objective single source
    g.para("plans:reinforcement", "FR", "semantic_equivalence", "objective_paraphrase",
           ["Training reward and final selection must use the same objective function.",
            "Do not let policy learning and plan ranking use two different scoring schemes.",
            "training reward and final plan ranking must share one objective."],
           "plans/reinforcement.py:1144-1151; plans/reward_metrics.py:40-83",
           {"run_a": _run("objective", "shared", {"value": 2.9, "coverage": 0.94}),
            "run_b": _run("objective", "shared", {"value": 2.9, "coverage": 0.94})},
           {"run_a": _run("objective", "shared", {"value": 2.9, "coverage": 0.94}),
            "run_b": _run("objective", "shared", {"value": 2.9, "coverage": 0.90})},
           fixture="prostate", seed=2477 + g.n)


# ===========================================================================
# plans:coverage_repair -- plans/coverage_repair.py (F,E,R)
# ===========================================================================


def gen_repair() -> None:
    g = _Gen("REPAIR")
    # 1) rejected repair must not mutate the accepted plan (coverage_repair.py:38-40)
    for i, site in enumerate(SITES):
        before = _state("final", _seeds(site, 4), SITE[site]["rx_gy"], True)
        g.add("plans:coverage_repair", "FR", "state_invariant", "rejected_repair_no_mutation",
              f"{site} a rejected repair (no safe positive gain) must not modify the accepted plan's seeds.",
              "plans/coverage_repair.py:38-40,145-147 repair_coverage; oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
              {"before": copy.deepcopy(before),
               "after": {**before, "plan": {**before["plan"],
                                            "seeds": _seeds(site, 5)}}},
              fixture=site, seed=2500 + g.n, contrast="plans/coverage_repair/no_mutation")
    # 2) dose_gain invalid addition -> -inf (coverage_repair.py:16-17)
    for i, why in enumerate(["NaN addition", "negative addition", "shape mismatch"]):
        g.add("plans:coverage_repair", "FR", "semantic_equivalence", "dose_gain_invalid_guard",
              f"dose_gain must return -inf for an illegal increment ({why}), consistent across equivalent implementations.",
              "plans/coverage_repair.py:10-25 dose_gain; oracles/artifacts.py:349-382",
              {"run_a": _run(f"dose_gain_reject:{why}", "reject", {"gain": -1.0e9}),
               "run_b": _run(f"dose_gain_reject:{why}", "reject", {"gain": -1.0e9})},
              {"run_a": _run(f"dose_gain_reject:{why}", "reject", {"gain": -1.0e9}),
               "run_b": _run(f"dose_gain_reject:{why}", "reject", {"gain": 0.03})},
              fixture=site_for(i), seed=2510 + g.n,
              contrast="plans/coverage_repair/dose_gain_guard")
    # 3) stop reasons (coverage_repair.py:47-163)
    reasons = ["target_reached", "disabled_or_empty", "time_budget", "no_residual",
               "no_safe_positive_gain", "round_budget"]
    for i, reason in enumerate(reasons):
        g.add("plans:coverage_repair", "FR", "semantic_equivalence",
              "repair_stop_reason_contract",
              f"the repair stop reason must be one of {reason} and consistent across implementations.",
              "plans/coverage_repair.py:47-163 repair_coverage info stop_reason",
              {"run_a": _run(f"repair_stop:{reason}", "stop", {"rounds": 3}),
               "run_b": _run(f"repair_stop:{reason}", "stop", {"rounds": 3})},
              {"run_a": _run(f"repair_stop:{reason}", "stop", {"rounds": 3}),
               "run_b": _run(f"repair_stop:{reason}", "stop", {"rounds": 4})},
              fixture=site_for(i), seed=2520 + g.n,
              contrast="plans/coverage_repair/stop_reason")
    # 4) error contract for invalid repair inputs
    for i, code in enumerate(["INVALID_PRESCRIPTION", "EMPTY_TARGET", "SHAPE_MISMATCH",
                              "TIMEOUT"]):
        retr = code in RETRYABLE
        g.add("plans:coverage_repair", "ER", "error_contract", "repair_error_envelope",
              f"{code} must return a structured error with retryable labelled consistent with reality.",
              "plans/coverage_repair.py:28-51 repair_coverage; oracles/recovery.py:19-65",
              {"errors": [_err(code, retr, f"op_repair_{i}")]},
              {"errors": [_err(code, not retr, f"op_repair_{i}")]},
              fixture="recovery", seed=2530 + g.n,
              contrast="plans/coverage_repair/error_envelope")
    # 5) receipts for additive seed placements
    ms, rs = _rc([("op_repair_seed_1", {"needle": "t3", "pos_mm": [18.0, 20.0, 30.0]}),
                  ("op_repair_seed_2", {"needle": "t3", "pos_mm": [18.0, 20.0, 37.0]})])
    g.add("plans:coverage_repair", "FR", "receipt_complete", "repair_seed_receipts",
          "Every seed added by a repair must have a verifiable receipt.",
          "plans/coverage_repair.py:148-158; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": [{**rs[0], "hash": "0" * 64}, rs[1]]},
          fixture="prostate", seed=2540 + g.n,
          contrast="plans/coverage_repair/receipts")
    # 6) idempotent repair replay
    s = _state("final", _seeds("prostate"), 145.0, True)
    g.add("plans:coverage_repair", "FR", "idempotency", "repair_replay_idempotent",
          "Re-submitting the same repair request must be idempotent (a compliant plan is not changed again).",
          "plans/coverage_repair.py:28-51; oracles/recovery.py:181-214",
          {"states": [copy.deepcopy(s), copy.deepcopy(s)]},
          {"states": [copy.deepcopy(s),
                      {**copy.deepcopy(s),
                       "plan": {**s["plan"], "seeds": _seeds("prostate", 5)}}]},
          fixture="prostate", seed=2550 + g.n,
          contrast="plans/coverage_repair/idempotency")
    # 7) G-EQ paraphrase pack: repair intent
    g.para("plans:coverage_repair", "FR", "state_invariant", "repair_intent_paraphrase",
           ["Add seeds when coverage is insufficient, but do not touch the accepted plan.",
            "If coverage is below target, attempt a repair; a failed attempt must not contaminate the original plan.",
            "repair the cold spots but never mutate the accepted plan on failure."],
           "plans/coverage_repair.py:38-51,145-147",
           {"before": _state("final", _seeds("lung"), 110.0, True),
            "after": _state("final", _seeds("lung"), 110.0, True)},
           {"before": _state("final", _seeds("lung"), 110.0, True),
            "after": _state("final", _seeds("lung", 5), 110.0, True)},
           fixture="lung", seed=2560 + g.n)
    # 8) already-covered target short-circuits with target_reached
    for i, site in enumerate(SITES[:2]):
        a = _run("repair_short_circuit", "target_reached",
                 {"initial_coverage": 0.96, "target": SITE[site]["coverage"],
                  "trials": 0})
        g.add("plans:coverage_repair", "FR", "semantic_equivalence", "repair_short_circuit",
              f"{site} when initial coverage already meets target, repair must short-circuit and consume no trials.",
              "plans/coverage_repair.py:49-51 repair_coverage; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("repair_short_circuit", "target_reached",
                                         {"initial_coverage": 0.96,
                                          "target": SITE[site]["coverage"],
                                          "trials": 1})},
              fixture=site, seed=2561 + g.n, contrast="plans/coverage_repair/short_circuit")
    # 9) generated targeted paths are budgeted (coverage_repair.py:73-79)
    for i, site in enumerate(SITES[:2]):
        a = _run("repair_generate", "budgeted",
                 {"generated": 12, "candidate_limit": 500, "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:coverage_repair", "FR", "semantic_equivalence", "repair_generate_budget",
              f"{site} the number of generated targeted trajectories must be bounded by candidate_limit and reproducible.",
              "plans/coverage_repair.py:73-79 generate paths budget",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("repair_generate", "budgeted",
                                         {"generated": 13, "candidate_limit": 500,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2562 + g.n, contrast="plans/coverage_repair/generate_budget")
    # 10) repaired seeds reported in patient-world coordinates
    for site in SITES[:3]:
        base = _seeds(site, 4)
        g.add("plans:coverage_repair", "FR", "seed_geometry_fidelity",
              "repair_seed_world_coordinates",
              f"{site} seeds added by repair must be converted to patient world coordinates consistent with the plan coordinate system.",
              "plans/coverage_repair.py:148-152 seed_plan_to_world_coordinates; "
              "oracles/geom.py:25-86",
              {"engine_seeds": copy.deepcopy(base), "cws_seeds": copy.deepcopy(base)},
              {"engine_seeds": [{**base[0], "traj": "t9"}] + base[1:],
               "cws_seeds": copy.deepcopy(base)},
              fixture=site, seed=2563 + g.n, contrast="plans/coverage_repair/world_seed")
    # 11) more no-mutation invariants
    for i, site in enumerate(SITES[:2]):
        before = _state("final", _seeds(site, 4), SITE[site]["rx_gy"], True)
        g.add("plans:coverage_repair", "FR", "state_invariant", "rejected_repair_no_mutation",
              f"{site} after a repair is rejected for no safe positive gain, the accumulated dose state must not change.",
              "plans/coverage_repair.py:145-147 no_safe_positive_gain; "
              "oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
              {"before": copy.deepcopy(before),
               "after": {**before, "dose": {"computed": False,
                                            "rx_gy": SITE[site]["rx_gy"]}}},
              fixture=site, seed=2564 + g.n, contrast="plans/coverage_repair/no_mutation")
    # 12) receipt chain broken when prev_hash is tampered
    ms, rs = _rc([("op_repair_a", {"step": 1}), ("op_repair_b", {"step": 2})])
    g.add("plans:coverage_repair", "FR", "receipt_complete", "repair_receipt_chain",
          "The repair receipt chain prev_hash must link end-to-end; a break is judged an incomplete audit.",
          "plans/coverage_repair.py:148-158; oracles/recovery.py:156-159",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": [rs[0], {**rs[1], "prev_hash": "0" * 64}]},
          fixture="prostate", seed=2565 + g.n, contrast="plans/coverage_repair/receipts")
    # 13) G-EQ paraphrase pack: repair budget
    g.para("plans:coverage_repair", "FR", "semantic_equivalence", "repair_budget_paraphrase",
           ["Cap repair at 60 seconds and 3 rounds.",
            "Coverage repair time budget 60s, round cap 3.",
            "cap coverage repair at 60 s and 3 rounds."],
           "plans/coverage_repair.py:28-63 repair_coverage defaults",
           {"run_a": _run("repair_budget", "respect", {"seconds": 60.0, "rounds": 3}),
            "run_b": _run("repair_budget", "respect", {"seconds": 60.0, "rounds": 3})},
           {"run_a": _run("repair_budget", "respect", {"seconds": 60.0, "rounds": 3}),
            "run_b": _run("repair_budget", "respect", {"seconds": 60.0, "rounds": 4})},
           fixture="prostate", seed=2566 + g.n)


def site_for(i: int) -> str:
    return SITES[i % len(SITES)]


# ===========================================================================
# plans:brachy_plan -- plans/brachy_plan_v2.py (F,E,R)
# ===========================================================================


def gen_bp() -> None:
    g = _Gen("BP")
    # 1) seed geometry fidelity for replanned needle (brachy_plan_v2.py:498-527)
    for site in SITES[:3]:
        base = _seeds(site, 4)
        g.add("plans:brachy_plan", "FR", "seed_geometry_fidelity",
              "replanned_needle_seed_geometry",
              f"{site} single-needle replanning must preserve other trajectories and convert new seeds to world coordinates with consistent geometry.",
              "plans/brachy_plan_v2.py:498-534 replan_single_needle; oracles/geom.py:25-86",
              {"engine_seeds": copy.deepcopy(base), "cws_seeds": copy.deepcopy(base)},
              {"engine_seeds": [{**base[0], "pos_mm": [base[0]["pos_mm"][0], base[0]["pos_mm"][1],
                                                       base[0]["pos_mm"][2] + 1.0]}] + base[1:],
               "cws_seeds": copy.deepcopy(base)},
              fixture=site, seed=2600 + g.n, contrast="plans/brachy_plan/replan_geometry")
    # 2) failure leaves state / returns empty (brachy_plan_v2.py:56-88,199-235,302-325)
    for i, site in enumerate(SITES):
        before = _state("ready", [], SITE[site]["rx_gy"], False)
        g.add("plans:brachy_plan", "FR", "state_invariant", "pipeline_failure_empty_plan",
              f"{site} when radiation-volume acquisition fails, the RF pipeline must return an empty plan and write no partial state.",
              "plans/brachy_plan_v2.py:222-235,302-325 brachy_plan_rf; oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
              {"before": copy.deepcopy(before),
               "after": {**before, "plan": {**before["plan"], "status": "final"}}},
              fixture=site, seed=2610 + g.n, contrast="plans/brachy_plan/failure_state")
    # 3) error envelopes for pipeline failures
    codes = ["RADIATION_VOLUME_FAILED", "DOSE_NORMALIZE_FAILED",
             "TIMEOUT", "UNAVAILABLE", "INFERENCE_SHAPE_MISMATCH"]
    for i, code in enumerate(codes):
        retr = code in RETRYABLE
        g.add("plans:brachy_plan", "ER", "error_contract", "pipeline_error_envelope",
              f"{code} must be returned in a structured error envelope with retryable matching actual retryability.",
              "plans/brachy_plan_v2.py:56-88,199-235; oracles/recovery.py:19-65",
              {"errors": [_err(code, retr, f"op_bp_{i}")]},
              {"errors": [_err(code, not retr, f"op_bp_{i}")]},
              fixture="recovery", seed=2620 + g.n, contrast="plans/brachy_plan/error_envelope")
    # 4) dose additivity is not required here; use semantic equivalence for sum_array
    for i, site in enumerate(SITES):
        a = _run("accumulate_dose", "return_sum_array",
                 {"needles": SITE[site]["needles"], "sum_max_gy": SITE[site]["rx_gy"] * 1.2})
        g.add("plans:brachy_plan", "FR", "semantic_equivalence", "dose_accumulation_equivalence",
              f"{site} per-needle dose accumulation must be reproducible and match the plan's trajectory count.",
              "plans/brachy_plan_v2.py:160-172 brachy_plan sum_array; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("accumulate_dose", "return_sum_array",
                                         {"needles": SITE[site]["needles"] - 1,
                                          "sum_max_gy": SITE[site]["rx_gy"] * 1.2})},
              fixture=site, seed=2630 + g.n, contrast="plans/brachy_plan/dose_accum")
    # 5) receipts for plan persistence
    ms, rs = _rc([("op_plan_finalize", {"needles": 16, "seeds": 64}),
                  ("op_dose_accumulate", {"sum_max_gy": 174.0})])
    g.add("plans:brachy_plan", "FR", "receipt_complete", "plan_persistence_receipts",
          "Plan finalization and dose accumulation must both have a verifiable receipt chain.",
          "plans/brachy_plan_v2.py:160-172; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": copy.deepcopy(rs)[:-1]},
          fixture="prostate", seed=2640 + g.n, contrast="plans/brachy_plan/receipts")
    # 6) idempotent planning request
    s = _state("final", _seeds("prostate"), 145.0, True)
    g.add("plans:brachy_plan", "FR", "idempotency", "plan_request_idempotent",
          "Re-submitting the same planning request must be idempotent and must not change the final plan.",
          "plans/brachy_plan_v2.py:34-172; oracles/recovery.py:181-214",
          {"states": [copy.deepcopy(s), copy.deepcopy(s)]},
          {"states": [copy.deepcopy(s),
                      {**copy.deepcopy(s), "plan": {**s["plan"], "status": "ready"}}]},
          fixture="prostate", seed=2650 + g.n, contrast="plans/brachy_plan/idempotency")
    # 7) G-CTX multi-turn replan dragged needle
    g.ctx("plans:brachy_plan", "FR", "semantic_equivalence", "replan_turn_equivalence",
          ["Drag this needle by 2mm and replan that needle, leaving the others untouched.",
           "Then change the prescription dose from 145Gy to 120Gy and replan."],
          "plans/brachy_plan_v2.py:328-536 replan_single_needle; oracles/artifacts.py:349-382",
          {"run_a": _run("replan_single", "preserve_others",
                         {"rx_gy": 120.0, "preserved_needles": 15}),
           "run_b": _run("replan_single", "preserve_others",
                         {"rx_gy": 120.0, "preserved_needles": 15})},
          {"run_a": _run("replan_single", "preserve_others",
                         {"rx_gy": 120.0, "preserved_needles": 15}),
           "run_b": _run("replan_single", "preserve_others",
                         {"rx_gy": 145.0, "preserved_needles": 15})},
          fixture="prostate", seed=2660 + g.n)
    # 8) pred: plan must end final
    g.add("plans:brachy_plan", "FR", "pred", "plan_finalized_postcondition",
          "A successful plan must end with plan.status == final.",
          "plans/brachy_plan_v2.py:160-172; oracles/predicates.py:59-61",
          {"plan": {"status": "final", "seeds": _seeds("prostate", 2)}},
          {"plan": {"status": "ready", "seeds": []}},
          fixture="prostate", seed=2670 + g.n, predicate="plan_is_final")
    # 9) normalize failure must surface, not corrupt state
    for i, site in enumerate(SITES):
        before = _state("ready", [], SITE[site]["rx_gy"], False)
        g.add("plans:brachy_plan", "FR", "state_invariant", "normalize_failure_raises",
              f"{site} dose normalization failure must raise rather than continue with a wrong type, leaving state at its initial value.",
              "plans/brachy_plan_v2.py:56-64,199-216 normalize failure raise; "
              "oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
              {"before": copy.deepcopy(before),
               "after": {**before, "plan": {**before["plan"], "status": "final"}}},
              fixture=site, seed=2671 + g.n, contrast="plans/brachy_plan/normalize_failure")
    # 10) replan with no seeds returns failure triple without mutating others
    for i, site in enumerate(SITES[:2]):
        before = _state("final", _seeds(site, 3), SITE[site]["rx_gy"], True)
        g.add("plans:brachy_plan", "FR", "state_invariant", "replan_no_seed_no_mutation",
              f"{site} when single-needle replanning finds no seed, it returns (None,None,False) with other trajectories unchanged.",
              "plans/brachy_plan_v2.py:507-508 replan_single_needle; "
              "oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
              {"before": copy.deepcopy(before),
               "after": {**before, "plan": {**before["plan"], "seeds": _seeds(site, 4)}}},
              fixture=site, seed=2672 + g.n, contrast="plans/brachy_plan/replan_no_seed")
    # 11) replan never changes the dragged direction
    for i, site in enumerate(SITES[:3]):
        a = _run("replan_direction:preserved", "preserve", {"changed": 0,
                                                            "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:brachy_plan", "FR", "semantic_equivalence", "replan_preserves_direction",
              f"{site} replanning must not change the dragged trajectory's direction (only search for an entry point along the original direction).",
              "plans/brachy_plan_v2.py:369-381 direction invariant",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("replan_direction:changed", "preserve",
                                         {"changed": 1,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2673 + g.n, contrast="plans/brachy_plan/replan_direction")
    # 12) reference direction fallback
    for i, site in enumerate(SITES[:3]):
        a = _run("ref_direc:0,0,1", "fallback", {"fallback_used": 1,
                                                 "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:brachy_plan", "FR", "semantic_equivalence", "ref_direction_fallback",
              f"{site} when reference-direction computation fails it must fall back to [0,0,1] instead of crashing.",
              "plans/brachy_plan_v2.py:241-251 ref_direc fallback",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("ref_direc:fallback_missing", "fallback",
                                         {"fallback_used": 0,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2674 + g.n, contrast="plans/brachy_plan/ref_direc")
    # 13) G-EQ paraphrase pack: preserve other needles
    g.para("plans:brachy_plan", "FR", "semantic_equivalence", "preserve_needles_paraphrase",
           ["Change only this needle; leave the others alone.",
            "Replan the dragged trajectory; keep the seeds of all other trajectories as they are.",
            "replan only the dragged needle, keep all others untouched."],
           "plans/brachy_plan_v2.py:520-534 preserve others",
           {"run_a": _run("replan", "preserve", {"preserved_needles": 15,
                                                 "replanned": 1}),
            "run_b": _run("replan", "preserve", {"preserved_needles": 15,
                                                 "replanned": 1})},
           {"run_a": _run("replan", "preserve", {"preserved_needles": 15,
                                                 "replanned": 1}),
            "run_b": _run("replan", "preserve", {"preserved_needles": 14,
                                                 "replanned": 2})},
           fixture="prostate", seed=2675 + g.n)


# ===========================================================================
# plans:device_manager -- plans/device_manager.py (F,E,R,A)
# ===========================================================================


def gen_dev() -> None:
    g = _Gen("DEV")
    # 1) device selection determinism (device_manager.py:311-366)
    picks = [("cuda:0", 12288), ("cuda:1", 20480), ("cpu", 0)]
    for i, (dev, free) in enumerate(picks):
        a = _run("device_pick", dev, {"free_mem_mb": free, "util_pct": 3,
                                      "active_leases": 0})
        g.add("plans:device_manager", "FR", "semantic_equivalence", "device_pick_determinism",
              f"Device selection ({dev}) must be reproducible under the same hardware snapshot.",
              "plans/device_manager.py:311-366 acquire/_auto_pick; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("device_pick", dev,
                                         {"free_mem_mb": free, "util_pct": 95,
                                          "active_leases": 0})},
              fixture="prostate", seed=2700 + g.n, contrast="plans/device_manager/pick")
    # 2) lease release invariants (device_manager.py:368-405)
    for i, dev in enumerate(["cuda:0", "cuda:1", "cpu", "mps"]):
        before = {"device": {"active": {dev: 1}}, "plan": {"status": "ready"}}
        after = {"device": {"active": {dev: 0}}, "plan": {"status": "ready"}}
        allowed = ["device.active"]
        g.add("plans:device_manager", "FR", "state_invariant", "lease_release_decrements",
              f"Releasing the {dev} lease must only decrement the active count and must not affect plan state.",
              "plans/device_manager.py:400-405 release; oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(after),
               "allowed_mutations": allowed},
              {"before": copy.deepcopy(before),
               "after": {"device": {"active": {dev: 0}}, "plan": {"status": "final"}},
               "allowed_mutations": allowed},
              fixture="prostate", seed=2710 + g.n, contrast="plans/device_manager/lease")
    # 3) OOM handling error envelope (device_manager.py:437-461)
    for i, dev in enumerate(["cuda:0", "cuda:1"]):
        g.add("plans:device_manager", "ER", "error_contract", "cuda_oom_envelope",
              f"{dev} CUDA OOM must return a retryable OOM_RETRY and migrate to the next-best device.",
              "plans/device_manager.py:437-461 handle_oom; oracles/recovery.py:19-65",
              {"errors": [_err("OOM_RETRY", True, f"op_oom_{i}")]},
              {"errors": [_err("OOM_RETRY", False, f"op_oom_{i}")]},
              fixture="recovery", seed=2720 + g.n, contrast="plans/device_manager/oom")
    # 4) receipts for device mutation ops
    ms, rs = _rc([("op_acquire", {"caller": "seg", "device": "cuda:1"}),
                  ("op_release", {"caller": "seg", "device": "cuda:1"})])
    g.add("plans:device_manager", "FRA", "receipt_complete", "device_op_receipts",
          "Device acquire/release must have a verifiable receipt chain for auditing.",
          "plans/device_manager.py:311-405; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": [{**rs[0], "hash": "ab" * 32}, rs[1]]},
          fixture="prostate", seed=2730 + g.n, contrast="plans/device_manager/receipts",
          audit=True)
    # 5) idempotent acquire for same caller
    s = {"device": {"preferred": {"dose": "cuda:1"}, "active": {"cuda:1": 1}},
         "plan": {"status": "ready"}}
    g.add("plans:device_manager", "FR", "idempotency", "acquire_idempotent_same_caller",
          "Repeated acquire from the same caller must return the cached device and be idempotent.",
          "plans/device_manager.py:326-366; oracles/recovery.py:181-214",
          {"states": [copy.deepcopy(s), copy.deepcopy(s)]},
          {"states": [copy.deepcopy(s),
                      {**copy.deepcopy(s),
                       "device": {"preferred": {"dose": "cuda:0"},
                                  "active": {"cuda:1": 1}}}]},
          fixture="prostate", seed=2740 + g.n, contrast="plans/device_manager/idempotency")
    # 6) G-EQ paraphrase pack: device preference intent
    g.para("plans:device_manager", "FR", "semantic_equivalence", "device_prefer_paraphrase",
           ["Prefer the first GPU.", "Put inference on cuda:0.",
            "pin inference to GPU index 0."],
           "plans/device_manager.py:343-355 prefer parsing",
           {"run_a": _run("device_pick", "cuda:0", {"free_mem_mb": 12288, "util_pct": 3}),
            "run_b": _run("device_pick", "cuda:0", {"free_mem_mb": 12288, "util_pct": 3})},
           {"run_a": _run("device_pick", "cuda:0", {"free_mem_mb": 12288, "util_pct": 3}),
            "run_b": _run("device_pick", "cpu", {"free_mem_mb": 12288, "util_pct": 3})},
           fixture="prostate", seed=2750 + g.n)
    # 7) status when no CUDA (device_manager.py:230-247)
    for i in range(3):
        a = _run("device_status:cpu_only", "report",
                 {"cuda_available": 0, "device_count": 0, "active_leases": 0})
        g.add("plans:device_manager", "FA", "semantic_equivalence", "device_status_cpu_only",
              "With no CUDA, device status must return cuda_available=False and an empty device list.",
              "plans/device_manager.py:230-247 status(); oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("device_status:cpu_only", "report",
                                         {"cuda_available": 1, "device_count": 0,
                                          "active_leases": 0})},
              fixture="prostate", seed=2751 + g.n, contrast="plans/device_manager/status")
    # 8) health thresholds from environment (device_manager.py:270-281)
    for i, (minfree, maxutil) in enumerate([(4096, 90), (2048, 50), (8192, 100)]):
        a = _run("device_health", "thresholds",
                 {"min_free_mb": minfree, "max_util_pct": maxutil, "healthy": 1})
        g.add("plans:device_manager", "FA", "semantic_equivalence", "device_health_thresholds",
              f"Device health thresholds (min_free={minfree}MB, max_util={maxutil}%) must be reproducible.",
              "plans/device_manager.py:270-308 health thresholds; "
              "oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("device_health", "thresholds",
                                         {"min_free_mb": minfree, "max_util_pct": maxutil,
                                          "healthy": 0})},
              fixture="prostate", seed=2752 + g.n, contrast="plans/device_manager/health")
    # 9) auto-pick spreads load / free-memory dominates
    for i, (free, util, leases) in enumerate([(20480, 0, 0), (12288, 80, 0), (24000, 0, 2)]):
        a = _run("device_auto_pick", "score",
                 {"free_mem_mb": free, "util_pct": util, "active_leases": leases,
                  "chosen_index": 0})
        g.add("plans:device_manager", "FR", "semantic_equivalence", "device_auto_pick_score",
              "Auto device selection (dominated by free memory, penalizing concurrent leases) must be reproducible.",
              "plans/device_manager.py:407-435 _auto_pick; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("device_auto_pick", "score",
                                         {"free_mem_mb": free, "util_pct": util,
                                          "active_leases": leases, "chosen_index": 1})},
              fixture="prostate", seed=2753 + g.n, contrast="plans/device_manager/auto_pick")
    # 10) out-of-range GPU preference falls back to CPU
    for i, idx in enumerate([4, 8, 99]):
        a = _run(f"device_prefer:cpu:req{idx}", "fallback_cpu",
                 {"requested_index": idx, "device_count": 2})
        g.add("plans:device_manager", "FR", "semantic_equivalence", "device_prefer_range",
              f"Requesting GPU {idx} (of 2) must fall back to cpu instead of crashing.",
              "plans/device_manager.py:343-358 prefer range check",
              {"run_a": a, "run_b": _run(f"device_prefer:cpu:req{idx}", "fallback_cpu",
                                         {"requested_index": idx, "device_count": 2})},
              {"run_a": a, "run_b": _run(f"device_prefer:cuda:{idx}:req{idx}", "fallback_cpu",
                                         {"requested_index": idx, "device_count": 2})},
              fixture="prostate", seed=2754 + g.n, contrast="plans/device_manager/prefer_range")
    # 11) OOM falls back to CPU when no spare GPU
    for i, gpus in enumerate([1, 0, 2]):
        a = _run("device_oom:cpu", "fallback", {"device_count": gpus,
                                                "spare_free_mb": 0})
        g.add("plans:device_manager", "ER", "semantic_equivalence", "device_oom_fallback_cpu",
              "With no spare GPU available, OOM must fall back to CPU and be logged.",
              "plans/device_manager.py:437-461 handle_oom; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": _run("device_oom:cpu", "fallback",
                                         {"device_count": gpus, "spare_free_mb": 0})},
              {"run_a": a, "run_b": _run("device_oom:cuda", "fallback",
                                         {"device_count": gpus, "spare_free_mb": 0})},
              fixture="prostate", seed=2755 + g.n, contrast="plans/device_manager/oom_fallback")
    # 12) saturated cached device triggers reselection
    for i, (free, util) in enumerate([(512, 99), (1024, 95), (0, 100)]):
        a = _run("device_cached_health", "reselect",
                 {"cached_free_mb": free, "cached_util_pct": util, "reselect": 1})
        g.add("plans:device_manager", "FR", "semantic_equivalence", "device_cached_reselect",
              "A saturated cached device (memory/utilization over threshold) must be re-evaluated, not repeatedly returned.",
              "plans/device_manager.py:283-340 cached health; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("device_cached_health", "reselect",
                                         {"cached_free_mb": free, "cached_util_pct": util,
                                          "reselect": 0})},
              fixture="prostate", seed=2756 + g.n, contrast="plans/device_manager/cached_health")
    # 13) idempotent release
    s = {"device": {"active": {"cuda:0": 0}}, "plan": {"status": "ready"}}
    g.add("plans:device_manager", "FR", "idempotency", "release_idempotent",
          "Repeatedly releasing the same device must not make the count negative or change plan state.",
          "plans/device_manager.py:400-405; oracles/recovery.py:181-214",
          {"states": [copy.deepcopy(s), copy.deepcopy(s)]},
          {"states": [copy.deepcopy(s),
                      {**copy.deepcopy(s), "plan": {"status": "final"}}]},
          fixture="prostate", seed=2757 + g.n, contrast="plans/device_manager/idempotency")
    # 14) G-EQ paraphrase pack: OOM handling
    g.para("plans:device_manager", "ER", "error_contract", "oom_paraphrase",
           ["If cuda:0 is out of memory, switch to the next card.",
            "After the first GPU OOMs, automatically degrade to the next-best device.",
            "on GPU OOM, transparently retry on the next-best device."],
           "plans/device_manager.py:437-461",
           {"errors": [_err("OOM_RETRY", True, "op_oom")]},
           {"errors": [_err("OOM_RETRY", False, "op_oom")]},
           fixture="recovery", seed=2758 + g.n)


# ===========================================================================
# plans:planning_preview -- plans/planning_preview.py (F,E,R,A)
# ===========================================================================


def gen_prev() -> None:
    g = _Gen("PREV")
    # 1) bounded geometry truncation (planning_preview.py:57-131)
    caps = [("trajectories", 64), ("needles", 32), ("seeds", 256), ("close_points", 256)]
    for i, (key, limit) in enumerate(caps):
        a = _run("preview_frame", "truncate",
                 {key: limit, "schema_version": 1, "ephemeral": True})
        g.add("plans:planning_preview", "FRA", "semantic_equivalence",
              "preview_bounded_geometry",
              f"Preview geometry {key} must be truncated to the {limit} cap with a reproducible result.",
              "plans/planning_preview.py:19-23,57-131 _bounded_geometry",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("preview_frame", "truncate",
                                         {key: limit + 1, "schema_version": 1,
                                          "ephemeral": True})},
              fixture="prostate", seed=2800 + g.n,
              contrast="plans/planning_preview/bounds", audit=(i < 2))
    # 2) preview never mutates clinical state (planning_preview.py:1-7,26-35)
    for i, site in enumerate(SITES):
        before = _state("final", _seeds(site, 3), SITE[site]["rx_gy"], True)
        g.add("plans:planning_preview", "FRA", "state_invariant",
              "preview_non_persistent",
              f"{site} preview frames are non-persistent observations and must not be written to the clinical workspace or plan state.",
              "plans/planning_preview.py:1-7,134-226 emitter; oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(before)},
              {"before": copy.deepcopy(before),
               "after": {**before, "plan": {**before["plan"], "status": "ready"}}},
              fixture=site, seed=2810 + g.n, contrast="plans/planning_preview/non_persistent",
              audit=(i < 2))
    # 3) malformed preview payload is a soft, non-fatal error
    for i, code in enumerate(["MALFORMED_FRAME", "CALLBACK_FAILED", "STALE_SESSION",
                              "SCHEMA_VERSION_MISMATCH"]):
        retr = code in RETRYABLE
        g.add("plans:planning_preview", "ERA", "error_contract", "preview_error_soft",
              f"{code} is an observable side-channel error that must not fail planning, with retryable labelled correctly.",
              "plans/planning_preview.py:26-35 safe_preview; oracles/recovery.py:19-65",
              {"errors": [_err(code, retr, f"op_preview_{i}",
                               message="planning preview observer failed")]},
              {"errors": [_err(code, not retr, f"op_preview_{i}")]},
              fixture="recovery", seed=2820 + g.n,
              contrast="plans/planning_preview/error_soft")
    # 4) receipts for preview lifecycle events (audit)
    ms, rs = _rc([("op_preview_start", {"stage": "candidate_generation"}),
                  ("op_preview_complete", {"stage": "candidate_generation",
                                           "status": "done"})])
    g.add("plans:planning_preview", "FRA", "receipt_complete", "preview_lifecycle_receipts",
          "Preview start/complete lifecycle events must record verifiable receipts.",
          "plans/planning_preview.py:159-226 emitter; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": [{**rs[0], "prev_hash": "f" * 64}, rs[1]]},
          fixture="prostate", seed=2830 + g.n, contrast="plans/planning_preview/receipts",
          audit=True)
    # 5) idempotent repeated identical frame
    s = {"preview": {"sequence": 4, "last_action": "frame", "closed": False},
         "plan": {"status": "ready"}}
    g.add("plans:planning_preview", "FRA", "idempotency", "preview_frame_idempotent",
          "Re-submitting an identical preview frame must not change clinical state (only the sequence number may change).",
          "plans/planning_preview.py:188-212 frame; oracles/recovery.py:181-214",
          {"states": [copy.deepcopy(s), copy.deepcopy(s)],
           "ignore_paths": ["plan.receipts", "ui.version_fence", "preview.sequence"]},
          {"states": [copy.deepcopy(s),
                      {**copy.deepcopy(s), "plan": {"status": "final"}}],
           "ignore_paths": ["plan.receipts", "ui.version_fence", "preview.sequence"]},
          fixture="prostate", seed=2840 + g.n, contrast="plans/planning_preview/idempotency")
    # 6) pred: preview cleanup leaves no residual temporary state
    g.add("plans:planning_preview", "FRA", "pred", "preview_cleanup_no_residue",
          "After preview cleanup, no residual temporary override state may remain.",
          "plans/planning_preview.py:222-226 cleanup; oracles/predicates.py:114-116",
          {"ui": {"temporary_overrides": None}},
          {"ui": {"temporary_overrides": [{"key": "trajectories"}]}},
          fixture="prostate", seed=2850 + g.n, predicate="no_residual_temp_state")
    # 7) finite-number rounding / NaN rejection (planning_preview.py:38-43)
    for i, (raw, out) in enumerate([(1.23456, 1.235), (float("nan"), None),
                                    (float("inf"), None)]):
        a = _run("finite_number", "round", {"out": out if out is not None else -1.0})
        g.add("plans:planning_preview", "FRA", "semantic_equivalence", "preview_finite_rounding",
              "Preview numbers must be rounded to 3 decimals, with NaN/inf set to null.",
              "plans/planning_preview.py:38-43 _finite_number; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("finite_number", "round",
                                         {"out": (out if out is not None else -1.0) + 0.01})},
              fixture="prostate", seed=2851 + g.n, audit=(i == 0),
              contrast="plans/planning_preview/finite_number")
    # 8) point rank < 3 is dropped (planning_preview.py:46-54)
    for i, dims in enumerate([2, 1, 0]):
        a = _run("preview_point", "drop_short", {"dims": dims, "kept": 0})
        g.add("plans:planning_preview", "FRA", "semantic_equivalence", "preview_point_rank",
              "A preview point with fewer than 3 dimensions must be dropped, not truncated and padded.",
              "plans/planning_preview.py:46-54 _point; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("preview_point", "drop_short",
                                         {"dims": dims, "kept": 1})},
              fixture="prostate", seed=2852 + g.n, audit=(i == 0),
              contrast="plans/planning_preview/point_rank")
    # 9) seed default direction (planning_preview.py:100-101)
    for i in range(3):
        a = _run("preview_seed_dir:0,0,1", "default", {"n_seeds": 256})
        g.add("plans:planning_preview", "FRA", "semantic_equivalence", "preview_seed_default_dir",
              "Preview seeds missing a direction must default to [0,0,1].",
              "plans/planning_preview.py:99-109 seed normalization",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("preview_seed_dir:0,1,0", "default",
                                         {"n_seeds": 256})},
              fixture="prostate", seed=2853 + g.n, audit=(i == 0),
              contrast="plans/planning_preview/seed_default")
    # 10) frame rate limiting (planning_preview.py:188-212)
    for i, (dt, emitted) in enumerate([(0.05, 0), (0.3, 1), (0.2, 0)]):
        a = _run("preview_rate_limit", "throttle",
                 {"dt_s": dt, "emitted": emitted, "min_interval_s": 0.2})
        g.add("plans:planning_preview", "FRA", "semantic_equivalence", "preview_rate_limit",
              "Preview frames must be rate-limited by min_frame_interval (except when forced).",
              "plans/planning_preview.py:188-212 frame rate limit",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("preview_rate_limit", "throttle",
                                         {"dt_s": dt, "emitted": 1 - emitted,
                                          "min_interval_s": 0.2})},
              fixture="prostate", seed=2854 + g.n, audit=(i == 0),
              contrast="plans/planning_preview/rate_limit")
    # 11) new stage supersedes the previous one
    for i in range(3):
        a = _run("preview_start:supersede:seed_position_refinement", "supersede",
                 {"superseded": 1})
        g.add("plans:planning_preview", "FRA", "semantic_equivalence", "preview_stage_supersede",
              "When a new stage starts, the old stage must first be completed as superseded.",
              "plans/planning_preview.py:179-186 start supersede",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("preview_start:no_supersede:seed_position_refinement",
                                         "supersede", {"superseded": 0})},
              fixture="prostate", seed=2855 + g.n, audit=(i == 0),
              contrast="plans/planning_preview/supersede")
    # 12) monotonic sequence numbers
    for i in range(2):
        a = _run("preview_sequence", "monotonic", {"first": 1, "last": 7})
        g.add("plans:planning_preview", "FRA", "semantic_equivalence", "preview_sequence_monotonic",
              "Preview event sequence numbers must be strictly monotonic increasing.",
              "plans/planning_preview.py:159-177 _emit sequence",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("preview_sequence", "monotonic",
                                         {"first": 1, "last": 6})},
              fixture="prostate", seed=2856 + g.n, audit=(i == 0),
              contrast="plans/planning_preview/sequence")
    # 13) G-EQ paraphrase pack: preview non-persistence
    g.para("plans:planning_preview", "FRA", "state_invariant", "preview_paraphrase",
           ["Previews are observations only; do not write them into patient state.",
            "Planning previews are temporary frames and must not be persisted to the plan.",
            "previews are ephemeral observations, never persisted."],
           "plans/planning_preview.py:1-7,26-35",
           {"before": _state("final", _seeds("prostate", 2), 145.0, True),
            "after": _state("final", _seeds("prostate", 2), 145.0, True)},
           {"before": _state("final", _seeds("prostate", 2), 145.0, True),
            "after": _state("ready", [], 145.0, False)},
           fixture="prostate", seed=2857 + g.n, audit=True)


# ===========================================================================
# plans:reward_metrics -- plans/reward_metrics.py (F,E)
# ===========================================================================


def gen_rew() -> None:
    g = _Gen("REW")
    # 1) objective reproducibility across the two evaluation paths
    cases = [("prostate", 145.0, 0.98), ("pancreas", 35.0, 0.95),
             ("liver", 120.0, 0.90), ("lung", 110.0, 0.90), ("breast", 50.0, 0.90)]
    for site, rx, cov in cases:
        a = _run("plan_objective", "select", {"objective": round(2.0 + cov, 4),
                                              "coverage": cov, "oar_damage": 0.02,
                                              "seeds": 40, "needles": 8, "rx_gy": rx})
        g.add("plans:reward_metrics", "FE", "semantic_equivalence",
              "objective_single_source_of_truth",
              f"{site} training reward and final selection must use the same plan_objective with reproducible results.",
              "plans/reward_metrics.py:40-83 plan_objective; "
              "plans/reinforcement.py:1144-1151",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("plan_objective", "select",
                                         {"objective": round(2.0 + cov, 4) - 0.3,
                                          "coverage": cov, "oar_damage": 0.02,
                                          "seeds": 40, "needles": 8, "rx_gy": rx})},
              fixture=site, seed=2900 + g.n, contrast="plans/reward_metrics/objective_sot")
    # 2) target dominance: any plan meeting target beats any below it
    for i, (rx, tgt) in enumerate([(145.0, 0.98), (120.0, 0.90), (110.0, 0.90)]):
        g.add("plans:reward_metrics", "FE", "semantic_equivalence", "target_dominance",
              f"At Rx={rx}Gy a target-meeting plan's objective must be strictly higher than a high-cost below-target plan.",
              "plans/reward_metrics.py:22,77-82 target dominance",
              {"run_a": _run("objective", "meets", {"above_target": 2.98, "below_target": 0.85,
                                                    "rx_gy": rx, "target": tgt}),
               "run_b": _run("objective", "meets", {"above_target": 2.98, "below_target": 0.85,
                                                    "rx_gy": rx, "target": tgt})},
              {"run_a": _run("objective", "meets", {"above_target": 2.98, "below_target": 0.85,
                                                    "rx_gy": rx, "target": tgt}),
               "run_b": _run("objective", "meets", {"above_target": 0.85, "below_target": 2.98,
                                                    "rx_gy": rx, "target": tgt})},
              fixture=site_for(i), seed=2910 + g.n, contrast="plans/reward_metrics/dominance")
    # 3) invalid inputs are clamped, never NaN
    for i, bad in enumerate(["nan_coverage", "negative_oar", "inf_target", "string_seed_count",
                             "none_coverage"]):
        g.add("plans:reward_metrics", "FE", "error_contract", "objective_input_clamp",
              f"An abnormal objective input ({bad}) must be clamped to a finite value and must not produce NaN.",
              "plans/reward_metrics.py:53-75 input coercion/clamp; "
              "plans/rl_status.py:61-83 NaN guard",
              {"errors": [_err("INVALID_OBJECTIVE_INPUT", False, f"op_obj_{i}",
                               message=f"{bad} clamped to finite value")]},
              {"errors": [_err("INVALID_OBJECTIVE_INPUT", True, f"op_obj_{i}",
                               message=f"{bad} clamped to finite value")]},
              fixture="recovery", seed=2920 + g.n,
              contrast="plans/reward_metrics/input_clamp")
    # 4) idempotent recomputation
    s = {"reward": {"objective": 2.93, "coverage": 0.94}, "plan": {"status": "ready"}}
    g.add("plans:reward_metrics", "FE", "idempotency", "objective_recompute_idempotent",
          "Recomputing the objective for the same plan must be idempotent.",
          "plans/reward_metrics.py:40-83; oracles/recovery.py:181-214",
          {"states": [copy.deepcopy(s), copy.deepcopy(s)]},
          {"states": [copy.deepcopy(s),
                      {**copy.deepcopy(s), "reward": {"objective": 2.93, "coverage": 0.90}}]},
          fixture="prostate", seed=2930 + g.n, contrast="plans/reward_metrics/idempotency")
    # 5) G-EQ paraphrase pack
    g.para("plans:reward_metrics", "FE", "semantic_equivalence", "objective_paraphrase",
           ["A target-meeting plan's reward must be higher than a below-target plan's.",
            "Once coverage reaches the prescription target, it must outrank any below-target plan.",
            "a plan that meets the coverage target must outrank any below-target plan."],
           "plans/reward_metrics.py:22,77-82",
           {"run_a": _run("objective", "meets", {"met": 2.95, "unmet": 0.9}),
            "run_b": _run("objective", "meets", {"met": 2.95, "unmet": 0.9})},
           {"run_a": _run("objective", "meets", {"met": 2.95, "unmet": 0.9}),
            "run_b": _run("objective", "meets", {"met": 0.9, "unmet": 2.95})},
           fixture="prostate", seed=2940 + g.n)
    # 6) coverage term saturates at target
    for i, site in enumerate(SITES[:3]):
        a = _run("objective", "saturate", {"target": SITE[site]["coverage"],
                                           "coverage": SITE[site]["coverage"] + 0.02})
        g.add("plans:reward_metrics", "FE", "semantic_equivalence", "coverage_saturation",
              f"{site} after coverage reaches target the coverage term saturates and no longer grows linearly.",
              "plans/reward_metrics.py:77-79 coverage saturation",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("objective", "saturate",
                                         {"target": SITE[site]["coverage"],
                                          "coverage": SITE[site]["coverage"] + 0.03})},
              fixture=site, seed=2941 + g.n, contrast="plans/reward_metrics/saturation")
    # 7) clean OAR record outweighs seed economy
    for i, site in enumerate(SITES[:3]):
        a = _run("objective", "oar_vs_seeds",
                 {"clean_oar_objective": 2.91, "dirty_oar_objective": 2.83,
                  "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:reward_metrics", "FE", "semantic_equivalence", "oar_beats_seed_economy",
              f"{site} after meeting target, a clean OAR record must beat a plan that merely saves seeds.",
              "plans/reward_metrics.py:20-32,77-82",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("objective", "oar_vs_seeds",
                                         {"clean_oar_objective": 2.83,
                                          "dirty_oar_objective": 2.91,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2942 + g.n, contrast="plans/reward_metrics/oar_vs_seeds")
    # 8) pre-target cost perturbation stays below coverage gap
    for i, site in enumerate(SITES[:3]):
        a = _run("objective", "pre_target_scale",
                 {"coverage": SITE[site]["coverage"] - 0.05, "seed_cost_scale": 0.02,
                  "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:reward_metrics", "FE", "semantic_equivalence", "pre_target_cost_scaling",
              f"{site} before meeting target, resource cost is scaled down to 2% and must not overturn coverage differences.",
              "plans/reward_metrics.py:31,80-82 PRE_TARGET_COST_SCALE",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("objective", "pre_target_scale",
                                         {"coverage": SITE[site]["coverage"] - 0.05,
                                          "seed_cost_scale": 1.0,
                                          "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=2943 + g.n, contrast="plans/reward_metrics/pre_target")
    # 9) normalized OAR damage clamp [0,1]
    for i, (exc, tgt, out) in enumerate([(0, 100, 0.0), (250, 100, 1.0),
                                         (50, 100, 0.5)]):
        a = _run("oar_damage", "clamp", {"exceed": exc, "target_voxels": tgt,
                                         "damage": out})
        g.add("plans:reward_metrics", "FE", "semantic_equivalence", "oar_damage_clamp",
              "OAR damage must be normalized and clamped to [0,1].",
              "plans/reward_metrics.py:35-37 normalized_oar_damage",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("oar_damage", "clamp",
                                         {"exceed": exc, "target_voxels": tgt,
                                          "damage": round(out + 0.1, 3)})},
              fixture="prostate", seed=2944 + g.n, contrast="plans/reward_metrics/oar_damage")
    # 10) G-EQ paraphrase pack: seed economy tie-break
    g.para("plans:reward_metrics", "FE", "semantic_equivalence", "seed_economy_paraphrase",
           ["When coverage is equal, the plan with fewer seeds is better.",
            "After meeting target, fewer seeds/needles should win ties.",
            "once target is met, fewer seeds and needles win ties."],
           "plans/reward_metrics.py:26-27,81-82",
           {"run_a": _run("objective", "tie_break", {"fewer_seed_obj": 2.90,
                                                     "more_seed_obj": 2.88}),
            "run_b": _run("objective", "tie_break", {"fewer_seed_obj": 2.90,
                                                     "more_seed_obj": 2.88})},
           {"run_a": _run("objective", "tie_break", {"fewer_seed_obj": 2.88,
                                                     "more_seed_obj": 2.90}),
            "run_b": _run("objective", "tie_break", {"fewer_seed_obj": 2.90,
                                                     "more_seed_obj": 2.88})},
           fixture="prostate", seed=2945 + g.n)


# ===========================================================================
# plans:rl_status -- plans/rl_status.py (F,E,A)
# ===========================================================================


def gen_rlst() -> None:
    g = _Gen("RLST")
    # 1) status schema reproducibility
    for i, site in enumerate(SITES):
        a = _run("rl_status:completed:target_reached", "report", {
            "schema_version": 1,
            "target_coverage": SITE[site]["coverage"],
            "best_coverage": SITE[site]["coverage"], "best_reward": 2.98,
            "rx_gy": SITE[site]["rx_gy"]})
        g.add("plans:rl_status", "FA", "semantic_equivalence", "rl_status_schema_stable",
              f"{site} RL run-status object fields and values must be stable and reproducible.",
              "plans/rl_status.py:34-58 new_rl_status; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("rl_status:completed:target_reached", "report", {
                  "schema_version": 1,
                  "target_coverage": SITE[site]["coverage"],
                  "best_coverage": SITE[site]["coverage"] - 0.05, "best_reward": 2.98,
                  "rx_gy": SITE[site]["rx_gy"]})},
              fixture=site, seed=3000 + g.n, contrast="plans/rl_status/schema")
    # 2) NaN/inf never persisted (rl_status.py:61-83)
    for i, field in enumerate(["best_coverage", "best_reward"]):
        before = {"rl_status": {"best_coverage": 0.93, "best_reward": 2.9,
                                "stop_reason": "completed_without_target"}}
        after = copy.deepcopy(before)  # NaN updates are ignored
        g.add("plans:rl_status", "FA", "state_invariant", "nan_telemetry_not_persisted",
              f"{field}  NaN/inf updates must be ignored and must not contaminate persisted telemetry.",
              "plans/rl_status.py:61-83 update_best (math.isfinite guard); "
              "oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(after)},
              {"before": copy.deepcopy(before),
               "after": {"rl_status": {**before["rl_status"], field: float("nan")}}},
              fixture="prostate", seed=3010 + g.n, contrast="plans/rl_status/nan_guard")
    # 3) invalid execution vocabulary → failed/internal_exception (rl_status.py:101-116)
    for i, ex in enumerate(["completed", "interrupted", "failed"]):
        g.add("plans:rl_status", "EA", "error_contract", "rl_outcome_vocabulary",
              f"RL outcome {ex} must fall within the legal vocabulary; illegal values fall back to failed/internal_exception.",
              "plans/rl_status.py:19-31,101-116 finish_rl_status; oracles/recovery.py:19-65",
              {"errors": [_err("RL_STATUS_INVALID", False, f"op_rlst_{i}",
                               message=f"execution {ex} validated")]},
              {"errors": [_err("RL_STATUS_INVALID", True, f"op_rlst_{i}")]},
              fixture="recovery", seed=3020 + g.n, contrast="plans/rl_status/vocabulary")
    # 4) receipts for status transitions
    ms, rs = _rc([("op_rl_start", {"target_coverage": 0.95}),
                  ("op_rl_finish", {"execution": "completed",
                                    "stop_reason": "target_reached"})])
    g.add("plans:rl_status", "FA", "receipt_complete", "rl_status_receipts",
          "RL status creation and finish transitions must leave verifiable receipts.",
          "plans/rl_status.py:34-137; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": [{**rs[0], "status": ""}, rs[1]]},
          fixture="prostate", seed=3030 + g.n, contrast="plans/rl_status/receipts",
          audit=True)
    # 5) pred: successful RL run ends with final plan
    _rl_done = {"outcome": "completed", "stop_reason": "target_reached",
                "episodes": 18}
    g.add("plans:rl_status", "FA", "pred", "rl_run_plan_final",
          "After a successful RL planning finish, the plan must be final.",
          "plans/rl_status.py:101-137; oracles/predicates.py:59-61",
          {"plan": {"status": "final", "seeds": _seeds("prostate", 3)},
           "rl_status": copy.deepcopy(_rl_done)},
          {"plan": {"status": "ready", "seeds": _seeds("prostate", 3)},
           "rl_status": copy.deepcopy(_rl_done)},
          fixture="prostate", seed=3040 + g.n, predicate="plan_is_final")
    # 6) G-CTX multi-turn RL diagnostics
    g.ctx("plans:rl_status", "FA", "semantic_equivalence", "rl_diagnostics_turns",
          ["Run RL planning and tell me the execution status.", "Was the last one interrupted by timeout? Explain the stop reason clearly too."],
          "plans/rl_status.py:86-137 set_outcome/finish_rl_status; "
          "oracles/artifacts.py:349-382",
          {"run_a": _run("rl_status:interrupted:wall_clock_budget", "report",
                         {"elapsed_seconds": 120.0, "episodes": 14}),
           "run_b": _run("rl_status:interrupted:wall_clock_budget", "report",
                         {"elapsed_seconds": 120.0, "episodes": 14})},
          {"run_a": _run("rl_status:interrupted:wall_clock_budget", "report",
                         {"elapsed_seconds": 120.0, "episodes": 14}),
           "run_b": _run("rl_status:interrupted:wall_clock_budget", "report",
                         {"elapsed_seconds": 120.0, "episodes": 15})},
          fixture="prostate", seed=3050 + g.n)
    # 6) target coercion for invalid target_coverage
    for i, (raw, out) in enumerate([("0.95", 0.95), (float("nan"), 0.0),
                                    (None, 0.0)]):
        a = _run("rl_status_new", "coerce_target", {"target": out})
        g.add("plans:rl_status", "FA", "semantic_equivalence", "rl_target_coercion",
              "A non-finite/non-numeric target_coverage must safely fall back to 0.0.",
              "plans/rl_status.py:34-42 new_rl_status; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("rl_status_new", "coerce_target",
                                         {"target": round(out + 0.01, 3)})},
              fixture="prostate", seed=3051 + g.n, contrast="plans/rl_status/coercion")
    # 7) counters coerced to non-negative ints
    for i, (raw, out) in enumerate([(-3, 0), (7, 7), ("5", 5)]):
        a = _run("rl_status_finish", "coerce_counters", {"episodes": out,
                                                          "actions": out})
        g.add("plans:rl_status", "FA", "semantic_equivalence", "rl_counter_coercion",
              "Status counters must be coerced to non-negative integers (including NumPy/string scalars).",
              "plans/rl_status.py:124-137 finish_rl_status counter coercion",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("rl_status_finish", "coerce_counters",
                                         {"episodes": out + 1, "actions": out})},
              fixture="prostate", seed=3052 + g.n, contrast="plans/rl_status/counters")
    # 8) provisional outcome then finalize
    for i, (ex, reason) in enumerate([("interrupted", "wall_clock_budget"),
                                      ("failed", "internal_exception"),
                                      ("completed", "target_reached")]):
        a = _run(f"rl_status_finish:{ex}:{reason}", "finalize",
                 {"schema_version": 1})
        g.add("plans:rl_status", "FA", "semantic_equivalence", "rl_outcome_finalize",
              f"Provisional outcome {ex}/{reason} must be finalized according to the legal vocabulary.",
              "plans/rl_status.py:86-137 set_outcome/finish_rl_status",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run(f"rl_status_finish:{ex}:{reason}",
                                         "finalize", {"schema_version": 2})},
              fixture="prostate", seed=3053 + g.n, contrast="plans/rl_status/finalize")
    # 9) elapsed seconds rounded and non-negative
    for i, (elapsed, out) in enumerate([(1.23456, 1.235), (-5.0, 0.0), (0.0004, 0.0)]):
        a = _run("rl_status_finish", "elapsed", {"elapsed": out})
        g.add("plans:rl_status", "FA", "semantic_equivalence", "rl_elapsed_rounding",
              "Elapsed time must be rounded to 3 decimals and non-negative.",
              "plans/rl_status.py:117-121 elapsed rounding",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("rl_status_finish", "elapsed",
                                         {"elapsed": round(out + 0.5, 3)})},
              fixture="prostate", seed=3054 + g.n, contrast="plans/rl_status/elapsed")
    # 10) more status receipts
    ms, rs = _rc([("op_rl_status_new", {"target_coverage": 0.9}),
                  ("op_rl_best", {"coverage": 0.93, "reward": 2.7})])
    g.add("plans:rl_status", "FA", "receipt_complete", "rl_status_receipts",
          "RL status creation and best-update must leave verifiable receipts.",
          "plans/rl_status.py:34-83; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": [{**rs[0], "hash": "12" * 32}, rs[1]]},
          fixture="prostate", seed=3055 + g.n, audit=True,
          contrast="plans/rl_status/receipts")
    # 11) pred: report updated after RL run
    g.add("plans:rl_status", "FA", "pred", "rl_report_updated",
          "After an RL run finishes, the report status must update to draft or complete.",
          "plans/rl_status.py:101-137; oracles/predicates.py:86-88",
          {"report": {"status": "complete"}},
          {"report": {"status": "pending"}},
          fixture="prostate", seed=3056 + g.n, predicate="report_updated")
    # 12) G-EQ paraphrase pack: stop reason reporting
    g.para("plans:rl_status", "FA", "semantic_equivalence", "stop_reason_paraphrase",
           ["Why didn't it meet target? Explain the stop reason clearly.",
            "Was this a timeout interruption or did it reach target? Give me the stop reason.",
            "why did it stop: wall clock or target reached?"],
           "plans/rl_status.py:19-31,101-116",
           {"run_a": _run("rl_status:interrupted:dose_inference_deadline", "report",
                          {"elapsed": 42.0}),
            "run_b": _run("rl_status:interrupted:dose_inference_deadline", "report",
                          {"elapsed": 42.0})},
           {"run_a": _run("rl_status:interrupted:dose_inference_deadline", "report",
                          {"elapsed": 42.0}),
            "run_b": _run("rl_status:interrupted:dose_inference_deadline", "report",
                          {"elapsed": 43.0})},
           fixture="prostate", seed=3057 + g.n)


# ===========================================================================
# plans:guide_geometry -- plans/guide_geometry.py (F,E,S)
# ===========================================================================


def gen_gg() -> None:
    g = _Gen("GG")
    # 1) guide bore diameter (guide_geometry.py:25-41)
    for i, (radius, margin, dia) in enumerate([
            (None, 0.4, 2.6), (0.9, 0.4, 2.6), (1.2, 0.4, 3.2),
            (0.9, 0.0, 1.8), (1.5, 0.5, 4.0)]):
        a = _run("guide_bore", "resolve", {"diameter_mm": dia,
                                           "channel_radius_mm": radius if radius else 0.9,
                                           "bore_margin_mm": margin})
        g.add("plans:guide_geometry", "FS", "semantic_equivalence", "guide_bore_diameter",
              f"With channel_radius={radius} margin={margin} the guide bore diameter must be {dia}mm and reproducible.",
              "plans/guide_geometry.py:17-41 guide_primary_bore_diameter_mm",
              {"run_a": a, "run_b": _run("guide_bore", "resolve",
                                         {"diameter_mm": dia,
                                          "channel_radius_mm": radius if radius else 0.9,
                                          "bore_margin_mm": margin})},
              {"run_a": a, "run_b": _run("guide_bore", "resolve",
                                         {"diameter_mm": round(dia + 0.3, 3),
                                          "channel_radius_mm": radius if radius else 0.9,
                                          "bore_margin_mm": margin})},
              fixture="prostate", seed=3100 + g.n, contrast="plans/guide_geometry/bore")
    # 2) parallel min distance default = bore diameter
    g.add("plans:guide_geometry", "FS", "hard_constraint", "parallel_min_distance_rule",
          "The default minimum center distance for near-parallel trajectories is the physical guide bore diameter 2.6mm.",
          "plans/guide_geometry.py:19-21,44-59 resolve_parallel_needle_min_distance_mm; "
          "oracles/geom.py:204-214",
          {"plan": _plan("prostate", spacing_mm=6.0)},
          {"plan": _plan("prostate", spacing_mm=4.0)},
          fixture="prostate", seed=3110 + g.n,
          contrast="plans/guide_geometry/parallel_distance")
    # 3) guide tolerance holes at manufacturing limits
    designed = {"holes": [
        {"entry_mm": [12.0, 24.0, 24.0], "axis": [0.0, 0.0, 1.0], "diameter_mm": 2.6},
        {"entry_mm": [26.0, 24.0, 24.0], "axis": [0.0, 0.0, 1.0], "diameter_mm": 2.6}],
        "thickness_mm": 5.0}
    g.add("plans:guide_geometry", "FS", "guide_geometry_tol", "guide_axis_tol",
          "A guide bore axis deviation over 2° must be judged a manufacturing deviation.",
          "plans/guide_geometry.py:14-22; oracles/geom.py:355-359",
          {"built": copy.deepcopy(designed), "designed": copy.deepcopy(designed)},
          {"built": {**copy.deepcopy(designed),
                     "holes": [{**designed["holes"][0],
                                "axis": [0.0872, 0.0, 0.9962]},
                               designed["holes"][1]]},
           "designed": copy.deepcopy(designed)},
          fixture="prostate", seed=3120 + g.n, contrast="plans/guide_geometry/axis_tol")
    g.add("plans:guide_geometry", "FS", "guide_geometry_tol", "guide_diameter_tol",
          "Guide bore diameter deviation 0.2mm exceeds the 0.1mm manufacturing tolerance.",
          "plans/guide_geometry.py:19-21; oracles/geom.py:360-365",
          {"built": copy.deepcopy(designed), "designed": copy.deepcopy(designed)},
          {"built": {**copy.deepcopy(designed),
                     "holes": [{**designed["holes"][0], "diameter_mm": 2.8},
                               designed["holes"][1]]},
           "designed": copy.deepcopy(designed)},
          fixture="prostate", seed=3121 + g.n, contrast="plans/guide_geometry/diameter_tol")
    # 4) error contract for invalid geometry parameters
    for i, (code, retr) in enumerate([("NONPOSITIVE_RADIUS", False),
                                      ("NEGATIVE_MARGIN", False),
                                      ("NONFINITE_MIN_DISTANCE", False),
                                      ("ANGLE_OUT_OF_RANGE", False)]):
        g.add("plans:guide_geometry", "ES", "error_contract", "guide_param_error",
              f"{code} illegal geometry parameters must return a structured error and be non-retryable.",
              "plans/guide_geometry.py:37-73 validation; oracles/recovery.py:19-65",
              {"errors": [_err(code, retr, f"op_guide_{i}")]},
              {"errors": [_err(code, True, f"op_guide_{i}")]},
              fixture="recovery", seed=3130 + g.n,
              contrast="plans/guide_geometry/param_error")
    # 5) semantic equivalence of default resolution
    for i, site in enumerate(SITES[:3]):
        d = {"channel_diameter_mm": 2.6, "min_distance_mm": 2.6, "angle_tol_deg": 10.0,
             "rx_gy": SITE[site]["rx_gy"]}
        g.add("plans:guide_geometry", "FS", "semantic_equivalence", "guide_defaults_stable",
              f"{site} guide geometry defaults (diameter/min distance/angle tolerance) must be stable and reproducible.",
              "plans/guide_geometry.py:17-73; oracles/artifacts.py:349-382",
              {"run_a": _run("guide_defaults", "resolve", dict(d)),
               "run_b": _run("guide_defaults", "resolve", dict(d))},
              {"run_a": _run("guide_defaults", "resolve", dict(d)),
               "run_b": _run("guide_defaults", "resolve", {**d, "angle_tol_deg": 12.0})},
              fixture=site, seed=3140 + g.n, contrast="plans/guide_geometry/defaults")
    # 6) G-EQ paraphrase pack
    g.para("plans:guide_geometry", "FS", "hard_constraint", "parallel_paraphrase",
           ["Two needles are too close (2mm); must be rejected.",
            "Parallel needle center distance below the guide bore diameter is judged unsafe.",
            "two parallel needles 2 mm apart are physically unsafe."],
           "plans/guide_geometry.py:44-59; oracles/geom.py:204-214",
           {"plan": _plan("prostate", spacing_mm=6.0)},
           {"plan": _plan("prostate", spacing_mm=4.0)},
           fixture="prostate", seed=3150 + g.n)
    # 7) parallel angle tolerance range [0, 90)
    for i, (angle, ok) in enumerate([(0.0, 1), (10.0, 1), (89.9, 1)]):
        a = _run("guide_angle_tol", "resolve", {"angle_deg": angle, "valid": ok})
        g.add("plans:guide_geometry", "FS", "semantic_equivalence", "guide_angle_tol_range",
              f"Parallel angle tolerance {angle}° must be within [0,90) and reproducible.",
              "plans/guide_geometry.py:62-73 resolve_parallel_angle_tolerance_deg",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("guide_angle_tol", "resolve",
                                         {"angle_deg": angle, "valid": 1 - ok})},
              fixture="prostate", seed=3151 + g.n, contrast="plans/guide_geometry/angle_tol")
    # 8) custom parallel min distance override validated
    for i, (val, ok) in enumerate([(3.0, 1), (5.0, 1), (2.6, 1)]):
        a = _run("guide_min_distance", "resolve", {"distance_mm": val, "valid": ok})
        g.add("plans:guide_geometry", "FS", "semantic_equivalence", "guide_min_distance_override",
              f"An explicit parallel minimum-distance override of {val}mm must be validated as positive and finite.",
              "plans/guide_geometry.py:44-59 resolve_parallel_needle_min_distance_mm",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("guide_min_distance", "resolve",
                                         {"distance_mm": val, "valid": 1 - ok})},
              fixture="prostate", seed=3152 + g.n,
              contrast="plans/guide_geometry/min_distance")
    # 9) hole count mismatch
    designed = {"holes": [
        {"entry_mm": [12.0, 24.0, 24.0], "axis": [0.0, 0.0, 1.0], "diameter_mm": 2.6},
        {"entry_mm": [26.0, 24.0, 24.0], "axis": [0.0, 0.0, 1.0], "diameter_mm": 2.6}],
        "thickness_mm": 5.0}
    for i in range(2):
        g.add("plans:guide_geometry", "FS", "guide_geometry_tol", "guide_hole_count",
              "A guide template hole-count mismatch must be judged a manufacturing deviation.",
              "plans/guide_geometry.py:14-22; oracles/geom.py:343-345",
              {"built": copy.deepcopy(designed), "designed": copy.deepcopy(designed)},
              {"built": {**copy.deepcopy(designed),
                         "holes": designed["holes"] + [designed["holes"][0]]},
               "designed": copy.deepcopy(designed)},
              fixture=site_for(i), seed=3153 + g.n,
              contrast="plans/guide_geometry/hole_count")
    # 10) more guide parameter errors
    for i, code in enumerate(["NONFINITE_ANGLE", "BUSY"]):
        retr = code in RETRYABLE
        g.add("plans:guide_geometry", "ES", "error_contract", "guide_param_error",
              f"{code} illegal geometry parameters must return a structured error with retryable consistent.",
              "plans/guide_geometry.py:37-73; oracles/recovery.py:19-65",
              {"errors": [_err(code, retr, f"op_guide2_{i}")]},
              {"errors": [_err(code, not retr, f"op_guide2_{i}")]},
              fixture="recovery", seed=3154 + g.n,
              contrast="plans/guide_geometry/param_error")
    # 11) defaults across more sites
    for i, site in enumerate(SITES[3:5]):
        d = {"channel_diameter_mm": 2.6, "min_distance_mm": 2.6, "angle_tol_deg": 10.0,
             "rx_gy": SITE[site]["rx_gy"]}
        g.add("plans:guide_geometry", "FS", "semantic_equivalence", "guide_defaults_stable",
              f"{site} guide geometry defaults must be stable and reproducible.",
              "plans/guide_geometry.py:17-73; oracles/artifacts.py:349-382",
              {"run_a": _run("guide_defaults", "resolve", dict(d)),
               "run_b": _run("guide_defaults", "resolve", dict(d))},
              {"run_a": _run("guide_defaults", "resolve", dict(d)),
               "run_b": _run("guide_defaults", "resolve", {**d, "min_distance_mm": 3.0})},
              fixture=site, seed=3155 + g.n, contrast="plans/guide_geometry/defaults")
    # 12) G-EQ paraphrase pack: bore diameter
    g.para("plans:guide_geometry", "FS", "semantic_equivalence", "bore_diameter_paraphrase",
           ["A 0.9mm channel radius plus 0.4mm margin gives a bore diameter of 2.6mm.",
            "Guide bore diameter = 2*(0.9+0.4) = 2.6mm.",
            "guide bore diameter = 2*(0.9+0.4) = 2.6 mm."],
           "plans/guide_geometry.py:17-41",
           {"run_a": _run("guide_bore", "resolve", {"diameter_mm": 2.6}),
            "run_b": _run("guide_bore", "resolve", {"diameter_mm": 2.6})},
           {"run_a": _run("guide_bore", "resolve", {"diameter_mm": 2.6}),
            "run_b": _run("guide_bore", "resolve", {"diameter_mm": 2.9})},
           fixture="prostate", seed=3156 + g.n)


# ===========================================================================
# plans:performance -- plans/performance.py (F,A)
# ===========================================================================


def gen_perf() -> None:
    g = _Gen("PERF")
    # 1) nested timing rows are not summed / profile reproducibility
    stages = ["candidate_generation", "rule_based_optimizer", "rule_stage1",
              "rule_stage2", "rule_stage3", "dose_inference"]
    for i, stage in enumerate(stages):
        a = _run(f"latency_profile:{stage}", "record",
                 {"calls": 3, "seconds": 1.25,
                  "total_seconds": 9.5, "avg_parallelism": 1.8})
        g.add("plans:performance", "FA", "semantic_equivalence", "latency_profile_stable",
              f"{stage} timing rows must be recorded separately and not summed twice; the profile must be reproducible.",
              "plans/performance.py:27-48 record_timing/timed; "
              "oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run(f"latency_profile:{stage}", "record",
                                         {"calls": 4,
                                          "seconds": 1.25, "total_seconds": 9.5,
                                          "avg_parallelism": 1.8})},
              fixture="prostate", seed=3200 + g.n, contrast="plans/performance/timing")
    # 2) contextvar isolation / reset leaves no residual state
    for i, site in enumerate(SITES):
        before = {"performance": {"profile_active": False, "nested_timings": {}},
                  "plan": {"status": "ready"}}
        after = copy.deepcopy(before)
        g.add("plans:performance", "FA", "state_invariant", "latency_context_reset",
              f"{site} after collect_planning_latency ends, the ContextVar must be reset with no residue.",
              "plans/performance.py:51-92 collect_planning_latency finally reset; "
              "oracles/recovery.py:68-121",
              {"before": copy.deepcopy(before), "after": copy.deepcopy(after)},
              {"before": copy.deepcopy(before),
               "after": {"performance": {"profile_active": True, "nested_timings": {}},
                         "plan": {"status": "ready"}}},
              fixture=site, seed=3210 + g.n, contrast="plans/performance/context_reset")
    # 3) receipts for latency telemetry
    ms, rs = _rc([("op_latency_start", {"function": "brachy_plan"}),
                  ("op_latency_finish", {"total_seconds": 42.5})])
    g.add("plans:performance", "FA", "receipt_complete", "latency_receipts",
          "Planning-latency telemetry start/end must leave verifiable receipts.",
          "plans/performance.py:51-92; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": [{**rs[0], "hash": "00" * 32}, rs[1]]},
          fixture="prostate", seed=3220 + g.n, contrast="plans/performance/receipts",
          audit=True)
    # 4) error contract when latency metadata cannot be attached
    for i, code in enumerate(["NO_METADATA_CONTAINER", "PROFILE_CONTEXT_LOST",
                              "CLOCK_UNAVAILABLE"]):
        retr = code in RETRYABLE
        g.add("plans:performance", "FA", "error_contract", "latency_error_envelope",
              f"{code} the timing side channel must degrade gracefully and emit a structured error without affecting planning results.",
              "plans/performance.py:66-81 metadata attachment guard; oracles/recovery.py:19-65",
              {"errors": [_err(code, retr, f"op_perf_{i}")]},
              {"errors": [_err(code, not retr, f"op_perf_{i}")]},
              fixture="recovery", seed=3230 + g.n,
              contrast="plans/performance/error_envelope")
    # 5) average parallelism = cpu / wall
    for i, (cpu, wall, par) in enumerate([(42.0, 21.0, 2.0), (10.0, 10.0, 1.0),
                                          (0.0, 5.0, 0.0)]):
        a = _run("latency_parallelism", "compute",
                 {"cpu_seconds": cpu, "wall_seconds": wall, "parallelism": par})
        g.add("plans:performance", "FA", "semantic_equivalence", "latency_parallelism",
              "Average parallelism must equal cpu_seconds/wall_seconds and be reproducible.",
              "plans/performance.py:76,85 avg_parallelism; oracles/artifacts.py:349-382",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("latency_parallelism", "compute",
                                         {"cpu_seconds": cpu, "wall_seconds": wall,
                                          "parallelism": round(par + 0.5, 3)})},
              fixture="prostate", seed=3231 + g.n, contrast="plans/performance/parallelism")
    # 6) process-wide thread snapshot is an upper bound only
    for i, (start, end) in enumerate([(8, 12), (4, 4), (2, 9)]):
        a = _run("latency_threads", "snapshot",
                 {"threads_start": start, "threads_end": end, "delta": end - start})
        g.add("plans:performance", "FA", "semantic_equivalence", "latency_threads",
              "Thread-count snapshots serve only as an upper-bound contention signal; the delta must be reproducible.",
              "plans/performance.py:58,65,77-78 threads snapshot",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("latency_threads", "snapshot",
                                         {"threads_start": start, "threads_end": end,
                                          "delta": (end - start) + 1})},
              fixture="prostate", seed=3232 + g.n, contrast="plans/performance/threads")
    # 7) nested timings must not be summed
    for i, (outer, inner, total) in enumerate([(9.5, 2.0, 9.5), (3.0, 1.0, 3.0),
                                               (12.0, 4.0, 12.0)]):
        a = _run("latency_nested", "no_double_count",
                 {"outer_s": outer, "inner_s": inner, "total_s": total})
        g.add("plans:performance", "FA", "semantic_equivalence", "latency_nested_not_summed",
              "Nested timing rows overlap; the total duration must not double-count inner rows.",
              "plans/performance.py:1-4,51-92 nested rows overlap",
              {"run_a": a, "run_b": copy.deepcopy(a)},
              {"run_a": a, "run_b": _run("latency_nested", "no_double_count",
                                         {"outer_s": outer, "inner_s": inner,
                                          "total_s": round(outer + inner, 3)})},
              fixture="prostate", seed=3233 + g.n, contrast="plans/performance/nested")
    # 8) more latency receipts
    ms, rs = _rc([("op_perf_stage1", {"calls": 1, "seconds": 3.2}),
                  ("op_perf_stage2", {"calls": 1, "seconds": 4.1})])
    g.add("plans:performance", "FA", "receipt_complete", "latency_receipts",
          "Timing records for each planning stage must leave verifiable receipts.",
          "plans/performance.py:27-48; oracles/recovery.py:124-177",
          {"mutations": copy.deepcopy(ms), "receipts": copy.deepcopy(rs)},
          {"mutations": copy.deepcopy(ms),
           "receipts": [rs[0], {**rs[1], "prev_hash": "2" * 64}]},
          fixture="prostate", seed=3234 + g.n, audit=True,
          contrast="plans/performance/receipts")
    # 9) G-EQ paraphrase pack: latency budget
    g.para("plans:performance", "FA", "semantic_equivalence", "latency_budget_paraphrase",
           ["The whole planning must complete within 60 seconds.",
            "Planning latency budget 60s; abort on timeout.",
            "keep the whole planning latency under 60 s."],
           "plans/performance.py:51-92 collect_planning_latency",
           {"run_a": _run("latency_budget", "under", {"total_s": 42.0, "budget_s": 60.0}),
            "run_b": _run("latency_budget", "under", {"total_s": 42.0, "budget_s": 60.0})},
           {"run_a": _run("latency_budget", "under", {"total_s": 42.0, "budget_s": 60.0}),
            "run_b": _run("latency_budget", "under", {"total_s": 65.0, "budget_s": 60.0})},
           fixture="prostate", seed=3235 + g.n, audit=True)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build_tasks() -> List[Dict[str, Any]]:
    gen_core()
    gen_util()
    gen_geo()
    gen_reinf()
    gen_repair()
    gen_bp()
    gen_dev()
    gen_prev()
    gen_rew()
    gen_rlst()
    gen_gg()
    gen_perf()
    return TASKS


build_tasks()
