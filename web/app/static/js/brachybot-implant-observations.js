/* Implanted observations are measurements, not editable future-plan sources.
 * Physical geometry is LPS mm. The captured timepoint and immutable revision
 * own every fetch, draft, drag and save. No local edit recalculates dose.
 */
(function implantedObservationUI() {
    'use strict';
    const records = new Map();
    let generation = 0, current = null, pending = null, draft = null, dragging = null, saveTimer = null, menu = null, sourceDialog=null, hit3D=()=>null;
    const copies=new Map();let lastStatus=null,lastStatusKind='info';
    const t = (zh,en) => {copies.set(zh,[zh,en]);copies.set(en,[zh,en]);return window._i18nLang === 'zh' ? zh : en;};
    const uuid = () => {
        if (typeof crypto.randomUUID==='function')return crypto.randomUUID();
        const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
        const hex=[...bytes].map(value=>value.toString(16).padStart(2,'0')).join('');
        return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
    };
    const finite = point => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite);
    const key = scope => JSON.stringify([scope.sessionId, scope.timepointId]);
    const capture = (explicit = null) => {
        const scope = explicit || window.BrachyBotTimepoints?.captureSubmission?.();
        if (!scope?.sessionId || !scope.timepointId) throw Error('implant_target_not_ready');
        return Object.freeze({ ...scope, observationGeneration: ++generation,
            viewerGeneration: typeof viewerDataLoadGeneration==='undefined' ? null : viewerDataLoadGeneration });
    };
    const mounted = scope => {
        let actual;
        try { actual = window.BrachyBotTimepoints?.captureSubmission?.(); } catch (_) { return false; }
        return actual?.sessionId === scope?.sessionId && actual?.timepointId === scope?.timepointId
            && (scope?.generation == null || actual?.generation === scope.generation)
            && (scope?.viewerGeneration == null || typeof viewerDataLoadGeneration==='undefined' || scope.viewerGeneration===viewerDataLoadGeneration);
    };
    const active = () => current && mounted(current.scope) ? current : null;
    const imageMounted = entry => entry?.viewerGeneration == null || typeof viewerDataLoadGeneration==='undefined'
        || entry.viewerGeneration===viewerDataLoadGeneration;
    const message = code => ({
        implant_target_not_ready: t('先加载目标时间点的图像。','Load the target timepoint image first.'),
        implant_revision_conflict: t('粒子识别记录已变更，已保留本次草稿。请刷新后重新核对。','Observation records changed. The draft is retained; refresh and review it again.'),
        implant_presentation_conflict: t('显示设置已在其他窗口变更，请刷新后重试。','Presentation changed in another window. Refresh and retry.'),
        implant_input_changed: t('图像已变更，未应用旧识别结果。请识别当前图像。','The image changed. Old detections were not applied. Detect the current image.'),
        seedfinder_not_configured: t('粒子识别模型未配置，请检查服务端 SeedFinder 配置。','SeedFinder is not configured. Check the server model configuration.'),
        implant_job_not_found: t('识别任务不再运行。请刷新已保存结果；若未提交，再启动识别。','The detection task is no longer running. Reload saved observations; start detection again if no result committed.'),
        implant_job_in_progress: t('此时间点正在识别粒子，请等待完成。','Detection is already running for this timepoint. Wait for completion.'),
        implant_reconstruction_not_found: t('先识别此图像中的粒子，再补充或修正。','Detect this image before adding or correcting observations.'),
    }[code] || t('粒子操作未完成，请核对目标和服务端状态后重试。','The observation operation did not complete. Check the target and server state before retrying.'));
    function status(copy, kind='info') {
        lastStatus=typeof copy==='function'?copy:(copies.get(copy) || copy);lastStatusKind=kind;
        const node = document.getElementById('implantObservationStatus');
        if (node) { node.textContent = typeof lastStatus==='function'?lastStatus():Array.isArray(lastStatus)?t(...lastStatus):copy; node.dataset.state=kind; }
    }
    async function request(scope, suffix='', method='GET', body=null) {
        const headers = new Headers({ 'X-BrachyBot-Session':scope.sessionId,'X-BrachyBot-Timepoint':scope.timepointId,
            'X-BrachyBot-Language':window._i18nLang === 'zh' ? 'zh':'en' });
        if (body !== null) headers.set('Content-Type','application/json');
        const url = '/api/sessions/' + encodeURIComponent(scope.sessionId) + '/timepoints/' + encodeURIComponent(scope.timepointId) + '/implants' + suffix;
        const init={ method,headers,...(body === null ? {} : {body:JSON.stringify(body)}) };
        let response;
        try {response=await fetch(url,init);}catch(error){
            // Only replay request-ID-bound observation transactions after a
            // lost network handshake. The exact target/body remains frozen.
            if(!body?.request_id || !['/detect','/corrections'].includes(suffix) || error.name==='AbortError')throw error;
            response=await fetch(url,init);
        }
        const data = await response.json();
        if (!response.ok || data.success === false) { const error = Error(data.code || 'implant_operation_failed'); error.code=data.code; throw error; }
        return data;
    }
    function removeMeshes() {
        if (typeof scene3D === 'undefined') return;
        Object.keys(scene3D.meshes).filter(id => id.startsWith('implanted_seed_') || id === 'implant_draft').forEach(id => {
            const object=scene3D.meshes[id]; scene3D.scene?.remove(object);
            object?.traverse?.(child=>{ child.geometry?.dispose?.(); child.material?.dispose?.(); });
            delete scene3D.meshes[id];
        });
    }
    function nodeFor(id) { return active()?.view.nodes.find(row=>row.id===id) || null; }
    const parentVisible=view=>typeof dataTreeState==='undefined' || !dataTreeState.planning
        || dataTreeState.planning.visible!==false && dataTreeState.planning[view==='2d'?'visible2D':'visible3D']!==false;
    function meshFor(row) {
        if (typeof THREE === 'undefined' || typeof init3DScene !== 'function') return null;
        init3DScene();
        let object;
        if (row.glyph === 'capsule' && finite(row.axis) && row.dimensions) {
            object=_makeSeedMesh({id:row.id,position:row.position,direction:row.axis,
                radius:row.dimensions.capsule_diameter_mm/2,length:row.dimensions.capsule_length_mm});
        } else {
            object=new THREE.Group();
            const sphere=new THREE.Mesh(new THREE.SphereGeometry(.7,12,8),new THREE.MeshBasicMaterial({color:row.color,transparent:true}));
            object.add(sphere); object.position.set(...row.position);
            if (finite(row.axis)) {
                const endpoints=row.axis.map(v=>v*2.5);
                object.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...endpoints.map(v=>-v)),new THREE.Vector3(...endpoints)]),
                    new THREE.LineBasicMaterial({color:row.color,transparent:true})));
            }
        }
        object.userData={type:'implanted_observation',id:row.id,observationId:row.observation_id,renderRole:'implanted_observation'};
        object.traverse?.(child=>{if(child.material){ child.material.color?.set(row.color); child.material.opacity=row.opacity;
            child.material.transparent=true; child.material.depthTest=true; }});
        object.visible=parentVisible('3d') && row.visible !== false && row.visible3D !== false && active()?.view.group?.visible !== false;
        object.renderOrder=42;
        return object;
    }
    function paint() {
        removeMeshes();
        const entry=active(); if(!entry || !imageMounted(entry)) return;
        for(const row of entry.view.nodes.filter(row=>!row.excluded)) {
            const object=meshFor({...row,opacity:row.opacity*(entry.view.group.opacity ?? 1)});
            if(object) {scene3D.scene.add(object);scene3D.meshes[row.id]=object;}
        }
        if(draft?.position && mounted(draft.scope)) {
            const object=meshFor({id:'implant_draft',position:draft.position,axis:null,glyph:'point_halo',color:'#FB7185',opacity:1,visible:true});
            if(object) {scene3D.scene.add(object);scene3D.meshes.implant_draft=object;}
        }
        if (!entry.cameraFramed && entry.view.active_count > 0) {
            entry.cameraFramed=true;
            if (scene3D._cameraUserInteracted !== true) window.ensureCameraFitsVisibleScene?.({reason:'implanted-source-reconstruction'});
        }
        if(Object.keys(scene3D.meshes).length){const placeholder=document.querySelector('#canvas3D .viewer-no-data');
            if(placeholder)placeholder.style.display='none';}
        reconcilePresentation();scene3D.requestRender?.(3); bindInteractions(); redraw2D();
    }
    function reconcilePresentation(){const entry=active();if(!entry || typeof scene3D==='undefined')return;
        const parentOpacity=typeof dataTreeState==='undefined'?1:dataTreeState.planning?.opacity ?? 1;
        for(const row of entry.view.nodes){const object=scene3D.meshes[row.id];if(!object)continue;
            object.visible=!row.excluded && parentVisible('3d') && row.visible!==false && row.visible3D!==false && entry.view.group.visible!==false;
            object.traverse?.(child=>{if(child.material)child.material.opacity=row.opacity*(entry.view.group.opacity ?? 1)*parentOpacity;});}
        scene3D.requestRender?.(2);
    }
    function accept(scope, view) {
        if(view.session_id!==scope.sessionId || view.timepoint_id!==scope.timepointId || !Array.isArray(view.nodes)
            || view.nodes.some(row=>!finite(row.position) || !/^#[0-9a-fA-F]{6}$/.test(row.color))) throw Error('invalid_implant_view');
        const previous = records.get(key(scope));
        records.set(key(scope),{scope,view,cameraFramed:previous?.cameraFramed === true,
            viewerGeneration:scope.viewerGeneration ?? (typeof viewerDataLoadGeneration==='undefined'?null:viewerDataLoadGeneration)});
        if(!mounted(scope)) return false;
        current=records.get(key(scope)); paint(); renderTree(); renderToolbar(); return true;
    }
    async function reload(explicit = null, options = {}) {
        let scope;
        try {if(!window.BrachyBotTimepoints?.getCatalog?.())await window.BrachyBotTimepoints?.refresh?.({activate:false});
            scope=capture(explicit); const data=await request(scope); if(scope.observationGeneration!==generation)return false; return accept(scope,data.view);}
        catch(error){ if(scope && mounted(scope))status(message(error.code),'error');
            // Resource hydration must not authorize presentation saves after a
            // genuine observation read failure. Superseded reads still return
            // false normally; existing interactive callers retain that contract.
            if(options.throwOnError)throw error;return false; }
    }
    async function detect() {
        const scope=capture(), entry=active(), requestId=uuid(), started=Date.now();
        if(pending || draft){ status(t('先完成或取消当前粒子修正。','Finish or cancel the current correction first.'));return false; }
        const operation={scope,requestId,started};pending=operation;renderToolbar();
        const timer=setInterval(()=>{if(mounted(scope))status(t('识别并重建粒子…','Detecting and reconstructing seeds…')+' '+Math.floor((Date.now()-started)/1000)+'s');},1000);
        try {
            if(!await flushPresentation())return false;
            await request(scope,'/detect','POST',{request_id:requestId,expected_revision_id:entry?.view.observation_revision_id || null});
            while(true) {
                await new Promise(resolve=>setTimeout(resolve,700));
                const {job}=await request(scope,'/jobs/'+encodeURIComponent(requestId));
                if(job.status==='completed'){accept(scope,job.view);
                    if(mounted(scope)) await window.BrachyBotTimepointWorkspace?.restoreActive?.();
                    const currentScope=window.BrachyBotTimepointWorkspace?.mountedScope?.();
                    if(currentScope?.sessionId===scope.sessionId && currentScope?.timepointId===scope.timepointId)
                        status(t('已识别并重建，逐颗复核后再计算剂量。','Detected and reconstructed. Review each observation before dose calculation.'));
                    return true;}
                if(job.status==='failed'){ const error=Error(job.code);error.code=job.code;throw error; }
            }
        } catch(error){if(mounted(scope))status(message(error.code),'error');return false;}
        finally {clearInterval(timer);if(pending===operation)pending=null;renderToolbar();}
    }
    function changePresentation(id, patch) {
        const entry=active(), row=nodeFor(id); if(!entry)return false;
        if(id==='implanted_observations') {Object.assign(entry.view.group,patch);entry.groupPatch={...entry.groupPatch,...patch};}
        else if(row){Object.assign(row,patch);entry.patches={...entry.patches,[row.observation_id]:{...entry.patches?.[row.observation_id],...patch}};}
        else return false;
        // Never replace a dragged slider or rebuild every mesh on input.
        const rows=id==='implanted_observations'?entry.view.nodes:[row];
        for(const item of rows){const object=typeof scene3D!=='undefined'?scene3D.meshes[item.id]:null;if(!object)continue;
            object.visible=!item.excluded && item.visible!==false && item.visible3D!==false && entry.view.group.visible!==false;
            object.traverse?.(child=>{if(child.material){child.material.color?.set(item.color);child.material.opacity=item.opacity*(entry.view.group.opacity ?? 1);}});
            const element=document.querySelector('[data-node-id="'+item.id+'"]');
            if(element){const eye=element.querySelector('.eye-btn');if(eye)eye.textContent=object.visible?'◉':'○';}
        }reconcilePresentation();scene3D.requestRender?.(2);redraw2D();clearTimeout(saveTimer);saveTimer=setTimeout(()=>void flushPresentation(),180);return true;
    }
    async function flushPresentation() {
        const entry=active(); if(!entry || !(entry.patches && Object.keys(entry.patches).length || entry.groupPatch))return true;
        if(entry.saving){await entry.saving;return flushPresentation();}
        const patches=entry.patches || {}, group=entry.groupPatch || {}, old=entry.view.presentation_revision;
        entry.patches=null;entry.groupPatch=null;
        entry.saving=(async()=>{try {const data=await request(entry.scope,'/presentation','PATCH',{expected_presentation_revision:old,patches,group});
            const later=entry.patches || {}, laterGroup=entry.groupPatch;for(const row of data.view.nodes)Object.assign(row,later[row.observation_id] || {});
            if(laterGroup)Object.assign(data.view.group,laterGroup);accept(entry.scope,data.view);
            const next=records.get(key(entry.scope));next.patches=later;next.groupPatch=laterGroup;return true;
        }catch(error){entry.patches={...patches,...entry.patches};entry.groupPatch={...group,...entry.groupPatch};status(message(error.code),'error');return false;}})();
        try{return await entry.saving;}finally{entry.saving=null;}
    }
    async function correction(action, rows=[], position=null) {
        const entry=active(); if(!entry || !entry.view.observation_revision_id || pending)return false;
        const scope={...entry.scope}; const revision=entry.view.observation_revision_id;
        const operation={scope,action};pending=operation;renderToolbar();
        try {if(!await flushPresentation())return false; const data=await request(scope,'/corrections','POST',{action,request_id:uuid(),expected_revision_id:revision,
            observation_ids:rows.map(row=>row.observation_id),...(position?{center_lps_mm:position}:{})});
            if(mounted(scope))draft=null;accept(scope,data.view);
            if(mounted(scope)) await window.BrachyBotTimepointWorkspace?.restoreActive?.();
            const now=window.BrachyBotTimepointWorkspace?.mountedScope?.();
            if(now?.sessionId===scope.sessionId && now?.timepointId===scope.timepointId)
                status(t('识别记录已修正；原始证据保留，相关剂量需重新计算。','Observation corrected. Original evidence is retained; dependent dose must be recomputed.'));
            return true;
        }catch(error){if(mounted(scope))status(message(error.code),'error');return false;}
        finally{if(pending===operation)pending=null;renderToolbar();}
    }
    async function exclude(id) {
        const row=nodeFor(id), entry=active();if(!row || !entry || pending)return false;
        const scope={...entry.scope}, revision=entry.view.observation_revision_id;
        const okay=await window._confirmAction?.(t('从识别结果中排除这颗粒子？不会改变患者体内的真实粒子。','Exclude this seed observation? This does not remove a physical implant.'),
            'Exclude this seed observation? This does not remove a physical implant.',{titleZh:'排除误识别粒子',titleEn:'Exclude false detection',yesZh:'排除',yesEn:'Exclude'});
        if(!okay || !mounted(scope) || active()?.view.observation_revision_id!==revision)return false;
        return correction('exclude',[row]);
    }
    function startAdd() {
        const entry=active();if(!entry?.view.observation_revision_id || pending)return false;
        draft={scope:{...entry.scope},revision:entry.view.observation_revision_id,position:null,action:'add'};
        switchPanel?.('viewers',document.querySelectorAll('.panel-tab')[2]);
        status(t('点击任一 2D 视图中的漏检粒子中心，再在 3D 中拖拽微调，最后点击保存。','Click the missed seed center in a 2D view, refine it by dragging in 3D, then Save.'));
        bindInteractions();renderToolbar();return true;
    }
    function startMove(id) {
        const entry=active(), row=nodeFor(id);if(!row || pending)return false;
        draft={scope:{...entry.scope},revision:entry.view.observation_revision_id,position:row.position.slice(),action:'move',row};
        status(t('拖拽粉红色草稿点微调；保存前原识别记录不会改变。','Drag the pink draft point to refine it. The saved observation stays unchanged until Save.'));
        paint();renderToolbar();return true;
    }
    function cancelDraft(){draft=null;dragging=null;paint();renderToolbar();status(t('已取消草稿，已保存识别结果保持不变。','Draft cancelled; saved observations are unchanged.'));}
    async function saveDraft(){if(!draft?.position || !mounted(draft.scope))return false;
        if(active()?.view.observation_revision_id!==draft.revision){status(message('implant_revision_conflict'),'error');return false;}
        return correction(draft.action,draft.row?[draft.row]:[],draft.position);}
    async function configureSource(){const scope=capture();if(pending || draft)return false;
        const data=await request(scope,'/dose-source');if(!mounted(scope))return false;sourceDialog?._close?.();
        const previous=document.activeElement,overlay=document.createElement('div');overlay.className='timepoint-modal';
        const form=document.createElement('form');form.className='timepoint-dialog';form.setAttribute('role','dialog');form.setAttribute('aria-modal','true');
        const bilingual=(tag,zh,en)=>{const node=document.createElement(tag);node.dataset.i18nZh=zh;node.dataset.i18nEn=en;node.textContent=t(zh,en);return node;};
        const title=bilingual('h2','体内粒子剂量源设置','Implanted-dose source settings');title.id='implantSourceTitle';form.setAttribute('aria-labelledby',title.id);form.append(title);
        form.append(bilingual('p','请输入当前体内粒子的真实尺寸。这里仅确认软件估计剂量参数，不构成临床批准。','Enter the actual implanted-source dimensions. This confirms software estimation settings, not clinical approval.'));
        const length=document.createElement('input'),radius=document.createElement('input');
        for(const [input,zh,en,value] of [[length,'粒子长度（mm）','Source length (mm)',data.profile?.seed_info?.length],[radius,'粒子半径（mm）','Source radius (mm)',data.profile?.seed_info?.radius]]){
            const label=document.createElement('label');label.append(bilingual('span',zh,en));input.type='number';input.step='.01';input.min='.01';input.max='100';input.required=true;input.value=value || '';input.setAttribute('aria-label',t(zh,en));label.append(input);form.append(label);}
        const calibration=document.createElement('p');calibration.append(bilingual('span','当前 CNN 标定（Gy／模型单位）：','Current CNN calibration (Gy/model unit): '),document.createTextNode(String(data.dose_scale_gy)));form.append(calibration);
        const errors=document.createElement('p');errors.setAttribute('role','alert');form.append(errors);
        const actions=document.createElement('div');actions.className='timepoint-dialog-actions';
        const cancel=bilingual('button','取消','Cancel'),save=bilingual('button','确认当前源设置','Confirm current source settings');cancel.type='button';save.type='submit';save.className='timepoint-action primary';cancel.className='timepoint-action';actions.append(cancel,save);form.append(actions);overlay.append(form);document.body.append(overlay);sourceDialog=overlay;
        const close=()=>{document.removeEventListener('keydown',keydown);overlay.remove();if(sourceDialog===overlay)sourceDialog=null;previous?.focus?.();};
        overlay._close=close;
        const keydown=event=>{if(event.key==='Escape'){event.preventDefault();close();}if(event.key==='Tab'){const nodes=[length,radius,cancel,save].filter(node=>!node.disabled);if(event.shiftKey&&document.activeElement===nodes[0]){event.preventDefault();nodes.at(-1).focus();}else if(!event.shiftKey&&document.activeElement===nodes.at(-1)){event.preventDefault();nodes[0].focus();}}};
        document.addEventListener('keydown',keydown);cancel.onclick=close;length.focus();
        form.onsubmit=async event=>{event.preventDefault();if(!mounted(scope)){close();return;}save.disabled=true;
            const operation={scope,action:'source-settings'};pending=operation;renderToolbar();
            try{await request(scope,'/dose-source','POST',{length_mm:Number(length.value),radius_mm:Number(radius.value),
                ...(Number.isInteger(data.clinical_revision)?{expected_clinical_revision:data.clinical_revision}:{expected_state_revision:data.state_revision})});close();
                const restored=mounted(scope)?await window.BrachyBotTimepointWorkspace?.restoreActive?.():false;
                const now=window.BrachyBotTimepointWorkspace?.mountedScope?.();
                if(now?.sessionId===scope.sessionId && now?.timepointId===scope.timepointId)
                    status(restored===false?t('源设置已保存，但显示恢复尚未完成。请重试恢复；不要重复确认源设置。','Source settings were saved, but display restoration did not finish. Retry restoration; do not submit the source settings again.'):
                        t('已确认当前源设置；可只重算体内粒子的剂量。','Current source settings confirmed; implanted-dose recomputation is available.'),restored===false?'error':'info');}
            catch(error){errors.dataset.errorCode=error.code || 'implant_operation_failed';errors.textContent=message(error.code);save.disabled=false;
                if(!overlay.isConnected)status(message(error.code),'error');}
            finally{if(pending===operation)pending=null;renderToolbar();}};
        return true;
    }
    async function reviewObservations(){const scope=capture(),view=active()?.view;
        if(pending || draft || !view?.observation_revision_id)return false;
        sourceDialog?._close?.();
        const previous=document.activeElement,overlay=document.createElement('div');overlay.className='timepoint-modal';
        const form=document.createElement('form');form.className='timepoint-dialog';form.setAttribute('role','dialog');form.setAttribute('aria-modal','true');
        const text=(tag,zh,en)=>{const node=document.createElement(tag);node.dataset.i18nZh=zh;node.dataset.i18nEn=en;node.textContent=t(zh,en);return node;};
        const title=text('h2','复核体内粒子','Review implanted observations');title.id='implantReviewTitle';form.setAttribute('aria-labelledby',title.id);form.append(title);
        form.append(text('p','请在 2D／3D 中检查包含的粒子、误检排除、位置与估计方向。确认用于软件增量规划，不等于临床批准。','Check included observations, exclusions, centers and estimated axes in 2D/3D. This confirms software continuation inputs, not clinical approval.'));
        const observation=document.createElement('input'),coverage=document.createElement('input');
        for(const [input,zh,en] of [[observation,'我已复核所有包含的粒子及方向','I reviewed all included observations and axes'],[coverage,'本次图像完整包含需要计入的已植入粒子','This scan covers the implanted sources that must be included']]){
            const label=document.createElement('label');input.type='checkbox';input.required=true;label.append(input,text('span',zh,en));form.append(label);}
        const label=document.createElement('label');label.append(text('span','复核记录','Review note'));
        const note=document.createElement('textarea');note.required=true;note.maxLength=4000;label.append(note);form.append(label);
        const error=document.createElement('p');error.setAttribute('role','alert');form.append(error);
        const actions=document.createElement('div');actions.className='timepoint-dialog-actions';
        const cancel=text('button','取消','Cancel'),save=text('button','确认复核','Confirm review');cancel.type='button';save.type='submit';actions.append(cancel,save);form.append(actions);
        overlay.append(form);document.body.append(overlay);sourceDialog=overlay;
        const close=()=>{document.removeEventListener('keydown',keydown);overlay.remove();if(sourceDialog===overlay)sourceDialog=null;previous?.focus?.();};overlay._close=close;
        const keydown=e=>{if(e.key==='Escape'){e.preventDefault();close();}if(e.key==='Tab'){const nodes=[observation,coverage,note,cancel,save].filter(n=>!n.disabled);
            if(e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes.at(-1).focus();}else if(!e.shiftKey&&document.activeElement===nodes.at(-1)){e.preventDefault();nodes[0].focus();}}};
        document.addEventListener('keydown',keydown);cancel.onclick=close;observation.focus();
        form.onsubmit=async event=>{event.preventDefault();if(!mounted(scope)){close();return;}save.disabled=true;
            try{const response=await request(scope,'/review','POST',{expected_revision_id:view.observation_revision_id,
                observations_confirmed:observation.checked,coverage_confirmed:coverage.checked,note:note.value.trim()});
                const owns=mounted(scope);if(owns)accept(scope,response.view);close();
                if(owns)await window.BrachyBotTimepointWorkspace?.restoreActive?.();
                const now=window.BrachyBotTimepointWorkspace?.mountedScope?.();
                if(now?.sessionId===scope.sessionId && now?.timepointId===scope.timepointId)
                    status(t('复核已保存；旧指标不会被当作当前指标，增量规划将重算或复用匹配的剂量。','Review saved. Old metrics are not current; continuation recomputes or reuses matching dose.'));}
            catch(e){error.dataset.errorCode=e.code||'implant_operation_failed';error.textContent=message(e.code);save.disabled=false;}};
        return true;
    }
    async function recomputeDose() {
        const entry=active();
        if (!entry || !entry.view.observation_revision_id) {status(message('implant_target_not_ready'),'error');return false;}
        if (pending || draft) {status(t('请先完成当前识别或粒子修正。','Finish the current detection or observation correction first.'),'error');return false;}
        const scope={...entry.scope}; pending={scope,action:'dose'}; renderToolbar();
        status(t('正在核对输入并重算体内粒子剂量…','Checking inputs and recomputing implanted-source dose…'));
        try {
            if (!await flushPresentation()) {status(message('implant_presentation_conflict'),'error');return false;}
            const endpoint='/api/sessions/'+encodeURIComponent(scope.sessionId)+'/timepoints/'+encodeURIComponent(scope.timepointId)+'/workspace';
            const workspaceResponse=await window.BrachyBotTimepoints.request(scope,endpoint);
            const workspace=await workspaceResponse.json();
            if (!workspaceResponse.ok) {status(message(workspace.code),'error');return false;}
            if (!mounted(scope)) {
                const currentScope=window.BrachyBotTimepointWorkspace?.mountedScope?.();
                if(currentScope?.sessionId===scope.sessionId && currentScope?.timepointId===scope.timepointId)
                    status(t('图像显示已重新加载，尚未开始剂量计算。请等待恢复完成后重试。','The image display was reloaded before dose computation started. Wait for restoration and retry.'),'error');
                return false;
            }
            const response=await window.BrachyBotTimepoints.request(scope,'/api/dose/recompute',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({source_set:'implanted',expected_clinical_revision:workspace.workspace.timepoint_clinical_revision,
                    expected_observation_revision_id:entry.view.observation_revision_id})});
            const packet=await response.json(); if(!mounted(scope))return false;
            if(!response.ok || !packet.success){status(message(packet.code || 'component_dose_recompute_failed'),'error');return false;}
            await window.BrachyBotTimepointWorkspace.restoreActive();
            const now=window.BrachyBotTimepointWorkspace.mountedScope();
            if (now?.sessionId!==scope.sessionId || now?.timepointId!==scope.timepointId) return false;
            await window.BrachyBotTimepointWorkspace.selectDose('implanted',{persist:false});
            status(t('体内粒子剂量已重算并保存，未重新规划或生成导板、报告。','Implanted-source dose was saved. No replanning, guide generation or report generation was performed.'));
            return true;
        } catch(error){if(mounted(scope))status(message(error.code || 'component_dose_recompute_failed'),'error');return false;}
        finally {if(pending?.scope===scope)pending=null;renderToolbar();}
    }
    function renderToolbar(){const node=document.getElementById('implantObservationActions');if(!node)return;
        const actions=[[t('识别并重建粒子','Detect & reconstruct'),detect,!!pending],
            [t('补充漏检粒子','Add missed seed'),startAdd,!!pending || !active()?.view.observation_revision_id],
            [t('刷新识别记录','Reload observations'),reload,!!pending]];
        if(draft)actions.push([t('保存修正','Save correction'),saveDraft,!!pending || !draft.position],[t('取消','Cancel'),cancelDraft,!!pending]);
        actions.push([t('源与剂量设置','Source & dose settings'),configureSource,!!pending || !!draft]);
        actions.push([t('复核体内粒子','Review implanted observations'),reviewObservations,!!pending || !!draft || !active()?.view.observation_revision_id]);
        actions.push([t('只重算体内粒子剂量','Recompute implanted dose only'),recomputeDose,!!pending || !!draft || !active()?.view.observation_revision_id]);
        const ids=new Map([[detect,'implantDetect'],[startAdd,'implantAddMissed'],[reload,'implantReload'],[saveDraft,'implantSaveCorrection'],[cancelDraft,'implantCancelCorrection'],[configureSource,'implantSourceSettings'],[reviewObservations,'implantReviewObservations'],[recomputeDose,'implantRecomputeDose']]);
        const retained=new Set();
        for(const [label,fn,disabled] of actions){const id=ids.get(fn);if(!id)continue;retained.add(id);
            let button=node.querySelector('#'+id);
            if(!button){button=document.createElement('button');button.id=id;button.type='button';button.className='btn btn-outline';node.append(button);}
            button.textContent=label;button.disabled=disabled;button.onclick=()=>void Promise.resolve(fn()).catch(error=>status(message(error.code),'error'));
        }
        // Preserve real nodes during async restoration. Replacing a pressed
        // button between pointerdown/up silently drops the click and focus.
        for(const button of [...node.children])if(!retained.has(button.id))button.remove();
    }
    function renderTree(){const body=document.getElementById('dataTreeBody');if(!body)return;
        body.querySelector('#implantedObservationTree')?.remove();const entry=active();if(!entry?.view.observation_revision_id){removeMeshes();return;}
        if(!imageMounted(entry)){removeMeshes();return;}
        const group=document.createElement('details');group.id='implantedObservationTree';group.className='implant-tree-group';group.open=true;
        const header=document.createElement('summary');header.textContent=t('已植入粒子 · 识别记录','Implanted seeds · observations')+' ('+entry.view.active_count+')';group.append(header);
        const actions=document.createElement('div');actions.className='implant-tree-actions';
        for(const [copy,show] of [[t('全部显示','Show all'),true],[t('全部隐藏','Hide all'),false]]){const button=document.createElement('button');button.textContent=copy;button.className='btn btn-outline';button.onclick=()=>changePresentation('implanted_observations',{visible:show});actions.append(button);}group.append(actions);
        const excluded=document.createElement('details'), title=document.createElement('summary');title.textContent=t('已排除的误识别','Excluded detections');excluded.append(title);
        if(entry.view.implanted_dose){const dose=document.createElement('div');dose.className='tree-item';dose.dataset.nodeType='implanted_dose';
            dose.textContent=entry.view.implanted_dose.stale?t('体内粒子剂量 · 已过期，需重算','Implanted dose · stale; recompute'):
                t('体内粒子剂量 · 已保存（估计）','Implanted dose · saved (estimated)');group.append(dose);}
        for(const row of entry.view.nodes){const item=document.createElement('div');item.className='tree-item implant-tree-item';item.dataset.nodeId=row.id;item.dataset.objectId=row.object_id;item.dataset.nodeType='implanted_observation';
            item.dataset.liveNode='true';item.dataset.visualTarget='true';item.dataset.timepointId=entry.scope.timepointId;
            item.dataset.status=row.excluded?'excluded':'ready';item.dataset.visible=String(row.visible!==false);item.dataset.visible2d=String(row.visible2D!==false);item.dataset.visible3d=String(row.visible3D!==false);
            const eye=document.createElement('button');eye.className='eye-btn';eye.textContent=row.visible && entry.view.group.visible!==false?'◉':'○';eye.title=t('显示／隐藏','Show / hide');eye.disabled=row.excluded;eye.onclick=()=>changePresentation(row.id,{visible:!row.visible});
            const color=document.createElement('input');color.type='color';color.className='implant-color';color.value=row.color;color.title=t('粒子颜色','Seed color');color.oninput=()=>changePresentation(row.id,{color:color.value});
            const label=document.createElement('span');label.className='item-label';label.textContent=t('植入粒子 ','Implanted seed ')+row.ordinal;label.title=row.observation_id+' | '+row.position.map(v=>v.toFixed(2)).join(', ')+' mm';
            row.label=label.textContent;
            const tag=document.createElement('span');tag.className='implant-review-tag';tag.textContent=row.excluded?t('已排除','Excluded'):row.review_status==='accepted'?t('已复核','Reviewed'):t('待复核','Review');
            const opacity=document.createElement('input');opacity.type='range';opacity.min=0;opacity.max=100;opacity.value=Math.round(row.opacity*100);opacity.className='opacity-slider';opacity.ariaLabel=t('透明度','Opacity');opacity.oninput=()=>changePresentation(row.id,{opacity:Number(opacity.value)/100});
            item.append(eye,color,label,tag,opacity);item.oncontextmenu=event=>{event.preventDefault();event.stopPropagation();showMenu(row.id,event.clientX,event.clientY);};label.onclick=event=>{if(typeof handleTreeItemClick==='function')handleTreeItemClick(row.id,event);focus(row.id);};
            (row.excluded?excluded:group).append(item);
        }if(excluded.children.length>1)group.append(excluded);
        const planning=body.querySelector('.tree-group[data-group="planning"]');
        (planning?.querySelector(':scope > .tree-group-items') || body.querySelector('.timepoint-data-root > .tree-group-items') || body).append(group);
    }
    function focus(id){const row=nodeFor(id);if(!row || !state?.ctShape)return;const index=_worldToIndex(...row.position);if(index){state.slices.axial=state.ctShape[0]-1-Math.round(index[0]);state.slices.sagittal=Math.round(index[2]);state.slices.coronal=Math.round(index[1]);['axial','sagittal','coronal'].forEach(axis=>{if(typeof updateSlice==='function')updateSlice(axis,state.slices[axis]);});}redraw2D();}
    function showMenu(id,x,y){hideContextMenu?.();menu?.remove();const row=nodeFor(id);if(!row)return;
        menu=document.createElement('div');menu.className='ctx-menu';menu.style.left=x+'px';menu.style.top=y+'px';
        const choices=row.excluded?[[t('恢复识别记录','Restore observation'),()=>correction('restore',[row])]]:
            [[t('定位此粒子','Locate seed'),()=>focus(id)],[t('微调识别位置','Refine observed position'),()=>startMove(id)],
             [t('排除误识别（不移除体内粒子）','Exclude detection (not physical implant)'),()=>exclude(id)],
             [t('显示／隐藏','Show / hide'),()=>changePresentation(id,{visible:!row.visible})],
             [row.visible2D===false?t('在 2D 显示','Show in 2D'):t('在 2D 隐藏','Hide in 2D'),()=>changePresentation(id,{visible2D:row.visible2D===false})],
             [row.visible3D===false?t('在 3D 显示','Show in 3D'):t('在 3D 隐藏','Hide in 3D'),()=>changePresentation(id,{visible3D:row.visible3D===false})],
             [t('补充漏检粒子','Add missed seed'),startAdd]];
        for(const [label,fn] of choices){const item=document.createElement('button');item.className='ctx-menu-item';item.textContent=label;item.onclick=()=>{menu.remove();menu=null;void fn();};menu.append(item);}document.body.append(menu);window.__brachyContextMenuElement=menu;window.positionBrachyContextMenu?.(menu,x,y);
    }
    function xyzToLps(voxel){const spacing=state.ctSpacing,origin=state.ctOrigin,dir=state.ctDirection;if(!finite(spacing)||!finite(origin)||!Array.isArray(dir)||dir.length!==9)return null;
        return [0,1,2].map(row=>origin[row]+[0,1,2].reduce((sum,column)=>sum+dir[row*3+column]*voxel[['x','y','z'][column]]*spacing[column],0));}
    function redraw2D(){for(const axis of ['axial','sagittal','coronal'])draw2D(axis);}
    function draw2D(axis){const slice=typeof getSliceCanvas==='function'?getSliceCanvas(axis):null;if(!slice)return;
        let canvas=document.getElementById('implantOverlay-'+axis);if(!canvas){canvas=document.createElement('canvas');canvas.id='implantOverlay-'+axis;canvas.style.cssText='position:absolute;pointer-events:none;z-index:8';slice.parentElement.append(canvas);}
        if(typeof _syncLayerToSliceCanvas!=='function')return;_syncLayerToSliceCanvas(axis,canvas,8,{vector:true});const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
        const entry=active();if(!entry || !imageMounted(entry) || !state.ctShape || entry.view.group.visible===false || !parentVisible('2d'))return;
        const shape=state.ctShape,geometry=_getMprGeometry(axis,shape,state.ctSpacing),normal={axial:0,sagittal:2,coronal:1}[axis];
        const rows=entry.view.nodes.filter(row=>!row.excluded && row.visible!==false && row.visible2D!==false);
        if(draft?.position && mounted(draft.scope))rows.push({position:draft.position,color:'#FB7185',opacity:1});
        for(const row of rows){const raw=_worldToIndex(...row.position);if(!raw)continue;const index=raw.slice();if(axis==='axial')index[0]=shape[0]-1-index[0];
            const tolerance=Math.max(.6,(row.dimensions?.capsule_length_mm || 1.4)/2/(state.ctSpacing[2-normal] || 1));
            if(Math.abs(index[normal]-state.slices[axis])>tolerance)continue;
            const dimA=axis==='sagittal'?1:2,dimB=axis==='axial'?1:0;
            const x=index[dimA]*canvas.width/shape[dimA],y=(axis==='axial'?index[dimB]:_volumeZToDisplayY(index[dimB],geometry.resampleRatio))*canvas.height/(axis==='axial'?shape[dimB]:geometry.height);
            const parentOpacity=typeof dataTreeState==='undefined'?1:dataTreeState.planning?.opacity ?? 1;
            ctx.save();ctx.globalAlpha=row.opacity*(entry.view.group.opacity ?? 1)*parentOpacity;ctx.strokeStyle=row.color;ctx.fillStyle=row.color;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,4,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.arc(x,y,1.5,0,Math.PI*2);ctx.fill();ctx.restore();
        }
    }
    function bindInteractions(){for(const axis of ['axial','sagittal','coronal']){const canvas=typeof getSliceCanvas==='function'?getSliceCanvas(axis):null;if(!canvas || canvas._implantBound)continue;canvas._implantBound=true;
        canvas.addEventListener('pointerdown',event=>{if(!draft || draft.position || !mounted(draft.scope) || event.button!==0)return;
            const coords=screenToImageCoords(axis,event.clientX,event.clientY),shape=state.ctShape;
            if(!shape)return;const geometry=_getMprGeometry(axis,shape,state.ctSpacing),width=axis==='sagittal'?shape[1]:shape[2],height=axis==='axial'?shape[1]:geometry.height;
            if(coords.x<0 || coords.y<0 || coords.x>=width || coords.y>=height)return;
            const voxel=_sliceImageCoordsToVoxel(axis,coords),point=voxel&&xyzToLps(voxel);if(!finite(point))return;
            event.preventDefault();event.stopImmediatePropagation();draft.position=point;paint();renderToolbar();},true);
    }
        const canvas=typeof scene3D!=='undefined'?scene3D.renderer?.domElement:null;if(!canvas || canvas._implantBound || typeof THREE==='undefined')return;canvas._implantBound=true;
        const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
        const ray=event=>{scene3D.scene.updateMatrixWorld(true);scene3D.camera.updateMatrixWorld();const box=canvas.getBoundingClientRect();pointer.set((event.clientX-box.left)/box.width*2-1,-(event.clientY-box.top)/box.height*2+1);raycaster.setFromCamera(pointer,scene3D.camera);};
        const picked=event=>{ray(event);const objects=Object.values(scene3D.meshes).filter(object=>object?.visible && object.userData?.type==='implanted_observation' && (nodeFor(object.userData.id)?.opacity ?? 1)>.001);let object=raycaster.intersectObjects(objects,true)[0]?.object;while(object?.parent && !object.userData?.observationId && object.userData?.id!=='implant_draft')object=object.parent;return object;};
        hit3D=event=>active()&&imageMounted(active())?picked(event):null;
        canvas.addEventListener('contextmenu',event=>{const hit=picked(event);if(!hit?.userData?.observationId)return;event.preventDefault();event.stopImmediatePropagation();showMenu(hit.userData.id,event.clientX,event.clientY);},true);
        canvas.addEventListener('pointerdown',event=>{if(event.button!==0 || pending)return;const hit=picked(event);if(!hit)return;
            if(hit.userData?.id!=='implant_draft' && !startMove(hit.userData.id))return;if(!draft?.position)return;
            ray(event);const normal=scene3D.camera.getWorldDirection(new THREE.Vector3()),plane=new THREE.Plane().setFromNormalAndCoplanarPoint(normal,new THREE.Vector3(...draft.position));
            dragging={plane,scope:{...draft.scope},pointerId:event.pointerId,controlsEnabled:scene3D.controls.enabled};scene3D.controls.enabled=false;
            event.preventDefault();event.stopImmediatePropagation();canvas.setPointerCapture?.(event.pointerId);},true);
        canvas.addEventListener('pointermove',event=>{if(!dragging || !draft || !mounted(dragging.scope))return;ray(event);const point=new THREE.Vector3();if(raycaster.ray.intersectPlane(dragging.plane,point)){draft.position=[point.x,point.y,point.z];scene3D.meshes.implant_draft?.position.copy(point);scene3D.requestRender?.(2);redraw2D();}event.preventDefault();event.stopImmediatePropagation();},true);
        const end=event=>{if(!dragging)return;scene3D.controls.enabled=dragging.controlsEnabled;dragging=null;canvas.releasePointerCapture?.(event.pointerId);renderToolbar();};canvas.addEventListener('pointerup',end,true);canvas.addEventListener('pointercancel',end,true);
    }
    async function applyTool(meta, ownerScope=null){const command=meta?.implant_command,view=meta?.implant_view;if(!command)return false;
        const scope=ownerScope || meta.timepoint_scope || {sessionId:command.session_id,timepointId:command.timepoint_id};
        if(window.BrachyBotTimepoints?.enabled?.() && !Number.isInteger(scope.generation))return false;
        if(scope.sessionId!==command.session_id || scope.timepointId!==command.timepoint_id || !mounted(scope))return false;
        if(command.action==='dose_ready'){await reload(scope);if(!mounted(scope))return false;
            await window.BrachyBotTimepointWorkspace?.selectDose?.('implanted',{persist:false});if(!mounted(scope))return false;
            status(t('体内粒子剂量已重算并保存；当前为估计剂量，需复核方向与源参数。','Implanted-dose recomputation is saved. This estimated dose needs axis and source review.'));return true;}
        if(!view)return false;
        accept(scope,view);if(command.action==='start_add')return startAdd();if(command.action==='start_review'){switchPanel?.('viewers',document.querySelectorAll('.panel-tab')[2]);return reviewObservations();}return true;
    }
    function reset(){if(dragging && typeof scene3D!=='undefined')scene3D.controls.enabled=dragging.controlsEnabled;sourceDialog?._close?.();sourceDialog=null;draft=null;dragging=null;current=null;generation++;removeMeshes();redraw2D();renderToolbar();}
    const ready=()=>{renderToolbar();window.addEventListener('i18nchange',()=>{renderToolbar();renderTree();
        sourceDialog?.querySelectorAll('[data-i18n-zh]').forEach(node=>{node.textContent=t(node.dataset.i18nZh,node.dataset.i18nEn);});
        const sourceError=sourceDialog?.querySelector('[role="alert"]');if(sourceError?.dataset.errorCode)sourceError.textContent=message(sourceError.dataset.errorCode);
        sourceDialog?.querySelectorAll('label').forEach(label=>{const span=label.querySelector('span'),input=label.querySelector('input');if(span&&input)input.setAttribute('aria-label',span.textContent);});
        if(lastStatus){const copy=lastStatus;status(typeof copy==='function'?copy:Array.isArray(copy)?()=>t(...copy):copy,lastStatusKind);}menu?.remove();menu=null;});
        window.addEventListener('brachybot:timepoint-changed', event => {
            const warm = event.detail?.warmResourcesRestored === true
                && window.__brachybotWarmRestore?.timepointId === event.detail?.timepointId
                && window.__brachybotWarmRestore?.sessionId === event.detail?.sessionId;
            const warmView = warm ? window.__brachybotWarmRestore?.implantView : null;
            reset();
            if (warm && warmView) {
                // The observation registry is module-private and its normal
                // timepoint listener resets it. Rebind the parked immutable
                // view instead of issuing a second /implants request.
                const scope = window.BrachyBotTimepoints?.captureSubmission?.();
                if (scope) accept(scope, warmView);
                return;
            }
            void reload();
        });
        window.addEventListener('brachybot:timepoint-session-ready',()=>{reset();void reload();});
        document.addEventListener('keydown',event=>{if(event.key==='Escape'){menu?.remove();menu=null;if(draft)cancelDraft();}});
        document.addEventListener('pointerdown',event=>{if(menu && !menu.contains(event.target)){menu.remove();menu=null;}},true);
        void reload();};
    window.BrachyBotImplants=Object.freeze({detect,reload,startAdd,startMove,saveDraft,cancelDraft,configureSource,exclude,focus,
        renderTree,draw2D,paint,bindInteractions,nodeFor,changePresentation,applyTool,accept,suspend:reset,reconcilePresentation,
        snapshot:()=>active()?.view || null,xyzToLps,recomputeDose,
        interactionMode:()=>draft&&mounted(draft.scope)?(draft.position?'refining':'placing'):null,
        owns3DPointer:event=>!!(draft&&mounted(draft.scope)) || !!hit3D(event)});
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready,{once:true});else ready();
})();
