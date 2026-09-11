const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = process.argv[2] || path.join(__dirname, '../web/app/static/js');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const api = read('brachybot-ui-api.js');
const workspace = read('brachybot-workspace.js');
function extract(source, name) {
    const start = source.indexOf('function ' + name + '(');
    assert(start >= 0, name);
    return source.slice(start, source.indexOf('\n}', start) + 2);
}
const deferred = () => {
    let resolve;
    const promise = new Promise(r => {resolve = r;});
    return {promise, resolve};
};
async function main() {
    let calls = 0;
    const core = deferred();
    const visual = deferred();
    const timers = [];
    const store = {case: {promise: visual.promise}};
    const ctx = vm.createContext({
        window: {}, _activeApiSessionId: () => 'case',
        _workspaceVisualReadinessStore: () => store,
        _runWorkspaceRestoreTransaction: () => {calls++; return core.promise;},
        setTimeout: fn => {timers.push(fn); return timers.length;},
        clearTimeout() {}, Date, console,
    });
    vm.runInContext('let _workspaceRestoreTransaction = null;\n'
        + extract(api, 'restoreActiveSessionWorkspace'), ctx);
    const first = vm.runInContext('restoreActiveSessionWorkspace()', ctx);
    const duplicate = vm.runInContext('restoreActiveSessionWorkspace()', ctx);
    assert.equal(first, duplicate, 'duplicate startup must share the same core load');
    await Promise.resolve();
    assert.equal(calls, 1);
    core.resolve({success: true});
    await first;
    const duringMeshes = vm.runInContext('restoreActiveSessionWorkspace()', ctx);
    assert.equal(duringMeshes, first, 'dedupe must extend beyond core to visual completion');
    assert.equal(calls, 1);

    const start = api.indexOf('window.awaitWorkspaceVisualReady = async function');
    const end = api.indexOf('\n};', start);
    vm.runInContext(api.slice(start, end + 3), ctx);
    let schedulerFinished = false;
    const scheduler = ctx.window.awaitWorkspaceVisualReady('case', {waitForCompletion: true})
        .then(result => {schedulerFinished = true; return result;});
    const bounded = ctx.window.awaitWorkspaceVisualReady('case', {timeoutMs: 1});
    timers.forEach(fn => fn());
    assert.equal((await bounded).ready, false);
    assert.equal(schedulerFinished, false, 'caller timeout is not a failed resource producer');
    assert.equal(calls, 1);
    visual.resolve({ready: true});
    assert.equal((await scheduler).ready, true);

    const planningRestore = api.slice(api.indexOf('const planningTask = ('),
        api.indexOf('// A segmentation-only case'));
    assert(planningRestore.includes('autoGenerateGuide: false'));
    assert(planningRestore.includes('suppressReportFigureCapture: true'));
    assert(planningRestore.includes('captureReportFigures: false'));
    assert(workspace.includes('waitForCompletion: true'));
    assert(workspace.includes('error.visualRestoreFailure !== true'));
    assert(workspace.includes("(typeof state === 'undefined' || state.ctLoaded !== true)"));
    assert(workspace.includes("typeof state !== 'undefined' && state.ctLoaded === true) return"));
    assert(api.includes('ready: failedCount === 0'));
    console.log('PASS: shared restore survives core completion and caller timeout; cold restore does not capture reports or generate guides; failed visual producers are not reported ready');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
