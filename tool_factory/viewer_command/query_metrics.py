"""
Query Metrics Tool
==================
Query dose metrics, plan quality, organ volumes.
Accepts data via kwargs (agent passes from memory).
"""

import os
import sys
import json
import logging
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class QueryMetricsTool(BaseTool):
    """Query medical metrics from treatment plan data."""

    @property
    def name(self) -> str:
        return "query_metrics"

    @property
    def description(self) -> str:
        return (
            "Query dose metrics (V100, D90, V150, V200), plan quality, CTV/OAR volumes, "
            "seed count, HU statistics. The agent passes data from memory via kwargs. "
            "Use when user asks about plan quality, dose coverage, organ doses, etc."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "metric_type": {
                    "type": "string",
                    "enum": ["dose_metrics", "ctv_volume", "oar_volumes", "seed_count",
                             "hu_statistics", "spacing_info", "plan_score", "all_metrics"],
                    "description": "Type of metric to query"
                },
                "metrics": {"type": "object", "description": "Dose metrics dict from memory"},
                "ctv_array": {"type": "object", "description": "CTV segmentation array"},
                "oar_array": {"type": "object", "description": "OAR segmentation array"},
                "organ_names": {"type": "object", "description": "Organ name mapping"},
                "ct_spacing": {"type": "array", "description": "CT voxel spacing"},
                "ct_data": {"type": "object", "description": "CT image data"},
                "seed_positions": {"type": "array", "description": "Seed positions"},
                "total_seeds": {"type": "integer", "description": "Total seed count"},
            },
            "required": ["metric_type"]
        }

    def _execute(self, **kwargs) -> ToolResult:
        metric_type = kwargs.get("metric_type", "all_metrics")

        try:
            if metric_type == "dose_metrics":
                return self._get_dose_metrics(kwargs)
            elif metric_type == "ctv_volume":
                return self._get_ctv_volume(kwargs)
            elif metric_type == "oar_volumes":
                return self._get_oar_volumes(kwargs)
            elif metric_type == "seed_count":
                return self._get_seed_count(kwargs)
            elif metric_type == "hu_statistics":
                return self._get_hu_statistics(kwargs)
            elif metric_type == "spacing_info":
                return self._get_spacing_info(kwargs)
            elif metric_type == "all_metrics":
                return self._get_all_metrics(kwargs)
            else:
                return self._get_all_metrics(kwargs)
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"Query failed: {e}")

    def _get_dose_metrics(self, kw) -> ToolResult:
        metrics = kw.get("metrics", {})
        if not metrics:
            return ToolResult(success=False, error="No metrics",
                            message="No dose metrics available. Run dose evaluation first.")
        dose = {
            "V100": metrics.get("v100", "N/A"),
            "V150": metrics.get("v150", "N/A"),
            "V200": metrics.get("v200", "N/A"),
            "D90": metrics.get("d90", "N/A"),
        }
        return ToolResult(success=True, message=json.dumps(dose, indent=2), metadata=dose)

    def _get_ctv_volume(self, kw) -> ToolResult:
        import numpy as np
        ctv = kw.get("ctv_array")
        if ctv is None:
            return ToolResult(success=False, error="No CTV", message="No CTV segmentation found.")
        spacing = kw.get("ct_spacing", [1, 1, 1])
        vol = int(np.sum(ctv > 0)) * float(np.prod(spacing)) / 1000
        return ToolResult(success=True, message=f"CTV volume: {vol:.1f} cm³",
                        metadata={"volume_cm3": round(vol, 1)})

    def _get_oar_volumes(self, kw) -> ToolResult:
        import numpy as np
        oar = kw.get("oar_array")
        names = kw.get("organ_names", {})
        if oar is None:
            return ToolResult(success=False, error="No OAR", message="No OAR segmentation found.")
        spacing = kw.get("ct_spacing", [1, 1, 1])
        voxel_vol = float(np.prod(spacing))
        volumes = {}
        for lid in np.unique(oar):
            if lid > 0:
                name = names.get(int(lid), names.get(str(int(lid)), f"organ_{int(lid)}"))
                volumes[name] = round(int(np.sum(oar == lid)) * voxel_vol / 1000, 2)
        return ToolResult(success=True, message=json.dumps(volumes, indent=2), metadata=volumes)

    def _get_seed_count(self, kw) -> ToolResult:
        seeds = kw.get("seed_positions", [])
        total = kw.get("total_seeds", 0)
        count = len(seeds) if seeds else total
        return ToolResult(success=True, message=f"Total seeds: {count}", metadata={"seed_count": count})

    def _get_hu_statistics(self, kw) -> ToolResult:
        import numpy as np
        ct = kw.get("ct_data")
        if ct is None:
            return ToolResult(success=False, error="No CT", message="No CT image loaded.")
        stats = {"hu_min": int(ct.min()), "hu_max": int(ct.max()),
                 "hu_mean": round(float(ct.mean()), 1), "shape": list(ct.shape)}
        return ToolResult(success=True, message=json.dumps(stats, indent=2), metadata=stats)

    def _get_spacing_info(self, kw) -> ToolResult:
        sp = kw.get("ct_spacing", [1, 1, 1])
        info = {"spacing_x": round(sp[0], 2), "spacing_y": round(sp[1], 2), "spacing_z": round(sp[2], 2)}
        return ToolResult(success=True, message=json.dumps(info, indent=2), metadata=info)

    def _get_all_metrics(self, kw) -> ToolResult:
        result = {}
        for getter in [self._get_dose_metrics, self._get_ctv_volume, self._get_seed_count,
                       self._get_hu_statistics, self._get_spacing_info]:
            try:
                r = getter(kw)
                if r.success and r.metadata:
                    result.update(r.metadata)
            except Exception as exc:
                logger.warning("Metric getter %s failed: %s", getattr(getter, "__name__", getter), exc)
        return ToolResult(success=True, message=json.dumps(result, indent=2), metadata=result)
