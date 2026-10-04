// Cross-module regressions: use the actual workspace registry and catalogue
// loader, not a mock writer that accepts every identity (the previous harness
// could not expose an alias mismatch in the real registry).
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = process.argv[2] || path.resolve(__dirname, '..');
const workspace = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-workspace.js'), 'utf8');
const viewer = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-viewer-volume.js'), 'utf8');

function topLevelFunction(source, name) {
    const declaration = new RegExp(`^(?:async )?function ${name}\\(`, 'm');
    const match = declaration.exec(source);
    assert(match, `actual function ${name} exists`);
    const tail = source.slice(match.index);
    const next = /\n(?:async )?function \w+\(/.exec(tail.slice(match[0].length));
    const block = next ? tail.slice(0, match[0].length + next.index) : tail;
    // The selected helper's function body ends before its window export or
    // the next comment/constant. Functions in these regions are declarations.
    return block.slice(0, block.lastIndexOf('\n}') + 2);
}

function makeContext(sessionId = 'case-a') {
    const context = vm.createContext({
        console, Set, ArrayBuffer, Uint8Array, Date, JSON,
        activeSessionId: sessionId,
        state: { sessionId, maskLabels: {}, maskLabelCounter: 0 },
        dataTreeState: { ctv: {}, oar: {}, skin: {}, ctvLabels: {}, organs: [],
            planning: { trajectories: [], seeds: [], needles: [], doseLevels: [], meshes: [] } },
        scene3D: { meshes: {} }, API: '/api',
        genericMaskVolumeData: {}, genericMaskCatalogSessionId: '', genericMaskCatalogGeneration: 0,
        _viewerDataScopeIsCurrent: scope => scope.sessionId === context.activeSessionId,
        _viewerDataHeaders: () => ({}), _viewerDataSessionId: () => context.activeSessionId,
        renderDataTree: () => {}, loadAllSlices: () => {},
        _disposeSceneMesh: () => {}, renderDataTreeDebounced: () => {},
        reloadOverlays: () => {}, redrawSeedNeedleOverlays: () => {},
        requestViewerVisualRefresh: () => {}, applyMeshOpacity: () => {},
        syncCtvWorkspaceColor: () => {}, _setMeshMaterialColor: () => {},
        isDataTreeNodeVisible3D: () => true, _queueDataTreeOpacityOverlayRefresh: () => {},
        _planningItems: () => [],
        _findDataTreeNode: id => context._maskStateEntry(id),
        getSelectableIds: () => Object.keys(context.state.maskLabels),
        controlState: () => ({}), sceneViewState: () => ({}), dvhViewState: () => ({}),
        workspaceChromeState: () => ({}),
        window: { BRACHYBOT_MAX_UPLOADED_MASK_LABELS: 64, scheduleWorkspaceSave: () => {} },
    });
    const registry = workspace.slice(workspace.indexOf('    const WORKSPACE_PRESENTATION_KEYS'),
        workspace.indexOf('    let presentationWriteLockToken'));
    const merge = workspace.slice(workspace.indexOf('    function mergePresentationNode('),
        workspace.indexOf('    window.workspacePresentationTree ='));
    const clone = workspace.slice(workspace.indexOf('    function jsonClone('),
        workspace.indexOf('    // A workspace is restored in several asynchronous phases.'));
    vm.runInContext(`let deferredPresentationSave = null;\n${clone}\n${merge}\n${registry}`, context);
    for (const name of ['getWorkspacePresentationForNode', 'updateWorkspacePresentationForNode',
        'isWorkspacePresentationRestoreActive']) {
        context.window[name] = context[name];
    }
    const helpers = ['_isGenericSegmentationMask', '_genericMaskClassification', '_isOpenGenericMask',
        '_maskStateEntry', '_maskStateKey', '_isDataTreeMaskId', '_maskSceneMeshId',
        '_dataTreePresentationRef', '_recordDataTreePresentation', '_syncAllDataTreePresentation',
        '_scheduleDataTreeSave', 'getDataTreeAppearanceForMesh', 'setDataTreeItemColor',
        'setDataOpacity', 'hydrateGenericMasksFromServer'];
    vm.runInContext(helpers.map(name => topLevelFunction(viewer, name)).join('\n'), context);
    // Use the real serializer to prove a live edit can survive a fresh runtime.
    const serializer = workspace.slice(workspace.indexOf('    function workspaceUiState('),
        workspace.indexOf('    function queueServerReportFigureUpload('));
    vm.runInContext(serializer, context);
    const copy = workspace.slice(workspace.indexOf('    function copyDisplayProperties('),
        workspace.indexOf('    function isCompactPlanningShell('));
    vm.runInContext(copy, context);
    const maskRestoreStart = workspace.indexOf('// Restore manual/threshold masks');
    // The final brace closes the enclosing viewer block, not this mask block.
    const maskRestore = workspace.slice(maskRestoreStart,
        workspace.indexOf('const presentationTree = workspacePresentationTree(snapshot)', maskRestoreStart))
        .replace(/\s*}\s*$/, '');
    vm.runInContext(`function replayMaskSnapshot(uiState, options, sessionId) { ${maskRestore} }`, context);
    return context;
}

