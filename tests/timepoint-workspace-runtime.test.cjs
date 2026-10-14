// Executed production loader/scope/retry functions with synthetic binary data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../web/app/static/js');
function functions(file, first, next) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    const start = source.search(new RegExp('(?:async )?function ' + first + '\\('));
    const end = source.indexOf(next, start + 1);
    assert(start >= 0 && end > start, `Missing production function ${first}`);
    return source.slice(start, end);
}
const scopeSource = functions('brachybot-viewer-volume.js', '_viewerDataHeaders', 'function _getMprGeometry(');
const volumeSource = functions('brachybot-viewer-volume.js', 'loadVolumeData', 'async function hydrateOarDataTreeFromServer(');
const retrySource = functions('brachybot-3d-manual.js', '_fetchViewerJsonWithRetry', '\nwindow.fetchViewerJsonWithRetry');
function context() {
    const A = Object.freeze({sessionId:'session', timepointId:'A', generation:1});
    const B = Object.freeze({sessionId:'session', timepointId:'B', generation:2});
    const value = {A,B,selected:A,viewerDataLoadGeneration:0,activeSessionId:'session',API:'/api',state:{ctPath:'same-name.nii.gz',viewerSettings:{}},
        Headers,Response,AbortController,ArrayBuffer,Int16Array,Uint8Array,DataView,TextDecoder,TextEncoder,
        // Keep the production cache deadline. Reducing it to 1 ms races this
        // test's deliberate setImmediate source switch and tests the wrong
        // event order (the fallback may legitimately finish while A is current).
        setTimeout:(fn,ms)=>setTimeout(fn,ms===5000?5000:Math.min(ms,1)).unref(),clearTimeout,Date,Promise,console,
        _VIEWER_RESOURCE_REQUEST_TIMEOUT_MS:1000,_VIEWER_RESOURCE_MAX_WAIT_MS:3000,
        volumeData:null,volumeShape:null,volumeSpacing:null,imageAnalysisData:{ct:{}},
        document:{getElementById:()=>null},capitalize:value=>value[0].toUpperCase()+value.slice(1),updateImageAnalysis:()=>{},uiDebugLog:()=>{},
        _viewerDataSessionId:()=>value.activeSessionId};
    value.window = value;
    value.BrachyBotTimepointWorkspace = {
        captureRequestScope:explicit=>Object.freeze({...explicit || value.selected}),
        scopeIsCurrent:scope=>scope.timepointId === value.selected.timepointId && scope.generation === value.selected.generation,
        headers:(scope, input={})=>{const headers=new Headers(input);if(scope){headers.set('X-BrachyBot-Session',scope.sessionId);headers.set('X-BrachyBot-Timepoint',scope.timepointId);}return Object.fromEntries(headers);},
    };
    vm.createContext(value); vm.runInContext(scopeSource + volumeSource, value);
    return value;
}
function binary(n) {
    return {response:new Response(null,{headers:{'X-Shape-Z':'1','X-Shape-Y':'1','X-Shape-X':'1','X-Spacing-X':'1','X-Spacing-Y':'1','X-Spacing-Z':'1'}}),data:new Int16Array([n]).buffer};
}
(async()=>{
    const c=context(), cacheKeys=[];
    c.SessionCache={get:async key=>{cacheKeys.push(key);return null;},put:async()=>{}};
    let finish;
    c.fetchViewerJsonWithRetry=()=>new Promise(resolve=>{finish=()=>resolve(binary(7));});
    const load=c.loadVolumeData({sessionId:'session',timepointScope:c.A,imageId:'image-A'});
    await new Promise(resolve=>setImmediate(resolve));
    c.selected=c.B; c.viewerDataLoadGeneration++; finish();
    assert.equal(await load,false); assert.equal(c.volumeData,null,'A volume cannot paint B');
    c.fetchViewerJsonWithRetry=async()=>binary(9);
    await c.loadVolumeData({sessionId:'session',timepointScope:c.B,imageId:'image-B'});
    assert.equal(c.volumeData[0],9);
    assert.notEqual(cacheKeys[0],cacheKeys[1],'same filename in two timepoints must use different CT caches');
    c.selected=c.A; c.viewerDataLoadGeneration++;
    let finishCache;
    const header=Buffer.from(JSON.stringify({z:1,y:1,x:1,sx:1,sy:1,sz:1}));
    const cached=new Uint8Array(4+header.length+2);new DataView(cached.buffer).setInt32(0,header.length,true);cached.set(header,4);cached.set(new Uint8Array(new Int16Array([17]).buffer),4+header.length);
    c.SessionCache.get=()=>new Promise(resolve=>{finishCache=()=>resolve(cached.buffer);});
    const cacheLoad=c.loadVolumeData({sessionId:'session',timepointScope:c.A});
    await new Promise(resolve=>setImmediate(resolve));c.selected=c.B;c.viewerDataLoadGeneration++;finishCache();
    assert.equal(await cacheLoad,false);assert.equal(c.volumeData[0],9,'late IndexedDB read must not replace B');
    const r=context();vm.runInContext(retrySource,r);
    const calls=[];r.fetch=async(url,init)=>{calls.push(Object.fromEntries(new Headers(init.headers)));r.selected=r.B;
        return calls.length===1 ? new Response(JSON.stringify({retry_after_ms:1}),{status:202,headers:{'Content-Type':'application/json'}})
            :new Response(JSON.stringify({success:true}),{headers:{'Content-Type':'application/json'}});};
    // Keep the event loop alive only while the helper's short retry is pending.
    const alive=setInterval(()=>{},10);
    try {const result=await r._fetchViewerJsonWithRetry('/api/viewer/volume',{headers:{'X-BrachyBot-Session':'session','X-BrachyBot-Timepoint':'A'}});
        assert.equal(result.data.success,true);assert.equal(calls.length,2);assert(calls.every(row=>row['x-brachybot-timepoint']==='A'),'retry cannot retarget B');}
    finally {clearInterval(alive);}
    console.log('4 production timepoint loader contracts passed (synthetic inputs).');
})().catch(error=>{console.error(error);process.exitCode=1;});
