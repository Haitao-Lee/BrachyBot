"""Real toolbar/annotation/Tree delete handlers; synthetic CT, no live case."""
from pathlib import Path
import re

import pytest
from test_viewers_toolbar_browser import page, stroke

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT/'web/app/static/js'


def function(source, name):
    start = re.search(r'(?:async )?function '+re.escape(name)+r'\(', source).start()
    return source[start:source.index('\n}', start)+2]


@pytest.fixture
def measurements(page):
    page.add_script_tag(content='''
        window.confirmed=true;window.savedMeasurements=[];window.dialogs=[];
        window._confirmAction=async(...args)=>{dialogs.push(args);return confirmed;};
        window.persistWorkspace=async(reason,options)=>{
            savedMeasurements.push({reason,options,annotations:JSON.parse(JSON.stringify(state.annotations)),treeAnnotations:JSON.parse(JSON.stringify(dataTreeState.annotations))});
            return window.saveResult!==false;
        };
        window.dataTreeState={annotations:[],exportArtifacts:[],planning:{id:'plan',version:2}};
        window.selectedItems=new Set();window.pendingDataTreeDeleteIds=new Set();
        window._viewerDataSessionId=()=>activeSessionId;window._structureAppearanceMap=()=>({});
        window._isDataTreeMaskId=()=>false;window._planningItems=()=>[];
        window._findDataTreeNode=id=>dataTreeState.annotations.find(a=>a.id===id);
        window.getSelectedDataTreeIds=()=>[...selectedItems];window.getSelectedOrganIds=window.getSelectedDataTreeIds;
        window._dtText=(zh,en)=>_t(zh,en);window.positionBrachyContextMenu=()=>{};
        window.escHtml=x=>String(x);window.lastClickedId=null;window.activeContextMenu=null;
        window._runDataTreeAction=p=>Promise.resolve(p).catch(e=>{chats.push(['error',e.message]);return false;});
        window.hideContextMenu=()=>document.querySelector('#ctxMenu')?.remove();
        window.renderDataTree=()=>{reconcileViewerAnnotationNodes();};
    ''')
    source = (JS/'brachybot-viewer-volume.js').read_text()
    page.add_script_tag(content='\n'.join(function(source,n) for n in (
        'ensureDataTreeNodeMetadata','reconcileViewerAnnotationNodes','_dataTreeObjectId',
        '_dataTreeDeleteMenuItem','_dataTreeRequestError',
        'deleteSelectedDataTreeItems','handleTreeItemRightClick','showContextMenu')))
    return page


def line(page):
    if page.evaluate('state.viewerSettings.activeTool')!='measure':
        page.evaluate("setViewerTool('measure')")
    page.locator('#sliceCanvasAxial').scroll_into_view_if_needed()
    box=page.locator('#sliceCanvasAxial').bounding_box()
    page.mouse.move(box['x']+10,box['y']+10);page.mouse.down()
    page.mouse.move(box['x']+40,box['y']+10,steps=2);page.mouse.up()
    return page.evaluate('state.annotations.at(-1).id')


def test_real_context_menu_deletes_a_fresh_unsaved_line_by_durable_identity(measurements):
    page=measurements;target=line(page)
    node=page.evaluate('dataTreeState.annotations[0]')
    assert node['objectId']=='annotation:'+target
    assert node['type']=='manual_annotation' and node['annotationType']=='line'
    assert node['planningId'] is None
    assert '3.0 mm' in node['label']
    page.evaluate('id=>handleTreeItemRightClick(id,{preventDefault(){},stopPropagation(){},clientX:0,clientY:0})',target)
    page.locator('#ctxMenu .ctx-menu-item').filter(has_text='Delete data').click()
    page.wait_for_function('state.annotations.length===0 && savedMeasurements.length===1')
    assert page.evaluate('dataTreeState.annotations.length')==0
    assert page.evaluate('savedMeasurements[0].annotations')==[]
    assert page.evaluate('savedMeasurements[0].treeAnnotations')==[]
    assert page.evaluate('state.annotationUndoStack.at(-1).type')=='annotation_remove'
    page.evaluate('viewerUndo()')
    assert page.evaluate('state.annotations[0].id')==target
    page.evaluate('viewerRedo()')
    assert page.evaluate('state.annotations.length')==0


