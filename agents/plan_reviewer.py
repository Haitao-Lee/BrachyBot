"""
Plan Reviewer Agent
===================
Reviews treatment plans for clinical quality and safety.
Extends the existing MultiAgentCritic with more specialized review capabilities.
"""

import logging
from typing import Dict, List, Any, Optional
from .base_agent import LLMCapableAgent
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    ReviewResult, Priority
)

logger = logging.getLogger(__name__)


class PlanReviewer(LLMCapableAgent):
    """
    Reviews treatment plans for clinical quality.

    Review dimensions:
    1. Dosimetry quality (D90, V100, V150, V200)
    2. OAR constraints
    3. Clinical protocol compliance
    4. Risk assessment
    """

    # Clinical thresholds for dose metrics
    DOSE_THRESHOLDS = {
        "v100": {"good": 0.95, "acceptable": 0.90, "unit": "%"},
        "v150": {"good": 0.50, "acceptable": 0.60, "unit": "%"},
        "v200": {"good": 0.20, "acceptable": 0.30, "unit": "%"},
        "d90": {"good": 1.0, "acceptable": 0.90, "unit": "normalized"},
        "d95": {"good": 0.95, "acceptable": 0.85, "unit": "normalized"},
    }

    # OAR dose constraints (normalized units)
    OAR_CONSTRAINTS = {
        "duodenum": {"d2cc": 1.0, "d01cc": 1.2},
        "stomach": {"d2cc": 1.0, "d01cc": 1.2},
        "small_bowel": {"d2cc": 1.0, "d01cc": 1.2},
        "colon": {"d2cc": 1.0, "d01cc": 1.2},
        "spinal_cord": {"d2cc": 0.8, "d01cc": 1.0},
        "liver": {"d2cc": 0.8, "d01cc": 1.0},
        "kidney": {"d2cc": 0.6, "d01cc": 0.8},
    }

    def __init__(self, llm_callback=None):
        super().__init__(AgentRole.PLAN_REVIEWER, llm_callback)

    async def process(self, message: AgentMessage) -> AgentResponse:
        """
        Review a treatment plan.

        Args:
            message: Contains plan data in content

        Returns:
            AgentResponse with ReviewResult
        """
        content = message.content

        # Extract dose metrics and plan info
        dose_metrics = content.get("dose_metrics", {})
        plan_info = content.get("plan_info", {})
        context = content.get("context", "")

        # Perform multi-dimensional review
        reviews = []

        # 1. Dosimetry review
        dosimetry_review = self._review_dosimetry(dose_metrics)
        reviews.append(dosimetry_review)

        # 2. OAR constraints review
        oar_review = self._review_oar_constraints(dose_metrics)
        reviews.append(oar_review)

        # 3. Clinical protocol review
        protocol_review = self._review_clinical_protocol(plan_info, dose_metrics)
        reviews.append(protocol_review)

        # 4. Risk assessment
        risk_review = self._assess_risks(dose_metrics, plan_info)
        reviews.append(risk_review)

        # Aggregate reviews
        final_review = self._aggregate_reviews(reviews)

        return AgentResponse(
            agent_role=self.role,
            success=True,
            result=final_review,
            confidence=final_review.confidence,
            reasoning=self._build_reasoning(reviews),
            suggestions=final_review.suggestions,
            warnings=[c for r in reviews for c in r.concerns],
        )

    def _review_dosimetry(self, dose_metrics: Dict) -> ReviewResult:
        """Review dosimetry quality."""
        concerns = []
        suggestions = []
        scores = []

        for metric, thresholds in self.DOSE_THRESHOLDS.items():
            value = dose_metrics.get(metric)
            if value is None:
                continue

            try:
                value = float(str(value).replace("%", "").replace("Gy", ""))
            except (ValueError, TypeError):
                continue

            if metric in ["v100", "v150", "v200"]:
                # Higher is better for V100, lower is better for V150/V200
                if metric == "v100":
                    if value >= thresholds["good"]:
                        scores.append(10)
                    elif value >= thresholds["acceptable"]:
                        scores.append(7)
                        concerns.append(f"{metric.upper()}={value:.1%} is below optimal ({thresholds['good']:.0%})")
                        suggestions.append(f"Consider adding more seeds to improve {metric.upper()}")
                    else:
                        scores.append(4)
                        concerns.append(f"{metric.upper()}={value:.1%} is critically low")
                        suggestions.append(f"Plan revision needed: {metric.upper()} must be ≥{thresholds['acceptable']:.0%}")
                else:  # V150, V200 - lower is better
                    if value <= thresholds["good"]:
                        scores.append(10)
                    elif value <= thresholds["acceptable"]:
                        scores.append(7)
                    else:
                        scores.append(5)
                        concerns.append(f"{metric.upper()}={value:.1%} indicates hot spots")
                        suggestions.append(f"Consider redistributing seeds to reduce {metric.upper()}")
            else:  # D90, D95
                if value >= thresholds["good"]:
                    scores.append(10)
                elif value >= thresholds["acceptable"]:
                    scores.append(7)
                    concerns.append(f"{metric.upper()}={value:.2f} is below optimal ({thresholds['good']:.2f})")
                else:
                    scores.append(4)
                    concerns.append(f"{metric.upper()}={value:.2f} is critically low")
                    suggestions.append(f"Dose coverage insufficient: {metric.upper()} should be ≥{thresholds['good']:.2f}")

        avg_score = sum(scores) / len(scores) if scores else 5.0

        return ReviewResult(
            reviewer="Dosimetry Review",
            decision=self._score_to_decision(avg_score),
            score=avg_score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.9,
        )

    def _review_oar_constraints(self, dose_metrics: Dict) -> ReviewResult:
        """Review OAR dose constraints."""
        concerns = []
        suggestions = []
        oar_metrics = dose_metrics.get("oar_metrics", {})

        if not oar_metrics:
            return ReviewResult(
                reviewer="OAR Review",
                decision="pass",
                score=8.0,
                concerns=["No OAR metrics available for review"],
                suggestions=["Ensure OAR segmentation is performed"],
                confidence=0.5,
            )

        violations = 0
        total_checks = 0

        for organ_name, metrics in oar_metrics.items():
            organ_lower = organ_name.lower()

            # Find matching constraint
            constraint = None
            for oar_key, oar_constraint in self.OAR_CONSTRAINTS.items():
                if oar_key in organ_lower:
                    constraint = oar_constraint
                    break

            if constraint is None:
                continue

            # Check D2cc
            d2cc = metrics.get("d2cc") or metrics.get("D2cc") or metrics.get("mean_dose")
            if d2cc is not None:
                total_checks += 1
                try:
                    d2cc_val = float(str(d2cc).replace("Gy", ""))
                    if d2cc_val > constraint["d2cc"]:
                        violations += 1
                        concerns.append(
                            f"{organ_name} D2cc={d2cc_val:.2f} exceeds limit ({constraint['d2cc']:.2f})"
                        )
                        suggestions.append(f"Reduce dose to {organ_name}")
                except (ValueError, TypeError):
                    pass

        if total_checks == 0:
            score = 7.0
            decision = "pass"
        else:
            violation_rate = violations / total_checks
            score = max(1, 10 * (1 - violation_rate))
            decision = self._score_to_decision(score)

        return ReviewResult(
            reviewer="OAR Review",
            decision=decision,
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.85,
        )

    def _review_clinical_protocol(self, plan_info: Dict, dose_metrics: Dict) -> ReviewResult:
        """Review clinical protocol compliance."""
        concerns = []
        suggestions = []
        score = 8.0

        # Check if all required steps were completed
        required_steps = ["ctv_segmentation", "oar_segmentation", "trajectory_planning",
                         "seed_planning", "dose_calculation", "dose_evaluation"]

        completed_steps = plan_info.get("completed_steps", [])
        missing_steps = [s for s in required_steps if s not in completed_steps]

        if missing_steps:
            concerns.append(f"Missing steps: {', '.join(missing_steps)}")
            suggestions.append("Complete all required planning steps")
            score -= len(missing_steps) * 1.5

        # Check seed count
        total_seeds = plan_info.get("total_seeds", 0)
        if total_seeds == 0:
            concerns.append("No seeds in the plan")
            suggestions.append("Verify seed planning was executed correctly")
            score -= 3
        elif total_seeds < 5:
            concerns.append(f"Low seed count ({total_seeds})")
            suggestions.append("Consider if seed count is adequate for target coverage")

        # Check trajectory count
        num_trajectories = plan_info.get("num_trajectories", 0)
        if num_trajectories == 0:
            concerns.append("No trajectories in the plan")
            score -= 2

        score = max(1, min(10, score))

        return ReviewResult(
            reviewer="Protocol Review",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.8,
        )

    def _assess_risks(self, dose_metrics: Dict, plan_info: Dict) -> ReviewResult:
        """Assess potential risks."""
        concerns = []
        suggestions = []
        risks = []

        # Check for hot spots
        max_dose = dose_metrics.get("max_dose")
        if max_dose is not None:
            try:
                max_dose_val = float(str(max_dose).replace("Gy", ""))
                if max_dose_val > 2.0:  # 2x prescription
                    risks.append("high_max_dose")
                    concerns.append(f"Maximum dose ({max_dose_val:.2f}) is very high")
                    suggestions.append("Verify hot spot location and OAR proximity")
            except (ValueError, TypeError):
                pass

        # Check coverage vs OAR trade-off
        v100 = dose_metrics.get("v100")
        if v100 is not None:
            try:
                v100_val = float(str(v100).replace("%", ""))
                if v100_val < 0.90:
                    risks.append("low_coverage")
                    concerns.append(f"Low V100 ({v100_val:.1%}) may indicate insufficient coverage")
            except (ValueError, TypeError):
                pass

        # Check for potential seed migration concerns
        total_seeds = plan_info.get("total_seeds", 0)
        num_trajectories = plan_info.get("num_trajectories", 0)
        if num_trajectories > 0 and total_seeds / num_trajectories > 10:
            risks.append("dense_seeding")
            concerns.append("High seed density per trajectory - consider migration risk")
            suggestions.append("Verify seed spacing is adequate")

        score = max(5, 10 - len(risks) * 2)

        return ReviewResult(
            reviewer="Risk Assessment",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.75,
        )

    def _aggregate_reviews(self, reviews: List[ReviewResult]) -> ReviewResult:
        """Aggregate multiple reviews into a single result."""
        # Weighted average score
        weights = {"Dosimetry Review": 1.5, "OAR Review": 1.3,
                   "Protocol Review": 1.0, "Risk Assessment": 1.2}

        total_weight = 0
        weighted_score = 0
        for review in reviews:
            w = weights.get(review.reviewer, 1.0)
            weighted_score += review.score * w
            total_weight += w

        final_score = weighted_score / total_weight if total_weight > 0 else 5.0

        # Aggregate concerns and suggestions
        all_concerns = []
        all_suggestions = []
        for review in reviews:
            all_concerns.extend(review.concerns)
            all_suggestions.extend(review.suggestions)

        # Determine overall decision
        decisions = [r.decision for r in reviews]
        if "reject" in decisions:
            final_decision = "reject"
        elif "escalate" in decisions:
            final_decision = "escalate"
        elif "conditional" in decisions:
            final_decision = "conditional"
        else:
            final_decision = "pass"

        # Calculate confidence
        avg_confidence = sum(r.confidence for r in reviews) / len(reviews) if reviews else 0.5

        return ReviewResult(
            reviewer="Plan Review (Aggregated)",
            decision=final_decision,
            score=final_score,
            concerns=list(set(all_concerns)),  # Deduplicate
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

    def _build_reasoning(self, reviews: List[ReviewResult]) -> str:
        """Build reasoning summary from reviews."""
        lines = ["Plan Review Summary:"]
        for review in reviews:
            lines.append(f"- {review.reviewer}: {review.decision} (score={review.score:.1f})")
            if review.concerns:
                for concern in review.concerns[:2]:  # Top 2 concerns
                    lines.append(f"  ⚠ {concern}")
        return "\n".join(lines)
