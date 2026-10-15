const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const dir = process.argv[2] || path.resolve(__dirname, '../web/app/static/js');
const chat = fs.readFileSync(path.join(dir, 'brachybot-chat-todo.js'), 'utf8');
const viewer = fs.readFileSync(path.join(dir, 'brachybot-3d-manual.js'), 'utf8');
function section(source, start, end) {
    const a=source.indexOf(start), b=source.indexOf(end,a+start.length);
    assert(a>=0 && b>a, start);
    return source.slice(a,b);
}
const tick = () => new Promise(setImmediate);
function handshakeHarness() {
    const timers = new Set();
    const c = vm.createContext({AbortController, DOMException, console,
        CHAT_CONNECT_TIMEOUT_MS:30000,
        setTimeout(fn) { const t=setTimeout(fn,8);timers.add(t);return t; },
        clearTimeout(t) {timers.delete(t);clearTimeout(t);},
    });
    vm.runInContext(section(chat,'async function _openChatHandshake(', '\n// A report regeneration'),c);
    let controller=new AbortController();
    const opts={controller, isDetached:()=>false,
        onController(next) {controller=next;},
        performHandshake:async()=>({ok:true}), recoverHandshake:null};
    return {c,opts,current:()=>controller,timers};
}
function neverRespond(controller) {
    return new Promise((resolve,reject)=>controller.signal.addEventListener('abort',
        ()=>reject(new DOMException('aborted','AbortError')),{once:true}));
}
test('normal handshake returns once and clears its timer', async()=>{
    const h=handshakeHarness();let count=0;
    h.opts.performHandshake=async()=>{count++;return {ok:true};};
    assert.equal((await h.c._openChatHandshake(h.opts)).ok,true);
    assert.equal(count,1);assert.equal(h.timers.size,0);
});
test('an HTTP rejection returns without resending an unauthorized request',async()=>{
    const h=handshakeHarness();let count=0;
    h.opts.performHandshake=async()=>{count++;return {ok:false,status:403};};
    assert.equal((await h.c._openChatHandshake(h.opts)).status,403);assert.equal(count,1);
});
test('a dropped fetch retries the same request with a new live controller',async()=>{
    const h=handshakeHarness();let count=0;const controllers=[];
    h.opts.performHandshake=async controller=>{
        controllers.push(controller);if(++count===1)throw new TypeError('Failed to fetch');
        return {ok:true};
    };
    await h.c._openChatHandshake(h.opts);
    assert.equal(count,2);assert.notEqual(controllers[0],controllers[1]);
});
test('two timeouts probe the accepted task and join its stream',async()=>{
    const h=handshakeHarness();let posts=0, probes=0;
    h.opts.performHandshake=controller=>{posts++;return neverRespond(controller);};
    h.opts.recoverHandshake=async()=>{probes++;return {ok:true,recovered:true};};
    assert.equal((await h.c._openChatHandshake(h.opts)).recovered,true);
    assert.equal(posts,2);assert.equal(probes,1);assert.equal(h.timers.size,0);
});
test('unconfirmed admission reports a connection timeout instead of hydration',async()=>{
    const h=handshakeHarness();h.opts.performHandshake=neverRespond;
    h.opts.recoverHandshake=async()=>null;
    await assert.rejects(h.c._openChatHandshake(h.opts),e=>e.code==='chat_connection_timeout');
});
test('network failure and failed lookup receive a classified connection failure',async()=>{
    const h=handshakeHarness();h.opts.performHandshake=async()=>{throw new TypeError('Failed to fetch');};
    h.opts.recoverHandshake=async()=>{throw new TypeError('offline');};
    await assert.rejects(h.c._openChatHandshake(h.opts),e=>e.code==='chat_connection_failed');
});
for (const mode of ['stop','detach']) test(`${mode} prevents retries and recovery`,async()=>{
    const h=handshakeHarness();let detached=false, posts=0,probes=0;
    h.opts.isDetached=()=>detached;
    h.opts.performHandshake=async controller=>{
        posts++;
        if(mode==='stop')controller.__brachybotExplicitStop=true;else detached=true;
        controller.abort();throw new DOMException('aborted','AbortError');
    };
    h.opts.recoverHandshake=async()=>{probes++;};
    await assert.rejects(h.c._openChatHandshake(h.opts));
    assert.equal(posts,1);assert.equal(probes,0);
});
const recoverSource=chat.match(/recoverHandshake: isResumingTask \? null : (async controller => \{[\s\S]*?\n            \}),\n        \}\);/)[1];
test('Stop while decoding the status probe prevents opening a stream',async()=>{
    const controller=new AbortController();let calls=0;
    const c=vm.createContext({window:{},activeSessionId:'case',turnSessionId:'case',turnRequestId:'request',
        submittedTarget:{timepointId:'tp'},API:'/api',DOMException,console:{warn(){}},
        fetch:async()=>{calls++;return {ok:true,json:async()=>{
            controller.__brachybotExplicitStop=true;controller.abort();
            return {task:{task_id:'task',request_id:'request',session_id:'case',timepoint_id:'tp'}};
        }};},
    });
    await assert.rejects(vm.runInContext(`(${recoverSource})`,c)(controller));
    assert.equal(calls,1);
});
for(const mismatch of ['request','session','timepoint','missing-timepoint','none','match']) test(`recovery respects ${mismatch} identity`,async()=>{
    const calls=[];const task={task_id:'task',request_id:'request',session_id:'case',timepoint_id:'tp'};
    if(mismatch==='request')task.request_id='old';
    if(mismatch==='session')task.session_id='other';
    if(mismatch==='timepoint')task.timepoint_id='other';
    if(mismatch==='missing-timepoint')delete task.timepoint_id;
    const c=vm.createContext({
        window:{}, activeSessionId:'case', turnSessionId:'case',turnRequestId:'request',
        submittedTarget:{timepointId:'tp'},API:'/api',DOMException,console:{warn(){}},
        fetch:async(url,init)=>{calls.push({url,init});return {ok:true,json:async()=>({task:mismatch==='none'?null:task})};},
    });
    const recover=vm.runInContext(`(${recoverSource})`,c);
    const result=await recover(new AbortController());
    assert.equal(calls.length,mismatch==='match'?2:1);
    if(mismatch==='match')assert(calls[1].url.includes('/tasks/task/stream?after_seq=0'));
    else assert.equal(result,null);
});
function doseHarness() {
    const calls=[];const c=vm.createContext({Promise,Map,AbortController,Number,Math,
        state:{doseOverlay:{slices:{},planningId:'plan',doseGeneration:1,maxSlice:{axial:200}}},
        _doseOverlayLoadGeneration:1,_doseOverlaySessionId:()=> 'case',
        _doseContourPlanningId:()=> 'plan',doseOverlaySliceCacheKey:(axis,index)=>`${axis}_${index}`,
        _doseContourCacheKey:(axis,index)=>`${axis}_${index}`,uiDebugLog(){}, API:'/api',
        _fetchViewerJsonWithRetry:(url,init)=>new Promise(resolve=>calls.push({url,init,resolve})),
    });
    vm.runInContext(`var _doseOverlayRequestVersion=0;var _doseOverlayAbortControllers=new Map();
        var _doseOverlayInflight=new Map();var _doseContourInflight=new Map();var _doseContourCache={};`,c);
    vm.runInContext(section(viewer,'const _doseSliceLanes =', '\nasync function fetchDoseOverlaySlice('),c);
    vm.runInContext(section(viewer,'async function fetchDoseOverlaySlice(', '\n// Preload adjacent dose slices'),c);
    vm.runInContext(section(viewer,'async function fetchDoseContourSlice(', '\nfunction renderDoseContourOnCanvas('),c);
    return {c,calls};
}
test('hundreds of scrub requests keep three active slots and only latest waiters',async()=>{
    const {c,calls}=doseHarness();const promises=[];
    for(let i=0;i<100;i++)for(const axis of ['axial','sagittal','coronal']) {
        promises.push(c.fetchDoseOverlaySlice(axis,i),c.fetchDoseContourSlice(axis,i));
    }
    await tick();assert.equal(calls.length,3);
    const completed=new Set();
    for(let round=0;round<10;round++) {
        for(const call of calls)if(!completed.has(call)) {
            completed.add(call);call.resolve({response:{ok:true},data:{success:true,slice:[],contours:[],planning_id:'plan',dose_generation:1}});
        }
        await tick();
    }
    await Promise.all(promises);
    assert(calls.length<=9,'intermediate slices must never reach fetch');
    assert.equal(vm.runInContext('_doseSliceActive',c),0);
    assert.equal(vm.runInContext('_doseSliceLanes.size',c),0);
    assert.equal(c._doseOverlayInflight.size+c._doseContourInflight.size,0);
    assert(calls.some(x=>JSON.parse(x.init.body).slice_index===99));
});
test('a queued old-generation slice never fetches after case resources change',async()=>{
    const {c,calls}=doseHarness();const pending=[];
    for(const axis of ['axial','sagittal','coronal'])pending.push(c.fetchDoseOverlaySlice(axis,0));
    pending.push(c.fetchDoseContourSlice('axial',2));
    await tick();assert.equal(calls.length,3);
    c._doseOverlayLoadGeneration++;
    for(const call of calls)call.resolve({response:{ok:true},data:{success:true,slice:[]}});
    await Promise.all(pending);await tick();assert.equal(calls.length,3);
});
