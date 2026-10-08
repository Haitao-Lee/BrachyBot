"""Canvas/DOM regression tests on synthetic CT, never a patient or provider.

The renderer and control executors are product functions. Only unrelated
network/3D/annotation services are stubbed; assertions inspect real pixels.
"""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web/app/static/js"


def function(source, name):
    start = re.search(r"(?:async )?function " + re.escape(name) + r"\(", source).start()
    end = source.index("\n}", start) + 2
    return source[start:end]


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(
            executable_path="/home/lht/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome",
            headless=True, args=["--no-sandbox"],
        )
        p = browser.new_page(viewport={"width": 1000, "height": 800})
        html = '<select id="displayMode"><option value="ct">CT Only</option><option value="overlay">CT+Label</option><option value="label">Label Only</option></select>'
        html += '<input id="overlayCTV" type="checkbox"><input id="overlayOAR" type="checkbox">'
        html += '<button id="showOAR" onclick="setGroupViewVisibility(\'oar\',\'2d\',true)">Show in 2D</button>'
        for axis in ("Axial", "Sagittal", "Coronal"):
            html += f'<div style="position:relative;width:120px;height:120px"><canvas id="sliceCanvas{axis}"></canvas><canvas id="labelOverlay_{axis}"></canvas></div>'
        p.set_content(html)
        p.add_script_tag(content="""
            var activeSessionId='synthetic', API='/api', viewerDataLoadGeneration=0;
            var state={ctPath:'/synthetic.nii',ctLoaded:true,slices:{axial:1,sagittal:0,coronal:0},
                viewerSettings:{window:200,level:0,threshold:null,displayMode:'ct',showCTV:false,showOAR:false},maskLabels:{}};
            var dataTreeState={ctv:{id:'ctv',visible:true,visible2D:true,visible3D:false,opacity:.5},
                oar:{id:'oar',visible:true,visible2D:true,visible3D:false,opacity:.5},
                skin:{id:'skin_surface',visible:false},ctvLabels:{ctv_2:{id:'ctv_2',labelId:2,parentId:'ctv',visible:true,opacity:.5,color:'#ff0000'}},
                organs:[{id:'organ_7',labelId:7,parentId:'oar',visible:true,visible2D:true,visible3D:false,opacity:.5,color:'#0000ff'}],
                planning:{visible:true}, ct:{visible:true}};
            var volumeShape=[2,2,2],volumeSpacing=[1,1,2],volumeData=new Int16Array(8);
            var ctvLabelData=new Uint8Array(8).fill(2),oarLabelData=new Uint16Array(8).fill(7);
            var ctvLabelColorLUT={2:[255,0,0]},oarLabelColorLUT={7:[0,0,255]},skinSurfaceData=null,genericMaskVolumeData={};
            var _pixelBuffer=null,_imageDataBuffer=null,_sliceOverlayJobs={},viewerDataAbortControllers=new Set();
            var sliceCache={axial:{},sagittal:{},coronal:{}},sliceCacheOrder={axial:[],sagittal:[],coronal:[]};
            var saved=[], selected=['oar'];
            window.scheduleWorkspaceSave=(reason)=>saved.push(reason);
            window._scheduleDataTreeSave=window.scheduleWorkspaceSave;
            window.capitalize=x=>x[0].toUpperCase()+x.slice(1);
            window._viewerDataSessionId=()=>activeSessionId;
            window._captureViewerDataScope=()=>({sessionId:activeSessionId,generation:viewerDataLoadGeneration});
            window._viewerDataScopeIsCurrent=s=>s.sessionId===activeSessionId && s.generation===viewerDataLoadGeneration;
            window._viewerDataHeaders=()=>({});
            window._isPlanningDescendantNode=()=>false;
            window._planningItems=()=>[];
            window._findDataTreeNode=id=>id==='oar'?dataTreeState.oar:id==='ctv'?dataTreeState.ctv:null;
            window.getSelectedOrganIds=()=>selected;
            window._isGenericSegmentationMask=()=>false;
            window._genericMaskClassification=()=>'';
            window.syncAnnotationCanvasSize=()=>{};window.redrawAllAnnotations=()=>{};
            window.renderDataTree=()=>{};window.loadAllSlices=()=>{};
            window.applyDataTreeViewVisibility=()=>{};
        """)
        source = (JS / "brachybot-viewer-volume.js").read_text()
        names = ["_clampViewerIndex", "_displayYToVolumeZ", "_viewerAxialDisplayToVolumeZ", "_viewerSliceIndex",
                 "_getMprGeometry", "_dataTreeParentNode", "_dataTreeNodeScopeVisible",
                 "isDataTreeNodeVisible2D", "_rgbForStructureColor", "_ctvLabelPresentation",
                 "_sliceSegmentationPresentation", "_enableSegmentation2DForNodes", "_sourceOverPackedRgba",
                 "_maskVisibleInTarget", "renderSliceFromVolume", "renderOverlayFromVolume", "loadOverlay",
                 "toggleOverlay", "setDisplayMode", "_setNodeViewVisibility", "batchSetViewVisibility",
                 "_groupViewScopeNodes", "setGroupViewVisibility", "_viewerSliceRequestKey",
                 "_cacheViewerSlice", "renderCachedSlice", "loadSlice", "preloadAxis"]
        p.add_script_tag(content="\n".join(function(source, name) for name in names))
        yield p
        browser.close()


