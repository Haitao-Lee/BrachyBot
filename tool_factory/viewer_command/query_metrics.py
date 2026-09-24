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
from tool_factory.plan_shapes import normalize_plan_entries
from utils.planning_metrics import (
    extract_oar_dose_metrics,
    has_oar_dose_metrics,
    normalize_dose_metrics,
)

logger = logging.getLogger(__name__)

# What each metric result actually answers.  The runtime uses this to decide
# whether a typed read may replace the normal answer path: a total seed count
# must not silently stand in for a per-needle distribution question.
_METRIC_COVERAGE: Dict[str, tuple] = {
    "dose_metrics": ("dose",),
    "oar_dose_metrics": ("oar_dose",),
    "ctv_volume": ("ctv_volume",),
    "oar_volumes": ("oar_volume",),
    "seed_count": ("seed_total",),
    "needle_count": ("needle_count",),
    "needle_seed_counts": ("needle_count", "seed_total", "seeds_per_needle"),
    "hu_statistics": ("hu",),
    "spacing_info": ("spacing",),
    "all_metrics": (
        "dose", "ctv_volume", "oar_volume", "seed_total", "hu", "spacing",
    ),
    "planning_method": ("planning_method",),
}

# The published mirror is updated by both the automatic pipeline and every
# manual edit; the legacy aliases can lag behind it, so it must win.
_SEED_SOURCE_KEYS = ("seed_plan_serialized", "manual_seeds", "seed_plan", "seed_positions")


