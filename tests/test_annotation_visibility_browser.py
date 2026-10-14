"""Actual Data Tree clicks must affect the canonical 3D annotation owner."""
import pytest

from test_planning_distance_annotations_browser import browser, page, install, real_presentation_registry, JS
from test_viewers_toolbar_browser import function


def expand(page):
    page.locator('#dataTreeBody details').evaluate_all('(rows)=>rows.forEach(row=>row.open=true)')


@pytest.mark.parametrize('index',[0,1,2])
def test_actual_eye_click_hides_only_one_distance_annotation_and_shows_it_again(page,index):
    packet=install(page)
    annotation_id=packet['records'][index]['id']
    other_ids=[row['id'] for row in packet['records'] if row['id']!=annotation_id]
    expand(page)
    row=page.locator(f'.tree-item[data-node-id="{annotation_id}"]')
    row.locator('.eye-btn').click()
    assert page.evaluate('id=>state.annotations.find(r=>r.id===id).visible',annotation_id) is False
    assert page.evaluate('id=>state.annotations.find(r=>r.id===id).visible3D',annotation_id) is False
    assert row.locator('.eye-btn').get_attribute('aria-pressed')=='false'
    assert page.locator('.planning-distance-tag').count()==2
    assert page.evaluate('ids=>state.annotations.filter(r=>ids.includes(r.id)).every(r=>r.visible!==false)',other_ids)
    expand(page)
    row.locator('.eye-btn').click()
    assert page.evaluate('id=>state.annotations.find(r=>r.id===id).visible',annotation_id) is True
    assert row.locator('.eye-btn').get_attribute('aria-pressed')=='true'
    assert page.locator('.planning-distance-tag').count()==3


@pytest.mark.parametrize('index',[0,2])
def test_eye_show_restores_annotation_hidden_by_3d_context_action(page,index):
    packet=install(page)
    annotation_id=packet['records'][index]['id']
    page.evaluate('id=>_setNodeViewVisibility(dataTreeState.annotations.find(r=>r.id===id),"3d",false)',annotation_id)
    assert page.locator('.planning-distance-tag').count()==2
    expand(page)
    page.locator(f'.tree-item[data-node-id="{annotation_id}"] .eye-btn').click()
    assert page.locator('.planning-distance-tag').count()==3
    assert page.evaluate('id=>state.annotations.find(r=>r.id===id).visible3D',annotation_id) is True


def test_legacy_split_visibility_is_migrated_and_eye_matches_the_3d_state(page):
    packet=install(page)
    annotation_id=packet['records'][0]['id']
    real_presentation_registry(page)
    page.evaluate('''id=>stageWorkspacePresentation({annotations:[{id,objectId:'annotation:'+id,
        visible:true,visible3D:false,opacity:.45,color:'#123456'}]},'case')''',annotation_id)
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',packet)
    row=page.evaluate('id=>state.annotations.find(r=>r.id===id)',annotation_id)
    assert row['visible'] is False and row['visible3D'] is False
    expand(page)
    button=page.locator(f'.tree-item[data-node-id="{annotation_id}"] .eye-btn')
    assert 'hidden' in button.get_attribute('class')
    button.click()
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',packet)
    row=page.evaluate('id=>state.annotations.find(r=>r.id===id)',annotation_id)
    assert row['visible'] is True and row['visible3D'] is True
    assert row['opacity']==.45 and row['color']=='#123456'
    assert page.locator(f'.planning-distance-tag[data-annotation-id="{annotation_id}"]').count()==1


def test_bulk_buttons_use_the_same_3d_state_without_affecting_guide_or_geometry(page):
    packet=install(page)
    seed_id=packet['records'][0]['id']
    before=page.evaluate('JSON.stringify(dataTreeState.planning)')
    page.evaluate('id=>_setNodeViewVisibility(dataTreeState.annotations.find(r=>r.id===id),"3d",false)',seed_id)
    expand(page)
    family=page.locator('.planning-distance-tree').nth(1)
    family.get_by_role('button',name='Show all',exact=True).click()
    assert page.locator('.planning-distance-tag').count()==3
    assert page.evaluate('state.annotations.filter(r=>r.kind==="seed_tip_distance").every(r=>r.visible&&r.visible3D)')
    family.get_by_role('button',name='Hide all',exact=True).click()
    assert page.locator('.planning-distance-tag').count()==1
    assert page.evaluate('state.annotations.filter(r=>r.kind==="seed_tip_distance").every(r=>!r.visible&&!r.visible3D)')
    assert before==page.evaluate('JSON.stringify(dataTreeState.planning)')
    assert page.evaluate('state.annotations.find(r=>r.id==="manual_line").visible') is True