def pixel(p, axis="Axial", x=0, y=0, overlay=False):
    prefix = "labelOverlay_" if overlay else "sliceCanvas"
    return p.evaluate("([id,x,y])=>Array.from(document.getElementById(id).getContext('2d').getImageData(x,y,1,1).data)", [prefix+axis,x,y])


@pytest.mark.parametrize("axis", ["axial", "sagittal", "coronal"])
def test_context_show_opens_ct_only_gate_and_paints_all_mpr_planes(page, axis):
    page.click("#showOAR")
    page.evaluate("axis=>renderSliceFromVolume(axis,state.slices[axis])", axis)
    rgba = pixel(page, axis.capitalize())
    assert rgba[2] > rgba[0] == rgba[1]
    assert page.input_value("#displayMode") == "overlay"
    assert page.is_checked("#overlayOAR")
    assert page.evaluate("dataTreeState.oar.visible3D") is False


@pytest.mark.parametrize('axis', ['axial','sagittal','coronal'])
@pytest.mark.parametrize('value,expected', [(999,1),(-3,0)])
def test_client_renderer_clamps_restored_slice_to_current_volume(page, axis, value, expected):
    page.click('#showOAR')
    page.evaluate('({axis,value})=>{state.slices[axis]=value;renderSliceFromVolume(axis,value)}', {'axis':axis,'value':value})
    assert page.evaluate('axis=>state.slices[axis]', axis) == expected
    rgba = pixel(page, axis.capitalize())
    assert rgba[2] > rgba[0] == rgba[1]


def test_group_and_batch_roundtrip_keep_independently_hidden_children(page):
    page.evaluate("""()=>{
        dataTreeState.organs[0].visible2D=false;
        setGroupViewVisibility('oar','2d',false);setGroupViewVisibility('oar','2d',true);
        batchSetViewVisibility('2d',false);batchSetViewVisibility('2d',true);
    }""")
    assert page.evaluate("dataTreeState.organs[0].visible2D") is False
    page.evaluate("renderSliceFromVolume('axial',1)")
    assert pixel(page)[:3] == pytest.approx([127.5,127.5,127.5], abs=.5)


def test_toolbar_overlay_is_2d_only_and_does_not_unhide_master(page):
    page.check("#overlayOAR")
    page.evaluate("toggleOverlay()")
    assert page.evaluate("dataTreeState.oar.visible") is True
    page.uncheck("#overlayOAR"); page.evaluate("toggleOverlay()")
    assert page.evaluate("dataTreeState.oar.visible") is True
    page.evaluate("dataTreeState.oar.visible=false; document.getElementById('displayMode').value='overlay';setDisplayMode()")
    assert page.evaluate("dataTreeState.oar.visible") is False
    assert page.evaluate("saved.length") == 3


