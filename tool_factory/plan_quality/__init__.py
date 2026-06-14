"""
Plan Quality Tools
================
Tools for evaluating and refining plan quality.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tool_factory import BaseTool, ToolResult

from .plan_quality_scorer import PlanQualityScorerTool
from .oar_constraint_checker import OARConstraintCheckerTool
from .plan_refinement import PlanRefinementTool
from .clinical_standards import (
    TARGET_STANDARDS,
    OAR_STANDARDS,
    WEIGHTS,
    REPLAN_TRIGGER_SCORE,
    REPLAN_TRIGGER_VIOLATIONS,
    get_target_standard,
    get_oar_standard,
    composite_score,
    should_replan,
)

__all__ = [
    "BaseTool", "ToolResult",
    "PlanQualityScorerTool", "OARConstraintCheckerTool", "PlanRefinementTool",
    "TARGET_STANDARDS", "OAR_STANDARDS", "WEIGHTS",
    "REPLAN_TRIGGER_SCORE", "REPLAN_TRIGGER_VIOLATIONS",
    "get_target_standard", "get_oar_standard", "composite_score", "should_replan",
]