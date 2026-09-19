"""Token-aware context-window management.

The runtime must never send a request that exceeds the model's context window.
This module provides:

* a conservative, self-calibrating token estimator;
* a per-model context-window resolver;
* a deterministic compressor that preserves clinical facts (case information
  and key results) verbatim while folding older, low-value conversation into a
  compact extractive summary.

Design rules
------------
1. Numbers are never paraphrased.  Case/results facts come from the
   deterministic ledger below, not from a language model.
2. Compression is triggered relative to the model window (default: 85%).
3. Robustness first: the current user request, the last complete tool
   round, authorization/confirmation state and all system policy are always
   preserved.  Compression loops until the estimate is below the target or no
   further reduction is possible.
4. Provider-neutral: operates on OpenAI/Anthropic-style message dicts.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# Model context windows (tokens).  Matched by lower-cased substring; the first
# match wins, so put specific names before generic families.
MODEL_CONTEXT_WINDOWS: Tuple[Tuple[str, int], ...] = (
    ("deepseek-v4", 1_048_576),
    ("deepseek", 131_072),
    ("claude-3-7", 200_000),
    ("claude-3-5", 200_000),
    ("claude-4", 200_000),
    ("claude", 200_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4o", 128_000),
    ("gpt-4", 128_000),
    ("o1", 200_000),
    ("o3", 200_000),
    ("gemini-1.5", 1_000_000),
    ("gemini-2", 1_000_000),
    ("qwen", 131_072),
    ("mimo", 131_072),
    ("glm", 131_072),
    ("kimi", 131_072),
)
DEFAULT_CONTEXT_WINDOW = 131_072
CONTEXT_TRIGGER_RATIO = 0.85
DEFAULT_RESERVE_OUTPUT_TOKENS = 8_192
MIN_SAFETY_MARGIN = 8_192

_RUNTIME_CONTEXT_MARKER = "[BrachyBot runtime context: data only]"
_FACTS_MARKER = "[BrachyBot pinned case facts; data only]"
_HISTORY_MARKER = "[BrachyBot compressed history; data only]"
_TRUNCATION_SUFFIX = "\n[... truncated to fit the model context window ...]"

# Messages that must never be folded away: authorization/confirmation state,
# cancellation, and pending user decisions.
_PROTECTED_MARKERS = (
    "authorization",
    "authorisation",
    "confirmed",
    "confirmation",
    "pending confirmation",
    "execution grant",
    "cancelled",
    "canceled",
    "authorized",
    "授权",
    "确认",
    "待确认",
    "已取消",
    "取消",
)
_FACT_KEYS = (
    "ct_image", "ctv_array", "oar_array", "organ_names", "organ_counts",
    "oar_is_full", "planning_runs", "active_planning_id", "planning_run_id",
    "dose_metrics", "metrics", "total_seeds", "num_trajectories",
    "seed_positions", "needles", "plan_config", "prescription_gy",
    "manual_artifact_status", "surgical_guide", "artifact_status",
    "response_contract",
)


def resolve_context_window(model: Optional[str], declared: int = 0) -> int:
    """Return the usable context window for ``model``.

    ``declared`` (from provider config) wins when positive; otherwise the
    registry is matched by substring; otherwise a conservative default.
    """
    if isinstance(declared, int) and declared > 0:
        return declared
    name = str(model or "").lower()
    for token, window in MODEL_CONTEXT_WINDOWS:
        if token in name:
            return window
    return DEFAULT_CONTEXT_WINDOW


def _cjk_count(text: str) -> int:
    return sum(1 for ch in text if "\u3400" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f")


def estimate_text(text: Any, *, safety: float = 1.15) -> int:
    """Conservative token estimate for plain text.

    CJK characters cost ~1 token each; Latin text is over-estimated at ~1
    token per 3.5 characters (real tokenizers are closer to 4).  A safety
    factor is applied so the budget is never optimistic.
    """
    if text is None:
        return 0
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return 0
    cjk = _cjk_count(text)
    other = max(0, len(text) - cjk)
    base = cjk + other / 3.5
    return int(base * safety) + 1


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, Mapping):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content or "")


def estimate_message(message: Mapping[str, Any], *, safety: float = 1.15) -> int:
    """Estimate one provider message, including tool calls and images."""
    if not isinstance(message, Mapping):
        return 0
    total = 4  # role / separator overhead
    total += estimate_text(_content_text(message.get("content")), safety=safety)
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        try:
            total += estimate_text(
                json.dumps(tool_calls, ensure_ascii=False, default=str), safety=safety
            )
        except Exception:
            total += 64 * len(tool_calls)
    content = message.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, Mapping) and (
                item.get("type") == "image_url" or "image_url" in item
            ):
                url = ""
                image_url = item.get("image_url")
                if isinstance(image_url, Mapping):
                    url = str(image_url.get("url") or "")
                elif isinstance(image_url, str):
                    url = image_url
                # base64 payloads are roughly 4 chars per token; count them.
                total += max(1_000, len(url) // 4)
    return total


def estimate_messages(
    messages: Iterable[Mapping[str, Any]],
    tools: Optional[Any] = None,
    *,
    safety: float = 1.15,
) -> int:
    total = sum(estimate_message(m, safety=safety) for m in (messages or []))
    if tools:
        try:
            total += estimate_text(json.dumps(tools, ensure_ascii=False, default=str), safety=safety)
        except Exception:
            total += 2_000
    return total


@dataclass
class CompressionMeta:
    window: int
    target_tokens: int
    trigger_ratio: float
    before_tokens: int
    after_tokens: int
    ratio_before: float
    ratio_after: float
    compressed: bool
    folded_messages: int = 0
    truncated_segments: int = 0
    passes: int = 0
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "window": self.window,
            "target_tokens": self.target_tokens,
            "trigger_ratio": self.trigger_ratio,
            "before_tokens": self.before_tokens,
            "after_tokens": self.after_tokens,
            "ratio_before": round(self.ratio_before, 4),
            "ratio_after": round(self.ratio_after, 4),
            "compressed": self.compressed,
            "folded_messages": self.folded_messages,
            "truncated_segments": self.truncated_segments,
            "passes": self.passes,
            "reason": self.reason,
        }


class ContextWindowManager:
    """Enforce a token budget on the provider message list."""

    def __init__(
        self,
        *,
        window: int,
        trigger_ratio: float = CONTEXT_TRIGGER_RATIO,
        reserve_output_tokens: int = DEFAULT_RESERVE_OUTPUT_TOKENS,
        safety_margin: int = 0,
        preserve_tail_rounds: int = 6,
        facts_max_chars: int = 8_000,
    ) -> None:
        self.window = max(8_192, int(window))
        self.trigger_ratio = min(0.98, max(0.5, float(trigger_ratio)))
        self.reserve_output_tokens = max(512, int(reserve_output_tokens))
        self.safety_margin = min(
            max(MIN_SAFETY_MARGIN, int(safety_margin), int(self.window * 0.02)),
            max(512, self.window // 4),
        )
        self.preserve_tail_rounds = max(2, int(preserve_tail_rounds))
        self.facts_max_chars = max(1_000, int(facts_max_chars))
        self.calibration = 1.0

    # -- budgeting ---------------------------------------------------------
    @property
    def target_tokens(self) -> int:
        return max(
            1_000,
            self.window - self.reserve_output_tokens - self.safety_margin,
        )

    @property
    def trigger_tokens(self) -> int:
        return int(self.target_tokens * self.trigger_ratio)

    def usage(self, messages: Iterable[Mapping[str, Any]], tools: Optional[Any] = None) -> int:
        return int(estimate_messages(messages, tools) * self.calibration)

    def ratio(self, messages: Iterable[Mapping[str, Any]], tools: Optional[Any] = None) -> float:
        return self.usage(messages, tools) / float(self.window)

    def should_compress(self, messages: Iterable[Mapping[str, Any]], tools: Optional[Any] = None) -> bool:
        return self.usage(messages, tools) >= self.trigger_tokens

    def record_usage(self, *, actual_prompt_tokens: int, estimated_tokens: int) -> None:
        """Calibrate the estimator from real provider usage (EMA)."""
        if actual_prompt_tokens <= 0 or estimated_tokens <= 0:
            return
        observed = actual_prompt_tokens / float(estimated_tokens)
        observed = min(4.0, max(0.25, observed))
        self.calibration = round(0.8 * self.calibration + 0.2 * observed, 4)

    def snapshot(self, messages: Iterable[Mapping[str, Any]], tools: Optional[Any] = None) -> Dict[str, Any]:
        used = self.usage(messages, tools)
        return {
            "window": self.window,
            "used_tokens": used,
            "target_tokens": self.target_tokens,
            "trigger_tokens": self.trigger_tokens,
            "trigger_ratio": self.trigger_ratio,
            "ratio": round(used / float(self.window), 4),
            "calibration": self.calibration,
            "message_count": len(list(messages)) if not isinstance(messages, list) else len(messages),
        }

    # -- compression -------------------------------------------------------
    def compress(
        self,
        messages: List[Dict[str, Any]],
        *,
        fact_block: str = "",
        aggressive: bool = False,
        tools: Optional[Any] = None,
        current_user_content: Any = None,
    ) -> Tuple[List[Dict[str, Any]], CompressionMeta]:
        source = [dict(m) for m in (messages or []) if isinstance(m, Mapping)]
        before = self.usage(source, tools)
        target = self.target_tokens
        if aggressive:
            target = int(target * 0.75)
        ratio_before = before / float(self.window)
        meta = CompressionMeta(
            window=self.window,
            target_tokens=target,
            trigger_ratio=self.trigger_ratio,
            before_tokens=before,
            after_tokens=before,
            ratio_before=ratio_before,
            ratio_after=ratio_before,
            compressed=False,
        )
        if not aggressive and before < self.trigger_tokens:
            return source, meta

        system_msgs = [m for m in source if m.get("role") == "system"]
        body = [m for m in source if m.get("role") != "system"]

        # The current user request is the last user message (the runtime
        # context is also a user message, so prefer the explicit content).
        current_idx = None
        for idx in range(len(body) - 1, -1, -1):
            if body[idx].get("role") == "user":
                if current_user_content is None or _content_text(body[idx].get("content")) == current_user_content:
                    current_idx = idx
                    break
        if current_idx is None and body:
            for idx in range(len(body) - 1, -1, -1):
                if body[idx].get("role") == "user":
                    current_idx = idx
                    break

        protected_idx = self._protected_indices(body)
        tail_start = self._tail_start(body, self.preserve_tail_rounds, protected_idx, current_idx)

        middle = body[:tail_start]
        tail = body[tail_start:]

        # Extractive fold of the compressible middle; keep numbers verbatim.
        folded = self._extract_summary(middle)
        meta.folded_messages = len(middle)

        assembled = list(system_msgs)
        if fact_block:
            assembled.append({
                "role": "user",
                "content": f"{_FACTS_MARKER}\n" + fact_block[: self.facts_max_chars],
            })
        if folded:
            assembled.append({
                "role": "user",
                "content": f"{_HISTORY_MARKER}\n" + folded,
            })
        assembled.extend(tail)

        passes = 0
        while self.usage(assembled, tools) > target and passes < 20:
            passes += 1
            shrunk = self._shrink(assembled, tools, target)
            if not shrunk:
                break
            assembled = shrunk

        meta.compressed = True
        meta.passes = passes
        meta.after_tokens = self.usage(assembled, tools)
        meta.ratio_after = meta.after_tokens / float(self.window)
        if meta.after_tokens > target:
            meta.reason = "budget_still_exceeded_after_compression"
        else:
            meta.reason = "compressed"
        return assembled, meta

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _protected_indices(body: List[Dict[str, Any]]) -> set:
        protected = set()
        for idx, msg in enumerate(body):
            text = _content_text(msg.get("content")).lower()
            if any(marker in text for marker in _PROTECTED_MARKERS):
                protected.add(idx)
        return protected

    @staticmethod
    def _tail_start(
        body: List[Dict[str, Any]],
        tail_rounds: int,
        protected: set,
        current_idx: Optional[int],
    ) -> int:
        """Start index of the verbatim tail, keeping tool pairs together."""
        n = len(body)
        start = max(0, n - max(2, tail_rounds * 2))
        # Never split an assistant tool_call from its tool results.
        while start > 0 and body[start].get("role") == "tool":
            start -= 1
        # Keep protected messages and the current request verbatim.
        required = set(protected)
        if current_idx is not None:
            required.add(current_idx)
        if required:
            start = min(start, min(required))
        return max(0, start)

    @staticmethod
    def _extract_summary(messages: List[Dict[str, Any]]) -> str:
        """Deterministic extractive summary; numbers preserved verbatim."""
        if not messages:
            return ""
        lines: List[str] = []
        for msg in messages:
            role = str(msg.get("role") or "?")
            text = re.sub(r"\s+", " ", _content_text(msg.get("content"))).strip()
            if not text and msg.get("tool_calls"):
                names = [
                    str(tc.get("function", {}).get("name") or tc.get("name") or "")
                    for tc in msg.get("tool_calls", [])
                    if isinstance(tc, Mapping)
                ]
                text = "called " + ", ".join(n for n in names if n)
            if not text:
                continue
            if len(text) > 220:
                text = text[:220].rstrip() + "…"
            lines.append(f"- {role}: {text}")
        if not lines:
            return ""
        return "\n".join(lines)

    def _shrink(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[Any],
        target: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """One reduction pass.

        Order: (1) truncate the largest data-only marker segment; (2) drop the
        oldest complete unit.  Tool-call/result pairs are always dropped
        together, and system policy, pinned facts, protected state and the
        current user request are never removed.
        """
        current_cost = self.usage(messages, tools)
        if current_cost <= target:
            return None
        n = len(messages)

        protected = set()
        for idx, msg in enumerate(messages):
            text = _content_text(msg.get("content"))
            if msg.get("role") == "system" or text.startswith(
                (_FACTS_MARKER, _HISTORY_MARKER, _RUNTIME_CONTEXT_MARKER)
            ):
                protected.add(idx)
            elif any(marker in text.lower() for marker in _PROTECTED_MARKERS):
                protected.add(idx)
        for idx in range(n - 1, -1, -1):
            if messages[idx].get("role") == "user":
                protected.add(idx)  # the current user request
                break

        # 1) Truncate the largest data-only segment (history/runtime/facts).
        best = None
        for idx, msg in enumerate(messages):
            text = _content_text(msg.get("content"))
            if text.startswith(
                (_HISTORY_MARKER, _RUNTIME_CONTEXT_MARKER, _FACTS_MARKER)
            ) and len(text) > 400:
                if best is None or len(text) > best[0]:
                    best = (len(text), idx)
        if best is not None:
            length, idx = best
            text = _content_text(messages[idx].get("content"))
            shortened = list(messages)
            shortened[idx] = {
                **messages[idx],
                "content": text[: int(length * 0.6)] + _TRUNCATION_SUFFIX,
            }
            if self.usage(shortened, tools) < current_cost:
                return shortened

        # 2) Drop the oldest complete unit that is not protected.
        for idx in range(n):
            if idx in protected:
                continue
            if messages[idx].get("role") == "tool":
                continue  # dropped together with its assistant tool_call
            end = idx + 1
            if messages[idx].get("tool_calls"):
                while end < n and messages[end].get("role") == "tool":
                    end += 1
            if any(i in protected for i in range(idx, end)):
                continue
            candidate = list(messages[:idx]) + list(messages[end:])
            if self.usage(candidate, tools) < current_cost:
                return candidate
        return None


# ---------------------------------------------------------------------------
# Deterministic case-fact ledger
# ---------------------------------------------------------------------------

_METRIC_LABELS = (
    "V100", "V150", "V200", "D90", "D95", "Dmean", "D2", "Dmax",
    "CI", "HI", "plan_score", "prescription_gy",
)


def build_case_facts(memory: Any) -> str:
    """Build a compact, verbatim case/results ledger from agent memory.

    This is the information that must survive any amount of compression:
    what case is loaded, which structures exist, how many needles/seeds were
    planned, and every dosimetric metric.  It is deterministic and never
    paraphrases numbers.
    """
    if memory is None:
        return ""
    retrieve = getattr(memory, "retrieve", None)
    if not callable(retrieve):
        return ""

    def _get(key: str, default: Any = None) -> Any:
        try:
            return retrieve(key, default) if default is not None else retrieve(key)
        except Exception:
            try:
                return retrieve(key)
            except Exception:
                return None

    lines: List[str] = ["## Case facts (verbatim)"]
    try:
        if _get("ct_path") or _get("ct_image") is not None:
            lines.append("- CT: loaded")
        ctv = _get("ctv_array")
        oar = _get("oar_array")
        lines.append(f"- CTV segmented: {'yes' if ctv is not None else 'no'}")
        lines.append(f"- OAR segmented: {'yes' if oar is not None else 'no'}")
        organ_names = _get("organ_names")
        if isinstance(organ_names, Mapping) and organ_names:
            names = [str(v) for v in list(organ_names.values())]
            lines.append(f"- OAR ({len(names)}): {', '.join(names[:40])}")
        counts = _get("organ_counts")
        if isinstance(counts, Mapping) and counts:
            top = sorted(((k, v) for k, v in counts.items()), key=lambda kv: kv[1], reverse=True)[:8]
            lines.append("- OAR volumes (voxels, top): " + ", ".join(f"{k}:{v}" for k, v in top))
    except Exception:
        pass

    try:
        seeds = _get("total_seeds")
        if seeds is None:
            positions = _get("seed_positions")
            seeds = len(positions) if isinstance(positions, (list, tuple)) else None
        needles = _get("num_trajectories")
        if needles is None:
            needles = _get("needles")
            if isinstance(needles, (list, tuple)):
                needles = len(needles)
        if seeds is not None:
            lines.append(f"- Seeds planned: {seeds}")
        if needles is not None:
            lines.append(f"- Needles/trajectories: {needles}")
        planning_id = _get("active_planning_id") or _get("planning_run_id")
        if planning_id:
            lines.append(f"- Active planning id: {planning_id}")
    except Exception:
        pass

    metrics = _get("dose_metrics") or _get("metrics")
    if isinstance(metrics, Mapping) and "metrics" in metrics and isinstance(metrics.get("metrics"), Mapping):
        metrics = metrics["metrics"]
    if isinstance(metrics, Mapping):
        pairs = []
        for key in _METRIC_LABELS:
            if key in metrics and isinstance(metrics[key], (int, float)):
                pairs.append(f"{key}={metrics[key]}")
        if pairs:
            lines.append("- Dosimetry (verbatim): " + ", ".join(pairs))
    prescription = _get("prescription_gy")
    if isinstance(prescription, (int, float)):
        lines.append(f"- Prescription: {prescription} Gy")

    artifact = _get("artifact_status") or _get("manual_artifact_status")
    if isinstance(artifact, Mapping) and artifact:
        try:
            lines.append("- Artifact status: " + json.dumps(artifact, ensure_ascii=False, default=str)[:600])
        except Exception:
            pass
    guide = _get("surgical_guide")
    if isinstance(guide, Mapping):
        state = guide.get("state") or guide.get("status")
        if state:
            lines.append(f"- Surgical guide: {state}")

    return "\n".join(lines) if len(lines) > 1 else ""


def is_context_length_error(error: Any) -> bool:
    """Detect a provider context-window overflow from an exception/message."""
    text = str(error or "").lower()
    if not text:
        return False
    if "context length" in text or "context_length" in text or "maximum context" in text:
        return True
    if "too many tokens" in text or "reduce the length" in text:
        return True
    if "token" in text and ("exceed" in text or "maximum" in text):
        return True
    return False
