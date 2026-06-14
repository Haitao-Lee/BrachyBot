"""
Auto-Generated Tools
====================

This package holds tools that the LLM creates (or that seed the
ToolCodeWriter pipeline for self-evolution). Each file in this directory
should expose a single BaseTool subclass. The brain integration
(``brain/integration/integration.py``) auto-discovers these on startup.

Seed/example tools:
    - dvh_curve_tool.DVHCurveTool

When the LLM writes a new tool here, it becomes immediately available
to the planner/agent on the next call to ``bridge.reload_auto_generated_tools()``.
"""

from tool_factory import BaseTool, ToolResult

from .dvh_curve_tool import DVHCurveTool

__all__ = ["BaseTool", "ToolResult", "DVHCurveTool"]


def list_auto_generated_tools():
    """Return the list of BaseTool subclasses available in this package."""
    return [DVHCurveTool]
