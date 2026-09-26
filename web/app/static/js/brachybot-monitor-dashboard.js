/* Resident projection of Monitor evidence, not another planning state store. */
(() => {
    let cards = [], preferences = {}, overview = null, overviewOwner = '', overviewRevision = '';
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
    function draw() {
        const panel = document.getElementById('monitorDashboard');
        if (!panel) return;
        const phase = trainingMonitorState.phase;
        panel.hidden = !['active', 'starting', 'stopping', 'stop_error'].includes(phase);
        if (panel.hidden) return;
        const summary = panel.querySelector('summary'), body = panel.querySelector('.monitor-dashboard-body');
        const historyOpen = !!body.querySelector('.monitor-history')?.open;
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
        const cardCurrent = card && Number(card.evidence.after_version) === currentVersion
            && String(card.evidence.planning_id) === String(planId) && !dragging;
        const overviewCurrent = overviewOwner === own() && Number(overview?.planning_version) === currentVersion
            && String(overview?.planning_id) === String(planId) && !dragging;
        const metrics = cardCurrent ? (card.evidence.dose?.after || {})
            : (overviewCurrent ? overview.metrics : {}) || {};
        const metricGrid = el('div', undefined, 'monitor-metrics');
        for (const [key, label, unit] of [['v100','V100','%'], ['d90','D90','Gy'], ['v200','V200','%']]) {
            const cell = el('div'); cell.append(el('span', label));
            cell.append(el('strong', Number.isFinite(metrics[key]) ? `${metrics[key].toFixed(2)} ${unit}` : '—'));
            metricGrid.append(cell);
        }
        body.append(metricGrid);
        const organ = overviewCurrent ? overview?.highest_recorded_oar : null;
        if (organ) body.append(el('p', t('已记录 OAR 中最高 Dmax：', 'Highest recorded OAR Dmax: ')
            + `${organ.organ} · ${organ.dmax.toFixed(2)} Gy`));
        if (!Object.keys(metrics).length) body.append(el('p', dragging
            ? t('正在拖动预览；保存后再核对剂量。', 'Drag preview in progress; assess dose after saving.')
            : t('当前几何尚无已核实的剂量指标。', 'No verified dose metrics for the current geometry.')));
        const workflow = el('div', undefined, 'monitor-workflow');
        const names = {ct:'CT',ctv:'CTV',oar:'OAR',geometry:t('针/粒子', 'Needles/seeds'),dose:t('剂量', 'Dose'), quality_check:t('质检', 'QA'),
            surgical_guide:t('导板', 'Guide'),report:t('报告', 'Report')};
        const states = {available:t('已有数据', 'Available'), stale:t('待更新', 'Stale'),
            running:t('运行中', 'Running'),failed:t('失败', 'Failed'),unknown:t('未核实', 'Unverified')};
        for (const stage of overviewCurrent ? overview?.stages || [] : []) {
            const badge = el('span', `${names[stage.key] || stage.key}: ${states[stage.state] || states.unknown}`);
            badge.dataset.state = stage.state; workflow.append(badge);
        }
        body.append(workflow);
        if (workflow.childNodes.length) body.append(el('small', t('数据可用不代表临床通过。', 'Data availability is not clinical approval.')));
        const controls = el('div', undefined, 'monitor-dashboard-actions');
        const toggleLabel = el('label'), toggle = el('input'); toggle.type = 'checkbox';
        toggle.checked = preferences.autoCompare === true; toggle.disabled = phase !== 'active';
        toggle.addEventListener('change', () => window.setMonitorAutoCompare(toggle.checked));
        toggleLabel.append(toggle, document.createTextNode(t(' 自动重算并比较（合并连续编辑）', ' Auto compare (coalesces edits)')));
        controls.append(toggleLabel, button(t('结束监测', 'Finish Monitor'), () => stopTrainingMode(), phase === 'starting' || phase === 'stopping'));
        body.append(controls);
        if (!card) body.append(el('p', t('保存一次编辑后，这里会显示变化、间距检查和下一步。', 'Save an edit to see its changes, spacing checks and next step here.')));
        if (card) {
            const info = card.data.interaction || {};
            const finding = el('div', undefined, 'monitor-finding'); finding.dataset.severity = info.severity || (info.priority === 'attention' ? 'warning' : 'info');
            if (!cardCurrent) finding.append(el('p', t('以下是较早版本的记录，不能作为当前规划结论。', 'Earlier revision record, not a conclusion about the current plan.')));
            finding.append(el('strong', info.headline || ''), el('p', info.next_step || ''), el('small', info.dose_note || ''));
            for (const pair of info.conflicts || []) {
                const value = pair.surface_clearance_mm ?? pair.distance_mm;
                finding.append(el('p', `${pair.first_id} ↔ ${pair.second_id} · ${Number(value).toFixed(2)} mm`));
            }
            if (card.busy || card.notice) finding.append(el('p', card.busy || card.notice));
            if (info.metric_rows?.length) {
                const comparison = el('details');
                comparison.append(el('summary', t('查看各指标与器官差值', 'Metric and organ-dose changes')));
                for (const row of info.metric_rows) comparison.append(el('p', `${row.metric}: ${Number(row.before).toFixed(2)} → ${Number(row.after).toFixed(2)} (${row.delta >= 0 ? '+' : ''}${Number(row.delta).toFixed(2)} ${row.unit})`));
                finding.append(comparison);
            }
            body.append(finding);
            const actions = el('div', undefined, 'monitor-dashboard-actions');
            const act = (label, action) => actions.append(button(label,
                () => window.runMonitorCheckpointAction(card.id, action), phase !== 'active' || !!card.busy || !cardCurrent));
            act(t('定位对象', 'Locate objects'), 'focus');
            actions.append(button(t('清除定位', 'Clear focus'), () => window.clearMonitorFocus(true)));
            if (!info.dose_current) act(t('立即重算比较', 'Compare now'), 'dose');
            if (card.evidence.restore_token && !card.decision) {
                act(t('恢复编辑前位置', 'Restore pre-edit position'), 'restore');
                act(t('保留编辑', 'Keep edit'), 'keep');
            }
            actions.append(button(t('查看证据与记录', 'View evidence and history'), () => {
                [...document.querySelectorAll('[data-message-id]')].find(node => node.dataset.messageId === card.messageId)
                    ?.scrollIntoView({block:'center', behavior:'smooth'});
            }));
            actions.append(button(adviceBusy ? t('正在解释…', 'Explaining…') : t('解释这些变化', 'Explain these changes'), async () => {
                // Explicitly requested, grounded read query; never automatic per drag.
                if (adviceBusy) return;
                adviceBusy = true; draw();
                try {
                    await requestPlanningAdvice({question:t('请结合最新已提交的监测编辑证据，简要解释几何间距与剂量差值的取舍；没有对应证据的因果、临床限值和最优移动方向不要推测。',
                        'Briefly explain the geometry and dose trade-offs in the latest committed monitor edit evidence. Do not infer causes, clinical limits or optimal movements without evidence.')});
                } finally { adviceBusy = false; draw(); }
            }, phase !== 'active' || adviceBusy));
            body.append(actions);
        }
        const history = el('details', undefined, 'monitor-history');
        history.open = historyOpen;
        history.append(el('summary', t(`本页保留 ${list.length} 次编辑 · 查看趋势`, `${list.length} retained edits · trends`)));
        history.append(el('small', t('每行对应一次已核实重算；跨多次编辑的差值不归因于单次拖动。', 'Each row represents a verified recomputation; multi-edit deltas are not attributed to one drag.')));
        for (const item of list.slice(-8)) {
            const info = item.data.interaction || {};
            const values = info.dose_comparable ? (info.metric_rows || []).filter(row => ['V100','v100','D90','d90'].includes(row.metric)) : [];
            history.append(el('p', `${new Date(item.createdAt).toLocaleTimeString()} · ${values.length
                ? values.map(row => `${row.metric} ${row.before.toFixed(2)} → ${row.after.toFixed(2)} (${row.delta >= 0 ? '+' : ''}${row.delta.toFixed(2)} ${row.unit})`).join(' | ')
                : info.dose_note || ''}`));
        }
        body.append(history);
    }
    async function refreshOverview() {
        if (trainingMonitorState.phase !== 'active' || typeof fetch !== 'function') return;
        const ownership = own(), sid = _activeApiSessionId(), sequence = ++requestSequence;
        overviewAbort?.abort(); const abort = new AbortController(); overviewAbort = abort;
        const timeout = setTimeout(() => abort.abort(), 5000);
        try {
            const response = await fetch(`${API}/training/status?overview=1`, {signal:abort.signal,
                headers:{'X-BrachyBot-Session':sid}});
            const data = await response.json();
            if (response.ok && data.success && sequence === requestSequence && ownership === own()
                && data.monitor_run_id === trainingMonitorState.runId && data.active) {
                overview = data.overview; overviewOwner = ownership; draw();
            }
        } catch (_) { /* The HUD says unverified instead of blocking edits. */ }
        finally { clearTimeout(timeout); }
    }
    function scheduleOverview() {
        if (overviewTimer) clearTimeout(overviewTimer);
        overviewTimer = setTimeout(() => { overviewTimer = null; void refreshOverview(); }, 250);
    }
    window.monitorDashboardEvent = event => {
        if (/^(planning|segmentation)\.step$|^manual\.dose$|^surgical_guide\./.test(event?.type || '')) scheduleOverview();
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
        if (phase === 'inactive') { overview = null; overviewOwner = ''; }
        draw();
    };
    window.clearMonitorFocus = (restore = false) => {
        if (restore) focusRestore?.();
        focusRestore = null;
        if (focusLayer) {
            focusLayer.parent?.remove(focusLayer);
            focusLayer.traverse(node => { node.geometry?.dispose(); node.material?.dispose(); });
            focusLayer = null;
            scene3D.requestRender?.(2);
        }
    };
    window.focusMonitorCheckpoint = (refs, evidence) => {
        if (typeof scene3D === 'undefined' || !scene3D.scene || manualPlanningState.monitorInteractionActive
            || trainingMonitorState.screenshotPendingRunId || window.__reportCaptureActive) return false;
        const matched = Object.entries(scene3D.meshes || {}).filter(([id, mesh]) =>
            _screenshot3DIdentityFor(id, mesh).some(ref => refs.includes(ref)) && _screenshot3DVisibility(id, mesh).locatable);
        if (!refs.length || !refs.every(ref => matched.some(([id, mesh]) =>
            _screenshot3DIdentityFor(id, mesh).includes(ref)))) return false;
        window.clearMonitorFocus();
        const restore = window.focusPlanningObjectsForScreenshot(refs, {editEvidence:evidence});
        if (!restore || restore.focusResult?.status !== 'resolved') { restore?.(); return false; }
        focusRestore = restore;
        focusLayer = new THREE.Group(); focusLayer.name = 'monitor-focus';
        for (const [, mesh] of matched) {
            const box = new THREE.Box3().setFromObject(mesh);
            const outline = new THREE.Box3Helper(box, 0xffb347);
            outline.userData.monitorAnnotation = true;
            focusLayer.add(outline);
        }
        // An outline locates a known object, not a measured collision point.
        // Never change mesh materials, visibility or clinical geometry.
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
