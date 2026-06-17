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
import re
import time
from typing import Any, Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import SimpleITK as sitk

logger = logging.getLogger(__name__)

from config.prompts import SYSTEM_PROMPT_TEMPLATE, get_prompt_modules


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
        """Convert tools to OpenAI function calling format.

        Handles two input_schema formats:
        - Nested: {"type": "object", "properties": {...}, "required": [...]}
        - Flat:   {"param1": {...}, "param2": {...}}  (auto-wrapped)
        """
        openai_tools = []
        for tool in self._tools.values():
            schema = tool.input_schema or {}
            # Detect format: if "type" key with "object" exists, treat as nested
            if "properties" in schema:
                properties = schema["properties"]
                required = schema.get("required", [])
            else:
                # Flat dict: each key is a property name
                properties = {k: v for k, v in schema.items() if isinstance(v, dict)}
                required = []
            func_def = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
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
    """Persistent memory for the agent session with smart context management."""

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
        self.user_lang: str = "en"  # Detected once per message, used everywhere

        # Smart context manager for intelligent context selection
        try:
            from memory.smart_context import SmartContextManager
            self.smart_context = SmartContextManager(max_context_tokens=8000)
        except ImportError:
            self.smart_context = None
            logger.warning("SmartContextManager not available, using basic conversation")

    def store(self, key: str, value: Any):
        self.planning_results[key] = value

    def retrieve(self, key: str, default: Any = None) -> Any:
        return self.planning_results.get(key, default)

    # ------------------------------------------------------------------
    # CTV/OAR label priority (2026-06-16)
    # ------------------------------------------------------------------
    # User rule: when the SAME anatomical label appears in BOTH the
    # CTV segmentation (e.g. pancreatic head CT nnUNet which extracts
    # pancreas / duodenum / vessels as CTV sub-labels) AND the OAR
    # segmentation (TotalSegmentator's 117-organ map), CTV wins. This
    # matters most for pancreatic patients where:
    #   - CTV nnUNet outputs: tumor, artery, vein, pancreas
    #   - OAR TotalSegmentator outputs: pancreas, duodenum, ...
    # Without merging, the data tree shows two `pancreas` rows, the
    # DVH has duplicate traces, and DVH dose_eval gets confused.
    #
    # Two helpers below:
    #   _merge_ctv_labels_into_oar(): called when CTV completes. It
    #     takes the CTV's oar_array (which contains the CTV-version
    #     of pancreas / vessels) and MERGES it INTO the existing
    #     oar_array. For labels that exist in BOTH, the CTV voxels
    #     overwrite the OAR voxels (priority).
    #
    #   _strip_oar_labels_in_ctv(): called when OAR completes AFTER
    #     CTV has already been stored. It REMOVES any OAR labels
    #     whose name is in the CTV label map (so the OAR's pancreas
    #     can't overwrite the CTV's pancreas).
    # ------------------------------------------------------------------
    def _normalize_label_name(self, name: str) -> str:
        """Normalize a label name for comparison: lowercase, strip
        common anatomical suffixes that don't change identity
        (pancreas_head = pancreas, kidney_left = kidney, etc.).
        We aggressively strip any trailing qualifier so that
        TotalSegmentator's `pancreas_head` and CTV nnUNet's
        `pancreas` are recognized as the same organ.
        """
        if not name:
            return ""
        s = str(name).strip().lower().replace("-", "_").replace(" ", "_")
        # Iteratively strip suffixes until none match (handles
        # 'pancreas_head_left' → 'pancreas').
        suffixes = (
            "_left", "_right", "_anterior", "_posterior",
            "_superior", "_inferior", "_medial", "_lateral",
            "_head", "_body", "_tail", "_upper", "_lower",
            "_proximal", "_distal", "_central", "_peripheral",
            "_anterior_lobe", "_posterior_lobe",
        )
        changed = True
        while changed:
            changed = False
            for suf in suffixes:
                if s.endswith(suf):
                    s = s[:-len(suf)]
                    changed = True
                    break
        return s

    def _merge_ctv_labels_into_oar(self, ctv_oar_array, ctv_organ_names,
                                    ctv_label_stats, ctv_label_map):
        """Merge the CTV segmentation's OAR-equivalent labels (pancreas,
        vessels, etc.) INTO the existing OAR array. For matching label
        names, CTV voxels win.

        Safe to call when oar_array / organ_names are None or empty —
        we just store the CTV's versions as the new baseline.
        """
        try:
            import numpy as np
        except ImportError:
            return
        if ctv_oar_array is None:
            return
        ctv_arr = np.asarray(ctv_oar_array)
        if ctv_arr.size == 0:
            return
        # The CTV tool labels: {numeric_label: name}
        ctv_labels = {}
        if isinstance(ctv_organ_names, dict):
            ctv_labels.update(ctv_organ_names)
        if isinstance(ctv_label_map, dict):
            for k, v in ctv_label_map.items():
                if v not in ctv_labels.values():
                    ctv_labels[k] = v
        if not ctv_labels:
            return

        # Get the existing OAR array and label dict
        existing_oar = self.retrieve("oar_array")
        existing_names = self.retrieve("organ_names") or {}
        if existing_oar is None:
            # No prior OAR → just use CTV's OAR as the new baseline
            self.store("oar_array", ctv_arr)
            self.store("organ_names", dict(ctv_labels))
            return

        existing_arr = np.asarray(existing_oar)
        if existing_arr.shape != ctv_arr.shape:
            # Shape mismatch (rare) — bail out, keep existing
            logger.warning(f"CTV/OAR array shape mismatch "
                           f"({ctv_arr.shape} vs {existing_arr.shape}); "
                           f"skipping merge")
            return

        # Build a normalized-name → existing-label-id map for matching
        existing_by_norm = {}
        for lid, name in existing_names.items():
            norm = self._normalize_label_name(name)
            if norm and norm not in existing_by_norm:
                existing_by_norm[norm] = (lid, name)

        # Merge: for each CTV label, find matching OAR label by
        # normalized name, then overwrite those voxels with CTV's
        # voxels and CTV's label id.
        merged_names = dict(existing_names)
        for ctv_lid, ctv_name in ctv_labels.items():
            norm = self._normalize_label_name(ctv_name)
            if not norm:
                continue
            match = existing_by_norm.get(norm)
            if match:
                # Replace OAR's voxels with CTV's voxels (priority)
                oar_lid, oar_name = match
                try:
                    ctv_lid_int = int(ctv_lid)
                    oar_lid_int = int(oar_lid)
                    mask = (ctv_arr == ctv_lid_int)
                    if mask.any():
                        existing_arr[mask] = oar_lid_int
                except (ValueError, TypeError):
                    pass
                # Keep the existing OAR's display name (CTV's name
                # might be longer / different formatting).
            else:
                # New label not in OAR — add CTV's voxels under a
                # NEW label id that's not currently used. Find the
                # max existing id.
                try:
                    max_id = max(int(k) for k in existing_names.keys() if str(k).isdigit())
                except (ValueError, TypeError):
                    max_id = 100
                new_id = str(max_id + 1)
                try:
                    ctv_lid_int = int(ctv_lid)
                    mask = (ctv_arr == ctv_lid_int)
                    if mask.any():
                        existing_arr[mask] = int(new_id)
                        merged_names[new_id] = ctv_name
                except (ValueError, TypeError):
                    pass

        self.store("oar_array", existing_arr)
        self.store("organ_names", merged_names)
        logger.info(f"CTV/OAR merge: kept {len(merged_names)} labels, "
                    f"CTV overwrote matching OAR voxels for "
                    f"{sum(1 for n in ctv_labels.values() if self._normalize_label_name(n) in existing_by_norm)} labels")

    def _strip_oar_labels_in_ctv(self, oar_array, organ_names, organ_counts):
        """Remove labels from the OAR array whose name matches a CTV
        label name. Returns the filtered (array, names, counts) tuple.

        Called BEFORE storing OAR results, so OAR's `pancreas` doesn't
        overwrite the CTV's `pancreas`.
        """
        try:
            import numpy as np
        except ImportError:
            return oar_array, organ_names, organ_counts
        if oar_array is None or organ_names is None:
            return oar_array, organ_names, organ_counts
        ctv_labels = self.retrieve("ctv_label_map") or {}
        if isinstance(self.retrieve("ctv_label_stats"), dict):
            # Build name → set from ctv_label_stats keys
            ctv_names = set(self._normalize_label_name(k)
                            for k in (self.retrieve("ctv_label_stats") or {}).keys())
        else:
            ctv_names = set()
        # Also include label_map values
        if isinstance(ctv_labels, dict):
            for v in ctv_labels.values():
                norm = self._normalize_label_name(v)
                if norm:
                    ctv_names.add(norm)
        if not ctv_names:
            return oar_array, organ_names, organ_counts

        arr = np.asarray(oar_array)
        filtered_names = {}
        filtered_counts = {}
        if isinstance(organ_counts, dict):
            for lid, name in organ_names.items():
                if self._normalize_label_name(name) in ctv_names:
                    # Zero out voxels for this label
                    try:
                        arr[arr == int(lid)] = 0
                    except (ValueError, TypeError):
                        pass
                    # Don't add to filtered_names — drop the label
                else:
                    filtered_names[lid] = name
                    if organ_counts.get(lid) is not None:
                        filtered_counts[lid] = organ_counts[lid]
        else:
            for lid, name in organ_names.items():
                if self._normalize_label_name(name) not in ctv_names:
                    filtered_names[lid] = name

        logger.info(f"OAR strip: removed {len(organ_names) - len(filtered_names)} "
                    f"labels that overlap CTV (kept {len(filtered_names)})")
        return arr, filtered_names, filtered_counts

    def log_tool_call(self, tool_name: str, inputs: Dict, result):
        self.tool_results.append({
            "tool": tool_name,
            "inputs": {k: str(v)[:100] for k, v in inputs.items()},
            "success": result.success,
            "message": result.message,
            "execution_time": result.execution_time,
        })

    def add_message(self, role: str, content: str):
        """Add a message with smart context tracking."""
        self.conversation.append({"role": role, "content": content})

        # Also add to smart context manager
        if self.smart_context:
            self.smart_context.add_message(role, content)
    
    def set_ui_state(self, state: Dict):
        """Update UI state from frontend (selected files, etc)."""
        self._ui_state.update(state)
    
    def get_ui_state(self) -> Dict:
        return dict(self._ui_state)

    @staticmethod
    def is_ct_loaded(ui_state: Optional[Dict]) -> bool:
        """Check if CT is loaded. Handles both flat and nested (viewer.ct_loaded) formats."""
        if not ui_state:
            return False
        # Check top-level ct_loaded
        if ui_state.get("ct_loaded", False):
            return True
        # Check nested viewer.ct_loaded (sent by frontend collectUIState())
        viewer = ui_state.get("viewer", {})
        if isinstance(viewer, dict) and viewer.get("ct_loaded", False):
            return True
        # Fallback: if ct_path is set, CT is effectively loaded
        if ui_state.get("ct_path", "").strip():
            return True
        return False

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

        # Add CTV segmentation stats if available
        ctv_label_stats = self.retrieve("ctv_label_stats")
        if ctv_label_stats:
            parts.append("\n### CTV Segmentation Results (per-label):")
            for name, stats in ctv_label_stats.items():
                parts.append(
                    f"  - {name}: {stats['volume_cm3']} cm³ "
                    f"({stats['voxel_count']} voxels), "
                    f"center=[{', '.join(str(c) for c in stats['centroid_world'])}] mm"
                )

        # Add OAR organ names if available
        organ_names = self.retrieve("organ_names")
        organ_counts = self.retrieve("organ_counts")
        if organ_names:
            parts.append(f"\n### OAR Segmentation: {len(organ_names)} organs detected")
            # Show top 5 largest organs
            if organ_counts:
                sorted_organs = sorted(organ_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                for oid, count in sorted_organs:
                    name = organ_names.get(oid, organ_names.get(str(oid), f"organ_{oid}"))
                    parts.append(f"  - {name}: {count} voxels")

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

    def clear_conversation(self):
        """Clear conversation history and context summary for fresh start."""
        self.conversation = []
        self.context_summary = ""
        self.compaction_count = 0
        self.tool_results = []

        # Also clear smart context manager to prevent old context pollution
        if hasattr(self, 'smart_context') and self.smart_context:
            self.smart_context.clear()
            logger.info("Smart context cleared")

        # Clear experience memory
        if hasattr(self, 'exp_memory') and self.exp_memory:
            self.exp_memory.clear()
            logger.info("Experience memory cleared")

    def clear_all_data(self):
        """Clear all loaded data (CT, CTV, OAR, planning results) for a completely fresh start."""
        # Clear planning results (stores CT, CTV, OAR, dose, seeds, etc.)
        self.planning_results.clear()
        # Clear patient data
        self.patient_data.clear()
        # Clear tool results
        self.tool_results.clear()
        # Reset planning phase
        self.current_phase = PlanningPhase.IDLE
        logger.info("All data cleared (CT, CTV, OAR, planning results)")

        # Clear all enhanced integration components
        if hasattr(self, 'enhanced') and self.enhanced:
            try:
                # Clear layered memory session data
                if hasattr(self.enhanced, 'layered_memory'):
                    self.enhanced.layered_memory.clear_session_data()
                    logger.info("Layered memory session data cleared")

                # Clear skill crystallizer
                if hasattr(self.enhanced, 'skill_crystallizer'):
                    self.enhanced.skill_crystallizer.clear()
                    logger.info("Skill crystallizer cleared")

                # Clear reflexion engine
                if hasattr(self.enhanced, 'reflexion'):
                    self.enhanced.reflexion.clear()
                    logger.info("Reflexion engine cleared")

                # Reinitialize enhanced integration for fresh start
                self._init_enhanced_integration()
                logger.info("Enhanced integration reset for new session")
            except Exception as e:
                logger.warning(f"Failed to reset enhanced integration: {e}")

        logger.info(f"Conversation cleared for session {self.session_id}")

    def get_clean_context(self) -> str:
        """Return context summary with memory artifacts removed."""
        if not self.context_summary:
            return ""
        cleaned = self.context_summary
        # Remove [Called tool_name] artifacts
        cleaned = re.sub(r'\[Called [^\]]+\]', '', cleaned)
        # Remove [Tool result: ...] artifacts
        cleaned = re.sub(r'\[Tool result: [^\]]*\]', '', cleaned)
        # Remove multiple newlines
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return cleaned

    def get_smart_context(self, current_query: str = "") -> str:
        """
        Get intelligent context based on the current query.

        Uses SmartContextManager to select relevant messages based on:
        1. Recency (recent messages are more relevant)
        2. Entity overlap (messages about same entities)
        3. Topic overlap (messages about same topics)
        4. Importance (high-importance messages are kept)
        """
        if not self.smart_context:
            # Fallback to basic conversation
            return self._get_basic_context()

        # Get relevant context from smart manager
        relevant_messages = self.smart_context.get_relevant_context(current_query)

        if not relevant_messages:
            return ""

        # Format context
        context_parts = []
        for msg in relevant_messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            # Skip very short messages
            if len(content) < 10:
                continue

            # Format based on role
            if role == "user":
                context_parts.append(f"User: {content[:500]}")
            elif role == "assistant":
                context_parts.append(f"Assistant: {content[:500]}")
            elif role == "system":
                context_parts.append(f"[System] {content[:300]}")

        if not context_parts:
            return ""

        # Add entity context if available
        entities = self.smart_context.get_active_topics()
        if entities:
            entity_info = []
            for entity in entities[:5]:  # Top 5 entities
                entity_info.append(f"- {entity['name']} ({entity['type']}, mentioned {entity['count']}x)")
            if entity_info:
                context_parts.append("\nActive entities:\n" + "\n".join(entity_info))

        return "\n".join(context_parts[-20:])  # Last 20 relevant messages

    def _get_basic_context(self) -> str:
        """Fallback: get basic context from conversation history."""
        if not self.conversation:
            return ""

        # Get last 10 messages
        recent = self.conversation[-10:]
        context_parts = []
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "user":
                context_parts.append(f"User: {content[:300]}")
            elif role == "assistant":
                context_parts.append(f"Assistant: {content[:300]}")

        return "\n".join(context_parts)

    def get_context_stats(self) -> dict:
        """Get context manager statistics."""
        if self.smart_context:
            return self.smart_context.get_stats()
        return {
            "message_count": len(self.conversation),
            "entity_count": 0,
            "topic_count": 0,
        }

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


class ToolResultPipeline:
    """Unified tool result formatting and synthesis pipeline.

    Replaces scattered _format_tool_result, _build_direct_response, _synthesize_with_llm.
    Single entry point for all tool result processing.

    Flow:
        ToolResult → format() → synthesize() → Response
    """

    # Tool name → display category mapping
    _SEGMENTATION_TOOLS = {"ctv_segmentation", "oar_segmentation", "seed_segmentation"}
    _ANALYSIS_TOOLS = {"code_executor"}
    _UI_TOOLS = {"ui_controller"}
    _PLANNING_TOOLS = {"planning_pipeline", "seed_planning", "trajectory_planning", "dose_engine", "dose_evaluation"}

    @staticmethod
    def format(tool_name: str, result, lang: str = "en") -> str:
        """Single entry point for formatting tool results.

        Priority: result.display > auto-generated from metadata > result.message > generic
        """
        if not result.success:
            return f"Error: {result.error}" if lang == "en" else f"错误: {result.error}"

        # 1. Use tool's own display if set
        if result.display:
            return result.display

        meta = result.metadata or {}

        # 2. Auto-generate based on tool category
        if tool_name in ToolResultPipeline._SEGMENTATION_TOOLS:
            return ToolResultPipeline._format_segmentation(tool_name, result, meta, lang)
        if tool_name in ToolResultPipeline._ANALYSIS_TOOLS:
            return ToolResultPipeline._format_analysis(tool_name, result, meta, lang)
        if tool_name in ToolResultPipeline._UI_TOOLS:
            return ToolResultPipeline._format_ui(tool_name, result, meta, lang)
        if tool_name in ToolResultPipeline._PLANNING_TOOLS:
            return ToolResultPipeline._format_planning(tool_name, result, meta, lang)

        # 3. Use display_message from metadata (legacy support)
        display_msg = meta.get("display_message")
        if display_msg:
            return display_msg

        # 4. Fallback to message
        return result.message or f"{tool_name} completed."

    @staticmethod
    def _format_segmentation(tool_name: str, result, meta: dict, lang: str) -> str:
        """Format segmentation tool results."""
        if tool_name == "ctv_segmentation":
            vol = meta.get("ctv_volume_mm3", 0)
            vox = meta.get("ctv_voxel_count", 0)
            label_stats = meta.get("label_stats", {})
            if lang == "zh":
                lines = [
                    "## 🎯 CTV 分割",
                    "",
                    "| 指标 | 数值 |",
                    "|--------|-------|",
                    f"| 总体积 | {vol:.1f} mm³ ({vol/1000:.1f} cm³) |",
                    f"| 总体素数 | {vox:,} |",
                ]
                if label_stats:
                    lines.append("")
                    lines.append("### 各标签统计:")
                    lines.append("")
                    lines.append("| 标签 | 体积 | 体素 | 中心 (mm) |")
                    lines.append("|-------|--------|--------|-------------|")
                    for name, stats in label_stats.items():
                        center = stats.get('centroid_world', [0, 0, 0])
                        lines.append(
                            f"| {name} | {stats['volume_cm3']} cm³ | "
                            f"{stats['voxel_count']:,} | "
                            f"({center[0]:.0f}, {center[1]:.0f}, {center[2]:.0f}) |"
                        )
                lines.append("")
                lines.append("✅ 结果已在查看器面板中显示。")
            else:
                lines = [
                    "## 🎯 CTV Segmentation",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Total Volume | {vol:.1f} mm³ ({vol/1000:.1f} cm³) |",
                    f"| Total Voxels | {vox:,} |",
                ]
                if label_stats:
                    lines.append("")
                    lines.append("### Per-Label Statistics:")
                    lines.append("")
                    lines.append("| Label | Volume | Voxels | Center (mm) |")
                    lines.append("|-------|--------|--------|-------------|")
                    for name, stats in label_stats.items():
                        center = stats.get('centroid_world', [0,0,0])
                        lines.append(
                            f"| {name} | {stats['volume_cm3']} cm³ | "
                            f"{stats['voxel_count']:,} | "
                            f"({center[0]:.0f}, {center[1]:.0f}, {center[2]:.0f}) |"
                        )
                lines.append("")
                lines.append("✅ Results displayed in the Viewer panel.")
            return "\n".join(lines)
        elif tool_name == "oar_segmentation":
            organ_names = meta.get("organ_names", {})
            count = len(organ_names) if organ_names else 0
            if lang == "zh":
                lines = [
                    "## 🎯 OAR 分割",
                    "",
                    "| 指标 | 数值 |",
                    "|--------|-------|",
                    f"| 已分割器官 | {count} |",
                    "",
                    "✅ 结果已在查看器面板中显示。",
                ]
            else:
                lines = [
                    "## 🎯 OAR Segmentation",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Organs segmented | {count} |",
                    "",
                    "✅ Results displayed in the Viewer panel.",
                ]
            return "\n".join(lines)
        return result.message or f"{tool_name} completed."

    @staticmethod
    def _format_analysis(tool_name: str, result, meta: dict, lang: str) -> str:
        """Format analysis tool results (code_executor with CT stats)."""
        if tool_name == "code_executor" and isinstance(result.data, dict):
            stdout = result.data.get("stdout", "").strip()
            if stdout:
                try:
                    import json as _json
                    d = _json.loads(stdout)
                    if isinstance(d, dict) and "dimensions" in d:
                        dims = d["dimensions"]
                        vs = d["voxel_size"]
                        sr = d["scan_range_cm"]
                        hu = d["hu_range"]
                        if lang == "zh":
                            lines = [
                                "## 🔍 CT 分析",
                                "",
                                "| 参数 | 数值 |",
                                "|-----------|-------|",
                                f"| 维度 | {dims[0]} × {dims[1]} × {dims[2]} 体素 |",
                                f"| 体素尺寸 | {vs[0]} × {vs[1]} × {vs[2]} mm |",
                                f"| 扫描范围 | {sr[0]} × {sr[1]} × {sr[2]} cm |",
                                f"| HU 范围 | {hu[0]} ~ {hu[1]} |",
                                f"| 平均 HU | {d.get('mean_hu', 'N/A')} |",
                            ]
                            tissues = d.get("tissues", [])
                            if tissues:
                                lines.append("")
                                lines.append("| 组织 | HU 范围 | 占比 |")
                                lines.append("|--------|----------|-------|")
                                for t in tissues:
                                    lines.append(f"| {t['name']} | {t['range']} | {t['pct']}% |")
                        else:
                            lines = [
                                "## 🔍 CT Analysis",
                                "",
                                "| Parameter | Value |",
                                "|-----------|-------|",
                                f"| Dimensions | {dims[0]} × {dims[1]} × {dims[2]} voxels |",
                                f"| Voxel size | {vs[0]} × {vs[1]} × {vs[2]} mm |",
                                f"| Scan range | {sr[0]} × {sr[1]} × {sr[2]} cm |",
                                f"| HU range | {hu[0]} ~ {hu[1]} |",
                                f"| Mean HU | {d.get('mean_hu', 'N/A')} |",
                            ]
                            tissues = d.get("tissues", [])
                            if tissues:
                                lines.append("")
                                lines.append("| Tissue | HU Range | Share |")
                                lines.append("|--------|----------|-------|")
                                for t in tissues:
                                    lines.append(f"| {t['name']} | {t['range']} | {t['pct']}% |")
                        return "\n".join(lines)
                except (ValueError, KeyError, TypeError):
                    pass
                return "\n".join(l.strip() for l in stdout.split('\n') if l.strip())
        return result.message or f"{tool_name} completed."

    @staticmethod
    def _format_ui(tool_name: str, result, meta: dict, lang: str) -> str:
        """Format UI controller results."""
        display_msg = meta.get("display_message")
        if display_msg:
            return display_msg
        return result.message or f"{tool_name} completed."

    @staticmethod
    def _format_planning(tool_name: str, result, meta: dict, lang: str) -> str:
        """Format planning tool results."""
        if tool_name == "planning_pipeline":
            step = meta.get("step_executed", "full")
            total_seeds = meta.get("total_seeds", 0)
            num_traj = meta.get("num_trajectories", 0)
            metrics = meta.get("dose_metrics", {})

            if step == "full":
                if lang == "zh":
                    lines = [
                        "## 📋 近距离放疗规划完成",
                        "",
                        "| 指标 | 数值 |",
                        "|--------|-------|",
                        f"| 粒子总数 | {total_seeds} |",
                        f"| 轨迹数 | {num_traj} |",
                        f"| V100 | {metrics.get('v100', 0):.1%} |",
                        f"| D90 | {metrics.get('d90', 0):.2f} |",
                        f"| 计划评分 | {metrics.get('plan_score', 0):.0f}/100 |",
                        "",
                        "✅ 粒子、针道和剂量已显示在 3D 查看器中。",
                    ]
                else:
                    lines = [
                        "## 📋 Brachytherapy Planning Complete",
                        "",
                        "| Metric | Value |",
                        "|--------|-------|",
                        f"| Total Seeds | {total_seeds} |",
                        f"| Trajectories | {num_traj} |",
                        f"| V100 | {metrics.get('v100', 0):.1%} |",
                        f"| D90 | {metrics.get('d90', 0):.2f} |",
                        f"| Plan Score | {metrics.get('plan_score', 0):.0f}/100 |",
                        "",
                        "✅ Seeds, needles, and dose displayed in 3D viewer.",
                    ]
                return "\n".join(lines)
            else:
                if lang == "zh":
                    return result.message or f"规划步骤 '{step}' 完成。"
                return result.message or f"Planning step '{step}' completed."

        elif tool_name == "seed_planning":
            total = meta.get("total_seeds", 0)
            num_traj = meta.get("num_trajectories", 0)
            mode = meta.get("mode", "rule_based")
            if lang == "zh":
                lines = [
                    "## 🎯 粒子植入规划",
                    "",
                    "| 指标 | 数值 |",
                    "|--------|-------|",
                    f"| 粒子数 | {total} |",
                    f"| 轨迹数 | {num_traj} |",
                    f"| 模式 | {mode} |",
                    "",
                    "✅ 结果已存储,用于剂量计算。",
                ]
            else:
                lines = [
                    "## 🎯 Seed Planning",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Seeds | {total} |",
                    f"| Trajectories | {num_traj} |",
                    f"| Mode | {mode} |",
                    "",
                    "✅ Results stored for dose calculation.",
                ]
            return "\n".join(lines)

        elif tool_name == "trajectory_planning":
            num = meta.get("num_trajectories", 0)
            max_depth = meta.get("max_depth_mm", 0)
            if lang == "zh":
                lines = [
                    "## 📍 轨迹规划",
                    "",
                    "| 指标 | 数值 |",
                    "|--------|-------|",
                    f"| 候选轨迹 | {num} |",
                    f"| 最大深度 | {max_depth:.1f} mm |",
                    "",
                    "✅ 结果已存储,用于粒子规划。",
                ]
            else:
                lines = [
                    "## 📍 Trajectory Planning",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Candidate Trajectories | {num} |",
                    f"| Max Depth | {max_depth:.1f} mm |",
                    "",
                    "✅ Results stored for seed planning.",
                ]
            return "\n".join(lines)

        elif tool_name == "dose_engine":
            max_dose = meta.get("max_dose", 0)
            mean_dose = meta.get("mean_dose", 0)
            num_seeds = meta.get("num_seeds", 0)
            engine = meta.get("engine", "cnn")
            if lang == "zh":
                lines = [
                    "## 💊 剂量计算",
                    "",
                    "| 指标 | 数值 |",
                    "|--------|-------|",
                    f"| 最大剂量 | {max_dose:.2f} |",
                    f"| 平均剂量 | {mean_dose:.2f} |",
                    f"| 粒子数 | {num_seeds} |",
                    f"| 引擎 | {engine} |",
                ]
            else:
                lines = [
                    "## 💊 Dose Calculation",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| Max Dose | {max_dose:.2f} |",
                    f"| Mean Dose | {mean_dose:.2f} |",
                    f"| Seeds | {num_seeds} |",
                    f"| Engine | {engine} |",
                ]
            return "\n".join(lines)

        elif tool_name == "dose_evaluation":
            v100 = meta.get("v100", 0)
            d90 = meta.get("d90", 0)
            score = meta.get("plan_score", 0)
            if lang == "zh":
                lines = [
                    "## 📊 剂量评估",
                    "",
                    "| 指标 | 数值 |",
                    "|--------|-------|",
                    f"| V100 | {v100:.1%} |",
                    f"| D90 | {d90:.2f} |",
                    f"| 计划评分 | {score:.0f}/100 |",
                ]
            else:
                lines = [
                    "## 📊 Dose Evaluation",
                    "",
                    "| Metric | Value |",
                    "|--------|-------|",
                    f"| V100 | {v100:.1%} |",
                    f"| D90 | {d90:.2f} |",
                    f"| Plan Score | {score:.0f}/100 |",
                ]
            return "\n".join(lines)

        return result.message or f"{tool_name} completed."

    @staticmethod
    def format_steps(steps: List[dict], lang: str = "en") -> str:
        """Format all tool steps into a raw concatenated response (no LLM synthesis)."""
        parts = []
        errors = []
        for s in steps:
            if s.get("type") != "tool":
                continue
            tool = s.get("tool", "")
            status = s.get("status", "")
            result = s.get("result", "")
            if status == "error":
                errors.append(f"❌ {tool}: {result}")
                continue
            if result:
                parts.append(result)
        if errors:
            parts.append(("## ⚠️ " + ("问题" if lang == "zh" else "Issues")) + "\n" + "\n".join(errors))
        return "\n\n".join(parts) or ("工具已执行。" if lang == "zh" else "Tools executed.")

    @staticmethod
    def synthesize(formatted_results: List[dict], user_message: str, brain_router, lang: str, query_type: str = "knowledge") -> str:
        """Call LLM once to synthesize all tool results into coherent narrative.

        Args:
            formatted_results: List of {"tool": str, "display": str}
            user_message: Original user question
            brain_router: LLM router for synthesis call
            lang: "zh" or "en"
            query_type: realtime|knowledge|analysis|system

        Returns:
            Synthesized response string, or concatenated results if LLM fails.
        """
        if not formatted_results:
            return ""

        # Build raw concatenation as fallback
        raw_parts = [r["display"] for r in formatted_results if r.get("display")]
        raw_fallback = "\n\n".join(raw_parts)

        if not brain_router:
            return raw_fallback

        # Build synthesis prompt
        tool_summary = []
        for r in formatted_results:
            name = r.get("tool", "")
            display = r.get("display", "")
            if display:
                tool_summary.append(f"[{name}]\n{display[:500]}")

        if not tool_summary:
            return raw_fallback

        # Source attribution based on query type
        if lang == "zh":
            source_rules = {
                'realtime': "标注数据来源和年份。如果搜索结果不包含所需数据，诚实说'未找到最新数据'，不要编造。",
                'knowledge': "引用来源（如指南名称、文献DOI）。如果AI知识与搜索结果矛盾，以搜索结果为准。",
                'analysis': "在回复末尾标注'💡 以上为AI分析，仅供参考'。",
                'system': "直接引用系统内部数据，不需要搜索验证。",
            }
        else:
            source_rules = {
                'realtime': "Cite source and year. If search results don't contain the data, say 'Latest data not found' honestly. Do NOT fabricate.",
                'knowledge': "Cite sources (e.g., guideline names, DOIs). If AI knowledge contradicts search results, prefer search results.",
                'analysis': "Add '💡 AI analysis, for reference only' at the end.",
                'system': "Quote internal system data directly. No search verification needed.",
            }
        source_rule = source_rules.get(query_type, source_rules['knowledge'])

        # Collect all source URLs from results
        all_sources = []
        for r in formatted_results:
            urls = r.get("all_source_urls", [])
            if urls:
                all_sources.extend(urls)
            elif r.get("source_url"):
                all_sources.append(r["source_url"])
        # Deduplicate
        seen = set()
        unique_sources = []
        for u in all_sources:
            if u not in seen:
                seen.add(u)
                unique_sources.append(u)
        sources_text = "\n".join(f"- {u}" for u in unique_sources) if unique_sources else ""

        # Detect search failures
        search_failed = False
        for r in formatted_results:
            tool_name = r.get("tool", "")
            display = r.get("display", "")
            if tool_name in ("web_search", "web_fetch", "web_access"):
                if "error" in display.lower() or "failed" in display.lower() or "network" in display.lower():
                    search_failed = True
                    break

        # Build anti-hallucination constraints
        if search_failed:
            anti_halluc = (
                "CRITICAL: Web search FAILED (network error). "
                "You may use your own knowledge to help, but you MUST add '(personal inference)' or '(I think)' at the end. "
                "Suggest the user retry or provide the information directly."
            ) if lang != "zh" else (
                "严重警告：网络搜索失败（网络错误）。"
                "你可以用自己的知识补充，但必须在相关内容后加'（个人推断）'或'（我认为）'。"
                "建议用户重试或直接提供信息。"
            )
        else:
            anti_halluc = (
                "IMPORTANT: Clearly distinguish information sources in your response:\n"
                "- Information FROM search results: state normally\n"
                "- Information from your OWN KNOWLEDGE (not in search results): add '(personal inference)' or '(I think)' at the end\n"
                "If results are insufficient, you may supplement with your knowledge but MUST label it. "
                "Never present unverified information as if it came from search results."
            ) if lang != "zh" else (
                "重要规则：回复中必须区分信息来源：\n"
                "- 来自搜索结果的信息：正常陈述\n"
                "- 来自你自身知识（搜索结果中没有的）：在句末加'（个人推断）'或'（我认为）'\n"
                "如果搜索结果不足，可以用自身知识补充，但必须标注来源。"
                "绝对不要把未经验证的信息当作搜索结果来呈现。"
            )

        if lang == "zh":
            synth_prompt = (
                f"用户问题: {user_message}\n\n"
                f"{anti_halluc}\n\n"
                "你刚刚自动执行了以下工具来回答用户问题。"
                "请基于结果生成一个连贯的中文回复。要求：\n"
                "1. **全部用中文回复**——包括搜索结果的摘要、文献介绍、所有内容必须翻译成中文\n"
                "2. 先用一句话说明做了什么（如：已完成CT分析、CTV分割和OAR分割）\n"
                "3. **所有适合结构化的数据必须用表格或列表展示**（如：图像参数、分割结果、器官列表、剂量指标等）\n"
                "4. 对关键数据给出简要解读\n"
                f"5. **信息溯源**: {source_rule}\n"
                "6. 如有异常（如分割体积为0），明确指出并建议\n"
                "7. 引用搜索结果时，将URL自然嵌入正文（如：[文献名](URL)），不要单独列出\n\n"
                f"工具执行结果：\n" + "\n\n".join(tool_summary)
                + (f"\n\n可用来源URL：\n{sources_text}" if sources_text else "")
            )
        else:
            # Detect if this was a planning run — if so, we demand a much
            # more comprehensive clinical response with all metrics,
            # OAR dose analysis, flagged issues, and clinical guidelines.
            # The user complained (2026-06-16) that the LLM response
            # after planning was just a 5-row table with no OAR analysis,
            # no flagged issues, no clinical context — "太简短"
            # (too brief). This template forces the LLM to actually
            # structure the response like a real clinical report.
            planning_tools = {"ctv_segmentation", "oar_segmentation",
                              "planning_pipeline", "seed_planning",
                              "dose_calc", "dose_evaluation",
                              "trajectory_init", "trajectory_refine"}
            is_planning = any(
                r.get("tool") in planning_tools
                for r in formatted_results
            )
            if is_planning:
                synth_prompt = (
                    f"User question: {user_message}\n\n"
                    f"{anti_halluc}\n\n"
                    "You just executed the brachytherapy planning pipeline. "
                    "Generate a COMPREHENSIVE clinical response — the user explicitly "
                    "complained that previous responses were too brief (just a 5-row "
                    "metric table). This response must be thorough.\n\n"
                    "REQUIRED SECTIONS (in this order):\n\n"
                    "## 1. Workflow Summary\n"
                    "2-3 sentences: which tools ran, in what order, and the overall "
                    "outcome (success / partial / needs-attention).\n\n"
                    "## 2. CTV Segmentation\n"
                    "- Tumor volume in cm³ (convert mm³ → cm³: divide by 1000)\n"
                    "- Voxel count\n"
                    "- Anatomical location (e.g. pancreatic head, prostate peripheral zone)\n"
                    "- Number of CTV sub-labels found (e.g. tumor, artery, vein, pancreas)\n\n"
                    "## 3. OAR Segmentation\n"
                    "- Total OAR count (typical: 50-117 for TotalSegmentator)\n"
                    "- List the 5-10 most clinically relevant OARs that appear in this case "
                    "(e.g. duodenum, small_bowel, colon, stomach, liver, kidney, spinal cord)\n"
                    "- Note any OARs that are MISSING or have zero voxels\n\n"
                    "## 4. Trajectory & Seed Plan\n"
                    "- Number of trajectories generated\n"
                    "- Number of seeds placed\n"
                    "- Mode used (rule_based / rl)\n"
                    "- Trajectory density (seeds per cm³ CTV)\n"
                    "- Any anatomical obstacles avoided (vessels, bones, critical OARs)\n\n"
                    "## 5. Dose Distribution\n"
                    "- Prescription dose\n"
                    "- CTV coverage: V100, V150, V200 (as percentages)\n"
                    "- D90, Dmean, D2 (max dose in Gy)\n"
                    "- Conformity Index (CI), Homogeneity Index (HI)\n"
                    "- Plan score (0-100)\n\n"
                    "## 6. OAR Dose Analysis — MUST INCLUDE TABLE\n"
                    "Present ALL OAR metrics returned by dose_evaluation in a TABLE:\n"
                    "| OAR | Dmax (Gy) | D2cc (Gy) | D1cc (Gy) | Status |\n"
                    "|-----|-----------|-----------|-----------|--------|\n"
                    "Then for each OAR, classify status as: OK / WARN / EXCEEDS based on:\n"
                    "- ABS / GEC-ESTRO / ICRU 89 / TG-43 / TG-229 / QUANTEC tolerance\n"
                    "- V100 < 1.0 Gy, D2cc < 1.0 Gy (1xRx) = OK\n"
                    "- Dmax > 2xRx = EXCEEDS\n"
                    "- D2cc > 1xRx = WARN\n\n"
                    "## 7. Flagged Issues\n"
                    "Bullet list of every metric that does NOT meet clinical tolerance, "
                    "with the actual value vs. the tolerance and a one-line clinical implication.\n\n"
                    "## 8. Clinical Recommendations\n"
                    "3-5 bullet points: actionable next steps (e.g. consider seed repositioning "
                    "near duodenum, validate with secondary dose calculation, consult radiation "
                    "oncologist for plan acceptance).\n\n"
                    "## 9. References\n"
                    "Inline links to relevant guidelines — pick the most applicable 2-3:\n"
                    "- [TG-43 AAPM](https://www.aapm.org/pubs/reports/RPT_268.pdf)\n"
                    "- [GEC-ESTRO](https://www.estro.org/Science/Guidelines)\n"
                    "- [ICRU Report 89](https://www.icru.org/report/icru-report-89-prescribing-recording-and-reporting-photon-beam-therapy-2nd-edition)\n"
                    "- [ABS Brachy Guidelines](https://www.americanbrachytherapy.org/)\n"
                    "- [TG-229 AAPM](https://www.aapm.org/pubs/reports/RPT_229.pdf)\n"
                    "- [NCCN Guidelines](https://www.nccn.org/guidelines)\n\n"
                    f"10. **Source attribution**: {source_rule}\n\n"
                    "## Tool results:\n" + "\n\n".join(tool_summary)
                    + (f"\n\nAvailable source URLs:\n{sources_text}" if sources_text else "")
                )
            else:
                synth_prompt = (
                    f"User question: {user_message}\n\n"
                    f"{anti_halluc}\n\n"
                    "You just executed the following tools. Generate a coherent English response.\n"
                    "Requirements:\n"
                    "1. **Respond entirely in English** — translate any non-English content\n"
                    "2. Summarize what was done and the results of each tool\n"
                    "3. **All structured data must be presented in tables or lists** (e.g., image parameters, segmentation results, organ lists, dose metrics)\n"
                    "4. Briefly interpret key data points\n"
                    f"5. **Source attribution**: {source_rule}\n"
                    "6. Note any anomalies (e.g., zero volume) and suggest next steps\n"
                    "7. When citing search results, embed URLs naturally in text (e.g., [title](URL)), don't list them separately\n\n"
                    "Tool results:\n" + "\n\n".join(tool_summary)
                    + (f"\n\nAvailable source URLs:\n{sources_text}" if sources_text else "")
                )

        try:
            resp = brain_router.chat(synth_prompt)
            synthesized = resp.content if hasattr(resp, 'content') else str(resp)
            return synthesized.strip() if synthesized.strip() else raw_fallback
        except Exception as e:
            logger.warning(f"LLM synthesis failed, using raw results: {e}")
            return raw_fallback


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

        # Register as global agent for tools that need it (e.g. planning_pipeline)
        import AgenticSys as _self_module
        _self_module._global_agent = self

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
                # Default: Anthropic-compatible provider.
                # base_url points to the proxy; model/api_key are
                # configurable. Works with any Anthropic-protocol endpoint.
                llm_config = {
                    "anthropic": {
                        "enabled": True,
                        "model": "mimo-v2.5",
                        "base_url": "https://token-plan-cn.xiaomimimo.com/anthropic",
                        "api_key": "tp-cebuhb3x0bgx7qhx4wyc5g7ri65s8a91b7x4gocgvsoom89y",
                    }
                }

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

    def _init_multi_agent(self):
        """Initialize multi-agent system for quality review."""
        self.multi_agent_wrapper = None
        try:
            from agents import BrachyAgentMultiAgentWrapper

            # Create LLM callback for multi-agent system
            llm_callback = None
            if self.brain_available and hasattr(self, "brain_router") and self.brain_router:
                def _ma_llm_cb(prompt):
                    resp = self.brain_router.chat(prompt)
                    return resp.content if hasattr(resp, "content") else str(resp)
                llm_callback = _ma_llm_cb

            self.multi_agent_wrapper = BrachyAgentMultiAgentWrapper(llm_callback=llm_callback)
            logger.info("Multi-agent system initialized")
        except Exception as e:
            logger.warning(f"Multi-agent system not available: {e}")

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
        the tool errors with "No CTV mask available". Previously
        the user saw this error and the LLM had to retry. Now we
        proactively auto-fire ctv_segmentation (and oar_segmentation
        if missing) so the planning call succeeds. This makes the
        LLM's life easier and avoids the error message.
        """
        # Tools that need CTV pre-segmentation
        planning_tools_need_ctv = {
            "planning_pipeline", "seed_planning", "trajectory_planning",
            "dose_evaluation", "dose_calc", "dose_engine",
        }
        if tool_name in planning_tools_need_ctv:
            ctv_array = self.memory.retrieve("ctv_array")
            if ctv_array is None:
                # Auto-fire ctv_segmentation
                ct_path = self.memory.retrieve("ct_path")
                if ct_path:
                    logger.info(f"[auto-fix] No CTV mask for {tool_name}; auto-firing ctv_segmentation")
                    if step_callback is not None:
                        try:
                            step_callback("ctv_segmentation", "pending", "Auto-fired: planning pipeline needs CTV")
                        except Exception:
                            pass
                    ctv_params = {"image_path": ct_path, "tumor_type": "nnunet_pancreatic"}
                    ct_img = self.memory.retrieve("ct_image")
                    if ct_img is not None:
                        ctv_params["image"] = ct_img
                    try:
                        ctv_result = self.registry.execute("ctv_segmentation", **ctv_params)
                        if ctv_result and ctv_result.success:
                            if "ctv_array" in (ctv_result.metadata or {}):
                                self.memory.store("ctv_array", ctv_result.metadata["ctv_array"])
                            if "ctv_mask" in (ctv_result.metadata or {}):
                                self.memory.store("ctv_mask", ctv_result.metadata["ctv_mask"])
                            # Store ctv_voxels/volume for report generation
                            _cv = (ctv_result.metadata or {}).get("ctv_voxel_count")
                            if not _cv:
                                try:
                                    _cv = int(np.sum(np.asarray(ctv_result.metadata["ctv_array"]) > 0))
                                except Exception:
                                    _cv = 0
                            self.memory.store("ctv_voxels", _cv)
                            _cvm3 = (ctv_result.metadata or {}).get("ctv_volume_mm3")
                            if _cvm3:
                                self.memory.store("ctv_volume_mm3", _cvm3)
                            if step_callback is not None:
                                try:
                                    step_callback("ctv_segmentation", "done",
                                                  f"Auto-fired: {ctv_result.message[:100]}")
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.warning(f"[auto-fix] ctv_segmentation auto-fire failed: {e}")
                # Also auto-fire oar if missing (planning also needs OAR for trajectory avoidance)
                if self.memory.retrieve("oar_array") is None:
                    ct_path2 = self.memory.retrieve("ct_path")
                    if ct_path2:
                        logger.info(f"[auto-fix] No OAR map for {tool_name}; auto-firing oar_segmentation")
                        oar_params = {"organ_type": "general", "image_path": ct_path2}
                        ct_img2 = self.memory.retrieve("ct_image")
                        if ct_img2 is not None:
                            oar_params["image"] = ct_img2
                        try:
                            oar_result = self.registry.execute("oar_segmentation", **oar_params)
                            if oar_result and oar_result.success:
                                if "oar_array" in (oar_result.metadata or {}):
                                    self.memory.store("oar_array", oar_result.metadata["oar_array"])
                                if "organ_names" in (oar_result.metadata or {}):
                                    self.memory.store("organ_names", oar_result.metadata["organ_names"])
                        except Exception as e:
                            logger.warning(f"[auto-fix] oar_segmentation auto-fire failed: {e}")
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
            # Map tumor_type to VoCo tool name if needed, and store for planning pipeline
            if "tumor_type" in params:
                params["tumor_type"] = self._map_tumor_type(params["tumor_type"])
                # Store tumor type so planning pipeline can use organ-specific reference direction
                self.memory.store("tumor_type_used", params["tumor_type"])
        elif tool_name == "oar_segmentation":
            # Same: always force-inject LPI-oriented CT
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
                    from tool_factory import ToolResult as _TR
                    result = _TR(
                        success=True,
                        data={"ctv_array": _existing_ctv},
                        message="CTV already segmented (skipped redundant call).",
                        metadata={
                            "ctv_array": _existing_ctv,
                            "ctv_mask": self.memory.retrieve("ctv_mask") or _existing_ctv,
                            "skipped_duplicate": True,
                        },
                    )
                    _skip_tool = True
        if tool_name == "oar_segmentation":
            _existing_oar = self.memory.retrieve("oar_array")
            _existing_names = self.memory.retrieve("organ_names") or {}
            _existing_path = self.memory.retrieve("ct_path")
            if _existing_oar is not None and len(_existing_names) >= 50:
                _req_path = params.get("image_path", _existing_path)
                if _req_path in (None, _existing_path):
                    logger.info(
                        f"[dedup] oar_segmentation called but memory "
                        f"already has {len(_existing_names)} organs "
                        f"(auto-OAR result). Skipping redundant run."
                    )
                    if progress_callback:
                        progress_callback("OAR already segmented (skipped)", 90)
                    from tool_factory import ToolResult as _TR
                    result = _TR(
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
            # Use validation + recovery for critical tools
            if tool_name in self._VALIDATORS:
                result = self._validate_and_execute(tool_name, params)
            else:
                result = self.registry.execute(tool_name, **params)

        if progress_callback:
            progress_callback(f"Processing results...", 90)

        if result.success:
            logger.info(f"Tool {tool_name} succeeded. Metadata keys: {list(result.metadata.keys()) if result.metadata else 'None'}")
            if tool_name == "ctv_segmentation" and "ctv_array" in result.metadata:
                self.memory.store("ctv_array", result.metadata["ctv_array"])
                if "ctv_mask" in result.metadata:
                    self.memory.store("ctv_mask", result.metadata["ctv_mask"])
                if "label_stats" in result.metadata:
                    self.memory.store("ctv_label_stats", result.metadata["label_stats"])
                if "label_map" in result.metadata:
                    self.memory.store("ctv_label_map", result.metadata["label_map"])
                # Store ctv_voxels and ctv_volume directly so
                # _build_planning_report can read them from memory.
                _cv = result.metadata.get("ctv_voxel_count")
                if not _cv:
                    try:
                        _cv = int(np.sum(np.asarray(result.metadata["ctv_array"]) > 0))
                    except Exception:
                        _cv = 0
                self.memory.store("ctv_voxels", _cv)
                _cvm3 = result.metadata.get("ctv_volume_mm3")
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
                        result.metadata.get("oar_array"),
                        result.metadata.get("organ_names"),
                        result.metadata.get("label_stats"),
                        result.metadata.get("label_map"),
                    )
                except AttributeError:
                    # Fallback if memory helper is missing (defensive)
                    if "oar_array" in result.metadata:
                        self.memory.store("oar_array", result.metadata["oar_array"])
                    if "organ_names" in result.metadata:
                        self.memory.store("organ_names", result.metadata["organ_names"])
            elif tool_name == "oar_segmentation":
                logger.info(f"OAR segmentation result: oar_array={'oar_array' in result.metadata}, organ_names={'organ_names' in result.metadata}")
                # BUG FIX 2026-06-16: BEFORE storing the new OAR
                # array, REMOVE any labels that are also in the
                # CTV label map (CTV wins). This handles the case
                # where OAR runs FIRST (before CTV) — when CTV
                # eventually runs, the CTV labels are merged on
                # top via _merge_ctv_labels_into_oar. But if the
                # user runs OAR again after CTV, this prevents the
                # OAR's `pancreas` from overwriting the CTV's
                # `pancreas`.
                oar_array = result.metadata.get("oar_array")
                organ_names = result.metadata.get("organ_names")
                organ_counts = result.metadata.get("organ_counts")
                if oar_array is not None:
                    # BUG FIX 2026-06-16: route helper through self.memory
                    try:
                        oar_array, organ_names, organ_counts = self.memory._strip_oar_labels_in_ctv(
                            oar_array, organ_names, organ_counts
                        )
                    except AttributeError:
                        pass
                if oar_array is not None:
                    self.memory.store("oar_array", oar_array)
                if organ_names is not None:
                    self.memory.store("organ_names", organ_names)
                    logger.info(f"Stored organ_names: {organ_names}")
                if organ_counts is not None:
                    self.memory.store("organ_counts", organ_counts)
            # If CTV segmentation completed but the resulting OAR map is
            # missing or only carries a few labels (the CTV pipeline also
            # extracts a tiny set of "vessel" labels), auto-trigger a
            # full OAR segmentation so the planning pipeline can use the
            # real organ map (TotalSegmentator's 117 organs) for dose
            # evaluation and trajectory avoidance. Without this, the
            # LLM sometimes skips oar_segmentation and planning_pipeline
            # runs with only the 2-3 vessel labels, producing a poor
            # V100 / D90 and a wrong "2 organs" report.
            if tool_name == "ctv_segmentation" and result.success:
                oar_array = self.memory.retrieve("oar_array")
                organ_count = 0
                if oar_array is not None:
                    try:
                        import numpy as _np
                        organ_count = int(len(_np.unique(oar_array)) - 1)  # subtract background
                    except Exception:
                        organ_count = 0
                if organ_count < 5:  # Need a real OAR map, not just 2-3 vessels
                    logger.info(f"[auto-oar] CTV seg completed but OAR map has only {organ_count} organs — auto-running oar_segmentation")
                    # Emit a 'pending' step event so the todo list ticks
                    # through oar_segmentation just like the LLM had
                    # called it explicitly. The user's complaint:
                    # "OAR was silently auto-run by the agent but the
                    # todo list never showed it, so the workflow
                    # appeared incomplete." With this emit, the
                    # predicted oar_segmentation row gets the
                    # breathing animation, then transitions to done
                    # when auto-OAR completes.
                    if step_callback is not None:
                        try:
                            step_callback("oar_segmentation", "pending", "Auto-running OAR (CTV map had <5 organs)")
                        except Exception as _e:
                            logger.debug(f"step_callback (oar pending) failed: {_e}")
                    try:
                        # The oar_segmentation tool accepts EITHER an in-memory
                        # `image` (SimpleITK Image) or an on-disk `image_path`.
                        # The in-memory path is faster (skips re-reading the
                        # file from disk) but the tool's validator rejects
                        # when the image is passed without image_path. Pass
                        # both, with image_path coming from the agent's
                        # memory if available (so the tool can also write
                        # cached side files consistently).
                        oar_params = {"organ_type": "general"}
                        ct_image = self.memory.retrieve("ct_image")
                        ct_path = self.memory.retrieve("ct_path")
                        if ct_image is not None:
                            oar_params["image"] = ct_image
                        if ct_path:
                            oar_params["image_path"] = ct_path
                        oar_result = self.registry.execute("oar_segmentation", **oar_params)
                        if oar_result and oar_result.success:
                            if "oar_array" in (oar_result.metadata or {}):
                                # BUG FIX 2026-06-16 (CTV/OAR priority):
                                # strip any OAR labels that overlap with
                                # the CTV's label map so the auto-OAR
                                # doesn't overwrite the CTV's pancreas
                                # with the TotalSegmentator version.
                                oar_a = oar_result.metadata["oar_array"]
                                oar_n = oar_result.metadata.get("organ_names", {})
                                oar_c = oar_result.metadata.get("organ_counts", {})
                                # BUG FIX 2026-06-16: route helper through self.memory
                                try:
                                    oar_a, oar_n, oar_c = self.memory._strip_oar_labels_in_ctv(
                                        oar_a, oar_n, oar_c
                                    )
                                except AttributeError:
                                    pass
                                self.memory.store("oar_array", oar_a)
                                if oar_n:
                                    self.memory.store("organ_names", oar_n)
                                if oar_c:
                                    self.memory.store("organ_counts", oar_c)
                            elif "organ_names" in (oar_result.metadata or {}):
                                # Fallback: OAR has no array but has names
                                # (rare). Still strip overlapping labels.
                                oar_n = oar_result.metadata["organ_names"]
                                oar_c = oar_result.metadata.get("organ_counts", {})
                                try:
                                    _, oar_n, oar_c = self.memory._strip_oar_labels_in_ctv(
                                        None, oar_n, oar_c
                                    )
                                except AttributeError:
                                    pass
                                self.memory.store("organ_names", oar_n)
                                if oar_c:
                                    self.memory.store("organ_counts", oar_c)
                            logger.info(f"[auto-oar] OAR seg done: {len(oar_result.metadata.get('organ_names', {}))} organs (after CTV-strip)")
                            # Emit 'done' for the predicted oar row.
                            if step_callback is not None:
                                try:
                                    n_organs = len(oar_result.metadata.get("organ_names", {}))
                                    step_callback("oar_segmentation", "done", f"{n_organs} organs")
                                except Exception as _e:
                                    logger.debug(f"step_callback (oar done) failed: {_e}")
                        else:
                            logger.warning(f"[auto-oar] OAR seg failed: {oar_result.error if oar_result else 'no result'}")
                            if step_callback is not None:
                                try:
                                    step_callback("oar_segmentation", "error", oar_result.error if oar_result else "no result")
                                except Exception as _e:
                                    logger.debug(f"step_callback (oar error) failed: {_e}")
                    except Exception as e:
                        logger.warning(f"[auto-oar] exception: {e}")
            elif tool_name == "trajectory_planning" and "trajectories" in result.metadata:
                self.memory.store("trajectories", result.metadata["trajectories"])
            elif tool_name == "seed_planning":
                if "optimal_plan" in result.metadata:
                    self.memory.store("seed_positions", result.metadata["optimal_plan"])
                    self.memory.store("total_seeds", result.metadata.get("total_seeds", 0))
                if "dose_distribution" in result.metadata:
                    self.memory.store("dose_distribution", result.metadata["dose_distribution"])
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

        self.memory.log_tool_call(tool_name, params, result)

        if progress_callback:
            progress_callback(f"{tool_name} completed", 100)

        return result

    # --- Tool Validation & Recovery ---
    # Validates tool results and automatically recovers from failures.
    # This is the core mechanism for reducing tool execution failures.

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
        "ctv_segmentation": [
            {"param_overrides": {"tumor_type": None}, "note": "Retry with auto-detect tumor type"},
        ],
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
                        from tool_factory import ToolResult
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

    def _store_tool_result(self, tool_name: str, result):
        """Store tool result in memory based on tool type."""
        if not result.success:
            print(f"[STORE] Skipping {tool_name}: not successful")
            return
        meta = result.metadata or {}
        print(f"[STORE] {tool_name}: metadata keys={list(meta.keys())}")
        ct_image = self.memory.retrieve("ct_image")
        if tool_name == "ctv_segmentation" and "ctv_array" in meta:
            print(f"[STORE] Storing ctv_array, shape={meta['ctv_array'].shape if hasattr(meta['ctv_array'], 'shape') else 'N/A'}, ct_image={'exists' if ct_image is not None else 'None'}")
            if ct_image is not None:
                self._store_label_with_metadata(meta["ctv_array"], ct_image, "ctv_array")
            else:
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
            if meta.get("tumor_type"):
                self.memory.store("tumor_type_used", meta["tumor_type"])
            logger.info(f"[STORE] ctv_segmentation: ctv_voxels={_cv}, ctv_volume_mm3={_cvm3}, tumor_type={meta.get('tumor_type')}")
        elif tool_name == "oar_segmentation":
            if "oar_array" in meta:
                if ct_image is not None:
                    self._store_label_with_metadata(meta["oar_array"], ct_image, "oar_array")
                else:
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
        elif tool_name == "seed_planning":
            if "optimal_plan" in meta:
                self.memory.store("seed_plan", meta["optimal_plan"])
            if "dose_distribution" in meta:
                self.memory.store("dose_distribution", meta["dose_distribution"])
        elif tool_name == "trajectory_planning" and "trajectories" in meta:
            self.memory.store("trajectories", meta["trajectories"])

    @staticmethod
    def _format_tool_result(tool_name: str, result, lang: str = "en") -> str:
        """Format tool result for display. Uses result.display, then auto-generates from metadata."""
        return ToolResultPipeline.format(tool_name, result, lang)

    # --- Analysis code template (used by direct execution) ---
    _ANALYSIS_CODE_TEMPLATE = """
import nibabel as nib
import numpy as np
import json

ct = nib.load('{ct_path}')
data = ct.get_fdata()
spacing = ct.header.get_zooms()

# Compute tissue distribution
total = data.size
tissues = []
for name, lo, hi in [("Air", -9999, -900), ("Fat", -900, -30), ("Soft tissue", -30, 200), ("Muscle/organ", 200, 400), ("Bone", 400, 9999)]:
    pct = np.sum((data >= lo) & (data < hi)) / total * 100
    tissues.append({{"name": name, "range": f"{{lo}}~{{hi}} HU" if lo > -9009 else f"< {{hi}} HU", "pct": round(pct, 1)}})

result = {{
    "dimensions": list(data.shape),
    "voxel_size": [round(float(s), 2) for s in spacing],
    "scan_range_cm": [round(data.shape[i]*float(spacing[i])/10, 1) for i in range(3)],
    "hu_range": [int(data.min()), int(data.max())],
    "mean_hu": round(float(data.mean()), 1),
    "tissues": tissues,
}}
print(json.dumps(result))
"""

    def _detect_tool_request(self, message: str) -> Optional[List[Dict]]:
        """Detect explicit tool requests. Returns tool calls in user-specified order, or None.
        Bypasses LLM to prevent unnecessary questions or wrong skill chains."""
        msg = message.strip().lower()
        ct_path = self.memory.retrieve("ct_path") or ""
        if not ct_path:
            ct_path = (self.memory.get_ui_state() or {}).get("ct_path", "")

        # Find action keywords and their positions to preserve user's intended order
        ACTION_PATTERNS = [
            (r'(分析|analyze)', 'analyze'),
            (r'(ctv|靶区|临床靶区|病灶|肿瘤|tumor|lesion).{0,8}(分割|segment)', 'segment_ctv'),
            (r'(分割|segment).{0,8}(ctv|靶区|临床靶区|病灶|肿瘤|tumor|lesion)', 'segment_ctv'),
            (r'(oar|危及器官|器官).{0,5}(分割|segment)', 'segment_oar'),
            (r'(分割|segment).{0,5}(oar|危及器官|器官)', 'segment_oar'),
            (r'(剂量|dose|计算剂量)', 'dose'),
            (r'(切换|switch).{0,10}(viewer|查看|浏览|视图)', 'ui:panel:viewers'),
            (r'(切换|switch).{0,10}(input|输入)', 'ui:panel:input'),
            (r'(切换|switch).{0,10}(metrics|指标)', 'ui:panel:metrics'),
        ]
        action_positions = []
        matched_spans = []
        for pattern, action in ACTION_PATTERNS:
            for match in re.finditer(pattern, msg, re.IGNORECASE):
                start, end = match.span()
                overlaps = any(not (end <= s or start >= e) for s, e in matched_spans)
                if not overlaps:
                    action_positions.append((start, action))
                    matched_spans.append((start, end))

        # Deduplicate, keeping first occurrence of each action
        seen = set()
        ordered_actions = []
        for pos, action in sorted(action_positions):
            if action not in seen:
                seen.add(action)
                ordered_actions.append(action)

        # If no specific segment found but generic "segment" is present, add segment_all
        has_specific_seg = 'segment_ctv' in seen or 'segment_oar' in seen
        if not has_specific_seg:
            for match in re.finditer(r'(分割|segment|再分)', msg, re.IGNORECASE):
                start, end = match.span()
                overlaps = any(not (end <= s or start >= e) for s, e in matched_spans)
                if not overlaps:
                    ordered_actions.append('segment_all')
                    break

        # Handle "分割CTV和OAR" / "分割靶区和器官" — detect both from a single "segment" action
        if has_specific_seg:
            has_ctv = 'segment_ctv' in seen
            has_oar = 'segment_oar' in seen
            # If we found CTV but not OAR, check if OAR keywords appear in the message
            if has_ctv and not has_oar:
                if re.search(r'(oar|危及器官|器官)', msg, re.IGNORECASE):
                    ordered_actions.append('segment_oar')
            elif has_oar and not has_ctv:
                if re.search(r'(ctv|靶区|临床靶区)', msg, re.IGNORECASE):
                    ordered_actions.append('segment_ctv')

        if not ordered_actions:
            return None

        # Map actions to tool calls
        tools = []
        for action in ordered_actions:
            # UI control actions
            if action.startswith('ui:'):
                _, target, value = action.split(':')
                tools.append({"id": f"tool_ui_{target}_{value}", "tool": "ui_controller",
                              "params": {"actions": [{"target": target, "command": "switch", "value": value}]}})
                continue

            if action == 'analyze' and ct_path:
                code = self._ANALYSIS_CODE_TEMPLATE.format(ct_path=ct_path)
                tools.append({"id": "tool_direct_analysis", "tool": "code_executor",
                              "params": {"code": code, "description": "Analyze CT image"}})
            elif action == 'segment_ctv' and ct_path:
                tools.append({"id": "tool_direct_ctv", "tool": "ctv_segmentation", "params": {"image_path": ct_path}})
            elif action == 'segment_oar' and ct_path:
                tools.append({"id": "tool_direct_oar", "tool": "oar_segmentation", "params": {"image_path": ct_path}})
            elif action == 'segment_all' and ct_path:
                tools.append({"id": "tool_direct_ctv", "tool": "ctv_segmentation", "params": {"image_path": ct_path}})
                tools.append({"id": "tool_direct_oar", "tool": "oar_segmentation", "params": {"image_path": ct_path}})
            elif action == 'dose' and ct_path:
                tools.append({"id": "tool_direct_dose", "tool": "dose_engine", "params": {}})

        return tools or None

    def _execute_direct_tools(self, tools: List[Dict], steps: List, step_id_ref: List[int], yield_event=None):
        """Execute tools with validation and recovery. Shared by streaming and non-streaming paths.

        Args:
            yield_event: Optional callback(step_data) called after each tool completes,
                         enabling incremental UI updates in streaming mode.
        """
        _lang = self.memory.user_lang
        for tc in tools:
            step_id_ref[0] += 1
            tool_step = {
                "id": step_id_ref[0], "type": "tool", "title": f"Direct: {tc['tool']}",
                "content": json.dumps(tc['params'], default=str)[:200],
                "status": "pending", "tool": tc['tool'], "params": tc['params'],
            }
            steps.append(tool_step)
            # Yield pending step for streaming UI
            if yield_event:
                yield_event(tool_step)
            try:
                result = self._validate_and_execute(tc['tool'], tc['params'])
                tool_step["status"] = "done"
                tool_step["result"] = self._format_tool_result(tc['tool'], result, lang=_lang)
                tool_step["metadata"] = result.metadata if result.success else {}
                tool_step["data"] = result.data if result.success else {}
                if result.success:
                    self._store_tool_result(tc['tool'], result)
                # Store tool call + result in conversation for context persistence
                self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                result_summary = result.message[:500] if result.success else f"Error: {result.error}"
                self.memory.add_message("user", f"[Tool result: {result_summary}]")
            except Exception as e:
                tool_step["status"] = "error"
                tool_step["result"] = str(e)
                logger.error(f"Direct tool failed: {tc['tool']}: {e}")
                self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                self.memory.add_message("user", f"[Tool result: Error: {str(e)[:200]}]")
            # Yield completed step for streaming UI (enables incremental viewer updates)
            if yield_event:
                yield_event(tool_step)

        # Build raw results summary, then synthesize with LLM
        raw_results = self._build_direct_response(steps, _lang)
        user_msg = ""
        for msg in reversed(self.memory.conversation):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break
        query_type = self._classify_query_type(user_msg)
        response = self._synthesize_with_llm(raw_results, steps, _lang, user_msg, query_type)

        # Quality review with feedback loop
        if self.multi_agent_wrapper and self.multi_agent_wrapper.enabled:
            _needs_review = any(
                tc.get('tool') in ["planning_pipeline", "seed_planning", "dose_evaluation"]
                for tc in tools
            )
            if _needs_review:
                _MAX_RETRIES = 3
                for _retry in range(_MAX_RETRIES):
                    try:
                        import asyncio
                        loop = asyncio.new_event_loop()
                        review_result = loop.run_until_complete(
                            self.multi_agent_wrapper.review_output("treatment_plan", {
                                "dose_metrics": self.memory.retrieve("dose_metrics", {}),
                                "plan_info": {
                                    "total_seeds": self.memory.retrieve("total_seeds", 0),
                                    "num_trajectories": self.memory.retrieve("num_trajectories", 0),
                                },
                                "plan_config": self.memory.retrieve("plan_config", {}),
                            }, lang=_lang)
                        )
                        loop.close()
                        if not review_result or review_result.get("passed"):
                            break
                        if _retry < _MAX_RETRIES - 1:
                            _concerns = []
                            for r in review_result.get("reviews", []):
                                _concerns.extend(r.get("concerns", []))
                            _concerns_text = "; ".join(_concerns) or review_result.get("display_text", "")
                            _retry_tools = self._detect_tool_request(
                                user_msg + f"\n\n[Quality review feedback: {_concerns_text}]"
                            )
                            if _retry_tools:
                                self._execute_direct_tools(_retry_tools, steps, step_id_ref)
                    except Exception as e:
                        logger.warning(f"Review retry {_retry + 1} failed: {e}")
                        break

        return response

    def _build_direct_response(self, steps: List, lang: str) -> str:
        """Build structured response. Delegates to ToolResultPipeline."""
        return ToolResultPipeline.format_steps(steps, lang)

    # BUG FIX 2026-06-16 (LLM response still brief): server-side
    # generation of a comprehensive planning report. Reads metrics
    # directly from memory and assembles a 10-section markdown
    # report — guaranteed to be detailed regardless of LLM behavior.
    def _build_planning_report(self, lang: str, steps: List = None) -> str:
        """Build a comprehensive planning report directly from
        stored metrics. Used to bypass the LLM synthesis when the
        user explicitly runs a planning pipeline, because the LLM
        was producing brief 5-row tables ignoring the detailed
        template prompt.
        """
        is_zh = lang == "zh"
        # Pull all the relevant metrics from memory. BUG FIX 2026-06-17
        # (empty report): the 'metrics' key holds the FLAT dict that
        # dose_evaluation populates. But for some planning modes
        # (e.g. rl) the 'metrics' key is not populated, while
        # 'dose_metrics' (raw nested dict) IS stored. Fall back to
        # dose_metrics if metrics is empty.
        metrics = self.memory.retrieve("metrics", {}) or {}
        if not metrics:
            dose_metrics_raw = self.memory.retrieve("dose_metrics", {}) or {}
            # If dose_metrics is the nested {metrics: {CTV: {...}, oars: ...}, ...}
            # shape, pull the target sub-dict (CTV) to the top level.
            if isinstance(dose_metrics_raw, dict) and "metrics" in dose_metrics_raw:
                nested = dose_metrics_raw.get("metrics", {}) or {}
                ctv_sub = nested.get("CTV", {}) if isinstance(nested, dict) else {}
                if ctv_sub:
                    metrics = dict(dose_metrics_raw)
                    metrics.update(ctv_sub)
                else:
                    metrics = dose_metrics_raw
            else:
                metrics = dose_metrics_raw
        total_seeds = self.memory.retrieve("total_seeds", 0) or 0
        num_traj = self.memory.retrieve("num_trajectories", 0) or 0
        ctv_voxels = self.memory.retrieve("ctv_voxels", 0) or 0
        logger.info(f"[_build_planning_report] ctv_voxels={ctv_voxels}, ctv_array={'exists' if self.memory.retrieve('ctv_array') is not None else 'None'}, tumor_type_used='{self.memory.retrieve('tumor_type_used', '')}'")
        # Fallback: compute from ctv_array if not stored directly
        if not ctv_voxels:
            ctv_array = self.memory.retrieve("ctv_array")
            if ctv_array is not None:
                try:
                    import numpy as _np
                    ctv_voxels = int(_np.sum(_np.asarray(ctv_array) > 0))
                    self.memory.store("ctv_voxels", ctv_voxels)
                except Exception:
                    pass
        tumor_type = self.memory.retrieve("tumor_type_used", "")
        oar_array = self.memory.retrieve("oar_array")
        organ_names = self.memory.retrieve("organ_names", {}) or {}

        # Compute CTV volume in cm³ — prefer pre-computed value
        ctv_vol_cm3 = None
        _cvm3 = self.memory.retrieve("ctv_volume_mm3")
        if _cvm3:
            ctv_vol_cm3 = _cvm3 / 1000.0
        elif ctv_voxels:
            spacing = self.memory.retrieve("ct_spacing") or [0.6836, 0.6836, 5]
            sx, sy, sz = spacing[0], spacing[1], spacing[2]
            vol_mm3 = ctv_voxels * sx * sy * sz
            ctv_vol_cm3 = vol_mm3 / 1000.0
            sx, sy, sz = spacing[0], spacing[1], spacing[2]
            vol_mm3 = ctv_voxels * sx * sy * sz
            ctv_vol_cm3 = vol_mm3 / 1000.0

        # Extract prescription
        rx_gy = 120  # default
        try:
            if self.memory.retrieve("plan_config"):
                rx_gy = self.memory.retrieve("plan_config", {}).get("prescription_dose", 1.0) * 120
        except Exception:
            pass

        # BUG FIX 2026-06-17 (None format): wrap metric reads with
        # `or 0` so None values don't crash :.1f / :.0f format specs.
        # Earlier code used metrics.get(k, 0) which returns None
        # when the key exists but value is None — the format spec
        # then raised "unsupported format string passed to NoneType".
        #
        # BUG FIX 2026-06-17 (plan_score double scaling): plan_score
        # is already on a 0-100 scale (e.g. 92.71 for a great plan).
        # Multiplying by 100 then formatting as :.0f yields 9271.
        # Section 5 displays it correctly as 93/100 (no scaling).
        # The workflow summary was incorrectly doing `*100` again.
        v100 = (metrics.get("v100") or 0) * 100
        v150 = (metrics.get("v150") or 0) * 100
        v200 = (metrics.get("v200") or 0) * 100
        d90 = metrics.get("d90") or 0
        dmean = metrics.get("dmean") or 0
        d2 = metrics.get("d2") or 0
        ci = metrics.get("ci") or 0
        hi = metrics.get("hi") or 0
        ps = metrics.get("plan_score") or 0
        v100_frac = metrics.get("v100") or 0
        d90_gy = metrics.get("d90") or 0
        # ps is already 0-100, do not multiply again
        ps_pct = ps

        # Helper for zh/en label lookup
        def L(zh, en):
            return zh if is_zh else en

        lines = []
        # Section 1: Workflow Summary
        lines.append(f"## {L('1. 流程总结', '1. Workflow Summary')}")
        lines.append("")
        # Find CTV/OAR/planning tool names from steps
        tools_run = []
        if steps:
            for s in steps:
                if s.get("tool") in ("ctv_segmentation", "oar_segmentation",
                                       "planning_pipeline", "trajectory_planning"):
                    tools_run.append(s["tool"])
        tools_summary = ", ".join(set(tools_run)) if tools_run else "ctv_segmentation, planning_pipeline"
        lines.append(L(
            f"已完成放射性粒子植入规划全流程,执行工具:{tools_summary}。靶区覆盖率V100达{v100_frac*100:.1f}%,D90为{d90_gy:.2f} Gy,规划评分{ps_pct:.0f}/100。",
            f"Brachytherapy planning pipeline completed. Tools executed: {tools_summary}. CTV coverage V100 = {v100_frac*100:.1f}%, D90 = {d90_gy:.2f} Gy, plan score = {ps_pct:.0f}/100."
        ))
        lines.append("")

        # Section 2: CTV Segmentation
        ctv_vol_str = f"{ctv_vol_cm3:.2f} cm³" if ctv_vol_cm3 else "N/A"
        lines.append(f"## {L('2. CTV 靶区分割', '2. CTV Segmentation')}")
        lines.append("")
        lines.append(f"- **{L('肿瘤体积', 'Tumor volume')}**: {ctv_vol_str} ({ctv_voxels:,} {L('体素', 'voxels')})")
        lines.append(f"- **{L('解剖位置', 'Anatomical location')}**: {tumor_type or L('胰腺', 'pancreas')}")
        lines.append(f"- **{L('分割算法', 'Segmentation algorithm')}**: nnUNet ({tumor_type or 'nnunet_pancreatic'})")
        lines.append("")

        # Section 3: OAR Segmentation
        lines.append(f"## {L('3. OAR 危及器官分割', '3. OAR Segmentation')}")
        lines.append("")
        oar_count = len(organ_names) if organ_names else 0
        lines.append(f"- **{L('OAR 总数', 'Total OAR count')}**: {oar_count}")
        # Show the 8 most clinically relevant OARs
        clinical_oars = ["duodenum", "small_bowel", "colon", "stomach", "liver",
                         "kidney", "spinal_cord", "pancreas", "spleen", "adrenal_gland"]
        relevant = [name for name in clinical_oars if name in organ_names][:8]
        if relevant:
            lines.append(f"- **{L('临床相关 OAR', 'Clinically relevant OARs detected')}**: {', '.join(relevant)}")
        lines.append("")

        # Section 4: Trajectory & Seed Plan
        lines.append(f"## {L('4. 轨迹与粒子计划', '4. Trajectory & Seed Plan')}")
        lines.append("")
        lines.append(f"- **{L('轨迹数', 'Trajectories generated')}**: {num_traj}")
        lines.append(f"- **{L('粒子数', 'Seeds placed')}**: {total_seeds}")
        if ctv_vol_cm3 and total_seeds:
            density = total_seeds / ctv_vol_cm3
            lines.append(f"- **{L('粒子密度', 'Seed density')}**: {density:.2f} {L('颗 / cm³', 'seeds/cm³')}")
        lines.append(f"- **{L('规划模式', 'Planning mode')}**: rule_based")
        lines.append("")

        # Section 5: Dose Distribution
        lines.append(f"## {L('5. 剂量分布', '5. Dose Distribution')}")
        lines.append("")
        lines.append(f"- **{L('处方剂量', 'Prescription dose')}**: {rx_gy:.1f} Gy")
        lines.append(f"- **V100 / V150 / V200**: {v100:.1f}% / {v150:.1f}% / {v200:.1f}%")
        lines.append(f"- **D90 / Dmean / D2**: {d90:.2f} / {dmean:.2f} / {d2:.2f} Gy")
        lines.append(f"- **{L('适形指数 CI', 'Conformity Index (CI)')}**: {ci:.3f}")
        lines.append(f"- **{L('均匀指数 HI', 'Homogeneity Index (HI)')}**: {hi:.3f}")
        lines.append(f"- **{L('规划评分', 'Plan Score')}**: {ps:.0f}/100")
        lines.append("")

        # Section 6: OAR Dose Analysis (table)
        lines.append(f"## {L('6. OAR 剂量分析', '6. OAR Dose Analysis')}")
        lines.append("")
        oar_metrics = metrics.get('oar_metrics', {}) or {}
        if oar_metrics:
            lines.append(f"| {L('危及器官', 'OAR')} | {L('最大剂量 (Gy)', 'Dmax (Gy)')} | D2cc (Gy) | D1cc (Gy) | {L('状态', 'Status')} |")
            lines.append("|" + "|".join(["---"] * 5) + "|")
            for organ, om in sorted(oar_metrics.items(), key=lambda kv: (kv[1].get('dmax') or 0), reverse=True):
                dmax = om.get('dmax') or 0
                d2cc = om.get('d2cc') or 0
                d1cc = om.get('d1cc') or 0
                # Status thresholds (clinical brachy practice):
                # - EXCEEDS: Dmax > 2xRx OR D2cc > 1xRx (critical OARs)
                #   Note: in brachy, a D2cc > 1xRx for duodenum/small_bowel
                #   is a real problem because they're serial organs.
                # - WARN:    Dmax > 1.5xRx OR D2cc > 0.75xRx
                # - OK:      otherwise
                if dmax > 2 * rx_gy or d2cc > rx_gy:
                    status = L('超限', 'EXCEEDS')
                elif dmax > 1.5 * rx_gy or d2cc > 0.75 * rx_gy:
                    status = L('警告', 'WARN')
                else:
                    status = L('正常', 'OK')
                lines.append(f"| {organ} | {dmax:.2f} | {d2cc:.2f} | {d1cc:.2f} | {status} |")
        else:
            lines.append(L('(剂量评估未返回 OAR 指标)', '(No OAR metrics returned by dose evaluation)'))
        lines.append("")

        # Section 7: Flagged Issues
        lines.append(f"## {L('7. 标记问题', '7. Flagged Issues')}")
        lines.append("")
        issues_found = False
        if oar_metrics:
            for organ, om in sorted(oar_metrics.items(), key=lambda kv: (kv[1].get('dmax') or 0), reverse=True):
                dmax = om.get('dmax') or 0
                d2cc = om.get('d2cc') or 0
                if dmax > 2 * rx_gy or d2cc > rx_gy:
                    lines.append(f"- **{L('超限', 'EXCEEDS')}**: {organ} {L('最大剂量', 'Dmax')} {dmax:.2f} Gy, D2cc {d2cc:.2f} Gy — {L('需重点关注,可考虑降低处方或重新规划粒子分布', 'requires attention, consider reducing prescription or replanning seed distribution')}")
                    issues_found = True
                elif dmax > 1.5 * rx_gy or d2cc > 0.75 * rx_gy:
                    lines.append(f"- **{L('警告', 'WARN')}**: {organ} {L('最大剂量', 'Dmax')} {dmax:.2f} Gy > 1.5×Rx ({1.5*rx_gy:.1f} Gy) — {L('接近耐受上限,需评估临床意义', 'near tolerance limit, evaluate clinical relevance')}")
                    issues_found = True
        if v200 > 30:
            lines.append(f"- **{L('热点', 'Hot spot')}**: V200={v200:.1f}% {L('超过 30%,提示剂量分布欠均匀', 'exceeds 30%, indicating non-uniform dose distribution')}")
            issues_found = True
        if not issues_found:
            lines.append(L('所有指标均在临床容许范围内,无需额外关注。', 'All metrics are within clinical tolerance — no action required.'))
        lines.append("")

        # Section 8: Clinical Recommendations
        lines.append(f"## {L('8. 临床建议', '8. Clinical Recommendations')}")
        lines.append("")
        lines.append(f"- {L('请放射肿瘤科医师审核本计划并签署批准', 'Have a radiation oncologist review and sign off on this plan')}")
        lines.append(f"- {L('使用独立剂量算法进行二次校验(蒙特卡罗或 TG-43)', 'Perform secondary dose verification using an independent algorithm (Monte Carlo or TG-43)')}")
        if oar_metrics:
            exceed_count = sum(1 for om in oar_metrics.values() if (om.get('dmax') or 0) > 2 * rx_gy)
            if exceed_count > 0:
                lines.append(f"- {L(f'重点关注 {exceed_count} 个超限 OAR,可在 Report 面板中调整粒子分布', f'Focus on the {exceed_count} OAR(s) exceeding limits; consider seed repositioning in the Report panel')}")
        lines.append(f"- {L('术后 1 个月复查 CT,评估粒子迁移和剂量验证', 'Schedule a 1-month follow-up CT to assess seed migration and dose verification')}")
        lines.append("")

        # Section 9: References
        lines.append(f"## {L('9. 参考文献', '9. References')}")
        lines.append("")
        lines.append(f"- [TG-43 AAPM](https://www.aapm.org/pubs/reports/RPT_268.pdf) — {L('放射性粒子源剂量学基础', 'Brachytherapy source dosimetry foundation')}")
        lines.append(f"- [GEC-ESTRO](https://www.estro.org/Science/Guidelines) — {L('欧洲近距离治疗指南', 'European brachytherapy guidelines')}")
        lines.append(f"- [ICRU Report 89](https://www.icru.org/report/icru-report-89-prescribing-recording-and-reporting-photon-beam-therapy-2nd-edition) — {L('光子束治疗处方与记录', 'Prescribing, recording, and reporting photon beam therapy')}")
        lines.append(f"- [NCCN Guidelines](https://www.nccn.org/guidelines) — {L('各癌种临床实践指南', 'Clinical practice guidelines by cancer type')}")
        lines.append("")

        return "\n".join(lines)

    def _synthesize_with_llm(self, raw_results: str, steps: List, lang: str, user_message: str = "", query_type: str = "knowledge") -> str:
        """Synthesize tool results. Delegates to ToolResultPipeline."""
        formatted = []
        for s in steps:
            if s.get("type") == "tool" and s.get("status") == "done":
                meta = s.get("metadata", {})
                data = s.get("data", {})
                # Extract source URLs from data or metadata
                source_urls = []
                if isinstance(data, dict):
                    sources = data.get("sources", [])
                    if isinstance(sources, list):
                        source_urls = [u for u in sources if u]
                if not source_urls and isinstance(meta, dict):
                    sources = meta.get("sources", [])
                    if isinstance(sources, list):
                        source_urls = [u for u in sources if u]
                formatted.append({
                    "tool": s.get("tool", ""),
                    "display": s.get("result", ""),
                    "source_url": source_urls[0] if source_urls else "",
                    "all_source_urls": source_urls,
                })
        return ToolResultPipeline.synthesize(formatted, user_message, self.brain_router, lang, query_type)

    # ============================================================
    # Information Reliability Hierarchy
    # ============================================================
    # Query Type → Strategy → Source Attribution
    #
    # ┌──────────────┬──────────────────────────────────────┐
    # │  Query Type  │  Strategy                            │
    # ├──────────────┼──────────────────────────────────────┤
    # │  realtime    │  MUST search. Use results + source.  │
    # │  knowledge   │  LLM first, search to verify/suppl.  │
    # │  analysis    │  LLM reasoning. Tag "AI analysis".   │
    # │  system      │  Read memory/tool_results. No search.│
    # └──────────────┴──────────────────────────────────────┘

    # Patterns for each query type
    _REALTIME_PATTERNS = [
        # Impact factors, journal metrics
        (r'(影响因子|impact\s*factor|cite\s*score|JCR|分区)', 'journal_metric'),
        # Financial data
        (r'(股价|市值|行情|汇率|利率|stock|price)', 'financial'),
        # Weather
        (r'(天气|气温|下雨|weather|temperature)', 'weather'),
        # Time/date
        (r'(今天|今日|现在|当前|几点|时间|日期|current.*time|current.*date)', 'datetime'),
        # News
        (r'(最新新闻|今日新闻|latest.*news|headline)', 'news'),
        # Rankings, scores
        (r'(排名|排行|ranking|score|得分)', 'ranking'),
        # Version numbers, releases
        (r'(最新版|最新版本|latest.*version|release)', 'version'),
        # Statistics that change
        (r'(发病率|患病率|死亡率|mortality|prevalence|incidence)', 'epidemiology'),
    ]

    _KNOWLEDGE_PATTERNS = [
        # Medical knowledge
        (r'(什么是|是什么|定义|definition|explain|介绍|原理|mechanism)', 'definition'),
        # Guidelines, protocols
        (r'(指南|规范|protocol|guideline|standard|TG-\d+|AAPM|ABS|ESTRO)', 'guideline'),
        # Dose, technique
        (r'(剂量|dose|technique|方法|method|procedure)', 'technique'),
        # Anatomy
        (r'(解剖|anatomy|organ|器官|structure)', 'anatomy'),
        # Drug, treatment
        (r'(药物|治疗|treatment|therapy|drug)', 'treatment'),
    ]

    _ANALYSIS_PATTERNS = [
        # Comparison
        (r'(比较|对比|compare|versus|vs|哪个好|which.*better)', 'comparison'),
        # Opinion, recommendation
        (r'(建议|推荐|recommend|opinion|观点|应该)', 'recommendation'),
        # Pros/cons
        (r'(优缺点|利弊|pros.*cons|advantage|disadvantage)', 'evaluation'),
    ]

    _SYSTEM_PATTERNS = [
        # Internal state
        (r'(刚才|之前|上一|已.*分割|已.*分析|当前.*状态|what.*done)', 'state'),
        # List/show results
        (r'(列.*表|显示.*结果|show.*result|list|display)', 'display'),
        # File/system operations
        (r'(保存|导出|加载|save|export|load|upload)', 'file_op'),
        # Tool operations (analyze image, segment, etc.)
        (r'(分析.*图像|分割.*图像|analyze.*image|segment.*image|计算.*剂量)', 'tool_op'),
    ]

    def _classify_query_type(self, message: str) -> str:
        """Classify query into: realtime, knowledge, analysis, system.

        Returns the query type string for strategy selection.
        Priority: system > realtime > knowledge > analysis
        """
        msg = message.strip().lower()

        # Check system patterns first (highest priority for internal queries)
        for pattern, _ in self._SYSTEM_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return 'system'

        # Check realtime patterns (must search, can't use training data)
        for pattern, _ in self._REALTIME_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return 'realtime'

        # Check knowledge patterns (LLM + search verification)
        # BEFORE analysis — because "recommendation" in guideline context is knowledge, not opinion
        for pattern, _ in self._KNOWLEDGE_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return 'knowledge'

        # Check analysis patterns (LLM reasoning)
        for pattern, _ in self._ANALYSIS_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return 'analysis'

        # Default: let LLM decide
        return 'knowledge'

    @staticmethod
    def _get_source_attribution(query_type: str, has_search: bool, lang: str = "en", search_year: str = "") -> str:
        """Generate source attribution text based on query type and data source."""
        if lang == "zh":
            if query_type == 'realtime':
                if has_search:
                    return f"📊 数据来源: 网络搜索 ({search_year})" if search_year else "📊 数据来源: 网络搜索"
                else:
                    return "⚠️ 注意: 未找到最新数据，以下信息可能已过时"
            elif query_type == 'knowledge':
                return "📚 数据来源: AI知识库 + 网络验证" if has_search else "📚 数据来源: AI知识库（未经实时验证）"
            elif query_type == 'analysis':
                return "💡 数据来源: AI分析（仅供参考）"
            elif query_type == 'system':
                return "📋 数据来源: 系统内部数据"
        else:
            if query_type == 'realtime':
                if has_search:
                    return f"📊 Source: Web search ({search_year})" if search_year else "📊 Source: Web search"
                else:
                    return "⚠️ Note: Latest data not found, information may be outdated"
            elif query_type == 'knowledge':
                return "📚 Source: AI knowledge + web verification" if has_search else "📚 Source: AI knowledge (not verified by search)"
            elif query_type == 'analysis':
                return "💡 Source: AI analysis (for reference only)"
            elif query_type == 'system':
                return "📋 Source: Internal system data"
        return ""

    # Tumor type → CTV tool mapping
    _TUMOR_TYPE_MAP = {
        # English names — pancreatic uses nnUNet (more accurate)
        "pancreatic_tumor": "nnunet_pancreatic",
        "pancreatic": "nnunet_pancreatic",
        "pancreas": "nnunet_pancreatic",
        "liver_tumor": "voco_liver",
        "liver": "voco_liver",
        "kidney_tumor": "voco_kidney",
        "kidney": "voco_kidney",
        "colon_tumor": "voco_colon",
        "colon": "voco_colon",
        "lung_tumor": "voco_lung",
        "lung": "voco_lung",
        "brain_tumor": "voco_brats21",
        "brain": "voco_brats21",
        "pulmonary_embolism": "voco_fumpe",
        "covid": "voco_covid",
        "aorta": "voco_aorta",
        # Chinese names — pancreatic uses nnUNet
        "胰腺癌": "nnunet_pancreatic",
        "胰腺肿瘤": "nnunet_pancreatic",
        "胰腺": "nnunet_pancreatic",
        "肝癌": "voco_liver",
        "肝肿瘤": "voco_liver",
        "肝脏": "voco_liver",
        "肾癌": "voco_kidney",
        "肾肿瘤": "voco_kidney",
        "肾脏": "voco_kidney",
        "结肠癌": "voco_colon",
        "结肠": "voco_colon",
        "肺癌": "voco_lung",
        "肺部": "voco_lung",
        "脑肿瘤": "voco_brats21",
        "脑癌": "voco_brats21",
        "肺栓塞": "voco_fumpe",
        "新冠": "voco_covid",
        "主动脉": "voco_aorta",
        "胰腺癌患者": "voco_pancreatic",
        "肝癌患者": "voco_liver",
        "肾癌患者": "voco_kidney",
        "肺癌患者": "voco_lung",
        "结肠癌患者": "voco_colon",
        "脑肿瘤患者": "voco_brats21",
    }

    def _map_tumor_type(self, tumor_type: str) -> str:
        """Map user-provided tumor type to VoCo tool name."""
        if tumor_type is None:
            return "voco_pancreatic"
        # Already a valid VoCo tool name
        if tumor_type.startswith("voco_"):
            return tumor_type
        # Look up in mapping
        mapped = self._TUMOR_TYPE_MAP.get(tumor_type.lower())
        if mapped:
            return mapped
        # Partial match for Chinese
        for key, val in self._TUMOR_TYPE_MAP.items():
            if key in tumor_type or tumor_type in key:
                return val
        # Default to pancreatic
        logger.warning(f"Unknown tumor_type '{tumor_type}', defaulting to voco_pancreatic")
        return "voco_pancreatic"

    def _detect_tumor_type_from_message(self, message: str) -> Optional[str]:
        """Detect tumor type from user message for CTV segmentation routing."""
        msg = message.lower()
        # Check each keyword in the mapping
        for keyword, tool_name in self._TUMOR_TYPE_MAP.items():
            if keyword in msg:
                return tool_name
        return None

    def _detect_realtime_query(self, message: str) -> Optional[str]:
        """Detect if the message requires a real-time web search.
        Returns a search query string if detected, None otherwise.
        The query is optimized for Bing/Baidu (not PubMed)."""
        msg = message.strip().lower()
        # Patterns that require real-time search
        # Weather queries are handled by specialized engine — just detect the intent
        realtime_patterns = [
            (r'(今天|今日|明天|昨天|本周|目前|当前|现在).*(天气|气温|温度|下雨|晴)', True),
            (r'(天气|气温|温度).*(如何|怎么样|怎样|多少|预报)', True),
            (r'(weather|temperature|forecast)', True),
            (r'(现在|当前|今天|几点|时间|日期)', False),
            (r'(what time|current time|what date)', False),
            (r'(最新|最近|今日|今天的).*(新闻|消息|头条)', False),
            (r'(news|headline|latest news)', False),
            (r'(nba|NBA|篮球).*(总决赛|季后赛|比赛|赛事|结果)', False),
            (r'(足球|世界杯|欧冠|英超|中超).*(比赛|赛事|结果|比分)', False),
            (r'(股价|股票|市值|行情)', False),
            (r'(汇率|美元|欧元|人民币)', False),
            (r'(疫情|新冠|病例)', False),
        ]
        for pattern, is_weather in realtime_patterns:
            if re.search(pattern, msg, re.IGNORECASE):
                if is_weather:
                    # Weather: pass original message, specialized engine extracts city
                    return message.strip()
                # Non-weather: generate a search query from the message
                return message.strip()
        return None

    def _normalize_tool_params(self, tool_calls: List[Dict]) -> List[Dict]:
        """Normalize tool call parameters (alias mapping, validation).

        Returns filtered list of valid tool calls. Invalid ones are dropped.
        """
        # INTERNAL FIELDS that the LLM must NEVER inject into a tool call.
        # These are runtime-side-channel values that the agent passes
        # via Python kwargs (e.g. step_callback), not part of the tool
        # input_schema. If the LLM hallucinates one of these field names
        # (M2.7-highspeed has been observed doing this in 2026-06-16
        # when the LLM saw "step_callback" leak through system prompt
        # wording), the literal repr "<function ...>" or "<class ...>"
        # would otherwise be passed to the tool, which would then log
        # it AND potentially inject it back into the next turn's
        # messages, causing an infinite hallucination loop.
        _INTERNAL_FIELDS = {
            "step_callback", "progress_callback", "memory", "agent",
            "_internal", "callback", "context", "ctx", "self_ref",
        }
        # Values that look like Python reprs — only seen when the LLM
        # is mimicking a schema field that doesn't exist. Reject any
        # tool call whose params include such a value.
        _PYTHON_REPR_RE = re.compile(
            r"^<function\s|^<class\s|^<bound method\s|^<module\s|^<object\s"
        )
        valid = []
        for tc in tool_calls:
            tn = tc.get("tool", "")
            p = tc.get("params", {})
            # GENERAL SANITIZATION (applies to ALL tools):
            # 1) Drop any internal-field name from the params dict
            #    silently — the LLM is hallucinating; the tool's
            #    runtime side-channel will set it correctly.
            # 2) Reject the entire tool call if any value looks like
            #    a Python repr (function/class object literal). The
            #    user saw `step_callback=<function ...>` get logged
            #    in 2026-06-16, which is exactly this shape.
            stripped = []
            for k in list(p.keys()):
                v = p[k]
                if k in _INTERNAL_FIELDS:
                    logger.warning(
                        f"Stripped internal field {k!r} from LLM "
                        f"tool call params for {tn!r}"
                    )
                    p.pop(k, None)
                    stripped.append(k)
                elif isinstance(v, str) and _PYTHON_REPR_RE.match(v):
                    logger.warning(
                        f"Refusing tool call {tn!r}: param {k!r} "
                        f"contains a Python repr ({v[:60]!r}) — the "
                        f"LLM is hallucinating a function-valued field"
                    )
                    p = None
                    break
            if p is None:
                continue  # Skip this tool call entirely
            if tn == "filesystem_browser":
                if "dirPath" in p and "path" not in p:
                    p["path"] = p.pop("dirPath")
                if "directory" in p and "path" not in p:
                    p["path"] = p.pop("directory")
                if "action" not in p:
                    p["action"] = "list"
                if p.get("action") not in ("list", "info"):
                    p["action"] = "list"
                if not p.get("path", "").strip():
                    continue
            elif tn == "code_executor":
                for alias in ("script", "python", "command"):
                    if alias in p and "code" not in p:
                        p["code"] = p.pop(alias)
                if not p.get("code", "").strip():
                    continue
            elif tn == "ui_controller":
                # Normalize: LLM may pass target/command at top level instead of inside actions
                if "target" in p and "actions" not in p:
                    p["actions"] = [{"target": p.pop("target"), "command": p.pop("command", "set"), "value": p.pop("value", None)}]
                if not p.get("actions"):
                    logger.warning(f"Dropping ui_controller call with no actions")
                    continue
            elif tn == "web_search":
                # Validate required parameters for web_search
                if not p.get("query", "").strip():
                    logger.warning(f"Dropping web_search call with empty query")
                    continue
            elif tn == "web_access":
                # Validate required parameters for web_access
                if not p.get("action"):
                    logger.warning(f"Dropping web_access call with no action")
                    continue
                if p.get("action") == "search" and not p.get("query", "").strip():
                    logger.warning(f"Dropping web_access search with empty query")
                    continue
                if p.get("action") == "fetch" and not p.get("url", "").strip():
                    logger.warning(f"Dropping web_access fetch with no URL")
                    continue
            elif tn == "web_fetch":
                # Validate required parameters for web_fetch
                if not p.get("url", "").strip():
                    logger.warning(f"Dropping web_fetch call with no URL")
                    continue
            valid.append(tc)
        return valid

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
        ui_state_for_override = self.memory.get_ui_state()
        _no_files_loaded = not AgentMemory.is_ct_loaded(ui_state_for_override)

        # === LANGUAGE DIRECTIVE (top-level) ===
        # The user complained that they typed English but the agent
        # replied in Chinese — a "顶层问题" (top-level issue). We now
        # detect the user's input language and prepend a HIGH-PRIORITY
        # language clause to the system prompt so the LLM is never in
        # doubt about which language to reply in. The detector handles
        # Chinese, English, Japanese, Korean, Russian, Arabic, and
        # falls back to the most recent session language for very
        # short messages (yes / no / do it). See memory/language.py
        # for the full detection rules.
        try:
            from memory.language import detect as _lang_detect, system_prompt_clause as _lang_clause
            _ui_lang = (ui_state_for_override or {}).get("language") or None
            _lang_info = _lang_detect(message, explicit=_ui_lang)
            enhanced_context += "\n" + _lang_clause(_lang_info) + "\n"
            # Persist for next-turn fallback (short messages like
            # "yes" / "do it" inherit the previous language instead
            # of being re-classified as English).
            try:
                self.memory.store("session_language", _lang_info)
            except Exception:
                pass
        except Exception as _e:
            logger.debug(f"language detection failed: {_e}")
        if _no_files_loaded:
            enhanced_context += "\n### ⚠️ OVERRIDE: NO FILES LOADED - LIMITED TOOLS\n"
            enhanced_context += "No CT files are loaded. You MUST answer directly from medical knowledge.\n"
            enhanced_context += "DO NOT call segmentation, dose, seed, or analysis tools.\n"
            enhanced_context += "YOU MAY use report_generator (to generate reports, summaries, DVH analysis, JSON/Markdown export)\n"
            enhanced_context += "YOU MAY use report_auto_fill (in-app Report panel — fills patient/metrics/OAR/narrative from current data)\n"
            enhanced_context += "YOU MAY use clinical_kb (for clinical knowledge queries)\n"
            enhanced_context += "For in-app Report panel requests, call report_auto_fill; for file export, call report_generator.\n"
            enhanced_context += "Provide comprehensive, detailed clinical responses.\n\n"
        if self.enhanced:
            try:
                pre_ctx = self.enhanced.pre_task_hook(message)
                if pre_ctx.get("reflexion_warnings") and not _no_files_loaded:
                    enhanced_context += "\n### Past Experience Warnings\n" + pre_ctx["reflexion_warnings"]
                if pre_ctx.get("matched_sop") and not _no_files_loaded:
                    sop = pre_ctx["matched_sop"]
                    enhanced_context += f"\n### Matched SOP: {sop['name']} (success: {sop['success_rate']:.0%})\n"
                    enhanced_context += f"Recommended chain: {' -> '.join(sop['steps'])}\n"
                    enhanced_context += "NOTE: Only follow when user's message requests this action.\n"
                if pre_ctx.get("crystallized_skill") and not _no_files_loaded:
                    sk = pre_ctx["crystallized_skill"]
                    # Skip skill if it doesn't match what the user actually wants
                    _direct = self._detect_tool_request(message)
                    if _direct:
                        _wanted = {tc["tool"] for tc in _direct}
                        _skill = set(sk['tool_chain'])
                        if not _wanted.intersection(_skill):
                            logger.info(f"Skip skill '{sk['name']}' — user wants {_wanted}, skill has {_skill}")
                        else:
                            enhanced_context += f"\n### Crystallized Skill: {sk['name']} ({sk['success_rate']:.0%})\n"
                            enhanced_context += f"Chain: {' -> '.join(sk['tool_chain'])}\n"
                    else:
                        enhanced_context += f"\n### Crystallized Skill: {sk['name']} ({sk['success_rate']:.0%})\n"
                        enhanced_context += f"Chain: {' -> '.join(sk['tool_chain'])}\n"
                if pre_ctx.get("user_preferences"):
                    prefs = pre_ctx["user_preferences"]
                    if prefs:
                        enhanced_context += f"\n### User Preferences\n"
                        for pid, pv in prefs.items():
                            enhanced_context += f"- {pv['name']}: {pv['value']} (confidence: {pv['confidence']:.2f})\n"
            except Exception as e:
                logger.warning(f"Enhanced pre_task_hook failed (non-critical): {e}")

        ui_state_summary = self.memory.get_ui_state_summary()

        # Classify query type for information reliability strategy
        query_type = self._classify_query_type(message)
        type_labels = {
            'realtime': '⏱️ Real-time data (MUST search, do NOT use training data)',
            'knowledge': '📚 Knowledge (LLM + search verification)',
            'analysis': '💡 Analysis (AI reasoning, tag as "AI analysis")',
            'system': '📋 System (read from memory/tool_results)',
        }
        query_strategy = type_labels.get(query_type, type_labels['knowledge'])
        enhanced_context += f"\n### Query Type: {query_strategy}\n"
        if query_type == 'realtime':
            enhanced_context += "This query requires CURRENT data. You MUST use web_search. Do NOT answer from training data.\n"
        elif query_type == 'system':
            enhanced_context += "This query is about internal state. Read from conversation history or tool_results. Do NOT search.\n"

        import datetime
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            ui_state_summary=ui_state_summary,
            enhanced_context=enhanced_context,
            clean_context=self.memory.get_clean_context(),
            current_date=datetime.datetime.now().strftime("%Y-%m-%d"),
        )

        # Inject relevant prompt modules based on message content
        prompt_modules = get_prompt_modules(message)
        if prompt_modules:
            system_prompt += "\n\n" + prompt_modules

        messages = [
            {"role": "system", "content": system_prompt},
        ]

        # Use smart context manager for intelligent context selection
        if self.memory.smart_context:
            # Get relevant context based on the current message
            smart_context_messages = self.memory.smart_context.get_relevant_context(message)
            for msg in smart_context_messages:
                content = msg.get("content", "")
                role = msg.get("role", "user")
                # Filter out memory artifacts
                if isinstance(content, str):
                    content = re.sub(r'\[Called [^\]]+\]', '', content).strip()
                    content = re.sub(r'\[Tool result: [^\]]*\]', '', content).strip()
                    if not content or len(content) < 10:
                        continue
                # Label as past context so the LLM knows this is prior
                # conversation, NOT the current task. Avoid "historical
                # reference" — the LLM was echoing that phrase back.
                messages.append({"role": role, "content": f"[Earlier conversation — ignore for current task]\n{content}"})
        else:
            # Fallback: use last 12 messages
            msg_history = self.memory.conversation[-12:]
            for msg in msg_history:
                content = msg["content"]
                # Filter out memory artifacts from conversation history
                if isinstance(content, str):
                    content = re.sub(r'\[Called [^\]]+\]', '', content).strip()
                    content = re.sub(r'\[Tool result: [^\]]*\]', '', content).strip()
                    if not content:
                        continue  # Skip empty messages after cleaning
                messages.append({"role": msg["role"], "content": content})

        # CRITICAL: Add the current user message if not already in history
        # This ensures the LLM always has the current query to respond to
        if not messages or messages[-1].get("content") != message:
            # Check if message contains screenshot URL for multimodal content
            user_content = self._build_multimodal_content(message)
            messages.append({"role": "user", "content": user_content})

        # Direct tool execution for explicit tool requests
        _direct_tool_calls = self._detect_tool_request(message)
        if _direct_tool_calls:
            logger.info(f"Direct tool execution: {len(_direct_tool_calls)} tools")
            return self._execute_direct_tools(_direct_tool_calls, steps, step_id_ref)

        # Force web search for real-time queries (weather, time, news, sports, etc.)
        _forced_search_query = self._detect_realtime_query(message)
        logger.info(f"Forced search check: msg='{message[:50]}', detected='{_forced_search_query}'")
        _had_forced_search = False
        if _forced_search_query:
            try:
                step_id_ref[0] += 1
                forced_step = {
                    "id": step_id_ref[0],
                    "type": "tool",
                    "title": f"Auto search: {_forced_search_query}",
                    "content": json.dumps({"query": _forced_search_query, "search_type": "general"}, default=str)[:200],
                    "status": "pending",
                    "tool": "web_search",
                    "params": {"query": _forced_search_query, "search_type": "general"},
                }
                steps.append(forced_step)

                # Use the new search tool with full pipeline (query processing, multi-engine, validation)
                search_tool = self.registry.get("web_search")
                search_result = None
                if search_tool:
                    search_result = search_tool.execute(query=_forced_search_query, search_type="general", max_results=5)

                # Build result text from search results
                result_text = ""
                first_url = ""
                if search_result and search_result.success:
                    data = search_result.data or {}
                    results = data.get("results", [])
                    quality = data.get("quality", "unknown")
                    result_text = f"Search quality: {quality}\n"
                    for i, r in enumerate(results[:5], 1):
                        title = r.get("title", "")
                        snippet = r.get("snippet", "")[:300]
                        page_content = r.get("page_content", "")
                        url = r.get("url", "")
                        result_text += f"{i}. {title}\n   {snippet}\n"
                        if page_content:
                            result_text += f"   [Full page content]: {page_content[:1000]}\n"
                        result_text += f"   URL: {url}\n\n"
                else:
                    result_text = "No real-time results found."

                # Record step
                forced_step["status"] = "done"
                forced_step["result"] = result_text[:200]

                # Inject search results into messages so LLM uses them
                if page_content:
                    result_text += f"\n\n### Detailed page content:\n{page_content}"
                messages.append({"role": "user", "content": f"[MANDATORY: The following are real-time search results. You MUST use this information to answer the user's question directly. DO NOT search again, DO NOT say you cannot get real-time info. Just answer based on these results.]\n\nSearch results for '{_forced_search_query}':\n{result_text[:3000]}"})
                # Tell the LLM to answer directly after forced search
                enhanced_context += f"\n### ⚠️ OVERRIDE: REAL-TIME SEARCH COMPLETED\nSearch for '{_forced_search_query}' has already been executed. The results are in the conversation. You MUST answer the user's question directly using these results. DO NOT call web_search again. DO NOT say you cannot get real-time information."
                _had_forced_search = True
                logger.info(f"Forced search for real-time query: {_forced_search_query}")
            except Exception as e:
                logger.warning(f"Forced search failed: {e}")

        # Rebuild system prompt in case enhanced_context was updated by forced search
        import datetime
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            ui_state_summary=ui_state_summary,
            enhanced_context=enhanced_context,
            clean_context=self.memory.get_clean_context(),
            current_date=datetime.datetime.now().strftime("%Y-%m-%d"),
        )

        # Inject relevant prompt modules based on message content
        prompt_modules = get_prompt_modules(message)
        if prompt_modules:
            system_prompt += "\n\n" + prompt_modules

        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = system_prompt
        else:
            messages.insert(0, {"role": "system", "content": system_prompt})

        max_iterations = 8
        iteration = 0
        final_response = ""
        tools_executed = False
        accumulated_text = ""  # Preserve text across LLM iterations
        _failed_tools = set()  # Track tools that returned 0/empty results
        _lang = self.memory.user_lang
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

            # DEBUG: Log raw LLM response

            # Accumulate text from this iteration
            cleaned_content = self._clean_response_text(content)
            if cleaned_content:
                accumulated_text += (" " if accumulated_text else "") + cleaned_content

            # Check for tool calls from both native API response and parsed text
            tool_calls = []
            if response.tool_calls:
                for tc in response.tool_calls:
                    # Handle OpenAI format: {"function": {"name": ..., "arguments": ...}}
                    if "function" in tc:
                        func = tc["function"]
                        raw_args = func.get("arguments", "{}")
                        if isinstance(raw_args, str):
                            args = json.loads(raw_args) if raw_args else {}
                        elif isinstance(raw_args, dict):
                            args = raw_args
                        else:
                            args = {}
                        tool_calls.append({
                            "id": tc.get("id", f"tool_{len(tool_calls)}"),
                            "tool": func.get("name", ""),
                            "params": args,
                        })
                    else:
                        # Native Anthropic format: {"name": ..., "arguments": ...}
                        raw_args = tc.get("arguments", tc.get("input", {}))
                        if isinstance(raw_args, str):
                            args = json.loads(raw_args) if raw_args else {}
                        elif isinstance(raw_args, dict):
                            args = raw_args
                        else:
                            args = {}
                        tool_calls.append({
                            "id": tc.get("id", f"tool_{len(tool_calls)}"),
                            "tool": tc.get("name", ""),
                            "params": args,
                        })
            else:
                # Parse from text format (```tool_call blocks)
                tool_calls = self._parse_tool_calls(content)


            if not tool_calls:
                # BUG FIX 2026-06-17: bypass LLM summary for
                # planning runs (same as streaming path fix).
                _executed_tool_names = [
                    s.get("tool", "")
                    for s in steps
                    if s.get("type") == "tool" and s.get("status") == "done"
                ]
                _planning_done = any(
                    t in _executed_tool_names
                    for t in ("planning_pipeline", "seed_planning",
                             "trajectory_planning", "dose_engine", "dose_evaluation")
                )
                if _planning_done:
                    final_response = self._build_planning_report(
                        self.memory.user_lang, steps
                    )
                else:
                    final_response = self._clean_response_text(content)
                    if not final_response:
                        final_response = content
                break

            # Filter out tool calls with empty required params, normalize param names
            valid_tool_calls = self._normalize_tool_params(tool_calls)

            # When CT is not loaded, block CT-dependent tool calls
            if _no_files_loaded and valid_tool_calls:
                _ct_dependent = {"ctv_segmentation", "oar_segmentation", "seed_planning",
                                 "seed_segmentation", "trajectory_planning", "dose_engine",
                                 "dose_evaluation", "ui_inspector", "filesystem_browser"}
                valid_tool_calls = [tc for tc in valid_tool_calls
                                    if tc.get("tool", "") not in _ct_dependent]

            if not valid_tool_calls:
                # Tool calls were generated but all filtered out (e.g. empty code)
                # Mark as executed so summary call triggers instead of fallback message
                tools_executed = True
                break

            tool_calls = valid_tool_calls
            tools_executed = True  # Mark that tools are being executed

            for tc in tool_calls:
                tool_name = tc.get("tool", "")
                params = tc.get("params", {})
                tool_id = tc.get("id", f"tool_{step_id_ref[0]}")

                # Skip duplicate tool calls that already failed (returned 0/empty)
                _tool_key = f"{tool_name}:{json.dumps(params, sort_keys=True, default=str)[:100]}"
                if _tool_key in _failed_tools:
                    logger.info(f"Skipping duplicate failed tool call: {tool_name}")
                    continue

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
                        result_text = ToolResultPipeline.format(tool_name, result, lang=_lang)
                    except Exception as e:
                        result_text = f"Exception: {str(e)}"
                        logger.error(f"Tool {tool_name} failed: {e}")
                else:
                    result_text = f"Unknown tool: {tool_name}. Available: {self.registry.tool_names}"

                step_status = "done" if "Error" not in result_text and "Exception" not in result_text else "error"
                steps[-1]["status"] = step_status
                steps[-1]["result"] = result_text[:200]

                # Track tools that returned 0 results to prevent retry loops
                if result_text and ("Found 0" in result_text or "0 match" in result_text or "No results" in result_text):
                    _failed_tools.add(_tool_key)
                    logger.info(f"Tool {tool_name} returned 0 results, marking as failed")

                # Append tool call and result to messages in Anthropic-compatible format
                tool_id = tc.get("id", f"tool_{step_id_ref[0]}")
                messages.append({
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": tool_id, "name": tool_name, "input": params}
                    ]
                })
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": tool_id, "content": result_text[:2000]}
                    ]
                })
                # Store in conversation memory for context persistence
                self.memory.add_message("assistant", f"[Called {tool_name}]")
                self.memory.add_message("user", f"[Tool result: {result_text[:500]}]")

            # After all tools executed, instruct LLM to continue or summarize.
            # The previous instruction let the LLM run open-ended, which
            # often produced mid-sentence truncation. Constrain the response
            # format to a compact table + one-line conclusion so the LLM
            # can't ramble and run out of output tokens mid-thought.
            #
            # IMPORTANT: this prompt must NOT give the LLM an excuse to
            # summarize early. We list the COMPLETE brachytherapy workflow
            # (CTV seg → OAR seg → planning_pipeline) and require the LLM
            # to call the next tool if the previous one is not the last in
            # the chain. The LLM is misreading "Tool execution completed"
            # as a signal to stop.
            if tool_calls:
                # Detect which tools have been called so far in this turn
                _executed_tool_names = [
                    s.get("tool", "")
                    for s in steps
                    if s.get("type") == "tool" and s.get("status") == "done"
                ]
                _has_planning = any(
                    t in _executed_tool_names
                    for t in ("planning_pipeline", "seed_planning", "trajectory_planning", "dose_engine", "dose_evaluation")
                )
                if not _has_planning:
                    # CTV + OAR are done, but planning is not. Force the
                    # LLM to continue with planning_pipeline. Without
                    # this the LLM summarizes after just the segmentations
                    # and never runs the actual planning.
                    _present_instruction = (
                        "Segmentation tools finished, but the planning workflow is INCOMPLETE. "
                        "You MUST call `planning_pipeline` next with `step: \"full\"` to compute the seed plan and dose. "
                        "Do NOT summarize yet. Do NOT list the steps as a todo list. "
                        "Just call the tool directly:\n"
                        "```tool_call\n"
                        "{\"tool\": \"planning_pipeline\", \"params\": {\"ct_image_path\": \"<the CT path>\", \"step\": \"full\", \"mode\": \"rule_based\"}}\n"
                        "```\n"
                        "After planning completes successfully, the system will give you a final-summary instruction."
                    )
                else:
                    # Planning has run. Now give the constrained summary
                    # format so the LLM can't ramble and run out of
                    # output tokens mid-thought.
                    _present_instruction = (
                        "All workflow tools completed. Now produce your FINAL summary in this exact format:\n"
                        "1. One short paragraph (≤ 3 sentences) describing what was completed.\n"
                        "2. A markdown table with columns | 指标 | 数值 | for the planning results (seeds, V100, D90, score, etc.).\n"
                        "3. One final sentence confirming completion.\n\n"
                        "DO NOT exceed this format. The 3D viewer is rebuilt automatically — do NOT ask the user to do it.\n"
                        "CRITICAL: Your ENTIRE response must be in the SAME language as the user's original question."
                    )
                messages.append({"role": "user", "content": _present_instruction})

        # Clean response - no summarization
        if final_response:
            raw_final = final_response
            final_response = self._clean_response_text(final_response)
            # If cleaning stripped everything, it was pure tool_call content
            if not final_response.strip() and raw_final.strip():
                final_response = ""

        # Strip transitional phrases from response (always run, not just when tools executed)
        if final_response:
            # Split into sentences, filter out transitional ones, keep substantive ones
            # Sentence terminators: 。！？.!?\n and ：(Chinese colon when used as terminator)
            sentences = re.split(r'(?<=[。！？.!?\n：])\s*', final_response.strip())
            _transitional_keywords = [
                '我来', '让我', '好的', '我帮你', '为您', '我直接',
                '搜索', '查询', '抓取', '获取', '访问', '查看', '读取',
                '页面内容', '知识库', '没有匹配', '没有找到',
                'let me', 'i\'ll', 'i will', 'allow me', 'sure',
            ]
            substantive = []
            for s in sentences:
                s = s.strip()
                if not s or len(s) < 3:
                    continue
                # Check if sentence is transitional (starts with transitional keyword)
                s_lower = s.lower()
                is_transitional = any(s_lower.startswith(kw) for kw in _transitional_keywords)
                # Also treat bracket-only content as transitional
                if re.match(r'^\[.{2,30}\]$', s):
                    is_transitional = True
                if not is_transitional:
                    substantive.append(s)

            if substantive:
                final_response = ' '.join(substantive)
            else:
                final_response = ""

        if not final_response:
            if tools_executed:
                # Extract tool results from steps (most reliable source)
                tool_results_text = []
                for step in steps:
                    if step.get("type") == "tool" and step.get("result"):
                        tool_name = step.get("title", "tool")
                        result = step.get("result", "")
                        if result and len(result) > 5:
                            tool_results_text.append(f"**{tool_name}**: {result}")


                # Also extract from messages (Anthropic format)
                if not tool_results_text:
                    for msg in messages:
                        if isinstance(msg.get("content"), list):
                            for block in msg["content"]:
                                if isinstance(block, dict) and block.get("type") == "tool_result":
                                    content = block.get("content", "")
                                    if content and len(content) > 10:
                                        tool_results_text.append(content[:2000])

                if tool_results_text:
                    final_response = "Based on the search results:\n\n" + "\n\n".join(tool_results_text)
                elif accumulated_text and len(accumulated_text) > 10:
                    final_response = accumulated_text
                    logger.info(f"Using accumulated_text as fallback: {len(final_response)} chars")
                else:
                    final_response = "I completed the requested searches but could not retrieve detailed content. The sources may require browser access."
                    logger.warning(f"Tool result fallback: no results found in {len(messages)} messages")
            else:
                final_response = "No response generated."

        step_id_ref[0] += 1
        steps.append({
            "id": step_id_ref[0],
            "type": "assistant",
            "title": "AI Response",
            "content": final_response,
            "status": "done",
        })
        self.memory.add_message("assistant", final_response)
        return final_response, {
            "usage": total_usage,
            "latency_ms": round(total_latency_ms, 1),
            "llm_calls": llm_calls,
        }

    @staticmethod
    def _build_multimodal_content(message: str):
        """Build multimodal content array if message contains screenshot URLs.

        OpenAI-compatible APIs support multimodal content:
        content = [
            {"type": "text", "text": "..."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]

        If no screenshot URL is found, returns the plain string message.
        The image is read from disk and encoded as base64 data URL so the LLM API
        can access it without needing to reach the local server.
        """
        import base64

        # Detect screenshot URLs in message
        screenshot_pattern = r'\[Screenshot captured:\s*(/api/screenshots/[^\]]+)\]'
        match = re.search(screenshot_pattern, message)

        if not match:
            return message  # Plain text, no multimodal needed

        screenshot_url = match.group(1)
        filename = screenshot_url.split("/")[-1]

        # Read image from disk and encode as base64
        screenshots_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "uploads", "screenshots"
        )
        image_path = os.path.join(screenshots_dir, filename)

        image_data_url = None
        if os.path.exists(image_path):
            try:
                with open(image_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                image_data_url = f"data:image/png;base64,{b64}"
                logger.info(f"Encoded screenshot as base64: {filename} ({len(b64)} chars)")
            except Exception as e:
                logger.warning(f"Failed to read screenshot for multimodal: {e}")

        if not image_data_url:
            # Fallback: use URL (may not work with remote LLM providers)
            image_data_url = screenshot_url
            logger.warning(f"Screenshot file not found, using URL: {screenshot_url}")

        # Extract the question/description from the message
        text_parts = re.sub(screenshot_pattern, '', message).strip()

        # Build multimodal content
        content = [
            {"type": "text", "text": text_parts or "Please analyze this screenshot."},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]

        logger.info(f"Built multimodal content with screenshot: {filename}")
        return content

    def _clean_response_text(self, content: str) -> str:
        """Remove tool call blocks from LLM response, keep only user-facing text.

        IMPORTANT (BUG FIX 2026-06-17): the cleaner was over-aggressive
        in stripping legitimate text. Patterns like
        `[Historical reference ...]`, `[Earlier conversation ...]`,
        `[MANDATORY: ...]` are used as INTERNAL context labels in
        the system prompt, but if the LLM echoes them as part of
        a response (rare), they get stripped. More commonly, the
        cleaner was eating real text that incidentally contained
        `[...]` patterns (e.g. "see [NCCN guidelines]"). We now:
          - Only strip these patterns at the START of the content
            (most LLM echoes of context labels appear at the
            beginning, never mid-response)
          - Make all tool-call patterns more strict (require
            specific structural markers so we don't eat legitimate
            JSON/tool mentions in body text)
        """
        # Strip internal context labels that LLM might echo back.
        # Only at the START of content (anchored with ^) to avoid
        # eating legitimate text like "[NCCN guidelines]".
        content = re.sub(r'^\[Historical reference[^\]]*\]\s*', '', content)
        content = re.sub(r'^\[Earlier conversation[^\]]*\]\s*', '', content)
        content = re.sub(r'^\[MANDATORY:[^\]]*\]\s*', '', content)
        # Also strip if these appear IMMEDIATELY after a leading
        # newline or whitespace (LLM may echo them with a blank
        # line first). Still anchored, not greedy.
        content = re.sub(r'^\s*\[Historical reference[^\]]*\]\s*', '', content)
        content = re.sub(r'^\s*\[Earlier conversation[^\]]*\]\s*', '', content)
        content = re.sub(r'^\s*\[MANDATORY:[^\]]*\]\s*', '', content)
        stripped = content.strip()

        # If content is purely a JSON tool call object, return empty
        if stripped.startswith('{') and '"tool"' in stripped and '"params"' in stripped:
            try:
                obj = json.loads(stripped)
                if "tool" in obj and "params" in obj:
                    return ""
            except json.JSONDecodeError:
                pass

        # If content is purely an Anthropic tool_use array (single or double quotes), return empty
        if stripped.startswith('[') and ('tool_use' in stripped or 'tool_use' in stripped):
            if re.match(r'^\[[\s]*\{[\'"]type[\'"]\s*:\s*[\'"]tool_use[\'"]', stripped):
                return ""
        # Also handle Python repr format: [{'type': 'tool_use', ...}]
        if stripped.startswith('[{') and "'type'" in stripped and "'tool_use'" in stripped:
            return ""
        if stripped.startswith('[{"type"') and '"tool_use"' in stripped:
            return ""

        cleaned = re.sub(r'```tool_call\s*\n.*?\n```', '', content, flags=re.DOTALL).strip()
        cleaned = re.sub(r'<minimax:tool_call>.*?</minimax:tool_call>', '', cleaned, flags=re.DOTALL).strip()
        # BUG FIX 2026-06-17 (response truncation): the LLM emits
        # the tool_call block as `<tool_call>...</tool_call>` (no
        # "minimax:" prefix), but the previous cleaner only
        # matched `<minimax:tool_call>` tags. When the LLM emitted
        # `<tool_call>{...}</tool_call>`, the cleaner left it
        # intact in the streamed text and the user saw partial
        # JSON syntax in their reply. We now match both forms.
        cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', cleaned, flags=re.DOTALL).strip()
        # Also remove an opening/incomplete <tool_call> tag (in case
        # the closing tag is missing because the stream ended mid-tag).
        cleaned = re.sub(r'<tool_call>.*', '', cleaned, flags=re.DOTALL).strip()
        # Also remove incomplete/opening minimax tool_call tags
        cleaned = re.sub(r'<minimax:tool_call>.*', '', cleaned, flags=re.DOTALL).strip()
        # Remove malformed minimax tags like ]<]minimax>[[
        cleaned = re.sub(r'\]<\]minimax\[>\[.*', '', cleaned, flags=re.DOTALL).strip()
        # Remove ```tool_call followed by garbage
        cleaned = re.sub(r'```tool_call\s*\n?.*?```', '', cleaned, flags=re.DOTALL).strip()
        cleaned = re.sub(r'```tool_call.*', '', cleaned, flags=re.DOTALL).strip()
        cleaned = re.sub(r'<invoke.*?</invoke>', '', cleaned, flags=re.DOTALL).strip()
        # Remove Anthropic tool_use JSON/Python dict blocks with nested dicts
        # Use non-greedy match with depth limit to avoid eating legitimate text after tool_use
        cleaned = re.sub(r'\[[\s]*\{[\'"]type[\'"]\s*:\s*[\'"]tool_use[\'".]{0,2000}\}[\s]*\]', '', cleaned, flags=re.DOTALL).strip()
        # Also handle tool_use blocks without array wrapper
        cleaned = re.sub(r'\{[\'"]type[\'"]\s*:\s*[\'"]tool_use[\'"],\s*[\'"]id[\'".]{0,2000}\}', '', cleaned, flags=re.DOTALL).strip()
        # Remove standalone tool_use objects
        cleaned = re.sub(r'\{[\'"]type[\'"]\s*:\s*[\'"]tool_use[\'".]{0,2000}\}', '', cleaned, flags=re.DOTALL).strip()
        # Remove Python set/dict format tool_use: {'tool_use', 'id': '...', 'name': '...', 'params': {...}}
        cleaned = re.sub(r'\[\{[\'"]tool_use[\'"],\s*[\'"]id[\'".]{0,2000}\}\]', '', cleaned, flags=re.DOTALL).strip()
        # Remove incomplete tool_use dict (without closing bracket) — limit to 500 chars
        cleaned = re.sub(r'\[\{[\'"]tool_use[\'"],\s*[\'"]id[\'"].{0,500}', '', cleaned, flags=re.DOTALL).strip()
        # Remove JSON tool call objects like {"tool": "code_executor", "params": {...}}
        cleaned = re.sub(r'\{[\'"]tool[\'"]\s*:\s*[\'"][^"\']+["\'],\s*[\'"]params[\'"]\s*:\s*\{.*?\}\s*\}', '', cleaned, flags=re.DOTALL).strip()
        # Remove [TOOL_CALL] and [/TOOL_CALL] blocks
        cleaned = re.sub(r'\[TOOL_CALL\].*?\[/TOOL_CALL\]', '', cleaned, flags=re.DOTALL).strip()
        cleaned = re.sub(r'\[/?TOOL_CALL\]', '', cleaned).strip()
        # Remove stray braces that look like tool call remnants
        cleaned = re.sub(r'\}?\[/TOOL_CALL\]\}?', '', cleaned).strip()
        # Remove lines that are just tool names followed by "completed"
        cleaned = re.sub(r'^\w+_segmentation completed$', '', cleaned, flags=re.MULTILINE).strip()
        # Remove [Called tool_name] and [Tool result: ...] memory artifacts
        cleaned = re.sub(r'\[Called [^\]]+\]', '', cleaned).strip()
        cleaned = re.sub(r'\[Tool result: [^\]]*\]', '', cleaned).strip()
        # Remove [call function ...] and [search_type ...] patterns
        cleaned = re.sub(r'\[call function[^\]]*\]', '', cleaned, flags=re.DOTALL).strip()
        cleaned = re.sub(r'\[search_type[^\]]*\]', '', cleaned, flags=re.DOTALL).strip()
        # BUG FIX 2026-06-16: remove hallucinated tool-call syntax
        # variants the LLM sometimes emits. Without this, an LLM that
        # fails to use the function-call API instead writes inline text
        # like "第一步：CTV肿瘤靶区分割[TOOL => \"oar_segmentation\",
        # params => {\"image_path\": \"...\", \"organ_type\": \"pancreatic\"}]"
        # and the response gets cut off mid-paren without ever
        # finishing. The cleaner left these intact because they
        # don't match the standard ```tool_call / <minimax:tool_call>
        # / [TOOL_CALL] patterns. We strip them too:
        #   [TOOL => "name", params => {...}]
        #   [TOOL_CALL] ... [/TOOL_CALL] (already handled but defensive)
        #   {TOOL => 'name', params => {...}}
        cleaned = re.sub(r'\[TOOL\s*=>\s*[\'"][^\'"]+[\'"],\s*params\s*=>\s*\{.*?\}\s*\]', '', cleaned, flags=re.DOTALL).strip()
        cleaned = re.sub(r'\{TOOL\s*=>\s*[\'"][^\'"]+[\'"],\s*params\s*=>\s*\{.*?\}\s*\}', '', cleaned, flags=re.DOTALL).strip()
        # Same but without trailing brace (LLM cut off):
        cleaned = re.sub(r'\[TOOL\s*=>\s*[\'"][^\'"]+[\'"],\s*params\s*=>\s*\{.*', '', cleaned, flags=re.DOTALL).strip()
        cleaned = re.sub(r'\{TOOL\s*=>\s*[\'"][^\'"]+[\'"],\s*params\s*=>\s*\{.*', '', cleaned, flags=re.DOTALL).strip()
        # Remove web_search completed markers
        cleaned = re.sub(r'web_search completed', '', cleaned).strip()
        # Remove <function_calls> blocks (empty or with content)
        cleaned = re.sub(r'<function_calls>.*?</function_calls>', '', cleaned, flags=re.DOTALL).strip()
        cleaned = re.sub(r'<function_calls>.*', '', cleaned, flags=re.DOTALL).strip()
        # Remove code blocks that are just tool call JSON
        cleaned = re.sub(r'```\s*\n?\{[\'"]tool[\'"].*?\}\s*\n?```', '', cleaned, flags=re.DOTALL).strip()
        # Remove multiple consecutive newlines
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return cleaned

    def _verify_response_against_sources(self, response: str, tool_results: List[Dict]) -> Tuple[bool, List[str]]:
        """
        Verify that response doesn't contain fabricated information.
        Returns (is_valid, list_of_issues).
        """
        issues = []

        # Extract all search results content
        search_content = ""
        for result in tool_results:
            if result.get("tool") == "web_search":
                search_content += result.get("result", "") + " "

        if not search_content:
            return True, []  # No search results to verify against

        # Check for common fabrication patterns
        # 1. Check DOI patterns - if response contains a DOI, verify it's in search results
        doi_pattern = r'10\.\d{4,}/[^\s]+'
        dois_in_response = re.findall(doi_pattern, response)
        dois_in_search = re.findall(doi_pattern, search_content)

        for doi in dois_in_response:
            if doi not in dois_in_search:
                issues.append(f"Fabricated DOI detected: {doi} (not in search results)")

        # 2. Check for journal names not in search results
        journal_patterns = [
            r'Nature Medicine',
            r'New England Journal of Medicine',
            r'The Lancet',
            r'JAMA',
            r'British Medical Journal',
        ]
        for journal in journal_patterns:
            if journal.lower() in response.lower() and journal.lower() not in search_content.lower():
                issues.append(f"Journal '{journal}' not found in search results")

        # 3. Check for specific numbers that might be fabricated
        # Look for "PMID: XXXXXXXX" patterns
        pmid_pattern = r'PMID:\s*(\d+)'
        pmids_in_response = re.findall(pmid_pattern, response)
        pmids_in_search = re.findall(pmid_pattern, search_content)

        for pmid in pmids_in_response:
            if pmid not in pmids_in_search:
                issues.append(f"Fabricated PMID: {pmid} (not in search results)")

        # 4. Check for year patterns that might be fabricated
        year_pattern = r'\b(20[12]\d)\b'
        years_in_response = re.findall(year_pattern, response)
        years_in_search = re.findall(year_pattern, search_content)

        # Only flag years that are very specific and not in search results
        for year in years_in_response:
            if year not in years_in_search and year not in ['2024', '2025', '2026']:
                # Years like 2024-2026 are reasonable, others might be fabricated
                pass  # Don't flag years as they're often general knowledge

        return len(issues) == 0, issues

    def _run_llm_function_calling_stream(self, message: str, steps: List[Dict], step_id_ref: List[int], yield_event):
        """
        Streaming version of _run_llm_function_calling.
        Yields events in real-time as a generator.
        Returns final response and llm_meta via result_container.
        """
        import time as _time

        # Helper to emit event and append to steps
        def emit(event_type, data):
            return yield_event(event_type, data)

        # Auto-compact conversation history if too long
        compaction_triggered = False
        if self.memory.needs_compaction():
            self.memory.compact(keep_last=6)
            compaction_triggered = True

        enhanced_context = ""
        ui_state_for_override = self.memory.get_ui_state()
        _no_files_loaded = not AgentMemory.is_ct_loaded(ui_state_for_override)

        # === LANGUAGE DIRECTIVE (top-level) ===
        # Detect user input language and inject a HIGH-PRIORITY
        # language clause into the system prompt. The user's complaint
        # was that they typed English and got Chinese back — we now
        # detect the language and tell the LLM explicitly to reply in
        # the same language. See memory/language.py for the full
        # detection rules.
        try:
            from memory.language import detect as _lang_detect, system_prompt_clause as _lang_clause
            _ui_lang = (ui_state_for_override or {}).get("language") or None
            _lang_info = _lang_detect(message, explicit=_ui_lang)
            enhanced_context += "\n" + _lang_clause(_lang_info) + "\n"
            try:
                self.memory.store("session_language", _lang_info)
            except Exception:
                pass
        except Exception as _e:
            logger.debug(f"language detection failed: {_e}")
        if _no_files_loaded:
            enhanced_context += "\n### ⚠️ OVERRIDE: NO FILES LOADED - LIMITED TOOLS\n"
            enhanced_context += "No CT files are loaded. You MUST answer directly from medical knowledge.\n"
            enhanced_context += "DO NOT call segmentation, dose, seed, or analysis tools.\n"
            enhanced_context += "YOU MAY use report_generator (to generate reports, summaries, DVH analysis, JSON/Markdown export)\n"
            enhanced_context += "YOU MAY use report_auto_fill (in-app Report panel — fills patient/metrics/OAR/narrative from current data)\n"
            enhanced_context += "YOU MAY use clinical_kb (for clinical knowledge queries)\n"
            enhanced_context += "For in-app Report panel requests, call report_auto_fill; for file export, call report_generator.\n"
            enhanced_context += "Provide comprehensive, detailed clinical responses.\n\n"
        if self.enhanced:
            try:
                pre_ctx = self.enhanced.pre_task_hook(message)
                if pre_ctx.get("reflexion_warnings") and not _no_files_loaded:
                    enhanced_context += "\n### Past Experience Warnings\n" + pre_ctx["reflexion_warnings"]
                if pre_ctx.get("matched_sop") and not _no_files_loaded:
                    sop = pre_ctx["matched_sop"]
                    enhanced_context += f"\n### Matched SOP: {sop['name']} (success: {sop['success_rate']:.0%})\n"
                    enhanced_context += f"Recommended chain: {' -> '.join(sop['steps'])}\n"
                    enhanced_context += "NOTE: Only follow when user's message requests this action.\n"
                if pre_ctx.get("crystallized_skill") and not _no_files_loaded:
                    sk = pre_ctx["crystallized_skill"]
                    # Skip skill if it doesn't match what the user actually wants
                    _direct = self._detect_tool_request(message)
                    if _direct:
                        _wanted = {tc["tool"] for tc in _direct}
                        _skill = set(sk['tool_chain'])
                        if not _wanted.intersection(_skill):
                            logger.info(f"Skip skill '{sk['name']}' — user wants {_wanted}, skill has {_skill}")
                        else:
                            enhanced_context += f"\n### Crystallized Skill: {sk['name']} ({sk['success_rate']:.0%})\n"
                            enhanced_context += f"Chain: {' -> '.join(sk['tool_chain'])}\n"
                    else:
                        enhanced_context += f"\n### Crystallized Skill: {sk['name']} ({sk['success_rate']:.0%})\n"
                        enhanced_context += f"Chain: {' -> '.join(sk['tool_chain'])}\n"
                if pre_ctx.get("user_preferences"):
                    prefs = pre_ctx["user_preferences"]
                    if prefs:
                        enhanced_context += f"\n### User Preferences\n"
                        for pid, pv in prefs.items():
                            enhanced_context += f"- {pv['name']}: {pv['value']} (confidence: {pv['confidence']:.2f})\n"
            except Exception as e:
                logger.warning(f"Enhanced pre_task_hook failed (non-critical): {e}")

        ui_state_summary = self.memory.get_ui_state_summary()

        # Classify query type for information reliability strategy
        query_type = self._classify_query_type(message)
        type_labels = {
            'realtime': '⏱️ Real-time data (MUST search, do NOT use training data)',
            'knowledge': '📚 Knowledge (LLM + search verification)',
            'analysis': '💡 Analysis (AI reasoning, tag as "AI analysis")',
            'system': '📋 System (read from memory/tool_results)',
        }
        query_strategy = type_labels.get(query_type, type_labels['knowledge'])
        enhanced_context += f"\n### Query Type: {query_strategy}\n"
        if query_type == 'realtime':
            enhanced_context += "This query requires CURRENT data. You MUST use web_search. Do NOT answer from training data.\n"
        elif query_type == 'system':
            enhanced_context += "This query is about internal state. Read from conversation history or tool_results. Do NOT search.\n"

        import datetime
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            ui_state_summary=ui_state_summary,
            enhanced_context=enhanced_context,
            clean_context=self.memory.get_clean_context(),
            current_date=datetime.datetime.now().strftime("%Y-%m-%d"),
        )

        # Inject relevant prompt modules based on message content
        prompt_modules = get_prompt_modules(message)
        if prompt_modules:
            system_prompt += "\n\n" + prompt_modules

        messages = [
            {"role": "system", "content": system_prompt},
        ]

        # Use smart context manager for intelligent context selection
        if self.memory.smart_context:
            # Get relevant context based on the current message
            smart_context_messages = self.memory.smart_context.get_relevant_context(message)
            for msg in smart_context_messages:
                content = msg.get("content", "")
                role = msg.get("role", "user")
                # Filter out memory artifacts
                if isinstance(content, str):
                    content = re.sub(r'\[Called [^\]]+\]', '', content).strip()
                    content = re.sub(r'\[Tool result: [^\]]*\]', '', content).strip()
                    if not content or len(content) < 10:
                        continue
                # Label as past context so the LLM knows this is prior
                # conversation, NOT the current task. Avoid "historical
                # reference" — the LLM was echoing that phrase back.
                messages.append({"role": role, "content": f"[Earlier conversation — ignore for current task]\n{content}"})
        else:
            # Fallback: use last 12 messages
            msg_history = self.memory.conversation[-12:]
            for msg in msg_history:
                content = msg["content"]
                # Filter out memory artifacts from conversation history
                if isinstance(content, str):
                    content = re.sub(r'\[Called [^\]]+\]', '', content).strip()
                    content = re.sub(r'\[Tool result: [^\]]*\]', '', content).strip()
                    if not content:
                        continue  # Skip empty messages after cleaning
                messages.append({"role": msg["role"], "content": content})

        # CRITICAL: Add the current user message if not already in history
        # This ensures the LLM always has the current query to respond to
        if not messages or messages[-1].get("content") != message:
            # Check if message contains screenshot URL for multimodal content
            user_content = self._build_multimodal_content(message)
            messages.append({"role": "user", "content": user_content})

        # Force web search for real-time queries (weather, time, news, sports, etc.)
        # Uses direct Bing/Baidu search instead of PubMed-based general search
        _forced_search_query = self._detect_realtime_query(message)
        logger.info(f"Forced search check: msg='{message[:50]}', detected='{_forced_search_query}'")
        _had_forced_search = False
        if _forced_search_query:
            try:
                step_id_ref[0] += 1
                forced_step = {
                    "id": step_id_ref[0],
                    "type": "tool",
                    "title": f"Auto search: {_forced_search_query}",
                    "content": json.dumps({"query": _forced_search_query}, default=str)[:200],
                    "status": "pending",
                    "tool": "web_search",
                    "params": {"query": _forced_search_query},
                }
                steps.append(forced_step)
                yield_event("step", forced_step)

                # Use the new search tool with full pipeline (query processing, multi-engine, validation)
                search_tool = self.registry.get("web_search")
                search_result = None
                if search_tool:
                    search_result = search_tool.execute(query=_forced_search_query, search_type="general", max_results=5)

                result_text = ""
                first_url = ""
                if search_result and search_result.success:
                    data = search_result.data or {}
                    results = data.get("results", [])
                    quality = data.get("quality", "unknown")
                    result_text = f"Search quality: {quality}\n"
                    for i, r in enumerate(results[:5], 1):
                        title = r.get("title", "")
                        snippet = r.get("snippet", "")[:300]
                        page_content = r.get("page_content", "")
                        url = r.get("url", "")
                        result_text += f"{i}. {title}\n   {snippet}\n"
                        if page_content:
                            result_text += f"   [Full page content]: {page_content[:1000]}\n"
                        result_text += f"   URL: {url}\n\n"
                else:
                    logger.warning(f"Forced search failed: {search_result.error if search_result else 'no tool'}")
                    result_text = "No real-time results found."

                    forced_step["status"] = "done"
                    forced_step["result"] = result_text[:200]
                    yield_event("step", forced_step)

                    # Inject search results into messages so LLM uses them
                    messages.append({"role": "user", "content": f"[MANDATORY: The following are real-time search results. You MUST use this information to answer the user's question directly. DO NOT search again. Just answer based on these results.]\n\nSearch results for '{_forced_search_query}':\n{result_text[:3000]}"})
                    enhanced_context += f"\n### ⚠️ OVERRIDE: REAL-TIME SEARCH COMPLETED\nSearch for '{_forced_search_query}' has already been executed. The results are in the conversation. You MUST answer the user's question directly using these results. DO NOT call web_search again."
                    _had_forced_search = True
                    logger.info(f"Forced search for real-time query: {_forced_search_query}")
            except Exception as e:
                logger.warning(f"Forced search failed: {e}")

        # Rebuild system prompt in case enhanced_context was updated by forced search
        import datetime
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            ui_state_summary=ui_state_summary,
            enhanced_context=enhanced_context,
            clean_context=self.memory.get_clean_context(),
            current_date=datetime.datetime.now().strftime("%Y-%m-%d"),
        )

        # Inject relevant prompt modules based on message content
        prompt_modules = get_prompt_modules(message)
        if prompt_modules:
            system_prompt += "\n\n" + prompt_modules

        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = system_prompt
        else:
            messages.insert(0, {"role": "system", "content": system_prompt})

        max_iterations = 8
        iteration = 0
        final_response = ""
        tools_executed = False
        accumulated_text = ""  # Preserve text across LLM iterations
        _failed_tools = set()  # Track tools that returned 0/empty results for longer responses
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
            yield yield_event("step", thinking_step)

            call_start = _time.time()
            full_content = ""
            iteration_text = ""  # Text from this iteration only
            tool_calls_from_stream = []
            llm_error = None

            try:
                # Get tools in OpenAI format for function calling
                tools_for_llm = self.registry.to_openai_tools() if hasattr(self.registry, 'to_openai_tools') else None

                # If no CT files are loaded, limit to non-CT-dependent tools
                # (utility tools like tool_creator, env_manager, shell_executor still work without CT)
                ui_state = self.memory.get_ui_state()
                ct_loaded = AgentMemory.is_ct_loaded(ui_state)
                if not ct_loaded and tools_for_llm is not None:
                    _allowed_without_ct = {
                        "report_generator", "clinical_kb", "doc_reader", "case_memory",
                        "tool_creator", "env_manager", "shell_executor", "code_executor",
                        "ui_inspector", "ui_controller", "ui_screenshot", "ui_annotate",
                        "filesystem_browser", "safety_validator",
                        "plan_comparator", "dicom_rt_exporter",
                        "web_search", "web_fetch"  # Allow web tools (no CT dependency)
                    }
                    tools_for_llm = [t for t in tools_for_llm
                                      if t.get("function", {}).get("name", "") in _allowed_without_ct]

                # Use streaming LLM call with tools
                prev_cleaned_len = 0
                for chunk in self.brain_router.chat_messages_stream(messages=messages, tools=tools_for_llm):
                    if isinstance(chunk, str):
                        # Text chunk from LLM
                        full_content += chunk
                        iteration_text += chunk
                        # Clean accumulated content
                        cleaned_content = self._clean_response_text(full_content)
                        # Yield only incremental new text, skipping partial tool_use patterns
                        if cleaned_content and len(cleaned_content) > prev_cleaned_len:
                            new_text = cleaned_content[prev_cleaned_len:]
                            # Don't yield if new text starts with tool_call patterns
                            # Use specific patterns to avoid filtering legitimate text like [type something]
                            # BUG FIX 2026-06-17: also skip <tool_call>...</tool_call>
                            # (the format the LLM actually emits, not the
                            # <minimax:tool_call> prefix that wasn't matched).
                            if not re.match(r'(\[\s*\{\s*["\']type["\']\s*:\s*["\']tool_use|```tool_call|<tool_call>|<minimax:tool_call>|\[\s*TOOL_CALL\s*\])', new_text):
                                yield yield_event("text_chunk", {"text": new_text})
                            # Always advance offset so tool_call text is consumed
                            # and doesn't block future chunks when _clean_response_text removes it
                            prev_cleaned_len = len(cleaned_content)
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
                                        # Handle different tool_call formats
                                        if "function" in tc:
                                            func = tc["function"]
                                            raw_args = func.get("arguments", "{}")
                                            # Handle both string and dict arguments
                                            if isinstance(raw_args, str):
                                                args = json.loads(raw_args) if raw_args else {}
                                            elif isinstance(raw_args, dict):
                                                args = raw_args
                                            else:
                                                args = {}
                                            tool_calls_from_stream.append({
                                                "id": tc.get("id", f"tool_{len(tool_calls_from_stream)}"),
                                                "tool": func.get("name", ""),
                                                "params": args,
                                            })
                                        elif "name" in tc:
                                            # Direct format
                                            raw_args = tc.get("arguments", "{}")
                                            if isinstance(raw_args, str):
                                                args = json.loads(raw_args) if raw_args else {}
                                            elif isinstance(raw_args, dict):
                                                args = raw_args
                                            else:
                                                args = {}
                                            tool_calls_from_stream.append({
                                                "id": tc.get("id", f"tool_{len(tool_calls_from_stream)}"),
                                                "tool": tc["name"],
                                                "params": args,
                                            })
                                    except (json.JSONDecodeError, KeyError, TypeError) as e:
                                        logger.warning(f"Failed to parse tool call: {e}")
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
                yield yield_event("step", thinking_step)
                yield {"type": "_result", "response": f"LLM error: {llm_error}", "llm_meta": {"usage": total_usage, "latency_ms": 0, "llm_calls": llm_calls}}
                return

            content = full_content

            # Accumulate text from this iteration (preserves across tool calls)
            cleaned_iteration = self._clean_response_text(iteration_text)
            if cleaned_iteration:
                accumulated_text += (" " if accumulated_text else "") + cleaned_iteration

            # Check for tool calls - always try text-based parsing as fallback
            tool_calls = tool_calls_from_stream if tool_calls_from_stream else []
            if not tool_calls:
                tool_calls = self._parse_tool_calls(content)

            if not tool_calls:
                # Check for incomplete tool call markers — LLM generated [TOOL_CALL] without JSON
                if re.search(r'\[TOOL_CALL\]\s*$', content.strip()) or re.search(r'```tool_call\s*$', content.strip()):
                    logger.info(f"[LLM loop] Incomplete tool call detected, retrying iteration={iteration}")
                    messages.append({"role": "user", "content": "Your tool call was incomplete. Please call the next tool in the workflow (e.g., oar_segmentation, planning_pipeline). Use the proper tool call format."})
                    continue  # Retry without breaking

                # BUG FIX 2026-06-17 (LLM response still brief):
                # the LLM keeps producing a 5-row summary table even
                # when planning_pipeline completed successfully.
                # For planning runs we BYPASS the LLM summary and
                # generate a comprehensive 9-section report directly
                # from the stored metrics. Same logic as the direct
                # tools path (see Bug U fix).
                _executed_tool_names = [
                    s.get("tool", "")
                    for s in steps
                    if s.get("type") == "tool" and s.get("status") == "done"
                ]
                _planning_done_in_stream = any(
                    t in _executed_tool_names
                    for t in ("planning_pipeline", "seed_planning",
                             "trajectory_planning", "dose_engine", "dose_evaluation")
                )
                if _planning_done_in_stream:
                    final_response = self._build_planning_report(
                        self.memory.user_lang, steps
                    )
                    logger.info(f"[LLM loop] Bypassed LLM summary for planning run; "
                                f"generated {len(final_response)}-char report.")
                else:
                    final_response = accumulated_text or self._clean_response_text(content)
                    if not final_response:
                        final_response = content  # Fallback to raw if cleaning removed everything
                thinking_step["status"] = "done"
                thinking_step["content"] = "Response generated"
                logger.info(f"[LLM loop] No tool calls found. Iteration={iteration}, content_len={len(content)}, cleaned_len={len(final_response)}, tools_executed={tools_executed}")
                logger.info(f"[LLM loop] Raw content (first 500): {content[:500]}")
                yield yield_event("step", thinking_step)
                break

            # Update thinking step
            thinking_step["status"] = "done"
            thinking_step["content"] = f"Found {len(tool_calls)} tool call(s)"
            yield yield_event("step", thinking_step)

            # Filter out tool calls with empty required params, normalize param names
            valid_tool_calls = self._normalize_tool_params(tool_calls)

            # When CT is not loaded, block CT-dependent tool calls from text-parsed results
            if not ct_loaded and valid_tool_calls:
                _ct_dependent = {"ctv_segmentation", "oar_segmentation", "seed_planning",
                                 "seed_segmentation", "trajectory_planning", "dose_engine",
                                 "dose_evaluation", "ui_inspector", "filesystem_browser"}
                valid_tool_calls = [tc for tc in valid_tool_calls
                                    if tc.get("tool", "") not in _ct_dependent]

            if not valid_tool_calls:
                # Tool calls were generated but all filtered out (e.g. empty code)
                # Mark as executed so summary call triggers instead of fallback message
                tools_executed = True
                break

            tool_calls = valid_tool_calls

            # Prevent ui_screenshot from being called multiple times per conversation
            _screenshot_called_this_turn = set()

            for tc in tool_calls:
                tool_name = tc.get("tool", "")
                params = tc.get("params", {})

                # Skip duplicate ui_screenshot calls
                if tool_name == "ui_screenshot":
                    if tool_name in _screenshot_called_this_turn:
                        logger.warning(f"Skipping duplicate ui_screenshot call")
                        step_id_ref[0] += 1
                        skip_step = {
                            "id": step_id_ref[0],
                            "type": "tool",
                            "title": f"Skipped: {tool_name}",
                            "content": "Screenshot already requested. Wait for the image.",
                            "status": "done",
                            "tool": tool_name,
                            "params": params,
                        }
                        steps.append(skip_step)
                        yield yield_event("step", skip_step)
                        continue
                    _screenshot_called_this_turn.add(tool_name)
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
                yield yield_event("step", tool_step)

                # Progress callback for real-time updates. This is a
                # regular function (not a generator) — the previous
                # code used `yield yield_event(...)` which was a no-op
                # because the function body containing `yield` makes it
                # a generator and the yield yields the SSE string
                # itself, never reaching the stream. We now append to
                # a shared list that the streaming wrapper drains
                # between event yields.
                #
                # The list (self._pending_callback_events) acts as a
                # bridge between the sync tool call (which can't
                # `yield` because it's a regular function) and the
                # streaming generator (which can). Tools call the
                # callback, the callback appends to the list, and
                # after the tool returns, the streaming wrapper
                # flushes the list as additional SSE events.
                if not hasattr(self, '_pending_callback_events'):
                    self._pending_callback_events = []
                self._pending_callback_events.clear()

                def tool_progress_callback(message, percent):
                    self._pending_callback_events.append((
                        "progress",
                        {
                            "type": "tool_progress",
                            "tool": tool_name,
                            "message": message,
                            "percent": percent,
                        },
                    ))

                # step_callback: called by tools (e.g. planning_pipeline
                # with step:full) for each internal sub-step transition.
                # The agent translates (substep_name, status) into an
                # SSE step event so the todo list ticks through the
                # 5 sub-steps with the breathing animation, instead of
                # showing a single black-box 'planning_pipeline' step.
                def tool_step_callback(substep_name, substep_status, substep_content=None):
                    # Human-friendly title that omits the "调用" prefix
                    # the generic tool loop adds. Sub-steps are already
                    # known to be tool calls, so just show the name +
                    # status, e.g. "trajectory_init (active)".
                    substep_step = {
                        "id": step_id_ref[0] + 1,
                        "type": "tool",
                        "title": f"{substep_name} — {substep_status}",
                        "content": substep_content or substep_name,
                        "status": substep_status,
                        "tool": substep_name,
                        "params": {},
                        "parent_tool": tool_name,
                    }
                    if substep_status == "pending":
                        step_id_ref[0] += 1
                        substep_step["id"] = step_id_ref[0]
                        steps.append(substep_step)
                        # BUG FIX 2026-06-17 (substep duplicate + lost pending):
                        # append a SHALLOW COPY to the events list. Otherwise
                        # the 'done' callback below mutates the SAME dict
                        # (sets status='done') and the SSE pump ends up
                        # yielding the same data twice, both with status='done'.
                        # The 'pending' event is also lost because by the time
                        # the events list is drained, the only copy of the step
                        # has been mutated to status='done'.
                        import copy as _copy
                        self._pending_callback_events.append(("step", _copy.copy(substep_step)))
                    elif substep_status in ("done", "error"):
                        # Find the matching pending entry we appended
                        # earlier and update it in place.
                        match = None
                        for s in steps:
                            if (s.get("tool") == substep_name
                                    and s.get("parent_tool") == tool_name
                                    and s.get("status") == "pending"):
                                match = s
                                break
                        if match:
                            match["status"] = substep_status
                            if substep_content:
                                match["result"] = str(substep_content)[:200]
                            self._pending_callback_events.append(("step", match))
                        else:
                            step_id_ref[0] += 1
                            substep_step["id"] = step_id_ref[0]
                            steps.append(substep_step)
                            self._pending_callback_events.append(("step", substep_step))

                tool_result = None  # Track result for metadata
                if tool_name in ("self_evolve", "evolve", "进化", "总结经验"):
                    result_text = self._handle_self_evolution()
                elif tool_name in ("code_writer", "write_tool", "create_tool", "写工具", "新工具"):
                    result_text = self._handle_code_writing(params)
                elif tool_name in self.registry.tool_names:
                    try:
                        # For long-running tools (code_executor), yield
                        # control briefly so the browser can render the
                        # "pending" step before execution blocks.
                        if tool_name == "code_executor":
                            import time as _t
                            _t.sleep(0.08)
                        result = self._execute_tool_with_memory(
                            tool_name, params,
                            progress_callback=tool_progress_callback,
                            step_callback=tool_step_callback,
                        )
                        # Drain any sub-step events the tool emitted
                        # while running. The tool's callbacks are
                        # sync, so they couldn't `yield` directly —
                        # they appended to _pending_callback_events,
                        # and now we flush that list into the SSE
                        # stream. THIS is what makes the todo list
                        # tick through 5 sub-steps in real time.
                        for _evt_type, _evt_data in self._pending_callback_events:
                            yield yield_event(_evt_type, _evt_data)
                        self._pending_callback_events.clear()
                        tool_result = result
                        if result.success:
                            result_text = result.message
                            # Special handling for web_search - include actual results
                            if tool_name == "web_search" and hasattr(result, "data") and result.data:
                                answer = result.data.get("answer", "")
                                sources = result.data.get("sources", [])
                                results_list = result.data.get("results", [])
                                if answer:
                                    result_text = answer
                                elif results_list:
                                    # Build summary from results
                                    result_text = "Search results:\n"
                                    for r in results_list[:3]:
                                        title = r.get("title", "")
                                        snippet = r.get("snippet", "")[:200]
                                        url = r.get("url", "")
                                        result_text += f"- {title}: {snippet}\n"
                                        if url:
                                            result_text += f"  Source: {url}\n"
                                if sources:
                                    result_text += f"\nSources: {', '.join(sources[:3])}"
                            # Special handling for web_access - include actual results
                            elif tool_name == "web_access" and hasattr(result, "data") and result.data:
                                data = result.data
                                action = params.get("action", "search")
                                if action == "search":
                                    answer = data.get("answer", "")
                                    sources = data.get("sources", [])
                                    if answer:
                                        result_text = answer
                                    if sources:
                                        result_text += f"\nSources: {', '.join(sources[:3])}"
                                elif action == "fetch":
                                    title = data.get("title", "")
                                    content = data.get("content", "")[:1000]
                                    source = data.get("source", "")
                                    result_text = f"Fetched: {title}\n"
                                    if content:
                                        result_text += f"Content:\n{content}\n"
                                    if source:
                                        result_text += f"Source: {source}"
                            # Special handling for web_fetch - include actual content
                            elif tool_name == "web_fetch" and hasattr(result, "data") and result.data:
                                data = result.data
                                title = data.get("title", "")
                                content = data.get("content", "")[:1000]
                                source = data.get("source", "")
                                result_text = f"Fetched: {title}\n"
                                if content:
                                    result_text += f"Content:\n{content}\n"
                                if source:
                                    result_text += f"Source: {source}"
                            elif tool_name == "code_executor" and hasattr(result, "data") and result.data:
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
                # Include metadata for frontend actions (ui_screenshot, ui_controller, etc.)
                if tool_result is not None and tool_result.success and hasattr(tool_result, 'metadata'):
                    tool_step["metadata"] = tool_result.metadata
                tools_executed = True
                yield yield_event("step", tool_step)

                # Store tool result in agent memory for downstream tools
                if tool_result is not None and tool_result.success:
                    print(f"[EXEC] Calling _store_tool_result for {tool_name}")
                    self._store_tool_result(tool_name, tool_result)
                    # Verify storage
                    if tool_name == 'ctv_segmentation':
                        _stored = self.memory.retrieve("ctv_array")
                        print(f"[VERIFY] After store: ctv_array={'exists' if _stored is not None else 'None'}, agent_id={id(self)}")
                        import AgenticSys as _ag
                        _global = getattr(_ag, '_global_agent', None)
                        print(f"[VERIFY] _global_agent id={id(_global) if _global else 'None'}, self id={id(self)}, same={_global is self}")
                    # Also store ct_path for planning pipeline
                    if tool_name in ('ctv_segmentation', 'oar_segmentation') and 'image_path' in params:
                        self.memory.store("ct_path", params['image_path'])
                        if self.memory.retrieve("ct_image") is None:
                            try:
                                import SimpleITK as sitk
                                ct_img = sitk.ReadImage(params['image_path'])
                                self.memory.store("ct_image", ct_img)
                                # Also keep the raw frame for label metadata alignment
                                self.memory.store("ct_image_raw", ct_img)
                            except Exception as e:
                                logger.warning(
                                    f"Failed to auto-load CT image from {params['image_path']}: {e}. "
                                    f"Downstream planning may fail with 'No CT image available'."
                                )

                # Append tool call and result to messages in Anthropic-compatible format
                tool_id = tc.get("id", f"tool_{step_id_ref[0]}")
                messages.append({
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": tool_id, "name": tool_name, "input": params}
                    ]
                })
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": tool_id, "content": result_text[:2000]}
                    ]
                })
                # Store in conversation memory for context persistence
                self.memory.add_message("assistant", f"[Called {tool_name}]")
                self.memory.add_message("user", f"[Tool result: {result_text[:500]}]")

            # After all tools executed, instruct LLM to continue or summarize.
            # The previous instruction let the LLM run open-ended, which
            # often produced mid-sentence truncation. Constrain the response
            # format to a compact table + one-line conclusion so the LLM
            # can't ramble and run out of output tokens mid-thought.
            #
            # IMPORTANT: this prompt must NOT give the LLM an excuse to
            # summarize early. We list the COMPLETE brachytherapy workflow
            # (CTV seg → OAR seg → planning_pipeline) and require the LLM
            # to call the next tool if the previous one is not the last in
            # the chain. The LLM is misreading "Tool execution completed"
            # as a signal to stop.
            if tool_calls:
                # Detect which tools have been called so far in this turn
                _executed_tool_names = [
                    s.get("tool", "")
                    for s in steps
                    if s.get("type") == "tool" and s.get("status") == "done"
                ]
                _has_planning = any(
                    t in _executed_tool_names
                    for t in ("planning_pipeline", "seed_planning", "trajectory_planning", "dose_engine", "dose_evaluation")
                )
                if not _has_planning:
                    # CTV + OAR are done, but planning is not. Force the
                    # LLM to continue with planning_pipeline. Without
                    # this the LLM summarizes after just the segmentations
                    # and never runs the actual planning.
                    _present_instruction = (
                        "Segmentation tools finished, but the planning workflow is INCOMPLETE. "
                        "You MUST call `planning_pipeline` next with `step: \"full\"` to compute the seed plan and dose. "
                        "Do NOT summarize yet. Do NOT list the steps as a todo list. "
                        "Just call the tool directly:\n"
                        "```tool_call\n"
                        "{\"tool\": \"planning_pipeline\", \"params\": {\"ct_image_path\": \"<the CT path>\", \"step\": \"full\", \"mode\": \"rule_based\"}}\n"
                        "```\n"
                        "After planning completes successfully, the system will give you a final-summary instruction."
                    )
                else:
                    # Planning has run. Now give the constrained summary
                    # format so the LLM can't ramble and run out of
                    # output tokens mid-thought.
                    _present_instruction = (
                        "All workflow tools completed. Now produce your FINAL summary in this exact format:\n"
                        "1. One short paragraph (≤ 3 sentences) describing what was completed.\n"
                        "2. A markdown table with columns | 指标 | 数值 | for the planning results (seeds, V100, D90, score, etc.).\n"
                        "3. One final sentence confirming completion.\n\n"
                        "DO NOT exceed this format. The 3D viewer is rebuilt automatically — do NOT ask the user to do it.\n"
                        "CRITICAL: Your ENTIRE response must be in the SAME language as the user's original question."
                    )
                messages.append({"role": "user", "content": _present_instruction})

        # No summarization - use LLM response directly
        if final_response:
            raw_final = final_response
            final_response = self._clean_response_text(final_response)
            # If cleaning stripped everything, it was pure tool_call content - not user-facing
            # Fall back to accumulated text or tool results
            if not final_response.strip() and raw_final.strip():
                logger.info("Cleaned response was empty (pure tool_call content), falling back")
                final_response = ""

        # Detect mid-sentence truncation. The LLM sometimes runs out of
        # output tokens mid-thought, leaving a colon / comma / dash /
        # ellipsis at the end. The user would see the response cut off
        # abruptly. If we detect this, append a short completion note so
        # the chat doesn't end with a dangling punctuation mark.
        if final_response:
            stripped = final_response.rstrip()
            if stripped and stripped[-1] in '：;，。、,;.-:—…' and len(stripped) < 4000:
                # Likely truncated mid-sentence. Append a clean closure.
                final_response = stripped.rstrip('：;，。、,;.-:—…').rstrip() + '。'
                logger.info(f"[LLM response] Detected mid-sentence truncation at len={len(stripped)}, appended closure")

        # If final_response is still empty, try fallbacks
        if not final_response:
            if accumulated_text:
                final_response = accumulated_text
            elif tools_executed:
                # Extract tool results from messages to provide a useful fallback
                tool_results_text = []
                for msg in messages:
                    if isinstance(msg.get("content"), list):
                        for block in msg["content"]:
                            if isinstance(block, dict) and block.get("type") == "tool_result":
                                content = block.get("content", "")
                                if content and len(content) > 20:
                                    tool_results_text.append(content[:2000])
                    elif isinstance(msg.get("content"), str) and msg["role"] == "user":
                        if "[Tool result:" in msg["content"]:
                            import re as _re
                            result_match = _re.search(r'\[Tool result: (.+?)\]', msg["content"])
                            if result_match:
                                tool_results_text.append(result_match.group(1)[:2000])
                if tool_results_text:
                    final_response = "\n\n".join(tool_results_text)
                else:
                    final_response = "Tools executed. Check the execution trace above for results."
            else:
                final_response = "Tools executed. Check the execution trace above for results."

        # Verify response against search results to detect fabrication
        if final_response and tools_executed:
            is_valid, issues = self._verify_response_against_sources(final_response, steps)
            if not is_valid:
                logger.warning(f"Potential fabrication detected: {issues}")
                warning = "\n\n⚠️ Warning: Some information in this response may not be fully accurate. Please verify the sources."
                final_response += warning

        step_id_ref[0] += 1
        response_step = {
            "id": step_id_ref[0],
            "type": "assistant",
            "title": "AI Response",
            "content": final_response,
            "status": "done",
        }
        steps.append(response_step)
        yield yield_event("step", response_step)

        self.memory.add_message("assistant", final_response)
        yield {"type": "_result", "response": final_response, "llm_meta": {
            "usage": total_usage,
            "latency_ms": round(total_latency_ms, 1),
            "llm_calls": llm_calls,
        }}
        return

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

        # Format 1B: Python list format tool_use (MiniMax sometimes outputs this)
        if not tool_calls:
            # Match [{'type': 'tool_use', ...}] or [{"type": "tool_use", ...}]
            py_tool_use = re.search(r"\[[\s]*\{[\s]*['\"]type['\"]\s*:\s*['\"]tool_use['\"].*?\}[\s]*\]", content, re.DOTALL)
            if py_tool_use:
                try:
                    # Replace single quotes with double quotes for JSON parsing
                    raw = py_tool_use.group(0).replace("'", '"')
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict) and item.get("type") == "tool_use":
                                tool_calls.append({
                                    "id": item.get("id", f"tool_{len(tool_calls)}"),
                                    "tool": item.get("name", ""),
                                    "params": item.get("input", {}),
                                })
                except (json.JSONDecodeError, Exception):
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

        # Format 3: [TOOL_CALL] prefix with JSON
        if not tool_calls:
            toc_pattern = r'\[TOOL_CALL\]\s*(\{.*?\})'
            toc_matches = re.findall(toc_pattern, content, re.DOTALL)
            for match in toc_matches:
                try:
                    tc = json.loads(match.strip())
                    if isinstance(tc, dict) and "tool" in tc:
                        tool_calls.append(tc)
                except json.JSONDecodeError:
                    # Try extracting from nested braces
                    start = match.find('{')
                    end = match.rfind('}')
                    if start != -1 and end != -1 and end > start:
                        try:
                            tc = json.loads(match[start:end+1].replace('\n', '\\n'))
                            if isinstance(tc, dict) and "tool" in tc:
                                tool_calls.append(tc)
                        except json.JSONDecodeError:
                            pass

        # Format 4: Bare JSON objects with "tool" key
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

        # Format 5: Anthropic format [{"type": "tool_use", "name": "...", "input": {...}}]
        if not tool_calls:
            anthropic_pattern = r'\[[\s]*\{[^{}]*"type"\s*:\s*"tool_use"[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*"input"\s*:\s*(\{[^}]*\})[^{}]*\}[\s]*\]'
            anthropic_matches = re.findall(anthropic_pattern, content, re.DOTALL)
            for name, input_str in anthropic_matches:
                try:
                    params = json.loads(input_str)
                    tool_calls.append({"tool": name, "params": params})
                except json.JSONDecodeError:
                    tool_calls.append({"tool": name, "params": {}})

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
        self.memory.user_lang = "zh" if re.search(r'[一-鿿]', message) else "en"

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
        self.memory.user_lang = "zh" if re.search(r'[一-鿿]', message) else "en"
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
                import traceback as _tb
                logger.error(f"LLM function calling failed: {e}\n{_tb.format_exc()}")
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
        self.memory.user_lang = "zh" if re.search(r'[一-鿿]', message) else "en"
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
        # Include the detected language so the frontend can pick
        # language-aware labels for the todo list, status messages,
        # and other UI text. The detection uses memory/language.py
        # which counts character ranges (CJK vs Latin) and falls
        # back to the previous session's language for ambiguous
        # short messages. See memory/language.py for the full
        # detection rules and the rationale for top-level injection.
        try:
            from memory.language import detect as _lang_detect_start
            _lang_info_start = _lang_detect_start(message)
        except Exception:
            _lang_info_start = {"code": "en", "name": "English", "source": "default"}
        yield yield_event("start", {"message": message, "language": _lang_info_start})

        # User step
        add_step("user", "User Input", message)
        yield yield_event("step", steps[-1])

        # Multi-agent routing (if available)
        # SKIP for short messages (< 15 chars) to save an LLM round-trip
        # on greetings / simple questions.
        _ma_routing = None
        if self.multi_agent_wrapper and self.multi_agent_wrapper.enabled and len(message.strip()) > 15:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                ma_result = loop.run_until_complete(self.multi_agent_wrapper.process_request(message))
                loop.close()
                _ma_routing = ma_result.get("routing")
                if _ma_routing:
                    step = add_step("thinking", "Multi-Agent Router",
                                  f"Intent: {_ma_routing.intent}, Complexity: {_ma_routing.complexity}, "
                                  f"Review: {'Required' if _ma_routing.requires_review else 'Optional'}")
                    yield yield_event("step", step)
            except Exception as e:
                logger.debug(f"Multi-agent routing failed: {e}")

        # Direct tool execution for explicit tool requests
        _direct_tool_calls = self._detect_tool_request(message)
        if _direct_tool_calls:
            _lang = self.memory.user_lang
            logger.info(f"Direct tool execution (stream): {len(_direct_tool_calls)} tools")
            for tc in _direct_tool_calls:
                step = add_step("tool", f"Direct: {tc['tool']}", json.dumps(tc['params'], default=str)[:200],
                                status="pending", tool=tc['tool'], params=tc['params'])
                yield yield_event("step", step)
                try:
                    # Store ct_path for downstream tools
                    if tc['tool'] in ('ctv_segmentation', 'oar_segmentation') and 'image_path' in tc['params']:
                        self.memory.store("ct_path", tc['params']['image_path'])
                        # Also load and store CT image if not already in memory
                        if self.memory.retrieve("ct_image") is None:
                            try:
                                import SimpleITK as sitk
                                ct_img = sitk.ReadImage(tc['params']['image_path'])
                                self.memory.store("ct_image", ct_img)
                                # Keep raw frame for label metadata alignment
                                self.memory.retrieve("ct_image_raw") or self.memory.store("ct_image_raw", ct_img)
                            except Exception as _e:
                                logger.warning(f"Failed to pre-load CT image: {_e}")

                    tool_obj = self.registry.get(tc['tool'])
                    if tool_obj:
                        result = tool_obj.execute(**tc['params'])
                        step["status"] = "done"
                        step["result"] = self._format_tool_result(tc['tool'], result, lang=_lang)
                        step["metadata"] = result.metadata if result.success else {}
                        yield yield_event("step", step)
                        if result.success:
                            self._store_tool_result(tc['tool'], result)
                            # After CTV/OAR seg, ensure ct_image is stored for downstream tools
                            if tc['tool'] == 'ctv_segmentation' and 'image_path' in tc['params']:
                                if self.memory.retrieve("ct_image") is None:
                                    try:
                                        import SimpleITK as sitk
                                        ct_img = sitk.ReadImage(tc['params']['image_path'])
                                        self.memory.store("ct_image", ct_img)
                                        # Also keep raw frame for label metadata alignment
                                        self.memory.retrieve("ct_image_raw") or self.memory.store("ct_image_raw", ct_img)
                                    except Exception as e:
                                        logger.warning(
                                            f"Failed to auto-load CT from {tc['params']['image_path']}: {e}. "
                                            f"Downstream planning may fail with 'No CT image available'."
                                        )
                        # Store in conversation for context persistence
                        self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                        result_summary = result.message[:500] if result.success else f"Error: {result.error}"
                        self.memory.add_message("user", f"[Tool result: {result_summary}]")
                except Exception as e:
                    step["status"] = "error"
                    step["result"] = str(e)
                    yield yield_event("step", step)
                    logger.error(f"Direct tool failed: {tc['tool']}: {e}")
                    self.memory.add_message("assistant", f"[Called {tc['tool']}]")
                    self.memory.add_message("user", f"[Tool result: Error: {str(e)[:200]}]")

            raw_response = self._build_direct_response(steps, _lang)
            user_msg = message
            # BUG FIX 2026-06-16 (LLM response still brief): the user
            # complained that the LLM synthesis after planning was
            # just a 5-row table — no OAR analysis, no flagged
            # issues, no clinical context. Even with the 10-section
            # template in the prompt, the LLM keeps producing brief
            # output (probably max_tokens truncation or the LLM
            # ignoring long instructions). For PLANNING runs, we
            # now BYPASS LLM synthesis and generate the full
            # structured response directly from the actual stored
            # metrics. This guarantees the user always sees the
            # complete clinical report.
            planning_tools_in_run = {"ctv_segmentation", "oar_segmentation",
                                     "planning_pipeline", "seed_planning",
                                     "dose_evaluation", "dose_calc"}
            has_planning = any(
                s.get("tool") in planning_tools_in_run
                for s in steps
            )
            if has_planning:
                response = self._build_planning_report(_lang, steps)
            else:
                query_type = self._classify_query_type(user_msg)
                response = self._synthesize_with_llm(raw_response, steps, _lang, user_msg, query_type)
            self.memory.add_message("assistant", response)

            # Multi-agent review with feedback loop
            if self.multi_agent_wrapper and self.multi_agent_wrapper.enabled:
                _needs_review = False
                _review_type = "general_response"
                for tc in _direct_tool_calls:
                    if tc['tool'] in ["planning_pipeline", "seed_planning", "dose_evaluation"]:
                        _needs_review = True
                        _review_type = "treatment_plan"
                        break

                if _needs_review:
                    _MAX_RETRIES = 3
                    for _retry in range(_MAX_RETRIES):
                        try:
                            import asyncio
                            loop = asyncio.new_event_loop()
                            review_result = loop.run_until_complete(
                                self.multi_agent_wrapper.review_output(_review_type, {
                                    "dose_metrics": self.memory.retrieve("dose_metrics", {}),
                                    "plan_info": {
                                        "total_seeds": self.memory.retrieve("total_seeds", 0),
                                        "num_trajectories": self.memory.retrieve("num_trajectories", 0),
                                    },
                                    "plan_config": self.memory.retrieve("plan_config", {}),
                                }, lang=self.memory.user_lang)
                            )
                            loop.close()

                            if review_result and review_result.get("display_text"):
                                step = add_step("review", "Quality Review",
                                              review_result["display_text"],
                                              status="done" if review_result["passed"] else "warning")
                                yield yield_event("step", step)

                            # If passed, break out of retry loop
                            if not review_result or review_result.get("passed"):
                                break

                            # Not passed — extract concerns and feed back to LLM
                            _concerns = review_result.get("display_text", "")
                            # Extract raw concerns from reviews
                            _raw_concerns = []
                            for r in review_result.get("reviews", []):
                                if r.get("concerns"):
                                    _raw_concerns.extend(r["concerns"])
                            _concerns_text = "; ".join(_raw_concerns) if _raw_concerns else _concerns

                            if _retry < _MAX_RETRIES - 1:
                                _feedback_msg = (
                                    f"Quality review REJECTED (attempt {_retry + 1}/{_MAX_RETRIES}).\n"
                                    f"Issues found: {_concerns_text}\n"
                                    f"Please fix these issues by calling the appropriate tools again."
                                )
                                step = add_step("thinking", "Review Feedback",
                                              f"Attempt {_retry + 1}: Retrying based on review feedback",
                                              status="done")
                                yield yield_event("step", step)

                                # Let LLM retry with feedback — re-enter function calling loop.
                                # Capture the retry's _result event so the final
                                # `yield yield_event("response", ...)` emits the
                                # RETRY's response, not the original (which would
                                # otherwise be a stale, truncated copy that the
                                # frontend would re-render on top of the streamed
                                # retry text, causing a confusing / truncated UI).
                                _retry_msg = message + f"\n\n[Quality review feedback - fix these issues: {_concerns_text}]"
                                for ev in self._run_llm_function_calling_stream(
                                        _retry_msg, steps, step_id, yield_event):
                                    if isinstance(ev, dict) and ev.get("type") == "_result":
                                        # Override the original response with the
                                        # retry's full response so the final
                                        # response event reflects what the user
                                        # actually saw in the streamed text.
                                        response = ev.get("response", response) or response
                                        if ev.get("llm_meta"):
                                            llm_meta = ev.get("llm_meta", {})
                                    else:
                                        yield ev
                        except Exception as e:
                            logger.warning(f"Review retry {_retry + 1} failed: {e}")
                            break

            # BUG FIX 2026-06-17: after quality review retry, the
            # LLM might produce a brief response that overwrites the
            # comprehensive planning report. Always regenerate from
            # stored metrics when planning tools were executed.
            if has_planning:
                response = self._build_planning_report(_lang, steps)
                logger.info(f"[streaming] Regenerated planning report after review: {len(response)} chars")

            yield yield_event("response", {"response": response})
            yield yield_event("done", {"context": {"message_count": len(self.memory.conversation)}})
            return

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
                for ev in self._run_llm_function_calling_stream(message, steps, step_id, yield_event):
                    if isinstance(ev, dict) and ev.get("type") == "_result":
                        response = ev.get("response", "")
                        llm_meta = ev.get("llm_meta", {})
                    else:
                        yield ev
            except Exception as e:
                import traceback as _tb
                logger.error(f"LLM function calling failed: {e}\n{_tb.format_exc()}")
                add_step("error", "LLM Error", str(e), status="error")
                response = f"Error: {e}"
                llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}
                yield yield_event("error", {"message": str(e)})
        else:
            response = self._rule_based_chat_with_steps_stream(message, steps, step_id, yield_event)
            llm_meta = {"usage": {}, "latency_ms": 0, "llm_calls": 0}

        self._record_experience(message, response, steps)

        # Multi-agent review (if available and needed)
        if self.multi_agent_wrapper and self.multi_agent_wrapper.enabled:
            try:
                # Determine if review is needed based on steps
                _needs_review = False
                _review_type = "general_response"
                _review_content = {"response": response, "steps": steps}

                # Check if treatment plan was generated
                for s in steps:
                    if s.get("tool") in ["planning_pipeline", "seed_planning", "dose_evaluation"]:
                        _needs_review = True
                        _review_type = "treatment_plan"
                        _review_content = {
                            "dose_metrics": self.memory.retrieve("dose_metrics", {}),
                            "plan_info": {
                                "total_seeds": self.memory.retrieve("total_seeds", 0),
                                "num_trajectories": self.memory.retrieve("num_trajectories", 0),
                            },
                            "plan_config": self.memory.retrieve("plan_config", {}),
                        }
                        break

                if _needs_review:
                    _MAX_RETRIES = 3
                    for _retry in range(_MAX_RETRIES):
                        import asyncio
                        loop = asyncio.new_event_loop()
                        review_result = loop.run_until_complete(
                            self.multi_agent_wrapper.review_output(
                                _review_type, _review_content,
                                lang=self.memory.user_lang)
                        )
                        loop.close()

                        if review_result and review_result.get("display_text"):
                            step = add_step("review", "Quality Review",
                                          review_result["display_text"],
                                          status="done" if review_result["passed"] else "warning",
                                          review_decision=review_result.get("decision", ""))
                            yield yield_event("step", step)

                        if not review_result or review_result.get("passed"):
                            break

                        # Extract concerns for feedback
                        _raw_concerns = []
                        for r in review_result.get("reviews", []):
                            if r.get("concerns"):
                                _raw_concerns.extend(r["concerns"])
                        _concerns_text = "; ".join(_raw_concerns) if _raw_concerns else review_result.get("display_text", "")

                        if _retry < _MAX_RETRIES - 1:
                            step = add_step("thinking", "Review Feedback",
                                          f"Attempt {_retry + 1}: Retrying based on review feedback",
                                          status="done")
                            yield yield_event("step", step)

                            _retry_msg = message + f"\n\n[Quality review feedback - fix these issues: {_concerns_text}]"
                            # Capture the retry's _result so the final
                            # `yield yield_event("response", ...)` below
                            # emits the RETRY's full response, not the
                            # original (stale, truncated) one — otherwise
                            # the frontend would re-render the original on
                            # top of the streamed retry text, causing a
                            # confusing / truncated chat UI.
                            for ev in self._run_llm_function_calling_stream(
                                    _retry_msg, steps, step_id, yield_event):
                                if isinstance(ev, dict) and ev.get("type") == "_result":
                                    response = ev.get("response", response) or response
                                    if ev.get("llm_meta"):
                                        llm_meta = ev.get("llm_meta", {})
                                else:
                                    yield ev
            except Exception as e:
                logger.debug(f"Multi-agent review failed: {e}")

        # SAFETY NET: after quality review retry, ensure the response
        # is the full planning report (not a brief LLM acknowledgment).
        _has_planning = any(
            s.get("tool") in ("ctv_segmentation", "oar_segmentation",
                               "planning_pipeline", "seed_planning",
                               "dose_evaluation", "dose_calc")
            for s in steps
        )
        if _has_planning and response:
            # Check if response is suspiciously short (likely a retry
            # artifact that didn't regenerate the full report)
            logger.info(f"[chat_with_stream] Safety net check: has_planning={_has_planning}, response_len={len(response)}")
            if len(response) < 500:
                try:
                    _full_report = self._build_planning_report(self.memory.user_lang, steps)
                    logger.info(f"[chat_with_stream] Safety net: regenerated report len={len(_full_report) if _full_report else 0}")
                    if _full_report and len(_full_report) > len(response):
                        logger.info(f"[chat_with_stream] Safety net: replaced {len(response)}-char response with {len(_full_report)}-char planning report")
                        response = _full_report
                except Exception as e:
                    logger.warning(f"[chat_with_stream] Safety net report generation failed: {e}")

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
                "  - 'Segment CTV' - Segment CTV\n"
                "  - 'Generate plan' - Generate treatment plan\n"
                "  - 'Evaluate dose' - Evaluate dose distribution\n"
                "  - 'Optimize plan' - Optimize treatment plan\n"
                "  - 'Self-evolve' - Trigger self-evolution\n"
                "  - 'Create tool' - Create new tool"
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
                "  - 'Segment CTV' - Segment CTV\n"
                "  - 'Generate plan' - Generate treatment plan\n"
                "  - 'Evaluate dose' - Evaluate dose distribution\n"
                "  - 'Optimize plan' - Optimize treatment plan\n"
                "  - 'Self-evolve' - Trigger self-evolution\n"
                "  - 'Create tool' - Create new tool"
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
                "  - 'Segment CTV' - Segment CTV\n"
                "  - 'Generate plan' - Generate treatment plan\n"
                "  - 'Evaluate dose' - Evaluate dose distribution\n"
                "  - 'Optimize plan' - Optimize treatment plan\n"
                "  - 'Self-evolve' - Trigger self-evolution\n"
                "  - 'Create tool' - Create new tool"
            )
        return response
    
    def _handle_ctv_segmentation_request(self, message: str) -> str:
        ct_image = self.memory.retrieve("ct_image")
        ctv_path = self.memory.retrieve("ctv_path")
        if ct_image is None:
            return "Please provide CT image path first. Use run_preoperative_plan(ct_path=...) to load CT."
        # Detect tumor type from message
        tumor_type = self._detect_tumor_type_from_message(message)
        params = {"image": ct_image, "label_path": ctv_path}
        if tumor_type:
            params["tumor_type"] = tumor_type
        result = self.registry.execute("ctv_segmentation", **params)
        self.memory.log_tool_call("ctv_segmentation", params, result)
        if result.success:
            self.memory.store("ctv_array", result.metadata["ctv_array"])
            self.memory.store("ctv_mask", result.metadata.get("ctv_mask"))
            if "label_stats" in result.metadata:
                self.memory.store("ctv_label_stats", result.metadata["label_stats"])
            if "label_map" in result.metadata:
                self.memory.store("ctv_label_map", result.metadata["label_map"])
            # Store ctv_voxels/volume for report generation
            _cv = result.metadata.get("ctv_voxel_count")
            if not _cv:
                try:
                    _cv = int(np.sum(np.asarray(result.metadata["ctv_array"]) > 0))
                except Exception:
                    _cv = 0
            self.memory.store("ctv_voxels", _cv)
            _cvm3 = result.metadata.get("ctv_volume_mm3")
            if _cvm3:
                self.memory.store("ctv_volume_mm3", _cvm3)
            if params.get("tumor_type"):
                self.memory.store("tumor_type_used", params["tumor_type"])
            return result.message
        return f"CTV segmentation failed: {result.error}"

    def _handle_oar_segmentation_request(self, message: str) -> str:
        ct_image = self.memory.retrieve("ct_image")
        oar_path = self.memory.retrieve("oar_path")
        if ct_image is None:
            return "Please provide CT image path first."
        result = self.registry.execute("oar_segmentation", image=ct_image, label_path=oar_path)
        self.memory.log_tool_call("oar_segmentation", {}, result)
        if result.success:
            self.memory.store("oar_array", result.metadata.get("oar_array"))
            if "organ_names" in result.metadata:
                self.memory.store("organ_names", result.metadata["organ_names"])
            if "organ_counts" in result.metadata:
                self.memory.store("organ_counts", result.metadata["organ_counts"])
            return result.message
        return f"OAR segmentation failed: {result.error}"
    
    def _handle_planning_request(self, message: str) -> str:
        trajectories = self.memory.retrieve("trajectories")
        radiation_volume = self.memory.retrieve("radiation_volume")
        ct_image = self.memory.retrieve("ct_image")
        if trajectories is None or radiation_volume is None or ct_image is None:
            return "Please load CT image and generate segmentation results first, then proceed with planning."
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
        return f"Seed planning failed: {result.error}"
    
    def _handle_evaluation_request(self, message: str) -> str:
        dose = self.memory.retrieve("dose_distribution")
        ctv = self.memory.retrieve("ctv_array")
        oar = self.memory.retrieve("oar_array")
        if dose is None or ctv is None:
            return "Please complete treatment plan generation first, then proceed with evaluation."
        result = self.registry.execute(
            "dose_evaluation", dose_array=dose, ctv_mask=ctv, oar_mask=oar,
        )
        self.memory.log_tool_call("dose_evaluation", {}, result)
        if result.success:
            return result.message
        return f"Dose evaluation failed: {result.error}"
    
    def _handle_optimization_request(self, message: str) -> str:
        dose = self.memory.retrieve("dose_distribution")
        ctv = self.memory.retrieve("ctv_array")
        oar = self.memory.retrieve("oar_array")
        if dose is None:
            return "No optimizable plan found. Please generate a treatment plan first."
        eval_result = self.registry.execute(
            "dose_evaluation", dose_array=dose, ctv_mask=ctv, oar_mask=oar,
        )
        if not eval_result.success:
            return f"Evaluation failed: {eval_result.error}"
        metrics = eval_result.metadata
        suggestions = []
        if metrics.get("v100", 0) < 0.90:
            suggestions.append("V100 < 90%, recommend increasing seed count or adjusting positions to improve target coverage.")
        if metrics.get("v200", 0) > 0.35:
            suggestions.append("V200 > 35%, over-irradiation detected. Recommend reducing seed count or adjusting positions.")
        if metrics.get("oar_violations"):
            violations = metrics["oar_violations"]
            suggestions.append(f"Detected {len(violations)} OAR dose violations. Plan needs re-optimization to protect organs at risk.")
        plan_score = metrics.get("plan_score", 0)
        if plan_score >= 80 or (plan_score <= 1 and plan_score >= 0.8):
            suggestions.append("Plan quality is good and ready for execution.")
        if not suggestions:
            suggestions.append("Plan evaluation complete. No significant issues found.")
        return f"Optimization suggestions:\n" + "\n".join(f"  - {s}" for s in suggestions)
    
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
            self.memory.store("ctv_voxels", ctv_result.metadata.get("ctv_voxel_count", 0))
            _cvm3 = ctv_result.metadata.get("ctv_volume_mm3")
            if _cvm3:
                self.memory.store("ctv_volume_mm3", _cvm3)
            logger.info(f"  CTV voxels: {ctv_result.metadata['ctv_voxel_count']}")
            
            logger.info("Step 3: OAR Segmentation")
            oar_result = self.registry.execute("oar_segmentation", image=ct_image, label_path=oar_path)
            self.memory.log_tool_call("oar_segmentation", {"image_path": ct_path, "label_path": oar_path}, oar_result)
            
            oar_array = oar_result.metadata.get("oar_array")
            dose_constraints = {}
            if oar_array is not None:
                self.memory.store("oar_array", oar_array)
                if "organ_names" in oar_result.metadata:
                    self.memory.store("organ_names", oar_result.metadata["organ_names"])
                if "organ_counts" in oar_result.metadata:
                    self.memory.store("organ_counts", oar_result.metadata["organ_counts"])
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
            v100_display = f"{v100_val * 100:.1f}%" if v100_val <= 1 else f"{v100_val:.1f}%"
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
            "ct_loaded": self.memory.retrieve("ct_data") is not None,
            "ct_path": self.memory.retrieve("ct_path") or "",
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
