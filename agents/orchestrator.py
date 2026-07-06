"""
Multi-Agent Orchestrator
========================
Coordinates all agents in the multi-agent system.
Integrates with BrachyAgent's existing architecture.
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Any, Optional, Callable
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    RoutingDecision, ReviewResult, GateResult, Priority
)
from communication.message_bus import MessageBus
from agents.router_agent import RouterAgent
from agents.plan_reviewer import PlanReviewer
from agents.fact_checker import FactChecker
from agents.safety_guardian import SafetyGuardian
from agents.completeness_checker import CompletenessChecker
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
        self.completeness_checker = CompletenessChecker(llm_callback=llm_callback)

        # Create quality gate
        self.quality_gate = QualityGate(agents={
            "plan_reviewer": self.plan_reviewer,
            "fact_checker": self.fact_checker,
            "safety_guardian": self.safety_guardian,
        })

        # Shared context for all sub-agents
        self._global_context = {}

        # Statistics
        self._request_count = 0
        self._review_count = 0
        self._gate_pass_count = 0
        self._gate_reject_count = 0

        logger.info("MultiAgentOrchestrator initialized")

    def update_global_context(self, context: Dict[str, Any]):
        """Update the shared context that all sub-agents can access.

        Called by the main agent before review phase to provide
        full situational awareness to sub-agents.

        Args:
            context: dict with keys like:
                - patient_info: {ct_path, ct_size, spacing, ...}
                - segmentation: {ctv_voxels, oar_count, organ_names, ...}
                - planning: {total_seeds, num_trajectories, mode, ...}
                - conversation_summary: str (recent user messages)
                - tool_history: list of {tool, status, ...}
                - user_message: str (current user request)
                - ui_state: {ct_loaded, plan_mode, ...}
        """
        self._global_context = context

    def _build_agent_context(self, role_specific: Dict) -> Dict:
        """Build full context for a sub-agent by merging global + role-specific."""
        overlap = set(self._global_context).intersection(role_specific)
        if overlap:
            logger.debug("Role-specific context overrides global keys: %s", sorted(overlap))
        return {**self._global_context, **role_specific}

    async def _distill_context(self, role: str, role_specific: Dict) -> Dict:
        """Use LLM to distill relevant context for a specific sub-agent task.

        Instead of dumping all raw data, the main agent (via this method)
        selects and organizes the information most relevant to the
        sub-agent's specific task. This improves judgment accuracy.

        Falls back to raw merge if LLM is unavailable.
        """
        if not self.llm_callback:
            return self._build_agent_context(role_specific)

        # Build raw context for the distiller
        ctx = self._global_context
        pt = ctx.get("patient_info", {})
        seg = ctx.get("segmentation", {})
        plan = ctx.get("planning", {})
        conv = ctx.get("conversation_state", {})
        tools = ctx.get("tool_history", [])
        user_msg = ctx.get("user_message", "")
        resp = ctx.get("response_preview", "")

        # Role-specific distillation prompts
        distill_prompts = {
            "plan_reviewer": f"""You are a context distiller for a PlanReviewer sub-agent.
The PlanReviewer will evaluate a brachytherapy treatment plan.

From the following information, extract ONLY the facts relevant to plan quality assessment.
Output a concise bullet-point summary (max 200 words).

## User Request
{user_msg}

## Clinical Context
- Tumor: {pt.get('tumor_type', 'unknown')}
- CTV: {seg.get('ctv_voxels', 0)} voxels ({(seg.get('ctv_volume_mm3', 0) or 0)/1000:.1f} cm³)
- OARs: {seg.get('oar_count', 0)} organs (top: {', '.join(seg.get('top_oars', []))})
- Seeds: {plan.get('total_seeds', 0)}, Trajectories: {plan.get('num_trajectories', 0)}

## Tools Executed
{', '.join(tools)}

## Role-Specific Data
{json.dumps(role_specific, ensure_ascii=False, default=str)[:500]}

## Output
Bullet-point summary of what the PlanReviewer needs to know:""",

            "fact_checker": f"""You are a context distiller for a FactChecker sub-agent.
The FactChecker will verify if search results are reliable and relevant.

From the following information, extract ONLY the facts relevant to source verification.
Output a concise bullet-point summary (max 150 words).

## User Request
{user_msg}

## Search Context
- Tools: {', '.join(tools)}
- Claims to check: {json.dumps(role_specific.get('claims', []), ensure_ascii=False)[:300]}
- Sources: {json.dumps(role_specific.get('sources', []), ensure_ascii=False)[:300]}

## Output
Bullet-point summary of what the FactChecker needs to know:""",

            "completeness_checker": f"""You are a context distiller for a CompletenessChecker sub-agent.
The CompletenessChecker will verify if the response addresses ALL user requirements.

From the following information, extract ONLY the facts relevant to requirement coverage.
Output a concise bullet-point summary (max 150 words).

## User Request
{user_msg}

## What Was Done
- Tools: {', '.join(tools)}
- Conversation state: CTV={'done' if conv.get('ctv_segmented') else 'no'}, OAR={'done' if conv.get('oar_segmented') else 'no'}, Planning={'done' if conv.get('planning_completed') else 'no'}

## Response Preview
{resp[:300]}