def test_ctv_and_oar_share_numeric_label_but_keep_separate_colors_and_order(page):
    page.evaluate("""()=>{
        setGroupViewVisibility('ctv','2d',true);setGroupViewVisibility('oar','2d',true);
        oarLabelData.fill(2);dataTreeState.organs[0].labelId=2;
        renderSliceFromVolume('axial',1);
    }""")
    assert pixel(page)[:3] == pytest.approx([159,32,96], abs=1)
    page.evaluate("dataTreeState.ctvLabels.ctv_2.visible2D=false;renderSliceFromVolume('axial',1)")
    assert pixel(page)[2] > pixel(page)[0]


def test_black_and_zero_channels_are_not_replaced_in_manual_masks_or_skin(page):
    page.evaluate("""()=>{
        ctvLabelData=null;oarLabelData=null;
        state.maskLabels={m:{color:'#000000',opacity:1,visible:true,voxels:new Set(['0,0,0'])}};
        renderSliceFromVolume('axial',1);
    }""")
    assert pixel(page)[:3] == [0,0,0]
    page.evaluate("state.maskLabels={};skinSurfaceData=new Uint8Array(8).fill(1);Object.assign(dataTreeState.skin,{visible:true,color:'#00ff00',opacity:1});renderSliceFromVolume('axial',1)")
    assert pixel(page)[:3] == [0,255,0]


def test_two_translucent_manual_masks_composite_instead_of_losing_second_mask(page):
    page.evaluate("""()=>{
        state.maskLabels={a:{color:'#ff0000',opacity:.5,visible:true,voxels:new Set(['0,0,0'])},
                          b:{color:'#0000ff',opacity:.5,visible:true,voxels:new Set(['0,0,0'])}};
        renderSliceFromVolume('axial',1);
    }""")
    assert pixel(page)[:3] == pytest.approx([96,32,159], abs=1)


def test_png_layer_uses_shared_transform_after_dose_host_creation(page):
    install_png_fetch(page)
    page.evaluate("""()=>{
        const ct=document.getElementById('sliceCanvasAxial');
        ct._doseWrapper={style:{transform:'scale(2) rotate(90deg)'}};
        window._syncExistingSliceLayer=(axis,c)=>{c.style.left='12px';c.style.top='14px'};
        window.applyViewerTransform=axis=>{document.getElementById('labelOverlay_'+capitalize(axis)).style.transform=ct._doseWrapper.style.transform};
    }""")
    page.evaluate("loadOverlay('axial',1)")
    assert page.locator('#labelOverlay_Axial').evaluate('c=>c.style.transform') == 'scale(2) rotate(90deg)'
    assert page.locator('#labelOverlay_Axial').evaluate('c=>c.style.left') == '12px'


def test_label_only_is_blank_without_labels_and_recovers_from_png_opacity(page):
    page.evaluate("ctvLabelData=null;oarLabelData=null;state.viewerSettings.displayMode='label';renderSliceFromVolume('axial',1)")
    assert pixel(page)[:3] == [0,0,0]
    page.evaluate("document.getElementById('sliceCanvasAxial').style.opacity='0';ctvLabelData=new Uint8Array(8).fill(2);setGroupViewVisibility('ctv','2d',true);renderSliceFromVolume('axial',1)")
    assert page.locator("#sliceCanvasAxial").evaluate("c=>c.style.opacity") == "1"
    assert pixel(page)[0] > 0


def install_png_fetch(page, delayed=False):
    page.evaluate("""(delayed)=>{
        volumeData=null;ctvLabelData=null;oarLabelData=null;
        setGroupViewVisibility('oar','2d',true);setGroupViewVisibility('ctv','2d',true);
        const base=document.getElementById('sliceCanvasAxial');base.width=2;base.height=2;
        window.requests=[];window.waiters=[];
        window.fetchViewerJsonWithRetry=async(url,options)=>{
            const body=JSON.parse(options.body);requests.push(body);
            if(delayed)await new Promise(resolve=>waiters.push(resolve));
            const c=document.createElement('canvas');c.width=2;c.height=2;
            const ctx=c.getContext('2d');ctx.fillStyle=body.overlay_type==='ctv'?'rgba(255,0,0,.5)':'rgba(0,0,255,.5)';ctx.fillRect(0,0,2,2);
            return {response:{ok:true},data:{has_mask:true,data:c.toDataURL()}};
        };
    }""", delayed)


