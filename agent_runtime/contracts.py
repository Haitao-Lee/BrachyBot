"""Deterministic runtime contracts for BrachyBot agent turns.

This module deliberately borrows the *discipline* of production coding-agent
runtimes without importing their execution model.  A clinical planning case is
not a disposable coding workspace: context, tool calls, and retries must stay
auditable, case-scoped, and safe across provider changes and server restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import threading
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from tool_factory import ToolResult


class RunStatus(str, Enum):
    """Stable lifecycle states shown in the execution trace and checkpoints."""

    QUEUED = "queued"
    REASONING = "reasoning"
    AWAITING_INPUT = "awaiting_input"
    EXECUTING_TOOL = "executing_tool"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_RUN_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


def _json_safe(value: Any) -> Any:
    """Create a stable, non-clinical-payload representation for audit keys."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    # Images, arrays, callbacks, and model instances must never be serialized
    # into the run journal. They are represented by type only.
    return {"$runtime_type": type(value).__name__}


def _estimate_tokens(text: Any) -> int:
    """Conservative provider-neutral estimate; CJK is costed separately."""
    if isinstance(text, list):
        # Multimodal provider payloads are kept intact. Count only their
        # serialised descriptors here; image bytes must never enter prompts.
        return sum(_estimate_tokens(item.get("text", "") if isinstance(item, Mapping) else item) for item in text)
    text = str(text or "")
    cjk = sum(1 for char in text if "\u3400" <= char <= "\u9fff")
    return max(1, cjk + max(0, len(text) - cjk) // 4) if text else 0


@dataclass
class RuntimeEvent:
    """An immutable, compact audit entry for one agent state transition."""

    at: float
    kind: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"at": self.at, "kind": self.kind, "detail": _json_safe(self.detail)}


