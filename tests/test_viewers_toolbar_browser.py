"""Real DOM mouse events against product annotation code on synthetic images.

No production session, patient data, provider calls or GPU inference is used.
"""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'web/app/static/js'


def function(source, name):
    start = re.search(r'(?:async )?function ' + name + r'\(', source).start()
    suffix = source[start:]
    end = re.search(r'\n(?:async )?function ', suffix[1:])
    result = suffix[:end.start()+1] if end else suffix
    return result.split('\nwindow.')[0].split('\nconst ')[0].split('\nlet ')[0]


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    chrome = Path('/home/lht/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome')
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=str(chrome), headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1280,'height':900})
        html = (ROOT / 'web/app/index.html').read_text()
        html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html)
        html = re.sub(r'<link\b[^>]*>', '', html)
        page.set_content(html)
        page.add_script_tag(content='''
            window.state={ctLoaded:true,ctPath:'/synthetic.nii.gz',ctShape:[8,8,8],ctSpacing:[1,2,3],
                slices:{axial:3,sagittal:3,coronal:3}, annotations:[],annotationUndoStack:[],annotationRedoStack:[],
                maskLabels:{},maskLabelCounter:0,viewerSettings:{activeTool:null,zoom:1,rotation:0,flipH:false,flipV:false}};
            window.volumeSpacing=[1,2,3]; window.scene3D={meshes:{},requestRender:()=>{}};
            window.saved=[];window.chats=[];window.activeSessionId='synthetic';window.API='/api';
            window._activeApiSessionId=()=>activeSessionId;
            window._t=(zh,en)=>window._i18nLang==='zh'?zh:en;
            window.scheduleWorkspaceSave=x=>saved.push(x);
            window.capitalize=x=>x[0].toUpperCase()+x.slice(1);
            window.getSliceCanvas=axis=>document.getElementById('sliceCanvas'+capitalize(axis));
            window.getAnnotationCanvas=axis=>document.getElementById('annotationCanvas'+capitalize(axis));
            window.renderDataTree=()=>{};window.reloadOverlays=()=>{};window.requestViewerVisualRefresh=()=>{};
            window.addChat=(...x)=>chats.push(x);window.request2DViewerResolutionRefresh=()=>{};
            window._syncExistingSliceLayer=()=>{};window._forEachMaterial=(mesh,fn)=>fn(mesh.material);
            document.getElementById('ctPath').value=state.ctPath;
        ''')
        volume = (JS / 'brachybot-viewer-volume.js').read_text()
        layout = (JS / 'brachybot-viewer-layout.js').read_text()
        page.add_script_tag(content='\n'.join(function(volume, name) for name in
            ['_getMprGeometry','_clampViewerIndex','_viewerAxialDisplayToVolumeZ','_viewerVolumeZToAxialDisplay','_viewerMprImageToVoxel']))
        page.add_script_tag(content=(JS / 'brachybot-manual-annotation.js').read_text())
        page.add_script_tag(content='''
            window.setupBasicInteractions=()=>{};
            window.getMprViewTransform=()=>({zoom:state.viewerSettings.zoom,panX:0,panY:0});
            for(const axis of ['axial','sagittal','coronal']) {
                const canvas=getSliceCanvas(axis); canvas.width=8;canvas.height=8;
                canvas._displayScale=10; canvas._displayW=80;canvas._displayH=80;
                canvas.style.cssText='position:relative;display:block;width:80px;height:80px;';
                const ann=getAnnotationCanvas(axis); ann.width=80;ann.height=80;ann.style.pointerEvents='none';
                setupAnnotationTool(axis);
            }
        ''')
        page.add_script_tag(content=function(layout,'setViewerTool'))
        yield page
        browser.close()


def stroke(page, tool, points, axis='axial'):
    page.evaluate('(tool)=>setViewerTool(tool)', tool)
    page.locator('#sliceCanvas'+axis.capitalize()).scroll_into_view_if_needed()
    box = page.locator('#sliceCanvas'+axis.capitalize()).bounding_box()
    page.mouse.move(box['x']+points[0][0],box['y']+points[0][1]);page.mouse.down()
    for x,y in points[1:]: page.mouse.move(box['x']+x,box['y']+y,steps=2)
    page.mouse.up()


