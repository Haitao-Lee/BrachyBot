"""Real Three.js projection and DOM controls on synthetic planning geometry."""
from pathlib import Path
import re

import pytest

from test_report_plan_tables_browser import browser
from test_viewers_toolbar_browser import function
from test_planning_distance_annotations import snapshot, guide, packet

ROOT=Path(__file__).resolve().parents[1]
JS=ROOT/'web/app/static/js'


@pytest.fixture
def page(browser):
    context=browser.new_context(viewport={'width':1280,'height':900})
    page=context.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content('''<!doctype html><html><body style="background:#0b1221;color:#cbd5e1;font-family:system-ui">
        <div style="display:flex;gap:15px"><div id="dataTreeBody" style="width:330px;height:720px;overflow:auto"></div>
        <div id="canvas3D" style="width:880px;height:680px;background:#000"></div></div></body></html>''')
    page.add_script_tag(path=str(JS/'three.min.js'))
    page.add_style_tag(path=str(ROOT/'web/app/static/css/brachybot-planning-distance-annotations.css'))
    page.add_script_tag(content='''
        var activeSessionId='case'; window._i18nLang='en';
        var state={ctPath:'/synthetic.nii',annotations:[{id:'manual_line',type:'line',visible:true}],ctLoaded:true};
        var dataTreeState={planning:{id:'plan',version:3,seeds:[],needles:[],meshes:[]},annotations:[]};
        var scene3D={camera:new THREE.PerspectiveCamera(50,880/680,.01,2000),meshes:{},requestRender:()=>{}};
        scene3D.camera.position.set(90,70,160);scene3D.camera.lookAt(0,0,10);scene3D.camera.updateMatrixWorld();
        window._activeApiSessionId=()=>activeSessionId;window.saved=[];
        window.scheduleWorkspaceSave=reason=>saved.push({reason,state:JSON.parse(JSON.stringify(state))});
        window.escHtml=x=>String(x||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        window.brachybotInlineArgument=x=>JSON.stringify(x).replace(/"/g,'&quot;');
        window.isDataTreeNodeMasterVisible=n=>n.visible!==false;
        window.isDataTreeNodeVisible3D=n=>n.visible!==false&&n.visible3D!==false;
        window._isDataTreeMaskId=()=>false;window._dtStatusText=x=>x;
        window._ctWindowSliderDomain=()=>({min:-1024,max:3071});
        var WINDOW_LEVEL_MIN_SPAN=1;var selectedItems=new Set();
        window.requestRender=()=>window.renderPlanningDistanceAnnotations?.();
    ''')
    volume=(JS/'brachybot-viewer-volume.js').read_text()
    page.add_script_tag(content='\n'.join(function(volume,n) for n in [
        '_viewerWindowValue','_viewerLevelValue','_windowLevelBounds',
        'ensureDataTreeNodeMetadata','reconcileViewerAnnotationNodes','renderTreeItem',
        'toggleDataVisibility','setDataItemVisibility','setDataOpacity','setDataTreeItemColor',
        'renameDataTreeNode','_setNodeViewVisibility']))
    page.add_script_tag(path=str(JS/'brachybot-planning-distance-annotations.js'))
    page.add_script_tag(content='''
        window.renderDataTree=()=>{
            reconcileViewerAnnotationNodes();
            const rows=dataTreeState.annotations.filter(r=>r.annotationType==='planning_distance');
            document.getElementById('dataTreeBody').innerHTML=renderPlanningDistanceAnnotationTree(rows,renderTreeItem,escHtml);
        };
        window.configureGeometry=packet=>{
            dataTreeState.planning.needles=[{id:'needle_1',points:[[0,0,40],[0,0,-30]],visible:true}];
            dataTreeState.planning.seeds=packet.records.filter(r=>r.kind==='seed_tip_distance')
                .map(r=>({id:r.source_object_id,position:r.anchor_world_mm,visible:true,visible3D:true}));
            scene3D.meshes={};
            dataTreeState.planning.seeds.forEach(s=>{const m=new THREE.Object3D();m.position.fromArray(s.position);scene3D.meshes[s.id]=m;});
            dataTreeState.planning.meshes=[{id:'patient_specific_puncture_guide',visible:true,dataVersion:2}];
            scene3D.meshes.patient_specific_puncture_guide=new THREE.Object3D();
        };
    ''')
    yield page
    context.close();assert not errors,errors


