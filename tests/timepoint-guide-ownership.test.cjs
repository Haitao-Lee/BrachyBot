// Executed production UI functions with explicit unit transport interleavings.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../web/app/static/js/brachybot-surgical-guide.js'),'utf8');
const section=(from,to)=>src.slice(src.indexOf(from),src.indexOf(to,src.indexOf(from)));
(async()=>{
 let selected='A',timer;const requests=[],events=[];
 const c=vm.createContext({activeSessionId:()=> 'session',t:(z,e)=>e,
  document:{getElementById:()=>null},guideParametersFromControls:()=>({}),selectedNeedleIds:()=>[],
  GUIDE_PLANNING_SELECTION_ID:'select',guideLoadGeneration:0,
  guideTransientRetryTimer:null,guideTransientRetryCount:0,
  setTimeout:fn=>{timer=fn;return 1;},setBusy:x=>events.push(['busy',x]),
  setValidationStatus:x=>events.push(['validation',x]),notify:x=>events.push(['notify',x]),
  applyGuideMetadata:()=>events.push(['metadata']),addGuideMesh:()=>events.push(['mesh']),
  FormData:class{append(){}},window:{__viewerRenderGeneration:1,
   BrachyBotTimepointWorkspace:{captureRequestScope:s=>s||({timepointId:selected,generation:1}),
     scopeIsCurrent:s=>s.timepointId===selected,headers:(s,h)=>({...h,'X-BrachyBot-Timepoint':s.timepointId})},
   fetchViewerJsonWithRetry:(url,init)=>new Promise(resolve=>requests.push({url,init,resolve}))}});
 vm.runInContext(section('    function guideRequestOwner(', '    window.loadSurgicalGuideMesh ='),c);
 vm.runInContext(section('    window.generateSurgicalGuide =', '    window.ensureSurgicalGuideForCurrentPlan ='),c);
 vm.runInContext(section('    window.validateImportedSurgicalGuideSTL =', '    window.getSurgicalGuideParameters ='),c);
 const generation=c.window.generateSurgicalGuide({silent:true,showProgress:false});
 assert.equal(requests[0].init.headers['X-BrachyBot-Timepoint'],'A');
 selected='B';requests[0].resolve({response:{ok:true,status:200},data:{success:true,guide:{version:1}}});
 assert.equal((await generation).detached,true);
 assert.deepEqual(events,[['busy',true]],'Old generation cannot publish mesh, progress, notifications or unlock B');
 events.length=0;selected='A';const validation=c.window.validateImportedSurgicalGuideSTL({name:'test.stl'});
 assert.equal(requests[1].init.headers['X-BrachyBot-Timepoint'],'A');selected='B';
 requests[1].resolve({response:{ok:true,status:200},data:{validation:{watertight:true}}});
 assert.equal(await validation,false);assert.equal(events.length,1,'Late validation cannot claim a result in B');
 let loads=0;c.window.loadSurgicalGuideMesh=()=>{loads++;};selected='A';
 c._scheduleTransientGuideRetry('session');selected='B';timer();assert.equal(loads,0,'Retry cannot target another scan');
 const html=fs.readFileSync(path.join(__dirname,'../web/app/index.html'),'utf8');
 assert.match(src,/auxiliary_hole_ring_count: 4/);assert.match(html,/id="guideAuxiliaryHoleRingCount"[^>]*value="4"/);
 assert.ok(!/[\uE000-\uF8FF]/.test(src),'Chinese UI text cannot contain encoding-corruption placeholders');
 console.log('Timepoint guide ownership and dense-default contracts passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
