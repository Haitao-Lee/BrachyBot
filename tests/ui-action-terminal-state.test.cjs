// Correct-behaviour contract for UI-action completion, dependency gating and
// overlay opacity.  These started as counterexamples R02/R06/R07 in
// docs/audits/nl-ui-parity-review-20260928/.  They load the production
// functions rather than a re-implementation, so a green run means the browser
// bundle really behaves this way.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert');

const ROOT = process.argv[2] || path.resolve(__dirname, '..');
const SRC = fs.readFileSync(path.join(ROOT, 'web/app/static/js/brachybot-ui-api.js'), 'utf8');

function slice(startMarker, endMarker) {
    const start = SRC.indexOf(startMarker);
    assert.ok(start >= 0, `missing ${startMarker}`);
    const end = SRC.indexOf(endMarker, start);
    assert.ok(end > start, `missing ${endMarker}`);
    return SRC.slice(start, end);
}
function fn(name, { async = false } = {}) {
    const marker = `${async ? 'async ' : ''}function ${name}(`;
    const start = SRC.indexOf(marker);
    assert.ok(start >= 0, `missing ${name}`);
    return SRC.slice(start, SRC.indexOf('\n}', start) + 2);
}
// The terminal-state classifier and the owner ledger are shared code.  The
// whole block is loaded together so the executor sees exactly the helpers the
// browser bundle gives it.
const CLASSIFIERS = slice('const _UI_ACTION_RUNNING_STATES', 'function _emitUIActionProgress');
const EXECUTOR = fn('_executeUIActionsWithProgress', { async: true });

function executorContext(impl) {
    const events = [];
    const executed = [];
    const ctx = {
        window: {},
        Date,
        Promise,
        setTimeout,
        console,
        _uiActionSessionIsCurrent: () => true,
        _activeApiSessionId: () => 'case',
        _emitUIActionProgress: (e) => events.push(e),
        _executeUIAction: async (a) => {
            executed.push(a.key || a.target);
            return impl(a);
        },
    };
    vm.createContext(ctx);
    vm.runInContext(`${CLASSIFIERS}\n${EXECUTOR}\n`, ctx);
    return { ctx, events, executed };
}
const run = (ctx, actions, options) => ctx._executeUIActionsWithProgress(actions, options);

const checks = [];
const test = (name, body) => checks.push({ name, body });

// --------------------------------------------------------------------------
// R02 - JobRef / dispatch is acceptance, never business completion.
// --------------------------------------------------------------------------
test('R02 a JobRef handler result is not a completion', () => {
    const { ctx } = executorContext(() => ({ success: true, completed: false, status: 'running', job_id: 'job-1' }));
    assert.strictEqual(ctx._uiActionResultState({ success: true, completed: false, status: 'running', job_id: 'job-1' }), 'running');
    assert.strictEqual(ctx._uiActionResultState({ success: true, job_id: 'job-1' }), 'running');
    assert.strictEqual(ctx._uiActionResultState({ success: true, dispatched: true }), 'dispatched');
    assert.strictEqual(ctx._uiActionResultState({ success: true, completed: false }), 'running');
    assert.strictEqual(ctx._uiActionResultState({ success: true, completed: true }), 'completed');
    assert.strictEqual(ctx._uiActionResultState({ success: true, message: 'ok' }), 'completed');
    assert.strictEqual(ctx._uiActionResultState({ success: false, error: 'x' }), 'failed');
    assert.strictEqual(ctx._uiActionResultState(false), 'failed');
});

test('R02 an incomplete receipt never reads as pending->done', async () => {
    const t = executorContext(() => ({ success: true, completed: false, dispatched: true }));
    await run(t.ctx, [{ key: 'pending', target: 'fixture', command: 'run' }], { sessionId: 'case' });
    const statuses = t.events.map((e) => e.status);
    assert.deepStrictEqual(statuses, ['pending', 'running'], `got ${JSON.stringify(statuses)}`);
    assert.ok(!statuses.includes('done'), 'an accepted job must not report done');
});

