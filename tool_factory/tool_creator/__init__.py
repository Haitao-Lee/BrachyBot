"""
Dynamic Tool Creator
====================
Allows the agent to create new tools dynamically, register them,
and use them immediately in the system.
"""

import os
import ast
import json
import logging
import importlib.util
import inspect
import re
from typing import Dict, Any, Optional, Type
from pathlib import Path

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Directory for dynamically created tools
TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dynamic_tools")
TOOLS_DIR_PATH = Path(TOOLS_DIR).resolve()
TRUE_VALUES = {"1", "true", "yes", "on"}


def _tool_creation_enabled() -> bool:
    """Dynamic imports are available only in trusted local Developer Mode."""
    return os.environ.get("BRACHYBOT_ENABLE_TOOL_CREATOR", "").lower() in TRUE_VALUES


def _validate_tool_code(code: str) -> list[str]:
    """Reject side-effectful module code and unsafe imports/calls."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Syntax error: {exc}"]

    allowed_imports = {
        "collections", "datetime", "itertools", "json", "math", "re",
        "statistics", "typing", "numpy", "pandas", "scipy", "SimpleITK",
        "skimage", "tool_factory",
    }
    configured = os.environ.get("BRACHYBOT_DYNAMIC_TOOL_IMPORT_ALLOWLIST", "")
    allowed_imports.update(item.strip() for item in configured.split(",") if item.strip())
    blocked_names = {"__import__", "compile", "eval", "exec", "globals", "locals", "open"}
    blocked_attributes = {
        "os.system", "os.popen", "shutil.rmtree", "socket.socket",
        "subprocess.call", "subprocess.check_output", "subprocess.Popen", "subprocess.run",
    }
    errors = []

    def attribute_path(node: ast.AST) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

    for top_level in tree.body:
        allowed = isinstance(top_level, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        if isinstance(top_level, ast.Expr) and isinstance(top_level.value, ast.Constant) and isinstance(top_level.value.value, str):
            allowed = True
        if isinstance(top_level, (ast.Assign, ast.AnnAssign)):
            try:
                ast.literal_eval(top_level.value)
                allowed = True
            except (ValueError, TypeError):
                allowed = False
        if not allowed:
            errors.append(f"Top-level executable statement is not allowed: {type(top_level).__name__}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] not in allowed_imports:
                    errors.append(f"Import is not allowlisted: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if node.level or root not in allowed_imports:
                errors.append(f"Import is not allowlisted: {node.module or '<relative>'}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in blocked_names:
                errors.append(f"Call is not allowed: {node.func.id}()")
            elif isinstance(node.func, ast.Attribute):
                call_name = attribute_path(node.func)
                if call_name in blocked_attributes:
                    errors.append(f"Call is not allowed: {call_name}()")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            errors.append(f"Dunder attribute access is not allowed: {node.attr}")

    return sorted(set(errors))

# Registry of dynamically created tools
_dynamic_tools: Dict[str, BaseTool] = {}


class DynamicTool(BaseTool):
    """Base class for dynamically created tools."""

    def __init__(self, name: str, description: str, func, input_schema: Dict = None, output_schema: Dict = None):
        self._name = name
        self._description = description
        self._func = func
        self._input_schema = input_schema or {}
        self._output_schema = output_schema or {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> Dict:
        return self._input_schema

    @property
    def output_schema(self) -> Dict:
        return self._output_schema

    def _execute(self, **kwargs) -> ToolResult:
        try:
            result = self._func(**kwargs)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(
                success=True,
                data=result,
                message=f"Tool '{self._name}' executed successfully",
            )
        except Exception as e:
            logger.error(f"Dynamic tool '{self._name}' failed: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Tool '{self._name}' failed: {e}",
            )


class ToolCreatorTool(BaseTool):
    """Create and manage dynamic tools."""

    name = "tool_creator"
    description = """Create and register tools when BRACHYBOT_ENABLE_TOOL_CREATOR=1 in trusted local Developer Mode.
