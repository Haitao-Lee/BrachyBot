const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path');
const root = process.argv[2] || path.resolve(__dirname, '../web/app/static/js');
const source = fs.readFileSync(path.join(root, 'brachybot-monitor-interaction.js'), 'utf8');
function harness() {
    let now = 0, seq = 0, session = 'case';
    const tasks = new Map(), events = {}, captures = [], doses = [], decisions = [];
    const ctx = {console, window:{}, Date, document:{hidden:false, addEventListener:(name, fn)=>events[name]=fn},
        trainingMonitorState:{phase:'active', active:true, runId:'run'},
        manualPlanningState:{planningVersion:1, planningId:'p'},
        _activeApiSessionId:()=>session, monitorConversationLanguage:()=> 'zh', addChat(){},
        reportUIEvent:async (...args)=>captures.push(args),
        recomputeManualDose:async reason=>{doses.push(reason);return {success:true};},
        setTimeout:(fn, delay)=>{tasks.set(++seq,{fn,at:now+delay});return seq;}, clearTimeout:id=>tasks.delete(id),
    };
    ctx.window.performMonitorEditDecision=async (...args)=>decisions.push(args);
    vm.createContext(ctx); vm.runInContext(source,ctx);
    const tick=async ms=>{
        now+=ms;
        for(const [id, task] of [...tasks]) if(task.at<=now){tasks.delete(id);await task.fn();}
    };
    const packet=(v)=>({session_id:'case',monitor_run_id:'run',language:'zh',
        event:{type:'manual.seed.drag',event_id:`event${v}`,detail:{edit_evidence:{geometry_event_id:`edit${v}`,
            event_id:`event${v}`,after_version:v,planning_id:'p',restore_token:'abcdef123456'}}},
        interaction:{headline:'已保存',dose_current:false,objects:[]},suggested_screenshot:{checkpoint_id:`event${v}`}});
    return {ctx,tick,captures,doses,decisions,packet,events,setSession:value=>session=value};
}
(async()=>{
    let h=harness(), data=h.packet(1); await h.ctx.window.receiveMonitorCheckpoint(data);
    h.ctx.document.hidden=true;
    h.ctx.window.updateMonitorCheckpointCapture(data,{success:false,error:'viewer_tab_hidden'});
    await h.tick(10000); assert.equal(h.captures.length,1,'background does not poll');
    h.ctx.document.hidden=false;h.events.visibilitychange();await Promise.resolve();
    assert.equal(h.captures.length,2,'visibility triggers same checkpoint automatically');
    h.ctx.window.updateMonitorCheckpointCapture(data,{success:false,error:'capture_failed'});
    await h.tick(1500);assert.equal(h.captures.length,3);
    h.ctx.window.updateMonitorCheckpointCapture(data,{success:false,error:'capture_failed'});
    await h.tick(3000);assert.equal(h.captures.length,4);
    h.ctx.window.updateMonitorCheckpointCapture(data,{success:false,error:'capture_failed'});
    await h.tick(10000);assert.equal(h.captures.length,4,'transient retries bounded');

    h=harness();data=h.packet(1);await h.ctx.window.receiveMonitorCheckpoint(data);
    h.ctx.window.updateMonitorCheckpointCapture(data,{success:false,error:'capture_failed'});
    h.ctx.manualPlanningState.planningVersion=2;await h.ctx.window.receiveMonitorCheckpoint(h.packet(2));
    await h.tick(10000);assert.equal(h.captures.length,2,'new edit cancels old retry');
    h.ctx.window.setMonitorAutoCompare(true);
    await h.tick(800);h.ctx.manualPlanningState.planningVersion=3;await h.ctx.window.receiveMonitorCheckpoint(h.packet(3));
    await h.tick(1800);assert.deepEqual(h.doses,['monitor_compare'],'rapid commits coalesce into one dose call');
    await h.tick(10000);assert.equal(h.doses.length,1,'no duplicate compare for same revision');
    await h.ctx.window.runMonitorCheckpointAction('edit3','keep');
    assert.equal(h.decisions[0][0],'abcdef123456');assert.equal(h.decisions[0][1],true);
    h.ctx.manualPlanningState.monitorInteractionActive=true;
    assert.equal(await h.ctx.window.runMonitorCheckpointAction('edit3','restore'),false,'no restore during drag');

    h=harness();await h.ctx.window.receiveMonitorCheckpoint(h.packet(1));h.ctx.window.setMonitorAutoCompare(true);
    h.setSession('other');await h.tick(5000);assert.equal(h.doses.length,0,'case switch fences automatic computation');
    h=harness();await h.ctx.window.receiveMonitorCheckpoint(h.packet(1));h.ctx.window.setMonitorAutoCompare(true);
    h.ctx.trainingMonitorState.active=false;h.ctx.window.refreshMonitorCheckpointPresentation('inactive');
    await h.tick(5000);assert.equal(h.doses.length,0,'stop cancels automatic computation');
    console.log('Dashboard state: bounded retries, visibility resume, supersession, coalesced dose, direct decisions and case/drag/stop fences passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
