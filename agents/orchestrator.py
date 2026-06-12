"""
Multi-Agent Orchestrator
========================
Coordinates all agents in the multi-agent system.
Integrates with BrachyAgent's existing architecture.
"""

import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Callable, AsyncGenerator
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    RoutingDecision, ReviewResult, GateResult, Priority
)
from communication.message_bus import MessageBus
from agents.router_agent import RouterAgent
from agents.plan_reviewer import PlanReviewer
from agents.fact_checker import FactChecker
from agents.safety_guardian import SafetyGuardian
from quality.quality_gate import QualityGate

logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """
    Orchestrates the multi-agent system for BrachyBot.

    Features:
    1. Automatic routing of user requests
    2. Quality gate for critical outputs
    3. Parallel agent execution
    4. Integration with existing BrachyAgent
    """

    def __init__(self, llm_callback: Callable = None):
        """
        Initialize the orchestrator.

        Args:
            llm_callback: Function to call LLM (prompt) -> response
        """
        self.llm_callback = llm_callback

        # Create message bus
        self.message_bus = MessageBus()

        # Create agents
        self.router = RouterAgent(llm_callback=llm_callback)
        self.plan_reviewer = PlanReviewer(llm_callback=llm_callback)
        self.fact_checker = FactChecker(llm_callback=llm_callback)
        self.safety_guardian = SafetyGuardian(llm_callback=llm_callback)

        # Create quality gate
        self.quality_gate = QualityGate(agents={
            "plan_reviewer": self.plan_reviewer,
            "fact_checker": self.fact_checker,
            "safety_guardian": self.safety_guardian,
        })

        # Statistics
        self._request_count = 0
        self._review_count = 0
        self._gate_pass_count = 0
        self._gate_reject_count = 0

        logger.info("MultiAgentOrchestrator initialized")

    async def route_request(self, user_input: str) -> RoutingDecision:
        """
        Route user request to appropriate agents.

        Args:
            user_input: User's input text

        Returns:
            RoutingDecision with intent, complexity, and agents needed
        """
        message = AgentMessage(
            sender=AgentRole.USER,
            receiver=AgentRole.ROUTER,
            message_type=MessageType.REQUEST,
            content=user_input,
        )

        response = await self.router.handle_message(message)

        if response.success and isinstance(response.result, RoutingDecision):
            return response.result
        else:
            # Fallback routing
            return RoutingDecision(
                intent="general",
                complexity="medium",
                agents_needed=[AgentRole.CLINICAL_EXECUTOR],
                requires_review=False,
                reasoning="Fallback routing",
                confidence=0.3,
            )

    async def review_output(self, output_type: str, content: Any,
                           context: Dict = None) -> GateResult:
        """
        Review an output through the quality gate.

        Args:
            output_type: Type of output (treatment_plan, dose_evaluation, etc.)
            content: The content to review
            context: Additional context

        Returns:
            GateResult with review decision
        """
        self._review_count += 1

        gate_result = await self.quality_gate.review(
            output_type=output_type,
            content=content,
            context=context,
        )

        if gate_result.passed:
            self._gate_pass_count += 1
        else:
            self._gate_reject_count += 1

        return gate_result

    async def should_review(self, output_type: str) -> bool:
        """
        Check if an output type should be reviewed.

        Args:
            output_type: Type of output

        Returns:
            True if review is needed
        """
        return output_type in QualityGate.MANDATORY_REVIEWS

    def format_review_for_display(self, gate_result: GateResult) -> str:
        """
        Format review result for display to user.

        Args:
            gate_result: The gate result to format

        Returns:
            Formatted string
        """
        if gate_result.passed and gate_result.decision == "pass":
            # Don't show review for passing results
            return ""

        lines = []

        # Header
        icon = {
            "pass": "✅",
            "conditional": "⚠️",
            "reject": "❌",
            "escalate": "🔔",
        }.get(gate_result.decision, "❓")

        lines.append(f"{icon} **Quality Review**: {gate_result.decision.upper()}")

        # Add concerns if any
        all_concerns = []
        for review in gate_result.reviews:
            all_concerns.extend(review.concerns)

        if all_concerns:
            lines.append("\n**Concerns:**")
            for concern in list(set(all_concerns))[:5]:
                lines.append(f"- {concern}")

        # Add suggestions if any
        all_suggestions = []
        for review in gate_result.reviews:
            all_suggestions.extend(review.suggestions)

        if all_suggestions:
            lines.append("\n**Suggestions:**")
            for suggestion in list(set(all_suggestions))[:3]:
                lines.append(f"- {suggestion}")

        # Add human review notice
        if gate_result.requires_human_review:
            lines.append("\n🔔 **Requires Human Review**")

        return "\n".join(lines)

    def get_stats(self) -> Dict:
        """Get orchestrator statistics."""
        return {
            "request_count": self._request_count,
            "review_count": self._review_count,
            "gate_pass_count": self._gate_pass_count,
            "gate_reject_count": self._gate_reject_count,
            "gate_pass_rate": (
                self._gate_pass_count / self._review_count
                if self._review_count > 0 else 0
            ),
            "router_stats": self.router.get_stats(),
            "quality_gate_stats": self.quality_gate.get_stats(),
        }

    def clear_history(self):
        """Clear all agent histories."""
        self.router.clear_history()
        self.plan_reviewer.clear_history()
        self.fact_checker.clear_history()
        self.safety_guardian.clear_history()
        self.quality_gate.clear_history()
        self._request_count = 0
        self._review_count = 0
        self._gate_pass_count = 0
        self._gate_reject_count = 0
