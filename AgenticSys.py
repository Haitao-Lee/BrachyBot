"""
Agentic System - AI-BrachyAgent
================================
LLM-driven closed-loop brachytherapy planning system.

Architecture (per 0319_markdown.md):
- LLM Decision Brain: Understands doctor instructions, decomposes tasks, schedules tools
- Tool Chain: CTV Seg -> OAR Seg -> Dose Engine -> Trajectory Plan -> Seed Plan -> Dose Eval
- Real-time Closed Loop: Intra-op imaging -> Seed detection -> Deviation check -> Replanning
- Self-Evolution: Learns from experiences, creates new skills, writes new tools

Usage:
    # Pre-operative planning
    agent = BrachyAgent()
    result = agent.run_preoperative_plan(ct_path, ctv_path, oar_path)

    # Intra-operative replanning
    result = agent.run_intraoperative_replan(intra_op_ct_path, original_plan)

    # Natural language interface (with LLM function calling)
    result = agent.chat("First segment CTV and OAR, then generate treatment plan")
"""

import os
import sys
import json
import logging
import math
import re
import time
import threading
from typing import Any, Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse, unquote

import numpy as np
import SimpleITK as sitk
from tool_factory import ToolResult

logger = logging.getLogger(__name__)

from agent_runtime.core import AgentMemory, PlanningPhase, ToolRegistry, ToolResultPipeline
from agent_runtime.contracts import ContextPackBuilder, RunLedger, ToolCallGateway
from agent_runtime.response_tools import ResponseToolMixin
from agent_runtime.llm_runtime import LLMRuntimeMixin
from agent_runtime.chat_workflows import ChatWorkflowMixin

