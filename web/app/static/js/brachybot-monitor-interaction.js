/* One edit, one evolving card. Only server-committed evidence enters here. */
(() => {
    const cards = new Map();
    let owner = '';
    let autoCompare = false, compareTimer = null;
    const timers = new Map();
    const cancelRetry = card => {
        if (timers.has(card.id)) clearTimeout(timers.get(card.id));
        timers.delete(card.id);
    };
    const publish = () => window.renderMonitorDashboard?.([...cards.values()], {autoCompare});
    const text = (card, zh, en) => card.language === 'zh' ? zh : en;
    const safe = value => String(value ?? '').replace(/[\\`*_{}\[\]<>|]/g, ' ');
    const current = card => typeof trainingMonitorState !== 'undefined'
        && trainingMonitorState.active && trainingMonitorState.runId === card.runId
        && _activeApiSessionId() === card.sessionId;
    const latest = card => current(card) && !card.superseded
        && (typeof manualPlanningState === 'undefined'
            || (!manualPlanningState.monitorInteractionActive
                && Number(manualPlanningState.planningVersion) === Number(card.evidence.after_version)
                && String(manualPlanningState.planningId) === String(card.evidence.planning_id)))
        && (typeof _monitorEvidenceMatchesLiveGeometry !== 'function'
            || _monitorEvidenceMatchesLiveGeometry(card.evidence));
    const errorText = (card, code) => {
        if (code === 'monitor_stopped') return text(card,
            '监测已停止，本检查点未完成截图；已记录的文字结果仍保留。',
            'Monitoring stopped before this image completed; recorded text is retained.');
        if (code === 'monitor_checkpoint_superseded') return text(card,
            '后续编辑已改变几何，旧检查点不再补拍；请查看最新编辑卡片。',
            'A newer edit changed the geometry; use the latest card for images.');
        if (code === 'viewer_tab_hidden') return text(card,
            '页面在后台，截图已暂缓；返回页面后会自动核对版本并补拍。',
            'Capture deferred in the background; returning will recheck the revision before retrying.');
        return text(card, '本次截图尚未完成；可以重试，以下文字仍是已保存的编辑结果。',
            'Image not captured yet. Retry below; the text still describes the saved edit.');
    };

    function render(card) {
        if (card.sessionId !== _activeApiSessionId() || card.runId !== trainingMonitorState.runId) return;
        const info = card.data.interaction;
        const lines = [text(card, '**这次编辑的反馈**', '**Feedback on this edit**')];
        if (card.superseded) lines.push(text(card, '此卡片记录较早的编辑；操作入口已关闭。',
            'This card records an earlier edit; its actions are no longer available.'));
        if (info) {
            lines.push(info.headline);
            for (const obj of info.objects || []) {
                const verb = obj.operation === 'moved'
                    ? text(card, `移动 ${Number(obj.distance_mm).toFixed(2)} mm`, `moved ${Number(obj.distance_mm).toFixed(2)} mm`)
                    : text(card, ({added:'新增', deleted:'删除', reoriented:'方向或归属改变'})[obj.operation] || obj.operation, obj.operation);
                lines.push(`- **${safe(obj.id)}**：${verb}`);
            }
            for (const pair of info.conflicts || []) {
                const value = pair.surface_clearance_mm ?? pair.distance_mm;
                lines.push(`- ${safe(pair.first_id)} ↔ ${safe(pair.second_id)}：${text(card,
                    pair.kind === 'seed_pairs' ? '表面间隙' : '针道距离',
                    pair.kind === 'seed_pairs' ? 'surface clearance' : 'needle distance')} ${Number(value).toFixed(2)} mm`);
            }
            lines.push(`**${text(card, '剂量对比', 'Dose comparison')}**`, info.dose_note);
            if (info.metric_rows?.length) {
                lines.push(text(card, '| 指标 | 编辑前 | 编辑后 | 差值 |', '| Metric | Before | After | Change |'),
                    '|---|---:|---:|---:|');
                for (const row of info.metric_rows) lines.push(`| ${safe(row.metric)} | ${Number(row.before).toFixed(2)} | ${Number(row.after).toFixed(2)} | ${row.delta >= 0 ? '+' : ''}${Number(row.delta).toFixed(2)} ${safe(row.unit)} |`);
            }
            lines.push(`**${text(card, '下一步', 'Next step')}**`, info.next_step);
        } else lines.push(card.data.feedback_localized || card.data.feedback || '');
        if (card.busy) lines.push(card.busy);
        if (card.notice) lines.push(card.notice);
        if (card.decision) lines.push(card.decision);
        const captureText = card.captureState === 'ready' ? text(card,
            '已核验的图像附在本卡片下方。若图中有紫色箭头，它表示返回编辑前位置的方向，不表示计算得到的最优位置。',
            'Verified images are attached below. Purple arrows, when present, indicate the pre-edit position, not an optimized destination.')
            : ['failed', 'deferred'].includes(card.captureState) ? errorText(card, card.captureError)
                : card.data.suggested_screenshot ? text(card, '正在准备本次编辑的定位截图…', 'Preparing location images for this edit…') : '';
        if (captureText) lines.push(captureText);
        addChat('bot-response', lines.join('\n\n').replace(/\|\n\n\|/g, '|\n|'), false,
            card.createdAt, false, card.sessionId, {requestId: card.requestId,
                messageId: card.messageId, messageKind:'monitor_feedback', responseLanguage: card.language});
        attachActions(card);
        publish();
    }

    async function capture(card) {
        if (!latest(card) || card.captureState === 'pending') return;
        cancelRetry(card);
        card.captureState = 'pending'; render(card);
        await reportUIEvent(card.data.event?.type || 'manual.edit', '', {}, {cachedCheckpoint: card.data});
    }

    function retryCapture(card) {
        cancelRetry(card);
        if (!latest(card) || ['monitor_checkpoint_superseded', 'monitor_stopped'].includes(card.captureError)) return;
        // Hidden pages wait for visibility, not a timer loop. Permanent
        // grounding failures retain text; transient failures have two retries.
        if (document.hidden) { card.captureState = 'deferred'; return; }
        if (!['viewer_tab_hidden', 'capture_failed', 'workspace_visual_restore_incomplete',
            'attachment_not_rendered', 'monitor_targets_unavailable'].includes(card.captureError)) return;
        if ((card.retryCount || 0) >= 2 || typeof setTimeout !== 'function') return;
        const revision = card.lastEventId;
        card.retryCount = (card.retryCount || 0) + 1;
        card.captureState = 'deferred';
        timers.set(card.id, setTimeout(() => {
            timers.delete(card.id);
            if (revision === card.lastEventId && latest(card)) void capture(card);
        }, card.retryCount * 1500));
    }

    window.runMonitorCheckpointAction = async (id, action) => {
        const card = cards.get(id);
        if (!card || !latest(card) || card.busy) return false;
        if (action === 'capture') { await capture(card); return true; }
        if (action === 'focus') {
            const refs = card.data.interaction?.spatial_refs || card.data.suggested_screenshot?.object_ids || [];
            const ok = window.focusMonitorCheckpoint?.(refs, card.evidence);
            if (!ok) { card.notice = text(card, '当前可见对象不足以定位；请先检查 Data Tree。',
                'The visible objects could not be located; check Data Tree first.'); render(card); }
            return !!ok;
        }
        if (action === 'dose') {
            if (typeof recomputeManualDose !== 'function' || manualPlanningState.doseRecomputeRunning
                || card.data.interaction?.dose_current) return false;
            card.busy = text(card, '剂量计算中；完成后会更新这里的对比结果。', 'Computing dose; this comparison will update when ready.');
            render(card);
            try {
                const result = await recomputeManualDose('monitor_compare');
                if (!result?.success) card.notice = text(card, '剂量重算未完成，请查看计算错误后重试。', 'Dose recomputation did not complete; review the error and retry.');
                return !!result?.success;
            } catch (_) {
                card.notice = text(card, '剂量重算未完成，请稍后重试。', 'Dose recomputation did not complete; retry shortly.');
                return false;
            } finally { card.busy = ''; render(card); }
        }
        if (!['keep', 'restore'].includes(action) || !card.evidence.restore_token || card.decision) return false;
        card.busy = text(card, '正在提交操作…', 'Applying decision…'); render(card);
        try {
            await window.performMonitorEditDecision(card.evidence.restore_token, action === 'keep',
                {sessionId: card.sessionId, runId: card.runId, language: card.language});
            return true;
        } catch (error) {
            card.notice = error?.code === 'monitor_plan_busy'
                ? text(card, '规划仍在更新，未执行本次操作；完成后可重试。', 'Planning is updating; this action was not applied. Retry when ready.')
                : text(card, '操作未确认。请核对最新检查点后重试。', 'Action unconfirmed. Check the latest checkpoint before retrying.');
            return false;
        } finally { card.busy = ''; render(card); }
    };

    function scheduleCompare() {
        if (compareTimer) clearTimeout(compareTimer);
        if (!autoCompare || typeof setTimeout !== 'function') return;
        const card = [...cards.values()].reverse().find(latest);
        if (!card || card.data.interaction?.dose_current || card.autoAttempt === card.lastEventId) return;
        compareTimer = setTimeout(async () => {
            compareTimer = null;
            if (!autoCompare || !latest(card)) return;
            // No GPU work during a drag, another job, or an evidence capture.
            if (card.busy || manualPlanningState.doseRecomputeRunning || trainingMonitorState.screenshotPendingRunId) {
                scheduleCompare(); return;
            }
            card.autoAttempt = card.lastEventId;
            await window.runMonitorCheckpointAction(card.id, 'dose');
            scheduleCompare();
        }, 1800);
    }
    window.setMonitorAutoCompare = enabled => { autoCompare = enabled === true; scheduleCompare(); publish(); };
    document.addEventListener?.('visibilitychange', () => {
        if (!document.hidden) for (const card of cards.values()) {
            if (card.captureState === 'deferred' && latest(card)) void capture(card);
        }
    });

    function attachActions(card) {
        if (typeof document.querySelectorAll !== 'function') return;
        const row = Array.from(document.querySelectorAll('[data-message-id]'))
            .find(node => node.dataset.messageId === card.messageId);
        if (!row) return;
        row.querySelector('.monitor-checkpoint-actions')?.remove();
        const actions = document.createElement('div');
        actions.className = 'monitor-checkpoint-actions';
        actions.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;margin-top:10px';
        const add = (zh, en, handler, disabled = false) => {
            const button = document.createElement('button');
            button.type = 'button'; button.className = 'btn btn-sm';
            button.textContent = text(card, zh, en);
            button.disabled = disabled || !!card.busy || !latest(card);
            button.addEventListener('click', async () => {
                if (!latest(card) || card.busy) return;
                await handler();
            });
            actions.appendChild(button);
        };
        add('定位编辑对象', 'Locate edited objects', () => window.runMonitorCheckpointAction(card.id, 'focus'));
        if (card.captureState === 'failed') add('重试截图', 'Retry image', () => window.runMonitorCheckpointAction(card.id, 'capture'));
        if (!card.data.interaction?.dose_current) add('重算剂量并比较', 'Recompute and compare', () => window.runMonitorCheckpointAction(card.id, 'dose'));
        if (card.evidence.restore_token && !card.decision) {
            for (const keep of [false, true]) add(keep ? '保留这次编辑' : '恢复编辑前位置',
                keep ? 'Keep this edit' : 'Restore pre-edit position', async () => {
                    await window.runMonitorCheckpointAction(card.id, keep ? 'keep' : 'restore');
                });
        }
        (row.querySelector('.chat-msg-wrapper') || row).appendChild(actions);
    }

    window.receiveMonitorCheckpoint = async data => {
        const evidence = data?.event?.detail?.edit_evidence;
        if (!evidence || !trainingMonitorState.active || data.monitor_run_id !== trainingMonitorState.runId) return null;
        const sessionId = _activeApiSessionId();
        if (data.session_id && data.session_id !== sessionId) return null;
        const runId = data.monitor_run_id;
        const owned = `${sessionId}:${runId}`;
        if (owner !== owned) {
            for (const previous of cards.values()) cancelRetry(previous);
            cards.clear(); owner = owned;
        }
        const id = evidence.geometry_event_id || evidence.event_id;
        if (!id) return null;
        let card = cards.get(id);
        if (card && Number(evidence.after_version) < Number(card.evidence.after_version)) return null;
        if (card?.lastEventId === evidence.event_id) return card;
        for (const prior of cards.values()) {
            if (prior.id !== id && Number(prior.evidence.after_version) <= Number(evidence.after_version)) {
                prior.superseded = true; cancelRetry(prior); render(prior);
            }
        }
        const newer = [...cards.values()].some(prior => Number(prior.evidence.after_version) > Number(evidence.after_version));
        if (!card) {
            card = {id, sessionId, runId, createdAt:Date.now(), requestId:`monitor-${runId}`,
                messageId:`assistant-monitor-${runId}-edit-${id}`, captureState:'pending'};
            cards.set(id, card);
            if (cards.size > 40) cards.delete(cards.keys().next().value);
        }
        Object.assign(card, {data, evidence, lastEventId:evidence.event_id,
            language: data.language || monitorConversationLanguage(sessionId), superseded:newer});
        cancelRetry(card); card.retryCount = 0;
        card.captureState = newer ? 'failed' : data.suggested_screenshot ? 'pending' : 'none';
        if (newer) card.captureError = 'monitor_checkpoint_superseded';
        card.notice = '';
        // Screenshots and their later outcomes use exactly this same message.
        data.monitor_card_id = card.messageId;
        render(card);
        window.clearMonitorFocus?.();
        scheduleCompare();
        if (!newer && data.suggested_screenshot) await reportUIEvent(data.event.type, data.event.label, {}, {cachedCheckpoint:data});
        return card;
    };
    window.updateMonitorCheckpointCapture = (data, result) => {
        const card = [...cards.values()].find(item => item.messageId === data?.monitor_card_id);
        if (!card || !current(card)) return false;
        if (data.event?.event_id !== card.lastEventId) return true;
        card.captureState = result.success ? 'ready' : 'failed';
        card.captureError = result.error || '';
        if (!result.success) retryCapture(card);
        render(card);
        return true;
    };
    window.resolveMonitorCheckpointDecision = (token, kept) => {
        for (const card of cards.values()) {
            if (card.evidence.restore_token !== token) continue;
            delete card.evidence.restore_token;
            card.decision = text(card, kept ? '已保留这次编辑。' : '已恢复编辑前位置；剂量仍需更新。',
                kept ? 'This edit was kept.' : 'Pre-edit position restored; dose requires updating.');
            render(card);
        }
    };
    window.refreshMonitorCheckpointPresentation = phase => {
        if (phase === 'active' && owner !== `${_activeApiSessionId()}:${trainingMonitorState.runId}`) {
            for (const card of cards.values()) cancelRetry(card);
            cards.clear(); autoCompare = false;
            owner = `${_activeApiSessionId()}:${trainingMonitorState.runId}`;
        }
        if (phase !== 'active') {
            autoCompare = false;
            if (compareTimer) clearTimeout(compareTimer);
            window.clearMonitorFocus?.();
        }
        for (const card of cards.values()) {
            if (phase !== 'active') cancelRetry(card);
            if (phase !== 'active' && ['pending', 'deferred'].includes(card.captureState)) {
                card.captureState = 'failed'; card.captureError = 'monitor_stopped';
            }
            render(card);
        }
        publish();
        window.monitorDashboardPhase?.(phase);
    };
})();
