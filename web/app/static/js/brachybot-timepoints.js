/* Timepoint control plane. Runtime hydration must register the fenced bridge below.
 * Bridge contract (all four flags must be true after integration is verified):
 *   timepoint_scope, async_fencing, scoped_persistence, preserves_shared_chat
 *   capture(scope) -> {ui: {...}, report?: {...}} synchronously, with owned IDs.
 *   suspend(scope) -> synchronously clear clinical panels, detach old resources,
 *       and cancel legacy Session restore/save timers without changing shared chat.
 *   prepare(workspace, context) -> Promise<{commit(), dispose?()}>. Preparation
 *       never paints. commit() is synchronous and applies all clinical panels.
 *       Every late loader checks context.isCurrent() before applying resources.
 *       context.request() always uses the initiating target, even after a switch.
 * The runtime bridge also routes every legacy clinical save, report, upload,
 * Monitor action and job callback through captured scope. Merely adding a header
 * cannot make Session-only restore/execution code safe. No production bridge is
 * registered here; brachybot-timepoint-workspace.js supplies the production adapter.
 */
(function timepointWorkspaceController() {
    'use strict';
    const stores = new Map();
    let sessionId = '', activeId = '', mountedId = '', generation = 0, catalogGeneration = 0;
    let catalog = null, bridge = null, switching = false, errorState = null, modal = null, operation = null;
    let saveTimer = null;
    const t = (zh, en) => window._i18nLang === 'zh' ? zh : en;
    const clone = value => value == null ? value : (window.cloneWorkspaceJSON
        ? window.cloneWorkspaceJSON(value) : JSON.parse(JSON.stringify(value, (_key, item) => item instanceof Set ? [...item] : item)));
    const sidNow = () => String(typeof _activeApiSessionId === 'function' ? _activeApiSessionId()
        : (typeof activeSessionId !== 'undefined' ? activeSessionId : '') || '');
    const scopeKey = scope => JSON.stringify([scope.sessionId, scope.timepointId]);
    const record = scope => {
        const key = scopeKey(scope);
        if (!stores.has(key)) stores.set(key, { workspace: null, presentation: null, patch: null, revision: null,
            dirty: false, saving: null, jobs: new Map(), state: 'unloaded', result: null });
        return stores.get(key);
    };
    const activeRecords = () => (catalog?.timepoints || []).filter(row => !isDeleted(row));
    const isDeleted = row => row.deleted === true || !!row.deleted_at || ['deleted', 'trashed'].includes(row.status);
    const findRow = id => catalog?.timepoints.find(row => row.id === String(id));
    const metadataFence = value => JSON.stringify({order:value?.order || [],
        timepoints:(value?.timepoints || []).map(row=>({id:row.id,title:row.title,status:row.status,
            stage:row.stage,preoperative_timepoint_id:row.preoperative_timepoint_id,
            previous_intraoperative_timepoint_id:row.previous_intraoperative_timepoint_id,
            revision:row.revision,lifecycle_revision:row.lifecycle_revision}))});
    const displayTitle = row => row?.auto_title === true ? t('术前', 'Preoperative') : String(row?.title || '');
    const bridgeReady = () => bridge?.timepoint_scope === true && bridge?.async_fencing === true && bridge?.scoped_persistence === true
        && bridge?.preserves_shared_chat === true && ['capture', 'suspend', 'prepare'].every(k => typeof bridge[k] === 'function');
    const enabled = () => !!sessionId && sessionId === sidNow() && catalog?.capabilities?.execution_scope === true && bridgeReady();
    const captureTarget = () => Object.freeze({ sessionId, timepointId: activeId, generation });
    function captureSubmission() {
        if (enabled() && (switching || !mountedId || mountedId !== activeId)) throw failure('timepoint_workspace_switching');
        // When runtime scope is gated, the displayed legacy panels are still
        // the default. A remembered/catalog-selected row is NOT mounted data.
        return Object.freeze({ sessionId: sidNow(), timepointId: enabled() ? mountedId
            : (catalog?.session_id === sidNow() ? catalog.default_timepoint_id : null),
            generation, legacyDefault: !enabled(), uiLanguage: window._i18nLang === 'zh' ? 'zh' : 'en' });
    }
    function isSubmissionCurrent(scope) {
        if (!scope || scope.sessionId !== sidNow()) return false;
        if (enabled()) return scope.timepointId === mountedId && scope.generation === generation && !switching;
        return scope.legacyDefault === true && (!scope.timepointId || !catalog || scope.timepointId === catalog.default_timepoint_id);
    }
    const isCurrent = scope => !!scope && scope.sessionId === sessionId && scope.sessionId === sidNow()
        && scope.timepointId === activeId && scope.generation === generation;
    const preferenceKey = sid => 'brachybot.timepoint:' + JSON.stringify([String(window.brachybotAuth?.user?.id || ''), sid]);
    const remember = () => { try { sessionStorage.setItem(preferenceKey(sessionId), activeId); } catch (_) {} };
    const remembered = sid => { try { return sessionStorage.getItem(preferenceKey(sid)); } catch (_) { return null; } };
    // Persist error identity, not translated prose or untrusted server exceptions.
    function failure(code, details = {}) { const error = new Error(code); error.code = code; error.details = details; return error; }
    const errorIdentity = error => ({ code: typeof error?.code === 'string' ? error.code : 'timepoint_request_failed',
        names: Array.isArray(error?.details?.names) ? error.details.names.map(String) : [] });
    function userError(error) {
        const messages = {
            timepoint_workspace_scope_mismatch: ['时间点数据标识不匹配，已取消恢复。', 'The workspace belongs to a different timepoint. Restoration was cancelled.'],
            revision_conflict: ['版本冲突。请重新加载时间点后再保存；当前编辑已保留。', 'Revision conflict. Reload the timepoint before saving; current edits are retained.'],
            timepoint_conflict: ['时间点已变更或当前不允许编辑。请重新加载并检查依赖。', 'The timepoint changed or cannot be edited yet. Reload it and check its dependencies.'],
            timepoint_not_found: ['时间点不可用，请刷新目录。', 'This timepoint is unavailable. Refresh the catalog.'],
            timepoint_integrity_error: ['时间点数据无法安全恢复，请检查服务端保存状态。', 'This timepoint cannot be safely restored. Check its saved state.'],
            stale_timepoint_action: ['病例已切换，已取消此操作。', 'The case changed. This operation was cancelled.'],
            confirmation_ui_unavailable: ['确认窗口不可用，已取消此操作。', 'The confirmation dialog is unavailable. This operation was cancelled.'],
            timepoint_scope_unavailable: ['时间点执行尚未启用。', 'Timepoint execution is not enabled.'],
            timepoint_service_unavailable: ['时间点服务尚不可用。当前病例工作区保持可用。', 'The timepoint service is unavailable. The current case workspace remains available.'],
            timepoint_stage_migration_required: ['已有临床数据的时间点需要显式迁移，不能直接修改阶段。', 'Populated timepoints require explicit migration before changing stage.'],
            timepoint_legacy_migration_required: ['默认时间点的删除需要完成运行时迁移。', 'Deleting the default timepoint requires runtime migration.'],
            timepoint_not_deleted: ['此时间点未被删除，无法从回收站恢复。', 'This timepoint is not in trash and cannot be restored from it.'],
            unknown_timepoint: ['时间点不可用，请刷新目录。', 'This timepoint is unavailable. Refresh the catalog.'],
            timepoint_target_required: ['请先选择此操作的目标时间点。', 'Select a target timepoint for this operation.'],
            invalid_timepoint_url: ['时间点请求地址无效，已取消此操作。', 'The timepoint request address is invalid. This operation was cancelled.'],
            timepoint_auth_required: ['登录已失效，请重新登录后重试。', 'Your sign-in expired. Sign in again and retry.'],
            timepoint_permission_denied: ['当前没有时间点编辑权限，请检查登录和编辑状态。', 'Timepoint access is denied. Check your sign-in and editing status.'],
            timepoint_network_error: ['无法连接时间点服务，请稍后重试。', 'Cannot connect to the timepoint service. Try again shortly.']
        };
        if (messages[error.code]) return t(...messages[error.code]);
        if (['timepoint_has_dependencies', 'timepoint_dependencies'].includes(error.code)) {
            const names = (error.names || []).join(', ');
            return names ? t('关联时间点阻止删除：', 'Dependent timepoints prevent deletion: ') + names
                : t('存在关联依赖，无法删除此时间点。', 'Dependencies prevent deleting this timepoint.');
        }
        if (String(error.code || '').startsWith('bridge_') || ['invalid_timepoint_catalog', 'invalid_timepoint_record',
            'invalid_preoperative_reference', 'invalid_timepoint_presentation_patch', 'timepoint_revision_required', 'timepoint_impact_required'].includes(error.code)) {
            return t('独立工作区数据或恢复组件尚未就绪，已取消此操作。', 'The timepoint data or restoration component is not ready. This operation was cancelled.');
        }
        const code = /^[a-z0-9_]{1,80}$/.test(String(error.code || '')) ? error.code : 'timepoint_request_failed';
        return t('时间点操作失败，请刷新目录并重试。当前编辑已保留。',
            'The timepoint operation failed. Refresh the catalog and retry. Current edits are retained.') + ' [' + code + ']';
    }
    function requireEnabled() { if (!enabled()) throw failure('timepoint_scope_unavailable'); }

    // Only same-origin clinical APIs inherit the mounted target. Explicit targets win.
    // Async executors must captureTarget() before their first await and use request().
    function addRequestHeaders(headers, pathname, requestSessionId) {
        if (!enabled() || !mountedId || switching || pathname === '/api/sessions'
            || pathname.startsWith('/api/sessions/') || pathname.startsWith('/api/auth/')
            || pathname === '/api/workspace/lease') return headers;
        const owner = headers.get('X-BrachyBot-Session') || String(requestSessionId || '');
        if (owner === sessionId && !headers.has('X-BrachyBot-Timepoint')) headers.set('X-BrachyBot-Timepoint', mountedId);
        return headers;
    }
    async function request(scope, url, init = {}) {
        if (!scope?.sessionId || !scope?.timepointId) throw failure('timepoint_target_required');
        const targetUrl = new URL(url, window.location.href);
        if (targetUrl.origin !== window.location.origin || !targetUrl.pathname.startsWith('/api/')) throw failure('invalid_timepoint_url');
        const headers = new Headers(init.headers || {});
        headers.set('X-BrachyBot-Session', scope.sessionId);
        headers.set('X-BrachyBot-Timepoint', scope.timepointId);
        headers.set('X-BrachyBot-Language', scope.uiLanguage || (window._i18nLang === 'zh' ? 'zh' : 'en'));
        return fetch(targetUrl.href, { ...init, headers });
    }
    const baseUrl = sid => '/api/sessions/' + encodeURIComponent(sid) + '/timepoints';
    async function jsonRequest(sid, tid, suffix, method = 'GET', body = null) {
        const url = baseUrl(sid) + (tid ? '/' + encodeURIComponent(tid) : '') + suffix;
        const headers = new Headers({ 'X-BrachyBot-Session': sid, 'X-BrachyBot-Language': window._i18nLang === 'zh' ? 'zh' : 'en' });
        if (tid) headers.set('X-BrachyBot-Timepoint', tid);
        if (body !== null) headers.set('Content-Type', 'application/json');
        let response;
        try { response = await fetch(url, { method, headers, ...(body === null ? {} : { body: JSON.stringify(body) }) }); }
        catch (_) { throw failure('timepoint_network_error'); }
        let data;
        try { data = await response.json(); } catch (_) { throw failure('timepoint_request_failed'); }
        if (!response.ok || data.success === false) throw failure(typeof data.code === 'string' ? data.code
            : ({ 401: 'timepoint_auth_required', 403: 'timepoint_permission_denied', 404: 'timepoint_not_found', 409: 'timepoint_conflict' })[response.status]
                || 'timepoint_request_failed');
        return data;
    }
    function normalizeCatalog(data, sid) {
        const value = data.catalog || data;
        if (value.session_id !== sid || !Array.isArray(value.timepoints)
            || !Number.isInteger(value.catalog_revision)) throw failure('invalid_timepoint_catalog');
        const ids = new Set();
        const rows = value.timepoints.map(row => {
            const id = String(row.id || row.timepoint_id || '');
            if (!id || ids.has(id) || !['preoperative', 'intraoperative'].includes(row.stage)
                || !Number.isInteger(row.revision)) throw failure('invalid_timepoint_record');
            ids.add(id); return { ...clone(row), id, title: String(row.title || id) };
        });
        for (const row of rows.filter(r => !isDeleted(r) && r.stage === 'intraoperative')) {
            if (!rows.some(r => r.id === row.preoperative_timepoint_id && r.stage === 'preoperative' && !isDeleted(r))) {
                throw failure('invalid_preoperative_reference');
            }
        }
        return { ...clone(value), timepoints: rows };
    }
    function acceptCatalog(data, sid, epoch) {
        if (sid !== sessionId || sid !== sidNow() || epoch !== catalogGeneration) return false;
        const next = normalizeCatalog(data, sid);
        if (catalog && next.catalog_revision < catalog.catalog_revision) return false;
        catalog = next;
        return true;
    }
    async function refresh(options = {}) {
        const sid = sidNow();
        if (!sid) { resetSession(''); return false; }
        if (sid !== sessionId) resetSession(sid);
        const epoch = ++catalogGeneration;
        try {
            const data = await jsonRequest(sid, '', '?include_trashed=1');
            if (!acceptCatalog(data, sid, epoch)) return false;
            errorState = null;
            if (!activeRecords().some(row => row.id === activeId)) activeId = '';
            render();
            // Metadata-only refreshes may replace an earlier bootstrap probe.
            // They can preserve an existing mount, but must not suppress the
            // first required workspace mount and leave every panel unbound.
            if (enabled() && !activeId && !switching) {
                const id = remembered(sid);
                const target = activeRecords().find(r => r.id === id) || activeRecords().find(r => r.id === catalog.default_timepoint_id)
                    || activeRecords()[0];
                if (target) await select(target.id);
            }
            return true;
        } catch (error) {
            if (sid === sessionId && epoch === catalogGeneration) {
                // A lost catalog/capability probe must revoke multi-timepoint activation.
                catalog = null; generation++; switching = false; errorState = { code: 'timepoint_service_unavailable' }; render();
            }
            return false;
        }
    }
    function resetSession(sid) {
        clearTimeout(saveTimer); generation++; catalogGeneration++;
        sessionId = sid; activeId = ''; mountedId = ''; catalog = null; switching = false; operation = null; errorState = null;
        modal?.close(null); render();
    }
    function invalidateMount() {
        if (!mountedId && !switching) return false;
        const previous = captureTarget();
        // A Session shell clears the clinical scene immediately. Revoke the
        // old generation before any DOM reset can schedule presentation saves
        // or an old resource callback can republish into the cleared scene.
        resetSession(sidNow());
        bridge?.suspend?.(previous);
        return true;
    }
    async function savePresentation(scope, patch = null, options = {}) {
        if (!options.allowDetached) requireEnabled();
        if (!options.allowDetached || isCurrent(scope)) await bridge?.waitForClinicalMutation?.(scope);
        const item = record(scope);
        // Capture only after the interaction settles. Navigation supplies its
        // synchronous outgoing-owner patch explicitly, before clearing the DOM.
        // A stale timer must never serialize another timepoint's presentation.
        if (patch === null && item.capturePending) {
            if (!isCurrent(scope)) throw failure('stale_timepoint_action');
            patch = bridge.capture(scope);
            if (patch && typeof patch.then === 'function') throw failure('bridge_capture_must_be_synchronous');
        }
        if (patch !== null) {
            if (!patch || typeof patch !== 'object' || Array.isArray(patch) || !patch.ui || typeof patch.ui !== 'object'
                || Object.keys(patch).some(k => !['ui', 'report'].includes(k))) throw failure('invalid_timepoint_presentation_patch');
            item.patch = clone(patch); item.presentation = clone(patch.ui); item.dirty = true;
            item.capturePending = false;
        }
        if (!item.dirty) return true;
        if (item.saving) { await item.saving; return savePresentation(scope, null, options); }
        const captured = clone(item.patch), revision = item.revision;
        const clinicalRevision = item.workspace?.timepoint_clinical_revision;
        const lifecycleRevision = item.workspace?.timepoint?.lifecycle_revision ?? 0;
        if (!Number.isInteger(revision)) throw failure('timepoint_revision_required');
        window._timepointPresentationSource = window._timepointPresentationSource || ('timepoint-' + (window.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2)));
        window._timepointPresentationSequence = Number(window._timepointPresentationSequence || 0) + 1;
        const presentationFence = {expected_clinical_revision:clinicalRevision, expected_lifecycle_revision:lifecycleRevision,
            presentation_source:window._timepointPresentationSource, presentation_sequence:window._timepointPresentationSequence,
            response_mode: 'presentation_receipt'};
        item.saving = (async () => {
            let data;
            try {
                data = await jsonRequest(scope.sessionId, scope.timepointId, '/workspace', 'PATCH', {
                    expected_state_revision: revision, patch: captured, ...presentationFence });
            } catch (error) {
                if (error.code !== 'timepoint_conflict') throw error;
                const latest = validateWorkspace(await jsonRequest(scope.sessionId, scope.timepointId, '/workspace?response_mode=resource_shell'), scope);
                if (latest.timepoint_clinical_revision !== clinicalRevision
                    || latest.timepoint.lifecycle_revision !== lifecycleRevision) throw error;
                // Rebase presentation only, once, when clinical inputs are
                // provably unchanged. A replaced image/plan is never rebased.
                data = await jsonRequest(scope.sessionId, scope.timepointId, '/workspace', 'PATCH', {
                    expected_state_revision: latest.timepoint_state_revision, patch: captured, ...presentationFence });
            }
            if (data.presentation_receipt) {
                const receipt = validateWorkspace({ workspace: data.presentation_receipt }, scope);
                const presentation = data.presentation;
                if (!presentation || typeof presentation !== 'object' || Array.isArray(presentation)
                    || Object.keys(presentation).some(key => !['ui', 'report'].includes(key))) throw failure('invalid_timepoint_presentation_patch');
                if (receipt.timepoint_clinical_revision !== clinicalRevision
                    || receipt.timepoint?.lifecycle_revision !== lifecycleRevision
                    || item.workspace?.timepoint_clinical_revision !== clinicalRevision
                    || item.workspace?.timepoint?.lifecycle_revision !== lifecycleRevision) throw failure('timepoint_conflict');
                // Clinical state was not changed by this transaction. Retain its
                // owned projection without cloning megabytes of unrelated data.
                item.revision = receipt.timepoint_state_revision;
                item.workspace = { ...item.workspace, ...receipt, ...presentation,
                    ui: { ...item.workspace.ui, ...presentation.ui },
                    timepoint: { ...item.workspace.timepoint, ...receipt.timepoint } };
            } else {
                // Mixed static/backend revisions and older servers stay valid.
                const workspace = validateWorkspace(data, scope);
                item.revision = workspace.timepoint_state_revision; item.workspace = clone(workspace);
            }
            if (!item.capturePending && JSON.stringify(item.patch) === JSON.stringify(captured)) item.dirty = false;
            // Clinical state saves can advance the catalog independently of metadata.
            // Read the new catalog before the next metadata mutation.
            if (scope.sessionId === sessionId && options.refreshCatalog !== false) await refresh({ activate: false });
            return true;
        })();
        try { return await item.saving; } finally { item.saving = null; render(); }
    }
    function validateWorkspace(data, scope) {
        // A raw snapshot itself has a `workspace` storage-metadata section.
        // Only an HTTP envelope may unwrap `workspace`; never mistake that
        // metadata section for the actual timepoint snapshot.
        const workspace = Number.isInteger(data?.timepoint_state_revision) ? data : data?.workspace;
        if (!workspace) throw failure('timepoint_workspace_scope_mismatch');
        if (String(workspace.session_id || workspace.session?.id || '') !== scope.sessionId
            || String(workspace.timepoint_id || workspace.timepoint?.id || '') !== scope.timepointId
            || !Number.isInteger(workspace.timepoint_state_revision)) throw failure('timepoint_workspace_scope_mismatch');
        return workspace;
    }
    async function select(id, options = {}) {
        requireEnabled();
        const row = findRow(id);
        if (!row || isDeleted(row)) throw failure('unknown_timepoint');
        if (switching) return false;
        if (options.reload !== true && activeId === row.id && mountedId === row.id && record(captureTarget()).state === 'ready') return true;
        const from = captureTarget(), sid = sessionId, currentBridge = bridge;
        if (options.reload === true) window.dropTimepointClinicalRuntime?.({ sessionId: sid, timepointId: row.id });
        const cached = options.reload !== true ? record({ sessionId: sid, timepointId: row.id }) : null;
        // The workspace bridge completes hydration asynchronously and keeps
        // the immutable resource entry after suspend().  Synchronize that
        // entry into the controller cache before deciding whether this is a
        // fast same-session switch; otherwise the controller would only see
        // its initial `ready: false` shell and fetch/rebuild on every click.
        if (cached && options.reload !== true && typeof currentBridge?.resourceState === 'function') {
            const live = currentBridge.resourceState({ sessionId: sid, timepointId: row.id });
            if (live?.ready === true && live.workspace) {
                cached.ready = true;
                cached.workspace = clone(live.workspace);
                cached.images = clone(live.images);
                cached.revision = live.revision ?? live.workspace.timepoint_state_revision;
                cached.status = live.status;
                cached.statusKind = live.statusKind;
            }
        }
        const cacheHit = options.reload !== true && cached?.ready === true
            && Number.isInteger(row.state_revision) && cached.revision === row.state_revision;
        switching = true; errorState = null; clearTimeout(saveTimer); render();
        // A ready resource shell is an immutable same-Session cache entry. Its
        // catalog state revision is the cheap clinical fence; reuse it for the
        // visible mount and avoid re-fetching images/config/meshes on every tab
        // click. A reload explicitly bypasses this fast path.
        const incoming = cacheHit ? Promise.resolve({ data: null })
            : jsonRequest(sid, row.id, '/workspace?response_mode=resource_shell')
                .then(data => ({ data }), error => ({ error }));
        let target = null, prepared = null;
        try {
            if (from.timepointId && mountedId === from.timepointId && options.reload !== true) {
                // Finish already-requested per-image presentation transactions
                // while their original workspace is still mounted.
                if (typeof currentBridge.flush === 'function') await currentBridge.flush(from);
                if (!isCurrent(from)) return false;
                // Capture and save before yielding ownership of the mounted workspace.
                const presentation = currentBridge.capture(from);
                if (presentation && typeof presentation.then === 'function') throw failure('bridge_capture_must_be_synchronous');
                await savePresentation(from, presentation, { refreshCatalog: false });
                if (!isCurrent(from)) return false;
            }
            generation++; activeId = row.id;
            target = captureTarget(); const item = record(target);
            item.state = 'loading'; render();
            // suspend clears only clinical panels/resources; chat stays Session-owned.
            mountedId = '';
            const suspended = currentBridge.suspend(target);
            if (suspended && typeof suspended.then === 'function') throw failure('bridge_suspend_must_be_synchronous');
            const receipt = await incoming;
            if (receipt.error) throw receipt.error;
            const workspace = cacheHit ? clone(cached.workspace) : validateWorkspace(receipt.data, target);
            item.workspace = clone(workspace); item.revision = workspace.timepoint_state_revision;
            item.presentation = clone(workspace.ui || {});
            if (!isCurrent(target) || !enabled() || bridge !== currentBridge) return false;
            prepared = await currentBridge.prepare(clone(workspace), { ...target,
                cachedItem: cacheHit ? cached : null,
                isCurrent: () => isCurrent(target) && enabled() && bridge === currentBridge,
                request: (url, init) => request(target, url, init),
                presentation: clone(item.presentation) });
            if (!isCurrent(target) || !enabled() || bridge !== currentBridge) { prepared?.dispose?.(); return false; }
            // prepare must not paint. commit is synchronous and rechecks all late loaders.
            if (typeof prepared?.commit !== 'function') throw failure('bridge_commit_required');
            const committed = prepared.commit();
            if (committed && typeof committed.then === 'function') throw failure('bridge_commit_must_be_synchronous');
            if (committed === false) throw failure('bridge_commit_refused');
            mountedId = row.id; item.state = 'ready'; switching = false; remember();
            const warmRestore = window.__brachybotWarmRestore;
            window.dispatchEvent(new CustomEvent('brachybot:timepoint-changed', {
                detail: { ...captureTarget(), warmResourcesRestored: !!warmRestore
                    && warmRestore.sessionId === sid && warmRestore.timepointId === row.id },
            }));
            if (warmRestore?.sessionId === sid && warmRestore?.timepointId === row.id) {
                // The implant observation module may be loaded independently
                // of the timepoint bridge. Leave the one-shot view available
                // until its synchronous change listener has rebuilt the tree.
                queueMicrotask(() => {
                    if (window.__brachybotWarmRestore?.timepointId === row.id) window.__brachybotWarmRestore = null;
                });
            }
            return true;
        } catch (error) {
            prepared?.dispose?.();
            console.warn('[timepoint mount]', error.code || error.message, error.stack || '');
            if (sid === sessionId && (!target || isCurrent(target))) { errorState = errorIdentity(error);
                if (activeId) record(captureTarget()).state = 'error'; }
            return false;
        } finally { if (sid === sessionId && (!target || isCurrent(target))) { switching = false; render(); } }
    }
    function schedulePresentationSave() {
        if (!enabled() || switching || !activeId || mountedId !== activeId) return false;
        const scope = captureTarget(), item = record(scope), wasDirty = item.dirty;
        // Camera, scrolling and report zoom generate many events per frame.
        // Debouncing only HTTP while cloning masks/report at event frequency
        // still blocked the UI. Defer that expensive capture as well.
        item.capturePending = true; item.dirty = true;
        clearTimeout(saveTimer); saveTimer = setTimeout(() => {
            if (isCurrent(scope)) void savePresentation(scope).catch(error => { errorState = errorIdentity(error); render(); });
        }, 700); if (!wasDirty) render(); return true;
    }
    function applyResult(scope, result, paint) {
        const item = record(scope); item.result = clone(result);
        if (!enabled() || switching || mountedId !== scope.timepointId || !isCurrent(scope)) { render(); return false; }
        if (typeof paint === 'function') paint(result, scope);
        return true;
    }
    function setJobState(scope, jobId, status) {
        record(scope).jobs.set(String(jobId), String(status)); render();
    }
    function render() {
        const strip = document.getElementById('timepointStrip'), tabs = document.getElementById('timepointTabs');
        if (!strip || !tabs) return;
        strip.setAttribute('aria-label', t('时间点', 'Timepoints')); tabs.setAttribute('aria-label', t('时间点', 'Timepoints'));
        strip.setAttribute('aria-busy', String(switching || !!operation)); strip.dataset.state = errorState ? 'error' : (enabled() ? 'ready' : 'gated');
        const heading = strip.querySelector('.timepoint-heading'); if (heading) heading.textContent = t('时间点', 'Timepoints');
        tabs.replaceChildren();
        for (const row of activeRecords()) {
            const item = record({ sessionId, timepointId: row.id });
            const button = document.createElement('button'); button.type = 'button'; button.className = 'timepoint-tab';
            button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', String(row.id === activeId));
            button.dataset.timepointId = row.id; button.disabled = !enabled() || switching;
            button.tabIndex = row.id === activeId || (!activeId && row.id === activeRecords()[0]?.id) ? 0 : -1;
            button.title = row.stage === 'intraoperative' ? t('关联术前：', 'Preoperative reference: ') + displayTitle(findRow(row.preoperative_timepoint_id)) : displayTitle(row);
            const title = document.createElement('span'); title.className = 'timepoint-tab-title'; title.textContent = displayTitle(row);
            const stage = document.createElement('span'); stage.className = 'timepoint-stage';
            stage.textContent = row.stage === 'intraoperative' ? t('术中', 'Intraoperative') : t('术前', 'Preoperative');
            button.append(title);
            if (stage.textContent !== title.textContent) button.append(stage);
            const running = [...item.jobs.values()].some(s => ['pending', 'queued', 'running'].includes(s));
            const badge = item.dirty ? t('未保存', 'Unsaved') : running ? t('任务进行中', 'Running')
                : ({ loading: t('加载中', 'Loading'), error: t('加载失败', 'Load failed') })[item.state]
                || ({ interrupted: t('已中断', 'Interrupted'), stale: t('已过期', 'Stale'), review_required: t('待复核', 'Review needed') })[row.status];
            if (badge) { const node = document.createElement('span'); node.className = 'timepoint-badge'; node.textContent = badge; button.append(node); }
            button.addEventListener('click', () => void select(row.id).catch(showError)); tabs.append(button);
            button.addEventListener('keydown', event => {
                const rows = activeRecords(), index = rows.findIndex(r => r.id === row.id);
                const next = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1
                    : event.key === 'ArrowRight' ? (index + 1) % rows.length
                    : event.key === 'ArrowLeft' ? (index + rows.length - 1) % rows.length : null;
                if (next === null || !enabled() || switching) return;
                event.preventDefault(); const targetId = rows[next].id;
                void select(targetId).then(() => {
                    if (activeId === targetId) [...tabs.children].find(n => n.dataset.timepointId === targetId)?.focus();
                }).catch(showError);
            });
        }
        // The create response is accepted into the catalog before the
        // optimistic operation is cleared.  Do not render a second tab for
        // the same identity during that short hand-off: the pending tab is
        // only useful while the server has not published the formal row yet.
        const pendingCreatedId = String(operation?.createdId || '');
        if (operation?.kind === 'creating' && !(pendingCreatedId && findRow(pendingCreatedId))) {
            const pending = document.createElement('span'); pending.className = 'timepoint-tab timepoint-tab-pending';
            pending.setAttribute('aria-busy', 'true'); pending.dataset.state = 'loading';
            const pendingTitle = document.createElement('span'); pendingTitle.className = 'timepoint-tab-title';
            pendingTitle.textContent = operation.title || t('新时间点', 'New timepoint');
            const pendingStage = document.createElement('span'); pendingStage.className = 'timepoint-stage';
            pendingStage.textContent = operation.stage === 'intraoperative' ? t('术中', 'Intraoperative') : t('术前', 'Preoperative');
            const pendingBadge = document.createElement('span'); pendingBadge.className = 'timepoint-badge';
            pendingBadge.textContent = t('创建中…', 'Creating…'); pending.append(pendingTitle, pendingStage, pendingBadge); tabs.append(pending);
        }
        const add = document.getElementById('timepointAdd'), manage = document.getElementById('timepointManage');
        if (add) { add.disabled = !enabled() || !!operation; add.setAttribute('aria-label', t('添加时间点', 'Add timepoint')); add.title = add.getAttribute('aria-label'); }
        if (manage) { manage.disabled = !enabled() || switching || !!operation; manage.textContent = t('管理', 'Manage'); }
        const status = document.getElementById('timepointStatus');
        if (status) { status.removeAttribute('data-i18n-zh'); status.removeAttribute('data-i18n-en');
            status.dataset.state = (switching || !!operation) ? 'loading' : errorState ? 'error' : 'idle';
            status.textContent = (errorState ? userError(errorState) : '') || (!catalog ? t('时间点服务尚不可用。当前病例工作区保持可用。', 'The timepoint service is unavailable. The current case workspace remains available.')
                : catalog.capabilities?.execution_scope !== true ? t('时间点目录可查看；独立执行尚未启用，切换和编辑已锁定。', 'The timepoint catalog is available; independent execution is not enabled. Switching and editing are locked.')
                : !bridgeReady() ? t('独立工作区恢复尚未就绪；切换和编辑已锁定。', 'Timepoint workspace restoration is not ready. Switching and editing are locked.')
                : operation?.kind === 'creating' ? t('正在创建时间点，完成后会自动切换…', 'Creating the timepoint; it will be selected when ready…')
                : operation?.kind === 'deleting' ? t('正在删除时间点…', 'Deleting timepoint…')
                : operation?.kind === 'saving' ? t('正在保存时间点设置…', 'Saving timepoint settings…')
                : switching ? t('正在恢复此时间点的图像和显示设置…', 'Restoring this timepoint’s images and presentation…')
                : activeId ? t('共享同一聊天；图像、规划、报告和显示设置属于当前时间点。', 'Chat is shared. Images, plans, reports and presentation belong to the selected timepoint.')
                : t('请选择时间点。', 'Select a timepoint.')); }
    }
    function showError(error) { operation = null; errorState = errorIdentity(error); render(); }
    const languageBindings = new WeakMap();
    const localizedCopy = copy => { const value = typeof copy === 'function' ? copy() : copy;
        return Array.isArray(value) ? t(...value) : String(value ?? ''); };
    function bindCopy(root, node, copy, attribute = '') {
        const update = () => { if (attribute) node.setAttribute(attribute, localizedCopy(copy));
            else node.textContent = localizedCopy(copy); };
        if (!languageBindings.has(root)) languageBindings.set(root, []);
        languageBindings.get(root).push(update); update();
    }
    function relabelDialog(root) {
        root.setAttribute('lang', window._i18nLang === 'zh' ? 'zh-CN' : 'en');
        for (const update of languageBindings.get(root) || []) update();
    }
    // Reuse the established modal and bind only the DOM it creates for this call.
    // Other application confirmations keep their own lifecycle and language policy.
    async function confirmLocalized(message, options) {
        if (typeof window._confirmAction !== 'function') throw failure('confirmation_ui_unavailable');
        modal?.close(null);
        const previous = document.activeElement, existing = new Set(document.body.children);
        const [zh, en] = typeof message === 'function' ? message() : message;
        const promise = window._confirmAction(zh, en, options);
        const overlay = [...document.body.children].find(node => !existing.has(node)
            && node.querySelector('#_confirmYes') && node.querySelector('#_confirmNo'));
        if (!overlay) return Boolean(await promise);
        const panel = overlay.firstElementChild, yes = overlay.querySelector('#_confirmYes'), no = overlay.querySelector('#_confirmNo');
        overlay.dataset.timepointConfirmation = 'true';
        panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
        const heading = panel.children[1], description = panel.children[2];
        heading.id = 'timepointConfirmationTitle'; description.id = 'timepointConfirmationMessage';
        panel.setAttribute('aria-labelledby', heading.id); panel.setAttribute('aria-describedby', description.id);
        bindCopy(panel, heading, [options.titleZh, options.titleEn]); bindCopy(panel, description, message);
        bindCopy(panel, yes, [options.yesZh || '确认', options.yesEn || 'Yes']);
        bindCopy(panel, no, [options.noZh || '取消', options.noEn || 'Cancel']);
        const close = () => no.click();
        const keydown = event => {
            if (event.key === 'Escape') { event.preventDefault(); close(); }
            if (event.key === 'Tab' && ((event.shiftKey && document.activeElement === yes) || (!event.shiftKey && document.activeElement === no))) {
                event.preventDefault(); (event.shiftKey ? no : yes).focus();
            }
        };
        const entry = { overlay, close, updateLanguage: () => relabelDialog(panel) };
        modal = entry; entry.updateLanguage(); document.addEventListener('keydown', keydown); no.focus();
        try { return Boolean(await promise); }
        finally { document.removeEventListener('keydown', keydown); languageBindings.delete(panel);
            if (modal === entry) { modal = null; previous?.focus?.(); } }
    }
    function openForm(title) {
        modal?.close(null);
        const previous = document.activeElement, overlay = document.createElement('div'); overlay.className = 'timepoint-modal';
        const form = document.createElement('form'); form.className = 'timepoint-dialog'; form.setAttribute('role', 'dialog');
        form.setAttribute('aria-modal', 'true'); form.setAttribute('aria-labelledby', 'timepointDialogTitle');
        form.noValidate = true;
        const heading = document.createElement('h2'); heading.id = 'timepointDialogTitle'; bindCopy(form, heading, title); form.append(heading);
        overlay.append(form); document.body.append(overlay);
        let resolve; const promise = new Promise(r => { resolve = r; });
        const close = value => { document.removeEventListener('keydown', keydown); languageBindings.delete(form); overlay.remove(); if (modal?.overlay === overlay) modal = null;
            previous?.focus?.(); resolve(value); };
        const keydown = event => {
            if (event.key === 'Escape') { event.preventDefault(); close(null); }
            if (event.key === 'Tab') {
                const nodes = [...form.querySelectorAll('input,select,button')].filter(n => !n.disabled && n.getClientRects().length);
                if (nodes.length && ((event.shiftKey && document.activeElement === nodes[0]) || (!event.shiftKey && document.activeElement === nodes.at(-1)))) {
                    event.preventDefault(); (event.shiftKey ? nodes.at(-1) : nodes[0]).focus();
                }
            }
        };
        document.addEventListener('keydown', keydown); overlay.addEventListener('click', e => { if (e.target === overlay) close(null); });
        modal = { overlay, close, updateLanguage: () => relabelDialog(form) }; modal.updateLanguage(); return { form, close, promise };
    }
    function field(form, label, kind, name, value = '') {
        const wrapper = document.createElement('label'), labelText = document.createElement('span'); bindCopy(form, labelText, label); wrapper.append(labelText);
        const input = document.createElement(kind); input.name = name; if (kind === 'input') { input.type = 'text'; input.maxLength = 120; }
        bindCopy(form, input, label, 'aria-label');
        input.value = value; wrapper.append(input); form.append(wrapper); return input;
    }
    function option(selectNode, value, text) { const node = document.createElement('option'); node.value = value;
        if (Array.isArray(text) || typeof text === 'function') bindCopy(selectNode.closest('form'), node, text); else node.textContent = text;
        selectNode.append(node); }
    function actions(form, close, submitLabel) {
        const box = document.createElement('div'); box.className = 'timepoint-dialog-actions';
        const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'timepoint-action'; bindCopy(form, cancel, ['取消', 'Cancel']); cancel.onclick = () => close(null);
        const submit = document.createElement('button'); submit.type = 'submit'; submit.className = 'timepoint-action primary'; bindCopy(form, submit, submitLabel);
        box.append(cancel, submit); form.append(box); return box;
    }
    async function mutate(id, method, suffix, values = {}, captured = null) {
        requireEnabled();
        const op = { kind: method === 'POST' && !id ? 'creating' : method === 'DELETE' ? 'deleting' : 'saving',
            title: String(values.title || ''), stage: values.stage || '' };
        operation = op; errorState = null; render();
        try {
            const owner = captured || { sessionId, catalogRevision: catalog.catalog_revision, revision: findRow(id)?.revision };
        if (owner.sessionId !== sessionId || owner.sessionId !== sidNow()) throw failure('stale_timepoint_action');
        const fence = owner.metadataFence || metadataFence(catalog);
        let latest = normalizeCatalog(await jsonRequest(owner.sessionId, '', '?include_trashed=1'), owner.sessionId);
        if (metadataFence(latest) !== fence) throw failure('timepoint_conflict');
        const body = { ...values, expected_revision: latest.catalog_revision,
            expected_metadata_signature: latest.metadata_signature };
        // Do not optimistically replace catalog data; a revision conflict keeps the prior state.
        let data;
        try { data = await jsonRequest(owner.sessionId, id, suffix, method, body); }
        catch (error) {
            if (error.code !== 'timepoint_conflict') throw error;
            latest = normalizeCatalog(await jsonRequest(owner.sessionId, '', '?include_trashed=1'), owner.sessionId);
            if (metadataFence(latest) !== fence) throw error;
            data = await jsonRequest(owner.sessionId, id, suffix, method, { ...values, expected_revision: latest.catalog_revision,
                expected_metadata_signature: latest.metadata_signature });
        }
        if (owner.sessionId === sessionId) {
            // Record the server identity before accepting/rendering the
            // catalog.  Otherwise render() briefly shows both the optimistic
            // “Creating…” tab and the newly published formal tab.
            if (data?.created_timepoint_id) op.createdId = String(data.created_timepoint_id);
            const accepted = acceptCatalog(data, owner.sessionId, catalogGeneration);
            if (!accepted || !findRow(data.created_timepoint_id || id)) await refresh({ activate: false });
            else render();
            if (data.created_timepoint_id && enabled()) await select(data.created_timepoint_id);
        }
        } finally { if (operation === op) { operation = null; render(); } }
    }
    async function editTimepoint(id = '') {
        requireEnabled();
        // Open immediately from the visible catalog. mutate() revalidates the
        // metadata fence against a fresh catalog before committing any edit.
        if (sessionId !== sidNow()) throw failure('stale_timepoint_action');
        const row = id ? findRow(id) : null;
        const owner = { sessionId, catalogRevision: catalog.catalog_revision, revision: row?.revision, metadataFence: metadataFence(catalog) };
        const dialog = openForm(row ? ['编辑时间点', 'Edit timepoint'] : ['添加时间点', 'Add timepoint']);
        const title = field(dialog.form, ['名称', 'Title'], 'input', 'title', displayTitle(row)); title.required = true;
        const stage = field(dialog.form, ['阶段', 'Stage'], 'select', 'stage');
        option(stage, 'preoperative', ['术前', 'Preoperative']); option(stage, 'intraoperative', ['术中', 'Intraoperative']); stage.value = row?.stage || 'preoperative';
        const reference = field(dialog.form, ['关联的术前时间点', 'Associated preoperative timepoint'], 'select', 'preoperative_timepoint_id');
        option(reference, '', ['请选择术前时间点', 'Choose a preoperative timepoint']);
        activeRecords().filter(r => r.stage === 'preoperative' && r.id !== id).forEach(r => option(reference, r.id, () => displayTitle(r)));
        reference.value = row?.preoperative_timepoint_id || '';
        const update = () => { reference.parentElement.hidden = stage.value !== 'intraoperative'; reference.required = stage.value === 'intraoperative'; relabelDialog(dialog.form); }; update(); stage.onchange = update;
        const migrationRequired = !!row && (row.legacy_default || row.state_revision > 0);
        stage.disabled = migrationRequired; reference.disabled = migrationRequired;
        const note = document.createElement('p'); note.className = 'timepoint-dialog-note'; bindCopy(dialog.form, note, () => migrationRequired
            ? ['阶段和术前关联已锁定：已有临床数据的时间点需要显式迁移。名称仍可修改。', 'Stage and reference are locked: populated timepoints require explicit migration. The title can still be changed.']
            : stage.value === 'intraoperative'
                ? ['创建术中独立工作区；仅保留与术前节点的关联关系，术中图像和临床资源从空白开始，需要重新上传/确认，不会自动复制术前数据。', 'Creates an independent intraoperative workspace; only the link to the preoperative point is kept. Intraoperative images and clinical resources start empty and must be uploaded or confirmed explicitly; preoperative data is not copied automatically.']
                : ['创建空白工作区。术后可再上传图像并选择规划参考。', 'Creates an empty workspace. Images and a planning reference can be selected later.']); dialog.form.append(note);
        let validation = '';
        const validationNode = document.createElement('p'); validationNode.className = 'timepoint-dialog-error'; validationNode.setAttribute('role', 'alert');
        bindCopy(dialog.form, validationNode, () => ({ title: ['请输入时间点名称。', 'Enter a timepoint title.'],
            reference: ['请选择关联的术前时间点。', 'Choose an associated preoperative timepoint.'] })[validation] || ['', '']);
        dialog.form.append(validationNode);
        const clearValidation = () => { validation = ''; relabelDialog(dialog.form); };
        title.addEventListener('input', clearValidation); reference.addEventListener('change', clearValidation);
        stage.addEventListener('change', clearValidation);
        actions(dialog.form, dialog.close, ['保存', 'Save']);
        dialog.form.onsubmit = event => {
            event.preventDefault();
            validation = !title.value.trim() ? 'title' : stage.value === 'intraoperative' && !reference.value ? 'reference' : '';
            if (validation) { relabelDialog(dialog.form); (validation === 'title' ? title : reference).focus(); return; }
            dialog.close({ title: title.value.trim(), stage: stage.value,
                preoperative_timepoint_id: stage.value === 'intraoperative' ? reference.value : null });
        };
        title.focus(); const values = await dialog.promise;
        if (!values || owner.sessionId !== sidNow()) return;
        if (row && (values.stage !== row.stage || values.preoperative_timepoint_id !== (row.preoperative_timepoint_id || null))) {
            if (row.legacy_default || row.state_revision > 0) throw failure('timepoint_stage_migration_required');
            if (!await confirmLocalized([
                '更改此空白时间点的阶段或关联术前时间点？此操作不会生成规划。',
                'Change this empty timepoint’s stage or preoperative reference? This does not run planning.'],
                { titleZh: '阶段变更影响', titleEn: 'Stage change impact' })) return;
        }
        await mutate(id, row ? 'PATCH' : 'POST', '', values, owner);
    }
    async function confirmImpact(id, action, owner) {
        const impact = await jsonRequest(owner.sessionId, id, '/delete-impact');
        if (!Array.isArray(impact.dependents) || typeof impact.can_delete !== 'boolean') throw failure('timepoint_impact_required');
        if (owner.sessionId !== sessionId || owner.sessionId !== sidNow()) throw failure('stale_timepoint_action');
        const names = impact.dependents.map(r => String(r.title || findRow(r.id || r)?.title || r.id || r));
        if (!impact.can_delete) throw failure(impact.reason === 'legacy_default_requires_runtime_migration'
            ? 'timepoint_legacy_migration_required' : 'timepoint_has_dependencies', { names });
        const targetTitle = findRow(id)?.title || id;
        return confirmLocalized([
            '时间点：“' + targetTitle + '”\n受影响的关联：' + (names.join(', ') || '无') + '\n' + (action === 'delete' ? '此时间点将移入回收站，可恢复。' : '阶段变更将使相关结果过期。'),
            'Timepoint: “' + targetTitle + '”\nAffected references: ' + (names.join(', ') || 'None') + '\n' + (action === 'delete' ? 'This timepoint will move to trash and can be restored.' : 'Changing stage invalidates dependent results.')],
            { titleZh: action === 'delete' ? '删除时间点' : '阶段变更影响', titleEn: action === 'delete' ? 'Delete timepoint' : 'Stage change impact',
                yesZh: action === 'delete' ? '删除' : '确认', yesEn: action === 'delete' ? 'Delete' : 'Confirm', noZh: '取消', noEn: 'Cancel' });
    }
    async function deleteTimepoint(id) {
        requireEnabled(); const owner = { sessionId, catalogRevision: catalog.catalog_revision, revision: findRow(id)?.revision };
        if (!await confirmImpact(id, 'delete', owner)) return;
        // Never publish a pending presentation under the next selected timepoint.
        if (id === activeId && mountedId === activeId) await savePresentation(captureTarget(), bridge.capture(captureTarget()));
        owner.revision = findRow(id)?.revision; owner.catalogRevision = catalog.catalog_revision;
        await mutate(id, 'DELETE', '', {}, owner);
    }
    async function restoreTimepoint(id) {
        requireEnabled(); const row = findRow(id), owner = { sessionId, catalogRevision: catalog.catalog_revision, revision: row?.revision };
        if (!row || !isDeleted(row)) throw failure('timepoint_not_deleted');
        if (await confirmLocalized(['恢复时间点“' + row.title + '”？关联依赖将由服务端校验。', 'Restore timepoint “' + row.title + '”? The server will validate its references.'],
            { titleZh: '恢复时间点', titleEn: 'Restore timepoint', yesZh: '恢复', yesEn: 'Restore', noZh: '取消', noEn: 'Cancel' })) await mutate(id, 'POST', '/restore', {}, owner);
    }
    async function manageTimepoints() {
        requireEnabled(); const id = activeId, sid = sessionId, dialog = openForm(['管理时间点', 'Manage timepoints']);
        const box = actions(dialog.form, dialog.close, ['重命名 / 阶段', 'Rename / stage']);
        const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'timepoint-action danger'; bindCopy(dialog.form, remove, ['删除', 'Delete']); remove.disabled = !id;
        remove.onclick = () => dialog.close('delete'); box.prepend(remove);
        for (const row of catalog.timepoints.filter(isDeleted)) {
            const line = document.createElement('div'); line.className = 'timepoint-trash-row'; const label = document.createElement('span'); label.textContent = row.title;
            const restore = document.createElement('button'); restore.type = 'button'; restore.className = 'timepoint-action'; bindCopy(dialog.form, restore, ['恢复', 'Restore']); restore.onclick = () => dialog.close({ restore: row.id }); line.append(label, restore); dialog.form.append(line);
        }
        dialog.form.onsubmit = event => { event.preventDefault(); dialog.close('edit'); }; box.querySelector('button')?.focus();
        const action = await dialog.promise;
        if (sid !== sessionId || sid !== sidNow()) return;
        if (action === 'edit' && id) await editTimepoint(id);
        if (action === 'delete') await deleteTimepoint(id);
        if (action?.restore) await restoreTimepoint(action.restore);
    }
    function registerBridge(value) {
        if (switching || activeId) throw failure('bridge_replacement_requires_session_reset');
        bridge = value; render();
        if (enabled()) void refresh();
        return bridgeReady();
    }
    function observeWorkspace(scope, data) {
        const workspace = validateWorkspace(data, scope), item = record(scope);
        if (Number.isInteger(item.revision) && workspace.timepoint_state_revision < item.revision) return false;
        item.workspace = clone(workspace); item.revision = workspace.timepoint_state_revision;
        if (!item.dirty) item.presentation = clone(workspace.ui || {});
        return true;
    }
    async function executeCommand(command, value = {}, owner = null) {
        requireEnabled();
        if (owner?.sessionId && owner.sessionId !== sessionId) throw failure('stale_timepoint_action');
        if (owner?.timepointId && !isSubmissionCurrent(owner)) throw failure('stale_timepoint_action');
        const data = typeof value === 'string' ? { timepoint_id: value } : value || {};
        const id = String(data.timepoint_id || data.id || '');
        if (['switch', 'select', 'activate'].includes(command)) return { success: await select(id), timepoint_id: id };
        if (command === 'refresh_images') {
            if (id && id !== activeId) throw failure('stale_timepoint_action');
            return {success:await window.BrachyBotTimepointWorkspace.restoreActive(),timepoint_id:activeId};
        }
        if (command === 'list') return { success: true, catalog: clone(catalog) };
        if (['add', 'create'].includes(command)) {
            if (!data.title) { await editTimepoint(); return { success: true, timepoint_id: activeId }; }
            await mutate('', 'POST', '', { title: data.title, stage: data.stage || 'preoperative',
                preoperative_timepoint_id: data.preoperative_timepoint_id || null });
            return { success: true, timepoint_id: activeId };
        }
        if (['edit', 'rename', 'update'].includes(command)) {
            if (!id) throw failure('timepoint_target_required');
            if (!data.title) await editTimepoint(id);
            else await mutate(id, 'PATCH', '', { title: data.title });
            return { success: true, timepoint_id: id };
        }
        if (['delete', 'trash'].includes(command)) { await deleteTimepoint(id); return { success: isDeleted(findRow(id)), timepoint_id: id }; }
        if (command === 'restore') { await restoreTimepoint(id); return { success: !isDeleted(findRow(id)), timepoint_id: id }; }
        if (command === 'manage') { await manageTimepoints(); return { success: true }; }
        throw failure('invalid_timepoint_command');
    }
    const shownTargetReceipts = new Set();
    async function confirmTargetOperation(packet, submission) {
        if (!packet?.receipt_id || packet.session_id !== submission?.sessionId
            || !isSubmissionCurrent(submission) || shownTargetReceipts.has(packet.receipt_id)) return false;
        const row = findRow(packet.timepoint_id);
        if (!row || isDeleted(row) || !packet.operation?.tool) return false;
        shownTargetReceipts.add(packet.receipt_id);
        const description = JSON.stringify(packet.operation);
        const approved = await confirmLocalized([
            '此操作将写入时间点“' + displayTitle(row) + '”，不是当前窗口。确认执行以下操作？\n' + description,
            'This operation writes to timepoint “' + displayTitle(row) + '”, not the current workspace. Execute this exact operation?\n' + description,
        ], { titleZh: '确认操作的时间点', titleEn: 'Confirm operation target',
            yesZh: '确认执行', yesEn: 'Confirm and execute', noZh: '取消', noEn: 'Cancel' });
        if (!approved || !isSubmissionCurrent(submission)) return false;
        // The new chat request supplies only the opaque receipt. The server
        // validates its frozen operation/read-set and editor lease; no model
        // argument or client-authored operation can substitute that receipt.
        return window.sendChat(t('执行已确认的跨时间点操作。', 'Execute the confirmed timepoint operation.'), {
            queueIfBusy: true, targetConfirmationReceiptId: packet.receipt_id,
            targetConfirmationConfirmed: true, timepointScope: submission,
        });
    }
    window.BrachyBotTimepoints = Object.freeze({ refresh, select, captureTarget, captureSubmission, isSubmissionCurrent, isCurrent, request, addRequestHeaders,
        applyResult, setJobState, schedulePresentationSave, savePresentation, registerBridge, editTimepoint, deleteTimepoint, invalidateMount,
        restoreTimepoint, enabled, observeWorkspace, executeCommand, reload: () => select(activeId,{reload:true}), getCatalog: () => clone(catalog),
        confirmTargetOperation, getDataState: scope => { const item = record(scope); return { workspace: clone(item.workspace), presentation: clone(item.presentation),
            revision: item.revision, dirty: item.dirty, state: item.state, jobs: Object.fromEntries(item.jobs), result: clone(item.result) }; } });
    const ready = () => {
        document.getElementById('timepointAdd')?.addEventListener('click', () => void editTimepoint().catch(showError));
        document.getElementById('timepointManage')?.addEventListener('click', () => void manageTimepoints().catch(showError));
        window.addEventListener('i18nchange', () => {
            const focusedId = document.activeElement?.dataset?.timepointId;
            render(); modal?.updateLanguage();
            if (focusedId && !modal) [...document.getElementById('timepointTabs')?.children || []]
                .find(node => node.dataset.timepointId === focusedId)?.focus();
        });
        window.addEventListener('brachybot:session-readiness', () => { if (sidNow() !== sessionId || !catalog) void refresh(); });
        window.addEventListener('brachybot:timepoint-session-ready', () => void refresh());
        window.addEventListener('brachybot:auth-ready', () => void refresh());
        window.addEventListener('brachybot:api-key-changed', () => void refresh());
        if (sidNow()) void refresh(); else render();
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, { once: true }); else ready();
})();
