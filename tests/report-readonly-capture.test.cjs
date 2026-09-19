const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = process.argv[2] || path.join(__dirname, '../web/app/static/js');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
function extract(source, name, async = false) {
    const start = source.indexOf((async ? 'async ' : '') + 'function ' + name + '(');
    assert(start >= 0, name);
    return source.slice(start, source.indexOf('\n}', start) + 2);
}
const api = read('brachybot-ui-api.js');
const editor = read('brachybot-report-editor.js');
const volume = read('brachybot-viewer-volume.js');
async function main() {
    let sid = 'case';
    let catalog = {success: true, active_planning_id: 'plan',
        runs: [{planning_id: 'plan', status: 'completed', data_version: 4}]};
    let httpStatus = 200;
    let failNetwork = false;
    const material = {opacity: 0.4, transparent: true, depthTest: true, depthWrite: false};
    const mesh = {visible: true, renderOrder: 1, material,
        traverse(fn) { fn(this); }};
    const context = vm.createContext({
        window: {}, API: '/api', AbortController, setTimeout, clearTimeout,
        console, _activeApiSessionId: () => sid,
        _reportCaptureAwait: async operation => operation(),
        REPORT_CAPTURE_STEP_TOTAL: 7, REPORT_CAPTURE_TOTAL_TIMEOUT_MS: 180000,
        _reportCaptureUiStart: () => 1,
        _planningRunHeaders: session => ({'X-Session-ID': session}),
        state: {slices: {axial: 8, sagittal: 9, coronal: 10},
            doseOverlay: {shape: [20, 20, 20], visible: false},
            doseTexture: {enabled: true}},
        dataTreeState: {planning: {id: 'plan', activePlanningId: 'plan',
            status: 'completed', dataVersion: 4}},
        scene3D: {renderer: {}, meshes: {ctv: mesh}, requestRender() {}},
        fetch: async (url, opts) => {
            assert.equal(url, '/api/planning/runs');
            assert.equal(opts.headers['X-Session-ID'], 'case');
            if (failNetwork) throw Error('offline');
            return {ok: true, status: httpStatus, json: async () => catalog};
        },
        document: {getElementById: () => null},
        _currentReportCaptureSessionId: () => sid,
        _currentReportCapturePlanningId: () => 'plan',
    });
    context.setDoseTextureMode = async enabled => {
        context.state.doseTexture.enabled = enabled;
        return {success: true, enabled};
    };
    context.updateSlice = (axis, slice) => {context.state.slices[axis] = slice;};
    vm.runInContext(extract(api, 'prepareReportSceneRead', true), context);
    const prepare = () => vm.runInContext("prepareReportSceneRead('case')", context);
    const before = JSON.stringify({state: context.state, tree: context.dataTreeState});
    assert.equal((await prepare()).success, true);
    assert.equal(JSON.stringify({state: context.state, tree: context.dataTreeState}), before);
    catalog.runs[0].status = 'running';
    assert.equal((await prepare()).stage, 'report_planning_in_progress');
    catalog.runs[0].status = 'completed';
    context.window.__brachybotPlanningRunActive = true;
    assert.equal((await prepare()).success, false);
    context.window.__brachybotPlanningRunActive = false;
    catalog.runs[0].data_version = 5;
    assert.equal((await prepare()).stage, 'report_planning_changed');
    catalog.runs[0].data_version = 4;
    httpStatus = 202;
    assert.equal((await prepare()).stage, 'report_catalog_not_ready');
    httpStatus = 200;
    failNetwork = true;
    assert.equal((await prepare()).stage, 'report_validation_failed');
    failNetwork = false;
    assert.equal(JSON.stringify({state: context.state, tree: context.dataTreeState}), before);
    assert.equal(context.scene3D.meshes.ctv, mesh);

    // Execute the same restoration transaction after a simulated capture error.
    vm.runInContext(extract(editor, 'hideReportUploadMasks'), context);
    const upload = {kind: 'uploaded_mask_label', visible: true, visible2D: false};
    const promoted = {kind: 'uploaded_mask_label', classification: 'ctv', visible: true};
    const group = {visible: true};
    context.state.maskLabels = {upload, promoted};
    context.dataTreeState.uploadMasks = [group];
    const uploadMesh = {visible: true, traverse(fn) { fn(this); }};
    context.scene3D.meshes.upload = uploadMesh;
    vm.runInContext(extract(editor, 'snapshotReportViewerPresentation'), context);
    const restore = vm.runInContext('snapshotReportViewerPresentation()', context);
    vm.runInContext('hideReportUploadMasks()', context);
    assert.equal(upload.visible, false);
    assert.equal(upload.visible3D, false);
    assert.equal(uploadMesh.visible, false);
    assert.equal(group.visible, false);
    assert.equal(promoted.visible, true);
    mesh.visible = false;
    material.opacity = 0;
    context.state.slices.axial = 19;
    context.state.doseOverlay.visible = true;
    context.state.doseTexture.enabled = false;
    await restore();
    assert.equal(upload.visible, true);
    assert.equal(upload.visible2D, false);
    assert.equal(Object.hasOwn(upload, 'visible3D'), false);
    assert.equal(uploadMesh.visible, true);
    assert.equal(group.visible, true);
    assert.equal(mesh.visible, true);
    assert.equal(material.opacity, 0.4);
    assert.equal(context.state.slices.axial, 8);
    assert.equal(context.state.doseOverlay.visible, false);
    assert.equal(context.state.doseTexture.enabled, true);
    sid = 'other';
    mesh.visible = false;
    await restore();
    assert.equal(mesh.visible, false, 'must not mutate a newly selected case');

    // Exercise the real async capture wrapper, not just its restore helper.
    sid = 'case';
    mesh.visible = true;
    Object.assign(context, {
        _reportCapturePromise: null, _reportCaptureGeneration: 1,
        reportCaptureAllowed: () => ({allowed: true}),
        _reportCaptureUiFinish() {}, uiDebugLog() {},
        prepareReportCaptureLayout: () => () => {},
        _reportDvhWaitForPaint: async () => {},
        _autoCaptureReportFiguresImpl: async () => {
            assert.equal(upload.visible, false);
            assert.equal(uploadMesh.visible, false);
            mesh.visible = false;
            material.opacity = 0;
            context.state.slices.axial = 19;
            throw Error('simulated WebGL readback failure');
        },
    });
    context.window.reportForm = {figures: [{axis: 'previous'}]};
    vm.runInContext(extract(editor, 'autoCaptureReportFigures', true), context);
    await assert.rejects(vm.runInContext('autoCaptureReportFigures()', context),
        /simulated WebGL readback failure/);
    assert.equal(mesh.visible, true);
    assert.equal(material.opacity, 0.4);
    assert.equal(context.state.slices.axial, 8);
    assert.equal(context.window.__reportCaptureActive, false);
    assert.equal(context._reportCapturePromise, null);
    assert.equal(context.window.reportForm.figures[0].axis, 'previous');
    assert.equal(upload.visible, true, 'capture failure restores Upload Mask');
    assert.equal(uploadMesh.visible, true);

    // Background tree and health repairs must not overwrite a capture profile.
    context.window.__reportCaptureActive = true;
    context._allDataTreeVisualNodes = () => {throw Error('unexpected tree rewrite');};
    vm.runInContext(extract(volume, '_apply3DNodeVisibility'), context);
    vm.runInContext("_apply3DNodeVisibility({id:'ctv'})", context);
    vm.runInContext(extract(read('brachybot-3d-manual.js'), '_repair3DSceneVisibility'), context);
    assert.equal(vm.runInContext('_repair3DSceneVisibility()', context), false);

    // Wiring contracts supplement the behavioral tests above.
    const action = api.slice(api.indexOf("if (target === 'report.autofill')"),
        api.indexOf("if (target === 'report.export')"));
    assert(!action.includes('refreshPlanningUI('), 'report cannot rebuild live scene');
    assert(action.includes('prepareReportSceneReadWithRetry(reportSessionId,'));
    assert(api.includes('last = await prepareReportSceneRead(sessionId)'));
    assert(editor.includes('doseSlicesReady.some(ready => ready !== true)'));
    const commit = editor.indexOf('window.reportForm.figures = (window.reportForm.figures');
    assert(editor.indexOf('if (missingAxes.length)') < commit);
    assert(editor.includes('preserveDoseTexture: !!state.doseTexture?.enabled'));
    console.log('PASS: read-only report checks, version/running/pending/offline failures, exact presentation restore, case isolation, capture guards and atomic figure publication');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
