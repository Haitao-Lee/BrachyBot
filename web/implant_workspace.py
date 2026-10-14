"""Owned observation-to-Viewer bridge, not an editable supplemental seed plan."""
from __future__ import annotations

import copy
from dataclasses import asdict
from contextlib import contextmanager
import hashlib
from pathlib import Path
import re
import numpy as np
from uuid import uuid4, uuid5, NAMESPACE_URL

from agent_runtime.core import AgentMemory
from utils.image_limits import read_image
from utils.implant_reconstruction import ImageReference, ImageGeometry, SeedAxisReconstruction
from tool_factory.seed_seg.seedfinder_adapter import sha256_file
from web.implant_service import (ImplantScope, ImplantInput, ImplantService, ImplantServiceError,
    ImplantReviewAuthorization, ImplantCorrectionRequest, IMPLANT_MEMORY_KEY)
from web.timepoints import TimepointConflict
from web.workspace_store import WorkspaceError


def validate_appearance(patch):
    if not isinstance(patch, dict) or set(patch) - {"visible", "visible2D", "visible3D", "color", "opacity"}:
        raise ImplantServiceError("invalid_implant_presentation", "Invalid presentation fields")
    for key in {"visible", "visible2D", "visible3D"} & patch.keys():
        if type(patch[key]) is not bool:
            raise ImplantServiceError("invalid_implant_presentation", "Visibility must be boolean")
    if "opacity" in patch and (isinstance(patch["opacity"], bool) or not isinstance(patch["opacity"], (int, float)) or not 0 <= patch["opacity"] <= 1):
        raise ImplantServiceError("invalid_implant_presentation", "Opacity must be in [0,1]")
    if "color" in patch and (not isinstance(patch["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", patch["color"])):
        raise ImplantServiceError("invalid_implant_presentation", "Use an RGB hexadecimal color")
    return copy.deepcopy(patch)


def public_implant_view(receipt, presentation=None):
    """All visible geometry derives from the current revision, not an old STL."""
    record = receipt["record"]
    revision = SeedAxisReconstruction.from_dict(record["reconstruction"])
    presentation = presentation or {"revision": 0, "items": {}, "group": {}}
    rows = []
    for number, item in enumerate(revision.observations, 1):
        user = presentation["items"].get(item.observation_id, {})
        rows.append({"id": "implanted_seed_" + item.observation_id.replace("-", ""),
            "object_id": "implant:" + item.observation_id, "observation_id": item.observation_id,
            "detection_id": item.detection_id, "ordinal": number,
            "position": list(item.center_lps_mm), "axis": list(item.axis_lps) if item.axis_lps is not None else None,
            "dimensions": asdict(item.dimensions) if item.dimensions is not None else None,
            "axis_source": item.axis_source, "review_status": item.review_status,
            "excluded": item.review_status == "rejected", "role": "implanted_observation",
            "type":"implanted_observation","loaded":True,"parentId":"implanted_observations",
            "timepoint_id":revision.image_ref.timepoint_id,"observation_revision_id":revision.revision_id,
            "color": user.get("color", "#22D3EE"), "opacity": user.get("opacity", 1.),
            "visible": user.get("visible", True) and item.review_status != "rejected",
            "visible2D": user.get("visible2D", True), "visible3D": user.get("visible3D", True),
            "center_uncertainty_mm": item.center_uncertainty_mm,
            "glyph": "capsule" if item.axis_lps is not None and item.dimensions is not None else "point_halo"})
    return {"session_id": revision.image_ref.session_id, "timepoint_id": revision.image_ref.timepoint_id,
        "image_ref": asdict(revision.image_ref), "observation_revision_id": revision.revision_id,
        "revision": revision.revision, "presentation_revision": presentation["revision"],
        "group": {"visible": True, "opacity": 1., **presentation.get("group", {})},
        "nodes": rows, "active_count": sum(not row["excluded"] for row in rows),
        "review_required": revision.review_status != "accepted", "clinical_use_ready": False,
        "dose_input_ready": revision.dose_input_ready, "coordinate_system": "LPS", "coordinate_unit": "mm",
        "render_source": "current_observation_revision_not_original_detector_stl"}


class ImplantWorkspace:
    def __init__(self, store, owner, session, target, *, agent=None, service_factory=None):
        self.store, self.owner, self.session, self.target = store, owner, session, target
        self.context = store.capture_timepoint_context(owner, session, target)
        self.snapshot = store.load_timepoint_snapshot(owner, session, target)
        self.memory = agent.memory if agent is not None else AgentMemory(session)
        self.bound_agent = agent
        collection = self.snapshot.get("image_collection") or {}
        scope = ImplantScope(owner, session, target, str(store.workspace_root(owner, session)),
            collection.get("planning_reference_image_id"))
        self.service = (service_factory or ImplantService)(scope, self.memory, image_fence=self.image_current,
            capacity_check=lambda path, size: store._ensure_replacement_capacity(owner, path, size))

    def _results(self):
        return (self.snapshot.get("agent") or {}).get("planning_results") or {}

    def _path(self, snapshot):
        values = (snapshot.get("agent") or {}).get("planning_results") or {}
        if snapshot.get("image_collection"):
            from web.timepoint_images import TimepointImageService
            bridge = TimepointImageService(self.store).planning_reference_bridge(self.owner, self.session, self.target,
                load_pixels=False, require_ct=True)
            return Path(bridge["ct_path"])
        if values.get("images"):
            raise ImplantServiceError("implant_reference_not_ready", "Explicit multi-image reference resolution is required")
        raw = values.get("ct_path") or values.get("ct_image_path")
        if not isinstance(raw, str) or not raw:
            raise ImplantServiceError("implant_image_required", "Load the current timepoint CT first")
        root = self.store.workspace_root(self.owner, self.session) / "inputs"
        candidate = Path(raw)
        candidate = candidate if candidate.is_absolute() else self.store.workspace_root(self.owner, self.session) / candidate
        path = candidate.resolve()
        if root.resolve() not in path.parents or path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise ImplantServiceError("invalid_implant_input", "CT input must be a regular file owned by this Session")
        return path

    def input(self):
        path = self._path(self.snapshot)
        image = read_image(path)
        values, timepoint = self._results(), self.snapshot["timepoint"]
        if str(values.get("image_modality") or "CT").upper() != "CT":
            raise ImplantServiceError("unsupported_implant_image", "SeedFinder currently supports CT observations")
        reference = ImageReference(self.session, self.target, (self.snapshot.get("image_collection") or {}).get("planning_reference_image_id")
            or values.get("ct_image_id") or "image:" + self.target,
            values.get("ct_image_revision") or 1, sha256_file(path, max_bytes=512_000_000), ImageGeometry.from_image(image))
        return ImplantInput(reference, str(path), str(self.store.workspace_root(self.owner, self.session) / "inputs"),
            timepoint.get("preoperative_timepoint_id"), stage=timepoint["stage"])

    def image_current(self, reference):
        self.store.require_local_session(self.owner, self.session)
        state = self.store.load_timepoint_snapshot(self.owner, self.session, self.target)
        try:
            image_id = (state.get("image_collection") or {}).get("planning_reference_image_id")
            return (image_id is None or image_id == reference.image_id) and sha256_file(self._path(state), max_bytes=512_000_000) == reference.image_sha256
        except (ValueError, OSError):
            return False

    def presentation(self):
        path = self.service.root / "presentation.json"
        with self.service._journal():
            value = self.service._read_json(path) if path.exists() else {"revision": 0, "items": {}, "group": {}}
        if (not isinstance(value, dict) or type(value.get("revision")) is not int or value["revision"] < 0
                or not isinstance(value.get("items"), dict) or len(value["items"]) > 2048):
            raise ImplantServiceError("implant_journal_integrity_error", "Invalid appearance state")
        validate_appearance(value.get("group", {}))
        for patch in value["items"].values():
            validate_appearance(patch)
        return value

    def view(self):
        try:
            receipt = self.service.get()
        except ImplantServiceError as exc:
            if exc.code != "implant_reconstruction_not_found":
                raise
            return {"session_id": self.session, "timepoint_id": self.target, "nodes": [], "active_count": 0,
                "observation_revision_id": None, "presentation_revision": 0, "group": {"visible": True, "opacity": 1.},
                "clinical_use_ready": False, "review_required": True}
        reference = SeedAxisReconstruction.from_dict(receipt["record"]["reconstruction"]).image_ref
        if not self.image_current(reference):
            raise ImplantServiceError("implant_input_changed", "Saved detections belong to a different image revision")
        self.publish(receipt)
        view=public_implant_view(receipt, self.presentation())
        dose=((self.store.load_timepoint_snapshot(self.owner,self.session,self.target).get('agent') or {}).get('planning_results') or {}).get('implanted_dose_record')
        if isinstance(dose,dict):
            view['implanted_dose']={key:dose[key] for key in ('observation_revision_id','source_count','dose_min_gy','dose_max_gy','dose_status','estimated_axis_count') if key in dose}
            view['implanted_dose']['stale']=dose.get('observation_revision_id')!=receipt['record']['reconstruction']['revision_id']
            profile=((self.store.load_timepoint_snapshot(self.owner,self.session,self.target).get('agent') or {}).get('planning_results') or {}).get('implant_dose_profile') or {}
            if dose.get('dose_profile',{})!=profile:view['implanted_dose']['stale']=True
            if not view['implanted_dose']['stale']:
                geometry={item['id']:item for item in dose.get('source_geometry',[]) if isinstance(item,dict) and 'id' in item}
                for row in view['nodes']:
                    estimate=geometry.get(row['observation_id'])
                    if row['axis'] is None and estimate is not None and estimate.get('position')==row['position']:
                        row['axis']=estimate['direction'];row['axis_source']='current_dose_orientation_estimate';row['axis_estimated']=True
                    info=dose.get('seed_info') or {}
                    if row['dimensions'] is None and info.get('length') and info.get('radius'):
                        row['dimensions']={'capsule_length_mm':info['length'],'capsule_diameter_mm':2*info['radius'],'source_model_id':'current_confirmed_software_source_settings'}
                    if row['axis'] is not None and row['dimensions'] is not None:row['glyph']='capsule'
        return view

    def publish(self, receipt):
        """Repair journal-to-workspace projection after restart, never repeat a clinical invalidation."""
        if receipt.get('is_current') is not True:
            raise ImplantServiceError('implant_revision_conflict','An old request receipt cannot replace the current observations')
        record = receipt["record"]
        head = record["reconstruction"]["revision_id"]
        state = self.store.load_timepoint_snapshot(self.owner, self.session, self.target)
        prior = ((state.get("agent") or {}).get("planning_results") or {}).get(IMPLANT_MEMORY_KEY) or {}
        previous = (prior.get("by_timepoint", {}).get(self.target, {}).get("current") or {}).get("reconstruction", {}).get("revision_id")
        results = (state.get("agent") or {}).get("planning_results") or {}
        prior_dependency = results.get("implant_dependency_state") or {}
        if previous == head and prior_dependency.get("invalidation_version") == 2:
            return
        from web.timepoint_resources import (fingerprint, observation_content,
                                            dependency_fingerprints, resource_state)
        before_resources = results.get("timepoint_resource_state") or {}
        leaves = dict(before_resources.get("fingerprints") or {})
        leaves["observation"] = fingerprint(observation_content(record["reconstruction"]))
        resources = dependency_fingerprints(leaves)
        graph = resource_state(before_resources, resources)
        updates = {IMPLANT_MEMORY_KEY: copy.deepcopy(self.memory.retrieve(IMPLANT_MEMORY_KEY)),
            "implant_dependency_state": {"state": "stale", "invalidation_version": 2,
                "observation_revision_id": head, "previous_observation_revision_id": previous,
                "families": graph["invalidated"], "requires_recompute": True,
                "planned_geometry_retained_as_history": True},
            "timepoint_resource_state": graph}
        # Current aliases are authority for the legacy heatmap, Dose/DVH, score,
        # reports and exports. Keep historical geometry/snapshots, but remove
        # every total-dose alias that could outlive an actual source correction.
        stale_keys = ("continuation_baseline", "continuation_baseline_record",
            "continuation_baseline_dependency_fingerprint", "continuation_inference_binding_sha256",
            "continuation_evaluation", "total_dose_evaluation", "dose_distribution",
            "dose_distribution_gy", "dose_distribution_physical_gy", "dose_distribution_current_normalized",
            "algorithm_plan_dose_distribution", "algorithm_plan_dose_distribution_current_normalized",
            "algorithm_plan_dose_distribution_gy", "additional_dose_distribution", "dose_metrics",
            "algorithm_plan_dose_metrics", "algorithm_plan_dvh_data", "metrics", "dvh_data",
            "plan_score", "dose_recompute_provenance", "report_data", "report_result",
            "report_path", "report_pdf_path", "report_html_path", "report_pdf", "report_html")
        updates.update({key: None for key in stale_keys if key in results})
        components = copy.deepcopy(results.get("dose_components") or {})
        for name in ("implanted", "total"):
            if isinstance(components.get(name), dict):
                components[name].update(status="stale", stale_reason="implant_observations_changed",
                                       invalidated_by_observation_revision_id=head)
        if components:
            updates["dose_components"] = components
        implanted = copy.deepcopy(results.get("implanted_dose_record"))
        if isinstance(implanted, dict):
            implanted.update(dose_status="stale", clinical_use_ready=False,
                             invalidated_by_observation_revision_id=head)
            updates["implanted_dose_record"] = implanted
        for key in ("artifact_status", "manual_artifact_status"):
            status = copy.deepcopy(results.get(key) or {})
            status.update(dose="stale", dvh="stale", report="stale", quality_check="stale",
                          reason="implant observations changed", observation_revision_id=head)
            updates[key] = status
        updates.update(planning_completed=False, manual_geometry_only=True,
                       report_status="stale", quality_check_status="stale")
        runs = results.get("planning_runs")
        if isinstance(runs, list):
            updates["planning_runs"] = [{**run, "clinical_inputs_current": False,
                "invalidated_by_observation_revision_id": head, "has_dose": False,
                "has_dvh": False, "has_metrics": False, "metrics_summary": {},
                "artifact_status": {**(run.get("artifact_status") or {}),
                    "dose": "stale", "dvh": "stale", "report": "stale", "quality_check": "stale"}}
                if isinstance(run, dict) else run for run in runs]
        if self.bound_agent is not None and getattr(self.bound_agent, "_workspace_scoped_chat_runtime", None) is not None:
            for key, value in updates.items():
                self.memory.store(key, value)
            self.memory.conversation_state["planning_completed"] = False
            return
        if self.context.target.legacy_default:
            self.store.save_agent_results_patch(self.owner, self.session, updates, reason="implant.observation_revision")
        else:
            self.store.save_timepoint_results(self.owner, self.session, self.target, updates,
                expected_clinical_revision=state["timepoint_clinical_revision"])
        if self.bound_agent is not None:
            for key, value in updates.items():
                self.bound_agent.memory.store(key, value)
            self.bound_agent.memory.conversation_state["planning_completed"] = False

    def detect(self, request_id, expected_revision_id=None, cancelled=None):
        from utils.cancellation import is_cancelled
        cancelled = cancelled or is_cancelled
        self.service._config().validate_available()
        profile=self._results().get('implant_dose_profile') or {}
        info=profile.get('seed_info') or {}
        from utils.implant_reconstruction import SeedDimensions
        dimensions=SeedDimensions(profile['source_model_id'],info['length'],2*info['radius']) if info.get('length') and info.get('radius') else None
        with self.store.workspace_output_transaction(self.owner, self.session, "implant_reconstruction",
                additional_bytes=512_000_000):
            # Reserve bytes without holding the account lock during inference.
            receipt = self.service.reconstruct(self.input(), request_id=request_id,
                expected_revision_id=expected_revision_id, dimensions=dimensions, cancelled=cancelled)
        if not receipt['is_current']:receipt=self.service.get()
        self.publish(receipt)
        return public_implant_view(receipt, self.presentation())

    def correct(self, payload, *, actor):
        if not isinstance(payload, dict) or set(payload) - {"action", "request_id", "expected_revision_id", "observation_ids", "center_lps_mm"}:
            raise ImplantServiceError("invalid_implant_arguments", "Unexpected correction fields")
        current = self.service.get()
        image_ref = SeedAxisReconstruction.from_dict(current["record"]["reconstruction"]).image_ref
        auth = ImplantReviewAuthorization(self.owner, image_ref, payload.get("expected_revision_id"), actor)
        request = ImplantCorrectionRequest(auth, payload.get("request_id"), payload.get("action"),
            tuple(payload.get("observation_ids") or ()), payload.get("center_lps_mm"))
        # The immutable journal owns its CAS. Never hold an account quota
        # lock while waiting for a journal held by a dose publication.
        receipt = self.service.correct(request)
        if not receipt['is_current']:receipt=self.service.get()
        self.publish(receipt)
        return public_implant_view(receipt, self.presentation())

    def review(self, payload, *, actor):
        """A separately authenticated human confirms observations and scan coverage."""
        from web.implant_service import ImplantReviewRequest
        from utils.implant_reconstruction import ObservationReview, SeedDimensions
        allowed = {"expected_revision_id", "observations_confirmed", "coverage_confirmed", "note", "axes"}
        if (not isinstance(payload, dict) or set(payload) - allowed
                or payload.get("observations_confirmed") is not True
                or type(payload.get("coverage_confirmed")) is not bool
                or not isinstance(payload.get("note"), str) or not payload["note"].strip()
                or len(payload["note"]) > 4000):
            raise ImplantServiceError("implant_review_authorization_required", "Explicit observation and coverage review is required")
        current = self.service.get()
        revision = SeedAxisReconstruction.from_dict(current["record"]["reconstruction"])
        axes = payload.get("axes") or {}
        if not isinstance(axes, dict) or set(axes) - {row.observation_id for row in revision.observations}:
            raise ImplantServiceError("invalid_implant_arguments", "Axis review must name current observation IDs")
        values = self._results()
        profile = values.get("implant_dose_profile") or {}
        dims = profile.get("seed_info") or {}
        dimensions = SeedDimensions(profile["source_model_id"], dims["length"], 2 * dims["radius"]) if dims.get("length") and dims.get("radius") else None
        dose = values.get("implanted_dose_record") or {}
        estimates = {row["id"]: row for row in dose.get("source_geometry", [])}
        decisions = []
        for row in revision.observations:
            estimated = estimates.get(row.physical_seed_id or "observed:" + row.observation_id)
            axis = axes.get(row.observation_id)
            if axis is None and row.axis_lps is None and dose.get("observation_revision_id") == revision.revision_id and estimated:
                if np.allclose(estimated["position"], row.center_lps_mm, atol=1e-6, rtol=0):
                    axis = estimated["direction"]
            if row.review_status != "rejected" and (row.axis_lps is None and axis is None or dimensions is None and row.dimensions is None):
                raise ImplantServiceError("implant_axis_unavailable", "Current dimensions and reviewed orientation are required for every included source")
            decisions.append(ObservationReview(row.detection_id,
                "rejected" if row.review_status == "rejected" else "accepted", payload["note"].strip(),
                corrected_axis_lps=axis, corrected_dimensions=dimensions))
        authorization = ImplantReviewAuthorization(self.owner, revision.image_ref, payload.get("expected_revision_id"), actor)
        receipt = self.service.review(ImplantReviewRequest(authorization, tuple(decisions),
            "complete" if payload["coverage_confirmed"] else "partial", payload["note"].strip()))
        self.publish(receipt)
        return public_implant_view(receipt, self.presentation())

    def set_presentation(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"expected_presentation_revision", "patches", "group"}:
            raise ImplantServiceError("invalid_implant_presentation", "Use a versioned appearance patch")
        expected, patches = payload["expected_presentation_revision"], payload["patches"]
        if type(expected) is not int or expected < 0 or not isinstance(patches, dict) or len(patches) > 1024:
            raise ImplantServiceError("invalid_implant_presentation", "Invalid presentation version/targets")
        receipt = self.service.get()
        known = {item["observation_id"] for item in receipt["record"]["reconstruction"]["observations"]}
        if not set(patches) <= known:
            raise ImplantServiceError("implant_observation_not_found", "Appearance target is absent")
        clean = {key: validate_appearance(value) for key, value in patches.items()}
        group = validate_appearance(payload["group"])
        with self.service._journal(), self.store._quota_commit_lock(self.owner):
            path = self.service.root / "presentation.json"
            value = self.service._read_json(path) if path.exists() else {"revision": 0, "items": {}, "group": {}}
            if expected != value["revision"]:
                raise ImplantServiceError("implant_presentation_conflict", "Appearance changed; reload before applying this patch")
            for key, patch in clean.items():
                value["items"][key] = {**value["items"].get(key, {}), **patch}
            value["group"] = {**value.get("group", {}), **group}
            value["revision"] += 1
            self.service._atomic_json(path, value)
        return public_implant_view(receipt, value)


def bind_implant_tool(agent, params):
    """Trusted runtime injector. Model arguments cannot construct services or approval."""
    config = getattr(agent, "config", {}) or {}
    store = getattr(agent, "_workspace_store", None)
    if store is None:
        return None
    from web.timepoints import default_timepoint_id
    target = config.get("_workspace_timepoint_id") or default_timepoint_id(config["_workspace_session_id"])
    workspace = ImplantWorkspace(store, config["_workspace_owner_id"], config["_workspace_session_id"], target, agent=agent)
    if params.get('image_path') is not None:
        if Path(params['image_path']).resolve()!=workspace._path(workspace.snapshot):
            raise ImplantServiceError('implant_input_changed','The named image is not this captured timepoint input')
        params.pop('image_path')
    action = params.get("action") or "reconstruct"
    if action=='detect':action='reconstruct'
    if action in {"start_add", "start_review"}:
        view = workspace.view()
        if action == "start_add" and not view["observation_revision_id"]:
            raise ImplantServiceError("implant_reconstruction_not_found", "Detect the selected image before adding observations")
        from tool_factory import ToolResult
        return ToolResult(True, message="Open observation correction tools",
            metadata={"timepoint_id": target, "implant_view": view,
                "implant_command": {"action": action, "session_id": workspace.session, "timepoint_id": target,
                    "observation_revision_id": view["observation_revision_id"]}, "clinical_use_ready": False})
    params["method"] = "seedfinder"
    params["action"] = action
    params["implant_service"] = workspace.service
    if action == "reconstruct":
        params["implant_input"] = workspace.input()
        if not params.get("request_id"):
            turn = (getattr(agent, "_active_turn_context", None) or {}).get("request_id") or uuid4().hex
            params["request_id"] = str(uuid5(NAMESPACE_URL, workspace.session + target + str(turn) + "implant_detect"))
        if "expected_revision_id" not in params:
            params["expected_revision_id"] = workspace.view()["observation_revision_id"]
    return workspace


def execute_bound_implant(agent, params):
    """Detect/reconstruct delivery uses the same correction actions as manual UI."""
    from tool_factory import ToolResult
    from web.timepoint_messages import timepoint_message
    locale = (getattr(agent, "_active_turn_context", None) or {}).get("ui_language") or agent.memory.user_lang
    try:
        workspace = bind_implant_tool(agent, params)
        if isinstance(workspace, ToolResult):
            workspace.message = timepoint_message("implant_edit_tools_opened", locale)["message"]
            return workspace
        if workspace is None:
            raise ImplantServiceError("implant_service_not_bound", "No authenticated workspace is bound")
        action = params["action"]
        if action == "reconstruct":
            view = workspace.detect(params["request_id"], params.get("expected_revision_id"))
        elif action == "get_reconstruction":
            view = workspace.view()
        elif action in {"exclude_observations", "restore_observations", "move_observation", "add_observation"}:
            aliases = {"exclude_observations": "exclude", "restore_observations": "restore", "move_observation": "move", "add_observation": "add"}
            view = workspace.correct({"action": aliases[action], "request_id": params.get("request_id") or str(uuid4()),
                "expected_revision_id": params.get("expected_revision_id"), "observation_ids": params.get("observation_ids") or [],
                **({"center_lps_mm": params["center_lps_mm"]} if "center_lps_mm" in params else {})}, actor=workspace.owner)
        else:
            raise ImplantServiceError("implant_review_authorization_required", "Clinical review needs a separate authenticated review event")
        return ToolResult(True, data=view["nodes"], message=timepoint_message("implant_view_ready", locale)["message"],
            metadata={"timepoint_id": workspace.target, "implant_view": view,
                "implant_command": {"action": "display", "session_id": workspace.session, "timepoint_id": workspace.target,
                    "observation_revision_id": view["observation_revision_id"]}, "num_detected": view["active_count"],
                "review_required": view["review_required"], "baseline_accepted": False, "clinical_use_ready": False})
    except (ImplantServiceError, WorkspaceError, ValueError, TypeError, OSError) as exc:
        code = getattr(exc, "code", "implant_operation_failed")
        packet = timepoint_message(code, locale)
        return ToolResult(False, error=packet["message"], message=packet["message"], metadata={**packet, "clinical_use_ready": False})


@contextmanager
def implant_publication_guard(agent,updates):
    """Keep observation authority stable through a scoped clinical CAS."""
    config=agent.config
    target=config.get('_workspace_timepoint_id')
    dose=updates.get('implanted_dose_record')
    catalog=updates.get(IMPLANT_MEMORY_KEY)
    expected=dose.get('observation_revision_id') if isinstance(dose,dict) else None
    if expected is None and isinstance(catalog,dict):
        expected=(catalog.get('by_timepoint',{}).get(target,{}).get('current') or {}).get('reconstruction',{}).get('revision_id')
    if not expected:
        yield;return
    store = agent._workspace_store
    snapshot = store.load_timepoint_snapshot(config['_workspace_owner_id'], config['_workspace_session_id'], target)
    image_id = (snapshot.get('image_collection') or {}).get('planning_reference_image_id')
    service=ImplantService(ImplantScope(config['_workspace_owner_id'],config['_workspace_session_id'],target,
        str(agent._workspace_store.workspace_root(config['_workspace_owner_id'],config['_workspace_session_id'])),
        image_id),agent.memory)
    with service._journal() as index:
        current=service._load_record(index['current'])['reconstruction']['revision_id']
        if current.replace('-','')!=expected.replace('-',''):
            raise TimepointConflict('Implant observations changed before clinical publication')
        yield
