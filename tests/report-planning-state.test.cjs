const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = process.argv[2] || path.join(__dirname, '../web/app/static/js');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
function extract(source, name) {
    const start = source.indexOf(`function ${name}(`);
    assert(start >= 0, name);
    const end = source.indexOf('\n}', start);
    return source.slice(start, end + 2);
}
const context = vm.createContext({
    activeSessionId: 'case-test', state: {}, window: {},
    dataTreeState: {planning: {id: 'plan-test', activePlanningId: 'plan-test', status: 'completed'}},
    _reportPlanningLifecycle: {active: false},
});
vm.runInContext(extract(read('brachybot-viewer-volume.js'), 'ensureDataTreeNodeMetadata'), context);
vm.runInContext(extract(read('brachybot-report-editor.js'), 'reportCaptureAllowed'), context);
function check(status, loaded) {
    context.dataTreeState.planning.status = status;
    context.dataTreeState.planning.loaded = loaded;
    // Reproduce the tree repaint between planning/results and figure capture.
    vm.runInContext("ensureDataTreeNodeMetadata(dataTreeState.planning, 'planning')", context);
    assert.equal(context.dataTreeState.planning.status, status);
    return vm.runInContext("reportCaptureAllowed({planningId: 'plan-test'})", context);
}
for (const loaded of [true, false, undefined]) {
    assert.equal(check('completed', loaded).allowed, true);
    // A "draft" lifecycle is normal for a manually-adjusted plan whose dose is
    // already current; terminal states follow data readiness (the scene gate),
    // not a lifecycle word. Only a genuinely running Planning blocks capture.
    for (const status of ['draft', 'failed', 'interrupted', 'cancelled']) {
        assert.equal(check(status, loaded).allowed, true, status);
    }
    assert.equal(check('running', loaded).allowed, false);
}
context.dataTreeState.planning.status = 'running';
context._reportPlanningLifecycle.active = true;
assert.equal(vm.runInContext("reportCaptureAllowed({planningId: 'plan-test'})", context).reason, 'planning_in_progress');
context._reportPlanningLifecycle.active = false;
assert.equal(vm.runInContext("reportCaptureAllowed({planningId: 'plan-test'})", context).reason, 'planning_not_completed');
context.dataTreeState.planning.status = 'completed';
assert.equal(vm.runInContext("reportCaptureAllowed({planningId: 'other'})", context).reason, 'planning_changed');
assert.equal(vm.runInContext("ensureDataTreeNodeMetadata({loaded:true}, 'oar_mask').status", context), 'ready');
console.log('PASS: tree repaint preserves Planning lifecycle; only running and switched plans remain blocked');
