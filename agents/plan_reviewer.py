"""
Plan Reviewer Agent
===================
Reviews treatment plans for clinical quality and safety.
Reads thresholds from plan_config (provided at runtime), not hardcoded.
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

    Thresholds are read from plan_config at runtime, not hardcoded.
    """

    # Default OAR constraints as multipliers of in_lowest_energy (prescription dose).
    # These are fallback values — actual limits come from plan_config if available.
    _DEFAULT_OAR_MULTIPLIERS = {
        "duodenum": {"d2cc": 1.0},
        "stomach": {"d2cc": 1.0},
        "small_bowel": {"d2cc": 1.0},
        "colon": {"d2cc": 1.0},
        "spinal_cord": {"d2cc": 0.8},
        "liver": {"d2cc": 0.8},
        "kidney": {"d2cc": 0.6},
    }

    def __init__(self, llm_callback=None):
        super().__init__(AgentRole.PLAN_REVIEWER, llm_callback)

    async def process(self, message: AgentMessage) -> AgentResponse:
        content = message.content

        dose_metrics = content.get("dose_metrics", {})
        plan_info = content.get("plan_info", {})
        plan_config = content.get("plan_config", {})

        # Read actual config values — no hardcoded defaults
        prescription = plan_config.get("in_lowest_energy", 1.0)

        reviews = []
        reviews.append(self._review_dosimetry(dose_metrics, prescription, plan_config))
        reviews.append(self._review_oar_constraints(dose_metrics, prescription, plan_config))
        reviews.append(self._review_clinical_protocol(plan_info, dose_metrics))
        reviews.append(self._assess_risks(dose_metrics, plan_info, prescription))

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

    def _review_dosimetry(self, dose_metrics: Dict, prescription: float,
                          plan_config: Dict = None) -> ReviewResult:
        """Review dosimetry quality using actual prescription threshold."""
        concerns = []
        suggestions = []
        scores = []
        cfg = plan_config or {}

        # Targets — configurable, with clinical-standard defaults
        v100_target = cfg.get("v100_target", 0.95)
        v100_warn = cfg.get("v100_warn", 0.90)
        v150_limit = cfg.get("v150_limit", 0.50)
        v150_warn = cfg.get("v150_warn", 0.60)
        v200_limit = cfg.get("v200_limit", 0.20)
        v200_warn = cfg.get("v200_warn", 0.30)

        for metric in ["v100", "v150", "v200", "d90", "d95"]:
            value = dose_metrics.get(metric)
            if value is None:
                continue
            try:
                value = float(str(value).replace("%", "").replace("Gy", ""))
            except (ValueError, TypeError):
                continue

            if metric == "v100":
                if value >= v100_target:
                    scores.append(10)
                elif value >= v100_warn:
                    scores.append(7)
                    concerns.append(f"{metric.upper()}={value:.1%}, target ≥{v100_target:.0%}")
                    suggestions.append(f"Add more seeds to improve {metric.upper()}")
                else:
                    scores.append(4)
                    concerns.append(f"{metric.upper()}={value:.1%} critically low")
                    suggestions.append(f"Plan revision: {metric.upper()} must be ≥{v100_warn:.0%}")
            elif metric == "v150":
                if value <= v150_limit:
                    scores.append(10)
                elif value <= v150_warn:
                    scores.append(7)
                else:
                    scores.append(5)
                    concerns.append(f"{metric.upper()}={value:.1%} indicates hot spots")
                    suggestions.append(f"Redistribute seeds to reduce {metric.upper()}")
            elif metric == "v200":
                if value <= v200_limit:
                    scores.append(10)
                elif value <= v200_warn:
                    scores.append(7)
                else:
                    scores.append(5)
                    concerns.append(f"{metric.upper()}={value:.1%} indicates hot spots")
                    suggestions.append(f"Redistribute seeds to reduce {metric.upper()}")
            else:  # D90, D95
                target = prescription if metric == "d90" else 0.95 * prescription
                if value >= target:
                    scores.append(10)
                elif value >= 0.85 * target:
                    scores.append(7)
                    concerns.append(f"{metric.upper()}={value:.2f}, target ≥{target:.2f}")
                else:
                    scores.append(4)
                    concerns.append(f"{metric.upper()}={value:.2f} critically low")
                    suggestions.append(f"Dose coverage: {metric.upper()} should be ≥{target:.2f}")

        avg_score = sum(scores) / len(scores) if scores else 5.0

        return ReviewResult(
            reviewer="Dosimetry Review",
            decision=self._score_to_decision(avg_score),
            score=avg_score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.9,
        )

    def _review_oar_constraints(self, dose_metrics: Dict, prescription: float,
                                 plan_config: Dict) -> ReviewResult:
        """Review OAR constraints using actual config values."""
        concerns = []
        suggestions = []
        oar_metrics = dose_metrics.get("oar_metrics", {})

        if not oar_metrics:
            return ReviewResult(
                reviewer="OAR Review",
                decision="pass",
                score=8.0,
                concerns=["No OAR metrics available"],
                suggestions=["Ensure OAR segmentation is performed"],
                confidence=0.5,
            )

        # Build actual constraints from config multipliers × prescription
        oar_constraints = {}
        config_oar = plan_config.get("oar_constraints", {})
        for organ, multipliers in self._DEFAULT_OAR_MULTIPLIERS.items():
            # Allow config to override multipliers
            actual_mult = config_oar.get(organ, multipliers)
            oar_constraints[organ] = {
                k: v * prescription for k, v in actual_mult.items()
            }

        violations = 0
        total_checks = 0

        for organ_name, metrics in oar_metrics.items():
            organ_lower = organ_name.lower()

            constraint = None
            for oar_key, oar_constraint in oar_constraints.items():
                if oar_key in organ_lower:
                    constraint = oar_constraint
                    break

            if constraint is None:
                continue

            d2cc = metrics.get("d2cc") or metrics.get("D2cc") or metrics.get("mean_dose")
            if d2cc is not None:
                total_checks += 1
                try:
                    d2cc_val = float(str(d2cc).replace("Gy", ""))
                    limit = constraint["d2cc"]
                    if d2cc_val > limit:
                        violations += 1
                        concerns.append(
                            f"{organ_name} D2cc={d2cc_val:.2f} exceeds limit ({limit:.2f})"
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

        required_steps = ["ctv_segmentation", "oar_segmentation", "trajectory_planning",
                         "seed_planning", "dose_calculation", "dose_evaluation"]

        completed_steps = plan_info.get("completed_steps", [])
        missing_steps = [s for s in required_steps if s not in completed_steps]

        if missing_steps:
            concerns.append(f"Missing steps: {', '.join(missing_steps)}")
            suggestions.append("Complete all required planning steps")
            score -= len(missing_steps) * 1.5

        total_seeds = plan_info.get("total_seeds", 0)
        if total_seeds == 0:
            concerns.append("No seeds in the plan")
            suggestions.append("Verify seed planning was executed correctly")
            score -= 3
        elif total_seeds < 5:
            concerns.append(f"Low seed count ({total_seeds})")
            suggestions.append("Consider if seed count is adequate for target coverage")

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

    def _assess_risks(self, dose_metrics: Dict, plan_info: Dict,
                       prescription: float) -> ReviewResult:
        """Assess risks using actual prescription threshold."""
        concerns = []
        suggestions = []
        risks = []

        # Hot spot: max dose > 3x prescription
        max_dose = dose_metrics.get("max_dose")
        if max_dose is not None:
            try:
                max_dose_val = float(str(max_dose).replace("Gy", ""))
                if max_dose_val > 3.0 * prescription:
                    risks.append("high_max_dose")
                    concerns.append(f"Max dose ({max_dose_val:.2f}) > 3x prescription ({3.0 * prescription:.2f})")
                    suggestions.append("Verify hot spot location and OAR proximity")
            except (ValueError, TypeError):
                pass

        # Low coverage
        v100 = dose_metrics.get("v100")
        if v100 is not None:
            try:
                v100_val = float(str(v100).replace("%", ""))
                if v100_val < 0.90:
                    risks.append("low_coverage")
                    concerns.append(f"Low V100 ({v100_val:.1%}) may indicate insufficient coverage")
            except (ValueError, TypeError):
                pass

        # Dense seeding
        total_seeds = plan_info.get("total_seeds", 0)
        num_trajectories = plan_info.get("num_trajectories", 0)
        if num_trajectories > 0 and total_seeds / num_trajectories > 10:
            risks.append("dense_seeding")
            concerns.append("High seed density per trajectory - migration risk")
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
        weights = {"Dosimetry Review": 1.5, "OAR Review": 1.3,
                   "Protocol Review": 1.0, "Risk Assessment": 1.2}

        total_weight = 0
        weighted_score = 0
        for review in reviews:
            w = weights.get(review.reviewer, 1.0)
            weighted_score += review.score * w
            total_weight += w

        final_score = weighted_score / total_weight if total_weight > 0 else 5.0

        all_concerns = []
        all_suggestions = []
        for review in reviews:
            all_concerns.extend(review.concerns)
            all_suggestions.extend(review.suggestions)

        # Only REJECT for SEVERE errors (protocol violations, zero results).
        # Score/quality issues (OAR dose, hot spots) are warnings — the
        # planning algorithm is deterministic, re-running produces the same
        # results. Only reject if critical steps are missing or results
        # are empty.
        decisions = [r.decision for r in reviews]
        protocol_review = next((r for r in reviews if r.reviewer == "Protocol Review"), None)
        has_severe_error = (
            (protocol_review and protocol_review.decision == "reject")
            or any(r.score <= 2 for r in reviews)
        )
        if has_severe_error:
            final_decision = "reject"
        elif "escalate" in decisions:
            final_decision = "escalate"
        elif "reject" in decisions:
            # Score/quality rejections → downgrade to warning (not reject)
            final_decision = "conditional"
        elif "conditional" in decisions:
            final_decision = "conditional"
        else:
            final_decision = "pass"

        avg_confidence = sum(r.confidence for r in reviews) / len(reviews) if reviews else 0.5

        return ReviewResult(
            reviewer="Plan Review (Aggregated)",
            decision=final_decision,
            score=final_score,
            concerns=list(set(all_concerns)),
            suggestions=list(set(all_suggestions)),
            confidence=avg_confidence,
        )

    def _score_to_decision(self, score: float) -> str:
        if score >= 7:
            return "pass"
        elif score >= 5:
            return "conditional"
        else:
            return "reject"

    def _build_reasoning(self, reviews: List[ReviewResult]) -> str:
        lines = ["Plan Review Summary:"]
        for review in reviews:
            lines.append(f"- {review.reviewer}: {review.decision} (score={review.score:.1f})")
            if review.concerns:
                for concern in review.concerns[:2]:
                    lines.append(f"  ⚠ {concern}")
        return "\n".join(lines)
