// Journey acceptance in real DOM and WebGL. Synthetic geometry only; no
// authenticated product API, patient data, model inference or implicit edits.
const {chromium}=require('playwright');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=process.argv[2] || path.resolve(__dirname,'../web/app/static/js');
(async()=>{
    const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH,
        args:['--enable-webgl','--enable-unsafe-swiftshader']});
    try{
        const page=await browser.newPage({viewport:{width:1240,height:960}}),errors=[];
        page.on('pageerror',error=>errors.push(String(error)));
        await page.setContent(`<style>body{margin:0;background:#0c1320;color:#e4edf9;font:14px/1.5 Arial}
            main{display:grid;grid-template-columns:440px 1fr;gap:16px;padding:16px}button{background:#19243a;border:1px solid #465674;color:inherit;cursor:pointer}
            #viewer{height:540px}#viewer3d{min-width:0}#chatMessages{margin:12px;padding:12px;border:1px solid #354257;border-radius:12px}
            @media(max-width:600px){main{display:block;padding:6px}#viewer{height:350px}}</style>
            <main><div><details id="monitorDashboard" open><summary></summary><div class="monitor-dashboard-body"></div></details><div id="chatMessages"></div></div><div id="viewer3d"><div class="viewer-card-body"><div id="viewer"></div></div><div class="viewer-card-ctrl"></div></div></main>`);
        await page.addStyleTag({path:path.resolve(root,'../css/brachybot-monitor-dashboard.css')});
        await page.addScriptTag({path:path.join(root,'three.min.js')});
        await page.addScriptTag({content:`
            window.API='/api';window._i18nLang='zh';window.language='zh';window.session='case';
            window.trainingMonitorState={active:true,phase:'active',runId:'run'};
            window.manualPlanningState={planningId:'plan',planningVersion:2,monitorInteractionEpoch:0};
            window._activeApiSessionId=()=>session;
            window._monitorEvidenceMatchesLiveGeometry=()=>true;
            window.commands=[];window.reportUIEvent=async()=>{};window.stopTrainingMode=async()=>({success:true});
            window.setMonitorPresentation=()=>{};
            window.recomputeManualDose=async()=>{commands.push('dose');return {success:true};};
            window.performMonitorEditDecision=async()=>{commands.push('restore');return {success:true};};
            window.requestPlanningAdvice=async()=>{};
            window.fetch=async()=>({ok:true,json:async()=>({success:true,active:true,monitor_run_id:'run',overview:{},events:[]})});
            window.addChat=(_type,content,_scroll,_at,_restore,_sid,meta)=>{
                let row=document.querySelector('[data-message-id="'+meta.messageId+'"]');
                if(!row){row=document.createElement('section');row.dataset.messageId=meta.messageId;row.innerHTML='<div class="chat-msg-wrapper"><div class="chat-msg bot-response"></div></div>';chatMessages.append(row);}
                row.querySelector('.bot-response').textContent=content;
            };
            window.scene3D={scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(45,1,.1,1000),meshes:{}};
            scene3D.controls=new THREE.EventDispatcher();scene3D.controls.target=new THREE.Vector3();
            scene3D.renderer=new THREE.WebGLRenderer({preserveDrawingBuffer:true});scene3D.renderer.setSize(730,540);viewer.append(scene3D.renderer.domElement);
            scene3D.camera.aspect=730/540;scene3D.camera.position.set(60,60,120);scene3D.camera.lookAt(0,0,15);scene3D.camera.updateProjectionMatrix();scene3D.camera.updateMatrixWorld(true);
            scene3D.requestRender=()=>scene3D.renderer.render(scene3D.scene,scene3D.camera);
            for(let i=0;i<40;i++){const mesh=new THREE.Mesh(new THREE.CylinderGeometry(.35,.35,30,8),new THREE.MeshBasicMaterial({color:0x667d9b}));
                mesh.rotation.x=Math.PI/2;mesh.position.set((i%8-4)*5,Math.floor(i/8)*5-10,15);scene3D.scene.add(mesh);scene3D.meshes['needle_'+i]=mesh;}
            const edited=scene3D.meshes.needle_23;edited.position.set(0,7.5,15);
            for(const [i,id] of ['seed_1_4','seed_1_5'].entries()){const mesh=new THREE.Mesh(new THREE.SphereGeometry(.8,16,12),new THREE.MeshBasicMaterial({color:0x40cbb9}));
                mesh.position.set(i*1.2,6,16);scene3D.meshes[id]=mesh;scene3D.scene.add(mesh);}
            window._screenshot3DIdentityFor=id=>[id];window._screenshot3DVisibility=(_id,mesh)=>({locatable:mesh.visible});
            window.focusPlanningObjectsForScreenshot=refs=>{const old=scene3D.camera.position.clone(),oldTarget=scene3D.controls.target.clone();
                const center=refs.includes('needle_23')?new THREE.Vector3(0,7.5,15):new THREE.Vector3(.6,6,16);
                scene3D.camera.position.copy(center).add(new THREE.Vector3(0,0,refs.includes('needle_23')?60:12));
                scene3D.controls.target.copy(center);scene3D.camera.lookAt(center);scene3D.camera.updateMatrixWorld(true);
                const restore=()=>{scene3D.camera.position.copy(old);scene3D.controls.target.copy(oldTarget);scene3D.camera.lookAt(oldTarget);scene3D.camera.updateMatrixWorld(true);};restore.focusResult={status:'resolved'};return restore;};
            window.guide={schema_version:1,focus_refs:['seed_1_4','seed_1_5'],localized:{
                zh:{state:'geometry_review',title:'先处理这对粒子的间距：seed_1_4 ↔ seed_1_5。',observation:'needle_23 最大端点位移 15.00 mm',
                    meaning:'实体表面间隙 -0.40 mm；配置要求至少 0.50 mm。这次编辑后该对间距新增违规；先解决几何，再判断剂量取舍。',
                    recommendation:'先查看这对对象的标注，确认是否是你想保留的调整。若是误拖，先预览编辑前位置，再决定是否恢复。',
                    verification:'保存修正后，确认这对对象的间距问题是否消除，再重算剂量核对覆盖、热点及器官受量。',
                    limitation:'间隙不足量不是建议拖动量；原位置并非已验证的安全位置。',findings:[],
                    steps:[{action:'focus',label:'查看这对对象的间距',refs:['seed_1_4','seed_1_5']},{action:'preview',label:'先预览原位置（不修改）'}]},
                en:{state:'geometry_review',title:'Check seed_1_4 and seed_1_5 spacing first.',observation:'needle_23 maximum endpoint displacement 15.00 mm',
                    meaning:'Finite surface gap -0.40 mm; configured minimum 0.50 mm. Address geometry before dose trade-offs.',recommendation:'Locate the pair first. Preview the prior position if the move was unintended.',
                    verification:'After correcting geometry, recompute dose.',limitation:'The prior position is not verified safe.',findings:[],steps:[{action:'focus',label:'Locate this spacing issue',refs:['seed_1_4','seed_1_5']}]}}};
            window.packet={session_id:'case',monitor_run_id:'run',language:'zh',event:{type:'manual.needle.drag',event_id:'e2',detail:{edit_evidence:{
                geometry_event_id:'edit2',event_id:'e2',planning_id:'plan',after_version:2,geometry_key:'g2',restore_token:'abcdef123456',
                changed_objects:[{id:'needle_23',kind:'needles',operation:'moved',before:[[0,0,0],[0,0,30]],after:[[0,0,0],[0,15,30]],distance_mm:15},
                    {id:'seed_1_4',kind:'seeds',operation:'moved',dependent_on_needle:true,after:[0,6,16],before:[0,4,16]}],
                conflicts:[{first_id:'seed_1_4',second_id:'seed_1_5',kind:'seed_pairs',change:'new',physical_overlap:true,measurement:{
                    coordinate_system:'patient_world_mm',clearance_basis:'finite_parallel_cylinders',points:[[0,6,16],[1.2,6,16]],value_mm:1.2,surface_clearance_mm:-.4}}]}}},
                interaction:{schema_version:3,language:'zh',guidance:guide,primary_action:'focus',severity:'blocking',headline:'新增 1 组间距问题',
                    dose_note:'剂量待重算',dose_current:false,decision_required:true,objects:[],spatial_refs:['needle_23','seed_1_4','seed_1_5'],
                    conflicts:[{first_id:'seed_1_4',second_id:'seed_1_5',kind:'seed_pairs',change:'new',physical_overlap:true}],related_object_counts:{dependent:1}},suggested_screenshot:null};
        `});
        const api=fs.readFileSync(path.join(root,'brachybot-ui-api.js'),'utf8');
        const langStart=api.indexOf('function monitorConversationLanguage('),langEnd=api.indexOf('\nfunction monitorChatText(',langStart);
        await page.addScriptTag({content:api.slice(langStart,langEnd)});
        // The actual global setter/event emitter, not a Monitor-local toggle.
        const core=fs.readFileSync(path.join(root,'brachybot-chat-core.js'),'utf8');
        const setStart=core.indexOf('    function applyI18n()'),setEnd=core.indexOf('\n})();',setStart);
        await page.addScriptTag({content:core.slice(setStart,setEnd)});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-interaction.js')});
        await page.addScriptTag({path:path.join(root,'brachybot-monitor-dashboard.js')});
        const original=await page.evaluate(()=>({camera:scene3D.camera.position.toArray(),colors:Object.values(scene3D.meshes).map(mesh=>mesh.material.color.getHex())}));
        await page.evaluate(async()=>window.card=await receiveMonitorCheckpoint(packet));
        const anchor=await page.evaluate(()=>scene3D.scene.getObjectByName('monitor-focus').children.filter(node=>node.isSprite && node.userData.objectRef).map(node=>node.userData));
        assert.deepEqual(anchor.map(item=>item.objectRef),['needle_23','seed_1_4','seed_1_5'],'one edited needle plus its actual pair, not forty tree IDs');
        assert.deepEqual(anchor.map(item=>item.letter),['A','B','C']);
        assert.deepEqual(anchor[0].locationAnchor,[0,15,30],'edited needle badge anchors to the moved endpoint');
        assert.match(anchor[0].label,/刚编辑的针道/);assert.doesNotMatch(anchor[1].label,/刚编辑/,'dependent seeds are not described as user drags');
        const labelCenters=await page.evaluate(()=>scene3D.scene.getObjectByName('monitor-focus').children.filter(node=>node.isSprite && node.userData.objectRef)
            .map(node=>{const p=node.position.clone().project(scene3D.camera);return {x:(p.x+1)*730/2,y:(1-p.y)*540/2};}));
        for(let i=0;i<labelCenters.length;i++)for(let j=i+1;j<labelCenters.length;j++)
            assert(Math.abs(labelCenters[i].y-labelCenters[j].y)>=35 || Math.abs(labelCenters[i].x-labelCenters[j].x)>=286,'letter labels do not obscure one another');
        assert.equal(await page.evaluate(()=>scene3D.scene.getObjectByName('monitor-focus').children.filter(node=>node.userData.purpose==='recorded_move_not_recommendation').length),1);
        assert.deepEqual(await page.evaluate(()=>scene3D.camera.position.toArray()),original.camera,'automatic marks never move the camera');
        assert.deepEqual(await page.evaluate(()=>Object.values(scene3D.meshes).map(mesh=>mesh.material.color.getHex())),original.colors);
        const locale=await page.evaluate(()=>{
            addMonitorLocalizedChat('bot-response',{zh:'本轮记录了 2 次编辑。',en:'This run recorded 2 edits.'},false,1,false,'case',
                {messageId:'localized-summary',messageKind:'monitor_summary'});
            previewMonitorGeometry({needles:[{id:'needle_23',points:[[0,0,0],[0,0,30]]}],seeds:[]},packet.event.detail.edit_evidence);
            const layer=scene3D.scene.getObjectByName('monitor-focus'),camera=scene3D.camera.position.toArray();
            setUiLanguage('en');
            const translated=layer.children.filter(node=>node.isSprite).map(node=>node.userData.label);
            const unchanged=layer===scene3D.scene.getObjectByName('monitor-focus') && JSON.stringify(camera)===JSON.stringify(scene3D.camera.position.toArray());
            const preview=layer.children.some(node=>node.userData.purpose==='preview_destination_not_optimized');
            const summary=document.querySelector('[data-message-id="localized-summary"] .bot-response').textContent;
            setUiLanguage('zh');clearMonitorFocus();
            focusMonitorCheckpoint(['needle_23','seed_1_4','seed_1_5'],packet.event.detail.edit_evidence,{reframe:false});
            refreshMonitorSpatialPresentation();return {translated,unchanged,preview,summary};
        });
        assert(locale.unchanged && locale.preview,'locale repaint preserves preview, layer and camera ownership');
        assert(locale.translated.some(label=>/Edited needle/.test(label)));assert(locale.translated.every(label=>!/[\u4e00-\u9fff]/.test(label)));
        assert.equal(locale.summary,'This run recorded 2 edits.','the same summary row follows the global setter');
        assert.equal(await page.locator('[data-message-id="localized-summary"]').count(),1,'locale projection does not add duplicate history');
        assert.equal(await page.evaluate(()=>{
            const restore=suspendMonitorSpatialAnnotations();const hidden=!scene3D.scene.getObjectByName('monitor-focus').visible;
            restore();return hidden && scene3D.scene.getObjectByName('monitor-focus').visible;
        }),true,'screen-capture transactions hide and restore helpers, never clinical meshes');
        const visible=await page.locator('#monitorDashboard .monitor-guidance').innerText();
        assert.doesNotMatch(visible,/needle_23|seed_1_[45]/,'IDs stay out of first-view prose');assert.match(visible,/A 最大端点位移 15.00 mm/);
        assert.match(visible,/Viewer 已标出 A \/ B \/ C/);assert.match(visible,/不是建议下一步拖动方向/);
        assert.equal(await page.locator('#monitorDashboard .monitor-primary-action:visible').count(),1);
        assert.equal(await page.locator('#monitorDashboard .monitor-plan-details').getAttribute('open'),null);
        const currentDose=await page.evaluate(()=>commands.length);assert.equal(currentDose,0);
        assert.equal(await page.locator('.monitor-receipt-guidance').getAttribute('open'),null,'chat defaults to a quiet receipt');
        assert.equal(await page.locator('.chat-msg.bot-response .monitor-primary-action:visible').count(),0,'chat does not duplicate the workspace toolbar');
        assert.equal(await page.locator('#viewer3d .monitor-primary-action:visible').count(),1,'the current action is beside the actual image');
        assert.equal(await page.locator('#viewer .monitor-viewer-guide').count(),0,'guidance is outside the captured canvas');
        assert.match(await page.locator('.monitor-viewer-copy').innerText(),/B ↔ C/);
        assert.doesNotMatch(await page.locator('.monitor-viewer-guide').innerText(),/needle_23|seed_1_[45]/);
        const railBounds=await page.locator('.monitor-viewer-guide').boundingBox(),canvasBounds=await page.locator('#viewer canvas').boundingBox();
        assert(railBounds.y>=canvasBounds.y+canvasBounds.height-1,'the guide does not cover diagnostic pixels');
        await page.evaluate(()=>document.getElementById('monitorDashboard').open=false);
        await page.locator('.monitor-open-coach').click();
        assert.equal(await page.locator('#monitorDashboard').getAttribute('open'),'','the receipt reopens the current coach');
        await page.screenshot({path:path.join(__dirname,'monitor-experience-desktop.png')});
        const primary=page.locator('#monitorDashboard .monitor-primary-action'),bounds=await primary.boundingBox(),bodyBounds=await page.locator('.monitor-dashboard-body').boundingBox();
        assert(bounds.y+bounds.height<=bodyBounds.y+bodyBounds.height,'the first action is above the panel fold');
        // Identical polling must not even replace the user's focused DOM node.
        await primary.focus();await page.evaluate(()=>window.focused=document.activeElement);
        await page.evaluate(()=>renderMonitorDashboard([card],{}));
        assert.equal(await page.evaluate(()=>document.activeElement===focused),true,'unchanged updates preserve node identity');
        await page.evaluate(()=>updateMonitorCheckpointCapture(packet,{success:true,attachments:[{target:'viewer-3d',url:'/synthetic.png'}]}));
        assert.equal(await page.evaluate(()=>document.activeElement.dataset.guideAction),'focus','late images preserve keyboard action focus');
        await page.locator('#monitorDashboard .monitor-guide-followup > summary').click();
        await page.evaluate(()=>{card.notice='新的状态';renderMonitorDashboard([card],{});});
        assert.equal(await page.locator('#monitorDashboard .monitor-guide-followup').getAttribute('open'),'','expanded verification survives asynchronous updates');
        await page.locator('#monitorDashboard .monitor-guide-followup > summary').click();
        await primary.click();
        assert.deepEqual(await page.evaluate(()=>getMonitorSpatialState(packet.event.detail.edit_evidence).refs),['seed_1_4','seed_1_5']);
        assert.match(await page.locator('#monitorDashboard .monitor-location-status').innerText(),/B \/ C/);
        assert.equal(await page.evaluate(()=>commands.length),0,'locating never recomputes or restores');
        assert.equal(await page.locator('#monitorDashboard .monitor-return-view').isVisible(),true,'explicit focus has an obvious reversible camera action');
        await page.locator('#monitorDashboard .monitor-return-view').click();
        assert.deepEqual(await page.evaluate(()=>scene3D.camera.position.toArray()),original.camera,'return restores only the owned camera pose');
        assert.equal(await page.evaluate(()=>commands.length),0);
        // Preview is an interaction state, not merely a paragraph appended to
        // old advice. The primary action changes; closing never mutates.
        await page.evaluate(()=>{
            const geometry={needles:[{id:'needle_23',points:[[0,0,0],[0,0,30]]}],seeds:[]};
            previewMonitorGeometry(geometry,card.evidence);card.previewGeometry=geometry;renderMonitorDashboard([card],{});
        });
        assert.equal(await primary.getAttribute('data-guide-action'),'restore');
        assert.match(await page.locator('.monitor-viewer-copy').innerText(),/尚未修改/);
        assert.match(await page.locator('#viewer3d .monitor-primary-action').innerText(),/确认恢复/);
        assert.equal(await page.evaluate(()=>commands.length),0,'merely viewing a preview does not restore it');
        await page.locator('#monitorDashboard .monitor-guide-actions').getByRole('button',{name:'关闭预览，不修改',exact:true}).click();
        assert.equal(await primary.getAttribute('data-guide-action'),'focus');
        assert.equal(await page.evaluate(()=>commands.length),0,'dismissal never calls a mutation');
        const needlePreview=await page.evaluate(()=>{
            previewMonitorGeometry({needles:[{id:'needle_23',points:[[0,0,0],[0,0,30]]}],seeds:[]},packet.event.detail.edit_evidence);
            const arrows=scene3D.scene.getObjectByName('monitor-focus').children.filter(node=>node.userData.purpose==='preview_destination_not_optimized');
            const result=arrows.map(node=>({endpoint:node.userData.endpoint,ref:node.userData.objectRef}));clearMonitorFocus(true);return result;
        });
        assert.deepEqual(needlePreview,[{endpoint:2,ref:'needle_23'}],'a second-endpoint edit has a second-endpoint undo reference, not an unchanged first endpoint');
        // Camera gesture owns its view; return/clear must not jump it backward.
        await page.evaluate(()=>{scene3D.controls.dispatchEvent({type:'start'});scene3D.camera.position.set(12,14,70);scene3D.controls.dispatchEvent({type:'end'});clearMonitorFocus(true);refreshMonitorSpatialPresentation();});
        assert.deepEqual(await page.evaluate(()=>scene3D.camera.position.toArray()),[12,14,70]);
        assert.doesNotMatch(await page.locator('#monitorDashboard .monitor-location-status').innerText(),/Viewer 已标出/);
        await page.evaluate(()=>{scene3D.meshes.seed_1_5.visible=false;return runMonitorCheckpointAction('edit2','focus');});
        assert.doesNotMatch(await page.locator('#monitorDashboard .monitor-location-status').innerText(),/Viewer 已标出/,'hidden targets are never reported as located');
        await page.evaluate(()=>{scene3D.meshes.seed_1_5.visible=true;});
        // A real DOM/Three.js recovery journey uses production availability,
        // exact-row resolution and tree expansion; no fuzzy name navigation.
        const volume=fs.readFileSync(path.join(root,'brachybot-viewer-volume.js'),'utf8');
        const extractFunction=(source,name)=>{const start=source.indexOf(`function ${name}(`),end=source.indexOf('\nfunction ',start+10);
            assert(start>=0 && end>start,name);return source.slice(start,end);};
        const rowsStart=api.indexOf('function _dataTreeRowSemanticIdentity('),rowsEnd=api.indexOf('\nfunction _dataTreeRowIdentities(',rowsStart);
        await page.addScriptTag({content:api.slice(rowsStart,rowsEnd)});
        await page.addScriptTag({content:['_treeExpansionState','_applyTreeGroupExpansion','setTreeGroupExpansion']
            .map(name=>extractFunction(volume,name)).join('\n')});
        await page.evaluate(()=>{
            window.oldVisibility=_screenshot3DVisibility;window.displayCommands=[];window.saves=[];
            window.dataTreeState={planning:{id:'planning',visible:true,visible3D:true},expansionState:{}};
            window.liveNodes={};for(const id of ['needle_23','seed_1_4','seed_1_5'])liveNodes[id]={id,parentId:'planning',
                sessionId:'case',planningId:'plan',status:'ready',visible:true,visible3D:true};
            window._findDataTreeNode=id=>liveNodes[id] || null;
            window._dataTreeParentNode=node=>node?.parentId==='planning'?dataTreeState.planning:null;
            window._scheduleDataTreeSave=reason=>saves.push(reason);
            window.setTreeGroupExpansion=setTreeGroupExpansion;
            window._screenshot3DVisibility=(id,mesh)=>({node:liveNodes[id],locatable:mesh.visible
                && liveNodes[id]?.visible!==false && liveNodes[id]?.visible3D!==false && dataTreeState.planning.visible});
            window.executeUIContextAction=async payload=>{displayCommands.push(payload);
                const node=liveNodes[payload.object_id];if(!node)return {success:false};
                if(payload.action_id==='node_show')node.visible=true;
                if(payload.action_id==='node_show_3d')node.visible3D=true;
                scene3D.meshes[node.id].visible=node.visible && node.visible3D;return {success:true};};
            const tree=document.createElement('section');tree.id='dataTreeBody';tree.innerHTML=`
                <div class="tree-group" data-group="planning"><div class="tree-group-header"><span class="arrow collapsed"></span></div>
                <div class="tree-group-items collapsed"><div class="tree-group" data-group="planning_seeds">
                <div class="tree-group-header"><span class="arrow collapsed"></span></div><div class="tree-group-items collapsed">
                <div class="tree-item planning-history-artifact" data-node-id="seed_1_5" data-live-node="false">Historical seed</div>
                <div class="tree-item" data-node-id="seed_1_50" data-object-id="seed_1_50" data-live-node="true">Similar name</div>
                <div class="tree-item" data-node-id="seed_1_5" data-object-id="seed_1_5" data-live-node="true">Current seed</div>
                </div></div></div></div>`;document.body.appendChild(tree);
            liveNodes.seed_1_5.visible=false;scene3D.meshes.seed_1_5.visible=false;clearMonitorFocus();refreshMonitorSpatialPresentation();
        });
        assert.match(await page.locator('#monitorDashboard .monitor-location-legend').innerText(),/C.*已隐藏/);
        assert.equal(await page.locator('#monitorDashboard .monitor-location-recovery button').count(),2,'one hidden object has precise recovery controls');
        await page.locator('#monitorDashboard .monitor-location-recovery button').getByText('在数据树定位 C',{exact:true}).click();
        assert.equal(await page.locator('#dataTreeBody .monitor-tree-target').innerText(),'Current seed','no history or same-prefix target wins');
        assert.equal(await page.locator('#dataTreeBody .tree-group-items.collapsed').count(),0,'only the exact row ancestors expand');
        assert.equal(await page.evaluate(()=>document.activeElement.dataset.nodeId),'seed_1_5');
        assert.equal(await page.evaluate(()=>displayCommands.length),0,'tree navigation changes no scene visibility');
        await page.locator('#monitorDashboard .monitor-location-recovery button').getByText('显示 C 并定位',{exact:true}).click();
        assert.equal(await page.evaluate(()=>liveNodes.seed_1_5.visible),true);
        assert.deepEqual(await page.evaluate(()=>displayCommands.map(item=>item.action_id)),['node_show','node_show_3d']);
        assert.deepEqual(await page.evaluate(()=>Object.values(scene3D.meshes).map(mesh=>mesh.material.color.getHex())),original.colors);
        assert.match(await page.locator('#monitorDashboard .monitor-location-status').innerText(),/Viewer 已标出 C/);
        await page.evaluate(()=>{dataTreeState.planning.visible=false;refreshMonitorSpatialPresentation();});
        assert.equal(await page.evaluate(()=>scene3D.scene.getObjectByName('monitor-focus') || null),null,'hiding an annotated group removes its live helpers');
        assert.doesNotMatch(await page.locator('.monitor-guidance-live-status').allTextContents().then(items=>items.join(' ')),/Object shown and located|已显示并定位/,'a display success notice cannot survive subsequent hiding');
        assert.equal(await page.locator('#monitorDashboard .monitor-location-recovery button').getByText(/显示/).count(),0,'hidden parent groups are never silently revealed');
        await page.evaluate(()=>{dataTreeState.planning.visible=true;liveNodes.seed_1_5.visible=false;refreshMonitorSpatialPresentation();});
        await page.evaluate(()=>setUiLanguage('en'));
        assert.doesNotMatch(await page.locator('#monitorDashboard .monitor-location-recovery').innerText(),/[\u4e00-\u9fff]/);
        await page.screenshot({path:path.join(__dirname,'monitor-recovery-desktop.png')});
        await page.evaluate(()=>{setUiLanguage('zh');liveNodes.seed_1_5.visible=true;_screenshot3DVisibility=oldVisibility;clearMonitorFocus();
            delete window._findDataTreeNode;delete window._dataTreeParentNode;dataTreeBody.remove();refreshMonitorSpatialPresentation();});
        // On-screen claims require a visible patient-space anchor, not merely
        // a loaded mesh that happens to be outside the camera's view.
        const offscreen=await page.evaluate(()=>{
            focusMonitorCheckpoint(['seed_1_4','seed_1_5'],packet.event.detail.edit_evidence,{reframe:false});
            const camera=scene3D.camera.position.clone(),rotation=scene3D.camera.quaternion.clone();
            scene3D.camera.lookAt(1000,1000,1000);scene3D.camera.updateMatrixWorld(true);
            const state=getMonitorSpatialState(packet.event.detail.edit_evidence);
            scene3D.camera.position.copy(camera);scene3D.camera.quaternion.copy(rotation);scene3D.camera.updateMatrixWorld(true);return state;
        });
        assert.equal(offscreen.status,'offscreen');assert.deepEqual(offscreen.refs,[]);
        // New versions invalidate buttons before any real mutation can occur.
        await page.evaluate(()=>{manualPlanningState.planningVersion=3;refreshMonitorSpatialPresentation();});
        assert.equal(await page.locator('.monitor-viewer-guide').isVisible(),false,'stale guidance is removed beside the image');
        assert.equal(await page.locator('#monitorDashboard .monitor-primary-action:enabled').count(),0,'version drift removes executable current guidance');
        assert.equal(await page.evaluate(()=>runMonitorCheckpointAction('edit2','restore')),false);
        await page.evaluate(()=>{manualPlanningState.planningVersion=2;refreshMonitorSpatialPresentation();});
        await page.evaluate(()=>{manualPlanningState.monitorInteractionActive=true;refreshMonitorSpatialPresentation();});
        assert.equal(await page.locator('.monitor-viewer-guide').isVisible(),false,'committed guidance does not chase a drag preview');
        await page.evaluate(()=>{manualPlanningState.monitorInteractionActive=false;refreshMonitorSpatialPresentation();});
        // Narrow/touch layouts, reduced motion and English use the same facts.
        await page.setViewportSize({width:390,height:900});
        await page.emulateMedia({reducedMotion:'reduce'});
        await page.screenshot({path:path.join(__dirname,'monitor-experience-mobile.png')});
        assert(await page.evaluate(()=>document.querySelector('#monitorDashboard').scrollWidth<=document.querySelector('#monitorDashboard').clientWidth+1),'panel has no horizontal overflow');
        const mobile=await primary.boundingBox(),mobileBody=await page.locator('.monitor-dashboard-body').boundingBox();
        assert(mobile.y+mobile.height<=mobileBody.y+mobileBody.height,'narrow first action stays above the fold');
        await page.evaluate(()=>{setUiLanguage('en');});
        assert.doesNotMatch(await page.locator('.monitor-viewer-guide').innerText(),/[\u4e00-\u9fff]/,'the Viewer rail follows the real global locale');
        const englishAction=await primary.boundingBox(),englishBody=await page.locator('.monitor-dashboard-body').boundingBox();
        assert(englishAction.y+englishAction.height<=englishBody.y+englishBody.height,'longer English also keeps its primary action above the fold');
        assert(await page.evaluate(()=>document.querySelector('#monitorDashboard').scrollWidth<=document.querySelector('#monitorDashboard').clientWidth+1),'English labels fit the narrow layout');
        await page.screenshot({path:path.join(__dirname,'monitor-experience-mobile-en.png')});
        await page.evaluate(()=>{setUiLanguage('zh');});
        assert.equal(await page.evaluate(()=>commands.length),0,'the complete journey runs no dose or mutation without a choice');
        await page.evaluate(()=>{performMonitorEditDecision=async()=>({success:false});return runMonitorCheckpointAction('edit2','keep');});
        assert.match(await page.locator('.monitor-guidance-live-status').innerText(),/尚未确认/,'an unconfirmed choice cannot silently look successful');
        await page.evaluate(async()=>{
            packet.event.event_id='dose3';packet.event.detail.edit_evidence.event_id='dose3';
            packet.interaction.dose_current=true;packet.interaction.primary_action='details';
            packet.interaction.dose_comparable=true;packet.interaction.assessment={edit_count:2};
            packet.interaction.guidance.localized.zh.steps=[{action:'details',label:'展开指标与器官取舍'}];
            packet.interaction.guidance.localized.en.steps=[{action:'details',label:'Expand metrics and organ-dose trade-offs'}];
            packet.interaction.metric_rows=[{key:'v100',metric:'V100',before:90,after:89,delta:-1,unit:'pp'},
                {key:'d90',metric:'D90',before:120,after:121,delta:1,unit:'Gy'},
                {key:'v200',metric:'V200',before:27,after:30,delta:3,unit:'pp'},
                {key:'oar:cord:d2cc',metric:'cord D2cc',before:8,after:9,delta:1,unit:'Gy'},
                {key:'dmax',metric:'Dmax',before:10,after:NaN,delta:NaN,unit:'Gy'}];
            await receiveMonitorCheckpoint(packet);
        });
        assert.match(await page.locator('.chat-msg.bot-response .monitor-guidance-live-status').innerText(),/较早检查点/,'old attachments cannot silently acquire the new feedback revision');
        assert.match(await page.locator('#monitorDashboard .monitor-guide-ledger').innerText(),/2 次编辑的合计影响/,'sequence attribution is visible, not buried in a disclosure');
        assert.equal(await page.locator('#monitorDashboard .monitor-key-changes tbody tr').count(),4);
        assert.match(await page.locator('#monitorDashboard .monitor-key-changes').innerText(),/V100.*90.00 → 89.00.*-1.00 pp/s);
        assert.doesNotMatch(await page.locator('#monitorDashboard .monitor-key-changes').innerText(),/NaN|Dmax/);
        assert.equal(await page.locator('.chat-msg.bot-response .monitor-key-changes:visible').count(),0,'history does not duplicate the current comparison');
        await page.locator('#monitorDashboard .monitor-primary-action').click();
        assert.equal(await page.locator('#monitorDashboard .monitor-object-record').getAttribute('open'),'','review action actually reveals the requested record');
        assert.match(await page.locator('#monitorDashboard .monitor-object-record').innerText(),/V100: 90.00.*89.00/);
        await page.evaluate(()=>{setUiLanguage('en');});
        assert.doesNotMatch(await page.locator('#monitorDashboard .monitor-guidance').innerText(),/刚编辑|如何确认|建议先做/);
        await page.evaluate(()=>{
            // The operator explicitly closes the just-reviewed record before
            // the initial English-layout capture; locale changes never do so.
            document.querySelectorAll('#monitorDashboard .monitor-object-record,#monitorDashboard .monitor-guide-followup').forEach(node=>node.open=false);
            document.querySelector('.monitor-dashboard-body').scrollTop=0;
        });
        assert(await page.evaluate(()=>document.querySelector('#monitorDashboard').scrollWidth<=document.querySelector('#monitorDashboard').clientWidth+1),'English labels also fit the narrow layout');
        await page.evaluate(()=>{trainingMonitorState.phase='stop_error';trainingMonitorState.active=false;refreshMonitorCheckpointPresentation('stop_error');});
        assert.equal(await page.getByRole('button',{name:'Retry Finish Monitor',exact:true}).isEnabled(),true);
        assert.equal(await page.locator('#monitorDashboard .monitor-primary-action:enabled').count(),0);
        assert.equal(await page.locator('.monitor-viewer-guide').isVisible(),false,'stop recovery does not leave an executable Viewer coach');
        // Inspect the same interaction with the product's actual tokens and
        // component CSS, not just the convenient isolated dark test shell.
        for(const name of ['brachybot-theme-layout.css','brachybot-chat-status.css','brachybot-report-controls.css',
            'brachybot-responsive.css','brachybot-theme-light.css','brachybot-monitor-dashboard.css'])
            await page.addStyleTag({path:path.resolve(root,'../css',name)});
        await page.setViewportSize({width:1240,height:960});
        await page.evaluate(()=>{
            trainingMonitorState.phase='active';trainingMonitorState.active=true;
            viewer3d.className='viewer-card viewer-card-3d';viewer3d.style.height='680px';
            setUiLanguage('en');refreshMonitorCheckpointPresentation('active');
            document.querySelector('.monitor-dashboard-body').scrollTop=0;
        });
        for(const theme of ['dark','light']){
            await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
            await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
            await page.waitForFunction(()=>getComputedStyle(monitorDashboard).backgroundColor===getComputedStyle(monitorDashboard).getPropertyValue('--bg-card').trim());
            const contrast=await page.evaluate(()=>{
                const ctx=document.createElement('canvas').getContext('2d');
                const rgba=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data];};
                const base=rgba(getComputedStyle(document.documentElement).getPropertyValue('--bg-2'));
                const luminance=color=>color.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;})
                    .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
                return [...document.querySelectorAll('#monitorDashboard .monitor-guide-ledger span,#monitorDashboard .monitor-location-status,#monitorDashboard .monitor-key-changes caption')]
                    .map(node=>{const fg=luminance(rgba(getComputedStyle(node).color)),bg=rgba(getComputedStyle(monitorDashboard).backgroundColor);
                        const back=luminance(bg.map((v,i)=>i<3?v*(bg[3]/255)+base[i]*(1-bg[3]/255):255));
                        return (Math.max(fg,back)+.05)/(Math.min(fg,back)+.05);});
            });
            if(contrast.some(value=>value<4.5))console.log(await page.evaluate(()=>({theme:document.documentElement.dataset.theme,
                base:getComputedStyle(document.documentElement).getPropertyValue('--bg-2'),card:getComputedStyle(monitorDashboard).getPropertyValue('--bg-card'),background:getComputedStyle(monitorDashboard).backgroundColor,
                colors:[...monitorDashboard.querySelectorAll('.monitor-guide-ledger span,.monitor-location-status,.monitor-key-changes caption')].map(node=>getComputedStyle(node).color)})));
            assert(contrast.every(value=>value>=4.5),`${theme} secondary status text is readable: ${contrast}`);
            const controls=await page.evaluate(()=>{
                const ctx=document.createElement('canvas').getContext('2d');
                const rgb=value=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=value;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data].slice(0,3);};
                const light=values=>values.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;})
                    .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
                return [...document.querySelectorAll('#monitorDashboard button:not(:disabled),.monitor-open-coach,.monitor-viewer-guide button:not(:disabled)')]
                    .filter(node=>node.getClientRects().length).map(node=>{const css=getComputedStyle(node),fg=light(rgb(css.color)),bg=light(rgb(css.backgroundColor));
                        return (Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05);});
            });
            assert(controls.every(value=>value>=4.5),`${theme} visible control labels are readable: ${controls}`);
            assert.equal(await page.locator('#viewer3d .monitor-primary-action:visible').count(),1);
            const rect=await page.locator('.monitor-viewer-guide').boundingBox(),pixels=await page.locator('#viewer canvas').boundingBox();
            assert(rect.y>=pixels.y+pixels.height-1,'product CSS preserves a separate, unobstructed image surface');
            assert(await page.evaluate(()=>monitorDashboard.scrollWidth<=monitorDashboard.clientWidth+1));
            await page.screenshot({path:path.join(__dirname,`monitor-product-${theme}.png`)});
        }
        await page.setViewportSize({width:390,height:900});
        assert(await page.evaluate(()=>monitorDashboard.scrollWidth<=monitorDashboard.clientWidth+1),'real product CSS also fits a narrow monitor panel');
        assert.equal(await page.evaluate(()=>commands.length),0,'theme, locale, guidance navigation and previews trigger no GPU or geometry work');
        assert.deepEqual(errors,[]);
        console.log('Journey: 40-needle recognition, exact hidden-object/tree recovery, no history/prefix aliases or silent group reveal, calm receipts, adjacent Viewer coach, preview confirmation, reversible view, measured trade-offs, product dark/light contrast, no hidden jobs, owner/drag/stop fences and global locale/narrow layout passed.');
    }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