def test_clear_toolbar_only_removes_measurements_and_is_one_undo_transaction(measurements):
    page=measurements;line(page)
    page.evaluate('''state.annotations.push(
      {id:'angle',type:'angle',axis:'axial',sliceIndex:3,angleDeg:54.9},
      {id:'rect',type:'rect',axis:'axial',sliceIndex:3,x1:1,y1:1,x2:3,y2:3},
      {id:'prompt',type:'sat3d_prompt',axis:'axial',sliceIndex:3,imagePath:state.ctPath,imageShape:JSON.stringify(state.ctShape),voxelZyx:[3,1,1],promptLabel:1},
      {id:'other',type:'freehand',axis:'axial',sliceIndex:3,points:[]});
      state.maskLabels.keep={voxels:new Set(['1,1,1']),visible:true};
      state.activeMaskId='keep';state.seeds=[{id:'seed'}];state.needles=[{id:'needle'}];
      renderDataTree();redrawAllAnnotations();''')
    before=page.evaluate('state.annotations.map(a=>a.id)')
    scheduled=page.evaluate('saved.length')
    page.locator('#toolClearMeasurements').click()
    page.wait_for_function('savedMeasurements.length===1')
    assert page.evaluate('saved.length')==scheduled, 'Scoped removal must not queue a redundant full snapshot'
    assert page.evaluate('state.annotations.map(a=>a.id)')==['prompt','other']
    assert page.evaluate('state.maskLabels.keep.voxels.size')==1
    assert page.evaluate('state.activeMaskId')=='keep'
    assert page.evaluate('state.seeds[0].id')=='seed' and page.evaluate('state.needles[0].id')=='needle'
    assert page.locator('#toolClearMeasurements').is_disabled()
    page.evaluate('viewerUndo()')
    assert page.evaluate('state.annotations.map(a=>a.id)')==before
    page.evaluate('viewerRedo()')
    assert page.evaluate('state.annotations.map(a=>a.id)')==['prompt','other']


def test_cancel_does_not_remove_measurements_or_change_history(measurements):
    page=measurements;target=line(page);page.evaluate('confirmed=false')
    before=page.evaluate('state.annotationUndoStack.length')
    page.locator('#toolClearMeasurements').click();page.wait_for_timeout(50)
    assert page.evaluate('state.annotations[0].id')==target
    assert page.evaluate('state.annotationUndoStack.length')==before
    assert page.evaluate('savedMeasurements.length')==0


def test_failed_save_restores_geometry_and_history_without_claiming_success(measurements):
    page=measurements;target=line(page);page.evaluate('saveResult=false')
    before=page.evaluate('state.annotationUndoStack.length')
    result=page.evaluate('clearViewerMeasurements()')
    assert result['success'] is False
    assert page.evaluate('state.annotations[0].id')==target
    assert page.evaluate('state.annotationUndoStack.length')==before
    assert not page.locator('#toolClearMeasurements').is_disabled()
    assert page.evaluate('chats.at(-1)[0]')=='error'


def test_late_failed_save_cannot_restore_deleted_rows_into_another_case(measurements):
    page=measurements;line(page)
    page.evaluate('''() => {
        persistWorkspace=()=>new Promise(resolve=>window.resolveSave=resolve);
        window.clearPromise=clearViewerMeasurements();
    }''')
    page.wait_for_function('!!window.resolveSave')
    page.evaluate("activeSessionId='another';state.ctPath='/other.nii.gz';state.annotations=[{id:'new-case',type:'line'}];state.annotationUndoStack=[];state.annotationRedoStack=[];")
    page.evaluate('resolveSave(false)')
    result=page.evaluate('window.clearPromise')
    assert result['stale'] and not result['success']
    assert page.evaluate('state.annotations.map(a=>a.id)')==['new-case']
    assert not page.evaluate('chats.length')


