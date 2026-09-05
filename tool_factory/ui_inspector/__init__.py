"""
UI Inspector Tool
=================
Allows the LLM to query and understand the UI state and components.
Dynamically parses the HTML shell and split application scripts to stay up-to-date.
"""

import os
import re
import json
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Path to the web app HTML
HTML_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "web", "app", "index.html"
)
APP_JS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "web", "app", "static", "js"
)


class UIInspectorTool(BaseTool):
    """Query UI state and get detailed information about components.
    Dynamically parses the HTML shell and split JavaScript files to stay up-to-date."""

    name = "ui_inspector"
    description = """Inspect the UI state and get detailed information about interface components.
Dynamically reads the actual HTML code to stay current.
Use this when:
- User asks about UI buttons or features
- User needs help navigating the interface
- You need to understand the current state
- User asks 'how to do X' in the interface

For an actionable request, prefer the returned action_capabilities. Each
capability is derived from the real DOM control or handler and contains the
exact ui_controller target, command, value, and value semantics. Do not infer
an action from a translated label or from a keyword-only source match.

For a question asking where a button/control is, inspect the actual
action_capabilities first. If a visible control is requested as evidence,
pass its stable DOM id to ui_screenshot with target=overlay-controls,
visual_purpose=locate, and annotation_policy=required. The screenshot browser
resolves the element bounds; never invent pixel coordinates or answer from a
generic remembered layout. Keep this query read-only: do not click the
control merely to explain where it is.

For any current-case location question, including arbitrary Data Tree data,
scene objects, object subparts, combinations, user-created/plugin objects, or
possibly nonexistent names, call query=state and inspect state.visual_targets.
Each entry is published by the live browser and carries labels, stable
target_refs, supported screenshot surfaces, visibility, loading state, and
hierarchy. Pass only matching stable IDs to ui_screenshot. If no entry matches,
say that the requested target was not found in the current UI; never use the
selected row, a previous-turn object, or a semantically neighboring object."""

    input_schema = {
        "query": {
            "type": "string",
            "description": "What to query: 'state', 'scan', 'component', 'help', 'workflows'"
        },
        "component": {
            "type": "string",
            "description": "Specific component name to search for"
        },
        "keyword": {
            "type": "string",
            "description": "Keyword to search in UI elements"
        }
    }
    output_schema = {
        "success": {"type": "boolean"},
        "data": {"type": "object"},
    }

    def __init__(self):
        self._html_cache = None
        self._cache_time = 0

    def _load_html(self) -> str:
        """Load and cache the HTML file."""
        import time
        current_time = os.path.getmtime(HTML_PATH) if os.path.exists(HTML_PATH) else 0

        if self._html_cache and current_time == self._cache_time:
            return self._html_cache

        try:
            with open(HTML_PATH, 'r', encoding='utf-8') as f:
                self._html_cache = f.read()
            self._cache_time = current_time
            logger.info("Reloaded HTML file")
        except Exception as e:
            logger.error(f"Failed to load HTML: {e}")
            return ""

        return self._html_cache

    def _load_app_scripts(self) -> str:
        """Load feature-split BrachyBot JavaScript files for behavior searches."""
        script_root = Path(APP_JS_DIR)
        if not script_root.exists():
            return ""
        chunks: List[str] = []
        for path in sorted(script_root.glob("brachybot-*.js")):
            try:
                chunks.append(f"\n/* {path.name} */\n" + path.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                logger.warning("Failed to read UI script %s: %s", path, exc)
        return "\n".join(chunks)

    @staticmethod
    def _parse_tag_attributes(raw: str) -> Dict[str, str]:
        """Parse HTML attributes without depending on a browser DOM.

        The inspector runs on the server, while the real controls live in the
        browser.  Returning stable attributes from the source is therefore
        more reliable than asking the model to infer an action from visible
        button text alone.
        """
        attrs: Dict[str, str] = {}
        pattern = re.compile(
            r"([:\w-]+)\s*(?:=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>`]+)))?",
            re.IGNORECASE,
        )
        for match in pattern.finditer(raw or ""):
            key = match.group(1).lower()
            value = next((item for item in match.groups()[1:] if item is not None), "")
            attrs[key] = value
        return attrs

    @staticmethod
    def _plain_markup_text(raw: str) -> str:
        text = re.sub(r"<[^>]+>", " ", raw or "")
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _action_from_markup(cls, attrs: Dict[str, str], handler: str = "") -> Optional[Dict[str, Any]]:
        """Translate a real control handler into the controller contract.

        This is capability discovery, not a natural-language keyword router:
        the mapping is derived from the actual handler or explicit
        ``data-ui-*`` metadata attached to the control.
        """
        target = attrs.get("data-ui-target", "").strip()
        command = attrs.get("data-ui-command", "").strip()
        value: Optional[str] = attrs.get("data-ui-value")
        if target and command:
            action: Dict[str, Any] = {"target": target, "command": command}
            if value not in (None, ""):
                action["value"] = value
            # A range/number control carries its runtime value in the DOM
            # event, not in the static HTML attribute. Preserve that fact in
            # the capability contract so the model does not invent a
            # hard-coded number for a slider.
            elif attrs.get("type", "").lower() in {"range", "number"}:
                action["value_source"] = "control"
            return action

        source = str(handler or "").replace("&quot;", '"').replace("&#39;", "'")
        patterns = (
            (r"toggleViewerFullscreen\(\s*['\"](axial|sagittal|coronal|3d)['\"]\s*\)",
             lambda m: {"target": "viewer.fullscreen", "command": "toggle", "value": m.group(1)}),
            (r"fitCameraToScene\s*\(\s*\)",
             lambda m: {"target": "3d.fit", "command": "run"}),
            (r"fitView\s*\(\s*\)",
             lambda m: {"target": "viewer.fit_all", "command": "run"}),
            (r"reconstruct3D\s*\(\s*\)",
             lambda m: {"target": "viewer.reconstruct3d", "command": "run"}),
            (r"reset3DView\s*\(\s*\)",
             lambda m: {"target": "3d.reset", "command": "run"}),
            (r"setViewerLayout\(\s*['\"]([^'\"]+)['\"]\s*\)",
             lambda m: {"target": "layout", "command": "set", "value": m.group(1)}),
            (r"switchPanel\(\s*['\"]([^'\"]+)['\"]",
             lambda m: {"target": "panel", "command": "switch", "value": m.group(1)}),
            (r"setViewerTool\(\s*['\"]([^'\"]+)['\"]\s*\)",
             lambda m: {"target": "viewer.tool", "command": "set", "value": m.group(1)}),
            (r"applyZoom\(\s*(?:this\.value|[^)]*)\)",
             lambda m: {"target": "viewer.zoom", "command": "set", "value_source": "control"}),
            (r"updateSlice\(\s*['\"](axial|sagittal|coronal)['\"]",
             lambda m: {"target": f"slice.{m.group(1)}", "command": "set", "value_source": "control"}),
            (r"update3DMeshOpacity\s*\(",
             lambda m: {"target": "3d.mesh_opacity", "command": "set", "value_source": "control"}),
            (r"updateDoseOpacity\s*\(",
             lambda m: {"target": "3d.dose_opacity", "command": "set", "value_source": "control"}),
        )
        for pattern, builder in patterns:
            match = re.search(pattern, source, re.IGNORECASE)
            if match:
                return builder(match)
        return None

    @staticmethod
    def _action_intents(action: Optional[Dict[str, Any]], attrs: Dict[str, str], label: str) -> List[str]:
        explicit = attrs.get("data-ui-intents", "")
        if explicit:
            return [item.strip() for item in re.split(r"[,|]", explicit) if item.strip()]
        if not action:
            return []
        target = action.get("target")
        if target == "viewer.fullscreen":
            return ["maximize viewer", "fullscreen", "expand viewer", "放大查看器", "全屏"]
        if target == "viewer.zoom":
            return ["viewer zoom", "zoom in", "zoom out", "缩放", "放大图像", "缩小图像"]
        if target == "3d.fit":
            return ["fit camera", "fit visible meshes", "适配三维相机", "显示全部模型"]
        if target == "viewer.reconstruct3d":
            return ["3D reconstruction", "3D reconstruct", "reconstruct 3D", "3D重建", "三维重建"]
        if target == "viewer.fit_all":
            return ["fit 2D viewers", "适配图像", "显示完整切片"]
        return [str(label).strip()] if str(label).strip() else []

    @classmethod
    def _capability_from_control(
        cls, attrs: Dict[str, str], label: str, handler: str = "", role: str = "button"
    ) -> Optional[Dict[str, Any]]:
        action = cls._action_from_markup(attrs, handler)
        if not action:
            return None
        item: Dict[str, Any] = {
            "role": role,
            "id": attrs.get("id") or None,
            "label": label or attrs.get("title") or attrs.get("aria-label") or "",
            "action": action,
            "semantic_intents": cls._action_intents(action, attrs, label),
        }
        for key in ("title", "aria-label", "min", "max", "step", "type"):
            if attrs.get(key) not in (None, ""):
                item[key.replace("-", "_")] = attrs[key]
        if action.get("target") == "viewer.zoom":
            item["value_semantics"] = {
                "set": "absolute percent",
                "increase": "positive delta",
                "decrease": "positive delta",
                "fit": "camera/view fit, not panel maximize",
            }
        return item

    def _scan_ui_elements(self) -> Dict:
        """Dynamically scan the HTML for UI elements."""
        html = self._load_html()
        if not html:
            return {"error": "Cannot load HTML file"}

        elements = {
            "panels": {},
            "buttons": [],
            "tabs": [],
            "inputs": [],
            "viewers": [],
            "controls": [],
            # Structured capabilities are the bridge between the real DOM and
            # ui_controller.  They prevent the model from guessing a target
            # from a translated button label such as "Zoom" or "放大".
            "action_capabilities": [],
        }

        # Find panel tabs
        tab_pattern = r'class="panel-tab[^"]*"[^>]*onclick="switchPanel\([\'"](\w+)[\'"][^>]*>([^<]*)<'
        tabs = re.findall(tab_pattern, html)
        for tab_id, tab_text in tabs:
            elements["tabs"].append({
                "id": tab_id,
                "text": tab_text.strip(),
            })

        # Find buttons in any attribute order and retain their executable
        # action identity, label, tooltip, and semantic intent.
        btn_pattern = re.compile(r"<button\b(?P<attrs>[^>]*)>(?P<body>.*?)</button>", re.IGNORECASE | re.DOTALL)
        for match in btn_pattern.finditer(html):
            attrs = self._parse_tag_attributes(match.group("attrs"))
            text = self._plain_markup_text(match.group("body"))
            onclick = attrs.get("onclick", "")
            label = text or attrs.get("title") or attrs.get("aria-label") or attrs.get("id", "")
            if not label and not onclick:
                continue
            button = {
                "id": attrs.get("id") or None,
                "text": text,
                "title": attrs.get("title", ""),
                "aria_label": attrs.get("aria-label", ""),
                "onclick": onclick[:160],
                "class": attrs.get("class", "")[:80],
            }
            capability = self._capability_from_control(attrs, label, onclick)
            if capability:
                button["action"] = capability["action"]
                button["semantic_intents"] = capability["semantic_intents"]
                elements["action_capabilities"].append(capability)
            elements["buttons"].append(button)

        # Inputs/selects are controls too.  In particular the zoom slider has
        # no visible "zoom in" button, but it exposes an exact range and step.
        input_pattern = re.compile(r"<(input|select|textarea)\b(?P<attrs>[^>]*)>", re.IGNORECASE | re.DOTALL)
        for match in input_pattern.finditer(html):
            attrs = self._parse_tag_attributes(match.group("attrs"))
            label = attrs.get("aria-label") or attrs.get("title") or attrs.get("id", "")
            capability = self._capability_from_control(
                attrs, label, attrs.get("oninput", "") or attrs.get("onchange", ""), role=match.group(1).lower()
            )
            control = {
                "id": attrs.get("id") or None,
                "type": attrs.get("type", match.group(1).lower()),
                "min": attrs.get("min"),
                "max": attrs.get("max"),
                "step": attrs.get("step"),
                "value": attrs.get("value"),
                "oninput": attrs.get("oninput", "")[:160],
                "onchange": attrs.get("onchange", "")[:160],
            }
            if capability:
                control["action"] = capability["action"]
                control["semantic_intents"] = capability["semantic_intents"]
                elements["action_capabilities"].append(capability)
            elements["inputs"].append(control)

        # Find viewer cards
        viewer_pattern = r'class="viewer-card[^"]*"[^>]*id="([^"]*)"'
        viewers = re.findall(viewer_pattern, html)
        for viewer_id in viewers:
            elements["viewers"].append(viewer_id)

        # Find layout buttons
        layout_pattern = r'data-layout="([^"]*)"[^>]*title="([^"]*)"'
        layouts = re.findall(layout_pattern, html)
        for layout_id, layout_title in layouts:
            elements["controls"].append({
                "type": "layout",
                "id": layout_id,
                "title": layout_title,
            })

        # Find window presets
        preset_pattern = r'<option value="([^"]*)"[^>]*>([^<]*)</option>'
        presets = re.findall(preset_pattern, html)
        for preset_value, preset_text in presets:
            if preset_value in ["soft_tissue", "lung", "bone", "abdomen", "brain"]:
                elements["controls"].append({
                    "type": "window_preset",
                    "value": preset_value,
                    "text": preset_text.strip(),
                })

        # Find slash commands
        cmd_pattern = r'data-cmd="(/[^"]*)"'
        commands = re.findall(cmd_pattern, html)
        elements["slash_commands"] = list(set(commands))

        # Find input file types
        file_pattern = r'accept="([^"]*)"'
        file_types = re.findall(file_pattern, html)
        elements["accepted_file_types"] = list(set(file_types))

        return elements

    def _search_component(self, keyword: str) -> List[Dict]:
        """Search for components matching keyword."""
        html = self._load_html()
        source = html + "\n" + self._load_app_scripts()
        if not source.strip():
            return []

        results = []
        keyword_lower = keyword.lower()

        # Search structured action capabilities first.  This is semantic UI
        # metadata from real controls, not a hard-coded phrase-to-command map.
        scanned = self._scan_ui_elements()
        for capability in scanned.get("action_capabilities", []):
            haystack = " ".join([
                str(capability.get("label", "")),
                str(capability.get("title", "")),
                " ".join(str(item) for item in capability.get("semantic_intents", [])),
                json.dumps(capability.get("action", {}), ensure_ascii=False),
            ]).lower()
            if keyword_lower in haystack:
                results.append({"type": "action_capability", **capability})

        # Keep the source search for comments, IDs, and implementation details.
        # Structured capabilities above are deliberately returned first.
        # Search in button text
        btn_pattern = r'<button[^>]*>([^<]*)</button>'
        for match in re.finditer(btn_pattern, html):
            text = match.group(1).strip()
            if keyword_lower in text.lower():
                # Get context
                start = max(0, match.start() - 200)
                context = html[start:match.start()]
                results.append({
                    "type": "button",
                    "text": text,
                    "context": context[-100:] if context else "",
                })

        # Search in comments
        comment_pattern = r'<!--\s*(.*?)\s*-->'
        for match in re.finditer(comment_pattern, source, re.DOTALL):
            comment = match.group(1).strip()
            if keyword_lower in comment.lower():
                results.append({
                    "type": "comment",
                    "content": comment[:200],
                })

        # Search in element IDs
        id_pattern = r'id="([^"]*)"'
        for match in re.finditer(id_pattern, html):
            elem_id = match.group(1)
            if keyword_lower in elem_id.lower():
                results.append({
                    "type": "element_id",
                    "id": elem_id,
                })

        # Search split JavaScript behavior functions after modularization.
        function_pattern = r"(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\("
        for match in re.finditer(function_pattern, source):
            fn_name = match.group(1)
            if keyword_lower in fn_name.lower():
                start = max(0, match.start() - 120)
                end = min(len(source), match.end() + 180)
                results.append({
                    "type": "function",
                    "name": fn_name,
                    "context": source[start:end],
                })

        return results[:20]  # Limit results

    def _get_ui_state(self, agent=None) -> Dict:
        """Get current UI state from agent memory.

        Exposes BOTH derived tool results (ctv_array/trajectories/etc.) AND
        the user's live UI inputs (reference_direc etc.) so the LLM can answer
        questions like "what reference direction did the user set?" without a
        screenshot.
        """
        state = {
            "loaded_files": {
                "ct": False,
                "ctv": False,
                "oar": False,
            },
            "computed": {
                "trajectories": False,
                "seeds": False,
                "dose": False,
                "evaluation": False,
            },
            "viewer": {
                "layout": "vertical",
                "window_preset": "soft_tissue",
                "overlays": {"ctv": False, "oar": False, "dose": False},
            },
            "planning_inputs": {
                "reference_direction": None,
                "ref_direc_auto": None,
                "plan_mode": None,
            },
            # Populated from the live browser on every user turn.  Unlike the
            # static HTML scan, this catalog contains current Data Tree rows,
            # loaded scene objects, user-created names, object parts, and
            # rendered controls with stable screenshot identities.
            "visual_targets": [],
        }

        if agent and hasattr(agent, 'memory'):
            memory = agent.memory
            state["loaded_files"]["ct"] = memory.retrieve("ct_image") is not None
            state["loaded_files"]["ctv"] = memory.retrieve("ctv_array") is not None
            state["loaded_files"]["oar"] = memory.retrieve("oar_array") is not None
            state["computed"]["trajectories"] = memory.retrieve("trajectories") is not None
            state["computed"]["seeds"] = memory.retrieve("seed_positions") is not None
            state["computed"]["dose"] = memory.retrieve("dose_distribution") is not None
            state["computed"]["evaluation"] = memory.retrieve("metrics") is not None

            # Live UI inputs from the frontend snapshot (POST /api/ui/state).
            ui_state = memory.get_ui_state() if hasattr(memory, 'get_ui_state') else None
            if isinstance(ui_state, dict):
                catalog = ui_state.get("visual_target_catalog")
                if isinstance(catalog, list):
                    state["visual_targets"] = [
                        item for item in catalog[:512] if isinstance(item, dict)
                    ]
                planning_state = ui_state.get("planning") if isinstance(ui_state.get("planning"), dict) else {}
                plan_mode = ui_state.get("plan_mode")
                ref_direc = planning_state.get("reference_direc")
                ref_auto = planning_state.get("ref_direc_auto")
                if plan_mode:
                    state["planning_inputs"]["plan_mode"] = plan_mode
                if ref_auto:
                    state["planning_inputs"]["ref_direc_auto"] = True
                    state["planning_inputs"]["reference_direction"] = "auto"
                elif isinstance(ref_direc, list) and len(ref_direc) == 3:
                    state["planning_inputs"]["reference_direction"] = ref_direc

        return state

    def _get_help(self) -> Dict:
        """Get comprehensive help information."""
        elements = self._scan_ui_elements()

        return {
            "description": "BrachyBot - Brachytherapy Treatment Planning System",
            "layout": {
                "left_panel": "Chat area - input commands and view responses",
                "right_panel": "Function area - 4 tabs",
            },
            "tabs": elements.get("tabs", []),
            "slash_commands": elements.get("slash_commands", []),
            "viewers": elements.get("viewers", []),
            "layouts": [c for c in elements.get("controls", []) if c.get("type") == "layout"],
            "window_presets": [c for c in elements.get("controls", []) if c.get("type") == "window_preset"],
            "typical_workflow": [
                "1. Upload CT image in Input tab",
                "2. Type 'segment' to automatically segment CTV and OAR",
                "3. Type 'plan' or wait for automatic trajectory and seed planning",
                "4. View DVH and evaluation results in Analysis tab",
                "5. Type 'export' to generate DICOM files"
            ],
            "tips": [
                "Drag and drop files into chat to send",
                "Ctrl+V to paste images",
                "Type / to see all commands",
                "Viewers tab has 5 layout options",
                "Click eye icon to show/hide data layers"
            ]
        }

    def _execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query", "state")
        component = kwargs.get("component", "")
        keyword = kwargs.get("keyword", "")

        # Try to get agent reference
        agent = kwargs.get("agent", None)

        if query == "state":
            state = self._get_ui_state(agent)
            return ToolResult(
                success=True,
                data={"state": state},
                message="Getting current UI state"
            )

        elif query == "scan":
            # Dynamically scan UI elements
            elements = self._scan_ui_elements()
            if keyword:
                elements["matched_actions"] = self._search_component(keyword)
            return ToolResult(
                success=True,
                data=elements,
                message=(
                    f"Scanned {len(elements.get('tabs', []))} tabs, "
                    f"{len(elements.get('buttons', []))} buttons, "
                    f"{len(elements.get('action_capabilities', []))} executable UI capabilities"
                )
            )

        elif query == "component":
            if not component:
                return ToolResult(
                    success=False,
                    error="component keyword required",
                    message="Please provide component keyword to search"
                )
            results = self._search_component(component)
            return ToolResult(
                success=True,
                data={"keyword": component, "results": results},
                message=f"Found {len(results)} matching items"
            )

        elif query == "help":
            help_info = self._get_help()
            return ToolResult(
                success=True,
                data=help_info,
                message="Help information"
            )

        elif query == "workflows":
            workflows = [
                {
                    "name": "Full Treatment Plan",
                    "steps": "Upload CT → Segment → Plan → Place seeds → Calculate dose → Evaluate → Export",
                    "trigger": "User says 'start planning' or /plan"
                },
                {
                    "name": "Manual Planning",
                    "steps": "Load CT -> CTV/OAR segmentation -> trajectory init/refine -> seed planning -> dose/DVH -> report/export",
                    "trigger": "User asks to run the plan step-by-step without LLM automation"
                },
                {
                    "name": "Training Monitor",
                    "steps": "Start monitor -> observe UI edits/buttons/sliders -> live feedback -> final advice report",
                    "trigger": "User asks BrachyBot to monitor, train, supervise, or review their planning process"
                },
                {
                    "name": "Quick Segmentation",
                    "steps": "Ensure CT is loaded → Auto segment CTV and OAR",
                    "trigger": "User says 'segment' or /segment"
                },
                {
                    "name": "Image Analysis",
                    "steps": "Load CT → Analyze image metadata and HU values",
                    "trigger": "User says 'analyze' or /analyze"
                }
            ]
            return ToolResult(
                success=True,
                data={"workflows": workflows},
                message="Available workflows"
            )

        elif query == "search":
            if not keyword:
                return ToolResult(
                    success=False,
                    error="keyword required",
                    message="Please provide search keyword"
                )
            results = self._search_component(keyword)
            return ToolResult(
                success=True,
                data={"keyword": keyword, "results": results},
                message=f"Search for '{keyword}' found {len(results)} results"
            )

        else:
            return ToolResult(
                success=False,
                error=f"Unknown query: {query}",
                message=f"Supported queries: state, scan, component, help, workflows, search"
            )
