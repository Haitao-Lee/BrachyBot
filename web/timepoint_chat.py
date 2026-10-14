"""Submission-owned chat targets and detached clinical execution.

One Session keeps one conversation. A browser's mounted timepoint is a default
captured BEFORE queueing, not a mutable pointer consulted by a tool later.
This module does not interpret human phrases or manufacture clinical approval.
"""
from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Mapping

from web.timepoints import TimepointError, TimepointConflict, timepoint_id


@dataclass(frozen=True)
class ChatTimepointScope:
    owner_id: str
    session_id: str
    timepoint_id: str
    ui_language: str = "en"
    legacy_default: bool = False

    def __post_init__(self):
        if not isinstance(self.owner_id, str) or not self.owner_id:
            raise TimepointError("An authenticated owner is required")
        timepoint_id(self.session_id)
        timepoint_id(self.timepoint_id)
        if self.ui_language not in {"zh", "en"}:
            raise TimepointError("Unsupported interface language")
        if type(self.legacy_default) is not bool:
            raise TimepointError("Invalid default-timepoint marker")

    def public_dict(self):
        # Account identity stays server-owned; only the target is presentation.
        return {"session_id": self.session_id, "timepoint_id": self.timepoint_id,
                "ui_language": self.ui_language}


def capture_chat_scope(store, owner_id, session_id, identifier=None, *, ui_language="en",
                       parent_scope=None):
    """Resolve one owned target without a navigation cookie or text heuristic.

    Ordinary requests name the mounted target. Older single-workspace clients
    omit it and resolve the legacy default. Hidden children inherit their
    actual parent, never the tab mounted when image analysis finally starts.
    """
    catalog = store.list_timepoints(owner_id, session_id)
    if parent_scope is not None:
        if not isinstance(parent_scope, ChatTimepointScope) or (
                parent_scope.owner_id, parent_scope.session_id) != (owner_id, session_id):
            raise TimepointConflict("The visual parent belongs to another Session")
        if identifier is not None and identifier != parent_scope.timepoint_id:
            raise TimepointConflict("The visual child must retain its parent's target")
        identifier = parent_scope.timepoint_id
    identifier = timepoint_id(catalog["default_timepoint_id"] if identifier is None else identifier)
    record = store._timepoint_record(catalog, identifier)
    return ChatTimepointScope(owner_id, session_id, identifier, ui_language, bool(record["legacy_default"]))


_IMMUTABLE_SCALAR_TYPES = frozenset((str, int, float, bool, type(None)))


