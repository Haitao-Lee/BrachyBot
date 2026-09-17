const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = process.argv[2] || path.join(__dirname, '../web/app/static/js');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
function extract(source, name, async = false) {
    const start = source.indexOf(`${async ? 'async ' : ''}function ${name}(`);
    assert(start >= 0, name);
    return source.slice(start, source.indexOf('\n}', start) + 2);
}
async function main() {
    const chat = read('brachybot-chat-todo.js');
    const editor = read('brachybot-report-editor.js');
    const exporter = read('brachybot-report-export.js');
    const c = vm.createContext({Promise, DOMException, console});
    vm.runInContext(extract(chat, '_awaitChatUIActions', true), c);
    let finish;
    let completed = false;
    const operation = new Promise(resolve => { finish = resolve; });
    const gate = c._awaitChatUIActions([operation]).then(result => { completed = true; return result; });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(completed, false, 'dispatch does not complete a browser operation');
    finish({success: true});
    assert.equal((await gate)[0].status, 'fulfilled');
    const controller = new AbortController();
    const cancelled = c._awaitChatUIActions([new Promise(() => {})], controller.signal);
    controller.abort();
    await assert.rejects(cancelled, {name: 'AbortError'});
    assert.equal((await c._awaitChatUIActions([Promise.reject(Error('save failed'))]))[0].status, 'rejected');
    assert(!chat.includes('CHAT_UI_ACTION_MAX_WAIT_MS'));
    let progress;
    const trace = {sessionId:'s',steps:[]};
    const traceContext = vm.createContext({window:{_brachyLiveTrace:trace},activeSessionId:'s',
        document:{addEventListener:(_,fn)=>{progress=fn;}}});
    const listenerStart = chat.indexOf("if (!window._brachyUiTraceListenerReady)");
    vm.runInContext(chat.slice(listenerStart,chat.indexOf('\nfunction _todoCreate',listenerStart)),traceContext);
    progress({detail:{id:'action1',session_id:'s',status:'pending'}});
    progress({detail:{id:'action1',session_id:'s',status:'done'}});
    assert.equal(trace.steps.length,1);
    assert.equal(trace.steps[0].status,'done');

    // Execute the real compositor with hidden dose and opaque label layers.
    const drawn = [];
    const ctx = {save(){},restore(){},fillRect(){},drawImage(layer){drawn.push([layer.id, this.globalAlpha]);}};
    const elements = {};
    for (const id of ['sliceCanvasAxial','labelOverlay_Axial','doseOverlayCanvasAxial',
        'contourCanvasAxial','seedsOverlayCanvasAxial','crosshairCanvasAxial','annotationCanvasAxial']) {
        elements[id] = {id,width:100,height:100,style:{opacity:'1'},dataset:{}};
    }
    elements.doseOverlayCanvasAxial.style = {display:'none',opacity:'0.01'};
    c.document = {getElementById:id=>elements[id],createElement:()=>({getContext:()=>ctx,toDataURL:()=> 'png'})};
    c.window = {getComputedStyle:layer=>layer.style};
    vm.runInContext(extract(exporter, '_composite2DViewerCanvas'), c);
    c._composite2DViewerCanvas('axial', {reportDoseProfile:true,doseOpacity:0.75});
    assert(drawn.some(([id,alpha])=>id==='doseOverlayCanvasAxial' && alpha===0.75));
    assert(!drawn.some(([id])=>/labelOverlay|crosshair|annotation/.test(id)));
    assert.equal(elements.doseOverlayCanvasAxial.style.display, 'none');
    drawn.length = 0;
    c._composite2DViewerCanvas('axial');
    assert(drawn.some(([id])=>id==='labelOverlay_Axial'), 'ordinary screenshots preserve live layers');
    assert(!drawn.some(([id])=>id==='doseOverlayCanvasAxial'));

    vm.runInContext(extract(exporter, '_reportFigureIsInvalidForExport'), c);
    const fig = {axis:'report_fig1_global',figureGroup:'figure1',subfigure:'a',displayMode:'normal_surface'};
    assert.equal(c._reportFigureIsInvalidForExport(fig), false);
    assert.equal(c._reportFigureIsInvalidForExport({...fig,displayMode:'dose_surface'}), true);
    assert.equal(c._reportFigureIsInvalidForExport({...fig,figureGroup:'figure2',subfigure:'d'}), true);
    c.window.reportFigureCaptureContractForAxis = ()=>'new-contract';
    assert.equal(c._reportFigureIsInvalidForExport(fig), true, 'legacy mislabeled captures cannot be exported');

    // Actual watchdog must settle the operation and restore even if capture hangs.
    let watchdog;
    let restored = 0;
    Object.assign(c, {
        setTimeout: fn => {watchdog=fn;return 1;}, clearTimeout(){},
        state:{doseTexture:{enabled:false}},dataTreeState:{planning:{dataVersion:1}},
        _reportCapturePromise:null,_reportCaptureGeneration:1,
        REPORT_CAPTURE_STEP_TOTAL:7,REPORT_CAPTURE_TOTAL_TIMEOUT_MS:180000,
        _currentReportCaptureSessionId:()=> 's',_currentReportCapturePlanningId:()=> 'p',
        reportCaptureAllowed:()=>({allowed:true}),_reportCaptureUiStart:()=>1,
        _reportCaptureUiFinish(){},uiDebugLog(){},
        snapshotReportViewerPresentation:()=>async()=>{restored++;},
        _reportCaptureAwait:async fn=>fn(),
        _autoCaptureReportFiguresImpl:()=>new Promise(()=>{}),
    });
    c.window.reportForm={figures:[{axis:'previous'}]};
    vm.runInContext(extract(editor,'autoCaptureReportFigures',true),c);
    const timeout = c.autoCaptureReportFigures();
    watchdog();
    await assert.rejects(timeout,/timed out/);
    assert.equal(restored,1);
    assert.equal(c._reportCapturePromise,null);
    assert.equal(c.window.__reportCaptureActive,false);
    assert.equal(c.window.reportForm.figures[0].axis,'previous');

    const material = {vertexColors:true,opacity:0.23,transparent:true};
    const mesh = {visible:false,material,traverse(fn){fn(this);}};
    c.scene3D={meshes:{ctv:mesh},requestRender(){}};
    c.state.slices={}; c.state.doseOverlay={visible:false};
    c.state.doseTexture={enabled:false,desiredEnabled:true,restorePending:true};
    vm.runInContext(extract(editor,'snapshotReportViewerPresentation'),c);
    vm.runInContext(extract(editor,'_setReportNormalSurface'),c);
    const restore = c.snapshotReportViewerPresentation();
    c._setReportNormalSurface(mesh);
    assert.equal(material.vertexColors,false);
    mesh.visible=true;material.opacity=1;
    c.state.doseTexture.desiredEnabled=false;
    await restore();
    assert.equal(material.vertexColors,true);
    assert.equal(material.opacity,0.23);
    assert.equal(mesh.visible,false);
    assert.equal(c.state.doseTexture.desiredEnabled,true);
    console.log('PASS: completion/abort/failure, dose-layer composition, slot contracts, watchdog settlement, exact presentation restore');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
