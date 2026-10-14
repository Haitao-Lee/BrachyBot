// Execute real product transaction boundaries. Declared transport/DOM fixtures
// test ownership and failure behavior, not clinical segmentation or rendering.
const fs=require('node:fs'), path=require('node:path'), vm=require('node:vm');
const test=require('node:test'), assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../web/app');
const source=n=>fs.readFileSync(path.join(root,'static/js/brachybot-'+n+'.js'),'utf8');
function segment(text,start,end){const a=text.indexOf(start),b=text.indexOf(end,a+start.length);assert(a>=0&&b>a);return text.slice(a,b);}
function deferred(){let resolve;return {promise:new Promise(r=>resolve=r),resolve:v=>resolve(v)};}
function setup(images){
 const scope={sessionId:'session',timepointId:'A',generation:1}, finish=deferred(), events=[];
 const c={console,Promise,scope,images,events,selected:scope,
  _statusFromWorkspaceSnapshot:()=>({}),
  restoreActiveSessionWorkspace:async()=>{},
  _workspaceRestoreTransaction:{sessionId:scope.sessionId,timepointScope:scope,completion:finish.promise},
  awaitWorkspaceVisualReady:async()=>({ready:true}),
  displayTimepointImage:async()=>events.push('hidden'),
  BrachyBotTimepointWorkspace:{scopeIsCurrent:s=>c.selected===s}};
 c.window=c;vm.createContext(c);
 vm.runInContext(segment(source('ui-api'),'window.hydrateTimepointWorkspace =','window.applyTimepointImageAppearance ='),c);
 return {c,finish,scope,events};
}
test('empty migrated catalog does not hide the recovered legacy CT',async()=>{
 const {c,finish,scope,events}=setup({images:[]});finish.resolve();
 assert.equal((await c.hydrateTimepointWorkspace({},scope,c.images)).ready,true);
 assert.deepEqual(events,[]);
});
test('intentional hidden image waits for the final presentation merge',async()=>{
 const {c,finish,scope,events}=setup({images:[{id:'image'}],planning_reference_image_id:'image',display_image_id:null});
 const task=c.hydrateTimepointWorkspace({},scope,c.images);
 for(let i=0;i<6;i++)await Promise.resolve();
 assert.deepEqual(events,[]);finish.resolve();await task;assert.deepEqual(events,['hidden']);
});
test('switching while the final merge is pending cannot publish ready or hide a new image',async()=>{
 const {c,finish,scope,events}=setup({images:[{id:'image'}],planning_reference_image_id:'image',display_image_id:null});
 const task=c.hydrateTimepointWorkspace({},scope,c.images);
 for(let i=0;i<6;i++)await Promise.resolve();c.selected={...scope,generation:2};finish.resolve();
 const result=await task;assert.equal(result.ready,false);assert.equal(result.cancelled,true);assert.deepEqual(events,[]);
});
test('dose transport failure retains the existing valid projection',async()=>{
 const scope={sessionId:'session',timepointId:'A',generation:1};const item={doseSequence:0};let clears=0;
 const c={scope,item,modes:['total'],fail:msg=>Error(msg),captureRequestScope:()=>scope,entry:()=>item,
  renderDoseControls(){},json:async()=>{throw Error('declared transport failure');},
  scopeIsCurrent:()=>true,status:key=>item.status=key,clearDoseView:()=>clears++,paintDose(){},validateDose(){}};
 vm.createContext(c);vm.runInContext(segment(source('timepoint-workspace'),'    async function selectDose(','    function button('),c);
 assert.equal(await c.selectDose('total'),false);assert.equal(clears,0);assert.equal(item.status,'dose_failed');
});
test('authoritative unavailable dose clears the old projection',async()=>{
 const scope={sessionId:'session',timepointId:'A',generation:1};const item={doseSequence:0};let clears=0;
 const c={scope,item,modes:['total'],fail:msg=>Error(msg),captureRequestScope:()=>scope,entry:()=>item,
  renderDoseControls(){},json:async()=>({available:false}),
  scopeIsCurrent:()=>true,status:key=>item.status=key,clearDoseView:()=>clears++,paintDose(){},validateDose(){}};
 vm.createContext(c);vm.runInContext(segment(source('timepoint-workspace'),'    async function selectDose(','    function button('),c);
 assert.equal(await c.selectDose('total'),false);assert.equal(clears,1);assert.equal(item.status,'dose_unavailable');
});
test('obsolete spinner callback cannot stop a new activation elapsed clock',()=>{
 const elapsed={hidden:false,textContent:'8s'},notice={dataset:{sessionId:'session',runId:'2'}};
 const c={activeSessionId:'session',caseActivationTimer:7,hydrationHideTimer:null,clearInterval(){throw Error('stale callback stopped timer');},
  document:{getElementById:id=>id==='workspaceHydrationNotice'?notice:elapsed},
  BrachyBotTimepointWorkspace:{scopeIsCurrent:()=>false}};
 c.window=c;vm.createContext(c);
 vm.runInContext(segment(source('workspace'),'    window.setWorkspaceHydrationState =','    // Cold-start hydration'),c);
 c.setWorkspaceHydrationState(false,'',{sessionId:'session',runId:1,timepointId:'old',generation:1});
 assert.equal(elapsed.hidden,false);assert.equal(elapsed.textContent,'8s');assert.equal(c.caseActivationTimer,7);
});
test('optional external fonts never block local restoration scripts',()=>{
 const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
 const link=html.match(/<link[^>]+href="https:\/\/fonts.googleapis.com\/css2[^>]+>/)[0];
 assert.match(link,/media="print"/);assert.match(link,/onload="this.media='all'"/);
});
test('same-owner guide loads share work instead of invalidating each other',async()=>{
 const scope={sessionId:'session',timepointId:'A',generation:1}, done=deferred();let loads=0;
 const c={Promise,Map,JSON,Number,String,activeSessionId:()=>scope.sessionId,
  guideMeshInFlight:new Map(),guideRequestOwner:()=>({timepointScope:scope,current:()=>true}),
  _loadSurgicalGuideMesh:async()=>{loads++;return done.promise;}};
 c.window=c;vm.createContext(c);
 vm.runInContext(segment(source('surgical-guide'),'    window.loadSurgicalGuideMesh =','    async function _loadSurgicalGuideMesh('),c);
 const first=c.loadSurgicalGuideMesh({sessionId:'session',timepointScope:scope});
 const second=c.loadSurgicalGuideMesh({sessionId:'session',timepointScope:scope});
 assert.equal(first,second);await Promise.resolve();assert.equal(loads,1);
 done.resolve(true);assert.equal(await first,true);assert.equal(await second,true);
 assert.equal(c.guideMeshInFlight.size,0);
});
