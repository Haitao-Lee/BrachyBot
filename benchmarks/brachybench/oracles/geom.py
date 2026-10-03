"""Geometry / shape checkers (DESIGN §8.3, tracks A2/A4/A6).

Implements: ``seed_geometry_fidelity``, ``dice_and_hd95``,
``hard_constraint``, ``acceptable_set_hit``, ``guide_geometry_tol``,
``interference_fp``, ``param_binding``.

Every oracle here is *deterministic* and needs no LLM judge: the answer is
either numerically computable (Dice, HD95, tolerances) or a predicate over a
frozen constraint table.  That is what makes them O1.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .base import ConstraintClass, Oracle, OracleResult, PartialStatus, Violation, register


# ---------------------------------------------------------------------------


@register
class SeedGeometryFidelity(Oracle):
    """§6.A3b check #3: seeds handed to the engine match ``cws.plan.seeds``.

    A dose computed on drifted coordinates is silently wrong, so this is a
    strict geometric identity check (N11 R-a: numerical reproducibility).
    """

    id = "seed_geometry_fidelity"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        engine_seeds: Sequence[Dict[str, Any]],
        cws_seeds: Sequence[Dict[str, Any]],
        *,
        tol_mm: float = 1e-4,
        at: Optional[str] = None,
    ) -> OracleResult:
        violations: List[Violation] = []
        a = {str(s.get("id")): s for s in engine_seeds or []}
        b = {str(s.get("id")): s for s in cws_seeds or []}
        if not a or not b:
            return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                evidence_gaps=[Violation("seed_geometry_empty", "nonempty seed observations required")])
        for label, seeds, mapped in (("engine", engine_seeds, a), ("cws", cws_seeds, b)):
            if len(seeds) != len(mapped) or any(s.get("id") is None for s in seeds):
                violations.append(Violation("seed_identity_invalid", f"{label}: missing or duplicate seed ID"))
        if set(a) != set(b):
            violations.append(
                Violation(
                    "seed_id_set_mismatch",
                    f"engine seeds {sorted(a)} != cws seeds {sorted(b)}",
                    at=at,
                )
            )
        worst = 0.0
        for sid in sorted(set(a) & set(b)):
            pa = np.asarray(a[sid].get("pos_mm", a[sid].get("pos")), dtype=np.float64).reshape(-1)
            pb = np.asarray(b[sid].get("pos_mm", b[sid].get("pos")), dtype=np.float64).reshape(-1)
            if pa.shape != (3,) or pb.shape != (3,) or not np.isfinite(pa).all() or not np.isfinite(pb).all():
                violations.append(
                    Violation("seed_pos_rank_mismatch", f"{sid}: {pa.shape} vs {pb.shape}", at=at)
                )
                continue
            err = float(np.max(np.abs(pa - pb))) if pa.size else 0.0
            worst = max(worst, err)
            if err > tol_mm:
                violations.append(
                    Violation(
                        "seed_position_drift",
                        f"{sid}: max |Δ| = {err:.6g} mm > tol {tol_mm}",
                        at=at,
                        detail={"err_mm": err},
                    )
                )
            for k in ("activity_u", "traj"):
                if a[sid].get(k) != b[sid].get(k):
                    violations.append(
                        Violation("seed_param_mismatch", f"{sid}.{k} differs", at=at)
                    )
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations,
            evidence={"worst_drift_mm": worst, "n_seeds": len(a), "tol_mm": tol_mm},
            constraint_class=self.constraint_class,
        )


@register
class DiceAndHd95(Oracle):
    """§8.3 ``dice_and_hd95``: segmentation agreement with a gold mask.

    Dice is volume overlap; HD95 is the 95th-percentile symmetric surface
    distance in mm.  Both are needed: Dice alone hides boundary errors on
    large structures, HD95 alone hides small-volume failures.
    """

    id = "dice_and_hd95"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        pred: Any,
        gold: Any,
        *,
        spacing_mm: Sequence[float] = (1.0, 1.0, 1.0),
        dice_min: float = 0.85,
        hd95_max_mm: Optional[float] = 4.0,
        at: Optional[str] = None,
    ) -> OracleResult:
        raw_p, raw_g = np.asarray(pred), np.asarray(gold)
        spacing = np.asarray(spacing_mm, dtype=float).reshape(-1)
        if (raw_p.size == 0 or raw_g.size == 0 or not np.isfinite(raw_p).all()
                or not np.isfinite(raw_g).all() or raw_p.ndim not in (2, 3)
                or spacing.size != raw_p.ndim or not np.isfinite(spacing).all() or np.any(spacing <= 0)
                or not set(np.unique(raw_p)).issubset({0, 1}) or not set(np.unique(raw_g)).issubset({0, 1})):
            return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                evidence_gaps=[Violation("mask_contract_invalid", "finite binary masks and rank-matched positive spacing required")])
        p, g = raw_p.astype(bool), raw_g.astype(bool)
        violations: List[Violation] = []
        if p.shape != g.shape:
            return OracleResult(
                oracle_id=self.id, passed=False, score=0.0,
                violations=[Violation("mask_shape_mismatch", f"{p.shape} vs {g.shape}", at=at)],
                constraint_class=self.constraint_class,
            )
        inter = float(np.count_nonzero(p & g))
        denom = float(np.count_nonzero(p) + np.count_nonzero(g))
        dice = (2.0 * inter / denom) if denom else 1.0
        if dice < dice_min:
            violations.append(
                Violation("dice_below_threshold", f"dice={dice:.4f} < {dice_min}", at=at,
                          detail={"dice": dice})
            )
        hd95 = self._hd95(p, g, np.asarray(spacing_mm, dtype=np.float64))
        if hd95_max_mm is not None and hd95 is None:
            return OracleResult(oracle_id=self.id, passed=False, score=float(dice), applicable=False,
                                evidence_gaps=[Violation("surface_distance_unavailable", "HD95 required but unavailable")])
        if hd95_max_mm is not None and hd95 is not None and hd95 > hd95_max_mm:
            violations.append(
                Violation("hd95_above_threshold", f"hd95={hd95:.4f} mm > {hd95_max_mm}", at=at,
                          detail={"hd95_mm": hd95})
            )
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=float(dice),
            violations=violations,
            evidence={"dice": dice, "hd95_mm": hd95, "dice_min": dice_min,
                      "hd95_max_mm": hd95_max_mm},
            constraint_class=self.constraint_class,
        )

    @staticmethod
    def _hd95(p: np.ndarray, g: np.ndarray, spacing: np.ndarray) -> Optional[float]:
        if not np.any(p) or not np.any(g):
            return 0.0 if not np.any(p) and not np.any(g) else float("inf")
        try:
            from scipy import ndimage  # optional; degrade to coarse estimate
        except Exception:  # pragma: no cover
            return None
        structure = ndimage.generate_binary_structure(p.ndim, 1)
        surf_p = p ^ ndimage.binary_erosion(p, structure=structure, border_value=0)
        surf_g = g ^ ndimage.binary_erosion(g, structure=structure, border_value=0)
        dt_p = ndimage.distance_transform_edt(~surf_p, sampling=spacing)
        dt_g = ndimage.distance_transform_edt(~surf_g, sampling=spacing)
        d_pg, d_gp = dt_g[surf_p], dt_p[surf_g]
        all_d = np.concatenate([d_pg, d_gp])
        return float(np.percentile(all_d, 95))


@register
class HardConstraint(Oracle):
    """§6.A4 / §8.3 ``hard_constraint``: the non-negotiable plan limits.

    These are *objective* limits from the frozen constraint table (DESIGN
    §6.A4: "CTV coverage, OAR hard limits, needle spacing, endpoint safety").
    Whether a plan is *acceptable* is a separate question (see
    :class:`AcceptableSetHit`).
    """

    id = "hard_constraint"
    constraint_class = ConstraintClass.POSTCONDITION

    def check(
        self,
        plan: Dict[str, Any],
        *,
        limits: Optional[Dict[str, Any]] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        lim = {
            "min_spacing_mm": 5.0,
            "min_endpoint_clearance_mm": 2.0,
            "min_coverage": 0.90,
            "oar_limits": {},          # {"bladder": {"metric": "D2cc", "limit": 75.0}}
            "max_seeds": 200,
            **(limits or {}),
        }
        violations: List[Violation] = []
        seeds = plan.get("seeds") or []
        trajs = plan.get("trajectories") or []
        gaps: List[Violation] = []
        if not seeds or not trajs:
            gaps.append(Violation("plan_geometry_missing", "nonempty seeds and trajectories required"))
        for t in trajs:
            entry = np.asarray(t.get("entry"), dtype=float).reshape(-1)
            if entry.size != 3 or not np.isfinite(entry).all():
                gaps.append(Violation("trajectory_entry_invalid", f"{t.get('id')}: finite xyz entry required"))

        if len(seeds) > lim["max_seeds"]:
            violations.append(Violation(
                "seed_count_exceeded", f"{len(seeds)} > {lim['max_seeds']}", at=at))

        # needle spacing: pairwise distance between trajectory entries
        entries = [np.asarray(t.get("entry"), dtype=np.float64) for t in trajs
                   if t.get("entry") is not None and np.asarray(t.get("entry")).size == 3
                   and np.isfinite(np.asarray(t.get("entry"), dtype=float)).all()]
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                d = float(np.linalg.norm(entries[i] - entries[j]))
                if d < lim["min_spacing_mm"]:
                    violations.append(Violation(
                        "needle_spacing_violation",
                        f"traj pair ({i},{j}) spacing {d:.3f} mm < {lim['min_spacing_mm']}",
                        at=at, detail={"distance_mm": d}))

        for t in trajs:
            c = t.get("clearance_mm")
            if c is None or not np.isfinite(float(c)):
                gaps.append(Violation("clearance_missing", f"{t.get('id')}: verified finite clearance required"))
            if c is not None and float(c) < lim["min_endpoint_clearance_mm"]:
                violations.append(Violation(
                    "endpoint_clearance_violation",
                    f"{t.get('id')} clearance {c:.3f} mm < {lim['min_endpoint_clearance_mm']}",
                    at=at, detail={"clearance_mm": c}))

        cov = (plan.get("coverage") or {}).get("ctv")
        if cov is None or not np.isfinite(float(cov)):
            gaps.append(Violation("coverage_missing", "finite CTV coverage required"))
        if cov is not None and float(cov) < lim["min_coverage"]:
            violations.append(Violation(
                "coverage_below_threshold",
                f"CTV coverage {cov:.4f} < {lim['min_coverage']}", at=at))

        for name, rule in (lim.get("oar_limits") or {}).items():
            val = (plan.get("oar_metrics") or {}).get(name, {}).get(rule.get("metric"))
            if val is None or not np.isfinite(float(val)):
                gaps.append(Violation("oar_metric_missing", f"{name}.{rule.get('metric')}: finite measured value required"))
            if val is not None and rule.get("limit") is not None and float(val) > float(rule["limit"]):
                violations.append(Violation(
                    "oar_limit_violation",
                    f"{name}.{rule['metric']} = {val} > limit {rule['limit']}",
                    at=at, detail={"oar": name, "value": val, "limit": rule["limit"]}))

        passed = not violations and not gaps
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations,
            evidence={"limits": lim, "n_seeds": len(seeds), "n_trajectories": len(trajs)},
            evidence_gaps=gaps,
            constraint_class=self.constraint_class,
        )


@register
class AcceptableSetHit(Oracle):
    """§6.A4 ``acceptable_set_hit`` = O1 hard constraints **and** O4 family
    membership (M12: explicitly ``O1 + O4``, never pure O1).

    Plan quality is *set-valued*: many different plans can be equally good.
    Scoring distance to a single gold plan is forbidden (DESIGN §6.A4).
    """

    id = "acceptable_set_hit"
    constraint_class = ConstraintClass.POSTCONDITION

    def check(
        self,
        plan: Dict[str, Any],
        *,
        acceptable_families: Sequence[Dict[str, Any]],
        expert_membership: Optional[Dict[str, Any]] = None,
        limits: Optional[Dict[str, Any]] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        # layer 1: O1 hard constraints must all hold
        hard = HardConstraint().check(plan, limits=limits, at=at)
        if not hard.passed:
            return OracleResult(
                oracle_id=self.id, passed=False, score=0.0,
                violations=hard.violations,
                evidence_gaps=hard.evidence_gaps,
                evidence={"layer": "O1 hard constraints", "hit_family": None},
                constraint_class=self.constraint_class,
                notes="O1 layer failed; O4 family membership not reached (M12)",
            )
        # layer 2: O4 family membership -- either supplied as a precomputed
        # expert verdict, or derived from family predicates
        hit = None
        if expert_membership is not None:
            fid = expert_membership.get("family_id")
            hit = fid if expert_membership.get("acceptable") else None
            if hit is None:
                return OracleResult(
                    oracle_id=self.id, passed=False, score=0.0,
                    violations=[Violation(
                        "outside_acceptable_set",
                        "expert adjudication: plan not in any acceptable family",
                        at=at, detail=expert_membership)],
                    evidence={"layer": "O4 expert", "hit_family": None,
                              "kappa": expert_membership.get("kappa"),
                              "ac1": expert_membership.get("ac1")},
                    constraint_class=self.constraint_class,
                    notes="O1 passed but O4 rejected (M12 composite)",
                )
        else:
            for fam in acceptable_families or []:
                pred = fam.get("predicate")
                if callable(pred) and bool(pred(plan)):
                    hit = fam.get("id")
                    break
            if hit is None:
                return OracleResult(
                    oracle_id=self.id, passed=False, score=0.0,
                    violations=[Violation(
                        "outside_acceptable_set",
                        f"plan matches none of {len(acceptable_families or [])} acceptable families",
                        at=at)],
                    evidence={"layer": "family predicates", "hit_family": None},
                    constraint_class=self.constraint_class,
                )
        return OracleResult(
            oracle_id=self.id, passed=True, score=1.0,
            evidence={"layer": "O1+O4", "hit_family": hit},
            constraint_class=self.constraint_class,
            notes="set-valued quality: hit an acceptable family (never distance-to-gold)",
        )


@register
class GuideGeometryTolerance(Oracle):
    """§6.A6 ``guide_geometry_tol``: hole position / axis / diameter / wall.

    Manufacturing tolerances, not clinical aesthetics.
    """

    id = "guide_geometry_tol"
    constraint_class = ConstraintClass.POSTCONDITION

    def check(
        self,
        built: Dict[str, Any],
        designed: Dict[str, Any],
        *,
        pos_tol_mm: float = 0.3,
        angle_tol_deg: float = 2.0,
        thickness_tol_mm: float = 0.2,
        diameter_tol_mm: float = 0.1,
        at: Optional[str] = None,
    ) -> OracleResult:
        violations: List[Violation] = []
        bh, dh = built.get("holes") or [], designed.get("holes") or []
        if not bh or not dh:
            return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                evidence_gaps=[Violation("guide_geometry_missing", "nonempty hole geometry required")])
        for hole in [*bh, *dh]:
            for key in ("entry_mm", "axis"):
                arr = np.asarray(hole.get(key), dtype=float).reshape(-1)
                if arr.size != 3 or not np.isfinite(arr).all() or (key == "axis" and np.linalg.norm(arr) <= 1e-12):
                    return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                        evidence_gaps=[Violation("hole_geometry_invalid", "finite entry and nonzero axis required")])
            if hole.get("diameter_mm") is not None and (not math.isfinite(float(hole["diameter_mm"])) or float(hole["diameter_mm"]) <= 0):
                violations.append(Violation("hole_diameter_invalid", "positive finite diameter required"))
        for guide in (built, designed):
            thickness = guide.get("thickness_mm")
            if thickness is not None and (not math.isfinite(float(thickness)) or float(thickness) <= 0):
                violations.append(Violation("guide_thickness_invalid", "positive finite thickness required"))
        if all(h.get("id") is not None for h in [*bh, *dh]):
            bm, dm = {str(h["id"]): h for h in bh}, {str(h["id"]): h for h in dh}
            if len(bm) != len(bh) or len(dm) != len(dh) or set(bm) != set(dm):
                violations.append(Violation("hole_identity_invalid", "duplicate or mismatched hole identities"))
            bh, dh = [bm[k] for k in sorted(bm.keys() & dm.keys())], [dm[k] for k in sorted(bm.keys() & dm.keys())]
        elif len(bh) == len(dh):
            from scipy.optimize import linear_sum_assignment
            costs = np.linalg.norm(np.asarray([h["entry_mm"] for h in bh])[:, None, :] -
                                   np.asarray([h["entry_mm"] for h in dh])[None, :, :], axis=2)
            rows, cols = linear_sum_assignment(costs)
            bh, dh = [bh[i] for i in rows], [dh[j] for j in cols]
        if len(bh) != len(dh):
            violations.append(Violation(
                "hole_count_mismatch", f"built {len(bh)} vs designed {len(dh)}", at=at))
        worst = {"pos": 0.0, "angle": 0.0, "thickness": 0.0, "diameter": 0.0}
        for i, (b, d) in enumerate(zip(bh, dh)):
            pb = np.asarray(b.get("entry_mm"), dtype=np.float64).reshape(-1)
            pd = np.asarray(d.get("entry_mm"), dtype=np.float64).reshape(-1)
            e = float(np.max(np.abs(pb - pd))) if pb.shape == pd.shape else float("inf")
            worst["pos"] = max(worst["pos"], e)
            if e > pos_tol_mm:
                violations.append(Violation(
                    "hole_position_out_of_tol", f"hole {i}: {e:.4f} mm > {pos_tol_mm}", at=at))
            ang = self._angle_deg(b.get("axis"), d.get("axis"))
            worst["angle"] = max(worst["angle"], ang)
            if ang > angle_tol_deg:
                violations.append(Violation(
                    "hole_axis_out_of_tol", f"hole {i}: {ang:.3f}° > {angle_tol_deg}", at=at))
            if b.get("diameter_mm") is not None and d.get("diameter_mm") is not None:
                e = abs(float(b["diameter_mm"]) - float(d["diameter_mm"]))
                worst["diameter"] = max(worst["diameter"], e)
                if e > diameter_tol_mm:
                    violations.append(Violation(
                        "hole_diameter_out_of_tol", f"hole {i}: {e:.4f} mm > {diameter_tol_mm}", at=at))
        if built.get("thickness_mm") is not None and designed.get("thickness_mm") is not None:
            e = abs(float(built["thickness_mm"]) - float(designed["thickness_mm"]))
            worst["thickness"] = e
            if e > thickness_tol_mm:
                violations.append(Violation(
                    "wall_thickness_out_of_tol", f"{e:.4f} mm > {thickness_tol_mm}", at=at))
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations,
            evidence={"worst": worst,
                      "tols_mm_deg": [pos_tol_mm, angle_tol_deg, thickness_tol_mm, diameter_tol_mm]},
            constraint_class=self.constraint_class,
        )

    @staticmethod
    def _angle_deg(a, b) -> float:
        va = np.asarray(a, dtype=np.float64).reshape(-1)
        vb = np.asarray(b, dtype=np.float64).reshape(-1)
        if va.size != 3 or vb.size != 3:
            return float("inf")
        na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
        if na <= 1e-12 or nb <= 1e-12:
            return float("inf")
        c = float(np.clip(abs(np.dot(va, vb)) / (na * nb), -1.0, 1.0))
        return float(math.degrees(math.acos(c)))


@register
class InterferenceFalsePositive(Oracle):
    """Compare classifications against segment/capsule distances.

    Endpoint proximity is neither proof nor disproof of physical collision.
    Radii and the required surface clearance define the geometry contract.
    Omitted radii mean zero-width segments, NOT a clinically valid seed model.
    """

    id = "interference_fp"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        predictions: Sequence[Dict[str, Any]],
        *,
        endpoint_band_frac: float = 0.05,
        geometry: Optional[Dict[str, Dict[str, Any]]] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``predictions`` items::

            {"id": .., "s": [P0, P1], "t": [Q0, Q1], "predicted_risk": "overlap|warning|none"}
        """
        violations: List[Violation] = []
        fp = fn = tp = tn = 0
        for pr in predictions or []:
            if geometry is not None:
                reference = geometry.get(str(pr.get("id")))
                if not reference:
                    return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                        evidence_gaps=[Violation("segment_reference_missing", "private physical reference required for each prediction")])
                pr = {"id": pr.get("id"), "predicted_risk": pr.get("predicted_risk"),
                      **{k: v for k, v in reference.items() if k in ("s", "t", "radius_s_mm", "radius_t_mm", "minimum_surface_gap_mm")}}
            s0 = np.asarray(pr["s"][0], dtype=np.float64)
            s1 = np.asarray(pr["s"][1], dtype=np.float64)
            t0 = np.asarray(pr["t"][0], dtype=np.float64)
            t1 = np.asarray(pr["t"][1], dtype=np.float64)
            if any(a.shape != (3,) for a in (s0, s1, t0, t1)) or not np.isfinite(np.asarray([s0, s1, t0, t1])).all():
                return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                    evidence_gaps=[Violation("segment_invalid", "finite segment endpoints required")])
            us, vs, _, _ = self._closest(s0, s1, t0, t1)
            distance = float(np.linalg.norm(self._at(s0, s1, us) - self._at(t0, t1, vs)))
            radius = float(pr.get("radius_s_mm", 0.0)) + float(pr.get("radius_t_mm", 0.0))
            clearance = float(pr.get("minimum_surface_gap_mm", 0.0))
            if not all(math.isfinite(v) and v >= 0 for v in
                       (float(pr.get("radius_s_mm", 0)), float(pr.get("radius_t_mm", 0)), clearance)):
                return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                    evidence_gaps=[Violation("capsule_policy_invalid", "finite nonnegative radii and clearance required")])
            truth_overlap = distance < radius if radius > 0 else distance < 1e-9
            truth_any = truth_overlap or distance < radius + clearance
            pred = pr.get("predicted_risk") or "none"
            if pred not in ("none", "warning", "overlap"):
                violations.append(Violation("interference_prediction_invalid", f"unrecognised predicted risk {pred!r}"))
                fp += 1
                continue
            pred_overlap = pred == "overlap"
            pred_any = pred in ("overlap", "warning")
            if pred_overlap and not truth_overlap:
                fp += 1
                violations.append(Violation(
                    "interference_false_positive",
                    f"{pr.get('id')}: predicted overlap but nearest pair is "
                    f"(u={us:.3f}, v={vs:.3f}); distance={distance:.4g} mm, radius sum={radius:.4g} mm",
                    at=at, detail={"u": float(us), "v": float(vs)}))
            elif pred_any and not truth_any and not truth_overlap:
                fp += 1
                violations.append(Violation(
                    "interference_false_positive",
                    f"{pr.get('id')}: predicted {pred} with an endpoint-dominant contact",
                    at=at, detail={"u": float(us), "v": float(vs)}))
            elif truth_any and not pred_any:
                fn += 1
                violations.append(Violation(
                    "interference_false_negative",
                    f"{pr.get('id')}: missed an interior contact (u={us:.3f}, v={vs:.3f})",
                    at=at))
            elif pred_overlap and truth_overlap or pred_any and truth_any:
                tp += 1
            else:
                tn += 1
        n = fp + fn + tp + tn
        passed = (fp == 0 and fn == 0 and n > 0)
        return OracleResult(
            oracle_id=self.id, passed=passed, score=(tp + tn) / n if n else 1.0,
            violations=violations,
            evidence={"tp": tp, "tn": tn, "fp": fp, "fn": fn,
                      "false_positive_rate": fp / n if n else 0.0,
                      "endpoint_band_frac": endpoint_band_frac},
            constraint_class=self.constraint_class,
            notes="distance-based segment/capsule contract; not clinical clearance certification",
        )

    @staticmethod
    def _at(a, b, u):  # noqa: A003
        return a + u * (b - a)

    @staticmethod
    def _closest(s0, s1, t0, t1) -> Tuple[float, float, bool, bool]:
        """Closest points between segments s0-s1 and t0-t1 -> (u, v)."""
        d1, d2 = s1 - s0, t1 - t0
        r = s0 - t0
        a = float(np.dot(d1, d1))
        e = float(np.dot(d2, d2))
        f = float(np.dot(d2, r))
        c = float(np.dot(d1, r))
        b = float(np.dot(d1, d2))
        den = a * e - b * b
        if a <= 1e-12:
            v = float(np.clip(f / e, 0, 1)) if e > 1e-12 else 0.0
            return 0.0, v, True, v in (0.0, 1.0)
        if e <= 1e-12:
            u = float(np.clip(-c / a, 0, 1))
            return u, 0.0, u in (0.0, 1.0), True
        if den > 1e-12:
            u = float(np.clip((b * f - c * e) / den, 0.0, 1.0))
        else:  # parallel
            u = 0.0
        v = (b * u + f) / e if e > 1e-12 else 0.0
        if v < 0.0:
            v = 0.0
            u = float(np.clip(-c / a, 0.0, 1.0)) if a > 1e-12 else 0.0
        elif v > 1.0:
            v = 1.0
            u = float(np.clip((b - c) / a, 0.0, 1.0)) if a > 1e-12 else 0.0
        return u, v, u in (0.0, 1.0), v in (0.0, 1.0)