class QueryMetricsTool(BaseTool):
    """Query medical metrics from treatment plan data."""

    @staticmethod
    def _read_metadata(values: Dict[str, Any], metric_type: str) -> Dict[str, Any]:
        """Attach the read-only response contract to a metric snapshot.

        Metric queries read the active session; they never mutate planning
        state and never need a second model pass just to turn JSON into a
        user-facing table.  The contract is deliberately capability-based so
        callers can make that decision without matching user wording.  The
        ``covers`` list names the data aspects the payload answers so the
        runtime can require synthesis/review when the question asks for more.
        """
        metadata = dict(values or {})
        metadata["metric_type"] = metric_type
        contract = {
            "mode": "direct_read",
            "resource": f"session_metrics:{metric_type}",
            "source": "active_session",
            "requires_synthesis": False,
            "requires_review": False,
        }
        covers = _METRIC_COVERAGE.get(metric_type)
        if covers:
            resolved_covers = list(covers)
            # An aggregate read covers organ dose only when it actually
            # contains dose-bearing OAR rows. OAR volumes alone never satisfy
            # a dose question.
            if metric_type == "all_metrics" and has_oar_dose_metrics(metadata):
                resolved_covers.append("oar_dose")
            contract["covers"] = resolved_covers
        metadata["response_contract"] = contract
        return metadata

    def _resolved_seed_facts(self, kw) -> tuple:
        """Resolve (entries, seed total, needle count) from live plan data.

        A plan is stored as one entry per needle, so ``len(plan)`` is the
        needle count, never the seed count.  Structured geometry is preferred;
        the declared memory totals are the fallback for geometry-less states.
        """
        entries = []
        for key in _SEED_SOURCE_KEYS:
            entries = normalize_plan_entries(kw.get(key))
            if entries:
                break
        structured_seeds = sum(entry["seed_count"] for entry in entries)
        structured_needles = len(entries)
        declared_seeds = self._declared_total(kw.get("total_seeds"))
        declared_needles = self._declared_total(kw.get("num_trajectories"))
        seed_total = structured_seeds if structured_seeds > 0 else declared_seeds
        needle_count = structured_needles if structured_needles > 0 else declared_needles
        return entries, seed_total, needle_count

    @staticmethod
    def _declared_total(value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        return number if number > 0 else 0

    @property
    def name(self) -> str:
        return "query_metrics"

    @property
    def description(self) -> str:
        return (
            "Query dose metrics (V100, D90, V150, V200), plan quality, CTV/OAR volumes, "
            "seed count, needle count, per-needle seed counts, HU statistics. "
            "Use metric_type='oar_dose_metrics' for the actual per-organ dose/DVH "
            "table (Dmax, D0.1cc, D1cc, D2cc, Dmean, V100/V150 where available); "
            "do not substitute OAR volumes for dose. Use 'dose_metrics' for CTV "
            "coverage metrics. "
            "Use metric_type='seed_count' for the total number of seeds, "
            "'needle_count' for how many needles/trajectories were planned, and "
            "'needle_seed_counts' when the user asks how many needles exist or how "
            "many seeds are on each needle. The agent passes data from memory via kwargs. "
            "Use when user asks about plan quality, dose coverage, organ doses, etc. "
            "For questions about which algorithm, mode, method, or planning run "
            "produced the result (for example RL versus rule-based, fallback "
            "provenance, why a method was chosen), use metric_type='planning_method' "
            "and compose the answer from those facts — never answer a method "
            "question with a dose-metrics table."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "metric_type": {
                    "type": "string",
                    "enum": ["dose_metrics", "oar_dose_metrics", "ctv_volume", "oar_volumes", "seed_count",
                             "needle_count", "needle_seed_counts",
                             "hu_statistics", "spacing_info", "plan_score",
                             "planning_method", "all_metrics"],
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
                "planning_method": {
                    "type": "object",
                    "description": "Planning mode/algorithm provenance facts from the active workspace",
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
                "num_trajectories": {
                    "type": "integer",
                    "description": "Planned needle/trajectory count from the active workspace",
                    "x-server-injected": True,
                },
                "seed_plan_serialized": {
                    "type": "array",
                    "description": "Published per-needle plan mirror from the active workspace",
                    "x-server-injected": True,
                },
                "manual_seeds": {
                    "type": "array",
                    "description": "Manual seed records from the active workspace",
                    "x-server-injected": True,
                },
                "seed_plan": {
                    "type": "array",
                    "description": "Optimizer plan entries from the active workspace",
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
            elif metric_type == "oar_dose_metrics":
                return self._get_oar_dose_metrics(kwargs)
            elif metric_type == "ctv_volume":
                return self._get_ctv_volume(kwargs)
            elif metric_type == "oar_volumes":
                return self._get_oar_volumes(kwargs)
            elif metric_type == "seed_count":
                return self._get_seed_count(kwargs)
            elif metric_type == "needle_count":
                return self._get_needle_count(kwargs)
            elif metric_type == "needle_seed_counts":
                return self._get_needle_seed_counts(kwargs)
            elif metric_type == "hu_statistics":
                return self._get_hu_statistics(kwargs)
            elif metric_type == "spacing_info":
                return self._get_spacing_info(kwargs)
            elif metric_type == "planning_method":
                return self._get_planning_method(kwargs)
            elif metric_type == "all_metrics":
                return self._get_all_metrics(kwargs)
            else:
                return self._get_all_metrics(kwargs)
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"Query failed: {e}")

    def _get_dose_metrics(self, kw) -> ToolResult:
        metrics = normalize_dose_metrics(kw.get("metrics", {}))
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

    def _get_oar_dose_metrics(self, kw) -> ToolResult:
        metrics = normalize_dose_metrics(kw.get("metrics", {}))
        oars = extract_oar_dose_metrics(metrics)
        if not oars:
            return ToolResult(
                success=False,
                error="No active OAR dose metrics",
                message=(
                    "No per-organ dose/DVH results are saved for the active Planning. "
                    "OAR structure volumes are not dose measurements."
                ),
            )
        values = {"oar_metrics": oars, "organ_count": len(oars)}
        return ToolResult(
            success=True,
            data=values,
            message=f"Read dose/DVH metrics for {len(oars)} OAR structures.",
            metadata=self._read_metadata(values, "oar_dose_metrics"),
        )

    def _get_planning_method(self, kw) -> ToolResult:
        """Report which algorithm/method actually produced the active plan.

        Method questions ("基于RL的还是规则-based的") must be answered from
        the persisted execution facts — requested mode, effective mode, and
        the rule-based fallback record — not from a dose-metrics table.
        """
        facts = kw.get("planning_method")
        facts = dict(facts) if isinstance(facts, dict) else {}
        if not any(facts.get(key) is not None for key in (
            "requested_mode", "effective_mode", "rl_fallback_used",
        )):
            return ToolResult(
                success=False,
                error="No planning method facts",
                message=("No planning-method facts available for the active "
                         "plan; the planning run did not persist its mode."),
            )
        rl_status = facts.get("rl_status")
        facts["rl_status"] = (
            dict(rl_status) if isinstance(rl_status, dict) else {}
        )
        requested = facts.get("requested_mode") or facts.get("mode") or "unknown"
        effective = facts.get("effective_mode") or requested
        lines = [
            "## Planning method / algorithm of the active plan",
            "",
            f"- requested_mode: `{requested}`",
            f"- effective_mode: `{effective}`",
        ]
        if facts.get("rl_fallback_used"):
            lines.append(
                "- rule-based fallback: used"
                + (f" (reason: `{facts.get('rl_fallback_reason')}`)"
                   if facts.get("rl_fallback_reason") else "")
            )
        for key in ("execution", "stop_reason", "best_coverage",
                    "target_coverage"):
            if facts["rl_status"].get(key) is not None:
                lines.append(f"- rl_status.{key}: {facts['rl_status'][key]}")
        return ToolResult(
            success=True,
            data=facts,
            message="\n".join(lines),
            metadata=self._read_metadata(facts, "planning_method"),
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
        # A plan container holds one entry per needle; counting the container
        # itself reported the needle count as the seed count.  Resolve the
        # actual seed records first and use the declared total only as a
        # fallback for geometry-less states.
        _entries, count, _needles = self._resolved_seed_facts(kw)
        return ToolResult(
            success=True,
            data={"seed_count": count},
            message=f"Total seeds: {count}",
            metadata=self._read_metadata({"seed_count": count}, "seed_count"),
        )

    def _get_needle_count(self, kw) -> ToolResult:
        _entries, _seeds, needle_count = self._resolved_seed_facts(kw)
        return ToolResult(
            success=True,
            data={"needle_count": needle_count},
            message=f"Total needles: {needle_count}",
            metadata=self._read_metadata({"needle_count": needle_count}, "needle_count"),
        )

    def _get_needle_seed_counts(self, kw) -> ToolResult:
        entries, seed_total, needle_count = self._resolved_seed_facts(kw)
        per_needle = []
        for index, entry in enumerate(entries, start=1):
            row: Dict[str, Any] = {"index": index, "seed_count": int(entry["seed_count"])}
            if entry.get("needle_id"):
                row["needle_id"] = str(entry["needle_id"])
            per_needle.append(row)
        values = {
            "needle_count": needle_count,
            "total_seeds": seed_total,
            "per_needle": per_needle,
        }
        return ToolResult(
            success=True,
            data=values,
            message=f"{needle_count} needles, {seed_total} seeds total",
            metadata=self._read_metadata(values, "needle_seed_counts"),
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
