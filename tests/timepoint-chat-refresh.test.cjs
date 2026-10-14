// Production terminal-event timers must restore results, not broaden user intent.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../web/app/static/js/brachybot-chat-todo.js'),'utf8');
(async()=>{
 let selected='A';const timers=[],calls=[],events=[];
 const c=vm.createContext({activeSessionId:'session',console,
  setTimeout:fn=>{timers.push(fn);return timers.length;},
  refreshPlanningUI:async options=>{calls.push(options);return {success:true,planningStatus:'completed',currentDoseReady:true,hasDvh:true};},
  CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
  window:{_sessionPlanningRefreshTimers:{},BrachyBotTimepointWorkspace:{captureRequestScope:s=>s||({timepointId:selected,generation:1}),
   scopeIsCurrent:s=>s.timepointId===selected},dispatchEvent:e=>events.push(e)}});
 vm.runInContext(src.slice(src.indexOf('function _scheduleCasePlanningRefresh('),src.indexOf('function _waitForFinalReplyPaint(')),c);
 assert.equal(c._scheduleCasePlanningRefresh('session'),true);selected='B';
 assert.equal(c._scheduleCasePlanningRefresh('session'),true,'Independent targets cannot coalesce terminal delivery');
 await timers[0]();assert.equal(calls.length,0);
 await timers[1]();assert.equal(calls.length,1);assert.equal(calls[0].timepointScope.timepointId,'B');
 assert.equal(calls[0].autoGenerateGuide,false);assert.equal(calls[0].captureReportFigures,false);
 assert.equal(calls[0].preserveReport,true);assert.equal(events[0].detail.capturePerformed,false);
 assert.equal(events[0].detail.reportCaptureReady,true,'Readiness does not mean unrequested capture was executed');
 let complete;c.window.loadSurgicalGuideMesh=()=>new Promise(resolve=>{complete=resolve;});
 selected='A';assert.equal(c._scheduleCaseSurgicalGuideRefresh('session'),true);
 const oldGuide=timers[2]();selected='B';complete(false);await oldGuide;
 assert.equal(calls.length,1,'Late guide completion cannot refresh B');
 console.log('Timepoint chat refresh effect and ownership contracts passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
