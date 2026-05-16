"""
Quality Decider
==============
Plan quality assessment and scoring decider.
"""

import json
from typing import Dict, List, Any, Optional

from ..core.base import BaseLLM, BaseDecider


class QualityDecider(BaseDecider):
    """
    Assesses brachytherapy plan quality.

    Evaluates:
    - Target coverage (V100, V150, V200)
    - Dose homogeneity (D90, D95, D99)
    - OAR sparing compliance
    - Overall quality score (0-100)
    """

    def __init__(self, llm: BaseLLM):
        super().__init__(llm)

    def decide(self, task: str, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Assess plan quality.

        Args:
            task: Quality assessment task
            context: Contains metrics, constraints, etc.

        Returns:
            Quality assessment with scores and recommendations
        """
        metrics = context.get("metrics", {})
        oar_metrics = context.get("oar_metrics", {})
        constraints = context.get("constraints", {})
        prescribed_dose = context.get("prescribed_dose", 1.0)

        assessment = self._assess_quality(metrics, oar_metrics, constraints, prescribed_dose)
        return assessment

    def decide_with_llm(
        self,
        task: str,
        context: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Use LLM to make quality judgment with reasoning.

        Falls back to rule-based assessment if LLM unavailable.
        """
        metrics = context.get("metrics", {})
        oar_metrics = context.get("oar_metrics", {})
        prescribed_dose = context.get("prescribed_dose", 1.0)

        metrics_text = self._format_metrics(metrics, prescribed_dose)
        oar_text = self._format_oar_metrics(oar_metrics)

        system_msg = (
            "You are an expert medical physicist specializing in brachytherapy plan quality assessment. "
            "Evaluate the plan quality based on clinical metrics and provide improvement suggestions."
        )

        user_text = (
            f"Quality Assessment Task: {task}\n\n"
            f"Plan Metrics:\n{metrics_text}\n\n"
            f"OAR Metrics:\n{oar_text}\n\n"
            "Provide a quality score (0-100), acceptability judgment, "
            "and specific improvement suggestions if needed."
        )

        response = self.llm.chat(prompt=user_text, system=system_msg)

        rule_based = self._assess_quality(metrics, oar_metrics, {}, prescribed_dose)

        if not response.content:
            return rule_based

        return {
            **rule_based,
            "llm_reasoning": response.content,
            "llm_model": response.model,
        }

    def _assess_quality(
        self,
        metrics: Dict[str, float],
        oar_metrics: Dict[str, Dict],
        constraints: Dict[str, float],
        prescribed_dose: float,
    ) -> Dict[str, Any]:
        """Rule-based quality assessment."""
        pd = prescribed_dose

        v100 = metrics.get("v100", 0)
        v150 = metrics.get("v150", 0)
        v200 = metrics.get("v200", 0)
        d90 = metrics.get("d90", 0)

        coverage_score = self._score_coverage(v100, v150, v200, pd)
        homogeneity_score = self._score_homogeneity(d90, pd)
        oar_score, violations = self._score_oars(oar_metrics, constraints, pd)

        overall = coverage_score + homogeneity_score + oar_score

        if overall >= 80 and not violations:
            acceptability = "ACCEPTABLE"
        elif overall >= 60:
            acceptability = "BORDERLINE"
        else:
            acceptability = "UNACCEPTABLE"

        suggestions = self._generate_suggestions(metrics, violations, pd)

        return {
            "quality_score": overall,
            "acceptability": acceptability,
            "sub_scores": {
                "coverage": coverage_score,
                "homogeneity": homogeneity_score,
                "oar_sparing": oar_score,
            },
            "violations": violations,
            "suggestions": suggestions,
            "metrics_summary": {
                "v100": f"{v100:.1%}",
                "v150": f"{v150:.1%}",
                "v200": f"{v200:.1%}",
                "d90": f"{d90:.2f} Gy",
            },
        }

    def _score_coverage(self, v100: float, v150: float, v200: float, pd: float) -> float:
        """Score target coverage (max 25)."""
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

    def _score_homogeneity(self, d90: float, pd: float) -> float:
        """Score dose homogeneity (max 25)."""
        ratio = d90 / pd if pd > 0 else 0
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
        return 0

    def _score_oars(
        self,
        oar_metrics: Dict[str, Dict],
        constraints: Dict[str, float],
        pd: float,
    ) -> tuple:
        """Score OAR sparing (max 30). Returns (score, violations)."""
        score = 30
        violations = []

        default_constraints = {
            "rectum": 2.0 * pd,
            "bladder": 1.5 * pd,
            "urethra": 1.2 * pd,
            "bowel": 0.8 * pd,
            "kidney": 0.2 * pd,
        }
        all_constraints = {**default_constraints, **constraints}

        for oar_name, metrics in oar_metrics.items():
            max_dose = metrics.get("max_dose", 0)
            constraint = all_constraints.get(oar_name.lower(), 2.0 * pd)

            if max_dose > constraint:
                excess = (max_dose - constraint) / constraint * 100
                penalty = min(15, excess / 10 * 5)
                score -= penalty
                violations.append({
                    "structure": oar_name,
                    "max_dose": float(max_dose),
                    "constraint": float(constraint),
                    "excess_pct": float(excess),
                })

        return max(0, score), violations

    def _generate_suggestions(self, metrics: Dict, violations: List, pd: float) -> List[str]:
        """Generate improvement suggestions."""
        suggestions = []
        v100 = metrics.get("v100", 0)
        v200 = metrics.get("v200", 0)

        if v100 < 0.90:
            suggestions.append(f"V100={v100:.1%} < 90%. Consider adding seeds in underdosed regions.")
        if v100 < 0.95:
            suggestions.append(f"V100={v100:.1%} < 95%. Adjust seed positions to improve coverage.")
        if v200 > 0.35:
            suggestions.append(f"V200={v200:.1%} > 35%. Reduce seed density in hot-spot areas.")
        if metrics.get("d90", 0) < pd * 0.9:
            suggestions.append(f"D90 below target. Increase seed strength or add seeds.")

        for v in violations:
            suggestions.append(
                f"{v['structure']} max dose {v['max_dose']:.1f}Gy exceeds "
                f"constraint {v['constraint']:.1f}Gy. Reposition seeds away from this OAR."
            )

        if not suggestions:
            suggestions.append("Plan quality is acceptable. No immediate changes recommended.")

        return suggestions

    def _format_metrics(self, metrics: Dict, pd: float) -> str:
        lines = []
        for k, v in metrics.items():
            if k in {"v100", "v150", "v200"}:
                lines.append(f"- {k}: {v:.1%} (target: see clinical guidelines)")
            elif k in {"d90", "d95", "d99"}:
                lines.append(f"- {k}: {v:.2f} Gy (prescribed: {pd:.2f} Gy)")
            else:
                lines.append(f"- {k}: {v}")
        return "\n".join(lines) if lines else "No metrics available"

    def _format_oar_metrics(self, oar_metrics: Dict) -> str:
        lines = []
        for name, data in oar_metrics.items():
            max_d = data.get("max_dose", "N/A")
            mean_d = data.get("mean_dose", "N/A")
            lines.append(f"- {name}: max={max_d}, mean={mean_d}")
        return "\n".join(lines) if lines else "No OAR metrics available"