def install(page,dense=0):
    data=snapshot()
    if dense:
        data['seeds']=[{'id':f'seed_1_{i+1}','trajectory_id':'traj_1','position':[0,0,10+i*.12]} for i in range(dense)]
    result=packet(data,guide=guide(),guide_current=True)
    page.evaluate('p=>{configureGeometry(p);acceptPlanningDistanceAnnotations(p);}',result)
    return result


def test_default_records_tree_and_fixed_screen_font(page):
    p=install(page)
    assert page.locator('.planning-distance-tag').count()==3
    assert page.locator('#dataTreeBody .tree-item').count()==3
    assert '15.0 mm' in page.locator('.planning-distance-overlay').text_content()
    assert page.evaluate('getComputedStyle(document.querySelector(".planning-distance-overlay text")).fontWeight')=='700'
    assert page.evaluate('state.annotations.some(a=>a.id==="manual_line")')
    assert all(r['visible'] for r in page.evaluate('state.annotations.filter(r=>r.type==="planning_distance")'))
    assert p['records'][-1]['tip_distance_mm']==50


def test_real_tree_eye_slider_color_and_reload_preserve_preferences(page):
    p=install(page);sid=p['records'][0]['id']
    page.locator('#dataTreeBody details').first.evaluate('(e)=>e.open=true')
    page.locator('#dataTreeBody details').nth(2).evaluate('(e)=>e.open=true')
    # Invoke the production Data Tree handlers (not a second test executor).
    page.evaluate('id=>{toggleDataVisibility(id);setDataOpacity(id,40);setDataTreeItemColor(id,"#123456");}',sid)
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    record=page.evaluate('id=>state.annotations.find(r=>r.id===id)',sid)
    assert record['visible'] is False and record['opacity']==.4 and record['color']=='#123456'
    assert page.locator('.planning-distance-tag').count()==2
    page.evaluate('id=>setDataItemVisibility(id,true)',sid)
    assert page.locator('.planning-distance-tag').count()==3


def test_saved_checkpoint_visual_preferences_survive_page_restore(page):
    p=install(page);sid=p['records'][0]['id']
    page.evaluate('id=>setPlanningDistanceAnnotationPresentation(id,{visible:false})',sid)
    saved=page.evaluate('JSON.parse(JSON.stringify(state.annotations))')
    page.evaluate('rows=>state.annotations=rows',saved)
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    assert page.evaluate('id=>state.annotations.find(r=>r.id===id).visible',sid) is False


def test_global_language_relocalizes_tree_and_labels_without_changing_values(page):
    install(page);before=page.evaluate('state.annotations.filter(r=>r.type==="planning_distance").map(r=>r.tip_distance_mm)')
    page.evaluate('window._i18nLang="zh";window.dispatchEvent(new CustomEvent("i18nchange"))')
    assert '导板入口' in page.locator('#dataTreeBody').inner_text()
    assert '针 1' in page.locator('.planning-distance-overlay').text_content()
    assert 'Guide mouth' not in page.locator('.planning-distance-overlay').text_content()
    assert before==page.evaluate('state.annotations.filter(r=>r.type==="planning_distance").map(r=>r.tip_distance_mm)')


@pytest.mark.parametrize('change',[
    'activeSessionId="other"', 'dataTreeState.planning.id="other"', 'dataTreeState.planning.version=4',
    'dataTreeState.planning.needles[0].points[0][2]=41',
])
def test_case_revision_or_drag_preview_cannot_show_old_distances(page,change):
    p=install(page);page.evaluate(change+';renderPlanningDistanceAnnotations()')
    assert page.locator('.planning-distance-tag').count()==0
    if 'activeSessionId' in change or 'planning.' in change and 'points' not in change:
        assert page.evaluate('p=>acceptPlanningDistanceAnnotations(p,"case")',p) is False


