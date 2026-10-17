"""Human-authored target evidence, independent of clinical action permission.

The primary model resolves intent in its existing call. This module only
checks whether the target identity is evidenced by the actual human request,
or by a server-owned confirmation of an exact pending call. A model argument,
assistant reply, image basename or navigation pointer cannot supply evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import time
import uuid
from contextlib import nullcontext

from web.timepoints import TimepointConflict, TimepointError
from agent_runtime.request_parse import parse_request


@dataclass(frozen=True)
class CatalogTargetContext:
    """Lifecycle fence for metadata operations, including a trashed target."""
    owner_id: str
    session_id: str
    target: object
    status: str
    dependencies: tuple = ()

    def assert_current(self, owner_id, session_id, catalog, *, legacy_revision):
        row = catalog["items"].get(self.target.timepoint_id)
        if ((owner_id, session_id) != (self.owner_id, self.session_id) or not row
                or row["status"] != self.status
                or row.get("lifecycle_revision", 0) != self.target.lifecycle_revision
                or (legacy_revision if row.get("legacy_default") else row.get("clinical_revision", 0))
                   != self.target.clinical_revision):
            raise TimepointConflict("The catalog target changed before confirmation")


def capture_catalog_target(store, scope, record):
    from web.timepoint_context import TimepointRead
    clinical = (store.get_session(scope.owner_id, scope.session_id).revision
                if record.get("legacy_default") else record.get("clinical_revision", 0))
    return CatalogTargetContext(scope.owner_id, scope.session_id,
        TimepointRead(record["id"], clinical, record["stage"], record.get("preoperative_timepoint_id"),
            record.get("previous_intraoperative_timepoint_id"), bool(record.get("legacy_default")),
            record.get("lifecycle_revision", 0)), record["status"])


def _digest(message):
    return hashlib.sha256(str(message or "").encode("utf-8")).hexdigest()


def _literal_present(message, literal):
    # Exact catalog identities, not an inventory of natural-language commands.
    # Latin letters/numbers need boundaries; Chinese titles can occur next to
    # ordinary Chinese prose without inserted spaces.
    left = r"(?<![A-Za-z0-9_])" if literal[:1].isascii() and literal[:1].isalnum() else ""
    right = r"(?![A-Za-z0-9_])" if literal[-1:].isascii() and literal[-1:].isalnum() else ""
    return bool(literal and re.search(left + re.escape(literal) + right, message, re.IGNORECASE))


@dataclass(frozen=True)
class HumanTimepointTargetEvidence:
    owner_id: str
    session_id: str
    request_sha256: str
    # (identity, clinical revision, lifecycle revision, literal human reference)
    targets: tuple

    def permits(self, scope, identifier, context, message):
        if (self.owner_id, self.session_id, self.request_sha256) != (
                scope.owner_id, scope.session_id, _digest(message)):
            return False
        # The execution captures its own clinical inputs. A completed earlier
        # sibling mutation does not revoke the human's selected identity.
        return any(identifier == row[0] and context.target.lifecycle_revision == row[2]
                   for row in self.targets)


def capture_human_target_evidence(store, scope, message):
    """Capture catalog-title/ID evidence before a model or worker can retarget.

    Title evidence must be unique, including deleted catalog entries; a title
    collision never chooses whichever row happens to be first. Longest title
    wins over a contained shorter title. Mentioning a target grants no action.
    """
    catalog = store.list_timepoints(scope.owner_id, scope.session_id, include_trashed=True)
    raw = str(message or "")
    rows = catalog["timepoints"]
    title_counts = {}
    for row in rows:
        title = str(row.get("title") or "")
        title_counts[title.casefold()] = title_counts.get(title.casefold(), 0) + 1
    matched_titles = [str(row["title"]) for row in rows
                      if title_counts[str(row.get("title") or "").casefold()] == 1
                      and _literal_present(raw, str(row.get("title") or ""))]
    targets = []
    for row in rows:
        literal = row["id"] if _literal_present(raw, row["id"]) else None
        title = str(row.get("title") or "")
        if literal is None and title in matched_titles and not any(
                title.casefold() != other.casefold() and title.casefold() in other.casefold()
                for other in matched_titles):
            literal = title
        if literal is not None:
            clinical = row.get("clinical_revision", 0)
            if row.get("legacy_default"):
                clinical = store.get_session(scope.owner_id, scope.session_id).revision
            targets.append((row["id"], clinical, row.get("lifecycle_revision", 0), literal))
    return HumanTimepointTargetEvidence(scope.owner_id, scope.session_id, _digest(raw), tuple(targets))


def readset_dict(context):
    """Public input fence without account identity or image/secret values."""
    return [{"timepoint_id": row.timepoint_id, "clinical_revision": row.clinical_revision,
             "lifecycle_revision": row.lifecycle_revision, "stage": row.stage}
            for row in (context.target, *context.dependencies)]


def _explicit_unique_stage_selection(store, scope, identifier, message, context):
    """Allow a plain stage request to select one uniquely identified target.

    ``timepoint_controller`` still has to use the catalog identity selected by
    the model.  This helper only supplies human-authored target evidence when
    the request explicitly contains a selection verb and a stage phrase, and
    the live catalog contains exactly one active timepoint at that stage.  It
    deliberately does not guess when two intraoperative points exist.
    """
    raw_message = str(message or "")
    if not raw_message or not isinstance(context, CatalogTargetContext):
        return False
    if not re.search(r"(?:切换|切到|切至|进入|选择|打开|switch|select|go\s+to|move\s+to)",
                    raw_message, re.IGNORECASE):
        return False
    stage = None
    if re.search(r"术中(?:的|节点|时间点)?|intra[-\s]?operative", raw_message, re.IGNORECASE):
        stage = "intraoperative"
    elif re.search(r"术前(?:的|节点|时间点)?|pre[-\s]?operative", raw_message, re.IGNORECASE):
        stage = "preoperative"
    if stage is None or context.target.stage != stage:
        return False
    # Match the same clause-level exclusions used by the catalog authorization
    # path. A quoted log, question, negation, or completed-action description
    # must never become a new target authorization.
    try:
        clauses = parse_request(raw_message).subtasks
    except Exception:
        return False
    if not any(
        re.search(r"(?:切换|切到|切至|进入|选择|打开|switch|select|go\s+to|move\s+to)", clause.raw, re.IGNORECASE)
        and re.search(r"术中(?:的|节点|时间点)?|intra[-\s]?operative|术前(?:的|节点|时间点)?|pre[-\s]?operative",
                      clause.raw, re.IGNORECASE)
        and not any((clause.negated, clause.conditional, clause.interrogative,
                     clause.quoted, clause.attributed, clause.completed_action,
                     clause.excluded))
        for clause in clauses
    ):
        return False
    try:
        catalog = store.list_timepoints(scope.owner_id, scope.session_id, include_trashed=False)
        rows = [row for row in catalog.get("timepoints", [])
                if row.get("status") == "active" and row.get("stage") == stage]
    except Exception:
        return False
    return len(rows) == 1 and str(rows[0].get("id")) == str(identifier)


def _call_json(name, params):
    encoded = json.dumps({"tool": name, "params": params}, ensure_ascii=False,
                         allow_nan=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 16000:
        raise TimepointError("The target confirmation operation is too large")
    return encoded


@dataclass(frozen=True)
class ConfirmedTimepointCall:
    owner_id: str
    session_id: str
    request_id: str
    payload: str
    context: object
    receipt_id: str

    def permits(self, scope, name, params, store, request_id):
        if (self.owner_id, self.session_id, self.request_id) != (
                scope.owner_id, scope.session_id, str(request_id or "")):
            return False
        if self.payload != _call_json(name, params):
            return False
        self.context.assert_current(self.owner_id, self.session_id,
            store._timepoint_catalog(self.owner_id, self.session_id),
            legacy_revision=store.get_session(self.owner_id, self.session_id).revision)
        return True


@dataclass(frozen=True)
class PendingTimepointCall:
    receipt_id: str
    owner_id: str
    session_id: str
    payload: str
    context: object
    expires_at: float

    @classmethod
    def create(cls, scope, name, params, context):
        return cls(uuid.uuid4().hex, scope.owner_id, scope.session_id,
                   _call_json(name, params), context, time.monotonic() + 240)

    def public_dict(self):
        from agent_runtime.confirmation import proposal_preview
        return {"receipt_id": self.receipt_id, "session_id": self.session_id,
                "timepoint_id": self.context.target.timepoint_id,
                "operation": json.loads(proposal_preview([json.loads(self.payload)]))[0],
                "readset": readset_dict(self.context), "expires_in_seconds":
                max(0, int(self.expires_at - time.monotonic())), "confirmed": False}


def confirm_pending_timepoint_call(control_agent, receipt_id, *, owner_id, session_id, request_id):
    """For an authenticated HUMAN confirmation route, never a model tool.

    The route must validate owner, editor lease and CSRF before calling this.
    Confirmation is consumed once and binds the new request's exact operation
    and clinical read-set. It is neither a whole-tool nor a planning grant.
    """
    with getattr(control_agent, "_turn_state_lock", None) or nullcontext():
        now = time.monotonic()
        confirmed = {key: item for key, item in getattr(control_agent, "_confirmed_timepoint_calls", {}).items()
                     if item[0] > now}
        cached = confirmed.get(str(receipt_id))
        if cached is not None:
            value = cached[1]
            if (value.owner_id, value.session_id, value.request_id) != (owner_id, session_id, str(request_id)):
                raise TimepointConflict("This confirmation was consumed by another request")
            value.context.assert_current(owner_id, session_id, control_agent._workspace_store._timepoint_catalog(owner_id, session_id),
                legacy_revision=control_agent._workspace_store.get_session(owner_id, session_id).revision)
            return value  # Same request ID can reconnect, not start a second task.
        pending = getattr(control_agent, "_pending_timepoint_calls", {})
        value = pending.get(str(receipt_id))
        if (not isinstance(value, PendingTimepointCall) or now >= value.expires_at
                or (value.owner_id, value.session_id) != (owner_id, session_id)
                or not str(request_id or "")):
            raise TimepointConflict("The target confirmation is absent, expired or belongs to another request")
        store = getattr(control_agent, "_workspace_store", None)
        value.context.assert_current(owner_id, session_id, store._timepoint_catalog(owner_id, session_id),
            legacy_revision=store.get_session(owner_id, session_id).revision)
        result = ConfirmedTimepointCall(owner_id, session_id, str(request_id), value.payload,
                                       value.context, value.receipt_id)
        pending.pop(str(receipt_id))
        confirmed[str(receipt_id)] = (value.expires_at, result)
        control_agent._confirmed_timepoint_calls = dict(list(confirmed.items())[-8:])
        return result


def require_human_target(agent, scope, identifier, name, params, *, context=None):
    """Target evidence and existing clinical authorization are separate gates."""
    store = getattr(agent, "_workspace_store", None)
    context = context or store.capture_timepoint_context(scope.owner_id, scope.session_id, identifier)
    if identifier == scope.timepoint_id:
        return context
    turn = getattr(agent, "_active_turn_context", {}) or {}
    evidence = turn.get("human_timepoint_evidence")
    local = getattr(agent, "_turn_local", None)
    message = getattr(local, "human_message", "")
    if isinstance(evidence, HumanTimepointTargetEvidence) and evidence.permits(scope, identifier, context, message):
        return context
    if (name == "timepoint_controller" and params.get("action") == "select"
            and _explicit_unique_stage_selection(store, scope, identifier, message, context)):
        return context
    receipt = turn.get("human_timepoint_confirmation")
    if isinstance(receipt, ConfirmedTimepointCall) and receipt.permits(
            scope, name, params, store, turn.get("request_id")):
        return context
    from web.timepoint_chat import CrossTimepointConfirmationRequired
    runtime = getattr(agent, "_workspace_scoped_chat_runtime", None)
    root = runtime.control_agent if runtime is not None else agent
    pending = PendingTimepointCall.create(scope, name, params, context)
    values = getattr(root, "_pending_timepoint_calls", {})
    values = {key: value for key, value in values.items() if value.expires_at > time.monotonic()}
    values[pending.receipt_id] = pending
    root._pending_timepoint_calls = dict(list(values.items())[-8:])
    error = CrossTimepointConfirmationRequired("A different mutation target needs human-authored identity or confirmation")
    error.confirmation = pending.public_dict()
    raise error
