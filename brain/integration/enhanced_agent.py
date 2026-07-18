"""
Enhanced Agent Integration
===========================
Wires all new self-evolving components into the BrachyAgent closed feedback loop.
This module provides the enhanced agent loop that integrates:
- Layered memory (L0-L4) for contextual information density
- Reflexion engine for trajectory-based self-reflection
- Skill crystallizer for automatic skill generation
- User profile for dialectic preference modeling
- Context optimizer for token-efficient prompting
- Multi-agent critic for clinical decision review
- Auto-evolution trigger for periodic self-improvement
"""

import os
import sys
import time
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class EnhancedAgentIntegration:
    """
    Integrates all advanced agent capabilities into BrachyAgent.
    
    This class is designed to be composed with BrachyAgent, adding:
    1. Layered memory system
    2. Reflexion-based self-reflection
    3. Skill crystallization pipeline
    4. User preference modeling
    5. Context density optimization
    6. Multi-agent clinical critique
    7. Auto-evolution scheduling
    """

    def __init__(
        self,
        agent,
        session_id: str = "default",
        llm_callback: Callable = None,
        storage_dir: Optional[str] = None,
    ):
        self.agent = agent
        self.session_id = session_id
        self.llm_callback = llm_callback
        self.storage_dir = os.path.abspath(storage_dir) if storage_dir else None
        if self.storage_dir:
            os.makedirs(self.storage_dir, exist_ok=True)

        from memory import (
            LayeredMemory, ReflexionEngine, ContextDensityOptimizer,
            UserProfile, SkillCrystallizer,
        )
        from brain.core import MultiAgentCritic

        self.layered_memory = LayeredMemory(
            base_dir=(os.path.join(self.storage_dir, "layered") if self.storage_dir else None),
        )
        self.reflexion = ReflexionEngine(
            memory_dir=(os.path.join(self.storage_dir, "reflexion") if self.storage_dir else None),
            llm_callback=llm_callback,
        )
        self.context_optimizer = ContextDensityOptimizer()
        self.user_profile = UserProfile(
            user_id=session_id,
            profile_dir=(os.path.join(self.storage_dir, "profiles") if self.storage_dir else None),
        )
        self.skill_crystallizer = SkillCrystallizer(
            skills_dir=(os.path.join(self.storage_dir, "skills") if self.storage_dir else None),
            llm_callback=llm_callback,
        )
        self.multi_agent_critic = MultiAgentCritic(
            llm_callback=llm_callback,
            history_path=(os.path.join(self.storage_dir, "critic", "history.json") if self.storage_dir else None),
        )

        self._setup_reflexion_llm()
        logger.info(f"Enhanced agent integration initialized (session: {session_id})")

    def _setup_reflexion_llm(self):
        if self.llm_callback:
            return
        if hasattr(self.agent, "brain_router") and self.agent.brain_router:
            def llm_callback(prompt):
                response = self.agent.brain_router.chat(prompt)
                return response.content if hasattr(response, "content") else str(response)
            self.reflexion.llm_callback = llm_callback
            self.skill_crystallizer.llm_callback = llm_callback
            self.multi_agent_critic.llm_callback = llm_callback
            self.llm_callback = llm_callback

    def pre_task_hook(self, user_input: str) -> dict:
        """Called before task execution. Retrieves relevant context from all memory layers."""
        self.user_profile.increment_session()

        context = {
            "reflexion_warnings": "",
            "matched_sop": None,
            "crystallized_skill": None,
            "user_preferences": {},
            "layered_context": {},
        }

        reflexion_ctx = self.reflexion.get_reflection_context(user_input)
        context["reflexion_warnings"] = reflexion_ctx

        matched_sop = self.layered_memory.find_sop(user_input)
        if matched_sop:
            context["matched_sop"] = {
                "name": matched_sop.name,
                "steps": [s.tool_name for s in matched_sop.steps],
                "success_rate": matched_sop.success_rate,
            }

        crystallized = self.skill_crystallizer.find_matching_skill(user_input)
        if crystallized:
            context["crystallized_skill"] = {
                "name": crystallized.name,
                "tool_chain": crystallized.tool_chain,
                "success_rate": crystallized.success_rate,
                "parameters": crystallized.parameters,
            }

        context["user_preferences"] = self.user_profile.get_active_preferences()
        context["layered_context"] = self.layered_memory.get_context_summary(user_input)

        return context

    def post_task_hook(self, user_input: str, tool_chain: list, tool_results: list,
                       outcome: str, success: bool, parameters: dict = None):
        """Called after task execution. Records experience, reflects, and crystallizes skills."""
        self.skill_crystallizer.record_interaction()

        self.reflexion.reflect(
            task_description=user_input,
            tool_chain=tool_chain,
            tool_results=tool_results,
            outcome=outcome,
            success=success,
        )

        if success and len(tool_chain) >= 2:
            self.skill_crystallizer.crystallize(
                task_description=user_input,
                tool_chain=tool_chain,
                tool_results=tool_results,
                parameters=parameters,
            )

        self.layered_memory.extract_facts_from_experience(tool_chain, success, {})

        self.user_profile.record_interaction(user_input, outcome, success)

        self.layered_memory.archive_session(
            session_id=self.session_id,
            user_intent=user_input,
            outcome=outcome,
            success=success,
            tool_chain=tool_chain,
            tags=self._extract_tags(user_input),
        )

        if self.skill_crystallizer.should_auto_evolve():
            self._trigger_auto_evolution()

    def _trigger_auto_evolution(self):
        experiences = []
        if hasattr(self.agent, "exp_memory") and self.agent.exp_memory:
            experiences = self.agent.exp_memory.experiences

        if not experiences:
            return

        cycle = self.skill_crystallizer.evolve(experiences, force=False)
        if cycle:
            logger.info(
                f"Auto-evolution cycle {cycle.cycle_id}: "
                f"{cycle.skills_created} skills created, "
                f"{cycle.skills_updated} updated, "
                f"{cycle.parameters_optimized} params optimized"
            )

    def _extract_tags(self, user_input: str) -> list:
        tags = []
        lower = user_input.lower()
        if "plan" in lower or "planning" in lower:
            tags.append("planning")
        if "seg" in lower or "segment" in lower:
            tags.append("segmentation")
        if "dose" in lower or "dosimetry" in lower:
            tags.append("dose")
        if "eval" in lower or "evaluation" in lower:
            tags.append("evaluation")
        if "ctv" in lower:
            tags.append("ctv")
        if "oar" in lower:
            tags.append("oar")
        return tags

    def review_plan_with_critics(self, plan_description: str, dose_metrics: dict = None,
                                  tool_chain: list = None) -> str:
        report = self.multi_agent_critic.review_plan(
            plan_description=plan_description,
            dose_metrics=dose_metrics,
            tool_chain=tool_chain,
        )
        return self.multi_agent_critic.format_report_for_display(report)

    def get_agent_status(self) -> dict:
        return {
            "layered_memory": self.layered_memory.get_stats(),
            "reflexion": {
                "total_reflections": len(self.reflexion.episodic.reflections),
                "failure_patterns": len(self.reflexion.episodic.failure_patterns),
                "success_patterns": len(self.reflexion.episodic.success_patterns),
            },
            "skill_crystallizer": self.skill_crystallizer.get_skill_summary(),
            "user_profile": self.user_profile.get_profile_summary(),
            "context_optimizer": self.context_optimizer.get_budget_status({}),
        }

    def build_enhanced_prompt(self, system_prompt: str, tool_descriptions: str,
                               conversation_history: list, current_task: str) -> dict:
        memory_context = self._build_memory_context(current_task)
        return self.context_optimizer.build_context(
            system_prompt=system_prompt,
            tool_descriptions=tool_descriptions,
            memory_context=memory_context,
            conversation_history=conversation_history,
            current_task=current_task,
        )

    def _build_memory_context(self, task: str) -> str:
        parts = []

        reflexion_ctx = self.reflexion.get_reflection_context(task)
        if reflexion_ctx:
            parts.append(reflexion_ctx)

        matched_sop = self.layered_memory.find_sop(task)
        if matched_sop:
            steps_str = " -> ".join(s.tool_name for s in matched_sop.steps)
            parts.append(f"Matched SOP: {matched_sop.name} ({matched_sop.success_rate:.0%} success): {steps_str}")

        crystallized = self.skill_crystallizer.find_matching_skill(task)
        if crystallized:
            parts.append(
                f"Crystallized skill: {crystallized.name} "
                f"({' -> '.join(crystallized.tool_chain)})"
            )

        facts = self.layered_memory.get_facts(min_confidence=0.7)
        if facts:
            parts.append("Relevant facts:")
            for f in facts[:3]:
                parts.append(f"  - {f.fact} (confidence: {f.confidence:.2f})")

        return "\n".join(parts)
