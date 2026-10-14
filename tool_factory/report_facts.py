"""Canonical planning facts consumed by every report entry point.

The browser report, the HTTP auto-fill route, and the report tool used to
resolve the same plan through different subsets of AgentMemory. That made a
fact such as the prescription dose appear in one view but remain blank in
another after a restart. This module contains side-effect-free extraction
and unit normalization so all report producers use the same contract.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Dict, Iterable, Optional

from plans.dose_pre.model_loader import resolve_prescription_gy
from utils.resource_status import resource_is_stale


def _retrieve(memory: Any, key: str, default: Any = None) -> Any:
    if memory is None:
        return default
    try:
        value = memory.retrieve(key)
    except TypeError:
        try:
            value = memory.retrieve(key, default)
        except Exception:
            value = default
    except Exception:
        value = default
    return default if value is None else value


def _walk_mappings(value: Any, *, depth: int = 0) -> Iterable[Mapping]:
    if depth > 4:
        return
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            if isinstance(child, Mapping):
                yield from _walk_mappings(child, depth=depth + 1)
            elif isinstance(child, list) and depth < 3:
                for item in child:
                    if isinstance(item, Mapping):
                        yield from _walk_mappings(item, depth=depth + 1)


def _first_value(sources: Iterable[Any], keys: Iterable[str]) -> Any:
    wanted = tuple(str(key) for key in keys)
    for source in sources:
        for mapping in _walk_mappings(source):
            for key in wanted:
                if key in mapping and mapping.get(key) not in (None, ""):
                    return mapping.get(key)
    return None


def _number(value: Any, *, positive: bool = False) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _integer(value: Any, *, positive: bool = False) -> Optional[int]:
    number = _number(value, positive=positive)
    if number is None:
        return None
    return int(round(number))


def _source_count(value):
    if isinstance(value,bool):return None
    number=_number(value)
    return int(number) if number is not None and number >= 0 and number.is_integer() else None


def _activity_to_mbq(value: Any, unit: str = "") -> Optional[float]:
    number = _number(value, positive=True)
    if number is None:
        return None
    normalized = str(unit or "").strip().lower().replace("µ", "u")
    if "mci" in normalized:
        return number * 37.0
    if "uci" in normalized:
        return number * 0.037
    return number


def _explicit_activity(sources: Iterable[Any], total_seeds: Optional[int]) -> Dict[str, Any]:
    total_keys = (
        "total_activity_mbq", "totalActivityMBq", "total_activity",
        "total_source_activity_mbq", "source_activity_total_mbq",
    )
    per_seed_mbq_keys = (
        "activity_mbq", "activity_mbq_per_seed", "seed_activity_mbq",
        "source_activity_mbq", "strength_mbq", "source_strength_mbq",
    )
    per_seed_mci_keys = (
        "activity_mci", "activity_mci_per_seed", "seed_activity_mci",
        "source_activity_mci",
    )
    per_seed_uci_keys = ("activity_uci", "activity_uci_per_seed", "seed_activity_uci")

    total_raw = _first_value(sources, total_keys)
    total_unit = _first_value(sources, ("total_activity_unit", "activity_unit")) or "MBq"
    total = _activity_to_mbq(total_raw, str(total_unit)) if total_raw is not None else None

    per_raw = _first_value(sources, per_seed_mbq_keys)
    per_unit = "MBq"
    if per_raw is None:
        per_raw = _first_value(sources, per_seed_mci_keys)
        per_unit = "mCi"
    if per_raw is None:
        per_raw = _first_value(sources, per_seed_uci_keys)
        per_unit = "uCi"
    per_seed = _activity_to_mbq(per_raw, per_unit) if per_raw is not None else None
    if total is None and per_seed is not None and total_seeds is not None:
        total = per_seed * int(total_seeds)

    if total is None:
        return {
            "seed_activity_mbq": None,
            "total_activity_mbq": None,
            "activity_source": "",
            "activity_status": "not_recorded",
        }
    return {
        "seed_activity_mbq": round(per_seed, 6) if per_seed is not None else None,
        "total_activity_mbq": round(total, 6),
        "activity_source": "explicit plan seed activity" if per_seed is not None else "explicit plan total activity",
        "activity_status": "explicit",
    }


def resolve_report_facts(memory: Any, config: Optional[Mapping] = None, *,
                         evaluation_basis: str = "current") -> Dict[str, Any]:
    """Resolve numeric and descriptive planning facts for report consumers.

    No clinical value is invented here. Activity is only populated when the
    plan explicitly records a source strength; a seed count alone cannot
    determine total activity. Historical callers supply their saved-plan memory
    and evaluation_basis="historical" to retain that plan's prescription.
    """
    stored_config = _retrieve(memory, "plan_config", {}) or {}
    base_config = dict(config) if isinstance(config, Mapping) else {}
    plan_config = {**base_config, **(dict(stored_config) if isinstance(stored_config, Mapping) else {})}
    if evaluation_basis not in {"current", "historical"}:
        raise ValueError("Report evaluation basis must be current or historical")
    saved_evaluation = _retrieve(memory, "current_dose_evaluation_config", {})
    historical_evaluation = dict(saved_evaluation) if isinstance(saved_evaluation, Mapping) and saved_evaluation else plan_config
    evaluation_config = historical_evaluation
    owned_config = {}
    if evaluation_basis == "current":
        from web.planning_config import current_evaluation_config
        evaluation_config = current_evaluation_config(
            lambda key: plan_config if key == "plan_config" else _retrieve(memory, key))
        owned_config = _retrieve(memory, "timepoint_planning_config", {}) or {}
        if not isinstance(owned_config, Mapping):
            owned_config = {}
    dose = _retrieve(memory, "dose_metrics", {}) or _retrieve(memory, "metrics", {}) or {}
    if evaluation_basis == "current":
        from web.planning_config import evaluation_inputs_current
        if not evaluation_inputs_current(lambda key: _retrieve(memory, key)):
            dose = {}
    source_components = _retrieve(memory,'dose_components',None)
    status = _retrieve(memory,'manual_artifact_status',{}) or _retrieve(memory,'artifact_status',{})
    if isinstance(status,Mapping) and any(resource_is_stale(status.get(key)) for key in ('dose','dvh','quality_check')):
        dose = {}
    if isinstance(source_components,Mapping):
        total = source_components.get('total')
        if not isinstance(total,Mapping) or total.get('status') == 'stale' or total.get('dose_status') == 'stale':
            dose = {}
    if not isinstance(dose, Mapping):
        dose = {}
    if isinstance(dose.get("metrics"), Mapping):
        dose = dict(dose.get("metrics") or {})
    else:
        dose = dict(dose)
    sources = [
        _retrieve(memory, "total_seeds"),
        _retrieve(memory, "num_trajectories"),
        _retrieve(memory, "dwell_position_count"),
        plan_config,
        dose,
    ]

    total_seeds = _source_count(_retrieve(memory, "total_seeds"))
    if total_seeds is None:
        total_seeds = _source_count(_first_value(sources, ("total_seeds", "seed_count", "num_seeds")))
    if total_seeds is None:
        seed_list = _retrieve(memory, "seeds")
        if isinstance(seed_list, list):
            total_seeds = len(seed_list)

    num_trajectories = _source_count(_retrieve(memory, "num_trajectories"))
    if num_trajectories is None:
        num_trajectories = _source_count(_first_value(sources, ("num_trajectories", "trajectory_count", "needle_count", "num_needles")))
    if num_trajectories is None:
        trajectory_list = _retrieve(memory, "trajectories")
        if trajectory_list is None:trajectory_list=_retrieve(memory,'needles')
        if isinstance(trajectory_list, list):
            num_trajectories = len(trajectory_list)

    dose_scale = (
        _number(dose.get("dose_scale_gy"), positive=True)
        or _number(_retrieve(memory, "dose_scale_gy"), positive=True)
        or _number(plan_config.get("dose_scale_gy"), positive=True)
    )
    prescription_gy = resolve_prescription_gy(evaluation_config, dose, dose_scale_gy=dose_scale)
    explicit_rx_keys = (
        "in_lowest_dose_gy", "prescription_dose_gy", "prescribed_dose_gy",
        "prescription_gy", "rx_gy", "in_lowest_energy", "prescribed_dose",
    )
    rx_source = ""
    for key in explicit_rx_keys:
        if evaluation_config.get(key) not in (None, ""):
            origin = "plan_config"
            if evaluation_basis == "historical" and historical_evaluation is not plan_config:
                origin = "current_dose_evaluation_config"
            elif (owned_config.get(key) not in (None, "") or
                  key == "in_lowest_dose_gy" and owned_config.get("in_lowest_energy") not in (None, "")):
                origin = "timepoint_planning_config"
            source_key = "in_lowest_energy" if (origin == "timepoint_planning_config" and
                owned_config.get(key) in (None, "") and key == "in_lowest_dose_gy") else key
            rx_source = f"{origin}.{source_key}"
            break
        if dose.get(key) not in (None, ""):
            rx_source = f"dose_metrics.{key}"
            break
    if not rx_source:
        rx_source = "default planning prescription (120 Gy; clinician verification required)"

    activity = _explicit_activity([plan_config, dose, _retrieve(memory, "seed_info", {})], total_seeds)
    tumor_type = (
        owned_config.get("tumor_type")
        or (historical_evaluation.get("tumor_type") if evaluation_basis == "historical" else None)
        or _retrieve(memory, "tumor_type_used")
        or _retrieve(memory, "tumor_type")
        or _retrieve(memory, "cancer_type")
        or _retrieve(memory, "organ")
        or _first_value([plan_config, dose], ("tumor_type", "cancer_type", "organ"))
        or ""
    )
    technique = _first_value([plan_config, dose], ("technique", "treatment_technique")) or ""
    radionuclide = _first_value([plan_config, dose], ("radionuclide", "isotope", "seed_model")) or ""
    dwell_count = _integer(
        _retrieve(memory, "dwell_position_count")
        or _first_value([plan_config, dose], ("dwell_position_count", "dwell_positions", "num_dwell_positions")),
        positive=True,
    )
    oar_metrics = _retrieve(memory, "oar_metrics") or dose.get("oar_metrics") or {}
    if source_components is not None and not dose:
        oar_metrics = {}
    oar_count = _integer(_first_value([plan_config, dose], ("oar_count", "num_oars")), positive=True)
    if oar_count is None and isinstance(oar_metrics, Mapping):
        oar_count = len(oar_metrics) or None

    return {
        "plan_config": plan_config,
        "evaluation_basis": evaluation_basis,
        "dose": dose,
        "total_seeds": total_seeds,
        "num_trajectories": num_trajectories,
        "dwell_position_count": dwell_count,
        "prescription_gy": float(prescription_gy) if prescription_gy is not None else None,
        "prescription_source": rx_source,
        "prescription_status": "explicit" if rx_source.startswith(("plan_config.", "dose_metrics.", "timepoint_planning_config.", "current_dose_evaluation_config.")) else "resolved_default",
        **activity,
        "tumor_type": str(tumor_type),
        "technique": str(technique),
        "radionuclide": str(radionuclide),
        "oar_count": oar_count,
        'source_components': report_source_components(memory),
    }


def report_source_components(memory):
    """Bounded source-separated report provenance, never attach dose arrays."""
    bundle = _retrieve(memory,'dose_components',None)
    if not isinstance(bundle,Mapping):
        return None
    fingerprints = (_retrieve(memory,'timepoint_resource_state',{}) or {}).get('fingerprints',{})
    planned_stale = any(
        isinstance(status, Mapping) and any(resource_is_stale(status.get(key))
            for key in ('dose', 'dvh', 'quality_check'))
        for status in (_retrieve(memory, 'manual_artifact_status', {}),
                       _retrieve(memory, 'artifact_status', {})))
    result = {'evaluation_source_set':'total','dose_basis':'projected_total_source_dose_not_elapsed_delivered_dose',
        'clinical_use_ready':False,'components':{}}
    for name in ('implanted','planned','total'):
        record = bundle.get(name)
        valid = isinstance(record,Mapping)
        stale = not valid or record.get('status') == 'stale' or record.get('dose_status') == 'stale'
        if name in ('planned', 'total') and planned_stale:
            stale = True
        if valid and (record.get('dose_units') != 'physical_gy'
                or record.get('dependency_fingerprint') != fingerprints.get(name+'_dose')):
            stale = True
        count = record.get('source_count') if valid else None
        result['components'][name] = {'status':'stale' if stale else 'current',
            'source_count':count if type(count) is int and count >= 0 else None,
            'units':'Gy' if valid and record.get('dose_units') == 'physical_gy' else None,
            'dose_sha256':record.get('dose_sha256') if valid else None}
    return result


def format_source_components_markdown(components, language='en'):
    if not isinstance(components,Mapping):
        return ''
    zh = str(language).startswith('zh')
    rows = ['## 剂量来源与粒子构成' if zh else '## Dose sources and source counts',
        '| 剂量来源 | 粒子数 | 数据状态 |' if zh else '| Dose source | Source count | Data status |',
        '|---|---:|---|']
    for key,label in [('implanted','体内实际粒子' if zh else 'Observed implanted sources'),
            ('planned','新增规划粒子' if zh else 'Supplemental planned sources'),('total','总剂量' if zh else 'Total dose')]:
        item = components.get('components',{}).get(key,{})
        count = item.get('source_count')
        state = ('当前' if zh else 'Current') if item.get('status') == 'current' else ('已失效，须重算' if zh else 'Stale; recomputation required')
        rows.append(f"| {label} | {count if type(count) is int else ('未记录' if zh else 'Not recorded')} | {state} |")
    rows += ['', '总剂量为体内粒子剂量与新增规划粒子剂量之和；DVH 和规划评价仅使用当前总剂量。此处为模型预测的完整源剂量，并非按时间累计的已递送剂量，且不构成临床批准。' if zh else
        'Total dose is implanted-source dose plus supplemental-source dose. DVH and plan quality use the current total only. This is projected full-source dose, not elapsed delivered dose, and does not constitute clinical approval.']
    return '\n'.join(rows)
