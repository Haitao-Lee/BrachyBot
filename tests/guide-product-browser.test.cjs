// Actual full application, owned endpoints, CPU registration and human review.
// The acquisition/printed mesh are declared synthetic software fixtures.
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const [origin,target]=process.argv.slice(2);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
  args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1600,height:1200}}),errors=[];
 page.setDefaultTimeout(60000);page.on('pageerror',e=>errors.push(e.stack));
 page.on('console',c=>{if(['warning','error'].includes(c.type()))console.log(c.text());});
 page.on('response',r=>{if(r.url().startsWith(origin+'/api/')&&r.status()>=400)void r.text().then(t=>console.log('API',r.status(),new URL(r.url()).pathname,t.slice(0,350))).catch(()=>{});});
 try{
  const login=await page.request.post(origin+'/api/auth/login',{data:{username:'guide_product_owner',password:'synthetic-browser-password-123'}});
  assert.equal(login.status(),200);
  await page.goto(origin+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready);
  await page.locator('#timepointTabs [data-timepoint-id="'+target+'"]').click();
  await page.waitForFunction(id=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready
   &&BrachyBotTimepoints.captureSubmission().timepointId===id,target);
  const panel=page.locator('#timepointGuideReview');
  await panel.locator('[name="guide_version"] option').first().waitFor({state:'attached'});
  await panel.locator('[name="manufactured_guide_id"]').fill('physical-guide-phantom');
  await panel.locator('[name="method"]').selectOption('image_rigid');
  const registered=page.waitForResponse(r=>r.url().endsWith('/guide-registration/jobs')&&r.request().method()==='POST');
  await panel.getByRole('button',{name:'Estimate placement',exact:true}).click();
  const start=await registered;assert.equal(start.status(),202,await start.text());
  await panel.getByRole('button',{name:'Confirm guide fit',exact:true}).waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelectorAll('#timepointGuideReview canvas').length===4
   &&[...document.querySelectorAll('#timepointGuideReview button')].find(b=>b.textContent==='Confirm guide fit')?.disabled===false);
  assert.equal(await panel.locator('canvas').count(),4);
  await panel.locator('[name="profile_id"]').fill('synthetic-overlay-review');
  await panel.locator('[name="note"]').fill('Software acceptance on synthetic phantom only; not clinical fit or printing approval.');
  await panel.locator('input[type="checkbox"]').check();
  const accepted=page.waitForResponse(r=>r.url().endsWith('/review')&&r.request().method()==='POST');
  await panel.getByRole('button',{name:'Confirm guide fit',exact:true}).click();
  const review=await accepted;assert.equal(review.status(),200,await review.text());
  const packet=await review.json();assert.equal(packet.placement.review_state,'accepted');
  assert.equal(packet.clinical_use_approved,false);
  await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState()?.ready);
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(id=>BrachyBotTimepointWorkspace.requestReady()&&BrachyBotTimepointWorkspace.resourceState()?.ready
   &&BrachyBotTimepoints.captureSubmission().timepointId===id,target);
  await page.waitForFunction(()=>[...document.querySelectorAll('#timepointGuideReview [name="placement_id"] option')]
   .some(o=>o.textContent.includes('Guide fit confirmed')));
  await panel.getByRole('button',{name:'Display fit overlays',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('#timepointGuideReview canvas').length===4);
  const rejected=page.waitForResponse(r=>r.url().endsWith('/review')&&r.request().method()==='POST');
  await panel.locator('[name="profile_id"]').fill('synthetic-overlay-rejection');
  await panel.locator('[name="note"]').fill('Synthetic rejection recovery test; do not initialize guide trajectories.');
  await panel.getByRole('button',{name:'Reject placement',exact:true}).click();
  const rejection=await rejected;assert.equal(rejection.status(),200,await rejection.text());
  assert.equal((await rejection.json()).placement.review_state,'rejected');
  assert.deepEqual(errors,[]);
  console.log('Actual product guide CPU registration, owned CT overlays, explicit human confirmation, cold restore and rejection passed.');
 }catch(e){console.error('RESTORE',await page.evaluate(()=>({resource:BrachyBotTimepointWorkspace.resourceState(),
   readiness:JSON.stringify(Object.values(window.__workspaceVisualReadiness||{}).map(r=>({state:r.state,result:r.result})))})).catch(()=>({})));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
