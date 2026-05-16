from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
import json
import os
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    id: int
    type: str
    description: str
    category: str
    parameters: Dict[str, Any]
    input_schema: str
    output_schema: str
    execute_fn: Callable


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}
        self._tools_by_id: Dict[int, ToolSpec] = {}
        self._categories: Dict[str, List[str]] = {}
        self._load_toolset_json()

    def _load_toolset_json(self):
        """Load tools from toolset.json if exists."""
        toolset_path = os.path.join(os.path.dirname(__file__), "toolset.json")
        if os.path.exists(toolset_path):
            try:
                with open(toolset_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for t in data.get("tools", []):
                        self.register(
                            name=t["name"],
                            id=t["id"],
                            type=t.get("type", "general"),
                            description=t["description"],
                            category=t.get("category", "general"),
                            parameters={},
                            input_schema=t.get("input", ""),
                            output_schema=t.get("output", ""),
                            execute_fn=lambda **kw: {"status": "placeholder"}
                        )
            except Exception as e:
                logger.warning(f"Failed to load toolset.json: {e}")

    def register(self, name: str, id: int = None, type: str = "general",
                 description: str = "", category: str = "general",
                 parameters: Dict[str, Any] = None, input_schema: str = "",
                 output_schema: str = "", execute_fn: Callable = None) -> None:
        if id is None:
            id = self._get_next_id()
        if execute_fn is None:
            execute_fn = lambda **kw: {"status": "placeholder"}
        spec = ToolSpec(
            name=name,
            id=id,
            type=type,
            description=description,
            category=category,
            parameters=parameters or {},
            input_schema=input_schema,
            output_schema=output_schema,
            execute_fn=execute_fn
        )
        self._tools[name] = spec
        self._tools_by_id[id] = spec
        if category not in self._categories:
            self._categories[category] = []
        if name not in self._categories[category]:
            self._categories[category].append(name)

    def _get_next_id(self) -> int:
        max_id = 0
        for tid in self._tools_by_id.keys():
            if tid > max_id:
                max_id = tid
        return max_id + 1

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def get_by_id(self, id: int) -> Optional[ToolSpec]:
        return self._tools_by_id.get(id)

    def list_by_category(self, category: str) -> List[str]:
        return self._categories.get(category, [])

    def list_all(self) -> List[str]:
        return list(self._tools.keys())

    def list_tool_ids(self) -> List[int]:
        return list(self._tools_by_id.keys())

    def get_all_tools(self) -> Dict[str, ToolSpec]:
        return self._tools.copy()

    def describe_all(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "category": spec.category,
                "parameters": spec.parameters
            }
            for spec in self._tools.values()
        ]

    def build_prompt_context(self) -> str:
        lines = ["Available tools:"]
        for category, tool_names in self._categories.items():
            lines.append(f"\n  [{category}]")
            for name in tool_names:
                spec = self._tools[name]
                lines.append(f"    - {name}: {spec.description}")
        return "\n".join(lines)

    def get_toolset_for_prompt(self) -> List[Dict[str, Any]]:
        """Get toolset in MedAgent-Pro format for LLM prompts."""
        tools = []
        for spec in self._tools.values():
            tools.append({
                "id": spec.id,
                "type": spec.type,
                "function": spec.name,
                "input": spec.input_schema,
                "output": spec.output_schema,
            })
        return sorted(tools, key=lambda x: x["id"])

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Get tools in OpenAI function calling format."""
        tools = []
        for spec in self._tools.values():
            tools.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters if spec.parameters else {"type": "object", "properties": {}},
                }
            })
        return tools


_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry


def register_tool(name: str, description: str, category: str,
                  parameters: Dict[str, Any], execute_fn: Callable) -> None:
    get_tool_registry().register(name, description=description, category=category,
                                 parameters=parameters, execute_fn=execute_fn)
