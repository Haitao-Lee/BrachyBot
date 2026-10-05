// Deterministic asynchronous lifecycle checks. No patient, server, or GPU work.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.argv[2] || path.resolve(__dirname,'../web/app/static/js');
const source=fs.readFileSync(path.join(root,'brachybot-monitor-interaction.js'),'utf8');
function harness(){
    let clock=0,seq=0,session='case',geometryCurrent=true;
    const timers=new Map(),listeners={},captures=[],targets=new Map();
    const ctx={console,Date,window:{},document:{hidden:false,addEventListener:(key,fn)=>listeners[key]=fn},
        trainingMonitorState:{active:true,phase:'active',runId:'run'},manualPlanningState:{planningId:'p',planningVersion:2},
        _activeApiSessionId:()=>session,_monitorEvidenceMatchesLiveGeometry:()=>geometryCurrent,
        monitorConversationLanguage:()=> 'en',addChat(){},reportUIEvent:async(...args)=>captures.push(args),
        setTimeout:(fn,delay)=>{timers.set(++seq,{fn,at:clock+delay});return seq;},clearTimeout:id=>timers.delete(id)};
    ctx.window.addEventListener=(key,fn)=>listeners[key]=fn;
    ctx.window.getMonitorTargetAvailability=refs=>refs.map(ref=>({ref,state:'not_loaded',loaded:false,...targets.get(ref)}));
    ctx.window.focusMonitorCheckpoint=()=>false;
    vm.createContext(ctx);vm.runInContext(source,ctx);
    const packet={session_id:'case',monitor_run_id:'run',event:{event_id:'e',type:'manual.seed.drag',detail:{edit_evidence:{
        event_id:'e',geometry_event_id:'edit',planning_id:'p',after_version:2,geometry_key:'g'}}},
        interaction:{spatial_refs:['seed_1','seed_2','seed_3'],objects:[]},suggested_screenshot:{object_ids:['seed_1','seed_2','seed_3']}};
    const tick=async ms=>{clock+=ms;for(const [id,timer] of [...timers])if(timer.at<=clock){timers.delete(id);await timer.fn();}await Promise.resolve();};
    return {ctx,captures,targets,listeners,packet,tick,setSession:value=>session=value,setGeometry:value=>geometryCurrent=value,
        ready:detail=>listeners['brachybot:monitor-resources-ready']({detail:detail || {session_id:session,planning_id:'p',planning_version:2}})};
}
(async()=>{
    const api=fs.readFileSync(path.join(root,'brachybot-ui-api.js'),'utf8');
    const start=api.indexOf('    const settleVisualReady = result => {'),end=api.indexOf('    readinessEntry.resolveReady = settleVisualReady;',start);
    assert(start>=0 && end>start);
    for(const [result,active,expected] of [
        [{ready:true},'case',1], [{ready:false,reason:'visual_restore_partial'},'case',1],
        [{ready:false,reason:'visual_restore_failed'},'case',0],
        [{ready:true,cancelled:true},'case',0], [{ready:true},'other',0],
    ]){
        const notices=[],context={readinessEntry:{settled:false},sessionAtStart:'case',hydrationRunId:'restore',
            resolveVisualReady(){},_activeApiSessionId:()=>active,
            CustomEvent:function(name,options){this.type=name;this.detail=options.detail;},
            window:{__workspaceHydrationRunId:'restore',dispatchEvent:event=>notices.push(event)}};
        vm.createContext(context);vm.runInContext(api.slice(start,end)+'\nthis.settle=settleVisualReady;',context);
        context.settle(result);assert.equal(notices.length,expected,'readiness notices retain actual partial/failure and owner semantics');
        if(result.ready===false)assert.equal(context.readinessEntry.state,'failed','target progress never reclassifies a failed global restore as ready');
    }
    let h=harness(),card=await h.ctx.window.receiveMonitorCheckpoint(h.packet);
    for(const delay of [1500,3000,10000]){h.ctx.window.updateMonitorCheckpointCapture(h.packet,{success:false,error:'monitor_targets_unavailable'});await h.tick(delay);}
    assert.equal(h.captures.length,3,'ordinary timer retries terminate');
    h.targets.set('seed_1',{loaded:false,state:'loading'});h.ready();await h.tick(120);
    assert.equal(h.captures.length,3,'loading flags without live geometry do not trigger capture');
    h.targets.set('seed_1',{loaded:true,state:'visible'});
    h.ready({session_id:'other',planning_id:'p',planning_version:2});await h.tick(120);
    assert.equal(h.captures.length,3,'wrong-case resource completion is ignored');
    h.ready({session_id:'case',planning_id:'p',planning_version:1});await h.tick(120);
    assert.equal(h.captures.length,3,'wrong-version resource completion is ignored');
    h.ready();h.ready();h.ready();await h.tick(120);
    assert.equal(h.captures.length,4,'late real geometry resumes the same card after timer exhaustion');
    assert.equal(card.messageId,h.packet.monitor_card_id,'recovery keeps one message identity');
    h.ctx.window.updateMonitorCheckpointCapture(h.packet,{success:true,attachments:[{target:'viewer-3d'}],omittedTargetRefs:['seed_2','seed_3']});
    h.ready();await h.tick(120);assert.equal(h.captures.length,4,'identical readiness does not recapture a partial result');
    h.targets.set('seed_2',{loaded:true,state:'hidden'});h.ready();await h.tick(120);
    assert.equal(h.captures.length,5,'a newly loaded hidden target may enter the existing temporary capture transaction');
    h.ctx.window.updateMonitorCheckpointCapture(h.packet,{success:true,attachments:[{target:'viewer-3d'}],omittedTargetRefs:['seed_3']});
    h.targets.set('seed_3',{loaded:true,state:'visible'});h.ready();await h.tick(120);
    assert.equal(h.captures.length,5,'readiness recovery is bounded to two resumptions per checkpoint');
    assert.equal(card.captureRecords.length,1,'checkpoint metadata is not counted as additional edits');

    h=harness();card=await h.ctx.window.receiveMonitorCheckpoint(h.packet);
    h.ctx.window.updateMonitorCheckpointCapture(h.packet,{success:false,error:'target_object_not_loaded_in_live_data_tree'});
    h.targets.set('seed_1',{loaded:true,state:'visible'});h.ctx.document.hidden=true;h.ready();await h.tick(120);
    assert.equal(h.captures.length,1,'background geometry completion runs no capture');
    assert.equal(card.captureState,'deferred');h.ctx.document.hidden=false;h.listeners.visibilitychange();await Promise.resolve();
    assert.equal(h.captures.length,2,'foreground resumes the exact deferred revision');

    for(const invalidate of ['session','version','geometry','stop','drag']){
        h=harness();await h.ctx.window.receiveMonitorCheckpoint(h.packet);
        h.ctx.window.updateMonitorCheckpointCapture(h.packet,{success:false,error:'target_object_not_loaded_in_live_data_tree'});
        h.targets.set('seed_1',{loaded:true,state:'visible'});h.ready();
        if(invalidate==='session')h.setSession('other');
        if(invalidate==='version')h.ctx.manualPlanningState.planningVersion=3;
        if(invalidate==='geometry')h.setGeometry(false);
        if(invalidate==='stop')h.ctx.trainingMonitorState.active=false;
        if(invalidate==='drag')h.ctx.manualPlanningState.monitorInteractionActive=true;
        await h.tick(120);assert.equal(h.captures.length,1,`${invalidate} invalidates queued resource recovery`);
    }
    h=harness();card=await h.ctx.window.receiveMonitorCheckpoint(h.packet);
    const commands=[];h.ctx.executeUIContextAction=async payload=>{commands.push(payload);return {success:true};};
    h.ctx.window.getMonitorTargetAvailability=refs=>refs.map(ref=>({ref,nodeId:'seed_1',revealable:true,state:commands.length===2?'visible':'hidden'}));
    h.ctx.window.focusMonitorCheckpoint=()=>true;
    assert.equal(await h.ctx.window.runMonitorCheckpointAction('edit','show_target',{refs:['unrelated']}),false);
    assert.equal(commands.length,0,'unowned refs cannot change presentation');
    h.ctx.trainingMonitorState.screenshotPendingRunId='run';
    assert.equal(await h.ctx.window.runMonitorCheckpointAction('edit','show_target',{refs:['seed_1']}),false);
    assert.equal(commands.length,0,'capture transactions cannot be interrupted by a reveal');
    h.ctx.trainingMonitorState.screenshotPendingRunId=null;
    assert.equal(await h.ctx.window.runMonitorCheckpointAction('edit','show_target',{refs:['seed_1']}),true);
    assert.deepEqual(commands.map(item=>item.action_id),['node_show','node_show_3d'],'explicit reveal shares the existing visibility executors');
    assert.match(card.notice,/color, opacity and plan geometry are unchanged/);
    console.log('Resource readiness: bounded late/partial recovery, real geometry, exact owner/version, background, stop/drag and explicit display fences passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
