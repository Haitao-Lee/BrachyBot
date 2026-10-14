// Software contract tests, not clinical inference or WebGL acceptance.
// Execute extracted product functions. Fixtures supply tiny declared HTTP bytes,
// controlled paint/debounce scheduling and DOM lifecycle hooks. No clinical
// calculation is replaced; the real generic reconstruction takes an HTTP-error
// path before rendering. Structural result fixtures test the producer boundary,
// not the mesh algorithm. The independently maintained fit helper is not tested here.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const root = path.resolve(__dirname, '../web/app/static/js');
const source = Object.fromEntries(['ui-api', 'viewer-volume', 'dvh-planning', 'viewer-layout']
    .map(name => [name, fs.readFileSync(path.join(root, `brachybot-${name}.js`), 'utf8')]));
function fn(file, name) {
    const text = source[file];
    const start = text.search(new RegExp(`(?:async )?function ${name}\\(`));
    assert(start >= 0, `Missing production function ${name}`);
    const end = text.indexOf('\n}', start);
    assert(end > start, `Missing production function end ${name}`);
    return text.slice(start, end + 2);
}
function section(file, first, next) {
    const text = source[file], start = text.indexOf(first), end = text.indexOf(next, start + first.length);
    assert(start >= 0 && end > start, `Missing production section ${first}`);
    return text.slice(start, end);
}
function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
}
async function bounded(promise) {
    let timer;
    try { return await Promise.race([promise, new Promise((_, reject) => {
        timer = setTimeout(() => reject(Error('Product promise did not settle')), 500);
    })]); } finally { clearTimeout(timer); }
}
function context(extra = {}) {
    const A = Object.freeze({ sessionId: 'session', timepointId: 'A', generation: 1 });
    const B = Object.freeze({ sessionId: 'session', timepointId: 'B', generation: 2 });
    const c = {
        A, B, selected: A, activeSessionId: 'session', API: '/api',
        viewerDataLoadGeneration: 0, __viewerRenderGeneration: 0,
        state: { sessionId: 'session', ctLoaded: true, ctPath: 'fixture.nii.gz', ctShape: [1, 1, 1],
            viewerSettings: {}, maskLabels: {}, slices: {} },
        dataTreeState: { organs: [], ctv: {}, skin: {} },
        volumeData: new Int16Array([17]), organMetaFromServer: { sentinel: 'current' },
        ctvStructureCatalog: [{ id: 'sentinel' }], genericMaskVolumeData: {},
        genericMaskCatalogSessionId: '', genericMaskCatalogGeneration: 0,
        console: { ...console, warn() {}, debug() {} }, uiDebugLog() {},
        Headers, Response, AbortController, ArrayBuffer, Uint8Array, Int16Array, DataView,
        Promise, Set, Map, Date, setTimeout, clearTimeout,
        document: { getElementById: () => null, documentElement: { lang: 'en' },
            body: { classList: { remove() {} } } },
        CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
        dispatchEvent() {}, ...extra,
    };
    c.window = c;
    c.BrachyBotTimepointWorkspace = {
        captureRequestScope: explicit => explicit || c.selected,
        scopeIsCurrent: scope => scope.sessionId === c.selected.sessionId
            && scope.timepointId === c.selected.timepointId && scope.generation === c.selected.generation,
        headers: (scope, input = {}) => ({ ...input, 'X-BrachyBot-Session': scope.sessionId,
            'X-BrachyBot-Timepoint': scope.timepointId }),
    };
    vm.createContext(c);
    vm.runInContext(section('viewer-volume', 'function _viewerDataSessionId(', 'function _getMprGeometry('), c);
    return c;
}
function planningContext() {
    const c = context(), timers = new Map();
    let sequence = 0;
    c.setTimeout = callback => { timers.set(++sequence, callback); return sequence; };
    c.clearTimeout = id => timers.delete(id);
    vm.runInContext(section('dvh-planning', 'let _refreshDebounce = null;', '// DEBUG: global diagnostic function')
        + fn('dvh-planning', '_planningRunSessionId')
        + fn('dvh-planning', '_planningRunHeaders') + fn('dvh-planning', 'refreshPlanningUI'), c);
    c.timers = timers;
    return c;
}
function genericContext({ empty = false, volumeFails = false, meshFails = false, lateMesh = null } = {}) {
    const c = context(), calls = [], id = 'mask_fixture';
    // One byte is a declared synthetic software mask, not a clinical segmentation.
    c.fetchViewerJsonWithRetry = async (url, init = {}) => {
        calls.push({ url, init });
        if (url.endsWith('/generic_masks')) return {
            response: new Response(null), data: { masks: empty ? [] : [
                { mask_id: id, kind: 'generic_segmentation', data_version: 1, visible3D: meshFails || !!lateMesh },
            ] },
        };
        if (url.includes('/generic_mask_volume?')) return volumeFails
            ? { response: new Response(null, { status: 503 }), data: { error: 'Declared fixture volume failure' } }
            : { response: new Response(null, { headers: { 'X-Shape-Z': '1', 'X-Shape-Y': '1', 'X-Shape-X': '1' } }),
                data: new Uint8Array([1]).buffer };
        if (url.endsWith('/3d_mask')) {
            if (lateMesh) await lateMesh.promise;
            return { response: new Response(null, { status: 503 }), data: { error: 'Declared fixture mesh failure' } };
        }
        throw Error(`Unexpected transport request ${url}`);
    };
    c.saves = [];
    c.scheduleWorkspaceSave = reason => c.saves.push(reason);
    vm.runInContext(fn('viewer-volume', '_isGenericSegmentationMask') + fn('viewer-volume', '_genericMaskClassification')
        + fn('viewer-volume', '_isOpenGenericMask') + fn('viewer-volume', 'hydrateGenericMasksFromServer'), c);
    // Real reconstruction wrapper, scope checks, node state and loading tokens.
    // HTTP failure prevents reaching the renderer; no renderer or mesh is faked.
    vm.runInContext(section('viewer-layout', 'let _viewer3DRequestGeneration = 0;', 'async function _get3DConfig(')
        + 'const _organ3DReconstructionInFlight = new Map();\n'
        + ['reconstructOrgan3D', '_viewer3DText', '_viewer3DNodeForId', '_setViewer3DNodeState',
            '_normalizeViewer3DResult', '_reconstructOrgan3D'].map(name => fn('viewer-layout', name)).join('\n'), c);
    return { c, calls, id, scope: c._captureViewerDataScope('session', c.A) };
}
async function barrierFor(producer, kind) {
    const c = context({ __workspaceHydrationRunId: 0 });
    c._activeApiSessionId = () => 'session';
    c._restoreActiveSessionWorkspace = async options => {
        options.registerBackgroundTask(producer, { kind });
        return { session_id: 'session' };
    };
    vm.runInContext(['_workspaceVisualReadinessStore', '_workspaceVisualReadinessKey',
        '_normalizeWorkspaceResourcePath', '_workspaceSnapshotCtPath', '_statusFromWorkspaceSnapshot',
        '_workspaceHasLiveVisibleClinicalState', '_workspaceNeedsClinicalRestore', '_runWorkspaceRestoreTransaction']
        .map(name => fn('ui-api', name)).join('\n'), c);
    await c._runWorkspaceRestoreTransaction({ timepointScope: c.A, workspace: {
        session_id: 'session', agent: { planning_results: { fixture_resource: true } },
    } });
    return bounded(Object.values(c.__workspaceVisualReadiness)[0].promise);
}

