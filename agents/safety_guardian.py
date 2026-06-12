"""
Safety Guardian Agent
=====================
Ensures clinical safety of all outputs.
Acts as the final safety gate before presenting results to users.
"""

import logging
from typing import Dict, List, Any
from .base_agent import BaseAgent
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    ReviewResult, Priority
)

logger = logging.getLogger(__name__)


class SafetyGuardian(BaseAgent):
    """
    Ensures clinical safety of treatment plans and recommendations.

    Safety checks:
    1. Dose safety (max dose, OAR constraints)
    2. Operation safety (required steps completed)
    3. Data integrity (valid values, no corruption)
    4. Risk warnings (potential complications)
    """

    # Critical safety thresholds
    SAFETY_LIMITS = {
        "max_dose_ratio": 3.0,  # Max dose should not exceed 3x prescription
        "min_coverage": 0.80,   # Minimum V100 coverage
        "max_oar_violations": 2, # Max allowed OAR violations
    }

    # Safety rules
    SAFETY_RULES = [
        {
            "id": "dose_range_check",
            "name": "Dose Range Check",
            "description": "Verify dose values are within reasonable range",
            "severity": "critical",
        },
        {
            "id": "coverage_check",
            "name": "Coverage Check",
            "description": "Verify minimum target coverage is met",
            "severity": "high",
        },
        {
            "id": "oar_constraint_check",
            "name": "OAR Constraint Check",
            "description": "Verify OAR dose constraints are respected",
            "severity": "critical",
        },
        {
            "id": "data_integrity_check",
            "name": "Data Integrity Check",
            "description": "Verify data values are valid and not corrupted",
            "severity": "critical",
        },
        {
            "id": "completeness_check",
            "name": "Completeness Check",
            "description": "Verify all required planning steps were completed",
            "severity": "high",
        },
    ]

    def __init__(self, llm_callback=None):
        super().__init__(AgentRole.SAFETY_GUARDIAN, llm_callback)

    async def process(self, message: AgentMessage) -> AgentResponse:
        """
        Perform safety checks on the content.

        Args:
            message: Contains data to check

        Returns:
            AgentResponse with ReviewResult
        """
        content = message.content

        # Extract data
        dose_metrics = content.get("dose_metrics", {})
        plan_info = content.get("plan_info", {})
        output_type = content.get("output_type", "unknown")

        # Run all safety checks
        check_results = []

        # 1. Dose range check
        dose_check = self._check_dose_range(dose_metrics)
        check_results.append(dose_check)

        # 2. Coverage check
        coverage_check = self._check_coverage(dose_metrics)
        check_results.append(coverage_check)

        # 3. OAR constraint check
        oar_check = self._check_oar_constraints(dose_metrics)
        check_results.append(oar_check)

        # 4. Data integrity check
        integrity_check = self._check_data_integrity(dose_metrics, plan_info)
        check_results.append(integrity_check)

        # 5. Completeness check
        completeness_check = self._check_completeness(plan_info)
        check_results.append(completeness_check)

        # Aggregate results
        final_result = self._aggregate_checks(check_results)

        return AgentResponse(
            agent_role=self.role,
            success=True,
            result=final_result,
            confidence=final_result.confidence,
            reasoning=self._build_reasoning(check_results),
            suggestions=final_result.suggestions,
            warnings=final_result.concerns,
        )

    def _check_dose_range(self, dose_metrics: Dict) -> ReviewResult:
        """Check if dose values are within reasonable range."""
        concerns = []
        suggestions = []

        max_dose = dose_metrics.get("max_dose")
        if max_dose is not None:
            try:
                max_dose_val = float(str(max_dose).replace("Gy", ""))

                # Check for unreasonable values
                if max_dose_val < 0:
                    concerns.append(f"Negative dose value: {max_dose_val}")
                    return ReviewResult(
                        reviewer="Dose Range Check",
                        decision="reject",
                        score=1.0,
                        concerns=concerns,
                        suggestions=["Data corruption detected - verify dose calculation"],
                        confidence=0.95,
                    )

                if max_dose_val > self.SAFETY_LIMITS["max_dose_ratio"]:
                    concerns.append(
                        f"Maximum dose ({max_dose_val:.2f}) exceeds safety limit "
                        f"({self.SAFETY_LIMITS['max_dose_ratio']}x prescription)"
                    )
                    suggestions.append("Verify hot spot location and consider dose reduction")

                if max_dose_val > 100:  # Unreasonably high in normalized units
                    concerns.append(f"Suspiciously high max dose: {max_dose_val}")
                    suggestions.append("Check dose calculation for errors")

            except (ValueError, TypeError):
                concerns.append(f"Invalid max_dose format: {max_dose}")
                return ReviewResult(
                    reviewer="Dose Range Check",
                    decision="reject",
                    score=2.0,
                    concerns=concerns,
                    suggestions=["Fix dose data format"],
                    confidence=0.9,
                )

        # Check mean dose
        mean_dose = dose_metrics.get("mean_dose")
        if mean_dose is not None:
            try:
                mean_dose_val = float(str(mean_dose).replace("Gy", ""))
                if mean_dose_val < 0:
                    concerns.append(f"Negative mean dose: {mean_dose_val}")
            except (ValueError, TypeError):
                pass

        score = max(1, 10 - len(concerns) * 3)

        return ReviewResult(
            reviewer="Dose Range Check",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.9,
        )

    def _check_coverage(self, dose_metrics: Dict) -> ReviewResult:
        """Check if minimum coverage is met."""
        concerns = []
        suggestions = []

        v100 = dose_metrics.get("v100")
        if v100 is not None:
            try:
                v100_val = float(str(v100).replace("%", ""))
                if v100_val < self.SAFETY_LIMITS["min_coverage"]:
                    concerns.append(
                        f"V100 ({v100_val:.1%}) below minimum coverage "
                        f"({self.SAFETY_LIMITS['min_coverage']:.0%})"
                    )
                    suggestions.append("Plan revision required to meet minimum coverage")

                    if v100_val < 0.70:
                        return ReviewResult(
                            reviewer="Coverage Check",
                            decision="reject",
                            score=2.0,
                            concerns=concerns,
                            suggestions=suggestions,
                            confidence=0.95,
                        )
            except (ValueError, TypeError):
                concerns.append(f"Invalid V100 format: {v100}")

        score = max(1, 10 - len(concerns) * 3)

        return ReviewResult(
            reviewer="Coverage Check",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.9,
        )

    def _check_oar_constraints(self, dose_metrics: Dict) -> ReviewResult:
        """Check OAR dose constraints."""
        concerns = []
        suggestions = []
        violations = 0

        oar_metrics = dose_metrics.get("oar_metrics", {})
        for organ_name, metrics in oar_metrics.items():
            # Check for extreme values
            max_dose = metrics.get("max_dose")
            if max_dose is not None:
                try:
                    max_val = float(str(max_dose).replace("Gy", ""))
                    if max_val > 2.0:  # 2x prescription
                        violations += 1
                        concerns.append(f"{organ_name} max dose ({max_val:.2f}) is very high")
                        suggestions.append(f"Review dose to {organ_name}")
                except (ValueError, TypeError):
                    pass

        if violations > self.SAFETY_LIMITS["max_oar_violations"]:
            return ReviewResult(
                reviewer="OAR Constraint Check",
                decision="reject",
                score=2.0,
                concerns=concerns,
                suggestions=suggestions,
                confidence=0.9,
            )

        score = max(1, 10 - violations * 2)

        return ReviewResult(
            reviewer="OAR Constraint Check",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.85,
        )

    def _check_data_integrity(self, dose_metrics: Dict, plan_info: Dict) -> ReviewResult:
        """Check data integrity."""
        concerns = []
        suggestions = []

        # Check for None/NaN values
        for key, value in dose_metrics.items():
            if value is None:
                concerns.append(f"Missing value for {key}")
            elif isinstance(value, float) and (value != value):  # NaN check
                concerns.append(f"NaN value for {key}")
                suggestions.append(f"Recalculate {key}")

        # Check for negative counts
        total_seeds = plan_info.get("total_seeds", 0)
        if total_seeds < 0:
            concerns.append(f"Invalid seed count: {total_seeds}")

        num_trajectories = plan_info.get("num_trajectories", 0)
        if num_trajectories < 0:
            concerns.append(f"Invalid trajectory count: {num_trajectories}")

        score = max(1, 10 - len(concerns) * 2)

        return ReviewResult(
            reviewer="Data Integrity Check",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.95,
        )

    def _check_completeness(self, plan_info: Dict) -> ReviewResult:
        """Check if all required steps were completed."""
        concerns = []
        suggestions = []

        required_fields = ["total_seeds", "num_trajectories"]
        for field in required_fields:
            if field not in plan_info:
                concerns.append(f"Missing required field: {field}")

        # Check if plan has actual content
        total_seeds = plan_info.get("total_seeds", 0)
        if total_seeds == 0:
            concerns.append("No seeds in the plan")
            suggestions.append("Verify seed planning was executed")

        score = max(1, 10 - len(concerns) * 2)

        return ReviewResult(
            reviewer="Completeness Check",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.85,
        )

    def _aggregate_checks(self, checks: List[ReviewResult]) -> ReviewResult:
        """Aggregate all safety checks."""
        if not checks:
            return ReviewResult(
                reviewer="Safety Guardian (Aggregated)",
                decision="conditional",
                score=5.0,
                concerns=["No safety checks performed"],
                confidence=0.3,
            )

        # Any critical failure fails the whole check
        critical_failures = [c for c in checks if c.decision == "reject"]

        if critical_failures:
            final_decision = "reject"
            final_score = min(c.score for c in critical_failures)
        else:
            # Weighted average
            weights = {
                "Dose Range Check": 1.5,
                "Coverage Check": 1.3,
                "OAR Constraint Check": 1.4,
                "Data Integrity Check": 1.2,
                "Completeness Check": 1.0,
            }

            total_weight = 0
            weighted_score = 0
            for check in checks:
                w = weights.get(check.reviewer, 1.0)
                weighted_score += check.score * w
                total_weight += w

            final_score = weighted_score / total_weight if total_weight > 0 else 5.0
            final_decision = self._score_to_decision(final_score)

        # Aggregate concerns and suggestions
        all_concerns = []
        all_suggestions = []
        for check in checks:
            all_concerns.extend(check.concerns)
            all_suggestions.extend(check.suggestions)

        avg_confidence = sum(c.confidence for c in checks) / len(checks)

        return ReviewResult(
            reviewer="Safety Guardian (Aggregated)",
            decision=final_decision,
            score=final_score,
            concerns=list(set(all_concerns)),
            suggestions=list(set(all_suggestions)),
            confidence=avg_confidence,
        )

    def _score_to_decision(self, score: float) -> str:
        """Convert score to decision."""
        if score >= 7:
            return "pass"
        elif score >= 5:
            return "conditional"
        else:
            return "reject"

    def _build_reasoning(self, checks: List[ReviewResult]) -> str:
        """Build reasoning summary."""
        lines = ["Safety Check Summary:"]
        for check in checks:
            status = "✓" if check.decision == "pass" else "⚠" if check.decision == "conditional" else "✗"
            lines.append(f"{status} {check.reviewer}: {check.decision} (score={check.score:.1f})")
            for concern in check.concerns[:1]:
                lines.append(f"    {concern}")
        return "\n".join(lines)
