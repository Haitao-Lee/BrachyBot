"""Physical dose reuse and current versus historical evaluation authority."""
from types import SimpleNamespace
import numpy as np
import SimpleITK as sitk
from agent_runtime.core import AgentMemory
from web.planning_config import input_config_invalidation, current_evaluation_config
from web.timepoint_resources import capture_resources


def values():
    mask = np.ones((4,4,4),np.uint8)
    image = sitk.GetImageFromArray(np.zeros(mask.shape,np.float32))
    source = {'length':4.5,'radius':.4,'margin_rate':1.}
    config = {'in_lowest_dose_gy':90.,'in_lowest_energy':90.,'dose_value_unit':'gy',
        'DVH_rate':.9,'seed_info':source}
    record = {'plan_config':dict(config), 'timepoint_planning_config':dict(config),
        'ctv_binary_array':mask,'oar_array':np.zeros_like(mask),'dose_metrics':{'v100':1.},
        'dose_distribution_physical_gy':np.full(mask.shape,90.,np.float32),
        'implanted_dose_record':{'status':'ready','source_count':12},
        'artifact_status':{'dose':'ready','dvh':'ready','quality_check':'ready','report':'ready'}}
    return image, config, record


def test_rx_change_invalidates_quality_without_discarding_physical_components():
    image, config, record = values()
    changed = {**config,'in_lowest_dose_gy':120.,'in_lowest_energy':120.}
    dose = record['dose_distribution_physical_gy']
    updates = input_config_invalidation(record.get,config,changed)
    assert updates['dose_metrics'] is None and updates['quality_check_status'] == 'stale'
    assert updates['artifact_status']['dose'] == 'ready'
    assert 'implanted_dose_record' not in updates and 'dose_distribution_physical_gy' not in updates
    assert record['dose_distribution_physical_gy'] is dose
    before = capture_resources(record.get,image)
    record.update(updates,timepoint_planning_config=changed)
    after = capture_resources(record.get,image)
    assert before['implanted_dose'] == after['implanted_dose']
    assert before['planned_dose'] == after['planned_dose'] and before['total_dose'] == after['total_dose']
    assert before['metrics'] != after['metrics'] and before['report'] != after['report']
    assert current_evaluation_config(record.get)['prescription_gy'] == 120.
    assert record['plan_config']['in_lowest_dose_gy'] == 90.


def test_optimizer_edit_changes_plan_identity_not_confirmed_implant_dose():
    image, config, record = values()
    before = capture_resources(record.get,image)
    changed = {**config,'seed_info':{**config['seed_info'],'margin_rate':1.5}}
    updates = input_config_invalidation(record.get,config,changed)
    assert updates['planning_inputs_status'] == 'stale'
    assert updates['artifact_status']['dvh'] == 'ready'
    assert updates['artifact_status']['dose'] == 'ready'
    assert 'implanted_dose_record' not in updates and 'dose_metrics' not in updates
    record.update(updates,timepoint_planning_config=changed)
    after = capture_resources(record.get,image)
    assert before['supplemental_plan'] != after['supplemental_plan']
    assert before['implanted_dose'] == after['implanted_dose']
    assert before['metrics'] == after['metrics']


def test_identical_owned_config_does_not_invalidate_resources():
    image, config, record = values()
    assert input_config_invalidation(record.get,config,dict(config)) == {}


def test_historical_activation_cannot_revive_quality_for_prior_rx():
    from web.planning_runs import ensure_planning_history, active_planning_id, activate_planning_run, current_planning_context
    _, config, record = values()
    memory = AgentMemory('a'*32)
    for key, value in record.items():
        memory.store(key,value)
    memory.store('total_seeds',1)
    ensure_planning_history(memory)
    identifier = active_planning_id(memory)
    memory.store('timepoint_planning_config',{**config,'in_lowest_dose_gy':120.,'in_lowest_energy':120.})
    activate_planning_run(SimpleNamespace(memory=memory),identifier)
    assert current_planning_context(memory)['metrics'] == {}
    assert memory.retrieve('dose_metrics') is None
    assert memory.retrieve('artifact_status')['quality_check'] == 'stale'
    assert np.all(memory.retrieve('dose_distribution_physical_gy') == 90.)
    assert memory.retrieve('plan_config')['in_lowest_dose_gy'] == 90.


def test_actual_manual_dose_evaluation_uses_current_rx_and_keeps_historical_input():
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool
    image, config, record = values()
    memory = AgentMemory('b'*32)
    for key,value in record.items():
        memory.store(key,value)
    memory.store('dose_distribution',np.full((4,4,4),90./190.8,np.float32))
    memory.store('timepoint_planning_config',{**config,'in_lowest_dose_gy':120.,'in_lowest_energy':120.})
    memory.store('dose_scale_gy',190.8)
    memory.store('resampled_ct',image)
    memory.store('ct_image',image)
    result = PlanningPipelineTool()._step_dose_eval(np.ones((4,4,4),np.uint8),
        np.zeros((4,4,4),np.uint8),SimpleNamespace(memory=memory))
    assert result.success, result.error
    assert result.metadata['v100'] == 0.
    assert result.metadata['prescription_gy'] == 120.
    assert result.metadata['d90'] == 90.
    assert memory.retrieve('plan_config')['in_lowest_dose_gy'] == 90.
    assert memory.retrieve('current_dose_evaluation_config')['prescription_gy'] == 120.