@register
class ParamBinding(Oracle):
    """§6.A9 ``param_binding`` + ``unit_conversion`` + ``metric_scope``.

    Multi-target requests must bind each value to its own target, in the order
    the user wrote them (R04), units must convert, and D90 / V100 / D2cc must
    never be conflated.
    """

    id = "param_binding"
    constraint_class = ConstraintClass.NONE

    # dose metrics normalise to Gy; Gy(RBE) is the standard clinical spelling
    # for the same physical quantity (constant factor 1.0).
    UNIT_TO_GY = {"gy": 1.0, "cgy": 0.01, "mgy": 0.001,
                  "gy(rbe)": 1.0, "gyrbe": 1.0, "gy_rbe": 1.0}
    # V-metrics (V100/V150/V200) are percentages of the structure volume; a
    # dose unit on a V metric is a scope confusion and must fail (P2 review).
    UNIT_VOLUME = {"%": 1.0, "percent": 1.0}
    METRIC_SCOPE = {"D90": "D", "D100": "D", "D2cc": "D", "V100": "V", "V150": "V", "V200": "V"}

    def check(
        self,
        bindings: Sequence[Dict[str, Any]],
        *,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``bindings`` items::

            {"target": "bladder", "metric": "D2cc", "value": 75, "unit": "Gy",
             "bound_target": "bladder", "bound_metric": "D2cc", "value_gy": 75}
        """
        violations: List[Violation] = []
        seen: Dict[str, List[str]] = {}
        for b in bindings or []:
            tgt, met = b.get("target"), b.get("metric")
            if b.get("bound_target") != tgt:
                violations.append(Violation(
                    "param_bound_to_wrong_target",
                    f"{tgt}.{met} bound to {b.get('bound_target')!r}", at=at))
            if b.get("bound_metric") != met:
                violations.append(Violation(
                    "metric_scope_confusion",
                    f"{tgt}.{met} bound as {b.get('bound_metric')!r}", at=at))
            # unit conversion -- dose metrics normalise to Gy; V metrics are
            # percentages.  A unit that does not fit the metric scope is a
            # binding error, not a convertible quantity.
            u = str(b.get("unit", "Gy")).strip().lower().replace(" ", "")
            scope = self.METRIC_SCOPE.get(str(met), "D")
            factor = (self.UNIT_VOLUME if scope == "V" else self.UNIT_TO_GY).get(u)
            want = float(b.get("value", 0.0)) * factor if factor is not None else float("nan")
            got = b.get("value_gy")
            if got is None or not math.isfinite(want) or not math.isfinite(float(got)) or abs(float(got) - want) > 1e-9:
                violations.append(Violation(
                    "unit_conversion_error",
                    f"{tgt}.{met}: {b.get('value')} {b.get('unit')} -> {got} Gy "
                    f"(expected {want})", at=at))
            # word-value ordering: repeated targets must keep written order
            seen.setdefault(str(tgt), []).append(str(met))
        n = len(bindings or [])
        if not n:
            return OracleResult(oracle_id=self.id, passed=False, score=0, applicable=False,
                                evidence_gaps=[Violation("binding_missing", "empty bindings do not prove correctness")])
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed,
            score=1.0 if passed else max(0.0, 1 - len(violations) / max(n, 1)),
            violations=violations,
            evidence={"n_bindings": n, "per_target": seen},
            constraint_class=self.constraint_class,
        )
