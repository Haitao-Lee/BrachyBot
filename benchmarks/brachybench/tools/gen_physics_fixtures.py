#!/usr/bin/env python3
"""Property-based physics-boundary fixtures (DESIGN §21.1, 80-150 configurations).

These are the one class of item that **can** be generated procedurally without
losing quality, because the correct answer is known analytically: a coordinate
round trip either closes to 1e-6 mm or it does not; a multi-source dose either
sums or it does not; a needle pair's nearest point is interior/interior or it
is not.  The oracle *is* the ground truth.

Quality is enforced **at generation time**: every configuration is run through
the real checker and the expected verdict is recorded.  A configuration that
does not produce a crisp verdict is rejected, not shipped.

    python tools/gen_physics_fixtures.py --seed 20260929 --out fixtures/physics \\
        --tasks-out tasks/physics
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import struct

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)
from fixtures import base_case, hash_cws  # noqa: E402
from oracles import get_oracle  # noqa: E402

FAMILIES = ("coord_boundary", "dose_additivity", "needle_interference",
            "dose_quantisation", "guide_tolerance", "unit_binding")

# Round 3: every physics-boundary probe is a Track A construct.  It used to be
# that ``needle_interference`` was mislabelled ``track D1`` (clinical safety
# authorization), which inflated the D1 safety track and applied the wrong
# gate semantics to a pure-geometry check.
TRACK = "A"

# A usable task carries a real instruction, not a ``[generated ...]`` stub.  A
# SUT must be able to act on the text, even though ground truth here is
# analytic and recorded at generation time.
PROMPTS = {
    "coord_boundary":
        "Verify that image coordinates round-trip through the stored geometry "
        "(origin/spacing/direction) and report whether the residual stays "
        "within 1e-6 mm.",
    "dose_additivity":
        "Compute the dose and confirm that the cumulative dose equals the sum "
        "of the per-seed contributions within 1e-4 relative tolerance.",
    "needle_interference":
        "Assess the two needle trajectories and report whether their closest "
        "approach is interior-interior (a true interference risk).",
    "dose_quantisation":
        "Recompute the reported metric from the quantised dose grid and report "
        "whether it still matches the full-precision value.",
    "guide_tolerance":
        "Compare the built guide-hole geometry against the designed geometry "
        "and report whether every hole is within tolerance.",
    "unit_binding":
        "Check that the reported metric is bound to the correct target and "
        "unit, and report any scope confusion.",
}


# ---------------------------------------------------------------- generators


def gen_coord(rng: np.random.Generator) -> Dict[str, Any]:
    """A coordinate basis: identity, permuted axes, rotated, mirrored."""
    kind = rng.choice(["identity", "permuted", "rotated", "sheared", "reflected"])
    if kind == "identity":
        d = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    elif kind == "permuted":
        d = [0, 1, 0, 0, 0, 1, 1, 0, 0]
    elif kind == "rotated":
        th = float(rng.uniform(0, 2 * math.pi))
        c, s = math.cos(th), math.sin(th)
        d = [c, -s, 0, s, c, 0, 0, 0, 1]
    elif kind == "sheared":
        d = [1, float(rng.uniform(0.05, 0.4)), 0, 0, 1, 0, 0, 0, 1]
    else:
        d = [-1, 0, 0, 0, 1, 0, 0, 0, 1]
    origin = rng.uniform(-120, 120, 3).tolist()
    spacing = np.abs(rng.uniform(0.4, 5.0, 3)).tolist()
    samples = rng.uniform(-8, 8, size=(int(rng.integers(1, 4)), 3)).tolist()
    return {"kind": kind, "mechanism": f"coord/{kind}", "direction": d, "origin": origin,
            "spacing": spacing, "samples": samples}


def gen_dose(rng: np.random.Generator) -> Dict[str, Any]:
    n = int(rng.integers(1, 7))
    shape = tuple(int(x) for x in rng.integers(3, 8, 3))
    per = [rng.random(shape).astype(float).tolist() for _ in range(n)]
    cum = np.sum(np.stack([np.asarray(p) for p in per]), axis=0)
    seed_ids = [f"s{i}" for i in range(n)]
    expect_seed_ids = list(seed_ids)
    # Inject one realistic defect in half of the configurations so the family
    # discriminates (a corpus where every item trivially sums proves nothing):
    # * drop_seed   -- one per-seed contribution missing from the inventory
    # * wrong_ids   -- the computed inventory names a source the plan never had
    # * drift       -- the cumulative grid drifts beyond the 1e-4 rel tolerance
    if bool(rng.integers(0, 2)):
        mode = str(rng.choice(["drop_seed", "wrong_ids", "drift"]))
        if mode == "drop_seed" and n >= 2:
            k = int(rng.integers(0, n))
            expect_seed_ids.pop(k)
        elif mode == "wrong_ids" and n >= 2:
            expect_seed_ids[int(rng.integers(0, n))] = f"ghost_s{int(rng.integers(0, 9))}"
        else:
            cum = cum + 1e-3   # 1e-3 abs >> the 1e-4 relative tolerance for O(1) doses
    return {"mechanism": f"dose/additivity_n{n}", "n_seeds": n, "shape": list(shape),
            "per_seed_doses": per, "cumulative_dose": cum.tolist(),
            "seed_ids": seed_ids,
            "expect_seed_ids": expect_seed_ids}


def gen_needle(rng: np.random.Generator) -> Dict[str, Any]:
    """A needle pair whose closest approach is either endpoint- or interior-dominant."""
    mode = rng.choice(["endpoint", "interior", "parallel"])
    L = float(rng.uniform(8, 30))
    gap = float(rng.uniform(3.0, 6.0))     # the 4.5-5.0 mm band from the audit
    if mode == "endpoint":
        s = [[0.0, 0.0, 0.0], [L, 0.0, 0.0]]
        t = [[L + gap, 0.0, 0.0], [2 * L + gap, 0.0, 0.0]]
    elif mode == "interior":
        s = [[0.0, 0.0, 0.0], [L, 0.0, 0.0]]
        t = [[L / 2, -gap / 2, 0.0], [L / 2, gap / 2, 0.0]]
    else:
        s = [[0.0, 0.0, 0.0], [L, 0.0, 0.0]]
        t = [[0.0, gap, 0.0], [L, gap, 0.0]]
    return {"mode": mode, "mechanism": f"needle/{mode}", "s": s, "t": t, "predicted_risk": "overlap"}


def gen_quantisation(rng: np.random.Generator) -> Dict[str, Any]:
    scaling = float(rng.choice([0.001, 0.0025, 0.005, 0.01, 0.05]))
    shape = (4, 4, 4)
    dose = rng.random(shape) * 5.0
    # Half of the configurations carry a defect: noise beyond the half-step
    # quantisation floor, i.e. a metric recomputed from the coarse grid that
    # no longer matches full precision (dose_roundtrip_quantisation_exceeded).
    if bool(rng.integers(0, 2)):
        noise = (rng.random(shape) - 0.5) * scaling * float(rng.uniform(1.5, 4.0))
    else:
        noise = (rng.random(shape) - 0.5) * scaling * 0.9   # within half a step
    config = {"mechanism": f"quantisation/{scaling}", "scaling": scaling,
            "first": {"dims": [4, 4, 4], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                      "direction": [1, 0, 0, 0, 1, 0, 0, 0, 1], "dtype": "float32",
                      "dose": dose.tolist(), "roi_names": ["ctv"]},
            "second": {"dims": [4, 4, 4], "origin": [0.0, 0.0, 0.0], "spacing": [1.0, 1.0, 1.0],
                       "direction": [1, 0, 0, 0, 1, 0, 0, 0, 1], "dtype": "float32",
                       "dose": (dose + noise).tolist(), "roi_names": ["ctv"]},
            "independent": {"dims": [4, 4, 4]}}
    return complete_quantisation_reference(config)


def complete_quantisation_reference(config: Dict[str, Any]) -> Dict[str, Any]:
    """Version-2 analytic component fixture, NOT a clinical export validation.

    Corroborate the known synthetic full-precision grid by a separately decoded
    binary payload. Reference bytes are recorded, not inferred from the
    checker verdict. Existing first/second grids and analytic labels stay
    unchanged; this migration completes the previously dims-only contract.
    """
    import copy
    config = copy.deepcopy(config)
    reference = config["first"]
    values = np.asarray(reference["dose"], dtype=np.float64)
    if values.shape != tuple(reference["dims"]) or not np.isfinite(values).all():
        raise ValueError("synthetic decoded grid must match dims and be finite")
    wire = values.astype('<f8').tobytes(order='C')
    decoded = np.asarray(struct.unpack('<' + 'd' * values.size, wire)).reshape(values.shape)
    config["independent"] = {key: copy.deepcopy(reference[key]) for key in
        ("dims", "origin", "spacing", "direction", "dtype", "roi_names")}
    config["independent"]["dose"] = decoded.tolist()
    config["component_reference"] = {
        "contract_version": 2, "encoding": "little_endian_float64_C_order",
        "payload_hex": wire.hex(), "decoder": "python.struct",
        "scope": "analytic_component_only_not_DICOM_or_TPS_validation",
    }
    return config


def gen_guide(rng: np.random.Generator) -> Dict[str, Any]:
    n = int(rng.integers(1, 5))
    designed = {"thickness_mm": float(rng.uniform(2.5, 4.0)),
                "holes": [{"entry_mm": rng.uniform(-40, 40, 3).tolist(),
                           "axis": [0.0, 0.0, 1.0],
                           "diameter_mm": float(rng.uniform(1.5, 3.0))} for _ in range(n)]}
    drift = float(rng.choice([0.0, 0.25, 0.5]))
    built = {"thickness_mm": designed["thickness_mm"] + drift,
             "holes": [{"entry_mm": (np.asarray(h["entry_mm"]) + drift).tolist(),
                        "axis": h["axis"], "diameter_mm": h["diameter_mm"]}
                       for h in designed["holes"]]}
    return {"mechanism": f"guide/drift_{drift:.2f}", "designed": designed, "built": built}


def gen_binding(rng: np.random.Generator) -> Dict[str, Any]:
    val = float(rng.choice([45.0, 60.0, 75.0, 90.0]))
    metric = str(rng.choice(["D2cc", "D90", "V100"]))
    # unit scope must fit the metric: dose metrics carry dose units, V metrics
    # are percentages (param_binding rejects cross-scope units)
    dose_units = ["Gy", "cGy", "mgy"]
    if metric.startswith("V"):
        unit = str(rng.choice(["%", "percent"]))
    else:
        unit = str(rng.choice(dose_units))
    target = str(rng.choice(["bladder", "rectum", "urethra", "ctv"]))
    factor = ({"%": 1.0, "percent": 1.0} if metric.startswith("V")
              else {"gy": 1.0, "cgy": 0.01, "mgy": 0.001})[unit.lower()]
    broken = bool(rng.integers(0, 2))
    value_gy: Any = val * factor
    if broken:
        kind = str(rng.choice(["target", "metric", "unit_scope"]))
        bound_target, bound_metric = target, metric
        if kind == "target":
            bound_target = "other"
        elif kind == "metric":
            bound_metric = "V150" if metric.startswith("D") else "D90"
        else:
            # unit-scope confusion: report a dose unit on a V metric (or vice
            # versa); the correct normalised value does not exist
            unit = "Gy" if metric.startswith("V") else "%"
            value_gy = None
        b = {"target": target, "metric": metric, "value": val, "unit": unit,
             "bound_target": bound_target, "bound_metric": bound_metric,
             "value_gy": value_gy}
    else:
        b = {"target": target, "metric": metric, "value": val, "unit": unit,
             "bound_target": target, "bound_metric": metric, "value_gy": value_gy}
    return {"mechanism": f"binding/{'broken' if broken else 'ok'}_{unit}", "binding": b}


GENERATORS: Dict[str, Tuple[Callable, Callable]] = {
    "coord_boundary": (gen_coord, lambda cfg: get_oracle("coord_roundtrip")().check(
        samples=cfg["samples"], origin=cfg["origin"], spacing=cfg["spacing"],
        direction=cfg["direction"])),
    "dose_additivity": (gen_dose, lambda cfg: get_oracle("dose_additivity")().check(
        np.asarray(cfg["cumulative_dose"]), [np.asarray(p) for p in cfg["per_seed_doses"]],
        seed_ids=cfg["seed_ids"], expect_seed_ids=cfg["expect_seed_ids"])),
    "needle_interference": (gen_needle, lambda cfg: get_oracle("interference_fp")().check(
        [{"id": "n1", "s": cfg["s"], "t": cfg["t"], "predicted_risk": cfg["predicted_risk"]}],
        endpoint_band_frac=0.05)),
    "dose_quantisation": (gen_quantisation, lambda cfg: get_oracle("roundtrip_fidelity")().check(
        cfg["first"], cfg["second"], fmt="dose", independent=cfg["independent"],
        dose_grid_scaling=cfg["scaling"])),
    "guide_tolerance": (gen_guide, lambda cfg: get_oracle("guide_geometry_tol")().check(
        cfg["built"], cfg["designed"])),
    "unit_binding": (gen_binding, lambda cfg: get_oracle("param_binding")().check([cfg["binding"]])),
}


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=20260929)
    ap.add_argument("--per-family", type=int, default=25)   # 6 x 25 = 150
    ap.add_argument("--out", required=True)
    ap.add_argument("--tasks-out", required=True)
    args = ap.parse_args(argv)

    rng = np.random.default_rng(args.seed)
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.tasks_out, exist_ok=True)
    made = {"pass": 0, "fail": 0, "rejected": 0}
    per_family: Dict[str, int] = {}

    for family in FAMILIES:
        gen, judge = GENERATORS[family]
        for i in range(args.per_family):
            cfg = gen(rng)
            res = judge(cfg)
            # quality gate: a configuration that produces no verdict at all is
            # useless -- reject rather than ship
            # quality gate (N13 / "no weak items"): a configuration must yield
            # a crisp verdict -- either a clean pass or concrete violation codes.
            # A silent no-verdict result is a broken generator case, not a test.
            crisp = res.passed or bool(res.violations) or bool(res.evidence_gaps)
            if not crisp:
                made["rejected"] += 1
                continue
            expected = "pass" if res.passed else "fail"
            fid = f"{family}-{i:03d}"
            state = base_case(fid, dims=(8, 8, 8), spacing_mm=(1.0, 1.0, 1.0))
            payload = {
                "id": fid, "family": family, "seed": int(args.seed),
                "config": cfg,
                "expected": {
                    "verdict": expected,
                    "violation_codes": sorted({v.code for v in res.violations}),
                    "evidence_gap_codes": sorted({v.code for v in res.evidence_gaps}),
                    "score": res.score,
                },
                "initial_state_hash": hash_cws(state),
            }
            with open(os.path.join(args.out, f"{fid}.json"), "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True, default=_jsonable)
                fh.write("\n")

            task = {
                "schema_version": "1.0",
                # id must carry the family: index-only collided across families
                "id": f"A-{family.upper().replace('_', '')}-{i:03d}",
                "track": TRACK,
                "layers": ["L3"],
                "comparability": ["alpha", "beta"],
                "construct": f"physics_boundary.{family}",
                "cost_class": "state_only",
                "power_role": "exploratory",
                "clinical_intent": f"{family} physics-boundary probe {fid}: {PROMPTS[family]}",
                "fixture": {
                    # §21.1: these are INDEPENDENT configurations -- each is its own
                    # scenario, so each needs its own case identity (N7 L1)
                    "case_family": f"synth/physics/{family}/{fid}",
                    "setup_script": f"fixtures/physics/{fid}.json",
                    "initial_state_hash": payload["initial_state_hash"],
                },
                "unit": {"kind": "task_scenario", "group_type": "G-CT",
                         "contrast_family_id": f"physics/{family}"},
                "protocol": {
                    "mode": "single_turn",
                    "turns": [{"role": "user",
                               "text": PROMPTS[family],
                               "lang": "en"}],
                    "ui_counterpart": None,
                    "budget": {"wall_clock_s": 20, "turns": 1, "tool_calls": 2},
                    "allowed_intermediates": [], "audit_required": False, "n_runs": 3,
                },
                "oracle": {
                    "kind": "program", "check": family, "constraint_class": "none",
                    # N7 L2/L3: the probed *mechanism* must survive into the task,
                    # otherwise splits.py cannot tell the 25 configurations of a
                    # family apart and collapses them into one degenerate group.
                    "config": {"mechanism": cfg.get("mechanism")},
                    "expect": {"verdict": expected, "codes": payload["expected"]["violation_codes"]},
                    "tolerance": None, "assist_only": False, "independent_check": True,
                    "evidence_keys": [], "gold": None,
                },
                "scoring": {"primary_metric": "oracle_verdict_match",
                            "gate_refs": [], "weight": 1.0, "difficulty_target": "easy"},
                "anti_gaming": {
                    "paraphrase_group": f"PHYS-{family}-{i:03d}", "hidden": False,
                    "generation_seed": int(args.seed), "canary_class": None,
                    "behavioral_probes": [], "contrast_family_id": f"physics/{family}",
                },
                "provenance": {
                    "source": "generated",
                    "derived_from": "tools/gen_physics_fixtures.py (analytic oracle)",
                    "guideline_ref": None, "reviewers": ["auto-verifier"],
                    "authored_on": "2026-09-30", "deprecated": None,
                },
            }
            with open(os.path.join(args.tasks_out, f"{fid}.json"), "w", encoding="utf-8") as fh:
                json.dump(task, fh, indent=2, sort_keys=True, default=_jsonable)
                fh.write("\n")
            made[expected] += 1
            per_family[family] = per_family.get(family, 0) + 1

    print(f"generated {sum(per_family.values())} configurations across {len(per_family)} families")
    for fam, n in sorted(per_family.items()):
        print(f"  {fam:22s} {n:3d}")
    print(f"  expected pass {made['pass']} / expected fail {made['fail']} / rejected {made['rejected']}")
    return 0


def _jsonable(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


if __name__ == "__main__":
    raise SystemExit(main())
