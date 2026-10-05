// Actual DOM and Three.js rendering with synthetic geometry, never patient data.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=process.argv[2]||path.resolve(__dirname,'../web/app/static/js');
(async()=>{
    const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH,
        args:['--enable-webgl','--enable-unsafe-swiftshader']});
    try{
        const page=await browser.newPage({viewport:{width:1100,height:800}}),errors=[];
        page.on('pageerror',error=>errors.push(String(error)));
        await page.setContent('<details id="monitorDashboard" open><summary></summary><div class="monitor-dashboard-body"></div></details><div id="chatMessages"></div><div id="viewer"></div>');
        await page.addScriptTag({path:path.join(root,'three.min.js')});
        await page.addScriptTag({content:`
            window.trainingMonitorState={active:true,phase:'active',runId:'r'};
            window.manualPlanningState={planningId:'p',planningVersion:1,monitorInteractionEpoch:0};
            window._activeApiSessionId=()=> 'c';window.monitorConversationLanguage=()=> 'zh';window.API='/api';
            window._monitorEvidenceMatchesLiveGeometry=()=>true;
            window.reportUIEvent=async()=>{};window.stopTrainingMode=async()=>({success:true});
            window.addChat=(_t,content,_scroll,_time,_restore,_sid,meta)=>{
                let row=document.querySelector('[data-message-id="'+meta.messageId+'"]');
                if(!row){row=document.createElement('section');row.dataset.messageId=meta.messageId;row.innerHTML='<div class="chat-msg-wrapper"><div class="chat-msg bot-response"></div></div>';chatMessages.append(row);}
                row.querySelector('.bot-response').textContent=content;
            };
            window.fetch=async()=>({ok:true,json:async()=>({success:true,active:true,monitor_run_id:'r',overview:{},events:[]})});
            window.scene3D={scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(45,1,.1,1000),meshes:{}};
            scene3D.controls=new THREE.EventDispatcher();scene3D.controls.target=new THREE.Vector3();
            scene3D.renderer=new THREE.WebGLRenderer();scene3D.renderer.setSize(400,400);viewer.append(scene3D.renderer.domElement);
            scene3D.camera.position.set(0,0,100);scene3D.camera.lookAt(0,0,0);scene3D.camera.updateMatrixWorld(true);
            scene3D.requestRender=()=>scene3D.renderer.render(scene3D.scene,scene3D.camera);
            const seed=new THREE.Mesh(new THREE.SphereGeometry(1),new THREE.MeshBasicMaterial({color:0x22ddaa}));
            seed.position.set(0,0,5);scene3D.meshes.b=seed;scene3D.scene.add(seed);
            window._screenshot3DIdentityFor=id=>[id];window._screenshot3DVisibility=()=>({locatable:true});
            window.focusPlanningObjectsForScreenshot=()=>{const old=scene3D.camera.position.clone();scene3D.camera.position.set(0,0,10);const restore=()=>scene3D.camera.position.copy(old);restore.focusResult={status:'resolved'};return restore;};
            window.packet={session_id:'c',monitor_run_id:'r',language:'zh',event:{type:'manual.seed.drag',event_id:'e',detail:{edit_evidence:{geometry_event_id:'e',event_id:'e',planning_id:'p',after_version:1,geometry_key:'g',restore_token:'abcdef123456',changed_objects:[{id:'b',kind:'seeds',operation:'moved',after:[0,0,5]}]}}},
                interaction:{headline:'编辑已保存',next_step:'核对剂量',dose_note:'待重算',decision_required:false,dose_current:false,spatial_refs:['b'],objects:[]},suggested_screenshot:null};
        `});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-interaction.js')});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-dashboard.js')});
        const result=await page.evaluate(async()=>{
            const old=scene3D.camera.position.toArray(),color=scene3D.meshes.b.material.color.getHex();
            await receiveMonitorCheckpoint(packet);
            const automatic=scene3D.camera.position.toArray();
            const ok=previewMonitorGeometry({seeds:[{id:'b',position:[0,0,15]}],needles:[]},packet.event.detail.edit_evidence);
            const preview=scene3D.camera.position.toArray(),seed=scene3D.meshes.b.position.toArray();
            const annotations=[];scene3D.scene.traverse(node=>{if(node.userData.readOnlyPreview)annotations.push(node.type);});
            focusMonitorCheckpoint(['b'],packet.event.detail.edit_evidence);
            scene3D.controls.dispatchEvent({type:'start'});scene3D.camera.position.set(12,14,50);
            scene3D.controls.dispatchEvent({type:'end'});clearMonitorFocus(true);
            return {old,automatic,ok,preview,seed,color,afterColor:scene3D.meshes.b.material.color.getHex(),annotations,userCamera:scene3D.camera.position.toArray()};
        });
        assert.deepEqual(result.automatic,result.old);assert.deepEqual(result.preview,result.old);
        assert(result.ok);assert.deepEqual(result.seed,[0,0,5]);assert.equal(result.afterColor,result.color);
        assert(result.annotations.includes('ArrowHelper'));assert.deepEqual(result.userCamera,[12,14,50]);
        assert.equal(await page.locator('.monitor-feedback-details').count(),1,'full record is retained behind a readable summary');
        assert.equal(await page.getByRole('button',{name:'保留编辑',exact:true}).isVisible(),false,'normal saves do not demand a keep confirmation');
        await page.locator('#monitorDashboard .monitor-secondary-actions summary').click();
        assert.equal(await page.getByRole('button',{name:'保留编辑',exact:true}).isVisible(),true,'optional restore/keep remains available');
        await page.screenshot({path:path.join(__dirname,'monitor-preview-qa.png')});
        assert.deepEqual(errors,[]);
        console.log('Browser: automatic focus/preview preserves camera, mesh position and color; ghost arrows, user-camera ownership, compact records and secondary normal-edit decisions passed.');
    }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