test('stale label entry rejects before metadata, transport and producer side effects', async () => {
    const c = context(); c.selected = c.B;
    let requests = 0, registrations = 0;
    c.fetchViewerJsonWithRetry = async () => { requests++; throw Error('Stale entry started transport'); };
    vm.runInContext(fn('viewer-volume', 'loadLabelVolumes') + fn('viewer-volume', 'hydrateGenericMasksFromServer'), c);
    const metadata = c.organMetaFromServer, catalog = c.ctvStructureCatalog;
    assert.equal(await c.loadLabelVolumes({ sessionId: 'session', timepointScope: c.A,
        resetPresentation: true, registerBackgroundTask: () => registrations++ }), false);
    assert.equal(c.organMetaFromServer, metadata); assert.equal(c.ctvStructureCatalog, catalog);
    assert.equal(c.state.viewerSettings.userConfigured, undefined);
    assert.equal(requests, 0); assert.equal(registrations, 0);
    assert.equal(await c.hydrateGenericMasksFromServer(null), false);
});

test('stale planning entry cannot cancel the current debounce or inflight request', async () => {
    const c = planningContext(); c.selected = c.B;
    const pendingB = c.refreshPlanningUI({ sessionId: 'session', timepointScope: c.B });
    const timerB = vm.runInContext('_refreshDebounce', c), generation = vm.runInContext('_refreshGeneration', c);
    let aborts = 0;
    c.inflightFixture = { abort: () => aborts++ };
    vm.runInContext('_refreshInflight = inflightFixture;', c);
    const rejected = await c.refreshPlanningUI({ sessionId: 'session', timepointScope: c.A });
    assert.equal(rejected.stale, true); assert.equal(rejected.success, false);
    assert(c.timers.has(timerB)); assert.equal(aborts, 0);
    assert.equal(vm.runInContext('_refreshGeneration', c), generation);
    const wrongSession = await c.refreshPlanningUI({ sessionId: 'another-session', timepointScope: c.B });
    assert.equal(wrongSession.stale, true); assert(c.timers.has(timerB)); assert.equal(aborts, 0);
    c.invalidatePlanningRefresh();
    assert.equal((await bounded(pendingB)).reason, 'workspace_changed');
});

