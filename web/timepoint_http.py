"""Request-owned adapters for legacy case APIs; never a mutable active pointer.

The old route implementations still call their familiar store and Agent APIs.
This boundary supplies a detached clinical view and a target-bound store, so
their work, exports and late callbacks remain owned by the submitted scan.
Root conversation/control metadata remains shared within the patient Session.
"""
from __future__ import annotations

import copy
import contextvars
import hashlib
import json
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from web.timepoints import TimepointConflict, TimepointError, timepoint_id


@dataclass(frozen=True)
class HttpTimepointBinding:
    owner_id: str
    session_id: str
    timepoint_id: str

    def __post_init__(self):
        if not isinstance(self.owner_id, str) or not self.owner_id:
            raise TimepointError("An authenticated request owner is required")
        timepoint_id(self.session_id)
        timepoint_id(self.timepoint_id)


_UNSET = object()
_CURRENT = contextvars.ContextVar("brachybot_http_timepoint", default=_UNSET)


def current_binding():
    value = _CURRENT.get()
    if value is not _UNSET:
        return value
    try:
        from flask import g, has_request_context
        return getattr(g, "brachybot_timepoint_binding", None) if has_request_context() else None
    except RuntimeError:
        return None


@contextmanager
def bound_request(binding):
    if binding is not None and not isinstance(binding, HttpTimepointBinding):
        raise TimepointError("A typed request binding is required")
    token = _CURRENT.set(binding)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def scoped_callable(fn, binding=None):
    """Capture before starting a worker; a later navigation cannot retarget it."""
    binding = current_binding() if binding is None else binding
    def call(*args, **kwargs):
        with bound_request(binding):
            return fn(*args, **kwargs)
    return call


def scoped_iterator(iterator, binding):
    iterator = iter(iterator)
    try:
        while True:
            try:
                with bound_request(binding):
                    chunk = next(iterator)
            except StopIteration:
                return
            yield chunk
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            with bound_request(binding):
                close()