def test_rectangle_runs_and_has_physical_dimensions(page):
    stroke(page,'rect',[(10,10),(40,30)])
    ann=page.evaluate('state.annotations[0]')
    assert ann['type']=='rect'
    assert (ann['x2']-ann['x1'])*ann['spacingX']==pytest.approx(3)
    assert (ann['y2']-ann['y1'])*ann['spacingY']==pytest.approx(4)
    assert ann['sliceIndex']==3


def test_line_is_not_scaled_by_display_zoom(page):
    stroke(page,'measure',[(10,10),(40,10)])
    ann=page.evaluate('state.annotations[0]')
    assert (ann['x2']-ann['x1'])*ann['spacingX']==pytest.approx(3)


def test_draw_and_erase_undo_restore_real_voxels_not_only_lines(page):
    stroke(page,'annotate',[(10,10),(50,10),(50,50),(10,50),(10,10)])
    before=page.evaluate('state.maskLabels[state.activeMaskId].voxels.size')
    assert before > 0
    assert page.evaluate('state.annotationUndoStack.at(-1).type')=='mask_edit'
    page.evaluate('viewerUndo()')
    assert page.evaluate('state.maskLabels[state.activeMaskId].voxels.size')==0
    page.evaluate('viewerRedo()')
    assert page.evaluate('state.maskLabels[state.activeMaskId].voxels.size')==before
    page.evaluate("state.maskLabels.other={voxels:new Set(state.maskLabels[state.activeMaskId].voxels),visible:true}")
    stroke(page,'eraser',[(10,10),(50,10),(50,50),(10,50),(10,10)])
    assert page.evaluate('state.maskLabels[state.activeMaskId].voxels.size')==0
    assert page.evaluate('state.maskLabels.other.voxels.size')==before
    page.evaluate('viewerUndo()')
    assert page.evaluate('state.maskLabels[state.activeMaskId].voxels.size')==before


@pytest.mark.parametrize('rotation', [0,90,180,270])
@pytest.mark.parametrize('flip_h,flip_v', [(False,False),(True,False),(False,True),(True,True)])
def test_screen_inverse_survives_rotation_flip_zoom_and_pan(page,rotation,flip_h,flip_v):
    actual=page.evaluate('''({rotation,flip_h,flip_v})=>{
        Object.assign(state.viewerSettings,{rotation,flipH:flip_h,flipV:flip_v,zoom:2});
        const c=getSliceCanvas('axial'); c.style.transform=_viewerTransformString('axial');
        c.style.transformOrigin='center center';const r=c.getBoundingClientRect();
        const a=rotation*Math.PI/180; const x=(20-40)*2*(flip_h?-1:1), y=(30-40)*2*(flip_v?-1:1);
        return screenToImageCoords('axial',r.left+r.width/2+x*Math.cos(a)-y*Math.sin(a),r.top+r.height/2+x*Math.sin(a)+y*Math.cos(a));
    }''',{'rotation':rotation,'flip_h':flip_h,'flip_v':flip_v})
    assert actual['displayX']==pytest.approx(20)
    assert actual['displayY']==pytest.approx(30)


def test_sat_points_have_voxel_and_slice_identity_and_clear_is_undoable(page):
    stroke(page,'sat3d_positive',[(20,30),(20,30)])
    payload=page.evaluate('sat3dPromptPayload()')
    assert payload['positive_points']==[[4,3,2]]
    page.evaluate('clearSat3dPromptPoints(); viewerUndo()')
    assert page.evaluate('sat3dPromptPayload().positive_points.length')==1
    page.evaluate('viewerRedo()')
    assert page.evaluate('sat3dPromptPayload().positive_points.length')==0


def test_sat_points_cannot_leak_to_a_new_image_in_the_same_case(page):
    stroke(page,'sat3d_positive',[(20,30),(20,30)])
    page.evaluate("state.ctPath='/different_image.nii.gz'")
    assert page.evaluate('sat3dPromptPayload().positive_points.length')==0
    page.evaluate("state.viewerSettings.activeTool=null")
    stroke(page,'sat3d_positive',[(20,30),(20,30)])
    assert page.evaluate('sat3dPromptPayload().positive_points')==[[4,3,2]]


