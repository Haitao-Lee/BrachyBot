const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),base=process.argv[2];
 try {
  const r=await page.request.post(base+'/api/auth/register',{data:{username:'chrome_fixture',password:'synthetic-password-123'}});
  assert.equal(r.status(),201);
  await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.BrachyBotTimepointWorkspace?.resourceState?.()?.ready===true);
  await page.locator('[data-panel="viewers"]').click();
  const chrome=await page.evaluate(()=>{
   const b=document.querySelector('.viewers-toolbar');
   return {height:b.getBoundingClientRect().height,display:getComputedStyle(b).display,
    direction:getComputedStyle(b).flexDirection,wrap:getComputedStyle(b).flexWrap,
    children:[...b.children].map(n=>({id:n.id,tag:n.tagName,height:n.getBoundingClientRect().height,display:getComputedStyle(n).display})),
    implantInside:b.contains(document.getElementById('implantObservationActions')),
    doseInside:!!b.querySelector('[data-timepoint-dose]'),
    tall:[...b.querySelectorAll('*')].filter(n=>n.getBoundingClientRect().height>50).map(n=>({tag:n.tagName,id:n.id,height:n.getBoundingClientRect().height,text:n.textContent.slice(0,50)})),
    computed:{height:getComputedStyle(b).height,minHeight:getComputedStyle(b).minHeight,padding:getComputedStyle(b).padding,flex:getComputedStyle(b).flex}};
  });
  console.log(JSON.stringify(chrome));
  if(process.env.BRACHYBOT_UI_ACCEPTANCE_DIR)await page.screenshot({path:process.env.BRACHYBOT_UI_ACCEPTANCE_DIR+'/chrome-empty-desktop.png'});
  assert.ok(chrome.height<110);assert.equal(chrome.implantInside,true);assert.equal(chrome.doseInside,true);
  assert.equal(await page.locator('#overlayCTV').isChecked(),true);
  assert.equal(await page.locator('#overlayOAR').isChecked(),true);
  assert.equal(await page.locator('#labelShow3d').isChecked(),true);
  const recovery=await page.evaluate(()=>{
   const form=window.reportForm;
   const snapshot={session_id:state.sessionId,ui:{state:{controls:{overlayCTV:{checked:false},overlayOAR:{checked:false},labelShow3d:{checked:true}},viewer:{labelImage:{'3d':{visible:true,opacity:.7}},annotations:[{id:'generated',type:'planning_distance',visible:true},{id:'manual',type:'line',visible:true}]}}},report:{form:{...form,editedFields:{}}}};
   const migrated=window.normalizePlanningPresentationSnapshot(snapshot);
   const preserved=window.normalizePlanningPresentationSnapshot({ui:{state:{planning_presentation_defaults_version:1,controls:{overlayCTV:{checked:false}}}}});
   window.applyTimepointWorkspaceSnapshot(snapshot,window.BrachyBotTimepointWorkspace.mountedScope());
   // The late hydration path invokes the shared restore directly. It must
   // not undo the migration performed by the initial synchronous mount.
   window.applyWorkspaceSnapshot(snapshot,{timepointScope:window.BrachyBotTimepointWorkspace.mountedScope(),skipChat:true,preserveClinicalData:true,persist:false});
   const cloned=window.cloneWorkspaceJSON({editedFields:new Set(['interpretation'])});
   const result={originalLabel:snapshot.ui.state.viewer.labelImage['3d'].visible,
    originalFields:snapshot.report.form.editedFields,restoredFieldsIsSet:window.reportForm.editedFields instanceof Set,
    lateControls:{ctv:document.getElementById('overlayCTV').checked,oar:document.getElementById('overlayOAR').checked,label:document.getElementById('labelShow3d').checked},
    cloned:cloned.editedFields,legacyMap:[...window.normalizeReportEditedFields({interpretation:true,other:false})],
    migrated:migrated.ui.state,preserved:preserved.ui.state.controls.overlayCTV.checked,
    border:getComputedStyle(document.querySelector('.timepoint-strip')).borderBottomColor,
    text:getComputedStyle(document.querySelector('.timepoint-strip')).color};
   state.annotations=[{id:'generated',type:'planning_distance',visible:true,visible2D:true,visible3D:true},{id:'manual',type:'line',visible:true}];
   window.applyPlanningPresentationDefaults();
   result.completion={ctv:state.viewerSettings.showCTV,oar:state.viewerSettings.showOAR,label:state.labelImage['3d'].visible,
    generated:state.annotations[0].visible,manual:state.annotations[1].visible};
   state.annotations=[];
   return result;
  });
  assert.equal(recovery.originalLabel,true);assert.deepEqual(recovery.originalFields,{});
  assert.equal(recovery.restoredFieldsIsSet,true);assert.deepEqual(recovery.cloned,['interpretation']);
  assert.deepEqual(recovery.lateControls,{ctv:true,oar:true,label:true});
  assert.deepEqual(recovery.legacyMap,['interpretation']);
  assert.equal(recovery.migrated.controls.overlayCTV.checked,true);assert.equal(recovery.migrated.controls.overlayOAR.checked,true);
  assert.equal(recovery.migrated.viewer.labelImage['3d'].visible,true);assert.equal(recovery.migrated.viewer.labelImage['3d'].opacity,.7);
  assert.equal(recovery.migrated.viewer.annotations[0].visible,false);assert.equal(recovery.migrated.viewer.annotations[1].visible,true);
  assert.equal(recovery.preserved,false);assert.notEqual(recovery.border,recovery.text);
  assert.deepEqual(recovery.completion,{ctv:true,oar:true,label:true,generated:false,manual:true});
  console.log('Legacy report Set/object recovery, immutable snapshots, one-time defaults and subtle separator passed');
  await page.evaluate(()=>{
   const form=window.cloneWorkspaceJSON(window.reportForm);
   form.editedFields={interpretation:true};form.interpretation='Synthetic retained report text';
   window.__reportWorkspaceSnapshots=[{t:Date.now(),label:'Synthetic legacy report',form}];
   window.__acceptanceReportRestore=Report.snapshots.restore(0);
  });
  await page.locator('#_confirmYes').click();
  assert.equal(await page.evaluate(()=>window.__acceptanceReportRestore),true);
  assert.deepEqual(await page.evaluate(()=>({protected:window.reportForm.editedFields.has('interpretation'),
   text:window.reportForm.interpretation})),{protected:true,text:'Synthetic retained report text'});
  await page.locator('[data-panel="viewers"]').click();
  await page.locator('#doseColorbarButton').click();
  await page.waitForFunction(()=>!document.getElementById('doseColorbarPanel').hidden);
  const popover=await page.locator('#doseColorbarPanel').boundingBox();
  assert.ok(popover && popover.x>=0 && popover.y>=0 && popover.y+popover.height<=1000);
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>document.getElementById('doseColorbarPanel').hidden);
  await page.setViewportSize({width:900,height:900});
  assert.ok(await page.locator('#panelViewers .viewers-toolbar').evaluate(n=>n.getBoundingClientRect().height<110));
  if(process.env.BRACHYBOT_UI_ACCEPTANCE_DIR)await page.screenshot({path:process.env.BRACHYBOT_UI_ACCEPTANCE_DIR+'/chrome-narrow.png'});
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
