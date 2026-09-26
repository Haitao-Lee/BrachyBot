const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(process.argv[2] || path.resolve(__dirname,
    '../web/app/static/js/brachybot-monitor-interaction.js'), 'utf8');
const messages = new Map(), captures = [];
let session = 'case';
const ctx = {console, window:{}, document:{}, Date,
    trainingMonitorState:{active:true, runId:'run'},
    manualPlanningState:{planningVersion:2, planningId:'p'},
    _activeApiSessionId:()=>session, monitorConversationLanguage:()=> 'zh',
    addChat:(_type,content,_scroll,_at,_from,_session,meta)=>messages.set(meta.messageId,content),
    reportUIEvent:async (...args)=>captures.push(args),
};
vm.createContext(ctx); vm.runInContext(source, ctx);
const packet = (edit, event, version, comparable=false) => ({
    monitor_run_id:'run',language:'zh',event:{type:'manual.seed.drag',event_id:event,detail:{edit_evidence:{
        geometry_event_id:edit,event_id:event,after_version:version,planning_id:'p',restore_token:'abcdef123456',
    }}}, interaction:{headline:'保存成功',dose_note:comparable?'差值覆盖两次编辑':'等待重算',next_step:'检查间距',
        objects:[{id:'seed_1',operation:'moved',distance_mm:2}],metric_rows:comparable?
            [{metric:'V100',before:90,after:91,delta:1,unit:'百分点'}]:[],dose_current:comparable},
    suggested_screenshot:{checkpoint_id:event,object_ids:['seed_1']},
});
(async () => {
    const first = packet('edit1','e1',2);
    await ctx.window.receiveMonitorCheckpoint(first);
    assert.equal(messages.size,1); assert.equal(captures.length,1);
    await ctx.window.receiveMonitorCheckpoint(first);
    assert.equal(captures.length,1,'replayed response cannot recapture');
    ctx.window.updateMonitorCheckpointCapture(first,{success:false,error:'viewer_tab_hidden'});
    assert.match(messages.get(first.monitor_card_id),/后台/);
    ctx.manualPlanningState.planningVersion=3;
    const dose = packet('edit1','dose1',3,true);
    await ctx.window.receiveMonitorCheckpoint(dose);
    assert.equal(messages.size,1,'dose enriches the same edit');
    assert.match(messages.get(first.monitor_card_id),/90.00.*91.00/);
    ctx.window.updateMonitorCheckpointCapture(first,{success:true});
    assert.doesNotMatch(messages.get(first.monitor_card_id),/已核验的图像/,'late image from older revision must not mark new evidence ready');
    ctx.window.updateMonitorCheckpointCapture(dose,{success:true});
    assert.match(messages.get(first.monitor_card_id),/已核验的图像/);
    ctx.manualPlanningState.planningVersion=4;
    const next = packet('edit2','e2',4);
    await ctx.window.receiveMonitorCheckpoint(next);
    assert.equal(messages.size,2,'independent edits retain separate histories');
    assert.match(messages.get(first.monitor_card_id),/入口已关闭/);
    const captureCount = captures.length;
    await ctx.window.receiveMonitorCheckpoint(packet('edit0','late',1));
    assert.equal(captures.length,captureCount,'late old evidence never captures the newer plan');
    session='other-case';
    const before = [...messages.values()].join('');
    ctx.window.updateMonitorCheckpointCapture(next,{success:true});
    assert.equal([...messages.values()].join(''),before,'case switch fences callbacks');
    ctx.trainingMonitorState.runId='new-run';
    await ctx.window.receiveMonitorCheckpoint(packet('edit3','old-run',5));
    assert.equal(captures.length,captureCount,'run switch rejects old checkpoint');
    console.log('Monitor cards: direct delivery, revision updates, duplicate events, partial capture and case/run fencing passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
