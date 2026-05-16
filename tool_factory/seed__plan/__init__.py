"""
Seed Planning Tools
=================
Tools for optimizing seed placement in brachytherapy.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tool_factory import BaseTool, ToolResult

from seed_planning import SeedPlanningTool
from seed_planning_rule_based import RuleBasedSeedPlanningTool
from seed_planning_rl import RLSeedPlanningTool


TOOL_REGISTRY = {
    "seed_planning": SeedPlanningTool,
    "seed_planning_rule_based": RuleBasedSeedPlanningTool,
    "seed_planning_rl": RLSeedPlanningTool,
}


def get_tool(tool_name: str):
    """Get a seed planning tool by name."""
    tool_class = TOOL_REGISTRY.get(tool_name)
    if tool_class is None:
        raise ValueError(f"Unknown tool: {tool_name}. Available: {list(TOOL_REGISTRY.keys())}")
    return tool_class()


def list_tools():
    """List all available seed planning tools."""
    return list(TOOL_REGISTRY.keys())


__all__ = [
    "BaseTool",
    "ToolResult",
    "SeedPlanningTool",
    "RuleBasedSeedPlanningTool",
    "RLSeedPlanningTool",
    "get_tool",
    "list_tools",
]
