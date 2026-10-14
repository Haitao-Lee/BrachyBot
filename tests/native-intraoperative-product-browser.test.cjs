// Actual native planning entry + actual supplied detector. Upstream source-plan
// and mask inputs are explicitly synthetic, not claimed clinical planning.
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const [origin,target,workflow]=process.argv.slice(2);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
  args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.setDefaultTimeout(90000);page.on('pageerror',e=>errors.push(e.stack));
 page.on('console',c=>{if(['error','warning'].includes(c.type()))console.log(c.text());});
 page.on('response',r=>{if(r.url().startsWith(origin+'/api/')&&r.status()>=400)void r.text().then(t=>console.log('API',r.status(),new URL(r.url()).pathname,t.slice(0,1000))).catch(()=>{});});
 try{
  assert.equal((await page.request.post(origin+'/api/auth/login',{data:{username:'native_intraoperative_owner',password:'synthetic-browser-password-123'}})).status(),200);
  await page.goto(origin+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready);
  await page.locator('#timepointTabs [data-timepoint-id="'+target+'"]').click();
  await page.waitForFunction(id=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready
    &&BrachyBotTimepoints.captureSubmission().timepointId===id,target);
  const replies=page.waitForResponse(r=>r.url().endsWith('/planning/run_step')&&r.request().method()==='POST');
  void replies.catch(()=>{}); // keep click failures observable, not an unhandled sibling timeout
  await page.locator('button[onclick="runIntra()"]:visible').click();
  const reply=await replies;assert.equal(reply.status(),202,await reply.text());
  const packet=await reply.json();assert.equal(packet.pending_review,true);assert.equal(packet.planning_completed,false);
  assert.equal(packet.phase,'awaiting_observation_review');
  await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState()?.ready&&BrachyBotImplants.snapshot()?.active_count>0);
  assert.equal(await page.evaluate(()=>BrachyBotImplants.snapshot().dose_input_ready),false);
  await page.locator('[data-panel="viewers"]').click();
  await page.waitForFunction(()=>BrachyBotImplants.snapshot().nodes.filter(r=>!r.excluded).every(r=>scene3D.meshes[r.id]));
  const count=await page.evaluate(()=>BrachyBotImplants.snapshot().active_count);
  assert.ok(count>1,'Detected source count is not forced to match the one-source preoperative input');
  assert.equal(await page.locator('#implantedObservationTree .implant-tree-item').count(),count);
  const legacy=await page.evaluate(async()=>{
   const scope=BrachyBotTimepoints.captureSubmission(),images=BrachyBotTimepointWorkspace.resourceState().images;
   const ref=images.images.find(image=>image.id===images.planning_reference_image_id);
   const response=await BrachyBotTimepoints.request(scope,'/api/plan/intraoperative',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({ct_path:ref.path,planning_reference_image_id:ref.id,use_current_plan:true})});
   return {status:response.status,packet:await response.json()};
  });
  assert.equal(legacy.status,202);assert.equal(legacy.packet.phase,'awaiting_observation_review');
  assert.equal(legacy.packet.metadata.implant_view.active_count,count,'Legacy alias reuses current observations, not a count-matched old plan');
  const wrongStage=await page.evaluate(async()=>{
   const scope=BrachyBotTimepoints.captureSubmission();
   const response=await BrachyBotTimepoints.request(scope,'/api/plan/preoperative',{method:'POST',
    headers:{'Content-Type':'application/json','X-BrachyBot-Language':'en'},body:JSON.stringify({})});
   return {status:response.status,packet:await response.json()};
  });
  assert.equal(wrongStage.status,400);
  assert.equal(wrongStage.packet.code,'preoperative_timepoint_required');
  assert.match(wrongStage.packet.error,/intraoperative/i);
  assert.equal(await page.evaluate(()=>BrachyBotImplants.snapshot().active_count),count);
  if(workflow==='complete'){
   // Declared software-test settings/low prescription, not clinical adequacy.
   await page.locator('#implantSourceSettings').click();
   await page.getByLabel('Source length (mm)').fill('4.5');
   await page.getByLabel('Source radius (mm)').fill('0.4');
   await page.locator('.timepoint-modal button[type="submit"]').click();
   await page.waitForFunction(()=>!document.querySelector('.timepoint-modal')&&BrachyBotTimepointWorkspace.resourceState()?.ready);
   assert.equal(await page.locator('#seedLength').inputValue(),'4.5','Confirmed physical source sets owned supplemental dimensions');
   assert.equal(await page.locator('#seedRadius').inputValue(),'0.4');
   await page.locator('#implantRecomputeDose').click();
   await page.waitForFunction(()=>BrachyBotImplants.snapshot()?.implanted_dose&&!BrachyBotImplants.snapshot().implanted_dose.stale
       &&!document.querySelector('#implantRecomputeDose').disabled);
   await page.locator('#implantReviewObservations').click();
   await page.locator('.timepoint-modal input[type="checkbox"]').nth(0).check();
   await page.locator('.timepoint-modal input[type="checkbox"]').nth(1).check();
   await page.locator('.timepoint-modal textarea').fill('Software composition with synthetic target and low prescription; not clinical approval.');
   await page.locator('.timepoint-modal button[type="submit"]').click();
   await page.waitForFunction(()=>BrachyBotImplants.snapshot()?.dose_input_ready&&BrachyBotTimepointWorkspace.resourceState()?.ready);
   await page.evaluate(()=>BrachyBotTimepointWorkspace.continuationSettings());
   for(const [key,value] of Object.entries({needle_radius_mm:.5,minimum_guiding_length_mm:2,
       obstacle_clearance_mm:.2,maximum_depth_mm:200}))
    await page.locator('.timepoint-modal input[name="'+key+'"]').fill(String(value));
   await page.locator('.timepoint-modal input[type="checkbox"]').check();
   await page.locator('.timepoint-modal button[type="submit"]').click();
   await page.waitForFunction(()=>!document.querySelector('.timepoint-modal')&&BrachyBotTimepointWorkspace.resourceState()?.ready);
   await page.locator('[data-panel="input"]').click();
   await page.locator('[aria-controls="hyperparamsSection"]').click();
   await page.locator('#inLowestEnergy').fill('1');
   const completion=page.waitForResponse(r=>r.url().endsWith('/planning/run_step')&&r.request().method()==='POST');
   void completion.catch(()=>{});
   await page.locator('button[onclick="runIntra()"]:visible').click();
   const done=await completion;assert.equal(done.status(),200,await done.text());
   const completed=await done.json();assert.equal(completed.success,true,JSON.stringify(completed));
   assert.equal(completed.metadata.planning_projection.seed_count,0,'Sufficient observed dose adds no future sources');
   await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState()?.ready);
   const total=await page.evaluate(async()=>{
    const r=await BrachyBotTimepoints.request(BrachyBotTimepoints.captureSubmission(),'/api/dose/view?source_set=total');
    const data=await r.json();delete data.dose;return {status:r.status,data};
   });
   assert.equal(total.status,200);assert.equal(total.data.available,true);assert.equal(total.data.stale,false);
   assert.equal(total.data.source_count,count);assert.equal(total.data.metrics.source_set,'total');
   assert.equal(await page.evaluate(()=>BrachyBotImplants.snapshot().active_count),count);
   console.log('Reviewed native continuation completed with actual CNN baseline and zero future sources; synthetic software inputs only.');
  }
  assert.deepEqual(errors,[]);
  console.log('Actual native intraoperative pipeline detected and displayed sources, paused for review, and did not claim completion.');
 }catch(e){console.error('NATIVE STATE',await page.evaluate(()=>({resource:BrachyBotTimepointWorkspace.resourceState(),
  observations:BrachyBotImplants.snapshot()?.active_count,readiness:JSON.stringify(Object.values(window.__workspaceVisualReadiness||{}).map(r=>r.result))})).catch(()=>({})));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