test('same-owner debounce replacement settles the replaced promise and leaves the new timer current', async () => {
    const c = planningContext();
    const first = c.refreshPlanningUI({ timepointScope: c.A });
    const firstTimer = vm.runInContext('_refreshDebounce', c);
    const second = c.refreshPlanningUI({ timepointScope: c.A });
    assert.equal((await bounded(first)).reason, 'refresh_replaced');
    assert(!c.timers.has(firstTimer)); assert.equal(c.timers.size, 1);
    c.invalidatePlanningRefresh();
    const result = await bounded(second);
    assert.equal(result.cancelled, true); assert.equal(result.success, false);
    assert.equal(c.timers.size, 0);
});

test('debounce callback detects a changed owner and settles explicitly', async () => {
    const c = planningContext(), pending = c.refreshPlanningUI({ timepointScope: c.A });
    c.selected = c.B;
    const [id, callback] = [...c.timers][0]; c.timers.delete(id);
    await callback();
    const result = await bounded(pending);
    assert.equal(result.stale, true); assert.equal(result.reason, 'stale_owner');
});

function restoreContext() {
    const c = context(), paints = [], calls = [];
    c._activeApiSessionId = () => c.activeSessionId;
    c.requestAnimationFrame = callback => paints.push(callback);
    c.setTimeout = callback => { callback(); return 1; }; c.clearTimeout = () => {};
    c.trainingMonitorState = { sessionId: 'session' };
    c.updateBrainStatusIndicator = () => {};
    c.refreshDicomRTImportStatus = () => {};
    c.restoreTrainingMonitorSnapshot = () => {};
    vm.runInContext(['_statusFromWorkspaceSnapshot', '_normalizeWorkspaceResourcePath', '_workspaceSnapshotCtPath',
        '_workspaceHasLiveVisibleClinicalState', '_workspaceHasSavedPresentation', '_isExplicitUploadedMaskSource',
        '_restoreActiveSessionWorkspace'].map(name => fn('ui-api', name)).join('\n'), c);
    c.loadLabelVolumes = options => { calls.push(['labels', options]); return Promise.resolve(false); };
    c.fitAllViewersAfterWorkspaceRestore = options => { calls.push(['fit', options]); return Promise.resolve(true); };
    c.restoreOptions = { workspace: { session_id: 'session', agent: { planning_results: {} } },
        status: { session_id: 'session', ct_path: 'fixture.nii.gz', stored_keys: [] },
        timepointScope: c.A, background: true, preserveVisibleClinicalState: true, skipClientClear: true };
    return { c, paints, calls };
}
async function microtasks() { for (let count = 0; count < 16; count++) await Promise.resolve(); }