def test_angle_uses_physical_not_anisotropic_pixel_angle(page):
    stroke(page,'angle',[(10,10),(10,10)])
    # Keep the three-click sequence; changing tool is deliberately avoided.
    box=page.locator('#sliceCanvasAxial').bounding_box()
    for x,y in [(30,30),(50,30)]:
        page.mouse.click(box['x']+x,box['y']+y)
    ann=page.evaluate('state.annotations[0]')
    assert ann['type']=='angle'
    assert ann['angleDeg']==pytest.approx(116.56505117707799)


def test_zoom_box_centers_the_selected_region_without_double_scaling_pan(page):
    stroke(page,'zoombox',[(0,0),(30,30)])
    settings=page.evaluate('state.viewerSettings')
    center=page.evaluate('({x:(_annotationToolState.startX+_annotationToolState.currentX)/2,y:(_annotationToolState.startY+_annotationToolState.currentY)/2})')
    assert settings['zoom']==pytest.approx(80/30)
    # Actual DOM mouse coordinates can be rounded at a fractional CSS offset;
    # verify the centered-region invariant, not a guessed pixel origin.
    assert center['x'] + settings['panX']==pytest.approx(40)
    assert center['y'] + settings['panY']==pytest.approx(40)
    assert 'viewer.zoombox' in page.evaluate('saved')


def test_undo_cannot_edit_a_different_cases_mask_with_the_same_id(page):
    stroke(page,'annotate',[(10,10),(50,10),(50,50),(10,50),(10,10)])
    before=page.evaluate('state.maskLabels[state.activeMaskId].voxels.size')
    page.evaluate("activeSessionId='another_case'; viewerUndo()")
    assert page.evaluate('state.maskLabels[state.activeMaskId].voxels.size')==before


def test_wireframe_does_not_reveal_hidden_meshes_or_reset_opacity(page):
    source=(JS/'brachybot-3d-manual.js').read_text()
    page.add_script_tag(content=function(source,'toggle3DWireframe'))
    result=page.evaluate('''()=>{
        scene3D.meshes={hidden:{visible:false,material:{opacity:.23}},shown:{visible:true,material:{opacity:.61}}};
        toggle3DWireframe(true);toggle3DWireframe(false); return Object.values(scene3D.meshes);
    }''')
    assert [m['visible'] for m in result]==[False,True]
    assert [m['material']['opacity'] for m in result]==[.23,.61]


def test_every_viewers_inline_handler_has_an_implementation():
    html=(ROOT/'web/app/index.html').read_text()
    viewers=html[html.index('id="panelViewers"'):html.index('id="loading3D"')]
    implementations='\n'.join(file.read_text() for file in JS.glob('*.js'))
    handlers=re.findall(r'(?:onclick|oninput|onchange)="([^"]+)"',viewers)
    names={re.match(r'([\w]+)\(',handler).group(1) for handler in handlers if re.match(r'([\w]+)\(',handler)}
    assert len(names)>=25
    for name in names:
        assert re.search(r'(?:function\s+'+re.escape(name)+r'\b|window\.'+re.escape(name)+r'\s*=)',implementations), name


def test_sat_workflow_requires_consent_and_fences_case_switch(page):
    page.add_script_tag(content=(JS/'brachybot-sat3d-interaction.js').read_text())
    result=page.evaluate('''async()=>{
        const calls=[];
        window.fetch=async()=>({ok:true,json:async()=>({success:true,models:[{tumor_type:'sat3d_interactive_generic_tumor',site:'unspecified',callable:true}]})});
        state.annotations=[{type:'sat3d_prompt',promptLabel:1,voxelZyx:[4,3,2],imagePath:state.ctPath,imageShape:JSON.stringify(state.ctShape)}];
        window._confirmAction=async()=>{activeSessionId='other';return true};
        window.runSegmentationStep=async(...args)=>{calls.push(args);return {success:true}};
        const result=await runSat3dInteractive();return {result,calls};
    }''')
    assert not result['calls']
    assert result['result']['code']=='cancelled_or_changed_case'


