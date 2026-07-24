/* Durable case workspace bridge: server sessions own all clinical state. */
(function () {
    // This flag lets compatibility shims in the older chat script route
    // direct global calls to the durable workspace implementation.
    window.__serverWorkspaceReady = true;
    let revision = null;
    const sessionRevisions = Object.create(null);
    let saveTimer = null;
    let restoring = false;
    let workspaceTransition = null;
    let workspaceTransitionGeneration = 0;
    let workspaceRestoreGeneration = 0;
    const workspaceRestoreTimers = new Set();
    let backgroundRestoreGeneration = 0;
    let backgroundRestoreTimer = null;
    // Control ids whose .value is persisted in model space but displayed
    // in physical Gy to the operator.  applyControls() must convert them
    // back via doseModelToGy() during workspace restoration.
    const GY_VALUE_IDS = new Set(['inLowestEnergy', 'outHighestEnergy']);
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
        window.setWorkspaceHydrationState?.(false);
    }

    window.setWorkspaceHydrationState = function setWorkspaceHydrationState(active, message) {
        const notice = document.getElementById('workspaceHydrationNotice');
        if (!notice) return;
        const target = document.getElementById('workspaceHydrationMessage');
        if (target && message) target.textContent = message;
        notice.hidden = !active;
        document.body.classList.toggle('workspace-hydrating', !!active);
    };

    function scheduleBackgroundWorkspaceRestore(workspace, sessionId) {
        const generation = ++backgroundRestoreGeneration;
        if (backgroundRestoreTimer) clearTimeout(backgroundRestoreTimer);
        window.setWorkspaceHydrationState?.(
            true,
            typeof window._t === 'function'
                ? window._t('正在恢复病例资源…', 'Restoring case resources...')
                : 'Restoring case resources...',
        );
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
                        // The optimistic shell has already cleared the old
                        // case. Do not erase a just-resumed task trace while
                        // the heavier CT/mesh resources hydrate.
                        skipClientClear: true,
                    });
                }
            } catch (error) {
                console.warn('[workspace] background case restore failed:', error);
            } finally {
                if (generation === backgroundRestoreGeneration) {
                    document.body.classList.remove('workspace-hydrating');
                    window.setWorkspaceHydrationState?.(false);
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

    function workspaceSnapshotSessionId(snapshot) {
        return String(snapshot?.session_id || snapshot?.session?.id || '');
    }

    function rememberWorkspaceRevision(snapshot) {
        const sessionId = workspaceSnapshotSessionId(snapshot);
        const value = snapshot?.session?.revision;
        if (sessionId && Number.isFinite(Number(value))) {
            sessionRevisions[sessionId] = Number(value);
            if (sessionId === String(activeSessionId || '')) revision = Number(value);
        }
    }

    function controlState() {
        const values = {};
        document.querySelectorAll('input[id], select[id], textarea[id]').forEach(el => {
            if (el.type === 'password' || /(?:api[_-]?key|token|secret)/i.test(el.id)) return;
            if (el.tagName === 'SELECT' && el.multiple) {
                // A guide can intentionally target a subset of planned
                // needles. Preserve every selected channel, rather than the
                // browser's scalar select.value (which exposes only the
                // first one), so the exported manufacturing geometry survives
                // a case switch or server restart unchanged.
                values[el.id] = {
                    values: Array.from(el.selectedOptions || [])
                        .map(option => String(option.value))
                        .filter(Boolean),
                };
                return;
            }
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

    function applyChatSnapshotFast(snapshot) {
        const chat = snapshot?.chat;
        const sessionId = workspaceSnapshotSessionId(snapshot);
        if (!chat || !sessionId || sessionId !== String(activeSessionId || '')
            || typeof sessions === 'undefined' || !sessions[sessionId]) return false;
        rememberWorkspaceRevision(snapshot);

        // Chat is the first-paint part of a workspace.  It contains no CT,
        // GPU, WebGL, or model state, so restoring it here keeps reconnects
        // responsive while the clinical data plane hydrates in the background.
        if (Array.isArray(chat.messages)) {
            sessions[sessionId].messages = jsonClone(chat.messages);
            sessions[sessionId].pending = false;
            if (typeof loadSessionChat === 'function') loadSessionChat(sessionId);
        }
        window._sessionChatQueues = window._sessionChatQueues || {};
        window._sessionChatQueues[sessionId] = Array.isArray(chat.queued) ? jsonClone(chat.queued) : [];
        window._sessionChatTaskStatuses = window._sessionChatTaskStatuses || {};
        if (chat.task_id) {
            window._sessionChatTaskIds = window._sessionChatTaskIds || {};
            window._sessionChatTaskIds[sessionId] = chat.task_id;
            window._sessionChatTaskStatuses[sessionId] = chat.task_status || 'running';
        } else {
            delete window._sessionChatTaskIds?.[sessionId];
            delete window._detachedChatTasks?.[sessionId];
            window._sessionChatTaskStatuses[sessionId] = chat.task_status || 'idle';
        }
        return true;
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
        if (!current) return {};
        const sessionId = String(activeSessionId || '');
        const queue = (window._sessionChatQueues && Array.isArray(window._sessionChatQueues[sessionId]))
            ? jsonClone(window._sessionChatQueues[sessionId]) : [];
        const taskId = (window._activeChatTaskSessionId === sessionId ? window._activeChatTaskId : null)
            || window._sessionChatTaskIds?.[sessionId]
            || window._detachedChatTasks?.[sessionId]
            || null;
        const savedStatus = window._sessionChatTaskStatuses?.[sessionId]
            || window._activeWorkspaceSnapshot?.chat?.task_status
            || null;
        return {
            messages: jsonClone(current.messages || []),
            pending: !!current.pending,
            queued: queue,
            task_id: taskId,
            task_status: taskId ? (savedStatus || 'running') : (savedStatus || 'idle'),
        };
    }

    const CASE_DATA_CONTROL_IDS = new Set(['ctPath', 'ctvPath', 'oarPath', 'fileCT', 'fileCTV', 'fileOAR']);

    function applyControls(values, options = {}) {
        Object.entries(values || {}).forEach(([id, saved]) => {
            // Clinical input paths are restored from the selected server
            // workspace, never from a potentially older browser snapshot.
            // Re-applying a stale empty path after CT hydration was the root
            // cause of viewers and the Input panel disagreeing after a switch.
            if (options.preserveClinicalData && CASE_DATA_CONTROL_IDS.has(id)) return;
            const element = document.getElementById(id);
            if (!element || !saved || typeof saved !== 'object') return;
            if (Object.prototype.hasOwnProperty.call(saved, 'checked')) element.checked = !!saved.checked;
            if (Array.isArray(saved.values) && element.tagName === 'SELECT' && element.multiple) {
                const selected = new Set(saved.values.map(value => String(value)));
                Array.from(element.options || []).forEach(option => {
                    option.selected = selected.has(String(option.value));
                });
                return;
            }
            if (Object.prototype.hasOwnProperty.call(saved, 'value')) {
                const v = Number(saved.value);
                // Saved values ≤ 100 for dose fields are assumed to be in
                // model space (1 = 120 Gy) and converted to physical Gy
                // before display.  Already-converted values > 100 pass
                // through unchanged.
                if (id && Number.isFinite(v) && v <= 100 && GY_VALUE_IDS.has(id)
                    && typeof doseModelToGy === 'function') {
                    element.value = doseModelToGy(v);
                } else {
                    element.value = saved.value;
                }
            }
        });
    }

    function copyDisplayProperties(target, saved) {
        if (!target || !saved || typeof saved !== 'object') return;
        // These are presentation preferences. Never copy label IDs, names,
        // voxel counts, categories, geometry, or planning arrays from a UI
        // snapshot: those values are reconstructed from the current case.
        ['visible', 'opacity', 'color', 'material', 'locked'].forEach(key => {
            if (Object.prototype.hasOwnProperty.call(saved, key)) target[key] = saved[key];
        });
    }

    function applyDataTreePresentation(savedTree) {
        if (!savedTree || typeof savedTree !== 'object' || typeof dataTreeState === 'undefined') return;
        ['ct', 'ctv', 'oar', 'dose', 'seeds', 'needles'].forEach(key => {
            copyDisplayProperties(dataTreeState[key], savedTree[key]);
        });
        if (savedTree.planning && dataTreeState.planning) {
            ['visible', 'opacity', 'color', 'material', 'locked'].forEach(key => {
                if (Object.prototype.hasOwnProperty.call(savedTree.planning, key)) {
                    dataTreeState.planning[key] = savedTree.planning[key];
                }
            });
            // Planning-side meshes, including the patient-specific puncture
            // guide, are reconstructed asynchronously. Restore only their
            // presentation by stable ID so late mesh hydration cannot discard
            // user-selected color, opacity, visibility, or material.
            const savedMeshes = new Map((savedTree.planning.meshes || [])
                .map(item => [String(item?.id || ''), item]));
            (dataTreeState.planning.meshes || []).forEach(mesh => {
                copyDisplayProperties(mesh, savedMeshes.get(String(mesh?.id || '')));
            });
        }
        const savedLabels = savedTree.ctvLabels || {};
        if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
        Object.entries(savedLabels).forEach(([id, saved]) => {
            const current = dataTreeState.ctvLabels[id] || {};
            dataTreeState.ctvLabels[id] = current;
            copyDisplayProperties(current, saved);
        });
        const byId = new Map((savedTree.organs || []).map(item => [String(item?.id || ''), item]));
        const byLabel = new Map((savedTree.organs || []).map(item => [String(item?.labelId ?? ''), item]));
        (dataTreeState.organs || []).forEach(organ => {
            const saved = byId.get(String(organ.id)) || byLabel.get(String(organ.labelId));
            copyDisplayProperties(organ, saved);
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

    async function applyWorkspaceSnapshot(snapshot, options = {}) {
        if (!snapshot) return;
        const sessionId = workspaceSnapshotSessionId(snapshot);
        if (!sessionId || sessionId !== String(activeSessionId || '')) return false;
        rememberWorkspaceRevision(snapshot);
        const ui = snapshot.ui || {};
        const uiState = ui.state || ui;
        const restoreGeneration = invalidateDeferredWorkspaceRestore();
        restoring = true;
        try {
            applyControls(uiState.controls || {}, options);
            if (uiState.viewer && typeof state !== 'undefined') {
                state.slices = Object.assign(state.slices || {}, uiState.viewer.slices || {});
                state.viewerSettings = Object.assign(state.viewerSettings || {}, uiState.viewer.settings || {});
                if (uiState.viewer.doseOpacity != null) state.doseOpacity = uiState.viewer.doseOpacity;
                if (uiState.viewer.doseTexture) state.doseTexture = Object.assign(state.doseTexture || {}, uiState.viewer.doseTexture);
            }
            if (uiState.data_tree && typeof dataTreeState !== 'undefined') {
                if (options.preserveClinicalData) applyDataTreePresentation(uiState.data_tree);
                else Object.assign(dataTreeState, uiState.data_tree);
            }
            if (!options.preserveClinicalData && uiState.manual && typeof _saveManualState === 'function') {
                _saveManualState(uiState.manual);
            }
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
            if (sessionId !== String(activeSessionId || '')) return false;
            window._sessionChatQueues = window._sessionChatQueues || {};
            window._sessionChatQueues[sessionId] = Array.isArray(chat.queued) ? jsonClone(chat.queued) : [];
            window._sessionChatTaskStatuses = window._sessionChatTaskStatuses || {};
            if (chat.task_id) {
                window._sessionChatTaskIds = window._sessionChatTaskIds || {};
                window._sessionChatTaskIds[sessionId] = chat.task_id;
                window._sessionChatTaskStatuses[sessionId] = chat.task_status || 'running';
            } else {
                delete window._sessionChatTaskIds?.[sessionId];
                delete window._detachedChatTasks?.[sessionId];
                window._sessionChatTaskStatuses[sessionId] = chat.task_status || 'idle';
            }
            if (!options.skipChat && Array.isArray(chat.messages) && typeof sessions !== 'undefined' && sessions[sessionId]) {
                // Preserve live browser-side messages that arrived after the
                // last server save (e.g. detached bot responses during a
                // session switch).  If the local copy has more messages than
                // the snapshot the browser is more up-to-date; otherwise the
                // snapshot is authoritative (page refresh, stale cache).
                const localMsgs = sessions[sessionId].messages || [];
                if (chat.messages.length >= localMsgs.length) {
                    sessions[sessionId].messages = chat.messages;
                }
                sessions[sessionId].pending = false;
                if (typeof loadSessionChat === 'function' && sessionId === String(activeSessionId || '')) {
                    loadSessionChat(sessionId);
                }
            }
            renderRecoveryNotice(snapshot.operation);
            if (!options.skipTaskResume && !options.skipChat
                && typeof window.resumeSessionChatTask === 'function') {
                // The selected-case task endpoint is authoritative. Query it
                // even when the snapshot raced with task finalization, so a
                // case switch/refresh never loses a live trace or spinner.
                // Capture the case identity. A stale timer must never resume
                // whichever case happens to become active after a rapid
                // subsequent switch.
                const resumeSessionId = sessionId;
                setTimeout(() => {
                    if (String(activeSessionId || '') !== resumeSessionId) return;
                    void window.resumeSessionChatTask();
                }, 0);
            }
            if (typeof setViewerLayout === 'function' && state?.viewerSettings?.layout) setViewerLayout(state.viewerSettings.layout);
            if (typeof renderDataTree === 'function') renderDataTree();
            if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
            restoreSceneView(uiState.viewer?.scene, uiState.viewer?.dvh, restoreGeneration);
            // The printable guide is a persisted clinical artifact, but its
            // mesh is loaded separately from the lightweight workspace JSON.
            // Bind the async restoration to this snapshot's session so a
            // rapid case switch cannot leak a guide into another viewer.
            if (typeof window.loadSurgicalGuideMesh === 'function') {
                const guideSessionId = sessionId;
                setTimeout(() => {
                    if (String(activeSessionId || '') === guideSessionId) {
                        void window.loadSurgicalGuideMesh({ sessionId: guideSessionId });
                    }
                }, 0);
            }
            return true;
        } finally {
            restoring = false;
        }
    }

    async function persistWorkspace(reason) {
        if (restoring || !window.brachybotAuth?.user || !activeSessionId) return;
        const ownerSessionId = String(activeSessionId);
        const ownerRevision = sessionRevisions[ownerSessionId] ?? revision;
        const payload = {
            session_id: ownerSessionId,
            revision: ownerRevision,
            ui_state: workspaceUiState(),
            report: reportState(),
            chat: chatState(),
            reason,
        };
        try {
            const response = await workspaceFetch('/api/workspace/state', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-BrachyBot-Session': ownerSessionId,
                },
                body: JSON.stringify(payload),
            });
            const data = await response.json().catch(() => null);
            if (response.status === 409) {
                if (data?.code === 'workspace_locked' && ownerSessionId === String(activeSessionId || '')) {
                    document.body.classList.add('workspace-readonly');
                }
                if (data?.code === 'stale_workspace' && ownerSessionId === String(activeSessionId || '')) {
                    console.debug('[workspace] stale save skipped; authoritative snapshot will refresh the revision');
                }
                return;
            }
            if (data?.success) {
                sessionRevisions[ownerSessionId] = data.revision;
                if (ownerSessionId === String(activeSessionId || '')) revision = data.revision;
            }
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
        // A case switch changes the visible workspace, not the case-owned
        // computation. Detach the browser stream without calling /chat/abort;
        // the task remains alive and is replayed when this case is selected.
        if (active && typeof window.detachActiveChatTurn === 'function') {
            window.detachActiveChatTurn('Session changed');
        }
        // Hidden screenshot/visual follow-ups are queued per case. They must
        // wait for that case to become active again, never leak into the next.
        return true;
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
            const existing = (typeof sessions !== 'undefined' && sessions?.[entry.id]) || null;
            const fresh = sessionStateFromPayload(entry);
            if (existing) {
                fresh.messages = Array.isArray(existing.messages) ? existing.messages : [];
                fresh.pending = !!existing.pending;
            }
            next[entry.id] = fresh;
        });
        return next;
    }

    function applySessionList(data) {
        sessions = sessionMapFromPayload(data);
        activeSessionId = data.active_session_id;
    }

    function paintSessionShell(sessionId, { clearWorkspace = true } = {}) {
        // Case selection is a control-plane action. Paint the selected case
        // immediately, then hydrate CT/labels/meshes asynchronously. Waiting
        // for a snapshot or a lazy Agent restore here makes a simple sidebar
        // click look like the application has frozen.
        const next = sessions[sessionId];
        if (!next) return false;
        // Cancel only browser-side hydration/render callbacks from the old
        // case. This does not contact /chat/abort and therefore cannot stop a
        // case-owned background planning or chat task.
        cancelBackgroundWorkspaceRestore();
        activeSessionId = sessionId;
        if (typeof state !== 'undefined') state.sessionId = sessionId;
        revision = sessionRevisions[sessionId] ?? null;
        window._activeWorkspaceSnapshot = null;
        if (clearWorkspace && typeof clearClientWorkspace === 'function') {
            clearClientWorkspace({ clearReport: true, deferDisposal: true });
        }
        renderSessionList();
        const title = document.getElementById('chatSessionTitle');
        if (title) title.textContent = next.title || 'New case';
        // Do not leave the prior transcript beneath an optimistically
        // highlighted case. A durable chat snapshot replaces this shell as
        // soon as the control-plane response arrives.
        if (typeof loadSessionChat === 'function') loadSessionChat(sessionId);
        window.setWorkspaceHydrationState?.(
            true,
            typeof window._t === 'function'
                ? window._t('\u6b63\u5728\u6253\u5f00\u75c5\u4f8b...', 'Opening case...')
                : 'Opening case...',
        );
        return true;
    }

    async function loadServerSessions({ commit = true, timeoutMs = WORKSPACE_REQUEST_TIMEOUT_MS } = {}) {
        const response = await workspaceFetch('/api/sessions', {}, timeoutMs);
        if (!response.ok) throw new Error(`Session list failed: HTTP ${response.status}`);
        const data = await response.json();
        if (commit) applySessionList(data);
        return data;
    }

    async function loadActiveWorkspace({
        commit = true,
        timeoutMs = WORKSPACE_REQUEST_TIMEOUT_MS,
        sessionId = String(activeSessionId || ''),
    } = {}) {
        const response = await workspaceFetch('/api/workspace/snapshot', {
            headers: sessionId ? { 'X-BrachyBot-Session': sessionId } : {},
        }, timeoutMs);
        if (!response.ok) throw new Error(`Workspace snapshot failed: HTTP ${response.status}`);
        const data = await response.json();
        if (sessionId && workspaceSnapshotSessionId(data.workspace) !== sessionId) {
            throw new Error('Workspace snapshot belongs to a different case');
        }
        if (commit) {
            revision = data.workspace?.session?.revision ?? null;
            rememberWorkspaceRevision(data.workspace);
            window._activeWorkspaceSnapshot = data.workspace;
        }
        return data.workspace;
    }

    async function refreshSessionAfterTaskCompletion(sessionId) {
        const ownerSessionId = String(sessionId || '');
        if (!ownerSessionId || ownerSessionId !== String(activeSessionId || '')) return false;
        const workspace = await loadActiveWorkspace({
            commit: false,
            sessionId: ownerSessionId,
        });
        if (ownerSessionId !== String(activeSessionId || '')) return false;
        rememberWorkspaceRevision(workspace);
        revision = workspace?.session?.revision ?? revision;
        window._activeWorkspaceSnapshot = workspace;
        applyChatSnapshotFast(workspace);
        await applyWorkspaceSnapshot(workspace, {
            preserveClinicalData: true,
            skipTaskResume: true,
        });
        // The completed task may have produced CT labels, planning arrays,
        // DVH data, report fields, or meshes while this case was not visible.
        // Replace any stale in-flight hydration with one authoritative pass.
        scheduleBackgroundWorkspaceRestore(workspace, ownerSessionId);
        return true;
    }

    async function recoverWorkspaceAfterTransitionFailure(generation) {
        try {
            const sessionData = await loadServerSessions({ commit: false, timeoutMs: WORKSPACE_RECOVERY_TIMEOUT_MS });
            const workspace = await loadActiveWorkspace({ commit: false, timeoutMs: WORKSPACE_RECOVERY_TIMEOUT_MS });
            if (!isCurrentTransition(generation)) return;
            applySessionList(sessionData);
            revision = workspace?.session?.revision ?? null;
            rememberWorkspaceRevision(workspace);
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
        const workspace = await loadActiveWorkspace();
        // Paint the durable transcript before /status and clinical hydration.
        // The latter may load CT, labels, meshes, dose arrays, and an agent;
        // none of that should make a restored conversation look missing.
        applyChatSnapshotFast(workspace);
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
            const previousSessionId = String(activeSessionId || '');
            if (typeof flushActiveReportState === 'function') flushActiveReportState();
            // Persistence is case-scoped and already captures the old active
            // id synchronously. Do not make creating an empty case wait for a
            // potentially slow disk/GPU snapshot of the previous case.
            void persistWorkspace('session.switching');
            // Paint a genuinely empty case on the next animation frame instead
            // of holding the previous transcript and viewer until the server
            // has allocated an id. The temporary id cannot reach a clinical
            // endpoint because workspace transitions keep controls disabled.
            const optimisticId = `pending-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            sessions[optimisticId] = {
                id: optimisticId,
                title: 'New case',
                created: Date.now(),
                updated: Date.now(),
                messages: [],
                pending: true,
                recoveryStatus: 'clean',
            };
            paintSessionShell(optimisticId);
            await new Promise(resolve => {
                if (typeof requestAnimationFrame === 'function') requestAnimationFrame(resolve);
                else setTimeout(resolve, 0);
            });
            const response = await workspaceFetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'New case' }) });
            const data = await response.json();
            if (!response.ok) {
                delete sessions[optimisticId];
                if (previousSessionId && sessions[previousSessionId]) paintSessionShell(previousSessionId);
                throw new Error(data.error || 'Unable to create case');
            }
            const createdSession = data.session;
            delete sessions[optimisticId];
            if (createdSession?.id) {
                // The create endpoint returns the authoritative session entry.
                // Upsert it before rendering so the sidebar reacts immediately
                // without a second list request or a delayed chat checkpoint.
                sessions[createdSession.id] = sessionStateFromPayload(createdSession);
            }
            activeSessionId = data.active_session_id || createdSession?.id || activeSessionId;
            if (typeof state !== 'undefined') state.sessionId = activeSessionId;
            revision = data.workspace?.session?.revision ?? null;
            rememberWorkspaceRevision(data.workspace);
            window._activeWorkspaceSnapshot = data.workspace || null;
            renderSessionList();
            // `clearClientWorkspace` resets rendering state, but the chat DOM
            // is owned by the session message store. Explicitly load the new
            // empty transcript so the previous case cannot remain visible
            // under the newly highlighted session.
            if (typeof loadSessionChat === 'function') loadSessionChat(activeSessionId);
            window.setWorkspaceHydrationState?.(false);
            if (data.lease && typeof window.brachybotAuth?.applyLeaseResult === 'function') {
                window.brachybotAuth.applyLeaseResult(data.lease);
            } else if (typeof window.brachybotAuth?.acquireLease === 'function') {
                // Lease acquisition is a control-plane refresh. The empty
                // case is usable immediately; update editability in the
                // background instead of blocking the sidebar transition.
                void window.brachybotAuth.acquireLease().catch(error => console.debug('[workspace] lease refresh deferred:', error));
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
            const previousSessionId = activeSessionId;
            if (typeof flushActiveReportState === 'function') flushActiveReportState();
            // Persist the current session's chat messages, report form, and UI
            // state before the switch so the server snapshot is up-to-date when
            // applyWorkspaceSnapshot overwrites sessions[id].messages later.
            await persistWorkspace('session.switching').catch(error => console.debug('[workspace] persist before switch deferred:', error));
            // The old lease is released before changing the active id, but a
            // slow lease endpoint must not hold the visible case switch.
            if (typeof window.brachybotAuth?.releaseLease === 'function') {
                void window.brachybotAuth.releaseLease(previousSessionId).catch(error => console.debug('[workspace] lease release deferred:', error));
            }
            // Show a switching indicator without changing activeSessionId or
            // clearing the workspace. The server request is a fast control-
            // plane round-trip; deferring the full shell paint until after
            // confirmation avoids the disorienting bounce when a select call
            // fails (timeout, auth expiry, stale csrf).
            window.setWorkspaceHydrationState?.(
                true,
                typeof window._t === 'function'
                    ? window._t('正在切换病例…', 'Switching case…')
                    : 'Switching case…',
            );
            document.body.classList.add('workspace-hydrating');
            let response;
            try {
                response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}/select`, { method: 'POST' });
            } catch (error) {
                document.body.classList.remove('workspace-hydrating');
                window.setWorkspaceHydrationState?.(false);
                throw error;
            }
            const data = await response.json();
            if (!response.ok) {
                document.body.classList.remove('workspace-hydrating');
                window.setWorkspaceHydrationState?.(false);
                throw new Error(data.error || 'Unable to open case');
            }
            // Server confirmed the switch. Paint the session shell now.
            activeSessionId = data.active_session_id;
            if (typeof state !== 'undefined') state.sessionId = data.active_session_id;
            revision = data.workspace?.session?.revision ?? null;
            rememberWorkspaceRevision(data.workspace);
            window._activeWorkspaceSnapshot = data.workspace;
            cancelBackgroundWorkspaceRestore();
            if (typeof clearClientWorkspace === 'function') {
                clearClientWorkspace({ clearReport: true, deferDisposal: true });
            }
            renderSessionList();
            const titleEl = document.getElementById('chatSessionTitle');
            if (titleEl) titleEl.textContent = sessions[id]?.title || 'New case';
            if (typeof loadSessionChat === 'function') loadSessionChat(data.active_session_id);
            if (typeof applyWorkspaceSnapshot === 'function') {
                // The selected Agent has not been hydrated yet. Restore only
                // durable presentation/chat state here; CT/labels/plan are
                // loaded by the background transaction from the server.
                await applyWorkspaceSnapshot(data.workspace, { preserveClinicalData: true });
            }
            scheduleBackgroundWorkspaceRestore(data.workspace, activeSessionId);
            if (typeof window.brachybotAuth?.acquireLease === 'function') {
                void window.brachybotAuth.acquireLease(activeSessionId).catch(error => console.debug('[workspace] lease refresh deferred:', error));
            }
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
        // It must not call prepareSessionChange(): the deleted case is not the
        // case currently being edited. Keeping this path separate preserves
        // the selected case's live task subscription, viewer, and controls.
        if (id !== activeSessionId) {
            const removedSession = sessions[id];
            // Sidebar deletion is optimistic. The server operation is still
            // authoritative, but a slow disk cleanup must not make the delete
            // button appear unresponsive.
            delete sessions[id];
            renderSessionList();
            try {
                const response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.error || 'Unable to delete case');
                void loadServerSessions().then(() => renderSessionList()).catch(error => console.debug('[workspace] session list refresh deferred:', error));
                return { success: true, active_session_id: activeSessionId };
            } catch (error) {
                // A timeout can happen after the server committed deletion.
                // Restore the row provisionally; the next authoritative list
                // refresh removes it again when appropriate.
                if (removedSession) sessions[id] = removedSession;
                renderSessionList();
                void loadServerSessions().then(() => renderSessionList()).catch(() => {});
                console.error('[workspace] inactive case deletion failed:', error);
                return { success: false, error: error?.message || 'Unable to delete case.' };
            }
        }

        return runWorkspaceTransition(async () => {
            // Deletion is the one case-management action that must cancel
            // the case-owned task: there will be no workspace to resume it
            // from after the recycle-bin move.
            if (id === activeSessionId && typeof window.cancelActiveChatTurn === 'function') {
                await window.cancelActiveChatTurn('Session deleted');
            }
            if (!await prepareSessionChange()) return { success: false, cancelled: true };
            if (id === activeSessionId && typeof flushActiveReportState === 'function') flushActiveReportState();
            void persistWorkspace('session.delete');
            if (id === activeSessionId && typeof window.brachybotAuth?.releaseLease === 'function') {
                void window.brachybotAuth.releaseLease().catch(error => console.debug('[workspace] lease release deferred:', error));
            }
            const response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Unable to delete case');
            if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true, deferDisposal: true });
            activeSessionId = data.active_session_id || activeSessionId;
            revision = data.workspace?.session?.revision ?? null;
            rememberWorkspaceRevision(data.workspace);
            window._activeWorkspaceSnapshot = data.workspace || null;
            renderSessionList();
            if (typeof window.brachybotAuth?.acquireLease === 'function') await window.brachybotAuth.acquireLease();
            if (data.workspace && typeof applyWorkspaceSnapshot === 'function') {
                await applyWorkspaceSnapshot(data.workspace);
            }
            scheduleBackgroundWorkspaceRestore(data.workspace || null, activeSessionId);
            // Reconcile titles/order and refresh editability after the new
            // case is already visible.
            void loadServerSessions().then(() => renderSessionList()).catch(error => console.debug('[workspace] session list refresh deferred:', error));
            if (typeof window.brachybotAuth?.acquireLease === 'function') {
                void window.brachybotAuth.acquireLease().catch(error => console.debug('[workspace] lease refresh deferred:', error));
            }
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
    window.applyChatSnapshotFast = applyChatSnapshotFast;
    window.loadServerSessions = loadServerSessions;
    window.refreshSessionAfterTaskCompletion = refreshSessionAfterTaskCompletion;
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
