"""
UI Inspector Tool
=================
Allows the LLM to query and understand the UI state and components.
Dynamically parses the actual HTML to stay up-to-date.
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


class UIInspectorTool(BaseTool):
    """Query UI state and get detailed information about components.
    Dynamically parses HTML to stay up-to-date."""

    name = "ui_inspector"
    description = """Inspect the UI state and get detailed information about interface components.
Dynamically reads the actual HTML code to stay current.
Use this when:
- User asks about UI buttons or features
- User needs help navigating the interface
- You need to understand the current state
- User asks 'how to do X' in the interface"""

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
            "controls": []
        }

        # Find panel tabs
        tab_pattern = r'class="panel-tab[^"]*"[^>]*onclick="switchPanel\([\'"](\w+)[\'"][^>]*>([^<]*)<'
        tabs = re.findall(tab_pattern, html)
        for tab_id, tab_text in tabs:
            elements["tabs"].append({
                "id": tab_id,
                "text": tab_text.strip(),
            })

        # Find buttons with onclick
        btn_pattern = r'<button[^>]*class="([^"]*)"[^>]*onclick="([^"]*)"[^>]*>([^<]*)<'
        buttons = re.findall(btn_pattern, html)
        for btn_class, onclick, text in buttons:
            if text.strip():
                elements["buttons"].append({
                    "text": text.strip(),
                    "onclick": onclick[:100],
                    "class": btn_class[:50],
                })

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
        if not html:
            return []

        results = []
        keyword_lower = keyword.lower()

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
        for match in re.finditer(comment_pattern, html, re.DOTALL):
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

        return results[:20]  # Limit results

    def _get_ui_state(self, agent=None) -> Dict:
        """Get current UI state from agent memory."""
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
            }
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
            return ToolResult(
                success=True,
                data=elements,
                message=f"Scanned {len(elements.get('tabs', []))} tabs, {len(elements.get('buttons', []))} buttons"
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
