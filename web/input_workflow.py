"""Small, authoritative contracts for the Input panel (no model execution)."""
from collections.abc import Mapping
import copy
import numpy as np

from web.timepoints import TimepointError


# Input settings are owned by the acquisition, not by a historical plan or the
# Session control Agent. Never persist provider credentials/workspace paths here.
PLANNING_CONFIG_KEYS = (
    'seed_info', 'radiation_array_params', 'reference_direc', 'ref_direc_auto',
    'reference_direc_mode', 'tumor_type', 'dose_value_unit', 'in_lowest_energy',
    'out_highest_energy', 'in_lowest_dose_gy', 'out_highest_dose_gy', 'DVH_rate',
    'max_iter', 'rf_params', 'distance_filter', 'direc_resolution', 'dl_params',
    'iter_rate', 'replan_rate', 'mode',
)


def planning_config_values(config):
    """An independently mutable, allowlisted Input configuration."""
    return {key: copy.deepcopy(config[key]) for key in PLANNING_CONFIG_KEYS
            if isinstance(config, Mapping) and key in config}


def restore_owned_planning_config(base, saved_agent):
    """Use the captured snapshot, including legacy migration, never a sibling.

    Schema-1 snapshots saved config on the Agent itself. New snapshots store the
    Input settings in clinical memory so normal CAS publishing/bundle recovery
    preserves them even when a detached request has ended.
    """
    restored = copy.deepcopy(base or {})
    restored.update(planning_config_values((saved_agent or {}).get('config')))
    results = (saved_agent or {}).get('planning_results') or {}
    restored.update(planning_config_values(results.get('timepoint_planning_config')))
    return restored


class PlanningReferenceInputError(TimepointError):
    code = 'planning_reference_input_mismatch'


def resolve_owned_reference_path(agent, value, image_id=None):
    """Translate only aliases of this request's registered planning image.

    Public collection paths are workspace-relative. They are not filenames
    relative to the server checkout, and a displayed sibling image is not a
    substitute for the explicitly selected numerical reference.
    """
    from pathlib import Path
    context=getattr(agent,'_workspace_timepoint_context',None)
    if context is None:
        return value
    raw=getattr(agent._workspace_store,'raw',agent._workspace_store)
    from web.timepoint_images import TimepointImageService
    service=TimepointImageService(raw)
    collection=service.list_images(context.owner_id,context.session_id,context.target.timepoint_id)
    reference=collection['planning_reference_image_id']
    if not reference:
        if not context.target.legacy_default:
            raise PlanningReferenceInputError('Select an owned planning reference before executing clinical work')
        return value
    if image_id is not None and image_id != reference:
        raise PlanningReferenceInputError('The submitted image is not the owned planning reference')
    row=next(item for item in collection['images'] if item['id']==reference)
    canonical, _ = service.source_file(context.owner_id,context.session_id,context.target.timepoint_id,reference)
    root=raw.workspace_root(context.owner_id,context.session_id)
    aliases={str(canonical), row['url']}
    for key in ('volume_path','source_path','ingest_source_path'):
        path=row.get(key)
        if path:
            aliases.update((str(path),str(root/Path(path))))
    if (not value and image_id==reference) or isinstance(value,str) and value in aliases:
        return str(canonical)
    raise PlanningReferenceInputError('The submitted path is not an alias of the owned planning reference')


def workflow_state(memory):
    """Completion comes from saved products, never a clicked button."""
    def present(key):
        value = memory.retrieve(key)
        if isinstance(value, np.ndarray):
            if key == 'oar_array':
                source=str(memory.retrieve('oar_source') or '').strip().lower()
                return value.size > 0 and bool(np.all(np.isfinite(value))) and (
                    bool(np.any(value>0)) or source not in {'','none','unknown','not_available'})
            return value.size > 0 and bool(np.any(value > 0) if key in ('ctv_binary_array', 'ctv_array') else np.all(np.isfinite(value)))
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
