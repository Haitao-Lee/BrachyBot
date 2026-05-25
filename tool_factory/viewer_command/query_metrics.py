"""
Query Metrics Tool
==================
Query and display various medical metrics, dose statistics, and plan quality indicators.
"""

import os
import sys
import json
import logging
import requests
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8080/api"


class QueryMetricsTool(BaseTool):
    """Query medical metrics and plan quality indicators."""

    @property
    def name(self) -> str:
        return "query_metrics"

    @property
    def description(self) -> str:
        return (
            "Query various medical metrics and plan quality indicators. "
            "Metrics: dose_metrics (V100, D90, etc.), oar_constraints, plan_score, "
            "ctv_volume, oar_volumes, seed_count, dvh_data, hu_statistics, spacing_info. "
            "Use this when the user asks about plan quality, dose coverage, organ doses, etc."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "metric_type": {
                    "type": "string",
                    "description": "Type of metric to query",
                    "enum": [
                        "dose_metrics",
                        "oar_constraints",
                        "plan_score",
                        "ctv_volume",
                        "oar_volumes",
                        "seed_count",
                        "dvh_data",
                        "hu_statistics",
                        "spacing_info",
                        "all_metrics"
                    ]
                },
                "organ_name": {
                    "type": "string",
                    "description": "For OAR metrics: specific organ name"
                }
            },
            "required": ["metric_type"]
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "metrics": {"type": "object"},
                "message": {"type": "string"}
            }
        }

    def _execute(self, **kwargs) -> ToolResult:
        """Query metrics."""
        metric_type = kwargs.get("metric_type", "all_metrics")
        organ_name = kwargs.get("organ_name")

        try:
            if metric_type == "dose_metrics":
                return self._get_dose_metrics()
            elif metric_type == "oar_constraints":
                return self._get_oar_constraints(organ_name)
            elif metric_type == "plan_score":
                return self._get_plan_score()
            elif metric_type == "ctv_volume":
                return self._get_ctv_volume()
            elif metric_type == "oar_volumes":
                return self._get_oar_volumes()
            elif metric_type == "seed_count":
                return self._get_seed_count()
            elif metric_type == "dvh_data":
                return self._get_dvh_data()
            elif metric_type == "hu_statistics":
                return self._get_hu_statistics()
            elif metric_type == "spacing_info":
                return self._get_spacing_info()
            elif metric_type == "all_metrics":
                return self._get_all_metrics()
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown metric type: {metric_type}",
                    message=f"Unknown metric type: {metric_type}"
                )
        except Exception as e:
            logger.error(f"Query metrics failed: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Query metrics failed: {e}"
            )

    def _get_dose_metrics(self) -> ToolResult:
        """Get dose metrics (V100, V150, V200, D90, D95)."""
        res = requests.post(f"{API_BASE}/viewer/control", json={"action": "get_state"})
        if not res.ok:
            return ToolResult(success=False, error="Failed to get state", message="Failed to get state")

        state = res.json()
        metrics = state.get("metrics", {})

        dose_metrics = {
            "V100": metrics.get("V100", "N/A"),
            "V150": metrics.get("V150", "N/A"),
            "V200": metrics.get("V200", "N/A"),
            "D90": metrics.get("D90", "N/A"),
            "D95": metrics.get("D95", "N/A"),
            "D100": metrics.get("D100", "N/A")
        }

        return ToolResult(
            success=True,
            message=json.dumps(dose_metrics, indent=2),
            metadata=dose_metrics
        )

    def _get_oar_constraints(self, organ_name: Optional[str] = None) -> ToolResult:
        """Get OAR dose constraints."""
        # This would need to query the actual plan data
        # For now, return placeholder
        constraints = {
            "rectum": {"D2cc": "N/A", "V75": "N/A"},
            "bladder": {"D2cc": "N/A", "V80": "N/A"},
            "urethra": {"D10": "N/A", "V150": "N/A"}
        }

        if organ_name:
            result = constraints.get(organ_name.lower(), {})
            return ToolResult(
                success=True,
                message=json.dumps({organ_name: result}, indent=2),
                metadata={organ_name: result}
            )

        return ToolResult(
            success=True,
            message=json.dumps(constraints, indent=2),
            metadata=constraints
        )

    def _get_plan_score(self) -> ToolResult:
        """Get overall plan quality score."""
        res = requests.post(f"{API_BASE}/viewer/control", json={"action": "get_state"})
        if not res.ok:
            return ToolResult(success=False, error="Failed to get state", message="Failed to get state")

        state = res.json()
        score = state.get("plan_score", "N/A")

        return ToolResult(
            success=True,
            message=f"Plan quality score: {score}",
            metadata={"plan_score": score}
        )

    def _get_ctv_volume(self) -> ToolResult:
        """Get CTV volume."""
        res = requests.post(f"{API_BASE}/viewer/control", json={"action": "get_state"})
        if not res.ok:
            return ToolResult(success=False, error="Failed to get state", message="Failed to get state")

        state = res.json()
        volume = state.get("ctv_volume", "N/A")

        return ToolResult(
            success=True,
            message=f"CTV volume: {volume} cc",
            metadata={"ctv_volume": volume}
        )

    def _get_oar_volumes(self) -> ToolResult:
        """Get OAR volumes."""
        res = requests.post(f"{API_BASE}/viewer/control", json={"action": "get_state"})
        if not res.ok:
            return ToolResult(success=False, error="Failed to get state", message="Failed to get state")

        state = res.json()
        volumes = state.get("oar_volumes", {})

        return ToolResult(
            success=True,
            message=json.dumps(volumes, indent=2),
            metadata=volumes
        )

    def _get_seed_count(self) -> ToolResult:
        """Get seed count."""
        res = requests.post(f"{API_BASE}/viewer/control", json={"action": "get_state"})
        if not res.ok:
            return ToolResult(success=False, error="Failed to get state", message="Failed to get state")

        state = res.json()
        count = state.get("seed_count", "N/A")

        return ToolResult(
            success=True,
            message=f"Total seeds: {count}",
            metadata={"seed_count": count}
        )

    def _get_dvh_data(self) -> ToolResult:
        """Get DVH data."""
        res = requests.post(f"{API_BASE}/viewer/control", json={"action": "get_state"})
        if not res.ok:
            return ToolResult(success=False, error="Failed to get state", message="Failed to get state")

        state = res.json()
        dvh = state.get("dvh_data", {})

        return ToolResult(
            success=True,
            message=json.dumps(dvh, indent=2),
            metadata=dvh
        )

    def _get_hu_statistics(self) -> ToolResult:
        """Get HU statistics of loaded CT."""
        res = requests.post(f"{API_BASE}/viewer/control", json={"action": "get_state"})
        if not res.ok:
            return ToolResult(success=False, error="Failed to get state", message="Failed to get state")

        state = res.json()
        hu_range = state.get("hu_range", [])
        spacing = state.get("spacing", [])
        shape = state.get("shape", [])

        stats = {
            "hu_min": hu_range[0] if len(hu_range) > 0 else "N/A",
            "hu_max": hu_range[1] if len(hu_range) > 1 else "N/A",
            "shape": shape,
            "spacing": spacing
        }

        return ToolResult(
            success=True,
            message=json.dumps(stats, indent=2),
            metadata=stats
        )

    def _get_spacing_info(self) -> ToolResult:
        """Get CT spacing information."""
        res = requests.post(f"{API_BASE}/viewer/control", json={"action": "get_state"})
        if not res.ok:
            return ToolResult(success=False, error="Failed to get state", message="Failed to get state")

        state = res.json()
        spacing = state.get("spacing", [])

        info = {
            "spacing_x": spacing[0] if len(spacing) > 0 else "N/A",
            "spacing_y": spacing[1] if len(spacing) > 1 else "N/A",
            "spacing_z": spacing[2] if len(spacing) > 2 else "N/A",
            "isotropic_xy": abs(spacing[0] - spacing[1]) < 0.01 if len(spacing) > 1 else False
        }

        return ToolResult(
            success=True,
            message=json.dumps(info, indent=2),
            metadata=info
        )

    def _get_all_metrics(self) -> ToolResult:
        """Get all available metrics."""
        res = requests.post(f"{API_BASE}/viewer/control", json={"action": "get_state"})
        if not res.ok:
            return ToolResult(success=False, error="Failed to get state", message="Failed to get state")

        state = res.json()

        all_metrics = {
            "dose_metrics": {
                "V100": state.get("metrics", {}).get("V100", "N/A"),
                "V150": state.get("metrics", {}).get("V150", "N/A"),
                "V200": state.get("metrics", {}).get("V200", "N/A"),
                "D90": state.get("metrics", {}).get("D90", "N/A"),
                "D95": state.get("metrics", {}).get("D95", "N/A")
            },
            "plan_score": state.get("plan_score", "N/A"),
            "ctv_volume": state.get("ctv_volume", "N/A"),
            "seed_count": state.get("seed_count", "N/A"),
            "hu_range": state.get("hu_range", []),
            "spacing": state.get("spacing", []),
            "shape": state.get("shape", [])
        }

        return ToolResult(
            success=True,
            message=json.dumps(all_metrics, indent=2),
            metadata=all_metrics
        )


if __name__ == "__main__":
    tool = QueryMetricsTool()
    print(f"Tool: {tool.name}")
    print(f"Description: {tool.description}")
