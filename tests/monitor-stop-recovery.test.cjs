const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');
const begin = source.indexOf('async function stopTrainingMode()');
const end = source.indexOf('\nfunction _formatAdviceReport(', begin);
assert(begin >= 0 && end > begin);

function harness(responses, status = { success: true, active: true, monitor_run_id: 'a' }) {
    const messages = [];
    const state = {
        phase: 'active', active: true, runId: 'a', sessionId: 'case',
        language: 'zh', screenshotGalleryContext: { items: [] }, pendingFeedback: [],
    };
    const window = {
        setTrainingMonitorPhase: phase => { state.phase = phase; state.active = phase === 'active'; },
    };
    const context = {
        window, trainingMonitorState: state, API: '/api',
        _activeApiSessionId: () => 'case', _monitorRequestHeaders: () => ({}),
        _readTrainingMonitorStatus: async () => status,
        _showRecoveredMonitorSummary: () => true,
        _inputButtonProgress: () => {}, _manualErrorDetail: e => e.message,
        _manualText: (zh, en) => zh, _flushMonitorFeedback: () => {},
        _clearMonitorFeedbackTimer: () => {},
        clearTrainingMonitorLocal: () => {
            state.phase = 'inactive'; state.active = false; state.runId = null;
        },
        addChat: (...args) => messages.push(args),
        fetch: async () => {
            const next = responses.shift();
            if (next instanceof Error) throw next;
            return { ok: true, status: 200, json: async () => next };
        },
        setTimeout, clearTimeout, AbortController,
    };
    vm.createContext(context);
    vm.runInContext(source.slice(begin, end) + '\nthis.stop = stopTrainingMode;', context);
    return { state, messages, stop: context.stop };
}

(async () => {
    const timeout = new Error('aborted'); timeout.name = 'AbortError';
    const first = harness([timeout, { success: true, summary: 'Done', advice: {} }]);
    const uncertain = await first.stop();
    assert.equal(uncertain.success, false);
    assert.equal(first.state.phase, 'stop_error');
    assert.equal(first.state.runId, 'a', 'an unacknowledged stop must retain its lease ID');
    await first.stop();
    assert.equal(first.state.phase, 'inactive');
    assert.equal(first.state.runId, null);

    const second = harness([
        { success: true, run_mismatch: true, no_active_run: false, active_monitor_run_id: 'b' },
        { success: true, summary: 'Done', advice: {} },
    ]);
    const mismatch = await second.stop();
    assert.equal(mismatch.run_mismatch, true);
    assert.equal(second.state.phase, 'stop_error');
    assert.equal(second.state.runId, 'b', 'retry must target the actual server run');
    await second.stop();
    assert.equal(second.state.phase, 'inactive');

    const third = harness([{ success: true, already_stopped: true, no_active_run: true }],
        { success: true, active: true, monitor_run_id: 'a' });
    third.state.phase = 'inactive'; third.state.runId = null;
    await third.stop();
    assert.equal(third.state.phase, 'inactive', 'explicit stop must consult and close a server-only run');
    console.log('Monitor timeout, mismatch, retry, and server-only stop recovery passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