Capabilities:
- create: Create a new tool from Python code
- register: Register an existing tool with the agent
- list: List all dynamically created tools
- delete: Delete a dynamic tool
- test: Test a dynamic tool
- get_code: Get the code of a dynamic tool"""

    input_schema = {
        "action": {
            "type": "string",
            "description": "Action to perform: create, register, list, delete, test, get_code",
            "enum": ["create", "register", "list", "delete", "test", "get_code"]
        },
        "tool_name": {
            "type": "string",
            "description": "Name of the tool"
        },
        "tool_code": {
            "type": "string",
            "description": "Python code for the tool (for create action). Must define a function called 'execute'"
        },
        "description": {
            "type": "string",
            "description": "Tool description for LLM understanding"
        },
        "input_schema": {
            "type": "object",
            "description": "JSON Schema for input parameters"
        },
        "output_schema": {
            "type": "object",
            "description": "JSON Schema for output format"
        },
        "test_params": {
            "type": "object",
            "description": "Parameters to test the tool with"
        },
    }
    output_schema = {
        "success": {"type": "boolean"},
        "message": {"type": "string"},
        "data": {"type": "object"},
    }

    def is_available(self) -> bool:
        return _tool_creation_enabled()

    _TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

    def _normalize_tool_name(self, tool_name: str) -> str:
        """Return a safe dynamic-tool module name or raise ValueError."""
        candidate = (tool_name or "").strip().replace(" ", "_").replace("-", "_").lower()
        if not self._TOOL_NAME_RE.fullmatch(candidate):
            raise ValueError(
                "tool_name must match ^[a-z][a-z0-9_]{0,63}$; "
                "path separators and traversal are not allowed"
            )
        return candidate

    def _tool_file(self, tool_name: str) -> Path:
        """Resolve a dynamic-tool file and keep it inside TOOLS_DIR."""
        safe_name = self._normalize_tool_name(tool_name)
        tool_file = (TOOLS_DIR_PATH / f"{safe_name}.py").resolve()
        if tool_file.parent != TOOLS_DIR_PATH:
            raise ValueError("Resolved dynamic tool path escaped TOOLS_DIR")
        return tool_file

    def _create_tool(self, tool_name: str, tool_code: str, description: str,
                     input_schema: Dict = None, output_schema: Dict = None,
                     agent=None) -> ToolResult:
        """Create a new tool from Python code."""
        try:
            tool_name = self._normalize_tool_name(tool_name)
        except ValueError as e:
            return ToolResult(success=False, error=str(e), message=str(e))

        if not tool_code:
            return ToolResult(success=False, error="tool_code required", message="tool_code is required")

        validation_errors = _validate_tool_code(tool_code)
        if validation_errors:
            message = "; ".join(validation_errors)
            return ToolResult(success=False, error=message, message=f"Tool code blocked: {message}")

        # Create tool file
        tool_file = self._tool_file(tool_name)

        try:
            TOOLS_DIR_PATH.mkdir(parents=True, exist_ok=True)
            # Wrap the code in a tool class
            wrapped_code = f'''
from tool_factory import BaseTool, ToolResult

{tool_code}
'''
            # Write the tool file
            tool_file.write_text(wrapped_code, encoding="utf-8")

            # Load the module
            spec = importlib.util.spec_from_file_location(tool_name, str(tool_file))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the execute function or class
            execute_func = None
            tool_class = None

            # Look for a function called 'execute'
            if hasattr(module, 'execute'):
                execute_func = module.execute
            # Look for a class that inherits from BaseTool
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (inspect.isclass(attr) and
                    issubclass(attr, BaseTool) and
                    attr is not BaseTool and
                    attr is not DynamicTool):
                    tool_class = attr
                    break

            if execute_func:
                # Create a dynamic tool from function
                tool = DynamicTool(
                    name=tool_name,
                    description=description or f"Dynamic tool: {tool_name}",
                    func=execute_func,
                    input_schema=input_schema or {},
                    output_schema=output_schema or {},
                )
            elif tool_class:
                # Instantiate the tool class
                tool = tool_class()
            else:
                return ToolResult(
                    success=False,
                    error="No execute function or BaseTool subclass found",
                    message="Tool code must define an 'execute' function or a class inheriting from BaseTool"
                )

            # Register the tool
            _dynamic_tools[tool_name] = tool

            # Also register with the agent's registry if available
            registered_with_agent = self._register_with_agent(tool, agent)

            return ToolResult(
                success=True,
                data={
                    "tool_name": tool_name,
                    "tool_file": str(tool_file),
                    "description": description,
                    "registered": registered_with_agent,
                },
                message=(
                    f"Tool '{tool_name}' created and registered successfully"
                    if registered_with_agent
                    else f"Tool '{tool_name}' created in the dynamic registry"
                ),
            )

        except Exception as e:
            logger.error(f"Failed to create tool: {e}")
            # Clean up file if it was created
            if tool_file.exists():
                tool_file.unlink()
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Failed to create tool '{tool_name}'"
            )

    def _register_with_agent(self, tool: BaseTool, agent=None) -> bool:
        """Register a tool with the BrachyAgent."""
        registry = getattr(agent, "registry", None)
        if registry is None or not hasattr(registry, "register"):
            logger.info("Tool '%s' retained in dynamic registry only", tool.name)
            return False
        registry.register(tool)
        logger.info("Tool '%s' registered with the active BrachyAgent", tool.name)
        return True

    def _register_tool(self, tool_name: str, tool_code: str, description: str,
                       input_schema: Dict = None, output_schema: Dict = None,
                       agent=None) -> ToolResult:
        """Register an existing tool with the agent."""
        return self._create_tool(tool_name, tool_code, description, input_schema, output_schema, agent)

    def _list_tools(self) -> ToolResult:
        """List all dynamically created tools."""
        tools = []
        for name, tool in _dynamic_tools.items():
            tools.append({
                "name": name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            })

        return ToolResult(
            success=True,
            data={"tools": tools, "count": len(tools)},
            message=f"Found {len(tools)} dynamic tool(s)",
        )

    def _delete_tool(self, tool_name: str, agent=None) -> ToolResult:
        """Delete a dynamic tool."""
        try:
            tool_name = self._normalize_tool_name(tool_name)
        except ValueError as e:
            return ToolResult(success=False, error=str(e), message=str(e))

        if tool_name in _dynamic_tools:
            del _dynamic_tools[tool_name]
            registry = getattr(agent, "registry", None)
            if registry is not None and hasattr(registry, "unregister"):
                registry.unregister(tool_name)

            # Also delete the file
            tool_file = self._tool_file(tool_name)
            if tool_file.exists():
                tool_file.unlink()

            return ToolResult(
                success=True,
                data={"tool_name": tool_name},
                message=f"Tool '{tool_name}' deleted",
            )
        else:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found",
                message=f"Tool '{tool_name}' not found in dynamic tools"
            )

    def _test_tool(self, tool_name: str, test_params: Dict = None) -> ToolResult:
        """Test a dynamic tool."""
        try:
            tool_name = self._normalize_tool_name(tool_name)
        except ValueError as e:
            return ToolResult(success=False, error=str(e), message=str(e))

        if tool_name not in _dynamic_tools:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found",
                message=f"Tool '{tool_name}' not found"
            )

        tool = _dynamic_tools[tool_name]
        try:
            result = tool.execute(**(test_params or {}))
            return ToolResult(
                success=True,
                data={"tool_name": tool_name, "result": result.to_dict() if hasattr(result, 'to_dict') else str(result)},
                message=f"Tool '{tool_name}' test completed",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Tool '{tool_name}' test failed: {e}"
            )

    def _get_code(self, tool_name: str) -> ToolResult:
        """Get the code of a dynamic tool."""
        try:
            tool_name = self._normalize_tool_name(tool_name)
            tool_file = self._tool_file(tool_name)
        except ValueError as e:
            return ToolResult(success=False, error=str(e), message=str(e))

        if not tool_file.exists():
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found",
                message=f"Tool '{tool_name}' code not found"
            )

        try:
            code = tool_file.read_text(encoding="utf-8")
            return ToolResult(
                success=True,
                data={"tool_name": tool_name, "code": code, "file_path": str(tool_file)},
                message=f"Code for tool '{tool_name}' retrieved",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Failed to read code for '{tool_name}'"
            )

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        agent = kwargs.get("_agent")

        if not _tool_creation_enabled():
            return ToolResult(
                success=False,
                error="tool_creator is disabled",
                message=(
                    "Dynamic tool creation is disabled by default. Set "
                    "BRACHYBOT_ENABLE_TOOL_CREATOR=1 only in trusted local Developer Mode."
                ),
            )

        if not action:
            return ToolResult(
                success=False,
                error="No action specified",
                message="Please specify an action: create, register, list, delete, test, get_code"
            )

        if action == "create":
            tool_name = kwargs.get("tool_name", "")
            tool_code = kwargs.get("tool_code", "")
            description = kwargs.get("description", "")
            input_schema = kwargs.get("input_schema")
            output_schema = kwargs.get("output_schema")
            return self._create_tool(tool_name, tool_code, description, input_schema, output_schema, agent)

        elif action == "register":
            tool_name = kwargs.get("tool_name", "")
            tool_code = kwargs.get("tool_code", "")
            description = kwargs.get("description", "")
            input_schema = kwargs.get("input_schema")
            output_schema = kwargs.get("output_schema")
            return self._register_tool(tool_name, tool_code, description, input_schema, output_schema, agent)

        elif action == "list":
            return self._list_tools()

        elif action == "delete":
            tool_name = kwargs.get("tool_name", "")
            if not tool_name:
                return ToolResult(success=False, error="tool_name required", message="tool_name is required for delete")
            return self._delete_tool(tool_name, agent)

        elif action == "test":
            tool_name = kwargs.get("tool_name", "")
            test_params = kwargs.get("test_params")
            if not tool_name:
                return ToolResult(success=False, error="tool_name required", message="tool_name is required for test")
            return self._test_tool(tool_name, test_params)

        elif action == "get_code":
            tool_name = kwargs.get("tool_name", "")
            if not tool_name:
                return ToolResult(success=False, error="tool_name required", message="tool_name is required for get_code")
            return self._get_code(tool_name)

        else:
            return ToolResult(
                success=False,
                error=f"Unknown action: {action}",
                message=f"Unknown action '{action}'. Valid actions: create, register, list, delete, test, get_code"
            )
