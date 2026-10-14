"""Current Input intent is separate from immutable historical plan inputs."""
import copy
from collections.abc import Mapping


EVALUATION_KEYS = ('dose_value_unit', 'planning_dose_unit', 'in_lowest_energy',
    'out_highest_energy', 'in_lowest_dose_gy', 'out_highest_dose_gy',
    'prescription_gy', 'prescribed_dose', 'DVH_rate', 'tumor_type', 'oar_constraints')
SEARCH_KEYS = ('seed_info', 'radiation_array_params', 'reference_direc',
    'ref_direc_auto', 'reference_direc_mode', 'max_iter', 'rf_params',
    'distance_filter', 'direc_resolution', 'dl_params', 'iter_rate', 'replan_rate', 'mode')


def current_evaluation_config(retrieve):
    """Current QA only; source/model/calibration stay on their confirmed record.

    Callers evaluating an explicitly historical plan must use its saved config
    instead. Never mutate that config to reflect a newer Input prescription.
    """
    plan = retrieve('plan_config') or {}
    result = copy.deepcopy(dict(plan)) if isinstance(plan, Mapping) else {}
    owned = retrieve('timepoint_planning_config') or {}
    if isinstance(owned, Mapping):
        result.update({key: copy.deepcopy(owned[key]) for key in EVALUATION_KEYS if key in owned})
        # A saved legacy prescription alias must not beat an applied physical Rx.
        if any(key in owned for key in ('in_lowest_dose_gy', 'in_lowest_energy')):
            from plans.dose_pre.model_loader import resolve_prescription_gy
            rx = resolve_prescription_gy(owned)
            result.update(in_lowest_dose_gy=rx, in_lowest_energy=rx,
                          prescription_gy=rx, prescribed_dose=rx, dose_value_unit='gy')
    return result


def planning_settings_content(retrieve):
    plan = retrieve('plan_config') or {}
    owned = retrieve('timepoint_planning_config') or {}
    combined = {**(dict(plan) if isinstance(plan, Mapping) else {}),
                **(dict(owned) if isinstance(owned, Mapping) else {})}
    result = {key: copy.deepcopy(combined.get(key)) for key in SEARCH_KEYS}
    if isinstance(result.get('dl_params'), Mapping):
        # Device/model handles are process runtime, not search policy. CNN
        # content and preprocessing have an independent physical-dose identity.
        result['dl_params'] = {key:value for key,value in result['dl_params'].items()
            if key not in {'device','dose_cal_model','dose_model','dose_model_path'}}
    return result


def evaluation_content(config):
    from plans.dose_pre.model_loader import resolve_prescription_gy, planning_dose_value_to_gy
    value = dict(config or {})
    outside = value.get('out_highest_dose_gy')
    if outside is None and value.get('out_highest_energy') is not None:
        outside = planning_dose_value_to_gy(value['out_highest_energy'],
            value_unit=value.get('dose_value_unit') or value.get('planning_dose_unit') or 'gy')
    return {'prescription_gy':resolve_prescription_gy(value), 'outside_limit_gy':outside,
        'DVH_rate':value.get('DVH_rate', .9), 'tumor_type':value.get('tumor_type') or '',
        'oar_constraints':value.get('oar_constraints') or {}}


def evaluation_inputs_current(retrieve, snapshot=None):
    """Do not revive historical QA after changing the owned Input prescription."""
    if not isinstance(retrieve('timepoint_planning_config'), Mapping):
        return True
    saved = snapshot if isinstance(snapshot, Mapping) else {}
    basis = saved.get('current_dose_evaluation_config') if snapshot is not None else retrieve('current_dose_evaluation_config')
    basis = basis or saved.get('plan_config') or retrieve('plan_config') or {}
    if not basis:
        return True  # No saved quality authority to revive.
    from web.timepoint_resources import fingerprint
    def values(key):
        if key == 'plan_config':
            return basis
        return retrieve(key)
    return fingerprint(evaluation_content(basis)) == fingerprint(evaluation_content(current_evaluation_config(values)))


def stale_evaluation_updates(retrieve):
    values = dict(total_dose_evaluation=None, dose_metrics=None, metrics=None,
        dvh_data=None, quality_check_status='stale', report_status='stale')
    for key in ('manual_artifact_status','artifact_status'):
        status = copy.deepcopy(retrieve(key) or {})
        status.update(dvh='stale',quality_check='stale',report='stale')
        values[key] = status
    return values


def input_config_invalidation(retrieve, previous_config, candidate):
    """Invalidate authority atomically, without discarding unchanged dose.

    Altering next-plan settings does not change confirmed implanted sources or
    move saved future particles. Existing numerical dose is retained as evidence;
    current quality and planning readiness require explicit reevaluation/replan.
    """
    from web.timepoint_resources import fingerprint
    values = {}
    def next_value(key):
        return candidate if key == 'timepoint_planning_config' else retrieve(key)
    before = current_evaluation_config(retrieve)
    after = current_evaluation_config(next_value)
    evaluate_changed = fingerprint(evaluation_content(before)) != fingerprint(evaluation_content(after))
    def settings(config):
        return planning_settings_content(lambda key: config if key == 'timepoint_planning_config' else {})
    search_changed = fingerprint(settings(previous_config)) != fingerprint(settings(candidate))
    present = any(retrieve(key) is not None for key in ('plan_config', 'dose_components',
        'implanted_dose_record', 'dose_metrics', 'seed_plan', 'manual_seeds'))
    if not present or not (evaluate_changed or search_changed):
        return values
    values.update(report_status='stale', planning_completed=False,
        planning_inputs_status='stale', planning_inputs_stale_reason='input_config_changed')
    if evaluate_changed:
        values.update(total_dose_evaluation=None, dose_metrics=None, metrics=None,
            dvh_data=None, quality_check_status='stale')
    for key in ('manual_artifact_status', 'artifact_status'):
        status = copy.deepcopy(retrieve(key) or {})
        status.update(report='stale', planning='stale')
        if evaluate_changed:
            status.update(dvh='stale', quality_check='stale')
        values[key] = status
    for key in ('report_data','report_result','report_path','report_pdf_path','report_html_path',
                'report_pdf','report_html'):
        if retrieve(key) is not None:
            values[key] = None
    return values