def test_seed_preview_and_hidden_source_suppress_only_that_annotation(page):
    install(page)
    page.evaluate('scene3D.meshes.seed_1_1.position.z+=1;renderPlanningDistanceAnnotations()')
    assert page.locator('.planning-distance-tag').count()==2
    page.evaluate('dataTreeState.planning.meshes[0].visible=false;renderPlanningDistanceAnnotations()')
    assert page.locator('.planning-distance-tag').count()==1


def test_dense_view_has_no_overlapping_label_boxes_and_all_records_expand(page,tmp_path):
    install(page,180)
    drawn=page.evaluate('getPlanningDistanceAnnotationLayout().map(x=>x.box)')
    for i,a in enumerate(drawn):
        for b in drawn[i+1:]:
            assert not (a['x']<b['x']+b['w'] and a['x']+a['w']>b['x'] and a['y']<b['y']+b['h'] and a['y']+a['h']>b['y'])
    assert page.locator('.planning-distance-cluster').count()==1
    page.locator('.planning-distance-cluster').click()
    assert page.locator('.planning-distance-list-row').count()==181
    assert page.locator('.planning-distance-list input[type=checkbox]:checked').count()==181
    page.locator('.planning-distance-list-header button').click()
    page.locator('#canvas3D').screenshot(path=str(tmp_path/'distance-annotations-dense.png'))


def test_camera_resize_moves_anchors_but_font_size_stays_screen_owned(page):
    install(page);before=page.evaluate('getPlanningDistanceAnnotationLayout()[0].anchor')
    page.evaluate('scene3D.camera.position.x+=30;scene3D.camera.lookAt(0,0,10);renderPlanningDistanceAnnotations()')
    assert before!=page.evaluate('getPlanningDistanceAnnotationLayout()[0].anchor')
    assert page.evaluate('getComputedStyle(document.querySelector(".planning-distance-overlay text")).fontSize')=='13px'


def test_late_request_cannot_cross_case(page):
    install(page)
    page.evaluate('() => {window.fetch=()=>new Promise(resolve=>window.releaseAnnotations=resolve);window.pending=refreshPlanningDistanceAnnotations();}')
    p=packet(guide=guide(),guide_current=True)
    page.evaluate('activeSessionId="other"')
    page.evaluate('p=>releaseAnnotations({ok:true,json:async()=>({success:true,distance_annotations:p})})',p)
    assert page.evaluate('window.pending') is False


def test_repeat_packet_does_not_repeat_save_or_drop_manual_annotations(page):
    p=install(page); count=page.evaluate('saved.length')
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    assert page.evaluate('saved.length')==count
    assert page.evaluate('state.annotations.filter(r=>r.type==="line").length')==1


def test_automatic_update_waits_for_manual_annotation_transaction(page):
    p=install(page)
    page.evaluate('window.isViewerAnnotationSavePending=()=>true')
    p['records'][0]['tip_distance_mm']=14
    assert page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p) is False
    assert page.evaluate('state.annotations.find(r=>r.type==="planning_distance").tip_distance_mm')==15
    page.evaluate('window.isViewerAnnotationSavePending=()=>false;flushPendingPlanningDistanceAnnotations()')
    assert page.evaluate('state.annotations.find(r=>r.type==="planning_distance").tip_distance_mm')==14
    assert page.evaluate('state.annotations.filter(r=>r.type==="line").length')==1


def test_pending_update_and_overlay_are_cleared_on_case_reset(page):
    p=install(page)
    page.evaluate('window.isViewerAnnotationSavePending=()=>true')
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    page.evaluate('clearPlanningDistanceAnnotationPresentation();activeSessionId="other";window.isViewerAnnotationSavePending=()=>false')
    assert page.locator('.planning-distance-tag').count()==0
    assert page.evaluate('flushPendingPlanningDistanceAnnotations()') is False


