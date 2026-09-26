// Synthetic browser/Three.js evidence; never opens or mutates a patient case.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = process.argv[2] || path.resolve(__dirname, '../web/app/static/js');
function extract(file, name) {
    const source = fs.readFileSync(path.join(root,file),'utf8');
    const start = source.indexOf(`function ${name}(`);
    assert(start >= 0, name);
    const ends = ['\nfunction ', '\nasync function ', '\nwindow.'].map(s=>source.indexOf(s,start+12)).filter(i=>i>0);
    return source.slice(start,Math.min(...ends));
}
(async()=>{
    const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH ||
        (process.platform==='win32'?'C:/Program Files/Google/Chrome/Application/chrome.exe':undefined),
        args:['--enable-webgl','--enable-unsafe-swiftshader']});
    try {
        const page = await browser.newPage({viewport:{width:1000,height:850}});
        await page.setContent('<body style="background:#111827;color:#eee;font:15px Arial"><div id="cards"></div><div id="viewer"></div></body>');
        await page.addScriptTag({path:path.join(root,'three.min.js')});
        await page.addScriptTag({content:`
            window.trainingMonitorState={active:true,runId:'r'};
            window.manualPlanningState={planningVersion:2,planningId:'p'};
            window._activeApiSessionId=()=> 'c';
            window.monitorConversationLanguage=()=> 'zh';
            window.captureRequests=[]; window.commands=[];
            window.reportUIEvent=async (...args)=>captureRequests.push(args);
            window.performMonitorEditDecision=async (token,kept,owner)=>commands.push({token,kept,owner});
            window.addChat=(_type,content,_scroll,_at,_from,_session,meta)=>{
                let row=[...document.querySelectorAll('[data-message-id]')].find(n=>n.dataset.messageId===meta.messageId);
                if(!row){row=document.createElement('section');row.dataset.messageId=meta.messageId;
                    row.style='border:1px solid #475569;border-radius:12px;padding:16px;margin:12px';
                    row.innerHTML='<div class="chat-msg-wrapper"><div class="content" style="white-space:pre-wrap"></div></div>';
                    document.getElementById('cards').appendChild(row);}
                row.querySelector('.content').textContent=content;
            };
            window.packet={session_id:'c',monitor_run_id:'r',language:'zh',event:{type:'manual.seed.drag',event_id:'e1',detail:{edit_evidence:{
                geometry_event_id:'e1',event_id:'e1',after_version:2,planning_id:'p',restore_token:'abcdef123456'}}},
                interaction:{headline:'这次编辑新增 1 组间距问题。',dose_note:'剂量等待重算。',next_step:'先检查 seed_1 与 seed_2。',
                    objects:[{id:'seed_1',operation:'moved',distance_mm:20}],metric_rows:[],dose_current:false},
                suggested_screenshot:{checkpoint_id:'e1'}};
        `});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-interaction.js')});
        await page.evaluate(()=>receiveMonitorCheckpoint(packet));
        assert.equal(await page.locator('[data-message-id]').count(),1);
        await page.getByRole('button',{name:'保留这次编辑',exact:true}).click();
        assert.deepEqual(await page.evaluate(()=>commands),[{token:'abcdef123456',kept:true,
            owner:{sessionId:'c',runId:'r',language:'zh'}}]);
        await page.evaluate(()=>updateMonitorCheckpointCapture(packet,{success:false,error:'viewer_tab_hidden'}));
        await page.evaluate(()=>runMonitorCheckpointAction('e1','capture'));
        assert.equal(await page.evaluate(()=>captureRequests.length),2);
        await page.evaluate(()=>{trainingMonitorState.active=false;refreshMonitorCheckpointPresentation('inactive');});
        assert.equal(await page.locator('button:enabled').count(),0,'stop disables every edit action');
        assert.match(await page.locator('.content').innerText(),/监测已停止/);
        await page.addScriptTag({content:`
            window.scene3D={scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(45,1,0.1,1000),
                controls:{target:new THREE.Vector3()},meshes:{},requestRender(){}};
            const seed=new THREE.Mesh(new THREE.SphereGeometry(1),new THREE.MeshBasicMaterial({color:0x22ddaa}));
            seed.userData={id:'seed_1',type:'seed'};scene3D.scene.add(seed);scene3D.meshes.seed_1=seed;
            scene3D.camera.position.set(0,0,100);scene3D.camera.lookAt(0,0,0);scene3D.camera.updateMatrixWorld(true);
            window._screenshot3DIdentityFor=(id)=>[id];
            window._screenshot3DVisibility=()=>({locatable:true});
            window.sync3DCameraPose=pose=>{
                scene3D.camera.position.copy(pose.position);scene3D.camera.up.copy(pose.up);
                scene3D.controls.target.copy(pose.target);scene3D.camera.near=pose.near;scene3D.camera.far=pose.far;
                scene3D.camera.lookAt(pose.target);if(pose.quaternion)scene3D.camera.quaternion.copy(pose.quaternion);
                scene3D.camera.updateProjectionMatrix();scene3D.camera.updateMatrixWorld(true);
            };
        `});
        for(const name of ['_project3DObjectBounds','_unionNormalizedBounds','focusPlanningObjectsForScreenshot'])
            await page.addScriptTag({content:extract('brachybot-3d-manual.js',name)});
        const framed=await page.evaluate(()=>{
            const oldPosition=scene3D.camera.position.toArray(),oldRotation=scene3D.camera.quaternion.toArray();
            const mesh=scene3D.meshes.seed_1,oldColor=mesh.material.color.getHex();
            const restore=focusPlanningObjectsForScreenshot(['seed_1'],{editEvidence:{changed_objects:[
                {id:'seed_1',kind:'seeds',operation:'moved',before:[0,0,20],after:[0,0,0]}]}});
            const previous=new THREE.Vector3(0,0,20).project(scene3D.camera);
            const current=mesh.position.clone().project(scene3D.camera);
            const separation=Math.hypot(previous.x-current.x,previous.y-current.y);
            const bounds=restore.focusResult.normalized_bounds;
            restore();
            return {oldPosition,position:scene3D.camera.position.toArray(),oldRotation,rotation:scene3D.camera.quaternion.toArray(),
                oldColor,color:mesh.material.color.getHex(),previous:previous.toArray(),separation,bounds};
        });
        assert.deepEqual(framed.position,framed.oldPosition); assert.deepEqual(framed.rotation,framed.oldRotation);
        assert.equal(framed.color,framed.oldColor); assert(framed.separation>0.2,'view reveals movement initially aligned with camera');
        assert(Math.abs(framed.previous[0])<0.98&&Math.abs(framed.previous[1])<0.98,'return location remains in frame');
        const errors=[];page.on('pageerror',error=>errors.push(String(error)));
        await page.screenshot({path:path.join(__dirname,'monitor-coaching-qa.png')});
        assert.deepEqual(errors,[]);
        console.log('Browser: real card buttons, retry, stop fencing, 3D side-view framing, return-point inclusion and exact camera/color restoration passed.');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
