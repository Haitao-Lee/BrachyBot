"""Current QA cannot be restored from an untouched historical algorithm plan."""
from agent_runtime.core import AgentMemory
from web.planning_runs import current_planning_context
import pytest


def test_invalidated_total_cannot_resurrect_reference_metrics():
    memory = AgentMemory('synthetic-quality')
    memory.store('algorithm_plan_dose_metrics',{'v100':.99,'d90':140.})
    memory.store('dose_metrics',None)
    memory.store('metrics',None)
    memory.store('dose_components',{'implanted':{'dose_status':'stale'},'planned':{},'total':None})
    memory.store('manual_artifact_status',{'dose':'stale','dvh':'stale','quality_check':'stale'})
    assert current_planning_context(memory)['metrics'] == {}
    from tool_factory.report_facts import resolve_report_facts
    assert resolve_report_facts(memory)['dose'] == {}
    assert memory.retrieve('algorithm_plan_dose_metrics')['v100'] == .99


def test_restored_current_total_can_publish_current_quality_again():
    memory = AgentMemory('synthetic-quality-restored')
    memory.store('dose_components',{'total':{'source_set':'total','dose_status':'ready'}})
    memory.store('dose_metrics',{'v100':.94,'d90':121.,'source_set':'total'})
    memory.store('manual_artifact_status',{'dose':'ready','dvh':'ready','quality_check':'ready'})
    assert current_planning_context(memory)['metrics']['v100'] == .94


def test_report_source_counts_preserve_zero_supplemental_and_total_evaluation_basis():
    from tool_factory.report_facts import report_source_components,format_source_components_markdown
    memory=AgentMemory('synthetic-source-report')
    counts={'implanted':12,'planned':0,'total':12}
    fingerprints={name+'_dose':name+'_fingerprint' for name in counts}
    memory.store('timepoint_resource_state',{'fingerprints':fingerprints})
    memory.store('dose_components',{name:{'source_set':name,'source_count':count,'dose_units':'physical_gy',
        'dependency_fingerprint':fingerprints[name+'_dose'],'dose_sha256':'a'*64} for name,count in counts.items()})
    data=report_source_components(memory)
    assert data['components']['planned']['source_count'] == 0
    assert data['evaluation_source_set'] == 'total'
    assert '| Supplemental planned sources | 0 | Current |' in format_source_components_markdown(data,'en')
    assert '| 新增规划粒子 | 0 | 当前 |' in format_source_components_markdown(data,'zh')
    from tool_factory.report_generator import ReportGeneratorTool
    markdown=ReportGeneratorTool()._generate_full_report({'total_seeds':99,'source_components':data})
    assert '**Supplemental planned seeds:** 0' in markdown
    assert '**Total seeds:** 99' not in markdown
    assert '| Observed implanted sources | 12 | Current |' in markdown


@pytest.mark.parametrize('status_key', ['manual_artifact_status', 'artifact_status'])
@pytest.mark.parametrize('resource', ['dose', 'dvh', 'quality_check'])
@pytest.mark.parametrize('stale', ['stale', {'status': 'stale', 'stale': True}])
def test_report_planned_and_total_sources_respect_artifact_invalidation(status_key, resource, stale):
    from tool_factory.report_facts import report_source_components, format_source_components_markdown
    memory = AgentMemory('source-report-after-edit')
    counts = {'implanted': 10, 'planned': 2, 'total': 12}
    fingerprints = {name + '_dose': name + '-before-edit' for name in counts}
    memory.store('timepoint_resource_state', {'fingerprints': fingerprints})
    memory.store('dose_components', {name: {'source_count': count, 'dose_units': 'physical_gy',
        'dependency_fingerprint': fingerprints[name + '_dose']} for name, count in counts.items()})
    memory.store('manual_seeds', [{'id': 'one-remaining-source'}])
    other = 'artifact_status' if status_key == 'manual_artifact_status' else 'manual_artifact_status'
    memory.store(other, {resource: 'ready'})
    memory.store(status_key, {resource: stale})
    data = report_source_components(memory)
    assert data['components']['implanted']['status'] == 'current'
    assert data['components']['planned']['status'] == 'stale'
    assert data['components']['total']['status'] == 'stale'
    markdown = format_source_components_markdown(data, 'en')
    assert '| Observed implanted sources | 10 | Current |' in markdown
    assert '| Supplemental planned sources | 2 | Stale; recomputation required |' in markdown
    assert '| Total dose | 12 | Stale; recomputation required |' in markdown
    memory.store(status_key, {resource: 'ready'})
    refreshed = report_source_components(memory)
    assert all(row['status'] == 'current' for row in refreshed['components'].values())


def test_zero_supplemental_plan_is_not_missing_geometry_or_activity():
    from tool_factory.report_facts import resolve_report_facts
    memory=AgentMemory('zero-supplemental')
    memory.store('total_seeds',0);memory.store('num_trajectories',0)
    memory.store('plan_config',{'activity_mbq_per_seed':1.7})
    facts=resolve_report_facts(memory)
    assert facts['total_seeds']==0 and facts['num_trajectories']==0
    assert facts['total_activity_mbq']==0.
    memory.store('refined_trajectories',[[1,2,3]])
    memory.store('manual_seeds',[{'id':'old-historical-source'}])
    context=current_planning_context(memory)
    assert context['total_seeds']==0 and context['num_trajectories']==0


def test_structured_stale_flags_cannot_restore_current_quality():
    memory=AgentMemory('structured-dose-stale')
    memory.store('dose_metrics',{'v100':.99,'d90':140.})
    memory.store('artifact_status',{'dose':{'status':'stale','stale':True}})
    assert current_planning_context(memory)['metrics']=={}
    from tool_factory.report_facts import resolve_report_facts
    assert resolve_report_facts(memory)['dose']=={}


def test_observed_source_dose_does_not_invent_a_completed_future_plan():
    from web.planning_runs import ensure_planning_history
    memory=AgentMemory('observed-dose-only')
    memory.store('implanted_seed_reconstruction',{'by_timepoint':{}})
    memory.store('dose_distribution_physical_gy',[120.])
    memory.store('dose_units','physical_gy');memory.store('dose_scale_gy',190.8)
    memory.store('plan_config',{'prescription_gy':120.})
    assert ensure_planning_history(memory)==[]
    assert memory.retrieve('active_planning_id') is None
    memory.store('seed_plan',[]);memory.store('total_seeds',0)
    assert len(ensure_planning_history(memory))==1