def test_reload_legacy_records_can_be_cleared_then_restored_with_stable_ids(measurements):
    page=measurements
    page.evaluate("state.annotations=[{type:'line',axis:'axial',x1:1,y1:1,x2:4,y2:1,spacingX:1,spacingY:1},{id:'legacy',type:'angle',axis:'axial',angleDeg:54.9}];state.annotationUndoStack=[];state.annotationRedoStack=[];renderDataTree();")
    ids=page.evaluate('state.annotations.map(a=>a.id)')
    result=page.evaluate('clearViewerMeasurements()')
    assert result['success'] and result['persisted']
    page.evaluate('viewerUndo()')
    assert page.evaluate('state.annotations.map(a=>a.id)')==ids
    page.evaluate('renderDataTree()')
    assert page.evaluate('dataTreeState.annotations.map(a=>a.objectId)')==['annotation:'+i for i in ids]


def test_unfinished_angle_clear_and_global_chinese_labels(measurements):
    page=measurements
    page.evaluate("_i18nLang='zh';setViewerTool('angle')")
    page.locator('#sliceCanvasAxial').scroll_into_view_if_needed()
    box=page.locator('#sliceCanvasAxial').bounding_box()
    page.mouse.click(box['x']+10,box['y']+10)
    assert not page.locator('#toolClearMeasurements').is_disabled()
    result=page.evaluate('clearViewerMeasurements()')
    assert result['success'] and page.evaluate('_annotationToolState.points.length')==0
    assert page.evaluate('savedMeasurements.length')==0
    line(page);page.evaluate("dispatchEvent(new Event('i18nchange'))")
    assert '线段测距' in page.evaluate('dataTreeState.annotations[0].label')
    assert '保留掩膜' in page.locator('#toolClearMeasurements').get_attribute('title')


@pytest.mark.parametrize('blocked',["document.body.classList.add('workspace-readonly')","state.ctLoaded=false"])
def test_readonly_or_incomplete_restore_cannot_clear_annotations(measurements,blocked):
    page=measurements;target=line(page);page.evaluate(blocked)
    result=page.evaluate('clearViewerMeasurements()')
    assert not result['success']
    assert page.evaluate('state.annotations[0].id')==target
    assert not page.evaluate('savedMeasurements.length')


def test_browser_controller_clear_receipt_uses_the_same_executor(measurements):
    page=measurements;line(page)
    api=(JS/'brachybot-ui-api.js').read_text()
    page.add_script_tag(content=function(api,'_executeUIActionRaw'))
    result=page.evaluate("_executeUIActionRaw({target:'viewer.annotations',command:'clear_measurements'})")
    assert result['success'] and result['persisted'] and result['removed']==1
    assert page.evaluate('state.annotations.length')==0


def test_confirmation_cannot_clear_annotations_after_a_case_switch(measurements):
    page=measurements;line(page)
    page.evaluate('''() => {
        _confirmAction=()=>new Promise(resolve=>window.resolveConfirm=resolve);
        window.clearPromise=clearViewerMeasurements();
    }''')
    page.evaluate("activeSessionId='another';state.annotations=[{id:'new',type:'line'}]")
    page.evaluate('resolveConfirm(true)')
    result=page.evaluate('clearPromise')
    assert result['stale'] and not result['success']
    assert page.evaluate('state.annotations[0].id')=='new'
    assert not page.evaluate('savedMeasurements.length')


def test_durable_ids_do_not_shift_after_deleting_the_first_record(measurements):
    page=measurements;first=line(page);second=line(page)
    assert page.evaluate('deleteViewerAnnotations([state.annotations[0].id])')['success']
    assert page.evaluate('state.annotations[0].id')==second
    page.evaluate('renderDataTree()')
    assert page.evaluate('dataTreeState.annotations[0].objectId')=='annotation:'+second
    assert page.evaluate('deleteViewerAnnotations([state.annotations[0].id])')['success']
    assert not page.evaluate('state.annotations.length')
    assert first!=second


