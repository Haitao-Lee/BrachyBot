"""Invalidate current numerical authority after changed confirmed source inputs.

Historical plans and printed guides are retained; source settings are not a
display edit. No inference, planning, deletion, or report generation occurs.
"""
import copy


def source_profile_invalidation(results):
    keys = ('dose_distribution', 'dose_distribution_gy', 'dose_distribution_physical_gy',
            'dose_distribution_current_normalized', 'algorithm_plan_dose_distribution',
            'algorithm_plan_dose_distribution_gy', 'algorithm_plan_dose_distribution_current_normalized',
            'additional_dose_distribution', 'dose_metrics', 'algorithm_plan_dose_metrics',
            'algorithm_plan_dvh_data', 'metrics', 'dvh_data', 'plan_score', 'total_dose_evaluation',
            'continuation_baseline', 'continuation_baseline_record',
            'continuation_baseline_dependency_fingerprint', 'continuation_inference_binding_sha256',
            'continuation_evaluation', 'continuation_search_record', 'dose_recompute_provenance',
            'report_data', 'report_result', 'report_path', 'report_pdf_path', 'report_html_path',
            'report_pdf', 'report_html')
    if not any(results.get(key) is not None for key in keys +
               ('dose_components', 'implanted_dose_record', 'manual_seeds', 'seed_plan', 'seed_plan_serialized')):
        return {}
    updates = {key: None for key in keys if key in results}
    components = copy.deepcopy(results.get('dose_components'))
    if isinstance(components, dict):
        for record in components.values():
            if isinstance(record, dict):
                record.update(status='stale', stale_reason='source_settings_changed')
        updates['dose_components'] = components
    observed = copy.deepcopy(results.get('implanted_dose_record'))
    if isinstance(observed, dict):
        observed.update(dose_status='stale', clinical_use_ready=False, stale_reason='source_settings_changed')
        updates['implanted_dose_record'] = observed
    for key in ('manual_artifact_status', 'artifact_status'):
        status = copy.deepcopy(results.get(key) or {})
        status.update(dose='stale', dvh='stale', report='stale', quality_check='stale',
                      reason='source settings changed')
        updates[key] = status
    runs = results.get('planning_runs')
    if isinstance(runs, list):
        updates['planning_runs'] = [{**row, 'clinical_inputs_current': False,
            'has_dose': False, 'has_current_dose': False, 'has_dvh': False,
            'has_metrics': False, 'metrics_summary': {},
            'artifact_status': {**(row.get('artifact_status') or {}),
                'dose': 'stale', 'dvh': 'stale', 'report': 'stale', 'quality_check': 'stale'}}
            if isinstance(row, dict) else row for row in runs]
    updates.update(planning_completed=False, manual_geometry_only=True,
                   report_status='stale', quality_check_status='stale')
    return updates
