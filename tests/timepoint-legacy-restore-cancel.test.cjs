// Actual legacy scheduler/cancellation functions with controlled startup order.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../web/app/static/js/brachybot-workspace.js'),'utf8');
function fn(name){const start=source.indexOf('    function '+name+'('),end=source.indexOf('\n    }',start);assert.ok(start>=0&&end>start);return source.slice(start,end+6);}
const resolved=[],notices=[],cleared=[];
const scope={sessionId:'patient',timepointId:'B',generation:2};
const c=vm.createContext({backgroundRestoreGeneration:0,backgroundRestoreTimer:1,backgroundRestoreRetryTimer:2,
 backgroundRestoreRetryCounts:{patient:1},backgroundRestoreNoticeTimer:3,
 clearTimeout:id=>cleared.push(id),activeSessionId:'patient',
 document:{body:{classList:{remove:x=>notices.push(x)}}},window:{
  __workspaceHydrationRunId:2,__workspaceRestoreScheduledSessionId:'patient',
  BrachyBotTimepoints:{},BrachyBotTimepointWorkspace:{},
  setWorkspaceHydrationState:()=>notices.push('clear'),__workspaceVisualReadiness:{
   owned:{sessionId:'patient',timepointScope:scope,settled:false,resolveReady:r=>resolved.push(['owned',r])},
   legacy:{sessionId:'patient',settled:false,resolveReady:r=>resolved.push(['legacy',r])}}}});
vm.runInContext(fn('cancelBackgroundWorkspaceRestore')+'\n'+fn('scheduleBackgroundWorkspaceRestore'),c);
c.scheduleBackgroundWorkspaceRestore({},'patient');
assert.deepEqual(resolved.map(([kind])=>kind),['legacy']);
assert.equal(c.window.__workspaceHydrationRunId,2,'Late legacy skip cannot invalidate the owned run');
assert.equal(c.window.__workspaceRestoreScheduledSessionId,'patient');
assert.deepEqual(notices,[]);assert.deepEqual(cleared,[1,2,3]);
c.cancelBackgroundWorkspaceRestore();
assert.ok(resolved.some(([kind,result])=>kind==='owned'&&result.cancelled===true),'Real Session transitions still cancel all old restore work');
assert.equal(c.window.__workspaceHydrationRunId,3);
assert.ok(notices.includes('clear'));
console.log('Timepoint legacy restore cancellation contracts passed');
