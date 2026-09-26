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
const settle = async () => { for (let i=0;i<20;i++) await Promise.resolve(); };
(async () => {
    const timers=[], captures=[], messages=[];
    let finish, event=1, fetchCount=0;
    const ctx = {console, API:'/api', window:{}, document:{hidden:false},
        trainingMonitorState:{active:true, runId:'r', sessionId:'c', lastScreenshotAt:Date.now()},
        _activeApiSessionId:()=> 'c', monitorConversationLanguage:()=> 'zh', monitorChatText:zh=>zh,
        _queueMonitorFeedback:()=> true, addChat:(...a)=>messages.push(a),
        setTimeout:f=>(timers.push(f),timers.length), clearTimeout:()=>{},
        fetch:async()=> {fetchCount++;return {json:async()=>({monitor_run_id:'r',suggested_screenshot:{
            target:'viewer-3d', object_ids:[`seed${event}`], checkpoint_id:`e${event}`, planning_version:event,
        }})};},
        _interceptScreenshot:async(target,question,context,options)=>{
            captures.push({context,options});
            if(captures.length===1) return new Promise(resolve=>finish=resolve);
            return {success:true,attachments:[{id:'second'}]};
        },
    };
    vm.createContext(ctx);
    for (const name of ['reportUIEvent','_recordMonitorCaptureFailure']) vm.runInContext(extract(name),ctx);
    await ctx.reportUIEvent('manual.seed.drag','move');
    assert.equal(timers.length,1,'edits bypass the ordinary 45s throttle');
    timers.shift()(); await settle();
    event=2;
    await ctx.reportUIEvent('manual.needle.drag','move');
    assert.equal(captures.length,1,'captures never overlap');
    assert.equal(ctx.trainingMonitorState.captureQueue.length,1,'later edit is queued, not dropped');
    event=3;
    await ctx.reportUIEvent('manual.seed.drag','move');
    assert.equal(ctx.trainingMonitorState.captureQueue.length,1,'only the newest pending Viewer pose is retained');
    assert.equal(ctx.trainingMonitorState.captureQueue[0].data.suggested_screenshot.checkpoint_id,'e3');
    finish({success:true,attachments:[{id:'first'}]}); await settle();
    assert.equal(timers.length,1);
    timers.shift()(); await settle();
    assert.equal(captures.length,2);
    assert.equal(fetchCount,3,'queued captures do not replay backend events');
    assert.equal(captures[1].options.plan.object_ids[0],'seed3');
    assert.notEqual(captures[0].context.messageId,captures[1].context.messageId);
    assert.equal(captures[1].options.plan.hide_unrelated,false);
    assert.equal(captures[1].options.plan.annotation_policy,'required');
    assert.equal(captures[1].options.monitorRunId,'r');

    const decisionStart=source.indexOf('window.handleMonitorConversation = async function(text)');
    const decisionEnd=source.indexOf('\nasync function reportUIEvent',decisionStart);
    const calls=[];
    Object.assign(ctx, {
        AbortController,
        document:{getElementById:()=>null},
        fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({success:true,kept:true})};},
        setStreamingState:()=>{}, _flushQueuedChatTurns:()=>{},
    });
    const executorStart=source.indexOf('window.performMonitorEditDecision = async function(');
    assert(executorStart >= 0 && executorStart < decisionStart, 'buttons and chat share a decision executor');
    vm.runInContext(source.slice(executorStart,decisionEnd),ctx);
    for(const text of ['是','复位','如果需要就复位 abcdef123456','他说“复位 abcdef123456”','复位 abcdef123456 然后生成报告']) {
        assert.equal(await ctx.window.handleMonitorConversation(text),false,text);
    }
    assert.equal(calls.length,0);
    ctx.window._chatTurnGeneration = 5;
    assert.equal(await ctx.window.handleMonitorConversation('保留 abcdef123456'),true);
    assert.equal(JSON.parse(calls[0].options.body).decision,'keep');
    assert.equal(ctx.window._chatTurnActive,false);
    // The decision runs inside the normal turn lifecycle: it bumps the
    // generation and releases its abort/cancel handles when it settles.
    assert.equal(ctx.window._chatTurnGeneration,6,'decision owns a fresh generation');
    assert.equal(ctx.window._monitorTurnAbort,null,'abort handle released');
    assert.equal(ctx.window._chatTurnCancelUi,null,'cancel hook released');
    ctx.trainingMonitorState.active=false;
    ctx.fetch=async(url)=>({ok:true,json:async()=>({success:true,active_planning_id:'draft',runs:[
        {planning_id:'original',source:'algorithm',status:'completed'},
        {planning_id:'draft',source:'manual_edit',status:'draft'},
    ]})});
    assert.equal(await ctx.window.handleMonitorConversation('请恢复原来的规划方案'),true);
    assert.match(messages.at(-1)[1],/original/);
    let restored=0;
    ctx.window.restoreAlgorithmPlan=async()=>{restored++;return {success:true,planning_id:'original'};};
    assert.equal(await ctx.window.handleMonitorConversation('恢复原始算法规划'),true);
    assert.equal(restored,1,'only the explicit algorithm restore mutates the plan');
    console.log('Monitor edit interaction: serialized checkpoints, per-edit attachments, explicit decisions, no duplicate telemetry passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
