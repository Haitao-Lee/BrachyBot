const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('function invalidateReportCapture()');
const end = source.indexOf('// Serialize report captures.', start);
const context = vm.createContext({window: {addEventListener() {}}, Date,
    dataTreeState: {planning: {status: 'completed', activePlanningId: 'plan1'}},
    _currentReportCaptureSessionId: () => 'session1', _reportCaptureGeneration: 0});
vm.runInContext(source.slice(start, end), context);
vm.runInContext(`
setReportPlanningLifecycle(true, {sessionId:'session1', requestId:'run1'});
`, context);
assert.equal(context._reportCaptureGeneration, 1);
assert.equal(vm.runInContext('reportCaptureAllowed().allowed', context), false);
assert.equal(vm.runInContext("reportCaptureAllowed({allowTerminalPlanning:true, planningId:'plan1'}).allowed", context), true);
vm.runInContext("setReportPlanningLifecycle(false, {sessionId:'session1', requestId:'run1'});", context);
assert.equal(context._reportCaptureGeneration, 1, 'completion must not cancel a terminal capture');
vm.runInContext("setReportPlanningLifecycle(false, {sessionId:'session1', requestId:'run1'});", context);
assert.equal(context._reportCaptureGeneration, 1, 'duplicate completion is idempotent');
vm.runInContext("setReportPlanningLifecycle(true, {sessionId:'session1', requestId:'run2'});", context);
assert.equal(context._reportCaptureGeneration, 2, 'replan cancels old capture');
assert.equal(vm.runInContext("reportCaptureAllowed({planningId:'plan0'}).allowed", context), false);
console.log('Report lifecycle race regression passed');
