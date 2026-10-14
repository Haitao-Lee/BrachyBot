// Actual hydration functions; synthetic receipts model a promise/ownership race only.
const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../web/app/static/js/brachybot-timepoint-workspace.js'),'utf8');
const start=source.indexOf('    async function hydrate(item) {');
const end=source.indexOf('    function persistImageAppearance(',start);
assert(start>=0&&end>start);
function fixture(navigateAway=false) {
  const scope={sessionId:'synthetic-session',timepointId:'A',generation:1};
  const item={scope,workspace:{timepoint_clinical_revision:1},images:{},doseMode:'planned'};
  const value={Promise,copy:x=>JSON.parse(JSON.stringify(x)),window:{
      hydrateTimepointWorkspace:async()=>({ready:true}),BrachyBotImplants:{reload:async()=>true}},
      mounted:scope,current:item,reloads:0,recoveryCalls:0,status:()=>{},assertOwner:()=>{},
      scopeIsCurrent:s=>value.mounted?.sessionId===s.sessionId&&value.mounted?.timepointId===s.timepointId&&value.mounted?.generation===s.generation,
      selectDose:async()=>true,json:async()=>({workspace:{timepoint_clinical_revision:2}}),
      entry:()=>value.current,
      restoreActive:async()=>{
        // A concurrent accepted metadata response can update the cached
        // workspace before recovery reads it, so replay selects the existing
        // hydrate promise rather than creating a new mount.
        value.recoveryCalls++;item.workspace={timepoint_clinical_revision:2};
        return value.hydrate(item);
      }};
  value.controller=()=>({
    observeWorkspace:()=>{},
    reload:async()=>{
      value.reloads++;
      value.mounted={sessionId:'synthetic-session',timepointId:navigateAway?'B':'A',generation:2};
      value.current={scope:value.mounted,workspace:{timepoint_clinical_revision:2},images:{},doseMode:'planned'};
      return true;
    }});
  vm.createContext(value);vm.runInContext(source.slice(start,end),value);
  return {value,item};
}
async function bounded(promise) {
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Hydration awaited its own promise')),2000);})]);}
  finally{clearTimeout(timer);}
}
(async()=>{
  const {value,item}=fixture();
  assert.equal(await bounded(value.hydrate(item)),true);
  assert.equal(value.reloads,1,'Clinical drift remounts from a fresh receipt');
  assert.equal(value.recoveryCalls,0,'An in-flight hydration never re-enters generic recovery');
  assert.equal(value.current.ready,true);
  assert.notEqual(value.current,item);
  assert.equal(item.ready,false,'Superseded owner cannot become ready');
  const rebased=fixture();let firstReceipt;
  const runtimeBuffer=new Float32Array([1,2,3]);
  rebased.item.workspace.runtimeGeometry=runtimeBuffer;
  rebased.value.window.hydrateTimepointWorkspace=async workspace=>{
    firstReceipt ??= workspace.timepoint_clinical_revision;
    if(workspace.timepoint_clinical_revision===1){
      assert.equal(workspace.runtimeGeometry,runtimeBuffer,'Version fencing must not JSON-serialize live geometry');
      assert.deepEqual([...workspace.runtimeGeometry],[1,2,3]);
    }
    rebased.item.workspace={timepoint_clinical_revision:2};
    return {ready:true};
  };
  assert.equal(await bounded(rebased.value.hydrate(rebased.item)),true);
  assert.equal(firstReceipt,1);
  assert.equal(rebased.value.reloads,1,'Mutable observer receipt cannot conceal consumed-resource drift');
  const failedImplants=fixture();
  failedImplants.value.window.BrachyBotImplants.reload=async(_scope,options)=>{
    assert.equal(options.throwOnError,true);throw Error('Synthetic transport failure');
  };
  assert.equal(await bounded(failedImplants.value.hydrate(failedImplants.item)),false);
  assert.equal(failedImplants.item.ready,false,'Failed observation read cannot authorize saves');
  const stale=fixture(true);
  assert.equal(await bounded(stale.value.hydrate(stale.item)),false);
  assert.notEqual(stale.value.current.ready,true,'A changed timepoint cannot inherit A readiness');
  const restoreStart=source.indexOf('    async function restoreActive(options = {}) {');
  const restoreEnd=source.indexOf('    function acceptPlanningConfig(',restoreStart);
  assert(restoreStart>=0&&restoreEnd>restoreStart);
  const queued={mounted:{sessionId:'synthetic-session',timepointId:'A',generation:1},
    restoreTasks:new Map(),calls:0,status:()=>{}};
  queued.restoreActiveResources=()=>{queued.calls++;return new Promise(resolve=>{queued.finish=resolve;});};
  vm.createContext(queued);vm.runInContext(source.slice(restoreStart,restoreEnd),queued);
  const first=queued.restoreActive(),second=queued.restoreActive();
  assert.equal(queued.calls,1,'Concurrent recovery shares one source-owned operation');
  queued.finish(true);
  assert.equal(await bounded(first),true);assert.equal(await bounded(second),true);
  assert.equal(queued.restoreTasks.size,0,'Settled recovery releases its slot');
  const third=queued.restoreActive();
  assert.equal(queued.calls,2,'A later explicit retry starts a fresh operation');
  queued.finish(false);assert.equal(await bounded(third),false);
  const restoreResourcesStart=source.indexOf('    async function restoreActiveResources(options = {}) {');
  const restoreResourcesEnd=source.indexOf('    async function observeCommittedState(',restoreResourcesStart);
  const same=(a,b)=>!!a&&!!b&&a.sessionId===b.sessionId&&a.timepointId===b.timepointId&&a.generation===b.generation;
  function recoveryFixture(){
    const oldScope={sessionId:'synthetic-session',timepointId:'A',generation:1};
    const old={scope:oldScope};let finish,reject;
    old.hydration=new Promise((resolve,no)=>{finish=resolve;reject=no;});
    const c={mounted:oldScope,current:old,restoreTasks:new Map(),same,status:()=>{c.failed=true;},
      controller:()=>({enabled:()=>true}),entry:()=>c.current,json:()=>{c.reads++;throw Error('Unexpected stale read');},reads:0};
    vm.createContext(c);vm.runInContext(source.slice(restoreStart,restoreEnd)+source.slice(restoreResourcesStart,restoreResourcesEnd),c);
    return {c,old,finish,reject};
  }
  const navigation=recoveryFixture(), oldRecovery=navigation.c.restoreActive();
  navigation.c.mounted={sessionId:'synthetic-session',timepointId:'B',generation:2};
  navigation.c.mounted={sessionId:'synthetic-session',timepointId:'A',generation:3};
  navigation.c.current={scope:navigation.c.mounted,ready:true};navigation.finish(false);
  assert.equal(await bounded(oldRecovery),false,'A1 -> B2 -> A3 cannot inherit A1 recovery');
  assert.equal(navigation.c.reads,0);assert.notEqual(navigation.c.failed,true);
  const rejected=recoveryFixture(), rejectedRecovery=rejected.c.restoreActive();
  rejected.c.mounted={sessionId:'synthetic-session',timepointId:'A',generation:2};
  rejected.c.current={scope:rejected.c.mounted,ready:true};
  // A pending old promise rejecting cannot paint a newer generation failed.
  rejected.reject(Error('Synthetic old-generation transport failure'));
  assert.equal(await bounded(rejectedRecovery),false);assert.notEqual(rejected.c.failed,true);
  const successor=recoveryFixture(), successorRecovery=successor.c.restoreActive();
  successor.c.mounted={sessionId:'synthetic-session',timepointId:'A',generation:2};
  successor.c.current={scope:successor.c.mounted,ready:true};successor.old.successor=successor.c.current;successor.finish(true);
  assert.equal(await bounded(successorRecovery),true,'An explicitly owned remount can succeed pending recovery');
  assert.equal(successor.c.reads,0);
  const implantSource=fs.readFileSync(path.resolve(__dirname,'../web/app/static/js/brachybot-implant-observations.js'),'utf8');
  const implantStart=implantSource.indexOf('    async function reload(explicit = null');
  const implantEnd=implantSource.indexOf('    async function detect()',implantStart);
  const impl={window:{BrachyBotTimepoints:{getCatalog:()=>({})}},generation:1,
    capture:()=>({observationGeneration:1}),request:async()=>{throw Error('Synthetic failed observation read');},mounted:()=>true,
    status:()=>{},message:x=>x,accept:()=>true};
  vm.createContext(impl);vm.runInContext(implantSource.slice(implantStart,implantEnd),impl);
  assert.equal(await impl.reload(),false,'Existing interactive boolean failure contract remains compatible');
  await assert.rejects(impl.reload(null,{throwOnError:true}),/Synthetic failed observation read/);
  impl.request=async()=>({view:{}});impl.capture=()=>({observationGeneration:0});
  assert.equal(await impl.reload(null,{throwOnError:true}),false,'Supersession is not a transport failure');
  console.log('9 production hydration reentry contracts passed (synthetic receipts).');
})().catch(error=>{console.error(error);process.exitCode=1;});
