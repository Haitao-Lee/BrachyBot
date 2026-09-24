"""Canonical, planning-scoped dose-metric normalization and rendering.

Dose results have historically been persisted in both a flat UI shape and a
nested evaluator shape (``metrics -> CTV / oars``).  Read paths must normalize
those shapes without crossing Planning boundaries or treating OAR volumes as
dose evidence.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, Dict


_DOSE_ROW_KEYS = frozenset({
    "dmax", "maxdose", "dmean", "meandose", "d01cc", "d1cc", "d2cc",
    "d90", "d95", "v100", "v150", "v200",
})
_OAR_CONTAINER_KEYS = ("oar_metrics", "oars", "oar", "organs_at_risk")
_CTV_NAMES = frozenset({
    "ctv", "gtv", "ptv", "target", "target_volume",
    "gross_tumor_volume", "gross_tumour_volume",
})


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _finite_number(value: Any):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _looks_like_dose_row(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    for name, item in value.items():
        if _key(name) in _DOSE_ROW_KEYS and _finite_number(item) is not None:
            return True
    return False


def _rows_from_container(value: Any) -> Dict[str, dict]:
    if not isinstance(value, Mapping):
        return {}
    # Some legacy snapshots wrapped the OAR map one more time.
    for wrapper in _OAR_CONTAINER_KEYS + ("structures",):
        nested = value.get(wrapper)
        if isinstance(nested, Mapping):
            value = nested
            break
    if _looks_like_dose_row(value):
        return {}
    return {
        str(name): dict(row)
        for name, row in value.items()
        if isinstance(row, Mapping) and _looks_like_dose_row(row)
    }


def extract_oar_dose_metrics(payload: Any) -> Dict[str, dict]:
    """Extract only organ rows that contain an observed dose/DVH value."""
    if not isinstance(payload, Mapping):
        return {}
    nested = payload.get("metrics")
    containers = [payload]
    if isinstance(nested, Mapping):
        containers.append(nested)

    # Explicit, canonical maps take precedence; merge older nested shapes only
    # to fill missing organ rows/fields from the same selected Planning.
    result: Dict[str, dict] = {}
    for container in reversed(containers):
        for name in _OAR_CONTAINER_KEYS:
            rows = _rows_from_container(container.get(name))
            for organ, row in rows.items():
                merged = dict(result.get(organ, {}))
                for key, value in row.items():
                    if value is not None or key not in merged:
                        merged[key] = value
                result[organ] = merged

        if container is nested and isinstance(container, Mapping):
            for organ, row in container.items():
                row_type = str(row.get("type", "")).strip().lower() if isinstance(row, Mapping) else ""
                if (
                    _key(organ) in _CTV_NAMES
                    or row_type in {"target", "ctv", "gtv", "ptv"}
                    or not _looks_like_dose_row(row)
                ):
                    continue
                merged = dict(result.get(str(organ), {}))
                for key, value in row.items():
                    if value is not None or key not in merged:
                        merged[key] = value
                result[str(organ)] = merged
    return result


def normalize_dose_metrics(payload: Any) -> Dict[str, Any]:
    """Flatten CTV fields and expose a canonical ``oar_metrics`` map.

    Top-level values remain authoritative over nested CTV values; the nested
    source is retained for compatibility with consumers that need provenance.
    """
    if not isinstance(payload, Mapping):
        return {}
    output: Dict[str, Any] = dict(payload)
    nested = payload.get("metrics")
    if isinstance(nested, Mapping):
        target = None
        for name, row in nested.items():
            if not isinstance(row, Mapping):
                continue
            if _key(name) in _CTV_NAMES or str(row.get("type", "")).lower() == "target":
                target = row
                break
        if target is not None:
            flattened = dict(target)
            flattened.update(output)
            output = flattened
    oars = extract_oar_dose_metrics(payload)
    if oars:
        output["oar_metrics"] = oars
    return output


def _prefer_merge(existing: Any, incoming: Any) -> Any:
    """Merge a lower-priority value with a higher-priority value."""
    if isinstance(existing, Mapping) and isinstance(incoming, Mapping):
        merged = {str(key): value for key, value in existing.items()}
        for key, value in incoming.items():
            key = str(key)
            if key in merged:
                merged[key] = _prefer_merge(merged[key], value)
            elif value is not None:
                merged[key] = value
        return merged
    if (
        incoming is None
        or (isinstance(incoming, Mapping) and not incoming)
        or (isinstance(incoming, (list, tuple)) and not incoming)
    ):
        return existing
    return incoming


def merge_dose_metric_sources(*sources: Any) -> Dict[str, Any]:
    """Merge metric aliases in priority order (first source wins conflicts)."""
    merged: Dict[str, Any] = {}
    for source in reversed(sources):
        normalized = normalize_dose_metrics(source)
        if normalized:
            merged = _prefer_merge(merged, normalized)
    return normalize_dose_metrics(merged)


def has_oar_dose_metrics(payload: Any) -> bool:
    return bool(extract_oar_dose_metrics(payload))


def _row_number(row: Mapping, aliases):
    by_key = {_key(name): value for name, value in row.items()}
    for alias in aliases:
        value = _finite_number(by_key.get(_key(alias)))
        if value is not None:
            return value
    return None


def format_oar_dose_table(oar_metrics: Any, lang: str = "en") -> str:
    """Render every available OAR dose row without making a pass/fail claim."""
    rows = extract_oar_dose_metrics({"oar_metrics": oar_metrics})
    if not rows:
        return ""

    columns = [
        ("Dmax (Gy)", ("dmax", "max_dose"), False),
        ("D0.1cc (Gy)", ("d0_1cc", "d0.1cc"), False),
        ("D1cc (Gy)", ("d1cc",), False),
        ("D2cc (Gy)", ("d2cc",), False),
        ("Dmean (Gy)", ("mean_dose", "dmean"), False),
        ("V100 (%)", ("v100",), True),
        ("V150 (%)", ("v150",), True),
    ]
    if any(_row_number(row, ("d90",)) is not None for row in rows.values()):
        columns.insert(4, ("D90 (Gy)", ("d90",), False))
    if any(_row_number(row, ("d95",)) is not None for row in rows.values()):
        columns.insert(5, ("D95 (Gy)", ("d95",), False))

    def rank(item):
        row = item[1]
        return max(
            _row_number(row, ("dmax", "max_dose")) or 0.0,
            _row_number(row, ("d2cc",)) or 0.0,
        )

    ordered = sorted(rows.items(), key=rank, reverse=True)
    zh = str(lang).lower().startswith("zh")
    title = f"各危及器官受照剂量（{len(ordered)} 个结构）" if zh else f"Dose metrics for all OARs ({len(ordered)} structures)"
    note = (
        "以下均为当前规划保存的观测值；数值本身不代表符合或违反临床限值。"
        if zh else
        "These are observed values from the active Planning; they do not by themselves indicate compliance with clinical limits."
    )
    headers = ["器官" if zh else "Organ"] + [
        (label.replace(" (Gy)", "（Gy）") if zh else label)
        for label, _aliases, _percent in columns
    ]
    lines = [f"## {title}", "", note, "", "| " + " | ".join(headers) + " |", "|" + "---:|" * len(headers)]
    for name, row in ordered:
        values = [str(name).replace("_", " ")]
        for _label, aliases, percent in columns:
            value = _row_number(row, aliases)
            if value is None:
                values.append("—")
            elif percent:
                if 1.0 < value <= 100.0:
                    value /= 100.0
                values.append(f"{value * 100.0:.2f}")
            else:
                values.append(f"{value:.2f}")
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
