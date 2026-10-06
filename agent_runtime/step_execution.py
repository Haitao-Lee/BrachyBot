"""Turn-local execution receipts shared by streaming and plain chat.

Ordering is not completion. Dependencies require a successful receipt, and a
browser dispatch remains pending. Cache reuse is valid only until another
operation may have changed workspace state.
"""
import json
from collections import Counter

from agent_runtime.action_plan import ActionPlan
from agent_runtime.execution_authorization import tool_call_is_mutating


def decode_provider_call(payload, index=0):
    """One provider boundary: preserve step identity and reject invalid JSON.

    In particular, Anthropic's `input` and OpenAI's `arguments` have the same
    contract. Invalid arguments must never become a default mutation.
    """
    if not isinstance(payload, dict):
        return {"tool": "invalid_tool_call", "params": {}, "_argument_error": "Tool call must be an object"}
    function = payload.get("function", payload)
    if not isinstance(function, dict):
        function = {}
    call = {key: payload[key] for key in ("key", "depends_on", "dependsOn") if key in payload}
    call.update(id=payload.get("id") or f"tool_{index}", tool=function.get("name", payload.get("tool", "")))
    raw = function.get("arguments", function.get("input", function.get("params", {})))
    try:
        params = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(params, dict):
            raise ValueError("Tool arguments must be a JSON object")
        call["params"] = params
    except (ValueError, TypeError):
        call.update(params={}, _argument_error="Invalid tool arguments; provide a complete JSON object")
    return call


def is_state_changing(tool, params):
    return tool_call_is_mutating(tool, params) or tool in {"code_executor", "code_writer", "self_evolve"}


class StepExecutionState:
    def __init__(self, receipts=None):
        self.receipts = receipts if receipts is not None else []
        self.outcomes = {}
        self.epoch = 0
        self.batch = 0
        self.successes = {}
        self.failures = set()

    def signature(self, tool, params):
        return (self.epoch, tool, json.dumps(params, sort_keys=True, default=str, ensure_ascii=False))

    def prepare(self, calls):
        self.batch += 1
        prepared = []
        counts = Counter()
        explicit_counts = Counter(str(c.get("key")).strip() for c in calls if c.get("key"))
        used_keys = set(explicit_counts)
        for call in calls:
            call = dict(call)
            tool = str(call.get("tool") or "")
            counts[tool] += 1
            key = str(call.get("key") or "").strip()
            if not key:
                key = tool if counts[tool] == 1 else f"{tool}#{counts[tool]}"
                while key in used_keys:
                    counts[tool] += 1
                    key = f"{tool}#{counts[tool]}"
            call["key"] = key
            used_keys.add(key)
            if explicit_counts[call["key"]] > 1:
                call["_dependency_error"] = "duplicate step identity: " + call["key"]
            call["_receipt_key"] = f"{self.batch}:{call['key']}"
            prepared.append(call)
        # Topological order of this actual executable batch, including
        # prerequisites inserted by the clinical normalizer.
        plan = ActionPlan.from_tool_calls(prepared)
        rank = {step.key: i for i, step in enumerate(plan.ordered_steps())}
        prepared.sort(key=lambda call: rank.get(call["key"], len(rank)))
        local = {call["key"]: call["_receipt_key"] for call in prepared}
        for call in prepared:
            call["_receipt_dependencies"] = tuple(
                local.get(dep, dep) for dep in ActionPlan._dependency_keys(call)
            )
        return prepared

    def blocked_reason(self, call):
        if call.get("_argument_error"):
            return call["_argument_error"]
        if call.get("_dependency_error"):
            return call["_dependency_error"]
        blocked = [
            f"{dep} ({self.outcomes.get(dep, 'not_completed')})"
            for dep in call.get("_receipt_dependencies", ())
            if self.outcomes.get(dep) != "succeeded"
        ]
        return ", ".join(blocked)

    def record(self, call, *, success, metadata=None, attempted=True):
        metadata = metadata if isinstance(metadata, dict) else {}
        pending = success and (
            metadata.get("completed") is False
            or metadata.get("status") in {"pending", "queued", "dispatched", "running"}
            or metadata.get("pending") is True
            or metadata.get("execution_claim") == "accepted_pending_browser"
        )
        status = "pending" if pending else "succeeded" if success else "failed"
        self.outcomes[call["_receipt_key"]] = status
        # Explicit references in a subsequent batch see the latest receipt.
        self.outcomes[call["key"]] = status
        tool, params = call.get("tool", ""), call.get("params") or {}
        self.receipts.append({"key": call["_receipt_key"], "tool": tool, "status": status,
                              "attempted": attempted, "epoch": self.epoch,
                              "admission_denied": bool(call.get("_argument_error")),
                              "partial_ui_batch": call.get("_partial_ui_batch")})
        del self.receipts[:-64]
        # A failed writer can have partially changed state too. Never reuse a
        # pre-write read as evidence for the post-write workspace.
        if attempted and is_state_changing(tool, params):
            self.epoch += 1
        if success:
            self.successes[self.signature(tool, params)] = status
        else:
            self.failures.add(self.signature(tool, params))
        return status

    def reuse(self, call):
        signature = self.signature(call.get("tool", ""), call.get("params") or {})
        if signature in self.successes:
            # Preserve pending dispatch state; reuse is not browser completion.
            status = self.successes[signature]
            self.outcomes[call["_receipt_key"]] = status
            self.outcomes[call["key"]] = status
            return True
        return False


def append_tool_receipt(messages, call, text):
    """Keep failures/skips visible to the model with valid tool-call pairing."""
    identifier = str(call.get("id") or call.get("_receipt_key") or call.get("key"))
    messages.append({"role": "assistant", "content": None, "tool_calls": [{
        "id": identifier, "type": "function", "function": {
            "name": call.get("tool", ""),
            "arguments": json.dumps(call.get("params") or {}, ensure_ascii=False, default=str),
        },
    }]})
    messages.append({"role": "tool", "tool_call_id": identifier, "content": text})
