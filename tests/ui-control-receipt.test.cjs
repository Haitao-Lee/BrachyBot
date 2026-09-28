// Execution receipt and value-coercion contracts (audit defects F02 / F10).
//
// A generic UI control may only claim business completion when its mounted
// business handler returned a receipt.  Dispatching a DOM event is not a
// receipt: the previous executor reported `success:true` even when the
// handler returned `{success:false}`, and it never awaited handlers that take
// an argument (`generateGuide('v1')`).
//
// Runs the production functions against inert DOM mocks. Never contacts a
// server and never mutates a case.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = process.argv[2] || path.join(__dirname, '..', 'web', 'app', 'static', 'js');
const src = fs.readFileSync(path.join(root, 'brachybot-ui-api.js'), 'utf8');

const genericSrc = src.slice(
    src.indexOf('async function executeGenericUIControl('),
    src.indexOf('\nfunction instrumentUIControls('),
);
assert.ok(genericSrc.includes('async function executeGenericUIControl('));
// The receipt reads the shared terminal-state classifier (audit R02).
const classifiersSrc = src.slice(
    src.indexOf('const _UI_ACTION_RUNNING_STATES'),
    src.indexOf('function _emitUIActionProgress'),
);
assert.ok(classifiersSrc.includes('_uiActionResultState'));

const rawStart = src.indexOf('function _overlayOpacityFraction(');
const rawEnd = src.indexOf('\n// Screenshot capture', rawStart);
assert.ok(rawStart >= 0 && rawEnd > rawStart);
const rawSrc = src.slice(rawStart, rawEnd);

async function probe(name, element, command, payload, extra = {}) {
    const events = [];
    const el = {
        id: 'test',
        tagName: 'BUTTON',
        type: 'button',
        disabled: false,
        min: '',
        max: '',
        step: '',
        value: '',
        getAttribute: () => null,
        getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 }),
        dispatchEvent: e => events.push(e),
        click: () => {},
        ...element,
    };
    const sandbox = {
        window: {},
        _parseUIControlPayload: x => x,
        _resolveUIControlElement: () => el,
        _uiOperationLabel: () => name,
        _uiOperationVisible: () => true,
        reportUIEvent: () => {},
        syncUIBridgeState: () => {},
        console,
        Event: class {
            constructor(type, init) {
                this.type = type;
                Object.assign(this, init);
            }
        },
        MouseEvent: class {
            constructor(type, init) {
                this.type = type;
                Object.assign(this, init);
            }
        },
    };
    sandbox.window.WheelEvent = sandbox.MouseEvent;
    sandbox.window.PointerEvent = sandbox.MouseEvent;
    Object.assign(sandbox, extra);
    if (extra.window) Object.assign(sandbox.window, extra.window);
    vm.createContext(sandbox);
    vm.runInContext(`${classifiersSrc}\n${genericSrc}\n`, sandbox);
    const result = await sandbox.executeGenericUIControl(command, payload);
    return { result, events };
}

async function rawProbe(action, globals = {}) {
    const applied = [];
    const context = {
        window: {},
        _activeApiSessionId: () => 'case',
        setGroupOpacity: (...args) => applied.push(['setGroupOpacity', ...args]),
        setDoseOverlayOpacity: (...args) => applied.push(['setDoseOverlayOpacity', ...args]),
        console,
        state: globals.state || {},
        dataTreeState: globals.dataTreeState,
    };
    Object.assign(context, globals);
    vm.createContext(context);
    vm.runInContext(rawSrc, context);
    const result = await context._executeUIActionRaw(action, {});
    return { result, applied };
}

function addHours(base) {
    return base;
}

