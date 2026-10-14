// Actual supplied detector, routes, immutable journal, THREE and pointer input.
// Source dimensions/review notes below are software-test inputs, not approval.
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const [origin,source]=process.argv.slice(2);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
  args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.setDefaultTimeout(60000);page.on('pageerror',e=>errors.push(e.stack));
 page.on('response',r=>{if(r.url().startsWith(origin+'/api/')&&r.status()>=400)void r.text().then(t=>console.log('API',r.status(),new URL(r.url()).pathname,t.slice(0,350))).catch(()=>{});});
 page.on('request',r=>{if(/dose\/recompute|dose-source|implants\/(detect|review|corrections)/.test(r.url()))console.log('CLINICAL REQUEST',r.method(),new URL(r.url()).pathname);});
 page.on('console',c=>{if(c.type()==='error'||c.type()==='warning'||c.text().startsWith('IMPLANT INPUT'))console.log('BROWSER',c.text());});
 try{
  assert.equal((await page.request.post(origin+'/api/auth/register',{data:{username:'real_implant_browser',password:'synthetic-browser-password-123'}})).status(),201);
  await page.goto(origin+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready);
  await page.locator('#fileCT').setInputFiles(source);
  await page.waitForFunction(()=>state.ctLoaded&&BrachyBotTimepointWorkspace.resourceState().images.images.length===1);
  await page.locator('[data-panel="viewers"]').click();
  await page.locator('#implantDetect').click();
  await page.waitForFunction(()=>BrachyBotImplants.snapshot()?.active_count>0&&!document.querySelector('#implantDetect').disabled);
  const original=await page.evaluate(()=>BrachyBotImplants.snapshot());
  const first=original.nodes.find(row=>!row.excluded),count=original.active_count;
  const row=page.locator('#implantedObservationTree [data-node-id="'+first.id+'"]');
  assert.equal(await page.locator('#implantedObservationTree [data-node-type="implanted_observation"]').count(),count);
  assert.equal(await page.evaluate(()=>Object.values(scene3D.meshes).filter(o=>o.userData?.type==='implanted_observation').length),count);
  await row.locator('.item-label').click();
  assert.equal(await page.locator('#implantOverlay-axial').count(),1);
  await row.locator('.eye-btn').click();
  await page.waitForFunction(id=>scene3D.meshes[id]?.visible===false,first.id);
  await row.locator('.eye-btn').click();
  await page.waitForFunction(id=>scene3D.meshes[id]?.visible===true,first.id);
  await row.locator('.implant-color').evaluate(input=>{input.value='#ff33bb';input.dispatchEvent(new Event('input',{bubbles:true}));});
  await row.locator('.opacity-slider').evaluate(input=>{input.value='61';input.dispatchEvent(new Event('input',{bubbles:true}));});
  await page.waitForFunction(id=>BrachyBotImplants.snapshot().nodes.find(x=>x.id===id)?.opacity===.61,first.id);
  await page.locator('#implantSourceSettings').click();
  await page.getByLabel('Source length (mm)').fill('4.5');await page.getByLabel('Source radius (mm)').fill('0.4');
  await page.locator('.timepoint-modal button[type="submit"]').click();
  await page.waitForFunction(()=>!document.querySelector('.timepoint-modal')&&BrachyBotTimepointWorkspace.requestReady()
    &&BrachyBotTimepointWorkspace.resourceState()?.ready&&!document.querySelector('#implantRecomputeDose').disabled);
  console.log('RECOMPUTE CONTROL',await page.locator('#implantRecomputeDose').evaluate(node=>({
    handler:String(node.onclick),type:node.type,label:node.textContent,disabled:node.disabled,
    duplicates:document.querySelectorAll('#implantRecomputeDose').length})));
  await page.evaluate(()=>{for(const type of ['pointerdown','pointerup','click','scroll','focusin','i18nchange'])document.addEventListener(type,event=>{
    console.log('IMPLANT INPUT',JSON.stringify({type,target:event.target.id,disabled:event.target.disabled,
      connected:event.target.isConnected,button:document.querySelector('#implantRecomputeDose')?.disabled,
      tag:event.target.tagName,cls:event.target.className,menu:!!document.querySelector('.ctx-menu'),
      status:document.querySelector('#implantObservationStatus')?.textContent}));},true);});
  await page.locator('#implantRecomputeDose').click();
  await page.waitForFunction(()=>BrachyBotImplants.snapshot()?.implanted_dose&&!BrachyBotImplants.snapshot().implanted_dose.stale
      &&!document.querySelector('#implantRecomputeDose').disabled);
  const dose=await page.evaluate(()=>BrachyBotImplants.snapshot().implanted_dose);
  assert.ok(dose);
  await page.locator('#implantAddMissed').click();
  const canvas=page.locator('#sliceCanvasAxial');const rect=await canvas.boundingBox();assert.ok(rect);
  await page.mouse.click(rect.x+rect.width*.5,rect.y+rect.height*.5);
  await page.waitForFunction(()=>scene3D.meshes.implant_draft&&BrachyBotImplants.interactionMode()==='refining');
  await page.locator('button[onclick="reset3DView()"]').click();
  const projected=await page.evaluate(()=>{scene3D.scene.updateMatrixWorld(true);scene3D.camera.updateMatrixWorld();
    const o=scene3D.meshes.implant_draft,point=o.position.clone().project(scene3D.camera),box=scene3D.renderer.domElement.getBoundingClientRect();
    return{x:box.left+(point.x+1)*box.width/2,y:box.top+(1-point.y)*box.height/2,z:point.z,before:o.position.toArray()};});
  assert.ok(projected.z>=-1&&projected.z<=1,JSON.stringify(projected));
  await page.mouse.move(projected.x,projected.y);await page.mouse.down();
  await page.mouse.move(projected.x+8,projected.y+5,{steps:5});await page.mouse.up();
  const moved=await page.evaluate(()=>scene3D.meshes.implant_draft.position.toArray());
  assert.ok(moved.some((x,i)=>Math.abs(x-projected.before[i])>1e-4),'Real 3D drag must refine the draft');
  await page.locator('#implantSaveCorrection').click();
  await page.waitForFunction(n=>BrachyBotImplants.snapshot()?.active_count===n+1&&!document.querySelector('#implantDetect').disabled,count);
  assert.equal(await page.evaluate(()=>BrachyBotImplants.snapshot().implanted_dose?.stale),true);
  const added=await page.evaluate(ids=>BrachyBotImplants.snapshot().nodes.find(row=>!ids.includes(row.observation_id)),original.nodes.map(row=>row.observation_id));
  assert.ok(added);added.position.forEach((x,i)=>assert.ok(Math.abs(x-moved[i])<1e-4));
  const addedRow=page.locator('#implantedObservationTree [data-node-id="'+added.id+'"]');
  await addedRow.click({button:'right'});
  await page.locator('.ctx-menu-item').filter({hasText:'Exclude detection (not physical implant)'}).click();
  await page.locator('#_confirmYes').click();
  await page.waitForFunction(n=>BrachyBotImplants.snapshot()?.active_count===n,count);
  await page.locator('#implantRecomputeDose').click();
  await page.waitForFunction(()=>BrachyBotImplants.snapshot()?.implanted_dose&&!BrachyBotImplants.snapshot().implanted_dose.stale
      &&!document.querySelector('#implantRecomputeDose').disabled);
  await page.locator('#implantReviewObservations').click();
  await page.locator('.timepoint-modal input[type="checkbox"]').nth(0).check();
  await page.locator('.timepoint-modal input[type="checkbox"]').nth(1).check();
  await page.locator('.timepoint-modal textarea').fill('Software acceptance on supplied demo only; not clinical approval.');
  await page.locator('.timepoint-modal button[type="submit"]').click();
  await page.waitForFunction(()=>BrachyBotImplants.snapshot()?.dose_input_ready===true);
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(n=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready
      &&BrachyBotImplants.snapshot()?.active_count===n,count);
  const saved=await page.evaluate(id=>BrachyBotImplants.snapshot().nodes.find(row=>row.id===id),first.id);
  assert.equal(saved.color.toLowerCase(),'#ff33bb');assert.equal(saved.opacity,.61);
  assert.equal(await page.evaluate(()=>BrachyBotImplants.snapshot().nodes.filter(row=>row.excluded).length),1);
  assert.equal(await page.locator('#canvas3D .viewer-no-data').isVisible(),false,'Existing observed geometry is not an empty 3D scene');
  const common=await page.evaluate(id=>({visibility:setDataItemVisibility(id,false),
      color:setDataTreeItemColor(id,'#aaff22'),opacity:setDataOpacity(id,42)}),first.id);
  assert.deepEqual(common,{visibility:true,color:true,opacity:true});
  await page.waitForFunction(id=>scene3D.meshes[id]?.visible===false&&BrachyBotImplants.snapshot().nodes.find(r=>r.id===id)?.opacity===.42,first.id);
  await page.evaluate(id=>setDataItemVisibility(id,true),first.id);
  const appearance=page.waitForResponse(r=>r.url().endsWith('/implants/presentation')&&r.request().method()==='PATCH');
  assert.equal((await appearance).status(),200);
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready&&BrachyBotImplants.snapshot()?.active_count>0);
  const commonSaved=await page.evaluate(id=>BrachyBotImplants.snapshot().nodes.find(r=>r.id===id),first.id);
  assert.equal(commonSaved.color.toLowerCase(),'#aaff22');assert.equal(commonSaved.opacity,.42);
  assert.equal(commonSaved.visible,true);
  await page.evaluate(()=>setGroupVisibility('planning',false));
  assert.equal(await page.evaluate(id=>scene3D.meshes[id].visible,first.id),false);
  assert.equal(await page.evaluate(id=>BrachyBotImplants.snapshot().nodes.find(r=>r.id===id).visible,first.id),true);
  await page.evaluate(()=>setGroupVisibility('planning',true));
  assert.equal(await page.evaluate(id=>scene3D.meshes[id].visible,first.id),true);
  for(let attempt=0;attempt<3;attempt++){
   await page.reload({waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready&&BrachyBotImplants.snapshot()?.active_count>0);
   const restored=await page.evaluate(id=>BrachyBotImplants.snapshot().nodes.find(r=>r.id===id),first.id);
   assert.equal(restored.color.toLowerCase(),'#aaff22');assert.equal(restored.opacity,.42);
  }
  assert.deepEqual(errors,[]);
  if(process.env.BRACHYBOT_ACCEPTANCE_SCREENSHOT)await page.screenshot({path:process.env.BRACHYBOT_ACCEPTANCE_SCREENSHOT,fullPage:true});
  console.log('Actual model + 2D/3D/tree presentation, pointer correction, dose invalidation/recompute, human review and cold restore passed;',count,'observations.');
 }catch(e){console.error('SCENE',await page.evaluate(()=>({resource:BrachyBotTimepointWorkspace.resourceState(),
   readiness:JSON.stringify(Object.values(window.__workspaceVisualReadiness||{}).map(r=>({state:r.state,result:r.result}))),
   observations:BrachyBotImplants.snapshot()?.nodes?.map(n=>({id:n.id,axis:n.axis,excluded:n.excluded})),
   status:document.querySelector('#implantObservationStatus')?.textContent,errors:[]})).catch(()=>({})));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