def test_png_path_composites_ctv_above_oar_and_sends_exact_view_presentation(page):
    install_png_fetch(page)
    page.evaluate("loadOverlay('axial',1)")
    assert pixel(page, overlay=True) == pytest.approx([170,0,85,192], abs=2)
    requests = page.evaluate("requests")
    assert [r['overlay_type'] for r in requests] == ['oar','ctv']
    assert requests[0]['label_colors']['7'] == [0,0,255]
    assert requests[1]['visible_labels'] == [2]
    assert requests[1]['label_opacities']['2'] == .5


@pytest.mark.parametrize("change", ["hide", "color", "case", "volume"])
def test_pending_same_slice_overlay_cannot_overwrite_new_presentation(page, change):
    install_png_fetch(page, True)
    page.evaluate("()=>{window.pending=loadOverlay('axial',1)}")
    page.wait_for_function("waiters.length===2")
    page.evaluate("""change=>{
        if(change==='hide')setGroupViewVisibility('oar','2d',false);
        if(change==='color')dataTreeState.organs[0].color='#00ff00';
        if(change==='case')activeSessionId='other';
        if(change==='volume'){volumeData=new Int16Array(8);ctvLabelData=new Uint8Array(8);}
        waiters.forEach(resolve=>resolve());
    }""", change)
    page.evaluate("pending")
    assert page.locator("#labelOverlay_Axial").evaluate("c=>c.style.display") == 'none'


def test_window_level_response_and_cached_frame_are_not_reused_after_change(page):
    page.evaluate("""()=>{
        volumeData=null;ctvLabelData=null;oarLabelData=null;
        window.resolveSlice=null;window.frames=[];window.renderSliceToCanvas=(...args)=>frames.push(args);
        window.fetchViewerJsonWithRetry=()=>new Promise(resolve=>resolveSlice=resolve);
        window.pending=loadSlice('axial',1);
        state.viewerSettings.window=400;
        resolveSlice({response:{ok:true},data:{success:true,data:'old-window'}});
    }""")
    page.evaluate("pending")
    assert page.evaluate("frames.length") == 0
    page.evaluate("_cacheViewerSlice('axial',1,'cached',_viewerSliceRequestKey());state.viewerSettings.level=40")
    assert page.evaluate("renderCachedSlice('axial',1)") is False


def test_slice_preload_includes_last_slice_and_cache_is_bounded(page):
    page.evaluate("""async()=>{
        const slider=document.createElement('input');slider.id='sliderAxial';slider.max='2';document.body.appendChild(slider);
        window.requests=[];window.uiDebugLog=()=>{};
        window.fetchViewerJsonWithRetry=async(url,options)=>{requests.push(JSON.parse(options.body).slice_index);return {response:{ok:true},data:{success:true,data:'frame'}}};
        await preloadAxis('axial');
    }""")
    assert page.evaluate("requests") == [0,1,2]
    page.evaluate("for(let i=0;i<100;i++)_cacheViewerSlice('axial',i,'frame',_viewerSliceRequestKey())")
    assert page.evaluate("Object.keys(sliceCache.axial).length") == 64


def test_png_decode_rechecks_window_and_does_not_replace_new_volume_frame(page):
    source = (JS / "brachybot-viewer-layout.js").read_text()
    page.add_script_tag(content=function(source, 'renderSliceToCanvas'))
    page.evaluate("""()=>{
        volumeData=null;window.oldImage=null;
        window.Image=class{constructor(){oldImage=this}set src(value){} };
        renderSliceToCanvas('axial','data:image/png;base64,synthetic',1);
        state.viewerSettings.window=400;
        oldImage.onload();
    }""")
    # Canvas retained its initial dimensions: the obsolete decoder never painted.
    assert page.locator('#sliceCanvasAxial').evaluate('c=>c.width') == 300
