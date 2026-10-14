"""Authenticated presentation routes never become clinical approval endpoints."""
from types import SimpleNamespace
from uuid import uuid4
import pytest
from flask import Flask
from web.auth import configure_auth,register_auth_routes
from web.routes.implant_routes import register_implant_routes
from web.workspace_store import WorkspaceStore
from web.implant_workspace import public_implant_view
from web.timepoints import default_timepoint_id


@pytest.fixture
def clients(tmp_path,monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT',str(tmp_path/'archive'))
    monkeypatch.delenv('BRACHYBOT_API_KEY',raising=False)
    monkeypatch.delenv('BRACHYBOT_REQUIRE_API_KEY',raising=False)
    store=WorkspaceStore(tmp_path/'runtime');app=Flask(__name__)
    configure_auth(app,store,{'secret_key':'synthetic-secret'});register_auth_routes(app,store)
    calls=[]
    class FakeWorkspace:
        def __init__(self,store,owner,sid,tid):self.owner,self.sid,self.tid=owner,sid,tid
        def view(self):return {'session_id':self.sid,'timepoint_id':self.tid,'nodes':[],'observation_revision_id':None}
        def correct(self,payload,actor):calls.append((self.owner,self.sid,self.tid,payload,actor));return self.view()
        def set_presentation(self,payload):calls.append(('presentation',payload));return self.view()
    app.config['IMPLANT_WORKSPACE_FACTORY']=FakeWorkspace
    register_implant_routes(app,store)
    a,b=app.test_client(),app.test_client()
    auth=a.post('/api/auth/register',json={'username':'implant_reader','password':'synthetic-password-123'}).get_json()
    b.post('/api/auth/register',json={'username':'other_reader','password':'synthetic-password-123'})
    sid=auth['active_session_id'];tid=default_timepoint_id(sid)
    return app,store,a,b,auth,'/api/sessions/'+sid+'/timepoints/'+tid+'/implants',calls


def test_owned_get_and_csrf_protect_corrections(clients):
    _,_,client,other,auth,url,calls=clients
    assert client.get(url).status_code==200
    assert other.get(url).status_code==400
    assert client.post(url+'/corrections',json={'action':'exclude'}).status_code==403
    response=client.post(url+'/corrections',headers={'X-CSRF-Token':auth['csrf_token']},json={'action':'exclude'})
    assert response.status_code==200 and calls[-1][-1]==auth['user']['id']


def test_conflicting_target_and_cross_browser_lease_never_edit(clients):
    _,store,client,_,auth,url,calls=clients
    headers={'X-CSRF-Token':auth['csrf_token'],'X-BrachyBot-Timepoint':uuid4().hex}
    assert client.post(url+'/corrections',headers=headers,json={}).status_code==400 and not calls
    store.acquire_lease(auth['user']['id'],auth['active_session_id'],'editor-'+uuid4().hex)
    response=client.post(url+'/corrections',headers={'X-CSRF-Token':auth['csrf_token'],'X-BrachyBot-Language':'zh'},json={})
    assert response.status_code!=200 and not calls
    assert '/private' not in response.get_data(as_text=True)


def test_explicit_source_settings_are_current_target_only_and_not_clinical_approval(clients,tmp_path,monkeypatch):
    from plans.dose_pre import model_loader
    _,store,client,_,auth,url,_=clients
    checkpoint=tmp_path/'inert-checkpoint.pth';checkpoint.write_bytes(b'not-loaded-test-fixture')
    monkeypatch.setattr(model_loader,'resolve_dose_model_path',lambda:checkpoint)
    info=client.get(url+'/dose-source').get_json()
    assert info['clinical_use_ready'] is False
    result=client.post(url+'/dose-source',headers={'X-CSRF-Token':auth['csrf_token']},json={
        'length_mm':3.7,'radius_mm':.4,'expected_state_revision':info['state_revision']})
    assert result.status_code==200,result.get_data(as_text=True)
    profile=result.get_json()['profile']
    assert profile['seed_info']['length']==3.7 and profile['clinical_use_ready'] is False
    assert 'not_clinical_approval' in profile['confirmation_scope']
    saved=store.load_snapshot(auth['user']['id'],auth['active_session_id'])['agent']['planning_results']
    assert saved['implant_dose_profile']['dose_model_sha256']==profile['dose_model_sha256']


@pytest.mark.parametrize('values',[{'length_mm':True,'radius_mm':.4},{'length_mm':.4,'radius_mm':1},{'length_mm':float('nan'),'radius_mm':.4}])
def test_source_profile_rejects_invalid_dimensions(clients,tmp_path,monkeypatch,values):
    from plans.dose_pre import model_loader
    _,_,client,_,auth,url,_=clients
    path=tmp_path/'dummy.pth';path.write_bytes(b'inert')
    monkeypatch.setattr(model_loader,'resolve_dose_model_path',lambda:path)
    info=client.get(url+'/dose-source').get_json()
    result=client.post(url+'/dose-source',headers={'X-CSRF-Token':auth['csrf_token']},json={**values,'expected_state_revision':info['state_revision']})
    assert result.status_code==400


def test_numerical_delta_roundtrips_without_overwriting_other_clinical_keys(clients,monkeypatch):
    import numpy as np
    from web.workspace_store import _decode_artifacts,WorkspaceLeaseConflict
    _,store,_,_,auth,_,_=clients
    owner,sid=auth['user']['id'],auth['active_session_id']
    store.save_agent_results_patch(owner,sid,{'manual_seeds':[{'id':'future-unchanged'}],
        'implant_dose_profile':{'confirmed_by':owner},'dose_distribution':'future-plan-unchanged'})
    revision=store.get_session(owner,sid).revision
    monkeypatch.setattr(store,'flush_agent_checkpoint',lambda *args,**kwargs:pytest.fail('A delta must not write a complete Agent'))
    grid=np.arange(512,dtype=np.float32).reshape(8,8,8)
    store.save_agent_results_delta(owner,sid,{'implanted_dose_record':{'source_set':'implanted',
        'dose_distribution_physical_gy':grid}},expected_revision=revision)
    restored=_decode_artifacts(store.load_snapshot(owner,sid)['agent']['planning_results'],store.workspace_root(owner,sid))
    np.testing.assert_array_equal(restored['implanted_dose_record']['dose_distribution_physical_gy'],grid)
    assert restored['manual_seeds']==[{'id':'future-unchanged'}]
    assert restored['dose_distribution']=='future-plan-unchanged'
    assert restored['implant_dose_profile']=={'confirmed_by':owner}
    with pytest.raises(WorkspaceLeaseConflict):
        store.save_agent_results_delta(owner,sid,{'implanted_dose_record':{'stale':True}},expected_revision=revision)
    assert store.load_snapshot(owner,sid)['agent']['planning_results']['implanted_dose_record']['source_set']=='implanted'


def test_small_source_patch_uses_atomic_revision_check(clients):
    from web.workspace_store import WorkspaceLeaseConflict
    _,store,_,_,auth,_,_=clients
    owner,sid=auth['user']['id'],auth['active_session_id']
    revision=store.get_session(owner,sid).revision
    store.save_agent_results_patch(owner,sid,{'implant_dose_profile':{'current':'new'}},expected_revision=revision)
    with pytest.raises(WorkspaceLeaseConflict):
        store.save_agent_results_patch(owner,sid,{'implant_dose_profile':{'current':'old'}},expected_revision=revision)
    assert store.load_snapshot(owner,sid)['agent']['planning_results']['implant_dose_profile']=={'current':'new'}


@pytest.mark.parametrize('payload',[{}, {'request_id':False}, {'request_id':'not-a-uuid'},
    {'request_id':str(uuid4()),'expected_revision_id':False}])
def test_invalid_detection_request_is_rejected_before_starting_any_job(clients,payload):
    _,_,client,_,auth,url,calls=clients
    result=client.post(url+'/detect',headers={'X-CSRF-Token':auth['csrf_token']},json=payload)
    assert result.status_code==400 and not calls
    assert result.get_json()['success'] is False