test('real restore stops at the CT-ready paint boundary after a timepoint switch', async () => {
    const { c, paints, calls } = restoreContext();
    const pending = c._restoreActiveSessionWorkspace(c.restoreOptions);
    await microtasks(); assert.equal(paints.length, 1);
    c.selected = c.B; c.viewerDataLoadGeneration++;
    c.organMetaFromServer = { B: 'current metadata' };
    paints.shift()();
    assert.equal(await bounded(pending), null);
    assert.equal(c.organMetaFromServer.B, 'current metadata'); assert.equal(calls.length, 0);
});

test('real restore fit caller passes the captured full requestScope without recapturing', async () => {
    const { c, paints, calls } = restoreContext();
    const pending = c._restoreActiveSessionWorkspace(c.restoreOptions);
    let settled = false; pending.finally(() => { settled = true; });
    for (let count = 0; count < 16 && !settled; count++) {
        await microtasks(); if (paints.length) paints.shift()();
    }
    await bounded(pending);
    const fit = calls.find(([kind]) => kind === 'fit')?.[1]; assert(fit);
    assert.equal(fit.requestScope.sessionId, 'session'); assert.equal(fit.requestScope.timepointScope, c.A);
    assert.equal(fit.requestScope.dataGeneration, c.viewerDataLoadGeneration);
    assert.equal(fit.requestScope.renderGeneration, c.__viewerRenderGeneration);
    assert.equal(c._viewerDataScopeIsCurrent(fit.requestScope, true), true);
});

test('stale restore transaction rejects before locks, transaction replacement or hydration generation', async () => {
    const c = context(); c.selected = c.B; c._activeApiSessionId = () => 'session';
    c.__workspaceHydrationRunId = 7;
    let locks = 0; c.lockWorkspacePresentationWrites = () => locks++;
    vm.runInContext('let _workspaceRestoreTransaction = null;\n'
        + fn('ui-api', 'restoreActiveSessionWorkspace') + fn('ui-api', '_runWorkspaceRestoreTransaction'), c);
    const rejected = await c.restoreActiveSessionWorkspace({ timepointScope: c.A });
    assert.equal(rejected.cancelled, true); assert.equal(locks, 0);
    assert.equal(vm.runInContext('_workspaceRestoreTransaction', c), null);
    assert.equal(await c._runWorkspaceRestoreTransaction({ timepointScope: c.A }), null);
    assert.equal(c.__workspaceHydrationRunId, 7);
});

