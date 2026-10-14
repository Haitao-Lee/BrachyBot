"""Source-set decisions survive normalization; dose does not imply replan."""
from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import nullcontext
import pytest
from agent_runtime.core import AgentMemory,ToolResultPipeline
from tool_factory import ToolResult
from tool_factory.dose_recompute import CurrentPlanDoseRecomputeTool
from test_implant_service import owned,service_for,reconstruct


def test_unqualified_recompute_defaults_to_both_when_current_observations_exist(monkeypatch):
    schema=CurrentPlanDoseRecomputeTool().input_schema
    assert schema['properties']['source_set']['enum']==['planned','implanted','both','total']
    memory=AgentMemory('a'*32);memory.store('implanted_seed_reconstruction',{'by_timepoint':{}})
    agent=SimpleNamespace(memory=memory)
    import web.dose_components as components
    calls=[]
    monkeypatch.setattr(components,'recompute_timepoint_dose',lambda agent,**values:
        calls.append(values['source_set']) or ToolResult(True, metadata={'source_set':values['source_set']}))
    result=CurrentPlanDoseRecomputeTool()._execute(_agent=agent)
    assert result.success and calls == ['both']


def test_tool_description_exposes_implanted_observation_dose_not_only_planning_dvh():
    tool=CurrentPlanDoseRecomputeTool()
    assert "source_set='implanted'" in tool.description and "source_set='planned'" in tool.description
    assert 'separate estimated physical-Gy' in tool.description
    assert 'not elapsed dose already delivered' in tool.description
    assert 'observation_revision_id' in tool.output_schema['properties']


def test_implanted_source_set_never_enters_the_planned_seed_executor(monkeypatch):
    import web.implanted_dose as module
    captured=[]
    monkeypatch.setattr(module,'recompute_implanted_dose',lambda agent,**kwargs:(captured.append(kwargs) or ToolResult(True,metadata={'source_set':'implanted'})))
    result=CurrentPlanDoseRecomputeTool()._execute(_agent=SimpleNamespace(memory=AgentMemory('a'*32)),source_set='implanted',expected_observation_revision_id='revision-1')
    assert result.success and captured==[{'expected_revision_id':'revision-1'}]


def test_formatter_does_not_claim_new_plan_or_delivered_dose():
    result=ToolResult(True,metadata={'source_set':'implanted','total_seeds':3,'dose_min_gy':0.,'dose_max_gy':10.})
    zh=ToolResultPipeline.format('dose_recompute',result,'zh')
    en=ToolResultPipeline.format('dose_recompute',result,'en')
    assert '未新增粒子' in zh and '不是已经实际释放' in zh
    assert 'No new sources' in en and 'not dose already delivered' in en


def dose_fixture(owned,monkeypatch):
    import numpy as np
    import web.implanted_dose as module
    from tool_factory.seed_plan import model_support
    from plans.dose_pre import model_loader
    scope,source,runtime,memory=owned
    memory.planning_results=memory.values
    memory.user_lang='en'
    service,_=service_for(owned);receipt=reconstruct(service,source)
    memory.store('plan_config',{'seed_info':{'length':3.7,'radius':.4,'margin_rate':1.5},'dose_scale_gy':190.8})
    memory.store('manual_seeds',[{'id':'future-plan-must-not-radiate','position':[0,0,0]}])
    captured=[]
    store=SimpleNamespace(save_timepoint_results=lambda *args,**kwargs:captured.append((args,kwargs)),
        _case_guard=lambda *args:nullcontext(),load_timepoint_snapshot=lambda *args:{'agent':{'planning_results':{}},'timepoint_state_revision':1})
    workspace=SimpleNamespace(service=service,input=lambda:source,image_current=lambda reference:True,
        owner=scope.owner_id,session=scope.session_id,context=SimpleNamespace(target=SimpleNamespace(legacy_default=False,clinical_revision=1)))
    monkeypatch.setattr(module,'ImplantWorkspace',lambda *args,**kwargs:workspace)
    monkeypatch.setattr(model_loader,'resolve_dose_model_path',lambda path=None:__import__('pathlib').Path(runtime.bundle_dir)/'models'/'best_autoencoder.pth')
    agent=SimpleNamespace(memory=memory,_workspace_store=store,config={'_workspace_owner_id':scope.owner_id,
        '_workspace_session_id':scope.session_id,'_workspace_timepoint_id':scope.timepoint_id})
    def compute(seeds,image,model,dl,seed_info,strict):
        assert strict and all(seed['id']!='future-plan-must-not-radiate' for seed in seeds)
        return np.full(image.GetSize()[::-1],len(seeds),np.float32),seeds
    monkeypatch.setattr(model_support,'compute_world_seed_dose_grid',compute)
    return module,agent,service,source,receipt,captured


