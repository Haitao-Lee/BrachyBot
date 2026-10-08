"""Bounded, content-free durable token accounting. Never stores model prompts.

Provider request occupancy, per-turn consumption and session consumption are
different quantities. Persistence must not convert one into another, infer
missing measurements, or change a measured request's model/window on restart.
"""
from __future__ import annotations

import math
import re
import time
import uuid
from typing import Any, Mapping

ACCOUNTING_VERSION = 3
MAX_COUNT = 2**53 - 1  # Exact in both Python and browser JavaScript.
COUNTERS = (
    "call_index", "turn_prompt_sum", "turn_completion_sum", "turn_total_sum",
    "missing_usage_calls", "peak_tokens", "session_input_tokens",
    "session_output_tokens", "session_total_tokens", "session_calls",
    "session_missing_usage_calls", "overhead_tokens", "last_estimate",
    "history_compactions_at_measurement",
)
SNAPSHOT_COUNTS = (
    "window", "used_tokens", "input_tokens", "output_tokens", "target_tokens",
    "trigger_tokens", "reserve_output_tokens", "message_count", "call_index",
)
META_COUNTS = ("folded_messages", "before_tokens", "after_tokens")
COMPONENTS = (
    "system", "runtime_context", "facts", "history", "tool_results",
    "conversation", "images", "tools", "other", "total",
)


def new_accounting_epoch() -> dict:
    """Explicit conversation reset tombstone, newer than previous snapshots."""
    timestamp = time.time() * 1000
    return sanitize_accounting({
        'version': ACCOUNTING_VERSION, 'epoch': uuid.uuid4().hex, 'revision': 1,
        'updated_at_ms': timestamp, 'coverage_started_at_ms': timestamp,
        'conversation_reset_at_ms': timestamp,
        'preexisting_history': False,
    })


def newer_accounting(candidate: Any, previous: Any) -> bool:
    """Fence a small ledger independently from asynchronous large checkpoints."""
    candidate = sanitize_accounting(candidate)
    previous = sanitize_accounting(previous)
    if not candidate:
        return False
    if not previous:
        return True
    if candidate['epoch'] == previous['epoch']:
        return candidate['revision'] > previous['revision']
    return candidate['updated_at_ms'] > previous['updated_at_ms']


def count(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
        if math.isfinite(number) and number.is_integer() and 0 <= number <= MAX_COUNT:
            return int(number)
    except (TypeError, ValueError, OverflowError):
        pass
    return default


def _timestamp(value: Any) -> float:
    try:
        number = float(value)
        return number if not isinstance(value, bool) and math.isfinite(number) and 0 <= number <= MAX_COUNT else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _identifier(value: Any) -> str:
    # Model/provider IDs only; never accept arbitrary tool output or secrets.
    text = str(value or "")[:160]
    return text if re.fullmatch(r"[\w./:+ -]*", text) and not text.startswith("sk-") else ""


def sanitize_accounting(value: Any) -> dict:
    """Whitelist numeric metadata and bounded identities at the disk boundary."""
    if not isinstance(value, Mapping) or value.get("version") != ACCOUNTING_VERSION:
        return {}
    epoch = str(value.get("epoch") or "")
    if not re.fullmatch(r"[a-f0-9]{32}", epoch):
        return {}
    result = {"version": ACCOUNTING_VERSION, "epoch": epoch,
              "revision": count(value.get("revision")),
              "observed_at_ms": _timestamp(value.get("observed_at_ms")),
              "updated_at_ms": _timestamp(value.get("updated_at_ms")),
              "coverage_started_at_ms": _timestamp(value.get("coverage_started_at_ms")),
              "conversation_reset_at_ms": _timestamp(value.get("conversation_reset_at_ms")),
              "preexisting_history": value.get("preexisting_history") is True,
              "turn_request_id": _identifier(value.get("turn_request_id"))}
    invalid_counters = False
    for key in COUNTERS:
        result[key] = count(value.get(key))
        if key in value and count(value[key], -1) < 0:
            invalid_counters = True
    if invalid_counters:
        # A corrupted counter cannot become a complete measured zero.
        result['session_missing_usage_calls'] = max(1, result['session_missing_usage_calls'])
    snapshot = value.get("snapshot")
    if (isinstance(snapshot, Mapping) and count(snapshot.get("window")) >= 512
            and count(snapshot.get('used_tokens'), -1) >= 0):
        cleaned = {key: count(snapshot[key]) for key in SNAPSHOT_COUNTS if key in snapshot and snapshot[key] is not None}
        for key in ("measured", "estimated", "input_reported", "output_reported", "context_complete"):
            if isinstance(snapshot.get(key), bool):
                cleaned[key] = snapshot[key]
        for key in ("model", "provider"):
            cleaned[key] = _identifier(snapshot.get(key))
        for key, allowed in {
            "source": {"provider_usage", "request_estimate", "retained_history_estimate"},
            "change_reason": {"new_request", "request_selection", "history_compaction", "model_route_changed", "manual_compression", "pending_request"},
            "window_source": {"runtime_config", "provider_config", "model_registry", "default", "provider_metadata"},
        }.items():
            if snapshot.get(key) in allowed:
                cleaned[key] = snapshot[key]
        cleaned["ratio"] = cleaned.get("used_tokens", 0) / cleaned["window"]
        result["snapshot"] = cleaned
    for key in ("components", "compression"):
        data = value.get(key)
        if isinstance(data, Mapping):
            fields = COMPONENTS if key == "components" else META_COUNTS
            result[key] = {name: count(data[name]) for name in fields if name in data}
            if key == "compression":
                result[key].update({name: data[name] for name in ("compressed", "manual") if isinstance(data.get(name), bool)})
    calibration = value.get("calibration")
    signature = value.get("manager_signature")
    if isinstance(signature, (tuple, list)) and len(signature) == 4:
        try:
            factor, ratio = float(calibration), float(signature[2])
            if (not isinstance(calibration, bool) and not isinstance(signature[2], bool)
                    and math.isfinite(factor) and .25 <= factor <= 4 and math.isfinite(ratio) and 0 < ratio <= 1):
                result.update(calibration=factor, manager_signature=[
                    _identifier(signature[0]), count(signature[1]), ratio, count(signature[3])])
        except (TypeError, ValueError, OverflowError):
            pass
    return result
