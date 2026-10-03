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
            window.addChat=(_type,_text,_scroll,_at,_from,_session,meta)=>{if(!meta)return;
                let row=document.querySelector('[data-message-id="'+meta.messageId+'"]');if(!row){row=document.createElement('div');row.dataset.messageId=meta.messageId;document.getElementById('cards').append(row);}};
            window.captureRequests=[];window.reportUIEvent=async (...args)=>captureRequests.push(args);
            window.requestPlanningAdvice=()=>{};window.stopTrainingMode=async()=>({success:true});
            window.decisions=[];window.performMonitorEditDecision=async (...args)=>decisions.push(args);
            window.fetch=async url=>({ok:true,json:async()=>url.includes('/timeline')?
                {success:true,active:true,monitor_run_id:'r',event_count:12,event_counts:{'manual.seed.drag':5},returned_event_count:3,dropped_event_count:0,
                    events:[90,91,80].map((v,i)=>({ts:i+1,type:'manual.dose',severity:'info',dose_sample:{series_key:i===2?'other':'same',
                        comparable:true,before:{v100:v-1},after:{v100:v}}}))}:
                {success:true,active:true,monitor_run_id:'r',overview:{planning_version:2,planning_id:'p',metrics:{v100:90.5,d90:121.4,v200:30.2,plan_score:83.2},
                    recorded_oars:[{organ:'cord',dmax:20}],coverage_target_percent:92,
                    stages:[{key:'ctv',state:'available'},{key:'report',state:'stale'}]}}});
            window.scene3D={scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(45,1,.1,1000),controls:{target:new THREE.Vector3()},meshes:{}};
            scene3D.renderer=new THREE.WebGLRenderer({preserveDrawingBuffer:true});scene3D.renderer.setSize(580,580);
            document.getElementById('viewer').append(scene3D.renderer.domElement);
            scene3D.requestRender=()=>scene3D.renderer.render(scene3D.scene,scene3D.camera);
            for(const [i,id] of ['seed_1','seed_2'].entries()){
                const mesh=new THREE.Mesh(new THREE.SphereGeometry(.8,24,16),new THREE.MeshBasicMaterial({color:0x20ccb0}));
                mesh.position.x=i*1.2;scene3D.meshes[id]=mesh;scene3D.scene.add(mesh);
            }
            scene3D.camera.position.set(0,0,35);scene3D.camera.lookAt(0,0,0);scene3D.camera.updateMatrixWorld(true);
            window._screenshot3DIdentityFor=id=>[id];window._screenshot3DVisibility=(id,mesh)=>({locatable:mesh.visible});
            window.sync3DCameraPose=pose=>{scene3D.camera.position.copy(pose.position);scene3D.camera.up.copy(pose.up);
                scene3D.controls.target.copy(pose.target);scene3D.camera.near=pose.near;scene3D.camera.far=pose.far;
                scene3D.camera.lookAt(pose.target);if(pose.quaternion)scene3D.camera.quaternion.copy(pose.quaternion);
                scene3D.camera.updateProjectionMatrix();scene3D.camera.updateMatrixWorld(true);};
            window.packet={session_id:'c',monitor_run_id:'r',language:'zh',event:{event_id:'e1',type:'manual.seed.drag',detail:{edit_evidence:{
                geometry_event_id:'e1',event_id:'e1',after_version:2,planning_id:'p',restore_token:'abcdef123456',dose:{after:{v100:90.5,d90:121.4,v200:30.2,plan_score:83.2}},
                conflicts:[{first_id:'seed_1',second_id:'seed_2',change:'new',risk:'overlap',physical_overlap:true,
                    measurement:{coordinate_system:'patient_world_mm',clearance_basis:'finite_parallel_cylinders',
                    points:[[0,0,0],[1.2,0,0]],value_mm:1.2,surface_clearance_mm:-.4}}]}}},
                interaction:{headline:'新增 1 组粒子间距问题',priority:'attention',severity:'blocking',objects:[],dose_current:true,
                    spatial_refs:['seed_1','seed_2'],conflicts:[{first_id:'seed_1',second_id:'seed_2',surface_clearance_mm:-.4,clearance_basis:'finite_parallel_cylinders',physical_overlap:true}],
                    dose_note:'本次重算对应当前几何。',next_step:'先核对两枚粒子的间距；非预期移动可恢复。'},suggested_screenshot:null};
        `});
        for(const name of ['_project3DObjectBounds','_unionNormalizedBounds','focusPlanningObjectsForScreenshot'])
            await page.addScriptTag({content:extract(name)});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-interaction.js')});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-dashboard.js')});
        await page.evaluate(async()=>{ window.card=await receiveMonitorCheckpoint(packet); });
        await page.waitForFunction(()=>document.querySelector('.monitor-workflow').textContent.includes('报告'));
        assert.match(await page.locator('#monitorDashboard').innerText(),/90.50 %/);
        assert.match(await page.locator('#monitorDashboard').innerText(),/83.20/);
        assert.match(await page.locator('#monitorDashboard').innerText(),/尚差 1.50/);
        assert.equal(await page.locator('.monitor-workflow [aria-current="step"]').count(),1);
        assert.equal(await page.locator('.monitor-sparkline line').count(),3,'different comparison baselines are not connected');
        assert.match(await page.locator('.monitor-timeline').innerText(),/本轮 5 项编辑事件.*12 个事件/);
        assert.equal(await page.locator('.monitor-finding').getAttribute('data-severity'),'blocking');
        await page.getByLabel(/自动重算/).check();
        await page.getByRole('button',{name:'保留编辑',exact:true}).click();
        assert.equal(await page.evaluate(()=>decisions.length),1);
        await page.getByRole('button',{name:'定位对象',exact:true}).click();
        assert.equal(await page.evaluate(()=>scene3D.scene.getObjectByName('monitor-focus').children.length),4);
        assert.match(await page.evaluate(()=>scene3D.scene.getObjectByName('monitor-focus').children.find(n=>n.isSprite).userData.label),/轴线 1.20 mm.*实体表面间隙 -0.40 mm/);
        assert(await page.evaluate(()=>scene3D.scene.getObjectByName('monitor-focus').children.find(n=>n.isSprite).scale.x < 10), 'label size adapts to a seed close-up');
        await page.evaluate(()=>{document.querySelector('.monitor-dashboard-body').scrollTop=0;});
        await page.screenshot({path:path.join(__dirname,'monitor-dashboard-spacing-qa.png')});
        await page.getByRole('button',{name:'seed_1',exact:true}).click();
        assert.equal(await page.evaluate(()=>scene3D.scene.getObjectByName('monitor-focus').children.length),1,'single-object focus does not draw the pair');
        await page.evaluate(()=>updateMonitorCheckpointCapture(packet,{success:true,attachments:[{target:'viewer-3d',url:'/synthetic.png'}]}));
        await page.getByRole('button',{name:'1 项图像证据未查看',exact:true}).click();
        assert.equal(await page.getByRole('button',{name:/项图像证据未查看/}).count(),0);
        assert.equal(await page.evaluate(()=>scene3D.meshes.seed_1.material.color.getHex()),0x20ccb0);
        await page.screenshot({path:path.join(__dirname,'monitor-dashboard-qa.png')});
        await page.getByRole('button',{name:'清除定位',exact:true}).click();
        assert.deepEqual(await page.evaluate(()=>scene3D.camera.position.toArray()),[0,0,35]);
        assert.equal(await page.evaluate(()=>!!scene3D.scene.getObjectByName('monitor-focus')),false);
        await page.evaluate(()=>resolveMonitorCheckpointDecision('abcdef123456',true));
        assert.match(await page.locator('#monitorDashboard').innerText(),/已保留这次编辑/);
        assert.equal(await page.getByRole('button',{name:'保留编辑',exact:true}).count(),0);
        await page.evaluate(()=>{
            packet.suggested_screenshot={checkpoint_id:'e1',object_ids:['seed_1']};
            updateMonitorCheckpointCapture(packet,{success:false,error:'monitor_targets_unavailable'});
        });
        assert.match(await page.locator('.monitor-capture-status').innerText(),/尚未就绪或不可见/);
        await page.locator('#monitorDashboard').getByRole('button',{name:'重试截图',exact:true}).click();
        assert.equal(await page.evaluate(()=>captureRequests.length),1,'HUD retry reaches the shared capture executor');
        await page.evaluate(()=>updateMonitorCheckpointCapture(packet,{success:true,
            attachments:[{target:'viewer-3d',url:'/partial.png'}],omittedTargetRefs:['seed_2']}));
        assert.match(await page.locator('.monitor-capture-status').innerText(),/部分图像.*未核验：seed_2/s);
        await page.evaluate(()=>{document.querySelector('.monitor-dashboard-body').scrollTop=80;renderMonitorDashboard([card],{});});
        assert.equal(await page.locator('.monitor-dashboard-body').evaluate(n=>n.scrollTop),80,'feedback updates preserve reading position');
        await page.evaluate(()=>{window._monitorEvidenceMatchesLiveGeometry=()=>false;renderMonitorDashboard([card],{});});
        assert.doesNotMatch(await page.locator('#monitorDashboard').innerText(),/90.50/,'live geometry mismatch fences equal-version facts');
        await page.evaluate(()=>{window._monitorEvidenceMatchesLiveGeometry=()=>true;renderMonitorDashboard([card],{});});
        await page.locator('.monitor-capture-status').evaluate(n=>n.scrollIntoView({block:'center'}));
        await page.screenshot({path:path.join(__dirname,'monitor-dashboard-ux-qa.png')});
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
