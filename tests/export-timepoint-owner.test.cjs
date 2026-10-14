// Transport/control contract, not numerical or real-browser acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const calls = [];
let mounted = {sessionId:'patient',timepointId:'A',uiLanguage:'en'};
const context = {console,Headers,URL,AbortController,setTimeout,clearTimeout,setInterval,clearInterval,
  document:{documentElement:{lang:'en'},addEventListener(){}},activeSessionId:'patient',
  fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({success:true})}},
  _viewerDataHeaders:sid=>({'X-BrachyBot-Session':sid,'X-BrachyBot-Timepoint':mounted.timepointId})};
context.window=context;context.addEventListener=()=>{};
context.BrachyBotTimepoints={captureSubmission:()=>mounted,
  request:async(scope,url,options={})=>{const headers=new Headers(options.headers);
    headers.set('X-BrachyBot-Session',scope.sessionId);headers.set('X-BrachyBot-Timepoint',scope.timepointId);
    return context.fetch(url,{...options,headers});}};
let source=fs.readFileSync(path.join(__dirname,'../web/app/static/js/brachybot-data-export.js'),'utf8');
source=source.replace('window.openSessionExportDialog = openSessionExportDialog;',
  'window.__ownedExportContract = {state,ownedFetch,fetchJson,sessionHeaders,assertReportOwner}; window.openSessionExportDialog = openSessionExportDialog;');
vm.createContext(context);vm.runInContext(source,context);
(async()=>{
 const api=context.__ownedExportContract;assert.ok(api);
 api.state.sessionId='patient';api.state.ownerScope=Object.freeze({...mounted});
 context.reportForm={sessionId:'patient'};api.assertReportOwner();
 mounted={sessionId:'patient',timepointId:'B',uiLanguage:'en'};
 await api.fetchJson('/api/data/exports/original');
 await api.fetchJson('/api/data/exports/original/cancel',{method:'POST'});
 await api.ownedFetch('/api/data/exports/original/files/source.stl');
 for(const call of calls){assert.equal(call.options.headers.get('X-BrachyBot-Timepoint'),'A');
  assert.equal(call.options.headers.get('X-BrachyBot-Session'),'patient');}
 assert.equal(api.sessionHeaders('patient')['X-BrachyBot-Timepoint'],'A');
 assert.throws(()=>api.assertReportOwner(),/report does not belong/);
 mounted={sessionId:'another-patient',timepointId:'C',uiLanguage:'en'};
 await api.fetchJson('/api/data/exports/original');
 assert.equal(calls.at(-1).options.headers.get('X-BrachyBot-Session'),'patient');
 assert.equal(calls.at(-1).options.headers.get('X-BrachyBot-Timepoint'),'A');
 console.log('Captured export poll, cancel, file download and report ownership contracts passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
