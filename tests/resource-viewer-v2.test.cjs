const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const test=require('node:test'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.resolve(__dirname,'../web/app/static/js/brachybot-3d-manual.js'),'utf8');
function segment(start,end){const a=source.indexOf(start),b=source.indexOf(end,a+start.length);assert(a>=0&&b>a);return source.slice(a,b);}
function deferred(){let resolve;return {promise:new Promise(r=>resolve=r),resolve};}

test('label statistics scan each immutable volume once and follow replacement buffers',()=>{
 const volume=fs.readFileSync(path.resolve(__dirname,'../web/app/static/js/brachybot-viewer-volume.js'),'utf8');
 const begin=volume.indexOf('const _labelVolumeCounts = new WeakMap();'),end=volume.indexOf('\n}',begin)+2;
 const c={Map,WeakMap,Number};vm.createContext(c);vm.runInContext(volume.slice(begin,end),c);
 let reads=0;const a={length:4,get 0(){reads++;return 0;},get 1(){reads++;return 10000;},get 2(){reads++;return 2;},get 3(){reads++;return 10000;}};
 assert.deepEqual([...c.getLabelVolumeCounts(a)],[[10000,2],[2,1]]);
 assert.deepEqual([...c.getLabelVolumeCounts(a)],[[10000,2],[2,1]]);assert.equal(reads,4);
 const b=new Uint16Array([0,2,2]);assert.deepEqual([...c.getLabelVolumeCounts(b)],[[2,2]]);
 assert.equal(c.getLabelVolumeCounts(null).size,0);
});
test('a render exception releases the scheduler for the next resource frame',()=>{
 const frames=[],c={console,document:{hidden:false},renderFrameId:0,drawingFrame:false,pendingFrames:0,
  scene3D:{renderer:{},contextLost:false,controls:{update:()=>{throw Error('transient WebGL failure');}}},
  requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},syncViewer3DSize:()=>({cssWidth:100,cssHeight:100})};
 c.window=c;vm.createContext(c);
 vm.runInContext(segment('    function requestRender(','    // Render the live 3D scene immediately'),c);
 c.requestRender();assert.equal(frames.length,1);
 assert.throws(()=>frames[0](),/transient/);assert.equal(c.drawingFrame,false);
 c.requestRender();assert.equal(frames.length,2);
});

test('incremental geometry uses the interactive peel budget and readiness restores final quality',()=>{
 const options=[],resource={ready:false,status:'loading'},c={controlsChanged:false,
  scene3D:{scene:{},camera:{},depthPeeling:{render:(_s,_c,opts)=>options.push(opts)}},
  BrachyBotTimepointWorkspace:{resourceState:()=>resource}};
 c.window=c;vm.createContext(c);
 const code=segment('        const resourceState = window.BrachyBotTimepointWorkspace',
     '        window.renderPlanningDistanceAnnotations?.();');
 const draw=()=>vm.runInContext('{'+code+'}',c);
 draw();assert.equal(options.at(-1).interactive,true);
 resource.ready=true;draw();assert.equal(options.at(-1).interactive,false);
 resource.ready=false;resource.status='partial';draw();assert.equal(options.at(-1).interactive,false);
 c.scene3D.peelingCapture=true;draw();assert.equal(options.at(-1).capture,true);
});
function meshContext(){
 const waits=[],signals=[],meshes=new Set(),scope={timepointId:'A',generation:1};
 const c={console,Promise,Set,Map,AbortController,setTimeout,API:'',state:{sessionId:'s'},ctvLabelData:[1],oarLabelData:[2],
  _segmentationMeshPrewarm:{generation:1,tasks:new Map(),controllers:new Set(),activeRuns:0},
  _activePlanningSceneSessionId:()=> 's',_sceneHasMesh:id=>meshes.has(id),
  _labelIdInMask:(array,id)=>array.includes(id),_meshTaskKey:(source,id,smoothing,sid)=>[source,id,smoothing,sid].join(':'),
  addMeshToScene:data=>meshes.add(data.organ_id),
  _fetchViewerJsonWithRetry:async(url,init)=>{const d=deferred();signals.push(init.signal);waits.push(d);return d.promise;},
  BrachyBotTimepointWorkspace:{captureRequestScope:()=>({...scope}),headers:()=>({}),scopeIsCurrent:s=>s.generation===scope.generation&&s.timepointId===scope.timepointId}};
 c.window=c;vm.createContext(c);
 vm.runInContext(segment('async function _fetchAndAddOrganMesh(','async function prewarmSegmentationMeshes('),c);
 return {c,waits,signals,meshes,scope};
}
const response=()=>({response:{ok:true},data:{success:true,vertex_count:3,face_count:1}});

