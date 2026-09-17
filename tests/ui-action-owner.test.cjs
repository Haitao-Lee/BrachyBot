const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=process.argv[2]||path.join(__dirname,'../web/app/static/js');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');
function extract(s,n,async=false){const start=s.indexOf(`${async?'async ':''}function ${n}(`);assert(start>=0);return s.slice(start,s.indexOf('\n}',start)+2);}
async function main(){
 let listener;const saved=[],painted=[];
 const first={sessionId:'s',requestId:'r1',steps:[],stepsDiv:'first'};
 const c=vm.createContext({window:{_brachyLiveTrace:first},activeSessionId:'s',Date,Map,
 document:{addEventListener:(_,fn)=>listener=fn},
 appendStepToChain:(div,step)=>painted.push([div,step.status]),
 saveSessionMessage:(...args)=>saved.push(args)});
 const todo=read('brachybot-chat-todo.js');const start=todo.indexOf('if (!window._brachyUiTraceListenerReady)');
 vm.runInContext(todo.slice(start,todo.indexOf('\nfunction _todoCreate',start)),c);
 const pending={id:'ui-action-1',tool:'ui-action-1',parent_tool:'ui_controller',session_id:'s',request_id:'r1',status:'pending'};
 listener({detail:pending});
 const second={sessionId:'s',requestId:'r2',steps:[],stepsDiv:'second'};
 c.window._brachyLiveTrace=second;
 listener({detail:{...pending,status:'done'}});
 assert.equal(first.steps.length,1);assert.equal(first.steps[0].status,'done');assert.equal(second.steps.length,0);
 assert.equal(painted.at(-1)[0],'first');assert.equal(saved.at(-1)[5].requestId,'r1');
 c.activeSessionId='other';const paints=painted.length;
 listener({detail:{...pending,status:'cancelled'}});
 assert.equal(painted.length,paints);assert.equal(saved.at(-1)[4],'s');
 vm.runInContext(extract(read('brachybot-chat-core.js'),'reconcileHistoricalUIActions'),c);
 let result=c.reconcileHistoricalUIActions([pending],'s','zh');assert.equal(result[0].status,'cancelled');
 c.window._brachyUIActionOwners.clear();
 result=c.reconcileHistoricalUIActions([pending],'s','zh');
 assert.equal(result[0].status,'error');assert(result[0].content.includes('结果未确认'));
 result=c.reconcileHistoricalUIActions([pending,{...pending,status:'done'}],'s','zh');
 assert.equal(result.length,1);assert.equal(result[0].status,'done');
 result=c.reconcileHistoricalUIActions([{...pending,status:'done'},pending],'s','zh');assert.equal(result[0].status,'done');
 const backend={id:'tool-1',tool:'planning_pipeline',status:'pending'};
 assert.equal(c.reconcileHistoricalUIActions([backend],'s','zh')[0].status,'pending');
 // A case switch must still emit a terminal event for the original action.
 let current=true;const events=[];
 Object.assign(c,{setTimeout,Promise,_uiActionSessionIsCurrent:()=>current,
 _activeApiSessionId:()=> 's',_emitUIActionProgress:step=>events.push(step),
 _executeUIAction:async()=>{current=false;return {success:true};}});
 vm.runInContext(extract(read('brachybot-ui-api.js'),'_executeUIActionsWithProgress',true),c);
 const results=await c._executeUIActionsWithProgress([{target:'report.autofill'}],{sessionId:'s',requestId:'r1'});
 assert.equal(events.length,2);assert.equal(events[1].status,'cancelled');assert.equal(events[1].request_id,'r1');
 assert.equal(results[0].stale,true);
 console.log('PASS: late completion ownership, durable update, cross-session isolation, orphan recovery, terminal precedence, switch settlement');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
