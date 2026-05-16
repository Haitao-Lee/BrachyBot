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
import copy
import time
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

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
        self.current_phase: PlanningPhase = PlanningPhase.IDLE
        self.deviation_threshold_mm: float = 2.0
    
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
        self._init_brain_system()
        self._init_self_evolution()
        self._init_enhanced_integration()

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
                provider = os.environ.get("BRACHY_LLM_PROVIDER", "openrouter")
                llm_config = {provider: {"enabled": True, "model": "hy3-preview"}}

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
        from tool_factory.seed__plan import SeedPlanningTool
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
            if seed_positions is not None and "seed_positions" not in params:
                params["seed_positions"] = seed_positions
            if ct_image is not None and "ct_image" not in params:
                params["ct_image"] = ct_image
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

        system_prompt = (
            "You are BrachyBot, an AI assistant for brachytherapy treatment planning.\n"
            "You have access to the following tools. When the user asks you to do something, "
            "call the appropriate tools with the correct parameters.\n\n"
            "Available tools:\n"
            f"{self.registry.to_tool_descriptions()}\n\n"
            "IMPORTANT RULES:\n"
            "1. When the user asks to segment, plan, evaluate, etc., call the tools directly.\n"
            "2. Use tool_call blocks to invoke tools.\n"
            "3. After calling tools, summarize the results for the user.\n"
            "4. If you need CT data but none is loaded, tell the user to provide a CT path.\n"
            "5. For self-evolution (进化/总结经验), respond with a summary of learned experiences.\n"
            "6. For writing new tools (写工具/create tool), describe the tool specification.\n"
            "7. Be clinical, precise, and actionable.\n"
            "8. Check past experiences and matched SOPs before planning.\n\n"
            f"{enhanced_context}\n\n"
            "Tool call format:\n"
            "```tool_call\n"
            '{"tool": "tool_name", "params": {"param1": "value1"}}\n'
            "```\n\n"
            "You can call multiple tools in sequence. After each tool call, you will see the result."
        )

        messages = [
            {"role": "system", "content": system_prompt},
        ]
        msg_history = self.memory.conversation[-6:]
        for msg in msg_history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})

        max_iterations = 10
        iteration = 0
        final_response = ""

        while iteration < max_iterations:
            iteration += 1

            try:
                response = self.brain_router.chat_messages(messages=messages)
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                return f"LLM error: {e}"

            content = response.content or ""
            tool_calls = self._parse_tool_calls(content)

            if not tool_calls:
                final_response = content
                break

            for tc in tool_calls:
                tool_name = tc.get("tool", "")
                params = tc.get("params", {})

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
                        result_text = result.message if result.success else f"Error: {result.error}"
                        if result.success and hasattr(result, "metadata") and result.metadata:
                            metrics_summary = {}
                            for k, v in result.metadata.items():
                                if isinstance(v, (int, float)) and not isinstance(v, bool):
                                    metrics_summary[k] = v
                            if metrics_summary:
                                result_text += f" | Metrics: {metrics_summary}"
                    except Exception as e:
                        result_text = f"Exception: {str(e)}"
                        logger.error(f"Tool {tool_name} failed: {e}")
                else:
                    result_text = f"Unknown tool: {tool_name}. Available: {self.registry.tool_names}"

                step_status = "done" if "Error" not in result_text and "Exception" not in result_text else "error"
                steps[-1]["status"] = step_status
                steps[-1]["result"] = result_text[:200]

                messages.append({
                    "role": "assistant",
                    "content": f"```tool_call\n{json.dumps(tc)}\n```"
                })
                messages.append({
                    "role": "tool",
                    "content": f"Tool {tool_name} result: {result_text}",
                })

        if final_response:
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
        return final_response

    def _parse_tool_calls(self, content: str) -> List[Dict]:
        """Parse tool calls from LLM response."""
        tool_calls = []
        import re
        pattern = r'```tool_call\s*\n(.*?)\n```'
        matches = re.findall(pattern, content, re.DOTALL)
        for match in matches:
            try:
                tc = json.loads(match.strip())
                if isinstance(tc, list):
                    tool_calls.extend(tc)
                elif isinstance(tc, dict) and "tool" in tc:
                    tool_calls.append(tc)
            except json.JSONDecodeError:
                pass
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
            response = self._run_llm_function_calling(message, [], [0])
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
                response = self._run_llm_function_calling(message, steps, step_id)
            except Exception as e:
                logger.error(f"LLM function calling failed: {e}")
                add_step("error", "LLM Error", str(e), status="error")
                response = f"Error: {e}"
        else:
            add_step("thinking", "Rule Matcher", "Brain unavailable — using rule-based parsing")
            response = self._rule_based_chat_with_steps(message, steps, step_id)

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

        return {"response": response, "steps": steps}

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
        if metrics.get("plan_score", 0) >= 80:
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
        dl_params: Optional[Dict] = None,
        rf_params: Optional[Dict] = None,
        seed_info: Optional[Dict] = None,
        output_dir: str = "./output",
    ) -> Dict:
        import SimpleITK as sitk
        
        self.memory.current_phase = PlanningPhase.PRE_OPERATIVE
        self.memory.add_message("system", f"Starting pre-operative planning for {ct_path}")
        
        default_seed_info = {"radius": 0.4, "length": 4.5, "seed_avr_dose": 50}
        seed_info = seed_info or default_seed_info
        dl_params = dl_params or {}
        
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
            radiation_volume[ctv_array > 0] = 1.0
            if oar_array is not None:
                oar_labels = np.unique(oar_array[oar_array > 0])
                for label in oar_labels:
                    radiation_volume[oar_array == label] = 3.0
            self.memory.store("radiation_volume", radiation_volume)
            
            logger.info("Step 5: Trajectory Planning")
            traj_result = self.registry.execute(
                "trajectory_planning",
                dose_image=ct_image, radiation_volume=radiation_volume,
                target_value=1, background_value=0, obstacle_value=3,
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
                "dose_image": ct_image, "mode": mode, "dl_params": dl_params,
                "seed_info": seed_info, "target_value": 1, "background_value": 0, "obstacle_value": 3,
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
            logger.info(f"  V100={eval_metrics.get('v100', 0):.1%}, D90={eval_metrics.get('d90', 0):.2f}Gy, Score={eval_metrics.get('plan_score', 0):.1f}")
            
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
        import SimpleITK as sitk
        
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
            import SimpleITK as sitk
            radiation_volume = sitk.GetArrayFromImage(intra_op_image)
            radiation_volume = (radiation_volume > 0).astype(np.float64)
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
            "skills_available": len(self.skill_registry.list_skills()),
            "learned_preferences": len(self.preference_store.get_high_confidence()),
        }
        if self.exp_memory:
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
        if self.evolution_engine:
            evolution_results = self.evolution_engine.evolve()
        return {
            "new_skills": [s.to_dict() for s in learned_skills],
            "evolved_skills": [s.to_dict() for s in evolved],
            "updated_preferences": self.preference_store.get_all_preferences(),
            "evolution_results": evolution_results if self.evolution_engine else {},
        }

    def apply_user_preference(self, tool_name: str, params: Dict) -> Dict:
        return self.preference_store.apply_to_tool_params(tool_name, params)
