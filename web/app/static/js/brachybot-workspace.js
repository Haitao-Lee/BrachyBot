/* Durable case workspace bridge: server sessions own all clinical state. */
(function () {
    // This flag lets compatibility shims in the older chat script route
    // direct global calls to the durable workspace implementation.
    window.__serverWorkspaceReady = true;
    let revision = null;
    const sessionRevisions = Object.create(null);
    let saveTimer = null;
    const workspaceSaveInFlight = Object.create(null);
    const workspaceSaveQueuedReasons = Object.create(null);
    let restoring = false;
    let workspaceTransition = null;
    let pendingSessionCreationId = null;
    let pendingSwitchSessionId = null;
    let _switchAbortController = null;
    let workspaceTransitionGeneration = 0;
    let workspaceRestoreGeneration = 0;
    const workspaceRestoreTimers = new Set();
    let backgroundRestoreGeneration = 0;
    let backgroundRestoreTimer = null;
    let backgroundRestoreRetryTimer = null;
    const backgroundRestoreRetryCounts = Object.create(null);
    let backgroundRestoreNoticeTimer = null;
    let hydrationHideTimer = null;
    // Dose controls are persisted in physical Gy. Legacy snapshots that
    // explicitly used model units are converted with their saved calibration.
    const GY_VALUE_IDS = new Set(['inLowestEnergy', 'outHighestEnergy']);
    const WORKSPACE_REQUEST_TIMEOUT_MS = 15000;
    const WORKSPACE_RECOVERY_TIMEOUT_MS = 5000;
    let recoveryNoticeDismissKey = '';

    function workspaceNow() {
        return typeof performance !== 'undefined' && typeof performance.now === 'function'
            ? performance.now()
            : Date.now();
    }

    function recordWorkspacePerformance(stage, options = {}) {
        const startedAt = Number(options.startedAt);
        const entry = {
            stage: String(stage || 'unknown'),
            session_id: String(options.sessionId || activeSessionId || ''),
            at: Date.now(),
            duration_ms: Number.isFinite(startedAt)
                ? Math.max(0, Number((workspaceNow() - startedAt).toFixed(1)))
                : null,
            details: options.details && typeof options.details === 'object'
                ? Object.assign({}, options.details)
                : {},
        };
        window.__workspacePerformance = Array.isArray(window.__workspacePerformance)
            ? window.__workspacePerformance
            : [];
        window.__workspacePerformance.push(entry);
        if (window.__workspacePerformance.length > 250) {
            window.__workspacePerformance.splice(0, window.__workspacePerformance.length - 250);
        }
        console.info('[workspace-perf]', entry);
        try {
            window.dispatchEvent(new CustomEvent('brachybot:workspace-performance', { detail: entry }));
        } catch (_) {}
        return entry;
    }
    window.recordWorkspacePerformance = recordWorkspacePerformance;

    async function workspaceFetch(input, init = {}, timeoutMs = WORKSPACE_REQUEST_TIMEOUT_MS) {
        const controller = typeof AbortController === 'function' ? new AbortController() : null;
        const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
        const externalSignal = init?.signal || null;
        try {
            const options = Object.assign({}, init);
            // Honour an externally-supplied signal (e.g. transition abort) by
            // chaining the internal timeout ­— if the external signal fires
            // first it cancels the fetch, otherwise our timer does.
            if (controller && options.signal) {
                const external = options.signal;
                const chained = new AbortController();
                if (external.aborted) chained.abort();
                else external.addEventListener('abort', () => chained.abort(), { once: true });
                if (controller.signal.aborted) chained.abort();
                else controller.signal.addEventListener('abort', () => chained.abort(), { once: true });
                options.signal = chained.signal;
            } else if (controller) {
                options.signal = controller.signal;
            }
            return await fetch(input, options);
        } catch (error) {
            if (error?.name === 'AbortError') {
                if (externalSignal?.aborted) throw error;
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
        // Invalidate the clinical restore wrapper as well as this module's
        // scheduling generation. A new/selected case must never inherit the
        // previous case's delayed spinner or resource callbacks.
        window.__workspaceHydrationRunId = (window.__workspaceHydrationRunId || 0) + 1;
        if (backgroundRestoreTimer) {
            clearTimeout(backgroundRestoreTimer);
            backgroundRestoreTimer = null;
        }
        if (backgroundRestoreRetryTimer) {
            clearTimeout(backgroundRestoreRetryTimer);
            backgroundRestoreRetryTimer = null;
        }
        Object.keys(backgroundRestoreRetryCounts).forEach(key => delete backgroundRestoreRetryCounts[key]);
        if (backgroundRestoreNoticeTimer) {
            clearTimeout(backgroundRestoreNoticeTimer);
            backgroundRestoreNoticeTimer = null;
        }
        window.__workspaceRestoreScheduledSessionId = null;
        window.__workspaceRestoreCompletedSessionId = null;
        document.body.classList.remove('workspace-hydrating');
        window.setWorkspaceHydrationState?.(false, '', { immediate: true });
    }

    window.setWorkspaceHydrationState = function setWorkspaceHydrationState(active, message, scope = null) {
        const notice = document.getElementById('workspaceHydrationNotice');
        if (!notice) return;
        const scopedSession = String(scope?.sessionId || '');
        const scopedRun = String(scope?.runId || '');
        const immediate = scope?.immediate === true;
        if (!active && scope && !immediate) {
            if ((scopedSession && notice.dataset.sessionId !== scopedSession)
                || (scopedRun && notice.dataset.runId !== scopedRun)) return;
        }
        const target = document.getElementById('workspaceHydrationMessage');
        if (target && message) target.textContent = message;
        if (hydrationHideTimer) {
            clearTimeout(hydrationHideTimer);
            hydrationHideTimer = null;
        }
        // Cancel any in-progress exit animation so a rapid show-hide or
        // show-again transition does not leave the notice stuck mid-animation.
        notice.getAnimations().forEach(a => a.cancel());
        notice.classList.remove('workspace-hydration-out');
        if (active) {
            if (scopedSession) notice.dataset.sessionId = scopedSession;
            if (scopedRun) notice.dataset.runId = scopedRun;
            notice.hidden = false;
        } else if (immediate) {
            notice.hidden = true;
            notice.classList.remove('workspace-hydration-out');
            delete notice.dataset.sessionId;
            delete notice.dataset.runId;
        } else {
            notice.classList.add('workspace-hydration-out');
            notice.addEventListener('animationend', function handler() {
                notice.removeEventListener('animationend', handler);
                // Only hide if the exit animation wasn't cancelled by a
                // subsequent show call (which removes the out class).
                if (notice.classList.contains('workspace-hydration-out')) {
                    notice.hidden = true;
                    notice.classList.remove('workspace-hydration-out');
                    delete notice.dataset.sessionId;
                    delete notice.dataset.runId;
                }
            }, { once: true });
            // Some embedded browsers do not dispatch animationend when the
            // element is hidden during a fast session transition. The
            // fallback prevents a stale "Opening/Loading" notice forever.
            hydrationHideTimer = setTimeout(() => {
                if (notice.classList.contains('workspace-hydration-out')) {
                    notice.hidden = true;
                    notice.classList.remove('workspace-hydration-out');
                    delete notice.dataset.sessionId;
                    delete notice.dataset.runId;
                }
                hydrationHideTimer = null;
            }, 700);
        }
        document.body.classList.toggle('workspace-hydrating', !!active);
    };

    // Cold-start hydration and a user-initiated session switch are the same
    // user-facing operation: resources for the selected case are arriving in
    // the background. Keep them on the one non-blocking lower-right notice.
    window.showCaseResourceLoading = function showCaseResourceLoading(scope = null) {
        window.setWorkspaceHydrationState?.(
            true,
            typeof window._t === 'function'
                ? window._t('正在加载病例资源…', 'Loading case resources...')
                : 'Loading case resources...',
            scope,
        );
    };

    function workspaceSnapshotHasClinicalResources(snapshot) {
        if (!snapshot || typeof snapshot !== 'object') return false;
        const agent = snapshot.agent && typeof snapshot.agent === 'object' ? snapshot.agent : {};
        const results = agent.planning_results && typeof agent.planning_results === 'object'
            ? agent.planning_results : {};
        const uiState = agent.ui_state && typeof agent.ui_state === 'object' ? agent.ui_state : {};
        const controls = snapshot.ui?.state?.controls || snapshot.ui?.controls || {};
        const pathValue = (value) => {
            if (typeof value === 'string') return value.trim();
            return value && typeof value.value === 'string' ? value.value.trim() : '';
        };
        const paths = [
            results.ct_path,
            results.ctPath,
            results.ct_image_path,
            uiState.ct_path,
            uiState.ctPath,
            pathValue(controls.ctPath),
            pathValue(controls.ctImagePath),
        ];
        if (paths.some(Boolean)) return true;
        // The empty snapshot deliberately has no planning result keys. These
        // keys are the durable data-plane contract and avoid treating a stale
        // UI-only snapshot as a clinical case that needs hydration.
        return [
            'ct_data', 'ct_image', 'ctv_array', 'ctv_mask', 'oar_array',
            'dose_distribution', 'dose_distribution_gy', 'dose_metrics',
            'trajectories', 'seed_plan', 'seed_plan_serialized',
            'surgical_guide',
        ].some(key => Object.prototype.hasOwnProperty.call(results, key))
            || Object.keys(results).some(key => key === 'planning_runs'
                || key.startsWith('planning_run:'));
    }
    window.workspaceSnapshotHasClinicalResources = workspaceSnapshotHasClinicalResources;

    function scheduleBackgroundWorkspaceRestore(workspace, sessionId) {
        if (String(sessionId || '') !== String(activeSessionId || '')
            || !workspaceSnapshotHasClinicalResources(workspace)) {
            cancelBackgroundWorkspaceRestore();
            console.debug('[workspace] background restore skipped: empty or stale case', sessionId);
            return;
        }
        const generation = ++backgroundRestoreGeneration;
        const restoreStartedAt = workspaceNow();
        // Startup and session switching share this scheduler. The init path
        // must be able to see that a restore is already scheduled, otherwise
        // a browser restart launches a second CT/plan hydration in parallel.
        window.__workspaceRestoreScheduledSessionId = String(sessionId);
        window.__workspaceRestoreCompletedSessionId = null;
        recordWorkspacePerformance('restore.scheduled', { sessionId });
        if (backgroundRestoreTimer) clearTimeout(backgroundRestoreTimer);
        if (backgroundRestoreNoticeTimer) clearTimeout(backgroundRestoreNoticeTimer);
        // Hydration is deliberately non-blocking.  Keep a small progress hint
        // while the first assets arrive, but never leave a permanent spinner
        // over the chat when a large CT/mesh restore is still running.
        window.setWorkspaceHydrationState?.(
            true,
            typeof window._t === 'function'
                ? window._t('正在恢复病例资源…', 'Restoring case resources...')
                : 'Restoring case resources...',
            { sessionId, runId: generation },
        );
        // Override legacy wording with the shared startup/switch notice.
        window.showCaseResourceLoading?.({ sessionId, runId: generation });
        document.body.classList.add('workspace-hydrating');
        backgroundRestoreNoticeTimer = setTimeout(() => {
            if (generation !== backgroundRestoreGeneration || sessionId !== activeSessionId) return;
            window.setWorkspaceHydrationState?.(
                false,
                typeof window._t === 'function'
                    ? window._t('资源继续在后台加载', 'Resources continue loading in the background')
                : 'Resources continue loading in the background',
                { sessionId, runId: generation },
            );
            backgroundRestoreNoticeTimer = null;
        }, 30000);
        backgroundRestoreTimer = setTimeout(async () => {
            backgroundRestoreTimer = null;
            if (generation !== backgroundRestoreGeneration || sessionId !== activeSessionId) return;
            let restoreSucceeded = false;
            let retryScheduled = false;
            try {
                // The snapshot returned by the fast select endpoint can be
                // one revision behind a task that finished while the case
                // was hidden. Refresh the small JSON snapshot before loading
                // large CT/mesh assets; otherwise a restored case may show
                // its chat while silently missing the just-finished plan.
                let authoritativeWorkspace = workspace;
                try {
                    const response = await workspaceFetch('/api/workspace/snapshot', {
                        headers: { 'X-BrachyBot-Session': String(sessionId) },
                    }, 10000);
                    if (response.ok) {
                        const payload = await response.json();
                        const candidate = payload?.workspace;
                        if (workspaceSnapshotSessionId(candidate) === String(sessionId)) {
                            authoritativeWorkspace = candidate;
                            window._activeWorkspaceSnapshot = candidate;
                            rememberWorkspaceRevision(candidate);
                        }
                    }
                } catch (refreshError) {
                    // The already received snapshot is still a valid fallback
                    // for a temporarily unavailable control-plane request.
                    console.debug('[workspace] fresh snapshot deferred:', refreshError);
                }
                if (typeof restoreActiveSessionWorkspace === 'function') {
                    await restoreActiveSessionWorkspace({
                        clearReport: false,
                        workspace: authoritativeWorkspace,
                        background: true,
                        // The optimistic shell has already cleared the old
                        // case. Do not erase a just-resumed task trace while
                        // the heavier CT/mesh resources hydrate.
                        skipClientClear: true,
                    });
                }
                // Resource hydration deliberately skips chat state so it
                // cannot erase a live replay. Reconcile once more after the
                // heavy phase because a task may have become active or
                // terminal while CT/mesh resources were loading.
                if (generation === backgroundRestoreGeneration
                    && sessionId === activeSessionId
                    && typeof window.resumeSessionChatTask === 'function') {
                    void window.resumeSessionChatTask();
                }
                recordWorkspacePerformance('restore.completed', {
                    sessionId,
                    startedAt: restoreStartedAt,
                });
                restoreSucceeded = true;
            } catch (error) {
                console.warn('[workspace] background case restore failed:', error);
                recordWorkspacePerformance('restore.failed', {
                    sessionId,
                    startedAt: restoreStartedAt,
                    details: { error: error?.message || String(error) },
                });
                const retryKey = String(sessionId || '');
                const retryCount = Number(backgroundRestoreRetryCounts[retryKey] || 0);
                if (generation === backgroundRestoreGeneration
                    && sessionId === activeSessionId
                    && retryCount < 2) {
                    backgroundRestoreRetryCounts[retryKey] = retryCount + 1;
                    retryScheduled = true;
                    const retryDelay = Math.min(5000, 1000 * (retryCount + 1));
                    backgroundRestoreRetryTimer = setTimeout(() => {
                        backgroundRestoreRetryTimer = null;
                        if (generation !== backgroundRestoreGeneration
                            || sessionId !== activeSessionId) return;
                        scheduleBackgroundWorkspaceRestore(
                            window._activeWorkspaceSnapshot || workspace,
                            sessionId,
                        );
                    }, retryDelay);
                    recordWorkspacePerformance('restore.retry_scheduled', {
                        sessionId,
                        startedAt: restoreStartedAt,
                        details: { attempt: retryCount + 1, delay_ms: retryDelay },
                    });
                }
            } finally {
                if (retryScheduled) return;
                if (backgroundRestoreNoticeTimer) {
                    clearTimeout(backgroundRestoreNoticeTimer);
                    backgroundRestoreNoticeTimer = null;
                }
                // The restore wrapper normally clears this state itself. Keep
                // the fallback here so a failed snapshot refresh or a missing
                // loader cannot leave a permanent spinner in the corner.
                if (generation === backgroundRestoreGeneration && sessionId === activeSessionId) {
                    if (restoreSucceeded) delete backgroundRestoreRetryCounts[String(sessionId || '')];
                    window.__workspaceRestoreScheduledSessionId = null;
                    window.__workspaceRestoreCompletedSessionId = restoreSucceeded ? String(sessionId) : null;
                    window.setWorkspaceHydrationState?.(
                        false,
                        '',
                        { sessionId, runId: generation },
                    );
                }
            }
        }, 0);
    }

    function clearScheduledWorkspaceSave() {
        if (!saveTimer) return;
        clearTimeout(saveTimer);
        saveTimer = null;
    }
    // Session transitions cancel the pending timer before the active case
    // changes, so a delayed report save cannot target the new case.
    window.cancelScheduledWorkspaceSave = clearScheduledWorkspaceSave;

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

    function activeSessionReadiness() {
        const sessionId = String(activeSessionId || '');
        const entry = sessionId && typeof sessions !== 'undefined'
            ? sessions?.[sessionId]
            : null;
        const pending = !!entry?.pending
            || (!!pendingSessionCreationId && pendingSessionCreationId === sessionId);
        return {
            sessionId,
            ready: !!sessionId && !!entry && !pending && !workspaceTransition,
            pending,
            transitioning: !!workspaceTransition,
        };
    }

    // Chat, uploads, and other case-owned mutations must wait until the
    // control plane has returned a durable Session ID. The optimistic shell
    // is presentation-only and must never be sent in X-BrachyBot-Session.
    window.activeSessionReadiness = activeSessionReadiness;
    window.awaitActiveSessionReady = async function awaitActiveSessionReady() {
        let transition = workspaceTransition;
        if (transition) {
            const result = await transition;
            if (!result?.success) {
                throw new Error(result?.error || 'The case transition did not complete.');
            }
        }
        let readiness = activeSessionReadiness();
        if (readiness.ready) return readiness.sessionId;

        // A completely empty account can reach the chat input before a case
        // exists. Allocate it through the same durable creation path instead
        // of reviving the legacy browser-only session generator.
        const createCase = window['newChat'];
        if (!readiness.sessionId && typeof createCase === 'function') {
            const created = await createCase();
            if (!created?.success) {
                throw new Error(created?.error || 'Unable to create a case.');
            }
            transition = workspaceTransition;
            if (transition) await transition;
            readiness = activeSessionReadiness();
            if (readiness.ready) return readiness.sessionId;
        }
        throw new Error('The selected case is not ready.');
    };

    function cancelTransitionUi() {
        document.body.classList.remove('workspace-hydrating');
        window.setWorkspaceHydrationState?.(false);
    }

    async function runWorkspaceTransition(operation) {
        if (workspaceTransition) {
            return { success: false, busy: true, error: 'A case transition is already in progress.' };
        }
        cancelBackgroundWorkspaceRestore();
        clearScheduledWorkspaceSave();
        invalidateDeferredWorkspaceRestore();
        setWorkspaceTransitionState(true);
        const transitionGeneration = ++workspaceTransitionGeneration;
        const transitionStartedAt = workspaceNow();
        recordWorkspacePerformance('transition.started', {
            sessionId: String(activeSessionId || ''),
            details: { generation: transitionGeneration },
        });
        const transition = (async () => {
            try {
                const result = await operation();
                // A replaced transition was killed by a newer switch click.
                // Its result must not overwrite the active session.
                if (result && result.replaced) return result;
                return result;
            } catch (error) {
                // An AbortError from a replaced transition is expected — the
                // newer switch already painted its spinner and the recovery
                // step would only add noise.
                if (error?.name === 'AbortError' && _switchAbortController?.signal.aborted) {
                    return { success: false, replaced: true };
                }
                console.error('[workspace] case transition failed:', error);
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
                workspaceTransition = null;
                setWorkspaceTransitionState(false);
                try {
                    window.dispatchEvent(new CustomEvent('brachybot:session-readiness', {
                        detail: activeSessionReadiness(),
                    }));
                } catch (_) {}
                recordWorkspacePerformance('transition.finished', {
                    sessionId: String(activeSessionId || ''),
                    startedAt: transitionStartedAt,
                    details: { generation: transitionGeneration },
                });
                // Auto-run any session switch that was queued while this
                // transition was in progress.  Rapid session-hopping must
                // not silently drop every other click.
                if (pendingSwitchSessionId !== null) {
                    const queued = pendingSwitchSessionId;
                    pendingSwitchSessionId = null;
                    setTimeout(() => window.switchSession(queued), 0);
                }
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

    function workspacePlanningIdentity(snapshot) {
        const results = snapshot?.agent?.planning_results;
        const ids = new Set();
        if (!results || typeof results !== 'object') return { ids, activeId: '' };
        const runs = Array.isArray(results.planning_runs) ? results.planning_runs : [];
        runs.forEach(run => {
            const planningId = String(run?.planning_id || run?.id || '').trim();
            if (planningId) ids.add(planningId);
        });
        Object.keys(results).forEach(key => {
            if (key.startsWith('planning_run:')) ids.add(key.slice('planning_run:'.length));
        });
        const activeId = String(
            results.active_planning_id || results.planning_run_id || '',
        ).trim();
        if (activeId) ids.add(activeId);
        return { ids, activeId };
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
            camera_up: numberArray(camera.up),
            camera_near: Number.isFinite(camera.near) ? camera.near : null,
            camera_far: Number.isFinite(camera.far) ? camera.far : null,
            camera_aspect: Number.isFinite(camera.aspect) ? camera.aspect : null,
            camera_fov: Number.isFinite(camera.fov) ? camera.fov : null,
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

    function workspaceUiState(ownerSessionId = '') {
        const sessionId = String(ownerSessionId || (typeof activeSessionId !== 'undefined' ? activeSessionId : '') || '');
        return {
            dose_value_unit: 'gy',
            prescription_base_gy: 120,
            dose_model_scale_gy: (
                typeof doseModelScaleGy === 'function' ? doseModelScaleGy() : 190.8
            ),
            controls: controlState(),
            viewer: {
                // `state.sessionId` changes as soon as the new shell paints.
                // A detached old-session save must keep the serialized viewer
                // projection attached to the old owner instead.
                sessionId: sessionId || (typeof state !== 'undefined' ? state.sessionId : null),
                slices: (typeof state !== 'undefined' && state.slices) ? jsonClone(state.slices) : {},
                settings: (typeof state !== 'undefined' && state.viewerSettings) ? jsonClone(state.viewerSettings) : {},
                doseOpacity: typeof state !== 'undefined' ? state.doseOpacity : null,
                // Raw slices, promises and Three.js materials are runtime-only.
                // Persisting them would create circular JSON and cannot restore a
                // WebGL resource after a restart; the enabled mode is sufficient.
                doseTexture: typeof state !== 'undefined' && state.doseTexture ? { enabled: !!state.doseTexture.enabled } : null,
                annotations: typeof state !== 'undefined' && Array.isArray(state.annotations)
                    ? jsonClone(state.annotations)
                    : [],
                // Manual/threshold masks are case data and must survive a
                // restart. voxels are Sets; jsonClone turns them into arrays,
                // and applyWorkspaceSnapshot converts them back.
                masks: (typeof state !== 'undefined' && state.maskLabels)
                    ? jsonClone({ labels: state.maskLabels, counter: state.maskLabelCounter || 0, activeMaskId: state.activeMaskId || null })
                    : { labels: {}, counter: 0, activeMaskId: null },
                scene: sceneViewState(),
                dvh: dvhViewState(),
            },
            data_tree: typeof dataTreeState !== 'undefined' ? jsonClone(dataTreeState) : {},
            manual: typeof _manualState === 'function' ? jsonClone(_manualState()) : {},
            training: typeof trainingMonitorState !== 'undefined' ? jsonClone(trainingMonitorState) : {},
        };
    }

    function queueServerReportFigureUpload(figure, sessionId) {
        if (!figure || !figure.dataUrl || figure._serverUrl || figure._serverUploadPromise) return;
        if (!/^data:image\/png;base64,/i.test(String(figure.dataUrl))) return;
        const source = String(figure.dataUrl);
        figure._serverUploadPromise = fetch('/api/screenshot', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-BrachyBot-Session': String(sessionId || ''),
            },
            body: JSON.stringify({
                image: source,
                target: 'report-figure',
                mode: 'report',
                description: String(figure.title || figure.axis || 'report figure'),
                title: String(figure.title || ''),
                planning_id: activeReportPlanningId(),
                attachment_id: `report-figure-${activeReportPlanningId()}-${String(figure.axis || figure.id || 'image')}`,
                view_metadata: {
                    axis: String(figure.axis || ''),
                    figure_group: String(figure.figureGroup || ''),
                    figure_number: Number(figure.figureNumber) || null,
                    subfigure: String(figure.subfigure || ''),
                    sort_order: Number(figure.sortOrder) || null,
                    capture_role: String(figure.captureRole || ''),
                    capture_contract: String(figure.captureContract || ''),
                    slice_index: Number.isFinite(Number(figure.sliceIdx)) ? Number(figure.sliceIdx) : null,
                    peak_voxel: figure.peakVoxel || null,
                },
            }),
        }).then(response => response.ok ? response.json() : null).then(payload => {
            const url = payload?.screenshot_url || payload?.url || '';
            // Do not overwrite a newer figure captured while the upload was
            // in flight. The URL is an authenticated, case-owned artifact.
            if (url && figure.dataUrl === source) {
                figure.dataUrl = url;
                figure._serverUrl = url;
                delete figure._cacheKey;
                if (String(sessionId || '') === String(activeSessionId || '')
                    && typeof scheduleWorkspaceSave === 'function') {
                    scheduleWorkspaceSave('report.figure.persisted');
                }
                if (typeof hydrateDataTreeArtifactCatalog === 'function') {
                    void hydrateDataTreeArtifactCatalog({ force: true });
                }
            }
            return url;
        }).catch(error => {
            console.debug('[workspace] report figure server upload deferred:', error);
            return '';
        }).finally(() => {
            delete figure._serverUploadPromise;
        });
    }

    function activeReportPlanningId() {
        const planning = typeof dataTreeState !== 'undefined' ? dataTreeState?.planning : null;
        return String(
            planning?.activePlanningId
            || planning?.id
            || window.__reportWorkspaceActivePlanningId
            || '__unassigned__',
        );
    }

    // Report figures are durable planning evidence, not an append-only image
    // gallery.  Every generated subfigure has one stable role that survives
    // the browser cache, server artifact catalog, PDF export, and Session
    // restore.  This prevents a second copy of the same role from becoming a
    // second Figure 1(a) after a restore.
    const REPORT_FIGURE_DEFINITIONS = Object.freeze({
        report_fig1_global: {
            figureGroup: 'figure1', figureNumber: 1, subfigure: 'a', sortOrder: 1,
            captureRole: 'planning_overview',
            title: 'Reference-direction plan overview',
            caption: 'Global view along the needle reference direction, showing the CTV, selected OARs, needle paths, and seeds.',
        },
        report_fig1_closeup: {
            figureGroup: 'figure1', figureNumber: 1, subfigure: 'b', sortOrder: 2,
            captureRole: 'planning_closeup',
            title: 'CTV seed-distribution close-up',
            caption: 'Target close-up with the CTV made translucent to show seed distribution and needle paths.',
        },
        report_fig2_axial: {
            figureGroup: 'figure2', figureNumber: 2, subfigure: 'a', sortOrder: 1,
            captureRole: 'peak_dose_axial',
            title: 'Peak-dose axial view',
            caption: 'Axial CT slice through the peak-dose location with dose overlay and planning projections.',
        },
        report_fig2_sagittal: {
            figureGroup: 'figure2', figureNumber: 2, subfigure: 'b', sortOrder: 2,
            captureRole: 'peak_dose_sagittal',
            title: 'Peak-dose sagittal view',
            caption: 'Sagittal CT slice through the peak-dose location with dose overlay and planning projections.',
        },
        report_fig2_coronal: {
            figureGroup: 'figure2', figureNumber: 2, subfigure: 'c', sortOrder: 3,
            captureRole: 'peak_dose_coronal',
            title: 'Peak-dose coronal view',
            caption: 'Coronal CT slice through the peak-dose location with dose overlay and planning projections.',
        },
        report_fig2_dose_surface: {
            figureGroup: 'figure2', figureNumber: 2, subfigure: 'd', sortOrder: 4,
            captureRole: 'dose_surface_3d',
            title: 'CTV and dose-isosurface overview',
            caption: 'Three-dimensional view of the CTV and relevant dose isosurfaces.',
        },
        report_fig2_dvh: {
            figureGroup: 'figure2', figureNumber: 2, subfigure: 'e', sortOrder: 5,
            captureRole: 'dvh',
            title: 'Dose-volume histogram',
            caption: 'Dose-volume curves for the CTV and available OAR structures in the current Planning run.',
        },
    });

    const REPORT_FIGURE_AXIS_BY_ROLE = Object.freeze(
        Object.fromEntries(Object.entries(REPORT_FIGURE_DEFINITIONS).map(([axis, definition]) => [definition.captureRole, axis]))
    );

    function reportFigureAxis(figure) {
        const explicitAxis = String(figure?.axis || '').trim();
        if (REPORT_FIGURE_DEFINITIONS[explicitAxis]) return explicitAxis;
        const role = String(figure?.captureRole || figure?.capture_role || '').trim();
        if (REPORT_FIGURE_AXIS_BY_ROLE[role]) return REPORT_FIGURE_AXIS_BY_ROLE[role];
        // Early reports stored the page and subfigure but did not yet persist
        // the capture role. Recover that identity from the standard report
        // layout so duplicate legacy Figure 1(a) entries collapse correctly.
        const figureNumber = Number(figure?.figureNumber);
        const subfigure = String(figure?.subfigure || '').trim().toLowerCase();
        const legacyAxis = Object.entries(REPORT_FIGURE_DEFINITIONS).find(([, definition]) => (
            Number(definition.figureNumber) === figureNumber
            && String(definition.subfigure || '').toLowerCase() === subfigure
        ))?.[0];
        return legacyAxis || explicitAxis;
    }

    function reportFigureIdentity(figure, index = 0) {
        const axis = reportFigureAxis(figure);
        if (REPORT_FIGURE_DEFINITIONS[axis]) return `report:${axis}`;
        const source = String(
            figure?._serverUrl || figure?.dataUrl || figure?.id || `${index}:${figure?.title || ''}`
        );
        return `supplemental:${source}`;
    }

    function isGenericReportFigureTitle(value) {
        return /^report\s+(figure|screenshot)\s+\d+$/i.test(String(value || '').trim());
    }

    function normalizeReportFigures(figures, options = {}) {
        const language = String(options.language || window.reportForm?.language || 'en').toLowerCase();
        const entries = Array.isArray(figures) ? figures : [];
        const selected = new Map();
        const score = figure => {
            let value = figure?._artifactFallback ? 0 : 100;
            if (figure?._cacheKey) value += 20;
            if (figure?._serverUrl || figure?.dataUrl) value += 10;
            if (figure?.title && !isGenericReportFigureTitle(figure.title)) value += 2;
            if (figure?.caption) value += 1;
            return value;
        };

        entries.forEach((figure, index) => {
            if (!figure || typeof figure !== 'object') return;
            const axis = reportFigureAxis(figure);
            const persistedUrl = String(figure?._serverUrl || figure?.dataUrl || '');
            const isUnidentifiedLegacyArtifact = !REPORT_FIGURE_DEFINITIONS[axis]
                && /^report_screenshot_/i.test(persistedUrl.split('/').pop() || '')
                && isGenericReportFigureTitle(figure.title);
            // Older catalog-only images without a stable report role remain
            // exportable artifacts, but they cannot be safely guessed as a
            // new report Figure. Do not reinsert them into a restored report.
            if ((figure._artifactFallback || isUnidentifiedLegacyArtifact)
                && !REPORT_FIGURE_DEFINITIONS[axis]) return;
            const identity = reportFigureIdentity({ ...figure, axis }, index);
            const previous = selected.get(identity);
            if (!previous || score(figure) > score(previous.figure)) {
                selected.set(identity, { figure, index, axis });
            }
        });

        const normalized = Array.from(selected.values()).map(({ figure, index, axis }) => {
            const definition = REPORT_FIGURE_DEFINITIONS[axis];
            if (!definition) return { figure, index, sortOrder: Number(figure.sortOrder) || 999 };
            figure.axis = axis;
            figure.figureGroup = definition.figureGroup;
            figure.figureNumber = definition.figureNumber;
            figure.subfigure = definition.subfigure;
            figure.sortOrder = definition.sortOrder;
            figure.captureRole = definition.captureRole;
            // Catalog-only recovery is evidence recovery rather than user-authored
            // report content. Give it the canonical title and caption so a legacy
            // random screenshot name or historical encoding cannot create a
            // misleading second "Report Figure N" entry after a Session restore.
            if (figure._artifactFallback || !figure.title || isGenericReportFigureTitle(figure.title)) {
                figure.title = definition.title;
            }
            if (figure._artifactFallback || !figure.caption) figure.caption = definition.caption;
            return { figure, index, sortOrder: definition.sortOrder };
        }).sort((left, right) => (
            Number(left.figure.figureNumber || 99) - Number(right.figure.figureNumber || 99)
            || left.sortOrder - right.sortOrder
            || left.index - right.index
        )).map(entry => entry.figure);

        // The definitions are currently English because report evidence is
        // generated in the report language. Existing localized captions are
        // preserved; only old catalog entries missing all text use this
        // medical-English fallback.
        void language;
        return normalized;
    }

    window.normalizeReportFigures = normalizeReportFigures;
    window.describeReportFigure = function describeReportFigure(axis) {
        const definition = REPORT_FIGURE_DEFINITIONS[String(axis || '')];
        return definition ? { title: definition.title, caption: definition.caption } : null;
    };

    function reportSectionSessionId(section) {
        const form = section?.form && typeof section.form === 'object'
            ? section.form : section;
        return String(form?.sessionId || form?.session_id || '').trim();
    }

    function sessionBoundReportMap(rawMap, sessionId, planningIds = null) {
        const filtered = {};
        if (!rawMap || typeof rawMap !== 'object') return filtered;
        Object.entries(rawMap).forEach(([planningId, section]) => {
            if (!section || typeof section !== 'object') return;
            if (planningIds?.size && !planningIds.has(String(planningId))) return;
            const owner = reportSectionSessionId(section);
            if (owner && owner !== String(sessionId || '')) return;
            filtered[String(planningId)] = section;
        });
        return filtered;
    }

    function reportState(ownerSessionId = '') {
        if (!window.reportForm) return {};
        const sessionId = String(ownerSessionId || (typeof activeSessionId !== 'undefined' ? activeSessionId : '') || '');
        // Persist the exact Reference/Status rows that are visible in the
        // report. Preview rendering is not a durable boundary and may not have
        // run before a fast Session switch or browser close.
        if (typeof window.syncReportQualityAssessment === 'function') {
            window.syncReportQualityAssessment(window.reportForm, { preserveStored: true });
        }
        const planningId = activeReportPlanningId();
        if (Array.isArray(window.reportForm.figures)) {
            window.reportForm.figures = normalizeReportFigures(window.reportForm.figures, {
                language: window.reportForm.language,
            });
        }
        // IndexedDB remains the fast local cache, but server-owned report
        // figures make restart and another browser deterministic. Uploads are
        // deliberately fire-and-forget and never delay chat/session changes.
        if (Array.isArray(window.reportForm.figures) && sessionId) {
            window.reportForm.figures.forEach(figure => {
                if (figure?.dataUrl && figure.dataUrl.length > 10000) {
                    queueServerReportFigureUpload(figure, sessionId);
                }
            });
        }
        const form = jsonClone(window.reportForm);
        if (form && sessionId) form.sessionId = sessionId;
        // Offload large base64 figure data URLs into IndexedDB so they
        // don't bloat every persistWorkspace payload (200 KB – 1 MB).
        if (form && Array.isArray(form.figures) && window.SessionCache && sessionId) {
            const sid = sessionId;
            for (let i = 0; i < form.figures.length; i++) {
                const f = form.figures[i];
                if (f && f.dataUrl && f.dataUrl.length > 10000) {
                    // Axis/role is stable across recapture and reordering; an
                    // array index is not. Stable keys prevent one of the 2+5
                    // report subfigures from restoring another image.
                    const identity = f.axis || f.captureRole || f.id || `${i}_${f.title || ''}`;
                    const cacheKey = `report_fig_${planningId}_${identity}`.replace(/[^a-zA-Z0-9_-]/g, '_');
                    try {
                        const enc = new TextEncoder();
                        void window.SessionCache.put(sid, 'report', cacheKey, enc.encode(f.dataUrl).buffer).catch(function(){});
                    } catch (_) {}
                    f._cacheKey = cacheKey;
                    f.dataUrl = ''; // Don't serialise the MB-size data URL
                }
            }
        }
        const section = {
            form: form,
            sources: window.Report?.sources?._map ? Array.from(window.Report.sources._map.entries()) : [],
            audit: jsonClone(window.__reportWorkspaceAudit || []),
            snapshots: jsonClone(window.__reportWorkspaceSnapshots || []),
            collapsed: jsonClone(window._reportCollapsed || {}),
        };
        // A report belongs to one immutable Planning run. Keep the legacy
        // top-level fields for old clients, but also maintain a per-run map so
        // switching Planning never shows the previous run's narrative or
        // screenshots under the newly selected dose/needles.
        const sameOwner = String(window.__reportWorkspaceSessionId || '') === sessionId;
        const byPlanning = sessionBoundReportMap(
            sameOwner ? window.__reportWorkspaceByPlanning : {},
            sessionId,
        );
        byPlanning[planningId] = section;
        window.__reportWorkspaceByPlanning = byPlanning;
        window.__reportWorkspaceActivePlanningId = planningId;
        window.__reportWorkspaceSessionId = sessionId;
        return {
            ...section,
            active_planning_id: planningId === '__unassigned__' ? null : planningId,
            by_planning_id: byPlanning,
        };
    }

    function _reportNarrativeLength(form) {
        if (!form || typeof form !== 'object') return 0;
        return ['interpretation', 'safety', 'qaNotes'].reduce((total, key) => {
            const value = form[key];
            return total + (typeof value === 'string' ? value.trim().length : 0);
        }, 0);
    }

    function _reportContentScore(form) {
        if (!form || typeof form !== 'object') return 0;
        let score = _reportNarrativeLength(form);
        const textPaths = [
            ['case', 'patientId'], ['case', 'tumorType'], ['case', 'plannerName'],
            ['study', 'diagnosis'], ['study', 'clinicalHistory'], ['study', 'priorTreatment'],
            ['segmentation', 'ctvModelName'], ['segmentation', 'oarModelName'],
        ];
        textPaths.forEach(([parent, key]) => {
            const value = form[parent]?.[key];
            if (typeof value === 'string') score += value.trim().length;
        });
        ['references', 'figures', 'oarDose'].forEach(key => {
            if (Array.isArray(form[key])) score += form[key].length * 32;
        });
        Object.values(form.metrics || {}).forEach(value => {
            if (value !== null && value !== undefined && value !== '') score += 8;
        });
        Object.values(form.planning || {}).forEach(value => {
            if (value !== null && value !== undefined && value !== '') score += 4;
        });
        Object.keys(form.qualityAssessment?.metrics || {}).forEach(() => { score += 4; });
        return score;
    }

    // Older workspaces stored the form directly under `report`, while newer
    // snapshots use `report.form` so audit/source metadata can live beside it.
    // Normalize both shapes before restoring; otherwise a legacy report can
    // keep its cached figures but silently lose every text field on a switch.
    const REPORT_FORM_KEYS = new Set([
        'version', 'language', 'templateKey', 'sessionId', 'updatedAt', 'updated_at',
        'hospital', 'patient', 'study', 'case', 'imaging', 'segmentation',
        'planning', 'metrics', 'qualityAssessment', 'oarDose', 'interpretation', 'safety', 'qaNotes',
        'references', 'figures', 'signature', 'editedFields',
    ]);

    function reportFormFromSnapshot(reportSection) {
        if (!reportSection || typeof reportSection !== 'object') return null;
        if (reportSection.form && typeof reportSection.form === 'object'
            && !Array.isArray(reportSection.form)) {
            return reportSection.form;
        }
        const hasDirectFormField = Object.keys(reportSection).some(key => REPORT_FORM_KEYS.has(key));
        return hasDirectFormField ? reportSection : null;
    }

    function reportSectionForPlanning(reportSection, planningId) {
        if (!reportSection || typeof reportSection !== 'object') return null;
        const target = String(planningId || '');
        const byPlanning = reportSection.by_planning_id || reportSection.byPlanning;
        if (target && byPlanning && typeof byPlanning === 'object') {
            const selected = byPlanning[target];
            if (selected && typeof selected === 'object') return selected;
            // A known Planning map is authoritative. Do not fall back to the
            // previous run's top-level report when a newly-created Planning
            // has not received its own report yet.
            return null;
        }
        return reportSection;
    }

    function _preservePopulatedReport(current, saved, options) {
        if (!options?.preserveClinicalData || !current || !saved) return false;
        if (current.sessionId && String(current.sessionId) !== String(activeSessionId || '')) return false;
        const currentUpdated = Number(current.updatedAt || current.updated_at || 0);
        const savedUpdated = Number(saved.updatedAt || saved.updated_at || 0);
        if (currentUpdated > savedUpdated && _reportContentScore(current) >= _reportContentScore(saved)) return true;
        // A background planning refresh may fill the report after a shell
        // snapshot was read. Never let that snapshot erase generated text.
        return _reportNarrativeLength(current) > 0 && _reportNarrativeLength(saved) === 0
            && _reportContentScore(current) > _reportContentScore(saved);
    }

    function _mergePersistedQualityAssessment(target, saved) {
        if (!target || !saved || typeof saved !== 'object') return false;
        const savedMetrics = saved.metrics;
        if (!savedMetrics || typeof savedMetrics !== 'object') return false;
        const targetMetrics = target.qualityAssessment?.metrics;
        if (!target.qualityAssessment || typeof target.qualityAssessment !== 'object') {
            target.qualityAssessment = jsonClone(saved);
            return true;
        }
        if (!targetMetrics || typeof targetMetrics !== 'object') {
            target.qualityAssessment.metrics = jsonClone(savedMetrics);
            return true;
        }
        let changed = false;
        Object.entries(savedMetrics).forEach(([key, savedRow]) => {
            if (!savedRow || typeof savedRow !== 'object') return;
            const targetRow = targetMetrics[key];
            const savedValue = savedRow.value == null || savedRow.value === '' ? null : Number(savedRow.value);
            const targetValue = targetRow?.value == null || targetRow.value === '' ? null : Number(targetRow.value);
            const sameValue = (Number.isFinite(savedValue) ? savedValue : null)
                === (Number.isFinite(targetValue) ? targetValue : null);
            if (!targetRow || sameValue) {
                targetMetrics[key] = { ...(targetRow || {}), ...jsonClone(savedRow) };
                changed = true;
            }
        });
        if (saved.language && !target.qualityAssessment.language) {
            target.qualityAssessment.language = saved.language;
            changed = true;
        }
        return changed;
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

    function applyChatSnapshotFast(snapshot, options = {}) {
        const chat = snapshot?.chat;
        const sessionId = workspaceSnapshotSessionId(snapshot);
        if (!chat || !sessionId || sessionId !== String(activeSessionId || '')
            || typeof sessions === 'undefined' || !sessions[sessionId]) return false;
        rememberWorkspaceRevision(snapshot);

        // Chat is the first-paint part of a workspace.  It contains no CT,
        // GPU, WebGL, or model state, so restoring it here keeps reconnects
        // responsive while the clinical data plane hydrates in the background.
        let messages = Array.isArray(chat.messages) ? chat.messages : null;
        // Older snapshots stored the last tool trace separately before chat
        // messages became the canonical transcript. Reconstruct a read-only
        // thinking row when that legacy shape is encountered so tool history
        // is not silently lost after a browser refresh.
        if (!messages && Array.isArray(chat.execution_trace) && chat.execution_trace.length) {
            const rawTimestamp = Number(chat.updated_at || snapshot.saved_at || Date.now());
            messages = [{
                type: 'thinking',
                content: '',
                steps: jsonClone(chat.execution_trace),
                timestamp: rawTimestamp < 1e12 ? rawTimestamp * 1000 : rawTimestamp,
            }];
        }
        if (messages) {
            const currentMessages = Array.isArray(sessions[sessionId].messages)
                ? sessions[sessionId].messages
                : [];
            sessions[sessionId].messages = typeof window.mergeSessionChatMessages === 'function'
                ? window.mergeSessionChatMessages(sessionId, messages, currentMessages, chat.attachments)
                : jsonClone(messages);
            sessions[sessionId].pending = false;
            if (typeof loadSessionChat === 'function') loadSessionChat(sessionId);
        }
        window._sessionChatQueues = window._sessionChatQueues || {};
        if (!options.skipChat) {
            window._sessionChatQueues[sessionId] = Array.isArray(chat.queued) ? jsonClone(chat.queued) : [];
            window._sessionChatTaskStatuses = window._sessionChatTaskStatuses || {};
            if (chat.task_id) {
                window._sessionChatTaskIds = window._sessionChatTaskIds || {};
                window._sessionChatTaskIds[sessionId] = chat.task_id;
                window._sessionChatTaskStatuses[sessionId] = chat.task_status || 'running';
            } else {
                // A fast switch snapshot may be one write behind the live
                // task identity. Preserve an in-memory running hint until
                // /api/chat/task confirms the server state; a stale empty
                // snapshot must not cancel replay for a case we just left.
                const localTaskId = window._sessionChatTaskIds?.[sessionId]
                    || window._detachedChatTasks?.[sessionId]
                    || null;
                const savedStatus = String(chat.task_status || '');
                const preserveLiveTask = !!localTaskId
                    && (!savedStatus || savedStatus === 'idle' || savedStatus === 'running');
                if (!preserveLiveTask) {
                    delete window._sessionChatTaskIds?.[sessionId];
                    delete window._detachedChatTasks?.[sessionId];
                    window._sessionChatTaskStatuses[sessionId] = chat.task_status || 'idle';
                } else {
                    window._sessionChatTaskStatuses[sessionId] = 'running';
                }
            }
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

    function chatState(ownerSessionId = '') {
        const sessionId = String(ownerSessionId || (typeof activeSessionId !== 'undefined' ? activeSessionId : '') || '');
        const current = (typeof sessions !== 'undefined' && sessionId) ? sessions[sessionId] : null;
        if (!current) return {};
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
                // Legacy controls stored Rx multipliers (1 = 120 Gy), not raw
                // DoseUNet output. Keep that conversion independent from the
                // model's 190.8 Gy/output-unit calibration.
                const unit = String(options.doseValueUnit || '').toLowerCase();
                const legacyModelValue = !unit && Number.isFinite(v) && v > 0 && v <= 5;
                if (id && GY_VALUE_IDS.has(id) && (unit === 'model' || legacyModelValue)) {
                    const savedBase = Number(options.prescriptionBaseGy);
                    const base = Number.isFinite(savedBase) && savedBase > 0 ? savedBase : 120;
                    element.value = v * base;
                } else {
                    element.value = saved.value;
                }
            }
        });
    }

    function _syncViewerControlsFromState() {
        var vs = (typeof state !== 'undefined') ? (state.viewerSettings || {}) : {};
        var dm = document.getElementById('displayMode');
        if (dm && vs.displayMode) dm.value = vs.displayMode;
        var ctv = document.getElementById('overlayCTV');
        if (ctv) ctv.checked = !!(vs.showCTV ?? true);
        var oar = document.getElementById('overlayOAR');
        if (oar) oar.checked = !!(vs.showOAR ?? false);
        var thr = document.getElementById('viewerThreshold');
        if (thr && vs.threshold != null) thr.value = vs.threshold;
        var doseSlider = document.getElementById('doseOverlayOpacity');
        if (doseSlider && typeof state.doseOpacity === 'number') doseSlider.value = Math.round(state.doseOpacity * 100);
        var doseLabel = document.getElementById('doseOpacityVal');
        if (doseLabel && typeof state.doseOpacity === 'number') doseLabel.textContent = Math.round(state.doseOpacity * 100) + '%';
        var seedCb = document.getElementById('overlaySeeds');
        if (seedCb) seedCb.checked = !!(vs.showSeeds ?? true);
    }

    function copyDisplayProperties(target, saved) {
        if (!target || !saved || typeof saved !== 'object') return;
        // These are presentation preferences. Geometry, voxel counts,
        // categories, and planning arrays are reconstructed from the current
        // case and must not be copied from a UI snapshot.
        ['visible', 'visible2D', 'visible3D', 'opacity', 'color', 'material', 'locked'].forEach(key => {
            if (Object.prototype.hasOwnProperty.call(saved, key)) target[key] = saved[key];
        });
        // A user-renamed node label is a deliberate presentation override and
        // must survive a refresh / session switch. Default anatomical names
        // (e.g. "CTV Mask", "OAR 3", "Seed seed_1", "Trajectory 1", "120 Gy")
        // are reconstructed from the case, so only carry over labels that do
        // not look like a generated default.
        if (Object.prototype.hasOwnProperty.call(saved, 'label') && typeof saved.label === 'string') {
            const savedLabel = String(saved.label).trim();
            const looksDefault = /^(CTV Mask|All OARs|Dose overlay \(2D\)|OAR\s+\d+|Seed\s+\S+|Needle\s+\S+|Trajectory\s+\d+|Label\s+\d+|\d+\s*Gy)$/i.test(savedLabel);
            if (savedLabel && !looksDefault) target.label = savedLabel;
        }
        // `name` is the backend-facing field for OAR organs; carry over only
        // when it matches the user label (avoids clobbering anatomy names).
        if (Object.prototype.hasOwnProperty.call(saved, 'name') && typeof saved.name === 'string'
            && target.label && String(saved.name).trim() === String(target.label).trim()) {
            target.name = target.label;
        }
    }

    function applyDataTreePresentation(savedTree) {
        if (!savedTree || typeof savedTree !== 'object' || typeof dataTreeState === 'undefined') return;
        // Expansion belongs to the current session's UI presentation. Restore
        // it independently of clinical arrays so a compact snapshot cannot
        // reopen unrelated groups during asynchronous tree hydration.
        const savedExpansion = savedTree.expansionState || savedTree.expansion_state;
        if (savedExpansion && typeof savedExpansion === 'object'
            && !Array.isArray(savedExpansion)) {
            dataTreeState.expansionState = jsonClone(savedExpansion);
        }
        // Upgrade only known application-default colors. This runs before any
        // presentation fields are copied so a legacy snapshot cannot repaint
        // the new CTV/OAR LUT, while custom colors remain authoritative.
        window.migrateLegacyStructurePalette?.(savedTree);
        ['ct', 'ctv', 'oar', 'skin', 'dose', 'seeds', 'needles'].forEach(key => {
            copyDisplayProperties(dataTreeState[key], savedTree[key]);
        });
        if (savedTree.planning && dataTreeState.planning) {
            ['visible', 'visible2D', 'visible3D', 'opacity', 'color', 'material', 'locked'].forEach(key => {
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
            // Restore user-renamed labels for planning rows (trajectories,
            // seeds, needles, dose iso-surfaces) by stable ID. These rows are
            // rebuilt from the server without labels, so the saved custom label
            // is the only record of a rename across a refresh.
            const savedByKey = (list, keyFn) => new Map((list || []).map(item => [String(keyFn(item)), item]));
            const savedTraj = savedByKey(savedTree.planning.trajectories, t => t?.id);
            const savedSeed = savedByKey(savedTree.planning.seeds, s => s?.id);
            const savedNeedle = savedByKey(savedTree.planning.needles, n => n?.id);
            const savedDose = savedByKey(savedTree.planning.doseLevels, d => d?.threshold);
            (dataTreeState.planning.trajectories || []).forEach(t => copyDisplayProperties(t, savedTraj.get(String(t?.id || ''))));
            (dataTreeState.planning.seeds || []).forEach(s => copyDisplayProperties(s, savedSeed.get(String(s?.id || ''))));
            (dataTreeState.planning.needles || []).forEach(n => copyDisplayProperties(n, savedNeedle.get(String(n?.id || ''))));
            (dataTreeState.planning.doseLevels || []).forEach(d => copyDisplayProperties(d, savedDose.get(String(d?.threshold ?? d?.thresholdGy ?? ''))));
        }
        const savedLabels = savedTree.ctvLabels || savedTree.ctv_labels || {};
        if (!dataTreeState.ctvLabels) dataTreeState.ctvLabels = {};
        Object.entries(savedLabels).forEach(([id, saved]) => {
            const current = dataTreeState.ctvLabels[id] || {};
            dataTreeState.ctvLabels[id] = current;
            copyDisplayProperties(current, saved);
        });
        const byId = new Map((savedTree.organs || []).map(item => [String(item?.id || ''), item]));
        const byLabel = new Map((savedTree.organs || []).map(item => [String(item?.labelId ?? item?.label_id ?? ''), item]));
        // OAR metadata may arrive after the fast control-plane snapshot. Keep
        // these presentation-only values until updateOrganList() materializes
        // the current case's authoritative rows; never restore old geometry or
        // ontology from this deferred map.
        window.__pendingOarPresentation = {
            byId: Object.fromEntries(byId),
            byLabel: Object.fromEntries(byLabel),
        };
        (dataTreeState.organs || []).forEach(organ => {
            const saved = byId.get(String(organ.id)) || byLabel.get(String(organ.labelId));
            copyDisplayProperties(organ, saved);
        });
        window.syncStructureColorLUTsFromTree?.(dataTreeState);
        // Mesh hydration can finish after this compact session snapshot. Apply
        // the per-view presentation now, and the mesh loader will reapply it
        // again when late geometry becomes available.
        window.applyDataTreeViewVisibility?.();
    }

    function hasTreeClinicalData(tree) {
        if (!tree || typeof tree !== 'object') return false;
        const hasRows = Array.isArray(tree.organs) && tree.organs.length > 0;
        const hasCtvLabels = tree.ctvLabels && typeof tree.ctvLabels === 'object'
            && Object.keys(tree.ctvLabels).length > 0;
        const planning = tree.planning && typeof tree.planning === 'object' ? tree.planning : {};
        const hasPlanningRows = [
            planning.trajectories,
            planning.seeds,
            planning.needles,
            planning.doseLevels,
            planning.meshes,
        ].some(value => Array.isArray(value) && value.length > 0);
        // Loaded flags are only control-plane hints. They are intentionally
        // excluded here because a compact snapshot can say "loaded" while
        // carrying no rows; treating that marker as clinical data would let
        // an empty snapshot erase live OAR or planning rows during hydration.
        return hasRows || hasCtvLabels || hasPlanningRows;
    }

    function applyDataTreeSnapshot(savedTree) {
        if (!savedTree || typeof savedTree !== 'object' || typeof dataTreeState === 'undefined') return;
        window.migrateLegacyStructurePalette?.(savedTree);
        const currentHasClinicalData = hasTreeClinicalData(dataTreeState);
        const savedHasClinicalData = hasTreeClinicalData(savedTree);

        // Clinical arrays and mesh records are data-plane state. A compact
        // browser snapshot may legitimately contain an older empty projection
        // while the authoritative label/plan loader has already populated the
        // current session. Never let that empty projection erase live data.
        // A genuinely empty/new case still receives the saved empty state,
        // because clearClientWorkspace() has fenced the previous case first.
        if (savedHasClinicalData || !currentHasClinicalData) {
            ['organs', 'ctvLabels', 'oarSource'].forEach(key => {
                if (!Object.prototype.hasOwnProperty.call(savedTree, key)) return;
                const value = savedTree[key];
                dataTreeState[key] = value && typeof value === 'object'
                    ? jsonClone(value)
                    : value;
            });
            ['ct', 'ctv', 'oar', 'skin', 'dose', 'seeds', 'needles'].forEach(key => {
                if (!Object.prototype.hasOwnProperty.call(savedTree, key)) return;
                const savedGroup = savedTree[key];
                if (!savedGroup || typeof savedGroup !== 'object') return;
                dataTreeState[key] = Object.assign(dataTreeState[key] || {}, jsonClone(savedGroup));
            });
            if (savedTree.planning && typeof savedTree.planning === 'object') {
                dataTreeState.planning = Object.assign(
                    dataTreeState.planning || {},
                    jsonClone(savedTree.planning),
                );
            }
        }

        // Presentation is always restored separately. This keeps visibility,
        // opacity, colors, and camera-facing choices without reintroducing old
        // geometry or overwriting a newer session's clinical arrays.
        applyDataTreePresentation(savedTree);
    }

    function restoreSceneView(scene, dvh, generation) {
        // Mark the camera as restore-owned until the hydrated scene has had a
        // chance to replace the old mesh set. The saved target is still
        // applied first so a valid user view is preserved, but the delayed
        // guard can reframe a stale target around the live objects.
        if (typeof scene3D !== 'undefined' && scene3D) {
            scene3D._workspaceRestoreActive = true;
            scene3D._cameraUserInteracted = false;
        }
        const applyScene = ({ initial = false } = {}) => {
            if (!scene || typeof scene3D === 'undefined' || !scene3D?.camera) return;
            // The first application establishes the saved view. Later passes
            // only compensate for asynchronous mesh/layout hydration. Once the
            // operator has zoomed, panned, rotated, selected, or dragged in the
            // live viewer, a delayed restore must never overwrite that pose.
            if (!initial && scene3D._cameraUserInteracted === true) return;
            const camera = scene3D.camera;
            const three = typeof THREE !== 'undefined' ? THREE : null;
            const positionValues = Array.isArray(scene.camera_position) && scene.camera_position.length === 3
                ? scene.camera_position : null;
            const quaternionValues = Array.isArray(scene.camera_quaternion) && scene.camera_quaternion.length === 4
                ? scene.camera_quaternion : null;
            const upValues = Array.isArray(scene.camera_up) && scene.camera_up.length === 3
                ? scene.camera_up : null;
            const targetValues = Array.isArray(scene.camera_target) && scene.camera_target.length === 3
                ? scene.camera_target : null;
            const position = positionValues && three?.Vector3
                ? new three.Vector3().fromArray(positionValues) : positionValues;
            const quaternion = quaternionValues && three?.Quaternion
                ? new three.Quaternion().fromArray(quaternionValues) : quaternionValues;
            const up = upValues && three?.Vector3
                ? new three.Vector3().fromArray(upValues) : upValues;
            const target = targetValues && three?.Vector3
                ? new three.Vector3().fromArray(targetValues) : targetValues;
            if (typeof window.sync3DCameraPose === 'function' && (position || quaternion || target)) {
                window.sync3DCameraPose({
                    position,
                    target,
                    quaternion,
                    up,
                    near: scene.camera_near,
                    far: scene.camera_far,
                    // The persisted aspect belongs to the old panel
                    // rectangle. The 3D renderer re-applies the current DOM
                    // aspect during resize; restoring this stale value here
                    // was the source of restart-time top/right clipping.
                    aspect: undefined,
                    fov: scene.camera_fov,
                    zoom: scene.camera_zoom,
                });
            } else {
                if (position) {
                    if (three?.Vector3 && typeof camera.position?.copy === 'function') camera.position.copy(position);
                    else camera.position?.fromArray?.(positionValues || position);
                }
                if (quaternion) {
                    if (three?.Quaternion && typeof camera.quaternion?.copy === 'function') camera.quaternion.copy(quaternion);
                    else camera.quaternion?.fromArray?.(quaternionValues || quaternion);
                }
                if (up) {
                    if (three?.Vector3 && typeof camera.up?.copy === 'function') camera.up.copy(up);
                    else camera.up?.fromArray?.(upValues || up);
                }
                if (target && scene3D.controls?.target) {
                    if (three?.Vector3 && typeof scene3D.controls.target.copy === 'function') scene3D.controls.target.copy(target);
                    else scene3D.controls.target.fromArray?.(targetValues || target);
                }
                if (Number.isFinite(scene.camera_zoom)) camera.zoom = scene.camera_zoom;
                if (Number.isFinite(scene.camera_near)) camera.near = scene.camera_near;
                if (Number.isFinite(scene.camera_far)) camera.far = scene.camera_far;
                if (Number.isFinite(scene.camera_aspect)) camera.aspect = scene.camera_aspect;
                if (Number.isFinite(scene.camera_fov)) camera.fov = scene.camera_fov;
                camera.updateProjectionMatrix?.();
                scene3D.controls?.syncExternalState?.();
            }
            scene3D.requestRender?.(4);
        };
        // Mesh reconstruction is asynchronous. Applying twice restores the
        // saved pose after geometry and renderer-resize work has settled.
        applyScene({ initial: true });
        scheduleDeferredWorkspaceRestore(generation, () => applyScene(), 450);
        scheduleDeferredWorkspaceRestore(generation, () => applyScene(), 1200);
        // Meshes may finish after the saved pose has been re-applied. Run the
        // non-destructive frustum guard after both layout and hydration settle.
        scheduleDeferredWorkspaceRestore(generation, () => {
            try {
                if (typeof scene3D === 'undefined' || scene3D?._cameraUserInteracted !== true) {
                    window.ensureCameraFitsVisibleScene?.({
                        forceCenter: true,
                        reason: 'workspace-restore-layout',
                    });
                }
            } catch (_) {}
        }, 1800);
        scheduleDeferredWorkspaceRestore(generation, () => {
            try {
                if (typeof scene3D === 'undefined' || scene3D?._cameraUserInteracted !== true) {
                    window.ensureCameraFitsVisibleScene?.({
                        forceCenter: true,
                        reason: 'workspace-restore-settled',
                    });
                }
            } catch (_) {}
            if (typeof scene3D !== 'undefined' && scene3D) {
                scene3D._workspaceRestoreActive = false;
            }
        }, 3000);

        const applyDvh = () => {
            const chart = document.getElementById('dvhChart');
            if (!dvh || !chart || typeof Plotly === 'undefined' || !Plotly.relayout) return;
            // A restored workspace can arrive before Plotly.newPlot has
            // created the graph object. Plotly.relayout assumes _fullLayout
            // and _guiEditing exist; calling it on the placeholder div throws
            // and aborts the rest of workspace restoration. Wait for the
            // chart's normal render pass instead of treating this as a fatal
            // restore error.
            if (!chart._fullLayout || !Array.isArray(chart.data) || !chart.layout) return;
            const update = {};
            if (Array.isArray(dvh.x_range) && dvh.x_range.length === 2) update['xaxis.range'] = dvh.x_range;
            if (Array.isArray(dvh.y_range) && dvh.y_range.length === 2) update['yaxis.range'] = dvh.y_range;
            if (dvh.axis_zoom_mode) chart._dvhAxisZoomMode = dvh.axis_zoom_mode;
            if (Object.keys(update).length) {
                try {
                    Plotly.relayout(chart, update);
                } catch (error) {
                    // Plotly can be destroyed during a rapid Session switch;
                    // ignore only this stale presentation update.
                    console.debug('[workspace] DVH relayout deferred:', error);
                }
            }
        };
        scheduleDeferredWorkspaceRestore(generation, applyDvh, 350);
        scheduleDeferredWorkspaceRestore(generation, applyDvh, 1100);
        // Plotly may render after the planning response and after the first
        // layout settles, especially on a cold browser cache.  Keep one last
        // guarded pass so the saved axis range is applied without ever
        // calling relayout on a placeholder div.
        scheduleDeferredWorkspaceRestore(generation, applyDvh, 2200);

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

    function hydrateReportFigureAssets(snapshot, sessionId, restoreGeneration, attempt = 0, targetForm = null) {
        const report = targetForm || reportFormFromSnapshot(snapshot?.report);
        if (!report || !Array.isArray(report.figures)) return;
        const pending = report.figures.filter(f => f && f._cacheKey && !f.dataUrl);
        if (!pending.length) return;
        // SessionCache is loaded as a separate script and IndexedDB may still
        // be opening during the first post-restart paint.  Do not turn that
        // harmless startup race into permanently missing report figures.
        if (!window.SessionCache) {
            if (attempt < 5) {
                setTimeout(() => hydrateReportFigureAssets(snapshot, sessionId, restoreGeneration, attempt + 1, report), 250 * (attempt + 1));
            }
            return;
        }
        // Report figures are presentation assets. Read them concurrently after
        // the control-plane snapshot has painted, so a large report never
        // delays chat/session switching or the clinical viewer restore.
        void Promise.all(pending.map(async figure => {
            try {
                const cached = await window.SessionCache.get(String(sessionId), 'report', figure._cacheKey);
                if (cached && cached.byteLength > 0) {
                    return { figure, dataUrl: new TextDecoder().decode(cached) };
                }
            } catch (_) {}
            return null;
        })).then(results => {
            if (String(activeSessionId || '') !== String(sessionId || '')
                || restoreGeneration !== workspaceRestoreGeneration) return;
            results.forEach(result => {
                if (!result) return;
                result.figure.dataUrl = result.dataUrl;
                delete result.figure._cacheKey;
            });
            const recovered = results.filter(Boolean).length;
            if (!recovered && attempt < 5) {
                setTimeout(() => hydrateReportFigureAssets(snapshot, sessionId, restoreGeneration, attempt + 1, report), 350 * (attempt + 1));
                return;
            }
            try { renderReportEditor(); } catch (_) {}
            try { _updateReportPreview(); } catch (_) {}
        });
    }

    async function restoreReportFiguresFromArtifacts(
        targetForm,
        sessionId,
        planningId,
        restoreGeneration,
    ) {
        if (!targetForm || !Array.isArray(targetForm.figures)) return 0;
        const existingFigures = normalizeReportFigures(targetForm.figures, {
            language: targetForm.language,
        });
        let artifacts = typeof dataTreeState !== 'undefined'
            && Array.isArray(dataTreeState?.exportArtifacts)
            ? dataTreeState.exportArtifacts : [];
        if (!artifacts.length && typeof hydrateDataTreeArtifactCatalog === 'function') {
            try { artifacts = await hydrateDataTreeArtifactCatalog(); } catch (_) { artifacts = []; }
        }
        if (String(activeSessionId || '') !== String(sessionId || '')
            || restoreGeneration !== workspaceRestoreGeneration) return 0;
        const screenshots = artifacts.filter(item => {
            const dataType = String(item?.dataType || item?.type || '');
            const objectId = String(item?.objectId || '');
            const filename = objectId.includes(':') ? objectId.split(':').slice(1).join(':') : objectId;
            const ownerPlanning = String(item?.planningId || '');
            return ['screenshot', 'report_figure'].includes(dataType)
                && /^report_screenshot_[^/\\]+\.png$/i.test(filename)
                && (!ownerPlanning || !planningId || ownerPlanning === String(planningId));
        });
        if (!screenshots.length) {
            targetForm.figures = existingFigures;
            return existingFigures.length;
        }
        const recoveredFigureMetadata = (axis, viewMetadata = {}) => {
            const map = {
                report_fig1_global: { figureGroup: 'figure1', figureNumber: 1, subfigure: 'a', sortOrder: 1, captureRole: 'planning_overview' },
                report_fig1_closeup: { figureGroup: 'figure1', figureNumber: 1, subfigure: 'b', sortOrder: 2, captureRole: 'planning_closeup' },
                report_fig2_axial: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'a', sortOrder: 1, captureRole: 'peak_dose_axial' },
                report_fig2_sagittal: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'b', sortOrder: 2, captureRole: 'peak_dose_sagittal' },
                report_fig2_coronal: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'c', sortOrder: 3, captureRole: 'peak_dose_coronal' },
                report_fig2_dose_surface: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'd', sortOrder: 4, captureRole: 'dose_surface_3d' },
                report_fig2_dvh: { figureGroup: 'figure2', figureNumber: 2, subfigure: 'e', sortOrder: 5, captureRole: 'dvh' },
            };
            const base = map[axis] || {};
            const captureContract = String(
                viewMetadata?.capture_contract || viewMetadata?.captureContract || '',
            ).trim();
            return captureContract ? { ...base, captureContract } : base;
        };
        const recoveredFigures = screenshots.map((item, index) => {
            const objectId = String(item.objectId || '');
            const filename = objectId.includes(':') ? objectId.split(':').slice(1).join(':') : objectId;
            const stem = filename.replace(/\.png$/i, '');
            const identityMatch = stem.match(/^report_screenshot_(report_fig[12]_.+)_([0-9a-f]{12})$/i);
            const axis = identityMatch ? identityMatch[1] : `restored-${index + 1}`;
            const figureMetadata = recoveredFigureMetadata(
                axis,
                item.viewMetadata || item.view_metadata || item.metadata || {},
            );
            const title = typeof _t === 'function'
                ? _t(`报告图 ${index + 1}`, `Report Figure ${index + 1}`)
                : `Report Figure ${index + 1}`;
            return {
                id: `restored-report-${filename.replace(/[^a-zA-Z0-9_-]/g, '_')}`,
                type: 'screenshot',
                title,
                axis,
                caption: '',
                _artifactFallback: true,
                dataUrl: `/api/sessions/${encodeURIComponent(sessionId)}/screenshots/${encodeURIComponent(filename)}`,
                _serverUrl: `/api/sessions/${encodeURIComponent(sessionId)}/screenshots/${encodeURIComponent(filename)}`,
                ...figureMetadata,
            };
        });
        // Merge, rather than append, catalog artifacts. A workspace snapshot
        // wins for an already-known role; catalog files only fill genuinely
        // missing roles and old UUID copies collapse to one stable subfigure.
        targetForm.figures = normalizeReportFigures(
            [...existingFigures, ...recoveredFigures],
            { language: targetForm.language },
        );
        try { renderReportEditor(); } catch (_) {}
        try { _updateReportPreview(); } catch (_) {}
        scheduleWorkspaceSave('report.figures.restored-from-catalog');
        return targetForm.figures.length;
    }

    function restoreReportForPlanning(planningId, options = {}) {
        const target = String(planningId || '');
        const byPlanning = window.__reportWorkspaceByPlanning
            && typeof window.__reportWorkspaceByPlanning === 'object'
            ? window.__reportWorkspaceByPlanning
            : {};
        const section = target ? byPlanning[target] : null;
        const report = reportFormFromSnapshot(section);
        if (report && typeof report === 'object') {
            const restored = jsonClone(report);
            restored.editedFields = new Set(restored.editedFields || []);
            restored.sessionId = String(activeSessionId || restored.sessionId || '');
            if (Array.isArray(restored.figures)) {
                restored.figures = normalizeReportFigures(restored.figures, {
                    language: restored.language,
                });
            }
            window.reportForm = restored;
            window.__reportWorkspaceActivePlanningId = target;
            if (window.Report?.sources?._map && Array.isArray(section?.sources)) {
                window.Report.sources._map = new Map(section.sources);
            }
            window.__reportWorkspaceAudit = Array.isArray(section?.audit) ? section.audit : [];
            window.__reportWorkspaceSnapshots = Array.isArray(section?.snapshots) ? section.snapshots : [];
            window._reportCollapsed = section?.collapsed || {};
            if (typeof window.syncReportQualityAssessment === 'function') {
                window.syncReportQualityAssessment(window.reportForm, { preserveStored: true });
            }
            hydrateReportFigureAssets(
                { report: section },
                String(activeSessionId || ''),
                workspaceRestoreGeneration,
                0,
                window.reportForm,
            );
            void restoreReportFiguresFromArtifacts(
                window.reportForm,
                String(activeSessionId || ''),
                target,
                workspaceRestoreGeneration,
            );
        } else if (typeof _newEmptyReportForm === 'function') {
            // A newly created Planning has no report yet. Do not leave the
            // previous run's text visible next to the new dose/needle set.
            window.reportForm = _newEmptyReportForm();
            window.reportForm.sessionId = String(activeSessionId || '');
            window.__reportWorkspaceActivePlanningId = target || null;
            window.__reportWorkspaceAudit = [];
            window.__reportWorkspaceSnapshots = [];
            window._reportCollapsed = {};
        }
        try { if (typeof renderReportEditor === 'function') renderReportEditor(); } catch (_) {}
        try { if (typeof _updateReportPreview === 'function') _updateReportPreview(); } catch (_) {}
        if (options.persist !== false) scheduleWorkspaceSave('planning.report.restored');
        return !!report;
    }

    async function applyWorkspaceSnapshot(snapshot, options = {}) {
        if (!snapshot) return;
        const sessionId = workspaceSnapshotSessionId(snapshot);
        if (!sessionId || sessionId !== String(activeSessionId || '')) return false;
        let qualityAssessmentNeedsPersist = false;
        let reportOwnershipNeedsPersist = false;
        rememberWorkspaceRevision(snapshot);
        const ui = snapshot.ui || {};
        const uiState = ui.state || ui;
        const restoreGeneration = invalidateDeferredWorkspaceRestore();
        restoring = true;
        try {
            applyControls(uiState.controls || {}, Object.assign({}, options, {
                doseValueUnit: uiState.dose_value_unit,
                prescriptionBaseGy: uiState.prescription_base_gy,
                doseScaleGy: uiState.dose_model_scale_gy,
            }));
            if (uiState.viewer && typeof state !== 'undefined') {
                state.slices = Object.assign(state.slices || {}, uiState.viewer.slices || {});
                state.viewerSettings = Object.assign(state.viewerSettings || {}, uiState.viewer.settings || {});
                if (uiState.viewer.doseOpacity != null) state.doseOpacity = uiState.viewer.doseOpacity;
                if (uiState.viewer.doseTexture) state.doseTexture = Object.assign(state.doseTexture || {}, uiState.viewer.doseTexture);
                if (Array.isArray(uiState.viewer.annotations)) {
                    state.annotations = jsonClone(uiState.viewer.annotations);
                }
                // Restore manual/threshold masks (voxels are stored as arrays
                // by jsonClone; convert back to Sets).
                if (uiState.viewer.masks && typeof state !== 'undefined') {
                    const labels = uiState.viewer.masks.labels || {};
                    state.maskLabels = {};
                    Object.entries(labels).forEach(([id, m]) => {
                        if (!m || typeof m !== 'object') return;
                        state.maskLabels[id] = {
                            ...m,
                            voxels: new Set(Array.isArray(m.voxels) ? m.voxels : []),
                        };
                    });
                    state.maskLabelCounter = Number(uiState.viewer.masks.counter) || 0;
                    state.activeMaskId = uiState.viewer.masks.activeMaskId || null;
                }
            }
            if (uiState.data_tree && typeof dataTreeState !== 'undefined') {
                if (options.preserveClinicalData) applyDataTreePresentation(uiState.data_tree);
                else applyDataTreeSnapshot(uiState.data_tree);
            }
            if (!options.preserveClinicalData && uiState.manual && typeof _saveManualState === 'function') {
                _saveManualState(uiState.manual);
            }
            if (typeof window.restoreManualWorkflowProgress === 'function') {
                window.restoreManualWorkflowProgress();
            }
            if (typeof trainingMonitorState !== 'undefined') {
                // The browser snapshot keeps presentation details while the
                // server bridge keeps feedback/events emitted by tools.
                Object.assign(trainingMonitorState, ui.bridge?.training || {}, uiState.training || {});
                // A snapshot can come from an older browser bridge without a
                // reliable owner id. The workspace id is authoritative after
                // the ownership check above.
                trainingMonitorState.sessionId = sessionId;
                trainingMonitorState.screenshotGalleryContext = null;
                trainingMonitorState.runId = trainingMonitorState.run_id
                    || trainingMonitorState.runId
                    || null;
                trainingMonitorState.language = trainingMonitorState.language
                    || window.conversationLanguageForSession?.(sessionId)
                    || window._i18nLang
                    || 'en';
                const restoredMonitorRunId = trainingMonitorState.runId;
                const restoredMonitorWasActive = !!trainingMonitorState.active;
                // A durable snapshot may outlive the browser/server process
                // that created the run. It is history, not proof of a live
                // monitor subscription. End it silently and never resurrect
                // the global monitor presentation during hydration.
                if (restoredMonitorWasActive) {
                    trainingMonitorState.active = false;
                    trainingMonitorState.phase = 'inactive';
                    trainingMonitorState.runId = null;
                    trainingMonitorState.pendingFeedback = [];
                    trainingMonitorState.screenshotGalleryContext = null;
                    if (typeof window.setTrainingMonitorPhase === 'function') {
                        window.setTrainingMonitorPhase('inactive');
                    } else if (typeof window.setMonitorPresentation === 'function') {
                        window.setMonitorPresentation('inactive');
                    } else {
                        document.body.classList.remove('monitor-active');
                    }
                    if (typeof window.releaseTrainingMonitorForSession === 'function') {
                        void window.releaseTrainingMonitorForSession(
                            sessionId,
                            'workspace_restore',
                            { runId: restoredMonitorRunId, skipLocal: true },
                        );
                    }
                } else if (typeof window.setTrainingMonitorPhase === 'function') {
                    window.setTrainingMonitorPhase('inactive');
                } else if (typeof window.setMonitorPresentation === 'function') {
                    window.setMonitorPresentation('inactive');
                } else {
                    document.body.classList.remove('monitor-active');
                }
            }
            const reportSection = snapshot.report && typeof snapshot.report === 'object'
                ? snapshot.report : null;
            const savedTreePlanning = uiState.data_tree?.planning || {};
            const planningIdentity = workspacePlanningIdentity(snapshot);
            const targetPlanningId = String(
                planningIdentity.activeId
                || savedTreePlanning.activePlanningId
                || savedTreePlanning.id
                || reportSection?.active_planning_id
                || '',
            );
            if (targetPlanningId && typeof dataTreeState !== 'undefined' && dataTreeState?.planning) {
                dataTreeState.planning.activePlanningId = targetPlanningId;
            }
            const reportMap = sessionBoundReportMap(
                reportSection?.by_planning_id,
                sessionId,
                planningIdentity.ids,
            );
            const rawReportMap = reportSection?.by_planning_id;
            const rawReportCount = rawReportMap && typeof rawReportMap === 'object'
                ? Object.keys(rawReportMap).length : 0;
            reportOwnershipNeedsPersist = !!reportSection && (
                rawReportCount !== Object.keys(reportMap).length
                || String(reportSection?.active_planning_id || '') !== targetPlanningId
            );
            const declaredReportPlanningId = String(
                reportSection?.active_planning_id || '',
            );
            const legacyReportOwner = reportSectionSessionId(reportSection);
            if (targetPlanningId && !reportMap[targetPlanningId]
                && reportFormFromSnapshot(reportSection)
                && (!declaredReportPlanningId || declaredReportPlanningId === targetPlanningId)
                && (!legacyReportOwner || legacyReportOwner === sessionId)) {
                const legacySection = { ...reportSection };
                delete legacySection.active_planning_id;
                delete legacySection.by_planning_id;
                delete legacySection.byPlanning;
                reportMap[targetPlanningId] = legacySection;
                reportOwnershipNeedsPersist = true;
            }
            window.__reportWorkspaceByPlanning = reportMap;
            window.__reportWorkspaceActivePlanningId = targetPlanningId || null;
            window.__reportWorkspaceSessionId = sessionId;
            const boundedReportSection = reportSection ? {
                ...reportSection,
                active_planning_id: targetPlanningId || null,
                by_planning_id: reportMap,
            } : null;
            const selectedReportSection = reportSectionForPlanning(boundedReportSection, targetPlanningId);
            const report = reportFormFromSnapshot(selectedReportSection);
            if (report && typeof report === 'object') {
                const keepCurrentReport = _preservePopulatedReport(window.reportForm, report, options);
                if (!keepCurrentReport) {
                    report.editedFields = new Set(report.editedFields || []);
                    report.sessionId = sessionId;
                    window.reportForm = report;
                }
                const targetReport = keepCurrentReport ? window.reportForm : report;
                if (keepCurrentReport) {
                    // The current form may already contain hydrated narrative
                    // text, while the control-plane snapshot is the authority
                    // for the selected Planning's quality cells. Merge only
                    // rows whose metric value still matches; never mix one
                    // Planning run's assessment into another run.
                    _mergePersistedQualityAssessment(targetReport, report.qualityAssessment);
                }
                const previousQualityTimestamp = Number(targetReport?.qualityAssessment?.generatedAt || 0);
                if (typeof window.syncReportQualityAssessment === 'function') {
                    window.syncReportQualityAssessment(targetReport, { preserveStored: true });
                    qualityAssessmentNeedsPersist = Number(targetReport?.qualityAssessment?.generatedAt || 0)
                        !== previousQualityTimestamp;
                }
                // Keep cache metadata from the control-plane snapshot attached
                // to the populated form when that form is newer. This lets the
                // image hydrate without replacing its narrative fields.
                if (keepCurrentReport && Array.isArray(report.figures) && Array.isArray(targetReport.figures)) {
                    report.figures.forEach(savedFigure => {
                        if (!savedFigure?._cacheKey) return;
                        const targetFigure = targetReport.figures.find(candidate =>
                            candidate && (candidate.id && savedFigure.id
                                ? candidate.id === savedFigure.id
                                : (candidate.axis || candidate.title || '') === (savedFigure.axis || savedFigure.title || ''))
                        );
                        if (targetFigure && !targetFigure.dataUrl) targetFigure._cacheKey = savedFigure._cacheKey;
                    });
                }
                if (targetPlanningId && selectedReportSection) {
                    window.__reportWorkspaceByPlanning[targetPlanningId] = selectedReportSection;
                }
                hydrateReportFigureAssets({ report: selectedReportSection }, sessionId, restoreGeneration, 0, targetReport);
                void restoreReportFiguresFromArtifacts(
                    targetReport,
                    sessionId,
                    targetPlanningId,
                    restoreGeneration,
                );
                const storedSources = selectedReportSection?.sources;
                if (window.Report?.sources?._map && Array.isArray(storedSources)) {
                    window.Report.sources._map = new Map(storedSources);
                }
                window.__reportWorkspaceAudit = Array.isArray(selectedReportSection?.audit) ? selectedReportSection.audit : [];
                window.__reportWorkspaceSnapshots = Array.isArray(selectedReportSection?.snapshots) ? selectedReportSection.snapshots : [];
                window._reportCollapsed = selectedReportSection?.collapsed || {};
                try { renderReportEditor(); } catch (_) {}
                try { _updateReportPreview(); } catch (_) {}
            } else if (targetPlanningId && reportSection?.by_planning_id) {
                // Keep a newly-created or geometry-only Planning visually
                // honest: it has no report until its own dose/guide results
                // are generated. Never leave the previous run's text in the
                // editor merely because the selected run has no entry yet.
                restoreReportForPlanning(targetPlanningId, { persist: false });
            }
            const chat = snapshot.chat || {};
            if (sessionId !== String(activeSessionId || '')) return false;
            window._sessionChatQueues = window._sessionChatQueues || {};
            if (!options.skipChat) {
                window._sessionChatQueues[sessionId] = Array.isArray(chat.queued) ? jsonClone(chat.queued) : [];
                window._sessionChatTaskStatuses = window._sessionChatTaskStatuses || {};
                if (chat.task_id) {
                    window._sessionChatTaskIds = window._sessionChatTaskIds || {};
                    window._sessionChatTaskIds[sessionId] = chat.task_id;
                    window._sessionChatTaskStatuses[sessionId] = chat.task_status || 'running';
                } else {
                    // A fast switch snapshot may be one write behind the
                    // live task identity. Preserve the local hint until the
                    // case-scoped task endpoint confirms its terminal state.
                    const localTaskId = window._sessionChatTaskIds?.[sessionId]
                        || window._detachedChatTasks?.[sessionId]
                        || null;
                    const savedStatus = String(chat.task_status || '');
                    const preserveLiveTask = !!localTaskId
                        && (!savedStatus || savedStatus === 'idle' || savedStatus === 'running');
                    if (!preserveLiveTask) {
                        delete window._sessionChatTaskIds?.[sessionId];
                        delete window._detachedChatTasks?.[sessionId];
                        window._sessionChatTaskStatuses[sessionId] = chat.task_status || 'idle';
                    } else {
                        window._sessionChatTaskStatuses[sessionId] = 'running';
                    }
                }
            }
            let chatMessages = Array.isArray(chat.messages) ? chat.messages : null;
            if (!chatMessages && Array.isArray(chat.execution_trace) && chat.execution_trace.length) {
                const rawTimestamp = Number(chat.updated_at || snapshot.saved_at || Date.now());
                chatMessages = [{
                    type: 'thinking',
                    content: '',
                    steps: jsonClone(chat.execution_trace),
                    timestamp: rawTimestamp < 1e12 ? rawTimestamp * 1000 : rawTimestamp,
                }];
            }
            if (!options.skipChat && Array.isArray(chatMessages) && typeof sessions !== 'undefined' && sessions[sessionId]) {
                const localMsgs = sessions[sessionId].messages || [];
                // Merge by stable message/request identity instead of using
                // array length as a freshness signal.  A server snapshot can
                // have the same number of rows while lacking a newly-uploaded
                // image attachment; replacing it would make the image vanish
                // after every refresh or Session switch.
                sessions[sessionId].messages = typeof window.mergeSessionChatMessages === 'function'
                    ? window.mergeSessionChatMessages(sessionId, chatMessages, localMsgs, chat.attachments)
                    : chatMessages;
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
            // Label/planning hydration may finish before this presentation
            // snapshot is applied. Reconcile once more after the snapshot so
            // valid current-case masks cannot remain in CT-only mode or be
            // painted only in an old canvas generation.
            if (typeof window.reconcileSegmentationViewerState === 'function') {
                window.reconcileSegmentationViewerState({
                    sessionId,
                    reason: 'workspace-presentation-restored',
                });
            }
            // Sync viewer DOM controls from restored state so checkboxes,
            // select, and sliders match what was saved. applyControls()
            // restores raw DOM values, but onchange handlers can desync
            // state.viewerSettings from the DOM — this locks them back.
            _syncViewerControlsFromState();
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
            if ((qualityAssessmentNeedsPersist || reportOwnershipNeedsPersist)
                && options.persist !== false) {
                scheduleWorkspaceSave(
                    reportOwnershipNeedsPersist
                        ? 'report.session-planning-ownership.repaired'
                        : 'report.quality_assessment.restored',
                );
            }
            return true;
        } finally {
            restoring = false;
        }
    }

    function workspaceSavePayload(ownerSessionId, reason) {
        return {
            session_id: ownerSessionId,
            revision: sessionRevisions[ownerSessionId] ?? revision,
            ui_state: workspaceUiState(ownerSessionId),
            report: reportState(ownerSessionId),
            chat: chatState(ownerSessionId),
            reason,
        };
    }

    async function postWorkspaceSave(ownerSessionId, payload) {
        const response = await workspaceFetch('/api/workspace/state', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-BrachyBot-Session': ownerSessionId,
            },
            body: JSON.stringify(payload),
        });
        return {
            response,
            data: await response.json().catch(() => null),
        };
    }

    async function persistWorkspace(reason, options = {}) {
        const ownerSessionId = String(options.sessionId || activeSessionId || '');
        if ((restoring && !options.allowDuringRestore) || !window.brachybotAuth?.user || !ownerSessionId) return false;
        if (workspaceSaveInFlight[ownerSessionId]) {
            // UI/report/chat writes are snapshots of the same selected case.
            // Serialize them so two debounce timers cannot race their CAS
            // revisions and fill the browser console with avoidable 409s.
            workspaceSaveQueuedReasons[ownerSessionId] = reason || 'ui.changed';
            return workspaceSaveInFlight[ownerSessionId];
        }

        // Capture the old case's complete payload before any asynchronous
        // retry or Session transition can change the global UI state. A
        // retry must update only its compare-and-swap revision; rebuilding
        // the payload from workspaceSavePayload() after a switch would send
        // the newly selected case's report/chat under the old session_id.
        const initialPayload = workspaceSavePayload(ownerSessionId, reason);
        const save = (async () => {
            // A server-side checkpoint can advance the revision between a
            // browser render and its debounced save. The route returns that
            // revision, so retry once with the same case-owned payload and
            // the authoritative CAS token.
            for (let attempt = 0; attempt < 2; attempt += 1) {
                const payload = attempt === 0
                    ? initialPayload
                    : Object.assign({}, initialPayload, {
                        revision: sessionRevisions[ownerSessionId] ?? initialPayload.revision,
                    });
                const { response, data } = await postWorkspaceSave(ownerSessionId, payload);
                if (response.status === 409) {
                    if (data?.code === 'workspace_locked' && ownerSessionId === String(activeSessionId || '')) {
                        document.body.classList.add('workspace-readonly');
                        return false;
                    }
                    const currentRevision = Number(data?.current_revision ?? data?.revision);
                    if (data?.code === 'stale_workspace'
                        && Number.isFinite(currentRevision)
                        && attempt === 0) {
                        sessionRevisions[ownerSessionId] = currentRevision;
                        if (ownerSessionId === String(activeSessionId || '')) revision = currentRevision;
                        continue;
                    }
                    console.debug('[workspace] save skipped after revision conflict');
                    return false;
                }
                if (data?.success) {
                    sessionRevisions[ownerSessionId] = data.revision;
                    if (ownerSessionId === String(activeSessionId || '')) revision = data.revision;
                }
                return !!data?.success;
            }
            return false;
        })();
        workspaceSaveInFlight[ownerSessionId] = save;
        try {
            return await save;
        } catch (error) {
            console.debug('[workspace] save deferred:', error);
            return false;
        } finally {
            if (workspaceSaveInFlight[ownerSessionId] === save) {
                delete workspaceSaveInFlight[ownerSessionId];
                const queuedReason = workspaceSaveQueuedReasons[ownerSessionId];
                delete workspaceSaveQueuedReasons[ownerSessionId];
                if (queuedReason && ownerSessionId === String(activeSessionId || '')) {
                    setTimeout(() => { void persistWorkspace(queuedReason); }, 0);
                }
            }
        }
    }

    function scheduleWorkspaceSave(reason) {
        clearScheduledWorkspaceSave();
        const ownerSessionId = String(activeSessionId || '');
        saveTimer = setTimeout(() => {
            saveTimer = null;
            // The transition path flushes the old case explicitly. A timer
            // that outlives that transition must never serialize the new case
            // using the old case's report/chat payload.
            if (!ownerSessionId || ownerSessionId !== String(activeSessionId || '')) return;
            void persistWorkspace(reason || 'ui.changed');
        }, 700);
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
        updateRecycleBinCount(data?.trashed_count);
        const requested = String(data.active_session_id || '');
        const available = Object.keys(sessions);
        activeSessionId = requested && sessions[requested]
            ? requested
            : (available[0] || null);
        if (!activeSessionId) {
            window._activeWorkspaceSnapshot = null;
            cancelBackgroundWorkspaceRestore();
        }
    }

    function paintSessionShell(sessionId, { clearWorkspace = true, blank = false } = {}) {
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
        if (typeof trainingMonitorState !== 'undefined') {
            // Background work remains attached to its original case, but its
            // live monitor UI must never bleed into the newly selected case.
            trainingMonitorState.active = false;
            trainingMonitorState.phase = 'inactive';
            trainingMonitorState.runId = null;
            trainingMonitorState.goal = '';
            trainingMonitorState.sessionId = sessionId;
            trainingMonitorState.language = window.conversationLanguageForSession?.(sessionId)
                || window._i18nLang
                || 'en';
            trainingMonitorState.screenshotGalleryContext = null;
            trainingMonitorState.lastFeedbackAt = 0;
            trainingMonitorState.lastScreenshotAt = 0;
            if (typeof window.setTrainingMonitorPhase === 'function') {
                window.setTrainingMonitorPhase('inactive');
            } else if (typeof window.setMonitorPresentation === 'function') {
                window.setMonitorPresentation('inactive');
            } else {
                document.body.classList.remove('monitor-active');
            }
        }
        revision = sessionRevisions[sessionId] ?? null;
        window._activeWorkspaceSnapshot = null;
        if (clearWorkspace && typeof clearClientWorkspace === 'function') {
            clearClientWorkspace({ clearReport: true, deferDisposal: true });
        }
        renderSessionList();
        const title = document.getElementById('chatSessionTitle');
        if (title) title.textContent = next.title || 'New case';
        const sessionDisplay = document.getElementById('sessionDisplay');
        if (sessionDisplay) sessionDisplay.textContent = sessionId;
        // Do not leave the prior transcript beneath an optimistically
        // highlighted case. A durable chat snapshot replaces this shell as
        // soon as the control-plane response arrives.
        if (typeof loadSessionChat === 'function') loadSessionChat(sessionId);
        // A newly-created case has no resources to hydrate.  Keeping the
        // generic opening notice here made a zero-resource operation look as
        // if the previous case was still being restored.  Existing-case
        // switching keeps the notice because CT/labels/meshes may still be
        // loaded in the background.
        if (blank) {
            window.setWorkspaceHydrationState?.(false);
        } else {
            window.showCaseResourceLoading?.({ sessionId });
        }
        return true;
    }

    function yieldWorkspaceShellPaint() {
        // A requestAnimationFrame callback runs immediately before painting.
        // Hop once more to a task so the browser can present the selected
        // Session shell before a potentially large old-case serialization.
        return new Promise(resolve => {
            const afterFrame = () => setTimeout(resolve, 0);
            if (typeof requestAnimationFrame === 'function') requestAnimationFrame(afterFrame);
            else setTimeout(afterFrame, 0);
        });
    }

    async function loadServerSessions({ commit = true, timeoutMs = WORKSPACE_REQUEST_TIMEOUT_MS } = {}) {
        const response = await workspaceFetch('/api/sessions', {}, timeoutMs);
        if (!response.ok) throw new Error(`Session list failed: HTTP ${response.status}`);
        const data = await response.json();
        if (commit) applySessionList(data);
        else updateRecycleBinCount(data?.trashed_count);
        if (!data.active_session_id && !Object.keys(sessions).length) {
            cancelBackgroundWorkspaceRestore();
        }
        return data;
    }

    window.reconcileActiveSession = async function reconcileActiveSession(preferredSessionId = '') {
        const preferred = String(preferredSessionId || '').trim().toLowerCase();
        const data = await loadServerSessions({ commit: false });
        const nextSessions = sessionMapFromPayload(data);
        const nextIds = Object.keys(nextSessions);
        const serverActive = String(data.active_session_id || '').trim().toLowerCase();
        const resolved = preferred && nextSessions[preferred]
            ? preferred
            : (serverActive && nextSessions[serverActive] ? serverActive : (nextIds[0] || ''));
        if (!resolved) {
            throw new Error('No available case session was found.');
        }
        sessions = nextSessions;
        activeSessionId = resolved;
        if (typeof state !== 'undefined') state.sessionId = resolved;
        updateRecycleBinCount(data?.trashed_count);
        renderSessionList();
        return resolved;
    };

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
        // The active case already received the authoritative SSE tool events.
        // Starting a second full CT/mesh restore here races the live viewer,
        // replays expensive array work, and shows a misleading loading notice
        // after a task has completed. Full hydration remains reserved for a
        // cold session switch or browser reconnect.
        return true;
    }

    async function recoverWorkspaceAfterTransitionFailure(generation) {
        try {
            const sessionData = await loadServerSessions({ commit: false, timeoutMs: WORKSPACE_RECOVERY_TIMEOUT_MS });
            const availableSessions = sessionMapFromPayload(sessionData);
            const serverActive = String(sessionData.active_session_id || '');
            const recoverySessionId = serverActive && availableSessions[serverActive]
                ? serverActive
                : (Object.keys(availableSessions)[0] || '');
            if (!recoverySessionId) {
                throw new Error('No available case session was found during recovery.');
            }
            // The failed transition may leave the browser pointing at an
            // optimistic, deleted, or otherwise stale case. Bind the recovery
            // snapshot to the authoritative server list instead of replaying
            // that stale identity and cascading 404s across every API call.
            const workspace = await loadActiveWorkspace({
                commit: false,
                timeoutMs: WORKSPACE_RECOVERY_TIMEOUT_MS,
                sessionId: recoverySessionId,
            });
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
        const listStartedAt = workspaceNow();
        const data = await loadServerSessions();
        recordWorkspacePerformance('startup.session_list', {
            sessionId: String(data.active_session_id || ''),
            startedAt: listStartedAt,
            details: { count: Array.isArray(data.sessions) ? data.sessions.length : 0 },
        });
        // The session directory is control-plane data. Render it immediately
        // after /api/sessions, before the selected case snapshot begins its
        // potentially slow CT/label/mesh restoration. Previously the first
        // sidebar paint was held behind loadActiveWorkspace(), so old cases
        // appeared only after an unrelated later action such as New Case.
        renderSessionList();
        recordWorkspacePerformance('startup.session_list_first_paint', {
            sessionId: String(activeSessionId || ''),
            startedAt: listStartedAt,
        });
        if (!activeSessionId) {
            window._activeWorkspaceSnapshot = null;
            window.setWorkspaceHydrationState?.(false);
            return data;
        }
        const snapshotStartedAt = workspaceNow();
        const workspace = await loadActiveWorkspace();
        recordWorkspacePerformance('startup.snapshot', {
            sessionId: String(activeSessionId || ''),
            startedAt: snapshotStartedAt,
        });
        // Paint the durable transcript before /status and clinical hydration.
        // The latter may load CT, labels, meshes, dose arrays, and an agent;
        // none of that should make a restored conversation look missing.
        applyChatSnapshotFast(workspace);
        recordWorkspacePerformance('startup.chat_first_paint', {
            sessionId: String(activeSessionId || ''),
            startedAt: snapshotStartedAt,
        });
        // A browser refresh has no trustworthy live in-memory transcript.
        // Apply the server snapshot authoritatively before starting the heavy
        // CT/mesh restore; otherwise a stale local shell can hide the last
        // assistant answer while the task/status spinner is already visible.
        await applyWorkspaceSnapshot(workspace, {
            authoritativeChat: true,
            // The startup snapshot is a compact control-plane projection. It
            // contains paths and presentation preferences, but not decoded CT
            // voxels or live Three.js objects. Treating it as clinical state
            // used to create a convincing Data Tree shell while clearing the
            // real viewer arrays that the background restore was about to
            // hydrate. Session switching already uses the correct contract:
            // paint the transcript/preferences first, then let the
            // session-scoped loaders reconstruct CT, labels and planning data.
            preserveClinicalData: true,
            // Never checkpoint the transient pre-hydration shell. In
            // particular, a blank report form must not overwrite a durable
            // planning-specific report before source-backed auto-fill runs.
            persist: false,
        });
        if (!workspaceSnapshotHasClinicalResources(workspace)) {
            cancelBackgroundWorkspaceRestore();
        } else {
            scheduleBackgroundWorkspaceRestore(workspace, activeSessionId);
        }
        return data;
    };

    window.saveSessions = function saveSessions() {
        // The server workspace is the only durable source.  Keep no clinical
        // transcript in localStorage; this invocation simply coalesces a save.
        scheduleWorkspaceSave('chat.changed');
    };

    window.newChat = async function newChat() {
        return runWorkspaceTransition(async () => {
            const createStartedAt = workspaceNow();
            if (!await prepareSessionChange()) return { success: false, cancelled: true };
            const previousSessionId = String(activeSessionId || '');
            if (previousSessionId && typeof window.releaseTrainingMonitorForSession === 'function') {
                void window.releaseTrainingMonitorForSession(previousSessionId, 'new_session', { forceRequest: true });
            }
            // Paint a genuinely empty case on the next animation frame instead
            // of holding the previous transcript and viewer until the server
            // has allocated an id. The temporary id cannot reach a clinical
            // endpoint because every mutation awaits activeSessionReadiness.
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
            pendingSessionCreationId = optimisticId;
            // New cases are an empty control-plane shell.  Do not show an
            // opening-case resource spinner and do not schedule hydration;
            // the old case's server task remains detached and case-owned.
            paintSessionShell(optimisticId, { blank: true, clearWorkspace: false });
            recordWorkspacePerformance('create.shell_first_paint', {
                sessionId: optimisticId,
                startedAt: createStartedAt,
            });
            await yieldWorkspaceShellPaint();
            // The old form/viewer is still intact while this synchronous
            // snapshot is captured. Explicit ownership prevents it from
            // inheriting the optimistic Session id painted above.
            const previousCaseFlush = typeof flushActiveReportState === 'function'
                ? Promise.resolve(flushActiveReportState({ sessionId: previousSessionId }))
                : Promise.resolve(persistWorkspace('session.switching', { sessionId: previousSessionId }));
            void previousCaseFlush.catch(error => {
                console.debug('[workspace] previous case flush deferred:', error);
            });
            if (typeof clearClientWorkspace === 'function') {
                clearClientWorkspace({ clearReport: true, deferDisposal: true });
            }
            let response;
            try {
                response = await workspaceFetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'New case' }) });
            } catch (error) {
                delete sessions[optimisticId];
                if (pendingSessionCreationId === optimisticId) pendingSessionCreationId = null;
                throw error;
            }
            const data = await response.json();
            if (!response.ok) {
                delete sessions[optimisticId];
                if (pendingSessionCreationId === optimisticId) pendingSessionCreationId = null;
                // Do not paint the previous shell — its chat, viewer, and
                // report are still in the DOM.  Just revert the active id
                // and sidebar highlight.
                if (previousSessionId && sessions[previousSessionId]) {
                    activeSessionId = previousSessionId;
                    if (typeof state !== 'undefined') state.sessionId = previousSessionId;
                    // Keep the rollback repaint local to the failed create
                    // path. The authoritative create path below must be the
                    // first sidebar repaint after the session upsert.
                    renderSessionListAfterCreateFailure();
                    if (typeof loadSessionChat === 'function') loadSessionChat(previousSessionId);
                }
                cancelTransitionUi();
                throw new Error(data.error || 'Unable to create case');
            }
            const createdSession = data.session;
            delete sessions[optimisticId];
            if (pendingSessionCreationId === optimisticId) pendingSessionCreationId = null;
            if (createdSession?.id) {
                // The create endpoint returns the authoritative session entry.
                // Upsert it before rendering so the sidebar reacts immediately
                // without a second list request or a delayed chat checkpoint.
                sessions[createdSession.id] = sessionStateFromPayload(createdSession);
            }
            activeSessionId = data.active_session_id || createdSession?.id || activeSessionId;
            recordWorkspacePerformance('create.server_confirmed', {
                sessionId: String(activeSessionId || ''),
                startedAt: createStartedAt,
            });
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
        // A transition is already in flight.  Abort its server request so
        // it bails out quickly instead of waiting for the 15 s timeout, then
        // queue this new target.  The finalised transition will auto-run the
        // queued switch, so the user's latest click always wins.
        if (workspaceTransition) {
            if (_switchAbortController) {
                _switchAbortController.abort();
                _switchAbortController = null;
            }
            pendingSwitchSessionId = id;
            return { success: true, queued: true, session_id: id };
        }
        return runWorkspaceTransition(async () => {
            const switchStartedAt = workspaceNow();
            _switchAbortController = new AbortController();
            const aborter = _switchAbortController;
            // The spinner is always the lower-right case-resource notice;
            // keep the immediate switch feedback and cold-start feedback
            // visually indistinguishable.
            window.showCaseResourceLoading?.({ sessionId: id });
            document.body.classList.add('workspace-hydrating');
            if (!(await prepareSessionChange())) {
                cancelTransitionUi();
                return { success: false, cancelled: true };
            }
            const previousSessionId = activeSessionId;
            if (previousSessionId && typeof window.releaseTrainingMonitorForSession === 'function') {
                void window.releaseTrainingMonitorForSession(previousSessionId, 'session_switch', { forceRequest: true });
            }
            if (typeof window.brachybotAuth?.releaseLease === 'function') {
                void window.brachybotAuth.releaseLease(previousSessionId).catch(error => console.debug('[workspace] lease release deferred:', error));
            }
            // Session selection is a control-plane action. Paint the new
            // shell before waiting for the server-side Agent/workspace
            // hydration so the sidebar, title, transcript and empty viewer
            // respond on the same frame as a normal panel switch. The server
            // request remains authoritative; failure below restores the old
            // shell instead of leaving a false selection highlighted.
            // Keep the old clinical projection in memory for one paint only.
            // The detached, explicitly owned checkpoint below captures it
            // after the new sidebar/title/transcript have become visible.
            paintSessionShell(id, { clearWorkspace: false });
            recordWorkspacePerformance('switch.shell_first_paint', {
                sessionId: id,
                startedAt: switchStartedAt,
            });
            await yieldWorkspaceShellPaint();
            const previousCaseFlush = typeof flushActiveReportState === 'function'
                ? Promise.resolve(flushActiveReportState({ sessionId: previousSessionId }))
                : Promise.resolve(persistWorkspace('session.switching', { sessionId: previousSessionId }));
            void previousCaseFlush.catch(error => {
                console.debug('[workspace] previous case flush deferred:', error);
            });
            if (typeof clearClientWorkspace === 'function') {
                clearClientWorkspace({ clearReport: true, deferDisposal: true });
            }
            let response;
            try {
                response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}/select`, { method: 'POST', signal: aborter.signal });
            } catch (error) {
                if (aborter.signal.aborted) return { success: false, replaced: true };
                paintSessionShell(previousSessionId);
                cancelTransitionUi();
                throw error;
            }
            const data = await response.json();
            if (!response.ok) {
                paintSessionShell(previousSessionId);
                cancelTransitionUi();
                throw new Error(data.error || 'Unable to open case');
            }
            // Server confirmed the switch. Keep the optimistic shell and
            // replace it with the authoritative snapshot below.
            activeSessionId = data.active_session_id;
            recordWorkspacePerformance('switch.snapshot_received', {
                sessionId: id,
                startedAt: switchStartedAt,
            });
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
            recordWorkspacePerformance('switch.presentation_ready', {
                sessionId: id,
                startedAt: switchStartedAt,
            });
            if (typeof window.brachybotAuth?.acquireLease === 'function') {
                void window.brachybotAuth.acquireLease(activeSessionId).catch(error => console.debug('[workspace] lease refresh deferred:', error));
            }
            return { success: true, session_id: activeSessionId };
        });
    };

    // Keep a failed optimistic create rollback separate from the
    // authoritative create repaint. This wrapper is hoisted by the browser
    // and intentionally delegates to the legacy renderer supplied by the
    // chat layer.
    function renderSessionListAfterCreateFailure() {
        renderSessionList();
    }

    async function clearDeletedSessionBrowserData(sessionId) {
        const id = String(sessionId || '');
        if (!id) return;
        const jobs = [];
        if (window.SessionCache) {
            jobs.push(Promise.resolve(window.SessionCache.invalidateSession(id)));
        }
        try { removeSessionScopedLocalState(id); } catch (_) {}

        // Earlier builds saved a few session-scoped recovery and UI keys
        // outside the four known clinical form keys. Remove only keys whose
        // scope is unambiguously this deleted case; global preferences and
        // the editor identity intentionally remain intact.
        const scoped = key => key.endsWith(`:${id}`) || key.includes(`:${id}:`);
        for (const storage of [window.localStorage, window.sessionStorage]) {
            try {
                const keys = [];
                for (let index = 0; index < storage.length; index += 1) {
                    const key = storage.key(index);
                    if (key && scoped(key)) keys.push(key);
                }
                keys.forEach(key => storage.removeItem(key));
            } catch (_) {}
        }

        // Remove the deleted case from the pre-workspace aggregate as well.
        // It is no longer used for normal persistence, but a stale legacy
        // blob must not be able to resurrect a deleted sidebar entry after a
        // failed bootstrap or a browser downgrade.
        try {
            const rawSessions = window.localStorage.getItem('brachybot_sessions');
            const legacySessions = rawSessions ? JSON.parse(rawSessions) : null;
            if (legacySessions && typeof legacySessions === 'object' && legacySessions[id]) {
                delete legacySessions[id];
                window.localStorage.setItem('brachybot_sessions', JSON.stringify(legacySessions));
            }
            if (window.localStorage.getItem('brachybot_active_session') === id) {
                window.localStorage.removeItem('brachybot_active_session');
            }
        } catch (_) {}
        delete sessionRevisions[id];
        delete window._sessionChatQueues?.[id];
        delete window._sessionChatTaskIds?.[id];
        delete window._sessionChatTaskStatuses?.[id];
        delete window._detachedChatTasks?.[id];
        await Promise.allSettled(jobs);
    }

    function updateRecycleBinCount(count) {
        const target = document.getElementById('recycleBinCount');
        if (!target) return;
        const value = Math.max(0, Number(count) || 0);
        target.textContent = value > 99 ? '99+' : String(value);
        target.hidden = value === 0;
    }

    window.deleteSession = async function deleteSession(id, options = {}) {
        if (!sessions[id]) return { success: false, error: 'The requested case does not exist.' };
        if (options.skipConfirm !== true) {
            const title = sessions[id].title || id;
            const confirmed = await confirmWorkspaceAction(
                `确定要永久删除病例“${title}”吗？此操作无法撤销。`,
                `Permanently delete case "${title}"? This cannot be undone.`,
            );
            if (!confirmed) return { success: false, cancelled: true };
        }
        // Always delete optimistically — remove from the list immediately,
        // send the server request in the background, and restore on failure.
        // The old active-session path used runWorkspaceTransition which could
        // silently reject (busy) and leave the user with no visible feedback.
        const removedSession = sessions[id];
        if (typeof window.releaseTrainingMonitorForSession === 'function') {
            void window.releaseTrainingMonitorForSession(id, 'session_deleted', { forceRequest: true });
        }
        // Inactive cases are deliberately independent from the active
        // clinical task. They are removed from the optimistic sidebar and
        // deleted in the background without prepareSessionChange().
        if (id !== activeSessionId) {
            // The active-case handoff uses
            // clearClientWorkspace({ clearReport: true, deferDisposal: true })
            // only after the next case has been selected.
        }
        const wasActive = id === activeSessionId;
        delete sessions[id];
        if (wasActive) {
            // Switch to the nearest remaining session before the server
            // round-trip so the workspace isn't stuck on a deleted case.
            const remaining = Object.keys(sessions).filter(k => k !== id);
            if (remaining.length) {
                const nextId = remaining[0];
                if (typeof window.detachActiveChatTurn === 'function') {
                    // Deleting a case changes the visible workspace but is
                    // not the explicit Stop action. Detach this browser's
                    // stream and let the server-owned task finish; the
                    // deleted case may no longer accept a final checkpoint,
                    // but another case must never be cancelled as a side
                    // effect of this UI operation.
                    window.detachActiveChatTurn('Session deleted');
                }
                await window.switchSession(nextId);
            }
        }
        // Re-render BEFORE the server round-trip
        renderSessionList();
        try {
            const response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}/purge`, { method: 'DELETE' });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.error || 'Unable to delete case');
            // The server mutation is authoritative.  Only after it succeeds
            // do we erase every browser cache entry for this case, so a
            // transient network error cannot turn a still-active case into a
            // locally unreadable one.
            await clearDeletedSessionBrowserData(id);
            void loadServerSessions().then(() => renderSessionList()).catch(error => console.debug('[workspace] session list refresh deferred:', error));
            return { success: true, active_session_id: activeSessionId };
        } catch (error) {
            if (removedSession) sessions[id] = removedSession;
            renderSessionList();
            void loadServerSessions().then(() => renderSessionList()).catch(() => {});
            console.error('[workspace] case deletion failed:', error);
            return { success: false, error: error?.message || 'Unable to delete case.' };
        }
    };

    window.renameServerSession = async function renameServerSession(id, title) {
        return runWorkspaceTransition(async () => {
            const response = await workspaceFetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Unable to rename case');
            if (sessions[id]) sessions[id].title = data.session.title;
            renderSessionList();
            return data.session;
        });
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
        await clearDeletedSessionBrowserData(id);
        await loadServerSessions();
        await window.openRecycleBin();
    };

    window.scheduleWorkspaceSave = scheduleWorkspaceSave;
    window.persistWorkspace = persistWorkspace;
    window.applyWorkspaceSnapshot = applyWorkspaceSnapshot;
    window.captureReportForPlanning = function captureReportForPlanning() {
        // reportState() performs the same lightweight cache/upload handling as
        // normal workspace persistence and records the current form under the
        // currently displayed Planning ID. The explicit flush performed by a
        // Planning switch then persists that map before the backend changes
        // the active aliases.
        if (!window.reportForm) return null;
        const section = reportState();
        return section?.active_planning_id || null;
    };
    window.restoreReportForPlanning = restoreReportForPlanning;
    window.applyChatSnapshotFast = applyChatSnapshotFast;
    window.clearDeletedSessionBrowserData = clearDeletedSessionBrowserData;
    window.updateRecycleBinCount = updateRecycleBinCount;
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