## Output
Bullet-point summary of requirements and what was addressed:""",
        }

        prompt = distill_prompts.get(role)
        if not prompt:
            return self._build_agent_context(role_specific)

        try:
            import asyncio
            # Use a short timeout — distiller should be fast
            distilled = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.llm_callback(prompt)
                ),
                timeout=5.0,
            )

            # Build enriched context with distilled summary
            enriched = self._build_agent_context(role_specific)
            enriched["distilled_context"] = distilled.strip()[:500]
            return enriched

        except Exception as e:
            logger.debug(f"Context distillation failed, using raw: {e}")
            return self._build_agent_context(role_specific)

    async def route_request(self, user_input: str) -> RoutingDecision:
        """
        Route user request to appropriate agents.

        Args:
            user_input: User's input text

        Returns:
            RoutingDecision with intent, complexity, and agents needed
        """
        self._request_count += 1

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

    def format_review_for_display(self, gate_result: GateResult,
                                  lang: str = "en") -> str:
        """
        Format review result for display to user.

        Args:
            gate_result: The gate result to format
            lang: Language code ("en" or "zh")

        Returns:
            Formatted string
        """
        if gate_result.passed and gate_result.decision == "pass":
            return ""

        # Labels by language
        all_labels = {
            "en": {
                "title": "Quality Review",
                "concerns": "Concerns",
                "suggestions": "Suggestions",
                "human_review": "Requires Human Review",
            },
            "zh": {
                "title": "Quality Review",
                "concerns": "Concerns",
                "suggestions": "Suggestions",
                "human_review": "Requires Human Review",
            },
        }
        labels = all_labels.get(lang, all_labels["en"])

        lines = []

        icon = {
            "pass": "✅",
            "conditional": "⚠️",
            "reject": "❌",
            "escalate": "🔔",
        }.get(gate_result.decision, "❓")

        lines.append(f"{icon} **{labels['title']}**: {gate_result.decision.upper()}")

        all_concerns = []
        for review in gate_result.reviews:
            all_concerns.extend(review.concerns)

        if all_concerns:
            lines.append(f"\n**{labels['concerns']}:**")
            for concern in list(set(all_concerns))[:5]:
                lines.append(f"- {concern}")

        all_suggestions = []
        for review in gate_result.reviews:
            all_suggestions.extend(review.suggestions)

        if all_suggestions:
            lines.append(f"\n**{labels['suggestions']}:**")
            for suggestion in list(set(all_suggestions))[:3]:
                lines.append(f"- {suggestion}")

        if gate_result.requires_human_review:
            lines.append(f"\n🔔 **{labels['human_review']}**")

        return "\n".join(lines)

    async def review_plan_append(self, dose_metrics: Dict, plan_info: Dict,
                                  plan_config: Dict = None, lang: str = "en") -> str:
        """Run PlanReviewer with distilled context. No retries."""
        try:
            role_data = {
                "dose_metrics": dose_metrics,
                "plan_info": plan_info,
                "plan_config": plan_config or {},
            }
            content = await self._distill_context("plan_reviewer", role_data)
            message = AgentMessage(
                sender=AgentRole.ROUTER,
                receiver=AgentRole.PLAN_REVIEWER,
                message_type=MessageType.REVIEW,
                content=content,
                priority=Priority.NORMAL,
            )
            response = await self.plan_reviewer.handle_message(message)
            if response.success and isinstance(response.result, ReviewResult):
                return self.plan_reviewer.format_as_appendix(response.result, lang)
        except Exception as e:
            logger.warning(f"Plan review failed: {e}")
        return ""

    async def review_facts_append(self, claims: list, sources: list,
                                    lang: str = "en",
                                    skip_distill: bool = False) -> str:
        """Run FactChecker. No retries.

        Args:
            skip_distill: If True, skip LLM context distillation.
                          Used when called from sync context (tool execution)
                          where nested event loops would cause issues.
        """
        try:
            role_data = {"claims": claims, "sources": sources}
            if skip_distill:
                content = self._build_agent_context(role_data)
            else:
                content = await self._distill_context("fact_checker", role_data)
            message = AgentMessage(
                sender=AgentRole.ROUTER,
                receiver=AgentRole.FACT_CHECKER,
                message_type=MessageType.REVIEW,
                content=content,
                priority=Priority.NORMAL,
            )
            response = await self.fact_checker.handle_message(message)
            if response.success and isinstance(response.result, ReviewResult):
                return self.fact_checker.format_as_source_summary(
                    response.result, lang
                )
        except Exception as e:
            logger.warning(f"Fact check failed: {e}")
        return ""

    async def check_completeness_append(self, user_message: str, response: str,
                                          steps: list = None, lang: str = "en") -> str:
        """Run CompletenessChecker with distilled context. No retries."""
        try:
            role_data = {
                "user_message": user_message,
                "response": response,
                "steps": steps or [],
            }
            content = await self._distill_context("completeness_checker", role_data)
            message = AgentMessage(
                sender=AgentRole.ROUTER,
                receiver=AgentRole.COMPLETENESS_CHECKER,
                message_type=MessageType.REVIEW,
                content=content,
                priority=Priority.NORMAL,
            )
            resp = await self.completeness_checker.handle_message(message)
            if resp.success and isinstance(resp.result, ReviewResult):
                return self.completeness_checker.format_as_appendix(resp.result, lang)
        except Exception as e:
            logger.warning(f"Completeness check failed: {e}")
        return ""

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
        self.completeness_checker.clear_history()
        self.quality_gate.clear_history()
        self._request_count = 0
        self._review_count = 0
        self._gate_pass_count = 0
        self._gate_reject_count = 0