def test_3d_visibility_and_alias_use_the_same_durable_record(page):
    p=install(page);sid=p['records'][0]['id']
    page.evaluate('id=>{renameDataTreeNode(id,"My seed");_setNodeViewVisibility(dataTreeState.annotations.find(r=>r.id===id),"3d",false);}',sid)
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    row=page.evaluate('id=>state.annotations.find(r=>r.id===id)',sid)
    assert row['custom_name']=='My seed' and row['visible3D'] is False
    assert page.evaluate('id=>_setNodeViewVisibility(dataTreeState.annotations.find(r=>r.id===id),"2d",true)',sid) is False


def test_real_dom_eye_click_keeps_the_annotation_branch_expanded(page):
    p=install(page);sid=p['records'][0]['id']
    page.locator('.planning-distance-tree').nth(1).evaluate('e=>e.open=true')
    page.locator('.planning-distance-tree').nth(1).locator('details').evaluate('e=>e.open=true')
    page.locator(f'[data-node-id="{sid}"] .eye-btn').click()
    assert page.evaluate('id=>state.annotations.find(r=>r.id===id).visible',sid) is False
    assert page.locator('.planning-distance-tree').nth(1).evaluate('e=>e.open') is True
    assert page.locator('.planning-distance-tree').nth(1).locator('details').evaluate('e=>e.open') is True


def test_selecting_a_label_marks_its_actual_needle_without_editing_geometry(page):
    p=install(page)
    before=page.evaluate('JSON.stringify(dataTreeState.planning.needles)')
    page.evaluate('id=>focusPlanningDistanceAnnotation(id)',p['records'][0]['id'])
    assert page.locator('[data-distance-focus="needle_1"]').count()==1
    assert before==page.evaluate('JSON.stringify(dataTreeState.planning.needles)')


def test_group_show_hide_is_durable_and_does_not_hide_the_guide_family(page):
    p=install(page)
    page.evaluate('setPlanningDistanceAnnotationGroup("seed_tip_distance",null,false)')
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    assert page.locator('.planning-distance-tag').count()==1
    assert page.evaluate('state.annotations.filter(r=>r.kind==="seed_tip_distance").every(r=>r.visible===false)')
    page.evaluate('setPlanningDistanceAnnotationGroup("seed_tip_distance",null,true)')
    assert page.locator('.planning-distance-tag').count()==3


def test_long_alias_is_fitted_without_losing_the_numeric_distance(page):
    p=install(page)
    page.evaluate('id=>setPlanningDistanceAnnotationPresentation(id,{custom_name:"很长的粒子标注名称".repeat(10)})',p['records'][0]['id'])
    texts=page.locator('.planning-distance-tag text').all_text_contents()
    assert any(t.endswith('15.0 mm') for t in texts)
    assert page.evaluate('''() => [...document.querySelectorAll('.planning-distance-tag')].every(g=>{
        const text=g.querySelector('text').getBBox(),box=g.querySelector('rect').getBBox();
        return text.x+text.width <= box.x+box.width-8;
    })''')


def test_authoritative_empty_geometry_removes_old_derived_rows_only(page):
    install(page)
    empty={'planning_id':'plan','planning_version':3,'records':[]}
    assert page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',empty)
    assert page.locator('.planning-distance-tag').count()==0
    assert page.evaluate('state.annotations')==[{'id':'manual_line','type':'line','visible':True}]


def workspace_function(source, name):
    start=source.index('function '+name+'(')
    ending=re.search(r'\n    \}(?:\r?\n|$)',source[start:])
    assert ending, name
    return source[start:start+ending.start()+len('\n    }')]


