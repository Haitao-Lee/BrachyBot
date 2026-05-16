"""
Plan Quality Scorer Tool
=======================
Computes overall plan quality score (0-100) based on clinical constraints.
Used for plan comparison and acceptance criteria.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
from typing import Dict, List, Optional
import numpy as np


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
                "oar_metrics": {
                    "type": "object",
                    "description": "Dict of OAR name -> {max_dose, mean_dose}",
                },
                "oar_constraints": {
                    "type": "object",
                    "description": "Dict of OAR name -> max_allowed_dose in Gy",
                },
            },
            "required": ["v100", "d90", "prescribed_dose"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "overall_score": {"type": "number", "description": "Overall plan score 0-100"},
                "coverage_score": {"type": "number", "description": "Target coverage sub-score 0-25"},
                "homogeneity_score": {"type": "number", "description": "Dose homogeneity sub-score 0-25"},
                "oar_score": {"type": "number", "description": "OAR sparing sub-score 0-30"},
                "acceptability": {"type": "string", "description": "'ACCEPTABLE', 'BORDERLINE', or 'UNACCEPTABLE'"},
                "violations": {"type": "array", "description": "List of constraint violations"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        v100 = kwargs.get("v100", 0)
        v150 = kwargs.get("v150", 0)
        v200 = kwargs.get("v200", 0)
        d90 = kwargs.get("d90", 0)
        prescribed_dose = kwargs["prescribed_dose"]
        oar_metrics = kwargs.get("oar_metrics", {})
        oar_constraints = kwargs.get("oar_constraints", {})

        coverage_score = self._score_coverage(v100, v150, v200, prescribed_dose)
        homogeneity_score = self._score_homogeneity(d90, prescribed_dose)
        oar_score, violations = self._score_oars(oar_metrics, oar_constraints, prescribed_dose)

        overall_score = coverage_score + homogeneity_score + oar_score

        if overall_score >= 80 and len(violations) == 0:
            acceptability = "ACCEPTABLE"
        elif overall_score >= 60 and len(violations) <= 1:
            acceptability = "BORDERLINE"
        else:
            acceptability = "UNACCEPTABLE"

        return ToolResult(
            success=True,
            data={
                "overall_score": overall_score,
                "coverage_score": coverage_score,
                "homogeneity_score": homogeneity_score,
                "oar_score": oar_score,
                "acceptability": acceptability,
                "violations": violations,
            },
            message=f"Plan quality score: {overall_score:.0f}/100 ({acceptability})",
            metadata={
                "overall_score": overall_score,
                "coverage_score": coverage_score,
                "homogeneity_score": homogeneity_score,
                "oar_score": oar_score,
                "acceptability": acceptability,
                "violations": violations,
            },
        )

    def _score_coverage(self, v100, v150, v200, prescribed_dose):
        score = 0.0
        if v100 >= 0.95:
            score += 15
        elif v100 >= 0.90:
            score += 12
        elif v100 >= 0.85:
            score += 8
        elif v100 >= 0.80:
            score += 4

        if v150 <= 0.35:
            score += 5
        elif v150 <= 0.50:
            score += 3

        if v200 <= 0.15:
            score += 5
        elif v200 <= 0.25:
            score += 3

        return min(25, score)

    def _score_homogeneity(self, d90, prescribed_dose):
        ratio = d90 / prescribed_dose if prescribed_dose > 0 else 0
        if ratio >= 1.0:
            return 25
        elif ratio >= 0.95:
            return 22
        elif ratio >= 0.90:
            return 18
        elif ratio >= 0.85:
            return 12
        elif ratio >= 0.80:
            return 6
        else:
            return 0

    def _score_oars(self, oar_metrics, oar_constraints, prescribed_dose):
        violations = []
        score = 30

        for oar_name, metrics in oar_metrics.items():
            max_dose = metrics.get("max_dose", 0)
            constraint = oar_constraints.get(oar_name, 2.0 * prescribed_dose)

            if max_dose > constraint:
                excess_pct = (max_dose - constraint) / constraint * 100
                penalty = min(15, excess_pct / 10 * 5)
                score -= penalty
                violations.append({
                    "oar": oar_name,
                    "max_dose": float(max_dose),
                    "constraint": float(constraint),
                    "excess_pct": float(excess_pct),
                })

        return max(0, score), violations


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Plan Quality Scorer")
    parser.add_argument("--v100", type=float, required=True)
    parser.add_argument("--v150", type=float, default=0)
    parser.add_argument("--v200", type=float, default=0)
    parser.add_argument("--d90", type=float, required=True)
    parser.add_argument("--prescribed_dose", type=float, required=True)
    args = parser.parse_args()

    tool = PlanQualityScorerTool()
    result = tool._execute(
        v100=args.v100, v150=args.v150, v200=args.v200,
        d90=args.d90, prescribed_dose=args.prescribed_dose,
    )
    print(result.message)
    print(f"Overall Score: {result.metadata['overall_score']:.0f}/100")


if __name__ == "__main__":
    main()