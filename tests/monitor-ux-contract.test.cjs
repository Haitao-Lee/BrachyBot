const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2] || path.resolve(__dirname,
    '../web/app/static/js/brachybot-monitor-interaction.js'), 'utf8');
function harness() {
    const messages = new Map(), renders = [], captures = [], timers = new Map();
    let writes = 0, serial = 0;
    const ctx = {window: {}, console, Date, document: {hidden: false},
        trainingMonitorState: {active: true, phase: 'active', runId: 'r'},
        manualPlanningState: {planningId: 'p', planningVersion: 1},
        _activeApiSessionId: () => 'c', monitorConversationLanguage: () => 'zh',
        addChat: (_type, content, _s, _at, _from, _session, meta) => { ++writes; messages.set(meta.messageId, content); },
        reportUIEvent: async (...args) => captures.push(args),
        setTimeout: fn => {timers.set(++serial, fn); return serial;},
        clearTimeout: id => timers.delete(id),
    };
    ctx.window.renderMonitorDashboard = cards => renders.push(cards.map(card => ({...card})));
    vm.createContext(ctx); vm.runInContext(source, ctx);
    const packet = (version, edit = `edit${version}`) => ({session_id: 'c', monitor_run_id: 'r', language: 'zh',
        event: {type:'manual.needle.drag', event_id:`event${version}`, detail:{edit_evidence:{geometry_event_id:edit,
            event_id:`event${version}`, planning_id:'p', after_version:version, restore_token:`token${version}`}}},
        interaction: {headline:'编辑已保存', dose_note:'等待剂量', next_step:'查看间距',
            conflict_counts:{resolved:1,existing:2}, related_object_counts:{dependent:3},
            return_movements:[{object_id:'n',endpoint:1,vector_mm:[-3,4,0]}],
            conflicts:[{first_id:'a',second_id:'b',kind:'needle_pairs',change:'new',clearance_basis:'finite_parallel_cylinders',
                surface_clearance_mm:.2,minimum_clearance_mm:.5}], dose_current:false},
        suggested_screenshot:{checkpoint_id:`event${version}`,object_ids:['n']}});
    return {ctx, packet, messages, renders, captures, timers, writes:()=>writes};
}
(async () => {
    let h = harness(), data = h.packet(1), card = await h.ctx.window.receiveMonitorCheckpoint(data);
    let content = h.messages.get(card.messageId);
    assert.match(content,/针道实体表面间隙 0.20 mm/);
    assert.doesNotMatch(content,/轴线距离 0.20/);
    assert.match(content,/尚差 0.30 mm（不是建议移动量）/);
    assert.match(content,/已消除 1 组/); assert.match(content,/2 组在编辑前已存在/);
    assert.match(content,/3 个关联粒子/); assert.match(content,/n 端点 1.*\[-3.00, \+4.00, \+0.00\]/);
    h.ctx.window.updateMonitorCheckpointCapture(data, {success:true});
    assert.equal(card.captureState,'deferred');
    assert.match(h.messages.get(card.messageId),/图像没有写入对话附件/);
    assert.equal(card.captureRecords,undefined,'an accepted plan is not image evidence');
    h.ctx.window.updateMonitorCheckpointCapture(data, {success:true, attachments:[{target:'viewer-3d'}], omittedTargetRefs:['b']});
    assert.equal(card.captureState,'partial');
    assert.match(h.messages.get(card.messageId),/未核验对象：b/);
    assert.equal(card.captureRecords.length,1);
    assert.equal(h.ctx.window.markMonitorEvidenceViewed(card.id),true);
    assert.equal(card.viewedCaptureEventId,card.lastEventId);
    const n = h.renders.length;
    h.ctx.window.resolveMonitorCheckpointDecision('token1',true);
    assert.equal(h.renders.length,n+1,'decision must immediately reach HUD');
    assert.match(h.renders.at(-1)[0].decision,/已保留/);
    assert.equal(card.evidence.restore_token,undefined);

    h.ctx.manualPlanningState.planningVersion=2;
    const dose=h.packet(2, 'edit1'); await h.ctx.window.receiveMonitorCheckpoint(dose);
    assert.equal(card.captureRecords.length,1,'enrichment preserves earlier delivery metadata');
    assert.match(h.messages.get(card.messageId),/先前检查点的图像/);
    h.ctx.window.updateMonitorCheckpointCapture(data,{success:true,attachments:[{}]});
    assert.equal(card.captureState,'pending','an old callback cannot finalize a newer checkpoint');
    h.ctx.window.updateMonitorCheckpointCapture(dose,{success:true,attachments:[{target:'dvh'}]});
    assert.equal(card.captureRecords.length,2,'independent view delivery is additive');

    const skew = h.ctx.window.monitorConflictText({kind:'needle_pairs',surface_clearance_mm:-.2,clearance_basis:'axis_lower_bound'},'en');
    assert.match(skew,/needle axis-model clearance bound/); assert.doesNotMatch(skew,/surface gap/);
    assert.match(h.ctx.window.monitorConflictText({},'zh'),/未核实/);
    assert.doesNotMatch(h.ctx.window.monitorConflictText({},'zh'),/NaN|0.00/);

    h=harness();
    for(let v=1;v<=80;v++) {
        h.ctx.manualPlanningState.planningVersion=v;
        const p=h.packet(v); await h.ctx.window.receiveMonitorCheckpoint(p);
        h.ctx.window.updateMonitorCheckpointCapture(p,{success:false,error:'capture_failed'});
    }
    assert(h.writes() <= 240,`writes ${h.writes()}: prior superseded cards must not repaint per event`);
    assert.equal(h.renders.at(-1).length,40,'resident history is bounded');
    assert.equal(h.timers.size,1,'evicted/superseded retry timers are cancelled');
    assert.equal(h.renders.at(-1).filter(c=>['pending','deferred'].includes(c.captureState)).length,1);
    console.log(JSON.stringify({synthetic_commits:80,chat_upserts:h.writes(),resident_cards:h.renders.at(-1).length,retry_timers:h.timers.size}));
    console.log('Monitor UX contracts: truthful measurements, return vectors, attachments, partial delivery, decisions, bounded repaint/timers passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
