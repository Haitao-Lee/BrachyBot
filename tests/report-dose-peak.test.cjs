// Execute the production timepoint paint/selection and report recovery functions.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(process.argv[2]||path.join(__dirname,'../web/app/static/js'));
const tp=fs.readFileSync(path.join(root,'brachybot-timepoint-workspace.js'),'utf8');
const report=fs.readFileSync(path.join(root,'brachybot-report-editor.js'),'utf8');
const dvh=fs.readFileSync(path.join(root,'brachybot-dvh-planning.js'),'utf8');
const between=(s,a,b)=>{const i=s.indexOf(a),j=s.indexOf(b,i+1);assert(i>=0&&j>i,a);return s.slice(i,j);};
const paint=between(tp,'    function paintDose(','    async function selectDose(');
const peak=report.includes('function resolveReportDosePeakVoxel(')
 ? between(report,'function resolveReportDosePeakVoxel(','function snapshotReportViewerPresentation(') : '';
const select=between(tp,'    async function selectDose(','    function button(');
const dvhHelpers=between(dvh,'function _isRenderableDvhPayload(','// Render the active plan');
const scope={sessionId:'synthetic',timepointId:'A',generation:1};
const item={scope,workspace:{ui:{state:{data_tree:{planning:{doseOverlay:{visible:false,visible2D:false,opacity:.27}}}}}}};
function fixture(){
 item.doseSequence=0;
 const c={state:{ctShape:[3,2,4],slices:{axial:0,sagittal:0,coronal:0}},Uint16Array,DataView,
  copy:x=>JSON.parse(JSON.stringify(x)),CustomEvent:class{},doseModelScaleGy:()=>190.8,
  dispatchEvent:()=>{},current:true,modes:['planned','implanted','total'],entry:()=>item,
  captureRequestScope:()=>scope,scopeIsCurrent:()=>c.current,renderDoseControls:()=>{},
  validateDose:()=>{},status:()=>{},handlePresentationSave:()=>{},fail:code=>Error(code)};
 c.window=c;vm.createContext(c);vm.runInContext(dvhHelpers+paint+peak+select,c);return c;
}
function packet(mode='total') {const dose=Array(24).fill(0);dose[15]=300;return {dose,shape:[3,2,4],
 planning_id:'plan-A',source_set:mode,dose_generation:7,geometry_signature:'grid-A',available:true,stale:false};}
function plain(v){return v == null ? v : JSON.parse(JSON.stringify(v));}
(async()=>{
 let checks=0;
 for(const [mode,index] of [['planned',3],['implanted',8],['total',15]]){
  const c=fixture(),d=packet(mode);d.dose.fill(0);d.dose[index]=300;c.paintDose(d,item);
  assert.deepEqual(plain(c.state.doseOverlay.peakVoxel),{x:index%4,y:Math.floor(index/4)%2,
   z:2-Math.floor(index/8),raw_z:Math.floor(index/8)});checks++;
  assert.equal(c.state.doseOverlay.doseSource,mode);assert.equal(c.state.doseOverlay.visible,false);
  assert.equal(c.state.doseOverlay.opacity,.27);assert.equal(c.state.doseOverlay.volumeData[index],65535);checks++;
 }
 const c=fixture();
 const curves={CTV:{dose_bins:[0,180,360],volume_pcts:[100,90,0]}};
 const nested=packet();nested.dvh={};nested.metrics={dvh_data:curves};c.paintDose(nested,item);
 assert.deepEqual(plain(c.state.dvhData),curves,'Restored nested curves survive an empty top-level dvh');checks++;
 const direct=packet('implanted');direct.dvh={CTV:{cumulative:{dose_bins:[0,20],volume_pcts:[100,0]}}};
 direct.metrics={dvh_data:curves};c.paintDose(direct,item);
 assert.deepEqual([...c.state.dvhData.CTV.dose_bins],[0,20],'Selected component curves take priority');checks++;
 const empty=packet('total');empty.dvh={};empty.metrics={};c.paintDose(empty,item);
 assert.deepEqual(plain(c.state.dvhData),{},'No previous source curves may leak into a source without DVH');checks++;
 for(const index of [0,23,16]){
  const d=packet();d.dose.fill(0);d.dose[index]=5;c.paintDose(d,item);
  const pv=c.state.doseOverlay.peakVoxel;
  assert.deepEqual(plain(pv),{x:index%4,y:Math.floor(index/4)%2,z:2-Math.floor(index/8),raw_z:Math.floor(index/8)});checks++;
 }
 for(const value of [0,5]){
  const d=packet();d.dose.fill(value);c.paintDose(d,item);
  assert.deepEqual(plain(c.state.doseOverlay.peakVoxel),{x:0,y:0,z:2,raw_z:0});checks++;
 }
 // Do not compute from the re-quantized array: adjacent high values can tie.
 const d=packet();d.dose[0]=299.999;c.paintDose(d,item);
 assert.equal(c.state.doseOverlay.peakVoxel.x,3);assert.equal(c.state.doseOverlay.peakVoxel.raw_z,1);checks++;
 const overlay=c.state.doseOverlay,values=overlay.volumeData;
 delete overlay.peakVoxel;
 const recovered=c.resolveReportDosePeakVoxel(overlay);
 assert(recovered);assert.equal(overlay,c.state.doseOverlay);assert.equal(values,overlay.volumeData);
 assert.equal(overlay.visible,false);assert.equal(overlay.opacity,.27);checks++;
 assert.equal(c.resolveReportDosePeakVoxel(overlay),recovered,'Valid peak requires no volume rescan');checks++;
 for(const mutation of [o=>o.shape=[1,2,4],o=>o.shape=[3,2,0],o=>o.doseStale=true,
  o=>o.doseStatus='stale',o=>o.volumeStatus='loading',o=>o.volumeData=new Uint16Array(1),
  o=>o.volumeEncoding='unknown',o=>o.volumeQuantizationScale=-1,o=>o.volumeMin=NaN,
  o=>o.volumeData=Array(24).fill(NaN)]){
  const o={...overlay,peakVoxel:null};mutation(o);assert.equal(c.resolveReportDosePeakVoxel(o),null);checks++;
 }
 const bad={...overlay,peakVoxel:{x:4,y:1,z:1}};
 assert(c.resolveReportDosePeakVoxel(bad));assert(bad.peakVoxel.x<4);checks++;
 // A response received after navigation cannot publish a new dose or peak.
 const late=fixture();let finish;late.json=()=>new Promise(r=>finish=r);
 const old=late.state.doseOverlay;const pending=late.selectDose('implanted');
 late.current=false;finish(packet('implanted'));
 assert.equal(await pending,false);assert.equal(late.state.doseOverlay,old);checks++;
 // Latest selected source wins when two responses arrive out of order.
 const race=fixture(),resolvers={};race.json=(_s,url)=>new Promise(r=>resolvers[url.split('=').at(-1)]=r);
 const first=race.selectDose('planned'),second=race.selectDose('total');
 resolvers.total(packet('total'));assert.equal(await second,true);
 resolvers.planned(packet('planned'));assert.equal(await first,false);
 assert.equal(race.state.doseOverlay.doseSource,'total');checks++;
 console.log(`PASS ${checks} dose peak, geometry, source, presentation and navigation checks`);
})().catch(e=>{console.error(e);process.exitCode=1;});
