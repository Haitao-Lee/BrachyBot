const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = process.argv[2] || path.resolve(__dirname, '../web/app/static/js');
const source = fs.readFileSync(process.argv[3] || path.join(root, 'brachybot-manual-annotation.js'), 'utf8');
const start = source.indexOf('async function runPlanningStep(step) {');
const end = source.indexOf('\nasync function showStepResults(', start);
assert(start >= 0 && end > start);

let sessionId = 'case-a';
let switchOnFetch = false;
let currentPanel = 'input';
let request = null;
let failFetch = false;
let failRefresh = false;
const trace = [];
const progress = {ctv_segmentation: true, trajectory_init: true, trajectory_refine: true,
    seed_planning: true, dose_calc: true};
const context = vm.createContext({
    document: {
        getElementById: id => id === 'ctPath' ? {value: '/owned/ct.nii.gz'} : null,
        querySelector: selector => selector === '.panel-tab.active'
            ? {dataset: {panel: currentPanel}}
            : selector.startsWith('.panel-tab[data-panel=') ? {dataset: {panel: selector.includes('metrics') ? 'metrics' : 'viewers'}}
                : null,
    },
    state: {ctLoaded: true},
    API: '/api',
    _activeApiSessionId: () => sessionId,
    _manualState: () => progress,
    _saveManualState: patch => Object.assign(progress, patch),
    _manualWorkflowLabel: (zh, en) => en,
    _manualWorkflowProgress: (step, status) => trace.push(['progress', step, status]),
    addChat: () => {},
    reportUIEvent: () => {},
    _invalidateDoseForPlanningRun: () => {},
    beginManualStepPresentation: () => {if (request) return null; trace.push(['begin']); return request = {owner: sessionId};},
    isCurrentManualStepRequest: token => request === token && token.owner === sessionId,
    finishManualStepPresentation: (token, committed) => {trace.push(['finish', committed]); if (request === token) request = null;},
    publishManualStepPresentation: (step, owner, visualization, outcome) => {
        trace.push(['publish', step, owner, visualization?.step, outcome.seedCount]);
        return true;
    },
    renderDataTree: () => {},
    refreshPlanningUI: async options => {
        assert.equal(options.preserveReport, true);
        assert.equal(options.suppressReportFigureCapture, true);
        trace.push(['refresh']); return {success: !failRefresh, seedCount: 24,
            manualStepCompletion: Promise.resolve({success: !failRefresh}),
            backgroundCompletion: new Promise(() => {}), // unrelated slow OAR must not block this step
        };
    },
    hydrateOarDataTreeFromServer: async () => {},
    scheduleWorkspaceSave: () => {},
    switchPanel: panel => {currentPanel = panel; trace.push(['panel', panel]);},
    fetch: async (_url, options) => {
        const step = JSON.parse(options.body).step;
        trace.push(['fetch', step]);
        if (failFetch) throw new Error('synthetic failure');
        if (switchOnFetch) sessionId = 'case-b';
        return {ok: true, json: async () => ({success: true, step,
            visualization: ['trajectory_init', 'trajectory_refine'].includes(step)
                ? {step, shown_trajectories: 3, trajectory_count: 3, close_point_count: 4,
                    geometry: {trajectories: [], close_points: []}}
                : null,
            metadata: {planning_projection: {seed_count: 24, has_dose: true}}})};
    },
});
vm.runInContext(source.slice(start, end), context);

(async () => {
    for (const step of ['trajectory_init', 'trajectory_refine', 'seed_planning', 'dose_calc', 'dose_eval']) {
        currentPanel = 'input';
        trace.length = 0;
        const result = await vm.runInContext(`runPlanningStep(${JSON.stringify(step)})`, context);
        assert.equal(result.success, true, step);
        assert.deepEqual(trace.filter(item => ['begin', 'fetch', 'refresh', 'publish'].includes(item[0])), [
            ['begin'], ['fetch', step], ['refresh'],
            ['publish', step, 'case-a', ['trajectory_init', 'trajectory_refine'].includes(step) ? step : undefined, 24],
        ], `${step} clears prior stage, refreshes official results and then publishes its own`);
        assert.equal(currentPanel, step === 'dose_eval' ? 'metrics' : 'viewers');
    }
    currentPanel = 'metrics';
    trace.length = 0;
    await vm.runInContext('runPlanningStep("trajectory_init")', context);
    assert.equal(trace.some(item => item[0] === 'panel'), false,
        'a tab the operator selected during the calculation stays selected');
    sessionId = 'case-a';
    switchOnFetch = true;
    trace.length = 0;
    const result = await vm.runInContext('runPlanningStep("trajectory_init")', context);
    assert.equal(result.success, true);
    assert.equal(result.detached, true);
    assert.equal(trace.filter(item => item[0] === 'publish').length, 0);
    switchOnFetch = false; sessionId = 'case-a'; failFetch = true; trace.length = 0;
    assert.equal((await vm.runInContext('runPlanningStep("trajectory_init")', context)).success, false);
    assert(trace.some(item => item[0] === 'finish' && item[1] === false));
    failFetch = false; failRefresh = true; trace.length = 0;
    const partial = await vm.runInContext('runPlanningStep("trajectory_init")', context);
    assert.equal(partial.success, false);
    assert.equal(partial.computationCompleted, true);
    assert(!trace.some(item => item[0] === 'progress' && item[2] === 'done'), 'no false visual completion');
    request = {}; trace.length = 0;
    assert.equal((await vm.runInContext('runPlanningStep("trajectory_init")', context)).success, false);
    assert(!trace.some(item => item[0] === 'fetch'), 'no duplicate clinical request');
    console.log('All five manual buttons publish after refresh, retire the previous stage, and fence case switches.');
})().catch(error => {console.error(error); process.exitCode = 1;});
