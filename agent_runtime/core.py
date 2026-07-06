"""Core state, registry, and formatting primitives for BrachyAgent."""

import json
import logging
import os
import re
import threading
from enum import Enum
from typing import Any, Dict, List, Optional

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
        self._lock = threading.RLock()
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
        # Structured conversation state — tracks what has been done
        # so the router and context builder can make state-aware decisions.
        self.conversation_state: Dict = {
            "ctv_segmented": False,
            "oar_segmented": False,
            "planning_completed": False,
            "last_tool_calls": [],
            "data_available": [],
        }

        # Smart context manager for intelligent context selection
        try:
            from memory.smart_context import SmartContextManager
            self.smart_context = SmartContextManager(max_context_tokens=8000)
        except ImportError:
            self.smart_context = None
            logger.warning("SmartContextManager not available, using basic conversation")

    def store(self, key: str, value: Any):
        with self._lock:
            self.planning_results[key] = value

    def retrieve(self, key: str, default: Any = None) -> Any:
        with self._lock:
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
                except (ValueError, TypeError) as exc:
                    logger.debug("Skipping non-integer OAR label during CTV/OAR merge: %s", exc)
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
                except (ValueError, TypeError) as exc:
                    logger.debug("Skipping CTV label merge after label conversion failure: %s", exc)

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
                    except (ValueError, TypeError) as exc:
                        logger.debug("Skipping OAR label strip after label conversion failure: %s", exc)
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
        with self._lock:
            self.tool_results.append({
                "tool": tool_name,
                "inputs": {k: str(v)[:100] for k, v in inputs.items()},
                "success": result.success,
                "message": result.message,
                "execution_time": result.execution_time,
            })

    def add_message(self, role: str, content: str):
        """Add a message with smart context tracking."""
        with self._lock:
            self.conversation.append({"role": role, "content": content})

        # Also add to smart context manager
        if self.smart_context:
            self.smart_context.add_message(role, content)

    def set_ui_state(self, state: Dict):
        """Update UI state from frontend (selected files, etc)."""
        with self._lock:
            self._ui_state.update(state)

    def get_ui_state(self) -> Dict:
        with self._lock:
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
        with self._lock:
            ui_state = dict(self._ui_state)
        ct = ui_state.get("ct_path", "")
        ctv = ui_state.get("ctv_path", "")
        oar = ui_state.get("oar_path", "")
        plan_mode = ui_state.get("plan_mode", "")
        dev_threshold = ui_state.get("dev_threshold", "")

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
        with self._lock:
            return len(self.conversation) > max_messages

    def compact(self, keep_last: int = 6) -> str:
        """Summarize old messages and keep only recent ones."""
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            context_summary = self.context_summary
        if not context_summary:
            return ""
        cleaned = context_summary
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
        with self._lock:
            conversation = list(self.conversation)
        if not conversation:
            return ""

        # Get last 10 messages
        recent = conversation[-10:]
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
        with self._lock:
            message_count = len(self.conversation)
        return {
            "message_count": message_count,
            "entity_count": 0,
            "topic_count": 0,
        }

    def export_state(self, path: str):
        with self._lock:
            state = {
                "session_id": self.session_id,
                "phase": self.current_phase.value,
                "tool_results": list(self.tool_results),
                "conversation": list(self.conversation),
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
    _UI_TOOLS = {"ui_controller", "ui_screenshot"}
    _PLANNING_TOOLS = {"planning_pipeline", "seed_planning", "trajectory_planning", "dose_engine", "dose_evaluation"}
    _LOCALIZABLE_TOOLS = {"filesystem_browser", "shell_executor", "code_executor"}

    @staticmethod
    def _L(zh: str, en: str, lang: str = "en") -> str:
        """Bilingual helper: return zh or en based on lang."""
        return zh if lang == "zh" else en

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

        # 4. Fallback to message — localize error/success prefix
        msg = result.message or f"{tool_name} completed."
        if lang == "zh":
            # Localize common English prefixes so Chinese users never see raw English
            msg = msg.replace("Error: ", "错误: ").replace("Command executed successfully", "命令执行成功")
            msg = msg.replace("Command executed with return code 0 successfully", "命令执行成功（返回码 0）")
            msg = msg.replace("Command failed with return code ", "命令执行失败（返回码 ")
            msg = msg.replace("Listed ", "已列出 ").replace(" items in ", " 个项目，路径: ")
            msg = msg.replace("File info for ", "文件信息: ")
            msg = msg.replace("Filesystem browse failed: ", "文件浏览失败: ")
        return msg

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
                except (ValueError, KeyError, TypeError) as exc:
                    logger.debug("Falling back to raw image-processing output formatting: %s", exc)
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
            if not num_traj:
                seed_plan = meta.get("seed_plan") or meta.get("trajectories") or []
                if isinstance(seed_plan, (list, tuple)):
                    num_traj = len(seed_plan)
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
            # no flagged issues, no clinical context — "too brief"
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
                    "| OAR | Dmax (Gy) | D2cc (Gy) | D1cc (Gy) | Interpretation status |\n"
                    "|-----|-----------|-----------|-----------|--------|\n"
                    "Do NOT classify OARs as OK/WARN/EXCEEDS from generic local ratios. "
                    "Write 'Needs clinical_kb/plan_config review' unless a retrieved source "
                    "or explicit plan_config provides the exact site-specific constraint.\n\n"
                    "## 7. Review Items\n"
                    "Bullet list of observed metrics that require source-backed review. "
                    "Only call a value a violation when the tolerance and source URL are available.\n\n"
                    "## 8. Clinical Recommendations\n"
                    "3-5 bullet points: actionable next steps (e.g. consider seed repositioning "
                    "near duodenum, validate with secondary dose calculation, consult radiation "
                    "oncologist for plan acceptance).\n\n"
                    "## 9. References\n"
                    "Inline links must point to retrieved clinical_kb/web sources used for clinical claims. "
                    "If no source was retrieved, state that site-specific thresholds were not sourced.\n\n"
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
