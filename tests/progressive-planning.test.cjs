const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const test=require('node:test'),assert=require('node:assert/strict');
test('a pending DVH renderer cannot postpone needle, seed, mask or dose loading',async()=>{
 const source=fs.readFileSync(path.resolve(__dirname,'../web/app/static/js/brachybot-dvh-planning.js'),'utf8');
 const code=source.slice(source.indexOf('async function refreshPlanningUI('),source.indexOf('/******** METRICS ********/'));
 let finishChart;const chart=new Promise(r=>finishChart=r),events=[];
 const scope={sessionId:'s',timepointId:'t',generation:1};
 const c={console,Promise,Set,Number,String,Array,Object,JSON,Error,AbortController,setTimeout,clearTimeout,
  API:'',activeSessionId:'s',_refreshGeneration:0,_refreshInflight:null,_refreshDebounce:null,
  _refreshDebounceResolve:null,selected:true,state:{ctLoaded:true,sessionId:'s',metrics:{}},
  dataTreeState:{planning:{},dose:{}},scene3D:{meshes:{}},
  _planningRunSessionId:()=> 's',_planningRunHeaders:()=>({}),uiDebugLog(){},
  _cancelPlanningRefreshDebounce(){},refreshPlanningRunCatalog:async()=>{},
  _extractRenderableDvhPayload:()=>({CTV:[1]}),_isRenderableDvhPayload:()=>true,
  document:{getElementById:()=>null,querySelectorAll:()=>[]},
  fetch:async()=>({ok:true,status:200,json:async()=>({success:true,planning_id:'p',planning_status:'completed',
    seeds:[{pos:[1,2,3]}],total_seeds:1,num_trajectories:1,has_dose:true,has_current_dose:true})}),
  updateMetrics(){},updateSeeds:()=>events.push('seed state'),refreshStructureDvhAnalysis:async()=>{},
  loadDoseOverlay:async()=>{events.push('dose');return {shape:[1,1,1]};},
  loadAllIsoSurfaces:async()=>{events.push('dose surfaces');return {};},
  loadCTVAndObstacleMeshes:async()=>{events.push('masks');return {};},
  loadSeeds3D:async()=>{events.push('implants');return {seeds:1,needles:1};},
  drawDVH:()=>{events.push('chart pending');return chart;},
  BrachyBotTimepointWorkspace:{captureRequestScope:()=>scope,scopeIsCurrent:()=>c.selected}};
 c.window=c;vm.createContext(c);vm.runInContext(code,c);
 const task=c.refreshPlanningUI({sessionId:'s',timepointScope:scope,preserveViewerState:true,
  skipLabelLoad:true,switchToViewers:false,suppressReportFigureCapture:true});
 try {
  for(let i=0;i<30&&!events.includes('chart pending');i++)await new Promise(r=>setTimeout(r,10));
  assert(events.includes('chart pending'));
  for(const name of ['seed state','implants','dose','dose surfaces','masks'])assert(events.includes(name),name);
 } finally {c.selected=false;finishChart();await task;}
});

test('a pending CTV surface does not prevent independent OAR workers from publishing',async()=>{
 const source=fs.readFileSync(path.resolve(__dirname,'../web/app/static/js/brachybot-3d-manual.js'),'utf8');
 const code=source.slice(source.indexOf('async function prewarmSegmentationMeshes('),source.indexOf('function startSegmentationMeshPrewarm('));
 let release;const ctv=new Promise(r=>release=r),published=[];
 const c={console,Promise,Set,Number,String,Array,Object,Math,setTimeout,clearTimeout,
  state:{ctLoaded:true,sessionId:'s'},scene3D:{},ctvLabelData:true,oarLabelData:true,
  ctvLabelColorLUT:{},dataTreeState:{ctv:{},organs:[{labelId:2},{labelId:3}]},
  _segmentationMeshPrewarm:{generation:1,activeRuns:0},init3DScene(){},
  getCtvMeshLabelIds:()=>[1],_setMeshPrewarmStatus(){},_parseTreeColorValue:(_,fallback)=>fallback,
  _fetchAndAddOrganMesh:async opts=>{
   if(opts.source==='ctv')await ctv;
   published.push(opts.organId);return {status:'loaded'};
  }};
 c.window=c;vm.createContext(c);vm.runInContext(code,c);
 const task=c.prewarmSegmentationMeshes('all',{sessionId:'s',allOAR:true});
 try {
  for(let i=0;i<20&&published.length<2;i++)await new Promise(r=>setTimeout(r,10));
  assert.deepEqual(published,['organ_2','organ_3']);
  assert.equal(c._segmentationMeshPrewarm.activeRuns,1);
 } finally {release();}
 const result=await task;
 assert.equal(result.success,true);assert.equal(result.completed,3);
 assert.deepEqual(published,['organ_2','organ_3','ctv_1']);
});
