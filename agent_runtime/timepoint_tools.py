"""Owned adapters for established tools, using one detached clinical memory.

This file binds inputs, not algorithms. It never runs a root/global executor,
creates clinical thresholds, borrows a preoperative dose, or grants mutation.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from web.timepoints import TimepointError

_EXECUTING_AGENT = ContextVar("timepoint_owned_tool_agent", default=None)


def owned_execution_active(agent):
    return _EXECUTING_AGENT.get() is agent


@contextmanager
def owned_tool_execution(agent):
    token = _EXECUTING_AGENT.set(agent)
    try:
        yield
    finally:
        _EXECUTING_AGENT.reset(token)


# These are runtime inputs, removed from provider-facing schemas. Exact paths
# for registered images/masks remain selectors and are separately validated.
OWNED_INPUT_FIELDS = {
    "ctv_segmentation": {"image", "ct_data"},
    "oar_segmentation": {"image", "ct_data"},
    "biomedparse_segmentation": {"image", "ct_data"},
    "trajectory_planning": {"dose_image", "radiation_volume"},
    "seed_planning": {"dose_image", "radiation_volume", "trajectories"},
    "seed_planning_rule_based": {"dose_image", "radiation_volume", "trajectories"},
    "seed_planning_rl": {"dose_image", "radiation_volume", "trajectories"},
    "dose_engine": {"seeds", "dose_image"},
    "dose_recompute": {"expected_observation_revision_id"},
    "dose_evaluation": {"dose_array", "ctv_mask", "oar_mask"},
    "safety_validator": {"plan", "tumor_type"},
    "report_generator": {"plan_data", "patient_info"},
    "dicom_rt_exporter": {"ct_image", "structures", "dose_array", "dose_units", "dose_scale_gy", "seed_plan", "seeds"},
    "plan_quality_scorer": {"v100", "v150", "v200", "d90", "oar_metrics", "prescribed_dose", "organ",
                            "target_constraints", "oar_constraints"},
    "oar_constraint_checker": {"oar_metrics", "tumor_type", "organ", "custom_constraints", "prescribed_dose"},
    "plan_refinement": {"current_plan", "dose_distribution", "ctv_mask", "oar_mask", "_candidate_only", "_dose_units"},
    "plan_comparator": {"plans", "plan_a", "plan_b"},
}


def _first(memory, *names):
    for name in names:
        value = memory.retrieve(name)
        if value is not None:
            return value
    return None


def _physical_inputs(memory):
    from plans.dose_pre.evaluation_inputs import resolve_dose_evaluation_inputs
    resolved = resolve_dose_evaluation_inputs(memory.retrieve)
    if resolved.get("resolution_error"):
        raise TimepointError(resolved["resolution_error"])
    return dict(resolved.get("params") or {})


def _measured_metric(values, *aliases):
    """Explicit canonical absence wins over legacy casing; zero is measured."""
    for key in aliases:
        if key in values:
            value = values[key]
            if isinstance(value, bool):
                return None
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                return None
            return number if math.isfinite(number) else None
    return None


def _quality_context(memory):
    from web.planning_runs import current_planning_context, planning_run_snapshot
    plan = current_planning_context(memory)
    metrics = dict(plan.get("metrics") or {})
    if metrics.get("source_set") not in (None, "", "total"):
        return {**plan, "metrics": {}}
    identifier = plan.get("planning_id")
    # A normalized casing alias must not undo a producer's explicit missing
    # canonical value. Inspect only this context's selected sources as a veto,
    # never as a fallback supplying values to an empty/stale context.
    if not identifier or memory.retrieve("planning_run_id") == identifier:
        retrieve = memory.retrieve
    else:
        retrieve = planning_run_snapshot(memory, identifier).get
    for field in ("v100", "v150", "v200", "d90", "plan_score"):
        for key in ("dose_metrics", "algorithm_plan_dose_metrics", "metrics"):
            source = retrieve(key)
            if isinstance(source, Mapping) and field in source:
                if _measured_metric(source, field) is None:
                    metrics.pop(field, None)
                    metrics.pop(field.upper(), None)
                break
    return {**plan, "metrics": metrics}


def _require_oar_measurements(metrics, tumor_type, custom_constraints, prescribed_dose=None):
    """The established checker defaults absent values to zero: block that path."""
    from tool_factory.plan_quality.oar_constraint_checker import OARConstraintCheckerTool, _norm
    checker = OARConstraintCheckerTool()
    constraints, _ = checker._build_constraints(_norm(tumor_type), custom_constraints)
    for name, row in metrics.items():
        if not isinstance(row, Mapping):
            raise TimepointError("Current OAR measurements are unavailable for " + str(name))
        selected = checker._match_constraints(_norm(name), constraints)
        checks = (
            (selected.get("max_dose") if 'max_dose' in selected else selected.get("dmax"), ("max_dose", "dmax")),
            (selected.get("d2cc"), ("d2cc", "D2cc")),
            (selected.get("d1cc"), ("d1cc", "D1cc")),
            (selected.get("mean_dose") if 'mean_dose' in selected else selected.get("dmean_max"), ("mean_dose", "dmean", "Dmean")),
        )
        relative = selected.get('max_dose_pct') is not None
        if relative:
            measured_ratio=_measured_metric(row,'max_dose_pct','dmax_pct')
            measured_absolute=_measured_metric(row,'max_dose','dmax','Dmax')
            if measured_ratio is None and not (measured_absolute is not None
                    and isinstance(prescribed_dose,(int,float)) and math.isfinite(prescribed_dose)
                    and prescribed_dose > 0):
                raise TimepointError("Current relative OAR measurement and prescription are unavailable for " + str(name))
        if selected and not relative and not any(limit is not None for limit, _ in checks):
            raise TimepointError("The OAR checker cannot assess the saved constraint units for " + str(name))
        for limit, aliases in checks:
            if limit is not None and _measured_metric(row, *aliases) is None:
                raise TimepointError("Current OAR measurement " + aliases[0] + " is unavailable for " + str(name))


def owned_tool_arguments(agent, name, params):
    runtime = getattr(agent, "_workspace_scoped_chat_runtime", None)
    if runtime is None:
        return params
    runtime.assert_current()
    args = dict(params)
    from agent_runtime.workspace_readiness import ensure_workspace_ready
    ensure_workspace_ready(agent, name, args)
    injected = OWNED_INPUT_FIELDS.get(name, ())
    for key in injected:
        args.pop(key, None)
    # No provider can replace the tool's in-process Agent binding.
    args.pop("agent", None)
    args.pop("_agent", None)
    memory = agent.memory
    image = memory.retrieve("ct_image")
    if name in {"ctv_segmentation", "oar_segmentation", "biomedparse_segmentation"}:
        if image is not None:
            args["image"] = image
    elif name in {"seed_planning", "seed_planning_rule_based", "seed_planning_rl", "trajectory_planning"}:
        if image is not None:
            args["dose_image"] = image
        if memory.retrieve("radiation_volume") is not None:
            args["radiation_volume"] = memory.retrieve("radiation_volume")
        if name != "trajectory_planning" and memory.retrieve("trajectories") is not None:
            args["trajectories"] = memory.retrieve("trajectories")
    elif name == "dose_engine":
        if image is not None:
            args["dose_image"] = image
        args["seeds"] = _first(memory, "seed_positions", "seed_plan_serialized", "seed_plan")
    elif name == "dose_evaluation":
        args.update(_physical_inputs(memory))
    elif name == "dose_recompute" and args.get("source_set") != "planned":
        # A provider's remembered revision is not an input dependency fence.
        # Bind the current request's owned observation head; the dose producer
        # still checks it before/after inference and the runtime retains its
        # clinical/lifecycle CAS. An explicitly human-named precondition is
        # kept, so this never silently retries an intentionally old revision.
        catalog = memory.retrieve("implanted_seed_reconstruction") or {}
        entry = (catalog.get("by_timepoint") or {}).get(runtime.scope.timepoint_id) if isinstance(catalog, Mapping) else None
        if entry is not None:
            identities = entry.get("scope") or {}
            if any(identities.get(key) != value for key, value in (
                    ("owner_id", runtime.scope.owner_id), ("session_id", runtime.scope.session_id),
                    ("timepoint_id", runtime.scope.timepoint_id))):
                raise TimepointError("The observation head does not belong to this captured workspace")
            head = ((entry.get("current") or {}).get("reconstruction") or {}).get("revision_id")
            if not isinstance(head, str) or not head:
                raise TimepointError("The current owned observation revision is unavailable")
            supplied = params.get("expected_observation_revision_id")
            human = str(getattr(getattr(agent, "_turn_local", None), "human_message", "") or "")
            args["expected_observation_revision_id"] = supplied if (
                isinstance(supplied, str) and supplied and supplied in human) else head
    elif name in {"report_generator", "safety_validator", "plan_quality_scorer", "oar_constraint_checker"}:
        plan = _quality_context(memory)
        # Empty current context is authoritative. Never revive a raw alias.
        metrics = plan.get("metrics") or {}
        if not isinstance(metrics, Mapping):
            metrics = {}
        if name == "report_generator":
            if args.get("action") == "summary" and any(
                    _measured_metric(metrics, field) is None for field in ("plan_score", "v100")):
                raise TimepointError("Current score and coverage are required for a report summary")
            # Use the existing registered report preparation contract.
            args["plan_data"] = copy.deepcopy(plan)
            args["plan_data"].setdefault("metrics", copy.deepcopy(dict(metrics)))
            from tool_factory.report_facts import resolve_report_facts, report_source_components
            from tool_factory.report_context import build_prescription_rationale
            facts = resolve_report_facts(memory)
            args["plan_data"].update(prescription_gy=facts["prescription_gy"],
                prescription_rationale=build_prescription_rationale(memory), evaluation_basis="current")
            args['plan_data']['source_components'] = report_source_components(memory)
            args["patient_info"] = copy.deepcopy(memory.patient_data)
        elif name == "safety_validator":
            fields = {'check_coverage': ('v100','d90'), 'check_hotspots': ('v150','v200'),
                'check_dose': ()}.get(args.get('action'), ('v100','v150','v200','d90'))
            if not metrics or any(_measured_metric(metrics, key, key.upper()) is None for key in fields):
                raise TimepointError("Current total-dose measurements are required for safety review")
            from web.planning_config import current_evaluation_config
            from plans.dose_pre.model_loader import resolve_prescription_gy
            evaluation = current_evaluation_config(memory.retrieve)
            site = evaluation.get('tumor_type') or plan.get('tumor_type') or ''
            args['tumor_type'] = site
            args['plan'] = {**plan, 'metrics': copy.deepcopy(metrics), 'tumor_type': site,
                'current_dose_evaluation_config': evaluation,
                'prescription_gy': resolve_prescription_gy(evaluation, dict(metrics)),
                'current_oar_constraints': copy.deepcopy(evaluation.get('oar_constraints') or {})}
            if args.get('action') in {'validate','pre_export','check_dose'}:
                _require_oar_measurements(metrics.get('oar_metrics') or {}, site,
                    evaluation.get('oar_constraints') or {}, args['plan']['prescription_gy'])
        elif name == "oar_constraint_checker":
            if not metrics.get("oar_metrics"):
                raise TimepointError("Current total-dose OAR measurements are unavailable")
            from web.planning_config import current_evaluation_config
            evaluation = current_evaluation_config(memory.retrieve)
            args["oar_metrics"] = copy.deepcopy(metrics.get("oar_metrics") or {})
            args["tumor_type"] = evaluation.get("tumor_type") or plan.get("tumor_type") or ""
            args["custom_constraints"] = copy.deepcopy(evaluation.get("oar_constraints") or {})
            from plans.dose_pre.model_loader import resolve_prescription_gy
            args['prescribed_dose']=resolve_prescription_gy(evaluation,dict(metrics))
            _require_oar_measurements(args["oar_metrics"], args["tumor_type"], args["custom_constraints"],args['prescribed_dose'])
        else:
            for field in ("v100", "v150", "v200", "d90"):
                value = _measured_metric(metrics, field, field.upper())
                if value is None:
                    raise TimepointError("Current total-dose measurement " + field + " is unavailable")
                args[field] = value
            args["oar_metrics"] = copy.deepcopy(metrics.get("oar_metrics") or {})
            from web.planning_config import current_evaluation_config
            from plans.dose_pre.model_loader import resolve_prescription_gy
            evaluation = current_evaluation_config(memory.retrieve)
            args["prescribed_dose"] = resolve_prescription_gy(evaluation, dict(metrics))
            args["organ"] = evaluation.get("tumor_type") or plan.get("tumor_type") or ""
            args["oar_constraints"] = copy.deepcopy(evaluation.get("oar_constraints") or {})
            if isinstance(evaluation.get("target_constraints"), Mapping):
                args["target_constraints"] = copy.deepcopy(evaluation["target_constraints"])
    elif name == "plan_refinement":
        physical = _physical_inputs(memory)
        prescription = physical.get("prescribed_dose")
        if "prescribed_dose" in args:
            requested = args["prescribed_dose"]
            try:
                same_prescription = (not isinstance(requested, bool)
                    and math.isfinite(float(requested)) and float(requested) == float(prescription))
            except (TypeError, ValueError, OverflowError):
                same_prescription = False
            if not same_prescription:
                raise TimepointError("A refinement proposal cannot override the current prescription; update the owned evaluation configuration separately")
        # A cold voxel is not an admitted needle/seed. The legacy proposal
        # format has neither a physical grid nor a validated bore association.
        # Owned calls therefore expose advisory locations only; preparation,
        # path admission and source-dose inference remain separate operations.
        args["_candidate_only"] = True
        args["_dose_units"] = "physical_gy"
        args.update(current_plan=copy.deepcopy(_first(memory, "seed_plan_serialized", "seed_plan") or []),
                    dose_distribution=physical["dose_array"], ctv_mask=physical["ctv_mask"])
        if "oar_mask" in physical:
            args["oar_mask"] = physical["oar_mask"]
        if prescription is not None:
            args["prescribed_dose"] = prescription
    elif name == "dicom_rt_exporter":
        from utils.tool_security import output_directory
        from web.structure_service import build_effective_structures
        structures = build_effective_structures(memory)
        physical = _physical_inputs(memory)
        args.update(ct_image=image, dose_array=physical["dose_array"], dose_units="physical_gy",
                    output_dir=str(output_directory("dicom_rt", ".")),
                    seed_plan=copy.deepcopy(_first(memory, "seed_plan_serialized", "seed_plan") or []))
        args["structures"] = {row["name"]: row["mask"] for row in structures.structures
                              if isinstance(row, Mapping) and row.get("mask") is not None}
        if not args["structures"]:
            # The effective structure service's canonical CTV/OAR arrays are
            # still owned by this target; retain them when no named rows exist.
            args["structures"] = {"CTV": physical["ctv_mask"]}
            if physical.get("oar_mask") is not None:
                import numpy as np
                labels = np.unique(physical["oar_mask"])
                names = memory.retrieve("organ_names") or {}
                for label in labels:
                    if label > 0:
                        args["structures"][str(names.get(int(label), names.get(str(int(label)), f"OAR_{label}")))] = physical["oar_mask"] == label
    elif name == "plan_comparator":
        from web.planning_runs import current_planning_context, planning_run_snapshot
        identifiers = params.get("planning_ids")
        if identifiers is None:
            plans = [current_planning_context(memory)]
        elif not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 16:
            raise TimepointError("Plan comparison requires 1 to 16 owned planning IDs")
        else:
            plans = [planning_run_snapshot(memory, identifier) for identifier in identifiers]
            if any(not plan for plan in plans):
                raise TimepointError("A requested Planning is absent from this timepoint")
        args.pop("planning_ids", None)
        args["plans"] = plans
        if len(plans) == 2:
            args.update(plan_a=plans[0], plan_b=plans[1])
    if name == "query_metrics" and args.get("metric_type", "all_metrics") in {
            "dose_metrics", "oar_dose_metrics", "plan_score", "all_metrics"}:
        from web.planning_runs import current_planning_context
        if set(_quality_context(memory)["metrics"]) != set(current_planning_context(memory).get("metrics", {})):
            raise TimepointError("Current quality contains an explicitly unavailable measurement")
    if name == "report_auto_fill" and args.get("scope", "all") != "patient":
        # This legacy producer falls back to raw dose_metrics when report facts
        # deliberately suppress current QA. Refuse that route before execution.
        if not _quality_context(memory).get("metrics"):
            raise TimepointError("Current total-dose quality is required before report auto-fill")
    if name in {"planning_pipeline", "dose_recompute", "report_auto_fill", "ui_content", "surgical_guide", "seed_segmentation", "plan_refinement"}:
        args["_agent"] = agent
    if name == "ui_inspector":
        args["agent"] = agent
    return args


DIRECT_PLANNING_STEPS = {
    "trajectory_init": ("trajectory_init",),
    "trajectory_refine": ("trajectory_refine",),
    "trajectory_planning": ("trajectory_init", "trajectory_refine"),
    "seed_planning": ("seed_planning",),
    "seed_planning_rule_based": ("seed_planning",),
    "seed_planning_rl": ("seed_planning",),
}


def execute_owned_planning_steps(agent, name, params, **callbacks):
    """Delegate a direct operation to its canonical grid/baseline step only.

    This consumes the caller's existing exact action grant. It does not grant
    or invoke the full pipeline, generate masks, dose, guides or reports. The
    pipeline step owns planning-grid resampling and immutable prior implants.
    """
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
    from tool_factory import ToolResult
    from web.timepoint_http import HttpTimepointBinding, bound_request
    runtime = getattr(agent, "_workspace_scoped_chat_runtime", None)
    if runtime is None or name not in DIRECT_PLANNING_STEPS:
        return None
    allowed = {"timepoint_id", "ref_direc", "planning_params", "seed_info", "mode", "max_iterations",
               "refine", "sampling_step", "angle_step", "obstacle_value", "target_value"}
    # Clinical arrays and continuation objects were removed by owned adapter;
    # supplied action parameters must have a real canonical mapping.
    from tool_factory.seed_plan.planning_pipeline import _PLANNING_PARAM_KEYS
    allowed |= set(_PLANNING_PARAM_KEYS) | set(OWNED_INPUT_FIELDS.get(name, ()))
    unknown = set(params) - allowed
    if unknown:
        raise TimepointError("Direct planning parameters have no canonical step mapping: " + ", ".join(sorted(unknown)))
    args = {key: value for key, value in params.items() if key in {"ref_direc", "planning_params", "seed_info", "mode"}}
    overrides = dict(args.get("planning_params") or {})
    for key in _PLANNING_PARAM_KEYS:
        if key in params:
            overrides[key] = params[key]
    if overrides:
        args["planning_params"] = overrides
    if name == "seed_planning_rule_based":
        args["mode"] = "rule_based"
    elif name == "seed_planning_rl":
        args["mode"] = "rl"
    steps = DIRECT_PLANNING_STEPS[name]
    if name == "trajectory_planning" and params.get("refine") is False:
        steps = steps[:1]
    result = None
    binding = HttpTimepointBinding(runtime.scope.owner_id, runtime.scope.session_id, runtime.scope.timepoint_id)
    with bound_request(binding):
        for step in steps:
            result = PlanningPipelineTool().execute(_agent=agent, step=step, **args,
                **{key: value for key, value in callbacks.items() if value is not None})
            if not result.success:
                break
    result = result or ToolResult(False, error="No requested planning step was executed")
    result.metadata = {**result.metadata, "requested_tool": name,
        "delegated_tool": "planning_pipeline", "requested_steps": list(steps),
        "full_pipeline_executed": False}
    agent.memory.log_tool_call(name, params, result)
    return result
