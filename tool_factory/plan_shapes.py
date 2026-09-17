"""Canonical needle/seed shape extraction for plan containers.

The optimizer publishes ``[trajectory, seeds, dose_maps]`` entries, the
published mirror stores per-trajectory dicts with ``seeds`` records, and a
flattened seed list can arrive as dicts, ``(position, direction)`` pairs, or
an ``(N, 3)`` array.  A metric read must count the seeds inside every shape
and must never mistake one plan entry (one needle) for one seed.

The helpers are deliberately dependency-free so metric and report callers do
not import the planning stack (torch, dose models) just to count seeds.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List, Optional


def _as_sequence(value: Any) -> Optional[List[Any]]:
    if value is None or isinstance(value, (str, bytes, bytearray, Mapping)):
        return None
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return None


def _is_point(value: Any) -> bool:
    """Return True for a coordinate vector such as ``[x, y, z]``."""
    if value is None or isinstance(value, (str, bytes, bytearray, Mapping)):
        return False
    sequence = _as_sequence(value)
    if not sequence:
        return False
    try:
        float(sequence[0])
    except (TypeError, ValueError):
        return False
    return True


def _is_scalar(value: Any) -> bool:
    if value is None or isinstance(value, (str, bytes, bytearray, Mapping)):
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _is_seed_record(value: Any) -> bool:
    """Return True for one seed record.

    Records are mappings with ``position``/``pos``, ``(position, direction)``
    pairs, or bare position vectors in flattened seed lists.
    """
    if isinstance(value, Mapping):
        return any(key in value for key in ("position", "pos", "direction", "dir"))
    sequence = _as_sequence(value)
    if sequence is None or len(sequence) < 2:
        return False
    if _is_point(sequence[0]):
        return True
    try:
        for item in sequence:
            float(item)
    except (TypeError, ValueError):
        return False
    return True


def _seed_records(value: Any) -> Optional[List[Any]]:
    """Return the seed record list when *value* is a container of seeds.

    Anything else — including a trajectory object or a single coordinate
    vector — returns None so callers can distinguish a seed list from other
    nested plan data.
    """
    sequence = _as_sequence(value)
    if sequence is None:
        return None
    if sequence and all(_is_scalar(item) for item in sequence):
        # A bare coordinate vector is one point, not a container of seeds.
        return None
    for record in sequence:
        if not _is_seed_record(record):
            return None
    return sequence


def _declared_count(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _mapping_needle_id(mapping: Mapping) -> Optional[str]:
    for key in ("needle_id", "trajectory_id", "id"):
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value)
    trajectory = mapping.get("trajectory")
    if isinstance(trajectory, Mapping):
        for key in ("needle_id", "trajectory_id", "id"):
            value = trajectory.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _entry_needle_id(trajectory: Any) -> Optional[str]:
    if isinstance(trajectory, Mapping):
        return _mapping_needle_id(trajectory)
    return None


def _normalize_entry(entry: Any) -> Optional[Dict[str, Any]]:
    """Normalize one plan entry, or return None for flat seed records."""
    if isinstance(entry, Mapping):
        if "seeds" in entry or "num_seeds" in entry:
            records = _seed_records(entry.get("seeds")) or []
            count = len(records) if records else _declared_count(entry.get("num_seeds"))
            return {"needle_id": _mapping_needle_id(entry), "seed_count": count}
        if "position" in entry or "pos" in entry:
            return None
        if any(key in entry for key in ("trajectory", "trajectory_id", "needle_id")):
            return {
                "needle_id": _mapping_needle_id(entry),
                "seed_count": _declared_count(entry.get("num_seeds")),
            }
        return None
    sequence = _as_sequence(entry)
    if sequence is None or len(sequence) < 2:
        return None
    records = _seed_records(sequence[1])
    if records is None:
        return None
    return {"needle_id": _entry_needle_id(sequence[0]), "seed_count": len(records)}


def _flat_groups(records: List[Any]) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for record in records:
        needle_id: Optional[str] = None
        if isinstance(record, Mapping):
            needle_id = _mapping_needle_id(record)
        key = needle_id or ""
        if key not in groups:
            groups[key] = {"needle_id": needle_id, "seed_count": 0}
            order.append(key)
        groups[key]["seed_count"] += 1
    return [groups[key] for key in order]


def normalize_plan_entries(plan: Any) -> List[Dict[str, Any]]:
    """Normalize any plan container to ``{needle_id, seed_count}`` entries.

    An empty or unusable container returns an empty list; callers fall back
    to their declared totals instead of inventing geometry.
    """
    sequence = _as_sequence(plan)
    if not sequence:
        return []
    entries: List[Dict[str, Any]] = []
    for entry in sequence:
        normalized = _normalize_entry(entry)
        if normalized is None:
            entries = []
            break
        entries.append(normalized)
    if entries:
        return entries
    records = _seed_records(sequence)
    if records is None:
        return []
    return _flat_groups(records)


def count_plan_seeds(plan: Any) -> int:
    return sum(entry["seed_count"] for entry in normalize_plan_entries(plan))


def count_plan_needles(plan: Any) -> int:
    return len(normalize_plan_entries(plan))
