"""Small JSON projections; clinical volumes remain in owned dose endpoints."""
from collections.abc import Mapping
import math
import numpy as np


def planning_response_metadata(metadata):
    """Prune nested numerical payloads, not just top-level arrays.

    Continuation metadata contains component records with full dose volumes.
    Publishing those through a button response both fails JSON serialization
    and bypasses the scoped component read interface. Preserve scalar quality,
    provenance, and review fields while leaving heavy/unsupported data out.
    """
    omitted = object()

    def small(value, depth=0):
        if depth > 12 or isinstance(value, (np.ndarray, bytes, bytearray)):
            return omitted
        if isinstance(value, np.generic):
            return small(value.item(), depth)
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                projected = small(item, depth + 1)
                if projected is not omitted:
                    result[str(key)] = projected
            return result
        if isinstance(value, (list, tuple)):
            if len(value) > 256:
                return omitted
            items = [small(item, depth + 1) for item in value]
            return omitted if any(item is omitted for item in items) else items
        return omitted

    projected = small(metadata)
    return projected if isinstance(projected, dict) else {}
