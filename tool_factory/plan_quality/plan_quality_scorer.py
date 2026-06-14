"""
Plan Quality Scorer Tool
=======================
Computes overall plan quality score (0-100) based on clinical constraints.
Used for plan comparison and acceptance criteria.

Uses :mod:`clinical_standards` as the single source of truth for
per-organ pass criteria (D90, V100, V150, V200) and OAR dose limits
(GEC-ESTRO / ABS / AAPM TG-229).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
from typing import Dict, List, Optional
import numpy as np

from .clinical_standards import (
    get_target_standard,
    get_oar_standard,
    composite_score,
    should_replan,
    WEIGHTS,
)


class PlanQualityScorerTool(BaseTool):
    """
    Tool for computing overall brachytherapy plan quality score.

    Evaluates plan quality based on:
    - Target coverage (V100, V150, V200)
    - Dose homogeneity (D90, D50)
    - OAR sparing (dose constraints)
    - Overall score (0-100)
    """

    @property
    def name(self) -> str:
        return "plan_quality_scorer"

    @property
    def description(self) -> str:
        return (
            "Compute overall brachytherapy plan quality score (0-100). "
            "Based on target coverage, dose homogeneity, and OAR constraints. "
            "Input: dose metrics dict or individual Vx/Dx/OAR metrics. "
            "Output: Score breakdown and pass/fail recommendation."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "v100": {"type": "number", "description": "Target coverage fraction (0-1)"},
                "v150": {"type": "number", "description": "Over-dose fraction (0-1)"},
                "v200": {"type": "number", "description": "Severe over-dose fraction (0-1)"},
                "d90": {"type": "number", "description": "Dose covering 90% of target in Gy"},
                "prescribed_dose": {"type": "number", "description": "Prescribed dose in Gy"},
                "organ": {
                    "type": "string",
                    "description": (
                        "Target organ / tumor type. Picks the corresponding clinical "
                        "pass criteria from clinical_standards (prostate / pancreas / "
                        "liver / lung / kidney / colon / head_neck). Defaults to "
                        "generic ABS / GEC-ESTRO values."
                    ),
                    "default": "default",
                },
                "oar_metrics": {
                    "type": "object",
                    "description": "Dict of OAR name -> {max_dose, d2cc, mean_dose}",
                },
                "oar_constraints": {
                    "type": "object",
                    "description": (
                        "Custom constraints dict (overrides per-organ standards). "
                        "Each OAR entry is a dict of {max_dose, d2cc} in Gy."
                    ),
                },
                "auto_replan_threshold": {
                    "type": "number",
                    "description": (
                        "Composite-score threshold below which the plan is flagged "
                        "for automatic replanning. Default 60."
                    ),
                    "default": 60.0,
                },
            },
            "required": ["v100", "d90", "prescribed_dose"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "overall_score": {"type": "number", "description": "Composite weighted score 0-100"},
                "coverage_score": {"type": "number", "description": "Coverage sub-score 0-100 (weight 0.40)"},
                "homogeneity_score": {"type": "number", "description": "Homogeneity sub-score 0-100 (weight 0.20)"},
                "oar_score": {"type": "number", "description": "OAR sparing sub-score 0-100 (weight 0.30)"},
                "conformance_score": {"type": "number", "description": "Hot-spot control sub-score 0-100 (weight 0.10)"},
                "acceptability": {"type": "string", "description": "'ACCEPTABLE', 'BORDERLINE', or 'UNACCEPTABLE'"},
                "violations": {"type": "array", "description": "List of constraint violations"},
                "needs_replan": {"type": "boolean", "description": "True if composite < threshold or >1 hard violation"},
                "organ": {"type": "string", "description": "Organ the standards were drawn from"},
                "weights": {"type": "object", "description": "Composite-score weights used"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        v100 = kwargs.get("v100", 0)
        v150 = kwargs.get("v150", 0)
        v200 = kwargs.get("v200", 0)
        d90 = kwargs.get("d90", 0)
        prescribed_dose = kwargs["prescribed_dose"]
        organ = (kwargs.get("organ") or "default").lower()
        oar_metrics = kwargs.get("oar_metrics", {})
        oar_constraints = kwargs.get("oar_constraints", {})
        replan_threshold = float(kwargs.get("auto_replan_threshold", 60.0))

        # Look up the per-organ clinical standard; merge with any caller overrides
        target_std = get_target_standard(organ)
        oar_std = get_oar_standard(organ)
        if oar_constraints:
            for k, v in oar_constraints.items():
                oar_std.setdefault(k.lower(), {}).update(v)

        coverage_score, coverage_notes = self._score_coverage(v100, v150, v200, target_std)
        homogeneity_score = self._score_homogeneity(d90, prescribed_dose, target_std)
        oar_score, violations = self._score_oars(oar_metrics, oar_std)
        conformance_score = self._score_conformance(v150, v200, target_std)

        overall = composite_score(coverage_score, homogeneity_score, oar_score, conformance_score)

        if overall >= 80 and len(violations) == 0:
            acceptability = "ACCEPTABLE"
        elif overall >= replan_threshold and len(violations) <= 1:
            acceptability = "BORDERLINE"
        else:
            acceptability = "UNACCEPTABLE"

        needs_replan = should_replan(overall, len(violations)) or acceptability == "UNACCEPTABLE"

        return ToolResult(
            success=True,
            data={
                "overall_score": round(overall, 2),
                "coverage_score": round(coverage_score, 2),
                "homogeneity_score": round(homogeneity_score, 2),
                "oar_score": round(oar_score, 2),
                "conformance_score": round(conformance_score, 2),
                "acceptability": acceptability,
                "violations": violations,
                "needs_replan": needs_replan,
                "organ": organ,
                "weights": dict(WEIGHTS),
            },
            message=(
                f"Plan quality score: {overall:.1f}/100 ({acceptability}) "
                f"organ={organ}, needs_replan={needs_replan}"
            ),
            metadata={
                "overall_score": round(overall, 2),
                "coverage_score": round(coverage_score, 2),
                "homogeneity_score": round(homogeneity_score, 2),
                "oar_score": round(oar_score, 2),
                "conformance_score": round(conformance_score, 2),
                "acceptability": acceptability,
                "violations": violations,
                "needs_replan": needs_replan,
                "organ": organ,
                "weights": dict(WEIGHTS),
                "target_standard": target_std,
                "coverage_notes": coverage_notes,
            },
        )

    def _score_coverage(self, v100, v150, v200, target_std) -> tuple:
        """Score target coverage against the per-organ standard.

        Returns (score 0-100, notes list).
        """
        v100_min = target_std.get("v100_min", 0.90)
        score = 0.0
        notes = []

        # V100 is the dominant coverage metric; full credit at 100%+ of standard
        if v100 >= v100_min:
            score += 70
        elif v100 >= v100_min - 0.05:
            score += 55
            notes.append(f"V100={v100:.1%} slightly below {v100_min:.0%}")
        elif v100 >= v100_min - 0.10:
            score += 35
            notes.append(f"V100={v100:.1%} notably below {v100_min:.0%}")
        else:
            score += 10
            notes.append(f"V100={v100:.1%} severely below {v100_min:.0%}")

        # V100 above 100% is fine (over-coverage), no penalty
        # Partial credit if V150 is within bounds
        v150_max = target_std.get("v150_max", 0.50)
        if v150 <= v150_max:
            score += 20
        elif v150 <= v150_max + 0.10:
            score += 10
            notes.append(f"V150={v150:.1%} above {v150_max:.0%}")
        else:
            score += 0
            notes.append(f"V150={v150:.1%} much above {v150_max:.0%}")

        # V200 severe hot-spot penalty
        v200_max = target_std.get("v200_max", 0.20)
        if v200 <= v200_max:
            score += 10
        else:
            notes.append(f"V200={v200:.1%} above {v200_max:.0%}")

        return min(100.0, score), notes

    def _score_homogeneity(self, d90, prescribed_dose, target_std) -> float:
        """Score dose homogeneity against per-organ D90 standard (0-100)."""
        if prescribed_dose <= 0:
            return 0.0
        d90_min_pct = target_std.get("d90_min_pct", 1.0)
        ratio = d90 / prescribed_dose
        if ratio >= d90_min_pct:
            return 100.0
        elif ratio >= d90_min_pct - 0.05:
            return 80.0
        elif ratio >= d90_min_pct - 0.10:
            return 55.0
        elif ratio >= d90_min_pct - 0.20:
            return 25.0
        return 0.0

    def _score_oars(self, oar_metrics, oar_constraints) -> tuple:
        """Score OAR sparing against per-organ constraints (0-100).

        Starts at 100 and applies per-OAR penalties based on how badly
        each constraint is violated.
        """
        score = 100.0
        violations = []

        for oar_name, metrics in oar_metrics.items():
            oar_name_l = oar_name.lower()
            constraints = oar_constraints.get(oar_name_l, {})
            if not constraints:
                # No standard for this OAR — be lenient (no penalty)
                continue

            for constraint_type, limit in constraints.items():
                if constraint_type not in metrics:
                    continue
                actual = float(metrics[constraint_type])
                if actual > limit:
                    excess_pct = (actual - limit) / limit * 100.0
                    # Penalty grows linearly with excess, capped at 30 per OAR
                    penalty = min(30.0, excess_pct * 0.5)
                    score -= penalty
                    violations.append({
                        "oar": oar_name,
                        "constraint_type": constraint_type,
                        "actual": actual,
                        "limit": float(limit),
                        "excess_pct": float(excess_pct),
                        "penalty": round(penalty, 2),
                    })

        return max(0.0, score), violations

    def _score_conformance(self, v150, v200, target_std) -> float:
        """Score hot-spot control (V150/V200) — 0-100."""
        v150_max = target_std.get("v150_max", 0.50)
        v200_max = target_std.get("v200_max", 0.20)

        score = 0.0
        if v150 <= v150_max:
            score += 60
        elif v150 <= v150_max + 0.10:
            score += 30
        if v200 <= v200_max:
            score += 40
        elif v200 <= v200_max + 0.05:
            score += 20
        return min(100.0, score)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Plan Quality Scorer (weighted composite, per-organ standards)")
    parser.add_argument("--v100", type=float, required=True)
    parser.add_argument("--v150", type=float, default=0)
    parser.add_argument("--v200", type=float, default=0)
    parser.add_argument("--d90", type=float, required=True)
    parser.add_argument("--prescribed_dose", type=float, required=True)
    parser.add_argument("--organ", default="default", help="Target organ (prostate/pancreas/liver/lung/kidney/colon/head_neck)")
    args = parser.parse_args()

    tool = PlanQualityScorerTool()
    result = tool._execute(
        v100=args.v100, v150=args.v150, v200=args.v200,
        d90=args.d90, prescribed_dose=args.prescribed_dose,
        organ=args.organ,
    )
    print(result.message)
    print(f"Overall Score: {result.metadata['overall_score']:.1f}/100")
    print(f"Acceptability: {result.metadata['acceptability']}")
    print(f"Needs Replan: {result.metadata['needs_replan']}")
    if result.metadata['violations']:
        print(f"Violations ({len(result.metadata['violations'])}):")
        for v in result.metadata['violations']:
            print(f"  - {v['oar']} {v['constraint_type']} = {v['actual']:.2f} (limit {v['limit']:.2f})")


if __name__ == "__main__":
    main()