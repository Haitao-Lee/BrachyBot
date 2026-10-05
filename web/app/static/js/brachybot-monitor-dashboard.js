/* Resident projection of Monitor evidence, not another planning state store. */
(() => {
    let cards = [], preferences = {}, overview = null, overviewOwner = '', overviewRevision = '';
    let timeline = null, timelineOwner = '';
    let requestSequence = 0, overviewAbort = null, overviewTimer = null, focusLayer = null, focusRestore = null;
    let stopRecovery = null;
    let adviceBusy = false;
    let spatialState = null, spatialLabels = [], drawnSignature = '';
    const lang = () => monitorConversationLanguage(_activeApiSessionId());
    const t = (zh, en) => lang() === 'zh' ? zh : en;
    const el = (tag, value, className) => {
        const node = document.createElement(tag);
        if (value !== undefined) node.textContent = value;
        if (className) node.className = className;
        return node;
    };
    const own = () => `${_activeApiSessionId()}:${trainingMonitorState.runId || ''}`;
    const planIdentity = () => `${own()}:${manualPlanningState.planningId}:${manualPlanningState.planningVersion}:${!!manualPlanningState.monitorInteractionActive}`;
    const ownedCards = () => cards.filter(card => card.sessionId === _activeApiSessionId()
        && card.runId === trainingMonitorState.runId);
    const latest = () => ownedCards().filter(card => !card.superseded).at(-1);
    const button = (label, action, disabled = false, control = '') => {
        const node = el('button', label, 'btn btn-sm'); node.type = 'button'; node.disabled = disabled;
        node.dataset.brachyControlRef = `monitor:${trainingMonitorState.runId || ''}:${latest()?.id || ''}:${control || label}`;
        node.addEventListener('click', action); return node;
    };
    function showEvidence(card) {
        const message = [...document.querySelectorAll('[data-message-id]')].find(node => node.dataset.messageId === card.messageId);
        if (!message) return false;
        message.scrollIntoView({block:'center', behavior:'smooth'});
        window.markMonitorEvidenceViewed?.(card.id); return true;
    }
    window.openMonitorGuidance = id => {
        const card=latest(),panel=document.getElementById('monitorDashboard');
        if(!panel || panel.hidden || !card || card.id!==id)return false;
        panel.open=true;
        const body=panel.querySelector('.monitor-dashboard-body');body.scrollTop=0;
        const heading=body.querySelector('.monitor-guidance-title');
        heading?.focus?.({preventScroll:true});
        return true;
    };
    function viewerCoach(card,current) {
        // Keep guidance beside the image, outside the canvas. No popup, no
        // camera takeover and no extra words burned into captured pixels.
        const viewer=document.getElementById('viewer3d');
        if(!viewer)return;
        let rail=viewer.querySelector('.monitor-viewer-guide');
        if(!rail){rail=el('section',undefined,'monitor-viewer-guide');
            rail.setAttribute('data-html2canvas-ignore','true');
            rail.setAttribute('aria-label',t('当前编辑建议','Current edit guidance'));
            viewer.insertBefore(rail,viewer.querySelector('.viewer-card-ctrl'));}
        const info=window.monitorInteractionFor?.(card?.data.interaction,lang());
        const guide=window.monitorGuidanceFor?.(info,lang());
        rail.hidden=!current || trainingMonitorState.phase!=='active' || !guide;
        if(rail.hidden){rail.replaceChildren();return;}
        const restore=window.preserveMonitorPresentation?.(rail) || (()=>{});
        rail.dataset.monitorOwner=`${own()}:${card.id}`;
        rail.dataset.severity=info.severity || 'info';
        rail.setAttribute('aria-label',t('当前编辑建议','Current edit guidance'));
        rail.setAttribute('aria-busy',String(!!(card.busy || card.previewBusy)));
        const panel=window.createMonitorGuidancePanel(info,lang(),false,{evidence:card.evidence});
        const text=el('div',undefined,'monitor-viewer-copy');
        text.append(el('small',t('本次编辑','This edit')),el('strong',card.previewGeometry
            ? t('位置预览 · 尚未修改规划','Position preview · plan unchanged') : panel.querySelector('.monitor-guidance-title').textContent));
        const status=card.busy || (card.previewBusy?t('正在核对几何…','Checking geometry…'):card.notice || card.decision);
        text.append(el('span',status || (card.previewGeometry ? t('确认后仍需安全检查和剂量重算。','Confirmation still requires safety checks and dose recomputation.')
            : panel.querySelector('.monitor-guide-meaning p')?.textContent) || ''));
        const commands=el('div',undefined,'monitor-viewer-actions');
        const preview=card.previewGeometry && (card.previewCandidate || card.evidence.restore_token && !card.decision);
        const step=preview ? {action:card.previewCandidate?'apply':'restore',label:card.previewCandidate
            ? t('确认候选位置','Confirm candidate') : t('确认恢复原位置','Confirm restoration')}
            : guide.steps?.find(step=>step.action===info.primary_action);
        if(step && ['focus','dose','details','preview','spacing','apply','restore'].includes(step.action)){
            const control=button(step.label,()=>window.runMonitorCheckpointAction(card.id,step.action,
                {refs:step.refs,objectId:step.object_id,candidateId:card.previewCandidate?.candidate_id,surface:'viewer'}),
                !!card.busy || !!card.previewBusy || !!window.__reportCaptureActive,'viewer-primary');
            control.classList.add('monitor-primary-action');commands.append(control);
        }
        commands.append(button(t('详细建议','Guidance'),()=>window.openMonitorGuidance(card.id),false,'viewer-guidance'));
        rail.replaceChildren(text,commands);restore();
    }
    function sparkline(samples, key) {
        const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
        svg.setAttribute('viewBox', '0 0 240 64'); svg.classList.add('monitor-sparkline');
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', `${key}: ${samples.map(item => item.after[key]).join(' → ')}`);
        const values = samples.flatMap(item => [item.before?.[key], item.after[key]]).filter(Number.isFinite);
        const min = Math.min(...values), span = Math.max(...values) - min || 1;
        const y = value => 57 - (value - min) / span * 50;
        let prior = null;
        samples.forEach((item, index) => {
            const x = 12 + index * 210 / Math.max(1, samples.length - 1);
            if (prior && prior.series_key && prior.series_key === item.series_key) {
                const line = document.createElementNS(NS, 'line');
                for (const [attr, value] of Object.entries({x1:prior.x,y1:y(prior.after[key]),x2:x,y2:y(item.after[key])})) line.setAttribute(attr, value);
                svg.append(line);
            } else if (item.comparable && Number.isFinite(item.before?.[key])) {
                const line = document.createElementNS(NS, 'line');
                for (const [attr,value] of Object.entries({x1:x - 9,y1:y(item.before[key]),x2:x,y2:y(item.after[key])})) line.setAttribute(attr,value);
                svg.append(line);
            }
            const dot = document.createElementNS(NS, 'circle'); dot.setAttribute('cx', x); dot.setAttribute('cy', y(item.after[key])); dot.setAttribute('r', 3);
            const title = document.createElementNS(NS, 'title'); title.textContent = `${key}: ${item.after[key].toFixed(2)}`; dot.append(title); svg.append(dot);
            prior = {...item, x};
        });
        return svg;
    }
    function eventText(event) {
        const labels = {'manual.seed.drag':t('粒子编辑','Seed edit'),'manual.needle.drag':t('针道编辑','Needle edit'),
            'manual.seed.add':t('添加粒子','Add seed'),'manual.seed.delete':t('删除粒子','Delete seed'),
            'manual.needle.add':t('添加针道','Add needle'),'manual.needle.delete':t('删除针道','Delete needle'),
            'manual.dose':t('剂量重算','Dose recomputation'),'planning.step':t('规划步骤','Planning step'),
            'segmentation.step':t('分割步骤','Segmentation step'),'training.start':t('监测启动','Monitor started'),
            'training.stop':t('监测结束','Monitor finished')};
        const steps = {ctv:'CTV',oar:'OAR',trajectory_init:t('轨迹初始化','Trajectory initialization'),
            trajectory_refine:t('轨迹细化','Trajectory refinement'),seed_planning:t('粒子布源','Seed placement'),
            dose_calc:t('剂量计算','Dose calculation'),dose_eval:t('剂量评估','Dose evaluation'),full:t('全流程','Full workflow')};
        const statuses = {running:t('进行中','Running'),completed:t('已完成','Completed'),failed:t('失败','Failed')};
        return [labels[event.type] || (/^surgical_guide\./.test(event.type) ? t('导板更新','Guide update') : t('界面操作','UI action')),
            steps[event.step],statuses[event.status]].filter(Boolean).join(' · ');
    }
    function draw() {
        const panel = document.getElementById('monitorDashboard');
        if (!panel) return;
        const phase = trainingMonitorState.phase;
        panel.hidden = !['active', 'starting', 'stopping', 'stop_error'].includes(phase);
        if (panel.hidden) {viewerCoach(null,false);return;}
        const summary = panel.querySelector('summary'), body = panel.querySelector('.monitor-dashboard-body');
        const signature=JSON.stringify([own(),lang(),phase,!!stopRecovery,preferences.autoCompare===true,adviceBusy,
            planIdentity(),ownedCards().map(card=>[card.lastEventId,card.superseded,card.data.interaction,
                card.captureState,card.captureError,card.omittedRefs,card.viewedCaptureEventId,card.busy,card.notice,
                card.decision,card.detailsOpen,card.previewCandidates,card.previewCandidate,card.previewBusy]),
            overviewOwner,overview,timelineOwner,timeline,window.getMonitorSpatialState?.(latest()?.evidence),
            latest() ? window.getMonitorTargetAvailability?.(latest().data.interaction?.spatial_refs || [],latest().evidence) : null,
            typeof _monitorEvidenceMatchesLiveGeometry==='function' && latest() ? _monitorEvidenceMatchesLiveGeometry(latest().evidence) : null]);
        if(signature===drawnSignature)return;
        drawnSignature=signature;
        const restorePresentation=window.preserveMonitorPresentation?.(body) || (()=>{});
        const scrollTop = body.scrollTop;
        const historyOpen = !!body.querySelector('.monitor-history')?.open;
        const timelineOpen = !!body.querySelector('.monitor-timeline')?.open, oarsOpen = !!body.querySelector('.monitor-oars')?.open;
        summary.textContent = t('监测工作台', 'Monitor workspace') + ' · ' + ({
            active:t('监测中', 'Active'), starting:t('启动中', 'Starting'),
            stopping:t('正在结束', 'Finishing'), stop_error:stopRecovery
                ? t('正在重新核实结束状态', 'Rechecking stop status') : t('结束尚未确认', 'Stop unconfirmed'),
        })[phase];
        body.replaceChildren();
        const card = latest(), list = ownedCards();
        body.dataset.monitorOwner=`${own()}:${card?.id || ''}`;
        const currentVersion = typeof manualPlanningState === 'undefined' ? null : Number(manualPlanningState.planningVersion);
        const planId = typeof manualPlanningState === 'undefined' ? null : manualPlanningState.planningId;
        const dragging = typeof manualPlanningState !== 'undefined' && manualPlanningState.monitorInteractionActive;
        const cardRevisionMatches = card && Number(card.evidence.after_version) === currentVersion
            && String(card.evidence.planning_id) === String(planId);
        const geometryMatches = !cardRevisionMatches || typeof _monitorEvidenceMatchesLiveGeometry !== 'function'
            || _monitorEvidenceMatchesLiveGeometry(card.evidence);
        const cardCurrent = cardRevisionMatches && !dragging && geometryMatches;
        viewerCoach(card,cardCurrent);
        const overviewCurrent = overviewOwner === own() && Number(overview?.planning_version) === currentVersion
            && String(overview?.planning_id) === String(planId) && !dragging && geometryMatches;
        const metrics = cardCurrent && Object.keys(card.evidence.dose?.after || {}).length ? card.evidence.dose.after
            : (overviewCurrent ? overview.metrics : {}) || {};
        const metricGrid = el('div', undefined, 'monitor-metrics');
        for (const [key, label, unit] of [['v100','V100','%'], ['d90','D90','Gy'], ['v200','V200','%'], ['plan_score',t('评分','Score'),'/100']]) {
            const cell = el('div'); cell.append(el('span', label));
            cell.append(el('strong', Number.isFinite(metrics[key]) ? `${metrics[key].toFixed(2)} ${unit}` : '—'));
            const delta = cardCurrent && card.evidence.dose?.comparable ? card.evidence.dose.delta?.[key] : null;
            if (Number.isFinite(delta)) cell.append(el('small', `${delta > 0 ? '↑ +' : delta < 0 ? '↓ ' : '→ '}${delta.toFixed(2)} ${key.startsWith('v') ? t('百分点','pp') : key === 'plan_score' ? t('分','points') : 'Gy'}`));
            if (key === 'v100' && Number.isFinite(metrics[key])) {
                const meter = el('meter'); meter.min = 0; meter.max = 100; meter.value = metrics[key]; meter.setAttribute('aria-label', 'V100'); cell.append(meter);
            }
            metricGrid.append(cell);
        }
        body.append(metricGrid);
        const organs = overviewCurrent ? overview?.recorded_oars || (overview?.highest_recorded_oar ? [overview.highest_recorded_oar] : []) : [];
        if (organs.length) {
            const oars = el('details',undefined,'monitor-oars'); oars.open = oarsOpen; oars.append(el('summary',t('已记录器官 Dmax（最高受量项）','Recorded OAR Dmax (highest values)')));
            for (const organ of organs) oars.append(el('p', `${organ.organ} · ${organ.dmax.toFixed(2)} Gy`));
            body.append(oars);
        }
        const target = overviewCurrent ? overview.coverage_target_percent : null;
        if (Number.isFinite(target) && Number.isFinite(metrics.v100)) body.append(el('p',t(
            `配置的覆盖目标 ${target.toFixed(1)}%；尚差 ${Math.max(0,target - metrics.v100).toFixed(2)} 个百分点（不是临床通过标准）。`,
            `Configured coverage target ${target.toFixed(1)}%; remaining ${Math.max(0,target - metrics.v100).toFixed(2)} pp (not a clinical acceptance threshold).`)));
        if (!Object.keys(metrics).length) body.append(el('p', dragging
            ? t('正在拖动预览；保存后再核对剂量。', 'Drag preview in progress; assess dose after saving.')
            : t('当前几何尚无已核实的剂量指标。', 'No verified dose metrics for the current geometry.')));
        const workflow = el('ol', undefined, 'monitor-workflow');
        const names = {ct:'CT',ctv:'CTV',oar:'OAR',geometry:t('针/粒子', 'Needles/seeds'),dose:t('剂量', 'Dose'), quality_check:t('质检', 'QA'),
            surgical_guide:t('导板', 'Guide'),report:t('报告', 'Report')};
        const states = {available:t('已有数据', 'Available'), stale:t('待更新', 'Stale'),
            running:t('运行中', 'Running'),failed:t('失败', 'Failed'),unknown:t('未核实', 'Unverified')};
        const stages = overviewCurrent ? overview?.stages || [] : [];
        const currentStage = stages.find(stage => stage.state === 'running') || stages.find(stage => ['failed','stale','unknown'].includes(stage.state));
        const tips = {ct:t('先加载并核对 CT。','Load and verify CT first.'),ctv:t('核对或完成靶区分割。','Verify or complete target segmentation.'),
            oar:t('核对相关器官分割。','Verify relevant organ segmentation.'),geometry:t('核对针道和粒子几何。','Verify needle and seed geometry.'),
            dose:t('重算剂量后比较覆盖、热点和器官受量。','Recompute dose, then compare coverage, hot spots and organ dose.'),
            quality_check:t('复核当前版本的几何与剂量质检。','Review geometry and dose QA for this revision.'),
            surgical_guide:t('按最终针道更新导板并复核制造性。','Update the guide from final needles and review manufacturability.'),
            report:t('用当前结果更新报告并复核。','Update and review the report from current results.')};
        for (const stage of stages) {
            const badge = el('li'); badge.dataset.state = stage.state;
            if (stage === currentStage) badge.setAttribute('aria-current','step');
            badge.append(el('span', stage.state === 'available' ? '✓' : stage === currentStage ? '→' : '·'),
                el('span', `${names[stage.key] || stage.key}: ${states[stage.state] || states.unknown}`));
            badge.title = tips[stage.key] || ''; workflow.append(badge);
        }
        body.append(workflow);
        if (currentStage) body.append(el('p', t('下一步优先核对：','Next review: ') + tips[currentStage.key]));
        if (workflow.childNodes.length) body.append(el('small', t('数据可用不代表临床通过。', 'Data availability is not clinical approval.')));
        const controls = el('div', undefined, 'monitor-dashboard-actions');
        controls.classList.add('monitor-session-controls');
        const toggleLabel = el('label'), toggle = el('input'); toggle.type = 'checkbox';
        toggle.checked = preferences.autoCompare === true; toggle.disabled = phase !== 'active';
        toggle.dataset.brachyControlRef=`monitor:${trainingMonitorState.runId}:auto-compare`;
        toggle.addEventListener('change', () => window.setMonitorAutoCompare(toggle.checked));
        toggleLabel.append(toggle, document.createTextNode(t(' 自动重算并比较（合并连续编辑）', ' Auto compare (coalesces edits)')));
        controls.append(button(phase==='stop_error' ? t('重试结束监测','Retry Finish Monitor') : t('结束监测', 'Finish Monitor'),
            () => stopTrainingMode(), phase === 'starting' || phase === 'stopping','finish'));
        const statusDetails=el('details',undefined,'monitor-plan-details');statusDetails.dataset.monitorSection='plan-details';
        statusDetails.open=!window.monitorGuidanceFor?.(card?.data.interaction,lang());
        const statusSummary=el('summary',t('剂量、流程状态与监测设置','Dose, workflow and monitor settings'));
        statusSummary.dataset.brachyControlRef=`monitor:${trainingMonitorState.runId}:plan-details`;
        statusDetails.append(statusSummary);
        for(const child of [...body.childNodes]) statusDetails.append(child);
        statusDetails.append(toggleLabel,el('small',t('自动重算默认关闭。开启后才会合并连续编辑并计算剂量。','Auto compare is off by default. Enabling it coalesces edits before calculating dose.')));
        body.append(controls);
        if(phase!=='active')body.append(el('p',phase==='stop_error'
            ? t('结束请求尚未得到服务器确认。这里保留记录，但不再执行编辑建议；可重试结束。','The server has not confirmed the stop. Records remain, edit guidance is disabled; retry Finish Monitor.')
            : t('正在核对监测状态；不会自动修改规划。','Checking monitor state; the plan will not be changed automatically.'),'monitor-session-state'));
        const unread = list.filter(item => ['ready','partial'].includes(item.captureState) && item.viewedCaptureEventId !== item.lastEventId);
        const pendingImages = list.filter(item => !item.superseded && ['pending','deferred'].includes(item.captureState));
        const decisions = list.filter(item => !item.superseded && !item.decision && item.evidence.restore_token
            && item.data.interaction?.decision_required !== false
            && Number(item.evidence.after_version) === currentVersion && String(item.evidence.planning_id) === String(planId));
        const pending = el('div',undefined,'monitor-pending');
        if(decisions.length || pendingImages.length) pending.append(el('span',t(`${decisions.length} 项编辑待选择 · ${pendingImages.length} 项截图准备中`,`${decisions.length} edit decisions · ${pendingImages.length} captures preparing`)));
        if (unread.length) pending.append(button(t(`${unread.length} 项图像证据未查看`,`${unread.length} unseen image records`), () => showEvidence(unread[0])));
        body.append(pending);
        if (!card) body.append(el('p', t('照常拖动并保存针道或粒子。我会标出刚编辑的对象，先反馈几何问题；剂量需要你确认重算，不会偷偷计算。',
            'Drag and save a needle or seed as usual. I will mark the edited object and check geometry first; dose calculation needs your choice, never hidden work.'),'monitor-onboarding'));
        if (card) {
            const info = window.monitorInteractionFor?.(card.data.interaction,lang()) || card.data.interaction || {};
            const finding = el('div', undefined, 'monitor-finding'); finding.dataset.severity = info.severity || (info.priority === 'attention' ? 'warning' : 'info');
            if (info.severity === 'blocking' && !window.monitorGuidanceFor?.(info,lang()))
                finding.append(el('strong',t('需先处理：物理几何重叠','Resolve first: physical geometry overlap')));
            if (!cardCurrent) finding.append(el('p', t('以下是较早版本的记录，不能作为当前规划结论。', 'Earlier revision record, not a conclusion about the current plan.')));
            const headline = el('p',undefined,'monitor-headline'); headline.setAttribute('role','status');
            headline.append(el('strong',info.assessment?.title || info.headline || ''));
            const guide = window.monitorGuidanceFor?.(info,lang());
            const guidancePanel = window.createMonitorGuidancePanel?.(info,lang(),!cardCurrent,
                {id:card.id,runId:card.runId,evidence:card.evidence,surface:'dashboard',preview:!!card.previewGeometry,
                    canConfirmPreview:!!card.previewCandidate || !!card.evidence.restore_token && !card.decision,
                    candidateId:card.previewCandidate?.candidate_id,current:cardCurrent && phase === 'active',busy:card.busy || card.previewBusy});
            if (guidancePanel) finding.append(guidancePanel);
            else finding.append(headline, el('p', cardCurrent ? info.next_step || '' : ''), el('small', info.dose_note || ''));
            const record=el('details',undefined,'monitor-object-record');record.dataset.monitorSection='object-record';
            record.open=!guidancePanel;
            record.append(el('summary',t('对象编号、检查过程与详细差值','Object IDs, checks and detailed changes')));
            const stages = el('div',undefined,'monitor-edit-stages');
            for (const label of [t('✓ 编辑已保存','✓ Edit saved'), t('✓ 几何已检查','✓ Geometry checked'),
                info.dose_comparable ? t('✓ 剂量可比较','✓ Dose comparable') : info.dose_current
                    ? t('剂量已更新 · 缺前值','Dose current · baseline missing') : t('剂量待更新','Dose pending'),
                ({ready:t('图像已交付','Images delivered'),partial:t('部分图像已交付','Partial images delivered'),
                    pending:t('截图准备中','Images preparing'),deferred:t('截图暂缓','Capture deferred'),
                    failed:t('截图未完成','Capture incomplete'),none:t('本次未安排截图','No image scheduled')})[card.captureState] || t('截图状态未核实','Image status unverified')])
                stages.append(el('span',label));
            record.append(stages);
            for (const pair of info.conflicts || []) {
                const row = el('p');
                for (const [i,ref] of [pair.first_id,pair.second_id].entries()) {
                    if (i) row.append(document.createTextNode(' ↔ '));
                    row.append(button(ref, () => window.runMonitorCheckpointAction(card.id,'focus',{refs:[ref]}), !cardCurrent || phase !== 'active'));
                }
                row.append(document.createTextNode(` · ${window.monitorConflictText(pair, lang())} `));
                row.append(button(t('查看间距','Show spacing'), () => window.runMonitorCheckpointAction(card.id,'focus',{refs:[pair.first_id,pair.second_id]}), !cardCurrent || phase !== 'active'));
                record.append(row);
            }
            for (const obj of info.objects || []) if (obj.operation !== 'deleted') record.append(button(obj.id,
                () => window.runMonitorCheckpointAction(card.id,'focus',{refs:[obj.id]}), !cardCurrent || phase !== 'active'));
            if (card.busy || card.notice) finding.append(el('p', card.busy || card.notice));
            if (card.decision) finding.append(el('p', card.decision, 'monitor-decision'));
            const counts = info.conflict_counts || {};
            if (counts.resolved || counts.existing) record.append(el('small', t(
                `已消除 ${counts.resolved || 0} 组；另有 ${counts.existing || 0} 组编辑前已存在。`,
                `${counts.resolved || 0} resolved; ${counts.existing || 0} pre-existing conflicts.`)));
            if (info.metric_rows?.length) {
                const comparison = el('details');
                comparison.open = !!card.detailsOpen;
                comparison.addEventListener('toggle',()=>{card.detailsOpen=comparison.open;});
                comparison.append(el('summary', t('查看各指标与器官差值', 'Metric and organ-dose changes')));
                for (const row of info.metric_rows) comparison.append(el('p', `${row.metric}: ${Number(row.before).toFixed(2)} → ${Number(row.after).toFixed(2)} (${row.delta >= 0 ? '+' : ''}${Number(row.delta).toFixed(2)} ${row.unit})`));
                record.append(comparison);
            }
            finding.append(record);
            body.append(finding);
            const capture = el('div', undefined, 'monitor-capture-status');
            capture.dataset.state = card.captureState;
            const captureLabels = {pending:t('截图正在准备，文字反馈已保存。', 'Images are preparing; text feedback is saved.'),
                deferred:t('截图已暂缓；页面可见且版本仍有效时重试。', 'Capture deferred; retries require a visible page and a current revision.'),
                ready:t('已交付图像证据。', 'Image evidence delivered.'),
                partial:t('部分图像已交付；未核验对象不能据图定位。', 'Partial images delivered; unverified objects cannot be located from them.'),
                failed:t('未交付本检查点图像；文字反馈仍有效。', 'No images delivered for this checkpoint; recorded text is retained.'),
                none:t('本次未安排定位截图；不代表对象不存在。', 'No location image scheduled; this does not establish missing objects.')};
            capture.append(el('p',captureLabels[card.captureState] || ''));
            if (card.omittedRefs?.length && card.captureState === 'partial') capture.append(el('small',t('未核验：','Unverified: ') + card.omittedRefs.join(', ')));
            const reasons = {monitor_interaction_busy:t('正在操作 Viewer；空闲后再捕获，不抢占操作。','Viewer interaction active; capture resumes when idle.'),
                monitor_targets_unavailable:t('Viewer 对象尚未就绪或不可见。','Viewer targets are not ready or visible.'),
                viewer_tab_hidden:t('浏览器页面在后台。','The browser page is in the background.'),
                attachment_not_rendered:t('图像未写入对话附件。','Images were not delivered to chat attachments.'),
                workspace_visual_restore_incomplete:t('Viewer 资源仍在恢复。','Viewer resources are still restoring.'),
                target_object_not_loaded_in_live_data_tree:t('目标数据节点尚未加载。','Target data nodes have not loaded.'),
                target_not_verified_visible_in_viewer:t('目标图像位置尚不可核验。','Target image locations are unverified.'),
                monitor_checkpoint_superseded:t('后续编辑已改变几何；旧版本不能补拍。','Later edits changed geometry; old revisions cannot be recaptured.'),
                monitor_stopped:t('监测已经结束。','Monitoring has stopped.')};
            if (card.captureError && ['failed','deferred'].includes(card.captureState)) capture.append(el('small',
                reasons[card.captureError] || t('截图未完成，可在当前资源就绪后重试。','Capture incomplete; retry when current resources are ready.')));
            body.append(capture);
            const actions = el('div', undefined, 'monitor-dashboard-actions');
            const act = (label, action) => {
                if (guidancePanel?.querySelector(`.monitor-guide-actions [data-guide-action="${action}"]`)) return;
                const control = button(guide?.steps?.find(step=>step.action === action)?.label || label, () => window.runMonitorCheckpointAction(card.id, action),
                    phase !== 'active' || !!card.busy || !cardCurrent, action);
                if (action === info.primary_action) control.classList.add('monitor-primary-action');
                actions.append(control);
            };
            if ((info.spatial_refs || card.data.suggested_screenshot?.object_ids || []).length)
                act(t('定位对象', 'Locate objects'), 'focus');
            actions.append(button(t('清除定位', 'Clear focus'), () => window.runMonitorCheckpointAction(card.id,'clear_focus')));
            if (!info.dose_current) act(t('立即重算比较', 'Compare now'), 'dose');
            if (info.primary_action === 'details') act(t('查看本次指标取舍','Review measured trade-offs'),'details');
            if (['failed','deferred','partial'].includes(card.captureState) && card.data.suggested_screenshot
                && !['monitor_checkpoint_superseded','monitor_stopped'].includes(card.captureError))
                act(t('重试截图', 'Retry image'), 'capture');
            if (card.evidence.restore_token && !card.decision) {
                if (info.schema_version === 3) act(t('预览编辑前位置（不修改）','Preview pre-edit position (read only)'), 'preview');
                act(t('恢复编辑前位置', 'Restore pre-edit position'), 'restore');
                act(t('保留编辑', 'Keep edit'), 'keep');
            }
            for (const obj of info.objects || []) if (info.schema_version === 3 && obj.kind === 'seeds' && info.decision_required && obj.operation !== 'deleted'
                && !guide?.steps?.some(step=>step.action === 'spacing' && step.object_id === obj.id))
                actions.append(button(guide?.steps?.find(step=>step.action === 'spacing' && step.object_id === obj.id)?.label || t(`寻找 ${obj.id} 间距候选`,`Find spacing candidates for ${obj.id}`),
                    () => window.runMonitorCheckpointAction(card.id,'spacing',{objectId:obj.id}), !cardCurrent || !!card.previewBusy));
            for (const candidate of card.previewCandidates || []) actions.append(button(
                t(`预览候选 ${candidate.distance_mm.toFixed(2)} mm（未算剂量）`,`Preview candidate ${candidate.distance_mm.toFixed(2)} mm (no dose)`),
                () => window.runMonitorCheckpointAction(card.id,'select_candidate',{candidateId:candidate.candidate_id}), !cardCurrent || !!card.previewBusy));
            if (card.previewCandidate) actions.append(button(t('确认应用几何候选（剂量待重算）','Confirm geometric candidate (dose needs updating)'),
                () => window.runMonitorCheckpointAction(card.id,'apply',{candidateId:card.previewCandidate.candidate_id}), !cardCurrent || !!card.previewBusy));
            if (info.decision_required === false) {
                const more = el('details',undefined,'monitor-secondary-actions');
                more.append(el('summary',t('更多操作（无需每次确认保留）','More actions (no routine keep confirmation required)')));
                more.firstChild.dataset.brachyControlRef = `monitor:${card.runId}:${card.id}:more`;
                const secondary = [...actions.children].filter(node => /恢复编辑前|保留编辑|Restore pre-edit|Keep edit/.test(node.textContent));
                secondary.forEach(node => more.append(node)); actions.append(more);
            }
            actions.append(button(t('查看证据与记录', 'View evidence and history'), () => showEvidence(card)));
            actions.append(button(adviceBusy ? t('正在解释…', 'Explaining…') : t('解释这些变化', 'Explain these changes'), async () => {
                // Explicitly requested, grounded read query; never automatic per drag.
                if (adviceBusy) return;
                adviceBusy = true; draw();
                try {
                    await requestPlanningAdvice({question:t('请依据最新已提交的监测编辑证据，像带我操作一样简短说明：这一步具体改变了什么、实际影响和代价、优先下一步及选择条件、操作后如何验证。区分单次编辑与连续编辑；无有效前值不补造比较。引用当前具体对象和实测值，不重复泛泛检查清单，不推测没有证据的临床限值、因果或最优移动方向。',
                        'Coach me briefly using the latest committed monitor evidence: what this edit changed, measured effects and costs, the first next step and when to choose it, and how to verify afterward. Distinguish single edits from sequences; do not invent missing baselines. Use current object references and measurements, not generic checklists or unsupported clinical limits, causes or optimal movements.')});
                } finally { adviceBusy = false; draw(); }
            }, phase !== 'active' || adviceBusy || !cardCurrent));
            if(guidancePanel){
                const options=el('details',undefined,'monitor-command-options');options.dataset.monitorSection='commands';
                const optionsSummary=el('summary',t('定位、撤销与其他操作','Location, undo and other actions'));
                optionsSummary.dataset.brachyControlRef=`monitor:${card.runId}:${card.id}:commands`;
                options.append(optionsSummary,actions);body.append(options);
                if(card.previewGeometry || card.previewCandidate){
                    const preview=el('div',undefined,'monitor-preview-decision');
                    preview.append(el('p',t('紫色位置是只读预览，规划尚未改变。先看位置，再确认操作。','Purple geometry is a read-only preview; the plan has not changed. Inspect it before confirming.')));
                    if(card.previewCandidate && !guidancePanel.querySelector('[data-guide-action="apply"]'))preview.append(button(t('确认应用几何候选（剂量待重算）','Confirm geometric candidate (dose needs updating)'),
                        ()=>window.runMonitorCheckpointAction(card.id,'apply',{candidateId:card.previewCandidate.candidate_id}),!cardCurrent || !!card.previewBusy,'confirm-preview'));
                    else if(!card.previewCandidate && card.evidence.restore_token && !card.decision && !guidancePanel.querySelector('[data-guide-action="restore"]'))preview.append(button(t('确认恢复编辑前位置','Confirm restore pre-edit position'),
                        ()=>window.runMonitorCheckpointAction(card.id,'restore'),!cardCurrent || !!card.busy,'confirm-restore'));
                    // The live guide already owns confirmation and dismissal.
                    // Preserve alternatives in the disclosure, not a second CTA.
                    options.append(preview);
                }
            }else body.append(actions);
            body.insertBefore(finding,controls.nextSibling);
        }
        body.append(statusDetails);
        const history = el('details', undefined, 'monitor-history');
        history.open = historyOpen;
        history.append(el('summary', t(`本页保留 ${list.length} 次编辑 · 查看趋势`, `${list.length} retained edits · trends`)));
        history.append(el('small', t('每行对应一次已核实重算；跨多次编辑的差值不归因于单次拖动。', 'Each row represents a verified recomputation; multi-edit deltas are not attributed to one drag.')));
        const timelineCurrent = timelineOwner === own();
        const samples = timelineCurrent ? (timeline?.events || []).filter(event => event.dose_sample).map(event => event.dose_sample) : [];
        // Card updates replace their own checkpoint; never count a dose update as another edit.
        const chartSamples = samples.length ? samples : list.filter(item => item.evidence.dose?.after).map(item => item.evidence.dose);
        for (const [key,label] of [['v100','V100'],['d90','D90'],['plan_score',t('评分','Score')]]) {
            const values = chartSamples.filter(item => Number.isFinite(item.after?.[key]));
            if (values.length) { history.append(el('strong',label),sparkline(values,key)); }
        }
        history.append(el('small',t('图线仅连接相同可比基线的已记录重算；数值增加不等于整体改善。','Lines connect recorded recomputations with the same comparison baseline; increases do not imply overall improvement.')));
        for (const item of list.slice(-8)) {
            const info = item.data.interaction || {};
            const values = info.dose_comparable ? (info.metric_rows || []).filter(row => ['V100','v100','D90','d90'].includes(row.metric)) : [];
            history.append(el('p', `${new Date(item.createdAt).toLocaleTimeString()} · ${values.length
                ? values.map(row => `${row.metric} ${row.before.toFixed(2)} → ${row.after.toFixed(2)} (${row.delta >= 0 ? '+' : ''}${row.delta.toFixed(2)} ${row.unit})`).join(' | ')
                : info.dose_note || ''}`));
        }
        body.append(history);
        if (timelineCurrent && timeline) {
            const events = el('details',undefined,'monitor-timeline');
            events.open = timelineOpen;
            const editCount = Object.entries(timeline.event_counts || {}).filter(([key]) => /^manual\.(seed|needle)\.(drag|add|delete|position_only|restore)$/.test(key)).reduce((sum,[,n]) => sum+n,0);
            events.append(el('summary',t(`本轮 ${editCount} 项编辑事件 · 共 ${timeline.event_count} 个事件`,`${editCount} edit events · ${timeline.event_count} total events this run`)));
            for (const event of timeline.events || []) {
                const row = el('p',`${new Date(Number(event.ts)*1000).toLocaleTimeString()} · ${eventText(event)}`);
                row.dataset.severity = event.severity; events.append(row);
            }
            events.append(el('small',t(`显示最近 ${timeline.returned_event_count} 个事件；${timeline.dropped_event_count} 个旧事件已超出保留范围。`,
                `Showing ${timeline.returned_event_count} recent events; ${timeline.dropped_event_count} earlier events exceeded retention.`)));
            body.append(events);
        }
        body.scrollTop = scrollTop;
        restorePresentation();
    }
    async function refreshOverview() {
        if (trainingMonitorState.phase !== 'active' || typeof fetch !== 'function') return;
        const ownership = own(), sid = _activeApiSessionId(), sequence = ++requestSequence;
        overviewAbort?.abort(); const abort = new AbortController(); overviewAbort = abort;
        const timeout = setTimeout(() => abort.abort(), 5000);
        try {
            const read = async url => {
                const response = await fetch(url,{signal:abort.signal,headers:{'X-BrachyBot-Session':sid}});
                if (!response.ok) throw new Error('monitor_overview_unavailable');
                return response.json();
            };
            const results = await Promise.allSettled([read(`${API}/training/status?overview=1`),
                read(`${API}/training/timeline?compact=1&limit=40&monitor_run_id=${encodeURIComponent(trainingMonitorState.runId)}`)]);
            if (sequence !== requestSequence || ownership !== own() || trainingMonitorState.phase !== 'active') return;
            const valid = result => result.status === 'fulfilled' && result.value.success
                && result.value.monitor_run_id === trainingMonitorState.runId && result.value.active;
            if (valid(results[0])) { overview = results[0].value.overview; overviewOwner = ownership; }
            if (valid(results[1])) { timeline = results[1].value; timelineOwner = ownership; }
            draw();
        } catch (_) { /* The HUD says unverified instead of blocking edits. */ }
        finally { clearTimeout(timeout); }
    }
    function scheduleOverview() {
        if (overviewTimer) clearTimeout(overviewTimer);
        overviewTimer = setTimeout(() => { overviewTimer = null; void refreshOverview(); }, 250);
    }
    window.monitorDashboardEvent = event => {
        if (/^(planning|segmentation)\.step$|^manual\.|^surgical_guide\./.test(event?.type || '')) scheduleOverview();
    };
    window.renderMonitorDashboard = (nextCards, nextPreferences) => {
        cards = nextCards; preferences = nextPreferences;
        bindControls();
        if (typeof manualPlanningState !== 'undefined') visibleIdentity = planIdentity();
        const card = latest(), revision = `${own()}:${card?.lastEventId || ''}`;
        if (revision !== overviewRevision) { overviewRevision = revision; scheduleOverview(); }
        draw();
    };
    window.monitorDashboardPhase = phase => {
        if (phase === 'active') scheduleOverview();
        else { overviewAbort?.abort(); ++requestSequence; clearTimeout(overviewTimer); }
        if (phase === 'inactive') { overview = null; overviewOwner = ''; timeline = null; timelineOwner = ''; }
        draw();
    };
    window.clearMonitorFocus = (restore = false) => {
        (document.querySelectorAll?.('.monitor-tree-target') || []).forEach(row=>row.classList.remove('monitor-tree-target'));
        if (restore) focusRestore?.();
        focusRestore = null;
        if (focusLayer) {
            focusLayer.parent?.remove(focusLayer);
            focusLayer.traverse(node => {
                node.geometry?.dispose();
                for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
                    material?.map?.dispose(); material?.dispose();
                }
            });
            focusLayer = null;
            scene3D.requestRender?.(2);
        }
        spatialState=null;spatialLabels=[];
    };
    // Availability is not a location claim. Resolve exact identities in the
    // live scene/tree without hydrating, reconstructing, or changing visibility.
    window.getMonitorTargetAvailability = (refs, evidence) => {
        if (!trainingMonitorState.active || !Array.isArray(refs) || refs.length > 8
            || typeof scene3D === 'undefined'
            || String(evidence?.planning_id) !== String(manualPlanningState.planningId)
            || Number(evidence?.after_version) !== Number(manualPlanningState.planningVersion)
            || manualPlanningState.monitorInteractionActive
            || (typeof _monitorEvidenceMatchesLiveGeometry === 'function' && !_monitorEvidenceMatchesLiveGeometry(evidence))) return [];
        return refs.map(ref => {
            const entries = Object.entries(scene3D.meshes || {}).filter(([id,mesh]) =>
                _screenshot3DIdentityFor(id,mesh).includes(ref));
            const visibility = entries.map(([id,mesh]) => _screenshot3DVisibility(id,mesh));
            const direct = String(ref).replace(/^(?:seed|needle|trajectory):/, '');
            const node = visibility.find(item => item.node)?.node
                || (typeof _findDataTreeNode === 'function' ? _findDataTreeNode(direct) : null);
            if (node?.sessionId && String(node.sessionId) !== String(_activeApiSessionId())
                || node?.planningId && String(node.planningId) !== String(evidence.planning_id))
                return {ref,state:'unavailable'};
            const unavailable = /^(deleted|missing|not_generated|failed|error)$/.test(String(node?.status || ''));
            const loading = node?.loading === true || /^(loading|restoring|persisted_not_loaded|generating)$/.test(String(node?.status || ''));
            let parentHidden = false, parent = typeof _dataTreeParentNode === 'function' ? _dataTreeParentNode(node) : null;
            const seen = new Set();
            while (parent && !seen.has(parent)) {
                seen.add(parent);
                if (parent.visible === false || parent.visible3D === false) parentHidden = true;
                parent = typeof _dataTreeParentNode === 'function' ? _dataTreeParentNode(parent) : null;
            }
            const ownHidden = node?.visible === false || node?.visible3D === false;
            const state = unavailable ? 'unavailable' : loading ? 'loading'
                : visibility.some(item => item.locatable) ? 'visible'
                : ownHidden || parentHidden ? 'hidden' : entries.length ? 'not_renderable' : 'not_loaded';
            return {ref,state,nodeId:node?.id,loaded:entries.length > 0,
                // Never reveal an entire hidden group, change opacity, or
                // reconstruct geometry as a side effect of locating one seed.
                revealable:state === 'hidden' && ownHidden && !parentHidden && entries.length > 0};
        });
    };
    window.locateMonitorDataTreeTarget = (ref, evidence) => {
        const target = window.getMonitorTargetAvailability([ref],evidence)[0];
        if (!target || target.state === 'unavailable'
            || typeof window.resolveDataTreeRowTargetRef !== 'function') return false;
        const row = window.resolveDataTreeRowTargetRef(ref);
        if (!row || row.dataset.liveNode === 'false' || !row.closest('#dataTreeBody')) return false;
        const identities = [row.dataset.nodeId,row.dataset.objectId,row.dataset.item].filter(Boolean);
        if (![target.nodeId,ref,String(ref).replace(/^(?:seed|needle|trajectory):/,'')]
            .filter(Boolean).some(id => identities.includes(id))) return false;
        const tab = document.querySelector('.panel-tab[data-panel="viewers"]');
        if (tab && typeof switchPanel === 'function') switchPanel('viewers',tab);
        for (let group = row.closest('.tree-group'); group; group = group.parentElement?.closest('.tree-group')) {
            if (group.dataset.group && typeof window.setTreeGroupExpansion === 'function')
                window.setTreeGroupExpansion(group.dataset.group,true);
        }
        document.querySelectorAll('.monitor-tree-target').forEach(item => item.classList.remove('monitor-tree-target'));
        row.classList.add('monitor-tree-target');row.tabIndex = -1;
        row.scrollIntoView?.({block:'nearest',behavior:'auto'});row.focus?.({preventScroll:true});
        return true;
    };
    window.reconcileMonitorSpatialVisibility = () => {
        if(!focusLayer || !spatialState || trainingMonitorState.screenshotPendingRunId
            || window.__reportCaptureActive || window.isWorkspacePresentationWriteLocked?.(_activeApiSessionId()))return;
        const valid=spatialState.refs.every(ref=>Object.entries(scene3D.meshes || {}).some(([id,mesh])=>
            _screenshot3DIdentityFor(id,mesh).includes(ref) && _screenshot3DVisibility(id,mesh).locatable));
        if(!valid)window.clearMonitorFocus();
    };
    window.getMonitorSpatialState = evidence => {
        if(!spatialState || !focusLayer || focusLayer.visible===false || spatialState.owner!==own()
            || !trainingMonitorState.active || manualPlanningState.monitorInteractionActive
            || String(evidence?.planning_id)!==String(spatialState.planningId)
            || Number(evidence?.after_version)!==Number(spatialState.version)
            || (evidence?.geometry_key && evidence.geometry_key!==spatialState.geometryKey)
            || String(manualPlanningState.planningId)!==String(spatialState.planningId)
            || Number(manualPlanningState.planningVersion)!==Number(spatialState.version)
            || (typeof _monitorEvidenceMatchesLiveGeometry==='function' && !_monitorEvidenceMatchesLiveGeometry(evidence)))return null;
        const visible=spatialState.refs.filter(ref=>Object.entries(scene3D.meshes || {}).some(([id,mesh])=>
            _screenshot3DIdentityFor(id,mesh).includes(ref) && _screenshot3DVisibility(id,mesh).locatable));
        if(!visible.length || visible.length!==spatialState.refs.length)return null;
        const inFrame=visible.filter(ref=>{
            const item=spatialLabels.find(label=>label.sprite.userData.objectRef===ref);
            if(!item)return false;
            const point=item.anchor.clone().project(scene3D.camera);
            return [point.x,point.y,point.z].every(Number.isFinite) && Math.abs(point.x)<=1 && Math.abs(point.y)<=1 && Math.abs(point.z)<=1;
        });
        return {status:inFrame.length ? 'located' : 'offscreen',refs:inFrame,letters:spatialState.letters,canRestore:!!focusRestore};
    };
    window.suspendMonitorSpatialAnnotations = () => {
        const layer=focusLayer,ownership=own(),wasVisible=layer?.visible;
        if(!layer)return null;
        layer.visible=false;scene3D.requestRender?.(1);
        return () => {
            if(layer!==focusLayer || ownership!==own())return;
            layer.visible=wasVisible;placeSpatialLabels();scene3D.requestRender?.(2);
        };
    };
    function placeSpatialLabels(){
        if(!spatialLabels.length || !scene3D.camera)return;
        const camera=scene3D.camera,size=scene3D.renderer?.getSize?.(new THREE.Vector2());
        const height=size?.y || 600,width=Math.min(224,(size?.x || 600)*.65);
        const canvasWidth=size?.x || 600,occupied=[];
        const right=new THREE.Vector3(1,0,0).applyQuaternion(camera.quaternion),up=new THREE.Vector3(0,1,0).applyQuaternion(camera.quaternion);
        for(const [index,item] of spatialLabels.entries()){
            const visibleHeight=camera.isOrthographicCamera ? (camera.top-camera.bottom)/camera.zoom
                : 2*item.anchor.distanceTo(camera.position)*Math.tan(THREE.MathUtils.degToRad(camera.fov/2));
            const unit=visibleHeight/height,labelWidth=item.isMeasurement ? Math.min(360,(size?.x || 600)*.85) : width;
            const labelHeight=(item.isMeasurement ? labelWidth/8 : 28)*unit;
            item.sprite.scale.set(labelWidth*unit,labelHeight,1);
            // Stagger labels without moving their patient-space anchors. Lines
            // explicitly connect each label to the verified object, not a box
            // midpoint mistaken for a collision witness.
            item.sprite.position.copy(item.anchor).addScaledVector(up,(item.isMeasurement ? -46 : 34+index*36)*unit)
                .addScaledVector(right,(index%2 ? 1 : -1)*Math.min(45,width/5)*unit);
            const projected=item.sprite.position.clone().project(camera);
            if([projected.x,projected.y,projected.z].every(Number.isFinite) && Math.abs(projected.z)<=1){
                const marginX=Math.min(.9,labelWidth/(size?.x || 600)+.04),marginY=(item.isMeasurement ? labelWidth/8+4 : 34)/height;
                projected.x=Math.max(-1+marginX,Math.min(1-marginX,projected.x));
                projected.y=Math.max(-1+marginY,Math.min(1-marginY,projected.y));
                const pixelHeight=item.isMeasurement ? labelWidth/8 : 30;
                const originalX=(projected.x+1)*canvasWidth/2,originalY=(1-projected.y)*height/2;
                let chosen=null;
                // At most three object badges and a few measurements. Try a
                // bounded set of screen-space lanes, preserving the leaders'
                // fixed patient anchors; stacked labels must not hide letters.
                for(const shift of [0,-36,36,-72,72,-108,108,-144,144]){
                    const candidate={x:originalX,y:Math.max(pixelHeight/2+4,Math.min(height-pixelHeight/2-4,originalY+shift)),w:labelWidth,h:pixelHeight};
                    if(!occupied.some(box=>Math.abs(candidate.x-box.x)<(candidate.w+box.w)/2+6
                        && Math.abs(candidate.y-box.y)<(candidate.h+box.h)/2+6)){chosen=candidate;break;}
                }
                if(chosen){projected.x=chosen.x/canvasWidth*2-1;projected.y=1-chosen.y/height*2;occupied.push(chosen);}
                else occupied.push({x:originalX,y:originalY,w:labelWidth,h:pixelHeight});
                item.sprite.position.copy(projected.unproject(camera));
            }
            item.line.geometry.setFromPoints([item.anchor,item.sprite.position]);
        }
    }
    window.focusMonitorCheckpoint = (refs, evidence, options = {}) => {
        if (typeof scene3D === 'undefined' || !scene3D.scene || manualPlanningState.monitorInteractionActive
            || trainingMonitorState.screenshotPendingRunId || window.__reportCaptureActive) return false;
        if (!trainingMonitorState.active || !Array.isArray(refs) || refs.length>8
            || String(evidence?.planning_id) !== String(manualPlanningState.planningId)
            || Number(evidence?.after_version) !== Number(manualPlanningState.planningVersion)
            || (evidence.geometry_key && typeof _monitorEvidenceMatchesLiveGeometry === 'function'
                && !_monitorEvidenceMatchesLiveGeometry(evidence))) return false;
        const matched = Object.entries(scene3D.meshes || {}).filter(([id, mesh]) =>
            _screenshot3DIdentityFor(id, mesh).some(ref => refs.includes(ref)) && _screenshot3DVisibility(id, mesh).locatable);
        if (!refs.length || !refs.every(ref => matched.some(([id, mesh]) =>
            _screenshot3DIdentityFor(id, mesh).includes(ref)))) return false;
        window.clearMonitorFocus(options.reframe !== false);
        if (options.reframe !== false) {
            const restore = window.focusPlanningObjectsForScreenshot(refs, {editEvidence:evidence});
            if (!restore || restore.focusResult?.status !== 'resolved') { restore?.(); return false; }
            focusRestore = restore;
        }
        focusLayer = new THREE.Group(); focusLayer.name = 'monitor-focus';
        const overlap = (evidence.conflicts || []).some(pair => pair.change !== 'existing'
            && pair.physical_overlap === true);
        const color = overlap ? 0xff687a : 0xffb347;
        const colors=[0x62c9ff,0xffc56b,0xea9cff];
        const ownedLabels=window.monitorSpatialGuide?.(latest()?.data.interaction,evidence,lang()) || [];
        const labels=(options.labels || (ownedLabels.length ? ownedLabels : refs.slice(0,3).map((ref,index)=>({ref,letter:String.fromCharCode(65+index),label:t('定位对象','Located object')}))))
            .filter(item=>refs.includes(item.ref)).slice(0,3);
        for (const [id, mesh] of matched) {
            const box = new THREE.Box3().setFromObject(mesh);
            const refsForMesh=_screenshot3DIdentityFor(id,mesh);
            const identity=labels.find(item=>refsForMesh.includes(item.ref));
            const accent=identity ? colors['ABC'.indexOf(identity.letter)] || colors[0] : color;
            const outline = new THREE.Box3Helper(box, accent);
            outline.material.depthTest=false;outline.renderOrder=1000;
            outline.userData.monitorAnnotation = true;
            focusLayer.add(outline);
            // Draw a separate geometric edge overlay, not a recolored mesh.
            // Bound work even if a ref unexpectedly resolves to a large mesh.
            let edgeCount=0;mesh.traverse(child=>{
                if(edgeCount>=4 || !child.isMesh || !child.geometry?.attributes?.position
                    || child.geometry.attributes.position.count>5000)return;
                const edge=new THREE.LineSegments(new THREE.EdgesGeometry(child.geometry,12),
                    new THREE.LineBasicMaterial({color:accent,depthTest:false}));
                edge.matrixAutoUpdate=false;edge.matrix.copy(child.matrixWorld);edge.renderOrder=1001;
                edge.userData={monitorAnnotation:true,objectRef:identity?.ref,purpose:'object_outline_not_mesh_change'};
                focusLayer.add(edge);edgeCount++;
            });
        }
        for(const item of labels){
            const match=matched.find(([id,mesh])=>_screenshot3DIdentityFor(id,mesh).includes(item.ref));
            if(!match)continue;
            const box=new THREE.Box3().setFromObject(match[1]),anchor=box.getCenter(new THREE.Vector3());
            const change=(evidence.changed_objects || []).find(obj=>String(obj.id)===item.ref
                && !obj.dependent_on_needle && !obj.derived_from_normalization);
            const valid=point=>Array.isArray(point) && point.length===3 && point.every(Number.isFinite);
            const points=change?.kind==='needles' && Array.isArray(change.after) ? change.after : [change?.after];
            const previous=change?.kind==='needles' && Array.isArray(change.before) ? change.before : [change?.before];
            const moved=points.map((point,index)=>({point,prior:previous[index]})).filter(pair=>valid(pair.point) && valid(pair.prior))
                .sort((a,b)=>new THREE.Vector3(...b.point).distanceTo(new THREE.Vector3(...b.prior))-new THREE.Vector3(...a.point).distanceTo(new THREE.Vector3(...a.prior)));
            if(moved.length)anchor.set(...moved[0].point);
            else if(valid(points[0]))anchor.set(...points[0]);
            const accent=colors['ABC'.indexOf(item.letter)] || colors[0];
            const canvas=document.createElement('canvas');canvas.width=480;canvas.height=60;
            const ctx=canvas.getContext('2d');if(!ctx)continue;
            ctx.fillStyle='#111b2b';ctx.fillRect(0,0,480,60);ctx.strokeStyle=`#${accent.toString(16).padStart(6,'0')}`;ctx.lineWidth=3;ctx.strokeRect(2,2,476,56);
            ctx.fillStyle='#ffffff';ctx.font='bold 26px sans-serif';ctx.textBaseline='middle';
            const label=`${item.letter} · ${item.label}`;ctx.fillText(label,14,30,450);
            const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(canvas),depthTest:false}));
            sprite.renderOrder=1002;sprite.userData={monitorAnnotation:true,label,objectRef:item.ref,letter:item.letter,locationAnchor:anchor.toArray()};
            const line=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:accent,depthTest:false}));
            line.renderOrder=1001;line.userData.monitorAnnotation=true;focusLayer.add(sprite,line);spatialLabels.push({sprite,line,anchor,canvas,accent});
            // Actual moved endpoint/seed trace. This arrow records the past
            // movement (before -> after), never recommends a future direction.
            for(const pair of moved.slice(0,2)){
                const before=new THREE.Vector3(...pair.prior),after=new THREE.Vector3(...pair.point),vector=after.clone().sub(before);
                if(vector.length()<.01)continue;
                const arrow=new THREE.ArrowHelper(vector.clone().normalize(),before,vector.length(),accent,
                    Math.min(vector.length()*.22,1.5),Math.min(vector.length()*.12,.8));
                arrow.traverse(node=>{if(node.material){node.material.depthTest=false;node.renderOrder=1001;}});
                arrow.userData={monitorAnnotation:true,purpose:'recorded_move_not_recommendation',objectRef:item.ref};focusLayer.add(arrow);
            }
        }
        // These points come from the very same finite-segment spacing check.
        // An endpoint witness may only provide a conservative axis-model bound.
        for (const pair of evidence.conflicts || []) {
            if (!refs.includes(pair.first_id) || !refs.includes(pair.second_id)) continue;
            const measurement = pair.measurement, points = measurement?.points;
            if (measurement?.coordinate_system !== 'patient_world_mm' || !Array.isArray(points) || points.length !== 2
                || !points.every(point => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite))) continue;
            const [a,b] = points.map(point => new THREE.Vector3(...point));
            if (!Number.isFinite(measurement.value_mm) || Math.abs(a.distanceTo(b) - measurement.value_mm) > .01) continue;
            const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a,b]),new THREE.LineBasicMaterial({color,depthTest:false}));
            line.userData.monitorAnnotation = true; line.userData.measurement = measurement; focusLayer.add(line);
            const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 80;
            const ctx = canvas.getContext('2d'); if (!ctx) continue;
            const exactSurface = measurement.clearance_basis === 'finite_parallel_cylinders';
            const label = Number.isFinite(measurement.surface_clearance_mm)
                ? t(`轴线 ${measurement.value_mm.toFixed(2)} mm · ${exactSurface ? '实体表面间隙' : '轴线模型间隙下界'} ${measurement.surface_clearance_mm.toFixed(2)} mm`,
                    `Axis ${measurement.value_mm.toFixed(2)} mm · ${exactSurface ? 'finite surface gap' : 'axis-model clearance bound'} ${measurement.surface_clearance_mm.toFixed(2)} mm`)
                : t(`针道最短轴线距离 ${measurement.value_mm.toFixed(2)} mm`,`Needle-axis distance ${measurement.value_mm.toFixed(2)} mm`);
            ctx.fillStyle = '#172030'; ctx.fillRect(0,0,640,80); ctx.fillStyle = '#ffffff'; ctx.font = '24px sans-serif';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(label,320,40,620);
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(canvas),depthTest:false}));
            sprite.position.copy(a).add(b).multiplyScalar(.5);
            // Keep the label readable in both whole-body and millimetre close-up
            // views; a fixed 24-mm sprite would engulf a pair of seeds.
            const camera = scene3D.camera, size = scene3D.renderer?.getSize?.(new THREE.Vector2());
            const height = size?.y || 600, width = Math.min(320, (size?.x || 600) * .65);
            const visibleHeight = camera.isOrthographicCamera
                ? (camera.top - camera.bottom) / camera.zoom
                : 2 * sprite.position.distanceTo(camera.position) * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
            const labelHeight = visibleHeight * (width / 8) / height;
            sprite.scale.set(labelHeight * 8, labelHeight, 1);
            sprite.position.addScaledVector(camera.up.clone().normalize(), labelHeight * 1.5);
            sprite.userData.monitorAnnotation = true; sprite.userData.label = label; focusLayer.add(sprite);
            const leader=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color,depthTest:false}));
            leader.userData.monitorAnnotation=true;focusLayer.add(leader);
            spatialLabels.push({sprite,line:leader,anchor:a.clone().add(b).multiplyScalar(.5),isMeasurement:true,canvas,measurement,exactSurface});
        }
        spatialState={owner:own(),planningId:evidence.planning_id,version:evidence.after_version,geometryKey:evidence.geometry_key,
            refs:labels.map(item=>item.ref),letters:labels.map(item=>item.letter)};
        placeSpatialLabels();scene3D.scene.add(focusLayer); scene3D.requestRender?.(3);
        return true;
    };
    window.previewMonitorGeometry = (geometry, evidence) => {
        const items = [...(geometry?.seeds || []), ...(geometry?.needles || [])];
        const refs = items.map(item=>String(item.id));
        if (!refs.length || items.length > 32 || !window.focusMonitorCheckpoint(refs,evidence,{reframe:false})) return false;
        const valid = point => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite);
        for (const item of items) {
            const points = item.points || [item.position];
            if (!points.length || !points.every(valid)) { window.clearMonitorFocus(); return false; }
            const geometry = new THREE.BufferGeometry().setFromPoints(points.map(point=>new THREE.Vector3(...point)));
            const material = new THREE.LineDashedMaterial({color:0xb38aff,dashSize:1,gapSize:.6,depthTest:false});
            const line = new THREE.Line(geometry,material); line.computeLineDistances();
            line.userData.monitorAnnotation = true; line.userData.readOnlyPreview = true; focusLayer.add(line);
            // A point marker is a location reference, not a fabricated seed mesh.
            for (const point of points) {
                const marker = new THREE.Mesh(new THREE.SphereGeometry(.45,8,6),new THREE.MeshBasicMaterial({color:0xb38aff,wireframe:true,depthTest:false}));
                marker.position.set(...point); marker.userData.monitorAnnotation = true; focusLayer.add(marker);
            }
            const change = (evidence.changed_objects || []).find(change=>String(change.id) === String(item.id));
            const currentPoints=change?.kind === 'seeds' ? [change.after] : change?.after || [];
            for(const [index,point] of points.entries())if (valid(currentPoints[index]) && valid(point)) {
                const start = new THREE.Vector3(...currentPoints[index]), end = new THREE.Vector3(...point), vector = end.clone().sub(start);
                if (vector.length() > .01) {
                    const arrow = new THREE.ArrowHelper(vector.clone().normalize(),start,vector.length(),0xb38aff,
                        Math.min(vector.length()*.25,1.5),Math.min(vector.length()*.15,.8));
                    arrow.traverse(node=>{if(node.material){node.material.depthTest=false;node.renderOrder=1001;}});
                    arrow.userData.monitorAnnotation = true; arrow.userData.readOnlyPreview = true;
                    arrow.userData.purpose='preview_destination_not_optimized';arrow.userData.objectRef=item.id;arrow.userData.endpoint=index+1;
                    focusLayer.add(arrow);
                }
            }
        }
        scene3D.requestRender?.(3); return true;
    };
    window.addEventListener?.('i18nchange', () => {
        // Repaint text textures in place: no camera restore/reframe, preview
        // dismissal, geometry mutation, network request or new screenshot.
        const labels=window.monitorSpatialGuide?.(latest()?.data.interaction,latest()?.evidence,lang()) || [];
        for(const item of spatialLabels){
            const ctx=item.canvas?.getContext('2d');if(!ctx)continue;
            let label;
            if(item.isMeasurement){
                const m=item.measurement,exact=item.exactSurface;
                label=Number.isFinite(m.surface_clearance_mm)
                    ? t(`轴线 ${m.value_mm.toFixed(2)} mm · ${exact?'实体表面间隙':'轴线模型间隙下界'} ${m.surface_clearance_mm.toFixed(2)} mm`,
                        `Axis ${m.value_mm.toFixed(2)} mm · ${exact?'finite surface gap':'axis-model clearance bound'} ${m.surface_clearance_mm.toFixed(2)} mm`)
                    : t(`针道最短轴线距离 ${m.value_mm.toFixed(2)} mm`,`Needle-axis distance ${m.value_mm.toFixed(2)} mm`);
                ctx.fillStyle='#172030';ctx.fillRect(0,0,640,80);ctx.fillStyle='#ffffff';ctx.font='24px sans-serif';
                ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(label,320,40,620);
            }else{
                const identity=labels.find(row=>row.ref===item.sprite.userData.objectRef);if(!identity)continue;
                label=`${identity.letter} · ${identity.label}`;
                ctx.fillStyle='#111b2b';ctx.fillRect(0,0,480,60);ctx.strokeStyle=`#${item.accent.toString(16).padStart(6,'0')}`;
                ctx.lineWidth=3;ctx.strokeRect(2,2,476,56);ctx.fillStyle='#ffffff';ctx.font='bold 26px sans-serif';
                ctx.textAlign='left';ctx.textBaseline='middle';ctx.fillText(label,14,30,450);
            }
            item.sprite.userData.label=label;item.sprite.material.map.needsUpdate=true;
        }
        if(focusLayer)scene3D.requestRender?.(1);
        draw();
    });
    // An explicit focus may offer camera restoration. Once the user moves
    // the camera, clearing an annotation must not restore that older pose.
    let observedControls = null;
    const bindControls = () => {
        if (typeof scene3D === 'undefined' || !scene3D.controls?.addEventListener || observedControls === scene3D.controls) return;
        observedControls = scene3D.controls;
        const controls = observedControls;
        controls.addEventListener('start', () => {
            if (!trainingMonitorState.active || typeof scene3D === 'undefined' || scene3D.controls !== controls) return;
            focusRestore = null; window.__monitorCameraInteracting = true;
            manualPlanningState.monitorInteractionEpoch = Number(manualPlanningState.monitorInteractionEpoch || 0)+1;
        });
        controls.addEventListener('end', () => {
            if (typeof scene3D === 'undefined' || scene3D.controls !== controls) return;
            window.__monitorCameraInteracting = false; window.resumeMonitorInteraction?.();
            window.refreshMonitorSpatialPresentation?.();draw();
        });
        controls.addEventListener('change',()=>{
            if(scene3D.controls!==controls || !focusLayer)return;
            placeSpatialLabels();scene3D.requestRender?.(1);
        });
    };
    window.queueMonitorStopRecovery = (sessionId, runId) => {
        const key = `${sessionId}:${runId}`;
        if (stopRecovery?.key === key) return true;
        const job = {key, attempt:0}; stopRecovery = job;
        const retry = async () => {
            if (stopRecovery !== job || own() !== key || trainingMonitorState.phase !== 'stop_error') {
                if (stopRecovery === job) stopRecovery = null;
                return;
            }
            job.attempt++;
            const result = await stopTrainingMode();
            if (result?.success || result?.run_mismatch || own() !== key || job.attempt >= 2) {
                if (stopRecovery === job) stopRecovery = null; draw(); return;
            }
            setTimeout(retry, 4000);
        };
        setTimeout(retry, 2000); draw(); return true;
    };
    // Plan selection can change without a Monitor edit event. Observe only a
    // compact identity tuple; never poll geometry or call the model here.
    let visibleIdentity = '';
    if (typeof setInterval === 'function') setInterval(() => {
        if (document.hidden || trainingMonitorState.phase !== 'active') return;
        const identity = planIdentity();
        bindControls();
        if (identity === visibleIdentity) return;
        visibleIdentity = identity;
        window.clearMonitorFocus();
        if (!manualPlanningState.monitorInteractionActive) scheduleOverview();
        draw();
    }, 1000);
})();
