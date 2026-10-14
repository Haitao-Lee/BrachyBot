"""Publish a successful standalone Agent evaluation, not a new dose or plan."""
from collections.abc import Mapping
import copy


def store_agent_dose_evaluation(memory, result):
    if not result.success:
        return False
    meta = result.metadata or {}
    rows = meta.get('metrics') or result.data
    if not isinstance(rows, Mapping) or not isinstance(rows.get('CTV'), Mapping):
        return False
    target = rows['CTV']
    if 'error' in target or not target.get('total_voxels'):
        return False
    from web.planning_config import current_evaluation_config, evaluation_content
    from web.timepoint_resources import fingerprint
    config = current_evaluation_config(memory.retrieve)
    from plans.dose_pre.model_loader import resolve_prescription_gy
    current_rx = resolve_prescription_gy(config, memory.retrieve('dose_metrics') or memory.retrieve('metrics') or {})
    config.update(in_lowest_dose_gy=current_rx, prescription_gy=current_rx, prescribed_dose=current_rx,
                  in_lowest_energy=current_rx, dose_value_unit='gy')
    actual = meta.get('evaluation_basis') or {}
    basis = copy.deepcopy(config)
    if isinstance(actual, Mapping):
        basis.update({key: copy.deepcopy(actual[key]) for key in ('tumor_type', 'oar_constraints') if key in actual})
    rx = meta.get('prescribed_dose')
    if rx is None:
        return False
    basis.update(in_lowest_dose_gy=rx, in_lowest_energy=rx,
        prescription_gy=rx, prescribed_dose=rx, dose_value_unit='gy')
    # Explicit legacy what-if evaluations are valid answers, but must never
    # overwrite current clinical quality with a different Rx/protocol.
    current = fingerprint(evaluation_content(basis)) == fingerprint(evaluation_content(config))
    meta['evaluation_is_current'] = current
    meta['source_set'] = 'total'
    if not current:
        return False
    metrics = {key.lower(): copy.deepcopy(value) for key, value in target.items() if key != 'dvh'}
    dvh = {name: copy.deepcopy(row['dvh']) for name, row in rows.items()
           if isinstance(row, Mapping) and 'dvh' in row}
    metrics.update(source_set='total', dose_value_unit='gy', volume_metric_units='fraction',
        prescribed_dose=rx, prescription_gy=rx, plan_score=meta.get('plan_score'),
        oar_violations=copy.deepcopy(meta.get('oar_violations') or []), dvh_data=dvh,
        oar_metrics={name: {key.lower(): copy.deepcopy(value) for key, value in row.items() if key != 'dvh'}
                     for name, row in rows.items() if name != 'CTV' and isinstance(row, Mapping)})
    scale = memory.retrieve('dose_scale_gy')
    if scale is not None:
        metrics['dose_scale_gy'] = scale
    evaluation = {key: copy.deepcopy(value) for key, value in meta.items()
                  if key in ('metrics', 'prescribed_dose', 'plan_score', 'oar_violations', 'voxel_volume_cc')}
    evaluation.update(source_set='total', dose_units='physical_gy')
    bundle = memory.retrieve('dose_components')
    if isinstance(bundle, Mapping) and isinstance(bundle.get('total'), Mapping):
        from web.timepoint_resources import capture_resources, dependency_fingerprints
        state = copy.deepcopy(memory.retrieve('timepoint_resource_state') or {})
        resources = dict(state.get('fingerprints') or {})
        fresh = capture_resources(memory.retrieve, memory.retrieve('ct_image'))
        # Only QA leaves change here; physical dose/source identities remain
        # exactly the producer's receipt, not inferred from process defaults.
        resources.update({key: fresh[key] for key in ('ctv', 'oar', 'constraints')})
        resources = dependency_fingerprints(resources)
        evaluation.update(dependency_fingerprint=resources['metrics'],
                          total_dose_sha256=bundle['total']['dose_sha256'])
        state['fingerprints'] = resources
        state['ready'] = sorted(set(state.get('ready') or ()) | {'metrics'})
        state['invalidated'] = sorted((set(state.get('invalidated') or ()) - {'metrics'}) | {'report'})
        memory.store('timepoint_resource_state', state)
    for key, value in {'metrics':metrics, 'dose_metrics':metrics, 'dvh_data':dvh,
                      'total_dose_evaluation':evaluation, 'current_dose_evaluation_config':basis,
                      'quality_check_status':'ready', 'report_status':'stale'}.items():
        memory.store(key, value)
    for key in ('manual_artifact_status', 'artifact_status'):
        status = copy.deepcopy(memory.retrieve(key) or {})
        status.update(dvh='ready', quality_check='ready', report='stale')
        memory.store(key, status)
    # Cached report bodies must not continue to describe older QA. This does
    # not publish a Planning or change any physical dose/geometry arrays.
    for key in ('report_data','report_result','report_path','report_pdf_path','report_html_path','report_pdf','report_html'):
        if memory.retrieve(key) is not None:
            memory.store(key, None)
    return True
