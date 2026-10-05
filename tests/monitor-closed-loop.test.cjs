const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../web/app/static/js');
const source=fs.readFileSync(path.join(root,'brachybot-monitor-interaction.js'),'utf8');
function harness(){
    const timers=new Map(),messages=[],captures=[],marks=[],requests=[];let serial=0;
    const ctx={console,window:{},Date,AbortController,API:'/api',document:{hidden:false},
        trainingMonitorState:{active:true,phase:'active',runId:'r'},
        manualPlanningState:{planningId:'p',planningVersion:1},
        _activeApiSessionId:()=> 'c',monitorConversationLanguage:()=> 'zh',
        _monitorEvidenceMatchesLiveGeometry:()=>true,
        setTimeout:(fn,ms)=>{timers.set(++serial,{fn,ms});return serial;},clearTimeout:id=>timers.delete(id),
        addChat:(...args)=>messages.push(args),reportUIEvent:async(...args)=>{captures.push(args);return new Promise(()=>{});},
        fetch:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({success:true,mode:'previous',geometry:{seeds:[{id:'b',position:[0,0,10]}],needles:[]}})}},
    };
    ctx.window.renderMonitorDashboard=()=>{};
    ctx.window.focusMonitorCheckpoint=(...args)=>{marks.push(args);return true;};
    ctx.window.previewMonitorGeometry=(...args)=>{marks.push(args);return true;};
    vm.createContext(ctx);vm.runInContext(source,ctx);
    const packet=()=>({session_id:'c',monitor_run_id:'r',language:'zh',event:{event_id:'e1',type:'manual.seed.drag',detail:{edit_evidence:{
        geometry_event_id:'edit1',event_id:'e1',planning_id:'p',after_version:1,geometry_key:'g',restore_token:'abcdef123456'}}},
        interaction:{schema_version:3,headline:'已保存',next_step:'检查间距',dose_note:'待更新',dose_current:false,spatial_refs:['b'],objects:[]},
        suggested_screenshot:{checkpoint_id:'e1'}});
    return {ctx,timers,messages,captures,marks,requests,packet};
}
(async()=>{
    let h=harness();
    const card=await h.ctx.window.receiveMonitorCheckpoint(h.packet());
    assert.equal(card.id,'edit1','a never-ending image request does not block edit feedback');
    assert.equal(h.messages.length,1);
    assert.equal(h.marks[0][2].reframe,false,'automatic marks preserve the camera');
    assert.equal(h.ctx.window.getMonitorUXMetrics().checkpoint_to_feedback.count,1);
    assert(!JSON.stringify(h.ctx.window.getMonitorUXMetrics()).includes('abcdef'),'no identifiers in timing export');
    assert.equal(await h.ctx.window.runMonitorCheckpointAction(card.id,'preview'),true);
    assert.equal(h.requests[0].body.geometry_key,'g');assert.equal(h.requests[0].body.checkpoint_id,'edit1');
    assert.equal(h.requests[0].body.monitor_run_id,'r');assert.equal(h.requests[0].body.mode,'previous');
    assert.match(card.notice,/未改动规划/);
    assert.equal(await h.ctx.window.runMonitorCheckpointAction(card.id,'apply',{candidateId:'forged'}),false);
    assert.equal(h.requests.length,1,'apply requires a selected server-issued candidate');

    h=harness();const p=h.packet();p.suggested_screenshot=null;
    const c=await h.ctx.window.receiveMonitorCheckpoint(p);
    let computed=0;h.ctx.recomputeManualDose=async()=>{computed++;return {success:true};};
    h.ctx.window.setMonitorAutoCompare(true);
    h.ctx.manualPlanningState.monitorInteractionActive=true;
    let job=[...h.timers.values()].find(t=>t.ms===1800);h.timers.clear();await job.fn();
    assert.equal(computed,0);assert([...h.timers.values()].some(t=>t.ms===1800),'drag defers rather than losing the auto-compare');
    h.ctx.manualPlanningState.monitorInteractionActive=false;h.ctx.window.resumeMonitorInteraction();
    job=[...h.timers.values()].find(t=>t.ms===1800);h.timers.clear();await job.fn();
    assert.equal(computed,1);

    h=harness();const c2=await h.ctx.window.receiveMonitorCheckpoint(h.packet());
    let resolve;h.ctx.fetch=()=>new Promise(done=>resolve=done);
    const pending=h.ctx.window.runMonitorCheckpointAction(c2.id,'preview');
    h.ctx.manualPlanningState.planningVersion=2;
    resolve({ok:true,json:async()=>({success:true,geometry:{seeds:[{id:'b',position:[99,99,99]}]}})});
    assert.equal(await pending,false);assert.equal(h.marks.length,1,'late preview cannot draw into a newer revision');

    const ui=fs.readFileSync(path.join(root,'brachybot-ui-api.js'),'utf8');
    const begin=ui.indexOf('window.performMonitorEditDecision = async function('),end=ui.indexOf('\nasync function reportUIEvent',begin);
    h=harness();vm.runInContext(ui.slice(begin,end),h.ctx);
    for(const query of ['刚刚变好了吗','如何调整这根针道','请解释这次变化，不要修改'])
        assert.equal(await h.ctx.window.handleMonitorConversation(query),false,'semantic questions must not be intercepted by keyword templates');
    assert.equal(h.requests.length,0);
    console.log('Closed-loop: nonblocking feedback, camera-preserving marks, owner-fenced previews, explicit apply, drag-resumed compare, timing privacy and semantic routing passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
