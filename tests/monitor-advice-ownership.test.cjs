const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.argv[2]||path.resolve(__dirname,'../web/app/static/js');
const source=fs.readFileSync(path.join(root,'brachybot-3d-manual.js'),'utf8');
const start=source.indexOf('async function requestPlanningAdvice('),end=source.indexOf('\nfunction _formatReadinessReport',start);
function harness(){
    let session='a';const messages=[],progress=[],requests=[];
    const ctx={window:{monitorConversationLanguage:()=> 'zh'},API:'/api',AbortController,
        setTimeout:()=>1,clearTimeout(){},trainingMonitorState:{runId:'r'},manualPlanningState:{planningId:'p',planningVersion:1},
        _activeApiSessionId:()=>session,_inputButtonProgress:(...args)=>progress.push(args),
        _manualText:zh=>zh,_manualErrorDetail:()=>'',addChat:(...args)=>messages.push(args),reportUIEvent(){},
        collectUIState:()=>{throw new Error('Full scene serialization is not needed for advice');},
        fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve})),
    };
    vm.createContext(ctx);vm.runInContext(source.slice(start,end),ctx);
    const finish=i=>requests[i].resolve({ok:true,json:async()=>({success:true,natural_response:`answer${i}`})});
    return {ctx,messages,progress,requests,finish,setSession:value=>session=value};
}
(async()=>{
    let h=harness(),promise=h.ctx.requestPlanningAdvice({question:'解释变化'});
    assert.deepEqual(JSON.parse(h.requests[0].options.body).ui_state,{language:'zh'});
    h.setSession('b');h.finish(0);await promise;assert.equal(h.messages.length,0);
    h=harness();promise=h.ctx.requestPlanningAdvice({question:'解释变化'});
    h.ctx.manualPlanningState.planningVersion=2;h.finish(0);await promise;
    assert.equal(h.messages.length,0);assert.equal(h.progress.at(-1)[1],'done','superseded advice leaves no pending spinner');
    h=harness();const old=h.ctx.requestPlanningAdvice({question:'旧请求'}),next=h.ctx.requestPlanningAdvice({question:'新请求'});
    h.finish(1);await next;h.finish(0);await old;
    assert.equal(h.messages.length,1);assert.equal(h.messages[0][1],'answer1');
    console.log('Advice: compact request, case/plan-version ownership and latest-request-wins passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
