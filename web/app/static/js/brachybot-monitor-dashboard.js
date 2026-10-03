/* Resident projection of Monitor evidence, not another planning state store. */
(() => {
    let cards = [], preferences = {}, overview = null, overviewOwner = '', overviewRevision = '';
    let timeline = null, timelineOwner = '';
    let requestSequence = 0, overviewAbort = null, overviewTimer = null, focusLayer = null, focusRestore = null;
    let stopRecovery = null;
    let adviceBusy = false;
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
    const button = (label, action, disabled = false) => {
        const node = el('button', label, 'btn btn-sm'); node.type = 'button'; node.disabled = disabled;
        node.addEventListener('click', action); return node;
    };
    function showEvidence(card) {
        const message = [...document.querySelectorAll('[data-message-id]')].find(node => node.dataset.messageId === card.messageId);
        if (!message) return false;
        message.scrollIntoView({block:'center', behavior:'smooth'});
        window.markMonitorEvidenceViewed?.(card.id); return true;
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
        if (panel.hidden) return;
        const summary = panel.querySelector('summary'), body = panel.querySelector('.monitor-dashboard-body');
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
        const currentVersion = typeof manualPlanningState === 'undefined' ? null : Number(manualPlanningState.planningVersion);
        const planId = typeof manualPlanningState === 'undefined' ? null : manualPlanningState.planningId;
        const dragging = typeof manualPlanningState !== 'undefined' && manualPlanningState.monitorInteractionActive;
        const cardRevisionMatches = card && Number(card.evidence.after_version) === currentVersion
            && String(card.evidence.planning_id) === String(planId);
        const geometryMatches = !cardRevisionMatches || typeof _monitorEvidenceMatchesLiveGeometry !== 'function'
            || _monitorEvidenceMatchesLiveGeometry(card.evidence);
        const cardCurrent = cardRevisionMatches && !dragging && geometryMatches;
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
        const toggleLabel = el('label'), toggle = el('input'); toggle.type = 'checkbox';
        toggle.checked = preferences.autoCompare === true; toggle.disabled = phase !== 'active';
        toggle.addEventListener('change', () => window.setMonitorAutoCompare(toggle.checked));
        toggleLabel.append(toggle, document.createTextNode(t(' 自动重算并比较（合并连续编辑）', ' Auto compare (coalesces edits)')));
        controls.append(toggleLabel, button(t('结束监测', 'Finish Monitor'), () => stopTrainingMode(), phase === 'starting' || phase === 'stopping'));
        body.append(controls);
        const unread = list.filter(item => ['ready','partial'].includes(item.captureState) && item.viewedCaptureEventId !== item.lastEventId);
        const pendingImages = list.filter(item => !item.superseded && ['pending','deferred'].includes(item.captureState));
        const decisions = list.filter(item => !item.superseded && !item.decision && item.evidence.restore_token
            && Number(item.evidence.after_version) === currentVersion && String(item.evidence.planning_id) === String(planId));
        const pending = el('div',undefined,'monitor-pending');
        pending.append(el('span',t(`${decisions.length} 项编辑待选择 · ${pendingImages.length} 项截图准备中`,`${decisions.length} edit decisions · ${pendingImages.length} captures preparing`)));
        if (unread.length) pending.append(button(t(`${unread.length} 项图像证据未查看`,`${unread.length} unseen image records`), () => showEvidence(unread[0])));
        body.append(pending);
        if (!card) body.append(el('p', t('保存一次编辑后，这里会显示变化、间距检查和下一步。', 'Save an edit to see its changes, spacing checks and next step here.')));
        if (card) {
            const info = card.data.interaction || {};
            const finding = el('div', undefined, 'monitor-finding'); finding.dataset.severity = info.severity || (info.priority === 'attention' ? 'warning' : 'info');
            if (info.severity === 'blocking') finding.append(el('strong',t('需先处理：物理几何重叠','Resolve first: physical geometry overlap')));
            if (!cardCurrent) finding.append(el('p', t('以下是较早版本的记录，不能作为当前规划结论。', 'Earlier revision record, not a conclusion about the current plan.')));
            const headline = el('p',undefined,'monitor-headline'); headline.append(el('strong',info.headline || ''));
            finding.append(headline, el('p', info.next_step || ''), el('small', info.dose_note || ''));
            for (const pair of info.conflicts || []) {
                const row = el('p');
                for (const [i,ref] of [pair.first_id,pair.second_id].entries()) {
                    if (i) row.append(document.createTextNode(' ↔ '));
                    row.append(button(ref, () => window.runMonitorCheckpointAction(card.id,'focus',{refs:[ref]}), !cardCurrent || phase !== 'active'));
                }
                row.append(document.createTextNode(` · ${window.monitorConflictText(pair, lang())} `));
                row.append(button(t('查看间距','Show spacing'), () => window.runMonitorCheckpointAction(card.id,'focus',{refs:[pair.first_id,pair.second_id]}), !cardCurrent || phase !== 'active'));
                finding.append(row);
            }
            for (const obj of info.objects || []) if (obj.operation !== 'deleted') finding.append(button(obj.id,
                () => window.runMonitorCheckpointAction(card.id,'focus',{refs:[obj.id]}), !cardCurrent || phase !== 'active'));
            if (card.busy || card.notice) finding.append(el('p', card.busy || card.notice));
            if (card.decision) finding.append(el('p', card.decision, 'monitor-decision'));
            const counts = info.conflict_counts || {};
            if (counts.resolved || counts.existing) finding.append(el('small', t(
                `已消除 ${counts.resolved || 0} 组；另有 ${counts.existing || 0} 组编辑前已存在。`,
                `${counts.resolved || 0} resolved; ${counts.existing || 0} pre-existing conflicts.`)));
            if (info.metric_rows?.length) {
                const comparison = el('details');
                comparison.append(el('summary', t('查看各指标与器官差值', 'Metric and organ-dose changes')));
                for (const row of info.metric_rows) comparison.append(el('p', `${row.metric}: ${Number(row.before).toFixed(2)} → ${Number(row.after).toFixed(2)} (${row.delta >= 0 ? '+' : ''}${Number(row.delta).toFixed(2)} ${row.unit})`));
                finding.append(comparison);
            }
            body.append(finding);
            const capture = el('div', undefined, 'monitor-capture-status');
            capture.dataset.state = card.captureState;
            const captureLabels = {pending:t('截图正在准备，文字反馈已保存。', 'Images are preparing; text feedback is saved.'),
                deferred:t('截图已暂缓；页面可见且版本仍有效时重试。', 'Capture deferred; retries require a visible page and a current revision.'),
                ready:t('已交付图像证据。', 'Image evidence delivered.'),
                partial:t('部分图像已交付；未核验对象不能据图定位。', 'Partial images delivered; unverified objects cannot be located from them.'),
                failed:t('未交付本检查点图像；文字反馈仍有效。', 'No images delivered for this checkpoint; recorded text is retained.'),
                none:t('本次没有需要定位的存续对象，不安排定位截图。', 'No surviving target requires location capture for this edit.')};
            capture.append(el('p',captureLabels[card.captureState] || ''));
            if (card.omittedRefs?.length && card.captureState === 'partial') capture.append(el('small',t('未核验：','Unverified: ') + card.omittedRefs.join(', ')));
            const reasons = {monitor_targets_unavailable:t('Viewer 对象尚未就绪或不可见。','Viewer targets are not ready or visible.'),
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
            const act = (label, action) => actions.append(button(label,
                () => window.runMonitorCheckpointAction(card.id, action), phase !== 'active' || !!card.busy || !cardCurrent));
            if ((info.spatial_refs || card.data.suggested_screenshot?.object_ids || []).length)
                act(t('定位对象', 'Locate objects'), 'focus');
            actions.append(button(t('清除定位', 'Clear focus'), () => window.clearMonitorFocus(true)));
            if (!info.dose_current) act(t('立即重算比较', 'Compare now'), 'dose');
            if (['failed','deferred','partial'].includes(card.captureState) && card.data.suggested_screenshot
                && !['monitor_checkpoint_superseded','monitor_stopped'].includes(card.captureError))
                act(t('重试截图', 'Retry image'), 'capture');
            if (card.evidence.restore_token && !card.decision) {
                act(t('恢复编辑前位置', 'Restore pre-edit position'), 'restore');
                act(t('保留编辑', 'Keep edit'), 'keep');
            }
            actions.append(button(t('查看证据与记录', 'View evidence and history'), () => showEvidence(card)));
            actions.append(button(adviceBusy ? t('正在解释…', 'Explaining…') : t('解释这些变化', 'Explain these changes'), async () => {
                // Explicitly requested, grounded read query; never automatic per drag.
                if (adviceBusy) return;
                adviceBusy = true; draw();
                try {
                    await requestPlanningAdvice({question:t('请结合最新已提交的监测编辑证据，简要解释几何间距与剂量差值的取舍；没有对应证据的因果、临床限值和最优移动方向不要推测。',
                        'Briefly explain the geometry and dose trade-offs in the latest committed monitor edit evidence. Do not infer causes, clinical limits or optimal movements without evidence.')});
                } finally { adviceBusy = false; draw(); }
            }, phase !== 'active' || adviceBusy || !cardCurrent));
            body.append(actions);
        }
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
    };
    window.focusMonitorCheckpoint = (refs, evidence) => {
        if (typeof scene3D === 'undefined' || !scene3D.scene || manualPlanningState.monitorInteractionActive
            || trainingMonitorState.screenshotPendingRunId || window.__reportCaptureActive) return false;
        if (String(evidence?.planning_id) !== String(manualPlanningState.planningId)
            || Number(evidence?.after_version) !== Number(manualPlanningState.planningVersion)
            || (evidence.geometry_key && typeof _monitorEvidenceMatchesLiveGeometry === 'function'
                && !_monitorEvidenceMatchesLiveGeometry(evidence))) return false;
        const matched = Object.entries(scene3D.meshes || {}).filter(([id, mesh]) =>
            _screenshot3DIdentityFor(id, mesh).some(ref => refs.includes(ref)) && _screenshot3DVisibility(id, mesh).locatable);
        if (!refs.length || !refs.every(ref => matched.some(([id, mesh]) =>
            _screenshot3DIdentityFor(id, mesh).includes(ref)))) return false;
        window.clearMonitorFocus(true);
        const restore = window.focusPlanningObjectsForScreenshot(refs, {editEvidence:evidence});
        if (!restore || restore.focusResult?.status !== 'resolved') { restore?.(); return false; }
        focusRestore = restore;
        focusLayer = new THREE.Group(); focusLayer.name = 'monitor-focus';
        const overlap = (evidence.conflicts || []).some(pair => pair.change !== 'existing'
            && pair.physical_overlap === true);
        const color = overlap ? 0xff687a : 0xffb347;
        for (const [, mesh] of matched) {
            const box = new THREE.Box3().setFromObject(mesh);
            const outline = new THREE.Box3Helper(box, color);
            outline.userData.monitorAnnotation = true;
            focusLayer.add(outline);
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
        }
        scene3D.scene.add(focusLayer); scene3D.requestRender?.(3);
        return true;
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
        if (identity === visibleIdentity) return;
        visibleIdentity = identity;
        window.clearMonitorFocus();
        if (!manualPlanningState.monitorInteractionActive) scheduleOverview();
        draw();
    }, 1000);
})();
