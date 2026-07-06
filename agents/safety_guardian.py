"""
Safety Guardian Agent
=====================
Deterministic safety review for brachytherapy outputs.

Clinical pass/fail limits are read from runtime `plan_config`; the agent does
not invent OAR or target thresholds. Generic sanity checks are reported as data
integrity concerns, not as sourced clinical criteria.
"""

import logging
import math
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent
from communication.protocol import AgentMessage, AgentResponse, AgentRole, ReviewResult

logger = logging.getLogger(__name__)


class SafetyGuardian(BaseAgent):
    """Advisory safety guardian for plan output integrity and configured limits."""

    def __init__(self, llm_callback=None):
        super().__init__(AgentRole.SAFETY_GUARDIAN, llm_callback)

    async def process(self, message: AgentMessage) -> AgentResponse:
        content = message.content
        dose_metrics = content.get("dose_metrics", {}) or {}
        plan_info = content.get("plan_info", {}) or {}
        plan_config = content.get("plan_config", {}) or {}

        checks = [
            self._check_data_integrity(dose_metrics, plan_info),
            self._check_completeness(plan_info),
            self._check_configured_target_limits(dose_metrics, plan_config),
            self._check_configured_oar_limits(dose_metrics, plan_config),
            self._check_advisory_dose_distribution(dose_metrics, plan_config),
            self._check_sanity_outliers(dose_metrics, plan_config),
        ]
        final_result = self._aggregate_checks(checks)

        return AgentResponse(
            agent_role=self.role,
            success=True,
            result=final_result,
            confidence=final_result.confidence,
            reasoning=self._build_reasoning(checks),
            suggestions=final_result.suggestions,
            warnings=final_result.concerns,
        )

    def _check_data_integrity(self, dose_metrics: Dict[str, Any], plan_info: Dict[str, Any]) -> ReviewResult:
        concerns: List[str] = []
        suggestions: List[str] = []

        def walk(prefix: str, value: Any):
            if value is None:
                return
            if isinstance(value, dict):
                for k, v in value.items():
                    walk(f"{prefix}.{k}" if prefix else str(k), v)
                return
            if isinstance(value, (list, tuple)):
                for idx, v in enumerate(value):
                    walk(f"{prefix}[{idx}]", v)
                return
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                concerns.append(f"Invalid numeric value at {prefix}: {value}")
            if isinstance(value, (int, float)) and "dose" in prefix.lower() and value < 0:
                concerns.append(f"Negative dose value at {prefix}: {value}")

        walk("", dose_metrics)

        for key in ("total_seeds", "num_trajectories"):
            val = plan_info.get(key)
            if isinstance(val, (int, float)) and val < 0:
                concerns.append(f"Invalid {key}: {val}")

        if concerns:
            suggestions.append("Recompute dose and verify source data before clinical interpretation.")

        return ReviewResult(
            reviewer="Data Integrity Check",
            decision="reject" if concerns else "pass",
            score=2.0 if concerns else 10.0,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.95,
        )

    def _check_completeness(self, plan_info: Dict[str, Any]) -> ReviewResult:
        concerns: List[str] = []
        suggestions: List[str] = []

        for field in ("total_seeds", "num_trajectories"):
            if field not in plan_info:
                concerns.append(f"Missing required plan field: {field}")

        if plan_info.get("total_seeds", 0) == 0:
            concerns.append("No seeds are reported in the plan.")
            suggestions.append("Verify seed planning completed before reviewing dose quality.")

        return ReviewResult(
            reviewer="Completeness Check",
            decision="conditional" if concerns else "pass",
            score=max(4.0, 10.0 - len(concerns) * 2),
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.85,
        )

    def _check_configured_target_limits(self, dose_metrics: Dict[str, Any], plan_config: Dict[str, Any]) -> ReviewResult:
        checks = self._target_checks(plan_config)
        if not checks:
            return ReviewResult(
                reviewer="Configured Target Limits",
                decision="conditional",
                score=6.0,
                concerns=["No source-backed target limits were supplied in plan_config."],
                suggestions=["Query clinical_kb for site-specific target coverage standards before final approval."],
                confidence=0.65,
            )

        concerns: List[str] = []
        for metric, rule in checks.items():
            value = self._metric_value(dose_metrics, metric)
            if value is None:
                continue
            ok = value >= rule["threshold"] if rule["operator"] == ">=" else value <= rule["threshold"]
            if not ok:
                concerns.append(
                    f"{metric.upper()}={value:.3g} violates configured limit "
                    f"{rule['operator']} {rule['threshold']:.3g} {rule.get('unit', '')}".strip()
                )

        return ReviewResult(
            reviewer="Configured Target Limits",
            decision="conditional" if concerns else "pass",
            score=max(4.0, 10.0 - len(concerns) * 3),
            concerns=concerns,
            suggestions=["Adjust seed distribution and recompute dose." ] if concerns else [],
            confidence=0.9,
        )

    def _check_configured_oar_limits(self, dose_metrics: Dict[str, Any], plan_config: Dict[str, Any]) -> ReviewResult:
        oar_metrics = dose_metrics.get("oar_metrics", {})
        constraints = plan_config.get("oar_constraints", {}) or {}
        if not isinstance(oar_metrics, dict) or not oar_metrics:
            return ReviewResult(
                reviewer="Configured OAR Limits",
                decision="pass",
                score=10.0,
                concerns=[],
                suggestions=[],
                confidence=0.8,
            )
        if not isinstance(constraints, dict) or not constraints:
            return ReviewResult(
                reviewer="Configured OAR Limits",
                decision="conditional",
                score=6.0,
                concerns=["OAR metrics are present, but no source-backed OAR constraints were supplied."],
                suggestions=["Query clinical_kb for site-specific OAR limits before final approval."],
                confidence=0.65,
            )

        concerns: List[str] = []
        normalized = {str(k).lower(): v for k, v in constraints.items() if isinstance(v, dict)}
        for organ_name, metrics in oar_metrics.items():
            if not isinstance(metrics, dict):
                continue
            constraint = self._match_constraint(str(organ_name).lower(), normalized)
            if not constraint:
                continue
            for metric_key, aliases in {
                "d2cc": ("d2cc", "D2cc"),
                "max_dose": ("max_dose", "dmax", "Dmax"),
                "mean_dose": ("mean_dose", "dmean", "Dmean"),
            }.items():
                limit = constraint.get(metric_key)
                value = self._first_numeric(metrics, aliases)
                if limit is not None and value is not None and value > float(limit):
                    concerns.append(f"{organ_name} {metric_key}={value:.2f} Gy exceeds configured limit {float(limit):.2f} Gy")

        return ReviewResult(
            reviewer="Configured OAR Limits",
            decision="conditional" if concerns else "pass",
            score=max(3.0, 10.0 - len(concerns) * 2),
            concerns=concerns,
            suggestions=["Move seeds away from the affected OARs or adjust needle paths." ] if concerns else [],
            confidence=0.9,
        )

    def _check_sanity_outliers(self, dose_metrics: Dict[str, Any], plan_config: Dict[str, Any]) -> ReviewResult:
        """Flag implausible numeric outliers without treating them as guideline limits."""
        concerns: List[str] = []
        prescription = self._first_numeric(plan_config, ("prescribed_dose", "in_lowest_energy"))
        max_dose = self._first_numeric(dose_metrics, ("max_dose", "dmax", "Dmax"))
        if prescription and max_dose and max_dose > 10 * prescription:
            concerns.append(
                f"Max dose {max_dose:.2f} is >10x configured prescription/context value {prescription:.2f}; verify unit scaling."
            )

        return ReviewResult(
            reviewer="Dose Sanity Check",
            decision="conditional" if concerns else "pass",
            score=7.0 if concerns else 10.0,
            concerns=concerns,
            suggestions=["Verify dose units and scaling before interpreting plan quality."] if concerns else [],
            confidence=0.75,
        )

    def _check_advisory_dose_distribution(self, dose_metrics: Dict[str, Any], plan_config: Dict[str, Any]) -> ReviewResult:
        """Flag obvious distribution problems as advisory safety concerns."""
        concerns: List[str] = []
        v100 = self._normalized_fraction(self._metric_value(dose_metrics, "v100"))
        v150 = self._normalized_fraction(self._metric_value(dose_metrics, "v150"))
        v200 = self._normalized_fraction(self._metric_value(dose_metrics, "v200"))
        d90_ratio = self._dose_ratio_or_fraction(dose_metrics, plan_config, "d90")
        max_ratio = self._dose_ratio_or_fraction(dose_metrics, plan_config, "max_dose")

        if v100 is not None and v100 < 0.80:
            concerns.append(f"Advisory dose-distribution concern: V100 is {v100:.1%}; verify coverage before approval.")
        if d90_ratio is not None and d90_ratio < 0.80:
            concerns.append(f"Advisory dose-distribution concern: D90 is {d90_ratio:.1%} of prescription/context.")
        if v150 is not None and v150 > 0.60:
            concerns.append(f"Advisory dose-distribution concern: V150 is {v150:.1%}; verify high-dose spread.")
        if v200 is not None and v200 > 0.30:
            concerns.append(f"Advisory dose-distribution concern: V200 is {v200:.1%}; verify hot spots.")
        if max_ratio is not None and max_ratio > 3.0:
            concerns.append(f"Advisory dose-distribution concern: max dose is {max_ratio:.1f}x prescription/context.")

        return ReviewResult(
            reviewer="Advisory Dose Distribution",
            decision="conditional" if concerns else "pass",
            score=max(3.0, 10.0 - len(concerns) * 1.4),
            concerns=concerns,
            suggestions=["Recompute dose, inspect DVH, and revise seed placement if concerns persist."] if concerns else [],
            confidence=0.75,
        )

    @staticmethod
    def _target_checks(plan_config: Dict[str, Any]) -> Dict[str, dict]:
        checks: Dict[str, dict] = {}
        for metric, keys in {
            "v100": ("v100_min", "v100_target"),
            "v150": ("v150_max", "v150_limit"),
            "v200": ("v200_max", "v200_limit"),
        }.items():
            for key in keys:
                if key in plan_config:
                    checks[metric] = {
                        "threshold": float(plan_config[key]),
                        "operator": ">=" if metric == "v100" else "<=",
                        "unit": "fraction",
                    }
                    break
        if "d90_min_gy" in plan_config:
            checks["d90"] = {"threshold": float(plan_config["d90_min_gy"]), "operator": ">=", "unit": "Gy"}
        elif "d90_min_pct" in plan_config:
            checks["d90"] = {"threshold": float(plan_config["d90_min_pct"]), "operator": ">=", "unit": "fraction_of_prescription"}
        return checks

    @staticmethod
    def _match_constraint(organ_lower: str, constraints: Dict[str, dict]) -> Optional[dict]:
        for key, value in constraints.items():
            if key == organ_lower or key in organ_lower or organ_lower in key:
                return value
        return None

    @staticmethod
    def _metric_value(metrics: Dict[str, Any], key: str) -> Optional[float]:
        return SafetyGuardian._first_numeric(metrics, (key, key.upper(), key.capitalize()))

    @staticmethod
    def _first_numeric(values: Dict[str, Any], keys) -> Optional[float]:
        if not isinstance(values, dict):
            return None
        for key in keys:
            if key not in values:
                continue
            try:
                return float(str(values[key]).replace("%", "").replace("Gy", "").strip())
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _normalized_fraction(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return value / 100.0 if value > 1.5 else value

    def _dose_ratio_or_fraction(self, dose_metrics: Dict[str, Any], plan_config: Dict[str, Any], key: str) -> Optional[float]:
        value = self._metric_value(dose_metrics, key)
        if value is None:
            return None
        if value <= 5.0:
            return value
        prescription = self._first_numeric(dose_metrics, ("prescribed_dose", "prescription"))
        if prescription is None:
            prescription = self._first_numeric(plan_config, ("prescribed_dose", "in_lowest_energy", "prescription_dose"))
        if prescription is not None and prescription <= 5.0:
            dose_scale = (
                self._first_numeric(dose_metrics, ("dose_scale_gy",))
                or self._first_numeric(plan_config, ("dose_scale_gy",))
                or 120.0
            )
            prescription *= dose_scale
        if prescription and prescription > 0:
            return value / prescription
        return None

    def _aggregate_checks(self, checks: List[ReviewResult]) -> ReviewResult:
        concerns: List[str] = []
        suggestions: List[str] = []
        reject = False
        conditional = False
        weighted_score = 0.0
        total_weight = 0.0

        for check in checks:
            concerns.extend(check.concerns)
            suggestions.extend(check.suggestions)
            if check.decision == "reject":
                reject = True
            elif check.decision == "conditional":
                conditional = True
            weight = 1.0
            weighted_score += check.score * weight
            total_weight += weight

        if reject:
            decision = "reject"
        elif conditional:
            decision = "conditional"
        else:
            decision = "pass"

        return ReviewResult(
            reviewer="Safety Guardian (Aggregated)",
            decision=decision,
            score=weighted_score / total_weight if total_weight else 5.0,
            concerns=list(dict.fromkeys(concerns)),
            suggestions=list(dict.fromkeys(suggestions)),
            confidence=sum(c.confidence for c in checks) / len(checks) if checks else 0.3,
        )

    def _build_reasoning(self, checks: List[ReviewResult]) -> str:
        lines = ["Safety Check Summary:"]
        for check in checks:
            lines.append(f"- {check.reviewer}: {check.decision} (score={check.score:.1f})")
            for concern in check.concerns[:1]:
                lines.append(f"  {concern}")
        return "\n".join(lines)
