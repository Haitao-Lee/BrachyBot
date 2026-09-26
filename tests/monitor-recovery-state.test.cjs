const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.argv[2]||path.resolve(__dirname,'../web/app/static/js');
const source=fs.readFileSync(path.join(root,'brachybot-monitor-dashboard.js'),'utf8');
function harness(){
    const timers=[], calls=[];
    const ctx={window:{},document:{getElementById:()=>null},
        trainingMonitorState:{phase:'stop_error',runId:'a'},_activeApiSessionId:()=> 'case',
        setTimeout:fn=>timers.push(fn),clearTimeout(){},
        stopTrainingMode:async()=>{calls.push(ctx.trainingMonitorState.runId);return {success:false};},
    };
    vm.createContext(ctx);vm.runInContext(source,ctx);return {ctx,timers,calls};
}
(async()=>{
    let h=harness();h.ctx.window.queueMonitorStopRecovery('case','a');
    await h.timers.shift()();await h.timers.shift()();
    assert.deepEqual(h.calls,['a','a']);assert.equal(h.timers.length,0,'at most two automatic stop attempts');
    h=harness();h.ctx.window.queueMonitorStopRecovery('case','a');h.ctx.trainingMonitorState.runId='b';
    await h.timers.shift()();assert.equal(h.calls.length,0,'a successor run is never stopped');
    h=harness();h.ctx.window.queueMonitorStopRecovery('case','a');
    h.ctx.stopTrainingMode=async()=>({success:false,run_mismatch:true});
    await h.timers.shift()();assert.equal(h.timers.length,0,'mismatch terminates automatic recovery');
    console.log('Stop recovery: bounded retries, successor ownership and mismatch termination passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
