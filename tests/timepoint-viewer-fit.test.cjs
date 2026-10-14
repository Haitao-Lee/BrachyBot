// Real product fit helper; controlled paint promises only (no clinical model).
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../web/app/static/js/brachybot-viewer-layout.js'),'utf8');
const start=source.indexOf('let _workspaceViewerFitGeneration = 0;');
const end=source.indexOf('\nfunction resetViewer()',start);
assert.ok(start>=0&&end>start);
(async()=>{
 let selected='A',mount=1;
 const effects=[],paint=[];
 const capture=()=>({sessionId:'patient',timepointScope:{timepointId:selected,generation:mount},dataGeneration:1,renderGeneration:mount});
 const c=vm.createContext({state:{ctLoaded:true},_activeApiSessionId:()=> 'patient',
  _captureViewerDataScope:capture,_viewerDataScopeIsCurrent:s=>s.timepointScope.timepointId===selected&&s.timepointScope.generation===mount,
  fitView:()=>effects.push(['fit',selected]),loadAllSlices:async()=>effects.push(['slices',selected]),
  syncViewerGeometry:()=>effects.push(['geometry',selected]),setTimeout:fn=>fn(),
  window:{requestAnimationFrame:fn=>paint.push(fn),reconcile2DViewerLayers:()=>effects.push(['layers',selected]),
   resizeViewer3D:()=>effects.push(['size',selected]),ensureCameraFitsVisibleScene:()=>effects.push(['camera',selected]),
   forceRender3DViewer:()=>effects.push(['render',selected])}});
 vm.runInContext(source.slice(start,end),c);
 const ownerA=capture(),a=c.window.fitAllViewersAfterWorkspaceRestore({sessionId:'patient',requestScope:ownerA});
 assert.deepEqual(effects,[['fit','A']]);
 selected='B';mount=2;const ownerB=capture();
 const b=c.window.fitAllViewersAfterWorkspaceRestore({sessionId:'patient',requestScope:ownerB,preserveSavedView:true});
 const fitGeneration=vm.runInContext('_workspaceViewerFitGeneration',c);
 assert.equal(await c.window.fitAllViewersAfterWorkspaceRestore({sessionId:'patient',requestScope:ownerA}),false);
 assert.equal(vm.runInContext('_workspaceViewerFitGeneration',c),fitGeneration,'Stale A cannot cancel B fit');
 paint.shift()();assert.equal(await a,false);
 for(let i=0;i<8;i++){while(paint.length)paint.shift()();await Promise.resolve();}
 assert.equal(await b,true);
 assert.ok(effects.some(([kind,id])=>kind==='geometry'&&id==='B'));
 assert.ok(!effects.some(([kind,id])=>id==='B'&&['fit','camera'].includes(kind)),'B saved framing remains untouched');
 assert.ok(!effects.some(([kind,id])=>id==='A'&&kind!=='fit'),'Late A cannot repaint B');
 const layoutStart=source.indexOf('function syncViewerGeometry('),layoutEnd=source.indexOf('\nwindow.syncViewerGeometry =',layoutStart);
 const frames=[],delayed=[],positions=[];
 const d=vm.createContext({_viewerGeometrySync:{generation:0,timer:null},_captureViewerDataScope:capture,
  _viewerDataScopeIsCurrent:s=>s.timepointScope.timepointId===selected&&s.timepointScope.generation===mount,
  requestAnimationFrame:fn=>frames.push(fn),setTimeout:fn=>{delayed.push(fn);return delayed.length;},clearTimeout:()=>{},
  getSliceCanvas:axis=>({set _posSet(v){positions.push([selected,axis,v]);}}),capitalize:x=>x,
  document:{getElementById:()=>null},resizeCanvas:x=>positions.push([selected,'resize',x]),
  _restoreViewerViewport:()=>{},window:{}});
 vm.runInContext(source.slice(layoutStart,layoutEnd),d);
 selected='A';mount=3;d.syncViewerGeometry({resetPositions:true,settleMs:120});
 selected='B';mount=4;
 while(frames.length)frames.shift()();
 delayed.shift()();while(frames.length)frames.shift()();
 assert.deepEqual(positions,[],'A deferred geometry/settle pass must not reset B even with acceptNewerGeneration');
 console.log('Timepoint viewer fit ownership contracts passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