def test_programmatic_single_show_and_saved_restore_use_the_same_canonical_record(page):
    packet=install(page)
    annotation_id=packet['records'][0]['id']
    real_presentation_registry(page)
    page.evaluate("stageWorkspacePresentation({annotations:dataTreeState.annotations},'case')")
    page.evaluate('id=>_setNodeViewVisibility(dataTreeState.annotations.find(r=>r.id===id),"3d",false)',annotation_id)
    assert page.evaluate('id=>setDataItemVisibility(id,true)',annotation_id) is True
    assert page.locator(f'.planning-distance-tag[data-annotation-id="{annotation_id}"]').count()==1
    page.evaluate('id=>setDataItemVisibility(id,false)',annotation_id)
    # Model a cold workspace restore, not merely a redraw of live data.
    page.evaluate('''() => {
        const saved=JSON.parse(JSON.stringify(state.annotations));
        state.annotations=[];
        stageWorkspacePresentation({annotations:saved},'case');
    }''')
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',packet)
    row=page.evaluate('id=>state.annotations.find(r=>r.id===id)',annotation_id)
    assert row['visible'] is False and row['visible3D'] is False
    assert page.locator(f'.planning-distance-tag[data-annotation-id="{annotation_id}"]').count()==0


def test_dense_single_show_prioritizes_the_requested_annotation_without_moving_geometry(page):
    packet=install(page,180)
    drawn=set(page.locator('.planning-distance-tag').evaluate_all('(rows)=>rows.map(row=>row.dataset.annotationId)'))
    annotation_id=next(row['id'] for row in packet['records'] if row['kind']=='seed_tip_distance' and row['id'] not in drawn)
    before=page.evaluate('JSON.stringify(dataTreeState.planning)')
    page.evaluate('id=>setDataItemVisibility(id,false)',annotation_id)
    expand(page)
    page.locator(f'.tree-item[data-node-id="{annotation_id}"] .eye-btn').click()
    assert page.locator(f'.planning-distance-tag[data-annotation-id="{annotation_id}"]').count()==1
    assert page.locator('[data-distance-focus="needle_1"]').count()==1
    assert before==page.evaluate('JSON.stringify(dataTreeState.planning)')


def test_show_does_not_override_a_hidden_source_or_zero_opacity(page):
    packet=install(page)
    annotation_id=packet['records'][0]['id']
    source_id=packet['records'][0]['source_object_id']
    page.evaluate('id=>scene3D.meshes[id].visible=false',source_id)
    page.evaluate('id=>setDataItemVisibility(id,true)',annotation_id)
    assert page.locator(f'.planning-distance-tag[data-annotation-id="{annotation_id}"]').count()==0
    assert page.evaluate('id=>scene3D.meshes[id].visible',source_id) is False
    page.evaluate('id=>scene3D.meshes[id].visible=true',source_id)
    page.evaluate('id=>setPlanningDistanceAnnotationPresentation(id,{opacity:0,visible:true})',annotation_id)
    assert page.locator(f'.planning-distance-tag[data-annotation-id="{annotation_id}"]').count()==0
    assert page.evaluate('id=>state.annotations.find(r=>r.id===id).opacity',annotation_id)==0


@pytest.mark.parametrize('language',['en','zh'])
def test_eye_labels_follow_global_language_and_saved_visibility(page,language):
    page.add_script_tag(content='window._t=(zh,en)=>window._i18nLang==="zh"?zh:en;'+
        function((JS/'brachybot-viewer-volume.js').read_text(),'_dtText'))
    packet=install(page)
    annotation_id=packet['records'][0]['id']
    page.evaluate('lang=>{window._i18nLang=lang;window.dispatchEvent(new Event("i18nchange"));}',language)
    expand(page)
    button=page.locator(f'.tree-item[data-node-id="{annotation_id}"] .eye-btn')
    assert button.get_attribute('aria-label')==('隐藏此标注' if language=='zh' else 'Hide this annotation')
    button.click()
    assert ('显示此标注' if language=='zh' else 'Show this annotation') in button.get_attribute('aria-label')
    assert button.get_attribute('aria-pressed')=='false'
