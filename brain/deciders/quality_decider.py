"""
Quality Decider
==============
Plan quality assessment and scoring decider.
"""

import json
from typing import Dict, List, Any, Optional

from ..core.base import BaseLLM, BaseDecider
from agents.clinical_metrics import (
    dose_ratio,
    first_numeric,
    match_constraint_name,
    normalized_fraction,
)


class QualityDecider(BaseDecider):
    """
    Assesses brachytherapy plan quality.

    Evaluates:
    - Target coverage (V100, V150, V200)
    - Dose homogeneity (D90, D95, D99)
    - OAR sparing compliance
    - Compliance with caller-supplied, source-backed criteria
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
        target_constraints = context.get("target_constraints", {})
        prescribed_dose = context.get("prescribed_dose")

        assessment = self._assess_quality(
            metrics, oar_metrics, constraints, prescribed_dose, target_constraints
        )
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
        constraints = context.get("constraints", {})
        target_constraints = context.get("target_constraints", {})
        prescribed_dose = context.get("prescribed_dose")

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

        rule_based = self._assess_quality(
            metrics, oar_metrics, constraints, prescribed_dose, target_constraints
        )

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
        constraints: Dict[str, Any],
        prescribed_dose: Optional[float],
        target_constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Assess only criteria explicitly supplied by a source-backed caller."""
        pd = prescribed_dose

        v100 = metrics.get("v100")
        v150 = metrics.get("v150")
        v200 = metrics.get("v200")
        d90 = metrics.get("d90")

        target_score, target_checks, target_violations = self._score_coverage(
            v100, v150, v200, d90, pd, target_constraints or {}
        )
        oar_score, oar_checks, oar_violations = self._score_oars(
            oar_metrics, constraints, pd
        )
        checks = target_checks + oar_checks
        violations = target_violations + oar_violations
        overall = ((target_score + oar_score) / checks * 100.0) if checks else None
        acceptability = (
            "UNVERIFIED" if not checks
            else "REVIEW_REQUIRED" if violations
            else "MEETS_CONFIGURED_CRITERIA"
        )
        suggestions = self._generate_suggestions(violations, checks)

        return {
            "quality_score": round(overall, 1) if overall is not None else None,
            "acceptability": acceptability,
            "sub_scores": {
                "target_passed": target_score,
                "target_checked": target_checks,
                "oar_passed": oar_score,
                "oar_checked": oar_checks,
            },
            "violations": violations,
            "suggestions": suggestions,
            "metrics_summary": {
                "v100": f"{v100:.1%}" if v100 is not None else "N/A",
                "v150": f"{v150:.1%}" if v150 is not None else "N/A",
                "v200": f"{v200:.1%}" if v200 is not None else "N/A",
                "d90": f"{d90:.2f} Gy" if d90 is not None else "N/A",
            },
        }

    def _score_coverage(self, v100: Optional[float], v150: Optional[float],
                        v200: Optional[float], d90: Optional[float],
                        pd: Optional[float],
                        criteria: Dict[str, Any]) -> tuple:
        """Return (passed, checked, violations) for configured target limits."""
        passed = 0
        checked = 0
        violations = []
        values = {
            "v100": normalized_fraction(v100),
            "v150": normalized_fraction(v150),
            "v200": normalized_fraction(v200),
        }
        for metric, key, operator in (
            ("v100", "v100_min", ">="),
            ("v150", "v150_max", "<="),
            ("v200", "v200_max", "<="),
        ):
            if key not in criteria or values[metric] is None:
                continue
            checked += 1
            threshold = normalized_fraction(criteria[key])
            ok = threshold is not None and (
                values[metric] >= threshold if operator == ">="
                else values[metric] <= threshold
            )
            if ok:
                passed += 1
            else:
                violations.append({
                    "structure": "CTV",
                    "metric": metric,
                    "value": values[metric],
                    "constraint": threshold,
                    "operator": operator,
                })

        if "d90_min_gy" in criteria and d90 is not None:
            checked += 1
            threshold = float(criteria["d90_min_gy"])
            if float(d90) >= threshold:
                passed += 1
            else:
                violations.append({
                    "structure": "CTV", "metric": "d90", "value": float(d90),
                    "constraint": threshold, "operator": ">=", "unit": "Gy",
                })
        elif "d90_min_pct" in criteria and d90 is not None and pd is not None and pd > 0:
            checked += 1
            ratio = dose_ratio(
                {"d90": d90, "prescription_dose": pd},
                {"prescription_dose": pd},
                "d90",
            )
            threshold = normalized_fraction(criteria["d90_min_pct"])
            if ratio is not None and threshold is not None and ratio >= threshold:
                passed += 1
            else:
                violations.append({
                    "structure": "CTV", "metric": "d90_ratio", "value": ratio,
                    "constraint": threshold, "operator": ">=",
                })
        return passed, checked, violations

    def _score_oars(
        self,
        oar_metrics: Dict[str, Dict],
        constraints: Dict[str, Any],
        pd: Optional[float],
    ) -> tuple:
        """Return (passed, checked, violations) for configured OAR limits."""
        passed = 0
        checked = 0
        violations = []
        for oar_name, metrics in oar_metrics.items():
            if not isinstance(metrics, dict):
                continue
            matched = match_constraint_name(oar_name, constraints)
            rule = constraints.get(matched) if matched else None
            if rule is None:
                continue
            if isinstance(rule, (int, float)):
                rule = {"max_dose": float(rule)}
            if not isinstance(rule, dict):
                continue
            for metric_name, aliases in {
                "max_dose": ("max_dose", "dmax", "Dmax"),
                "d2cc": ("d2cc", "D2cc"),
                "mean_dose": ("mean_dose", "dmean", "Dmean"),
            }.items():
                limit = first_numeric(rule, (metric_name, f"{metric_name}_gy"))
                value = first_numeric(metrics, aliases)
                if limit is None or value is None:
                    continue
                checked += 1
                if value <= limit:
                    passed += 1
                else:
                    violations.append({
                        "structure": oar_name,
                        "matched_constraint": matched,
                        "metric": metric_name,
                        "value": float(value),
                        "constraint": float(limit),
                        "operator": "<=",
                        "unit": "Gy",
                    })
        return passed, checked, violations

    def _generate_suggestions(self, violations: List, checks: int) -> List[str]:
        """Generate suggestions only from explicit configured violations."""
        if not checks:
            return [
                "Load source-backed target and OAR criteria from clinical_kb "
                "before assessing plan acceptability."
            ]
        suggestions = []
        for v in violations:
            structure = v.get("structure", "Structure")
            metric = v.get("metric", "metric")
            suggestions.append(f"Review {structure} {metric} against its configured criterion.")

        if not suggestions:
            suggestions.append("All supplied source-backed criteria were met.")

        return suggestions

    def _format_metrics(self, metrics: Dict, pd: Optional[float]) -> str:
        lines = []
        for k, v in metrics.items():
            if k in {"v100", "v150", "v200"}:
                lines.append(f"- {k}: {v:.1%} (target: see clinical guidelines)")
            elif k in {"d90", "d95", "d99"}:
                prescribed = f" (prescribed: {pd:.2f} Gy)" if pd is not None else ""
                lines.append(f"- {k}: {v:.2f} Gy{prescribed}")
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