def test_sat_run_uses_interactive_override_and_explicit_ood_consent(page):
    page.add_script_tag(content=(JS/'brachybot-sat3d-interaction.js').read_text())
    result=page.evaluate('''async()=>{
        const calls=[];window.fetch=async()=>({ok:true,json:async()=>({success:true,models:[{tumor_type:'sat3d_interactive_generic_tumor',site:'unspecified',callable:true}]})});
        state.annotations=[{type:'sat3d_prompt',promptLabel:1,voxelZyx:[4,3,2],imagePath:state.ctPath,imageShape:JSON.stringify(state.ctShape)}];
        window._confirmAction=async()=>true;window.runSegmentationStep=async(...args)=>{calls.push(args);return {success:true}};
        await runSat3dInteractive();return calls;
    }''')
    assert result==[['ctv_segmentation',{'tumor_type':'sat3d_interactive_generic_tumor','allow_out_of_distribution':True}]]


def test_sat_manual_request_never_imports_stale_upload_path(page):
    result=page.evaluate('''async()=>{
        document.getElementById('ctvPath').value='/old_uploaded_mask.nii.gz';
        state.annotations=[{type:'sat3d_prompt',promptLabel:1,voxelZyx:[4,3,2],imagePath:state.ctPath,imageShape:JSON.stringify(state.ctShape)}];
        window._saveManualState=()=>{};window._manualWorkflowProgress=()=>{};window.reportUIEvent=()=>{};
        const bodies=[];window._postSegmentationWithHydrationRetry=async(body)=>{
            bodies.push(body);return {response:{ok:true},payload:{success:true,total_labels:1}}};
        window.hydrateCompletedSegmentationArtifacts=async()=>{};
        await runSegmentationStep('ctv_segmentation',{tumor_type:'sat3d_interactive_generic_tumor',allow_out_of_distribution:true});
        return bodies;
    }''')
    assert len(result)==1
    body=result[0]
    assert body['tumor_type']=='sat3d_interactive_generic_tumor'
    assert body['allow_out_of_distribution'] is True
    assert body['positive_points']==[[4,3,2]]
    assert 'label_path' not in body


def test_3d_label_controls_change_only_labels_and_preserve_tree_hiding(page):
    source=(JS/'brachybot-viewer-volume.js').read_text()
    layout=(JS/'brachybot-viewer-layout.js').read_text()
    page.add_script_tag(content='window.getMeshSurface=mesh=>mesh;')
    page.add_script_tag(content=function(layout,'applyMeshVisibility')+'\n'+function(layout,'applyMeshOpacity'))
    page.add_script_tag(content=function(source,'updateLabelImage'))
    result=page.evaluate('''()=>{
        state.labelImage={};
        scene3D.meshes={ctv_1:{visible:true,material:{opacity:.8}},organ_2:{visible:false,material:{opacity:.4}},guide:{visible:true,material:{opacity:.7}}};
        document.getElementById('labelOp3d').value=50;
        document.getElementById('labelShow3d').checked=false;updateLabelImage('3d');
        const hidden=scene3D.meshes.ctv_1.visible;
        document.getElementById('labelShow3d').checked=true;updateLabelImage('3d');
        return {hidden,meshes:scene3D.meshes};
    }''')
    assert result['hidden'] is False
    assert result['meshes']['ctv_1']['visible'] is True
    assert result['meshes']['ctv_1']['material']['opacity']==pytest.approx(.4)
    assert result['meshes']['organ_2']['visible'] is False
    assert result['meshes']['guide']['material']['opacity']==.7


def test_late_tree_edit_or_label_mesh_cannot_bypass_the_group_label_controls(page):
    layout=(JS/'brachybot-viewer-layout.js').read_text()
    page.add_script_tag(content='window.getMeshSurface=mesh=>mesh;')
    page.add_script_tag(content=function(layout,'applyMeshVisibility')+'\n'+function(layout,'applyMeshOpacity'))
    result=page.evaluate('''()=>{
        state.labelImage={'3d':{configured:true,visible:false,opacity:.5}};
        const late={visible:true,userData:{id:'ctv_2'},material:{opacity:.8}};
        applyMeshOpacity(late,.8,true); const hidden=late.visible;
        applyMeshVisibility(late,true,.8); const hiddenAfterEye=late.visible;
        state.labelImage['3d'].visible=true;
        applyMeshOpacity(late,.4,true);
        return {hidden,hiddenAfterEye,visible:late.visible,opacity:late.material.opacity};
    }''')
    assert result=={'hidden':False,'hiddenAfterEye':False,'visible':True,'opacity':.2}