@dataclass
class AgentRun:
    """A durable logical turn, independent of provider-specific request IDs."""

    id: str
    status: RunStatus = RunStatus.QUEUED
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tool_calls: int = 0
    context_manifest: Dict[str, Any] = field(default_factory=dict)
    events: List[RuntimeEvent] = field(default_factory=list)

    def transition(self, status: RunStatus, kind: str, **detail: Any) -> None:
        if self.status in _TERMINAL_RUN_STATUSES and status != self.status:
            # A late provider or browser callback must not resurrect a completed
            # or cancelled clinical turn.
            return
        self.status = status
        self.updated_at = time.time()
        self.events.append(RuntimeEvent(self.updated_at, kind, _json_safe(detail)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "tool_calls": self.tool_calls,
            "context_manifest": _json_safe(self.context_manifest),
            "events": [event.to_dict() for event in self.events[-100:]],
        }


class RunLedger:
    """Case-local run ledger with bounded, checkpoint-friendly history."""

    def __init__(self, max_history: int = 40):
        self._lock = threading.RLock()
        self.max_history = max(1, int(max_history))
        self.active: Optional[AgentRun] = None
        self.history: List[Dict[str, Any]] = []

    def begin(self, message: str) -> AgentRun:
        with self._lock:
            if self.active and self.active.status not in _TERMINAL_RUN_STATUSES:
                self.active.transition(RunStatus.CANCELLED, "run.superseded")
                self._archive_active()
            run = AgentRun(id=f"run_{uuid.uuid4().hex}")
            run.transition(RunStatus.REASONING, "run.started", message_chars=len(str(message or "")))
            self.active = run
            return run

    def _archive_active(self) -> None:
        if self.active is None:
            return
        self.history.append(self.active.to_dict())
        self.history = self.history[-self.max_history:]

    def transition(self, status: RunStatus, kind: str, **detail: Any) -> None:
        with self._lock:
            if self.active is not None:
                self.active.transition(status, kind, **detail)
                if status in _TERMINAL_RUN_STATUSES:
                    self._archive_active()
                    self.active = None

    def active_id(self) -> Optional[str]:
        with self._lock:
            return self.active.id if self.active else None

    def active_status(self) -> Optional[RunStatus]:
        """Return the live state without exposing the mutable run object."""
        with self._lock:
            return self.active.status if self.active else None

    def record_tool(self, tool_name: str, call_id: str, success: bool, **detail: Any) -> None:
        with self._lock:
            if self.active is None:
                return
            self.active.tool_calls += 1
            self.active.events.append(RuntimeEvent(
                time.time(), "tool.completed" if success else "tool.failed",
                _json_safe({"tool": tool_name, "call_id": call_id, **detail}),
            ))
            self.active.updated_at = time.time()

    def set_context_manifest(self, manifest: Mapping[str, Any]) -> None:
        with self._lock:
            if self.active is not None:
                self.active.context_manifest = _json_safe(dict(manifest))
                self.active.updated_at = time.time()

    def export_state(self) -> Dict[str, Any]:
        with self._lock:
            state = {"history": list(self.history[-self.max_history:])}
            if self.active is not None:
                state["active"] = self.active.to_dict()
            return state

    def restore_state(self, state: Mapping[str, Any]) -> None:
        # Running processes are never revived from persistence. The workspace
        # layer marks them interrupted, preserving the last reliable artifact.
        with self._lock:
            self.history = list((state or {}).get("history") or [])[-self.max_history:]
            active = (state or {}).get("active")
            if isinstance(active, Mapping):
                restored = dict(active)
                # Asking for a missing tumour site is not an interrupted GPU
                # job. Preserve that explicit user-facing clarification state;
                # only work that was actively reasoning or executing becomes
                # interrupted after a process restart.
                if restored.get("status") != RunStatus.AWAITING_INPUT.value:
                    restored["status"] = "interrupted"
                self.history.append(restored)
                self.history = self.history[-self.max_history:]
            self.active = None


class ContextPackBuilder:
    """Build a bounded, provenance-labelled LLM message pack.

    Provider-native compaction blobs are intentionally not handled here. Those
    blobs are opaque and provider-specific, while BrachyBot supports multiple
    OpenAI/Anthropic-compatible endpoints. This portable structured pack is
    safe to restore and send to any configured provider.
    """

    def __init__(self, max_tokens: int = 12000, reserve_output_tokens: int = 2000):
        self.max_tokens = max(2000, int(max_tokens))
        self.reserve_output_tokens = max(256, int(reserve_output_tokens))

    @property
    def input_budget(self) -> int:
        return max(1000, self.max_tokens - self.reserve_output_tokens)

    @staticmethod
    def _message_tokens(message: Mapping[str, Any]) -> int:
        content = message.get("content")
        if isinstance(content, list):
            return sum(_estimate_tokens(str(item)) for item in content)
        return _estimate_tokens(str(content or ""))

    @staticmethod
    def _compact_tool_content(content: str) -> str:
        content = str(content or "")
        if len(content) <= 1400:
            return content
        return content[:1400].rstrip() + "\n[Tool evidence truncated; see durable execution trace.]"

    def build(self, messages: Iterable[Mapping[str, Any]], current_user_content: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        source = [dict(item) for item in messages if isinstance(item, Mapping)]
        system = [item for item in source if item.get("role") == "system"]
        non_system = [item for item in source if item.get("role") != "system"]
        selected: List[Dict[str, Any]] = list(system)
        used = sum(self._message_tokens(item) for item in selected)
        reserved_current = _estimate_tokens(current_user_content)
        available = max(0, self.input_budget - used - reserved_current)

        # Retain the most recent relevant turns in chronological order. Tool
        # outputs are compacted before selection because raw arrays/logs make
        # contextual relevance worse, not better.
        tail: List[Dict[str, Any]] = []
        skipped = 0
        for item in reversed(non_system):
            candidate = dict(item)
            if candidate.get("role") == "tool":
                # A historical tool result may no longer have its matching
                # provider function-call envelope after compaction. Convert it
                # into ordinary evidence rather than emitting an invalid OpenAI
                # or Anthropic tool-message sequence to the next provider call.
                candidate = {
                    "role": "user",
                    "content": "[Historical tool evidence]\n" + self._compact_tool_content(candidate.get("content", "")),
                }
            cost = self._message_tokens(candidate)
            if cost <= available:
                tail.append(candidate)
                available -= cost
            else:
                skipped += 1
        selected.extend(reversed(tail))

        # Current intent is invariant even when a caller accidentally included
        # an older duplicate user turn in the history.
        if (
            not selected
            or selected[-1].get("role") != "user"
            or selected[-1].get("content") != current_user_content
        ):
            selected.append({"role": "user", "content": current_user_content})
        manifest = {
            "input_budget_tokens": self.input_budget,
            "estimated_input_tokens": sum(self._message_tokens(item) for item in selected),
            "system_messages": len(system),
            "retained_non_system_messages": len(tail),
            "dropped_non_system_messages": skipped,
            "strategy": "portable_structured_budget_v1",
        }
        return selected, manifest


@dataclass(frozen=True)
class ToolCall:
    """Provider-neutral call normalized before it reaches a clinical tool."""

    id: str
    name: str
    params: Dict[str, Any]

    @classmethod
    def from_payload(cls, tool_name: str, params: Any, call_id: Optional[str] = None) -> "ToolCall":
        if not isinstance(params, Mapping):
            raise ValueError("Tool parameters must be a JSON object")
        return cls(str(call_id or f"tool_{uuid.uuid4().hex}"), str(tool_name or ""), dict(params))

    def idempotency_key(self, workspace_revision: Optional[int] = None) -> str:
        payload = {
            "name": self.name,
            "params": _json_safe(self.params),
            "workspace_revision": workspace_revision,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ToolCallGateway:
    """Validate and journal registry calls without changing tool behavior.

    Schemas in the established tool factory are heterogeneous and several
    tools receive server-injected image/callback values. The gateway therefore
    validates declared fields and required arguments, while intentionally
    preserving unknown server-injected values for legacy compatibility. New
    high-risk tools can opt into strict unknown-field rejection later.
    """

    # Cache only immutable, case-independent retrieval. Viewer commands,
    # UI inspection, metrics, and model availability depend on live browser,
    # case, or installation state. They must never reuse a result merely
    # because an optional workspace revision was unavailable in a legacy UI
    # snapshot.
    _CACHEABLE_TOOLS = {"clinical_kb"}

    def __init__(self, ledger: RunLedger):
        self.ledger = ledger
        self._lock = threading.RLock()
        self._cache: Dict[str, ToolResult] = {}

    @staticmethod
    def _declared_properties(schema: Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(schema.get("properties"), Mapping):
            return schema["properties"]
        return {key: value for key, value in schema.items() if isinstance(value, Mapping)}

    @staticmethod
    def _matches_type(value: Any, expected: str) -> bool:
        expected = str(expected or "")
        if not expected:
            return True
        if expected == "string":
            return isinstance(value, str)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "array":
            return isinstance(value, (list, tuple))
        if expected == "object":
            return isinstance(value, Mapping)
        return True

    def validate(self, registry: Any, call: ToolCall) -> Optional[ToolResult]:
        if not call.name or call.name not in registry.tool_names:
            return ToolResult(False, error=f"Unknown tool: {call.name}", message=f"Unknown tool: {call.name}")
        tool = registry.get(call.name)
        schema = tool.input_schema or {}
        properties = self._declared_properties(schema)
        required = schema.get("required", []) if isinstance(schema, Mapping) else []
        missing = [field for field in required if field not in call.params or call.params.get(field) is None]
        if missing:
            self.ledger.transition(
                RunStatus.AWAITING_INPUT,
                "tool.input_required",
                tool=call.name,
                missing=missing,
            )
            return ToolResult(False, error=f"Missing required parameters: {', '.join(missing)}", message=f"Missing required parameters: {', '.join(missing)}")
        for field, definition in properties.items():
            if field not in call.params or not isinstance(definition, Mapping):
                continue
            value = call.params[field]
            if not self._matches_type(value, definition.get("type", "")):
                return ToolResult(False, error=f"Invalid parameter type for {field}", message=f"Invalid parameter type for {field}")
            allowed = definition.get("enum")
            if isinstance(allowed, list) and value not in allowed:
                return ToolResult(False, error=f"Invalid value for {field}", message=f"Invalid value for {field}")
        return None

    def execute(
        self,
        registry: Any,
        tool_name: str,
        params: Mapping[str, Any],
        executor: Callable[[], ToolResult],
        *,
        call_id: Optional[str] = None,
        workspace_revision: Optional[int] = None,
    ) -> ToolResult:
        call = ToolCall.from_payload(tool_name, params, call_id)
        invalid = self.validate(registry, call)
        if invalid is not None:
            self.ledger.record_tool(call.name, call.id, False, error=invalid.error, validation=True)
            return invalid
        cache_key = call.idempotency_key(workspace_revision)
        with self._lock:
            if call.name in self._CACHEABLE_TOOLS and cache_key in self._cache:
                cached = self._cache[cache_key]
                metadata = dict(cached.metadata or {})
                metadata["reused_idempotent_result"] = True
                result = ToolResult(cached.success, cached.data, cached.message, cached.display, metadata, cached.error, cached.execution_time)
                self.ledger.record_tool(call.name, call.id, result.success, reused=True)
                return result
        self.ledger.transition(RunStatus.EXECUTING_TOOL, "tool.started", tool=call.name, call_id=call.id)
        started = time.time()
        try:
            result = executor()
            if not isinstance(result, ToolResult):
                result = ToolResult(False, error="Tool returned an invalid result", message="Tool returned an invalid result")
        except Exception as exc:  # The gateway must never let a malformed tool escape the trace.
            result = ToolResult(False, error=str(exc), message=f"Tool execution failed: {exc}")
        result.execution_time = result.execution_time or (time.time() - started)
        if result.success and call.name in self._CACHEABLE_TOOLS:
            with self._lock:
                self._cache[cache_key] = result
        self.ledger.record_tool(call.name, call.id, result.success, duration_s=round(result.execution_time, 3))
        self.ledger.transition(RunStatus.REASONING, "tool.returned", tool=call.name, call_id=call.id, success=result.success)
        return result
