"""
Quality Gate
============
Orchestrates review agents and gates critical outputs.
Inspired by OpenCode's verification patterns and LangChain's output parsers.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    ReviewResult, GateResult, Priority
)

logger = logging.getLogger(__name__)


class QualityGate:
    """
    Quality gate that reviews critical outputs before presentation.

    Features:
    - Parallel review by multiple agents
    - Configurable triggers for mandatory/optional reviews
    - Aggregation of review results
    - Escalation to human review when needed
    """

    # Output types that MUST be reviewed
    MANDATORY_REVIEWS = {
        "treatment_plan",
        "dose_evaluation",
        "clinical_recommendation",
        "web_search_medical",
    }

    # Output types that CAN be reviewed
    OPTIONAL_REVIEWS = {
        "segmentation_result",
        "trajectory_plan",
        "general_response",
        "knowledge_response",
    }

    def __init__(self, agents: Dict[str, Any] = None):
        """
        Initialize quality gate.

        Args:
            agents: Dictionary of review agents
        """
        self.agents = agents or {}
        self.review_history: List[GateResult] = []
        self._review_count = 0
        self._pass_count = 0
        self._reject_count = 0
        logger.info(f"QualityGate initialized with agents: {list(self.agents.keys())}")

    def register_agent(self, name: str, agent: Any):
        """Register a review agent."""
        self.agents[name] = agent
        logger.info(f"Registered agent: {name}")

    async def review(self, output_type: str, content: Any,
                    context: Dict = None,
                    force_review: bool = False) -> GateResult:
        """
        Review content through quality gate.

        Args:
            output_type: Type of output being reviewed
            content: The content to review
            context: Additional context
            force_review: Force review even for optional types

        Returns:
            GateResult with review decision
        """
        self._review_count += 1

        # Check if review is needed
        needs_review = (
            output_type in self.MANDATORY_REVIEWS or
            output_type in self.OPTIONAL_REVIEWS or
            force_review
        )

        if not needs_review:
            return GateResult(
                passed=True,
                decision="pass",
                reviews=[],
                final_message="No review required",
                requires_human_review=False,
            )

        # Prepare review message
        review_content = {
            "output_type": output_type,
            "content": content,
            "context": context or {},
        }

        # Determine which agents to use
        agents_to_use = self._select_agents(output_type)

        if not agents_to_use:
            # Review is append-only and must not hide the clinical output, but
            # unavailable reviewers are not equivalent to a successful review.
            logger.warning(f"No review agents available for {output_type}")
            return GateResult(
                passed=True,
                decision="conditional",
                reviews=[],
                final_message="No review agents available",
                requires_human_review=True,
            )

        # Run reviews in parallel
        reviews = await self._parallel_review(agents_to_use, review_content, output_type)

        # Aggregate results
        gate_result = self._aggregate_reviews(reviews, output_type)

        # Update statistics
        if gate_result.passed:
            self._pass_count += 1
        elif gate_result.decision == "reject":
            self._reject_count += 1

        # Record history
        self.review_history.append(gate_result)

        logger.info(
            f"Quality gate for {output_type}: {gate_result.decision} "
            f"(passed={gate_result.passed}, reviews={len(reviews)})"
        )

        return gate_result

    def _select_agents(self, output_type: str) -> Dict[str, Any]:
        """Select which agents to use for review."""
        selected = {}

        # Plan reviewer for clinical outputs
        if output_type in {"treatment_plan", "dose_evaluation", "clinical_recommendation"}:
            if "plan_reviewer" in self.agents:
                selected["plan_reviewer"] = self.agents["plan_reviewer"]

        # Fact checker for knowledge/search AND clinical outputs (verify claims)
        if output_type in {"web_search_medical", "knowledge_response",
                           "treatment_plan", "clinical_recommendation"}:
            if "fact_checker" in self.agents:
                selected["fact_checker"] = self.agents["fact_checker"]

        # SafetyGuardian reasons over dose/plan structure, so keep it on
        # clinical plan outputs only. FactChecker handles web-search quality.
        if output_type in {"treatment_plan", "dose_evaluation", "clinical_recommendation"}:
            if "safety_guardian" in self.agents:
                selected["safety_guardian"] = self.agents["safety_guardian"]

        # If no specific agent selected, use all available
        if not selected:
            selected = self.agents.copy()

        return selected

    # Minimal static context — only unit metadata that never changes.
    # Dynamic config (in_lowest_energy, seed_info, etc.) comes from plan_config
    # stored in agent memory at planning time.
    _STATIC_CONTEXT = {
        "dose_units": "NORMALIZED (0-255 range), NOT Gy",
        "planning_grid": [128, 128, 64],
    }

    def _prepare_content_for_agent(self, agent_name: str, content: Dict,
                                   output_type: str) -> Dict:
        """Prepare content in the format expected by each agent."""
        # Extract the actual data from the wrapper structure
        # The review_content has: {"output_type": ..., "content": actual_data, "context": ...}
        actual_data = content.get("content", content)
        context = content.get("context", {})

        # Merge static context with any dynamic context
        if isinstance(context, dict):
            context = {**self._STATIC_CONTEXT, **context}
        else:
            context = self._STATIC_CONTEXT

        # If content already has the right structure, pass it through
        if "dose_metrics" in actual_data or "claims" in actual_data:
            # Ensure plan_config is included for all clinical reviewers
            if agent_name in ["plan_reviewer", "safety_guardian"]:
                return {
                    "dose_metrics": actual_data.get("dose_metrics", {}),
                    "plan_config": actual_data.get("plan_config", {}),
                    "plan_info": actual_data.get("plan_info", context),
                    "context": context,
                    "output_type": output_type,
                }
            elif agent_name == "fact_checker":
                return {
                    "claims": actual_data.get("claims", []),
                    "sources": actual_data.get("sources", []),
                    "plan_config": actual_data.get("plan_config", {}),
                    "context": context,
                }
            else:
                return actual_data

        # Otherwise, wrap the content appropriately
        if agent_name == "plan_reviewer":
            return {
                "dose_metrics": actual_data if isinstance(actual_data, dict) else {},
                "plan_config": actual_data.get("plan_config", {}) if isinstance(actual_data, dict) else {},
                "plan_info": context if isinstance(context, dict) else {},
                "context": str(context),
            }
        elif agent_name == "fact_checker":
            return {
                "claims": [str(actual_data)] if actual_data else [],
                "sources": context.get("sources", []) if isinstance(context, dict) else [],
                "context": str(context),
            }
        elif agent_name == "safety_guardian":
            return {
                "dose_metrics": actual_data if isinstance(actual_data, dict) else {},
                "plan_config": actual_data.get("plan_config", {}) if isinstance(actual_data, dict) else {},
                "plan_info": context if isinstance(context, dict) else {},
                "output_type": output_type,
            }
        else:
            return content

    async def _parallel_review(self, agents: Dict[str, Any],
                              content: Dict, output_type: str = "unknown") -> List[ReviewResult]:
        """Run reviews in parallel."""
        tasks = []

        for name, agent in agents.items():
            task = self._run_single_review(name, agent, content, output_type)
            tasks.append(task)

        # Run all tasks with timeout
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Parallel review failed: {e}")
            results = []

        # Filter out exceptions
        valid_results = []
        for result in results:
            if isinstance(result, ReviewResult):
                valid_results.append(result)
            elif isinstance(result, Exception):
                logger.warning("Review agent failed", exc_info=(type(result), result, result.__traceback__))

        return valid_results

    # Map agent names to their correct AgentRole
    _AGENT_ROLE_MAP = {
        "plan_reviewer": AgentRole.PLAN_REVIEWER,
        "fact_checker": AgentRole.FACT_CHECKER,
        "safety_guardian": AgentRole.SAFETY_GUARDIAN,
    }

    async def _run_single_review(self, name: str, agent: Any,
                                content: Dict, output_type: str = "unknown") -> ReviewResult:
        """Run a single review agent."""
        try:
            # Prepare content for this specific agent
            agent_content = self._prepare_content_for_agent(name, content, output_type)

            message = AgentMessage(
                sender=AgentRole.ROUTER,
                receiver=self._AGENT_ROLE_MAP.get(name, AgentRole.PLAN_REVIEWER),
                message_type=MessageType.REVIEW,
                content=agent_content,
                priority=Priority.HIGH,
            )

            response = await agent.handle_message(message)

            if response.success and isinstance(response.result, ReviewResult):
                return response.result
            else:
                # Create a default result
                return ReviewResult(
                    reviewer=name,
                    decision="conditional",
                    score=5.0,
                    concerns=[f"Review agent {name} returned invalid result"],
                    confidence=0.3,
                )

        except Exception as e:
            logger.error(f"Review agent {name} failed: {e}")
            return ReviewResult(
                reviewer=name,
                decision="conditional",
                score=5.0,
                concerns=[f"Review agent {name} failed: {str(e)}"],
                confidence=0.2,
            )

    def _aggregate_reviews(self, reviews: List[ReviewResult],
                          output_type: str) -> GateResult:
        """Aggregate review results into gate decision."""
        if not reviews:
            return GateResult(
                passed=True,
                decision="conditional",
                reviews=[],
                final_message="No reviews available",
                requires_human_review=True,
            )

        # Count decisions
        decisions = [r.decision for r in reviews]
        conditional_count = decisions.count("conditional")
        reject_count = decisions.count("reject")
        escalate_count = decisions.count("escalate")

        # Calculate weighted score
        total_weight = sum(r.confidence for r in reviews)
        if total_weight > 0:
            weighted_score = sum(r.score * r.confidence for r in reviews) / total_weight
        else:
            weighted_score = sum(r.score for r in reviews) / len(reviews)

        # Determine final decision
        # APPEND-ONLY MODE (2026-06-27): never reject or retry.
        # All review results are passed through as supplementary info.
        # BY DESIGN: The LLM agent (BrachyAgent) is the final decision maker,
        # not this gate. Sub-agents (SafetyGuardian, PlanReviewer, FactChecker)
        # are advisory — see system_prompt.md "Sub-Agent Results Are ADVISORY".
        # Blocking clinical output here would be dangerous: a false reject from
        # any sub-agent would prevent all planning. Instead, concerns are appended
        # to the response for the LLM to weigh independently.
        # These bands are software review-confidence bands, not clinical dose
        # constraints. They only control the advisory label and never alter a
        # treatment plan or suppress its output.
        if reject_count > 0:
            final_decision = "conditional"
            passed = True  # don't block — append review to response
            requires_human = True
        elif escalate_count > 0:
            final_decision = "conditional"
            passed = True
            requires_human = True
        elif weighted_score < 5.0:
            final_decision = "conditional"
            passed = True
            requires_human = True
        elif conditional_count > len(reviews) / 2:
            final_decision = "conditional"
            passed = True
            requires_human = True
        elif weighted_score < 7.0:
            final_decision = "conditional"
            passed = True
            requires_human = False
        else:
            final_decision = "pass"
            passed = True
            requires_human = False

        # Aggregate concerns and suggestions
        all_concerns = []
        all_suggestions = []
        for review in reviews:
            all_concerns.extend(review.concerns)
            all_suggestions.extend(review.suggestions)

        # Build final message
        final_message = self._build_final_message(reviews, final_decision, weighted_score)

        return GateResult(
            passed=passed,
            decision=final_decision,
            reviews=reviews,
            final_message=final_message,
            requires_human_review=requires_human,
        )

    def _build_final_message(self, reviews: List[ReviewResult],
                            decision: str, score: float) -> str:
        """Build final message from reviews."""
        lines = [f"Quality Gate: {decision.upper()} (score={score:.1f})"]

        # Add review summaries.
        for review in reviews:
            status_icon = {
                "pass": "[OK]",
                "conditional": "[WARN]",
                "reject": "[REJECT]",
                "escalate": "[ESCALATE]",
            }.get(review.decision, "?")
            lines.append(f"{status_icon} {review.reviewer}: {review.decision}")

        # Add top concerns.
        all_concerns = self._dedupe_review_text([c for r in reviews for c in r.concerns])
        if all_concerns:
            lines.append("\nKey Concerns:")
            for concern in all_concerns[:3]:
                lines.append(f"  - {concern}")

        # Add top suggestions.
        all_suggestions = self._dedupe_review_text([s for r in reviews for s in r.suggestions])
        if all_suggestions:
            lines.append("\nSuggestions:")
            for suggestion in all_suggestions[:3]:
                lines.append(f"  - {suggestion}")

        return "\n".join(lines)

    @staticmethod
    def _dedupe_review_text(items: List[str]) -> List[str]:
        """Deduplicate review text while preserving order and common semantics."""
        result: List[str] = []
        seen = set()
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            lowered = " ".join(text.lower().split())
            if "oar" in lowered and "source-backed" in lowered and "constraint" in lowered:
                key = "missing_oar_constraints"
            elif "target" in lowered and "source-backed" in lowered:
                key = "missing_target_thresholds"
            else:
                key = lowered
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    def get_stats(self) -> Dict:
        """Get quality gate statistics."""
        return {
            "total_reviews": self._review_count,
            "passed": self._pass_count,
            "rejected": self._reject_count,
            "pass_rate": self._pass_count / self._review_count if self._review_count > 0 else 0,
            "registered_agents": list(self.agents.keys()),
            "history_size": len(self.review_history),
        }

    def clear_history(self):
        """Clear review history."""
        self.review_history.clear()
        self._review_count = 0
        self._pass_count = 0
        self._reject_count = 0
