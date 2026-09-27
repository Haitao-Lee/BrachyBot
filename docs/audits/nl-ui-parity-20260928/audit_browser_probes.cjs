// Executes production functions against inert DOM mocks. Never contacts a server.
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[2] || __dirname;
const src=fs.readFileSync(path.join(root,'web/app/static/js/brachybot-ui-api.js'),'utf8');
const fn=src.slice(src.indexOf('async function executeGenericUIControl('),src.indexOf('\nfunction instrumentUIControls('));
const results=[];
async function probe(name, element, command, payload, extra={}) {
  const events=[];
  const el={id:'test',tagName:'BUTTON',type:'button',disabled:false,min:'',max:'',step:'',value:'',getAttribute:k=>k==='onclick'?'failOperation()':null,getBoundingClientRect:()=>({left:0,top:0,width:100,height:100}),dispatchEvent:e=>events.push(e),click:()=>{},...element};
  const sandbox={window:{failOperation:async()=>({success:false,error:'business_failure'})},_parseUIControlPayload:x=>x,_resolveUIControlElement:()=>el,_uiOperationLabel:()=>name,_uiOperationVisible:()=>true,reportUIEvent:()=>{},syncUIBridgeState:()=>{},console,Event:class {constructor(type,init){this.type=type;Object.assign(this,init)}},MouseEvent:class {constructor(type,init){this.type=type;Object.assign(this,init)}}};
  sandbox.window.WheelEvent=sandbox.MouseEvent;sandbox.window.PointerEvent=sandbox.MouseEvent;
  Object.assign(sandbox,extra); vm.createContext(sandbox); vm.runInContext(fn,sandbox);
  const result=await sandbox.executeGenericUIControl(command,payload);
  results.push({name,result,events});
}
(async()=>{
  await probe('simple_async_failure_is_discarded',{},'click',{});
  await probe('numeric_without_bounds_clamped_to_zero',{tagName:'INPUT',type:'number',value:'12',getAttribute:()=>null},'set',{value:25});
  await probe('ctrl_wheel_loses_modifier',{tagName:'CANVAS',getAttribute:()=>null},'wheel',{ctrlKey:true,deltaY:-120});
  await probe('drag_only_pointer_events',{tagName:'CANVAS',getAttribute:()=>null},'drag',{from:{x:10,y:10},to:{x:40,y:40}});
  await probe('checkbox_string_false_becomes_true',{tagName:'INPUT',type:'checkbox',checked:true,getAttribute:()=>null},'set',{value:'false'});
  let pending=false;
  await probe('argument_handler_not_awaited',{getAttribute:k=>k==='onclick'?"generateGuide('v1')":null,click:()=>{pending=true;}},'click',{});
  results[results.length-1].pendingAfterSuccess=pending;
  const batch=src.slice(src.indexOf('async function _executeUIActionsWithProgress('),src.indexOf('\nwindow._executeUIActionsWithProgress'));
  const executed=[]; const c={window:{},_uiActionSessionIsCurrent:()=>true,_activeApiSessionId:()=> 'case',_emitUIActionProgress:()=>{},_executeUIAction:async a=>{executed.push(a.target);return a.target==='first'?{success:false,error:'test_failure'}:{success:true}},setTimeout,console};
  vm.createContext(c);vm.runInContext(batch,c);const outcome=await c._executeUIActionsWithProgress([{target:'first',command:'run'},{target:'independent_second',command:'run'}],{sessionId:'case'});
  results.push({name:'independent_batch_stops_after_failure',executed,outcome});
  const raw=src.slice(src.indexOf('async function _executeUIActionRaw('),src.indexOf('\n// Screenshot capture'));
  const applied=[];const rawContext={window:{},_activeApiSessionId:()=> 'case',setGroupOpacity:(...a)=>applied.push(a),setDoseOverlayOpacity:(...a)=>applied.push(a),console};
  vm.createContext(rawContext);vm.runInContext(raw,rawContext);
  for (const target of ['overlay.ctv.opacity','overlay.oar.opacity','overlay.dose.opacity']) {
    const result=await rawContext._executeUIActionRaw({target,command:'increase',value:10});
    results.push({name:'relative_opacity_is_absolute',target,result,applied:applied[applied.length-1]});
  }
  const virtual=src.slice(src.indexOf('function _uiOperationVirtualTreeActions('),src.indexOf('\nfunction _uiOperationSceneActions('));
  const virtualContext={_visualCatalogFamily:()=>'',_dataTreeGroupObjectIds:()=>['id']};vm.createContext(virtualContext);vm.runInContext(virtual,virtualContext);
  const nodes=[...Array.from({length:181},(_,i)=>({id:`seed_${i}`,type:'seed',planningId:'plan'})),...Array.from({length:24},(_,i)=>({id:`needle_${i}`,type:'needle',planningId:'plan'})),...Array.from({length:53},(_,i)=>({id:`organ_${i}`,type:'organ'}))];
  const entries=virtualContext._uiOperationVirtualTreeActions(nodes);
  results.push({name:'virtual_catalog_capacity',nodes:nodes.length,virtual_entries:entries.length,cap:4096,note:'excludes DOM, scene actions, guide, dose, manual steps and other artifacts'});
  fs.writeFileSync(path.join(__dirname,'audit_browser_probes.json'),JSON.stringify(results,null,2)); console.log(JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exitCode=1});
