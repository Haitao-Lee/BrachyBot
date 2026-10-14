"""Actual legacy manual-dose executor retains fixed sources through edits."""
from types import SimpleNamespace
import numpy as np
import pytest
import SimpleITK as sitk
from agent_runtime.core import AgentMemory
from plans.continuation import ContinuationBaseline, array_sha256, grid_signature
from tool_factory.seed_plan.continuation_support import baseline_record
from utils.dose_seed_cache import DoseSeedCache


@pytest.fixture
def manual_case(monkeypatch):
    from web import server_support as support
    from plans import device_manager, utilizations
    from tool_factory.seed_plan import planning_pipeline
    image = sitk.GetImageFromArray(np.zeros((8, 8, 8), np.int16))
    target = np.ones((8, 8, 8), np.uint8)
    dose = np.full(target.shape, .6)
    baseline = ContinuationBaseline.create(dose,image,baseline_unit='normalized_model',
        baseline_grid_signature=grid_signature(image),baseline_dose_sha256=array_sha256(dose),
        complete_target_mask=target>0,dose_scale_gy=37.,dose_contract_id='synthetic-v1',
        needle_radius_mm=.2,clearance_mm=0.)
    memory=AgentMemory('f'*32)
    for key,value in dict(ct_image=image,ct_data=sitk.GetArrayFromImage(image),ctv_binary_array=target,
        oar_array=np.zeros_like(target),resampled_ct=image,resampled_ctv=target,
        resampled_oar=np.zeros_like(target),continuation_baseline_record=baseline_record(baseline,image),
        plan_config={'seed_info':{'length':1.,'radius':.2},'dose_scale_gy':37.,'prescription_gy':37.},
        dose_scale_gy=37.).items():memory.store(key,value)
    agent=SimpleNamespace(memory=memory,config={},session_id='f'*32)
    monkeypatch.setattr(support,'_validate_manual_needle_safety',lambda *a:None)
    monkeypatch.setattr(support,'_MANUAL_DOSE_MODEL_CACHE',{})
    monkeypatch.setattr(support,'_MANUAL_DOSE_SEED_CACHE',DoseSeedCache())
    monkeypatch.setattr(device_manager,'get_device',lambda **k:'cpu')
    monkeypatch.setattr(planning_pipeline,'_load_dose_model',lambda **k:(object(),None))
    monkeypatch.setattr(utilizations,'normalize_dose_image',lambda *a,**k:image)
    calls=[]
    def compute(seeds,*a,**k):
        calls.append(len(seeds))
        return [np.full(target.shape,.4,np.float32) for _ in seeds]
    monkeypatch.setattr(utilizations,'batch_seed_dose_calculation_dl',compute)
    return support,agent,image,calls


def test_actual_manual_zero_supplemental_sources_retains_fixed_baseline(manual_case):
    support,agent,image,calls=manual_case
    result=support._compute_manual_ai_dose(agent,[],[])
    assert result['success'] and not calls
    assert np.allclose(agent.memory.retrieve('dose_distribution_gy'),22.2)
    assert np.allclose(agent.memory.retrieve('dose_distribution'),.6)
    assert np.allclose(agent.memory.retrieve('additional_dose_distribution'),0)
    assert result['metrics']['d90']==pytest.approx(22.2,abs=1e-4)


def test_actual_manual_edit_evaluates_total_and_unchanged_sources_reuse_maps(manual_case):
    support,agent,image,calls=manual_case
    seed={'id':'new-source','position':[4.,4.,4.],'direction':[0.,0.,1.]}
    first=support._compute_manual_ai_dose(agent,[seed],[])
    assert first['metrics']['v100']==1.
    assert first['metrics']['d90']==pytest.approx(37.,abs=1e-4)
    assert np.allclose(agent.memory.retrieve('dose_components')['implanted']['dose_distribution_physical_gy'],22.2)
    assert np.allclose(agent.memory.retrieve('dose_components')['planned']['dose_distribution_physical_gy'],14.8)
    second=support._compute_manual_ai_dose(agent,[seed],[])
    assert second['metrics']['d90']==pytest.approx(37.,abs=1e-4)
    assert calls==[1]


def test_missing_intraop_baseline_rejects_before_model(manual_case):
    support,agent,image,calls=manual_case
    agent.memory.store('continuation_baseline_record',None)
    agent._workspace_timepoint_context=SimpleNamespace(target=SimpleNamespace(stage='intraoperative'))
    with pytest.raises(ValueError,match='fixed.dose|fixed dose'):
        support._compute_manual_ai_dose(agent,[],[])
    assert not calls
