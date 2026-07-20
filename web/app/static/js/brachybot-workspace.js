/* Durable case workspace bridge: server sessions own all clinical state. */
(function () {
    // This flag lets compatibility shims in the older chat script route
    // direct global calls to the durable workspace implementation.
    window.__serverWorkspaceReady = true;
    let revision = null;
    let saveTimer = null;
    let restoring = false;
    let workspaceTransition = null;
    let workspaceTransitionGeneration = 0;
    let workspaceRestoreGeneration = 0;
    const workspaceRestoreTimers = new Set();
    let backgroundRestoreGeneration = 0;
    let backgroundRestoreTimer = null;
    const WORKSPACE_REQUEST_TIMEOUT_MS = 15000;
    const WORKSPACE_RECOVERY_TIMEOUT_MS = 5000;
    let recoveryNoticeDismissKey = '';

    async function workspaceFetch(input, init = {}, timeoutMs = WORKSPACE_REQUEST_TIMEOUT_MS) {
        const controller = typeof AbortController === 'function' ? new AbortController() : null;
        const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
        try {
            const options = Object.assign({}, init);
            if (controller) options.signal = controller.signal;
            return await fetch(input, options);
        } catch (error) {
            if (error?.name === 'AbortError') {
                throw new Error('Workspace request timed out. Check that the BrachyBot server is running.');
            }
            throw error;
        } finally {
            if (timer) clearTimeout(timer);
        }
    }

    function isCurrentTransition(generation) {
        return generation === workspaceTransitionGeneration;
    }

    function cancelBackgroundWorkspaceRestore() {
        backgroundRestoreGeneration += 1;
        if (backgroundRestoreTimer) {
            clearTimeout(backgroundRestoreTimer);
            backgroundRestoreTimer = null;
        }
        document.body.classList.remove('workspace-hydrating');
    }

    function scheduleBackgroundWorkspaceRestore(workspace, sessionId) {
        const generation = ++backgroundRestoreGeneration;
        if (backgroundRestoreTimer) clearTimeout(backgroundRestoreTimer);
        document.body.classList.add('workspace-hydrating');
        // Let the lightweight case transition paint before loading CT,
        // meshes, dose arrays, and the hydrated agent. The selected case is
        // checked again before and after this task so a rapid second switch
        // cannot let an old restore repaint the current case.
        backgroundRestoreTimer = setTimeout(async () => {
            backgroundRestoreTimer = null;
            if (generation !== backgroundRestoreGeneration || sessionId !== activeSessionId) return;
            try {
                if (typeof restoreActiveSessionWorkspace === 'function') {
                    await restoreActiveSessionWorkspace({
                        clearReport: false,
                        workspace,
                        background: true,
                    });
                }
            } catch (error) {
                console.warn('[workspace] background case restore failed:', error);
            } finally {
                if (generation === backgroundRestoreGeneration) {
                    document.body.classList.remove('workspace-hydrating');
                }
            }
        }, 0);
    }

    function clearScheduledWorkspaceSave() {
        if (!saveTimer) return;
        clearTimeout(saveTimer);
        saveTimer = null;
    }

    function invalidateDeferredWorkspaceRestore() {
        // A mesh or chart restore may deliberately run after asynchronous
        // rendering settles. Those callbacks belong to one case only: a
        // newer case selection must never let an older snapshot repaint it.
        workspaceRestoreGeneration += 1;
        workspaceRestoreTimers.forEach(timer => clearTimeout(timer));
        workspaceRestoreTimers.clear();
        return workspaceRestoreGeneration;
    }

    function scheduleDeferredWorkspaceRestore(generation, callback, delay) {
        const timer = setTimeout(() => {
            workspaceRestoreTimers.delete(timer);
            if (generation !== workspaceRestoreGeneration) return;
            callback();
        }, delay);
        workspaceRestoreTimers.add(timer);
        return timer;
    }

    function setWorkspaceTransitionState(active) {
        document.body.classList.toggle('workspace-transitioning', active);
        const sidebar = document.getElementById('sessionSidebar');
        if (!sidebar) return;
        sidebar.setAttribute('aria-busy', active ? 'true' : 'false');
    }

    async function runWorkspaceTransition(operation) {
        // A case change coordinates several server and browser mutations.
        // Serializing them prevents a late restore response from repainting a
        // previously selected case over the user's most recent selection.
        if (workspaceTransition) {
            return { success: false, busy: true, error: 'A case transition is already in progress.' };
        }
        cancelBackgroundWorkspaceRestore();
        clearScheduledWorkspaceSave();
        invalidateDeferredWorkspaceRestore();
        setWorkspaceTransitionState(true);
        const transitionGeneration = ++workspaceTransitionGeneration;
        const transition = (async () => {
            try {
                return await operation();
            } catch (error) {
                console.error('[workspace] case transition failed:', error);
                // A request can fail after the server has already selected a
                // different case. Rehydrate from the authoritative server
                // selection instead of leaving chat and viewer state split.
                // Recovery is bounded: an offline server must never leave the
                // sidebar permanently marked as busy.
                try {
                    await Promise.race([
                        recoverWorkspaceAfterTransitionFailure(transitionGeneration),
                        new Promise(resolve => setTimeout(resolve, WORKSPACE_RECOVERY_TIMEOUT_MS)),
                    ]);
                } catch (recoveryError) {
                    console.error('[workspace] case transition recovery failed:', recoveryError);
                }
                return { success: false, error: error?.message || 'Unable to change case.' };
            } finally {
                // A timed-out recovery may still be unwinding in the
                // background. Invalidate it before releasing the busy gate so
                // a late response cannot repaint an older case after the UI
                // has already reported the transition result.
                if (workspaceTransitionGeneration === transitionGeneration) {
                    workspaceTransitionGeneration += 1;
                }
                setWorkspaceTransitionState(false);
                workspaceTransition = null;
            }
        })();
        workspaceTransition = transition;
        return transition;
    }

    function jsonClone(value) {
        return JSON.parse(JSON.stringify(value, (_key, item) => {
            if (item instanceof Set) return Array.from(item);
            if (typeof item === 'function' || typeof item === 'undefined') return undefined;
            if (item && item.constructor && /^(WebGL|HTMLCanvas|ImageData)/.test(item.constructor.name)) return undefined;
            return item;
        }));
    }

    function controlState() {
        const values = {};
        document.querySelectorAll('input[id], select[id], textarea[id]').forEach(el => {
            if (el.type === 'password' || /(?:api[_-]?key|token|secret)/i.test(el.id)) return;
            values[el.id] = el.type === 'checkbox' || el.type === 'radio'
                ? { checked: !!el.checked }
                : { value: el.value };
        });
        return values;
    }

    function numberArray(value) {
        return value && Number.isFinite(value.x) ? [value.x, value.y, value.z] : null;
    }

    function sceneViewState() {
        if (typeof scene3D === 'undefined' || !scene3D?.camera) return {};
        const camera = scene3D.camera;
        return {
            camera_position: numberArray(camera.position),
            camera_quaternion: camera.quaternion ? [camera.quaternion.x, camera.quaternion.y, camera.quaternion.z, camera.quaternion.w] : null,
            camera_zoom: Number.isFinite(camera.zoom) ? camera.zoom : null,
            camera_target: numberArray(scene3D.controls?.target),
            display_mode: typeof state !== 'undefined' ? state.doseTexture?.enabled ? 'dose_surface' : 'normal_surface' : null,
        };
    }

    function dvhViewState() {
        const chart = document.getElementById('dvhChart');
        const layout = chart?._fullLayout;
        return {
            x_range: Array.isArray(layout?.xaxis?.range) ? layout.xaxis.range.slice(0, 2) : null,
            y_range: Array.isArray(layout?.yaxis?.range) ? layout.yaxis.range.slice(0, 2) : null,
            axis_zoom_mode: chart?._dvhAxisZoomMode || null,
        };
    }

    function workspaceUiState() {
        return {
            controls: controlState(),
            viewer: {
                sessionId: typeof state !== 'undefined' ? state.sessionId : null,
                slices: (typeof state !== 'undefined' && state.slices) ? jsonClone(state.slices) : {},
                settings: (typeof state !== 'undefined' && state.viewerSettings) ? jsonClone(state.viewerSettings) : {},
                doseOpacity: typeof state !== 'undefined' ? state.doseOpacity : null,
                // Raw slices, promises and Three.js materials are runtime-only.
                // Persisting them would create circular JSON and cannot restore a
                // WebGL resource after a restart; the enabled mode is sufficient.
                doseTexture: typeof state !== 'undefined' && state.doseTexture ? { enabled: !!state.doseTexture.enabled } : null,
                scene: sceneViewState(),
                dvh: dvhViewState(),
            },
            data_tree: typeof dataTreeState !== 'undefined' ? jsonClone(dataTreeState) : {},
            manual: typeof _manualState === 'function' ? jsonClone(_manualState()) : {},
            training: typeof trainingMonitorState !== 'undefined' ? jsonClone(trainingMonitorState) : {},
        };
    }

    function reportState() {
        if (!window.reportForm) return {};
        return {
            form: jsonClone(window.reportForm),
            sources: window.Report?.sources?._map ? Array.from(window.Report.sources._map.entries()) : [],
            audit: jsonClone(window.__reportWorkspaceAudit || []),
            snapshots: jsonClone(window.__reportWorkspaceSnapshots || []),
            collapsed: jsonClone(window._reportCollapsed || {}),
        };
    }

    function renderRecoveryNotice(operation) {
        bindWorkspaceNoticeControls();
        const target = document.getElementById('workspaceRecoveryNotice');
        if (!target) return;
        if (operation?.state !== 'interrupted') {
            target.hidden = true;
            const message = document.getElementById('workspaceRecoveryMessage');
            if (message) message.textContent = '';
            recoveryNoticeDismissKey = '';
            return;
        }
        const session = String(typeof activeSessionId !== 'undefined' ? activeSessionId : 'current');
        const identity = String(operation.interrupted_at || operation.updated_at || operation.revision || operation.message || 'interrupted');
        const dismissKey = `brachybot:recovery-notice:${session}:${identity}`;
        recoveryNoticeDismissKey = dismissKey;
        if (readRecoveryDismissal(dismissKey)) {
            target.hidden = true;
            return;
        }
        const checkpoint = operation.checkpoint || {};
        const step = checkpoint.step ? ` Resume from ${checkpoint.step}.` : '';
        const message = document.getElementById('workspaceRecoveryMessage');
        const text = `${operation.message || 'The previous task was interrupted.'}${step} The last saved case state is available; rerun the unfinished action when ready.`;
        if (message) message.textContent = text;
        else target.textContent = text;
        target.hidden = false;
    }

    function readRecoveryDismissal(key) {
        try { return sessionStorage.getItem(key) === '1'; } catch (_) { return false; }
    }

    function dismissWorkspaceRecoveryNotice() {
        // A dismissed recovery banner never acknowledges or clears the
        // interrupted operation; the saved checkpoint remains authoritative.
        if (recoveryNoticeDismissKey) {
            try { sessionStorage.setItem(recoveryNoticeDismissKey, '1'); } catch (_) {}
        }
        const target = document.getElementById('workspaceRecoveryNotice');
        if (target) target.hidden = true;
    }

    function bindWorkspaceNoticeControls() {
        const recoveryClose = document.getElementById('workspaceRecoveryDismiss');
        if (recoveryClose && !recoveryClose.dataset.bound) {
            recoveryClose.dataset.bound = 'true';
            recoveryClose.addEventListener('click', dismissWorkspaceRecoveryNotice);
        }
        const lockClose = document.getElementById('workspaceLockDismiss');
        if (lockClose && !lockClose.dataset.bound) {
            lockClose.dataset.bound = 'true';
            lockClose.addEventListener('click', () => window.brachybotAuth?.dismissWorkspaceLockNotice?.());
        }
    }

    function chatState() {
        const current = (typeof sessions !== 'undefined' && typeof activeSessionId !== 'undefined') ? sessions[activeSessionId] : null;
        return current ? { messages: jsonClone(current.messages || []), pending: !!current.pending } : {};
    }

    function applyControls(values) {
        Object.entries(values || {}).forEach(([id, saved]) => {
            const element = document.getElementById(id);
            if (!element || !saved || typeof saved !== 'object') return;
            if (Object.prototype.hasOwnProperty.call(saved, 'checked')) element.checked = !!saved.checked;
            if (Object.prototype.hasOwnProperty.call(saved, 'value')) element.value = saved.value;
        });
    }

    function restoreSceneView(scene, dvh, generation) {
        const applyScene = () => {
            if (!scene || typeof scene3D === 'undefined' || !scene3D?.camera) return;
            const camera = scene3D.camera;
            if (Array.isArray(scene.camera_position) && scene.camera_position.length === 3) camera.position.fromArray(scene.camera_position);
            if (Array.isArray(scene.camera_quaternion) && scene.camera_quaternion.length === 4) camera.quaternion.fromArray(scene.camera_quaternion);
            if (Number.isFinite(scene.camera_zoom)) camera.zoom = scene.camera_zoom;
            if (Array.isArray(scene.camera_target) && scene.camera_target.length === 3 && scene3D.controls?.target) scene3D.controls.target.fromArray(scene.camera_target);
            camera.updateProjectionMatrix?.();
            scene3D.controls?.update?.();
            scene3D.requestRender?.(4);
        };
        // Mesh reconstruction is asynchronous. Applying twice restores the
        // saved pose after geometry and renderer-resize work has settled.
        applyScene();
        scheduleDeferredWorkspaceRestore(generation, applyScene, 450);
        scheduleDeferredWorkspaceRestore(generation, applyScene, 1200);

        const applyDvh = () => {
            const chart = document.getElementById('dvhChart');
            if (!dvh || !chart || typeof Plotly === 'undefined' || !Plotly.relayout) return;
            const update = {};
            if (Array.isArray(dvh.x_range) && dvh.x_range.length === 2) update['xaxis.range'] = dvh.x_range;
            if (Array.isArray(dvh.y_range) && dvh.y_range.length === 2) update['yaxis.range'] = dvh.y_range;
            if (dvh.axis_zoom_mode) chart._dvhAxisZoomMode = dvh.axis_zoom_mode;
            if (Object.keys(update).length) Plotly.relayout(chart, update);
        };
        scheduleDeferredWorkspaceRestore(generation, applyDvh, 350);
        scheduleDeferredWorkspaceRestore(generation, applyDvh, 1100);

        if (scene?.display_mode === 'dose_surface' && typeof setDoseTextureMode === 'function') {
            // Recreate textures from the restored dose grid; WebGL materials
            // themselves are intentionally not persisted in the workspace.
            scheduleDeferredWorkspaceRestore(
                generation,
                () => setDoseTextureMode(true, { silent: true }),
                900,
            );
        }
    }

    async function applyWorkspaceSnapshot(snapshot) {
        if (!snapshot) return;
        const ui = snapshot.ui || {};
        const uiState = ui.state || ui;
        const restoreGeneration = invalidateDeferredWorkspaceRestore();
        restoring = true;
        try {
            applyControls(uiState.controls || {});
            if (uiState.viewer && typeof state !== 'undefined') {
                state.slices = Object.assign(state.slices || {}, uiState.viewer.slices || {});
                state.viewerSettings = Object.assign(state.viewerSettings || {}, uiState.viewer.settings || {});
                if (uiState.viewer.doseOpacity != null) state.doseOpacity = uiState.viewer.doseOpacity;
                if (uiState.viewer.doseTexture) state.doseTexture = Object.assign(state.doseTexture || {}, uiState.viewer.doseTexture);
            }
            if (uiState.data_tree && typeof dataTreeState !== 'undefined') {
                Object.assign(dataTreeState, uiState.data_tree);
            }
            if (uiState.manual && typeof _saveManualState === 'function') _saveManualState(uiState.manual);
            if (typeof trainingMonitorState !== 'undefined') {
                // The browser snapshot keeps presentation details while the
                // server bridge keeps feedback/events emitted by tools.
                Object.assign(trainingMonitorState, ui.bridge?.training || {}, uiState.training || {});
            }
            const report = snapshot.report && snapshot.report.form;
            if (report && typeof report === 'object') {
                report.editedFields = new Set(report.editedFields || []);
                window.reportForm = report;
                const storedSources = snapshot.report?.sources;
                if (window.Report?.sources?._map && Array.isArray(storedSources)) {
                    window.Report.sources._map = new Map(storedSources);
                }
                window.__reportWorkspaceAudit = Array.isArray(snapshot.report?.audit) ? snapshot.report.audit : [];
                window.__reportWorkspaceSnapshots = Array.isArray(snapshot.report?.snapshots) ? snapshot.report.snapshots : [];
                window._reportCollapsed = snapshot.report?.collapsed || {};
                try { renderReportEditor(); } catch (_) {}
                try { _updateReportPreview(); } catch (_) {}
            }
            const chat = snapshot.chat || {};
            if (Array.isArray(chat.messages) && typeof sessions !== 'undefined' && activeSessionId && sessions[activeSessionId]) {
                // Pending is a transient browser presentation state.  Never
                // resurrect an old spinner after a reload or case switch.
                sessions[activeSessionId].messages = chat.messages;
                sessions[activeSessionId].pending = false;
                if (typeof loadSessionChat === 'function') loadSessionChat(activeSessionId);
            }
            renderRecoveryNotice(snapshot.operation);
            if (typeof setViewerLayout === 'function' && state?.viewerSettings?.layout) setViewerLayout(state.viewerSettings.layout);
            if (typeof renderDataTree === 'function') renderDataTree();
            if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
            restoreSceneView(uiState.viewer?.scene, uiState.viewer?.dvh, restoreGeneration);
        } finally {
            restoring = false;
        }
    }

    async function persistWorkspace(reason) {
        if (restoring || !window.brachybotAuth?.user || !activeSessionId) return;
        try {
            const response = await workspaceFetch('/api/workspace/state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ revision, ui_state: workspaceUiState(), report: reportState(), chat: chatState(), reason }),
            });
            if (response.status === 409) {
                document.body.classList.add('workspace-readonly');
                return;
            }
            const data = await response.json().catch(() => null);
            if (data?.success) revision = data.revision;
        } catch (error) {
            console.debug('[workspace] save deferred:', error);
        }
    }

    function scheduleWorkspaceSave(reason) {
        clearScheduledWorkspaceSave();
        saveTimer = setTimeout(() => persistWorkspace(reason || 'ui.changed'), 700);
    }

    async function prepareSessionChange() {
        const active = !!window._chatTurnActive || !!window._chatStreaming
            || (typeof isStreaming !== 'undefined' && isStreaming);
        const pendingFollowUps = (Array.isArray(window._pendingHiddenChats)
            && window._pendingHiddenChats.length > 0) || !!window._hiddenChatFlushRunning;
        if (!active && !pendingFollowUps) return true;
        // Switching cases is an explicit user action. Stop the current
        // response first so its late SSE events cannot mutate the next case.
        if (typeof window.cancelActiveChatTurn === 'function') {
            await window.cancelActiveChatTurn('Session changed');
            return true;
        }
        return false;
    }

    function confirmWorkspaceAction(messageZh, messageEn) {
        if (typeof _confirmAction === 'function') return _confirmAction(messageZh, messageEn);
        // Never fall back to the browser-native confirm dialog: it is
        // visually inconsistent and can be blocked by embedded browsers.
        console.error('[workspace] Confirmation UI is unavailable; action cancelled.');
        return Promise.resolve(false);
    }

    function sessionStateFromPayload(entry) {
        return {
            id: entry.id,
            title: entry.title,
            created: Math.round(Number(entry.created_at || Date.now() / 1000) * 1000),
            updated: Math.round(Number(entry.updated_at || Date.now() / 1000) * 1000),
            messages: [],
            recoveryStatus: entry.recovery_status,
        };
    }

    function sessionMapFromPayload(data) {
        const next = {};
        (data.sessions || []).forEach(entry => {
            next[entry.id] = sessionStateFromPayload(entry);
        });
        return next;
    }

    function applySessionList(data) {
        sessions = sessionMapFromPayload(data);
        activeSessionId = data.active_session_id;
    }

    async function loadServerSessions({ commit = true, timeoutMs = WORKSPACE_REQUEST_TIMEOUT_MS } = {}) {
        const response = await workspaceFetch('/api/sessions', {}, timeoutMs);
        if (!response.ok) throw new Error(`Session list failed: HTTP ${response.status}`);
        const data = await response.json();
        if (commit) applySessionList(data);
        return data;
    }

    async function loadActiveWorkspace({ commit = true, timeoutMs = WORKSPACE_REQUEST_TIMEOUT_MS } = {}) {
        const response = await workspaceFetch('/api/workspace/snapshot', {}, timeoutMs);
        if (!response.ok) throw new Error(`Workspace snapshot failed: HTTP ${response.status}`);
        const data = await response.json();
        if (commit) {
            revision = data.workspace?.session?.revision ?? null;
            window._activeWorkspaceSnapshot = data.workspace;
        }
        return data.workspace;
    }

    async function recoverWorkspaceAfterTransitionFailure(generation) {
        try {
            const sessionData = await loadServerSessions({ commit: false, timeoutMs: WORKSPACE_RECOVERY_TIMEOUT_MS });
            const workspace = await loadActiveWorkspace({ commit: false, timeoutMs: WORKSPACE_RECOVERY_TIMEOUT_MS });
            if (!isCurrentTransition(generation)) return;
            applySessionList(sessionData);
            revision = workspace?.session?.revision ?? null;
            window._activeWorkspaceSnapshot = workspace;
            if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true });
            renderSessionList();
            if (typeof window.brachybotAuth?.acquireLease === 'function') await window.brachybotAuth.acquireLease();
            if (!isCurrentTransition(generation)) return;
            if (typeof restoreActiveSessionWorkspace === 'function') {
                await restoreActiveSessionWorkspace({ clearReport: false, workspace });
            }
            loadSessionChat(activeSessionId);
        } catch (recoveryError) {
            // Preserve the original failure as the user-facing result. This
            // second log remains useful when the network itself is unavailable.
            console.error('[workspace] case transition recovery failed:', recoveryError);
        }
    }

    window.loadSessions = async function loadSessions() {
        const data = await loadServerSessions();
        await loadActiveWorkspace();
        return data;
    };

    window.saveSessions = function saveSessions() {
        // The server workspace is the only durable source.  Keep no clinical
        // transcript in localStorage; this invocation simply coalesces a save.
        scheduleWorkspaceSave('chat.changed');
    };

    window.newChat = async function newChat() {
        return runWorkspaceTransition(async () => {
            if (!await prepareSessionChange()) return { success: false, cancelled: true };
            if (typeof flushActiveReportState === 'function') flushActiveReportState();
            await persistWorkspace('session.switching');
            const response = await workspaceFetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'New case' }) });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Unable to create case');
            if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true });
            const createdSession = data.session;
            if (createdSession?.id) {
                // The create endpoint returns the authoritative session entry.
                // Upsert it before rendering so the sidebar reacts immediately
                // without a second list request or a delayed chat checkpoint.
                sessions[createdSession.id] = sessionStateFromPayload(createdSession);
            }
            activeSessionId = data.active_session_id || createdSession?.id || activeSessionId;
            revision = data.workspace?.session?.revision ?? null;
            window._activeWorkspaceSnapshot = data.workspace || null;
            renderSessionList();
            if (data.lease && typeof window.brachybotAuth?.applyLeaseResult === 'function') {
                window.brachybotAuth.applyLeaseResult(data.lease);
            } else if (typeof window.brachybotAuth?.acquireLease === 'function') {
                await window.brachybotAuth.acquireLease();
            }
            // A newly-created case has no CT, arrays, meshes, report, or chat
            // to restore. Avoid the background status call here: it would
            // hydrate a full BrachyAgent solely for an empty workspace and
            // make a pure UI operation appear to hang.
            return { success: true, session_id: activeSessionId };
        });
    };

    window.switchSession = async function switchSession(id) {
        document.getElementById('sessionSidebar')?.classList.remove('mobile-open');
        if (id === activeSessionId) return { success: true, session_id: id, unchanged: true };
        if (!sessions[id]) return { success: false, error: 'The requested case does not exist.' };
        return runWorkspaceTransition(async () => {
            if (!(await prepareSessionChange())) return { success: false, cancelled: true };
            if (typeof flushActiveReportState === 'function') flushActiveReportState();
            await persistWorkspace('session.switching');
            if (typeof window.brachybotAuth?.releaseLease === 'function') await window.brachybotAuth.releaseLease();
            const response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}/select`, { method: 'POST' });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Unable to open case');
            activeSessionId = data.active_session_id;
            revision = data.workspace?.session?.revision ?? null;
            if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true });
            window._activeWorkspaceSnapshot = data.workspace;
            renderSessionList();
            if (typeof window.brachybotAuth?.acquireLease === 'function') await window.brachybotAuth.acquireLease();
            if (typeof applyWorkspaceSnapshot === 'function') await applyWorkspaceSnapshot(data.workspace);
            scheduleBackgroundWorkspaceRestore(data.workspace, activeSessionId);
            return { success: true, session_id: activeSessionId };
        });
    };

    window.deleteSession = async function deleteSession(id, options = {}) {
        if (!sessions[id]) return { success: false, error: 'The requested case does not exist.' };
        if (options.skipConfirm !== true) {
            const title = sessions[id].title || id;
            const confirmed = await confirmWorkspaceAction(
                `确定要将病例“${title}”移入回收站吗？`,
                `Move case "${title}" to the recycle bin?`,
            );
            if (!confirmed) return { success: false, cancelled: true };
        }
        // Deleting an inactive case is an independent control-plane action.
        // It must not call prepareSessionChange(): that helper intentionally
        // cancels the active chat/plan stream before switching cases, and the
        // deleted case is not the case currently being edited. Keeping this
        // path separate also avoids clearing and restoring the active viewer.
        if (id !== activeSessionId) {
            try {
                const response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.error || 'Unable to delete case');
                await loadServerSessions();
                renderSessionList();
                return { success: true, active_session_id: activeSessionId };
            } catch (error) {
                console.error('[workspace] inactive case deletion failed:', error);
                return { success: false, error: error?.message || 'Unable to delete case.' };
            }
        }

        return runWorkspaceTransition(async () => {
            if (!await prepareSessionChange()) return { success: false, cancelled: true };
            if (id === activeSessionId && typeof flushActiveReportState === 'function') flushActiveReportState();
            await persistWorkspace('session.delete');
            if (id === activeSessionId && typeof window.brachybotAuth?.releaseLease === 'function') await window.brachybotAuth.releaseLease();
            const response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Unable to delete case');
            await loadServerSessions();
            if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true });
            activeSessionId = data.active_session_id || activeSessionId;
            revision = data.workspace?.session?.revision ?? null;
            window._activeWorkspaceSnapshot = data.workspace || null;
            renderSessionList();
            if (typeof window.brachybotAuth?.acquireLease === 'function') await window.brachybotAuth.acquireLease();
            if (data.workspace && typeof applyWorkspaceSnapshot === 'function') {
                await applyWorkspaceSnapshot(data.workspace);
            }
            scheduleBackgroundWorkspaceRestore(data.workspace || null, activeSessionId);
            return { success: true, active_session_id: activeSessionId };
        });
    };

    window.renameServerSession = async function renameServerSession(id, title) {
        const response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to rename case');
        if (sessions[id]) sessions[id].title = data.session.title;
    };

    function timestamp(value) {
        const date = new Date(Number(value || 0) * 1000);
        return Number.isFinite(date.getTime()) ? date.toLocaleString() : '';
    }

    function recycleRow(entry) {
        const row = document.createElement('div');
        row.className = 'recycle-bin-item';
        const title = document.createElement('div');
        title.className = 'recycle-bin-title';
        title.textContent = entry.title || 'Untitled case';
        const meta = document.createElement('div');
        meta.className = 'recycle-bin-meta';
        meta.textContent = `Deleted ${timestamp(entry.deleted_at || entry.updated_at)}`;
        const actions = document.createElement('div');
        actions.className = 'recycle-bin-actions';
        const restore = document.createElement('button');
        restore.type = 'button';
        restore.textContent = 'Restore';
        restore.addEventListener('click', () => window.restoreTrashedSession(entry.id));
        const purge = document.createElement('button');
        purge.type = 'button';
        purge.className = 'danger';
        purge.textContent = 'Delete permanently';
        purge.addEventListener('click', () => window.purgeTrashedSession(entry.id, entry.title));
        actions.append(restore, purge);
        row.append(title, meta, actions);
        return row;
    }

    window.closeRecycleBin = function closeRecycleBin() {
        const panel = document.getElementById('recycleBinPanel');
        if (panel) panel.hidden = true;
    };

    window.openRecycleBin = async function openRecycleBin() {
        const panel = document.getElementById('recycleBinPanel');
        const list = document.getElementById('recycleBinList');
        if (!panel || !list) return;
        panel.hidden = false;
        list.replaceChildren();
        try {
            const response = await fetch('/api/sessions/trash');
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Unable to load recycle bin');
            const entries = data.sessions || [];
            if (!entries.length) {
                const empty = document.createElement('div');
                empty.className = 'recycle-bin-empty';
                empty.textContent = 'No deleted cases. Cases are retained for 7 days.';
                list.append(empty);
            } else {
                entries.forEach(entry => list.append(recycleRow(entry)));
            }
        } catch (error) {
            const empty = document.createElement('div');
            empty.className = 'recycle-bin-empty';
            empty.textContent = error.message || 'Unable to load recycle bin';
            list.append(empty);
        }
    };

    window.restoreTrashedSession = async function restoreTrashedSession(id) {
        const response = await fetch(`/api/sessions/${encodeURIComponent(id)}/restore`, { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to restore case');
        await loadServerSessions();
        renderSessionList();
        await window.openRecycleBin();
    };

    window.purgeTrashedSession = async function purgeTrashedSession(id, title) {
        const label = title || 'this case';
        const confirmed = await confirmWorkspaceAction(
            `确定要永久删除“${label}”吗？此操作无法撤销。`,
            `Permanently delete "${label}"? This cannot be undone.`,
        );
        if (!confirmed) return;
        const response = await fetch(`/api/sessions/${encodeURIComponent(id)}/purge`, { method: 'DELETE' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to permanently delete case');
        await window.openRecycleBin();
    };

    window.scheduleWorkspaceSave = scheduleWorkspaceSave;
    window.persistWorkspace = persistWorkspace;
    window.applyWorkspaceSnapshot = applyWorkspaceSnapshot;
    window.loadServerSessions = loadServerSessions;
    window.invalidateDeferredWorkspaceRestore = invalidateDeferredWorkspaceRestore;

    function installScenePersistenceHook() {
        if (typeof scene3D === 'undefined' || !scene3D?.controls) {
            setTimeout(installScenePersistenceHook, 500);
            return;
        }
        if (scene3D.controls._workspacePersistenceHook) return;
        scene3D.controls._workspacePersistenceHook = true;
        scene3D.controls.addEventListener('change', () => scheduleWorkspaceSave('viewer.camera'));
    }
    setTimeout(installScenePersistenceHook, 500);
})();