async function main() {
    // ------------------------------------------------------------------
    // F02: a business handler's failure is the action's failure
    // ------------------------------------------------------------------
    {
        const { result } = await probe(
            'simple_async_failure_propagates',
            { getAttribute: k => (k === 'onclick' ? 'failOperation()' : null) },
            'click',
            {},
            {
                window: {
                    failOperation: async () => ({ success: false, error: 'business_failure' }),
                },
            },
        );
        assert.equal(result.success, false, 'a handler failure must not be reported as success');
        assert.match(String(result.error), /business_failure/);
    }

    {
        const { result } = await probe(
            'sync_handler_false_propagates',
            { getAttribute: k => (k === 'onclick' ? 'failOperation()' : null) },
            'click',
            {},
            { window: { failOperation: () => false } },
        );
        assert.equal(result.success, false, 'a handler returning false is a failure');
    }

    {
        const { result } = await probe(
            'handler_throw_propagates',
            { getAttribute: k => (k === 'onclick' ? 'boom()' : null) },
            'click',
            {},
            {
                window: {
                    boom: () => {
                        throw new Error('exploded');
                    },
                },
            },
        );
        assert.equal(result.success, false);
        assert.match(String(result.error), /exploded/);
    }

    // ------------------------------------------------------------------
    // F02: an argument-taking handler is awaited and its receipt kept
    // ------------------------------------------------------------------
    {
        let pending = true;
        let seenArgs = null;
        const { result } = await probe(
            'argument_handler_awaited',
            {
                getAttribute: k => (k === 'onclick' ? "generateGuide('v1')" : null),
                click: () => {
                    pending = true;
                },
            },
            'click',
            {},
            {
                window: {
                    generateGuide: async version => {
                        seenArgs = version;
                        await new Promise(resolve => setTimeout(resolve, 5));
                        pending = false;
                        return { success: true, job_id: 'guide-1', version };
                    },
                },
            },
        );
        assert.equal(result.success, true);
        assert.equal(pending, false, 'the handler promise must be awaited before success is reported');
        assert.equal(seenArgs, 'v1');
        // A job id is a JobRef: it proves the work was accepted, not that it
        // finished.  This assertion previously read `completed === true`, which
        // *was* audit defect R02 — a queued guide read as a generated one
        // (tightened for R02, see NL_UI_PARITY_IMPLEMENTATION_STATUS).
        assert.equal(result.completed, false, 'a JobRef is acceptance, not business completion');
        assert.equal(result.status, 'running');
        assert.equal(result.dispatched, true);
        assert.equal(result.receipt.job_id, 'guide-1');
    }

    {
        // An explicit terminal claim from the mounted handler is still a
        // completion: only the bare JobRef is downgraded.
        const { result } = await probe(
            'argument_handler_terminal_receipt',
            { getAttribute: k => (k === 'onclick' ? "generateGuide('v2')" : null) },
            'click',
            {},
            {
                window: {
                    generateGuide: async version => ({ success: true, completed: true, version }),
                },
            },
        );
        assert.equal(result.completed, true, 'an explicit terminal receipt proves completion');
        assert.equal(result.status, 'completed');
    }

    {
        const { result } = await probe(
            'argument_handler_failure_propagates',
            { getAttribute: k => (k === 'onclick' ? "generateGuide('v1')" : null) },
            'run',
            {},
            {
                window: {
                    generateGuide: async () => ({ success: false, error: 'mesh_failed' }),
                },
            },
        );
        assert.equal(result.success, false);
        assert.match(String(result.error), /mesh_failed/);
    }

    // ------------------------------------------------------------------
    // F02: a bare dispatch is never upgraded to "completed"
    // ------------------------------------------------------------------
    {
        const { result } = await probe(
            'bare_dispatch_is_not_completed',
            { getAttribute: () => null },
            'click',
            {},
        );
        assert.equal(result.success, true, 'the dispatch itself succeeded');
        assert.equal(result.dispatched, true);
        assert.equal(result.completed, false, 'no handler receipt means the business result is unknown');
        assert.equal(result.receipt.completed, false);
    }

    {
        const { result } = await probe(
            'handler_without_receipt_is_not_completed',
            { getAttribute: k => (k === 'onclick' ? 'fireAndForget()' : null) },
            'click',
            {},
            { window: { fireAndForget: () => undefined } },
        );
        assert.equal(result.success, true);
        assert.equal(result.completed, false);
    }

    // ------------------------------------------------------------------
    // F10: numeric bounds — an absent bound is not zero
    // ------------------------------------------------------------------
    {
        const { result } = await probe(
            'numeric_without_bounds_is_not_clamped_to_zero',
            { tagName: 'INPUT', type: 'number', value: '12', getAttribute: () => null },
            'set',
            { value: 25 },
        );
        assert.equal(result.success, true);
        assert.equal(result.value, '25', 'no min/max must not clamp the value to 0');
    }

    {
        const { result } = await probe(
            'numeric_lower_bound_only',
            { tagName: 'INPUT', type: 'number', value: '12', min: '10', max: '', getAttribute: () => null },
            'set',
            { value: 5 },
        );
        assert.equal(result.value, '10', 'a one-sided bound still clamps');
    }

    {
        const { result } = await probe(
            'numeric_upper_bound_only',
            { tagName: 'INPUT', type: 'number', value: '12', min: '', max: '50', getAttribute: () => null },
            'set',
            { value: 80 },
        );
        assert.equal(result.value, '50');
    }

    {
        const { result } = await probe(
            'numeric_both_bounds',
            { tagName: 'INPUT', type: 'number', value: '12', min: '0', max: '100', getAttribute: () => null },
            'set',
            { value: 25 },
        );
        assert.equal(result.value, '25');
    }

    {
        const { result } = await probe(
            'numeric_nan_is_rejected',
            { tagName: 'INPUT', type: 'number', value: '12', min: '', max: '', getAttribute: () => null },
            'set',
            { value: 'not-a-number' },
        );
        assert.equal(result.success, false, 'NaN must not be written into a numeric control');
    }

    {
        const { result } = await probe(
            'numeric_infinity_is_rejected',
            { tagName: 'INPUT', type: 'number', value: '12', min: '', max: '', getAttribute: () => null },
            'set',
            { value: Infinity },
        );
        assert.equal(result.success, false);
    }

    // ------------------------------------------------------------------
    // F10: booleans accept booleans or explicit normalizations only
    // ------------------------------------------------------------------
    {
        const { result } = await probe(
            'checkbox_string_false_stays_false',
            { tagName: 'INPUT', type: 'checkbox', checked: true, getAttribute: () => null },
            'set',
            { value: 'false' },
        );
        assert.equal(result.success, true);
        assert.equal(result.checked, false, 'the string "false" must not coerce to true');
        assert.equal(result.applied, false);
    }

    {
        const { result } = await probe(
            'checkbox_string_true_is_true',
            { tagName: 'INPUT', type: 'checkbox', checked: false, getAttribute: () => null },
            'set',
            { value: 'true' },
        );
        assert.equal(result.checked, true);
    }

    {
        const { result } = await probe(
            'checkbox_boolean_false_is_false',
            { tagName: 'INPUT', type: 'checkbox', checked: true, getAttribute: () => null },
            'set',
            { value: false },
        );
        assert.equal(result.checked, false);
    }

    {
        const { result } = await probe(
            'checkbox_chinese_off_is_false',
            { tagName: 'INPUT', type: 'checkbox', checked: true, getAttribute: () => null },
            'set',
            { value: '关' },
        );
        assert.equal(result.checked, false);
    }

    // ------------------------------------------------------------------
    // F10: relative overlay opacity is relative, and returns the applied value
    // ------------------------------------------------------------------
    for (const [target, setter] of [
        ['overlay.ctv.opacity', 'setGroupOpacity'],
        ['overlay.oar.opacity', 'setGroupOpacity'],
        ['overlay.dose.opacity', 'setDoseOverlayOpacity'],
    ]) {
        const axis = target.includes('ctv') ? 'ctv' : target.includes('oar') ? 'oar' : null;
        const state = target === 'overlay.dose.opacity' ? { doseOverlay: { opacity: 0.5 } } : {};
        const dataTreeState = axis
            ? { ctv: { opacity: 0.5 }, organs: [{ opacity: 0.5 }] }
            : undefined;
        const { result, applied } = await rawProbe(
            { target, command: 'increase', value: 10 },
            { state, dataTreeState },
        );
        assert.equal(result.success, true, `${target} increase must succeed`);
        assert.equal(result.applied, 60, `${target} increase must be relative to the current 50%`);
        assert.equal(result.requested, 10);
        const call = applied.at(-1);
        assert.equal(call[0], setter);
        assert.equal(call[call.length - 1], 60, `${target} must be set to the resolved absolute percentage`);
    }

    {
        const { result, applied } = await rawProbe(
            { target: 'overlay.ctv.opacity', command: 'decrease', value: 20 },
            { dataTreeState: { ctv: { opacity: 0.5 }, organs: [] } },
        );
        assert.equal(result.applied, 30);
        assert.equal(applied.at(-1)[applied.at(-1).length - 1], 30);
    }

    {
        const { result } = await rawProbe(
            { target: 'overlay.ctv.opacity', command: 'increase', value: 40 },
            { dataTreeState: { ctv: { opacity: 0.9 }, organs: [] } },
        );
        assert.equal(result.applied, 100, 'relative changes clamp to 0..100');
    }

    {
        const { result } = await rawProbe(
            { target: 'overlay.dose.opacity', command: 'decrease', value: 90 },
            { state: { doseOverlay: { opacity: 0.2 } } },
        );
        assert.equal(result.applied, 0, 'relative changes clamp to 0..100');
    }

    {
        const { result } = await rawProbe(
            { target: 'overlay.ctv.opacity', command: 'set', value: 30 },
            { dataTreeState: { ctv: { opacity: 0.5 }, organs: [] } },
        );
        assert.equal(result.applied, 30, 'absolute set is unchanged');
    }

    {
        const { result } = await rawProbe(
            { target: 'overlay.ctv.opacity', command: 'increase', value: 10 },
            { dataTreeState: undefined, state: {} },
        );
        assert.equal(result.success, false, 'a relative change without a readable current value must not guess');
    }

    console.log('PASS: F02 execution receipts (handler failure, argument handler, dispatch≠completed)');
    console.log('PASS: F10 value coercion (numeric bounds, NaN/Infinity, boolean strings, relative opacity)');
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
