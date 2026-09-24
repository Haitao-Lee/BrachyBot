const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2] || path.resolve(__dirname, '../web/app/static/js/brachybot-ui-api.js'), 'utf8');
function extract(name) {
    const start = source.indexOf(`function ${name}(`);
    const ends = ['\nfunction ', '\nasync function '].map(s => source.indexOf(s, start + 12)).filter(n => n > 0);
    return source.slice(source.slice(start - 6, start) === 'async ' ? start - 6 : start, Math.min(...ends));
}
(async () => {
    let captures = 0, success = false;
    const timers = [], notices = [];
    const ctx = { console, API: '/api', window: {}, document: {hidden:false},
        trainingMonitorState: {active:true,runId:'a',lastScreenshotAt:0},
        _activeApiSessionId:()=> 'case', monitorConversationLanguage:()=> 'zh',
        monitorChatText:zh=>zh, _queueMonitorFeedback:()=>true,
        addChat:(...args)=>notices.push(args),
        fetch:async()=>({json:async()=>({monitor_run_id:'a',suggested_screenshot:{target:'viewer-3d'}})}),
        setTimeout:f=>(timers.push(f), timers.length), clearTimeout:()=>{},
        requestAnimationFrame:()=>1, cancelAnimationFrame:()=>{},
        _interceptScreenshot:async()=>{captures++;return {success,attachments:success?[{url:'/shot'}]:[]};},
    };
    vm.createContext(ctx);
    for(const name of ['reportUIEvent','_recordMonitorCaptureFailure','_waitScreenshotFrames']) vm.runInContext(extract(name),ctx);
    const settle = async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();};
    await ctx.reportUIEvent('manual.seed.add','changed');
    await ctx.reportUIEvent('manual.seed.add','changed');
    assert.equal(timers.length,1,'burst must schedule only one capture');
    timers.shift()(); await settle();
    assert.equal(ctx.trainingMonitorState.lastScreenshotAt,0,'failure must not consume throttle');
    assert.equal(notices.length,1,'first missing image must be visible in chat');
    assert.match(notices[0][1],/没有图像附件/);
    await ctx.reportUIEvent('manual.seed.add','changed'); timers.shift()(); await settle();
    assert.equal(notices.length,1,'repeated failures are coalesced');
    success=true;
    await ctx.reportUIEvent('manual.seed.add','changed'); timers.shift()(); await settle();
    assert.ok(ctx.trainingMonitorState.lastScreenshotAt>0);
    assert.equal(ctx.trainingMonitorState.captureFailures,0);
    ctx.document.hidden=true;
    await ctx.reportUIEvent('manual.dose','done');
    assert.equal(timers.length,0,'hidden tabs must not queue captures');
    assert.match(notices.at(-1)[1],/后台/);
    const wait = ctx._waitScreenshotFrames();
    const rejected = assert.rejects(wait,/timed out/);
    timers.shift()(); await rejected;

    const manifest = refs => ({targets: refs.map(ref => ({target_ref:ref,
        loaded:ref !== 'seed_missing', scene_visible:ref !== 'seed_missing',
        data_tree_visible:ref !== 'seed_missing', visible:ref !== 'seed_missing',
        in_view:true, annotatable:true, status:'ready', normalized_bounds:[0.2,0.2,0.2,0.2],
    }))});
    const subsetCtx={window:{get3DScreenshotGroundingManifest:manifest},_screenshotTargetRefs:plan=>plan.object_ids,
        _findDataTreeNode:id=>id==='seed_loaded'?{id}:null,
        _dataTreeRowForTargetRef:()=>null, _groupViewNodes:()=>[],
        _dataTreeParentNode:()=>null,applyDataTreeViewVisibility:()=>{},renderDataTree:()=>{}};
    vm.createContext(subsetCtx);
    for(const name of ['_revealScreenshotNodes','_monitorLiveCaptureRefs','_verifiedScreenshotTargetRefs'])
        vm.runInContext(extract(name),subsetCtx);
    const restored=subsetCtx._revealScreenshotNodes({object_ids:['seed_loaded','seed_missing']});
    assert.deepEqual(Array.from(restored.resolvedTargetRefs),['seed_loaded'],
        'live model object remains available when the Data Tree row is collapsed');
    assert.deepEqual(Array.from(subsetCtx._monitorLiveCaptureRefs(['seed_loaded','seed_missing'])),['seed_loaded']);
    assert.deepEqual(Array.from(subsetCtx._verifiedScreenshotTargetRefs(manifest(['seed_loaded','seed_missing']).targets,
        ['seed_loaded','seed_missing'])),['seed_loaded']);
    restored();

    const uploaded=[], rendered=[], persisted=[];
    const screenshotCtx={console,API:'/api',window:{get3DScreenshotGroundingManifest:manifest,
            ensureAssistantReplyContainer:()=>({}),
            renderAssistantAttachments:(shell,attachments)=>rendered.push(...attachments)},
        document:{},trainingMonitorState:{active:true,runId:'run'},
        manualPlanningState:{planningVersion:4,planningId:'plan'},
        _activeApiSessionId:()=> 'case',
        _normalizeStructuredScreenshotPlan:()=>({mode:'monitor',layout:'auto',views:[{target:'viewer-3d'}],
            visual_purpose:'locate',annotation_policy:'required',object_ids:['seed_loaded','seed_missing'],
            highlight_object_ids:['seed_loaded','seed_missing'],planning_id:'plan',case_id:'case'}),
        _screenshotTargetRefs:plan=>[...new Set([...(plan.target_refs||[]),...(plan.object_ids||[]),
            ...(plan.highlight_object_ids||[])])],
        _orderLocateCaptureViews:(plan,views)=>views,
        _snapshotScreenshotViewerState:()=>({}),
        _revealScreenshotNodes:()=>Object.assign(()=>{},
            {resolvedTargetRefs:['seed_loaded','seed_missing'],unresolvedTargetRefs:[],changed:false}),
        _waitScreenshotFrames:async()=>{}, _prepareScreenshotTarget:async()=>({}),
        _screenshotNeeds3DReframe:()=>false,
        _applyStructuredScreenshotPlan:async()=>({focusResult:{status:'resolved'}}),
        _hideGuideOccludingCtvCapture:()=>null,
        _captureScreenshotEvidenceBundle:async()=>({dataUrl:'data:image/png;base64,AA==',
            groundingManifest:manifest(['seed_loaded','seed_missing'])}),
        _validateScreenshotDataUrl:async()=>true,
        _screenshotPlanIdentity:()=> 'id', _localizedScreenshotTargetLabel:()=> '3D',
        _localizedScreenshotText:()=> '3D', _annotateRequiredScreenshotBeforeDisplay:async item=>item,
        saveSessionMessage:(...args)=>persisted.push(args),scrollToBottom:()=>{},
        _restoreScreenshotViewerState:async()=>{},
        _screenshotFailureMessage:()=> 'capture failed',
        fetch:async(url,options)=>{uploaded.push(JSON.parse(options.body));return {ok:true,
            text:async()=>JSON.stringify({url:'/verified.png',attachment:{id:'a'}})};},
    };
    vm.createContext(screenshotCtx);
    for(const name of ['_monitorLiveCaptureRefs','_verifiedScreenshotTargetRefs',
        '_appendScreenshotToGallery','_interceptScreenshot'])
        vm.runInContext(extract(name),screenshotCtx);
    const gallery={items:[],sessionId:'case',requestId:'monitor-run',messageId:'checkpoint'};
    const result=await screenshotCtx._interceptScreenshot('viewer-3d','where',gallery,
        {monitorOnly:true,sessionId:'case',monitorRunId:'run',monitorPlanningId:'plan',
            monitorPlanningVersion:4});
    assert.equal(result.success,true,'one verified target must produce an image attachment');
    assert.deepEqual(Array.from(result.omittedTargetRefs),['seed_missing']);
    assert.equal(result.attachments.length,1);
    assert.equal(rendered.length,1,'the verified image must be rendered in chat');
    assert.equal(persisted.length,1,'the verified image must be saved in chat history');
    assert.equal(persisted[0][5].attachments[0].url,'/verified.png');
    assert.deepEqual(Array.from(uploaded[0].view_metadata.target_refs),['seed_loaded'],
        'upload metadata must never claim the missing object');
    assert.equal(uploaded[0].view_metadata.grounding_manifest.targets.length,1);
    assert.equal(uploaded[0].view_metadata.grounding_manifest.targets[0].target_ref,'seed_loaded');
    screenshotCtx.window.ensureAssistantReplyContainer=()=>null;
    const notDelivered=await screenshotCtx._interceptScreenshot('viewer-3d','where',
        {items:[],sessionId:'case',requestId:'monitor-run',messageId:'failed-attachment'},
        {monitorOnly:true,sessionId:'case',monitorRunId:'run',monitorPlanningId:'plan',
            monitorPlanningVersion:4});
    assert.equal(notDelivered.success,false,'upload without a chat attachment is not delivery');
    assert.equal(notDelivered.error,'attachment_not_rendered');
    console.log('Monitor capture: failure retry, deduplication, throttle, hidden tab and frame timeout passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
