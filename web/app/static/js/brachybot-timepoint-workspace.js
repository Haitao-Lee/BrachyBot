/* Production adapter for the existing Input/Analysis/Viewer/Report workspace.
 * Preparation reads metadata only. The synchronous commit owns the shell;
 * real CT/label/mesh/report loaders retain that captured owner until they settle.
 */
(function timepointWorkspaceBridge() {
    'use strict';
    const records = new Map(), requests = new Set(), imageMutations = new Map(), restoreTasks = new Map();
    const modes = ['implanted', 'planned', 'total'];
    let mounted = null, registered = false, suspended = false, guideController = null;
    const copy = value => value == null ? value : (window.cloneWorkspaceJSON
        ? window.cloneWorkspaceJSON(value) : JSON.parse(JSON.stringify(value, (_key, item) => item instanceof Set ? [...item] : item)));
    const t = (zh, en) => window._i18nLang === 'zh' ? zh : en;
    const key = scope => JSON.stringify([scope.sessionId, scope.timepointId]);
    const controller = () => window.BrachyBotTimepoints;
    const fail = code => { const error = Error(code); error.code = code; return error; };
    const same = (a, b) => !!a && !!b && a.sessionId === b.sessionId
        && a.timepointId === b.timepointId && a.generation === b.generation;
    const dependencies = () => ['captureTimepointWorkspacePresentation', 'captureTimepointWorkspaceReport',
        'applyTimepointWorkspaceSnapshot', 'hydrateTimepointWorkspace', 'suspendTimepointWorkspace'].every(name => typeof window[name] === 'function')
        && ['_captureViewerDataScope', '_viewerDataScopeIsCurrent', '_capturePlanningSceneScope',
            '_planningSceneScopeIsCurrent', '_fetchViewerJsonWithRetry', 'displayTimepointImage'].every(name => typeof window[name] === 'function');
    function scopeIsCurrent(scope) {
        return !suspended && same(scope, mounted) && controller()?.isCurrent(scope) === true;
    }
    function captureRequestScope(explicit = null) {
        if (explicit?.timepointId) return Object.freeze({ ...explicit });
        if (!registered || !controller()?.enabled()) return null;
        if (!mounted || suspended || !controller().isCurrent(mounted)) throw fail('timepoint_workspace_switching');
        return Object.freeze({ ...mounted, uiLanguage: window._i18nLang === 'zh' ? 'zh' : 'en' });
    }
    const requestReady = () => !!mounted && !suspended && controller()?.isSubmissionCurrent(mounted) === true;
    function headers(scope, values = {}) {
        const result = new Headers(values);
        if (scope) {
            result.set('X-BrachyBot-Session', scope.sessionId);
            result.set('X-BrachyBot-Timepoint', scope.timepointId);
            result.set('X-BrachyBot-Language', scope.uiLanguage || 'en');
        }
        return Object.fromEntries(result);
    }
    function assertCurrent(scope) {
        if (scope && !scopeIsCurrent(scope)) { const error = fail('stale_timepoint_action'); error.name = 'AbortError'; throw error; }
    }
    async function awaitOwned(scope, operation) {
        assertCurrent(scope);
        try { const value = await operation(); assertCurrent(scope); return value; }
        catch (error) { assertCurrent(scope); throw error; }
    }
    function callbackOwned(scope, callback) {
        return function (...args) { if (!scope || scopeIsCurrent(scope)) return callback.apply(this, args); };
    }
    async function fetchOwned(scope, input, init = {}) {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        if (!scope || url.origin !== location.origin || !url.pathname.startsWith('/api/')) return window.fetch(input, init);
        assertCurrent(scope);
        const response = await window.fetch(input, { ...init, headers: headers(scope, init.headers || input.headers || {}) });
        assertCurrent(scope);
        if (response.ok && ((response.headers.get('X-BrachyBot-Timepoint') && response.headers.get('X-BrachyBot-Timepoint') !== scope.timepointId)
            || (response.headers.get('X-BrachyBot-Session') && response.headers.get('X-BrachyBot-Session') !== scope.sessionId))) throw fail('timepoint_workspace_scope_mismatch');
        return response;
    }
    async function json(scope, url, init = {}) {
        const abort = new AbortController(); requests.add(abort);
        try {
            const response = await controller().request(scope, url, { ...init, signal: init.signal || abort.signal });
            const data = await response.json();
            if (!response.ok || data.success === false) throw fail(data.code || 'timepoint_resource_failed');
            return data;
        } finally { requests.delete(abort); }
    }
    function assertOwner(data, scope) {
        if (data?.session_id !== scope.sessionId || data?.timepoint_id !== scope.timepointId) throw fail('timepoint_workspace_scope_mismatch');
    }
    const imageUrl = scope => '/api/sessions/' + encodeURIComponent(scope.sessionId) + '/timepoints/' + encodeURIComponent(scope.timepointId) + '/images';
    function imagesPacket(data, scope) {
        const value = data.collection || data; assertOwner(value, scope);
        if (!Array.isArray(value.images) || !Number.isInteger(value.collection_revision)) throw fail('timepoint_image_collection_invalid');
        const ids = new Set();
        for (const image of value.images) {
            if (!image?.id || ids.has(image.id) || !(image.path || image.url)) throw fail('timepoint_image_collection_invalid');
            ids.add(image.id);
            if (image.url && new URL(image.url, location.href).origin !== location.origin) throw fail('timepoint_image_resource_invalid');
        }
        for (const field of ['display_image_id', 'planning_reference_image_id']) {
            if (value[field] && !ids.has(value[field])) throw fail('timepoint_image_collection_invalid');
        }
        return copy(value);
    }
    function entry(scope) { return records.get(key(scope)); }
    function status(code, kind = 'info') {
        if (!mounted) return;
        const item = entry(mounted); if (item) { item.status = code; item.statusKind = kind; }
        renderStatus();
    }
    function renderStatus() {
        const item = mounted && entry(mounted), node = document.getElementById('timepointResourceStatus');
        if (!node) return;
        const texts = {
            loading: ['正在恢复图像、结构和报告…', 'Restoring images, structures and report…'],
            ready: ['此时间点的已保存资源已恢复。', 'Saved resources for this timepoint are restored.'],
            partial: ['部分资源尚未恢复，请重试。显示设置已保留。', 'Some resources did not restore. Retry; saved presentation is retained.'],
            failed: ['资源恢复失败，请重试。', 'Resource restoration failed. Retry.'],
            image_failed: ['图像操作失败，请刷新后重试。', 'The image operation failed. Refresh and retry.'],
            reference_saved: ['已明确选择规划参考图像。', 'Planning reference image selected explicitly.'],
            dose_unavailable: ['所选剂量尚不可用。', 'The selected dose is unavailable.'],
            dose_stale: ['所选剂量已过期，请重算后查看。', 'The selected dose is stale. Recompute before viewing.'],
            dose_failed: ['所选剂量无法恢复，请重试。', 'The selected dose could not restore. Retry.'],
            dose_ready: ['所选剂量已加载（Gy）。', 'The selected dose is loaded (Gy).'],
        };
        node.textContent = item?.status && texts[item.status] ? t(...texts[item.status]) : '';
        node.dataset.state = item?.statusKind || 'info';
        const retry=document.getElementById('timepointRetryRestore');
        if(retry){retry.textContent=t('重试恢复当前时间点','Retry current timepoint restoration');
            retry.hidden=!item || !['partial','failed','dose_failed','image_failed'].includes(item.status);
            retry.disabled=!mounted || suspended || item?.status==='loading';}
    }
    function capture(scope) {
        if (!same(scope, mounted)) throw fail('bridge_capture_scope_mismatch');
        const item = entry(scope);
        if (!item?.ready) return { ui: copy(item?.workspace.ui || {}), ...(item?.workspace.report ? { report: copy(item.workspace.report) } : {}) };
        const ui = copy(window.captureTimepointWorkspacePresentation(scope.sessionId));
        // Presentation lives under the same ui.state namespace as legacy saves.
        ui.viewer = ui.viewer || {};
        ui.viewer.timepointId = scope.timepointId;
        ui.viewer.doseSourceSet = item.doseMode || 'planned';
        const report = window.captureTimepointWorkspaceReport(scope);
        return { ui: { state: ui }, ...(report ? { report: copy(report) } : {}) };
    }
    function suspend(scope) {
        suspended = true;
        requests.forEach(abort => abort.abort()); requests.clear();
        if (mounted) { const item = entry(mounted); if (item) item.cancelled = true; }
        mounted = null;
        guideController?.unmount(); guideController = null;
        window.BrachyBotImplants?.suspend?.();
        window.suspendTimepointWorkspace(scope);
        document.querySelectorAll('[data-timepoint-images], [data-timepoint-dose-tree]').forEach(node => node.replaceChildren());
    }
    async function prepare(workspace, context) {
        assertOwner(workspace, context);
        const scope = Object.freeze({ sessionId: context.sessionId, timepointId: context.timepointId,
            generation: context.generation, uiLanguage: window._i18nLang === 'zh' ? 'zh' : 'en' });
        const images = imagesPacket(await json(scope, imageUrl(scope)), scope);
        if (window.BrachyBotInputPlanningConfig) {
            workspace = await window.BrachyBotInputPlanningConfig.prepareSnapshot(workspace, scope, context.isCurrent);
            if (!workspace) throw fail('stale_timepoint_action');
        }
        if (!context.isCurrent()) throw fail('stale_timepoint_action');
        const saved = workspace.ui?.state || workspace.ui || {};
        const item = { scope, workspace: copy(workspace), images, cancelled: false, ready: false,
            doseMode: modes.includes(saved.viewer?.doseSourceSet) ? saved.viewer.doseSourceSet : 'planned',
            doseSequence: 0, imageSequence: 0, status: 'loading', statusKind: 'info' };
        let committed = false;
        return {
            commit() {
                if (!context.isCurrent() || committed) return false;
                mounted = scope; suspended = false; records.set(key(scope), item); committed = true;
                // This hook is synchronous and invokes the production controls,
                // DataTree, manual-state, report editor and appearance restore.
                const result = window.applyTimepointWorkspaceSnapshot(item.workspace, scope);
                if (result === false || result?.then) throw fail('bridge_commit_refused');
                window.BrachyBotInputPlanningConfig?.mounted();
                renderImages(); renderDoseControls(); renderStatus();
                mountGuideReview(item);
                queueMicrotask(() => { if (scopeIsCurrent(scope)) void hydrate(item); });
                return true;
            },
            dispose() { if (!committed) item.cancelled = true; },
        };
    }
    async function hydrate(item) {
        if (item.hydration) return item.hydration;
        const work = hydrateResources(item);
        item.hydration = work;
        try { return await work; }
        finally { if (item.hydration === work) item.hydration = null; }
    }
    async function hydrateResources(item) {
        const scope = item.scope;
        if (!scopeIsCurrent(scope) || item.cancelled) return false;
        // Observers may update the cache while resource producers are pending.
        // Compare against the exact receipt consumed, not that mutable cache.
        const consumedWorkspace = item.workspace, consumedImages = item.images;
        const consumedClinicalRevision = consumedWorkspace.timepoint_clinical_revision;
        const consumedLifecycleRevision = consumedWorkspace.timepoint?.lifecycle_revision;
        item.ready = false; status('loading');
        const hydrationNoticeScope = {...scope, allowAfterCompleted:true};
        window.showCaseResourceLoading?.(hydrationNoticeScope);
        try {
            const result = await window.hydrateTimepointWorkspace(consumedWorkspace, scope, consumedImages);
            if (!scopeIsCurrent(scope) || item.cancelled) return false;
            // Partial/failed late resources never authorize an empty save.
            const geometryReady = result?.ready === true && result?.partial !== true;
            status(geometryReady ? 'loading' : 'partial', geometryReady ? 'info' : 'error');
            if (!geometryReady) return false;
            // Continue the same notice through observations, selected dose and
            // the final revision receipt, not just the mesh producer boundary.
            hydrationNoticeScope.runId = window.__workspaceHydrationRunId;
            window.showCaseResourceLoading?.(hydrationNoticeScope);
            await window.BrachyBotImplants?.reload?.(scope, { throwOnError: true });
            if (!scopeIsCurrent(scope)) return false;
            const doseRestored = await selectDose(item.doseMode, { persist: false });
            if (!scopeIsCurrent(scope) || item.cancelled) return false;
            // An intentionally absent/stale dose is a valid saved state. A
            // transport or geometry error is not: never authorize a partial
            // projection to overwrite the durable presentation.
            if (!doseRestored && item.status === 'dose_failed') return false;
            // Legacy plan-history normalization during actual resource loading
            // can publish a new clinical version. Do not hand subsequent UI
            // writers the older shell receipt or rebase its presentation.
            const latest=await json(scope,'/api/sessions/'+encodeURIComponent(scope.sessionId)
                +'/timepoints/'+encodeURIComponent(scope.timepointId)+'/workspace');
            if(!scopeIsCurrent(scope) || item.cancelled)return false;
            assertOwner(latest.workspace,scope);
            if(latest.workspace.timepoint_clinical_revision!==consumedClinicalRevision
                || latest.workspace.timepoint?.lifecycle_revision !== consumedLifecycleRevision) {
                // Generic recovery may observe an already-rebased item and
                // return hydrate(item): that is this very pending promise.
                // Drift requires a fresh mount, never recursive self-replay.
                if (!await controller().reload()) return false;
                const next = mounted && entry(mounted);
                if (!next || next === item || next.scope.sessionId !== scope.sessionId
                    || next.scope.timepointId !== scope.timepointId) return false;
                item.successor = next;
                return hydrate(next);
            }
            controller().observeWorkspace(scope,latest.workspace);
            item.workspace=copy(latest.workspace);
            // The shell/geometry is not the final readiness boundary: observation
            // reload and selected-dose restoration can still replace its owner.
            item.ready = true;
            if (item.status === 'loading') status('ready');
            return true;
        } catch (error) {
            if (scopeIsCurrent(scope) && error.name !== 'AbortError') status('failed', 'error');
            return false;
        } finally {
            if (scopeIsCurrent(scope) && !item.successor) {
                window.setWorkspaceHydrationState?.(false, '', hydrationNoticeScope);
            }
        }
    }
    function persistImageAppearance(scope) {
        const item = entry(scope), image = item?.images.images.find(row => row.id === item.images.display_image_id);
        if (!image || !same(scope,mounted) || state.displayImageId !== image.id) return null;
        const patch = {opacity:Number(dataTreeState.ct.opacity), color:dataTreeState.ct.color,
            wwl:{width:Number(state.viewerSettings.window),level:Number(state.viewerSettings.level)}};
        if (!/^#[0-9a-fA-F]{6}$/.test(patch.color || '')) delete patch.color;
        const changed = patch.opacity !== image.opacity || patch.color && patch.color.toLowerCase() !== image.color?.toLowerCase()
            || patch.wwl.width !== image.wwl?.width || patch.wwl.level !== image.wwl?.level;
        if (!changed) return null;
        const digest = JSON.stringify({image:image.id,patch});
        if (item.appearancePending?.digest === digest) return item.appearancePending.work;
        const work = changeImage(image.id,patch);
        item.appearancePending = {digest,work};
        void work.finally(()=>{if (item.appearancePending?.work === work) item.appearancePending = null;});
        return work;
    }
    async function flush(scope) {
        await awaitPlanningConfig(scope);
        if (same(scope,mounted) && entry(scope)?.ready && await persistImageAppearance(scope) === false)
            throw fail('timepoint_image_save_failed');
        const pending = imageMutations.get(key(scope));
        if (pending && await pending === false) throw fail('timepoint_image_save_failed');
    }
    function handlePresentationSave(options = {}) {
        if (!registered || !controller()?.enabled()) return false;
        if (!mounted || suspended || !entry(mounted)?.ready) return true;
        if (options.sessionId && options.sessionId !== mounted.sessionId) return true;
        if (options.timepointScope && !scopeIsCurrent(options.timepointScope)) return true;
        const scope = mounted, pending = persistImageAppearance(scope);
        if (pending) void pending.then(saved=>{if (saved && scopeIsCurrent(scope)) controller().schedulePresentationSave();});
        else controller().schedulePresentationSave();
        return true;
    }
    async function persistPresentation(options = {}) {
        if (!registered || !controller()?.enabled()) return null;
        const scope = captureRequestScope(options.timepointScope);
        if (!scope || !scopeIsCurrent(scope) || !entry(scope)?.ready) return false;
        // Capture the outgoing owner's DOM/state before the Session shell is
        // cleared. Never read the newly selected case after an asynchronous
        // image/config save. The server's clinical/lifecycle CAS still applies.
        const captured = capture(scope);
        const appearance = persistImageAppearance(scope);
        try { await flush(scope); }
        catch (error) {
            if (!options.allowDetached || scopeIsCurrent(scope)) throw error;
            // Browser-side cancellation after navigation does not cancel an
            // already sent owned image save. Save the captured presentation
            // separately; the server must validate/rebase its original CAS.
        }
        if (appearance) {
            try { if (await appearance === false && !options.allowDetached) return false; }
            catch (error) { if (!options.allowDetached || scopeIsCurrent(scope)) throw error; }
        }
        if (!options.allowDetached && !scopeIsCurrent(scope)) return false;
        return controller().savePresentation(scope, captured, { allowDetached: options.allowDetached === true });
    }
    async function restoreActive(options = {}) {
        const owner = mounted;
        const requestKey = owner && JSON.stringify([owner.sessionId, owner.timepointId, owner.generation]);
        if (requestKey && restoreTasks.has(requestKey)) return restoreTasks.get(requestKey);
        const work = (async () => {
            try { return await restoreActiveResources(options); }
            catch (error) {
                if (same(owner, mounted)) status('failed','error');
                return false;
            }
        })();
        if (requestKey) restoreTasks.set(requestKey, work);
        try { return await work; }
        finally { if (requestKey && restoreTasks.get(requestKey) === work) restoreTasks.delete(requestKey); }
    }
    function acceptPlanningConfig(scope, config) {
        if (!scope || !scopeIsCurrent(scope)) return false;
        const item = entry(scope);
        // Retain the accepted values during an already queued resource replay.
        // This is a browser projection; persistence remains server-owned.
        const projected = window.BrachyBotInputPlanningConfig.projectSnapshot(item.workspace, config);
        Object.assign(item.workspace, projected);
        // Rebase this exact clinical CAS owner before presentation/navigation.
        item.configCommit = observeCommittedState(scope);
        void item.configCommit.catch(() => { if (scopeIsCurrent(scope)) status('failed','error'); });
        return true;
    }
    async function awaitPlanningConfig(scope) {
        const item = scope && entry(scope), pending = item?.configCommit;
        if (!pending) return true;
        if (await pending === false || !scopeIsCurrent(scope)) throw fail('stale_timepoint_action');
        if (item.configCommit === pending) item.configCommit = null;
        return true;
    }
    async function waitForClinicalMutation(scope) {
        const pending = entry(scope)?.configMutation;
        if (pending) await pending;
        return awaitPlanningConfig(scope);
    }
    async function beginPlanningConfig(scope) {
        assertCurrent(scope);
        await flush(scope);
        await controller().savePresentation(scope, capture(scope));
        assertCurrent(scope);
        const item = entry(scope);
        let release;
        const pending = new Promise(resolve => { release = resolve; });
        item.configMutation = pending;
        return () => {
            if (item.configMutation === pending) item.configMutation = null;
            release();
        };
    }
    async function restoreActiveResources(options = {}) {
        if (!controller()?.enabled()) return false;
        const initialOwner = mounted;
        const initialItem = mounted && entry(mounted);
        const pending = initialItem?.hydration;
        if (pending) {
            await pending;
            if (!mounted || mounted.sessionId !== initialOwner.sessionId
                || mounted.timepointId !== initialOwner.timepointId) return false;
            if (!same(mounted, initialOwner)) {
                // Only a remount explicitly created by that hydration may
                // succeed it. A1 -> B2 -> A3 navigation is not A1 recovery.
                let successor = initialItem?.successor, depth = 0;
                while (successor && depth++ < 16) {
                    if (same(successor.scope, mounted)) return successor.ready === true;
                    successor = successor.successor;
                }
                return false;
            }
        }
        if (mounted && scopeIsCurrent(mounted)) {
            const item = entry(mounted);
            item.ready = false;
            const response = await json(mounted, '/api/sessions/' + encodeURIComponent(mounted.sessionId)
                + '/timepoints/' + encodeURIComponent(mounted.timepointId) + '/workspace');
            if (!scopeIsCurrent(item.scope)) return false;
            assertOwner(response.workspace, item.scope);
            controller().observeWorkspace(item.scope, response.workspace);
            if (response.workspace.timepoint_clinical_revision !== item.workspace.timepoint_clinical_revision
                || response.workspace.timepoint?.lifecycle_revision !== item.workspace.timepoint?.lifecycle_revision)
            {
                // reload() commits a shell synchronously; its owned resource
                // hydration is queued. Wait for that actual new mount as well.
                if (!await controller().reload()) return false;
                const next = mounted && entry(mounted);
                if (!next || next.scope.sessionId !== item.scope.sessionId
                    || next.scope.timepointId !== item.scope.timepointId) return false;
                return hydrate(next);
            }
            const restored = window.BrachyBotInputPlanningConfig
                ? await window.BrachyBotInputPlanningConfig.prepareSnapshot(response.workspace, item.scope,
                    () => scopeIsCurrent(item.scope)) : response.workspace;
            if (!restored || !scopeIsCurrent(item.scope)) return false;
            item.workspace = copy(restored); return hydrate(item);
        }
        await controller().refresh(); return !!mounted;
    }
    async function observeCommittedState(scope) {
        const response = await json(scope, '/api/sessions/' + encodeURIComponent(scope.sessionId)
            + '/timepoints/' + encodeURIComponent(scope.timepointId) + '/workspace');
        if (!scopeIsCurrent(scope)) return false;
        assertOwner(response.workspace, scope);
        entry(scope).workspace = copy(response.workspace);
        controller().observeWorkspace(scope, response.workspace);
        const saved = response.workspace.agent?.planning_results || {};
        const artifact = saved.manual_artifact_status || saved.artifact_status || {};
        if (['stale','pending','failed','expired'].includes(artifact.dvh)
            || ['stale','pending','failed','expired'].includes(artifact.quality_check)) clearQualityView();
        await controller().refresh({ activate: false });
        return scopeIsCurrent(scope);
    }
    async function reloadImages(explicit = null) {
        const scope = captureRequestScope(explicit); if (!scope) return false;
        const item = entry(scope), sequence = ++item.imageSequence;
        const packet = imagesPacket(await json(scope, imageUrl(scope)), scope);
        if (!scopeIsCurrent(scope) || sequence !== item.imageSequence) return false;
        item.images = packet; renderImages(); return observeCommittedState(scope);
    }
    async function changeImage(id, patch) {
        const scope = captureRequestScope(); if (!scope) return false;
        // Serialize this browser's image controls against their actual source
        // collection. A queued edit never recaptures a newly selected target.
        const previous = imageMutations.get(key(scope)) || Promise.resolve();
        const work = previous.catch(() => {}).then(() => updateOwnedImage(scope, id, patch));
        imageMutations.set(key(scope), work);
        try { return await work; }
        finally { if (imageMutations.get(key(scope)) === work) imageMutations.delete(key(scope)); }
    }
    async function updateOwnedImage(scope, id, patch) {
        const item = entry(scope), sequence = ++item.imageSequence;
        try {
            const packet = imagesPacket(await json(scope, imageUrl(scope) + '/' + encodeURIComponent(id), {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ expected_collection_revision: item.images.collection_revision, ...patch }),
            }), scope);
            item.images = packet;
            if (!scopeIsCurrent(scope) || sequence !== item.imageSequence) return false;
            renderImages();
            if (patch.planning_reference === true) { status('reference_saved'); await restoreActive(); return true; }
            if ('display' in patch || 'show' in patch || patch.restore) {
                item.ready = false; status('loading');
                const image = packet.images.find(row => row.id === packet.display_image_id);
                const result = await window.displayTimepointImage(image, scope);
                if (!scopeIsCurrent(scope) || sequence !== item.imageSequence) return false;
                item.ready = result?.success === true;
                status(item.ready ? 'ready' : 'partial', item.ready ? 'info' : 'error');
            } else if (packet.display_image_id === id && ('opacity' in patch || 'wwl' in patch || 'color' in patch)) {
                window.applyTimepointImageAppearance?.(packet.images.find(row => row.id === id), scope);
            }
            return observeCommittedState(scope);
        } catch (error) { if (scopeIsCurrent(scope) && error.name !== 'AbortError') status('image_failed', 'error'); return false; }
    }
    async function registerImage(path, details = {}, explicit = null) {
        const scope = captureRequestScope(explicit); if (!scope) return false;
        const item = entry(scope);
        const packet = imagesPacket(await json(scope, imageUrl(scope), { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, modality: document.getElementById('imageModality')?.value || 'CT',
                role: item.workspace.timepoint?.stage === 'intraoperative' ? 'intraop' : 'preop',
                ...details, expected_collection_revision: item.images.collection_revision }),
        }), scope);
        // Detached upload commits to its original server target, without a paint.
        if (!scopeIsCurrent(scope)) return false;
        item.images = packet; renderImages(); return observeCommittedState(scope);
    }
    async function removeImage(id) {
        const scope = captureRequestScope(); if (!scope) return false;
        const item = entry(scope), image = item.images.images.find(row => row.id === id);
        if (!image) return false;
        const okay = await window._confirmAction('将此图像移出当前时间点的图像集合？依赖将由服务端校验。',
            'Remove this image from the current timepoint image collection? The server will check its dependencies.');
        if (!okay || !scopeIsCurrent(scope)) return false;
        try {
            const packet = imagesPacket(await json(scope, imageUrl(scope) + '/' + encodeURIComponent(id), {
                method: 'DELETE', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ expected_collection_revision: item.images.collection_revision }),
            }), scope);
            if (!scopeIsCurrent(scope)) return false;
            item.images = packet; renderImages(); await restoreActive(); return true;
        } catch (error) { if (scopeIsCurrent(scope)) status('image_failed', 'error'); return false; }
    }
    const doseLabel = mode => ({ implanted: t('体内已有粒子', 'Implanted sources'), planned: t('补充规划', 'Planned sources'),
        total: t('体内＋补充总剂量', 'Implanted + planned total') })[mode];
    function clearQualityView() {
        if (typeof state !== 'undefined') { state.dvhData = null; state.structureAnalysis = null; state.metrics = {}; }
        window.updateMetrics?.({}); window.updateOARTable?.({});
        const chart = document.getElementById('dvhChart'); if (chart && window.Plotly) Plotly.purge(chart);
        if (typeof drawDVH === 'function') drawDVH._lastSig = null;
        const placeholder = document.getElementById('dvhPlaceholder'); if (placeholder) placeholder.style.display = '';
    }
    function clearDoseView() {
        window.clearDoseOverlayRuntime?.({ preserveDesired: true });
        clearQualityView();
    }
    function validateDose(data, scope, mode) {
        assertOwner(data, scope);
        if (data.source_set !== mode || typeof data.available !== 'boolean' || typeof data.stale !== 'boolean') throw fail('timepoint_dose_invalid');
        if (!data.available || data.stale) return;
        if (data.dose_units !== 'gy' || !Array.isArray(data.shape) || data.shape.length !== 3
            || data.shape.some(v => !Number.isInteger(v) || v <= 0) || !Array.isArray(data.dose)
            || data.dose.length !== data.shape.reduce((n, v) => n * v, 1) || data.dose.some(v => !Number.isFinite(v) || v < 0)
            || !data.geometry_signature || !Array.isArray(data.spacing) || !Array.isArray(data.origin)
            || !Array.isArray(data.direction)) throw fail('timepoint_dose_invalid');
        if (typeof state !== 'undefined' && (JSON.stringify(data.shape) !== JSON.stringify(state.ctShape)
            || JSON.stringify(data.spacing) !== JSON.stringify(state.ctSpacing) || JSON.stringify(data.origin) !== JSON.stringify(state.ctOrigin)
            || JSON.stringify(data.direction) !== JSON.stringify(state.ctDirection))) throw fail('timepoint_dose_geometry_mismatch');
    }
    function paintDose(data, item) {
        const scale = typeof doseModelScaleGy === 'function' ? doseModelScaleGy() : 190.8;
        // Existing heatmap/contour consumers use model units. Convert the declared
        // physical Gy exactly once at that boundary, never by guessing magnitude.
        let minimum = Infinity, maximum = -Infinity;
        for (const value of data.dose) { minimum = Math.min(minimum, value / scale); maximum = Math.max(maximum, value / scale); }
        const quantization = (maximum - minimum) / 65535, voxels = new Uint16Array(data.dose.length);
        for (let i = 0; i < voxels.length; i++) voxels[i] = quantization ? Math.round((data.dose[i] / scale - minimum) / quantization) : 0;
        const prior = item.workspace.ui?.state?.data_tree?.planning?.doseOverlay || {};
        state.doseOverlay = { shape: data.shape, planningId: data.planning_id || '', doseGeneration: data.dose_generation || 0,
            doseMin: minimum, doseMax: maximum, doseUnits: 'normalized_model_output', doseScaleGy: scale,
            doseStale: false, doseStatus: 'ready', doseSource: data.source_set, sourcePhysicalUnits: 'gy',
            timepointScope: item.scope, geometrySignature: data.geometry_signature, visible: prior.visible !== false,
            visible2D: prior.visible2D !== false, opacity: Number.isFinite(prior.opacity) ? prior.opacity : .4,
            volumeData: voxels, volumeMin: minimum, volumeQuantizationScale: quantization, volumeEncoding: 'uint16-linear-le',
            volumeStatus: 'ready', slices: {}, maxSlice: { axial: data.shape[0] - 1, sagittal: data.shape[2] - 1, coronal: data.shape[1] - 1 } };
        state.dvhData = copy(data.dvh || {}); state.dvhPlanningId = data.planning_id || '';
        state.metrics = copy(data.metrics || {}); state.doseSourceSet = data.source_set;
        window.invalidateDoseOverlayRenderCache?.(); window.applyDoseOverlayLayerOpacity?.();
        window.updateDoseColorbars?.(true, minimum, maximum);
        window.updateMetrics?.(state.metrics); window.updateOARTable?.(state.metrics.oar_metrics || {});
        if (typeof drawDVH === 'function') { drawDVH._lastSig = null; drawDVH(); }
        for (const axis of ['axial', 'sagittal', 'coronal']) window.updateSlice?.(axis, state.slices[axis]);
        window.dispatchEvent(new CustomEvent('brachybot:dose-source-changed', { detail: { ...item.scope, source_set: data.source_set } }));
    }
    async function selectDose(mode, options = {}) {
        if (!modes.includes(mode)) throw fail('timepoint_dose_invalid');
        const scope = captureRequestScope(); if (!scope) return false;
        const item = entry(scope), sequence = ++item.doseSequence;
        item.doseMode = mode; renderDoseControls();
        try {
            const data = await json(scope, '/api/dose/view?source_set=' + encodeURIComponent(mode));
            if (data.available && !data.stale && data.volume_url) {
                const response = await controller().request(scope, data.volume_url);
                if (!response.ok || response.headers.get('X-Dose-Source-Set') !== mode
                    || response.headers.get('X-BrachyBot-Timepoint') !== scope.timepointId) throw fail('timepoint_dose_invalid');
                const bytes = await response.arrayBuffer(), expected = data.shape.reduce((value, size) => value * size, 1);
                if (bytes.byteLength !== expected * 2) throw fail('timepoint_dose_invalid');
                const low = Number(response.headers.get('X-Dose-Min-Gy'));
                const scale = Number(response.headers.get('X-Dose-Quantization-Gy'));
                if (!Number.isFinite(low) || !Number.isFinite(scale) || scale < 0) throw fail('timepoint_dose_invalid');
                const view = new DataView(bytes);
                data.dose = Array.from({length: expected}, (_, index) => low + view.getUint16(index * 2, true) * scale);
            }
            validateDose(data, scope, mode);
            if (!scopeIsCurrent(scope) || sequence !== item.doseSequence) return false;
            if (!data.available || data.stale) { clearDoseView(); status(data.stale ? 'dose_stale' : 'dose_unavailable', 'error'); return false; }
            paintDose(data, item); status('dose_ready');
            if (options.persist !== false) handlePresentationSave();
            return true;
        } catch (error) { if (scopeIsCurrent(scope) && sequence === item.doseSequence && error.name !== 'AbortError') status('dose_failed', 'error'); return false; }
    }
    function button(text, action) {
        const node = document.createElement('button'); node.type = 'button'; node.className = 'timepoint-workspace-action';
        node.textContent = text; node.onclick = () => { void action(); }; return node;
    }
    function mountGuideReview(item) {
        guideController?.unmount(); guideController = null;
        const panel = document.getElementById('panelInput');
        if (!panel) return;
        let container = document.getElementById('timepointGuideReview');
        if (!container) { container = document.createElement('section'); container.id = 'timepointGuideReview'; panel.append(container); }
        if (item.workspace.timepoint?.stage !== 'intraoperative' || !window.BrachyGuideRegistration) { container.replaceChildren(); return; }
        const scope = item.scope;
        const capture = {session_id: scope.sessionId, timepoint_id: scope.timepointId, mount_generation: scope.generation};
        guideController = new BrachyGuideRegistration.GuideRegistrationController({container,
            getCapture: () => scopeIsCurrent(scope) ? capture : null,
            language: () => window._i18nLang || 'en',
            request: (path, options = {}) => json(scope, path, {method: options.method || 'GET',
                headers: {'Content-Type': 'application/json'}, ...(options.body ? {body: JSON.stringify(options.body)} : {})}),
            onReview: () => { if (scopeIsCurrent(scope)) void restoreActive(); }});
        void guideController.mount(capture).catch(() => { if (scopeIsCurrent(scope)) status('partial', 'error'); });
    }
    async function continuationSettings() {
        const scope = captureRequestScope(); if (!scope) return;
        const url = '/api/sessions/' + scope.sessionId + '/timepoints/' + scope.timepointId + '/intraoperative-settings';
        const response = await json(scope, url); if (!scopeIsCurrent(scope)) return;
        const overlay = document.createElement('div'); overlay.className = 'timepoint-modal';
        const form = document.createElement('form'); form.className = 'timepoint-dialog'; form.setAttribute('role', 'dialog'); form.setAttribute('aria-modal', 'true');
        const bilingual = (tag, zh, en) => { const node = document.createElement(tag); node.dataset.i18nZh = zh; node.dataset.i18nEn = en; node.textContent = t(zh, en); return node; };
        const heading = bilingual('h2', '术中增量规划设置', 'Intraoperative continuation settings'); heading.id = 'continuationSettingsTitle'; form.setAttribute('aria-labelledby', heading.id); form.append(heading);
        const fields = {};
        for (const [key, zh, en] of [['needle_radius_mm', '针半径（mm）', 'Needle radius (mm)'],
            ['minimum_guiding_length_mm', '最小导向长度（mm）', 'Minimum guiding length (mm)'],
            ['obstacle_clearance_mm', '障碍物间隙（mm）', 'Obstacle clearance (mm)'],
            ['maximum_depth_mm', '最大穿刺深度（mm）', 'Maximum insertion depth (mm)']]) {
            const label = document.createElement('label'); label.append(bilingual('span', zh, en));
            const input = document.createElement('input'); input.type = 'number'; input.step = '.01'; input.min = key === 'obstacle_clearance_mm' ? '0' : '.01';
            input.required = true; input.value = response.settings?.[key] ?? ''; input.name = key; fields[key] = input; label.append(input); form.append(label);
        }
        const confirm = document.createElement('input'); confirm.type = 'checkbox'; confirm.required = true;
        const label = document.createElement('label'); label.append(confirm, bilingual('span', '我确认这些软件几何参数；此操作不构成临床批准。', 'I confirm these software geometry inputs; this is not clinical approval.')); form.append(label);
        const error = document.createElement('p'); error.setAttribute('role', 'alert'); form.append(error);
        const actions = document.createElement('div'); actions.className = 'timepoint-dialog-actions';
        const cancel = bilingual('button', '取消', 'Cancel'), save = bilingual('button', '保存设置', 'Save settings'); cancel.type = 'button'; save.type = 'submit'; actions.append(cancel, save); form.append(actions);
        overlay.append(form); document.body.append(overlay); const previous = document.activeElement;
        const close = () => { overlay.remove(); document.removeEventListener('keydown', onKey);
            window.removeEventListener('i18nchange', localize); previous?.focus?.(); };
        const onKey = event => { if (event.key === 'Escape') { event.preventDefault(); close(); } if (event.key === 'Tab') {
            const nodes = [...Object.values(fields), confirm, cancel, save].filter(node => !node.disabled);
            if (event.shiftKey && document.activeElement === nodes[0]) { event.preventDefault(); nodes.at(-1).focus(); }
            else if (!event.shiftKey && document.activeElement === nodes.at(-1)) { event.preventDefault(); nodes[0].focus(); }
        }};
        document.addEventListener('keydown', onKey); cancel.onclick = close; Object.values(fields)[0].focus();
        form.onsubmit = async event => { event.preventDefault(); if (!scopeIsCurrent(scope)) { close(); return; } save.disabled = true;
            try { await json(scope, url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
                ...Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, Number(input.value)])),
                confirmed: confirm.checked, ...(Number.isInteger(response.clinical_revision)
                    ? {expected_clinical_revision:response.clinical_revision}:{expected_state_revision:response.state_revision})})}); close(); await restoreActive(); }
            catch (_) { error.textContent = t('设置未保存，请核对参数与版本后重试。', 'Settings were not saved. Check values and revision, then retry.'); save.disabled = false; }
        };
        const localize = () => overlay.querySelectorAll('[data-i18n-zh]').forEach(node => { node.textContent = t(node.dataset.i18nZh, node.dataset.i18nEn); });
        window.addEventListener('i18nchange', localize);
    }
    function imageRoleLabel(role) {
        return role === 'preop' ? t('术前', 'Preoperative') : role === 'intraop'
            ? t('术中', 'Intraoperative') : t('未分组图像', 'Images');
    }
    function imageGroupMenu(event) {
        event.preventDefault(); event.stopPropagation(); window.hideContextMenu?.();
        const item = mounted && entry(mounted); if (!item) return;
        const menu = document.createElement('div'); menu.id = 'ctxMenu'; menu.className = 'ctx-menu';
        menu.style.left = Math.min(event.clientX,window.innerWidth-240)+'px'; menu.style.top = Math.min(event.clientY,window.innerHeight-180)+'px';
        const id = item.images.display_image_id || item.images.images.at(-1)?.id;
        for (const [label,action] of [[t('显示图像背景','Show image background'),()=>id && changeImage(id,{display:true})],
            [t('隐藏所有图像背景','Hide all image backgrounds'),()=>id && changeImage(id,{display:false})],
            [t('保存图像集合…','Save image collection…'),()=>window.openSessionExportDialog?.({sessionId:item.scope.sessionId,
                timepointScope:item.scope,requireCurrentSession:true,group_ids:['group:images']})]]) {
            const node = button(label,()=>{menu.remove(); if (scopeIsCurrent(item.scope)) return action();}); node.className='ctx-menu-item'; menu.append(node);
        }
        document.body.append(menu); menu.querySelector('button')?.focus();
        menu.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();menu.remove();}};
    }
    function imageMenu(event, image, item) {
        event.preventDefault(); event.stopPropagation();
        window.hideContextMenu?.();
        const menu = document.createElement('div'); menu.id = 'ctxMenu'; menu.className = 'ctx-menu';
        menu.style.left = Math.min(event.clientX, window.innerWidth - 250) + 'px';
        menu.style.top = Math.min(event.clientY, window.innerHeight - 300) + 'px';
        const owned = item.scope;
        const action = (label, execute) => {
            const node = document.createElement('button'); node.type = 'button'; node.className = 'ctx-menu-item'; node.textContent = label;
            node.onclick = () => { menu.remove(); if (scopeIsCurrent(owned)) void execute(); }; menu.append(node);
        };
        action(image.id === item.images.display_image_id ? t('隐藏图像', 'Hide image') : t('在 2D 中显示', 'Show in 2D'),
            () => changeImage(image.id, {display: image.id !== item.images.display_image_id}));
        action(t('设为规划参考', 'Use as planning reference'), () => changeImage(image.id, {planning_reference:true}));
        for (const role of ['unclassified', 'preop', 'intraop']) {
            action(t('移至：', 'Move to: ') + imageRoleLabel(role), () => changeImage(image.id, {role}));
        }
        action(t('保存此图像…','Save this image…'), () => window.openSessionExportDialog?.({
            sessionId:owned.sessionId,timepointScope:owned,requireCurrentSession:true,object_ids:['image:'+image.id]}));
        action(t('移除图像…', 'Remove image…'), () => removeImage(image.id));
        document.body.append(menu); menu.querySelector('button')?.focus();
        menu.onkeydown = event => {if (event.key === 'Escape') {event.preventDefault(); menu.remove();}};
    }
    function imageRow(image, item, tree) {
        const active = image.id === item.images.display_image_id;
        const row = document.createElement('div'); row.className = 'timepoint-image-row'; row.dataset.imageId = image.id;
        row.dataset.timepointId = item.scope.timepointId; row.dataset.nodeType = 'image';
        row.oncontextmenu = event => imageMenu(event, image, item);
        // The displayed volume retains the original CT row's live two-handle
        // W/L and opacity controls. Its persistence is now owned by this UUID.
        if (tree && active && typeof window.renderTreeItem === 'function' && typeof dataTreeState !== 'undefined') {
            row.classList.add('timepoint-image-native');
            row.innerHTML = window.renderTreeItem('ct', {...dataTreeState.ct,
                label:image.name || image.id, visible:true, loaded:true}, image.modality);
            const native = row.querySelector('.tree-item');
            if (native) { native.dataset.objectId = 'image:'+image.id; native.dataset.nodeId = 'image:'+image.id;
                native.dataset.nodeType = 'image'; native.oncontextmenu = row.oncontextmenu; native.onclick = event => {
                if (!event.target.closest('button,input,.color-swatch,.eye-btn')) native.classList.toggle('selected');
            }; }
            const eye = row.querySelector('.eye-btn');
            if (eye) eye.onclick = event => {event.stopPropagation(); void changeImage(image.id,{display:false});};
            row.addEventListener('change', event => {
                if (!scopeIsCurrent(item.scope)) return;
                if (event.target.matches('[data-ct-window-level]')) void changeImage(image.id,{wwl:{
                    width:Number(state.viewerSettings.window),level:Number(state.viewerSettings.level)}});
                if (event.target.matches('.opacity-slider')) void changeImage(image.id,{opacity:Number(event.target.value)/100});
            });
        } else {
            const view = button(active ? '◉' : '○', () => changeImage(image.id,{display:!active}));
            view.setAttribute('aria-pressed', String(active));
            view.setAttribute('aria-label', (active ? t('隐藏图像：','Hide image: ') : t('显示图像：','Display image: ')) + image.name);
            const name = document.createElement('span'); name.className = 'timepoint-image-name'; name.textContent = image.name || image.id;
            row.append(view, name);
            if (tree) {
                const controls = document.createElement('details'); controls.className = 'timepoint-image-controls';
                const summary = document.createElement('summary'); summary.textContent = t('显示设置','Display settings'); controls.append(summary);
                const inputs = {};
                for (const [field,caption,value] of [['width','W',image.wwl?.width ?? 400],['level','L',image.wwl?.level ?? 40]]) {
                    const label = document.createElement('label'); label.textContent = caption;
                    const input = document.createElement('input'); input.type = 'number'; input.step = '.5'; input.value = value;
                    if (field === 'width') input.min = '.5';
                    input.setAttribute('aria-label', t('图像窗宽窗位：','Image window/level: ') + image.name + ' ' + caption);
                    inputs[field] = input; label.append(input); controls.append(label);
                    input.onchange = () => {if (Object.values(inputs).every(node=>node.checkValidity())) void changeImage(image.id,
                        {wwl:{width:Number(inputs.width.value),level:Number(inputs.level.value)}});};
                }
                const opacity = document.createElement('input'); opacity.type = 'range'; opacity.min = '0'; opacity.max = '100';
                opacity.value = Math.round((image.opacity ?? 1)*100); opacity.className = 'opacity-slider';
                opacity.setAttribute('aria-label', t('图像透明度：','Image opacity: ') + image.name);
                opacity.onchange = () => void changeImage(image.id,{opacity:Number(opacity.value)/100}); controls.append(opacity); row.append(controls);
                const color = document.createElement('input'); color.type = 'color'; color.value = image.color || '#888888';
                color.setAttribute('aria-label',t('图像标记颜色：','Image marker color: ') + image.name);
                color.onchange = () => void changeImage(image.id,{color:color.value}); controls.append(color);
            }
        }
        row.title = [image.original_filename || image.name, image.modality, (image.geometry?.size || []).join(' × '),
            (image.geometry?.spacing || []).join(' × ') + ' mm', image.id].join('\n');
        if (!tree) row.append(button(image.id === item.images.planning_reference_image_id ? t('规划参考 ✓','Planning reference ✓')
            : t('设为规划参考','Use as planning reference'), () => changeImage(image.id,{planning_reference:true})),
            button(t('移除','Remove'), () => removeImage(image.id)));
        if (tree && image.id === item.images.planning_reference_image_id) {
            const name = row.querySelector('.item-label,.timepoint-image-name');
            if (name) {
                const tag = document.createElement('span'); tag.className = 'timepoint-image-reference';
                tag.textContent = t('参考','Ref');
                tag.title = t('规划参考影像：规划输入与坐标系以这份影像为准；显示影像可独立切换。右键可更改。',
                    'Planning reference: planning inputs and coordinates use this image. The displayed image can be changed independently. Right-click to change the reference.');
                tag.setAttribute('aria-label', tag.title); name.append(tag);
            }
        }
        return row;
    }
    function renderImages() {
        const item = mounted && entry(mounted);
        const configure = document.getElementById('intraoperativeContinuationSettings');
        if (configure) {
            configure.hidden = item?.workspace.timepoint?.stage !== 'intraoperative';
            configure.textContent = t('术中规划设置', 'Continuation settings');
        }
        for (const host of document.querySelectorAll('[data-timepoint-images]')) {
            host.replaceChildren(); if (!item) continue;
            const tree = host.id === 'timepointImageTree';
            if (!tree) { const heading = document.createElement('h3'); heading.textContent = t('图像集合','Image collection'); host.append(heading); }
            for (const role of ['unclassified','preop','intraop']) {
                const images = item.images.images.filter(image => (image.role || 'unclassified') === role);
                if (!tree) { for (const image of images) host.append(imageRow(image,item,false)); continue; }
                if (role === 'unclassified') { for (const image of images) host.append(imageRow(image,item,true)); continue; }
                if (!images.length) continue;
                const group = document.createElement('div'); group.className = 'tree-group'; group.dataset.group = 'image_role_' + role;
                const header = document.createElement('div'); header.className = 'tree-group-header';
                const arrow = document.createElement('span'); arrow.className = 'arrow'; arrow.textContent = '▼';
                const label = document.createElement('span'); label.textContent = imageRoleLabel(role) + ' (' + images.length + ')'; header.append(arrow,label);
                header.onclick = () => window.toggleTreeGroup?.(header);
                const children = document.createElement('div'); children.className = 'tree-group-items';
                for (const image of images) children.append(imageRow(image,item,true)); group.append(header,children); host.append(group);
            }
            if (!item.images.images.length) { const empty = document.createElement('p'); empty.textContent = t('尚无图像；上传后将显示最新图像。', 'No images yet. The latest uploaded image will be displayed.'); host.append(empty); }
            if (tree) {
                const empty = host.querySelector('p');
                if (empty) { const leaf=document.createElement('div'); leaf.className='tree-item tree-empty-node'; leaf.textContent=t('暂无图像','No images'); empty.replaceWith(leaf); }
                continue;
            }
            const note = document.createElement('p'); note.className = 'timepoint-workspace-note';
            note.textContent = item.images.planning_reference_image_id ? t('显示图像和规划参考分别选择。', 'Display image and planning reference are selected separately.')
                : t('规划前请明确选择参考图像。', 'Select a planning reference image explicitly before planning.'); host.append(note);
        }
    }
    function renderDoseControls() {
        const mode = mounted && entry(mounted)?.doseMode;
        for (const select of document.querySelectorAll('[data-timepoint-dose]')) {
            select.replaceChildren();
            for (const value of modes) { const option = document.createElement('option'); option.value = value; option.textContent = doseLabel(value); select.append(option); }
            select.value = mode || 'planned'; select.disabled = !mounted || suspended;
            select.setAttribute('aria-label', t('剂量来源', 'Dose sources'));
        }
        for (const node of document.querySelectorAll('[data-timepoint-dose-label]')) node.textContent = t('剂量来源', 'Dose sources');
        for (const host of document.querySelectorAll('[data-timepoint-dose-tree]')) {
            host.replaceChildren(); if (!mounted) continue;
            for (const value of modes) { const node = button(doseLabel(value), () => selectDose(value));
                node.className = 'tree-item timepoint-dose-node';
                node.dataset.nodeType = 'timepoint_dose'; node.dataset.sourceSet = value; node.dataset.timepointId = mounted.timepointId;
                node.setAttribute('aria-pressed', String(value === mode)); host.append(node); }
        }
    }
    function mountControls() {
        // Popovers must not be clipped by the unified scrolling control bar.
        const popover = document.getElementById('doseColorbarPanel');
        const viewerPanel = document.getElementById('panelViewers');
        if (popover && viewerPanel && popover.closest('.viewers-toolbar')) viewerPanel.append(popover);
        const input = document.getElementById('panelInput');
        const toolbar = document.querySelector('#panelViewers .viewers-toolbar');
        const implantToolbar = document.querySelector('#panelViewers .implant-toolbar');
        if (toolbar && implantToolbar && implantToolbar.parentElement !== toolbar) toolbar.append(implantToolbar);
        if (input && !document.getElementById('timepointImageCollection')) {
            const host = document.createElement('section'); host.id = 'timepointImageCollection'; host.dataset.timepointImages = ''; input.prepend(host);
            const statusNode = document.createElement('p'); statusNode.id = 'timepointResourceStatus'; statusNode.setAttribute('role', 'status'); statusNode.setAttribute('aria-live', 'polite');
            input.prepend(statusNode);
            const retry=button(t('重试恢复当前时间点','Retry current timepoint restoration'),restoreActive);
            retry.id='timepointRetryRestore';retry.type='button';retry.hidden=true;
            statusNode.after(retry);
            const configure = button(t('术中规划设置', 'Continuation settings'), continuationSettings);
            configure.id = 'intraoperativeContinuationSettings'; input.prepend(configure);
        }
        for (const id of ['panelMetrics', 'panelViewers']) {
            const panel = document.getElementById(id); if (!panel || panel.querySelector('[data-timepoint-dose]')) continue;
            const label = document.createElement('label'); label.className = 'timepoint-dose-selector';
            const text = document.createElement('span'); text.dataset.timepointDoseLabel = '';
            const select = document.createElement('select'); select.dataset.timepointDose = ''; select.onchange = () => void selectDose(select.value);
            label.append(text, select);
            if (id === 'panelViewers' && toolbar) toolbar.prepend(label); else panel.prepend(label);
        }
        const tree = document.getElementById('dataTreeBody');
        const imageParent = tree?.querySelector('[data-group="image"] > .tree-group-items');
        if (tree && !tree.querySelector('[data-timepoint-images]')) {
            const images = document.createElement('section'); images.id = 'timepointImageTree'; images.dataset.timepointImages = '';
            (imageParent || tree).append(images);
        }
        if (tree && !tree.querySelector('[data-timepoint-dose-tree]')) {
            const dose = document.createElement('section'); dose.dataset.timepointDoseTree = '';
            (tree.querySelector('[data-group="planning"] > .tree-group-items') || tree).append(dose);
        }
        renderImages(); renderDoseControls(); renderStatus();
        window._restoreTreeGroupExpansionState?.(tree || document);
    }
    function register() {
        if (registered || !dependencies() || !controller()) return false;
        registered = controller().registerBridge({ timepoint_scope: true, async_fencing: true,
            scoped_persistence: true, preserves_shared_chat: true, capture, suspend, prepare, flush, waitForClinicalMutation });
        return registered;
    }
    window.BrachyBotTimepointWorkspace = Object.freeze({ captureRequestScope, scopeIsCurrent, headers, assertCurrent, awaitOwned, callbackOwned, fetchOwned,
        requestReady,
        acceptPlanningConfig, awaitPlanningConfig, beginPlanningConfig,
        handlePresentationSave, persistPresentation, restoreActive, reloadImages, registerImage, changeImage, removeImage,
        selectDose, mountControls, register, dependencies, mountedScope: () => mounted && Object.freeze({ ...mounted }),
        continuationSettings, renderImages, imageGroupMenu,
        resourceState: () => mounted ? { ready: entry(mounted)?.ready === true, status: entry(mounted)?.status,
            doseMode: entry(mounted)?.doseMode, images: copy(entry(mounted)?.images) } : null });
    const ready = () => {
        mountControls(); register();
        window.addEventListener('brachybot:timepoint-runtime-ready', register);
        window.addEventListener('i18nchange', () => { renderImages(); renderDoseControls(); renderStatus(); });
        window.addEventListener('brachybot:timepoint-session-ready', () => {
            if (mounted && mounted.sessionId !== String(window._activeApiSessionId?.() || '')) { suspended = true; mounted = null; }
        });
        window.addEventListener('brachybot:data-tree-rendered', mountControls);
        // The legacy tree rebuilds its children. Observe its structural changes
        // only, reinstalling these owned groups without replacing legacy nodes.
        const tree = document.getElementById('dataTreeBody');
        if (tree) new MutationObserver(() => {
            if (!tree.querySelector('[data-timepoint-images]')) mountControls();
        }).observe(tree, { childList: true });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, { once: true }); else ready();
})();