def real_presentation_registry(page):
    source=(JS/'brachybot-workspace.js').read_text()
    keys=source[source.index('const WORKSPACE_PRESENTATION_KEYS'):source.index('    let workspacePresentationRestore')]
    page.add_script_tag(content='''
        var workspacePresentationRestore=null,deferredPresentationSave=null;
        function jsonClone(x){return JSON.parse(JSON.stringify(x));}
    '''+keys+'\n'+'\n'.join(workspace_function(source,name) for name in [
        'mergePresentationNode','workspacePresentationTree','workspaceSnapshotSessionId',
        '_presentationClone','_presentationRecord','_presentationFamily','_presentationAdd',
        'stageWorkspacePresentation','getWorkspacePresentationForNode','updateWorkspacePresentationForNode',
    ])+'''
        window.getWorkspacePresentationForNode=getWorkspacePresentationForNode;
        window.updateWorkspacePresentationForNode=updateWorkspacePresentationForNode;
    ''')


def test_real_restore_registry_beats_default_placeholder_and_live_edits_are_mirrored(page):
    p=install(page);sid=p['records'][0]['id']
    real_presentation_registry(page)
    page.evaluate('''id=>stageWorkspacePresentation({annotations:[{id,objectId:'annotation:'+id,
        visible:false,visible3D:false,color:'#123456',opacity:.35}]},'case')''',sid)
    # The first resource load already inserted a default; the restore index
    # still owns its saved preference. The real workspace lookup/write code
    # is exercised, not a mock accepting any family name.
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    row=page.evaluate('id=>state.annotations.find(r=>r.id===id)',sid)
    assert row['visible'] is False and row['visible3D'] is False
    assert row['color']=='#123456' and row['opacity']==.35
    page.evaluate('id=>setPlanningDistanceAnnotationPresentation(id,{visible:true,visible3D:true,color:"#abcdef",opacity:.8})',sid)
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    row=page.evaluate('id=>getWorkspacePresentationForNode({id,family:"annotation"})',sid)
    assert row['visible'] is True and row['visible3D'] is True
    assert row['color']=='#abcdef' and row['opacity']==.8


def test_batch_hide_updates_actual_restore_index_and_late_reload_keeps_it(page):
    p=install(page);real_presentation_registry(page)
    page.evaluate("stageWorkspacePresentation({annotations:dataTreeState.annotations},'case')")
    page.evaluate('setPlanningDistanceAnnotationGroup("seed_tip_distance",null,false)')
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    assert page.evaluate('state.annotations.filter(r=>r.kind==="seed_tip_distance").every(r=>r.visible===false)')
    assert page.locator('.planning-distance-tag').count()==1


def test_restored_foreign_case_registry_cannot_supply_current_preferences(page):
    p=install(page);sid=p['records'][0]['id'];real_presentation_registry(page)
    page.evaluate('id=>stageWorkspacePresentation({annotations:[{id,visible:false}]},"other")',sid)
    page.evaluate('p=>acceptPlanningDistanceAnnotations(p)',p)
    assert page.evaluate('id=>state.annotations.find(r=>r.id===id).visible',sid) is True


def test_authoritative_manual_commit_refreshes_distances_once_not_per_preview(page):
    install(page)
    source=(JS/'brachybot-3d-manual.js').read_text()
    page.add_script_tag(content='''
        var manualPlanningState={planningId:'plan',planningVersion:3};
        window._syncManualObjectCounters=()=>{};window._syncManualSafetyState=()=>{};
        window._syncSeedsOverlayFromDataTree=()=>{};
        window.requests=[];window.fetch=async (url,opts)=>{requests.push(url);return {ok:true,json:async()=>({success:true,
            distance_annotations:{planning_id:'plan',planning_version:4,records:[]}})};};
    '''+'\n'.join(function(source,name) for name in ['_dedupeManualSeeds','_dedupeManualNeedles','_applyAuthoritativeManualSeeds']))
    page.evaluate('_applyAuthoritativeManualSeeds({planning_id:"plan",planning_version:4,seeds:[],needles:[]})')
    page.wait_for_function('state.annotations.filter(r=>r.type==="planning_distance").length===0')
    assert page.evaluate('requests.length')==1
    assert page.evaluate('state.annotations.some(r=>r.id==="manual_line")')
