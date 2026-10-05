// Locale ownership, late delivery and pending decisions without patient data.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.argv[2] || path.resolve(__dirname,'../web/app/static/js');
const api=fs.readFileSync(path.join(root,'brachybot-ui-api.js'),'utf8');
const begin=api.indexOf('function monitorConversationLanguage('),end=api.indexOf('\nfunction monitorChatText(',begin);
assert(begin>=0 && end>begin);
const events=[],messages=new Map();let session='case',jobs=0,releaseDose;
const ctx={console,Date,Map,window:{_i18nLang:'zh',_responseLanguage:'en',conversationLanguageForSession:()=> 'en',
    addEventListener:(name,callback)=>events.push([name,callback])},document:{},
    trainingMonitorState:{active:true,phase:'active',runId:'run',sessionId:'case',language:'en'},
    manualPlanningState:{planningId:'plan',planningVersion:2},_activeApiSessionId:()=>session,
    setMonitorPresentation:()=>{},reportUIEvent:async()=>{throw new Error('a locale flip cannot capture');},
    addChat:(_type,content,_scroll,_at,_restore,_sid,metadata)=>messages.set(metadata.messageId,content),
    recomputeManualDose:()=>{jobs++;return new Promise(resolve=>releaseDose=resolve);},
};
vm.createContext(ctx);vm.runInContext(api.slice(begin,end),ctx);
ctx.window.setMonitorPresentation=ctx.setMonitorPresentation;
assert.equal(ctx.monitorConversationLanguage('case'),'zh','global UI wins over frozen run and response language');
ctx.window._i18nLang='en';ctx.trainingMonitorState.language='zh';ctx.window.conversationLanguageForSession=()=> 'zh';
assert.equal(ctx.monitorConversationLanguage('case'),'en','Chinese user text never changes an English Monitor UI');
ctx.window._i18nLang='zh';
vm.runInContext(fs.readFileSync(path.join(root,'brachybot-monitor-interaction.js'),'utf8'),ctx);
const flip=lang=>{ctx.window._i18nLang=lang;for(const [name,callback] of events)if(name==='i18nchange')callback({detail:{lang}});};
const packet={session_id:'case',monitor_run_id:'run',language:'en',event:{event_id:'e2',type:'manual.seed.drag',detail:{edit_evidence:{
    event_id:'e2',geometry_event_id:'g2',planning_id:'plan',after_version:2,restore_token:'private-token',changed_objects:[],conflicts:[]}}},
    interaction:{language:'en',headline:'Saved',dose_note:'Dose pending',next_step:'Recompute dose',dose_current:false,
        localized:{zh:{headline:'编辑已保存',dose_note:'剂量待更新',next_step:'重算剂量'},en:{headline:'Saved',dose_note:'Dose pending',next_step:'Recompute dose'}}}};
(async()=>{
    const card=await ctx.window.receiveMonitorCheckpoint(packet),identity=card.messageId;
    assert.equal(card.language,'zh','late English backend packet obeys the current global language');
    assert.match(messages.get(identity),/编辑已保存/);assert.doesNotMatch(messages.get(identity),/Dose pending|Recompute dose/);
    const facts=JSON.stringify(packet.event.detail.edit_evidence);
    const pending=ctx.window.runMonitorCheckpointAction(card.id,'dose');
    assert.match(messages.get(identity),/剂量计算中/);assert.equal(jobs,1);
    flip('en');assert.equal(card.language,'en');assert.match(messages.get(identity),/Computing dose/);
    assert.doesNotMatch(messages.get(identity),/剂量计算中|编辑已保存/);
    assert.equal(jobs,1,'switching neither restarts nor cancels an explicitly requested computation');
    releaseDose({success:false});await pending;
    assert.match(messages.get(identity),/Dose recomputation did not complete/);
    flip('zh');assert.match(messages.get(identity),/剂量重算未完成/);
    assert.equal(JSON.stringify(packet.event.detail.edit_evidence),facts,'display language leaves medical facts and restore authorization unchanged');
    assert.equal(messages.size,1,'the same card is translated in place, not duplicated');
    session='other';const old=messages.get(identity);flip('en');assert.equal(messages.get(identity),old,'old-case cards cannot leak into a new case');
    session='case';ctx.document.querySelectorAll=()=>[{dataset:{messageId:'summary'}}];
    ctx.window.addMonitorLocalizedChat('bot-response',{zh:'本轮保存了 2 次编辑。',en:'This run saved 2 edits.'},true,10,false,'case',
        {messageId:'summary',messageKind:'monitor_summary',attachments:[{id:'immutable-image',url:'/evidence.png'}]});
    flip('zh');assert.equal(messages.get('summary'),'本轮保存了 2 次编辑。');
    const size=messages.size;flip('en');assert.equal(messages.get('summary'),'This run saved 2 edits.');
    assert.equal(messages.size,size,'close-out records update in place without a new response');assert.equal(jobs,1);
    const visual=fs.readFileSync(path.join(root,'brachybot-visual-annotation.js'),'utf8');
    const start=visual.indexOf('    function languageFor('),stop=visual.indexOf('\n    function ',start+15);
    const v={window:{_i18nLang:'zh',_responseLanguage:'en'},metadataFor:a=>a.view_metadata || {},normalizeAnnotationLanguage:x=>x,activeSessionIdValue:()=> 'case'};
    vm.createContext(v);vm.runInContext(visual.slice(start,stop),v);
    assert.equal(v.languageFor({mode:'monitor',response_language:'en',question:'English'},{responseLanguage:'en'}),'zh');
    v.window._i18nLang='en';assert.equal(v.languageFor({mode:'monitor',response_language:'zh'}),'en');
    assert.equal(v.languageFor({mode:'chat',response_language:'zh'}),'zh','ordinary chat remains turn-localized');
    assert.equal(v.languageFor({mode:'report',response_language:'zh'}),'zh','report artifact language contract is not broadened');
    console.log('Global Monitor locale: frozen-run/turn overrides rejected, late packets, pending actions and errors relocalized, same identity/facts, no hidden jobs, case fence, ordinary artifact boundaries passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
