"""
Dose Evaluation Tools
====================
Comprehensive dose metrics calculation tools for brachytherapy planning.
Includes Vx, Dx, absolute dose metrics, DVH curves, and plan quality scoring.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tool_factory import BaseTool, ToolResult

from .vx_metrics import VxMetricsTool
from .dx_metrics import DxMetricsTool
from .absolute_dose_metrics import AbsoluteDoseMetricsTool
from .dvh_calculation import DVHCalculationTool
from .comprehensive_dose_evaluation import ComprehensiveDoseEvaluationTool


TOOL_REGISTRY = {
    "vx_metrics": VxMetricsTool,
    "dx_metrics": DxMetricsTool,
    "absolute_dose_metrics": AbsoluteDoseMetricsTool,
    "dvh_calculation": DVHCalculationTool,
    "comprehensive_dose_evaluation": ComprehensiveDoseEvaluationTool,
}


def get_tool(tool_name: str):
    """Get a dose evaluation tool by name."""
    tool_class = TOOL_REGISTRY.get(tool_name)
    if tool_class is None:
        raise ValueError(f"Unknown tool: {tool_name}. Available: {list(TOOL_REGISTRY.keys())}")
    return tool_class()


def list_tools():
    """List all available dose evaluation tools."""
    return list(TOOL_REGISTRY.keys())


class DoseEvaluationTool(BaseTool):
    """
    Unified dose evaluation tool that wraps comprehensive dose metrics.

    Provides complete dose plan quality assessment including Vx, Dx,
    absolute dose metrics, DVH curves, and plan quality score.
    """

    @property
    def name(self) -> str:
        return "dose_evaluation"

    @property
    def description(self) -> str:
        return (
            "Comprehensive dose evaluation for brachytherapy planning. "
            "Computes Vx metrics (V100, V150, V200), Dx metrics (D90, D95, D99), "
            "absolute dose metrics (Dmax, Dmean, D2cc), DVH curves, and plan quality score. "
            "Input: 3D dose array, CTV/OAR masks, prescribed dose. "
            "Output: Complete metrics dictionary and plan quality assessment."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "dose_array": {"type": "array", "description": "3D NumPy array of dose distribution in Gy"},
                "ctv_mask": {"type": "array", "description": "CTV binary mask array"},
                "oar_mask": {"type": "array", "description": "OAR multi-label mask array (optional)"},
                "prescribed_dose": {"type": "number", "default": 1.0, "description": "Prescribed dose in Gy"},
                "target_value": {"type": "number", "default": 1, "description": "CTV label value"},
                "oar_constraints": {"type": "object", "description": "OAR dose constraints dict"},
            },
            "required": ["dose_array", "ctv_mask"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "v100": {"type": "number", "description": "Fraction of CTV receiving >= prescribed dose"},
                "v150": {"type": "number", "description": "Fraction of CTV receiving >= 1.5x prescribed dose"},
                "v200": {"type": "number", "description": "Fraction of CTV receiving >= 2.0x prescribed dose"},
                "d90": {"type": "number", "description": "Dose covering 90% of CTV in Gy"},
                "d95": {"type": "number", "description": "Dose covering 95% of CTV in Gy"},
                "d99": {"type": "number", "description": "Dose covering 99% of CTV in Gy"},
                "plan_score": {"type": "number", "description": "Overall plan quality score (0-100)"},
                "oar_metrics": {"type": "object", "description": "Per-OAR dose metrics"},
                "dvh_data": {"type": "object", "description": "DVH curve data"},
            },
        }

    def _execute(self, **kwargs):
        import numpy as np

        dose_array = kwargs["dose_array"]
        ctv_mask = kwargs.get("ctv_mask")
        oar_mask = kwargs.get("oar_mask")
        prescribed_dose = kwargs.get("prescribed_dose", 1.0)
        target_value = kwargs.get("target_value", 1)
        oar_constraints = kwargs.get("oar_constraints", {})

        masks = {}
        if ctv_mask is not None:
            masks["CTV"] = ctv_mask
        if oar_mask is not None:
            unique_labels = np.unique(oar_mask)
            for label in unique_labels:
                if label > 0:
                    masks[f"OAR_{int(label)}"] = (oar_mask == label).astype(np.float32)

        tool = ComprehensiveDoseEvaluationTool()
        structure_type = {"CTV": "target"}
        for key in masks:
            if key.startswith("OAR"):
                structure_type[key] = "oar"
        result = tool._execute(
            dose_array=dose_array,
            masks=masks,
            prescribed_dose=prescribed_dose,
            structure_type=structure_type,
        )

        if not result.success:
            return result

        metrics = result.metadata.get("metrics", {})

        ctv_metrics = metrics.get("CTV", {})
        oar_metrics = {}
        for key, val in metrics.items():
            if key.startswith("OAR"):
                oar_metrics[key] = val

        return ToolResult(
            success=True,
            data=metrics,
            message=f"Dose evaluation completed. V100={ctv_metrics.get('V100', 0):.1%}, D90={ctv_metrics.get('D90', 0):.2f}Gy, Score={result.metadata.get('plan_score', 0):.0f}",
            metadata={
                "v100": ctv_metrics.get("V100", 0),
                "v150": ctv_metrics.get("V150", 0),
                "v200": ctv_metrics.get("V200", 0),
                "v90": ctv_metrics.get("V90", 0),
                "d90": ctv_metrics.get("D90", 0),
                "d95": ctv_metrics.get("D95", 0),
                "d99": ctv_metrics.get("D99", 0),
                "plan_score": result.metadata.get("plan_score", 0),
                "oar_metrics": oar_metrics,
                "oar_violations": result.metadata.get("oar_violations", []),
                "dvh_data": ctv_metrics.get("dvh", {}),
            },
        )


__all__ = [
    "BaseTool",
    "ToolResult",
    "VxMetricsTool",
    "DxMetricsTool",
    "AbsoluteDoseMetricsTool",
    "DVHCalculationTool",
    "ComprehensiveDoseEvaluationTool",
    "DoseEvaluationTool",
    "get_tool",
    "list_tools",
]