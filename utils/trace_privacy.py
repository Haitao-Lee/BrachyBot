"""Bounded presentation parameters, not executable arguments or a PHI detector.

Paths, payloads and patient-data containers are omitted. Operator-supplied
object names may still be sensitive; deployment log access/retention controls
are required independently of this allowlist.
"""
import math
import re

# No paths, prompts, queries, patient fields, arrays, arbitrary values or URLs.
# UI action values remain on the authenticated action executor, not the trace.
_FIELDS = frozenset({"action", "command", "target", "mode", "method", "format", "metric_type", "views", "layout", "object_ids", "planning_id", "component", "classification"})
_TOKEN = re.compile(r"^[\w .:\-]{1,160}$", re.UNICODE)


def presentation_params(params):
    safe = {}
    for key, value in params.items():
        if key not in _FIELDS:
            continue
        if isinstance(value, str) and _TOKEN.fullmatch(value):
            safe[key] = value
        elif isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, (int, float)) and math.isfinite(value):
            safe[key] = value
        elif isinstance(value, (list, tuple)) and len(value) <= 64 and all(isinstance(v, str) and _TOKEN.fullmatch(v) for v in value):
            safe[key] = list(value)
    return safe
