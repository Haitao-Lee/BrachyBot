// UI state sync contract (audit defect F07).
//
// `syncUIBridgeState` used to ignore `response.ok` and swallow every error,
// so a failed write still produced "UI state synchronized" and the caller
// could assume the state had been persisted.  A sync now reports its accepted
// revision, or an explicit unsynced failure that downstream work must not
// treat as persisted.
//
// Runs the production functions against inert fetch mocks. Never contacts a
// server.
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

const syncSrc = extract(src, 'syncUIBridgeState', true);
assert.ok(syncSrc.includes('syncUIBridgeState'));
// The sync resolves the authoritative planning revision (audit R05).
const planRevisionSrc = extract(src, '_currentPlanRevision');
assert.ok(planRevisionSrc.includes('_currentPlanRevision'));

// The generic ui.state action must propagate a sync failure instead of
// reporting success unconditionally.
const rawStart = src.indexOf('async function _executeUIActionRaw(');
const rawEnd = src.indexOf('\n// Screenshot capture', rawStart);
assert.ok(rawStart >= 0 && rawEnd > rawStart);
const rawSrc = src.slice(rawStart, rawEnd);

function makeSyncContext(fetchImpl) {
    const context = {
        window: {},
        API: '/api',
        fetch: fetchImpl,
        Date,
        Promise,
        console,
        _activeApiSessionId: () => 'case-1',
        collectUIState: () => ({ viewer: { zoom: 100 } }),
        scheduleWorkspaceSave: () => {},
    };
    vm.createContext(context);
    vm.runInContext(`${planRevisionSrc}\n${syncSrc}\n`, context);
    return context;
}

async function main() {
    // ------------------------------------------------------------------
    // A rejected write is a failed sync, not a success
    // ------------------------------------------------------------------
    {
        const context = makeSyncContext(async () => ({
            ok: false,
            status: 500,
            json: async () => ({ success: false, error: 'server_busy' }),
        }));
        const result = await context.syncUIBridgeState('test');
        assert.equal(result.success, false);
        assert.equal(result.unsynced, true);
        assert.match(String(result.error), /server_busy/);
        assert.equal(context.window._uiStateSyncStatus.synced, false,
            'the status records that the state is unsynced');
    }

    // ------------------------------------------------------------------
    // A non-2xx with an unparseable body is still a failed sync
    // ------------------------------------------------------------------
    {
        const context = makeSyncContext(async () => ({
            ok: false,
            status: 502,
            json: async () => {
                throw new Error('not json');
            },
        }));
        const result = await context.syncUIBridgeState('test');
        assert.equal(result.success, false);
        assert.equal(result.unsynced, true);
        assert.match(String(result.error), /502/);
    }

    // ------------------------------------------------------------------
    // A network failure is reported as unsynced, never as skipped success
    // ------------------------------------------------------------------
    {
        const context = makeSyncContext(async () => {
            throw new Error('offline');
        });
        const result = await context.syncUIBridgeState('test');
        assert.equal(result.success, false);
        assert.equal(result.unsynced, true);
        assert.match(String(result.error), /offline/);
    }

    // ------------------------------------------------------------------
    // A 2xx that does not acknowledge the write is a failed sync
    // ------------------------------------------------------------------
    {
        const context = makeSyncContext(async () => ({
            ok: true,
            status: 200,
            json: async () => ({ success: false, error: 'stale_state_seq' }),
        }));
        const result = await context.syncUIBridgeState('test');
        assert.equal(result.success, false);
        assert.match(String(result.error), /stale_state_seq/);
    }

    // ------------------------------------------------------------------
    // A successful sync reports the accepted revision and clears the flag
    // ------------------------------------------------------------------
    {
        let body = null;
        const context = makeSyncContext(async (url, init) => {
            body = JSON.parse(init.body);
            return {
                ok: true,
                status: 200,
                json: async () => ({
                    success: true,
                    accepted_revision: { accepted: true, state_seq: 12, plan_revision: 3 },
                }),
            };
        });
        const result = await context.syncUIBridgeState('planning.done');
        assert.equal(result.success, true);
        assert.equal(result.accepted_revision.state_seq, 12);
        assert.equal(context.window._uiStateSyncStatus.synced, true);
        assert.equal(context.window._uiStateSyncStatus.revision.state_seq, 12);
        assert.ok(body.state_seq > 0, 'the request carries a monotonic sequence');
        assert.equal(body.browser_instance, context.window._uiBrowserInstanceId());
        assert.equal(typeof body.mode, 'string', 'the write kind is explicit');
    }

    // The sequence is monotonic across calls for one browser instance.
    {
        const sequences = [];
        const context = makeSyncContext(async (url, init) => {
            sequences.push(JSON.parse(init.body).state_seq);
            return {
                ok: true,
                status: 200,
                json: async () => ({ success: true, accepted_revision: { accepted: true } }),
            };
        });
        await context.syncUIBridgeState('a');
        await context.syncUIBridgeState('b');
        assert.ok(sequences[1] > sequences[0], 'state_seq must increase');
    }

    // ------------------------------------------------------------------
    // The ui.state action must not claim success over a failed sync
    // ------------------------------------------------------------------
    {
        const context = {
            window: {},
            _activeApiSessionId: () => 'case-1',
            syncUIBridgeState: async () => ({ success: false, error: 'offline', unsynced: true }),
            addChat: () => {
                throw new Error('must not chat a success message on a failed sync');
            },
            console,
        };
        vm.createContext(context);
        vm.runInContext(rawSrc, context);
        const result = await context._executeUIActionRaw({ target: 'ui.state', command: 'sync' }, {});
        assert.equal(result.success, false, 'a failed sync must not report success');
        assert.equal(result.unsynced, true);
        assert.match(String(result.error), /offline/);
    }

    {
        const messages = [];
        const context = {
            window: {},
            _activeApiSessionId: () => 'case-1',
            syncUIBridgeState: async () => ({
                success: true,
                accepted_revision: { accepted: true, state_seq: 4 },
            }),
            addChat: (_kind, text) => messages.push(text),
            monitorChatText: (zh) => zh,
            console,
        };
        vm.createContext(context);
        vm.runInContext(rawSrc, context);
        const result = await context._executeUIActionRaw({ target: 'ui.state', command: 'sync' }, {});
        assert.equal(result.success, true);
        assert.equal(result.accepted_revision.state_seq, 4);
        assert.equal(messages.length, 1, 'only a real success is announced');
    }

    console.log('PASS: F07 sync reports accepted revision or explicit unsynced failure');
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
