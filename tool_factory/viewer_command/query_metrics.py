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

    @staticmethod
    def _read_metadata(values: Dict[str, Any], metric_type: str) -> Dict[str, Any]:
        """Attach the read-only response contract to a metric snapshot.

        Metric queries read the active session; they never mutate planning
        state and never need a second model pass just to turn JSON into a
        user-facing table.  The contract is deliberately capability-based so
        callers can make that decision without matching user wording.
        """
        metadata = dict(values or {})
        metadata["metric_type"] = metric_type
        metadata["response_contract"] = {
            "mode": "direct_read",
            "resource": f"session_metrics:{metric_type}",
            "source": "active_session",
            "requires_synthesis": False,
            "requires_review": False,
        }
        return metadata

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
                # These values belong to the active workspace and are
                # injected by AgenticSys immediately before execution. They
                # are intentionally excluded from the provider schema and
                # from ordinary JSON type validation; accepting a model's
                # serialized NumPy array here was the source of the
                # ``Invalid parameter type for ctv_array`` failure.
                "metrics": {
                    "type": "object",
                    "description": "Dose metrics dict from the active workspace",
                    "x-server-injected": True,
                },
                "ctv_array": {
                    "type": "object",
                    "description": "CTV segmentation array from the active workspace",
                    "x-server-injected": True,
                },
                "oar_array": {
                    "type": "object",
                    "description": "OAR segmentation array from the active workspace",
                    "x-server-injected": True,
                },
                "organ_names": {
                    "type": "object",
                    "description": "Organ name mapping from the active workspace",
                    "x-server-injected": True,
                },
                "ct_spacing": {
                    "type": "array",
                    "description": "CT voxel spacing from the active workspace",
                    "x-server-injected": True,
                },
                "ct_data": {
                    "type": "object",
                    "description": "CT image data from the active workspace",
                    "x-server-injected": True,
                },
                "seed_positions": {
                    "type": "array",
                    "description": "Seed positions from the active workspace",
                    "x-server-injected": True,
                },
                "total_seeds": {
                    "type": "integer",
                    "description": "Total seed count from the active workspace",
                    "x-server-injected": True,
                },
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

        def _first(*keys, default="N/A"):
            for key in keys:
                value = metrics.get(key)
                if value is not None:
                    return value
            return default

        # Preserve the complete normalized dose contract. Older callers only
        # received V100/V150/V200/D90, which made a follow-up dose question
        # lose Dmean, D2, CI/HI, plan score, prescription, and OAR metrics.
        dose = {
            "V100": _first("v100", "V100"),
            "V150": _first("v150", "V150"),
            "V200": _first("v200", "V200"),
            "D90": _first("d90", "D90"),
            "D95": _first("d95", "D95"),
            "Dmean": _first("dmean", "Dmean", "mean_dose"),
            "D2": _first("d2", "D2", "d2cc", "D2cc"),
            "Dmax": _first("dmax", "Dmax", "max_dose"),
            "CI": _first("ci", "CI"),
            "HI": _first("hi", "HI"),
            "plan_score": _first("plan_score", "score"),
            "prescription_gy": _first("prescription_gy", "prescribed_dose"),
            "oar_metrics": metrics.get("oar_metrics", {}),
        }
        return ToolResult(
            success=True,
            data=dose,
            message=json.dumps(dose, indent=2),
            metadata=self._read_metadata(dose, "dose_metrics"),
        )

    def _get_ctv_volume(self, kw) -> ToolResult:
        import numpy as np
        ctv = kw.get("ctv_array")
        if ctv is None:
            return ToolResult(success=False, error="No CTV", message="No CTV segmentation found.")
        spacing = kw.get("ct_spacing", [1, 1, 1])
        vol = int(np.sum(ctv > 0)) * float(np.prod(spacing)) / 1000
        metadata = self._read_metadata({"volume_cm3": round(vol, 1)}, "ctv_volume")
        return ToolResult(success=True, message=f"CTV volume: {vol:.1f} cm³",
                        metadata=metadata)

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
        return ToolResult(
            success=True,
            data=volumes,
            message=json.dumps(volumes, indent=2),
            metadata=self._read_metadata(volumes, "oar_volumes"),
        )

    def _get_seed_count(self, kw) -> ToolResult:
        seeds = kw.get("seed_positions", [])
        total = kw.get("total_seeds", 0)
        # NumPy arrays do not have a scalar truth value.  Use an explicit
        # length check so live planning arrays and serialized lists behave the
        # same way when the metrics tool is called from the agent bridge.
        try:
            seed_count = len(seeds) if seeds is not None else 0
        except TypeError:
            seed_count = 0
        count = seed_count if seed_count > 0 else total
        return ToolResult(
            success=True,
            message=f"Total seeds: {count}",
            metadata=self._read_metadata({"seed_count": count}, "seed_count"),
        )

    def _get_hu_statistics(self, kw) -> ToolResult:
        import numpy as np
        ct = kw.get("ct_data")
        if ct is None:
            return ToolResult(success=False, error="No CT", message="No CT image loaded.")
        stats = {"hu_min": int(ct.min()), "hu_max": int(ct.max()),
                 "hu_mean": round(float(ct.mean()), 1), "shape": list(ct.shape)}
        return ToolResult(
            success=True,
            data=stats,
            message=json.dumps(stats, indent=2),
            metadata=self._read_metadata(stats, "hu_statistics"),
        )

    def _get_spacing_info(self, kw) -> ToolResult:
        sp = kw.get("ct_spacing", [1, 1, 1])
        info = {"spacing_x": round(sp[0], 2), "spacing_y": round(sp[1], 2), "spacing_z": round(sp[2], 2)}
        return ToolResult(
            success=True,
            data=info,
            message=json.dumps(info, indent=2),
            metadata=self._read_metadata(info, "spacing_info"),
        )

    def _get_all_metrics(self, kw) -> ToolResult:
        result = {}
        unavailable = {}
        getters = [
            ("dose_metrics", self._get_dose_metrics),
            ("ctv_volume", self._get_ctv_volume),
            ("oar_volumes", self._get_oar_volumes),
            ("seed_count", self._get_seed_count),
            ("hu_statistics", self._get_hu_statistics),
            ("spacing_info", self._get_spacing_info),
        ]
        for label, getter in getters:
            try:
                r = getter(kw)
                if r.success and r.metadata:
                    # Each child carries its own response contract.  Keep
                    # the useful flat fields for existing callers, while
                    # avoiding the last child's metric_type overwriting the
                    # aggregate type.
                    result.update({
                        key: value
                        for key, value in r.metadata.items()
                        if key not in {"metric_type", "response_contract"}
                    })
                else:
                    unavailable[label] = str(
                        r.error or r.message or "Metric is unavailable"
                    )
            except Exception as exc:
                logger.warning("Metric getter %s failed: %s", getattr(getter, "__name__", getter), exc)
                unavailable[label] = str(exc)

        # ``all_metrics`` is a read operation: a missing CT, CTV, or OAR
        # should be reported as a structured absence, not converted into a
        # misleading successful-looking partial answer or a parameter-type
        # exception.  Keep the flat fields above for backwards compatibility.
        payload = {"available": result, "unavailable": unavailable}
        metadata = self._read_metadata(result, "all_metrics")
        if unavailable:
            metadata["unavailable"] = dict(unavailable)
        result_with_status = dict(result)
        if unavailable:
            result_with_status["_missing"] = dict(unavailable)
        return ToolResult(
            success=True,
            data=result_with_status,
            message=json.dumps(payload, indent=2),
            metadata=metadata,
        )
