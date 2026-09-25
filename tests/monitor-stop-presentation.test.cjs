const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');
const begin = source.indexOf('function setMonitorPresentation(');
const end = source.indexOf('\nwindow.setMonitorPresentation =', begin);
assert(begin >= 0 && end > begin);
const start = { disabled: false, setAttribute() {} };
const stop = { disabled: true, setAttribute() {} };
const label = { textContent: '', dataset: {} };
const status = { hidden: true, setAttribute() {}, querySelector: () => label };
const elements = { monitorStartButton: start, monitorStopButton: stop, monitorStatus: status };
const context = {
    document: {
        body: { classList: { toggle() {} }, dataset: {} },
        getElementById: id => elements[id] || null,
        querySelector: () => null,
    },
    monitorChatText: zh => zh,
    requestAnimationFrame: fn => fn(),
    setTimeout, clearTimeout,
};
vm.createContext(context);
vm.runInContext(source.slice(begin, end) + '\nthis.paint = setMonitorPresentation;', context);
context.paint('stop_error');
assert.equal(start.disabled, true, 'a new run must be blocked while stop is unconfirmed');
assert.equal(stop.disabled, false, 'Finish Monitor must remain retryable');
assert.equal(status.hidden, false, 'the unresolved state must be visible');
assert.match(label.textContent, /未确认/);
assert.match(label.dataset.i18nZh, /未确认/);
context.paint('inactive');
assert.equal(start.disabled, false);
assert.equal(stop.disabled, true);
console.log('Unconfirmed stop keeps status visible and Finish Monitor retryable.');