test('structural producer retains failures through its actual promise expression and workspace barrier', async () => {
    const c = context(); c.options = {}; c.timepointScope = c.A; c.expectedSessionId = 'session';
    c.scene3D = { meshes: {} }; c._meshPromises = [];
    c.loadCTVAndObstacleMeshes = async options => {
        assert.equal(options.timepointScope, c.A);
        // Declared structural producer-boundary result: no computed mesh/dose.
        const response = new Response(JSON.stringify({ success: false, complete: false,
            failed: [{ kind: 'ctv', object_id: 'ctv:fixture', status: 503, error: 'Declared fixture structural failure' }] }),
        { headers: { 'Content-Type': 'application/json' } });
        return response.json();
    };
    vm.runInContext(section('dvh-planning', '        function _withTimeout(', '        function _waitForViewerPaint(')
        + section('dvh-planning', '        // CTV + OAR meshes', '        // Seeds + needles.'), c);
    const values = await Promise.all(c._meshPromises);
    const failed = c._collectViewerMeshFailures(values);
    assert.equal(failed.length, 1); assert.equal(failed[0].object_id, 'ctv:fixture');
    c.isCurrentCase = () => c.BrachyBotTimepointWorkspace.scopeIsCurrent(c.A);
    c.guideRestorePromise = null; c.refreshOutcome = {};
    c.requestAnimationFrame = callback => callback();
    vm.runInContext(section('dvh-planning', '        function _waitForViewerPaint(', '        const _meshPromises = []')
        + section('dvh-planning', '            const backgroundMeshesPromise = Promise.all(_meshPromises)',
            '            const essentialError =')
        + section('dvh-planning', '            const viewerCompletionPromise = backgroundMeshesPromise.then(',
            '            // Report repair/capture'), c);
    const completion = await c.refreshOutcome.backgroundCompletion;
    assert.equal(completion.stage, 'viewer_partial'); assert.equal(completion.success, false);
    const result = await barrierFor(c.refreshOutcome.backgroundCompletion, 'viewer_3d');
    assert.equal(result.ready, false); assert.equal(result.partial, true);
    assert.equal(result.failures[0].resources[0].object_id, 'ctv:fixture');
    assert.equal(c._collectViewerMeshFailures([false]).length, 1);
    assert.equal(c._collectViewerMeshFailures([{ success: false }]).length, 1);
    assert.equal(c._collectViewerMeshFailures([{ complete: false }]).length, 1);
    assert.equal(c._collectViewerMeshFailures([null, { success: true }]).length, 0);
});

test('generic binary HTTP failure remains partial with mask identity at the real barrier', async () => {
    const { c, id, scope } = genericContext({ volumeFails: true });
    const result = await c.hydrateGenericMasksFromServer(scope);
    assert.equal(result.success, false); assert.equal(result.failed[0].kind, 'generic_mask_volume');
    assert.equal(result.failed[0].mask_id, id); assert.equal(c.state.maskLabels[id].status, 'error');
    const readiness = await barrierFor(Promise.resolve(result), 'generic_masks');
    assert.equal(readiness.ready, false); assert.equal(readiness.reason, 'visual_restore_partial');
    assert.equal(readiness.failures[0].resources[0].mask_id, id); assert.equal(c.saves.length, 0);
});

test('generic 3D HTTP failure executes real reconstruction and remains partial', async () => {
    const { c, id, scope, calls } = genericContext({ meshFails: true });
    const result = await c.hydrateGenericMasksFromServer(scope);
    assert(calls.some(call => call.url.endsWith('/3d_mask')));
    assert.equal(c.genericMaskVolumeData[id].data[0], 1);
    assert.equal(result.success, false); assert.equal(result.failed[0].kind, 'generic_mask_mesh');
    assert.match(result.failed[0].error, /Declared fixture mesh failure/);
    assert.equal((await barrierFor(Promise.resolve(result), 'generic_masks')).ready, false);
});

test('one failed generic volume preserves a successful sibling and remains partial', async () => {
    const { c, id, scope } = genericContext({ volumeFails: true });
    const originalTransport = c.fetchViewerJsonWithRetry;
    c.fetchViewerJsonWithRetry = async (url, init) => {
        if (url.endsWith('/generic_masks')) return { response: new Response(null), data: { masks: [
            { mask_id: id, kind: 'generic_segmentation', visible3D: false },
            { mask_id: 'mask_sibling', kind: 'generic_segmentation', visible3D: false },
        ] } };
        if (url.endsWith('mask_id=mask_sibling')) return {
            response: new Response(null, { headers: { 'X-Shape-Z': '1', 'X-Shape-Y': '1', 'X-Shape-X': '1' } }),
            data: new Uint8Array([1]).buffer,
        };
        return originalTransport(url, init);
    };
    const result = await c.hydrateGenericMasksFromServer(scope);
    assert.equal(result.success, false); assert.equal(result.failed.length, 1);
    assert.equal(result.failed[0].mask_id, id);
    assert.equal(c.state.maskLabels.mask_sibling.status, 'ready');
    assert.equal(c.genericMaskVolumeData.mask_sibling.data[0], 1);
});

