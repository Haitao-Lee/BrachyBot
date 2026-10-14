// Unit interleavings execute the actual product handlers. Controlled transports
// below are unit fixtures, not detector/dose or end-to-end acceptance evidence.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../web/app/static/js/brachybot-viewer-volume.js'),'utf8');
const section=(from,to)=>src.slice(src.indexOf(from),src.indexOf(to,src.indexOf(from)));
function fixture(){
 let current='A',confirm=async()=>true,transport=async()=>({ok:true,json:async()=>({success:true,results:[]})});
 const events=[],scope=()=>({sessionId:'session',timepointScope:{timepointId:current,generation:1}});
 const c=vm.createContext({window:{BrachyBotTimepointWorkspace:{scopeIsCurrent:s=>s.timepointId===current},
  _confirmAction:(...a)=>confirm(...a)},_captureViewerDataScope:scope,_viewerDataSessionId:()=> 'session',
  state:{annotations:[]},selectedItems:{clear:()=>events.push('clear')},pendingDataTreeDeleteIds:new Set(),
  _structureAppearanceMap:()=>({}),_dataTreeObjectId:x=>x,_canonicalDataTreeObjectId:x=>x,
  getSelectedDataTreeIds:()=>['structure:1','structure:2'],
  _viewerDataHeaders:(s,h,t)=>({'X-BrachyBot-Timepoint':t.timepointId}),API:'/api',
  fetch:async(url,init)=>{events.push({url,headers:init.headers});return transport();},
  _dtText:(z,e)=>e,_dataTreeRequestError:()=>Error('request failed'),
  addChat:()=>events.push('chat'),renderDataTree:()=>events.push('render'),
  _refreshAfterDataMutation:async()=>events.push('refresh'),
  reconstructOrgan3D:async id=>{events.push('mesh:'+id);current='B';}});
 vm.runInContext(section('function _dataTreeMutationIsCurrent(', 'async function _refreshAfterDataMutation('),c);
 vm.runInContext(section('async function deleteSelectedDataTreeItems(', 'async function deleteDataTreeGroup('),c);
 vm.runInContext(section('async function batchReconstruct3D(', 'function moveOrganToCategory('),c);
 return {c,events,switch:()=>{current='B';},confirm:f=>{confirm=f;},transport:f=>{transport=f;}};
}
(async()=>{
 const duringConfirm=fixture();duringConfirm.confirm(async()=>{duringConfirm.switch();return true;});
 assert.equal(await duringConfirm.c.deleteSelectedDataTreeItems(['structure:1']),false);
 assert.deepEqual(duringConfirm.events,[],'Confirmation cannot retarget a destructive request');
 const late=fixture();late.transport(async()=>{late.switch();return {ok:true,json:async()=>({success:true,results:[]})};});
 assert.equal(await late.c.deleteSelectedDataTreeItems(['structure:1']),true);
 assert.equal(late.events.length,1,'Committed old-target result cannot repaint or clear new-target selection');
 assert.equal(late.events[0].headers['X-BrachyBot-Timepoint'],'A');
 const batch=fixture();assert.equal(await batch.c.batchReconstruct3D(),false);
 assert.deepEqual(batch.events,['mesh:structure:1'],'Batch cannot continue on another timepoint');
 const current=fixture();assert.equal(await current.c.deleteSelectedDataTreeItems(['structure:1']),true);
 assert.deepEqual(current.events.slice(1),['refresh','clear','chat'],'Current-target handler still completes normally');
 const replan=fixture();replan.c.state.ctPath='image';const execution=[];
 replan.c.window.beginInputAction=()=>({ctPath:'image',current:()=>true,finish:()=>execution.push('finish')});
 replan.c.window.fetchInputJson=async(owner,url,body)=>{execution.push({url,body});return {workflow_state:{seed_planning:true}};};
 replan.c.refreshPlanningUI=async options=>{execution.push(options);return {success:true};};
 vm.runInContext(section('async function replanAfterStructureChange(', 'async function exportSelectedDataTreeItems('),replan.c);
 assert.equal(await replan.c.replanAfterStructureChange('session'),true);
 assert.equal(execution[0].url,'/planning/run_step');assert.equal(execution[0].body.step,'full');
 assert.equal(execution[1].timepointScope.timepointId,'A');assert.equal(execution[1].autoGenerateGuide,false);
 assert.equal(execution[2],'finish','Replan invokes the actual executor rather than only repainting');
 const refresh=fixture();const loads=[];refresh.c.invalidateViewerDataLoads=()=>{};
 refresh.c._adoptPromotedMaskMeshes=()=>refresh.events.push('adopt');refresh.c.reloadOverlays=()=>{};
 refresh.c.requestViewerVisualRefresh=()=>{};
 refresh.c.loadLabelVolumes=options=>new Promise(resolve=>loads.push({options,resolve}));
 vm.runInContext(section('let _genericMaskViewerRefreshTask =', 'async function moveSelectedMasks('),refresh.c);
 const old=refresh.c._scheduleGenericMaskViewerRefresh('session');refresh.switch();
 const next=refresh.c._scheduleGenericMaskViewerRefresh('session');
 assert.equal(loads.length,2,'Different timepoints cannot coalesce label hydration');
 assert.equal(loads[0].options.timepointScope.timepointId,'A');assert.equal(loads[1].options.timepointScope.timepointId,'B');
 loads[0].resolve(true);assert.equal(await old,false);assert.deepEqual(refresh.events,[]);
 loads[1].resolve(true);assert.equal(await next,true);assert.deepEqual(refresh.events,['adopt','render']);
 const inputEvents=[];let selected='A',resolve;
 const input=vm.createContext({API:'/api',state:{ctPath:'image',ctLoaded:true},
  document:{getElementById:()=>({value:'image'}),addEventListener:()=>{}},
  _activeApiSessionId:()=> 'session',fetch:async(url,init)=>{inputEvents.push(init.headers);return new Promise(r=>{resolve=r;});},
  window:{BrachyBotTimepointWorkspace:{captureRequestScope:()=>({timepointId:selected,generation:1}),
   scopeIsCurrent:s=>s.timepointId===selected,headers:(s,h)=>({...h,'X-BrachyBot-Timepoint':s.timepointId})}}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/app/static/js/brachybot-input-actions.js'),'utf8'),input);
 const a=input.window.beginInputAction('full',{mutation:true,image:true});
 const lateInput=input.window.fetchInputJson(a,'/planning/run_step',{step:'full'});
 selected='B';assert.equal(a.current(),false);
 const b=input.window.beginInputAction('full',{mutation:true,image:true});
 a.finish();assert.equal(input.window.inputMutationPending(),true,'Old target completion cannot unlock B');
 resolve({ok:true,status:200,json:async()=>({success:true})});
 assert.equal(await lateInput,null);assert.equal(inputEvents[0]['X-BrachyBot-Timepoint'],'A');
 assert.equal(b.current(),true);b.finish();assert.equal(input.window.inputMutationPending(),false);
 input.window.BrachyBotTimepointWorkspace.resourceState=()=>({images:{planning_reference_image_id:'reference',
   display_image_id:'display',images:[{id:'reference',path:'inputs/reference.nii.gz'},{id:'display',path:'image'}]}});
 const numerical=input.window.beginInputAction('segmentation',{mutation:true,image:true});
 assert.equal(numerical.ctPath,'inputs/reference.nii.gz','Numerical work uses the selected reference, not a sibling backdrop');
 input.fetch=async(url,init)=>{inputEvents.push(JSON.parse(init.body));return {ok:true,status:200,json:async()=>({success:true})};};
 await input.window.fetchInputJson(numerical,'/segmentation',{image_path:numerical.ctPath});
 assert.equal(inputEvents.at(-1).planning_reference_image_id,'reference');numerical.finish();
 console.log('Timepoint data-tree mutation interleaving contracts passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
