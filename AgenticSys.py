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
    result = agent.chat("先分割CTV和OAR，然后生成治疗计划")
"""

import os
import sys
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import SimpleITK as sitk

logger = logging.getLogger(__name__)


class PlanningPhase(Enum):
    """Phases of the brachytherapy planning workflow."""
    IDLE = "idle"
    PRE_OPERATIVE = "pre_operative"
    INTRA_OPERATIVE = "intra_operative"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolRegistry:
    """Registry for all available planning tools."""
    
    def __init__(self):
        self._tools: Dict[str, Any] = {}
    
    def register(self, tool):
        self._tools[tool.name] = tool
    
    def get(self, name: str):
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}. Available: {list(self._tools.keys())}")
        return self._tools[name]
    
    def list_tools(self) -> List[Dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "output_schema": tool.output_schema,
            }
            for tool in self._tools.values()
        ]
    
    def execute(self, tool_name: str, **kwargs):
        tool = self.get(tool_name)
        return tool.execute(**kwargs)
    
    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    def to_openai_tools(self) -> List[Dict]:
        """Convert tools to OpenAI function calling format."""
        openai_tools = []
        for tool in self._tools.values():
            func_def = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": tool.input_schema.get("properties", {}),
                        "required": tool.input_schema.get("required", []),
                    }
                }
            }
            openai_tools.append(func_def)
        return openai_tools

    def to_tool_descriptions(self) -> str:
        """Generate human-readable tool descriptions for LLM prompts."""
        lines = []
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
            if tool.input_schema.get("properties"):
                props = tool.input_schema["properties"]
                req = tool.input_schema.get("required", [])
                param_strs = []
                for pname, pdef in props.items():
                    tag = " (required)" if pname in req else ""
                    ptype = pdef.get("type", "any")
                    param_strs.append(f"    {pname}: {ptype}{tag}")
                lines.extend(param_strs)
        return "\n".join(lines)


class AgentMemory:
    """Persistent memory for the agent session."""
    
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.patient_data: Dict = {}
        self.planning_results: Dict = {}
        self.tool_results: List[Dict] = []
        self.conversation: List[Dict] = []
        self.context_summary: str = ""
        self.compaction_count: int = 0
        self.current_phase: PlanningPhase = PlanningPhase.IDLE
        self.deviation_threshold_mm: float = 2.0
        self._ui_state: Dict = {}
    
    def store(self, key: str, value: Any):
        self.planning_results[key] = value
    
    def retrieve(self, key: str, default: Any = None) -> Any:
        return self.planning_results.get(key, default)
    
    def log_tool_call(self, tool_name: str, inputs: Dict, result):
        self.tool_results.append({
            "tool": tool_name,
            "inputs": {k: str(v)[:100] for k, v in inputs.items()},
            "success": result.success,
            "message": result.message,
            "execution_time": result.execution_time,
        })
    
    def add_message(self, role: str, content: str):
        self.conversation.append({"role": role, "content": content})
    
    def set_ui_state(self, state: Dict):
        """Update UI state from frontend (selected files, etc)."""
        self._ui_state.update(state)
    
    def get_ui_state(self) -> Dict:
        return dict(self._ui_state)
    
    def get_ui_state_summary(self) -> str:
        """Generate a human-readable summary of current UI state for the LLM."""
        parts = []
        ct = self._ui_state.get("ct_path", "")
        ctv = self._ui_state.get("ctv_path", "")
        oar = self._ui_state.get("oar_path", "")
        plan_mode = self._ui_state.get("plan_mode", "")
        dev_threshold = self._ui_state.get("dev_threshold", "")
        
        if ct:
            parts.append(f"CT Image loaded: `{ct}`")
        if ctv:
            parts.append(f"CTV Mask loaded: `{ctv}`")
        if oar:
            parts.append(f"OAR Mask loaded: `{oar}`")
        if plan_mode:
            parts.append(f"Planning Mode: {plan_mode}")
        if dev_threshold:
            parts.append(f"Deviation Threshold: {dev_threshold} mm")
        
        if not parts:
            return "No files loaded in the UI yet. The user has not selected any CT/CTV/OAR files."
        
        return "Current UI state:\n" + "\n".join(parts)
    
    def needs_compaction(self, max_messages: int = 12) -> bool:
        return len(self.conversation) > max_messages
    
    def compact(self, keep_last: int = 6) -> str:
        """Summarize old messages and keep only recent ones."""
        if len(self.conversation) <= keep_last:
            return self.context_summary
        
        overflow = self.conversation[:-keep_last]
        summary_parts = []
        for msg in overflow:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]
            if role == "user":
                summary_parts.append(f"User: {content}")
            elif role == "assistant":
                summary_parts.append(f"Assistant: {content}")
        
        if self.context_summary:
            self.context_summary += "\n" + "\n".join(summary_parts)
        else:
            self.context_summary = "Previous conversation summary:\n" + "\n".join(summary_parts)
        
        self.conversation = self.conversation[-keep_last:]
        self.compaction_count += 1
        return self.context_summary
    
    def export_state(self, path: str):
        state = {
            "session_id": self.session_id,
            "phase": self.current_phase.value,
            "tool_results": self.tool_results,
            "conversation": self.conversation,
            "planning_summary": {
                k: str(v)[:200] if not isinstance(v, (int, float, str, bool, list, dict)) else v
                for k, v in self.planning_results.items()
            },
        }
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)
        logger.info(f"Agent state exported to {path}")


class BrachyAgent:
    """
    LLM-driven brachytherapy planning agent with self-evolution.
    
    Capabilities:
    1. Pre-operative: CT -> Segmentation -> Trajectory -> Seed Plan -> Dose Eval
    2. Intra-operative: Imaging -> Seed Detection -> Deviation Check -> Replanning
    3. LLM Function Calling: LLM can discover and invoke tools directly
    4. Self-Evolution: Learns from experiences, creates skills, writes new tools
    5. Code Writing: Can generate new tool code and register it dynamically
    """
    
    def __init__(self, session_id: str = "default", config: Optional[Dict] = None):
        self.memory = AgentMemory(session_id)
        self.registry = ToolRegistry()
        self.config = config or {}
        self._load_tools()

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
        )

        self.interaction_memory = InteractionMemory(session_id=session_id)
        self.preference_store = PreferenceStore(user_id=session_id)
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
        ]:
            self.skill_registry.register(skill_class())

        self._init_brain_system()
        self._init_self_evolution()
        self._init_enhanced_integration()

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
                anthropic_base = os.environ.get("ANTHROPIC_BASE_URL", "")
                anthropic_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "") or os.environ.get("ANTHROPIC_API_KEY", "")
                if anthropic_base and anthropic_token:
                    provider = "anthropic"
                    llm_config = {
                        provider: {
                            "enabled": True,
                            "model": os.environ.get("ANTHROPIC_MODEL", "MiniMax-M2.7-highspeed"),
                            "base_url": anthropic_base,
                            "api_key": anthropic_token,
                        }
                    }
                else:
                    provider = os.environ.get("BRACHY_LLM_PROVIDER", "openrouter")
                    llm_config = {provider: {"enabled": True}}

            self.brain_router = LLMRouter(llm_config)
            self.brain_rag = get_rag()

            tool_registry = get_tool_registry()
            self.brain_executor = CaseExecutor(tool_registry)

            self.brain_bridge = initialize_brain_integration()
            self.brain_bridge.set_brain_registry(tool_registry)
            self.brain_bridge.set_plan_executor(self.brain_executor)

            self.tool_code_writer = ToolCodeWriter(tool_registry=self.registry)

            self._brain_available = len(self.brain_router.providers) > 0

            if self._brain_available:
                default_llm = self.brain_router.providers.get(self.brain_router.default_provider)
                if default_llm:
                    self.planner_decider = PlannerDecider(default_llm, tool_registry)
                    self.clinical_decider = ClinicalDecider(default_llm)
                    self.quality_decider = QualityDecider(default_llm)

            logger.info(f"Brain system initialized: provider={self.brain_router.default_provider}, "
                       f"tools={len(tool_registry.list_all())}")

        except ImportError as e:
            logger.warning(f"Brain system not available: {e}")
        except Exception as e:
            logger.warning(f"Brain system initialization failed: {e}")

    def _init_self_evolution(self):
        """Initialize self-evolution system."""
        self.evolution_engine = None
        try:
            from memory import ExperienceMemory, SelfEvolutionEngine
            self.exp_memory = ExperienceMemory(session_id=self.memory.session_id)
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
                agent=self, session_id=self.memory.session_id, llm_callback=llm_callback,
            )
            logger.info("Enhanced self-evolving integration initialized")
        except Exception as e:
            logger.warning(f"Enhanced integration not available: {e}")

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
        if not self.brain_available:
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
        from tool_factory.CTV_seg import CTVSegmentationTool
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
            from tool_factory.output.report_generator import ReportGeneratorTool
            self.registry.register(ReportGeneratorTool())
        except ImportError as e:
            logger.warning(f"ReportGeneratorTool not available: {e}")

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

        self.registry.register(CTVSegmentationTool())
        self.registry.register(OARSegmentationTool())
        self.registry.register(DoseEngineTool())
        self.registry.register(DoseEvaluationTool())
        self.registry.register(SeedPlanningTool())
        self.registry.register(SeedSegmentationTool())
        self.registry.register(TrajectoryPlanningTool())

        logger.info(f"Registered {len(self.registry.tool_names)} tools: {self.registry.tool_names}")
    
    def _execute_tool_with_memory(self, tool_name: str, params: Dict) -> Any:
        """Execute a tool, automatically injecting memory-stored data."""
        ct_image = self.memory.retrieve("ct_image")
        ctv_array = self.memory.retrieve("ctv_array")
        oar_array = self.memory.retrieve("oar_array")
        trajectories = self.memory.retrieve("trajectories")
        radiation_volume = self.memory.retrieve("radiation_volume")
        dose_distribution = self.memory.retrieve("dose_distribution")
        seed_positions = self.memory.retrieve("seed_positions")

        if tool_name == "ctv_segmentation" and "image" not in params:
            if ct_image is not None:
                params["image"] = ct_image
        elif tool_name == "oar_segmentation" and "image" not in params:
            if ct_image is not None:
                params["image"] = ct_image
        elif tool_name == "trajectory_planning":
            if "dose_image" not in params and ct_image is not None:
                params["dose_image"] = ct_image
            if "radiation_volume" not in params:
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
        elif tool_name == "seed_planning":
            if "dose_image" not in params and ct_image is not None:
                params["dose_image"] = ct_image
            if "radiation_volume" not in params and radiation_volume is not None:
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

        result = self.registry.execute(tool_name, **params)

        if result.success:
            if tool_name == "ctv_segmentation" and "ctv_array" in result.metadata:
                self.memory.store("ctv_array", result.metadata["ctv_array"])
            elif tool_name == "oar_segmentation" and "oar_array" in result.metadata:
                self.memory.store("oar_array", result.metadata.get("oar_array"))
            elif tool_name == "trajectory_planning" and "trajectories" in result.metadata:
                self.memory.store("trajectories", result.metadata["trajectories"])
            elif tool_name == "seed_planning":
                if "optimal_plan" in result.metadata:
                    self.memory.store("seed_positions", result.metadata["optimal_plan"])
                    self.memory.store("total_seeds", result.metadata.get("total_seeds", 0))
                if "dose_distribution" in result.metadata:
                    self.memory.store("dose_distribution", result.metadata["dose_distribution"])
            elif tool_name == "dose_engine" and "dose_distribution" in result.data:
                self.memory.store("dose_distribution", result.data["dose_distribution"])
            elif tool_name == "dose_evaluation":
                self.memory.store("metrics", result.metadata)

        self.memory.log_tool_call(tool_name, params, result)
        return result

    def _run_llm_function_calling(self, message: str, steps: List[Dict], step_id_ref: List[int]) -> str:
        """
        LLM-driven function calling loop with enhanced self-evolving memory.
        """
        # Auto-compact conversation history if too long
        compaction_triggered = False
        if self.memory.needs_compaction():
            self.memory.compact(keep_last=6)
            compaction_triggered = True

        enhanced_context = ""
        if self.enhanced:
            pre_ctx = self.enhanced.pre_task_hook(message)
            if pre_ctx.get("reflexion_warnings"):
                enhanced_context += "\n### Past Experience Warnings\n" + pre_ctx["reflexion_warnings"]
            if pre_ctx.get("matched_sop"):
                sop = pre_ctx["matched_sop"]
                enhanced_context += f"\n### Matched SOP: {sop['name']} (success: {sop['success_rate']:.0%})\n"
                enhanced_context += f"Recommended chain: {' -> '.join(sop['steps'])}\n"
            if pre_ctx.get("crystallized_skill"):
                sk = pre_ctx["crystallized_skill"]
                enhanced_context += f"\n### Crystallized Skill: {sk['name']} (success: {sk['success_rate']:.0%})\n"
                enhanced_context += f"Tool chain: {' -> '.join(sk['tool_chain'])}\n"
            if pre_ctx.get("user_preferences"):
                prefs = pre_ctx["user_preferences"]
                if prefs:
                    enhanced_context += f"\n### User Preferences\n"
                    for pid, pv in prefs.items():
                        enhanced_context += f"- {pv['name']}: {pv['value']} (confidence: {pv['confidence']:.2f})\n"

        ui_state_summary = self.memory.get_ui_state_summary()

        system_prompt = (
            "You are BrachyBot, an AI assistant for brachytherapy treatment planning.\n"
            "You have access to the following tools. When the user asks you to do something, "
            "call the appropriate tools with the correct parameters.\n\n"
            "Available tools:\n"
            f"{self.registry.to_tool_descriptions()}\n\n"
            "ADDITIONAL CAPABILITIES:\n"
            "- **Code Execution**: You can write and execute Python code on demand using the `code_executor` tool.\n"
            "  Use it for ad-hoc tasks: computing statistics, analyzing data, etc.\n"
            "  The code runs in a sandboxed Python environment with numpy, scipy, nibabel, SimpleITK available.\n"
            "- **Filesystem Browser**: You can list directories and inspect file metadata using `filesystem_browser`.\n"
            "- **Knowledge Base**: You have access to brachytherapy clinical guidelines, tool documentation, and past experience.\n\n"
            "WEB INTERFACE CONTEXT:\n"
            "You are accessed through a web interface with two panels:\n"
            "- LEFT PANEL: Chat conversation area where users type messages.\n"
            "- RIGHT PANEL: Interactive controls with tabs:\n"
            "  1. **Input tab**: File path fields for CT Image (required), CTV Mask (optional), OAR Mask (optional).\n"
            "     Each field has a text input AND a 'Browse' button to select local files (.nii, .nii.gz, .mha, .nrrd).\n"
            "     Planning Mode selector (Rule-Based / RL), Deviation Threshold input.\n"
            "     Action buttons: 'Start Plan', 'Intraop', 'Reset'.\n"
            "  2. **Metrics tab**: Target coverage metrics (V100, V150, V200, D90, D95, Score) and OAR constraint table.\n"
            "  3. **DVH tab**: Dose-Volume Histogram chart.\n"
            "  4. **Seeds tab**: Individual seed positions and doses.\n"
            "  5. **Viewers tab**: Interactive CT slice viewers (Axial, Sagittal, Coronal) and 3D reconstruction.\n"
            "     The Viewers tab has controls for: Window/Level adjustment, Threshold segmentation,\n"
            "     CTV/OAR overlay toggles, and 3D mesh reconstruction from threshold.\n"
            "     CT images are AUTOMATICALLY loaded into the viewers when the user uploads via Browse.\n\n"
            "Users can input CT paths by typing in the text fields OR clicking 'Browse' buttons in the Input tab.\n"
            "When the user selects a file via Browse, you AUTOMATICALLY see the path — you do NOT need to ask for it.\n"
            "After planning, results appear in the Metrics, DVH, Seeds, and Viewers panels automatically.\n\n"
            "CRITICAL: DO NOT generate static images (matplotlib, plt.savefig, etc.).\n"
            "The web UI has built-in interactive viewers. When the user wants to view CT, CTV, or OAR:\n"
            "1. Use `code_executor` to analyze the data (dimensions, HU values, tumor location, etc.)\n"
            "2. Tell the user to check the 'Viewers' tab in the right panel\n"
            "3. Suggest they use the Window/Level, Threshold, or CTV overlay controls\n"
            "NEVER use matplotlib, plt.imshow, or save images to disk for viewing.\n\n"
            "VIEWER CONTROL (LLM-callable via code_executor):\n"
            "You can control the CT viewer through API calls. Use `code_executor` with this pattern:\n"
            "```python\n"
            "import requests\n"
            "res = requests.post('http://localhost:8080/api/viewer/control', json={\n"
            '    "action": "set_preset", "preset": "lung"\n'
            "})\n"
            "print(res.json())\n"
            "```\n"
            "Available viewer actions:\n"
            "- `set_preset`: Apply window preset. Presets: soft (W:400 L:40), bone (W:2000 L:400), lung (W:1500 L:-600), brain (W:80 L:40)\n"
            "- `set_window`: Set custom window/level. Params: window (int), level (int)\n"
            "- `navigate_slice`: Navigate to specific slice. Params: axis (axial|sagittal|coronal), slice_index (int)\n"
            "- `set_threshold`: Set HU threshold overlay. Params: threshold (int, HU value)\n"
            "- `toggle_overlay`: Toggle CTV/OAR overlay. Params: overlay (ctv|oar)\n"
            "- `get_state`: Get current viewer state (no params)\n\n"
            f"CURRENT UI STATE:\n{ui_state_summary}\n\n"
            "IMPORTANT RULES:\n"
            "1. When the user asks to segment, plan, evaluate, etc., call the tools directly.\n"
            "2. Use tool_call blocks to invoke tools.\n"
            "3. After calling tools, summarize the results for the user.\n"
            "4. If the user asks you to inspect a file, write code, or compute something — use `code_executor`.\n"
            "5. If the user asks about files or directories — use `filesystem_browser`.\n"
            "6. If you need CT data and it's NOT in the UI state above, tell the user to use the Input panel.\n"
            "7. For self-evolution (进化/总结经验), respond with a summary of learned experiences.\n"
            "8. For writing new tools (写工具/create tool), describe the tool specification.\n"
            "9. Be clinical, precise, and actionable.\n"
            "10. Check past experiences and matched SOPs before planning.\n"
            "11. When the user asks to adjust the viewer (e.g., 'switch to lung window', 'go to slice 50'),\n"
            "    use `code_executor` to call the viewer control API as described above.\n\n"
            f"{enhanced_context}\n"
            f"{self.memory.context_summary}\n\n"
            "Tool call format:\n"
            "```tool_call\n"
            '{"tool": "tool_name", "params": {"param1": "value1"}}\n'
            "```\n\n"
            "CRITICAL: After you have received all tool results, you MUST provide a final text response to the user.\n"
            "Do NOT output another tool_call block after you have the results. Instead, summarize the results in plain text.\n"
            "The conversation ends when you output plain text without any tool_call blocks.\n"
            "Example flow:\n"
            "1. User asks a question\n"
            "2. You call a tool with ```tool_call\n"
            "3. You see the tool result\n"
            "4. You respond with plain text summarizing the result (NO tool_call blocks)\n"
            "IMPORTANT: Once you have the tool results, DO NOT call more tools. Just summarize for the user.\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
        ]
        msg_history = self.memory.conversation[-6:]
        for msg in msg_history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        max_iterations = 8
        iteration = 0
        final_response = ""
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        total_latency_ms = 0.0
        llm_calls = 0

        while iteration < max_iterations:
            iteration += 1

            try:
                response = self.brain_router.chat_messages(messages=messages)
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                return f"LLM error: {e}"

            if response.usage:
                total_usage["prompt_tokens"] += response.usage.get("prompt_tokens", 0)
                total_usage["completion_tokens"] += response.usage.get("completion_tokens", 0)
                total_usage["total_tokens"] += response.usage.get("total_tokens", 0)
            total_latency_ms += response.latency_ms or 0
            llm_calls += 1

            content = response.content or ""

            # Check for tool calls from both native API response and parsed text
            tool_calls = []
            if response.tool_calls:
                # Native tool calls from API (Anthropic format)
                for tc in response.tool_calls:
                    tool_calls.append({
                        "id": tc.get("id", f"tool_{len(tool_calls)}"),
                        "tool": tc.get("name", ""),
                        "params": tc.get("arguments", tc.get("input", {})),
                    })
            else:
                # Parse from text format (```tool_call blocks)
                tool_calls = self._parse_tool_calls(content)

            if not tool_calls:
                final_response = content
                break

            # If we've already executed tools and LLM outputs more tool calls,
            # check if there's meaningful text before the tool calls - use that as final response
            if any(s["type"] == "tool" for s in steps):
                import re as _re
                text_before = _re.sub(r'```tool_call\s*\n.*?\n```', '', content, flags=_re.DOTALL).strip()
                text_before = _re.sub(r'<minimax:tool_call>.*?</minimax:tool_call>', '', text_before, flags=_re.DOTALL).strip()
                if len(text_before) > 10:
                    final_response = text_before
                    break

            # Filter out tool calls with empty required params, normalize param names
            valid_tool_calls = []
            for tc in tool_calls:
                tn = tc.get("tool", "")
                p = tc.get("params", {})
                if tn == "filesystem_browser":
                    if "dirPath" in p and "path" not in p:
                        p["path"] = p.pop("dirPath")
                    if "directory" in p and "path" not in p:
                        p["path"] = p.pop("directory")
                    if "action" not in p:
                        p["action"] = "list"
                    if not p.get("path", "").strip():
                        continue
                if tn == "code_executor":
                    if "script" in p and "code" not in p:
                        p["code"] = p.pop("script")
                    if "python" in p and "code" not in p:
                        p["code"] = p.pop("python")
                    if not p.get("code", "").strip():
                        continue
                valid_tool_calls.append(tc)

            if not valid_tool_calls:
                final_response = content
                break

            tool_calls = valid_tool_calls

            for tc in tool_calls:
                tool_name = tc.get("tool", "")
                params = tc.get("params", {})
                tool_id = tc.get("id", f"tool_{step_id_ref[0]}")

                step_id_ref[0] += 1
                steps.append({
                    "id": step_id_ref[0],
                    "type": "tool",
                    "title": f"Calling {tool_name}",
                    "content": json.dumps(params, default=str)[:200],
                    "status": "pending",
                    "tool": tool_name,
                    "params": params,
                })

                if tool_name in ("self_evolve", "evolve", "进化", "总结经验"):
                    result_text = self._handle_self_evolution()
                elif tool_name in ("code_writer", "write_tool", "create_tool", "写工具", "新工具"):
                    result_text = self._handle_code_writing(params)
                elif tool_name in self.registry.tool_names:
                    try:
                        result = self._execute_tool_with_memory(tool_name, params)
                        if result.success:
                            result_text = result.message
                            # Include actual output for code_executor so LLM can summarize
                            if tool_name == "code_executor" and hasattr(result, "data") and result.data:
                                stdout = result.data.get("stdout", "").strip()
                                if stdout:
                                    result_text = stdout[:1000]
                            if result.success and hasattr(result, "metadata") and result.metadata:
                                metrics_summary = {}
                                for k, v in result.metadata.items():
                                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                                        metrics_summary[k] = v
                                if metrics_summary:
                                    result_text += f" | Metrics: {metrics_summary}"
                        else:
                            # Include data.stderr if available (for code_executor)
                            error_msg = result.error or ""
                            if hasattr(result, "data") and result.data and "stderr" in result.data:
                                stderr = result.data["stderr"][:300]
                                error_msg = f"{error_msg}: {stderr}" if error_msg else stderr
                            result_text = f"Error: {error_msg}" if error_msg else "Error: execution failed"
                    except Exception as e:
                        result_text = f"Exception: {str(e)}"
                        logger.error(f"Tool {tool_name} failed: {e}")
                else:
                    result_text = f"Unknown tool: {tool_name}. Available: {self.registry.tool_names}"

                step_status = "done" if "Error" not in result_text and "Exception" not in result_text else "error"
                steps[-1]["status"] = step_status
                steps[-1]["result"] = result_text[:200]

                # Append tool call and result to messages
                # Use a simple format that works with all providers
                messages.append({
                    "role": "assistant",
                    "content": f"Called {tool_name}."
                })
                messages.append({
                    "role": "user",
                    "content": f"Tool result: {result_text}"
                })

        if final_response:
            final_response = self._clean_response_text(final_response)
            step_id_ref[0] += 1
            steps.append({
                "id": step_id_ref[0],
                "type": "assistant",
                "title": "AI Response",
                "content": final_response,
                "status": "done",
            })
        else:
            final_response = "Tools executed. Check the execution trace above for results."

        self.memory.add_message("assistant", final_response)
        return final_response, {
            "usage": total_usage,
            "latency_ms": round(total_latency_ms, 1),
            "llm_calls": llm_calls,
        }

    def _clean_response_text(self, content: str) -> str:
        """Remove tool call blocks from LLM response, keep only user-facing text."""
        import re as _re
        cleaned = _re.sub(r'```tool_call\s*\n.*?\n```', '', content, flags=_re.DOTALL).strip()
        cleaned = _re.sub(r'<minimax:tool_call>.*?</minimax:tool_call>', '', cleaned, flags=_re.DOTALL).strip()
        cleaned = _re.sub(r'<invoke.*?</invoke>', '', cleaned, flags=_re.DOTALL).strip()
        return cleaned

    def _run_llm_function_calling_stream(self, message: str, steps: List[Dict], step_id_ref: List[int], yield_event):
        """
        Streaming version of _run_llm_function_calling. Returns (events_list, response, llm_meta).
        """
        import time as _time
        events = []

        # Auto-compact conversation history if too long
        compaction_triggered = False
        if self.memory.needs_compaction():
            self.memory.compact(keep_last=6)
            compaction_triggered = True

        enhanced_context = ""
        if self.enhanced:
            pre_ctx = self.enhanced.pre_task_hook(message)
            if pre_ctx.get("reflexion_warnings"):
                enhanced_context += "\n### Past Experience Warnings\n" + pre_ctx["reflexion_warnings"]
            if pre_ctx.get("matched_sop"):
                sop = pre_ctx["matched_sop"]
                enhanced_context += f"\n### Matched SOP: {sop['name']} (success: {sop['success_rate']:.0%})\n"
                enhanced_context += f"Recommended chain: {' -> '.join(sop['steps'])}\n"
            if pre_ctx.get("crystallized_skill"):
                sk = pre_ctx["crystallized_skill"]
                enhanced_context += f"\n### Crystallized Skill: {sk['name']} (success: {sk['success_rate']:.0%})\n"
                enhanced_context += f"Tool chain: {' -> '.join(sk['tool_chain'])}\n"
            if pre_ctx.get("user_preferences"):
                prefs = pre_ctx["user_preferences"]
                if prefs:
                    enhanced_context += f"\n### User Preferences\n"
                    for pid, pv in prefs.items():
                        enhanced_context += f"- {pv['name']}: {pv['value']} (confidence: {pv['confidence']:.2f})\n"

        ui_state_summary = self.memory.get_ui_state_summary()

        system_prompt = (
            "You are BrachyBot, an AI assistant for brachytherapy treatment planning.\n"
            "You have access to the following tools. When the user asks you to do something, "
            "call the appropriate tools with the correct parameters.\n\n"
            "Available tools:\n"
            f"{self.registry.to_tool_descriptions()}\n\n"
            "ADDITIONAL CAPABILITIES:\n"
            "- **Code Execution**: You can write and execute Python code on demand using the `code_executor` tool.\n"
            "  Use it for ad-hoc tasks: computing statistics, analyzing data, etc.\n"
            "  The code runs in a sandboxed Python environment with numpy, scipy, nibabel, SimpleITK available.\n"
            "- **Filesystem Browser**: You can list directories and inspect file metadata using `filesystem_browser`.\n"
            "- **Knowledge Base**: You have access to brachytherapy clinical guidelines, tool documentation, and past experience.\n\n"
            "WEB INTERFACE CONTEXT:\n"
            "You are accessed through a web interface with two panels:\n"
            "- LEFT PANEL: Chat conversation area where users type messages.\n"
            "- RIGHT PANEL: Interactive controls with tabs:\n"
            "  1. **Input tab**: File path fields for CT Image (required), CTV Mask (optional), OAR Mask (optional).\n"
            "     Each field has a text input AND a 'Browse' button to select local files (.nii, .nii.gz, .mha, .nrrd).\n"
            "     Planning Mode selector (Rule-Based / RL), Deviation Threshold input.\n"
            "     Action buttons: 'Start Plan', 'Intraop', 'Reset'.\n"
            "  2. **Metrics tab**: Target coverage metrics (V100, V150, V200, D90, D95, Score) and OAR constraint table.\n"
            "  3. **DVH tab**: Dose-Volume Histogram chart.\n"
            "  4. **Seeds tab**: Individual seed positions and doses.\n"
            "  5. **Viewers tab**: Interactive CT slice viewers (Axial, Sagittal, Coronal) and 3D reconstruction.\n"
            "     The Viewers tab has controls for: Window/Level adjustment, Threshold segmentation,\n"
            "     CTV/OAR overlay toggles, and 3D mesh reconstruction from threshold.\n"
            "     CT images are AUTOMATICALLY loaded into the viewers when the user uploads via Browse.\n\n"
            "Users can input CT paths by typing in the text fields OR clicking 'Browse' buttons in the Input tab.\n"
            "When the user selects a file via Browse, you AUTOMATICALLY see the path — you do NOT need to ask for it.\n"
            "After planning, results appear in the Metrics, DVH, Seeds, and Viewers panels automatically.\n\n"
            "CRITICAL: DO NOT generate static images (matplotlib, plt.savefig, etc.).\n"
            "The web UI has built-in interactive viewers. When the user wants to view CT, CTV, or OAR:\n"
            "1. Use `code_executor` to analyze the data (dimensions, HU values, tumor location, etc.)\n"
            "2. Tell the user to check the 'Viewers' tab in the right panel\n"
            "3. Suggest they use the Window/Level, Threshold, or CTV overlay controls\n"
            "NEVER use matplotlib, plt.imshow, or save images to disk for viewing.\n\n"
            "VIEWER CONTROL (LLM-callable via code_executor):\n"
            "You can control the CT viewer through API calls. Use `code_executor` with this pattern:\n"
            "```python\n"
            "import requests\n"
            "res = requests.post('http://localhost:8080/api/viewer/control', json={\n"
            '    "action": "set_preset", "preset": "lung"\n'
            "})\n"
            "print(res.json())\n"
            "```\n"
            "Available viewer actions:\n"
            "- `set_preset`: Apply window preset. Presets: soft (W:400 L:40), bone (W:2000 L:400), lung (W:1500 L:-600), brain (W:80 L:40)\n"
            "- `set_window`: Set custom window/level. Params: window (int), level (int)\n"
            "- `navigate_slice`: Navigate to specific slice. Params: axis (axial|sagittal|coronal), slice_index (int)\n"
            "- `set_threshold`: Set HU threshold overlay. Params: threshold (int, HU value)\n"
            "- `toggle_overlay`: Toggle CTV/OAR overlay. Params: overlay (ctv|oar)\n"
            "- `get_state`: Get current viewer state (no params)\n\n"
            f"CURRENT UI STATE:\n{ui_state_summary}\n\n"
            "IMPORTANT RULES:\n"
            "1. When the user asks to segment, plan, evaluate, etc., call the tools directly.\n"
            "2. Use tool_call blocks to invoke tools.\n"
            "3. After calling tools, summarize the results for the user.\n"
            "4. If the user asks you to inspect a file, write code, or compute something — use `code_executor`.\n"
            "5. If the user asks about files or directories — use `filesystem_browser`.\n"
            "6. If you need CT data and it's NOT in the UI state above, tell the user to use the Input panel.\n"
            "7. For self-evolution (进化/总结经验), respond with a summary of learned experiences.\n"
            "8. For writing new tools (写工具/create tool), describe the tool specification.\n"
            "9. Be clinical, precise, and actionable.\n"
            "10. Check past experiences and matched SOPs before planning.\n"
            "11. When the user asks to adjust the viewer (e.g., 'switch to lung window', 'go to slice 50'),\n"
            "    use `code_executor` to call the viewer control API as described above.\n\n"
            f"{enhanced_context}\n"
            f"{self.memory.context_summary}\n\n"
            "Tool call format:\n"
            "```tool_call\n"
            '{"tool": "tool_name", "params": {"param1": "value1"}}\n'
            "```\n\n"
            "CRITICAL: After you have received all tool results, you MUST provide a final text response to the user.\n"
            "Do NOT output another tool_call block after you have the results. Instead, summarize the results in plain text.\n"
            "The conversation ends when you output plain text without any tool_call blocks.\n"
            "Example flow:\n"
            "1. User asks a question\n"
            "2. You call a tool with ```tool_call\n"
            "3. You see the tool result\n"
            "4. You respond with plain text summarizing the result (NO tool_call blocks)\n"
            "IMPORTANT: Once you have the tool results, DO NOT call more tools. Just summarize for the user.\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
        ]
        msg_history = self.memory.conversation[-6:]
        for msg in msg_history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        max_iterations = 8
        iteration = 0
        final_response = ""
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        total_latency_ms = 0.0
        llm_calls = 0

        while iteration < max_iterations:
            iteration += 1

            # Thinking step
            step_id_ref[0] += 1
            thinking_step = {
                "id": step_id_ref[0],
                "type": "thinking",
                "title": f"LLM Call {iteration}",
                "content": "Waiting for AI response...",
                "status": "pending",
            }
            steps.append(thinking_step)
            events.append(yield_event("step", thinking_step))

            call_start = _time.time()
            full_content = ""
            tool_calls_from_stream = []
            llm_error = None

            try:
                # Use streaming LLM call
                for chunk in self.brain_router.chat_messages_stream(messages=messages):
                    if isinstance(chunk, str):
                        # Text chunk from LLM
                        full_content += chunk
                        # Yield text chunk for real-time display
                        events.append(yield_event("text_chunk", {"text": chunk}))
                    elif isinstance(chunk, dict):
                        if chunk.get("type") == "final":
                            # Final metadata
                            call_latency = (_time.time() - call_start) * 1000
                            total_latency_ms += call_latency
                            llm_calls += 1

                            if chunk.get("usage"):
                                total_usage["prompt_tokens"] += chunk["usage"].get("prompt_tokens", 0)
                                total_usage["completion_tokens"] += chunk["usage"].get("completion_tokens", 0)
                                total_usage["total_tokens"] += chunk["usage"].get("total_tokens", 0)

                            # Check for tool calls in streaming response
                            if chunk.get("tool_calls"):
                                for tc in chunk["tool_calls"]:
                                    try:
                                        args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                                        tool_calls_from_stream.append({
                                            "id": tc.get("id", f"tool_{len(tool_calls_from_stream)}"),
                                            "tool": tc["function"]["name"],
                                            "params": args,
                                        })
                                    except json.JSONDecodeError:
                                        pass
                            break
                        elif chunk.get("type") == "error":
                            llm_error = chunk.get("content", "Unknown error")
                            break
            except Exception as e:
                logger.error(f"LLM stream call failed: {e}")
                llm_error = str(e)

            if llm_error:
                thinking_step["status"] = "error"
                thinking_step["content"] = f"LLM error: {llm_error}"
                events.append(yield_event("step", thinking_step))
                return events, f"LLM error: {llm_error}", {"usage": total_usage, "latency_ms": 0, "llm_calls": llm_calls}

            content = full_content

            # Check for tool calls
            tool_calls = tool_calls_from_stream if tool_calls_from_stream else []
            if not tool_calls:
                tool_calls = self._parse_tool_calls(content)

            if not tool_calls:
                final_response = content
                thinking_step["status"] = "done"
                thinking_step["content"] = "Response generated"
                events.append(yield_event("step", thinking_step))
                break

            # Update thinking step
            thinking_step["status"] = "done"
            thinking_step["content"] = f"Found {len(tool_calls)} tool call(s)"
            events.append(yield_event("step", thinking_step))

            # If we've already executed tools and LLM outputs more tool calls,
            # check if there's meaningful text before the tool calls
            if any(s["type"] == "tool" for s in steps):
                import re as _re
                text_before = _re.sub(r'```tool_call\s*\n.*?\n```', '', content, flags=_re.DOTALL).strip()
                text_before = _re.sub(r'<minimax:tool_call>.*?</minimax:tool_call>', '', text_before, flags=_re.DOTALL).strip()
                if len(text_before) > 10:
                    final_response = text_before
                    break

            # Filter out tool calls with empty required params, normalize param names
            valid_tool_calls = []
            for tc in tool_calls:
                tn = tc.get("tool", "")
                p = tc.get("params", {})
                if tn == "filesystem_browser":
                    if "dirPath" in p and "path" not in p:
                        p["path"] = p.pop("dirPath")
                    if "directory" in p and "path" not in p:
                        p["path"] = p.pop("directory")
                    if "action" not in p:
                        p["action"] = "list"
                    if not p.get("path", "").strip():
                        continue
                if tn == "code_executor":
                    if "script" in p and "code" not in p:
                        p["code"] = p.pop("script")
                    if "python" in p and "code" not in p:
                        p["code"] = p.pop("python")
                    if not p.get("code", "").strip():
                        continue
                valid_tool_calls.append(tc)

            if not valid_tool_calls:
                final_response = content
                break

            tool_calls = valid_tool_calls

            for tc in tool_calls:
                tool_name = tc.get("tool", "")
                params = tc.get("params", {})
                tool_id = tc.get("id", f"tool_{step_id_ref[0]}")

                # Tool call step
                step_id_ref[0] += 1
                tool_step = {
                    "id": step_id_ref[0],
                    "type": "tool",
                    "title": f"Calling {tool_name}",
                    "content": json.dumps(params, default=str)[:200],
                    "status": "pending",
                    "tool": tool_name,
                    "params": params,
                }
                steps.append(tool_step)
                events.append(yield_event("step", tool_step))

                if tool_name in ("self_evolve", "evolve", "进化", "总结经验"):
                    result_text = self._handle_self_evolution()
                elif tool_name in ("code_writer", "write_tool", "create_tool", "写工具", "新工具"):
                    result_text = self._handle_code_writing(params)
                elif tool_name in self.registry.tool_names:
                    try:
                        result = self._execute_tool_with_memory(tool_name, params)
                        if result.success:
                            result_text = result.message
                            if tool_name == "code_executor" and hasattr(result, "data") and result.data:
                                stdout = result.data.get("stdout", "").strip()
                                if stdout:
                                    result_text = stdout[:1000]
                            if result.success and hasattr(result, "metadata") and result.metadata:
                                metrics_summary = {}
                                for k, v in result.metadata.items():
                                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                                        metrics_summary[k] = v
                                if metrics_summary:
                                    result_text += f" | Metrics: {metrics_summary}"
                        else:
                            error_msg = result.error or ""
                            if hasattr(result, "data") and result.data and "stderr" in result.data:
                                stderr = result.data["stderr"][:300]
                                error_msg = f"{error_msg}: {stderr}" if error_msg else stderr
                            result_text = f"Error: {error_msg}" if error_msg else "Error: execution failed"
                    except Exception as e:
                        result_text = f"Exception: {str(e)}"
                        logger.error(f"Tool {tool_name} failed: {e}")
                else:
                    result_text = f"Unknown tool: {tool_name}. Available: {self.registry.tool_names}"

                step_status = "done" if "Error" not in result_text and "Exception" not in result_text else "error"
                tool_step["status"] = step_status
                tool_step["result"] = result_text[:200]
                events.append(yield_event("step", tool_step))

                # Append tool call and result to messages
                messages.append({
                    "role": "assistant",
                    "content": f"Called {tool_name}."
                })
                messages.append({
                    "role": "user",
                    "content": f"Tool result: {result_text}"
                })

        if final_response:
            final_response = self._clean_response_text(final_response)
            step_id_ref[0] += 1
            response_step = {
                "id": step_id_ref[0],
                "type": "assistant",
                "title": "AI Response",
                "content": final_response,
                "status": "done",
            }
            steps.append(response_step)
            events.append(yield_event("step", response_step))
        else:
            final_response = "Tools executed. Check the execution trace above for results."

        self.memory.add_message("assistant", final_response)
        return events, final_response, {
            "usage": total_usage,
            "latency_ms": round(total_latency_ms, 1),
            "llm_calls": llm_calls,
        }

    def _parse_tool_calls(self, content: str) -> List[Dict]:
        """Parse tool calls from LLM response. Supports multiple formats."""
        tool_calls = []

        # Format 1: ```tool_call blocks
        pattern = r'```tool_call\s*\n(.*?)\n```'
        matches = re.findall(pattern, content, re.DOTALL)
        for match in matches:
            try:
                # Try direct parse first
                tc = json.loads(match.strip())
                if isinstance(tc, list):
                    tool_calls.extend(tc)
                elif isinstance(tc, dict) and "tool" in tc:
                    tool_calls.append(tc)
            except json.JSONDecodeError:
                # If direct parse fails, try to extract the JSON object
                # by finding the outermost braces
                cleaned = match.strip()
                start = cleaned.find('{')
                end = cleaned.rfind('}')
                if start != -1 and end != -1 and end > start:
                    json_str = cleaned[start:end+1]
                    # Fix: escape literal newlines in string values
                    # This handles the case where the LLM outputs JSON with actual newlines
                    fixed = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                    try:
                        tc = json.loads(fixed)
                        if isinstance(tc, list):
                            tool_calls.extend(tc)
                        elif isinstance(tc, dict) and "tool" in tc:
                            tool_calls.append(tc)
                    except json.JSONDecodeError:
                        pass

        # Format 2: MiniMax XML-style variations
        if not tool_calls:
            minimax_pattern = r'<minimax:tool_call>(.*?)</minimax:tool_call>'
            minimax_matches = re.findall(minimax_pattern, content, re.DOTALL)
            for match in minimax_matches:
                try:
                    invoke_match = re.search(r'<invoke\s+name="([^"]+)">(.*?)</invoke>', match, re.DOTALL)
                    if invoke_match:
                        tool_name = invoke_match.group(1)
                        inner = invoke_match.group(2)
                        params = {}
                        for pmatch in re.finditer(r'<parameter\s+name="([^"]+)">(.*?)</parameter>', inner, re.DOTALL):
                            params[pmatch.group(1)] = pmatch.group(2)
                        tool_calls.append({"tool": tool_name, "params": params})
                        continue
                    # Format 2B: <invoke name="tool_name", "params": {...}>
                    invoke_json = re.search(r'<invoke\s+name="([^"]+)",\s*"params":\s*\{', match, re.DOTALL)
                    if invoke_json:
                        tool_name = invoke_json.group(1)
                        # Find the matching closing brace by counting
                        brace_start = invoke_json.end() - 1  # position of opening {
                        depth = 0
                        brace_end = -1
                        for i in range(brace_start, len(match)):
                            if match[i] == '{':
                                depth += 1
                            elif match[i] == '}':
                                depth -= 1
                                if depth == 0:
                                    brace_end = i
                                    break
                        if brace_end != -1:
                            params_str = match[brace_start:brace_end+1]
                            tool_calls.append({"tool": tool_name, "params": json.loads(params_str)})
                            continue
                except (json.JSONDecodeError, AttributeError):
                    pass

        # Format 3: Bare JSON objects with "tool" key
        if not tool_calls:
            pattern2 = r'\{[^{}]*"tool"[^{}]*\}'
            matches2 = re.findall(pattern2, content)
            for match in matches2:
                try:
                    tc = json.loads(match)
                    if "tool" in tc:
                        tool_calls.append(tc)
                except json.JSONDecodeError:
                    pass

        return tool_calls

    def _handle_self_evolution(self) -> str:
        """Handle self-evolution request."""
        if not self.evolution_engine:
            return "Self-evolution system not available."
        results = self.evolution_engine.evolve()
        lines = ["Self-evolution cycle complete:"]
        if results["new_skills"]:
            lines.append(f"  New skills: {len(results['new_skills'])}")
            for s in results["new_skills"]:
                lines.append(f"    - {s['name']}: {s['description']}")
        if results["lessons"]:
            lines.append(f"  Lessons learned: {len(results['lessons'])}")
        if results["parameter_updates"]:
            lines.append(f"  Parameter optimizations: {len(results['parameter_updates'])}")
        if results["failure_insights"]:
            lines.append(f"  Failure insights: {len(results['failure_insights'])}")
        summary = self.evolution_engine.get_evolution_summary()
        lines.append(f"\nTotal experiences: {summary['experience_summary']['total_experiences']}")
        lines.append(f"Success rate: {summary['experience_summary']['success_rate']:.1%}")
        return "\n".join(lines)

    def _handle_code_writing(self, params: Dict) -> str:
        """Handle tool code writing request."""
        if not self.tool_code_writer:
            return "Tool code writer not available."
        if not self.brain_available:
            return "LLM brain required for code writing."

        tool_spec = params.get("tool_spec", params)
        if "name" not in tool_spec:
            spec_prompt = (
                "Please provide a tool specification with these fields:\n"
                "- name: tool name (snake_case)\n"
                "- description: what the tool does\n"
                "- category: subdirectory under tool_factory/\n"
                "- input_schema: input parameters\n"
                "- output_schema: output format\n"
                "- execute_logic: Python code for the _execute method"
            )
            return spec_prompt

        result = self.tool_code_writer.generate_tool_from_llm_spec(tool_spec)
        if result["success"]:
            tool_info = result["tool"]
            reg_result = self.tool_code_writer.register_generated_tool(tool_info["name"])
            if reg_result["success"]:
                return (
                    f"Tool '{tool_info['name']}' generated and registered successfully!\n"
                    f"  File: {tool_info['file_path']}\n"
                    f"  Class: {tool_info['class_name']}\n"
                    f"  Description: {tool_info['description']}"
                )
            else:
                return f"Tool generated but registration failed: {reg_result['error']}"
        else:
            return f"Tool generation failed: {result['error']}"

    def chat(self, message: str) -> str:
        self.memory.add_message("user", message)

        if self.enhanced:
            self.enhanced.pre_task_hook(message)

        if self.brain_available:
            response, _ = self._run_llm_function_calling(message, [], [0])
        else:
            response = self._rule_based_chat(message)

        self._record_experience(message, response)

        if self.enhanced:
            tool_chain = []
            tool_results = []
            for step in self.memory.tool_results[-10:]:
                tool_chain.append(step.get("tool", ""))
                tool_results.append((step.get("tool", ""), step.get("success", False), step.get("message", "")))
            self.enhanced.post_task_hook(
                user_input=message, tool_chain=tool_chain, tool_results=tool_results,
                outcome=response[:500], success="error" not in response.lower() and "fail" not in response.lower(),
            )

        return response

    def chat_with_trace(self, message: str) -> Dict[str, Any]:
        self.memory.add_message("user", message)
        steps = []
        step_id = [0]

        def add_step(step_type, title, content, status="done", **kwargs):
            step_id[0] += 1
            steps.append({
                "id": step_id[0],
                "type": step_type,
                "title": title,
                "content": content,
                "status": status,
                **kwargs
            })

        add_step("user", "User Input", message)

        if self.enhanced:
            pre_ctx = self.enhanced.pre_task_hook(message)
            if pre_ctx.get("matched_sop"):
                sop = pre_ctx["matched_sop"]
                add_step("memory", "Matched SOP", f"{sop['name']} ({sop['success_rate']:.0%} success): {' -> '.join(sop['steps'])}")
            if pre_ctx.get("crystallized_skill"):
                sk = pre_ctx["crystallized_skill"]
                add_step("memory", "Crystallized Skill", f"{sk['name']} ({sk['success_rate']:.0%}): {' -> '.join(sk['tool_chain'])}")
            if pre_ctx.get("reflexion_warnings"):
                add_step("memory", "Experience Recall", pre_ctx["reflexion_warnings"][:300])

        if self.brain_available:
            add_step("thinking", "LLM Brain", "Using AI brain system with function calling...")
            try:
                response, llm_meta = self._run_llm_function_calling(message, steps, step_id)
            except Exception as e:
                logger.error(f"LLM function calling failed: {e}")
                add_step("error", "LLM Error", str(e), status="error")
                response = f"Error: {e}"
                llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
        else:
            add_step("thinking", "Rule Matcher", "Brain unavailable — using rule-based parsing")
            response = self._rule_based_chat_with_steps(message, steps, step_id)
            llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}

        self._record_experience(message, response, steps)

        if self.enhanced:
            tool_chain = [s.get("tool", "") for s in steps if s.get("type") == "tool"]
            tool_results = [(s.get("tool", ""), s.get("status") == "done", s.get("result", "")) for s in steps if s.get("type") == "tool"]
            self.enhanced.post_task_hook(
                user_input=message, tool_chain=tool_chain, tool_results=tool_results,
                outcome=response[:500], success="error" not in response.lower() and "fail" not in response.lower(),
            )
            enhanced_status = self.enhanced.get_agent_status()
            add_step("evolution", "Self-Evolution Status", json.dumps({
                "layered_memory": enhanced_status["layered_memory"],
                "reflexion": enhanced_status["reflexion"],
                "skill_crystallizer": {"total_skills": enhanced_status["skill_crystallizer"]["total_skills"], "verified": enhanced_status["skill_crystallizer"]["verified_skills"]},
            }, ensure_ascii=False))

        return {"response": response, "steps": steps, "llm_meta": llm_meta}

    def chat_with_stream(self, message: str):
        """Streaming version of chat_with_trace. Yields SSE events."""
        self.memory.add_message("user", message)
        steps = []
        step_id = [0]
        response = ""  # Initialize response variable
        llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}

        def add_step(step_type, title, content, status="done", **kwargs):
            step_id[0] += 1
            step = {
                "id": step_id[0],
                "type": step_type,
                "title": title,
                "content": content,
                "status": status,
                **kwargs
            }
            steps.append(step)
            return step

        def yield_event(event_type, data):
            return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"

        # Start
        yield yield_event("start", {"message": message})

        # User step
        add_step("user", "User Input", message)
        yield yield_event("step", steps[-1])

        # Enhanced context
        if self.enhanced:
            pre_ctx = self.enhanced.pre_task_hook(message)
            if pre_ctx.get("matched_sop"):
                sop = pre_ctx["matched_sop"]
                step = add_step("memory", "Matched SOP", f"{sop['name']} ({sop['success_rate']:.0%} success): {' -> '.join(sop['steps'])}")
                yield yield_event("step", step)
            if pre_ctx.get("crystallized_skill"):
                sk = pre_ctx["crystallized_skill"]
                step = add_step("memory", "Crystallized Skill", f"{sk['name']} ({sk['success_rate']:.0%}): {' -> '.join(sk['tool_chain'])}")
                yield yield_event("step", step)
            if pre_ctx.get("reflexion_warnings"):
                step = add_step("memory", "Experience Recall", pre_ctx["reflexion_warnings"][:300])
                yield yield_event("step", step)

        if self.brain_available:
            try:
                events, response, llm_meta = self._run_llm_function_calling_stream(message, steps, step_id, yield_event)
                for ev in events:
                    yield ev
            except Exception as e:
                logger.error(f"LLM function calling failed: {e}")
                add_step("error", "LLM Error", str(e), status="error")
                response = f"Error: {e}"
                llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
                yield yield_event("error", {"message": str(e)})
        else:
            response = self._rule_based_chat_with_steps_stream(message, steps, step_id, yield_event)
            llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}

        self._record_experience(message, response, steps)

        # Final response
        yield yield_event("response", {"response": response, "steps": steps, "llm_meta": llm_meta})
        yield yield_event("done", {
            "context": {
                "summary": self.memory.context_summary or None,
                "compaction_count": self.memory.compaction_count,
                "message_count": len(self.memory.conversation),
                "ui_state": self.memory.get_ui_state(),
            }
        })

    def _rule_based_chat_with_steps_stream(self, message: str, steps: List[Dict], step_id: List[int], yield_event) -> str:
        """Streaming version of rule-based chat that yields steps as they happen."""
        msg_lower = message.lower()

        def yield_step(step):
            steps.append(step)
            yield_event("step", step)

        if "分割" in msg_lower or "segment" in msg_lower:
            target = "CTV"
            if "oar" in msg_lower or "organ" in msg_lower or "器官" in msg_lower:
                target = "OAR"

            step_id[0] += 1
            tool_step = {
                "id": step_id[0], "type": "tool", "title": f"Segmentation: {target}",
                "content": f"Running {target} segmentation...", "status": "pending",
                "tool": f"{target.lower()}_segmentation", "params": {},
            }
            yield_step(tool_step)

            result = self._handle_ctv_segmentation_request(message) if target == "CTV" else self._handle_oar_segmentation_request(message)

            tool_step["status"] = "done"
            tool_step["result"] = result[:200]
            yield_step(tool_step)

            step_id[0] += 1
            result_step = {"id": step_id[0], "type": "result", "title": f"{target} Result", "content": result, "status": "done"}
            yield_step(result_step)

            return result

        elif "计划" in msg_lower or "plan" in msg_lower or "规划" in msg_lower:
            mode = "rl" if "rl" in msg_lower or "强化" in msg_lower else "rule_based"

            step_id[0] += 1
            tool_step = {
                "id": step_id[0], "type": "tool", "title": "Seed Planning",
                "content": f"Generating seed plan ({mode} mode)...", "status": "pending",
                "tool": "seed_planning", "params": {"mode": mode},
            }
            yield_step(tool_step)

            result = self._handle_planning_request(message)

            tool_step["status"] = "done"
            tool_step["result"] = result[:200]
            yield_step(tool_step)

            step_id[0] += 1
            result_step = {"id": step_id[0], "type": "result", "title": "Planning Result", "content": result, "status": "done"}
            yield_step(result_step)

            return result

        elif "评估" in msg_lower or "eval" in msg_lower or "剂量" in msg_lower:
            step_id[0] += 1
            tool_step = {
                "id": step_id[0], "type": "tool", "title": "Dose Evaluation",
                "content": "Evaluating dose distribution...", "status": "pending",
                "tool": "dose_evaluation", "params": {},
            }
            yield_step(tool_step)

            result = self._handle_evaluation_request(message)

            tool_step["status"] = "done"
            tool_step["result"] = result[:200]
            yield_step(tool_step)

            step_id[0] += 1
            result_step = {"id": step_id[0], "type": "result", "title": "Evaluation Result", "content": result, "status": "done"}
            yield_step(result_step)

            return result

        elif "优化" in msg_lower or "optim" in msg_lower or "调整" in msg_lower:
            result = self._handle_optimization_request(message)
            return result

        elif "进化" in msg_lower or "evolve" in msg_lower or "学习" in msg_lower or "总结经验" in msg_lower:
            result = self._handle_self_evolution()
            return result

        elif "写工具" in msg_lower or "create tool" in msg_lower or "新工具" in msg_lower:
            result = self._handle_code_writing({})
            return result

        else:
            result = (
                "I can help with brachytherapy planning. Try:\n"
                "  - '分割CTV' - Segment CTV\n"
                "  - '生成治疗计划' - Generate plan\n"
                "  - '评估剂量' - Evaluate dose\n"
                "  - '优化计划' - Optimize plan\n"
                "  - '总结经验' - Self-evolve\n"
                "  - '写工具' - Create new tool"
            )
            return result

    def _rule_based_chat_with_steps(self, message: str, steps: List[Dict], step_id: List[int]) -> str:
        msg_lower = message.lower()
        if "分割" in msg_lower or "segment" in msg_lower:
            target = "CTV"
            if "oar" in msg_lower or "organ" in msg_lower or "器官" in msg_lower:
                target = "OAR"
            step_id[0] += 1
            steps.append({
                "id": step_id[0], "type": "tool", "title": f"Segmentation: {target}",
                "content": f"Running {target} segmentation...", "status": "done",
                "tool": f"{target.lower()}_segmentation", "params": {},
            })
            result = self._handle_ctv_segmentation_request(message) if target == "CTV" else self._handle_oar_segmentation_request(message)
            step_id[0] += 1
            steps.append({"id": step_id[0], "type": "result", "title": f"{target} Result", "content": result, "status": "done"})
            return result
        elif "计划" in msg_lower or "plan" in msg_lower or "规划" in msg_lower:
            mode = "rl" if "rl" in msg_lower or "强化" in msg_lower else "rule_based"
            step_id[0] += 1
            steps.append({
                "id": step_id[0], "type": "tool", "title": "Seed Planning",
                "content": f"Generating seed plan ({mode} mode)...", "status": "done",
                "tool": "seed_planning", "params": {"mode": mode},
            })
            result = self._handle_planning_request(message)
            step_id[0] += 1
            steps.append({"id": step_id[0], "type": "result", "title": "Planning Result", "content": result, "status": "done"})
            return result
        elif "评估" in msg_lower or "eval" in msg_lower or "剂量" in msg_lower:
            step_id[0] += 1
            steps.append({
                "id": step_id[0], "type": "tool", "title": "Dose Evaluation",
                "content": "Evaluating dose distribution...", "status": "done",
                "tool": "dose_evaluation", "params": {},
            })
            result = self._handle_evaluation_request(message)
            step_id[0] += 1
            steps.append({"id": step_id[0], "type": "result", "title": "Evaluation Result", "content": result, "status": "done"})
            return result
        elif "优化" in msg_lower or "optim" in msg_lower or "调整" in msg_lower:
            result = self._handle_optimization_request(message)
            return result
        elif "进化" in msg_lower or "evolve" in msg_lower or "学习" in msg_lower or "总结经验" in msg_lower:
            result = self._handle_self_evolution()
            return result
        elif "写工具" in msg_lower or "create tool" in msg_lower or "新工具" in msg_lower:
            result = self._handle_code_writing({})
            return result
        else:
            result = (
                "I can help with brachytherapy planning. Try:\n"
                "  - '分割CTV' - Segment CTV\n"
                "  - '生成治疗计划' - Generate plan\n"
                "  - '评估剂量' - Evaluate dose\n"
                "  - '优化计划' - Optimize plan\n"
                "  - '总结经验' - Self-evolve\n"
                "  - '写工具' - Create new tool"
            )
            return result

    def _record_experience(self, message: str, response: str, steps: List[Dict] = None):
        """Record the interaction as an experience for self-evolution."""
        if not self.exp_memory:
            return
        tool_chain = []
        for step in (steps or []):
            if step.get("type") == "tool":
                tool_chain.append({
                    "tool": step.get("tool", ""),
                    "params": step.get("params", {}),
                })
        success = "error" not in response.lower() and "fail" not in response.lower()
        self.exp_memory.record(
            user_intent=message,
            context={"phase": self.memory.current_phase.value},
            tool_chain=tool_chain,
            outcome=response[:500],
            success=success,
            metrics=self.memory.planning_results.get("metrics", {}),
        )

    def _rule_based_chat(self, message: str) -> str:
        msg_lower = message.lower()
        if "分割" in msg_lower or "segment" in msg_lower:
            if "ctv" in msg_lower or "target" in msg_lower or "肿瘤" in msg_lower:
                response = self._handle_ctv_segmentation_request(message)
            elif "oar" in msg_lower or "organ" in msg_lower or "器官" in msg_lower:
                response = self._handle_oar_segmentation_request(message)
            else:
                response = self._handle_ctv_segmentation_request(message)
        elif "计划" in msg_lower or "plan" in msg_lower or "规划" in msg_lower:
            response = self._handle_planning_request(message)
        elif "评估" in msg_lower or "eval" in msg_lower or "剂量" in msg_lower:
            response = self._handle_evaluation_request(message)
        elif "优化" in msg_lower or "optim" in msg_lower or "调整" in msg_lower:
            response = self._handle_optimization_request(message)
        elif "进化" in msg_lower or "evolve" in msg_lower or "学习" in msg_lower or "总结经验" in msg_lower:
            response = self._handle_self_evolution()
        elif "写工具" in msg_lower or "create tool" in msg_lower or "新工具" in msg_lower:
            response = self._handle_code_writing({})
        elif "工具" in msg_lower or "tool" in msg_lower or "帮助" in msg_lower or "help" in msg_lower:
            tools_info = "\n".join(
                f"  - {t['name']}: {t['description'][:80]}..."
                for t in self.registry.list_tools()
            )
            response = f"Available tools:\n{tools_info}"
        else:
            response = (
                "I can help with brachytherapy planning. Try:\n"
                "  - '分割CTV' - Segment CTV\n"
                "  - '生成治疗计划' - Generate plan\n"
                "  - '评估剂量' - Evaluate dose\n"
                "  - '优化计划' - Optimize plan\n"
                "  - '总结经验' - Self-evolve\n"
                "  - '写工具' - Create new tool"
            )
        return response
    
    def _handle_ctv_segmentation_request(self, message: str) -> str:
        ct_image = self.memory.retrieve("ct_image")
        ctv_path = self.memory.retrieve("ctv_path")
        if ct_image is None:
            return "请先提供CT影像路径。使用 run_preoperative_plan(ct_path=...) 加载CT。"
        result = self.registry.execute("ctv_segmentation", image=ct_image, label_path=ctv_path)
        self.memory.log_tool_call("ctv_segmentation", {}, result)
        if result.success:
            self.memory.store("ctv_array", result.metadata["ctv_array"])
            return result.message
        return f"CTV分割失败: {result.error}"
    
    def _handle_oar_segmentation_request(self, message: str) -> str:
        ct_image = self.memory.retrieve("ct_image")
        oar_path = self.memory.retrieve("oar_path")
        if ct_image is None:
            return "请先提供CT影像路径。"
        result = self.registry.execute("oar_segmentation", image=ct_image, label_path=oar_path)
        self.memory.log_tool_call("oar_segmentation", {}, result)
        if result.success:
            self.memory.store("oar_array", result.metadata.get("oar_array"))
            return result.message
        return f"OAR分割失败: {result.error}"
    
    def _handle_planning_request(self, message: str) -> str:
        trajectories = self.memory.retrieve("trajectories")
        radiation_volume = self.memory.retrieve("radiation_volume")
        ct_image = self.memory.retrieve("ct_image")
        if trajectories is None or radiation_volume is None or ct_image is None:
            return "请先加载CT影像并生成分割结果，然后再规划。"
        mode = "rl" if "rl" in message.lower() or "强化" in message else "rule_based"
        seed_info = self.config.get("seed_info", {"radius": 0.4, "length": 4.5, "seed_avr_dose": 50})
        dl_params = self.config.get("dl_params", {})
        result = self.registry.execute(
            "seed_planning",
            trajectories=trajectories,
            radiation_volume=radiation_volume,
            dose_image=ct_image,
            mode=mode,
            dl_params=dl_params,
            seed_info=seed_info,
        )
        self.memory.log_tool_call("seed_planning", {"mode": mode}, result)
        if result.success:
            self.memory.store("optimal_plan", result.metadata["optimal_plan"])
            self.memory.store("dose_distribution", result.metadata.get("dose_distribution"))
            self.memory.store("total_seeds", result.metadata["total_seeds"])
            return result.message
        return f"种子规划失败: {result.error}"
    
    def _handle_evaluation_request(self, message: str) -> str:
        dose = self.memory.retrieve("dose_distribution")
        ctv = self.memory.retrieve("ctv_array")
        oar = self.memory.retrieve("oar_array")
        if dose is None or ctv is None:
            return "请先完成治疗计划生成，然后再评估。"
        result = self.registry.execute(
            "dose_evaluation", dose_array=dose, ctv_mask=ctv, oar_mask=oar,
        )
        self.memory.log_tool_call("dose_evaluation", {}, result)
        if result.success:
            return result.message
        return f"剂量评估失败: {result.error}"
    
    def _handle_optimization_request(self, message: str) -> str:
        dose = self.memory.retrieve("dose_distribution")
        ctv = self.memory.retrieve("ctv_array")
        oar = self.memory.retrieve("oar_array")
        if dose is None:
            return "没有可优化的计划。请先生成治疗计划。"
        eval_result = self.registry.execute(
            "dose_evaluation", dose_array=dose, ctv_mask=ctv, oar_mask=oar,
        )
        if not eval_result.success:
            return f"评估失败: {eval_result.error}"
        metrics = eval_result.metadata
        suggestions = []
        if metrics.get("v100", 0) < 0.90:
            suggestions.append("V100 < 90%，建议增加种子数量或调整种子位置以提高靶区覆盖率。")
        if metrics.get("v200", 0) > 0.35:
            suggestions.append("V200 > 35%，存在过度照射区域，建议减少种子数量或调整位置。")
        if metrics.get("oar_violations"):
            violations = metrics["oar_violations"]
            suggestions.append(f"检测到 {len(violations)} 个OAR剂量超标，需要重新优化计划以保护危及器官。")
        plan_score = metrics.get("plan_score", 0)
        if plan_score >= 80 or (plan_score <= 1 and plan_score >= 0.8):
            suggestions.append("计划质量良好，可以考虑执行。")
        if not suggestions:
            suggestions.append("计划评估完成，未发现明显问题。")
        return f"优化建议:\n" + "\n".join(f"  - {s}" for s in suggestions)
    
    def run_preoperative_plan(
        self,
        ct_path: str,
        ctv_path: Optional[str] = None,
        oar_path: Optional[str] = None,
        mode: str = "rule_based",
        seed_info: Optional[Dict] = None,
        radiation_array_params: Optional[Dict] = None,
        reference_direc: Optional[List] = None,
        in_lowest_energy: Optional[int] = None,
        out_highest_energy: Optional[int] = None,
        DVH_rate: Optional[float] = None,
        max_iter: Optional[int] = None,
        rf_params: Optional[Dict] = None,
        output_dir: str = "./output",
    ) -> Dict:
        self.memory.current_phase = PlanningPhase.PRE_OPERATIVE
        self.memory.add_message("system", f"Starting pre-operative planning for {ct_path}")
        
        default_seed_info = {"radius": 0.4, "length": 3.7, "seed_avr_dose": 50}
        seed_info = seed_info or self.config.get("seed_info") or default_seed_info
        radiation_array_params = radiation_array_params or self.config.get("radiation_array_params", {})
        reference_direc = reference_direc or self.config.get("reference_direc", [0, 1, 0])
        in_lowest_energy = in_lowest_energy if in_lowest_energy is not None else self.config.get("in_lowest_energy", 1)
        out_highest_energy = out_highest_energy if out_highest_energy is not None else self.config.get("out_highest_energy", 1)
        DVH_rate = DVH_rate if DVH_rate is not None else self.config.get("DVH_rate", 0.9)
        max_iter = max_iter if max_iter is not None else self.config.get("max_iter", 4)
        
        target_value = radiation_array_params.get("target_value", 1)
        obstacle_value = radiation_array_params.get("obstacle_value", 2)
        background_value = radiation_array_params.get("background_value", 0)
        backlit_angle = radiation_array_params.get("backlit_angle", 0.5)
        max_candi_traj = radiation_array_params.get("maximum_candidate_trajectories", 200)
        
        try:
            logger.info("Step 1: Loading CT image")
            ct_image = sitk.ReadImage(ct_path)
            self.memory.store("ct_image", ct_image)
            self.memory.store("ct_path", ct_path)
            
            logger.info("Step 2: CTV Segmentation")
            ctv_result = self.registry.execute("ctv_segmentation", image=ct_image, label_path=ctv_path)
            self.memory.log_tool_call("ctv_segmentation", {"image_path": ct_path, "label_path": ctv_path}, ctv_result)
            if not ctv_result.success:
                raise RuntimeError(f"CTV segmentation failed: {ctv_result.error}")
            
            ctv_array = ctv_result.metadata["ctv_array"]
            self.memory.store("ctv_array", ctv_array)
            logger.info(f"  CTV voxels: {ctv_result.metadata['ctv_voxel_count']}")
            
            logger.info("Step 3: OAR Segmentation")
            oar_result = self.registry.execute("oar_segmentation", image=ct_image, label_path=oar_path)
            self.memory.log_tool_call("oar_segmentation", {"image_path": ct_path, "label_path": oar_path}, oar_result)
            
            oar_array = oar_result.metadata.get("oar_array")
            dose_constraints = {}
            if oar_array is not None:
                self.memory.store("oar_array", oar_array)
                dose_constraints = self.config.get("oar_constraints", {})
                logger.info(f"  OAR labels: {list(oar_result.metadata.get('organ_counts', {}).keys())}")
            
            logger.info("Step 4: Building radiation volume")
            radiation_volume = np.zeros_like(ctv_array, dtype=np.float64)
            radiation_volume[ctv_array > 0] = target_value
            if oar_array is not None:
                oar_labels = np.unique(oar_array[oar_array > 0])
                for label in oar_labels:
                    radiation_volume[oar_array == label] = obstacle_value
            self.memory.store("radiation_volume", radiation_volume)
            
            logger.info("Step 5: Trajectory Planning")
            traj_result = self.registry.execute(
                "trajectory_planning",
                dose_image=ct_image, radiation_volume=radiation_volume,
                target_value=target_value, background_value=background_value, obstacle_value=obstacle_value,
            )
            self.memory.log_tool_call("trajectory_planning", {"num_candidates": "computed"}, traj_result)
            if not traj_result.success:
                raise RuntimeError(f"Trajectory planning failed: {traj_result.error}")
            
            trajectories = traj_result.metadata["trajectories"]
            self.memory.store("trajectories", trajectories)
            logger.info(f"  Generated {len(trajectories)} candidate trajectories")
            
            logger.info(f"Step 6: Seed Planning (mode={mode})")
            plan_kwargs = {
                "trajectories": trajectories, "radiation_volume": radiation_volume,
                "dose_image": ct_image, "mode": mode,
                "seed_info": seed_info, "target_value": target_value, "background_value": background_value, "obstacle_value": obstacle_value,
            }
            if mode == "rl" and rf_params:
                plan_kwargs["rf_params"] = rf_params
            
            seed_result = self.registry.execute("seed_planning", **plan_kwargs)
            self.memory.log_tool_call("seed_planning", {"mode": mode, "num_trajectories": len(trajectories)}, seed_result)
            if not seed_result.success:
                raise RuntimeError(f"Seed planning failed: {seed_result.error}")
            
            optimal_plan = seed_result.metadata["optimal_plan"]
            dose_distribution = seed_result.metadata.get("dose_distribution", np.zeros_like(radiation_volume))
            total_seeds = seed_result.metadata["total_seeds"]
            
            self.memory.store("optimal_plan", optimal_plan)
            self.memory.store("dose_distribution", dose_distribution)
            self.memory.store("total_seeds", total_seeds)
            logger.info(f"  Planned {total_seeds} seeds")
            
            logger.info("Step 7: Dose Evaluation")
            eval_result = self.registry.execute(
                "dose_evaluation", dose_array=dose_distribution, ctv_mask=ctv_array,
                oar_mask=oar_array, prescribed_dose=1.0, target_value=1,
                oar_constraints=dose_constraints,
            )
            self.memory.log_tool_call("dose_evaluation", {"prescribed_dose": 1.0}, eval_result)
            
            eval_metrics = eval_result.metadata
            v100_val = eval_metrics.get("v100", 0)
            v100_display = f"{v100_val:.1f}%" if v100_val <= 1 else f"{v100_val:.1f}%"
            logger.info(f"  V100={v100_display}, D90={eval_metrics.get('d90', 0):.2f}Gy, Score={eval_metrics.get('plan_score', 0):.1f}")
            
            os.makedirs(output_dir, exist_ok=True)
            self.memory.export_state(os.path.join(output_dir, "agent_state.json"))
            
            self.memory.current_phase = PlanningPhase.COMPLETED
            
            return {
                "success": True, "phase": "pre_operative",
                "total_seeds": total_seeds,
                "num_trajectories": len(optimal_plan) if optimal_plan else 0,
                "metrics": eval_metrics, "optimal_plan": optimal_plan,
                "dose_distribution": dose_distribution, "output_dir": output_dir,
            }
        except Exception as e:
            self.memory.current_phase = PlanningPhase.FAILED
            self.memory.add_message("system", f"Planning failed: {str(e)}")
            logger.error(f"Pre-operative planning failed: {str(e)}")
            return {"success": False, "phase": "pre_operative", "error": str(e)}
    
    def run_intraoperative_replan(
        self,
        intra_op_ct_path: str,
        original_plan: Any,
        deviation_threshold_mm: float = 2.0,
        output_dir: str = "./output/replan",
    ) -> Dict:
        self.memory.current_phase = PlanningPhase.INTRA_OPERATIVE
        self.memory.deviation_threshold_mm = deviation_threshold_mm
        
        try:
            logger.info(f"Loading intra-op CT from {intra_op_ct_path}")
            intra_op_image = sitk.ReadImage(intra_op_ct_path)
            
            logger.info("Detecting implanted seeds")
            planned_seeds = self._extract_planned_seeds(original_plan)
            
            seed_seg_result = self.registry.execute(
                "seed_segmentation", image=intra_op_image, planned_seeds=planned_seeds,
            )
            self.memory.log_tool_call("seed_segmentation", {"image_path": intra_op_ct_path}, seed_seg_result)
            
            if not seed_seg_result.success:
                raise RuntimeError(f"Seed detection failed: {seed_seg_result.error}")
            
            deviation_stats = seed_seg_result.metadata.get("deviation_stats", {})
            max_deviation = deviation_stats.get("max_deviation_mm", 0)
            mean_deviation = deviation_stats.get("mean_deviation_mm", 0)
            logger.info(f"  Max deviation: {max_deviation:.2f}mm, Mean: {mean_deviation:.2f}mm")
            
            needs_replan = max_deviation > deviation_threshold_mm
            
            if needs_replan:
                logger.info(f"Deviation {max_deviation:.2f}mm > threshold. Triggering replanning...")
                self.memory.current_phase = PlanningPhase.REPLANNING
                replan_result = self._trigger_replanning(
                    intra_op_image, original_plan, seed_seg_result.data, output_dir,
                )
                self.memory.current_phase = PlanningPhase.COMPLETED
                return {
                    "success": True, "phase": "replanning",
                    "deviation_detected": True,
                    "max_deviation_mm": max_deviation, "mean_deviation_mm": mean_deviation,
                    "replan_result": replan_result,
                }
            else:
                logger.info(f"Deviation {max_deviation:.2f}mm within threshold.")
                self.memory.current_phase = PlanningPhase.COMPLETED
                return {
                    "success": True, "phase": "intra_operative",
                    "deviation_detected": False,
                    "max_deviation_mm": max_deviation, "mean_deviation_mm": mean_deviation,
                    "message": "Seed positions within acceptable range.",
                }
        except Exception as e:
            self.memory.current_phase = PlanningPhase.FAILED
            logger.error(f"Intra-operative replanning failed: {str(e)}")
            return {"success": False, "phase": "intra_operative", "error": str(e)}
    
    def _extract_planned_seeds(self, plan) -> List:
        planned_seeds = []
        if isinstance(plan, (list, tuple)):
            for entry in plan:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    seeds = entry[1]
                    if isinstance(seeds, list):
                        for seed in seeds:
                            if isinstance(seed, (list, tuple)) and len(seed) >= 1:
                                planned_seeds.append([seed[0], seed[1] if len(seed) > 1 else [0, 0, 1]])
        return planned_seeds
    
    def _trigger_replanning(self, intra_op_image, original_plan, detected_seeds, output_dir) -> Dict:
        logger.info("Starting replanning process")
        ct_image = self.memory.retrieve("ct_image")
        radiation_volume = self.memory.retrieve("radiation_volume")
        ctv_array = self.memory.retrieve("ctv_array")
        oar_array = self.memory.retrieve("oar_array")
        if ct_image is None:
            ct_image = intra_op_image
        if radiation_volume is None:
            if ctv_array is not None:
                radiation_volume = ctv_array.astype(np.float64)
                radiation_volume[radiation_volume > 0] = 1.0
                logger.warning("Using CTV array as radiation volume for replanning")
            else:
                radiation_volume = sitk.GetArrayFromImage(intra_op_image)
                radiation_volume = (radiation_volume > -1000).astype(np.float64)
                logger.warning("No CTV available; using CT threshold as radiation volume (suboptimal)")
        delivered_dose = self.memory.retrieve("dose_distribution")
        if delivered_dose is None:
            delivered_dose = np.zeros(radiation_volume.shape)
        adjusted_volume = radiation_volume.copy()
        if ctv_array is not None:
            already_covered = delivered_dose * ctv_array > 1.0
            adjusted_volume[already_covered] = 0.5
        traj_result = self.registry.execute(
            "trajectory_planning", dose_image=ct_image, radiation_volume=adjusted_volume,
            target_value=1, background_value=0, obstacle_value=3,
        )
        if traj_result.success and len(traj_result.data) > 0:
            seed_info = self.config.get("seed_info", {"radius": 0.4, "length": 4.5, "seed_avr_dose": 50})
            dl_params = self.config.get("dl_params", {})
            plan_result = self.registry.execute(
                "seed_planning", trajectories=traj_result.data, radiation_volume=adjusted_volume,
                dose_image=ct_image, mode="rule_based", dl_params=dl_params, seed_info=seed_info,
            )
            if plan_result.success:
                os.makedirs(output_dir, exist_ok=True)
                self.memory.export_state(os.path.join(output_dir, "replan_state.json"))
                return {
                    "success": True, "new_plan": plan_result.data,
                    "total_seeds": plan_result.metadata.get("total_seeds", 0),
                    "dose_distribution": plan_result.metadata.get("dose_distribution"),
                }
        return {"success": False, "error": "Replanning could not generate a valid plan"}
    
    def get_status(self) -> Dict:
        status = {
            "session_id": self.memory.session_id,
            "phase": self.memory.current_phase.value,
            "tools_available": self.registry.tool_names,
            "tool_calls_made": len(self.memory.tool_results),
            "messages": len(self.memory.conversation),
            "stored_keys": list(self.memory.planning_results.keys()),
        }
        try:
            status["skills_available"] = len(self.skill_registry.list_skills())
        except AttributeError:
            status["skills_available"] = 0
        try:
            status["learned_preferences"] = len(self.preference_store.get_high_confidence())
        except AttributeError:
            status["learned_preferences"] = 0
        if getattr(self, "exp_memory", None):
            status["experiences"] = self.exp_memory.get_summary()
        if self.evolution_engine:
            status["evolution"] = self.evolution_engine.get_evolution_summary()
        if self.enhanced:
            status["enhanced"] = self.enhanced.get_agent_status()
        return status

    def get_recommended_skill(self, message: str) -> Optional[Dict]:
        matching_skills = self.skill_registry.find_by_trigger(message)
        if not matching_skills:
            return None
        best = matching_skills[0]
        return {
            "name": best.name, "description": best.description,
            "tool_sequence": best.tool_sequence, "parameters": best.parameters,
            "success_rate": best.success_rate(), "usage_count": best.usage_count,
        }

    def evolve_from_interactions(self) -> Dict:
        learned_skills = self.skill_learner.learn_from_interactions(min_occurrences=3)
        learned_prefs = self.skill_learner.learn_parameter_preferences()
        self.preference_store.update_from_learned(learned_prefs)
        evolved = self.skill_registry.evolve_from_interactions(
            self.interaction_memory, self.skill_learner
        )
        evolution_results = {}
        if self.evolution_engine:
            evolution_results = self.evolution_engine.evolve()
        return {
            "new_skills": [s.to_dict() for s in learned_skills],
            "evolved_skills": [s.to_dict() for s in evolved],
            "updated_preferences": self.preference_store.get_all_preferences(),
            "evolution_results": evolution_results,
        }

    def apply_user_preference(self, tool_name: str, params: Dict) -> Dict:
        return self.preference_store.apply_to_tool_params(tool_name, params)
