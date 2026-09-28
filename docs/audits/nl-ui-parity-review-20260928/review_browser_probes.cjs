// Inert VM probes using production functions; no server, case or viewer writes.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = process.argv[2] || path.resolve(__dirname, '../../..');
const src = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-ui-api.js'), 'utf8');
function extract(name, async = false) {
  const start = src.indexOf(`${async ? 'async ' : ''}function ${name}(`);
  if (start < 0) throw Error(name);
  return src.slice(start, src.indexOf('\n}', start) + 2);
}
function context(impl) {
  const events = [], executed = [];
  const c = {window: {}, Date, Promise, setTimeout, console,
    _uiActionSessionIsCurrent: () => true, _activeApiSessionId: () => 'case',
    _emitUIActionProgress: e => events.push(e),
    _executeUIAction: async a => { executed.push(a.key); return impl(a); }};
  vm.createContext(c); vm.runInContext(extract('_executeUIActionsWithProgress', true), c);
  return {c, events, executed};
}
(async () => {
  const out = {};
  let t = context(() => ({success:true, completed:false, dispatched:true}));
  await t.c._executeUIActionsWithProgress([{key:'pending',target:'fixture',command:'run'}], {sessionId:'case'});
  out.incomplete_receipt = t.events.map(e => e.status);
  t = context(a => ({success:a.key !== 'producer'}));
  await t.c._executeUIActionsWithProgress([{key:'producer',target:'fixture'}], {sessionId:'case'});
  await t.c._executeUIActionsWithProgress([{key:'consumer',target:'fixture',depends_on:['producer']}], {sessionId:'case'});
  out.cross_batch_failed_dependency = t.executed;
  t = context(() => ({success:true}));
  await t.c._executeUIActionsWithProgress([{key:'consumer',target:'fixture',depends_on:['missing']}], {sessionId:'case',signal:{aborted:true}});
  out.missing_dependency_and_aborted_request = t.executed;
  const el = {id:'fixture',tagName:'BUTTON',type:'button',disabled:false,
    getAttribute:k => k === 'onclick' ? 'queuedJob()' : null, click:()=>{}, dispatchEvent:()=>{}};
  const c = {window:{queuedJob:async()=>({success:true,completed:false,status:'running',job_id:'job-1'})},
    console, _parseUIControlPayload:x=>x, _resolveUIControlElement:()=>el,
    _uiOperationLabel:()=> 'fixture', _uiOperationVisible:()=>true,
    reportUIEvent:()=>{},syncUIBridgeState:()=>{}};
  vm.createContext(c);
  vm.runInContext(src.slice(src.indexOf('async function executeGenericUIControl('),src.indexOf('\nfunction instrumentUIControls(')),c);
  out.queued_job_receipt = await c.executeGenericUIControl('click',{});
  const opacity = {state:{doseOpacity:0.6}};
  vm.createContext(opacity);
  vm.runInContext(extract('_overlayOpacityFraction') + '\n' + extract('_resolveOverlayOpacityPercent'), opacity);
  out.relative_dose_opacity_without_overlay_object = opacity._resolveOverlayOpacityPercent('overlay.dose.opacity','increase',10);
  console.log(JSON.stringify(out,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