test('late generic reconstruction cannot schedule a save against the new timepoint', async () => {
    const gate = deferred(), { c, scope, calls } = genericContext({ lateMesh: gate });
    const pending = c.hydrateGenericMasksFromServer(scope);
    await microtasks(); assert(calls.some(call => call.url.endsWith('/3d_mask')));
    c.selected = c.B; c.viewerDataLoadGeneration++;
    gate.resolve();
    assert.equal(await bounded(pending), false); assert.equal(c.saves.length, 0);
});

test('empty catalogue is a successful no-op and hidden valid binary mask decodes successfully', async () => {
    const empty = genericContext({ empty: true });
    assert.equal(await empty.c.hydrateGenericMasksFromServer(empty.scope), true);
    assert.equal(empty.calls.length, 1);
    const good = genericContext();
    assert.equal(await good.c.hydrateGenericMasksFromServer(good.scope), true);
    assert.equal(good.c.genericMaskVolumeData[good.id].data[0], 1);
    assert.equal(good.c.state.maskLabels[good.id].status, 'ready');
    assert.equal((await barrierFor(Promise.resolve(true), 'generic_masks')).ready, true);
});

function readinessContext() {
    const c = context(); c._activeApiSessionId = () => 'session';
    vm.runInContext(['_workspaceVisualReadinessStore', '_workspaceVisualReadinessKey',
        '_workspaceVisualReadinessSleep', '_normalizeWorkspaceResourcePath', '_workspaceSnapshotCtPath',
        '_statusFromWorkspaceSnapshot', '_workspaceHasLiveVisibleClinicalState'].map(name => fn('ui-api', name)).join('\n')
        + section('ui-api', 'window.awaitWorkspaceVisualReady = async function', 'let _workspaceRestoreTransaction = null;'), c);
    const partial = { ready: false, partial: true, reason: 'visual_restore_partial', failed_tasks: 1 };
    c.__workspaceVisualReadiness = { [c._workspaceVisualReadinessKey('session', c.A)]: { promise: Promise.resolve(partial) } };
    c._activeWorkspaceSnapshot = { session_id: 'session' };
    return { c, partial };
}

test('default and completion timepoint barriers keep a partial live scene not ready', async () => {
    const { c } = readinessContext();
    assert.equal(c._workspaceHasLiveVisibleClinicalState(c._activeWorkspaceSnapshot, 'session'), true);
    for (const waitForCompletion of [false, true]) {
        const result = await c.awaitWorkspaceVisualReady('session', { timepointScope: c.A, waitForCompletion, timeoutMs: 100 });
        assert.equal(result.ready, false); assert.equal(result.partial, true);
        assert.equal(result.reason, 'visual_restore_partial');
    }
});

test('legacy non-timepoint partial live-scene fallback remains explicitly legacy', async () => {
    const { c, partial } = readinessContext();
    delete c.BrachyBotTimepointWorkspace;
    c.__workspaceVisualReadiness = { session: { promise: Promise.resolve(partial) } };
    const result = await c.awaitWorkspaceVisualReady('session', { timeoutMs: 100 });
    assert.equal(result.ready, true); assert.equal(result.partial, true);
    assert.equal(result.reason, 'visual_restore_partial_with_live_scene');
});

test('real timepoint evidence handler refuses partial live scene before capture', async () => {
    const { c } = readinessContext();
    c.BrachyBotTimepointWorkspace.awaitOwned = async (scope, operation) => operation();
    c._normalizeStructuredScreenshotPlan = () => ({ mode: 'chat', views: [{ target: 'viewer-3d' }] });
    c._screenshotFailureMessage = () => 'Declared fixture failure message';
    vm.runInContext(fn('ui-api', '_interceptScreenshot'), c);
    const result = await c._interceptScreenshot('viewer-3d', '', {}, { timepointScope: c.A });
    assert.equal(result.success, false); assert.equal(result.error, 'workspace_visual_restore_incomplete');
    assert.equal(result.attachments.length, 0);
});

