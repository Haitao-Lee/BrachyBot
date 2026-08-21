"""High-level current-Planning dose recomputation tool.

The low-level ``dose_engine`` tool intentionally exposes the model input
contract (a CT image and a normalized seed list).  That contract is useful
inside a pipeline, but it is the wrong interface for a conversational request
such as "recalculate the current dose".  This tool owns the application-level
contract: resolve the active persisted Planning, run the same authoritative
DoseUNet-backed manual dose path used by the Viewer, and persist the resulting
Dose/DVH state under that Planning.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from tool_factory import BaseTool, ToolResult


logger = logging.getLogger(__name__)


def _ensure_ct_runtime(agent: Any) -> None:
    """Rebuild the canonical CT memory fields when hydration restored only a path.

    Session hydration normally restores these fields from durable artifacts.
    The fallback is deliberately state-based rather than phrase-based: a
    restored Planning must remain usable even while the Viewer is still
    rebuilding its UI state.
    """
    memory = agent.memory
    ct_image = memory.retrieve("ct_image")
    ct_data = memory.retrieve("ct_data")
    if ct_image is not None and ct_data is not None:
        return

    import numpy as np
    import SimpleITK as sitk
    from utils.ct_volume import normalize_ct_image

    if ct_image is None:
        ui_state = memory.get_ui_state() if callable(getattr(memory, "get_ui_state", None)) else {}
        ui_state = ui_state or {}
        ct_path = memory.retrieve("ct_path") or ui_state.get("ct_path")
        if not ct_path:
            raise ValueError("No CT image is available in the current Session.")

        raw = sitk.ReadImage(str(ct_path))
        normalized, source_meta = normalize_ct_image(raw)
        if int(normalized.GetDimension()) != 3:
            raise ValueError("The current CT is not a scalar 3-D volume.")
        # Match the Viewer load path so masks, seeds, dose, and DVH share the
        # same LPI coordinate frame after a lazy post-hydration load.
        oriented = sitk.DICOMOrient(normalized, "LPI")
        memory.store("ct_image", oriented)
        if memory.retrieve("ct_image_raw") is None:
            memory.store("ct_image_raw", raw)
        meta = dict(memory.retrieve("ct_source_meta") or {})
        meta.update(source_meta or {})
        memory.store("ct_source_meta", meta)
        memory.store("ct_path", str(ct_path))
        ct_image = oriented

    if ct_data is None:
        ct_data = sitk.GetArrayFromImage(ct_image)
        memory.store("ct_data", ct_data)

    # The manual dose path consumes these geometry aliases directly.  Populate
    # only missing fields so a live Viewer state always remains authoritative.
    if memory.retrieve("ct_spacing") is None:
        memory.store("ct_spacing", tuple(float(v) for v in ct_image.GetSpacing()))
    if memory.retrieve("ct_origin") is None:
        memory.store("ct_origin", tuple(float(v) for v in ct_image.GetOrigin()))
    if memory.retrieve("ct_direction") is None:
        memory.store("ct_direction", tuple(float(v) for v in ct_image.GetDirection()))
    if memory.retrieve("ct_shape") is None:
        memory.store("ct_shape", [int(v) for v in np.asarray(ct_data).shape])
    if memory.retrieve("ct_window_center") is None:
        memory.store("ct_window_center", 40)
    if memory.retrieve("ct_window_width") is None:
        memory.store("ct_window_width", 400)


class CurrentPlanDoseRecomputeTool(BaseTool):
    """Recompute Dose and DVH for the active persisted Planning."""

    @property
    def name(self) -> str:
        return "dose_recompute"

    @property
    def description(self) -> str:
        return (
            "Recompute the dose distribution and DVH for the current active "
            "Planning using the authoritative persisted Needle/Seed geometry. "
            "Use this high-level tool when the user asks to recalculate, "
            "recompute, update, or refresh the current dose after Planning "
            "or manual geometry edits. Do not request raw CT or seed arrays: "
            "the server resolves them from the active Session and Planning. "
            "This does not rerun CTV/OAR segmentation or choose new needle "
            "paths. A successful recomputation updates Dose, DVH, metrics, "
            "Viewer state, and Session persistence; dependent Report and "
            "Surgical Guide artifacts are marked stale until regenerated."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "planning_id": {
                    "type": "string",
                    "description": "Optional active Planning ID; omit to use the currently displayed Planning.",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional internal-facing reason summary for the persisted operation.",
                },
            },
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "planning_id": {"type": "string"},
                "total_seeds": {"type": "integer"},
                "num_trajectories": {"type": "integer"},
                "metrics": {"type": "object"},
                "dvh_data": {"type": "object"},
                "artifact_status": {"type": "object"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        agent = kwargs.get("_agent")
        if agent is None or not hasattr(agent, "memory"):
            return ToolResult(
                success=False,
                error="The current Session agent is unavailable.",
            )

        memory = agent.memory
        language = str(getattr(memory, "user_lang", "en") or "en").lower()
        is_zh = language.startswith("zh")

        try:
            # Import the shared planning services lazily.  This keeps the tool
            # registry importable in lightweight unit tests and avoids a web
            # route import cycle during application startup.
            from web.planning_runs import (
                active_planning_id,
                list_planning_runs,
                publish_planning_run,
                restore_active_planning_aliases,
            )
            from web.routes.planning_routes import (
                _compute_manual_ai_dose,
                _current_planning_snapshot,
            )

            _ensure_ct_runtime(agent)
            restore_active_planning_aliases(memory)
            current_id = active_planning_id(memory)
            requested_id = str(kwargs.get("planning_id") or "").strip()
            if requested_id and requested_id != str(current_id or ""):
                message = (
                    f"请求的 Planning {requested_id} 不是当前显示的 Planning。请先切换到该 Planning 后再重算剂量。"
                    if is_zh
                    else f"Planning {requested_id} is not the active displayed Planning. Activate it before recalculating dose."
                )
                return ToolResult(success=False, error=message, message=message)

            if not current_id:
                message = (
                    "当前 Session 没有可用于剂量重算的 Planning 结果。请先完成一次粒子植入规划。"
                    if is_zh
                    else "The current Session has no Planning result available for dose recomputation. Complete a seed-implant plan first."
                )
                return ToolResult(
                    success=False,
                    error=message,
                    message=message,
                    metadata={"clarification_required": True},
                )

            current_summary = next(
                (
                    item
                    for item in list_planning_runs(memory)
                    if str(item.get("planning_id") or "") == str(current_id)
                ),
                {},
            )
            planning_label = str(
                current_summary.get("label") or current_id
            )
            snapshot = _current_planning_snapshot(agent)
            seeds = list(snapshot.get("seeds") or [])
            needles = list(snapshot.get("needles") or [])
            if not seeds or not needles:
                message = (
                    "当前 Planning 缺少可用的粒子或针道几何，暂时无法重算剂量。请先确认 Planning 结果已加载完成。"
                    if is_zh
                    else "The current Planning does not contain usable seed and needle geometry. Confirm that the Planning has finished loading, then retry."
                )
                return ToolResult(
                    success=False,
                    error=message,
                    message=message,
                    metadata={"clarification_required": True, "planning_id": current_id},
                )

            # Keep the recomputed artifacts in the current Planning namespace.
            # This is a dose refresh, not a new geometry/Planning version.
            if not memory.retrieve("manual_planning_id"):
                memory.store("manual_planning_id", str(current_id))

            payload = _compute_manual_ai_dose(
                agent,
                seeds,
                needles,
                previous_needles=None,
                previous_seeds=None,
                previous_dose=None,
            )
            payload = dict(payload or {})
            payload["planning_id"] = str(current_id)
            payload["reason"] = str(kwargs.get("reason") or "chat dose recomputation")

            # Publish only after all Dose/DVH/metric aliases have been written
            # by the shared computation path.  A failed inference therefore
            # cannot replace the last valid persisted Planning snapshot.
            result = ToolResult(
                success=True,
                data={
                    "planning_id": str(current_id),
                    "planning_label": planning_label,
                    "metrics": payload.get("metrics") or memory.retrieve("dose_metrics") or {},
                    "dvh_data": memory.retrieve("dvh_data") or {},
                    "artifact_status": payload.get("artifact_status") or memory.retrieve("manual_artifact_status") or {},
                },
                message=(
                    "已根据当前 Planning 重新计算剂量和 DVH。"
                    if is_zh
                    else "Dose and DVH were recomputed from the current Planning."
                ),
                metadata={
                    "planning_id": str(current_id),
                    "planning_label": planning_label,
                    "total_seeds": int(payload.get("total_seeds") or len(seeds)),
                    "num_trajectories": int(payload.get("num_trajectories") or len(needles)),
                    "metrics": payload.get("metrics") or memory.retrieve("dose_metrics") or {},
                    "artifact_status": payload.get("artifact_status") or memory.retrieve("manual_artifact_status") or {},
                    "dose_units": payload.get("dose_units") or memory.retrieve("dose_units"),
                    "dose_scale_gy": payload.get("dose_scale_gy") or memory.retrieve("dose_scale_gy"),
                    "dose_range_gy": payload.get("dose_range_gy"),
                },
            )
            publish_planning_run(agent, result, status="completed")
            return result
        except Exception as exc:
            logger.exception("Current Planning dose recomputation failed")
            message = (
                f"当前 Planning 的剂量重算失败：{exc}"
                if is_zh
                else f"Dose recomputation for the current Planning failed: {exc}"
            )
            return ToolResult(success=False, error=message, message=message)
