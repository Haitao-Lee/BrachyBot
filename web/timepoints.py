"""Owned, revisioned timepoint catalog and immutable workspace states.

The catalog lives in SQLite. State manifests and numerical sidecars are
published before their catalog reference, so an interrupted write leaves an
orphan rather than a partially visible clinical state. The original schema-1
workspace is a live default-timepoint projection; no legacy file is moved.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Mapping


def _resource_snapshot(state, *, resource_only=False):
    """Detach presentation/metadata now, clinical history only when requested."""
    from web.timepoint_chat import _detached
    from web.resource_view import RequestResults
    agent = state.get('agent') or {}
    excluded = {'chat', 'ui', 'report', 'image_presentations'} if resource_only else {'chat'}
    excluded_agent = set(_SHARED_AGENT_KEYS) | {'ui_state'} if resource_only else _SHARED_AGENT_KEYS
    result = _detached({**{k:v for k,v in state.items() if k not in excluded},
        'agent': {**{k:v for k,v in agent.items() if k not in excluded_agent}, 'planning_results': {}}})
    result['agent']['planning_results'] = RequestResults(agent.get('planning_results') or {})
    return result


def _manifest_projection(state, *, resource_only=False, image_metadata=False):
    if image_metadata:
        from web.timepoint_chat import _detached
        return _detached({'image_collection': state['image_collection']}) if 'image_collection' in state else {}
    return _resource_snapshot(state, resource_only=resource_only)


CATALOG_VERSION = 1
MAX_TIMEPOINTS = 256
MAX_HISTORY = 256
_ID = re.compile(r"^[0-9a-f]{32}$")
_SHARED_AGENT_KEYS = (
    "conversation", "context_summary", "compaction_count", "context_accounting",
    "user_lang",
)


class TimepointError(ValueError):
    code = "invalid_timepoint"


class TimepointNotFound(TimepointError):
    code = "timepoint_not_found"


class TimepointConflict(TimepointError):
    code = "timepoint_conflict"


class TimepointDependencyConflict(TimepointConflict):
    code = "timepoint_dependencies"

    def __init__(self, dependents):
        self.dependents = list(dependents)
        super().__init__("Other timepoints still reference this timepoint")


class TimepointIntegrityError(TimepointError):
    code = "timepoint_integrity_error"


def timepoint_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise TimepointError("A timepoint ID must be a 32-character lowercase UUID")
    return value


def revision(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TimepointError("A revision must be a nonnegative integer")
    return value


def title(value):
    if not isinstance(value, str):
        raise TimepointError("A timepoint title must be text")
    value = value.strip()
    if not value or len(value) > 160 or any(ord(c) < 32 for c in value):
        raise TimepointError("A timepoint title must contain 1 to 160 printable characters")
    return value


def default_timepoint_id(session_id):
    return uuid.uuid5(uuid.NAMESPACE_URL, "brachybot:timepoint:" + str(session_id)).hex


def new_record(identifier, name, *, legacy_default=False, now=None):
    now = time.time() if now is None else float(now)
    return {
        "id": timepoint_id(identifier), "title": title(name), "auto_title": bool(legacy_default),
        "stage": "preoperative", "preoperative_timepoint_id": None,
        "previous_intraoperative_timepoint_id": None, "episode_id": None,
        "status": "active", "revision": 0, "state_revision": 0, 'lifecycle_revision': 0,
        "clinical_revision": 0, "presentation_revision": 0,
        "legacy_default": bool(legacy_default), "state_ref": None,
        "state_history": [], "created_at": now, "updated_at": now,
        "deleted_at": None,
    }


def default_catalog(session_id, *, created_at=None):
    identifier = default_timepoint_id(session_id)
    return {
        "schema_version": CATALOG_VERSION, "session_id": str(session_id),
        "catalog_revision": 0, "default_timepoint_id": identifier,
        "order": [identifier],
        "items": {identifier: new_record(identifier, "Preoperative", legacy_default=True, now=created_at)},
    }


def validate_catalog(catalog, session_id):
    if not isinstance(catalog, dict) or catalog.get("schema_version") != CATALOG_VERSION:
        raise TimepointIntegrityError("Unsupported timepoint catalog")
    if catalog.get("session_id") != str(session_id):
        raise TimepointIntegrityError("The timepoint catalog belongs to another Session")
    revision(catalog.get("catalog_revision"))
    items, order = catalog.get("items"), catalog.get("order")
    if not isinstance(items, dict) or not 1 <= len(items) <= MAX_TIMEPOINTS:
        raise TimepointIntegrityError("Invalid timepoint catalog size")
    if not isinstance(order, list) or len(order) != len(set(order)) or set(order) != set(items):
        raise TimepointIntegrityError("The timepoint order does not match its identities")
    default = timepoint_id(catalog.get("default_timepoint_id"))
    if default not in items:
        raise TimepointIntegrityError("The default timepoint is unavailable")
    for identifier, item in items.items():
        timepoint_id(identifier)
        if not isinstance(item, dict) or item.get("id") != identifier:
            raise TimepointIntegrityError("Invalid timepoint record identity")
        title(item.get("title"))
        revision(item.get("revision"))
        revision(item.get("state_revision"))
        revision(item.get("clinical_revision", 0))
        revision(item.get("lifecycle_revision", 0))
        revision(item.get("presentation_revision", 0))
        if item.get("status") not in {"active", "trashed"}:
            raise TimepointIntegrityError("Invalid timepoint lifecycle")
        if item.get("stage") not in {"preoperative", "intraoperative"}:
            raise TimepointIntegrityError("Invalid timepoint stage")
        source = item.get("preoperative_timepoint_id")
        if item["stage"] == "intraoperative":
            if source == identifier or source not in items or items[source]["stage"] != "preoperative":
                raise TimepointIntegrityError("An intraoperative timepoint requires a preoperative source")
            if item["status"] == "active" and items[source]["status"] != "active":
                raise TimepointIntegrityError("An active source timepoint cannot be deleted")
        elif source is not None:
            raise TimepointIntegrityError("A preoperative timepoint cannot have a preoperative source")
        previous = item.get("previous_intraoperative_timepoint_id")
        if previous is not None:
            if previous == identifier or previous not in items or items[previous]["stage"] != "intraoperative":
                raise TimepointIntegrityError("Invalid previous intraoperative timepoint")
            if items[previous].get("preoperative_timepoint_id") != source:
                raise TimepointIntegrityError("An intraoperative sequence must have one preoperative source")
            if item["status"] == "active" and items[previous]["status"] != "active":
                raise TimepointIntegrityError("An active predecessor cannot be deleted")
        # Explicit sequence links cannot form a cycle.
        seen, cursor = {identifier}, previous
        while cursor is not None:
            if cursor in seen:
                raise TimepointIntegrityError("The intraoperative sequence contains a cycle")
            seen.add(cursor)
            cursor = items[cursor].get("previous_intraoperative_timepoint_id")
        history = item.get("state_history")
        if not isinstance(history, list) or len(history) > MAX_HISTORY:
            raise TimepointIntegrityError("Invalid retained state history")
        for state in [item.get("state_ref"), *history]:
            if state is None:
                continue
            if not isinstance(state, dict) or not isinstance(state.get("arrays"), list):
                raise TimepointIntegrityError("Invalid state manifest reference")
            if not isinstance(state.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", state["sha256"]):
                raise TimepointIntegrityError("Invalid state manifest checksum")
    return catalog


def public_catalog(catalog):
    """Never serialize another timepoint's clinical results into the catalog."""
    result = {k: copy.deepcopy(v) for k, v in catalog.items() if k != "items"}
    result["items"] = {}
    for identifier, item in catalog["items"].items():
        result["items"][identifier] = {
            k: copy.deepcopy(v) for k, v in item.items()
            if k not in {"state_ref", "state_history"}
        }
        result['items'][identifier].setdefault('clinical_revision', 0)
        result['items'][identifier].setdefault('lifecycle_revision', 0)
    result["timepoints"] = [result["items"][i] for i in result["order"]]
    # Catalog edits depend on names/stages/references/lifecycle, not the
    # immutable state pointer changed by every appearance checkpoint.
    import hashlib
    metadata = {'order': catalog['order'], 'default_timepoint_id': catalog['default_timepoint_id'],
                'items': {key: {field: value.get(field) for field in ('id','title','auto_title','stage',
                    'preoperative_timepoint_id','previous_intraoperative_timepoint_id','episode_id',
                    'status','revision','lifecycle_revision','deleted_at')} for key,value in result['items'].items()}}
    result['metadata_signature'] = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    # Enable only after all existing runtime entrypoints enforce captured scope.
    result["capabilities"] = {"execution_scope": bool(catalog.get("runtime_migration_version")), "catalog": True, "durable_states": True,
                              "explicit_pipeline_tool": True, "chat_target_binding": True}
    return result