def _detached(value):
    """Copy containers, share immutable input-array views (not writable aliases)."""
    if type(value) in _IMMUTABLE_SCALAR_TYPES:
        return value
    import numpy as np
    if isinstance(value, np.ndarray):
        result = value.view()
        result.flags.writeable = False
        return result
    if isinstance(value, dict):
        return {key: _detached(item) for key, item in value.items()}
    if isinstance(value, list):
        if all(type(item) in _IMMUTABLE_SCALAR_TYPES for item in value):
            return value.copy()
        return [_detached(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_detached(item) for item in value)
    return copy.deepcopy(value)


def _state_token(value):
    """Detect memory replacements without rehashing a large dose on every read.

    Input arrays are read-only. Clinical writers replace them through store();
    mutable JSON containers are compared recursively. Computed arrays have
    invocation-owned identity and are committed before another writer runs.
    """
    import numpy as np
    if isinstance(value, np.ndarray):
        return ("array", id(value), value.shape, value.dtype.str)
    if isinstance(value, (Mapping, list, tuple)):
        # DVH/history metadata can contain millions of ordinary JSON scalars.
        # Canonical C-backed serialization avoids building millions of Python
        # token tuples per Viewer request, while still detecting nested edits.
        import hashlib
        import json
        def reference(item):
            if isinstance(item, np.ndarray):
                return ["array", id(item), list(item.shape), item.dtype.str]
            return [type(item).__name__, id(item)]
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=reference).encode("utf-8")
            return (type(value).__name__, hashlib.sha256(encoded).hexdigest())
        except (TypeError, ValueError, UnicodeError):
            pass  # Non-JSON keys/legacy text retain the exact recursive path.
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _state_token(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_state_token(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return (type(value).__name__, value)
    return (type(value).__name__, id(value))


def _detach_request_lifecycle(view, control, snapshot):
    """Do not inherit a cached Agent's active turn or hydration worker state."""
    from agent_runtime.contracts import RunLedger, ToolCallGateway
    for key in tuple(vars(view)):
        if key.startswith(("_active_turn", "_turn_", "_ctx_", "_last_turn", "_latest_turn",
                           "_blocked_mutating", "_visual_analysis", "_workspace_hydration")):
            delattr(view, key)
    view._turn_local = threading.local()
    view._turn_state_lock = threading.RLock()
    view._turn_generation = int(getattr(control, "_turn_generation", 0))
    view._active_turn_token = 0
    view._active_turn_context = {}
    view._turn_execution_authorizations = {}
    view._turn_execution_authorization = None
    view._cancel_requested = False
    view._cancel_event = threading.Event()
    view._workspace_hydration_cancel = threading.Event()
    view._workspace_ready_event = threading.Event()
    view._workspace_hydration_in_progress = False
    view._workspace_hydration_phase = "metadata"
    view._workspace_hydration_error = ""
    view._workspace_hydration_superseded = False
    view._workspace_hydration_repaired = False
    view._workspace_ct_ready = False
    view._workspace_resource_waiter = None
    # A new HTTP request cannot inherit the preceding request's runtime/cache.
    for key in ("_workspace_scoped_http_runtime", "_workspace_scoped_chat_runtime",
                "_workspace_timepoint_context", "_active_trace_language", "_turn_reference_material"):
        vars(view).pop(key, None)
    view.run_ledger = RunLedger()
    saved_ledger = (snapshot.get("agent") or {}).get("run_ledger")
    if isinstance(saved_ledger, Mapping):
        view.run_ledger.restore_state(saved_ledger)
    view.tool_gateway = ToolCallGateway(view.run_ledger)


# Capability admission is about tested software entrypoints, NOT user phrases.
# Browser commands and Session-only services remain unavailable until their
# own target-fenced delivery adapters exist; a header cannot make them safe.
SCOPED_CLINICAL_TOOLS = frozenset({
    "ctv_segmentation", "oar_segmentation", "biomedparse_segmentation",
    "trajectory_init", "trajectory_refine", "trajectory_planning",
    "seed_planning", "seed_planning_rule_based", "seed_planning_rl",
    "planning_pipeline", "dose_engine", "dose_evaluation", "query_metrics",
    "safety_validator", "report_generator", "dicom_rt_exporter", "surgical_guide", "seed_segmentation",
    "dose_recompute", "report_auto_fill", "plan_quality_scorer", "oar_constraint_checker",
    "plan_refinement", "plan_comparator", "ui_inspector", "timepoint_images",
})
SHARED_READ_TOOLS = frozenset({"timepoint_inspector", "clinical_kb", "web_search", "web_fetch",
    "web_access", "pubmed_search", "pubmed_fetch", "literature_search", "literature_fetch",
    "ctv_model_catalog", "doc_reader"})
BROWSER_TOOLS = frozenset({"ui_controller", "ui_screenshot", "ui_content"})
SHARED_RESULT_KEYS = frozenset({"session_language"})


def project_timepoint_schemas(schemas, scope):
    """Expose a stable optional target argument on clinical capabilities.

    No second classifier/provider call. The native implementation receives
    image objects from the executor, never a model-generated clinical array.
    """
    if not isinstance(scope, ChatTimepointScope):
        return schemas
    result = copy.deepcopy(schemas)
    for entry in result or []:
        function = entry.get("function") if isinstance(entry, dict) else None
        if not isinstance(function, dict) or function.get("name") not in SCOPED_CLINICAL_TOOLS | BROWSER_TOOLS:
            continue
        parameters = function.get("parameters")
        if not isinstance(parameters, dict):
            continue
        properties = parameters.setdefault("properties", {})
        properties["timepoint_id"] = {"type": "string", "pattern": "^[0-9a-f]{32}$",
            "description": "Optional explicit same-Session timepoint ID from timepoint_inspector. Omit to use the human's submission-captured Table Viewer. Never use a display title or file path as an ID."}
        from agent_runtime.timepoint_tools import OWNED_INPUT_FIELDS
        injected = OWNED_INPUT_FIELDS.get(function["name"], ())
        for key in injected:
            properties.pop(key, None)
        parameters["required"] = [key for key in parameters.get("required", ()) if key not in injected]
    return result


class ScopedChatRuntime:
    """A task view of clinical state; never replace the cached Session Agent."""
    def __init__(self, control_agent, scope, *, include_shared=True, _snapshot=None, _context=None, _hydrated_values=None):
        from agent_runtime.core import AgentMemory
        if not isinstance(scope, ChatTimepointScope):
            raise TimepointError("A server-captured chat target is required")
        parent = getattr(control_agent, "_workspace_scoped_chat_runtime", None)
        control_agent = parent.control_agent if parent is not None else control_agent
        self.control_agent, self.scope = control_agent, scope
        provided_store = getattr(control_agent, "_workspace_store", None)
        self.store = getattr(provided_store, "raw", provided_store)
        config = getattr(control_agent, "config", {}) or {}
        if self.store is None or (config.get("_workspace_owner_id"), config.get("_workspace_session_id")) != (
                scope.owner_id, scope.session_id):
            raise TimepointConflict("The target is not bound to this authenticated Agent")
        self.context = _context or self.store.capture_timepoint_context(scope.owner_id, scope.session_id, scope.timepoint_id)
        self.legacy = self.context.target.legacy_default
        self.view = control_agent
        self.closed = False
        if self.legacy:
            raise ScopedToolUnavailable("The default timepoint must be detached before clinical execution")
        snapshot = _snapshot if _snapshot is not None else self.store.load_timepoint_snapshot(
            scope.owner_id, scope.session_id, scope.timepoint_id, decode_arrays=False, include_shared=include_shared)
        self.snapshot = snapshot
        saved_agent = snapshot.get("agent") or {}
        # snapshot is already invocation-owned, not the manifest cache graph.
        # Writers mutate detached memory, never these immutable source records.
        self.encoded_results = dict(saved_agent.get("planning_results") or {})
        from web.workspace_store import _restore_hydration_metadata
        self.view = copy.copy(control_agent)
        _detach_request_lifecycle(self.view, control_agent, snapshot)
        memory = AgentMemory(scope.session_id)
        memory._workspace_timepoint_id = scope.timepoint_id
        memory.planning_results = (_detached(_hydrated_values) if _hydrated_values is not None
            else _restore_hydration_metadata(self.encoded_results))
        memory.planning_results["timepoint_context"] = {"timepoint_id": scope.timepoint_id,
            "stage": self.context.target.stage, "preoperative_timepoint_id": self.context.target.preoperative_timepoint_id}
        for key in SHARED_RESULT_KEYS:
            if control_agent.memory.retrieve(key) is not None:
                memory.planning_results[key] = copy.deepcopy(control_agent.memory.retrieve(key))
        memory._planning_versions = dict(saved_agent.get("planning_versions") or {})
        memory.patient_data = copy.deepcopy(saved_agent.get("patient_data") or {})
        memory.conversation_state.update(data_available=sorted(key for key, value in self.encoded_results.items() if value is not None),
            ctv_segmented=self.encoded_results.get("ctv_array") is not None or self.encoded_results.get("ctv_binary_array") is not None,
            oar_segmented=self.encoded_results.get("oar_array") is not None,
            planning_completed=bool(memory.retrieve("planning_completed")))
        # Conversation control is shared, but never save this view through the
        # legacy root clinical checkpoint. Scalars are synchronized on close.
        for key in ("conversation", "context_summary", "compaction_count", "context_accounting", "user_lang",
                    "_context_revision", "smart_context", "tool_results"):
            if hasattr(control_agent.memory, key):
                setattr(memory, key, getattr(control_agent.memory, key))
        memory.set_ui_state((snapshot.get("ui") or {}).get("state") or saved_agent.get("ui_state") or {})
        self.view.memory = memory
        from web.input_workflow import restore_owned_planning_config
        self.view.config = restore_owned_planning_config(config, saved_agent)
        self.view.config.update(_workspace_timepoint_id=scope.timepoint_id,
            _workspace_output_root=str(self.store.workspace_root(scope.owner_id, scope.session_id) / "timepoints" / scope.timepoint_id),
            _workspace_state_dir=str(self.store.workspace_root(scope.owner_id, scope.session_id) / "timepoints" / scope.timepoint_id / "agent_state"))
        self.view._workspace_state_dir = self.view.config["_workspace_state_dir"]
        self.view._workspace_data_ready = _hydrated_values is not None
        self.view._workspace_ct_ready = _hydrated_values is not None and memory.retrieve('ct_data') is not None
        self.view._workspace_hydration_error = ''
        self.view._workspace_resource_waiter = self._waiter
        self.view._workspace_scoped_chat_runtime = self
        self.view._workspace_timepoint_context = self.context
        # Each registry and Agent-retaining tool must bind to the detached
        # view. A shallow Agent copy alone leaves the old executor reachable.
        registry = getattr(control_agent, "registry", None)
        if registry is not None:
            self.view.registry = registry.bind_workspace(self.view)
        from web.timepoint_http import HttpTimepointBinding, ScopedWorkspaceStore
        self.view._workspace_store = ScopedWorkspaceStore(self.store,
            HttpTimepointBinding(scope.owner_id, scope.session_id, scope.timepoint_id), runtime=self)
        self.clinical = self  # Common read-set contract for the store facade.
        report = (snapshot.get("report") or {}).get("form")
        if isinstance(report, Mapping):
            memory.planning_results.setdefault("report_form", copy.deepcopy(dict(report)))
        self.baseline = {key: _state_token(value) for key, value in memory.planning_results.items()}
        self.saved_keys = set(memory.planning_results)

    def _waiter(self, required):
        self.assert_current()
        if required and not self.view._workspace_data_ready:
            # A saved-dose/report question must not decode all CT/OAR/dose
            # sidecars. Hydrate once only when the selected tool needs arrays.
            from web.workspace_store import _decode_artifacts
            root = self.store.workspace_root(self.scope.owner_id, self.scope.session_id)
            decoded = _detached(_decode_artifacts(self.encoded_results, root))
            decoded["timepoint_context"] = {"timepoint_id": self.scope.timepoint_id,
                "stage": self.context.target.stage, "preoperative_timepoint_id": self.context.target.preoperative_timepoint_id}
            pending = {key: value for key, value in self.view.memory.planning_results.items()
                       if key not in self.baseline or _state_token(value) != self.baseline[key]}
            hydrated = {**self.snapshot, "agent": {**self.snapshot.get("agent", {}), "planning_results": decoded}}
            if self.snapshot.get("image_collection") and self.snapshot["image_collection"].get("planning_reference_image_id"):
                from web.timepoint_images import TimepointImageService
                bridge = TimepointImageService(self.store).planning_reference_bridge(
                    self.scope.owner_id, self.scope.session_id, self.scope.timepoint_id)
                decoded.update({key: value for key, value in bridge.items() if key not in
                    {"timepoint_clinical_revision", "display_image_id"}})
                image = bridge["ct_image"]
                decoded.update(ct_spacing=image.GetSpacing(), ct_origin=image.GetOrigin(), ct_direction=image.GetDirection(),
                    ct_shape=list(image.GetSize()[::-1]), ct_image_raw=image,
                    ct_axis_map={"axial": 0, "sagittal": 2, "coronal": 1}, image_modality=bridge["planning_reference_receipt"]["modality"])
            elif decoded.get("ct_data") is not None:
                from web.guide_service import GuidePlacementService
                decoded["ct_image"] = GuidePlacementService(self.control_agent)._target_ct_image(hydrated)
            self.assert_current()  # No concurrent input replacement during decode.
            self.baseline = {key: _state_token(value) for key, value in decoded.items()}
            decoded.update(pending)
            self.view.memory.planning_results = decoded
            self.view._workspace_data_ready = True
            self.view._workspace_ct_ready = decoded.get("ct_image") is not None
            self.view._workspace_hydration_phase = "ready"
            self.view._workspace_ready_event.set()

    def assert_current(self):
        if self.closed:
            raise TimepointConflict("The task's target binding has ended")
        self.store.require_local_session(self.scope.owner_id, self.scope.session_id)
        self.context.assert_current(self.scope.owner_id, self.scope.session_id,
            self.store._timepoint_catalog(self.scope.owner_id, self.scope.session_id),
            legacy_revision=self.store.get_session(self.scope.owner_id, self.scope.session_id).revision)

    def admit_tool(self, name, params):
        self.assert_current()
        explicit = params.get("timepoint_id")
        if name != "timepoint_controller" and explicit is not None and explicit != self.scope.timepoint_id:
            raise TimepointConflict("A tool cannot bypass its bound timepoint through the registry")
        if name == "timepoint_controller":
            return  # Its action-specific catalog/lease/target adapter is authoritative.
        from agent_runtime.timepoint_capabilities import capability_contract
        registry = getattr(self.view, "registry", None)
        tool = registry.get(name) if registry is not None and name in registry.tool_names else None
        contract = capability_contract(name, tool)
        if contract in {"declared_pure", "declared_read", "owned_file_read", "owned_experience_read"}:
            from agent_runtime.execution_authorization import tool_call_is_mutating
            if tool_call_is_mutating(name, params):
                raise TimepointError("A read/pure capability cannot perform a persistent mutation")
            return
        if contract == "owned_screenshot_annotation":
            from urllib.parse import urlparse
            filename = Path(urlparse(str(params.get("image_url") or "")).path).name
            if not filename.startswith(self.scope.timepoint_id + "_"):
                raise TimepointConflict("Screenshot annotation must use this timepoint's owned capture")
            return
        if name in SHARED_READ_TOOLS:
            from agent_runtime.execution_authorization import tool_call_is_mutating
            if tool_call_is_mutating(name, params):
                raise TimepointError("Shared knowledge mutations require their own Session-scoped executor")
            return
        if name in BROWSER_TOOLS:
            # Commands are accepted only when the product installs the real
            # envelope-aware delivery bridge. A legacy browser has no fence.
            if self.view.config.get("_workspace_scoped_browser_delivery") is not True:
                raise ScopedToolUnavailable("The browser must support timepoint-scoped command delivery")
            return
        if name not in SCOPED_CLINICAL_TOOLS:
            raise ScopedToolUnavailable("This tool needs a target-scoped service or browser delivery adapter")
        for key, saved_key in (("ct_path", "ct_path"), ("image_path", "ct_path"),
                               ("ct_image_path", "ct_path"), ("label_path", "ctv_path"),
                               ("ctv_mask_path", "ctv_path"), ("oar_mask_path", "oar_path")):
            if params.get(key) is not None:
                saved = self.view.memory.retrieve(saved_key)
                if not saved or Path(params[key]).resolve() != Path(saved).resolve():
                    raise TimepointConflict("Clinical image arguments must refer to this timepoint's bound input")

    def before_tool(self, name=None, params=None):
        self._before_tool_name = name
        if name in {'ui_inspector','ui_controller','ui_screenshot','ui_content'}:
            # Full operation/target dictionaries are needed by UI tools, not
            # by every slice, dose or clinical restore request. They have one
            # canonical owned bridge instead of copies in each image profile.
            bridge = self.store.load_timepoint_snapshot(self.scope.owner_id,self.scope.session_id,
                self.scope.timepoint_id).get('ui',{}).get('bridge',{}).get('state',{})
            if isinstance(bridge,Mapping) and bridge:
                self.view.memory.set_ui_state({**bridge,**self.view.memory.get_ui_state()})
        if name is not None:
            from agent_runtime.workspace_readiness import ensure_workspace_ready
            ensure_workspace_ready(self.view, name, params)
        self._before_results = _detached(self.view.memory.planning_results)
        self._before_versions = dict(self.view.memory._planning_versions)
        self._before_state = copy.deepcopy(self.view.memory.conversation_state)

    def rollback_tool(self):
        if hasattr(self, "_before_results"):
            self.view.memory.planning_results = self._before_results
            self.view.memory._planning_versions = self._before_versions
            self.view.memory.conversation_state = self._before_state
            self.baseline = {key: _state_token(value) for key, value in self.view.memory.planning_results.items()}

    def result_envelope(self, result, *, changed=False):
        from agent_runtime.timepoint_targets import readset_dict
        turn = getattr(self.view, "_active_turn_context", {}) or {}
        envelope = {**self.scope.public_dict(), "request_id": str(turn.get("request_id") or ""),
            "clinical_revision": self.context.target.clinical_revision,
            "lifecycle_revision": self.context.target.lifecycle_revision,
            "readset": readset_dict(self.context)}
        metadata = dict(result.metadata or {})
        # A catalog reader owns a larger read-set than the current target.
        metadata.setdefault("readset", envelope["readset"])
        metadata.setdefault("timepoint_ids", [self.scope.timepoint_id])
        metadata.setdefault("timepoint_id", self.scope.timepoint_id)
        for key in ("content_command", "screenshot_command", "implant_command", "ui_action"):
            if isinstance(metadata.get(key), Mapping):
                metadata[key] = {**metadata[key], "scope": copy.deepcopy(envelope)}
        if isinstance(metadata.get("actions"), list):
            metadata["actions"] = [{**row, "scope": copy.deepcopy(envelope)}
                for row in metadata["actions"] if isinstance(row, Mapping)]
        result.metadata = {**metadata, "session_id": self.scope.session_id,
            "published_to_timepoint": changed or bool(metadata.get("published_to_timepoint")),
            "timepoint_clinical_revision": self.context.target.clinical_revision,
            "execution_scope": "captured_timepoint", "scope": envelope, "viewer_mounted": False}
        return result

    def accept_external_patch(self, saved, updates, removals):
        """Rebase an already-CAS-published service result without publishing twice."""
        if saved.get("timepoint_id") != self.scope.timepoint_id:
            raise TimepointConflict("A service published to a different timepoint")
        self.context = replace(self.context, target=replace(self.context.target,
            clinical_revision=saved["timepoint_clinical_revision"]))
        self.view._workspace_timepoint_context = self.context
        self.snapshot = saved
        self.encoded_results = copy.deepcopy(saved["agent"]["planning_results"])
        for key, value in updates.items():
            self.view.memory.planning_results[key] = value
            self.baseline[key] = _state_token(value)
            if hasattr(self, "_before_results"):
                self._before_results[key] = _detached(value)
        for key in removals:
            self.view.memory.planning_results.pop(key, None)
            self.baseline.pop(key, None)
            if hasattr(self, "_before_results"):
                self._before_results.pop(key, None)
        self.saved_keys = set(saved["agent"]["planning_results"])

    def commit_tool(self, result):
        if not result.success:
            self.rollback_tool()
            return self.result_envelope(result)
        results = self.view.memory.planning_results
        updates = {key: value for key, value in results.items() if key != "ct_image" and key not in SHARED_RESULT_KEYS
                   and (key not in self.baseline or _state_token(value) != self.baseline[key])}
        removals = tuple((self.saved_keys - set(results)) - SHARED_RESULT_KEYS)
        changed = bool(updates or removals)
        from agent_runtime.timepoint_capabilities import capability_contract
        name = getattr(self, "_before_tool_name", None)
        registry = getattr(self.view, "registry", None)
        tool = registry.get(name) if registry is not None and name in registry.tool_names else None
        if changed and capability_contract(name, tool) in {"declared_pure", "declared_read", "owned_file_read", "owned_experience_read"}:
            self.rollback_tool()
            raise TimepointError("The declared read/pure tool attempted to change clinical memory")
        if changed:
            from web.implant_workspace import implant_publication_guard
            with implant_publication_guard(self.view,updates):
                saved = self.store.save_timepoint_results(self.scope.owner_id, self.scope.session_id,
                    self.scope.timepoint_id, updates, expected_clinical_revision=self.context.target.clinical_revision,
                    removals=removals, execution_context=self.context)
            self.context = replace(self.context, target=replace(self.context.target,
                clinical_revision=saved["timepoint_clinical_revision"]))
            self.view._workspace_timepoint_context = self.context
            self.encoded_results = copy.deepcopy(saved["agent"]["planning_results"])
            self.snapshot = saved
            self.view.memory.planning_results = _detached(results)
            self.baseline = {key: _state_token(value) for key, value in self.view.memory.planning_results.items()}
            self.saved_keys = set(results)
        else:
            self.assert_current()
        return self.result_envelope(result, changed=changed)

    def replace_published_workspace(self, saved):
        """Accept an owned source change; never retain its old numerical grid."""
        from web.workspace_store import _restore_hydration_metadata
        values = _restore_hydration_metadata((saved.get('agent') or {}).get('planning_results') or {})
        self.accept_external_patch(saved,values,set(self.view.memory.planning_results)-set(values))
        self.view._workspace_data_ready = False
        self.view._workspace_ct_ready = False
        self.view._workspace_hydration_phase = 'metadata'
        http = getattr(self.view,'_workspace_scoped_http_runtime',None)
        if http is not None:
            from web.timepoint_hydration import clinical_hydration
            http.hydration = clinical_hydration(self.store,self.control_agent,saved,self.context)
            self.view._workspace_ready_event = http.hydration.ready

    def synchronize_conversation(self):
        """Flush shared scalar conversation state while retaining the clinical view."""
        if not self.legacy:
            # Only shared conversational fields are copied back. No patient,
            # image, plan, dose, UI or report aliases can enter the root Agent.
            with self.control_agent.memory._lock:
                for key in ("conversation", "context_summary", "compaction_count", "context_accounting", "user_lang",
                            "_context_revision", "smart_context", "tool_results"):
                    setattr(self.control_agent.memory, key, getattr(self.view.memory, key))
                self.control_agent._turn_generation = max(int(getattr(self.control_agent, "_turn_generation", 0)),
                                                          int(getattr(self.view, "_turn_generation", 0)))
                self.control_agent._pending_execution_confirmation = getattr(self.view, "_pending_execution_confirmation", None)
            for key in SHARED_RESULT_KEYS:
                value = self.view.memory.retrieve(key)
                if value is not None and value != self.control_agent.memory.retrieve(key):
                    self.control_agent.memory.store(key, copy.deepcopy(value))

    def close(self):
        if self.closed:
            return
        self.synchronize_conversation()
        self.closed = True


class ScopedToolUnavailable(TimepointError):
    code = "timepoint_tool_not_ready"


class CrossTimepointConfirmationRequired(TimepointConflict):
    code = "timepoint_target_confirmation_required"


def run_scoped_tool(agent, name, params, execute, **callbacks):
    """Common boundary for omitted and explicitly named clinical tool targets."""
    runtime = getattr(agent, "_workspace_scoped_chat_runtime", None)
    captured = (getattr(agent, "_active_turn_context", None) or {}).get("timepoint_scope")
    explicit = params.get("timepoint_id")
    if runtime is None and captured is None:
        return None
    if not isinstance(captured, ChatTimepointScope):
        raise TimepointError("A typed request target is required")
    if name in SHARED_READ_TOOLS or name == "timepoint_controller":
        if runtime is not None:
            runtime.admit_tool(name, params)
            return None
        identifier = captured.timepoint_id
    else:
        identifier = timepoint_id(explicit) if explicit is not None else captured.timepoint_id
    if identifier != captured.timepoint_id:
        # Validate ownership before any confirmation or target-specific view.
        agent._workspace_store._timepoint_record(agent._workspace_store.list_timepoints(
            captured.owner_id, captured.session_id), identifier)
        from agent_runtime.execution_authorization import tool_call_is_mutating
        if tool_call_is_mutating(name, params):
            from agent_runtime.timepoint_targets import require_human_target
            require_human_target(agent, captured, identifier, name, params)
    # Explicit stable targets take precedence without changing the default for
    # sibling calls. A different target gets a new detached clinical view.
    if runtime is not None and identifier == runtime.scope.timepoint_id:
        runtime.admit_tool(name, params)
        return None  # execute locally in this already-detached view
    catalog = agent._workspace_store.list_timepoints(captured.owner_id, captured.session_id)
    record = agent._workspace_store._timepoint_record(catalog, identifier)
    if record["legacy_default"]:
        raise ScopedToolUnavailable("The default timepoint must be detached before clinical execution")
    scope = replace(captured, timepoint_id=identifier, legacy_default=bool(record["legacy_default"]))
    child = ScopedChatRuntime(agent, scope)
    child.view._active_turn_context = {**(getattr(agent, "_active_turn_context", None) or {}),
        "timepoint_scope": scope, "submission_timepoint_scope": captured}
    # Explicit invocation state is transferred after lifecycle detachment.
    # Hydration events/cancel flags/old requests are never copied from root.
    local = getattr(agent, "_turn_local", None)
    for key in ("human_message", "token", "authorization", "confirmed_calls"):
        if local is not None and hasattr(local, key):
            setattr(child.view._turn_local, key, copy.deepcopy(getattr(local, key)))
    child.view._turn_execution_authorization = getattr(child.view._turn_local, "authorization", None)
    child.view._active_turn_token = getattr(agent, "_active_turn_token", 0)
    try:
        from web.timepoint_http import HttpTimepointBinding, bound_request
        # Legacy locks/UI bridge helpers also consult the context-local HTTP
        # binding. Rebinding memory alone leaves those services on the parent's
        # target during an explicitly addressed sibling operation.
        with bound_request(HttpTimepointBinding(scope.owner_id, scope.session_id, scope.timepoint_id)):
            child.admit_tool(name, params)
            arguments = dict(params)
            return execute(child.view, name, arguments, **callbacks)
    finally:
        child.close()
