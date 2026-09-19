const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
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
    await ctx.reportUIEvent('manual.seed.add','changed'); timers.shift()(); await settle();
    assert.equal(notices.length,1,'repeated failure produces one visible notice');
    success=true;
    await ctx.reportUIEvent('manual.seed.add','changed'); timers.shift()(); await settle();
    assert.ok(ctx.trainingMonitorState.lastScreenshotAt>0);
    assert.equal(ctx.trainingMonitorState.captureFailures,0);
    ctx.document.hidden=true;
    await ctx.reportUIEvent('manual.dose','done');
    assert.equal(timers.length,0,'hidden tabs must not queue captures');
    const wait = ctx._waitScreenshotFrames();
    const rejected = assert.rejects(wait,/timed out/);
    timers.shift()(); await rejected;
    console.log('Monitor capture: failure retry, deduplication, throttle, hidden tab and frame timeout passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