function snapshot(labels, agentLabels = {}) {
    return { session_id: 'case-a', ui: { state: { viewer: { masks: { labels } } } },
        agent: { ui_state: { viewer: { masks: { labels: agentLabels } } } } };
}

function serverMask(id, overrides = {}) {
    return { mask_id: id, object_id: `mask:${id}`, data_tree_node_id: id,
        kind: 'uploaded_mask_label', source: 'uploaded_mask', name: 'Label 2',
        classification: 'unclassified', shape: [1, 1, 1], ...overrides };
}

function serve(context, entries) {
    context.window.fetchViewerJsonWithRetry = async url => url.endsWith('/generic_masks')
        ? { response: { ok: true }, data: { masks: entries, uploads: [] } }
        : { response: { ok: true, headers: { get: name =>
            name.startsWith('X-Shape-') ? '1' : null } }, data: new ArrayBuffer(1) };
}

const failures = [];
let passed = 0;
async function test(name, fn) {
    try { await fn(); passed += 1; console.log(`PASS: ${name}`); }
    catch (error) { failures.push(name); console.error(`FAIL: ${name}: ${error.message}`); }
}

(async () => {
    await test('map key, snake-case object identity and DOM alias resolve one record', () => {
        const ctx = makeContext();
        ctx.stageWorkspacePresentation(snapshot({ upload_a_label_2: {
            id: 'legacy_dom_alias', object_id: 'mask:upload_a_label_2',
            data_tree_node_id: 'upload_a_label_2', color: '#124578', opacity: 0.23,
        } }), 'case-a');
        for (const id of ['upload_a_label_2', 'mask:upload_a_label_2', 'legacy_dom_alias']) {
            const restored = ctx.getWorkspacePresentationForNode({ family: 'mask', id });
            assert.equal(restored?.color, '#124578', id);
            assert.equal(restored?.opacity, 0.23, id);
        }
    });
    await test('two uploads with the same label never share appearance', () => {
        const ctx = makeContext();
        ctx.stageWorkspacePresentation(snapshot({
            upload_a_label_2: { id: 'mask:upload_a_label_2', name: 'Label 2', color: '#112233', opacity: 0 },
            upload_b_label_2: { id: 'mask:upload_b_label_2', name: 'Label 2', color: '#445566', opacity: 0.91 },
        }), 'case-a');
        assert.equal(ctx.getWorkspacePresentationForNode({ family: 'mask', id: 'upload_a_label_2' })?.opacity, 0);
        assert.equal(ctx.getWorkspacePresentationForNode({ family: 'mask', id: 'upload_b_label_2' })?.color, '#445566');
        assert.equal(ctx.getWorkspacePresentationForNode({ family: 'mask', id: 'new_upload_label_2', name: 'Label 2' }), null);
    });
    await test('partial browser projection retains agent-only mask style fields', () => {
        const ctx = makeContext();
        ctx.stageWorkspacePresentation(snapshot({ upload_a_label_2: { opacity: 0.19 } },
            { upload_a_label_2: { color: '#8899aa', opacity: 0.73, visible3D: false } }), 'case-a');
        const value = ctx.getWorkspacePresentationForNode({ family: 'mask', id: 'upload_a_label_2' });
        assert.equal(value?.color, '#8899aa');
        assert.equal(value?.opacity, 0.19);
        assert.equal(value?.visible3D, false);
    });
    await test('agent-only catalogue style restores during a cold resource load', async () => {
        const ctx = makeContext();
        ctx.stageWorkspacePresentation(snapshot({}, { upload_a_label_2: {
            color: '#987654', opacity: 0.14, visible2D: false, visible3D: false,
        } }), 'case-a');
        serve(ctx, [serverMask('upload_a_label_2')]);
        await ctx.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 1 });
        assert.equal(ctx.state.maskLabels.upload_a_label_2.color, '#987654');
        assert.equal(ctx.state.maskLabels.upload_a_label_2.opacity, 0.14);
        assert.equal(ctx.state.maskLabels.upload_a_label_2.visible3D, false);
    });
    await test('legacy Agent UI bridge nodes recover presentation but not clinical fields', () => {
        const ctx = makeContext();
        const saved = snapshot({});
        saved.agent.ui_state.data_tree = { nodes: [{
            node_id: 'upload_a_label_2', object_id: 'mask:upload_a_label_2', type: 'generic_mask',
            color: '#102030', opacity: 0.47, classification: 'ctv', voxels: [7, 8, 9],
        }] };
        ctx.stageWorkspacePresentation(saved, 'case-a');
        const value = ctx.getWorkspacePresentationForNode({ family: 'mask', id: 'upload_a_label_2' });
        assert.equal(value?.color, '#102030');
        assert.equal(value?.opacity, 0.47);
        assert.equal(value.classification, undefined);
        assert.equal(value.voxels, undefined);
    });
    await test('server metadata is a style fallback, including zero opacity and hidden flags', async () => {
        const ctx = makeContext();
        serve(ctx, [serverMask('upload_a_label_2', { color: '#abcdef', opacity: 0,
            visible: false, visible2D: false, visible3D: false })]);
        await ctx.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 1 });
        const value = ctx.state.maskLabels.upload_a_label_2;
        assert.equal(value.color, '#abcdef');
        assert.equal(value.opacity, 0);
        assert.equal(value.visible, false);
        assert.equal(value.visible2D, false);
        assert.equal(value.visible3D, false);
    });
    await test('live colour/opacity edits survive repeated hydration and fresh-runtime restore', async () => {
        const ctx = makeContext();
        ctx.stageWorkspacePresentation(snapshot({ upload_a_label_2: {
            id: 'mask:upload_a_label_2', color: '#112233', opacity: 0.8,
        } }), 'case-a');
        serve(ctx, [serverMask('upload_a_label_2')]);
        await ctx.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 1 });
        ctx.finalizeWorkspacePresentationRestore('case-a', null, { persistDeferred: false });
        assert.equal(ctx.setDataTreeItemColor('upload_a_label_2', '#88aaff'), true);
        ctx.setDataOpacity('upload_a_label_2', '0');
        await ctx.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 2 });
        assert.equal(ctx.state.maskLabels.upload_a_label_2.color, '#88aaff');
        assert.equal(ctx.state.maskLabels.upload_a_label_2.opacity, 0);
        const meshStyle = ctx.getDataTreeAppearanceForMesh('upload_a_label_2', {
            userData: { objectId: 'mask:upload_a_label_2' },
        });
        assert.equal(meshStyle.color, '#88aaff');
        assert.equal(meshStyle.opacity, 0);
        const fresh = makeContext();
        const saved = JSON.parse(JSON.stringify({ session_id: 'case-a', ui: { state: ctx.workspaceUiState('case-a') } }));
        fresh.stageWorkspacePresentation(saved, 'case-a');
        serve(fresh, [serverMask('upload_a_label_2')]);
        await fresh.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 1 });
        assert.equal(fresh.state.maskLabels.upload_a_label_2.color, '#88aaff');
        assert.equal(fresh.state.maskLabels.upload_a_label_2.opacity, 0);
        assert.equal(fresh.getDataTreeAppearanceForMesh('mask:upload_a_label_2', {
            userData: { objectId: 'mask:upload_a_label_2' },
        }).color, '#88aaff');
    });
    await test('first-time mask keeps its edits although the staged snapshot has no record', async () => {
        const ctx = makeContext();
        ctx.stageWorkspacePresentation(snapshot({}), 'case-a');
        serve(ctx, [serverMask('upload_a_label_2')]);
        await ctx.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 1 });
        ctx.setDataTreeItemColor('upload_a_label_2', '#cdefab');
        assert.equal(ctx.getWorkspacePresentationForNode({ family: 'mask', id: 'upload_a_label_2' })?.color, '#cdefab');
    });
    await test('late snapshot reconciliation does not undo an edit made during resource loading', async () => {
        const ctx = makeContext();
        const saved = snapshot({ upload_a_label_2: { color: '#112233', opacity: 0.8 } });
        ctx.stageWorkspacePresentation(saved, 'case-a');
        serve(ctx, [serverMask('upload_a_label_2')]);
        await ctx.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 1 });
        ctx.setDataTreeItemColor('upload_a_label_2', '#ff8844');
        ctx.setDataOpacity('upload_a_label_2', '17');
        ctx.replayMaskSnapshot(saved.ui.state, { preserveClinicalData: true }, 'case-a');
        assert.equal(ctx.state.maskLabels.upload_a_label_2.color, '#ff8844');
        assert.equal(ctx.state.maskLabels.upload_a_label_2.opacity, 0.17);
    });
    await test('server classification still wins; promoted masks never regain a standalone volume', async () => {
        const ctx = makeContext();
        ctx.stageWorkspacePresentation(snapshot({ upload_a_label_2: { color: '#445566', opacity: 0.32 } }), 'case-a');
        serve(ctx, [serverMask('upload_a_label_2', { classification: 'ctv' })]);
        await ctx.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 1 });
        assert.equal(ctx.state.maskLabels.upload_a_label_2.classification, 'ctv');
        assert.equal(ctx.genericMaskVolumeData.upload_a_label_2, undefined);
    });
    await test('snapshot reconciliation retains a hydrated open-mask sibling after CTV promotion', async () => {
        const ctx = makeContext();
        const saved = snapshot({ upload_a_label_1: {
            kind: 'uploaded_mask_label', classification: 'ctv', color: '#102030', opacity: 0.41,
        } });
        ctx.stageWorkspacePresentation(saved, 'case-a');
        serve(ctx, [serverMask('upload_a_label_1', { classification: 'ctv' }),
            serverMask('upload_a_label_2', { color: '#445566', opacity: 0.82 })]);
        await ctx.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 1 });
        ctx.replayMaskSnapshot(saved.ui.state, { preserveClinicalData: true }, 'case-a');
        assert.deepEqual(Object.keys(ctx.state.maskLabels).sort(), ['upload_a_label_1', 'upload_a_label_2']);
        assert.equal(ctx.state.maskLabels.upload_a_label_1.classification, 'ctv');
        assert.equal(ctx.genericMaskVolumeData.upload_a_label_1, undefined);
        assert.equal(ctx.state.maskLabels.upload_a_label_2.classification, 'unclassified');
        assert.equal(ctx.state.maskLabels.upload_a_label_2.color, '#445566');
        assert.equal(ctx.state.maskLabels.upload_a_label_2.opacity, 0.82);
        assert(ctx.genericMaskVolumeData.upload_a_label_2);
    });
    await test('same numeric CTV label and mask ID do not contaminate each other', () => {
        const ctx = makeContext();
        const saved = snapshot({ '2': { color: '#223344', opacity: 0.28 } });
        saved.ui.state.data_tree = { ctvLabels: { ctv_2: { color: '#aabbcc', opacity: 0.85 } } };
        ctx.stageWorkspacePresentation(saved, 'case-a');
        ctx.updateWorkspacePresentationForNode({ family: 'mask', id: '2' }, { color: '#556677' });
        assert.equal(ctx.getWorkspacePresentationForNode({ family: 'ctv', id: 'ctv_2' }).color, '#aabbcc');
        assert.equal(ctx.getWorkspacePresentationForNode({ family: 'mask', id: '2' }).color, '#556677');
    });
    await test('manual/threshold mask IDs and voxel Sets keep their existing restore semantics', () => {
        const ctx = makeContext();
        const saved = snapshot({ mask_threshold: { id: 'mask_threshold',
            color: '#446688', opacity: 0.63, voxels: [2, 3, 4] } });
        ctx.stageWorkspacePresentation(saved, 'case-a');
        ctx.replayMaskSnapshot(saved.ui.state, { preserveClinicalData: false }, 'case-a');
        assert.deepEqual([...ctx.state.maskLabels.mask_threshold.voxels], [2, 3, 4]);
        assert.equal(ctx.getWorkspacePresentationForNode({ family: 'mask', id: 'mask_threshold' }).opacity, 0.63);
    });
    await test('late old-case catalogue result cannot write into the new case', async () => {
        const ctx = makeContext();
        ctx.stageWorkspacePresentation(snapshot({ upload_a_label_2: { color: '#112233' } }), 'case-a');
        let resolve;
        ctx.window.fetchViewerJsonWithRetry = () => new Promise(done => { resolve = done; });
        const pending = ctx.hydrateGenericMasksFromServer({ sessionId: 'case-a', dataGeneration: 1 });
        ctx.activeSessionId = 'case-b';
        ctx.state = { sessionId: 'case-b', maskLabels: {} };
        assert.equal(ctx.getWorkspacePresentationForNode({ family: 'mask', id: 'upload_a_label_2' }), null);
        assert.equal(ctx.updateWorkspacePresentationForNode({ family: 'mask', id: 'upload_a_label_2' }, { color: '#ffffff' }), false);
        resolve({ response: { ok: true }, data: { masks: [serverMask('upload_a_label_2')], uploads: [] } });
        assert.equal(await pending, false);
        assert.equal(Object.keys(ctx.state.maskLabels).length, 0);
    });
    console.log(JSON.stringify({ passed, failed: failures.length, failures }));
    process.exitCode = failures.length ? 1 : 0;
})();
