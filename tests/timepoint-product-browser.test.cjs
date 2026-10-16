// Actual page, actual routes and actual uploaded NIfTI bytes. No route mocks,
// patched product globals, synthetic scene implementations or provider calls.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [origin, preoperative, intraoperative] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({headless:true, args:['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE} : {})});
  const page = await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
  page.on('pageerror', error => errors.push(error.stack));
  page.on('response', response => { if(response.status()>=400 && response.url().startsWith(origin+'/'))
    void response.text().then(text=>console.error('API failure:',response.status(),new URL(response.url()).pathname,text.slice(0,1000))).catch(()=>{}); });
  page.on('response', response => {if(response.url().includes('/timepoints') && response.status()<400)
    void response.json().then(data=>console.log('TIMEPOINT HTTP',response.request().method(),new URL(response.url()).pathname,
      data.catalog_revision,data.workspace?.timepoint_state_revision,data.workspace?.timepoint_clinical_revision,
      data.workspace?.timepoint?.lifecycle_revision)).catch(()=>{});});
  page.on('request', request => {if(request.method()==='PATCH' && /\/timepoints\/[^/]+\/workspace$/.test(new URL(request.url()).pathname)) {
    const {patch,...fence}=request.postDataJSON() || {}; console.log('PRESENTATION FENCE',new URL(request.url()).pathname,JSON.stringify(fence));
  }});
  page.on('console', event => { if(['error','warning'].includes(event.type())) console.error('Browser:', event.text()); });
  page.setDefaultTimeout(30000);
  try {
    const registered = await page.request.post(origin+'/api/auth/register', {data:{username:'browser_owner',password:'synthetic-browser-password-123'}});
    assert.equal(registered.status(),201);
    const auth=await registered.json();
    await page.goto(origin+'/', {waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => window.BrachyBotTimepoints?.enabled?.() === true);
    await page.waitForFunction(() => window.BrachyBotTimepointWorkspace?.resourceState?.()?.ready === true);
    assert.equal(await page.locator('#overlayCTV').isChecked(),true);
    assert.equal(await page.locator('#overlayOAR').isChecked(),true);
    assert.equal(await page.locator('#labelShow3d').isChecked(),true);
    const A=await page.evaluate(() => BrachyBotTimepoints.captureSubmission().timepointId);
    assert.match(A,/^[a-f0-9]{32}$/);
    assert.equal((await page.evaluate(() => BrachyBotTimepoints.getCatalog().timepoints)).length,1);
    await page.locator('#fileCT').setInputFiles(preoperative);
    await page.waitForFunction(() => window.BrachyBotTimepointWorkspace.resourceState()?.images?.images?.length === 1
      && state.ctLoaded && JSON.stringify(state.ctShape)==='[12,18,20]');
    assert.equal(await page.locator('#ctPath').inputValue().then(x=>x.includes('preoperative')),true);
    assert.equal(await page.evaluate(()=>BrachyBotTimepointWorkspace.resourceState().images.images[0].name),'preoperative.nii.gz');
    console.log('PASS actual first image upload and decoder');
    async function applyOwnedSettings(rx, iterations) {
      await page.locator('[data-panel="input"]').click();
      if(!await page.locator('#inLowestEnergy').isVisible())
        await page.locator('[aria-controls="hyperparamsSection"]').click();
      await page.locator('#inLowestEnergy').fill(String(rx));
      await page.locator('#maxIter').fill(String(iterations));
      const saved=page.waitForResponse(r=>r.url().endsWith('/api/config')&&r.request().method()==='POST');
      await page.locator('button[onclick="applyHyperparams()"]:visible').click();
      const response=await saved;assert.equal(response.status(),200,await response.text());
      assert.equal((await response.json()).config.in_lowest_dose_gy,rx);
    }
    await applyOwnedSettings(130,7);
    await page.locator('#timepointAdd').click();
    await page.locator('.timepoint-modal input[name="title"]').fill('Intraoperative acquisition');
    await page.locator('.timepoint-modal select[name="stage"]').selectOption('intraoperative');
    await page.locator('.timepoint-modal select[name="preoperative_timepoint_id"]').selectOption(A);
    await page.locator('.timepoint-modal button[type="submit"]').click();
    await page.waitForFunction(a=>BrachyBotTimepointWorkspace.requestReady() && BrachyBotTimepoints.captureTarget().timepointId!==a
      && BrachyBotTimepointWorkspace.resourceState()?.ready===true,A);
    const B=await page.evaluate(() => BrachyBotTimepoints.captureSubmission().timepointId);
    assert.notEqual(A,B);
    assert.equal(await page.evaluate(()=>state.ctLoaded),false);
    assert.equal(await page.locator('#ctPath').inputValue(),'');
    await page.locator('#fileCT').setInputFiles(intraoperative);
    await page.waitForFunction(() => BrachyBotTimepointWorkspace.resourceState()?.images?.images?.length===1
      && state.ctLoaded && JSON.stringify(state.ctShape)==='[14,16,22]');
    assert.equal(await page.locator('#ctPath').inputValue().then(x=>x.includes('intraoperative')),true);
    console.log('PASS linked intraoperative empty workspace and actual second upload');
    await applyOwnedSettings(145,9);
    await page.locator('#timepointTabs [data-timepoint-id="'+A+'"]').click();
    await page.waitForFunction(a=>BrachyBotTimepointWorkspace.requestReady() && BrachyBotTimepoints.captureTarget().timepointId===a
      && BrachyBotTimepointWorkspace.resourceState()?.ready===true && JSON.stringify(state.ctShape)==='[12,18,20]',A);
    assert.equal(await page.locator('#inLowestEnergy').inputValue(),'130');
    assert.equal(await page.locator('#maxIter').inputValue(),'7');
    await page.evaluate(()=>switchPanel('report',document.querySelector('[data-panel="report"]')));
    assert.equal(await page.locator('#reportFormHost input[data-key="patient.name"]').count(),1);
    await page.locator('[data-lang-btn="zh"]:visible').first().click();
    await page.waitForFunction(()=>window._i18nLang==='zh');
    // Real presentation save must preserve the raw clinical version.
    const before=await page.request.get(origin+'/api/sessions/'+auth.active_session_id+'/timepoints/'+A+'/workspace');
    const beforeState=(await before.json()).workspace;
    await page.evaluate(()=>BrachyBotTimepointWorkspace.persistPresentation());
    const after=await page.request.get(origin+'/api/sessions/'+auth.active_session_id+'/timepoints/'+A+'/workspace');
    const afterState=(await after.json()).workspace;
    assert.equal(afterState.timepoint_clinical_revision,beforeState.timepoint_clinical_revision);
    assert.equal(afterState.ui?.state?.controls?.fileCT,undefined,'A file chooser handle is not saved case data');
    // An actual older persisted presentation can contain a browser fake path.
    // Restore must ignore that handle, rather than aborting all four panels.
    const legacy=await page.evaluate(async({version,sid,tid})=>{
      const scope=BrachyBotTimepoints.captureSubmission();
      const response=await BrachyBotTimepoints.request(scope,'/api/sessions/'+sid+'/timepoints/'+tid+'/workspace',{
        method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_state_revision:version,
          patch:{ui:{state:{controls:{importWorkspaceFile:{value:'C:\\fakepath\\legacy-workspace.zip'}}}}}})});
      return {status:response.status,body:await response.json()};
    },{version:afterState.timepoint_state_revision,sid:auth.active_session_id,tid:A});
    assert.equal(legacy.status,200,JSON.stringify(legacy.body));
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(a=>BrachyBotTimepoints.enabled() && BrachyBotTimepointWorkspace.requestReady() && BrachyBotTimepointWorkspace.resourceState()?.ready
      && BrachyBotTimepoints.captureTarget().timepointId===a && JSON.stringify(state.ctShape)==='[12,18,20]',A);
    assert.equal(await page.locator('#inLowestEnergy').inputValue(),'130');
    await page.locator('#timepointTabs [data-timepoint-id="'+B+'"]').click();
    await page.waitForFunction(b=>BrachyBotTimepointWorkspace.requestReady() && BrachyBotTimepoints.captureTarget().timepointId===b
      && BrachyBotTimepointWorkspace.resourceState()?.ready && JSON.stringify(state.ctShape)==='[14,16,22]',B);
    assert.equal(await page.evaluate(b=>BrachyBotTimepoints.getCatalog().timepoints.find(x=>x.id===b).preoperative_timepoint_id,B),A);
    await page.evaluate(()=>switchPanel('viewers',document.querySelector('[data-panel="viewers"]')));
    await page.waitForFunction(()=>document.querySelector('#timepointImageTree [data-image-id]'));
    const firstB=await page.evaluate(()=>BrachyBotTimepointWorkspace.resourceState().images.planning_reference_image_id);
    assert.equal(await page.locator('#dataTreeBody > [data-group="image"] [data-group="image_role_intraop"] [data-image-id]').count(),1);
    assert.equal(await page.locator('#dataTreeBody > [data-group="segmentation"][data-source-image-id="'+firstB+'"]').count(),1);
    assert.equal(await page.locator('#dataTreeBody .timepoint-data-root, #dataTreeBody [data-group^="segmentation_image_"]').count(),0);
    await page.locator('#timepointImageTree [data-image-id="'+firstB+'"] .tree-item').click({button:'right'});
    await page.locator('#ctxMenu button').filter({hasText:/^(移至：未分组图像|Move to: Images)$/}).click();
    await page.waitForFunction(id=>BrachyBotTimepointWorkspace.resourceState().images.images.find(x=>x.id===id)?.role==='unclassified',firstB);
    assert.equal(await page.locator('#timepointImageTree > [data-image-id="'+firstB+'"]').count(),1);
    await page.locator('#fileCT').setInputFiles(preoperative);
    await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState().images.images.length===2 && JSON.stringify(state.ctShape)==='[12,18,20]');
    const displayed=await page.evaluate(()=>BrachyBotTimepointWorkspace.resourceState().images.display_image_id);
    assert.notEqual(displayed,firstB);
    assert.equal(await page.evaluate(()=>BrachyBotTimepointWorkspace.resourceState().images.planning_reference_image_id),firstB);
    await page.waitForFunction(()=>document.querySelectorAll('#timepointImageTree [data-image-id]').length===2);
    await page.locator('#timepointImageTree [data-image-id="'+displayed+'"] .eye-btn').click();
    await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState().images.display_image_id===null);
    assert.equal(await page.evaluate(()=>state.ctLoaded),true);
    await page.locator('#timepointImageTree [data-image-id="'+firstB+'"] button').first().click();
    await page.waitForFunction(id=>BrachyBotTimepointWorkspace.resourceState().images.display_image_id===id && JSON.stringify(state.ctShape)==='[14,16,22]',firstB);
    await page.locator('#timepointImageTree [data-image-id="'+firstB+'"] .opacity-slider').evaluate(input=>{
      input.value='37';input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
    await page.waitForFunction(id=>BrachyBotTimepointWorkspace.resourceState().images.images.find(x=>x.id===id)?.opacity===.37,firstB);
    await page.evaluate(()=>BrachyBotTimepointWorkspace.persistPresentation());
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(b=>BrachyBotTimepointWorkspace.requestReady() && BrachyBotTimepointWorkspace.resourceState()?.ready
      && BrachyBotTimepoints.captureTarget().timepointId===b && state.ctLoaded && JSON.stringify(state.ctShape)==='[14,16,22]',B);
    assert.equal(await page.evaluate(id=>BrachyBotTimepointWorkspace.resourceState().images.images.find(x=>x.id===id).opacity,firstB),.37);
    assert.equal(await page.evaluate(()=>dataTreeState.ct.opacity),.37);
    assert.equal(await page.locator('#inLowestEnergy').inputValue(),'145');
    assert.equal(await page.locator('#maxIter').inputValue(),'9');
    for(let attempt=0;attempt<3;attempt++){
      await page.reload({waitUntil:'domcontentloaded'});
      await page.waitForFunction(b=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready
        &&BrachyBotTimepoints.captureTarget().timepointId===b&&state.ctLoaded&&JSON.stringify(state.ctShape)==='[14,16,22]',B);
      assert.equal(await page.evaluate(()=>dataTreeState.ct.opacity),.37);
    }
    const exportJob=await page.evaluate(async()=>{
      const r=await fetch('/api/data/exports',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({selections:[{object_id:'session:complete',format:'workspace_bundle'}],bundle_name:'synthetic_complete_patient'})});
      const data=await r.json();if(!r.ok)throw new Error(JSON.stringify(data));return data.job;});
    let job=exportJob;
    const deadline=Date.now()+60000;
    while(!['completed','completed_with_errors','failed','cancelled'].includes(job.status) && Date.now()<deadline){
      job=await page.evaluate(async id=>(await (await fetch('/api/data/exports/'+id)).json()).job,job.job_id);
      if(job.status==='running'||job.status==='queued') await page.waitForTimeout(300);
    }
    assert.equal(job.status,'completed',JSON.stringify(job));
    const bundle=job.files.find(file=>file.object_id==='session:complete');assert.ok(bundle);
    assert.ok(bundle.download_url,'The actual export response must supply an owned file URL');
    assert.equal(new URL(bundle.download_url,origin).searchParams.get('timepoint_id'),B);
    const archive=await page.request.get(new URL(bundle.download_url,origin).href);
    assert.equal(archive.status(),200);
    await page.evaluate(()=>{if(document.querySelector('#sessionSidebar').style.display==='none') toggleSessionSidebar();});
    const [chooser]=await Promise.all([page.waitForEvent('filechooser'),page.locator('#importWorkspaceButton').click()]);
    await chooser.setFiles({name:'complete_patient.zip',mimeType:'application/zip',buffer:await archive.body()});
    await page.locator('#_confirmYes').click();
    await page.waitForFunction(original=>BrachyBotTimepointWorkspace.requestReady() && BrachyBotTimepointWorkspace.resourceState()?.ready
      && BrachyBotTimepoints.captureTarget().sessionId!==original && state.ctLoaded,auth.active_session_id);
    const restored=await page.evaluate(()=>({scope:BrachyBotTimepoints.captureTarget(),catalog:BrachyBotTimepoints.getCatalog()}));
    assert.notEqual(restored.scope.sessionId,auth.active_session_id);
    assert.equal(restored.catalog.timepoints.length,2);
    assert.equal(restored.catalog.timepoints.find(row=>row.id===B).preoperative_timepoint_id,A);
    // Import creates a new Session, whose initial mounted row is not the old
    // Session's browser preference. Verify the actual mount before selecting B.
    assert.ok([A,B].includes(restored.scope.timepointId));
    assert.equal(await page.locator('#inLowestEnergy').inputValue(),restored.scope.timepointId===A?'130':'145');
    if(restored.scope.timepointId!==B){
      await page.locator('#timepointTabs [data-timepoint-id="'+B+'"]').click();
      await page.waitForFunction(b=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready
        &&BrachyBotTimepoints.captureTarget().timepointId===b,B);
    }
    assert.equal(await page.locator('#inLowestEnergy').inputValue(),'145');
    assert.equal(await page.locator('#maxIter').inputValue(),'9');
    const originalState=await page.request.get(origin+'/api/sessions/'+auth.active_session_id+'/timepoints/'+B+'/workspace');
    assert.equal((await originalState.json()).workspace.image_collection.images[firstB].opacity,.37);
    console.log('PASS actual complete-workspace export, native file chooser, import and independent new-session restoration');
    // Unified chrome is checked against the actual rendered page, not a mockup.
    await page.locator('[data-panel="viewers"]').click();
    const chrome=await page.evaluate(()=>{
      const bar=document.querySelector('#panelViewers .viewers-toolbar');
      return {implantInside:bar.contains(document.getElementById('implantObservationActions')),
        doseInside:!!bar.querySelector('[data-timepoint-dose]'),height:bar.getBoundingClientRect().height,
        wrap:getComputedStyle(bar).flexWrap,
        children:[...bar.children].map(n=>({id:n.id,tag:n.tagName,height:n.getBoundingClientRect().height,display:getComputedStyle(n).display})),
        fonts:[...document.querySelectorAll('#dataTreeBody .item-label')].map(n=>getComputedStyle(n).fontSize)};
    });
    if(process.env.BRACHYBOT_UI_ACCEPTANCE_DIR)await page.screenshot({path:process.env.BRACHYBOT_UI_ACCEPTANCE_DIR+'/viewer-desktop.png'});
    assert.equal(chrome.implantInside,true);assert.equal(chrome.doseInside,true);
    assert.equal(chrome.wrap,'nowrap');assert.ok(chrome.height<110,JSON.stringify(chrome));
    assert.ok(chrome.fonts.every(size=>size==='12px'),JSON.stringify(chrome));
    if(process.env.BRACHYBOT_UI_ACCEPTANCE_DIR)await page.screenshot({path:process.env.BRACHYBOT_UI_ACCEPTANCE_DIR+'/viewer-desktop.png'});
    const outgoing=await page.evaluate(()=>BrachyBotTimepoints.captureTarget());
    await page.evaluate(async()=>{
      for(const title of ['Synthetic fast switch A','Synthetic fast switch B']){
        const response=await fetch('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title})});
        if(!response.ok)throw Error('Cannot create isolated switching fixture');
      }
      await loadServerSessions({commit:false});
      const data=await (await fetch('/api/sessions')).json();
      for(const row of data.sessions)if(!sessions[row.id])sessions[row.id]={...row,messages:[]};
    });
    const targets=await page.evaluate(()=>Object.values(sessions).filter(row=>row.title.startsWith('Synthetic fast switch')).map(row=>row.id));
    assert.equal(targets.length,2);
    // Delay only transport; every response is still generated by the real API.
    await page.route('**/api/sessions/*/select',async route=>{await new Promise(r=>setTimeout(r,400));await route.continue();});
    const immediate=await page.evaluate(([first,last])=>{
      document.getElementById('viewerWindow').value='711';document.getElementById('viewerLevel').value='55';
      applyViewerSettings();
      void switchSession(first);const firstPaint=activeSessionId===first;
      void switchSession(last);return {firstPaint,lastPaint:activeSessionId===last,cleared:state.ctLoaded!==true};
    },targets);
    assert.deepEqual(immediate,{firstPaint:true,lastPaint:true,cleared:true});
    await page.waitForFunction(last=>activeSessionId===last && BrachyBotTimepoints.captureTarget().sessionId===last
      && BrachyBotTimepointWorkspace.resourceState()?.ready,targets[1]);
    await page.unroute('**/api/sessions/*/select');
    await page.evaluate(sid=>switchSession(sid),outgoing.sessionId);
    await page.waitForFunction(sid=>activeSessionId===sid && BrachyBotTimepointWorkspace.resourceState()?.ready && state.ctLoaded,outgoing.sessionId);
    assert.equal(await page.locator('#inLowestEnergy').inputValue(),'145');
    assert.equal(await page.locator('#maxIter').inputValue(),'9');
    assert.equal(await page.locator('#viewerWindow').inputValue(),'711');
    assert.equal(await page.locator('#viewerLevel').inputValue(),'55');
    console.log('PASS immediate rapid Session switching, cleared projection, last-click wins and outgoing-state preservation');
    assert.deepEqual(errors,[]);
    console.log('Full-product two-timepoint upload, switch and cold restoration passed.');
  } catch(error) {
    console.error('Safe product diagnostic:', await page.evaluate(() => {
      const result={};
      const read=(name,fn)=>{try{result[name]=fn();}catch(error){result[name]={error:String(error)};}};
      read('target',()=>window.BrachyBotTimepoints?.captureTarget?.());
      read('submission',()=>window.BrachyBotTimepoints?.captureSubmission?.());
      read('resource',()=>window.BrachyBotTimepointWorkspace?.resourceState?.());
      read('controllerState',()=>window.BrachyBotTimepoints?.getDataState?.(window.BrachyBotTimepoints.captureTarget()));
      read('visualReadiness',()=>Object.values(window.__workspaceVisualReadiness||{}).filter(Boolean).map(r=>({state:r.state,result:r.result})));
      read('catalog',()=>window.BrachyBotTimepoints?.getCatalog?.());
      read('timepointStatus',()=>document.querySelector('#timepointStatus')?.textContent);
      read('bodyText',()=>document.body.innerText.slice(0,3000));
      return result;
    }).catch(error=>({evaluationError:String(error)})));
    console.error('Product state:', await page.evaluate(()=>({errors:[],timepoint:window.BrachyBotTimepoints?.captureTarget?.(),
      resources:window.BrachyBotTimepointWorkspace?.resourceState?.(),ct:typeof state==='object'?{loaded:state.ctLoaded,shape:state.ctShape}:null,
      readiness:JSON.stringify(Object.values(window.__workspaceVisualReadiness||{}).map(r=>({state:r.state,result:r.result}))),
      message:document.querySelector('#timepointStatus')?.textContent,
      enabled:window.BrachyBotTimepoints?.enabled?.(), catalog:window.BrachyBotTimepoints?.getCatalog?.(),
      dependencies:window.BrachyBotTimepointWorkspace?.dependencies?.(),
      dependencyTypes:Object.fromEntries(['captureTimepointWorkspacePresentation','captureTimepointWorkspaceReport','applyTimepointWorkspaceSnapshot',
        'hydrateTimepointWorkspace','suspendTimepointWorkspace','_captureViewerDataScope','_viewerDataScopeIsCurrent',
        '_capturePlanningSceneScope','_planningSceneScopeIsCurrent','_fetchViewerJsonWithRetry','displayTimepointImage'].map(name=>[name,typeof window[name]]))})).catch(()=>({})));
    console.error('Page errors:',errors);
    throw error;
  } finally {await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
