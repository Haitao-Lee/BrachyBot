// Real controller/adapter DOM interaction; synthetic HTTP and resource barriers.
const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'../web/app/static/js');
(async()=>{
    const browser=await chromium.launch({headless:true,args:['--no-sandbox'],
        ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE} : {})});
    try {
        const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
        await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<html><body></body></html>'}));
        await page.goto('http://timepoint-workspace.invalid/');
        await page.setContent('<div id="chatMessages">Shared chat sentinel</div><section id="timepointStrip"><div id="timepointTabs"></div><span id="timepointStatus"></span><button id="timepointAdd"></button><button id="timepointManage"></button></section><section id="panelInput"></section><section id="panelMetrics"></section><section id="panelViewers"></section><section id="panelReport"></section><div id="dataTreeBody"><span id="legacyTreeNode">Legacy tree</span></div><div id="dvhChart"></div><div id="dvhPlaceholder"></div>');
        await page.evaluate(()=>{
            window.activeSessionId='s';window._activeApiSessionId=()=>activeSessionId;window._i18nLang='en';window.calls=[];window.paints=[];
            window.catalog={session_id:'s',default_timepoint_id:'A',catalog_revision:1,capabilities:{execution_scope:true},timepoints:[{id:'A',title:'Baseline',stage:'preoperative',revision:1},{id:'B',title:'Intraop',stage:'intraoperative',preoperative_timepoint_id:'A',revision:1}]};
            window.ws={A:{session_id:'s',timepoint_id:'A',timepoint_state_revision:1,ui:{state:{viewer:{doseSourceSet:'implanted',scene:{camera_position:[1,2,3]}},data_tree:{seed_1:{color:'#00ffcc'}}}},report:{label:'Report A'}},
                B:{session_id:'s',timepoint_id:'B',timepoint_state_revision:1,ui:{state:{viewer:{doseSourceSet:'planned',scene:{camera_position:[4,5,6]}},data_tree:{seed_1:{color:'#ffaa00'}}}},report:{label:'Report B'}}};
            window.collections=Object.fromEntries(['A','B'].map(id=>[id,{session_id:'s',timepoint_id:id,collection_revision:1,images:[{id:'one',name:'same-name.nii.gz',path:'/owned/'+id+'/one'},{id:'two',name:'second.nii.gz',path:'/owned/'+id+'/two'}],display_image_id:'two',planning_reference_image_id:'one'}]));
            const response=data=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
            window.fetch=async(url,init={})=>{
                const parsed=new URL(url,location.href),headers=Object.fromEntries(new Headers(init.headers)),body=init.body?JSON.parse(init.body):null;
                const id=parsed.pathname.split('/')[5]||headers['x-brachybot-timepoint'];calls.push({path:parsed.pathname,method:init.method,headers,body});
                if(parsed.pathname==='/api/dose/view'){
                    if(window.emptyDose)return response({success:true,session_id:'s',timepoint_id:id,
                        source_set:parsed.searchParams.get('source_set'),available:false,stale:true});
                    const mode=parsed.searchParams.get('source_set');const dose={success:true,session_id:'s',timepoint_id:id,source_set:mode,available:mode!=='total',stale:false,dose_units:'gy',geometry_signature:'grid-'+id,shape:[1,1,1],spacing:[1,1,1],origin:[0,0,0],direction:[1,0,0,0,1,0,0,0,1],dose:[38.16],metrics:{D90:38.16},dvh:{CTV:{dose_bins:[0,38.16],volume_pcts:[100,0]}}};
                    if(window.deferDose){window.deferDose=false;return new Promise(resolve=>window.finishDose=()=>resolve(response(dose)));}return response(dose);
                }
                if(parsed.pathname.endsWith('/images')||parsed.pathname.includes('/images/')){
                    if(body?.display)collections[id].display_image_id=parsed.pathname.split('/').at(-1);
                    if(body?.planning_reference)collections[id].planning_reference_image_id=parsed.pathname.split('/').at(-1);
                    if(body)collections[id].collection_revision++;
                    if(window.deferImages){window.deferImages=false;return new Promise(resolve=>window.finishImages=()=>resolve(response(structuredClone(collections[id]))));}
                    return response(structuredClone(collections[id]));
                }
                if(parsed.pathname.endsWith('/workspace')){if(body){ws[id].ui=body.patch.ui;ws[id].report=body.patch.report||ws[id].report;ws[id].timepoint_state_revision++;catalog.catalog_revision++;}return response({success:true,workspace:structuredClone(ws[id])});}
                return response({success:true,...catalog});
            };
            window.captureTimepointWorkspacePresentation=()=>structuredClone(window.presentation||{});
            window.captureTimepointWorkspaceReport=()=>structuredClone(window.report||{});
            window.suspendTimepointWorkspace=()=>{window.presentation={};window.report={};paints.push('suspend');};
            window.applyTimepointWorkspaceSnapshot=(snapshot,scope)=>{window.presentation=structuredClone(snapshot.ui.state);window.report=structuredClone(snapshot.report);paints.push('commit:'+scope.timepointId);return true;};
            window.hydrateTimepointWorkspace=async(snapshot,scope)=>{
                if(window.deferHydrate){window.deferHydrate=false;await new Promise(resolve=>window.finishHydrate=resolve);}
                if(BrachyBotTimepointWorkspace.scopeIsCurrent(scope))paints.push('resources:'+scope.timepointId);
                return {ready:true};
            };
            window.displayTimepointImage=async(image,scope)=>{paints.push('image:'+scope.timepointId+':'+image.id);return {success:true};};
            window.state={ctShape:[1,1,1],ctSpacing:[1,1,1],ctOrigin:[0,0,0],ctDirection:[1,0,0,0,1,0,0,0,1],slices:{axial:0,coronal:0,sagittal:0}};
            window.clearDoseOverlayRuntime=()=>state.doseOverlay=null;window.updateMetrics=()=>{};window.updateOARTable=()=>{};window.updateSlice=()=>{};
            window.Plotly={purge:()=>{}};window.doseModelScaleGy=()=>190.8;window._confirmAction=async()=>true;
            window.__timepointFrontendContracts={viewer:1,planning:1,meshes:1,persistence:1};
        });
        await page.addScriptTag({path:path.join(root,'brachybot-timepoints.js')});
        await page.addScriptTag({path:path.join(root,'brachybot-timepoint-workspace.js')});
        assert.equal(await page.evaluate(()=>BrachyBotTimepoints.enabled()),false,'missing real restore contract keeps gate closed');
        await page.evaluate(()=>{
            // Only this isolated synthetic protocol harness supplies these
            // dependencies. Product acceptance loads all original scripts.
            window._captureViewerDataScope=()=>({});window._viewerDataScopeIsCurrent=()=>true;
            window._capturePlanningSceneScope=()=>({});window._planningSceneScopeIsCurrent=()=>true;
            window._fetchViewerJsonWithRetry=async()=>({});
            __timepointFrontendContracts.restore=1;deferImages=true;BrachyBotTimepointWorkspace.register();
        });
        await page.waitForFunction(()=>typeof finishImages==='function');
        assert.equal(await page.evaluate(()=>paints.some(v=>v.startsWith('commit:'))),false,'prepare must not paint');
        await page.evaluate(()=>finishImages());
        await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState()?.ready&&state.doseOverlay?.doseSource==='implanted');
        assert.equal(await page.locator('[data-timepoint-dose]').count(),2);
        assert.equal(await page.locator('#legacyTreeNode').textContent(),'Legacy tree');
        assert.equal(await page.locator('#timepointImageCollection').isVisible(),false,'Input does not duplicate the Data Tree image inventory');
        assert.equal(await page.evaluate(()=>state.doseOverlay.volumeMin*state.doseOverlay.doseScaleGy),38.16,'physical Gy converted exactly once');
        await page.getByLabel('Display image: same-name.nii.gz').first().click();
        await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState().images.display_image_id==='one');
        assert.equal(await page.evaluate(()=>collections.A.planning_reference_image_id),'one');
        await page.locator('#timepointImageTree [data-image-id="two"]').click({button:'right'});
        await page.locator('#ctxMenu button').filter({hasText:'Use as planning reference'}).click();
        await page.waitForFunction(()=>collections.A.planning_reference_image_id==='two');
        assert.equal(await page.evaluate(()=>collections.A.display_image_id),'one','planning reference does not replace display');
        await page.evaluate(()=>{deferDose=true;window.dosePromise=BrachyBotTimepointWorkspace.selectDose('implanted');});
        await page.waitForFunction(()=>typeof finishDose==='function');
        await page.evaluate(()=>BrachyBotTimepoints.select('B'));
        await page.waitForFunction(()=>state.doseOverlay?.doseSource==='planned');
        await page.evaluate(()=>finishDose());
        assert.equal(await page.evaluate(()=>dosePromise),false,'late dose A cannot paint B');
        assert.equal(await page.evaluate(()=>state.doseOverlay.doseSource),'planned');
        await page.locator('[data-timepoint-dose]').first().selectOption('total');
        await page.waitForFunction(()=>document.getElementById('timepointResourceStatus').textContent.includes('unavailable'));
        assert.equal(await page.evaluate(()=>state.doseOverlay),null,'unavailable total never falls back to planned dose');
        await page.evaluate(async()=>{
            emptyDose=true;ws.B.agent={planning_results:{}};
            await BrachyBotTimepoints.reload();
        });
        await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState()?.ready);
        assert.equal(await page.locator('#timepointResourceStatus').isVisible(),false,'Blank timepoint has no automatic stale-dose warning');
        await page.evaluate(async()=>{
            ws.B.agent.planning_results.dose_distribution={$available:true};
            await BrachyBotTimepoints.reload();
        });
        await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState()?.ready);
        assert.match(await page.locator('#timepointResourceStatus').innerText(),/stale/,'An invalidated saved dose still warns');
        await page.evaluate(()=>{emptyDose=false;delete ws.B.agent;});
        await page.evaluate(()=>{_i18nLang='zh';dispatchEvent(new Event('i18nchange'));});
        assert.match(await page.locator('[data-timepoint-dose]').first().innerText(),/体内已有粒子/);
        // The real bridge may have completed geometry but must not advertise
        // ready while observation/dose resources for that mount are pending.
        await page.evaluate(()=>{window.BrachyBotImplants={reload:()=>new Promise(resolve=>window.finishImplants=()=>resolve(true))};
            window.observationRestore=BrachyBotTimepointWorkspace.restoreActive();});
        await page.waitForFunction(()=>typeof finishImplants==='function');
        assert.equal(await page.evaluate(()=>BrachyBotTimepointWorkspace.resourceState().ready),false);
        await page.evaluate(()=>finishImplants());
        assert.equal(await page.evaluate(()=>observationRestore),true);
        assert.equal(await page.evaluate(()=>BrachyBotTimepointWorkspace.resourceState().ready),true);
        await page.evaluate(()=>delete window.BrachyBotImplants);
        await page.evaluate(()=>{const original=fetch;window.fetch=async(...args)=>{
            window.fetch=original;throw new Error('Synthetic one-shot connection interruption');};
            window.failedRestore=BrachyBotTimepointWorkspace.restoreActive();});
        assert.equal(await page.evaluate(()=>failedRestore),false);
        assert.equal(await page.evaluate(()=>BrachyBotTimepointWorkspace.resourceState().ready),false);
        assert.equal(await page.locator('#timepointRetryRestore').isVisible(),true);
        await page.locator('#timepointRetryRestore').click();
        await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState()?.ready);
        assert.equal(await page.locator('#timepointRetryRestore').isVisible(),false);
        await page.evaluate(()=>{deferHydrate=true;window.restorePromise=BrachyBotTimepointWorkspace.restoreActive();});
        await page.waitForFunction(()=>typeof finishHydrate==='function');
        await page.evaluate(()=>BrachyBotTimepoints.select('A'));
        await page.waitForFunction(()=>BrachyBotTimepointWorkspace.resourceState()?.ready&&BrachyBotTimepointWorkspace.mountedScope().timepointId==='A');
        const count=await page.evaluate(()=>paints.filter(v=>v==='resources:B').length);
        await page.evaluate(()=>finishHydrate());
        assert.equal(await page.evaluate(()=>restorePromise),false);
        assert.equal(await page.evaluate(()=>paints.filter(v=>v==='resources:B').length),count,'late B resource completion must not paint A');
        assert.equal(await page.locator('#chatMessages').textContent(),'Shared chat sentinel');
        assert.deepEqual(errors,[]);
        console.log('13 production adapter browser contracts passed (synthetic HTTP/resources).');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
