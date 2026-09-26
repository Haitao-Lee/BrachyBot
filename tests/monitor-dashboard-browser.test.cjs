// Synthetic fixtures only: no patient data, network requests or clinical jobs.
const {chromium} = require('playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = process.argv[2] || path.resolve(__dirname, '../web/app/static/js');
function extract(name) {
    const source = fs.readFileSync(path.join(root,'brachybot-3d-manual.js'),'utf8');
    const start = source.indexOf(`function ${name}(`);
    const ends = ['\nfunction ', '\nasync function ', '\nwindow.'].map(s=>source.indexOf(s,start+12)).filter(i=>i>0);
    return source.slice(start,Math.min(...ends));
}
(async()=>{
    const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH,
        args:['--enable-webgl','--enable-unsafe-swiftshader']});
    try {
        const page=await browser.newPage({viewport:{width:1100,height:800}}), errors=[];
        page.on('pageerror',error=>errors.push(String(error)));
        await page.setContent(`<body style="background:#0c1320;color:#dae5f2;font:14px Arial;display:flex;gap:20px">
            <div style="width:440px"><details id="monitorDashboard" open><summary></summary><div class="monitor-dashboard-body"></div></details><div id="cards"></div></div>
            <div id="viewer" style="width:580px;height:580px"></div></body>`);
        const css=fs.existsSync(path.join(root,'brachybot-monitor-dashboard.css')) ? path.join(root,'brachybot-monitor-dashboard.css')
            : path.join(root,'../css/brachybot-monitor-dashboard.css');
        await page.addStyleTag({path:css});
        await page.addScriptTag({path:path.join(root,'three.min.js')});
        await page.addScriptTag({content:`
            window.API='/api';window.lang='zh';window.caseId='c';
            window.trainingMonitorState={active:true,phase:'active',runId:'r'};
            window.manualPlanningState={planningVersion:2,planningId:'p'};
            window._activeApiSessionId=()=>caseId;window.monitorConversationLanguage=()=>lang;
            window.addChat=()=>{};window.reportUIEvent=async()=>{};
            window.requestPlanningAdvice=()=>{};window.stopTrainingMode=async()=>({success:true});
            window.decisions=[];window.performMonitorEditDecision=async (...args)=>decisions.push(args);
            window.fetch=async()=>({ok:true,json:async()=>({success:true,active:true,monitor_run_id:'r',
                overview:{planning_version:2,planning_id:'p',metrics:{v100:90.5,d90:121.4,v200:30.2},
                    stages:[{key:'ctv',state:'available'},{key:'report',state:'stale'}]}})});
            window.scene3D={scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(45,1,.1,1000),controls:{target:new THREE.Vector3()},meshes:{}};
            scene3D.renderer=new THREE.WebGLRenderer({preserveDrawingBuffer:true});scene3D.renderer.setSize(580,580);
            document.getElementById('viewer').append(scene3D.renderer.domElement);
            scene3D.requestRender=()=>scene3D.renderer.render(scene3D.scene,scene3D.camera);
            for(const [i,id] of ['seed_1','seed_2'].entries()){
                const mesh=new THREE.Mesh(new THREE.SphereGeometry(.8,24,16),new THREE.MeshBasicMaterial({color:0x20ccb0}));
                mesh.position.x=i*3;scene3D.meshes[id]=mesh;scene3D.scene.add(mesh);
            }
            scene3D.camera.position.set(0,0,35);scene3D.camera.lookAt(0,0,0);scene3D.camera.updateMatrixWorld(true);
            window._screenshot3DIdentityFor=id=>[id];window._screenshot3DVisibility=(id,mesh)=>({locatable:mesh.visible});
            window.sync3DCameraPose=pose=>{scene3D.camera.position.copy(pose.position);scene3D.camera.up.copy(pose.up);
                scene3D.controls.target.copy(pose.target);scene3D.camera.near=pose.near;scene3D.camera.far=pose.far;
                scene3D.camera.lookAt(pose.target);if(pose.quaternion)scene3D.camera.quaternion.copy(pose.quaternion);
                scene3D.camera.updateProjectionMatrix();scene3D.camera.updateMatrixWorld(true);};
            window.packet={session_id:'c',monitor_run_id:'r',language:'zh',event:{event_id:'e1',type:'manual.seed.drag',detail:{edit_evidence:{
                geometry_event_id:'e1',event_id:'e1',after_version:2,planning_id:'p',restore_token:'abcdef123456',dose:{after:{v100:90.5,d90:121.4,v200:30.2}}}}},
                interaction:{headline:'新增 1 组粒子间距问题',priority:'attention',severity:'warning',objects:[],dose_current:true,
                    spatial_refs:['seed_1','seed_2'],conflicts:[{first_id:'seed_1',second_id:'seed_2',surface_clearance_mm:.2}],
                    dose_note:'本次重算对应当前几何。',next_step:'先核对两枚粒子的间距；非预期移动可恢复。'},suggested_screenshot:null};
        `});
        for(const name of ['_project3DObjectBounds','_unionNormalizedBounds','focusPlanningObjectsForScreenshot'])
            await page.addScriptTag({content:extract(name)});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-interaction.js')});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-dashboard.js')});
        await page.evaluate(async()=>{ window.card=await receiveMonitorCheckpoint(packet); });
        await page.waitForFunction(()=>document.querySelector('.monitor-workflow').textContent.includes('报告'));
        assert.match(await page.locator('#monitorDashboard').innerText(),/90.50 %/);
        assert.equal(await page.locator('.monitor-finding').getAttribute('data-severity'),'warning');
        await page.getByLabel(/自动重算/).check();
        await page.getByRole('button',{name:'保留编辑',exact:true}).click();
        assert.equal(await page.evaluate(()=>decisions.length),1);
        await page.getByRole('button',{name:'定位对象',exact:true}).click();
        assert.equal(await page.evaluate(()=>scene3D.scene.getObjectByName('monitor-focus').children.length),2);
        assert.equal(await page.evaluate(()=>scene3D.meshes.seed_1.material.color.getHex()),0x20ccb0);
        await page.screenshot({path:path.join(__dirname,'monitor-dashboard-qa.png')});
        await page.getByRole('button',{name:'清除定位',exact:true}).click();
        assert.deepEqual(await page.evaluate(()=>scene3D.camera.position.toArray()),[0,0,35]);
        assert.equal(await page.evaluate(()=>!!scene3D.scene.getObjectByName('monitor-focus')),false);
        assert.equal(await page.evaluate(()=>{scene3D.meshes.seed_2.visible=false;return focusMonitorCheckpoint(['seed_1','seed_2'],{});}),false,
            'a partially hidden pair cannot be presented as fully located');
        await page.evaluate(()=>{manualPlanningState.monitorInteractionActive=true;renderMonitorDashboard([card],{});});
        assert.doesNotMatch(await page.locator('#monitorDashboard').innerText(),/90.50/,'drag previews are not current dose geometry');
        await page.evaluate(()=>{manualPlanningState.monitorInteractionActive=false;manualPlanningState.planningId='other-plan';renderMonitorDashboard([card],{});});
        assert.doesNotMatch(await page.locator('#monitorDashboard').innerText(),/90.50/,'equal version in a different plan must not reuse metrics');
        await page.evaluate(()=>{lang='en';renderMonitorDashboard([],{});});
        assert.match(await page.locator('#monitorDashboard').innerText(),/Monitor workspace/);
        await page.evaluate(()=>{caseId='other';renderMonitorDashboard([],{});});
        assert.doesNotMatch(await page.locator('#monitorDashboard').innerText(),/90.50/,'case switch must not retain metrics');
        await page.evaluate(()=>{trainingMonitorState.phase='inactive';trainingMonitorState.active=false;refreshMonitorCheckpointPresentation('inactive');});
        assert.equal(await page.locator('#monitorDashboard').isVisible(),false);
        assert.deepEqual(errors,[]);
        console.log('Browser HUD: localized controls, current metrics, stale workflow, direct decisions, real WebGL outlines, exact restoration and case fencing passed.');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
