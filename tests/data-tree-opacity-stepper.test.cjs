const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const root = process.argv[2];
assert(root, 'pass the repository root');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const uiApiPath = fs.existsSync(path.join(root, 'web/app/static/js/brachybot-ui-api.js'))
    ? 'web/app/static/js/brachybot-ui-api.js' : 'brachybot-ui-api.js';
const viewerPath = fs.existsSync(path.join(root, 'web/app/static/js/brachybot-viewer-volume.js'))
    ? 'web/app/static/js/brachybot-viewer-volume.js' : 'brachybot-viewer-volume.js';
function topLevelFunction(source, declaration, nextDeclaration) {
    const start = source.indexOf(declaration);
    assert(start >= 0, `${declaration} exists`);
    const end = source.indexOf(nextDeclaration, start);
    assert(end >= 0, `${nextDeclaration} follows ${declaration}`);
    return source.slice(start, end).trim();
}

async function main() {
    const uiApi = read(uiApiPath);
    const viewer = read(viewerPath);

    // Stepper clicks are represented by the corresponding range input, not by
    // a second UI-click snapshot. Opacity range changes likewise use one
    // compact, debounced slider event; ordinary controls keep their telemetry.
    const handlers = {};
    const telemetry = [];
    const timers = new Map();
    let nextTimer = 1;
    const instrumentationContext = vm.createContext({
        window: {_brachyUiInstrumentationReady: false},
        document: {addEventListener: (name, callback) => { handlers[name] = callback; }},
        setTimeout: (callback, delay) => {
            const id = nextTimer++;
            timers.set(id, {callback, delay});
            return id;
        },
        clearTimeout: id => timers.delete(id),
        reportUIEvent: (...args) => telemetry.push(args),
    });
    vm.runInContext(topLevelFunction(uiApi, 'function instrumentUIControls() {', '\n(function installApiRequestFetchWrapper'), instrumentationContext);
    instrumentationContext.instrumentUIControls();

    const makeButton = stepper => ({
        disabled: false,
        className: stepper ? 'range-stepper-btn range-stepper-btn--increase' : 'ordinary-button',
        textContent: stepper ? '' : 'Run',
        id: stepper ? '' : 'runButton',
        matches: selector => stepper && selector === '.range-stepper-btn',
        getAttribute: () => null,
    });
    const click = button => handlers.click({
        target: {closest: selector => selector === 'button' ? button : null},
    });
    click(makeButton(true));
    assert.equal(telemetry.length, 0, 'stepper click is not double-recorded');
    click(makeButton(false));
    assert.equal(telemetry[0][0], 'ui.click', 'ordinary button telemetry remains active');

    const opacitySlider = {
        tagName: 'INPUT', type: 'range', id: 'upload_mask_label_2_opacity', value: '47',
        classList: {contains: name => name === 'opacity-slider'},
    };
    handlers.change({target: opacitySlider});
    assert.equal(telemetry.length, 1, 'opacity change does not serialize a duplicate snapshot');
    handlers.input({target: opacitySlider});
    const opacityTimer = [...timers.entries()][0];
    assert.equal(opacityTimer[1].delay, 400);
    timers.delete(opacityTimer[0]);
    opacityTimer[1].callback();
    assert.equal(telemetry[1][0], 'ui.slider');
    assert.deepEqual(
        JSON.parse(JSON.stringify(telemetry[1][3])),
        {omitUiState: true, skipWorkspaceSave: true},
    );

    const ordinarySelect = {tagName: 'SELECT', type: 'select-one', id: 'mode', value: 'auto'};
    handlers.change({target: ordinarySelect});
    assert.equal(telemetry[2][0], 'ui.change', 'ordinary change telemetry remains active');

    // The real reporter must honor the compact-event flags while ordinary
    // events continue to collect full UI state and schedule their normal save.
    const reportEventSource = topLevelFunction(uiApi, 'async function reportUIEvent(', '\nfunction _recordMonitorCaptureFailure');
    const requests = [];
    let stateCollectionCount = 0;
    let saves = 0;
    const reportContext = vm.createContext({
        window: {scheduleWorkspaceSave: () => { saves += 1; }},
        API: '/api',
        _activeApiSessionId: () => 'session-1',
        monitorConversationLanguage: () => 'en',
        trainingMonitorState: {runId: null, active: false},
        collectUIState: () => { stateCollectionCount += 1; return {uiProbe: true}; },
        _queueMonitorFeedback: () => false,
        _shouldLogTrainingFeedback: () => false,
        fetch: async (url, options) => {
            requests.push({url, body: JSON.parse(options.body)});
            return {json: async () => ({})};
        },
        console,
    });
    vm.runInContext(reportEventSource, reportContext);
    await reportContext.reportUIEvent('ui.slider', 'opacity', {value: '47'}, {
        omitUiState: true, skipWorkspaceSave: true,
    });
    assert.deepEqual(JSON.parse(JSON.stringify(requests[0].body.ui_state)), {});
    assert.equal(stateCollectionCount, 0);
    assert.equal(saves, 0, 'opacity handler already owns persistence');
    await reportContext.reportUIEvent('ui.change', 'mode', {value: 'auto'});
    assert.deepEqual(JSON.parse(JSON.stringify(requests[1].body.ui_state)), {uiProbe: true});
    assert.equal(stateCollectionCount, 1);
    assert.equal(saves, 1, 'ordinary events keep workspace-save behavior');

    // Leaf mask opacity updates its mesh immediately, keeps effective hidden
    // state, and defers the expensive all-slice redraw out of the click stack.
    const mask = {id: 'upload_mask_label_2', visible: true, opacity: 0.2};
    const viewerTimers = new Map();
    let nextViewerTimer = 1;
    let reloadCount = 0;
    let refreshCount = 0;
    let persisted = 0;
    const meshUpdates = [];
    const viewerContext = vm.createContext({
        state: {ctLoaded: true, maskLabels: {label2: mask}},
        scene3D: {meshes: {upload_mask_label_2: {}}},
        _maskStateEntry: () => mask,
        _maskSceneMeshId: () => 'upload_mask_label_2',
        _planningItems: () => [],
        _isDataTreeMaskId: () => true,
        _isGenericSegmentationMask: () => false,
        isDataTreeNodeVisible3D: () => false,
        applyMeshOpacity: (mesh, opacity, visible) => meshUpdates.push({mesh, opacity, visible}),
        reloadOverlays: () => { reloadCount += 1; },
        requestViewerVisualRefresh: () => { refreshCount += 1; },
        _scheduleDataTreeSave: () => { persisted += 1; },
        clearTimeout: id => viewerTimers.delete(id),
        setTimeout: (callback, delay) => {
            const id = nextViewerTimer++;
            viewerTimers.set(id, {callback, delay});
            return id;
        },
    });
    const helperStart = viewer.indexOf('let _opacityTimer = null;');
    const setterStart = viewer.indexOf('function setDataOpacity(id, value) {', helperStart);
    const setterEnd = viewer.indexOf('\nfunction selectDataItem(', setterStart);
    assert(helperStart >= 0 && setterStart > helperStart && setterEnd > setterStart);
    vm.runInContext(viewer.slice(helperStart, setterStart) + viewer.slice(setterStart, setterEnd), viewerContext);
    viewerContext.setDataOpacity('upload_mask_label_2', '47');
    assert.equal(mask.opacity, 0.47);
    assert.equal(meshUpdates.length, 1);
    assert.equal(meshUpdates[0].visible, false, 'opacity changes do not reveal a hidden node');
    assert.equal(reloadCount, 0, 'all-slice refresh is not synchronous with the stepper click');
    assert.equal(persisted, 1, 'the state change is still persisted');
    const redraw = [...viewerTimers.values()].find(timer => timer.delay === 80);
    assert(redraw, 'an 80 ms coalesced visual refresh is scheduled');
    redraw.callback();
    assert.equal(reloadCount, 1);
    assert.equal(refreshCount, 1);

    console.log('PASS: stepper opacity interaction avoids duplicate full-state telemetry and defers costly slice redraw while preserving values, hidden state, and persistence');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