test('R02 a completed receipt still reports done', async () => {
    const t = executorContext(() => ({ success: true, completed: true, message: 'applied' }));
    await run(t.ctx, [{ key: 'ok', target: 'fixture' }], { sessionId: 'case' });
    assert.deepStrictEqual(t.events.map((e) => e.status), ['pending', 'done']);
});

test('R02 a queued job is not upgraded to completed by the control receipt', async () => {
    const el = {
        id: 'fixture', tagName: 'BUTTON', type: 'button', disabled: false,
        getAttribute: (k) => (k === 'onclick' ? 'queuedJob()' : null),
        click: () => {}, dispatchEvent: () => {},
    };
    const ctx = {
        window: {
            queuedJob: async () => ({ success: true, completed: false, status: 'running', job_id: 'job-1' }),
        },
        console,
        _parseUIControlPayload: (x) => x,
        _resolveUIControlElement: () => el,
        _uiOperationLabel: () => 'fixture',
        _uiOperationVisible: () => true,
        reportUIEvent: () => {},
        syncUIBridgeState: () => {},
    };
    vm.createContext(ctx);
    vm.runInContext(
        `${CLASSIFIERS}\n${SRC.slice(SRC.indexOf('async function executeGenericUIControl('), SRC.indexOf('\nfunction instrumentUIControls('))}`,
        ctx,
    );
    const receipt = await ctx.executeGenericUIControl('click', {});
    assert.strictEqual(receipt.completed, false, 'a running job must not read as completed');
    assert.strictEqual(receipt.status, 'running');
    assert.strictEqual(receipt.dispatched, true, 'dispatch is still a true claim');
    assert.strictEqual(ctx._uiActionResultState(receipt), 'running');
});

// --------------------------------------------------------------------------
// R07 - dependencies are gated by a ledger that outlives one batch, and an
// aborted request never reaches the business layer.
// --------------------------------------------------------------------------
test('R07 a producer that failed in an earlier batch still blocks its consumer', async () => {
    const t = executorContext((a) => ({ success: a.key !== 'producer' }));
    await run(t.ctx, [{ key: 'producer', target: 'fixture' }], { sessionId: 'case' });
    await run(t.ctx, [{ key: 'consumer', target: 'fixture', depends_on: ['producer'] }], { sessionId: 'case' });
    assert.deepStrictEqual(t.executed, ['producer'], `executed ${JSON.stringify(t.executed)}`);
});

test('R07 an unknown prerequisite is unmet, never assumed successful', async () => {
    const t = executorContext(() => ({ success: true }));
    await run(t.ctx, [{ key: 'consumer', target: 'fixture', depends_on: ['missing'] }], { sessionId: 'case' });
    assert.deepStrictEqual(t.executed, [], `executed ${JSON.stringify(t.executed)}`);
});

test('R07 an aborted request runs nothing', async () => {
    const t = executorContext(() => ({ success: true }));
    await run(t.ctx, [{ key: 'consumer', target: 'fixture' }], { sessionId: 'case', signal: { aborted: true } });
    assert.deepStrictEqual(t.executed, [], `executed ${JSON.stringify(t.executed)}`);
});

test('R07 an accepted prerequisite does not release its consumer', async () => {
    const t = executorContext(() => ({ success: true, completed: false, dispatched: true }));
    await run(t.ctx, [
        { key: 'producer', target: 'fixture' },
        { key: 'consumer', target: 'fixture', depends_on: ['producer'] },
    ], { sessionId: 'case' });
    assert.deepStrictEqual(t.executed, ['producer'], `executed ${JSON.stringify(t.executed)}`);
});

test('R07 an independent step still runs after a failure', async () => {
    const t = executorContext((a) => ({ success: a.key !== 'bad' }));
    await run(t.ctx, [
        { key: 'bad', target: 'fixture' },
        { key: 'free', target: 'fixture' },
        { key: 'held', target: 'fixture', depends_on: ['bad'] },
    ], { sessionId: 'case' });
    assert.deepStrictEqual(t.executed, ['bad', 'free']);
});