def test_current_observations_only_are_aggregated_and_scaled_once(owned,monkeypatch):
    module,agent,service,source,receipt,captured=dose_fixture(owned,monkeypatch)
    result=module.recompute_implanted_dose(agent,model=object())
    assert result.success,result.error
    assert result.metadata['total_seeds']==2 and result.metadata['downstream_actions_executed']==[]
    record=captured[-1][0][3]['implanted_dose_record']
    assert abs(record['dose_max_gy']-381.6)<.001
    assert record['dose_units']=='physical_gy' and record['source_set']=='implanted'
    assert agent.memory.retrieve('dose_distribution') is None
    assert agent.memory.retrieve('manual_seeds')[0]['id']=='future-plan-must-not-radiate'


def test_missing_current_source_dimensions_block_instead_of_borrowing_preop(owned,monkeypatch):
    module,agent,*_=dose_fixture(owned,monkeypatch)
    agent.memory.store('plan_config',{})
    result=module.recompute_implanted_dose(agent,model=object())
    assert not result.success and result.metadata['code']=='implant_source_parameters_required'


def test_edit_during_cnn_aggregation_rejects_stale_dose(owned,monkeypatch):
    from web.implant_service import ImplantReviewAuthorization,ImplantCorrectionRequest
    from uuid import uuid4
    import numpy as np
    from tool_factory.seed_plan import model_support
    module,agent,service,source,receipt,captured=dose_fixture(owned,monkeypatch)
    row=receipt['record']['reconstruction']['observations'][0]
    def compute(seeds,image,model,dl,seed_info,strict):
        auth=ImplantReviewAuthorization(owned[0].owner_id,source.image_ref,receipt['record']['reconstruction']['revision_id'],'human-reader')
        service.correct(ImplantCorrectionRequest(auth,str(uuid4()),'exclude',(row['observation_id'],)))
        return np.zeros(image.GetSize()[::-1],np.float32),seeds
    monkeypatch.setattr(model_support,'compute_world_seed_dose_grid',compute)
    result=module.recompute_implanted_dose(agent,model=object())
    assert not result.success and result.metadata['code']=='implant_revision_conflict' and not captured


def test_source_settings_changed_at_publication_cannot_be_restored_by_old_dose(owned,monkeypatch):
    module,agent,service,source,receipt,captured=dose_fixture(owned,monkeypatch)
    reads=[]
    def state(*args):
        reads.append(1)
        profile={} if len(reads)<3 else {'seed_info':{'length':4.2,'radius':.4}}
        return {'agent':{'planning_results':{'implant_dose_profile':profile}},'timepoint_state_revision':3}
    agent._workspace_store.load_timepoint_snapshot=state
    result=module.recompute_implanted_dose(agent,model=object())
    assert not result.success and result.metadata['code']=='implant_input_changed' and not captured


