"""Detached numerical pipeline execution for one captured timepoint.

No active global memory is swapped. A scoped job cannot publish into a tab
selected later, and failed computations do not overwrite the saved clinical
state. This internal executor is not a blanket admission for legacy APIs.
"""
import copy
from types import SimpleNamespace
from collections.abc import Mapping

from web.timepoints import TimepointConflict, TimepointError


class ScopedPipelineExecutor:
    def __init__(self, session_agent):
        self.control_agent = session_agent
        self.store = getattr(session_agent, "_workspace_store", None)
        self.config = getattr(session_agent, "config", {}) or {}
        self.owner = self.config.get("_workspace_owner_id")
        self.session = self.config.get("_workspace_session_id")
        if self.store is None or not self.owner or not self.session:
            raise TimepointError("An authenticated shared Session agent is required")

    def execute(self, target_timepoint_id, *, step="full", mode="rule_based", planning_params=None,
                ref_direc=None, seed_info=None, step_callback=None, preview_callback=None):
        from agent_runtime.core import AgentMemory
        from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
        from web.guide_service import GuidePlacementService
        from utils.tool_security import tool_scope
        context = self.store.capture_timepoint_context(self.owner, self.session, target_timepoint_id)
        if context.target.legacy_default:
            raise TimepointError("The default uses the existing guarded execution path until runtime migration is complete")
        snapshot = self.store.load_timepoint_snapshot(self.owner, self.session, target_timepoint_id, decode_arrays=True)
        original = (snapshot.get("agent") or {}).get("planning_results") or {}
        if not isinstance(original, Mapping):
            raise TimepointError("Saved clinical state is unavailable")
        # Clinical arrays are decoded off the memory lock. The execution owns
        # new containers, and all input arrays are read-only until replaced.
        memory = AgentMemory(self.session)
        def detached(value):
            import numpy as np
            if isinstance(value, np.ndarray):
                result = value.view()
                result.flags.writeable = False
                return result
            if isinstance(value, dict):
                return {key: detached(item) for key,item in value.items()}
            if isinstance(value, list):
                return [detached(item) for item in value]
            if isinstance(value, tuple):
                return tuple(detached(item) for item in value)
            return copy.deepcopy(value)
        memory.planning_results = detached(dict(original))
        memory._planning_versions = dict((snapshot.get("agent") or {}).get("planning_versions") or {})
        memory.user_lang = self.control_agent.memory.user_lang
        memory.set_ui_state((snapshot.get("ui") or {}).get("state") or (snapshot.get("agent") or {}).get("ui_state") or {})
        image = GuidePlacementService(self.control_agent)._target_ct_image(snapshot)
        memory.store("ct_image", image)
        memory.store("timepoint_context", {"timepoint_id": target_timepoint_id, "stage": context.target.stage,
            "preoperative_timepoint_id": context.target.preoperative_timepoint_id})
        from utils.ctv_targets import resolve_ctv_target
        if resolve_ctv_target(memory.retrieve) is None or memory.retrieve("oar_array") is None:
            raise TimepointError("Select current-timepoint CTV and OAR first; this executor never runs segmentation on another timepoint")
        from web.input_workflow import restore_owned_planning_config
        view_config = restore_owned_planning_config(self.config, snapshot.get('agent'))
        view_config.update(_workspace_timepoint_id=target_timepoint_id,
                           _workspace_state_dir=str(self.store.workspace_root(self.owner, self.session) / "timepoints" / target_timepoint_id / "agent_state"))
        view = SimpleNamespace(memory=memory, config=view_config, _workspace_store=self.store,
                               _workspace_timepoint_context=context, _workspace_data_ready=True)
        def scoped_preview(event):
            if preview_callback is not None and isinstance(event, dict):
                preview_callback({**event, "session_id": self.session, "timepoint_id": target_timepoint_id,
                    "clinical_revision": context.target.clinical_revision})
        def scoped_step(name, status, content=None):
            # Preserve the existing trace callback contract. Visual callbacks
            # carry a target envelope separately; trace text is shared chat.
            if step_callback is not None:
                step_callback(name, status, f"timepoint_id={target_timepoint_id} | {content or ''}")
        kwargs = {"ref_direc": ref_direc} if ref_direc is not None else {}
        if seed_info is not None:
            kwargs["seed_info"] = seed_info
        with tool_scope(view_config):
            result = PlanningPipelineTool()._execute(_agent=view, step=step, mode=mode,
                planning_params=planning_params, step_callback=scoped_step if step_callback else None,
                # Legacy SSE/Viewer consumers know Session scope only. Do not
                # paint another timepoint into the default scene merely by
                # adding an unknown field to an otherwise accepted event.
                preview_callback=scoped_preview if preview_callback and getattr(preview_callback, "supports_timepoint_scope", False) is True else None,
                **kwargs)
        if not result.success:
            result.metadata = {**(result.metadata or {}), "session_id": self.session,
                "timepoint_id": target_timepoint_id, "published_to_timepoint": False}
            return result
        updates = dict(memory.planning_results)
        removed = tuple(set(original) - set(updates))
        try:
            saved = self.store.save_timepoint_results(self.owner, self.session, target_timepoint_id, updates,
                expected_clinical_revision=context.target.clinical_revision, removals=removed,
                execution_context=context)
        except TimepointConflict:
            # A calculated but uncommitted result is not a successful current
            # plan, even if the internal numerical registry had committed.
            from tool_factory import ToolResult
            return ToolResult(success=False, error="The target or source changed during computation; no stale result was published as current.",
                metadata={"timepoint_id": target_timepoint_id, "published_to_timepoint": False,
                          "calculation_completed": True})
        result.metadata = {**(result.metadata or {}), "session_id": self.session,
            "timepoint_id": target_timepoint_id, "published_to_timepoint": True,
            "timepoint_title": snapshot["timepoint"]["title"], "viewer_mounted": False,
            "timepoint_clinical_revision": saved["timepoint_clinical_revision"]}
        return result
