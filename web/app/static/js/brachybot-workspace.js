/* Durable case workspace bridge: server sessions own all clinical state. */
(function () {
    let revision = null;
    let saveTimer = null;
    let restoring = false;

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
        const target = document.getElementById('workspaceRecoveryNotice');
        if (!target) return;
        if (operation?.state !== 'interrupted') {
            target.hidden = true;
            target.textContent = '';
            return;
        }
        const checkpoint = operation.checkpoint || {};
        const step = checkpoint.step ? ` Resume from ${checkpoint.step}.` : '';
        target.textContent = `${operation.message || 'The previous task was interrupted.'}${step} The last saved case state is available; rerun the unfinished action when ready.`;
        target.hidden = false;
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

    function restoreSceneView(scene, dvh) {
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
        setTimeout(applyScene, 450);
        setTimeout(applyScene, 1200);

        const applyDvh = () => {
            const chart = document.getElementById('dvhChart');
            if (!dvh || !chart || typeof Plotly === 'undefined' || !Plotly.relayout) return;
            const update = {};
            if (Array.isArray(dvh.x_range) && dvh.x_range.length === 2) update['xaxis.range'] = dvh.x_range;
            if (Array.isArray(dvh.y_range) && dvh.y_range.length === 2) update['yaxis.range'] = dvh.y_range;
            if (dvh.axis_zoom_mode) chart._dvhAxisZoomMode = dvh.axis_zoom_mode;
            if (Object.keys(update).length) Plotly.relayout(chart, update);
        };
        setTimeout(applyDvh, 350);
        setTimeout(applyDvh, 1100);

        if (scene?.display_mode === 'dose_surface' && typeof setDoseTextureMode === 'function') {
            // Recreate textures from the restored dose grid; WebGL materials
            // themselves are intentionally not persisted in the workspace.
            setTimeout(() => setDoseTextureMode(true, { silent: true }), 900);
        }
    }

    async function applyWorkspaceSnapshot(snapshot) {
        if (!snapshot) return;
        const ui = snapshot.ui || {};
        const uiState = ui.state || ui;
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
            if (chat.messages && typeof sessions !== 'undefined' && activeSessionId && sessions[activeSessionId]) {
                sessions[activeSessionId].messages = chat.messages;
                sessions[activeSessionId].pending = !!chat.pending;
            }
            renderRecoveryNotice(snapshot.operation);
            if (typeof setViewerLayout === 'function' && state?.viewerSettings?.layout) setViewerLayout(state.viewerSettings.layout);
            if (typeof renderDataTree === 'function') renderDataTree();
            if (typeof _refreshManualStepUI === 'function') _refreshManualStepUI();
            restoreSceneView(uiState.viewer?.scene, uiState.viewer?.dvh);
        } finally {
            restoring = false;
        }
    }

    async function persistWorkspace(reason) {
        if (restoring || !window.brachybotAuth?.user || !activeSessionId) return;
        try {
            const response = await fetch('/api/workspace/state', {
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
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(() => persistWorkspace(reason || 'ui.changed'), 700);
    }

    async function loadServerSessions() {
        const response = await fetch('/api/sessions');
        if (!response.ok) throw new Error(`Session list failed: HTTP ${response.status}`);
        const data = await response.json();
        sessions = {};
        (data.sessions || []).forEach(entry => {
            sessions[entry.id] = {
                id: entry.id,
                title: entry.title,
                created: Math.round(Number(entry.created_at || Date.now() / 1000) * 1000),
                updated: Math.round(Number(entry.updated_at || Date.now() / 1000) * 1000),
                messages: [],
                recoveryStatus: entry.recovery_status,
            };
        });
        activeSessionId = data.active_session_id;
        return data;
    }

    async function loadActiveWorkspace() {
        const response = await fetch('/api/workspace/snapshot');
        if (!response.ok) throw new Error(`Workspace snapshot failed: HTTP ${response.status}`);
        const data = await response.json();
        revision = data.workspace?.session?.revision ?? null;
        window._activeWorkspaceSnapshot = data.workspace;
        return data.workspace;
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
        if (typeof _canChangeChatSession === 'function' && !_canChangeChatSession()) return;
        if (typeof flushActiveReportState === 'function') flushActiveReportState();
        await persistWorkspace('session.switching');
        if (typeof window.brachybotAuth?.releaseLease === 'function') await window.brachybotAuth.releaseLease();
        const response = await fetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'New case' }) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to create case');
        await loadServerSessions();
        if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true });
        await loadActiveWorkspace();
        renderSessionList();
        if (typeof window.brachybotAuth?.acquireLease === 'function') await window.brachybotAuth.acquireLease();
        if (typeof restoreActiveSessionWorkspace === 'function') await restoreActiveSessionWorkspace({ clearReport: false });
        loadSessionChat(activeSessionId);
    };

    window.switchSession = async function switchSession(id) {
        document.getElementById('sessionSidebar')?.classList.remove('mobile-open');
        if (id === activeSessionId || !sessions[id] || (typeof _canChangeChatSession === 'function' && !_canChangeChatSession())) return;
        if (typeof flushActiveReportState === 'function') flushActiveReportState();
        await persistWorkspace('session.switching');
        if (typeof window.brachybotAuth?.releaseLease === 'function') await window.brachybotAuth.releaseLease();
        const response = await fetch(`/api/sessions/${encodeURIComponent(id)}/select`, { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to open case');
        activeSessionId = data.active_session_id;
        revision = data.workspace?.session?.revision ?? null;
        if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true });
        window._activeWorkspaceSnapshot = data.workspace;
        renderSessionList();
        if (typeof window.brachybotAuth?.acquireLease === 'function') await window.brachybotAuth.acquireLease();
        if (typeof restoreActiveSessionWorkspace === 'function') await restoreActiveSessionWorkspace({ clearReport: false, workspace: data.workspace });
        loadSessionChat(activeSessionId);
    };

    window.deleteSession = async function deleteSession(id, options = {}) {
        if (!sessions[id] || (typeof _canChangeChatSession === 'function' && !_canChangeChatSession())) return;
        if (options.skipConfirm !== true && !window.confirm(`Move case "${sessions[id].title || id}" to the recycle bin?`)) return;
        if (id === activeSessionId && typeof flushActiveReportState === 'function') flushActiveReportState();
        await persistWorkspace('session.delete');
        if (id === activeSessionId && typeof window.brachybotAuth?.releaseLease === 'function') await window.brachybotAuth.releaseLease();
        const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to delete case');
        await loadServerSessions();
        if (typeof clearClientWorkspace === 'function') clearClientWorkspace({ clearReport: true });
        await loadActiveWorkspace();
        renderSessionList();
        if (typeof window.brachybotAuth?.acquireLease === 'function') await window.brachybotAuth.acquireLease();
        if (typeof restoreActiveSessionWorkspace === 'function') await restoreActiveSessionWorkspace({ clearReport: false });
        loadSessionChat(activeSessionId);
    };

    window.renameServerSession = async function renameServerSession(id, title) {
        const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) });
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
        if (!window.confirm(`Permanently delete "${title || 'this case'}"? This cannot be undone.`)) return;
        const response = await fetch(`/api/sessions/${encodeURIComponent(id)}/purge`, { method: 'DELETE' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to permanently delete case');
        await window.openRecycleBin();
    };

    window.scheduleWorkspaceSave = scheduleWorkspaceSave;
    window.persistWorkspace = persistWorkspace;
    window.applyWorkspaceSnapshot = applyWorkspaceSnapshot;
    window.loadServerSessions = loadServerSessions;

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
