"""Small, authoritative contracts for the Input panel (no model execution)."""
from collections.abc import Mapping
import copy
import numpy as np


def workflow_state(memory):
    """Completion comes from saved products, never a clicked button."""
    def present(key):
        value = memory.retrieve(key)
        if isinstance(value, np.ndarray):
            return value.size > 0 and bool(np.any(value > 0) if key in ('ctv_binary_array', 'ctv_array', 'oar_array') else np.all(np.isfinite(value)))
        if isinstance(value, (Mapping, list, tuple)):
            return bool(value)
        return value is not None
    status = memory.retrieve('manual_artifact_status') or {}
    if not isinstance(status, Mapping):
        status = {}
    outdated = {'stale', 'expired', 'pending', 'running', 'failed', 'not_generated'}
    dose_current = not bool(memory.retrieve('manual_geometry_only')) and str(status.get('dose') or '').lower() not in outdated
    dvh_current = dose_current and str(status.get('dvh') or '').lower() not in outdated
    return {
        'ct_loaded': present('ct_image') or present('ct_data'),
        'ctv_segmentation': present('ctv_binary_array') or present('ctv_array'),
        'oar_segmentation': present('oar_array'),
        'trajectory_init': present('trajectories'),
        'trajectory_refine': present('refined_trajectories'),
        'seed_planning': present('seed_plan_serialized') or present('seed_plan'),
        'dose_calc': dose_current and (present('dose_distribution_gy') or present('dose_distribution') or present('dose_distribution_physical_gy')),
        'dose_eval': dvh_current and present('dose_metrics'),
    }


def validated_config(current, patch):
    """Validate the complete candidate before replacing the live config.

    Reuse the planner's supported-parameter validator, not a second set of
    clinical limits. Display/segmentation settings are validated separately.
    """
    from plans.config import setting
    from tool_factory.seed_plan.planning_pipeline import _apply_planning_overrides, normalize_planning_mode
    from plans.dose_pre.model_loader import planning_dose_value_to_gy
    if not isinstance(patch, Mapping):
        raise ValueError('Configuration must be a JSON object')
    candidate = copy.deepcopy(current or {})
    candidate.update(copy.deepcopy(dict(patch)))
    for legacy, physical in (('in_lowest_energy', 'in_lowest_dose_gy'), ('out_highest_energy', 'out_highest_dose_gy')):
        if physical in patch:
            value = float(patch[physical])
        elif legacy in patch:
            value = planning_dose_value_to_gy(patch[legacy], value_unit=patch.get('dose_value_unit') or 'gy')
        else:
            continue
        if not np.isfinite(value) or value < 0:
            raise ValueError(f'{physical} must be finite and non-negative')
        candidate[legacy] = candidate[physical] = value
    candidate['dose_value_unit'] = 'gy'
    candidate['mode'] = normalize_planning_mode(candidate.get('mode'))
    _apply_planning_overrides(setting(), candidate)
    direction = candidate.get('reference_direc')
    if direction is not None and direction != 'auto' and direction != 'auto_detect':
        vector = np.asarray(direction, dtype=float)
        if vector.shape != (3,) or not np.all(np.isfinite(vector)) or np.linalg.norm(vector) == 0:
            raise ValueError('reference_direc must be a finite non-zero 3-vector or auto')
    return candidate


def reset_current_plan(agent):
    """Create an empty draft; preserve inputs, conversation and plan history.

    A new identity prevents restore_active_planning_aliases from resurrecting
    the outgoing plan after a restart. Canonical history handles the snapshot.
    """
    from web.planning_runs import begin_planning_run, mark_planning_run, publish_planning_run
    from web.structure_service import _batch_memory_update
    memory = agent.memory
    with memory._lock:
        planning_id = begin_planning_run(agent, step='reset', force_new=True)
        _batch_memory_update(memory, {'planning_version': int(memory.retrieve('planning_version', 0) or 0) + 1},
            removals=('seeds', 'needles', 'plan_score', 'planning_fingerprint', 'entry_boundary_faces',
                'resampled_ctv', 'resampled_oar', 'resampled_ct', 'manual_step_outputs', 'quality_check', 'report'))
        mark_planning_run(agent, planning_id, 'draft')
        publish_planning_run(agent, status='draft')
    return workflow_state(memory)