def scoped_download_url(url, binding=None):
    """Anchors/image tags carry explicit ownership without mutable tab cookies."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    binding = binding or current_binding()
    if binding is None:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(session_id=binding.session_id, timepoint_id=binding.timepoint_id)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def bucket_key(session_id, binding=None):
    binding = binding or current_binding()
    if binding is not None and str(session_id) == binding.session_id:
        return (binding.owner_id, binding.session_id, binding.timepoint_id)
    return str(session_id)


class ScopedWorkspaceStore:
    """Facade scoped either to one task or the immutable current HTTP request.

    Internal catalog/version methods always delegate to the raw store, avoiding
    recursive projection. Passing another Session to a bound facade is denied,
    not silently reinterpreted as the currently mounted patient's data.
    """
    def __init__(self, raw, binding=None, runtime=None):
        self.raw = getattr(raw, "raw", raw)
        self.binding = binding
        self.runtime = runtime

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def for_binding(self, binding=None):
        binding = current_binding() if binding is None else binding
        return ScopedWorkspaceStore(self.raw, binding, self.runtime)

    def _scope(self, user_id, session_id):
        binding = self.binding or current_binding()
        if binding is None:
            return None
        if (str(user_id), str(session_id)) != (binding.owner_id, binding.session_id):
            if self.binding is not None:
                raise TimepointConflict("This task cannot write or read another patient Session")
            return None  # Account/session control-plane operations stay shared.
        self.raw.require_local_session(user_id, session_id)
        catalog = self.raw._timepoint_catalog(user_id, session_id)
        self.raw._timepoint_record(catalog, binding.timepoint_id)
        return binding

    def _snapshot(self, user_id, session_id, binding, *, projection=None):
        result = self.raw.load_timepoint_snapshot(user_id, session_id, binding.timepoint_id, projection=projection)
        # Legacy forms use workspace/session revision interchangeably. Both
        # represent the addressed clinical workspace in this response only.
        result["session"] = {**result["session"], "session_revision": result["session"]["revision"],
            "revision": result["timepoint_state_revision"]}
        return result

    def load_snapshot(self, user_id, session_id, *, projection=None):
        binding = self._scope(user_id, session_id)
        return self._snapshot(user_id, session_id, binding, projection=projection) if binding else self.raw.load_snapshot(user_id, session_id, projection=projection)

    def save_snapshot_patch(self, user_id, session_id, patch, *, expected_revision=None, reason="workspace.updated"):
        binding = self._scope(user_id, session_id)
        if binding is None:
            return self.raw.save_snapshot_patch(user_id, session_id, patch, expected_revision=expected_revision, reason=reason)
        if not isinstance(patch, Mapping):
            raise TimepointError("A workspace patch must be an object")
        shared = {key: value for key, value in patch.items() if key in {"chat"}}
        local = {key: value for key, value in patch.items() if key != "chat"}
        allowed = {"ui", "report", "operation", "agent", "viewer_annotations", "review"}
        if set(local) - allowed:
            raise TimepointError("Unsupported scoped workspace section")
        if local:
            with self.raw._case_guard(user_id, session_id):
                catalog = self.raw._timepoint_catalog(user_id, session_id)
                item = self.raw._timepoint_record(catalog, binding.timepoint_id)
                if expected_revision is not None and expected_revision != item["state_revision"]:
                    raise TimepointConflict("This timepoint was updated; reload it before saving")
                state = self.raw._read_timepoint_state(user_id, session_id, item)
                from web.timepoints import merge_presentation_patch
                from web.workspace_store import _safe_json, _merge_report_patch, _sanitize_report_for_snapshot
                for section, incoming in local.items():
                    if not isinstance(incoming, Mapping):
                        raise TimepointError("Workspace section patches must be objects")
                    if section == "agent" and "planning_results" in incoming:
                        raise TimepointError("Browser snapshots cannot publish numerical planning results")
                    value = _safe_json(incoming)
                    if section == "report":
                        state[section] = _sanitize_report_for_snapshot(
                            _merge_report_patch(state.get(section) or {}, value), state, session_id)
                    else:
                        state[section] = merge_presentation_patch(state.get(section), value)
                self.raw._publish_timepoint_state(user_id, session_id, catalog, item, state, retain_previous=False)
        if shared:
            self.raw.save_snapshot_patch(user_id, session_id, shared, reason=reason)
        return self._snapshot(user_id, session_id, binding)

    def save_viewer_annotations(self, user_id, session_id, annotations, tree_annotations):
        for rows in (annotations, tree_annotations):
            if not isinstance(rows, list) or len(rows) > 10000 or any(not isinstance(row, Mapping) for row in rows):
                raise TimepointError("Invalid annotation records")
            ids = [str(row.get("id") or "") for row in rows]
            if any(not value for value in ids) or len(set(ids)) != len(ids):
                raise TimepointError("Annotations require unique IDs")
        if {row["id"] for row in annotations} != {row["id"] for row in tree_annotations}:
            raise TimepointError("Annotation geometry and tree identities disagree")
        return self.save_snapshot_patch(user_id, session_id, {"viewer_annotations": {
            "annotations": annotations, "data_tree_annotations": tree_annotations}})

    def replace_snapshot_section(self, user_id, session_id, section, value, *, reason="workspace.section_replaced", expected_revision=None):
        binding = self._scope(user_id, session_id)
        if binding is None or section == "chat":
            return self.raw.replace_snapshot_section(user_id, session_id, section, value, reason=reason,
                expected_revision=expected_revision if binding is None else None)
        if section not in {"ui", "report", "operation"} or not isinstance(value, Mapping):
            raise TimepointError("Unsupported target presentation section")
        with self.raw._case_guard(user_id, session_id):
            catalog = self.raw._timepoint_catalog(user_id, session_id)
            item = self.raw._timepoint_record(catalog, binding.timepoint_id)
            if expected_revision is not None and expected_revision != item["state_revision"]:
                raise TimepointConflict("The timepoint changed before section replacement")
            state = self.raw._read_timepoint_state(user_id, session_id, item)
            from web.workspace_store import _safe_json
            state[section] = _safe_json(dict(value))
            return self.raw._publish_timepoint_state(user_id, session_id, catalog, item, state, retain_previous=False)

    def save_agent_results_patch(self, user_id, session_id, updates=None, removals=None, *, reason="agent.results.patch", expected_revision=None):
        binding = self._scope(user_id, session_id)
        if binding is None:
            return self.raw.save_agent_results_patch(user_id, session_id, updates, removals,
                reason=reason, expected_revision=expected_revision)
        snapshot = self.raw.load_timepoint_snapshot(user_id, session_id, binding.timepoint_id)
        if expected_revision is not None and expected_revision != snapshot["timepoint_state_revision"]:
            raise TimepointConflict("The target changed before this clinical patch")
        context = getattr(getattr(self.runtime, "clinical", None), "context", None)
        saved = self.raw.save_timepoint_results(user_id, session_id, binding.timepoint_id, updates or {},
            removals=removals or (), expected_clinical_revision=(context.target.clinical_revision
                if context else snapshot["timepoint_clinical_revision"]), execution_context=context)
        if self.runtime is not None and hasattr(self.runtime, "accept_external_patch"):
            self.runtime.accept_external_patch(saved, updates or {}, removals or ())
        return saved

    def save_agent_results_delta(self, user_id, session_id, updates=None, removals=None, *, reason="agent.results.delta", expected_revision=None):
        return self.save_agent_results_patch(user_id, session_id, updates, removals,
            reason=reason, expected_revision=expected_revision)

    def save_ui_bridge(self, user_id, session_id, bridge, *, reason="ui.bridge"):
        binding = self._scope(user_id, session_id)
        if binding is None:
            return self.raw.save_ui_bridge(user_id, session_id, bridge, reason=reason)
        return self.save_snapshot_patch(user_id, session_id, {"ui": {"bridge": bridge}}, reason=reason)

    def load_ui_bridge(self, user_id, session_id):
        binding = self._scope(user_id, session_id)
        if binding is None:
            return self.raw.load_ui_bridge(user_id, session_id)
        return copy.deepcopy((self.raw.load_timepoint_snapshot(user_id, session_id, binding.timepoint_id).get("ui") or {}).get("bridge") or {})

    def _runtime_for(self, agent):
        return getattr(agent, "_workspace_scoped_http_runtime", None) or getattr(agent, "_workspace_scoped_chat_runtime", None)

    def schedule_agent_checkpoint(self, user_id, session_id, agent, reason, operation=None):
        runtime = self._runtime_for(agent)
        if runtime is None:
            return self.raw.schedule_agent_checkpoint(user_id, session_id, agent, reason, operation=operation)
        if hasattr(runtime, "mark_dirty"):
            runtime.mark_dirty(operation=operation)

    def flush_agent_checkpoint(self, user_id, session_id, agent, reason, operation=None):
        runtime = self._runtime_for(agent)
        if runtime is None:
            return self.raw.flush_agent_checkpoint(user_id, session_id, agent, reason, operation=operation)
        if hasattr(runtime, "checkpoint"):
            return runtime.checkpoint(operation=operation)
        # Scoped chat commits each successful tool before final conversation
        # persistence; do not replay its arrays through a root checkpoint.
        runtime.assert_current()
        from web.workspace_store import _safe_json
        shared_keys = ("conversation", "context_summary", "compaction_count", "context_accounting", "user_lang")
        control = {key: _safe_json(getattr(agent.memory, key)) for key in shared_keys if hasattr(agent.memory, key)}
        self.raw.save_shared_agent_control(user_id, session_id, control, reason=reason)
        if operation is not None:
            bound = HttpTimepointBinding(runtime.scope.owner_id, runtime.scope.session_id, runtime.scope.timepoint_id)
            ScopedWorkspaceStore(self.raw, bound).save_snapshot_patch(user_id, session_id, {"operation": operation}, reason=reason)
        return self.raw.load_timepoint_snapshot(user_id, session_id, runtime.scope.timepoint_id)

    def mark_operation(self, user_id, session_id, agent, operation):
        return self.flush_agent_checkpoint(user_id, session_id, agent, "operation.checkpoint", operation=operation)

    def _category(self, category, binding):
        return str(category) + "_tp_" + binding.timepoint_id if binding else category

    def workspace_output_transaction(self, user_id, session_id, category, **kwargs):
        return self.raw.workspace_output_transaction(user_id, session_id,
            self._category(category, self._scope(user_id, session_id)), **kwargs)

    def write_artifact(self, user_id, session_id, category, filename, stream, expected_bytes=0):
        return self.raw.write_artifact(user_id, session_id,
            self._category(category, self._scope(user_id, session_id)), filename, stream, expected_bytes)

    def write_upload(self, user_id, session_id, relative, stream, expected_bytes=0):
        binding = self._scope(user_id, session_id)
        relative = f"timepoints/{binding.timepoint_id}/{relative}" if binding else relative
        return self.raw.write_upload(user_id, session_id, relative, stream, expected_bytes)

    def write_screenshot(self, user_id, session_id, filename, png):
        binding = self._scope(user_id, session_id)
        if binding and not str(filename).startswith(binding.timepoint_id + "_"):
            filename = binding.timepoint_id + "_" + str(filename)
        return self.raw.write_screenshot(user_id, session_id, filename, png)

    def session_artifact_path(self, user_id, session_id, category, filename):
        """Retain legacy files only on their migrated default, never a sibling."""
        import re
        from pathlib import PurePosixPath
        from web.workspace_store import WorkspaceNotFound
        binding = self.binding or current_binding()
        if binding is None:
            return self.raw.session_artifact_path(user_id,session_id,category,filename)
        if (str(user_id),str(session_id)) != (binding.owner_id,binding.session_id):
            raise WorkspaceNotFound('Artifact not found in this captured workspace')
        # Preserve ownership/traversal validation before interpreting provenance.
        path = self.raw.session_artifact_path(user_id,session_id,category,filename)
        catalog = self.raw.list_timepoints(user_id,session_id)
        self.raw._timepoint_record(catalog,binding.timepoint_id)
        parts = PurePosixPath(str(filename).replace('\\','/')).parts
        if category == 'screenshots':
            match = re.match(r'^([0-9a-f]{32})_', parts[0] if parts else '')
        elif category == 'artifacts':
            match = re.search(r'_tp_([0-9a-f]{32})$',parts[0] if parts else '')
        else:
            raise WorkspaceNotFound('Artifact category is not a scoped download')
        target = match.group(1) if match else catalog['default_timepoint_id']
        if target != binding.timepoint_id:
            raise WorkspaceNotFound('Artifact not found in this captured timepoint')
        return path


class ScopedHttpRuntime:
    """One HTTP operation, including streaming work after navigation changes."""
    def __init__(self, control_agent, binding, *, lightweight=False):
        from web.timepoint_chat import ChatTimepointScope, ScopedChatRuntime
        self.binding = binding
        scope = ChatTimepointScope(binding.owner_id, binding.session_id, binding.timepoint_id,
            "zh" if str(control_agent.memory.user_lang).startswith("zh") else "en", False)
        # Capture once and reuse completed immutable hydration directly. The
        # old warm path first built/copied placeholder history, then hashed and
        # replaced it with decoded history on every slice/mask request.
        from web.timepoint_hydration import clinical_hydration
        provided_store = control_agent._workspace_store
        raw_store = getattr(provided_store, 'raw', provided_store)
        from flask import has_request_context, request
        # These routes consume clinical arrays/geometry and never edit browser
        # presentation or reports. Large saved UI packets are irrelevant to a
        # mesh or raster slice and must not be copied on every read.
        resource_only = has_request_context() and request.path in {
            '/api/viewer/3d_mask', '/api/viewer/volume', '/api/viewer/slice',
            '/api/viewer/label_volume', '/api/viewer/generic_masks', '/api/viewer/generic_mask_volume',
            '/api/viewer/3d_skin', '/api/viewer/skin_surface_volume',
            '/api/planning/dose_contour_slice', '/api/planning/dose_overlay_slice',
            '/api/planning/dose_overlay_volume',
        }
        context = raw_store.capture_timepoint_context(binding.owner_id, binding.session_id, binding.timepoint_id)
        snapshot = raw_store.load_timepoint_snapshot(binding.owner_id, binding.session_id,
            binding.timepoint_id, include_shared=False, defer_results=True, resource_only=resource_only)
        self.hydration = clinical_hydration(raw_store, control_agent, snapshot, context)
        hydrated = self.hydration.values if self.hydration.ready.is_set() and self.hydration.error is None else None
        self.clinical = ScopedChatRuntime(control_agent, scope, include_shared=False,
            _snapshot=snapshot, _context=context, _hydrated_values=hydrated, _defer_results=True, _defer_ui=resource_only)
        self.view = self.clinical.view
        self.raw_store = self.clinical.store
        self.store = ScopedWorkspaceStore(self.raw_store, binding, self)
        self.view._workspace_store = self.store
        self.view._workspace_scoped_http_runtime = self
        self._lock = threading.RLock()
        self.dirty = False
        self.operation = None
        import uuid
        self.operation_id = uuid.uuid4().hex
        self.closed = False
        self.view.memory.set_persistence_callback(lambda reason: self.mark_dirty())
        self.view._workspace_ready_event = self.hydration.ready
        self.view._workspace_ct_ready = self.view._workspace_data_ready and self.view.memory.retrieve('ct_data') is not None
        self.view._workspace_hydration_error = ''
        self.view._workspace_hydration_in_progress = not self.hydration.ready.is_set()
        self.view._workspace_hydration_phase = "artifacts" if self.view._workspace_hydration_in_progress else "ready"
        self.view._workspace_resource_waiter = self.hydrate
        if not lightweight or self.hydration.ready.is_set():
            self.hydrate(True)
        with bound_request(binding):
            from web import server_support
            bucket = server_support._ui_bucket(binding.session_id)
            with server_support._UI_BRIDGE_LOCK:
                if not bucket.get("updated_at"):
                    bridge = self.store.load_ui_bridge(binding.owner_id, binding.session_id)
                    if bridge:
                        bucket.update(state=copy.deepcopy(bridge.get("state") or {}),
                            events=copy.deepcopy(bridge.get("events") or []),
                            training=server_support._close_stale_training_snapshot(bridge.get("training") or {}),
                            updated_at=bridge.get("updated_at"))

    def hydrate(self, required):
        self.clinical.assert_current()
        if not required or self.view._workspace_data_ready:
            return
        if not self.hydration.ready.wait(timeout=300):
            raise TimepointConflict("The owned timepoint resources did not finish loading")
        if self.hydration.error is not None:
            self.view._workspace_hydration_error = str(self.hydration.error)
            self.view._workspace_hydration_phase = "failed"
            raise self.hydration.error
        self.clinical.assert_current()
        from web.timepoint_chat import _detached, _state_token
        from web.resource_view import RequestResults
        decoded = RequestResults(self.hydration.values or {})
        existing = self.view.memory.planning_results
        materialized = existing.materialized_items() if isinstance(existing, RequestResults) else existing.items()
        pending = {key: value for key, value in materialized
            if key not in self.clinical.baseline or _state_token(value) != self.clinical.baseline[key]}
        removals = set(self.clinical.baseline) - set(existing)
        self.clinical.baseline = decoded.baseline
        decoded.update(pending)
        for key in removals:
            decoded.pop(key, None)
        self.view.memory.planning_results = decoded
        self.view._workspace_data_ready = True
        self.view._workspace_ct_ready = decoded.get("ct_data") is not None
        self.view._workspace_hydration_in_progress = False
        self.view._workspace_hydration_phase = "ready"

    def mark_dirty(self, operation=None):
        with self._lock:
            self.dirty = True
            if operation is not None:
                self.operation = copy.deepcopy(dict(operation))
                self.raw_store.save_timepoint_operation(self.binding.owner_id, self.binding.session_id,
                    self.binding.timepoint_id, self.operation_id, self.operation)

    def checkpoint(self, operation=None):
        from tool_factory import ToolResult
        with self._lock, bound_request(self.binding):
            if self.closed:
                raise TimepointConflict("This request's clinical binding has ended")
            if operation is not None:
                self.operation = copy.deepcopy(dict(operation))
            result = self.clinical.commit_tool(ToolResult(success=True, message="Scoped HTTP checkpoint"))
            if self.operation is not None:
                self.raw_store.save_timepoint_operation(self.binding.owner_id, self.binding.session_id,
                    self.binding.timepoint_id, self.operation_id, self.operation)
                self.store.save_snapshot_patch(self.binding.owner_id, self.binding.session_id,
                    {"operation": self.operation})
                self.operation = None
            # UI-only edits must not increment clinical revision.
            self.store.save_snapshot_patch(self.binding.owner_id, self.binding.session_id,
                {"ui": {"state": self.view.memory.get_ui_state()}})
            self.dirty = False
            return self.store.load_snapshot(self.binding.owner_id, self.binding.session_id)

    def accept_external_patch(self, saved, updates, removals):
        from dataclasses import replace
        from web.timepoint_chat import _state_token
        with self._lock:
            runtime = self.clinical
            runtime.context = replace(runtime.context, target=replace(runtime.context.target,
                clinical_revision=saved["timepoint_clinical_revision"]))
            runtime.view._workspace_timepoint_context = runtime.context
            runtime.snapshot = saved
            runtime.encoded_results = copy.deepcopy(saved["agent"]["planning_results"])
            for key in updates:
                if key in runtime.view.memory.planning_results:
                    runtime.baseline[key] = _state_token(runtime.view.memory.planning_results[key])
            for key in removals:
                runtime.baseline.pop(key, None)
            runtime.saved_keys = set(saved["agent"]["planning_results"])

    def close(self, *, commit=True):
        with self._lock:
            if self.closed:
                return
            if commit and self.dirty:
                self.checkpoint()
            latest = self.raw_store.latest_timepoint_operation(self.binding.owner_id, self.binding.session_id, self.binding.timepoint_id)
            if latest and latest.get("operation_id") == self.operation_id and latest.get("state") == "running":
                self.raw_store.save_timepoint_operation(self.binding.owner_id, self.binding.session_id,
                    self.binding.timepoint_id, self.operation_id, {**latest, "state": "ready" if commit else "interrupted"})
            # HTTP display/manual requests do not own conversational scalars.
            # Closing an older Viewer request must not reset accounting or a
            # chat turn's pending confirmation with the values it copied.
            self.clinical.closed = True
            self.closed = True
