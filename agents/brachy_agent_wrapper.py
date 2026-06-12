"""
BrachyAgent Multi-Agent Wrapper
================================
Wraps the existing BrachyAgent with multi-agent capabilities.
This is the main integration point between the multi-agent system and BrachyBot.
"""

import logging
from typing import Dict, Any, Optional, Callable
from .orchestrator import MultiAgentOrchestrator

logger = logging.getLogger(__name__)


class BrachyAgentMultiAgentWrapper:
    """
    Wraps BrachyAgent with multi-agent capabilities.

    This class:
    1. Intercepts outputs that need review
    2. Routes requests through the orchestrator
    3. Adds quality gate results to responses
    4. Provides a clean interface for integration
    """

    # Output types that trigger quality review
    REVIEWABLE_OUTPUTS = {
        "treatment_plan",
        "dose_evaluation",
        "clinical_recommendation",
        "web_search_medical",
    }

    def __init__(self, llm_callback: Callable = None):
        """
        Initialize the wrapper.

        Args:
            llm_callback: Function to call LLM
        """
        self.orchestrator = MultiAgentOrchestrator(llm_callback=llm_callback)
        self._enabled = True
        logger.info("BrachyAgentMultiAgentWrapper initialized")

    @property
    def enabled(self) -> bool:
        """Check if multi-agent review is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable multi-agent review."""
        self._enabled = value
        logger.info(f"Multi-agent review {'enabled' if value else 'disabled'}")

    async def process_request(self, user_input: str) -> Dict[str, Any]:
        """
        Process a user request through the multi-agent system.

        Args:
            user_input: User's input text

        Returns:
            Dict with routing decision and any pre-context
        """
        if not self._enabled:
            return {"routing": None, "pre_context": None}

        try:
            # Route the request
            routing = await self.orchestrator.route_request(user_input)

            return {
                "routing": routing,
                "pre_context": {
                    "intent": routing.intent,
                    "complexity": routing.complexity,
                    "requires_review": routing.requires_review,
                    "agents_needed": [a.value for a in routing.agents_needed],
                },
            }
        except Exception as e:
            logger.error(f"Multi-agent request processing failed: {e}")
            return {"routing": None, "pre_context": None}

    async def review_output(self, output_type: str, content: Any,
                           context: Dict = None,
                           lang: str = "en") -> Optional[Dict[str, Any]]:
        """
        Review an output through the quality gate.

        Args:
            output_type: Type of output
            content: The content to review
            context: Additional context
            lang: Language for display text ("en" or "zh")

        Returns:
            Dict with review result, or None if review not needed
        """
        if not self._enabled:
            return None

        # Check if this output type needs review
        if output_type not in self.REVIEWABLE_OUTPUTS:
            return None

        try:
            gate_result = await self.orchestrator.review_output(
                output_type=output_type,
                content=content,
                context=context,
            )

            # Format for display with correct language
            display_text = self.orchestrator.format_review_for_display(gate_result, lang=lang)

            return {
                "passed": gate_result.passed,
                "decision": gate_result.decision,
                "display_text": display_text,
                "requires_human_review": gate_result.requires_human_review,
                "reviews": [
                    {
                        "reviewer": r.reviewer,
                        "decision": r.decision,
                        "score": r.score,
                        "concerns": r.concerns,
                        "suggestions": r.suggestions,
                    }
                    for r in gate_result.reviews
                ],
            }
        except Exception as e:
            logger.error(f"Multi-agent review failed: {e}")
            return None

    async def review_treatment_plan(self, dose_metrics: Dict,
                                   plan_info: Dict,
                                   plan_config: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Convenience method to review a treatment plan.

        Args:
            dose_metrics: Dose metrics dict
            plan_info: Plan information dict
            plan_config: Actual planning config (in_lowest_energy, seed_info, etc.)

        Returns:
            Review result dict or None
        """
        return await self.review_output(
            output_type="treatment_plan",
            content={
                "dose_metrics": dose_metrics,
                "plan_info": plan_info,
                "plan_config": plan_config or {},
            },
        )

    async def review_web_search(self, claims: list,
                               sources: list) -> Optional[Dict[str, Any]]:
        """
        Convenience method to review web search results.

        Args:
            claims: List of claims to verify
            sources: List of sources

        Returns:
            Review result dict or None
        """
        return await self.review_output(
            output_type="web_search_medical",
            content={
                "claims": claims,
                "sources": sources,
            },
        )

    def get_stats(self) -> Dict:
        """Get wrapper statistics."""
        return self.orchestrator.get_stats()

    def clear_history(self):
        """Clear all histories."""
        self.orchestrator.clear_history()