test('R02 a session switch makes the action fail rather than succeed silently', async () => {
    // A report action whose case changed underneath it must read as a failure:
    // the screenshot/report transaction belongs to the old case.
    let current = true;
    const events = [];
    const executed = [];
    const ctx = {
        window: {}, Date, Promise, setTimeout, console,
        _uiActionSessionIsCurrent: () => current,
        _activeApiSessionId: () => 'case',
        _emitUIActionProgress: (e) => events.push(e),
        _executeUIAction: async (a) => {
            executed.push(a.key);
            current = false;
            return { success: true, message: 'applied' };
        },
    };
    vm.createContext(ctx);
    vm.runInContext(`${CLASSIFIERS}\n${EXECUTOR}\n`, ctx);
    const results = await ctx._executeUIActionsWithProgress(
        [{ key: 'report', target: 'report', command: 'run' }, { key: 'after', target: 'fixture' }],
        { sessionId: 'case' },
    );
    assert.strictEqual(results[0].stale, true, `got ${JSON.stringify(results[0])}`);
    assert.strictEqual(ctx._uiActionResultState(results[0]), 'stale');
    assert.ok(!executed.includes('after'), 'no action may run without an owner');
});

// --------------------------------------------------------------------------
// R06 - a missing value is missing, not a real 0, and a relative opacity
// never guesses a base.
// --------------------------------------------------------------------------
function opacityContext(scaffold) {
    const ctx = { console, ...scaffold };
    vm.createContext(ctx);
    vm.runInContext(`${fn('_overlayOpacityFraction')}\n${fn('_resolveOverlayOpacityPercent')}\n`, ctx);
    return ctx;
}

test('R06 a missing overlay object falls back to the effective opacity', () => {
    // `Number(null)` is 0: reading the absent overlay as a real 0% base is
    // what turned "increase 10" into 10% instead of 70%.
    const ctx = opacityContext({ state: { doseOpacity: 0.6 } });
    assert.strictEqual(ctx._overlayOpacityFraction('overlay.dose.opacity'), 0.6);
    const resolved = ctx._resolveOverlayOpacityPercent('overlay.dose.opacity', 'increase', 10);
    assert.strictEqual(resolved.percent, 70, JSON.stringify(resolved));
    assert.strictEqual(resolved.base, 60);
});

test('R06 a blank value is missing rather than 0', () => {
    const ctx = opacityContext({ state: { doseOpacity: '' } });
    assert.strictEqual(ctx._overlayOpacityFraction('overlay.dose.opacity'), null);
    const resolved = ctx._resolveOverlayOpacityPercent('overlay.dose.opacity', 'increase', 10);
    assert.ok(resolved.error, 'a relative change without a base must be refused');
});

test('R06 an overlay value wins over the stale fallback', () => {
    const ctx = opacityContext({ state: { doseOpacity: 0.6, doseOverlay: { opacity: 0.4 } } });
    assert.strictEqual(ctx._overlayOpacityFraction('overlay.dose.opacity'), 0.4);
});

test('R06 a group whose members disagree refuses a relative change', () => {
    const ctx = opacityContext({
        dataTreeState: { organs: [{ opacity: 0.2 }, { opacity: 0.8 }] },
    });
    assert.strictEqual(ctx._overlayOpacityFraction('overlay.oar.opacity'), null);
    const resolved = ctx._resolveOverlayOpacityPercent('overlay.oar.opacity', 'increase', 10);
    assert.ok(resolved.error, 'a divergent group must not silently take the first member');
});

test('R06 a uniform group is a usable base', () => {
    const ctx = opacityContext({
        dataTreeState: { organs: [{ opacity: 0.5 }, { opacity: 0.5 }] },
    });
    const resolved = ctx._resolveOverlayOpacityPercent('overlay.oar.opacity', 'increase', 10);
    assert.strictEqual(resolved.percent, 60, JSON.stringify(resolved));
});

(async () => {
    let failed = 0;
    for (const { name, body } of checks) {
        try {
            await body();
            console.log(`ok   ${name}`);
        } catch (error) {
            failed += 1;
            console.log(`FAIL ${name}`);
            console.log(`     ${error && error.message}`);
        }
    }
    console.log(`${checks.length - failed}/${checks.length} passed`);
    if (failed) process.exitCode = 1;
})();