def test_real_global_confirmation_dialog_uses_chinese_and_cancel_is_safe(measurements,tmp_path):
    page=measurements;line(page)
    api=(JS/'brachybot-ui-api.js').read_text()
    page.add_script_tag(content=function(api,'_confirmAction'))
    page.add_style_tag(path=str(ROOT/'web/app/static/css/brachybot-theme-layout.css'))
    page.evaluate("_i18nLang='zh';dispatchEvent(new Event('i18nchange'))")
    page.locator('#toolClearMeasurements').click()
    assert page.locator('#_confirmYes').inner_text()=='清除'
    assert '不会删除掩膜、SAT3D 提示点、针道或粒子' in page.locator('#_confirmYes').locator('..').locator('..').inner_text()
    page.screenshot(path=str(tmp_path/'measurement-clear-confirmation.png'))
    page.locator('#_confirmNo').click()
    assert page.evaluate('state.annotations.length')==1
    assert page.evaluate('savedMeasurements.length')==0
    page.locator('#toolClearMeasurements').click();page.locator('#_confirmYes').click()
    page.wait_for_function('savedMeasurements.length===1')
    assert page.evaluate('state.annotations.length')==0


@pytest.mark.parametrize('target',['viewer.annotations','viewer.transform'])
def test_both_history_controller_routes_do_not_claim_success_for_empty_history(measurements,target):
    api=(JS/'brachybot-ui-api.js').read_text()
    measurements.add_script_tag(content=function(api,'_executeUIActionRaw'))
    result=measurements.evaluate("target=>_executeUIActionRaw({target,command:'undo'})",target)
    assert not result['success']


def test_clear_saving_state_is_visible_and_duplicate_actions_are_blocked(measurements):
    page=measurements;line(page)
    page.evaluate('''() => {
        persistWorkspace=()=>new Promise(resolve=>window.resolveSave=resolve);
        window.clearPromise=clearViewerMeasurements();
    }''')
    page.wait_for_function('!!window.resolveSave')
    assert page.locator('#toolClearMeasurements').inner_text()=='Saving…'
    assert page.locator('#toolClearMeasurements').is_disabled()
    result=page.evaluate('clearViewerMeasurements()')
    assert not result['success'] and result['pending']
    assert not page.evaluate('chats.length')
    assert page.evaluate('deleteViewerAnnotations(["duplicate"])')['pending']
    assert not page.evaluate('deleteSelectedDataTreeItems(["annotation:duplicate"])')
    assert not page.evaluate('chats.length')
    assert page.evaluate('state.annotationUndoStack.filter(x=>x.type==="annotation_remove").length')==1
    page.evaluate('resolveSave(true)');assert page.evaluate('clearPromise')['success']


def test_pending_status_ticks_and_context_delete_is_disabled_not_an_error(measurements,tmp_path):
    page=measurements;target=line(page)
    page.evaluate('''() => {
        persistWorkspace=()=>new Promise(resolve=>window.resolveSave=resolve);
        window.clearPromise=clearViewerMeasurements();
    }''')
    page.wait_for_function('!!window.resolveSave')
    page.wait_for_function('document.querySelector("#toolClearMeasurements").textContent.includes("2s")')
    assert 'No need to click again' in page.locator('#toolClearMeasurements').get_attribute('title')
    page.evaluate("id=>selectedItems.add(id)",target)
    assert 'aria-disabled="true"' in page.evaluate('_dataTreeDeleteMenuItem()')
    assert 'ctx-menu-danger' not in page.evaluate('_dataTreeDeleteMenuItem()')
    for filename in ('brachybot-theme-layout.css','brachybot-panels-viewers.css','brachybot-data-export.css'):
        page.add_style_tag(path=str(ROOT/'web/app/static/css'/filename))
    page.locator('#panelViewers').evaluate("el=>{el.style.display='block';el.scrollIntoView();}")
    page.locator('#toolClearMeasurements').scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path/'annotation-save-pending.png'))
    page.evaluate("_i18nLang='zh';dispatchEvent(new Event('i18nchange'))")
    assert '正在保存' in page.locator('#toolClearMeasurements').inner_text()
    page.evaluate('resolveSave(true)');assert page.evaluate('clearPromise')['success']
    assert page.evaluate('chats.every(row=>row[0]!=="error")')