test('binary guide decoding preserves packed positions and rejects truncated resource bodies',()=>{
 const c={ArrayBuffer,Uint8Array,Float32Array,Uint32Array,DataView,TextDecoder,JSON,Math,Error};
 vm.createContext(c);vm.runInContext(segment('function decodeViewerBinaryMesh(','async function _fetchViewerJsonWithRetry('),c);
 const metadata=new TextEncoder().encode(JSON.stringify({success:true,guide:{version:2}}));
 const offset=20+Math.ceil(metadata.length/4)*4,buffer=new ArrayBuffer(offset+36+12),bytes=new Uint8Array(buffer);
 bytes.set(new TextEncoder().encode('BBMESH1\0'));const header=new DataView(buffer);
 header.setUint32(8,metadata.length,true);header.setUint32(12,3,true);header.setUint32(16,1,true);bytes.set(metadata,20);
 new Float32Array(buffer,offset,9).set([.123456789,-2,3,4,5,6,7,8,9]);new Uint32Array(buffer,offset+36,3).set([0,1,2]);
 const data=c.decodeViewerBinaryMesh(buffer);assert.equal(data.guide.vertex_count,3);assert.equal(data.guide.version,2);
 assert.deepEqual(Array.from(data.guide.vertices),Array.from(new Float32Array([.123456789,-2,3,4,5,6,7,8,9])));
 assert.deepEqual(Array.from(data.guide.faces),[0,1,2]);
 assert.throws(()=>c.decodeViewerBinaryMesh(buffer.slice(0,-1)),/lengths/);
 header.setUint32(8,0xffffffff,true);assert.throws(()=>c.decodeViewerBinaryMesh(buffer),/lengths/);
});
test('old mesh finalizer cannot remove a new timepoint task; stale geometry is discarded',async()=>{
 const {c,waits,meshes,scope}=meshContext(),args={labelId:1,source:'ctv',organId:'ctv_1',sessionId:'s'};
 const old=c._fetchAndAddOrganMesh(args);scope.timepointId='B';scope.generation++;
 const current=c._fetchAndAddOrganMesh(args);assert.equal(waits.length,2);
 waits[0].resolve(response());assert.equal((await old).status,'stale');assert.equal(meshes.size,0);
 assert.equal(c._segmentationMeshPrewarm.tasks.size,1);
 const same=c._fetchAndAddOrganMesh(args);assert.equal(waits.length,2);
 waits[1].resolve(response());assert.equal((await current).status,'loaded');assert.equal((await same).status,'loaded');
 assert.equal(c._segmentationMeshPrewarm.tasks.size,0);assert.equal(meshes.size,1);
});
test('a silently rejected mesh cannot be reported as loaded',async()=>{
 const {c,waits}=meshContext();c.addMeshToScene=()=>{};
 const task=c._fetchAndAddOrganMesh({labelId:1,source:'ctv',organId:'ctv_1'});
 waits[0].resolve(response());assert.equal((await task).status,'error');
});
test('a failed forced replacement cannot claim success through an existing mesh',async()=>{
 const {c,waits,meshes}=meshContext();meshes.add('ctv_1');c.addMeshToScene=()=>false;
 const task=c._fetchAndAddOrganMesh({labelId:1,source:'ctv',organId:'ctv_1',force:true});
 waits[0].resolve(response());assert.equal((await task).status,'error');assert.equal(meshes.has('ctv_1'),true);
});
test('invalidating reconstruction aborts pending fetches',async()=>{
 const {c,waits,signals}=meshContext();c._segmentationMeshPrewarm.statusTimer=null;c._segmentationMeshPrewarm.statusSessionId='s';
 c.clearTimeout=()=>{};c._setMeshPrewarmStatus=()=>{};
 vm.runInContext(segment('function invalidateSegmentationMeshPrewarm(','function _sceneHasMesh('),c);
 const task=c._fetchAndAddOrganMesh({labelId:1,source:'ctv',organId:'ctv_1'});
 c.invalidateSegmentationMeshPrewarm();assert.equal(signals[0].aborted,true);
 waits[0].resolve(response());assert.equal((await task).status,'stale');
 assert.equal(c._segmentationMeshPrewarm.controllers.size,0);
});

