const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.argv[2]||__dirname;
function source(name){const nested=path.join(root,'web/app/static/js',name+'.js');return fs.readFileSync(fs.existsSync(nested)?nested:path.join(root,name+'.js'),'utf8');}
const workspace=source('brachybot-workspace'),bridge=source('brachybot-timepoint-workspace'),layout=source('brachybot-viewer-layout'),manual=source('brachybot-3d-manual');
function fn(src,name){const m=new RegExp('^( *)(?:async )?function '+name+'\\(','m').exec(src);assert(m,name);const tail=src.slice(m.index);return tail.slice(0,new RegExp('^'+m[1]+'}','m').exec(tail).index+m[1].length+1);}
const scope={sessionId:'s',timepointId:'t',generation:3};let current=true,saves=0;
const reg={sessionId:'s',timepointScope:scope,active:true,labelImageEdits:{},nodeEdits:new Map(),byFamilyId:{'oar:oar':{},'oar:organ_2':{}}};
const c=vm.createContext({console,Map,Set,JSON,Number,String,Object,activeSessionId:'s',workspacePresentationRestore:reg,
 dataTreeState:{oar:{visible3D:true},organs:[{id:'organ_2',visible3D:true,opacity:.5}]},
 WORKSPACE_PRESENTATION_KEYS:['visible','visible2D','visible3D','opacity','color'],
 _presentationFamily:x=>x,_presentationClone:x=>JSON.parse(JSON.stringify(x)),jsonClone:x=>JSON.parse(JSON.stringify(x)),
 workspaceSnapshotSessionId:x=>x?.session_id||'',
 window:{BrachyBotTimepointWorkspace:{scopeIsCurrent:()=>current}},
});
c.window._findDataTreeNode=id=>c.dataTreeState.organs.find(n=>n.id===id);
for(const name of ['livePresentationRegistry','recordWorkspaceLabelPresentation','withLiveLabelPresentation','applyLiveNodePresentation','updateWorkspacePresentationForNode'])vm.runInContext(fn(workspace,name),c);
let passed=0;
async function test(name,work){await work();console.log('PASS '+name);passed++;}
(async()=>{
 await test('confirmed Session return mounts the invalidated controller; legacy restoration remains available',async()=>{
  let refreshes=0,scheduled=0;
  const x=vm.createContext({window:{BrachyBotTimepoints:{refresh:async()=>{refreshes++;return true;}},
   BrachyBotTimepointWorkspace:{}},scheduleBackgroundWorkspaceRestore:()=>scheduled++});
  vm.runInContext(fn(workspace,'restoreSelectedSessionResources'),x);
  await x.restoreSelectedSessionResources({},'s');assert.equal(refreshes,1);assert.equal(scheduled,0);
  delete x.window.BrachyBotTimepoints;await x.restoreSelectedSessionResources({},'s');assert.equal(refreshes,1);assert.equal(scheduled,1);
 });
 await test('Session scene invalidation revokes the old generation before suspending resource producers',()=>{
  let current=true,owner='old',cancelled=false;
  const x=vm.createContext({mountedId:'t',switching:false,captureTarget:()=>({sessionId:owner}),sidNow:()=> 'new',resetSession:sid=>{owner=sid;current=false;},
   bridge:{suspend:scope=>{assert.equal(scope.sessionId,'old');assert.equal(current,false);cancelled=true;}}});
  vm.runInContext(fn(source('brachybot-timepoints'),'invalidateMount'),x);x.invalidateMount();assert(cancelled);assert.equal(owner,'new');
  x.mountedId='';cancelled=false;assert.equal(x.invalidateMount(),false);assert.equal(cancelled,false);
 });
 await test('a suspended mount suppresses presentation writes instead of falling through to the legacy writer',()=>{
  const x=vm.createContext({registered:true,suspended:true,controller:()=>({enabled:()=>false})});
  vm.runInContext(fn(bridge,'handlePresentationSave'),x);assert.equal(x.handlePresentationSave(),true);
 });
 const snapshot={session_id:'s',timepoint_id:'t',clinical:{immutable:'geometry'},ui:{state:{controls:{labelShow3d:{checked:false}},viewer:{labelImage:{'3d':{visible:false,opacity:.6}},masks:{labels:{saved:{id:'saved'}}}}}}};
 const before=JSON.stringify(snapshot);
 await test('late snapshot preserves explicit LABEL show and opacity without changing clinical data',()=>{
  c.recordWorkspaceLabelPresentation('3d',{visible:true,opacity:.4,configured:true});
  const next=c.withLiveLabelPresentation(snapshot);
  assert.equal(next.ui.state.controls.labelShow3d.checked,true);assert.equal(next.ui.state.controls.labelOp3d.value,'40');
  assert.equal(next.ui.state.viewer.labelImage['3d'].visible,true);assert.equal(next.clinical,snapshot.clinical);
  assert.equal(JSON.stringify(snapshot),before);assert.equal(next.ui.state.viewer.masks,snapshot.ui.state.viewer.masks);
 });
 await test('a later explicit hide wins; untouched views and independent objects keep saved values',()=>{
  c.recordWorkspaceLabelPresentation('3d',{visible:false,opacity:0,configured:true});
  const next=c.withLiveLabelPresentation(snapshot);assert.equal(next.ui.state.viewer.labelImage['3d'].visible,false);
  assert.equal(next.ui.state.viewer.labelImage['3d'].opacity,0);assert.equal(next.ui.state.viewer.labelImage.axial,undefined);
 });
 await test('edits cannot leak to another Session or a stale timepoint mount',()=>{
  const other={...snapshot,session_id:'other'};assert.equal(c.withLiveLabelPresentation(other),other);
  const otherTimepoint={...snapshot,timepoint_id:'other'};assert.equal(c.withLiveLabelPresentation(otherTimepoint),otherTimepoint);
  current=false;assert.equal(c.withLiveLabelPresentation(snapshot),snapshot);assert.equal(c.recordWorkspaceLabelPresentation('3d',{}),false);current=true;
 });
 await test('final tree merge retains explicit parent show and independently hidden child',()=>{
  c.updateWorkspacePresentationForNode({family:'oar',id:'oar'},{visible3D:true});
  c.updateWorkspacePresentationForNode({family:'oar',id:'organ_2'},{visible3D:false,opacity:0});
  c.dataTreeState.oar.visible3D=false;c.dataTreeState.organs[0].visible3D=true;c.applyLiveNodePresentation();
  assert.equal(c.dataTreeState.oar.visible3D,true);assert.equal(c.dataTreeState.organs[0].visible3D,false);assert.equal(c.dataTreeState.organs[0].opacity,0);
 });
 await test('no interaction leaves a saved hidden scene unchanged',()=>{
  reg.labelImageEdits={};assert.equal(c.withLiveLabelPresentation(snapshot),snapshot);
 });
 await test('cold clinical reset restores saved LABEL before the first mesh without requesting a save',()=>{
  const controls={labelShow3d:{checked:false},labelOp3d:{value:'60'}};let reconciled=0;
  c.state={labelImage:{'3d':{visible:false,opacity:.6}}};
  c.document={getElementById:id=>controls[id]};c.normalizePlanningPresentationSnapshot=x=>x;
  c.updateLabelImage=(view,options)=>{assert.equal(options.persist,false);reconciled++;};
  vm.runInContext(fn(workspace,'restoreWorkspaceLabelPresentation'),c);
  const saved={...snapshot,ui:{state:{viewer:{labelImage:{'3d':{visible:true,opacity:.35}}}}}};
  c.restoreWorkspaceLabelPresentation(saved);
  assert.equal(c.state.labelImage['3d'].visible,true);assert.equal(controls.labelShow3d.checked,true);
  assert.equal(controls.labelOp3d.value,'35');assert.equal(reconciled,4);assert.deepEqual(reg.labelImageEdits,{});
 });
 const item={scope,ready:false,workspace:{timepoint_clinical_revision:1,timepoint:{lifecycle_revision:1}},images:{}};
 const b=vm.createContext({console,registered:true,mounted:scope,suspended:false,entry:()=>item,scopeIsCurrent:()=>current,
  controller:()=>({enabled:()=>true,schedulePresentationSave:()=>saves++,observeWorkspace:()=>{}}),
  persistImageAppearance:()=>null,copy:x=>x,status:()=>{},selectDose:async()=>true,
  json:async()=>({workspace:item.workspace}),assertOwner:()=>{},
  window:{hydrateTimepointWorkspace:async()=>({ready:true}),BrachyBotImplants:{reload:async()=>{}}}});
 for(const name of ['handlePresentationSave','hydrateResources'])vm.runInContext(fn(bridge,name),b);
 await test('loading-time save stores intent without serializing an incomplete tree',()=>{
  assert.equal(b.handlePresentationSave({timepointScope:scope}),true);assert.equal(item.presentationSavePending,true);assert.equal(saves,0);
 });
 await test('save flushes once only after full resource and revision readiness',async()=>{
  assert.equal(await b.hydrateResources(item),true);assert.equal(item.ready,true);assert.equal(item.presentationSavePending,false);assert.equal(saves,1);
 });
 await test('failed partial recovery never flushes an incomplete presentation',async()=>{
  item.ready=false;item.presentationSavePending=true;b.window.hydrateTimepointWorkspace=async()=>({ready:false,partial:true});
  assert.equal(await b.hydrateResources(item),false);assert.equal(saves,1);assert.equal(item.presentationSavePending,true);
 });
 await test('silent rediscovery reuses exact mount and data version; explicit/changed meshes still rebuild',async()=>{
  let rebuilt=0;
  const owner={sessionId:'s',generation:5,timepointId:'t',timepointGeneration:3};
  const n={dataVersion:4};
  const k=vm.createContext({console,Map,_organ3DReconstructionInFlight:new Map(),
   _captureViewer3DRequestScope:()=>({sessionId:'s',generation:5}),_viewer3DRequestScopeIsCurrent:()=>true,
   _viewer3DNodeForId:()=>n,_setViewer3DNodeState:()=>{},_normalizeViewer3DResult:x=>x,
   _reconstructOrgan3D:async()=>{rebuilt++;return{success:true};},
   scene3D:{meshes:{skin_surface:{geometry:{},userData:{dataVersion:4,reconstructionOwner:owner}}}},
   window:{BrachyBotTimepointWorkspace:{captureRequestScope:()=>scope}}});
  vm.runInContext(fn(layout,'reconstructOrgan3D'),k);
  assert.equal((await k.reconstructOrgan3D('skin_surface',true)).preserved,true);assert.equal(rebuilt,0);
  await k.reconstructOrgan3D('skin_surface',false);assert.equal(rebuilt,1);
  n.dataVersion=5;await k.reconstructOrgan3D('skin_surface',true);assert.equal(rebuilt,2);
  n.dataVersion=4;owner.timepointGeneration=2;await k.reconstructOrgan3D('skin_surface',true);assert.equal(rebuilt,3);
 });
 await test('late scene mutations cannot take camera ownership during loading',()=>{
  let fits=0;
  const m=vm.createContext({scene3D:{initialized:true,_cameraUserInteracted:true,_workspaceRestoreActive:true,requestRender:()=>{}},
   window:{ensureCameraFitsVisibleScene:()=>fits++},setTimeout:()=>{throw Error('must not schedule an automatic fit');}});
  vm.runInContext(fn(manual,'scheduleCameraFitForSceneMutation'),m);assert.equal(m.scheduleCameraFitForSceneMutation(),false);assert.equal(fits,0);
 });
 await test('late snapshot restores preserve the interacted camera, while a new mount restores its own saved pose',()=>{
  let applied=0;
  const cameraScene={camera:{},requestRender:()=>{}};
  const k=vm.createContext({console,activeSessionId:'s',scene3D:cameraScene,livePresentationRegistry:()=>({timepointScope:scope}),
   scheduleDeferredWorkspaceRestore:()=>{},window:{sync3DCameraPose:()=>applied++}});
  vm.runInContext(fn(workspace,'restoreSceneView'),k);
  const scene={camera_position:[0,0,300],camera_target:[0,0,0]};
  k.restoreSceneView(scene,null,1);assert.equal(applied,1);
  cameraScene._cameraUserInteracted=true;k.restoreSceneView(scene,null,2);
  assert.equal(applied,1);assert.equal(cameraScene._cameraUserInteracted,true);
  k.livePresentationRegistry=()=>({timepointScope:{...scope,timepointId:'other',generation:4}});
  k.restoreSceneView(scene,null,3);assert.equal(applied,2);assert.equal(cameraScene._cameraUserInteracted,false);
 });
 await test('replacement construction failure retains the already displayed surface and its materials',()=>{
  let removed=0,disposed=0;
  const old={geometry:{dispose:()=>disposed++},material:{dispose:()=>disposed++}};
  const k=vm.createContext({console,Float32Array,Uint32Array,Number,
   init3DScene:()=>{},scene3D:{meshes:{organ_1:old},scene:{remove:()=>removed++}},window:{},
   THREE:{BufferGeometry:function(){throw Error('synthetic allocation failure');}}});
  vm.runInContext(fn(manual,'addMeshToScene'),k);
  assert.throws(()=>k.addMeshToScene({organ_id:'organ_1',vertices:[0,0,0,1,0,0,0,1,0],faces:[0,1,2]}),/synthetic allocation/);
  assert.equal(k.scene3D.meshes.organ_1,old);assert.equal(removed,0);assert.equal(disposed,0);
 });
 console.log(passed+' passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
