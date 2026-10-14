"""Actual safety executor cannot approve missing/stale or historical-Rx QA."""
import os
import pytest
from test_owned_quality_tool_inputs import owned_quality
from tool_factory.safety_validator import SafetyValidatorTool
from agent_runtime.timepoint_tools import owned_tool_arguments
from agent_runtime.core import ToolResultPipeline


@pytest.fixture(autouse=True)
def portable_store(monkeypatch):
    if os.name=='nt':
        monkeypatch.setattr('web.workspace_store.WorkspaceStore._fsync_directory',staticmethod(lambda path:None))


@pytest.mark.parametrize('action',['validate','pre_export','check_coverage','check_hotspots','check_dose'])
def test_owned_stale_total_measurements_refuse_safety_even_with_caller_plan(owned_quality,action):
    runtime=owned_quality
    runtime.view.memory.store('manual_artifact_status',{'dvh':'stale','quality_check':'stale'})
    with pytest.raises(ValueError,match='Current total-dose measurements'):
        owned_tool_arguments(runtime.view,'safety_validator',{'action':action,
            'tumor_type':'prostate','organ':'bladder','plan':{'metrics':{'v100':1.,'v200':0.,'d90':200.}}})


def test_owned_safety_uses_current_rx_site_and_actual_oar_constraints(owned_quality):
    args=owned_tool_arguments(owned_quality.view,'safety_validator',{'action':'validate','tumor_type':'invented'})
    assert args['tumor_type']=='prostate'
    assert args['plan']['current_dose_evaluation_config']['in_lowest_dose_gy']==120.
    assert args['plan']['plan_config']['in_lowest_dose_gy']==90.
    result=SafetyValidatorTool().execute(**args)
    assert result.success and not result.data['safe']
    assert any(row['metric']=='current_oar_constraints' for row in result.data['critical_violations'])


@pytest.mark.parametrize('action',['validate','pre_export','check_coverage','check_hotspots','check_dose'])
def test_empty_measurements_never_pass_standalone(action):
    result=SafetyValidatorTool().execute(action=action,tumor_type='prostate',organ='bladder',plan={'metrics':{}})
    assert not result.data.get('safe')
    assert not result.data.get('approved')
    assert not result.data.get('all_passed')


@pytest.mark.parametrize('value',[None,float('nan'),float('inf'),True,-1.])
def test_invalid_measurements_are_unverified_not_passed(value):
    result=SafetyValidatorTool().execute(action='validate',tumor_type='prostate',
        plan={'metrics':{'v100':value,'v150':0.,'v200':0.,'d90':1.1}})
    assert result.success and not result.data['safe']
    assert any(row.get('metric')=='v100' and row.get('measurement_available') is False for row in result.data['warnings'])


def test_actual_zero_hotspot_and_oar_are_measured_not_missing():
    tool=SafetyValidatorTool()
    hotspots=tool.execute(action='check_hotspots',tumor_type='prostate',plan={'metrics':{'v150':0.,'v200':0.}})
    assert hotspots.success and hotspots.data['all_passed']
    limits=tool._get_oar_limits_for_site('prostate')['urethra']
    metrics={f'urethra_{key}':0. for key in limits}
    checked=tool.execute(action='check_dose',tumor_type='prostate',organ='urethra',plan={'metrics':metrics})
    assert checked.success and checked.data['all_passed']
    assert all(row['measurement_available'] for row in checked.data['checks'].values())


def test_explicit_low_gy_d90_and_current_prescription_are_not_guessed_as_ratio():
    result=SafetyValidatorTool().execute(action='check_coverage',tumor_type='prostate',
        plan={'metrics':{'v100':1.,'d90':1.,'dose_units':'physical_gy'},
            'plan_config':{'prescription_gy':1.},'current_dose_evaluation_config':{'prescription_gy':2.}})
    assert result.success and not result.data['all_passed']
    assert result.data['checks']['d90']['value']==.5


def test_complete_source_backed_measurements_have_a_positive_validation_control():
    tool=SafetyValidatorTool()
    metrics={'v100':1.,'v150':0.,'v200':0.,'d90':1.1,'oar_metrics':{}}
    for name,limits in tool._get_oar_limits_for_site('prostate').items():
        metrics['oar_metrics'][name]={'max_dose':0.,'D2cc':0.,'mean_dose':0.}
    result=tool.execute(action='validate',tumor_type='prostate',
        plan={'metrics':metrics,'plan_config':{'prescription_gy':120.}})
    assert result.success and result.data['safe'],result.data
    assert result.data['clinical_efficacy_assessed'] is False


def test_unknown_oar_is_not_silently_ignored_in_full_review():
    result=SafetyValidatorTool().execute(action='validate',tumor_type='prostate',
        plan={'metrics':{'v100':1.,'v150':0.,'v200':0.,'d90':1.1,
            'oar_metrics':{'unknown_organ':{'max_dose':0.}}}})
    assert result.success and not result.data['safe']
    assert any(row.get('standards_available') is False for row in result.data['warnings'])


def test_missing_prescription_cannot_assess_relative_oar_dose():
    result=SafetyValidatorTool().execute(action='check_dose',tumor_type='prostate',organ='urethra',
        plan={'metrics':{'oar_metrics':{'urethra':{'max_dose':0.}}}})
    assert result.success and not result.data['all_passed']


def test_owned_oar_guard_enforces_zero_limit_and_accepts_relative_physical_measurement():
    from agent_runtime.timepoint_tools import _require_oar_measurements
    _require_oar_measurements({'bladder':{'max_dose':0.}},'prostate',{'bladder':{'max_dose':0.}})
    _require_oar_measurements({'urethra':{'max_dose':90.}},'prostate',{},120.)
    with pytest.raises(ValueError,match='measurement'):
        _require_oar_measurements({'bladder':{}},'prostate',{'bladder':{'max_dose':0.}})
    with pytest.raises(ValueError,match='prescription'):
        _require_oar_measurements({'urethra':{'max_dose':90.}},'prostate',{},None)
