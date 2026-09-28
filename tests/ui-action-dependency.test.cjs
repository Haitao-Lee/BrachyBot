// Task dependency isolation and batch serialization (audit defect F12).
//
// One failing UI action used to stop every later action in the same batch,
// including independent ones, and every batch of a turn started concurrently
// so two of them could touch the same Viewer and the same workspace save.
// A failure now blocks only its dependants; a batch is queued behind the
// previous one for the same owner session.
//
// Runs the production functions against inert mocks. Never contacts a server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = process.argv[2] || path.join(__dirname, '..', 'web', 'app', 'static', 'js');
const src = fs.readFileSync(path.join(root, 'brachybot-ui-api.js'), 'utf8');

function extract(source, name, isAsync = false) {
    const start = source.indexOf(`${isAsync ? 'async ' : ''}function ${name}(`);
    assert.ok(start >= 0, `could not locate ${name}`);
    return source.slice(start, source.indexOf('\n}', start) + 2);
}

// The executor reads the shared terminal-state classifier and owner ledger
// (audit R02/R07); load them into the same script scope it runs in.
const classifiersSrc = src.slice(
    src.indexOf('const _UI_ACTION_RUNNING_STATES'),
    src.indexOf('function _emitUIActionProgress'),
);
assert.ok(classifiersSrc.includes('_uiActionResultState'));
const progressSrc = extract(src, '_executeUIActionsWithProgress', true);
const queueSrc = extract(src, '_queueUIActionBatch', true);

function makeContext(executeImpl) {
    const events = [];
    const context = {
        window: {},
        Date,
        Promise,
        setTimeout,
        console,
        _uiActionSessionIsCurrent: () => true,
        _activeApiSessionId: () => 'case',
        _emitUIActionProgress: step => events.push(step),
        _executeUIAction: executeImpl,
    };
    vm.createContext(context);
    vm.runInContext(`${classifiersSrc}\n${progressSrc}\n`, context);
    return { context, events };
}