def merge_presentation_patch(current, incoming):
    """Partial appearance updates retain sibling controls; arrays replace explicitly."""
    result = copy.deepcopy(dict(current)) if isinstance(current, Mapping) else {}
    for key, value in incoming.items():
        result[key] = (merge_presentation_patch(result.get(key), value)
                       if isinstance(value, Mapping) else copy.deepcopy(value))
    return result


def compact_restore_presentation(ui):
    """Store restore values without duplicating the live capability dictionary.

    The authoritative detailed dictionary remains in ui.bridge.state. It is
    for Agent inspection, not pixels/controls restored separately for every
    image. Recreating it from the mounted DOM is already the browser contract.
    """
    value = copy.deepcopy(dict(ui or {}))
    fields = ('ui_operation_catalog','visual_target_catalog','ui_operations','action_capabilities')
    state = value.get('state')
    if isinstance(state,dict):
        for field in fields:
            state.pop(field,None)
    return value


class TimepointStoreMixin:
    """Explicitly scoped APIs; never swap a global active workspace pointer."""

    def _initialize_timepoints(self):
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS timepoint_catalogs (
                    session_id TEXT PRIMARY KEY REFERENCES case_sessions(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    manifest_path TEXT NOT NULL, catalog_json TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS timepoint_state_versions (
                    session_id TEXT NOT NULL REFERENCES case_sessions(id) ON DELETE CASCADE,
                    timepoint_id TEXT NOT NULL, state_revision INTEGER NOT NULL,
                    state_ref_json TEXT NOT NULL,
                    PRIMARY KEY(session_id, timepoint_id, state_revision)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS timepoint_operations (
                    operation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL REFERENCES case_sessions(id) ON DELETE CASCADE,
                    timepoint_id TEXT NOT NULL, state TEXT NOT NULL,
                    process_id INTEGER NOT NULL, process_start TEXT NOT NULL,
                    updated_at REAL NOT NULL, operation_json TEXT NOT NULL
                )
            """)

    def migrate_default_timepoint(self, user_id, session_id):
        """Detach schema-1 clinical state exactly once, retaining its recovery copy.

        Only the new immutable manifest and catalog are published. The old
        snapshot is not moved or erased; shared chat keeps using it and a
        crash before the catalog commit remains an ordinary legacy workspace.
        All runtime clinical readers/writers use the detached target after
        this transaction, so chat and display saves cannot change its inputs.
        """
        with self._case_guard(user_id, session_id):
            catalog = self._timepoint_catalog(user_id, session_id)
            if catalog.get("runtime_migration_version") == 1:
                return public_catalog(catalog)
            item = self._timepoint_record(catalog, catalog["default_timepoint_id"])
            if not item["legacy_default"]:
                raise TimepointIntegrityError("Incomplete default migration metadata")
            context = self.capture_timepoint_context(user_id, session_id, item["id"])
            state = copy.deepcopy(self.load_snapshot(user_id, session_id))
            state.pop("session", None)
            state.pop("workspace", None)
            state["migration"] = {"source_schema": 1, "source_session_revision":
                self.get_session(user_id, session_id).revision, "version": 1}
            bridge = self.load_ui_bridge(user_id, session_id)
            if bridge:
                from web.server_support import select_case_bridge
                state.setdefault("ui", {})["bridge"] = select_case_bridge(
                    (state.get("ui") or {}).get("bridge") or {}, bridge)
            item["legacy_default"] = False
            item["lifecycle_revision"] = item.get("lifecycle_revision", 0) + 1
            catalog["runtime_migration_version"] = 1
            self._publish_timepoint_state(user_id, session_id, catalog, item, state,
                retain_previous=False, clinical_change=True, execution_context=context)
            return self.list_timepoints(user_id, session_id, include_trashed=True)

    def _timepoint_catalog(self, user_id, session_id):
        session_record = self.require_local_session(user_id, session_id)
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT catalog_json, revision FROM timepoint_catalogs WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        if row is None:
            return default_catalog(session_id, created_at=session_record.created_at)
        try:
            catalog = json.loads(row["catalog_json"])
            validate_catalog(catalog, session_id)
            if catalog["catalog_revision"] != row["revision"]:
                raise TimepointIntegrityError("Catalog publication revisions disagree")
            return catalog
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise TimepointIntegrityError("The timepoint catalog is unreadable") from exc

    def list_timepoints(self, user_id, session_id, *, include_trashed=False):
        catalog = public_catalog(self._timepoint_catalog(user_id, session_id))
        if not include_trashed:
            catalog["timepoints"] = [r for r in catalog["timepoints"] if r["status"] == "active"]
            catalog["items"] = {r["id"]: r for r in catalog["timepoints"]}
            catalog["order"] = [r["id"] for r in catalog["timepoints"]]
        return catalog

    def _timepoint_record(self, catalog, identifier, *, include_trashed=False):
        identifier = timepoint_id(identifier)
        record = catalog["items"].get(identifier)
        if record is None or (record["status"] != "active" and not include_trashed):
            raise TimepointNotFound("The timepoint is unavailable")
        return record

    def _publish_timepoint_catalog(self, user_id, session_id, catalog, expected_revision, *, execution_context=None):
        from web.workspace_store import _atomic_bytes, _safe_workspace_child

        expected_revision = revision(expected_revision)
        catalog["catalog_revision"] = expected_revision + 1
        validate_catalog(catalog, session_id)
        root = self.workspace_root(user_id, session_id, create=True)
        relative = "timepoints/catalog/" + uuid.uuid4().hex + ".json"
        path = _safe_workspace_child(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(catalog, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        with self._quota_commit_lock(user_id):
            self._ensure_replacement_capacity(user_id, path, len(payload.encode("utf-8")))
            _atomic_bytes(path, payload.encode("utf-8"))
            self._invalidate_storage_usage(user_id)
            # Files exist before the SQLite commit; failed CAS leaves an orphan.
            with self._connection() as connection, connection:
                # _connection uses autocommit: BEGIN is essential for a
                # cross-process read/check/update compare-and-swap boundary.
                connection.execute("BEGIN IMMEDIATE")
                old = connection.execute(
                    "SELECT revision, catalog_json FROM timepoint_catalogs WHERE session_id = ? AND user_id = ?",
                    (session_id, user_id),
                ).fetchone()
                actual = int(old["revision"]) if old is not None else 0
                if actual != expected_revision:
                    raise TimepointConflict("The timepoint catalog changed; reload it before editing")
                if execution_context is not None:
                    # Check the entire captured read-set inside the same
                    # database transaction as publication, including another
                    # process updating a source scan after encoding started.
                    owned = connection.execute(
                        "SELECT revision, status, storage_status FROM case_sessions WHERE id = ? AND user_id = ?",
                        (session_id, user_id),
                    ).fetchone()
                    if not owned or owned["status"] != "active" or owned["storage_status"] != "active":
                        raise TimepointConflict("The execution patient is deleted or archived")
                    original = json.loads(old["catalog_json"]) if old is not None else default_catalog(session_id)
                    execution_context.assert_current(user_id, session_id, original, legacy_revision=int(owned["revision"]))
                connection.execute(
                    "INSERT INTO timepoint_catalogs(session_id, user_id, revision, manifest_path, catalog_json) "
                    "VALUES(?, ?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
                    "revision = excluded.revision, manifest_path = excluded.manifest_path, catalog_json = excluded.catalog_json",
                    (session_id, user_id, catalog["catalog_revision"], relative, payload),
                )
                for identifier, record in catalog["items"].items():
                    ref = record.get("state_ref")
                    if ref is not None:
                        connection.execute(
                            "INSERT OR IGNORE INTO timepoint_state_versions "
                            "(session_id,timepoint_id,state_revision,state_ref_json) VALUES(?,?,?,?)",
                            (session_id, identifier, record["state_revision"], json.dumps(ref, allow_nan=False)),
                        )
        self._audit(user_id, session_id, "timepoint.catalog_published", {
            "catalog_revision": catalog["catalog_revision"], "manifest": relative,
        })
        return public_catalog(catalog)

    def create_timepoint(self, user_id, session_id, name, *, expected_revision,
                         stage="preoperative", preoperative_timepoint_id=None):
        with self._case_guard(user_id, session_id):
            catalog = self._timepoint_catalog(user_id, session_id)
            if revision(expected_revision) != catalog["catalog_revision"]:
                raise TimepointConflict("The timepoint catalog changed")
            if len(catalog["items"]) >= MAX_TIMEPOINTS:
                raise TimepointError("This Session has reached its timepoint limit")
            item = new_record(uuid.uuid4().hex, name)
            item["stage"] = stage
            item["preoperative_timepoint_id"] = preoperative_timepoint_id
            catalog["items"][item["id"]] = item
            catalog["order"].append(item["id"])
            result = self._publish_timepoint_catalog(user_id, session_id, catalog, expected_revision)
            result["created_timepoint_id"] = item["id"]
            return result

    def update_timepoint(self, user_id, session_id, identifier, patch, *, expected_revision):
        if not isinstance(patch, Mapping) or set(patch) - {
            "title", "stage", "preoperative_timepoint_id", "previous_intraoperative_timepoint_id", "episode_id",
        }:
            raise TimepointError("Unsupported timepoint metadata patch")
        with self._case_guard(user_id, session_id):
            catalog = self._timepoint_catalog(user_id, session_id)
            if revision(expected_revision) != catalog["catalog_revision"]:
                raise TimepointConflict("The timepoint catalog changed")
            item = self._timepoint_record(catalog, identifier)
            if "title" in patch:
                item["title"] = title(patch["title"])
                item["auto_title"] = False
            for key in ("stage", "preoperative_timepoint_id", "previous_intraoperative_timepoint_id", "episode_id"):
                if key in patch and patch[key] != item.get(key):
                    if item.get('clinical_revision',0) or item["legacy_default"]:
                        raise TimepointConflict("Reclassifying populated/legacy clinical data requires an explicit migration")
                    if key == "episode_id" and patch[key] is not None:
                        timepoint_id(patch[key])
                    item[key] = patch[key]
                    item['lifecycle_revision']=item.get('lifecycle_revision',0)+1
            item["revision"] += 1
            item["updated_at"] = time.time()
            return self._publish_timepoint_catalog(user_id, session_id, catalog, expected_revision)

    def timepoint_delete_impact(self, user_id, session_id, identifier):
        catalog = self._timepoint_catalog(user_id, session_id)
        item = self._timepoint_record(catalog, identifier)
        dependents = [r["id"] for r in catalog["items"].values()
                      if r["status"] == "active" and r["id"] != identifier and
                      identifier in {r.get("preoperative_timepoint_id"), r.get("previous_intraoperative_timepoint_id")}]
        return {"id": identifier, "dependents": dependents, "recoverable": True,
                "can_delete": not dependents and not item["legacy_default"],
                "reason": "legacy_default_requires_runtime_migration" if item["legacy_default"] else None}

    def delete_timepoint(self, user_id, session_id, identifier, *, expected_revision):
        with self._case_guard(user_id, session_id):
            catalog = self._timepoint_catalog(user_id, session_id)
            if revision(expected_revision) != catalog["catalog_revision"]:
                raise TimepointConflict("The timepoint catalog changed")
            item = self._timepoint_record(catalog, identifier)
            impact = self.timepoint_delete_impact(user_id, session_id, identifier)
            if impact["dependents"]:
                raise TimepointDependencyConflict(impact["dependents"])
            if item["legacy_default"]:
                raise TimepointConflict("Legacy default deletion is gated until runtime scoping is complete")
            workspace = self._read_timepoint_state(user_id, session_id, item)
            live_operation = self.latest_timepoint_operation(user_id, session_id, identifier)
            if (workspace.get("operation") or {}).get("state") == "running" or (live_operation or {}).get("state") == "running":
                raise TimepointConflict("Stop and drain the timepoint task before deleting it")
            item.update(status="trashed", deleted_at=time.time(), updated_at=time.time(), revision=item["revision"] + 1,
                        lifecycle_revision=item.get("lifecycle_revision", 0) + 1)
            if catalog["default_timepoint_id"] == identifier:
                remaining = [key for key in catalog["order"] if catalog["items"][key]["status"] == "active"]
                if not remaining:
                    blank = new_record(uuid.uuid4().hex, "Preoperative")
                    catalog["items"][blank["id"]] = blank
                    catalog["order"].append(blank["id"])
                    remaining = [blank["id"]]
                catalog["default_timepoint_id"] = remaining[0]
            return self._publish_timepoint_catalog(user_id, session_id, catalog, expected_revision)

    def restore_timepoint(self, user_id, session_id, identifier, *, expected_revision):
        with self._case_guard(user_id, session_id):
            catalog = self._timepoint_catalog(user_id, session_id)
            if revision(expected_revision) != catalog["catalog_revision"]:
                raise TimepointConflict("The timepoint catalog changed")
            item = self._timepoint_record(catalog, identifier, include_trashed=True)
            if item["status"] == "active":
                return public_catalog(catalog)
            item.update(status="active", deleted_at=None, updated_at=time.time(), revision=item["revision"] + 1,
                        lifecycle_revision=item.get("lifecycle_revision", 0) + 1)
            return self._publish_timepoint_catalog(user_id, session_id, catalog, expected_revision)

    def _read_timepoint_state(self, user_id, session_id, item, *, defer_results=False, resource_only=False, image_metadata=False):
        from web.workspace_store import _safe_workspace_child

        if item["legacy_default"]:
            state = self.load_snapshot(user_id, session_id)
            return _manifest_projection(state, resource_only=resource_only, image_metadata=image_metadata) if defer_results or image_metadata else state
        ref = item.get("state_ref")
        if ref is None:
            return self._empty_snapshot(session_id)
        root = self.workspace_root(user_id, session_id)
        path = _safe_workspace_child(root, ref["path"])
        try:
            stat = path.stat()
            identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
                        ref["path"], ref["sha256"])
            cache_key = (user_id, session_id, item["id"])
            with self._lock:
                cache = getattr(self, "_timepoint_manifest_cache", None)
                if cache is None:
                    cache = self._timepoint_manifest_cache = OrderedDict()
                cached = cache.get(cache_key)
                if cached is not None and cached[0] == identity:
                    cache.move_to_end(cache_key)
                    # Normal writers parse owned containers from verified JSON.
                    # Resource readers may reuse a private immutable graph;
                    # both bytes and graph count toward the bounded cache.
                    if not defer_results and not image_metadata:
                        return json.loads(cached[1])
                    state = cached[3] if len(cached) > 3 else json.loads(cached[1])
                    if len(cached) <= 3:
                        from web.timepoint_hydration import _weight
                        weight = len(cached[1]) + _weight(state)
                        if weight <= 128 * 1024**2:
                            cache[cache_key] = (identity, cached[1], weight, state)
                            while len(cache) > 8 or sum(row[2] for row in cache.values()) > 128 * 1024**2:
                                cache.popitem(last=False)
                    return _manifest_projection(state, resource_only=resource_only, image_metadata=image_metadata)
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != ref["sha256"]:
                raise TimepointIntegrityError("The timepoint state checksum does not match")
            state = json.loads(data)
            if state.get("session_id") != session_id or state.get("timepoint_id") != item["id"]:
                raise TimepointIntegrityError("The state manifest belongs to another workspace")
            if len(data) <= 128 * 1024**2:
                with self._lock:
                    cache[cache_key] = (identity, data, len(data))
                    cache.move_to_end(cache_key)
                    while len(cache) > 8 or sum(row[2] for row in cache.values()) > 128 * 1024**2:
                        cache.popitem(last=False)
            return _manifest_projection(state, resource_only=resource_only, image_metadata=image_metadata) if defer_results or image_metadata else state
        except (OSError, ValueError, TypeError) as exc:
            if isinstance(exc, TimepointIntegrityError):
                raise
            raise TimepointIntegrityError("The timepoint state is missing or unreadable") from exc

    def load_timepoint_snapshot(self, user_id, session_id, identifier, *, decode_arrays=False, include_shared=True, defer_results=False, resource_only=False):
        from web.workspace_store import _decode_artifacts

        with self._case_guard(user_id, session_id):
            catalog = self._timepoint_catalog(user_id, session_id)
            item = self._timepoint_record(catalog, identifier)
            # The checksum-verified JSON decoder already returns a fresh owned
            # object; do not copy its complete clinical/UI history a second time.
            state = (self._read_timepoint_state(user_id, session_id, item, defer_results=True, resource_only=resource_only)
                if defer_results and not decode_arrays else self._read_timepoint_state(user_id, session_id, item))
            agent = state.setdefault("agent", {})
            if include_shared:
                shared = self.load_snapshot(user_id, session_id, shared_only=True)
                state["chat"] = shared.get("chat", {})
                for key in _SHARED_AGENT_KEYS:
                    if key in (shared.get("agent") or {}):
                        agent[key] = copy.deepcopy(shared["agent"][key])
            else:
                # Resource HTTP views already use the authenticated Session
                # control Agent's conversation. Do not reread/copy shared chat
                # and attachment history for every mask, slice and mesh.
                state.pop('chat', None)
                for key in _SHARED_AGENT_KEYS:
                    agent.pop(key, None)
            if decode_arrays:
                agent["planning_results"] = _decode_artifacts(
                    agent.get("planning_results") or {}, self.workspace_root(user_id, session_id),
                )
            state["timepoint_id"] = identifier
            state["timepoint"] = public_catalog(catalog)["items"][identifier]
            state["timepoint_state_revision"] = (
                self.get_session(user_id, session_id).revision if item["legacy_default"] else item["state_revision"]
            )
            state["timepoint_clinical_revision"] = (
                self.get_session(user_id, session_id).revision if item["legacy_default"] else item.get("clinical_revision", 0)
            )
            state["session"] = self.get_session(user_id, session_id).public_dict()
            state["workspace"] = {"revision": state["timepoint_state_revision"],
                                  "inputs_root": str(self.workspace_root(user_id, session_id) / "inputs")}
            operation = self.latest_timepoint_operation(user_id, session_id, identifier)
            if operation is not None:
                state["operation"] = operation
            return state

    @staticmethod
    def _operation_process_start(pid):
        import os
        from pathlib import Path
        try:
            return Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, ValueError, IndexError):
            return "current" if pid == os.getpid() else "unavailable"

    def save_timepoint_operation(self, user_id, session_id, identifier, operation_id, operation):
        import os
        from web.workspace_store import _safe_json
        timepoint_id(operation_id)
        if not isinstance(operation, Mapping) or operation.get("state") not in {"running", "ready", "idle", "interrupted", "failed", "cancelled"}:
            raise TimepointError("Invalid persisted operation state")
        self.require_local_session(user_id, session_id)
        self._timepoint_record(self._timepoint_catalog(user_id, session_id), identifier)
        value = _safe_json(dict(operation))
        value.update(operation_id=operation_id, session_id=session_id, timepoint_id=identifier, updated_at=time.time())
        data = json.dumps(value, separators=(",", ":"), allow_nan=False)
        if len(data) > 65536:
            raise TimepointError("Operation checkpoint exceeds its metadata limit")
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT user_id,session_id,timepoint_id FROM timepoint_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if previous is not None and (previous["user_id"], previous["session_id"], previous["timepoint_id"]) != (user_id, session_id, identifier):
                raise TimepointConflict("The operation identity belongs to another workspace")
            if operation["state"] == "running":
                for row in connection.execute("SELECT * FROM timepoint_operations WHERE user_id=? AND session_id=? AND timepoint_id=? AND state='running'",
                        (user_id, session_id, identifier)):
                    if row["operation_id"] != operation_id and self._operation_process_start(row["process_id"]) == row["process_start"]:
                        raise TimepointConflict("Another operation is still running on this timepoint")
            connection.execute("INSERT INTO timepoint_operations VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(operation_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at,operation_json=excluded.operation_json",
                (operation_id, user_id, session_id, identifier, operation["state"], os.getpid(),
                 self._operation_process_start(os.getpid()), time.time(), data))
        return value

    def latest_timepoint_operation(self, user_id, session_id, identifier):
        with self._read_connection() as connection:
            row = connection.execute("SELECT * FROM timepoint_operations WHERE user_id=? AND session_id=? AND timepoint_id=? ORDER BY updated_at DESC LIMIT 1",
                (user_id, session_id, identifier)).fetchone()
        if row is None:
            return None
        value = json.loads(row["operation_json"])
        if row["state"] == "running" and self._operation_process_start(row["process_id"]) != row["process_start"]:
            value.update(state="interrupted", message="The previous worker ended; saved resources are retained for explicit retry",
                reason="previous_worker_ended", updated_at=time.time())
            with self._connection() as connection:
                connection.execute("UPDATE timepoint_operations SET state='interrupted',updated_at=?,operation_json=? WHERE operation_id=? AND state='running'",
                    (time.time(), json.dumps(value), row["operation_id"]))
        return value

    def capture_timepoint_context(self, user_id, session_id, identifier):
        from web.timepoint_context import capture_context
        with self._case_guard(user_id, session_id):
            catalog = self._timepoint_catalog(user_id, session_id)
            self._timepoint_record(catalog, identifier)
            return capture_context(user_id, session_id, catalog, identifier,
                                   self.get_session(user_id, session_id).revision)

    def _publish_timepoint_state(self, user_id, session_id, catalog, item, state, *,
                                 retain_previous=True, clinical_change=False, execution_context=None):
        from web.workspace_store import _atomic_bytes, _array_references, _safe_workspace_child

        root = self.workspace_root(user_id, session_id, create=True)
        path_rel = f"timepoints/{item['id']}/states/{uuid.uuid4().hex}.json"
        path = _safe_workspace_child(root, path_rel)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        state["session_id"], state["timepoint_id"] = session_id, item["id"]
        state["saved_at"] = time.time()
        state['ui'] = compact_restore_presentation(state.get('ui'))
        for image_id,ui in list((state.get('image_presentations') or {}).items()):
            profile = compact_restore_presentation(ui)
            profile.pop('bridge',None) # Timepoint capabilities are not image appearance.
            state['image_presentations'][image_id] = profile
        # Chat/accounting are shared and never replaced by timepoint state saves.
        state.pop("chat", None)
        for key in _SHARED_AGENT_KEYS:
            (state.get("agent") or {}).pop(key, None)
        data = json.dumps(state, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
        with self._quota_commit_lock(user_id):
            self._ensure_replacement_capacity(user_id, path, len(data))
            _atomic_bytes(path, data)
            self._invalidate_storage_usage(user_id)
        old_ref = item.get("state_ref")
        if old_ref is not None and retain_previous:
            item["state_history"].append(old_ref)
            # The complete immutable version ledger remains authoritative.
            # Bound the hot catalog, not the number of legitimate edits.
            item["state_history"] = item["state_history"][-MAX_HISTORY:]
        item["state_revision"] += 1
        if clinical_change:
            item["clinical_revision"] = item.get("clinical_revision", 0) + 1
        else:
            item["presentation_revision"] = item.get("presentation_revision", 0) + 1
        item["state_ref"] = {"path": path_rel, "sha256": hashlib.sha256(data).hexdigest(),
                             "arrays": sorted(_array_references(state)), "revision": item["state_revision"]}
        item["updated_at"] = time.time()
        for attempt in range(4):
            try:
                options = {"execution_context": execution_context} if execution_context is not None else {}
                self._publish_timepoint_catalog(user_id, session_id, catalog, catalog["catalog_revision"], **options)
                break
            except TimepointConflict:
                latest = self._timepoint_catalog(user_id, session_id)
                if execution_context is not None:
                    execution_context.assert_current(user_id, session_id, latest,
                        legacy_revision=self.get_session(user_id, session_id).revision)
                current = self._timepoint_record(latest, item["id"])
                if (attempt == 3 or current["state_revision"] != item["state_revision"] - 1
                        or current["revision"] != item["revision"]):
                    raise
                # Another timepoint's save or metadata change is mergeable.
                # An edit of this same target is never silently overwritten.
                latest["items"][item["id"]] = item
                catalog = latest
        return self.load_timepoint_snapshot(user_id, session_id, item["id"])

    def save_timepoint_patch(self, user_id, session_id, identifier, patch, *, expected_state_revision,
                             expected_clinical_revision=None, expected_lifecycle_revision=None,
                             presentation_source=None, presentation_sequence=None):
        from web.workspace_store import _safe_json, _merge_report_patch, _sanitize_report_for_snapshot

        if not isinstance(patch, Mapping) or set(patch) - {"ui", "report", "operation"}:
            raise TimepointError("Only timepoint UI, report and operation sections can be patched")
        if any(not isinstance(value, Mapping) for value in patch.values()):
            raise TimepointError("Workspace section patches must be objects")
        with self._case_guard(user_id, session_id):
            catalog = self._timepoint_catalog(user_id, session_id)
            item = self._timepoint_record(catalog, identifier)
            actual = self.get_session(user_id, session_id).revision if item["legacy_default"] else item["state_revision"]
            expected_state_revision = revision(expected_state_revision)
            presentation_fenced = any(value is not None for value in (expected_clinical_revision,
                expected_lifecycle_revision, presentation_source, presentation_sequence))
            if presentation_fenced:
                if expected_state_revision > actual:
                    raise TimepointConflict('A future presentation revision cannot be acknowledged')
                if (item['legacy_default'] or set(patch) - {'ui', 'report'}
                        or revision(expected_clinical_revision) != item.get('clinical_revision', 0)
                        or revision(expected_lifecycle_revision) != item.get('lifecycle_revision', 0)):
                    raise TimepointConflict('The presentation belongs to replaced clinical inputs or lifecycle')
                if (not isinstance(presentation_source, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', presentation_source)
                        or revision(presentation_sequence) > 2**53 - 1):
                    raise TimepointError('A bounded presentation source and sequence are required')
            elif expected_state_revision != actual:
                raise TimepointConflict("The timepoint state changed; reload it before editing")
            if item["legacy_default"]:
                return self.save_snapshot_patch(user_id, session_id, patch, expected_revision=actual)
            state = self._read_timepoint_state(user_id, session_id, item)
            if presentation_fenced:
                encoded = json.dumps(_safe_json(patch), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                import hashlib
                digest = hashlib.sha256(encoded).hexdigest()
                receipts = state.setdefault('presentation_receipts', {})
                previous = receipts.get(presentation_source)
                if previous and presentation_sequence <= previous['sequence']:
                    if presentation_sequence == previous['sequence'] and digest == previous['sha256']:
                        return self.load_timepoint_snapshot(user_id, session_id, identifier)
                    raise TimepointConflict('An older or changed presentation request cannot overwrite newer settings')
                receipts[presentation_source] = {'sequence': presentation_sequence, 'sha256': digest, 'saved_at': time.time()}
                state['presentation_receipts'] = dict(sorted(receipts.items(), key=lambda row: row[1]['saved_at'])[-16:])
            for section, values in patch.items():
                current = state.get(section) or {}
                incoming = _safe_json(values)
                if section == "report":
                    merged = _merge_report_patch(current, incoming)
                    state[section] = _sanitize_report_for_snapshot(merged, state, session_id)
                elif section == "ui":
                    state[section] = merge_presentation_patch(current, incoming)
                else:
                    state[section] = {**current, **incoming}
            return self._publish_timepoint_state(user_id, session_id, catalog, item, state, retain_previous=False)

    def save_timepoint_results(self, user_id, session_id, identifier, updates, *,
                               expected_state_revision=None, expected_clinical_revision=None, removals=(), execution_context=None):
        """Server-only numerical state commit; not a browser patch endpoint."""
        from web.workspace_store import _ArtifactEncoder, _safe_workspace_child

        if not isinstance(updates, Mapping):
            raise TimepointError("Planning results must be an object")
        if (expected_state_revision is None) == (expected_clinical_revision is None):
            raise TimepointError("Specify exactly one state or clinical revision")
        if execution_context is not None:
            from web.timepoint_context import TimepointContext
            if not isinstance(execution_context, TimepointContext) or execution_context.target.timepoint_id != identifier:
                raise TimepointError("A server-captured context for this exact target is required")
        with self._case_guard(user_id, session_id):
            catalog = self._timepoint_catalog(user_id, session_id)
            item = self._timepoint_record(catalog, identifier)
            if execution_context is not None:
                execution_context.assert_current(user_id, session_id, catalog,
                    legacy_revision=self.get_session(user_id, session_id).revision)
            if item["legacy_default"]:
                raise TimepointConflict("Use the existing agent checkpoint for the legacy default timepoint")
            if expected_clinical_revision is not None:
                if revision(expected_clinical_revision) != item.get("clinical_revision", 0):
                    raise TimepointConflict("The timepoint clinical inputs changed")
            elif revision(expected_state_revision) != item["state_revision"]:
                raise TimepointConflict("The timepoint state changed")
            state = self._read_timepoint_state(user_id, session_id, item)
            results = dict((state.get("agent") or {}).get("planning_results") or {})
            if state.get("image_collection"):
                from web.timepoint_images import bind_reference_results
                reference = state["image_collection"].get("planning_reference_image_id")
                if reference is None:
                    raise TimepointConflict("Clinical results require the selected planning reference image")
                updates = bind_reference_results(state, updates, reference_image_id=reference)
            root = self.workspace_root(user_id, session_id, create=True)
            nonce = uuid.uuid4().hex
            created = []
            def track(source_key, name, relative):
                created.append(relative)
            with self._quota_commit_lock(user_id):
                encoder = _ArtifactEncoder(
                    root, ensure_capacity=lambda path, size: self._ensure_replacement_capacity(user_id, path, size),
                    record_array=track,
                )
                for key, value in updates.items():
                    key = str(key)
                    results[key] = encoder.encode(value, f"tp_{identifier}_{nonce}_{key}", key)
                    self._invalidate_storage_usage(user_id)
                for key in removals:
                    results.pop(str(key), None)
                # A restore/checkpoint may repeat an identical metadata patch
                # or remove an already absent legacy key. This is not a new
                # clinical state. Advancing its version would invalidate a
                # correctly captured image, task and presentation read-set.
                # Ownership/context/CAS checks above remain mandatory, even
                # for a no-op; a stale writer never gets an acknowledgement.
                if results == (state.get("agent") or {}).get("planning_results", {}):
                    return self.load_timepoint_snapshot(user_id, session_id, identifier)
                state.setdefault("agent", {})["planning_results"] = results
                # Verify every sidecar, including preexisting encoded references.
                from web.workspace_store import _array_references
                for relative in _array_references(results):
                    if not _safe_workspace_child(root, relative).is_file():
                        raise TimepointIntegrityError("A planning array reference is missing")
                return self._publish_timepoint_state(
                    user_id, session_id, catalog, item, state, clinical_change=True, execution_context=execution_context,
                )

    def timepoint_array_references(self, user_id, session_id):
        """Reachability includes inactive, historical and recoverably deleted states."""
        catalog = self._timepoint_catalog(user_id, session_id)
        references = set()
        for item in catalog["items"].values():
            for state in [item.get("state_ref"), *item["state_history"]]:
                if state is not None:
                    references.update(state["arrays"])
        with self._read_connection() as connection:
            for row in connection.execute(
                "SELECT state_ref_json FROM timepoint_state_versions WHERE session_id = ?", (session_id,)
            ):
                references.update(json.loads(row["state_ref_json"]).get("arrays") or [])
        return references