test('real timepoint report action refuses partial before live-scene preparation or autofill', async () => {
    const { c } = readinessContext();
    c.BrachyBotTimepointWorkspace.awaitOwned = async (scope, operation) => operation();
    vm.runInContext('const _reportAutoFillInFlight = new Map();\n' + fn('ui-api', '_executeUIActionRaw'), c);
    const result = await c._executeUIActionRaw({ target: 'report.autofill' }, { timepointScope: c.A });
    assert.equal(result.success, false); assert.equal(result.stage, 'report_workspace_not_ready');
    assert.equal(result.readiness.ready, false); assert.equal(result.readiness.reason, 'visual_restore_partial');
});

test('same-owner restore callers share one core and visual transaction until late producers finish', async () => {
    const c = context(), core = deferred(), visual = deferred();
    c._activeApiSessionId = () => 'session'; c.__workspaceHydrationRunId = 0;
    let loads = 0, locks = 0, releases = 0;
    c.lockWorkspacePresentationWrites = () => ++locks;
    c.unlockWorkspacePresentationWrites = () => releases++;
    c._restoreActiveSessionWorkspace = async options => {
        loads++; options.registerBackgroundTask(visual.promise, { kind: 'fixture_transport' });
        return core.promise;
    };
    vm.runInContext('let _workspaceRestoreTransaction = null;\n'
        + ['_workspaceVisualReadinessStore', '_workspaceVisualReadinessKey', '_workspaceNeedsClinicalRestore',
            'restoreActiveSessionWorkspace', '_runWorkspaceRestoreTransaction'].map(name => fn('ui-api', name)).join('\n'), c);
    const options = { timepointScope: c.A, workspace: { agent: { planning_results: { fixture_resource: true } } } };
    const first = c.restoreActiveSessionWorkspace(options);
    assert.equal(c.restoreActiveSessionWorkspace({ ...options, timepointScope: { ...c.A } }), first);
    await microtasks(); assert.equal(loads, 1); assert.equal(locks, 1);
    core.resolve({ session_id: 'session' }); await first; await microtasks();
    assert.equal(c.restoreActiveSessionWorkspace(options), first);
    assert.equal(loads, 1); assert.equal(releases, 0); assert.equal(c.__workspaceHydrationRunId, 1);
    const entry = Object.values(c.__workspaceVisualReadiness)[0]; assert.equal(entry.settled, false);
    assert.equal(entry.timepointScope, c.A);
    visual.resolve({ success: true }); assert.equal((await bounded(entry.promise)).ready, true);
    await microtasks(); assert.equal(releases, 1);
});

test('real readiness entries distinguish captured timepoint ownership from legacy entries', async () => {
    for (const owned of [true, false]) {
        const c = context(); c._activeApiSessionId = () => 'session';
        c._restoreActiveSessionWorkspace = async () => ({ session_id: 'session' });
        vm.runInContext(['_workspaceVisualReadinessStore', '_workspaceVisualReadinessKey',
            '_workspaceNeedsClinicalRestore', '_runWorkspaceRestoreTransaction']
            .map(name => fn('ui-api', name)).join('\n'), c);
        const timepointScope = owned ? c.A : null;
        await c._runWorkspaceRestoreTransaction({ timepointScope,
            workspace: { agent: { planning_results: { fixture_resource: true } } } });
        const entry = Object.values(c.__workspaceVisualReadiness)[0];
        assert.equal(entry.timepointScope, timepointScope);
        assert.equal(entry.sessionId, 'session'); assert.equal((await entry.promise).ready, true);
    }
});

// The Python wrapper consumes this marker and the exit code. Wait until the
// runner has finished so failures/cancellations cannot print a success marker.
process.on('exit', code => {
    if (code === 0) console.log('Timepoint restore producer contracts passed');
});
