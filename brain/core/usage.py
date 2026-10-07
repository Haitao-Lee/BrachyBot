"""Canonical token accounting for a single provider request.

Input is the full prompt, including cached input. Output includes provider
reported reasoning tokens; details are subsets, never added a second time.
Missing usage is not a measured zero. This module performs no tokenization.
"""
from collections.abc import Mapping
import math


def _count(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or number < 0 or not number.is_integer():
            return None
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_usage(usage):
    """Normalize OpenAI-style usage without inventing missing measurements."""
    source = dict(usage) if isinstance(usage, Mapping) else {}
    prompt = _count(source.get("prompt_tokens", source.get("input_tokens")))
    output = _count(source.get("completion_tokens", source.get("output_tokens")))
    # Preserve availability through repeated normalization at transport and
    # runtime boundaries. Generated zero placeholders are not measurements.
    input_known = bool(source.get("input_reported", prompt is not None))
    output_known = bool(source.get("output_reported", output is not None))
    # Providers often manufacture all-zero placeholders when usage is absent.
    # A completed chat request cannot have a genuinely empty provider prompt.
    input_known = input_known and prompt is not None and prompt > 0
    output_known = output_known and output is not None
    reported_total = _count(source.get("total_tokens"))
    result = {
        "prompt_tokens": prompt if input_known else 0,
        "completion_tokens": output if output_known else 0,
        "total_tokens": ((prompt + output) if input_known and output_known
                         else (reported_total or (prompt or 0) + (output or 0))),
        "input_reported": input_known,
        "output_reported": output_known,
        "usage_complete": input_known and output_known,
    }
    for key in ("provider", "model", "context_window", "window_source"):
        if key in source:
            result[key] = (_count(source[key]) or 0) if key == 'context_window' else source[key]
    return result


def anthropic_usage(usage):
    """Anthropic input_tokens excludes cache creation/read input tokens."""
    def field(name):
        return usage.get(name) if isinstance(usage, Mapping) else getattr(usage, name, None)

    input_count = _count(field("input_tokens"))
    output_count = _count(field("output_tokens"))
    source = {}
    if input_count is not None:
        source["prompt_tokens"] = input_count + sum(
            _count(field(key)) or 0
            for key in ("cache_creation_input_tokens", "cache_read_input_tokens")
        )
    if output_count is not None:
        source["completion_tokens"] = output_count
    return normalize_usage(source)


def merge_usage_snapshot(previous, update):
    """Merge cumulative stream snapshots, not deltas or repeated bills."""
    old, new = normalize_usage(previous), normalize_usage(update)
    merged = dict(old)
    for count, known in (("prompt_tokens", "input_reported"),
                         ("completion_tokens", "output_reported")):
        if new[known]:
            merged[count], merged[known] = new[count], True
    for key in ("provider", "model", "context_window", "window_source"):
        if key in new:
            merged[key] = new[key]
    merged.pop("total_tokens", None)
    return normalize_usage(merged)