async function main() {
    // ------------------------------------------------------------------
    // An independent action still runs after a sibling fails
    // ------------------------------------------------------------------
    {
        const executed = [];
        const { context, events } = makeContext(async action => {
            executed.push(action.target);
            return action.target === 'first'
                ? { success: false, error: 'test_failure' }
                : { success: true };
        });
        const outcome = await context._executeUIActionsWithProgress(
            [
                { key: 'a', target: 'first', command: 'run' },
                { key: 'b', target: 'independent_second', command: 'run' },
            ],
            { sessionId: 'case' },
        );
        assert.deepEqual(Array.from(executed), ['first', 'independent_second'],
            'an independent action must not be punished for a sibling failure');
        assert.equal(outcome.length, 2);
        assert.equal(outcome[0].success, false);
        assert.equal(outcome[1].success, true);
        const errorStep = events.find(step => step.status === 'error');
        assert.ok(errorStep, 'the failure is still reported');
    }

    // ------------------------------------------------------------------
    // A dependent action is skipped with a reason when its prerequisite failed
    // ------------------------------------------------------------------
    {
        const executed = [];
        const { context, events } = makeContext(async action => {
            executed.push(action.target);
            return action.target === 'produce'
                ? { success: false, error: 'producer_broke' }
                : { success: true };
        });
        const outcome = await context._executeUIActionsWithProgress(
            [
                { key: 'produce', target: 'produce', command: 'run' },
                { key: 'consume', target: 'consume', command: 'run', depends_on: ['produce'] },
            ],
            { sessionId: 'case' },
        );
        assert.deepEqual(Array.from(executed), ['produce'],
            'a dependant of a failed step must not run');
        assert.equal(outcome.length, 2, 'a skipped step is still accounted for');
        assert.equal(outcome[1].success, false);
        assert.equal(outcome[1].skipped, true);
        assert.deepEqual(Array.from(outcome[1].blocked_by_dependency), ['produce']);
        assert.match(String(outcome[1].error), /produce/);
        const blocked = events.find(step => step.metadata?.blockedByDependency);
        assert.ok(blocked, 'the trace records why the step was skipped');
    }

    // ------------------------------------------------------------------
    // A dependent action runs when its prerequisite succeeded
    // ------------------------------------------------------------------
    {
        const executed = [];
        const { context } = makeContext(async action => {
            executed.push(action.target);
            return { success: true };
        });
        const outcome = await context._executeUIActionsWithProgress(
            [
                { key: 'produce', target: 'produce', command: 'run' },
                { key: 'consume', target: 'consume', command: 'run', dependsOn: ['produce'] },
            ],
            { sessionId: 'case' },
        );
        assert.deepEqual(Array.from(executed), ['produce', 'consume']);
        assert.ok(outcome.every(result => result.success === true));
    }

    // ------------------------------------------------------------------
    // Transitive blocking: a chain stops at the first failure only
    // ------------------------------------------------------------------
    {
        const executed = [];
        const { context } = makeContext(async action => {
            executed.push(action.target);
            return action.target === 'a' ? { success: false, error: 'x' } : { success: true };
        });
        const outcome = await context._executeUIActionsWithProgress(
            [
                { key: 'a', target: 'a', command: 'run' },
                { key: 'b', target: 'b', command: 'run', depends_on: ['a'] },
                { key: 'c', target: 'c', command: 'run', depends_on: ['b'] },
                { key: 'd', target: 'd', command: 'run' },
            ],
            { sessionId: 'case' },
        );
        assert.deepEqual(Array.from(executed), ['a', 'd'], 'only the independent tail still runs');
        assert.deepEqual(Array.from(outcome, result => result.success), [false, false, false, true]);
        assert.equal(Array.from(outcome[2].blocked_by_dependency).join(','), 'b',
            'a transitive dependant names the step that actually blocked it');
    }

    // ------------------------------------------------------------------
    // Repeated tools keep distinct step identities
    // ------------------------------------------------------------------
    {
        const executed = [];
        const { context } = makeContext(async (action, options) => {
            executed.push(action.value);
            return { success: true };
        });
        await context._executeUIActionsWithProgress(
            [
                { key: 'dose-1', target: 'dose_recompute', command: 'run', value: 1 },
                { key: 'dose-2', target: 'dose_recompute', command: 'run', value: 2, depends_on: ['dose-1'] },
            ],
            { sessionId: 'case' },
        );
        assert.deepEqual(Array.from(executed), [1, 2]);
    }

    // Unnamed steps fall back to positional identity and never block each other.
    {
        const executed = [];
        const { context } = makeContext(async action => {
            executed.push(action.target);
            return action.target === 'first' ? { success: false, error: 'x' } : { success: true };
        });
        const outcome = await context._executeUIActionsWithProgress(
            [
                { target: 'first', command: 'run' },
                { target: 'second', command: 'run' },
            ],
            { sessionId: 'case' },
        );
        assert.deepEqual(Array.from(executed), ['first', 'second']);
        assert.equal(outcome[1].success, true);
    }

    // ------------------------------------------------------------------
    // Global aborts still stop the batch: a case switch is not a local failure
    // ------------------------------------------------------------------
    {
        let current = true;
        const executed = [];
        const { context, events } = makeContext(async action => {
            executed.push(action.target);
            current = false;
            return { success: true };
        });
        context._uiActionSessionIsCurrent = () => current;
        const outcome = await context._executeUIActionsWithProgress(
            [
                { target: 'first', command: 'run' },
                { target: 'second', command: 'run' },
            ],
            { sessionId: 'case' },
        );
        assert.deepEqual(Array.from(executed), ['first']);
        assert.equal(outcome[0].stale, true);
        assert.equal(events.at(-1).status, 'cancelled');
    }

    {
        const executed = [];
        const { context } = makeContext(async action => {
            executed.push(action.target);
            return { success: true, cancelled: true };
        });
        const outcome = await context._executeUIActionsWithProgress(
            [
                { target: 'first', command: 'run' },
                { target: 'second', command: 'run' },
            ],
            { sessionId: 'case' },
        );
        assert.deepEqual(Array.from(executed), ['first'], 'an explicit user cancel stops the batch');
        assert.equal(outcome[0].cancelled, true);
    }

    // ------------------------------------------------------------------
    // Cross-batch: batches for one owner session do not interleave
    // ------------------------------------------------------------------
    {
        const order = [];
        let releaseFirst;
        const firstGate = new Promise(resolve => {
            releaseFirst = resolve;
        });
        const handlers = {
            first: async () => {
                order.push('first:start');
                await firstGate;
                order.push('first:end');
                return { success: true };
            },
            second: async () => {
                order.push('second:start');
                return { success: true };
            },
        };
        const context = {
            window: { _uiActionBatchTails: new Map() },
            Date,
            Promise,
            setTimeout,
            console,
            _uiActionSessionIsCurrent: () => true,
            _activeApiSessionId: () => 'case',
            _emitUIActionProgress: () => {},
            _executeUIAction: action => handlers[action.target](),
        };
        vm.createContext(context);
        vm.runInContext(`${classifiersSrc}\n${progressSrc}\n`, context);
        vm.runInContext(queueSrc, context);

        const batchOne = context._queueUIActionBatch(
            [{ key: 'first', target: 'first', command: 'run' }],
            { sessionId: 'case' },
        );
        const batchTwo = context._queueUIActionBatch(
            [{ key: 'second', target: 'second', command: 'run' }],
            { sessionId: 'case' },
        );
        await new Promise(resolve => setTimeout(resolve, 5));
        assert.deepEqual(Array.from(order), ['first:start'],
            'the second batch must not start while the first is still running');
        releaseFirst();
        await Promise.all([batchOne, batchTwo]);
        assert.deepEqual(Array.from(order), ['first:start', 'first:end', 'second:start']);
    }

    // Independent owner sessions still run concurrently.
    {
        const order = [];
        let releaseA;
        const gateA = new Promise(resolve => {
            releaseA = resolve;
        });
        const handlers = {
            a: async () => {
                order.push('a:start');
                await gateA;
                order.push('a:end');
                return { success: true };
            },
            b: async () => {
                order.push('b:start');
                return { success: true };
            },
        };
        const context = {
            window: { _uiActionBatchTails: new Map() },
            Date,
            Promise,
            setTimeout,
            console,
            _uiActionSessionIsCurrent: () => true,
            _activeApiSessionId: () => 'case',
            _emitUIActionProgress: () => {},
            _executeUIAction: action => handlers[action.target](),
        };
        vm.createContext(context);
        vm.runInContext(`${classifiersSrc}\n${progressSrc}\n`, context);
        vm.runInContext(queueSrc, context);

        const batchA = context._queueUIActionBatch(
            [{ key: 'a', target: 'a', command: 'run' }],
            { sessionId: 'session-a' },
        );
        const batchB = context._queueUIActionBatch(
            [{ key: 'b', target: 'b', command: 'run' }],
            { sessionId: 'session-b' },
        );
        await new Promise(resolve => setTimeout(resolve, 5));
        assert.ok(order.includes('b:start'),
            'a different session is not blocked by this session\'s batch');
        releaseA();
        await Promise.all([batchA, batchB]);
    }

    console.log('PASS: F12 independent failure isolation, dependency blocking, batch serialization');
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