test('incoming 3D surfaces reconcile visibility without issuing another MPR refresh',()=>{
 const volume=fs.readFileSync(path.resolve(__dirname,'../web/app/static/js/brachybot-viewer-volume.js'),'utf8');
 const begin=volume.indexOf('function applyDataTreeViewVisibility('),end=volume.indexOf('function batchSetViewVisibility(',begin);
 const changes=[],c={console,state:{ctLoaded:true},scene3D:{requestRender:()=>changes.push('frame')},
  dataTreeState:{ct:{visible2D:true},planning:{visible2D:true}},document:{getElementById:()=>null},
  capitalize:s=>s,isDataTreeNodeVisible2D:node=>node?.visible2D!==false,
  _setPlanningDoseProjectionVisibility:()=>{},reloadOverlays:()=>changes.push('reload'),
  redrawSeedNeedleOverlays:()=>{},requestViewerVisualRefresh:()=>changes.push('refresh'),
  _migrateSegmentationMirrorsOutOfPlanning:()=>{},_allDataTreeVisualNodes:()=>[{id:'ctv'}],
  _apply3DNodeVisibility:()=>changes.push('3d-visible'),monitorVisualStateChanged:()=>changes.push('monitor'),
  BrachyBotImplants:{reconcilePresentation:()=>{},draw2D:()=>changes.push('mpr')},
  syncManualStepPresentationVisibility:()=>{}};
 c.window=c;vm.createContext(c);vm.runInContext(volume.slice(begin,end),c);
 c.applyDataTreeViewVisibility({meshOnly:true});assert.deepEqual(changes,['3d-visible','frame','monitor']);
 changes.length=0;c.applyDataTreeViewVisibility();
 assert.equal(changes.filter(event=>event==='mpr').length,3);
 assert(changes.includes('3d-visible'));assert(changes.includes('reload'));assert(changes.includes('refresh'));
});

test('a mesh tree publication updates nodes and 3D without reprojecting the guide into MPR',()=>{
 const volume=fs.readFileSync(path.resolve(__dirname,'../web/app/static/js/brachybot-viewer-volume.js'),'utf8');
 const begin=volume.indexOf('    const previousScrollLeft = Number(body.scrollLeft)'),end=volume.indexOf('function _scheduleDataTreeSave(',begin);
 const events=[],body={scrollLeft:3,scrollTop:7},c={Number,body,html:'saved nodes',imageCollection:false,previousScrollTop:7,
  scene3D:{requestRender:()=>events.push('3d')},_bindDataTreeOpacityControls:()=>{},_restoreTreeGroupExpansionState:()=>{},
  refreshAnalysisStructurePresentation:()=>events.push('analysis'),requestViewerVisualRefresh:()=>events.push('mpr')};
 c.window=c;vm.createContext(c);vm.runInContext('function publishTree(options={}) {\n'+volume.slice(begin,end),c);
 c.publishTree({meshOnly:true});assert.deepEqual(events,['analysis','3d']);assert.equal(body.innerHTML,'saved nodes');
 events.length=0;c.publishTree();assert.deepEqual(events,['analysis','mpr']);
});
