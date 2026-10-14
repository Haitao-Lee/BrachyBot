// The real task registrar cannot advertise boolean-failed producers as ready.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../web/app/static/js/brachybot-ui-api.js'),'utf8');
const start=src.indexOf('    const backgroundTasks = [];',src.indexOf('async function _runWorkspaceRestoreTransaction('));
const end=src.indexOf('    const updateHydrationProgress =',start);
const c=vm.createContext({Promise,Set,Map});
vm.runInContext(src.slice(start,end)+`
globalThis.register=registerBackgroundTask;
globalThis.drain=()=>Promise.allSettled(backgroundTasks);
globalThis.failed=()=>backgroundTaskFailures.size;
globalThis.details=()=>[...backgroundFailureDetails.values()];`,c);
(async()=>{
 c.register(Promise.resolve(false),{kind:'generic_masks'});
 c.register(Promise.resolve({success:false,error:'mesh_failure'}),{kind:'viewer_3d'});
 c.register(Promise.reject(Error('decoder_failure')),{kind:'labels'});
 c.register(Promise.resolve(null),{kind:'intentionally_absent'});
 c.register(Promise.resolve({success:true}),{kind:'ct'});
 await c.drain();assert.equal(c.failed(),3);
 assert.equal(c.details()[0].error,'resource_not_restored');
 assert.deepEqual(Array.from(c.details(),r=>r.kind).sort(),['generic_masks','labels','viewer_3d']);
 console.log('Timepoint visual producer failure contracts passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