def test_failed_refresh_and_missing_words_do_not_claim_data_was_deleted(measurements):
    page=measurements
    source=(JS/'brachybot-viewer-volume.js').read_text()
    page.add_script_tag(content=function(source,'_runDataTreeAction'))
    page.evaluate('''() => {window._refreshDataTreeAfterMissingObject=async()=>{window.refreshCount=(window.refreshCount||0)+1;return false;};}''')
    page.evaluate("_runDataTreeAction(Promise.reject(new Error('missing save acknowledgement')))")
    assert page.evaluate('window.refreshCount||0')==0
    assert page.evaluate('chats.at(-1)[0]')=='error'
    page.evaluate("_runDataTreeAction(Promise.reject(_dataTreeRequestError({status:404},{error:'not found'},activeSessionId,'failed')))")
    assert page.evaluate('refreshCount')==1
    assert page.evaluate('chats.at(-1)[0]')=='error'
    page.evaluate('() => {window._refreshDataTreeAfterMissingObject=async()=>true;}')
    page.evaluate("_runDataTreeAction(Promise.reject(_dataTreeRequestError({status:404},{error:'not found'},activeSessionId,'failed')))")
    assert 'could not find' in page.evaluate('chats.at(-1)[1]')
    assert 'no longer exists' not in page.evaluate('chats.at(-1)[1]')


def test_late_data_error_is_not_reconciled_or_reported_in_another_case(measurements):
    page=measurements;source=(JS/'brachybot-viewer-volume.js').read_text()
    page.add_script_tag(content=function(source,'_runDataTreeAction'))
    page.evaluate('''() => {
        window._refreshDataTreeAfterMissingObject=async()=>{throw new Error('must not refresh');};
        window.actionPromise=_runDataTreeAction(new Promise((resolve,reject)=>window.rejectAction=reject));
    }''')
    page.evaluate("activeSessionId='other';rejectAction(_dataTreeRequestError({status:404},{error:'not found'},'case','failed'))")
    assert not page.evaluate('actionPromise')
    assert not page.evaluate('chats.length')


def test_real_missing_refresh_does_not_claim_success_when_a_loader_fails(measurements):
    page=measurements;source=(JS/'brachybot-viewer-volume.js').read_text()
    page.add_script_tag(content=function(source,'_refreshDataTreeAfterMissingObject'))
    page.evaluate('''() => {
        window.invalidateViewerDataLoads=()=>{};
        window.loadLabelVolumes=async()=>{throw Error('offline');};
        window.hydrateDataTreeArtifactCatalog=async()=>true;
        window.reconcileSegmentationViewerState=()=>{};
    }''')
    assert not page.evaluate('_refreshDataTreeAfterMissingObject(activeSessionId)')
    page.evaluate('() => {window.loadLabelVolumes=async()=>true;}')
    assert page.evaluate('_refreshDataTreeAfterMissingObject(activeSessionId)')
    page.evaluate('''() => {
        window.refreshPlanningUI=async()=>({success:false,stage:'planning_results_http'});
    }''')
    assert not page.evaluate('_refreshDataTreeAfterMissingObject(activeSessionId)')
    page.evaluate('''() => {
        window.refreshPlanningUI=async()=>({success:true});
        window.loadLabelVolumes=async options=>{options.registerBackgroundTask(Promise.resolve(false));return true;};
    }''')
    assert not page.evaluate('_refreshDataTreeAfterMissingObject(activeSessionId)')


def test_catalog_failure_is_observable_only_for_strict_reconciliation(measurements):
    page=measurements;source=(JS/'brachybot-viewer-volume.js').read_text()
    page.add_script_tag(content='''let _dataTreeArtifactCatalogSession='';let _dataTreeArtifactCatalogPromise=null;
        window._viewerDataHeaders=()=>({});'''+function(source,'hydrateDataTreeArtifactCatalog'))
    page.route('**/api/data/catalog',lambda route:route.fulfill(status=503,json={'error':'offline'}))
    page.evaluate("window.API='https://synthetic.invalid/api'")
    assert page.evaluate('hydrateDataTreeArtifactCatalog({force:true})')==[]
    assert page.evaluate('hydrateDataTreeArtifactCatalog({force:true,strict:true}).then(()=>false,()=>true)')