def test_current_plan_source_dimensions_changing_during_cnn_cannot_publish_old_dose(owned,monkeypatch):
    import numpy as np
    from tool_factory.seed_plan import model_support
    module,agent,service,source,receipt,captured=dose_fixture(owned,monkeypatch)
    def compute(seeds,image,model,dl,seed_info,strict):
        agent.memory.store('plan_config',{'seed_info':{'length':4.2,'radius':.4},'dose_scale_gy':190.8})
        return np.zeros(image.GetSize()[::-1],np.float32),seeds
    monkeypatch.setattr(model_support,'compute_world_seed_dose_grid',compute)
    result=module.recompute_implanted_dose(agent,model=object())
    assert not result.success and result.metadata['code']=='implant_input_changed' and not captured


def test_unrelated_dvh_arrays_do_not_enter_source_parameter_fence(owned,monkeypatch):
    import numpy as np
    module,agent,service,source,receipt,captured=dose_fixture(owned,monkeypatch)
    agent.memory.store('dose_metrics',{'dose_scale_gy':190.8,'dvh':np.arange(12,dtype=np.float32)})
    result=module.recompute_implanted_dose(agent,model=object())
    assert result.success,result.error
    assert result.metadata['total_seeds']==2 and captured


def test_zero_included_observations_produce_zero_source_dose_without_new_sources(owned,monkeypatch):
    from web.implant_service import ImplantReviewAuthorization,ImplantCorrectionRequest
    from uuid import uuid4
    import numpy as np
    from tool_factory.seed_plan import model_support
    module,agent,service,source,receipt,captured=dose_fixture(owned,monkeypatch)
    observations=receipt['record']['reconstruction']['observations']
    auth=ImplantReviewAuthorization(owned[0].owner_id,source.image_ref,receipt['record']['reconstruction']['revision_id'],'human-reader')
    service.correct(ImplantCorrectionRequest(auth,str(uuid4()),'exclude',tuple(row['observation_id'] for row in observations)))
    monkeypatch.setattr(model_support,'compute_world_seed_dose_grid',lambda *args,**kwargs:pytest.fail('An empty source set must not invoke CNN'))
    result=module.recompute_implanted_dose(agent,model=object())
    assert result.success and result.metadata['total_seeds']==0 and result.metadata['downstream_actions_executed']==[]
    assert not np.any(captured[-1][0][3]['implanted_dose_record']['dose_distribution_physical_gy'])


def test_unchanged_implanted_dose_reuses_cnn_without_needing_valid_future_plan(owned,monkeypatch):
    from tool_factory.seed_plan import model_support
    module,agent,service,source,receipt,captured=dose_fixture(owned,monkeypatch)
    agent.memory.store('manual_plan_active',True)
    assert module.recompute_implanted_dose(agent,model=object()).success
    monkeypatch.setattr(model_support,'compute_world_seed_dose_grid',lambda *a,**k:pytest.fail('Unchanged current sources must reuse dose'))
    result=module.recompute_implanted_dose(agent,model=object())
    assert result.success,result.error
    assert result.metadata['reused'] is True and result.metadata['total_seeds']==2


def test_anatomy_deleted_after_implanted_reuse_clears_current_total_quality(owned,monkeypatch):
    from tool_factory.seed_plan import model_support
    module,agent,service,source,receipt,captured=dose_fixture(owned,monkeypatch)
    assert module.recompute_implanted_dose(agent,model=object()).success
    agent.memory.store('dose_metrics',{'plan_score':100.})
    agent.memory.store('dvh_data',{'CTV':{'dose_bins':[120.],'volume_pcts':[100.]}})
    agent.memory.store('oar_array',None)
    monkeypatch.setattr(model_support,'compute_world_seed_dose_grid',lambda *a,**k:pytest.fail('Anatomy does not change implanted CNN dose'))
    result=module.recompute_implanted_dose(agent,model=object())
    assert result.success,result.error
    assert agent.memory.retrieve('dose_metrics') is None and agent.memory.retrieve('dvh_data') is None
    assert agent.memory.retrieve('manual_artifact_status')['dvh']=='stale'
