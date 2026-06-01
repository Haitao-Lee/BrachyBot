"""
Dynamic Tool Creator
====================
Allows the agent to create new tools dynamically, register them,
and use them immediately in the system.
"""

import os
import sys
import json
import logging
import importlib.util
import inspect
from typing import Dict, Any, Optional, Type
from pathlib import Path

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Directory for dynamically created tools
TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dynamic_tools")
os.makedirs(TOOLS_DIR, exist_ok=True)

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
    description = """Create new tools dynamically, register them in the system, and use them immediately.
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

    def _create_tool(self, tool_name: str, tool_code: str, description: str,
                     input_schema: Dict = None, output_schema: Dict = None) -> ToolResult:
        """Create a new tool from Python code."""
        if not tool_name:
            return ToolResult(success=False, error="tool_name required", message="tool_name is required")

        if not tool_code:
            return ToolResult(success=False, error="tool_code required", message="tool_code is required")

        # Sanitize tool name
        tool_name = tool_name.replace(" ", "_").replace("-", "_").lower()

        # Create tool file
        tool_file = Path(TOOLS_DIR) / f"{tool_name}.py"

        try:
            # Wrap the code in a tool class
            wrapped_code = f'''
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

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
            self._register_with_agent(tool)

            return ToolResult(
                success=True,
                data={
                    "tool_name": tool_name,
                    "tool_file": str(tool_file),
                    "description": description,
                    "registered": True,
                },
                message=f"Tool '{tool_name}' created and registered successfully",
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

    def _register_with_agent(self, tool: BaseTool):
        """Register a tool with the BrachyAgent."""
        try:
            # Try to import and get the agent's registry
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
            from AgenticSys import BrachyAgent
            # Note: This would require access to the agent instance
            # For now, we just keep it in our local registry
            logger.info(f"Tool '{tool.name}' registered in dynamic registry")
        except ImportError:
            pass

    def _register_tool(self, tool_name: str, tool_code: str, description: str,
                       input_schema: Dict = None, output_schema: Dict = None) -> ToolResult:
        """Register an existing tool with the agent."""
        return self._create_tool(tool_name, tool_code, description, input_schema, output_schema)

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

    def _delete_tool(self, tool_name: str) -> ToolResult:
        """Delete a dynamic tool."""
        if tool_name in _dynamic_tools:
            del _dynamic_tools[tool_name]

            # Also delete the file
            tool_file = Path(TOOLS_DIR) / f"{tool_name}.py"
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
        tool_file = Path(TOOLS_DIR) / f"{tool_name}.py"

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
            return self._create_tool(tool_name, tool_code, description, input_schema, output_schema)

        elif action == "register":
            tool_name = kwargs.get("tool_name", "")
            tool_code = kwargs.get("tool_code", "")
            description = kwargs.get("description", "")
            input_schema = kwargs.get("input_schema")
            output_schema = kwargs.get("output_schema")
            return self._register_tool(tool_name, tool_code, description, input_schema, output_schema)

        elif action == "list":
            return self._list_tools()

        elif action == "delete":
            tool_name = kwargs.get("tool_name", "")
            if not tool_name:
                return ToolResult(success=False, error="tool_name required", message="tool_name is required for delete")
            return self._delete_tool(tool_name)

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