class BrachyAgent(ResponseToolMixin, LLMRuntimeMixin, ChatWorkflowMixin):
    """
    LLM-driven brachytherapy planning agent with self-evolution.

    Capabilities:
    1. Pre-operative: CT -> Segmentation -> Trajectory -> Seed Plan -> Dose Eval
    2. Intra-operative: Imaging -> Seed Detection -> Deviation Check -> Replanning
    3. LLM Function Calling: LLM can discover and invoke tools directly
    4. Self-Evolution: Learns from experiences, creates skills, writes new tools
    5. Code Writing: Can generate new tool code and register it dynamically
    """

    _REQUIRED_MIXIN_METHODS = (
        "_build_planning_report",
        "_check_search_reliability",
        "_clean_response_text",
        "_format_tool_result",
        "_parse_tool_calls",
        "_prepare_fact_check_brief",
    )

    @classmethod
    def _validate_mixin_contract(cls) -> None:
        """Fail fast if the runtime mixin composition is incomplete."""
        missing = [
            name for name in cls._REQUIRED_MIXIN_METHODS
            if not callable(getattr(cls, name, None))
        ]
        if missing:
            raise RuntimeError(
                "BrachyAgent runtime mixin contract is incomplete: "
                + ", ".join(missing)
            )

    def __init__(self, session_id: str = "default", config: Optional[Dict] = None):
        self._validate_mixin_contract()
        self.memory = AgentMemory(session_id)
        self.registry = ToolRegistry()
        self.config = config or {}
        # Web workspaces supply this directory from the authenticated case
        # root. Standalone/CLI agents keep the historical defaults, while a
        # web case never leaks interaction or learned-clinical state into the
        # repository-wide ``memory/data`` tree.
        workspace_state_dir = self.config.get("_workspace_state_dir")
        self._workspace_state_dir = os.path.abspath(str(workspace_state_dir)) if workspace_state_dir else None
        if self._workspace_state_dir:
            os.makedirs(self._workspace_state_dir, exist_ok=True)
        self._load_tools()
        self._cancel_requested = False
        self._turn_generation = 0
        self._active_turn_token = 0
        self._turn_state_lock = threading.RLock()
        self._turn_local = threading.local()
        # Runtime contracts are provider-neutral and case-local.  They add
        # observability and validation around the established execution path
        # without changing the validated clinical planning algorithms.
        self.run_ledger = RunLedger()
        runtime_cfg = self.config.get("agent_runtime", {}) if isinstance(self.config, dict) else {}
        self.context_packer = ContextPackBuilder(
            max_tokens=int(runtime_cfg.get("max_context_tokens", 12000)),
            reserve_output_tokens=int(runtime_cfg.get("reserve_output_tokens", 2000)),
        )
        self.tool_gateway = ToolCallGateway(self.run_ledger)

        from memory import InteractionMemory, SkillLearner, PreferenceStore
        from skills import SkillRegistry
        from skills import (
            StandardPlanningSkill, RLPlanningSkill, QuickPlanningSkill,
            PancreasSegmentationSkill, ProstateSegmentationSkill, GenericSegmentationSkill,
            StandardEvaluationSkill, DetailedEvaluationSkill,
            FullAutoPlanningSkill, QuickPlanSkill, RLPlanSkill,
            PancreasCTVSkill, PancreasOARSkill, PancreasFullSkill,
            ProstateFullSkill, DoseEvalSkill, PlanOptimizationSkill,
            IntraOpReplanSkill, DICOMExportSkill, ReportGenerationSkill,
            MultiOrganSegSkill, VoCoSegSkill, QualityCheckSkill,
            DVHAnalysisSkill, SelfEvolveSkill, CodeWriterSkill,
            LiverFullSkill, LungFullSkill,
        )

        self.interaction_memory = InteractionMemory(
            session_id=session_id,
            storage_dir=(os.path.join(self._workspace_state_dir, "interaction") if self._workspace_state_dir else None),
        )
        self.preference_store = PreferenceStore(
            user_id=session_id,
            storage_dir=(os.path.join(self._workspace_state_dir, "preferences") if self._workspace_state_dir else None),
        )
        self.skill_registry = SkillRegistry()
        self.skill_learner = SkillLearner(memory=self.interaction_memory)

        for skill_class in [
            StandardPlanningSkill, RLPlanningSkill, QuickPlanningSkill,
            PancreasSegmentationSkill, ProstateSegmentationSkill, GenericSegmentationSkill,
            StandardEvaluationSkill, DetailedEvaluationSkill,
            FullAutoPlanningSkill, QuickPlanSkill, RLPlanSkill,
            PancreasCTVSkill, PancreasOARSkill, PancreasFullSkill,
            ProstateFullSkill, DoseEvalSkill, PlanOptimizationSkill,
            IntraOpReplanSkill, DICOMExportSkill, ReportGenerationSkill,
            MultiOrganSegSkill, VoCoSegSkill, QualityCheckSkill,
            DVHAnalysisSkill, SelfEvolveSkill, CodeWriterSkill,
            LiverFullSkill, LungFullSkill,
        ]:
            self.skill_registry.register(skill_class())

        self._init_brain_system()
        self._init_self_evolution()
        self._init_enhanced_integration()
        self._init_multi_agent()

        logger.info(f"BrachyAgent initialized (session: {session_id})")

    def _init_brain_system(self):
        """Initialize the brain system for LLM-driven decision making."""
        self.brain_router = None
        self.brain_executor = None
        self.brain_rag = None
        self.brain_bridge = None
        self._brain_available = False
        self.tool_code_writer = None

        try:
            from brain import (
                LLMRouter, CaseExecutor, DoseRAG, get_rag,
                BrainToolBridge, get_tool_registry, initialize_brain_integration,
                PlannerDecider, ClinicalDecider, QualityDecider
            )
            from brain.core.tool_code_writer import ToolCodeWriter

            llm_config = self.config.get("llm", {})
            if not llm_config:
                # Auto-detect LLM provider from environment variables.
                # Supports all 15 built-in providers + any OpenAI-compatible API.
                #
                # Usage: set the provider-specific env vars and the system
                # auto-selects. No code changes needed.
                #
                # ┌─────────────────────────────────────────────────────────────┐
                # │ Provider      │ Env vars (set at least *_API_KEY)           │
                # ├─────────────────────────────────────────────────────────────┤
                # │ Anthropic     │ ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL,     │
                # │               │ ANTHROPIC_MODEL                             │
                # │ OpenAI        │ OPENAI_API_KEY, OPENAI_MODEL                │
                # │ Qwen          │ QWEN_API_KEY (or DASHSCOPE_API_KEY),        │
                # │               │ QWEN_MODEL                                  │
                # │ OpenRouter    │ OPENROUTER_API_KEY, OPENROUTER_MODEL        │
                # │ DeepSeek      │ DEEPSEEK_API_KEY, DEEPSEEK_MODEL            │
                # │ Kimi          │ KIMI_API_KEY, KIMI_MODEL                    │
                # │ GLM           │ GLM_API_KEY, GLM_MODEL                      │
                # │ Gemini        │ GEMINI_API_KEY, GEMINI_MODEL                │
                # │ Groq          │ GROQ_API_KEY, GROQ_MODEL                    │
                # │ Grok          │ GROK_API_KEY, GROK_MODEL                    │
                # │ MiniMax       │ MINIMAX_API_KEY, MINIMAX_MODEL              │
                # │ Tencent       │ TENCENT_API_KEY, TENCENT_MODEL              │
                # │ Ollama        │ OLLAMA_BASE_URL (default localhost:11434),   │
                # │               │ OLLAMA_MODEL                                │
                # │ Any OpenAI-   │ LLM_BASE_URL, LLM_API_KEY, LLM_MODEL       │
                # │ compatible    │ (generic fallback for any /v1/chat/ API)    │
                # └─────────────────────────────────────────────────────────────┘

                llm_config = self._auto_detect_llm_provider()

                if not llm_config:
                    logger.warning(
                        "No LLM provider detected from environment. "
                        "Set *_API_KEY for your provider (e.g. OPENAI_API_KEY, "
                        "ANTHROPIC_API_KEY, DEEPSEEK_API_KEY) or use generic: "
                        "LLM_BASE_URL + LLM_API_KEY + LLM_MODEL"
                    )

            self.brain_router = LLMRouter(llm_config)
            self.brain_rag = get_rag()

            tool_registry = get_tool_registry()
            self.brain_executor = CaseExecutor(tool_registry)

            self.brain_bridge = initialize_brain_integration()
            self.brain_bridge.set_brain_registry(tool_registry)
            self.brain_bridge.set_plan_executor(self.brain_executor)

            self.tool_code_writer = ToolCodeWriter(tool_registry=self.registry)

            self._brain_available = len(self.brain_router.providers) > 0
            self.planner_decider = None
            self.clinical_decider = None
            self.quality_decider = None

            if self._brain_available:
                default_llm = self.brain_router.providers.get(self.brain_router.default_provider)
                if default_llm:
                    self.planner_decider = PlannerDecider(default_llm, tool_registry)
                    self.clinical_decider = ClinicalDecider(default_llm)
                    self.quality_decider = QualityDecider(default_llm)
                else:
                    logger.warning("No default LLM provider found, deciders not initialized")
                    self._brain_available = False

            logger.info(f"Brain system initialized: provider={self.brain_router.default_provider}, "
                       f"tools={len(tool_registry.list_all())}")

        except ImportError as e:
            logger.warning(f"Brain system not available: {e}")
        except Exception as e:
            logger.warning(f"Brain system initialization failed: {e}")

    def _auto_detect_llm_provider(self) -> Dict:
        """Auto-detect LLM provider from environment variables.

        Returns a config dict suitable for LLMRouter, or {} if no
        provider is detected.  Each provider is keyed by its name
        in brain/core/router.py::_create_llm().
        """
        # ── Anthropic / Anthropic-compatible proxy ──────────────────
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_BASE_URL"):
            _base = os.environ.get("ANTHROPIC_BASE_URL", "")
            _key = os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
            _model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

            # Auto-detect API format from URL:
            #   - Contains "/anthropic" or "anthropic" in host → Anthropic SDK
            #   - Otherwise → OpenAI-compatible (generic provider)
            # This lets users switch base_url between Anthropic and
            # OpenAI endpoints without changing code.
            _is_anthropic_format = (
                "anthropic" in _base.lower()
                or _base.rstrip("/").endswith("/v1/messages")
                or not _base  # no base_url = direct Anthropic API
            )

            if _is_anthropic_format:
                return {
                    "anthropic": {
                        "enabled": True,
                        "model": _model,
                        "base_url": _base or None,
                        "api_key": _key,
                    }
                }
            else:
                # base_url looks OpenAI-compatible (e.g. /v1/chat/completions)
                # Use generic provider instead of Anthropic SDK.
                if not _base.rstrip("/").endswith("/v1"):
                    _base = _base.rstrip("/") + "/v1"
                return {
                    "generic": {
                        "enabled": True,
                        "type": "openai_compat",
                        "model": _model,
                        "api_key": _key,
                        "base_url": _base,
                    }
                }

        # ── OpenAI ──────────────────────────────────────────────────
        if os.environ.get("OPENAI_API_KEY"):
            return {
                "openai": {
                    "enabled": True,
                    "model": os.environ.get("OPENAI_MODEL", "gpt-4o"),
                    "api_key": os.environ["OPENAI_API_KEY"],
                }
            }

        # ── DeepSeek ────────────────────────────────────────────────
        if os.environ.get("DEEPSEEK_API_KEY"):
            return {
                "deepseek": {
                    "enabled": True,
                    "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                    "api_key": os.environ["DEEPSEEK_API_KEY"],
                }
            }

        # ── Qwen (DashScope) ────────────────────────────────────────
        if os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"):
            return {
                "qwen": {
                    "enabled": True,
                    "model": os.environ.get("QWEN_MODEL", "qwen-plus"),
                    "api_key": os.environ.get("QWEN_API_KEY", "") or os.environ.get("DASHSCOPE_API_KEY", ""),
                }
            }

        # ── Kimi (Moonshot) ─────────────────────────────────────────
        if os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY"):
            return {
                "kimi": {
                    "enabled": True,
                    "model": os.environ.get("KIMI_MODEL", "kimi-k2.6"),
                    "api_key": os.environ.get("KIMI_API_KEY", "") or os.environ.get("MOONSHOT_API_KEY", ""),
                }
            }

        # ── GLM (Zhipu) ────────────────────────────────────────────
        if os.environ.get("GLM_API_KEY") or os.environ.get("ZHIPU_API_KEY"):
            return {
                "glm": {
                    "enabled": True,
                    "model": os.environ.get("GLM_MODEL", "glm-4"),
                    "api_key": os.environ.get("GLM_API_KEY", "") or os.environ.get("ZHIPU_API_KEY", ""),
                }
            }

        # ── Gemini ──────────────────────────────────────────────────
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            return {
                "gemini": {
                    "enabled": True,
                    "model": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
                    "api_key": os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", ""),
                }
            }

        # ── Groq ────────────────────────────────────────────────────
        if os.environ.get("GROQ_API_KEY"):
            return {
                "groq": {
                    "enabled": True,
                    "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                    "api_key": os.environ["GROQ_API_KEY"],
                }
            }

        # ── Grok (xAI) ──────────────────────────────────────────────
        if os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY"):
            return {
                "grok": {
                    "enabled": True,
                    "model": os.environ.get("GROK_MODEL", "grok-2"),
                    "api_key": os.environ.get("GROK_API_KEY", "") or os.environ.get("XAI_API_KEY", ""),
                }
            }

        # ── MiniMax ─────────────────────────────────────────────────
        if os.environ.get("MINIMAX_API_KEY"):
            return {
                "minimax": {
                    "enabled": True,
                    "model": os.environ.get("MINIMAX_MODEL", "minimax-m2.7-20260318"),
                    "api_key": os.environ["MINIMAX_API_KEY"],
                }
            }

        # ── Tencent ─────────────────────────────────────────────────
        if os.environ.get("TENCENT_API_KEY"):
            return {
                "tencent": {
                    "enabled": True,
                    "model": os.environ.get("TENCENT_MODEL", "hy3-preview"),
                    "api_key": os.environ["TENCENT_API_KEY"],
                }
            }

        # ── OpenRouter ──────────────────────────────────────────────
        if os.environ.get("OPENROUTER_API_KEY"):
            return {
                "openrouter": {
                    "enabled": True,
                    "type": "openai_compat",
                    "model": os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4"),
                    "api_key": os.environ["OPENROUTER_API_KEY"],
                    "base_url": "https://openrouter.ai/api/v1",
                }
            }

        # ── Ollama (local) ──────────────────────────────────────────
        if os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_MODEL"):
            return {
                "ollama": {
                    "enabled": True,
                    "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:14b"),
                    "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                }
            }

        # ── Generic OpenAI-compatible (ANY API) ─────────────────────
        # Fallback for any provider with /v1/chat/completions endpoint.
        # Set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
        if os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_API_KEY"):
            return {
                "generic": {
                    "enabled": True,
                    "type": "openai_compat",
                    "model": os.environ.get("LLM_MODEL", "default"),
                    "api_key": os.environ["LLM_API_KEY"],
                    "base_url": os.environ["LLM_BASE_URL"],
                }
            }

        return {}

    def _init_self_evolution(self):
        """Initialize self-evolution system."""
        self.evolution_engine = None
        try:
            from memory import ExperienceMemory, SelfEvolutionEngine
            self.exp_memory = ExperienceMemory(
                session_id=self.memory.session_id,
                data_dir=(os.path.join(self._workspace_state_dir, "experience") if self._workspace_state_dir else None),
            )
            self.evolution_engine = SelfEvolutionEngine(
                experience_memory=self.exp_memory,
                skill_registry=self.skill_registry,
                preference_store=self.preference_store,
            )
            logger.info("Self-evolution system initialized")
        except Exception as e:
            logger.warning(f"Self-evolution system not available: {e}")

    def _init_enhanced_integration(self):
        """Initialize enhanced self-evolving agent components."""
        self.enhanced = None
        try:
            from brain.integration import EnhancedAgentIntegration
            llm_callback = None
            if self.brain_available and hasattr(self, "brain_router") and self.brain_router:
                def _llm_cb(prompt):
                    resp = self.brain_router.chat(prompt)
                    return resp.content if hasattr(resp, "content") else str(resp)
                llm_callback = _llm_cb
            self.enhanced = EnhancedAgentIntegration(
                agent=self,
                session_id=self.memory.session_id,
                llm_callback=llm_callback,
                storage_dir=(os.path.join(self._workspace_state_dir, "enhanced") if self._workspace_state_dir else None),
            )
            logger.info("Enhanced self-evolving integration initialized")
        except Exception as e:
            logger.warning(f"Enhanced integration not available: {e}")

    def _init_multi_agent(self):
        """Initialize multi-agent system for quality review."""
        self.multi_agent_wrapper = None
        try:
            from agents import BrachyAgentMultiAgentWrapper

            # Create LLM callback for multi-agent system
            llm_callback = None
            if self.brain_available and hasattr(self, "brain_router") and self.brain_router:
                def _ma_llm_cb(prompt, system_prompt=None, temperature=0.3):
                    messages = []
                    if system_prompt:
                        messages.append({"role": "system", "content": system_prompt})
                    messages.append({"role": "user", "content": prompt})
                    resp = self.brain_router.chat_messages(
                        messages=messages, temperature=temperature
                    )
                    return resp.content if hasattr(resp, "content") else str(resp)
                llm_callback = _ma_llm_cb

            self.multi_agent_wrapper = BrachyAgentMultiAgentWrapper(llm_callback=llm_callback)
            logger.info("Multi-agent system initialized")
        except Exception as e:
            logger.warning(f"Multi-agent system not available: {e}")

    def _get_llm_callback(self):
        """Return the shared synchronous LLM callback used by sub-agents."""
        if self.brain_available and hasattr(self, "brain_router") and self.brain_router:
            def _llm_cb(prompt, system_prompt=None, temperature=0.3):
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                resp = self.brain_router.chat_messages(
                    messages=messages, temperature=temperature
                )
                return resp.content if hasattr(resp, "content") else str(resp)
            return _llm_cb
        enhanced_cb = getattr(getattr(self, "enhanced", None), "llm_callback", None)
        if enhanced_cb:
            return enhanced_cb
        wrapper = getattr(self, "multi_agent_wrapper", None)
        orchestrator = getattr(wrapper, "orchestrator", None)
        return getattr(orchestrator, "llm_callback", None)

    @property
    def brain_available(self) -> bool:
        return self._brain_available

    def _build_planning_context(self) -> Dict[str, Any]:
        context = {
            "patient_data": {},
            "current_state": {
                "phase": self.memory.current_phase.value,
                "has_ct": self.memory.retrieve("ct_image") is not None,
                "has_ctv": self.memory.retrieve("ctv_array") is not None,
                "has_oar": self.memory.retrieve("oar_array") is not None,
                "has_plan": self.memory.retrieve("seed_positions") is not None,
                "has_dose": self.memory.retrieve("dose_distribution") is not None,
            },
            "metrics": {},
            "constraints": {},
        }
        ct_image = self.memory.retrieve("ct_image")
        if ct_image:
            context["patient_data"]["ct_path"] = self.memory.retrieve("ct_path", "unknown")
        ctv_array = self.memory.retrieve("ctv_array")
        if ctv_array is not None:
            context["metrics"]["ctv_voxels"] = int(np.sum(ctv_array > 0))
        dose = self.memory.retrieve("dose_distribution")
        if dose is not None:
            context["metrics"]["dose_calculated"] = True
        if self.brain_rag:
            context["constraints"] = {
                "pancreas": self.brain_rag.get_constraints("pancreas"),
                "prostate": self.brain_rag.get_constraints("prostate"),
                "lung": self.brain_rag.get_constraints("lung"),
            }
        return context

    def _llm_plan(self, task: str, context: Dict[str, Any]) -> Optional[Dict]:
        if not self.brain_available or not self.planner_decider:
            return None
        try:
            rag_context = ""
            if self.brain_rag:
                results = self.brain_rag.retrieve(task)
                rag_context = "\n".join(results[:3])
            plan = self.planner_decider.decide(
                task=task, context=context, rag_text=rag_context,
            )
            return plan
        except Exception as e:
            logger.error(f"LLM planning failed: {e}")
            return None

    def _llm_evaluate(self, result: Dict, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self.brain_available:
            return {"decision": "human_review", "confidence": 0.5}
        try:
            evaluation = self.quality_decider.decide(result, context)
            return evaluation
        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            return {"decision": "error", "error": str(e)}

    def _llm_clinical_decide(self, indicators: Dict, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self.brain_available:
            return {"accept": True, "reason": "llm_unavailable"}
        try:
            decision = self.clinical_decider.decide(indicators, context)
            return decision
        except Exception as e:
            logger.error(f"LLM clinical decision failed: {e}")
            return {"accept": False, "reason": f"error: {str(e)}"}

    def _load_tools(self):
        from tool_factory.CTV_seg import CTVModelCatalogTool, CTVSegmentationTool
        from tool_factory.OAR_seg import OARSegmentationTool
        from tool_factory.dose_engine import DoseEngineTool
        from tool_factory.dose_eval import DoseEvaluationTool
        from tool_factory.seed_plan import SeedPlanningTool
        from tool_factory.seed_seg import SeedSegmentationTool
        from tool_factory.traj_plan import TrajectoryPlanningTool

        try:
            from tool_factory.output.dicom_rt_exporter import DicomRTExporterTool
            self.registry.register(DicomRTExporterTool())
        except ImportError as e:
            logger.warning(f"DicomRTExporterTool not available: {e}")

        try:
            from tool_factory.code_executor import CodeExecutorTool
            self.registry.register(CodeExecutorTool())
        except ImportError as e:
            logger.warning(f"CodeExecutorTool not available: {e}")

        try:
            from tool_factory.filesystem_browser import FilesystemBrowserTool
            self.registry.register(FilesystemBrowserTool())
        except ImportError as e:
            logger.warning(f"FilesystemBrowserTool not available: {e}")

        try:
            from tool_factory.env_manager import EnvManagerTool
            self.registry.register(EnvManagerTool())
        except ImportError as e:
            logger.warning(f"EnvManagerTool not available: {e}")

        try:
            from tool_factory.tool_creator import ToolCreatorTool
            self.registry.register(ToolCreatorTool())
        except ImportError as e:
            logger.warning(f"ToolCreatorTool not available: {e}")

        try:
            from tool_factory.shell_executor import ShellExecutorTool
            self.registry.register(ShellExecutorTool())
        except ImportError as e:
            logger.warning(f"ShellExecutorTool not available: {e}")

        try:
            from tool_factory.doc_reader import DocumentReaderTool
            self.registry.register(DocumentReaderTool())
        except ImportError as e:
            logger.warning(f"DocumentReaderTool not available: {e}")

        try:
            from tool_factory.ui_inspector import UIInspectorTool
            self.registry.register(UIInspectorTool())
        except ImportError as e:
            logger.warning(f"UIInspectorTool not available: {e}")

        try:
            from tool_factory.ui_controller import UIControllerTool
            self.registry.register(UIControllerTool())
        except ImportError as e:
            logger.warning(f"UIControllerTool not available: {e}")

        try:
            from tool_factory.ui_screenshot import UIScreenshotTool
            self.registry.register(UIScreenshotTool())
        except ImportError as e:
            logger.warning(f"UIScreenshotTool not available: {e}")

        try:
            from tool_factory.ui_annotate import UIAnnotateTool
            self.registry.register(UIAnnotateTool())
        except ImportError as e:
            logger.warning(f"UIAnnotateTool not available: {e}")

        self.registry.register(CTVSegmentationTool())
        self.registry.register(CTVModelCatalogTool())
        self.registry.register(OARSegmentationTool())
        self.registry.register(DoseEngineTool())
        self.registry.register(DoseEvaluationTool())
        self.registry.register(SeedPlanningTool())
        self.registry.register(SeedSegmentationTool())
        self.registry.register(TrajectoryPlanningTool())

        # Planning pipeline (unified workflow)
        try:
            from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
            self.registry.register(PlanningPipelineTool())
        except ImportError as e:
            logger.warning(f"PlanningPipelineTool not available: {e}")

        # Advanced tools: knowledge, memory, safety, reporting
        try:
            from tool_factory.case_memory import CaseMemoryTool
            self.registry.register(CaseMemoryTool())
        except ImportError as e:
            logger.warning(f"CaseMemoryTool not available: {e}")

        try:
            from tool_factory.clinical_kb import ClinicalKnowledgeBaseTool
            self.registry.register(ClinicalKnowledgeBaseTool())
        except ImportError as e:
            logger.warning(f"ClinicalKnowledgeBaseTool not available: {e}")

        try:
            from tool_factory.plan_comparator import PlanComparatorTool
            self.registry.register(PlanComparatorTool())
        except ImportError as e:
            logger.warning(f"PlanComparatorTool not available: {e}")

        try:
            from tool_factory.safety_validator import SafetyValidatorTool
            self.registry.register(SafetyValidatorTool())
        except ImportError as e:
            logger.warning(f"SafetyValidatorTool not available: {e}")

        try:
            from tool_factory.plan_quality import (
                PlanQualityScorerTool,
                OARConstraintCheckerTool,
                PlanRefinementTool,
            )
            self.registry.register(PlanQualityScorerTool())
            self.registry.register(OARConstraintCheckerTool())
            self.registry.register(PlanRefinementTool())
        except ImportError as e:
            logger.warning(f"Plan quality tools not available: {e}")

        try:
            from tool_factory.report_generator import ReportGeneratorTool
            self.registry.register(ReportGeneratorTool())
        except ImportError as e:
            logger.warning(f"ReportGeneratorTool not available: {e}")

        try:
            from tool_factory.output.report_auto_fill import ReportAutoFillTool
            self.registry.register(ReportAutoFillTool())
            logger.info("ReportAutoFillTool registered (chat-driven in-app report fill)")
        except ImportError as e:
            logger.warning(f"ReportAutoFillTool not available: {e}")


        # Web search tool for internet connectivity
        try:
            from tool_factory.web_search import WebSearchTool
            self.registry.register(WebSearchTool())
            logger.info("WebSearchTool registered for internet search capability")
        except ImportError as e:
            logger.warning(f"WebSearchTool not available: {e}")

        # Web fetch tool for fetching specific URLs
        try:
            from tool_factory.web_fetch import WebFetchTool
            self.registry.register(WebFetchTool())
            logger.info("WebFetchTool registered for URL fetching")
        except ImportError as e:
            logger.warning(f"WebFetchTool not available: {e}")

        # Unified web access tool (combines search + fetch + evidence chain)
        try:
            from tool_factory.web_access import WebAccessTool
            self.registry.register(WebAccessTool())
            logger.info("WebAccessTool registered for unified web access")
        except ImportError as e:
            logger.warning(f"WebAccessTool not available: {e}")

        logger.info(f"Registered {len(self.registry.tool_names)} tools: {self.registry.tool_names}")

    def _truthy_payload(self, value) -> bool:
        """Return True for stored arrays/objects without forcing numpy truth tests."""
        if value is None:
            return False
        if isinstance(value, (dict, list, tuple, set, str, bytes)):
            return len(value) > 0
        return True

    def _has_completed_planning_in_steps(self, steps: List[Dict] = None) -> bool:
        """Return whether this turn reached a plan-finalizing tool."""
        # Seed placement and raw dose calculation are intermediate products;
        # neither proves that target/OAR metrics were evaluated.
        completed_tools = {"planning_pipeline", "dose_evaluation"}
        return bool(steps) and any(
            s.get("type") == "tool"
            and s.get("status") == "done"
            and s.get("tool") in completed_tools
            for s in steps
        )

    def _has_completed_planning(self, steps: List[Dict] = None) -> bool:
        """Require current-turn completion evidence and all durable plan products."""
        if steps is not None and not self._has_completed_planning_in_steps(steps):
            return False

        metrics = self.memory.retrieve("dose_metrics")
        seed_payload = self.memory.retrieve("seed_plan")
        if not self._truthy_payload(seed_payload):
            seed_payload = self.memory.retrieve("seed_plan_serialized")
        if not self._truthy_payload(seed_payload):
            seed_payload = self.memory.retrieve("seed_positions")
        dose_payload = (
            self.memory.retrieve("dose_distribution")
            if self.memory.retrieve("dose_distribution") is not None
            else self.memory.retrieve("dose_distribution_gy")
        )
        return (
            self._truthy_payload(metrics)
            and self._truthy_payload(seed_payload)
            and self._truthy_payload(dose_payload)
        )

    def _planning_requested(self, message: str, tool_calls: List[Dict] = None) -> bool:
        """Detect requests to execute planning, not educational questions about planning."""
        text = (message or "").lower()
        planning_tools = {"planning_pipeline", "seed_planning", "dose_engine", "dose_evaluation", "dose_calc"}
        planning_tool_requested = any((tc.get("tool") in planning_tools) for tc in (tool_calls or []))
        # A replan command can be phrased as a parameter edit (for example,
        # "reverse reference direction") and may contain no generic Chinese
        # execution keyword. The explicit tool call plus replan detector is
        # sufficient evidence to enter the clinical normalizer.
        if self._is_replan_request(message):
            return True

        knowledge_markers = (
            "介绍", "解释", "说明", "讲讲", "为什么", "为啥", "好处", "优势",
            "缺点", "局限", "比较", "区别", "对比", "不用其他治疗",
            "what is", "explain", "why", "benefit", "advantage", "disadvantage",
            "compare", "comparison", "versus", " vs ",
        )
        execution_markers = (
            "执行", "运行", "开始", "生成", "制定", "计算", "进行规划",
            "开始规划", "重新规划", "帮我规划", "请规划", "做一个计划",
            "做治疗计划", "治疗计划生成",
            "run", "execute", "start planning", "perform planning",
            "generate a treatment plan", "create a treatment plan",
            "compute plan", "replan",
        )
        has_execution_intent = any(k in text for k in execution_markers)
        is_knowledge_question = any(k in text for k in knowledge_markers)

        if is_knowledge_question and not has_execution_intent:
            return False

        planning_keywords = (
            "planning",
            "treatment plan",
            "brachytherapy",
            "implant",
            "\u89c4\u5212",
            "\u6cbb\u7597\u8ba1\u5212",
            "\u7c92\u5b50",
            "\u690d\u5165",
            "\u653e\u5c04\u6027",
        )
        has_planning_domain = any(k in text for k in planning_keywords)
        if has_execution_intent and has_planning_domain:
            return True
        return planning_tool_requested and has_execution_intent

    def _is_replan_request(self, message: str) -> bool:
        """Detect an explicit request to rerun an existing plan."""
        text = (message or "").lower()
        return bool(
            re.search(r"(?:重新|再次|再|重做|重跑).{0,8}(?:规划|计划)", text)
            or re.search(r"(?:规划|计划).{0,8}(?:反向|逆向|重新|再来)", text)
            or re.search(r"(?:反向|逆向).{0,10}(?:规划|计划)", text)
            or re.search(r"(?:\u91cd\u65b0|\u518d\u6b21|\u518d|\u91cd\u505a|\u91cd\u8dd1).{0,8}(?:\u89c4\u5212|\u8ba1\u5212)", text)
            or re.search(r"(?:\u53cd\u5411|\u9006\u5411).{0,10}(?:\u89c4\u5212|\u8ba1\u5212)", text)
            or re.search(r"\b(?:replan|re-plan|rerun(?: the)? plan|rerun planning)\b", text)
            or re.search(r"\breverse\b.{0,30}\breference\s*direction\b", text)
            or re.search(r"\breference\s*direction\b.{0,30}\breverse\b", text)
            or re.search(r"reference\s*direction.{0,30}(?:reverse|\u53cd\u5411|\u9006\u5411).{0,10}(?:plan|\u89c4\u5212|\u8ba1\u5212)", text)
            or re.search(r"(?:reverse|\u53cd\u5411|\u9006\u5411).{0,30}reference\s*direction", text)
        )

    @staticmethod
    def _coerce_reference_direction(value):
        """Return a finite non-zero 3-vector, or None for malformed input."""
        try:
            values = [float(v) for v in value]
        except (TypeError, ValueError):
            return None
        if len(values) != 3 or not all(math.isfinite(v) for v in values):
            return None
        if math.sqrt(sum(v * v for v in values)) <= 1e-9:
            return None
        return values

    def _current_reference_direction(self):
        """Read the latest explicit UI/config direction without mutating it.
        Returns a 3-vector, or 'auto' for automatic detection."""
        ui_state = self.memory.get_ui_state() or {}
        planning_state = ui_state.get("planning") if isinstance(ui_state.get("planning"), dict) else {}
        # UI input has highest priority.
        ref_direc = planning_state.get("reference_direc")
        if ref_direc == "auto" or planning_state.get("ref_direc_auto"):
            return "auto"
        if isinstance(ref_direc, (list, tuple)) and len(ref_direc) == 3:
            try:
                values = [float(v) for v in ref_direc]
                if all(math.isfinite(v) for v in values) and math.sqrt(sum(v * v for v in values)) > 1e-9:
                    return values
            except (TypeError, ValueError):
                pass
        # Fall back to config/memory (these may need negation).
        candidates = [
            ui_state.get("reference_direc"),
            (self.memory.retrieve("plan_config") or {}).get("reference_direc"),
            (getattr(self, "config", {}) or {}).get("reference_direc"),
        ]
        for candidate in candidates:
            direction = self._coerce_reference_direction(candidate)
            if direction is not None:
                return direction
        # Keep the defensive fallback aligned with plans/config.json and the
        # manual Web UI default. Explicit UI/config directions still win.
        return [0.0, 1.0, 0.0]

    def _reversed_reference_direction(self):
        """Return the negated current reference direction for an explicit replan."""
        # UI input is already in RAS, so reverse the vector directly. The
        # earlier implementation returned it unchanged, making a user request
        # to reverse the direction produce the same plan orientation.
        ui_state = self.memory.get_ui_state() or {}
        planning_state = ui_state.get("planning") if isinstance(ui_state.get("planning"), dict) else {}
        if planning_state.get("ref_direc_auto") or planning_state.get("reference_direc") == "auto":
            return "auto"
        ref_direc = planning_state.get("reference_direc")
        if isinstance(ref_direc, (list, tuple)) and len(ref_direc) == 3:
            try:
                values = [float(v) for v in ref_direc]
                if all(math.isfinite(v) for v in values) and math.sqrt(sum(v * v for v in values)) > 1e-9:
                    return [-value for value in values]
            except (TypeError, ValueError):
                pass
        # Fall back: negate config direction (historical convention).
        return [-value for value in self._current_reference_direction()]

    def _current_ct_path(self, tool_calls: List[Dict] = None) -> str:
        for tc in tool_calls or []:
            params = tc.get("params") or {}
            for key in ("ct_image_path", "image_path", "ct_path"):
                if params.get(key):
                    return params[key]
        return (
            self.memory.retrieve("ct_path")
            or (self.memory.get_ui_state() or {}).get("ct_path")
            or ""
        )

    def _normalize_clinical_tool_calls(self, tool_calls: List[Dict], message: str) -> List[Dict]:
        """Force full brachytherapy planning into CTV -> OAR -> planning order."""
        if not tool_calls or not self._planning_requested(message, tool_calls):
            return tool_calls

        planning_tools = {"planning_pipeline", "seed_planning", "dose_engine", "dose_evaluation", "dose_calc"}
        ctv_ready = self.memory.retrieve("ctv_array") is not None
        oar_ready = self.memory.retrieve("oar_array") is not None and (
            bool(self.memory.retrieve("oar_is_full"))
            or len(self.memory.retrieve("organ_names") or {}) >= 5
        )
        planning_ready = self._has_completed_planning()
        replan_requested = self._is_replan_request(message)
        ct_path = self._current_ct_path(tool_calls)
        tumor_type = (
            self.memory.retrieve("tumor_type_used")
            or self._detect_tumor_type_from_message(message)
        )

        def clone_call(tc):
            return {
                "id": tc.get("id"),
                "tool": tc.get("tool"),
                "params": dict(tc.get("params") or {}),
            }

        by_tool = {}
        rest = []
        for tc in tool_calls:
            tool_name = tc.get("tool")
            if tool_name in {"ctv_segmentation", "oar_segmentation", "planning_pipeline"}:
                by_tool.setdefault(tool_name, clone_call(tc))
            elif tool_name in planning_tools:
                # Replace stepwise planning tool fragments with the unified pipeline.
                by_tool.setdefault("planning_pipeline", {
                    "id": "auto_planning_pipeline",
                    "tool": "planning_pipeline",
                    "params": {"step": "full"},
                })
            else:
                rest.append(tc)

        def ensure_call(tool_name, params):
            call = by_tool.get(tool_name)
            if call is None:
                call = {"id": f"auto_{tool_name}", "tool": tool_name, "params": {}}
            call["params"] = dict(call.get("params") or {})
            call["params"].update({k: v for k, v in params.items() if v})
            return call

        ordered = []
        if not ctv_ready:
            ordered.append(ensure_call("ctv_segmentation", {
                "image_path": ct_path,
                "tumor_type": tumor_type,
            }))
        if not oar_ready:
            ordered.append(ensure_call("oar_segmentation", {"image_path": ct_path}))
        if not planning_ready or replan_requested:
            planning_params = {
                "ct_image_path": ct_path,
                "step": "full",
            }
            # Read ALL planning inputs from the live UI snapshot.
            # Older memory adapters and lightweight test doubles may expose
            # retrieve/store but not the optional UI snapshot API. Planning
            # must still proceed with the explicit message parameters.
            get_ui_state = getattr(self.memory, "get_ui_state", None)
            ui_state = get_ui_state() if callable(get_ui_state) else {}
            ui_state = ui_state or {}
            planning_state = ui_state.get("planning") if isinstance(ui_state.get("planning"), dict) else {}
            ui_mode = ui_state.get("plan_mode")
            planning_params["mode"] = ui_mode or "rule_based"
            planning_overrides = {}

            seed_info = planning_state.get("seed_info")
            if seed_info:
                planning_params["seed_info"] = seed_info
            radiation_params = planning_state.get("radiation_params")
            if radiation_params:
                planning_overrides["radiation_array_params"] = radiation_params
            in_lo = planning_state.get("in_lowest_energy")
            if in_lo is not None:
                planning_overrides["in_lowest_energy"] = in_lo
            out_hi = planning_state.get("out_highest_energy")
            if out_hi is not None:
                planning_overrides["out_highest_energy"] = out_hi
            dvh_rate = planning_state.get("dvh_rate")
            if dvh_rate is not None:
                planning_overrides["DVH_rate"] = dvh_rate
            max_iter = planning_state.get("max_iter")
            if max_iter is not None:
                planning_overrides["max_iter"] = max_iter
            iter_rate = planning_state.get("iter_rate")
            if iter_rate is not None:
                planning_overrides["iter_rate"] = iter_rate
            replan_rate = planning_state.get("replan_rate")
            if replan_rate is not None:
                planning_overrides["replan_rate"] = replan_rate
            dist_filter = planning_state.get("distance_filter")
            if dist_filter:
                planning_overrides["distance_filter"] = dist_filter
            if planning_overrides:
                # The pipeline treats this nested object as a per-run,
                # immutable override snapshot. This prevents different
                # pipeline stages from mixing live UI changes with defaults.
                planning_params["planning_params"] = planning_overrides

            # Preserve the live UI direction for both rule-based and RL
            # planning. The auto checkbox is an explicit geometric request;
            # do not replace it with the stale manual vector from the form.
            if not replan_requested:
                live_ref = planning_state.get("reference_direc")
                if planning_state.get("ref_direc_auto"):
                    live_ref = "auto"
                if live_ref is not None:
                    planning_params["ref_direc"] = live_ref

            if replan_requested:
                planning_params["ref_direc"] = self._reversed_reference_direction()
                planning_params["_reference_direction_user_override"] = True
            ordered.append(ensure_call("planning_pipeline", planning_params))

        if ordered:
            logger.info(
                "[workflow-normalizer] normalized clinical tool order: %s",
                " -> ".join(call.get("tool", "") for call in ordered),
            )
        return ordered + rest

    def _current_planning_obstacle_context(self):
        """Build the active case's obstacle policy for direct planning tools.

        The unified planning pipeline owns this logic, but the public
        ``trajectory_planning`` and ``seed_planning`` tools can still be
        called directly by an LLM. Keeping the same Data Tree-derived mask
        here prevents those legacy entry points from reintroducing paths that
        the unified pipeline would reject.
        """
        from tool_factory.seed_plan.planning_pipeline import (
            _build_radiation_volume,
            _merge_embedded_hard_obstacles,
            _resolve_data_tree_obstacle_labels,
        )
        from plans.config import setting

        ctv_mask = self.memory.retrieve("ctv_array")
        oar_mask = self.memory.retrieve("oar_array")
        ct_image = self.memory.retrieve("ct_image")
        if ctv_mask is None or ct_image is None:
            return None

        merged_oar, embedded_labels = _merge_embedded_hard_obstacles(oar_mask, self)
        obstacle_labels, obstacle_source = _resolve_data_tree_obstacle_labels(self)
        obstacle_labels.update(embedded_labels)
        args = setting()
        obstacle_value = args.radiation_array_params["obstacle_value"]
        radiation_volume = _build_radiation_volume(
            np.asarray(ctv_mask),
            None if merged_oar is None else np.asarray(merged_oar),
            target_value=args.radiation_array_params["target_value"],
            obstacle_value=obstacle_value,
            obstacle_labels=obstacle_labels,
            obstacle_source=obstacle_source,
        )
        return {
            "ct_image": ct_image,
            "ctv_mask": np.asarray(ctv_mask),
            "oar_mask": None if merged_oar is None else np.asarray(merged_oar),
            "radiation_volume": radiation_volume,
            "obstacle_labels": obstacle_labels,
            "obstacle_value": obstacle_value,
        }

    def _filter_direct_planning_trajectories(self, trajectories, context):
        """Apply the pipeline's candidate and physical safety gates.

        Direct tool calls use the original CT grid, so the CT image is also
        the planning image for the world-coordinate check. If a caller has no
        active case context, the direct tool's historical behavior is kept;
        active web sessions always have the context and fail closed when no
        candidate remains.
        """
        if context is None:
            return list(trajectories or []), None
        from tool_factory.seed_plan.planning_pipeline import (
            _filter_safe_trajectories,
            _filter_world_safe_trajectories,
        )

        candidates = _filter_safe_trajectories(
            trajectories,
            context["radiation_volume"],
            context["obstacle_value"],
        )
        candidates = _filter_world_safe_trajectories(
            candidates,
            context["ct_image"],
            context["ct_image"],
            context["ctv_mask"],
            context["oar_mask"],
            context["obstacle_labels"],
        )
        return candidates, context

    def _execute_tool_with_memory(self, tool_name: str, params: Dict, progress_callback=None, step_callback=None) -> Any:
        """Execute a tool, automatically injecting memory-stored data.

        step_callback (optional): callable(substep_name, status, content)
        passed to the tool so it can report internal sub-step transitions
        (e.g. planning_pipeline with step:full emits 5 sub-step events
        for trajectory_init, trajectory_refine, seed_planning, dose_calc,
        dose_eval). The streaming wrapper drains these into the SSE
        stream so the todo list ticks through the sub-steps with the
        breathing animation.

        BUG FIX 2026-06-16 (planning_pipeline needs CTV first):
        when the LLM calls planning_pipeline / seed_planning /
        trajectory_planning WITHOUT first calling ctv_segmentation,
        the tool errors with "No CTV mask available".
        DISABLED AUTO-FIX (2026-06-27): The auto-fix was hiding LLM errors.
        Now the LLM receives a clear error message and must learn to follow
        the correct workflow: ctv_segmentation → oar_segmentation → planning.
        """
        # DISABLED: Auto-fix mechanism that was hiding LLM errors
        # The LLM should follow the workflow order specified in system_prompt.md
        # If it doesn't, it should receive a clear error, not have the system
        # silently fix its mistake.
        # Auto-fix code removed - let the tool fail with clear error if masks are missing.

        if progress_callback:
            progress_callback(f"Preparing {tool_name}...", 10)

        ct_image = self.memory.retrieve("ct_image")
        ctv_array = self.memory.retrieve("ctv_array")
        oar_array = self.memory.retrieve("oar_array")
        trajectories = self.memory.retrieve("trajectories")
        radiation_volume = self.memory.retrieve("radiation_volume")
        dose_distribution = self.memory.retrieve("dose_distribution")
        seed_positions = self.memory.retrieve("seed_positions")

        if tool_name == "ctv_segmentation":
            # ALWAYS force-inject the LPI-oriented CT from memory.
            # The LLM may pass `image` as a string repr of a SimpleITK object,
            # which blocks injection and causes the tool to load raw CT from
            # image_path — producing masks in wrong orientation.
            if ct_image is not None:
                params["image"] = ct_image
            if "label_path" not in params and self.memory.retrieve("ctv_path"):
                params["label_path"] = self.memory.retrieve("ctv_path")
            # Map tumor_type to VoCo tool name if needed, and store for planning pipeline
            if "tumor_type" in params:
                params["tumor_type"] = self._map_tumor_type(params["tumor_type"])
                # Store tumor type so planning pipeline can use organ-specific reference direction
                if params["tumor_type"]:
                    self.memory.store("tumor_type_used", params["tumor_type"])
        elif tool_name == "oar_segmentation":
            # Same: always force-inject LPI-oriented CT
            if ct_image is not None:
                params["image"] = ct_image
        elif tool_name == "trajectory_planning":
            if "dose_image" not in params and ct_image is not None:
                params["dose_image"] = ct_image
            direct_obstacle_context = self._current_planning_obstacle_context()
            if direct_obstacle_context is not None:
                # Replace stale/client-supplied geometry with the current
                # Data Tree policy. This is the direct-tool equivalent of the
                # unified pipeline's candidate-generation safety gate.
                params["radiation_volume"] = direct_obstacle_context["radiation_volume"]
                params["obstacle_value"] = direct_obstacle_context["obstacle_value"]
                self.memory.store("radiation_volume", direct_obstacle_context["radiation_volume"])
            elif "radiation_volume" not in params:
                if radiation_volume is None and ctv_array is not None:
                    radiation_volume = np.zeros_like(ctv_array, dtype=np.float64)
                    radiation_volume[ctv_array > 0] = 1.0
                    if oar_array is not None:
                        oar_labels = np.unique(oar_array[oar_array > 0])
                        for label in oar_labels:
                            radiation_volume[oar_array == label] = 3.0
                    self.memory.store("radiation_volume", radiation_volume)
                if radiation_volume is not None:
                    params["radiation_volume"] = radiation_volume
        elif tool_name in {"seed_planning", "seed_planning_rule_based", "seed_planning_rl"}:
            if "dose_image" not in params and ct_image is not None:
                params["dose_image"] = ct_image
            direct_obstacle_context = self._current_planning_obstacle_context()
            if direct_obstacle_context is not None:
                params["radiation_volume"] = direct_obstacle_context["radiation_volume"]
                params["obstacle_value"] = direct_obstacle_context["obstacle_value"]
                source_trajectories = params.get("trajectories") or trajectories
                filtered, _ = self._filter_direct_planning_trajectories(
                    source_trajectories, direct_obstacle_context
                )
                if not filtered:
                    return ToolResult(
                        success=False,
                        error=(
                            "No candidate trajectories remain after validating "
                            "the current Data Tree non-traversable masks."
                        ),
                    )
                params["trajectories"] = filtered
            elif "radiation_volume" not in params and radiation_volume is not None:
                params["radiation_volume"] = radiation_volume
            if "trajectories" not in params and trajectories is not None:
                params["trajectories"] = trajectories
        elif tool_name == "dose_engine":
            if seed_positions is not None and "seeds" not in params:
                params["seeds"] = seed_positions
            if ct_image is not None and "dose_image" not in params:
                params["dose_image"] = ct_image
        elif tool_name == "dose_evaluation":
            if dose_distribution is not None and "dose_array" not in params:
                params["dose_array"] = dose_distribution
            if ctv_array is not None and "ctv_mask" not in params:
                params["ctv_mask"] = ctv_array
            if oar_array is not None and "oar_mask" not in params:
                params["oar_mask"] = oar_array
        elif tool_name == "seed_segmentation" and "image" not in params:
            if ct_image is not None:
                params["image"] = ct_image

        if progress_callback:
            progress_callback(f"Executing {tool_name}...", 50)

        # Pass step_callback to the tool ONLY for tools that understand
        # it (currently just planning_pipeline). Other tools (CTV/OAR
        # seg, etc.) would forward it to the LLM as a bogus param and
        # fail. Injecting it on every tool was a bug — the LLM was
        # getting 'step_callback=<function ...>' as a tool argument and
        # refusing to call the tool.
        if step_callback is not None and tool_name == "planning_pipeline":
            params["step_callback"] = step_callback
        # Pass agent reference so planning_pipeline can access CTV/OAR
        # from memory without relying on _global_agent (which may not
        # be set in all code paths).
        if tool_name == "planning_pipeline":
            params["_agent"] = self
        elif tool_name in {"report_auto_fill", "tool_creator"}:
            params["_agent"] = self

        # BUG FIX 2026-06-17 (duplicate oar_segmentation): the LLM
        # often calls oar_segmentation explicitly in Call 2, even
        # though the auto-OAR inside ctv_segmentation already ran
        # TotalSegmentator and stored >=5 organs in memory. This
        # wastes 30-60s of GPU time. Short-circuit: if the existing
        # oar_array already has 50+ unique organs and the LLM is
        # calling oar_segmentation again with the same image_path,
        # return early with a "skipped — already done" ToolResult.
        #
        # Same for ctv_segmentation: if ctv_array is already in
        # memory and the LLM calls ctv_segmentation again with the
        # same path, skip the redundant GPU run.
        _skip_tool = False
        if tool_name == "ctv_segmentation":
            _existing_ctv = self.memory.retrieve("ctv_array")
            _existing_path = self.memory.retrieve("ct_path")
            if _existing_ctv is not None:
                _req_path = params.get("image_path", _existing_path)
                if _req_path in (None, _existing_path):
                    logger.info(
                        f"[dedup] ctv_segmentation called but memory "
                        f"already has ctv_array. Skipping redundant run."
                    )
                    if progress_callback:
                        progress_callback("CTV already segmented (skipped)", 90)
                    result = ToolResult(
                        success=True,
                        data={"ctv_array": _existing_ctv},
                        message="CTV already segmented (skipped redundant call).",
                        metadata={
                            "ctv_array": _existing_ctv,
                            "ctv_mask": (
                                self.memory.retrieve("ctv_mask")
                                if self.memory.retrieve("ctv_mask") is not None
                                else _existing_ctv
                            ),
                            "skipped_duplicate": True,
                        },
                    )
                    _skip_tool = True
        if tool_name == "oar_segmentation":
            _existing_oar = self.memory.retrieve("oar_array")
            _existing_names = self.memory.retrieve("organ_names") or {}
            _existing_path = self.memory.retrieve("ct_path")
            # Fullness is an explicit provenance flag. Organ count is not a
            # reliable proxy because model/task variants legitimately expose
            # different label sets.
            if _existing_oar is not None and bool(self.memory.retrieve("oar_is_full")):
                _req_path = params.get("image_path", _existing_path)
                if _req_path in (None, _existing_path):
                    logger.info(
                        f"[dedup] oar_segmentation called but memory "
                        f"already has {len(_existing_names)} organs "
                        f"(auto-OAR result). Skipping redundant run."
                    )
                    if progress_callback:
                        progress_callback("OAR already segmented (skipped)", 90)
                    result = ToolResult(
                        success=True,
                        data={"oar_array": _existing_oar, "organ_names": _existing_names,
                              "organ_counts": self.memory.retrieve("organ_counts") or {}},
                        message=(
                            f"OAR already segmented (skipped redundant call). "
                            f"{len(_existing_names)} organs in memory."
                        ),
                        metadata={
                            "oar_array": _existing_oar,
                            "organ_names": _existing_names,
                            "organ_counts": self.memory.retrieve("organ_counts") or {},
                            "skipped_duplicate": True,
                        },
                    )
                    _skip_tool = True

        if not _skip_tool:
            # BaseTool.execute owns operation tracking. Outer wrappers used to
            # double-track every registry call and depended on global builtins.
            workspace_revision = (self.memory.get_ui_state() or {}).get("workspace_revision")
            result = self.tool_gateway.execute(
                self.registry,
                tool_name,
                params,
                lambda: (
                    self._validate_and_execute(tool_name, params)
                    if tool_name in self._VALIDATORS
                    else self.registry.execute(tool_name, **params)
                ),
                workspace_revision=workspace_revision,
            )

        if progress_callback:
            progress_callback(f"Processing results...", 90)

        if result.success:
            metadata = result.metadata or {}
            logger.info("Tool %s succeeded. Metadata keys: %s", tool_name, list(metadata))
            if tool_name == "trajectory_planning" and metadata.get("trajectories") is not None:
                # The trajectory tool itself generates paths, but the agent
                # must still enforce the current Data Tree policy before any
                # downstream seed optimizer can consume its output.
                context = locals().get("direct_obstacle_context")
                filtered, _ = self._filter_direct_planning_trajectories(
                    metadata.get("trajectories") or [], context
                )
                if not filtered:
                    return ToolResult(
                        success=False,
                        error=(
                            "Trajectory generation produced no path that is "
                            "safe against the current Data Tree non-traversable masks."
                        ),
                    )
                metadata["trajectories"] = filtered
                metadata["num_trajectories"] = len(filtered)
                result.data = filtered
            if tool_name == "ctv_segmentation" and "ctv_array" in metadata:
                self.memory.store("ctv_array", metadata["ctv_array"])
                if "ctv_mask" in metadata:
                    self.memory.store("ctv_mask", metadata["ctv_mask"])
                # Some CTV models emit additional hard structures (for
                # example artery/vein) alongside the tumor label. Preserve
                # that mask separately so a later full OAR segmentation
                # cannot overwrite the model-specific obstacle source.
                if metadata.get("oar_array") is not None:
                    self.memory.store("ctv_embedded_oar_array", metadata["oar_array"])
                if "label_stats" in metadata:
                    self.memory.store("ctv_label_stats", metadata["label_stats"])
                if "label_map" in metadata:
                    self.memory.store("ctv_label_map", metadata["label_map"])
                if metadata.get("full_label_array") is not None:
                    self.memory.store("ctv_full_labels", metadata["full_label_array"])
                # Store ctv_voxels and ctv_volume directly so
                # _build_planning_report can read them from memory.
                _cv = metadata.get("ctv_voxel_count")
                if not _cv:
                    try:
                        _cv = int(np.sum(np.asarray(metadata["ctv_array"]) > 0))
                    except Exception:
                        _cv = 0
                self.memory.store("ctv_voxels", _cv)
                _cvm3 = metadata.get("ctv_volume_mm3")
                if _cvm3:
                    self.memory.store("ctv_volume_mm3", _cvm3)
                if params.get("tumor_type"):
                    self.memory.store("tumor_type_used", params["tumor_type"])
                # BUG FIX 2026-06-16 (CTV/OAR label priority): for
                # pancreatic patients, CTV segmentation produces a
                # `pancreas` label (and sometimes other anatomically
                # adjacent structures like duodenum). OAR segmentation
                # (TotalSegmentator) ALSO produces `pancreas` and
                # `duodenum`. Without merging, the data tree, DVH,
                # and dose eval see TWO copies of the same label.
                # User's rule: CTV WINS. Merge the CTV labels into
                # the existing OAR map, OVERWRITING any voxels
                # currently tagged with the same label name. We keep
                # all other OAR labels (e.g. small_bowel, colon)
                # untouched.
                #
                # BUG FIX 2026-06-16 (runtime): the helpers
                # _merge_ctv_labels_into_oar / _strip_oar_labels_in_ctv
                # live on AgentMemory (where they can see the stored
                # arrays). Route through self.memory to call them.
                try:
                    self.memory._merge_ctv_labels_into_oar(
                        metadata.get("oar_array"),
                        metadata.get("organ_names"),
                        metadata.get("label_stats"),
                        metadata.get("label_map"),
                    )
                except AttributeError as exc:
                    # Fallback if memory helper is missing (defensive)
                    logger.debug("Memory label merge helper unavailable: %s", exc)
                    if "oar_array" in metadata:
                        self.memory.store("oar_array", metadata["oar_array"])
                    if "organ_names" in metadata:
                        self.memory.store("organ_names", metadata["organ_names"])
                if metadata.get("oar_array") is not None and not self.memory.retrieve("oar_is_full"):
                    self.memory.store("oar_source", "ctv_embedded")
                    self.memory.store("oar_is_full", False)
            elif tool_name == "oar_segmentation":
                logger.info("OAR segmentation result: oar_array=%s, organ_names=%s", "oar_array" in metadata, "organ_names" in metadata)
                # BUG FIX 2026-06-16: BEFORE storing the new OAR
                # array, REMOVE any labels that are also in the
                # CTV label map (CTV wins). This handles the case
                # where OAR runs FIRST (before CTV) — when CTV
                # eventually runs, the CTV labels are merged on
                # top via _merge_ctv_labels_into_oar. But if the
                # user runs OAR again after CTV, this prevents the
                # OAR's `pancreas` from overwriting the CTV's
                # `pancreas`.
                oar_array = metadata.get("oar_array")
                organ_names = metadata.get("organ_names")
                organ_counts = metadata.get("organ_counts")
                if oar_array is not None:
                    # BUG FIX 2026-06-16: route helper through self.memory
                    try:
                        oar_array, organ_names, organ_counts = self.memory._strip_oar_labels_in_ctv(
                            oar_array, organ_names, organ_counts
                        )
                    except AttributeError as exc:
                        logger.debug("Memory OAR label strip helper unavailable: %s", exc)
                if oar_array is not None:
                    self.memory.store("oar_array", oar_array)
                if organ_names is not None:
                    self.memory.store("organ_names", organ_names)
                    logger.info(f"Stored organ_names: {organ_names}")
                if organ_counts is not None:
                    self.memory.store("organ_counts", organ_counts)
                self.memory.store("oar_source", "totalsegmentator")
                self.memory.store("oar_is_full", True)

            if tool_name == "trajectory_planning" and "trajectories" in metadata:
                self.memory.store("trajectories", metadata["trajectories"])
            elif tool_name == "seed_planning":
                if "optimal_plan" in metadata:
                    self.memory.store("seed_positions", metadata["optimal_plan"])
                    self.memory.store("total_seeds", metadata.get("total_seeds", 0))
                if "dose_distribution" in metadata:
                    self.memory.store("dose_distribution", metadata["dose_distribution"])
            elif tool_name == "dose_engine" and result.data is not None:
                self.memory.store("dose_distribution", result.data)
            elif tool_name == "dose_evaluation":
                # BUG FIX 2026-06-16 (clinical eval scaling): the
                # dose_evaluation result has metadata shaped like
                #   {metrics: {CTV: {V100, V150, D90, D2, Dmean, ...},
                #            colon: {Dmax, D2cc, ...}, ...},
                #    plan_score: 73, prescribed_dose: 1.0, ...}
                # but state.metrics was being set to result.metadata
                # directly, which means the nested CTV metrics were
                # at state.metrics.metrics.CTV.V100 — NOT at
                # state.metrics.v100. The clinical eval panel
                # reads state.metrics.v100 etc., so it found
                # nothing for the top-level fields and instead
                # rendered organ-level data (e.g. colon.Dmax=127)
                # as if it were a plan metric — producing the
                # wildly wrong values the user reported (Score
                # 7307 instead of 73, D2 2874 Gy instead of 280,
                # HI 93.64 instead of 0.42).
                #
                # FIX: store a FLAT dict at state.metrics so the
                # clinical eval can read top-level v100/d90/d2/etc.
                # directly. We pull:
                #   - plan_score, prescribed_dose from metadata
                #   - V100/V150/D90/D2/Dmean/ci/hi from the CTV
                #     sub-dict (the target structure)
                #   - oar_metrics map (organ name → {Dmax, D2cc, ...})
                _flat = {}
                _meta = result.metadata or {}
                # Top-level scalars
                for k in ("plan_score", "prescribed_dose", "voxel_volume_cc"):
                    if k in _meta:
                        _flat[k] = _meta[k]
                # Nested structure metrics: find the target structure
                # (the one with type=="target") and flatten its keys.
                _nested = _meta.get("metrics", {}) or {}
                _target_name = None
                # If result.data has structure_type info, use it;
                # otherwise default to 'CTV' (the most common target).
                if isinstance(result.data, dict):
                    _stype = (result.data.get("structure_type") or {})
                    for _n, _t in _stype.items():
                        if (_t or "").lower() == "target":
                            _target_name = _n
                            break
                if not _target_name:
                    _target_name = "CTV" if "CTV" in _nested else (next(iter(_nested), None))
                _target = _nested.get(_target_name, {}) if _target_name else {}
                # Map nested metric names (V100, D90, D2cc, ...) to
                # the keys the clinical eval panel expects (v100, d90,
                # d2cc, ...). D90 → d90, V100 → v100, etc.
                for _n_k, _v in _target.items():
                    if _n_k in ("dvh", "total_voxels", "volume_cc", "error"):
                        continue
                    _flat[_n_k.lower()] = _v
                # Build oar_metrics map: name → {Dmax, D2cc, ...}
                _oar = {}
                for _n, _m in _nested.items():
                    if _n == _target_name:
                        continue
                    if not isinstance(_m, dict) or "error" in _m:
                        continue
                    _oar[_n] = {
                        "dmax": _m.get("Dmax"),
                        "d2cc": _m.get("D2cc"),
                        "d1cc": _m.get("D1cc"),
                        "d0_1cc": _m.get("D0.1cc"),
                        "dmean": _m.get("Dmean"),
                        "v100": (_m.get("V100") or 0) * 100,  # → percent
                    }
                _flat["oar_metrics"] = _oar
                self.memory.store("metrics", _flat)

            # This execution path is the canonical owner of successful LLM
            # tool-call state. Callers must not store the same result again:
            # duplicate OAR storage can overwrite the CTV-priority merge.
            cs = self.memory.conversation_state
            if tool_name == "ctv_segmentation":
                cs["ctv_segmented"] = True
            elif tool_name == "oar_segmentation":
                cs["oar_segmented"] = True
            elif tool_name == "planning_pipeline":
                cs["planning_completed"] = True
                if "dose_metrics" in metadata:
                    self.memory.store("dose_metrics", metadata["dose_metrics"])
                if "total_seeds" in metadata:
                    self.memory.store("total_seeds", metadata["total_seeds"])
                seed_plan = self.memory.retrieve("seed_plan")
                if seed_plan is not None:
                    self.memory.store("seed_positions", seed_plan)
            if tool_name not in cs["last_tool_calls"]:
                cs["last_tool_calls"].append(tool_name)
            cs["last_tool_calls"] = cs["last_tool_calls"][-10:]

        self.memory.log_tool_call(tool_name, params, result)

        if progress_callback:
            progress_callback(f"{tool_name} completed", 100)

        return result

    # --- Tool Validation & Recovery ---
    # Validates tool results and automatically recovers from failures.
    # This is the core mechanism for reducing tool execution failures.

    # Immutable callable/config tables are intentionally class-scoped. Runtime
    # code reads them but never mutates them, so instances cannot leak state.
    _VALIDATORS = {
        "ctv_segmentation": lambda r, m: (
            r.success and m.get("ctv_volume_mm3", 0) > 0,
            "CTV volume is 0 — model may not match this anatomy"
        ),
        "oar_segmentation": lambda r, m: (
            r.success and len(m.get("organ_names", {})) > 0,
            "No organs detected"
        ),
        "code_executor": lambda r, m: (
            r.success and isinstance(r.data, dict) and not r.data.get("stderr", "").strip(),
            f"Code execution error: {(r.data or {}).get('stderr', '')[:200]}"
        ),
    }

    _RECOVERY_ACTIONS = {
        # CTV site ambiguity requires user clarification. Retrying after
        # deleting tumor_type would repeat the same request without adding
        # evidence and could select the wrong model in a future fallback.
        "oar_segmentation": [
            {"param_overrides": {"organ_type": "general"}, "note": "Retry with general organ model"},
        ],
    }

    def _validate_and_execute(self, tool_name: str, params: Dict, max_retries: int = 1) -> Any:
        """Execute tool with validation and automatic recovery.
        If result is invalid, tries recovery actions before giving up."""
        # Pre-execution: check file existence for path-based tools
        if "image_path" in params:
            path = params["image_path"]
            if not os.path.exists(path):
                # 1) Try the same basename in the canonical uploads dir.
                alt = os.path.join(os.path.dirname(__file__), "uploads", os.path.basename(path))
                if os.path.exists(alt):
                    params["image_path"] = alt
                    logger.info(f"Path corrected: {path} → {alt}")
                else:
                    # 2) Fall back to the agent's remembered ct_path.
                    #    The LLM occasionally fabricates a CT filename
                    #    (e.g. wrong year in a timestamped upload) when
                    #    a real CT is already loaded in the session. We
                    #    do NOT fail the tool call — we substitute the
                    #    path we actually have. Without this fallback
                    #    (2026-06-16 bug) the agent gets stuck in an
                    #    infinite File-not-found retry loop because the
                    #    fabricated basename differs from the real one
                    #    by just a digit, and the LLM can't self-correct.
                    try:
                        remembered = self.memory.retrieve("ct_path")
                    except Exception:
                        remembered = None
                    if remembered and os.path.exists(remembered):
                        logger.warning(
                            f"LLM-supplied image_path {path!r} not "
                            f"found; substituting remembered ct_path "
                            f"{remembered!r}"
                        )
                        params["image_path"] = remembered
                    else:
                        return ToolResult(success=False, error=f"File not found: {path}")
            # Store ct_path in memory for 3D reconstruction and other tools
            if tool_name in ("ctv_segmentation", "oar_segmentation"):
                self.memory.store("ct_path", params["image_path"])

        # Remove invalid mask paths — tools will fall back to agent memory
        for mask_key in ("ctv_mask_path", "oar_mask_path"):
            if mask_key in params and params[mask_key]:
                if not os.path.exists(params[mask_key]):
                    logger.warning(f"{mask_key} not found: {params[mask_key]}. Removing — tool will use memory fallback.")
                    params.pop(mask_key)

        # Execute
        result = self.registry.execute(tool_name, **params)
        meta = result.metadata or {}

        # Validate
        validator = self._VALIDATORS.get(tool_name)
        if validator:
            is_valid, reason = validator(result, meta)
            if not is_valid and max_retries > 0:
                logger.warning(f"Validation failed for {tool_name}: {reason}")
                # Try recovery actions
                recovery_actions = self._RECOVERY_ACTIONS.get(tool_name, [])
                for action in recovery_actions[:max_retries]:
                    logger.info(f"Recovery: {action['note']}")
                    overrides = action.get("param_overrides", {})
                    recovered_params = {**params}
                    for k, v in overrides.items():
                        if v is None:
                            recovered_params.pop(k, None)
                        else:
                            recovered_params[k] = v
                    result = self.registry.execute(tool_name, **recovered_params)
                    meta = result.metadata or {}
                    is_valid, reason = validator(result, meta)
                    if is_valid:
                        logger.info(f"Recovery succeeded for {tool_name}")
                        break
                if not is_valid:
                    logger.warning(f"All recovery attempts failed for {tool_name}: {reason}")

        return result

    def _store_label_with_metadata(self, label_array, ct_image_source, label_key: str):
        """Store label array WITH spatial metadata from the LPI-oriented CT.

        Segmentation tools (ctv_segmentation, oar_segmentation) receive the
        LPI-oriented ct_image and produce masks already in LPI space.
        We store with LPI metadata so DICOMOrient('LPI') in _get_label_array
        sees it's already oriented and skips the transform.

        NOTE: Previously this used ct_image_raw (pre-orient), which caused a
        double Z-flip — the mask was in LPI space but tagged with raw metadata,
        then DICOMOrient flipped Z again, making head↔feet swap."""
        try:
            import SimpleITK as sitk
        except ImportError:
            self.memory.store(label_key, label_array)
            return

        try:
            # Use the LPI-oriented CT image for metadata — mask is already in LPI space
            ct_lpi = ct_image_source
            # Handle both numpy arrays and SimpleITK Images as input
            if isinstance(label_array, sitk.Image):
                label_sitk = sitk.Cast(label_array, sitk.sitkUInt8)
            else:
                label_sitk = sitk.GetImageFromArray(np.asarray(label_array).astype(np.uint8))
            label_sitk.CopyInformation(ct_lpi)
            self.memory.store(label_key, label_sitk)
            logger.info(f"Stored {label_key} with LPI CT metadata (direction={label_sitk.GetDirection()})")
        except Exception as e:
            logger.warning(f"Failed to store {label_key} with metadata: {e}")
            self.memory.store(label_key, label_array)

    def _get_label_array(self, label_key: str):
        """Retrieve label array, applying DICOMOrient('LPI') if stored as SimpleITK image.
        This ensures the label orientation always matches the CT orientation."""
        import numpy as np
        try:
            import SimpleITK as sitk
        except ImportError:
            return self.memory.retrieve(label_key)

        stored = self.memory.retrieve(label_key)
        if stored is None:
            logger.info(f"[_get_label_array] {label_key}: NOT found in memory (planning_results keys: {list(self.memory.planning_results.keys())[:10]})")
            return None
        logger.info(f"[_get_label_array] {label_key}: found, type={type(stored).__name__}")

        if isinstance(stored, sitk.Image):
            try:
                oriented = sitk.DICOMOrient(stored, 'LPI')
                return sitk.GetArrayFromImage(oriented)
            except Exception as e:
                logger.warning(f"DICOMOrient failed for {label_key}: {e}")
                return sitk.GetArrayFromImage(stored)

        # Already a numpy array (from older code or fallback)
        return stored

    def _sanitize_params_for_json(self, params: Dict) -> Dict:
        """Sanitize tool parameters to make them JSON-serializable.

        Removes or converts objects that can't be serialized to JSON:
        - SimpleITK Image objects
        - Functions/methods
        - Custom objects
        - Numpy arrays (convert to list or remove)

        Keeps only JSON-serializable types: str, int, float, bool, list, dict, None
        """
        import json

        sanitized = {}
        for key, value in params.items():
            # Skip internal parameters that shouldn't be sent to LLM
            if key in ('_agent', 'step_callback', 'progress_callback'):
                continue

            # Check if value is JSON-serializable
            try:
                json.dumps(value)
                sanitized[key] = value
            except (TypeError, ValueError):
                # Not serializable - convert to string representation or skip
                if value is None:
                    sanitized[key] = None
                elif isinstance(value, (str, int, float, bool)):
                    sanitized[key] = value
                elif isinstance(value, (list, tuple)):
                    # Try to convert list items
                    try:
                        sanitized[key] = [str(item) if not isinstance(item, (str, int, float, bool, type(None))) else item for item in value]
                    except Exception:
                        sanitized[key] = f"<{type(value).__name__} with {len(value)} items>"
                elif isinstance(value, dict):
                    # Recursively sanitize dict
                    sanitized[key] = self._sanitize_params_for_json(value)
                else:
                    # Convert to string representation
                    sanitized[key] = f"<{type(value).__name__}>"

        return sanitized

    def _store_tool_result(self, tool_name: str, result):
        """Store tool result in memory based on tool type."""
        if not result.success:
            logger.debug("[STORE] Skipping %s: not successful", tool_name)
            return
        meta = result.metadata or {}
        logger.debug("[STORE] %s: metadata keys=%s", tool_name, list(meta.keys()))
        ct_image = self.memory.retrieve("ct_image")
        if tool_name == "ctv_segmentation" and "ctv_array" in meta:
            logger.debug(
                "[STORE] Storing ctv_array, shape=%s, ct_image=%s",
                getattr(meta["ctv_array"], "shape", "N/A"),
                "exists" if ct_image is not None else "None",
            )
            # Store as plain numpy array (like OAR) — do NOT wrap in SimpleITK
            # with LPI metadata. The 3D mask endpoint uses ct_spacing/ct_origin/
            # ct_direction for the world transform, and DICOMOrient('LPI') in
            # _get_label_array would reorient the array, causing a mismatch
            # between the array orientation and the metadata.
            self.memory.store("ctv_array", meta["ctv_array"])
            if "label_stats" in meta:
                self.memory.store("ctv_label_stats", meta["label_stats"])
            if "label_map" in meta:
                self.memory.store("ctv_label_map", meta["label_map"])
            # Store full multi-label array for data tree display
            if "full_label_array" in meta and meta["full_label_array"] is not None:
                if ct_image is not None:
                    self._store_label_with_metadata(meta["full_label_array"], ct_image, "ctv_full_labels")
                else:
                    self.memory.store("ctv_full_labels", meta["full_label_array"])
            # Store ctv_voxels and ctv_volume for report generation
            _cv = meta.get("ctv_voxel_count")
            if not _cv:
                try:
                    _cv = int(np.sum(np.asarray(meta["ctv_array"]) > 0))
                except Exception as _e:
                    logger.warning(f"[STORE] ctv_voxel_count fallback failed: {_e}")
                    _cv = 0
            self.memory.store("ctv_voxels", _cv)
            _cvm3 = meta.get("ctv_volume_mm3")
            if _cvm3:
                self.memory.store("ctv_volume_mm3", _cvm3)
            tumor_type_used = meta.get("tumor_type_used") or meta.get("tumor_type")
            if tumor_type_used:
                self.memory.store("tumor_type_used", tumor_type_used)
            if meta.get("ctv_source"):
                self.memory.store("ctv_source", meta["ctv_source"])
            logger.info(f"[STORE] ctv_segmentation: ctv_voxels={_cv}, ctv_volume_mm3={_cvm3}, tumor_type={tumor_type_used}")
        elif tool_name == "oar_segmentation":
            if "oar_array" in meta:
                # Store as plain numpy array (like CTV) — do NOT wrap in SimpleITK
                # with LPI metadata. The 3D mask endpoint uses ct_spacing/ct_origin/
                # ct_direction for the world transform, and DICOMOrient('LPI') in
                # _get_label_array would reorient the array, causing a mismatch.
                self.memory.store("oar_array", meta["oar_array"])
            if "organ_names" in meta:
                self.memory.store("organ_names", meta["organ_names"])
            if "organ_counts" in meta:
                self.memory.store("organ_counts", meta["organ_counts"])
        elif tool_name == "dose_engine" and result.data is not None:
            self.memory.store("dose_distribution", result.data)
        elif tool_name == "planning_pipeline":
            # Note: planning_pipeline stores seed_plan/dose_distribution directly
            # in _step_seed_planning. Do NOT overwrite dose_distribution here —
            # _step_seed_planning stores planning grid dose (128,128,64),
            # _step_dose_calc stores resampled dose (512,512,48) as dose_distribution_gy.
            if "trajectories" in meta:
                self.memory.store("trajectories", meta["trajectories"])
            # Don't overwrite dose_distribution — preserve planning grid version
            # The resampled version is stored as dose_distribution_gy by _step_dose_calc
            if "dose_metrics" in meta:
                self.memory.store("dose_metrics", meta["dose_metrics"])
            if "total_seeds" in meta:
                self.memory.store("total_seeds", meta["total_seeds"])
            # Map seed_plan → seed_positions so data tree and 3D view can display seeds.
            # The planning pipeline stores seed_plan internally; the viewer needs seed_positions.
            _sp = self.memory.retrieve("seed_plan")
            if _sp is not None:
                self.memory.store("seed_positions", _sp)
        elif tool_name == "seed_planning":
            if "optimal_plan" in meta:
                self.memory.store("seed_plan", meta["optimal_plan"])
            if "dose_distribution" in meta:
                self.memory.store("dose_distribution", meta["dose_distribution"])
        elif tool_name == "trajectory_planning" and "trajectories" in meta:
            self.memory.store("trajectories", meta["trajectories"])

        # Update structured conversation state after every successful tool.
        # This drives the router's state-aware classification and the
        # context builder's structured summary.
        cs = self.memory.conversation_state
        if tool_name == "ctv_segmentation":
            cs["ctv_segmented"] = True
        elif tool_name == "oar_segmentation":
            cs["oar_segmented"] = True
        elif tool_name == "planning_pipeline":
            cs["planning_completed"] = True
        if tool_name not in cs["last_tool_calls"]:
            cs["last_tool_calls"].append(tool_name)
        # Keep only last 10 tool calls
        cs["last_tool_calls"] = cs["last_tool_calls"][-10:]
