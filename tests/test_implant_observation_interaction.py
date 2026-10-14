"""Correction records preserve raw evidence and cannot silently authorize dose."""
from dataclasses import replace
from uuid import uuid4
import pytest
from test_implant_service import owned, service_for, reconstruct
from web.implant_service import ImplantCorrectionRequest, ImplantReviewAuthorization, ImplantServiceError
from web.implant_workspace import public_implant_view, validate_appearance


def correction(owned, receipt, action, ids=(), center=None, rid=None):
    scope, source, _, _ = owned
    auth=ImplantReviewAuthorization(scope.owner_id,source.image_ref,receipt['record']['reconstruction']['revision_id'],'synthetic-reader')
    return ImplantCorrectionRequest(auth,rid or str(uuid4()),action,tuple(ids),center)


def test_exclude_restores_one_detection_without_removing_raw_detector_artifacts(owned):
    service,_=service_for(owned);first=reconstruct(service,owned[1]);row=first['record']['reconstruction']['observations'][0]
    request=correction(owned,first,'exclude',[row['observation_id']]);second=service.correct(request)
    assert second['record']['counts']['excluded_count']==1
    assert second['record']['artifacts']==first['record']['artifacts']
    assert second['record']['reconstruction']['parent_revision_id']==first['record']['reconstruction']['revision_id']
    assert service.correct(request)['record']==second['record']
    restored=service.correct(correction(owned,second,'restore',[row['observation_id']]))
    assert restored['record']['counts']['excluded_count']==0
    assert not restored['record']['reconstruction']['dose_input_ready']


def test_move_invalidates_axis_and_coverage_and_retains_observation_identity(owned):
    service,_=service_for(owned);first=reconstruct(service,owned[1]);row=first['record']['reconstruction']['observations'][0]
    center=owned[1].image_ref.geometry.points_from_xyz(__import__('numpy').asarray([6.,6.,7.])).tolist()
    second=service.correct(correction(owned,first,'move',[row['observation_id']],center))
    moved=next(item for item in second['record']['reconstruction']['observations'] if item['observation_id']==row['observation_id'])
    assert moved['center_lps_mm']==center and moved['axis_lps'] is None
    assert second['record']['reconstruction']['coverage_status']=='unknown'
    assert not second['record']['reconstruction']['dose_input_ready']
    assert second['record']['correction']['artifact_geometry_current'] is False


def test_add_is_distinct_review_needed_point_and_not_a_planned_source(owned):
    service,_=service_for(owned);first=reconstruct(service,owned[1])
    center=owned[1].image_ref.geometry.points_from_xyz(__import__('numpy').asarray([9.,7.,5.])).tolist()
    second=service.correct(correction(owned,first,'add',center=center))
    view=public_implant_view(second)
    assert view['active_count']==3
    assert all(row['color']=='#22D3EE' and row['role']=='implanted_observation' for row in view['nodes'])
    added=view['nodes'][-1]
    assert added['position']==center and added['axis'] is None and added['glyph']=='point_halo'
    assert not view['clinical_use_ready'] and view['review_required']


@pytest.mark.parametrize('point', [[float('nan'),1,1],[True,1,2],[1,2],[-999999,0,0]])
def test_invalid_or_outside_points_never_change_head(owned,point):
    service,_=service_for(owned);first=reconstruct(service,owned[1])
    with pytest.raises((ValueError,ImplantServiceError)):
        service.correct(correction(owned,first,'add',center=point))
    assert service.get()['current_revision_id']==first['current_revision_id']


def test_stale_move_and_foreign_authorization_are_rejected(owned):
    service,_=service_for(owned);first=reconstruct(service,owned[1]);row=first['record']['reconstruction']['observations'][0]
    request=correction(owned,first,'exclude',[row['observation_id']]);service.correct(request)
    with pytest.raises(ImplantServiceError,match='changed'):
        service.correct(correction(owned,first,'move',[row['observation_id']],row['center_lps_mm']))
    with pytest.raises(ImplantServiceError):
        service.correct(replace(request,request_id=str(uuid4()),authorization=replace(request.authorization,owner_id='other-owner')))


@pytest.mark.parametrize('patch',[{'opacity':float('nan')},{'opacity':True},{'visible':1},{'color':'red;script()'},{'position':[1,2,3]}])
def test_appearance_is_not_geometry_or_css_injection(patch):
    with pytest.raises(ImplantServiceError):validate_appearance(patch)


def test_capsule_dimensions_are_never_invented_for_unknown_axes(owned):
    service,_=service_for(owned);receipt=reconstruct(service,owned[1]);view=public_implant_view(receipt)
    assert all(row['glyph']=='point_halo' for row in view['nodes'])
    assert view['coordinate_system']=='LPS' and view['coordinate_unit']=='mm'
