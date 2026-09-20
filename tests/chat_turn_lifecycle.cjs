const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const filename = process.argv[2] || path.resolve(__dirname, '../web/app/static/js/brachybot-chat-todo.js');
const source = fs.readFileSync(filename, 'utf8');
function between(start, end) {
    const a = source.indexOf(start);
    const b = source.indexOf(end, a + start.length);
    assert(a >= 0 && b > a, start);
    return source.slice(a, b);
}
function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
function recoveryContext() {
    const header = deferred();
    const effects = [];
    const context = vm.createContext({
        window: {
            _chatTurnGeneration: 0, _chatTurnActive: false, _chatStreaming: false,
            _sessionChatTaskIds: {}, _sessionChatTaskStatuses: {}, _detachedChatTasks: {},
            hideWorkspaceRecoveryNotice: () => effects.push('hide'),
        },
        activeSessionId: 'case-a', API: '/api',
        fetch: () => header.promise,
        setTimeout() {},
        console: { warn() {} },
        _hadInFlightTask: () => true,
        _addTaskRecoveryNotice: () => effects.push('notice'),
        _setCaseTaskState: () => effects.push('state'),
        setStreamingState: () => effects.push('button'),
        sendChat: async () => { effects.push('replay'); },
    });
    vm.runInContext(between('window.resumeSessionChatTask = async function', '\n/******** STATE ********/'), context);
    function startNewTurn(completed = false) {
        Object.assign(context.window, {
            _chatTurnGeneration: 1,
            _chatTurnActive: !completed, _chatStreaming: !completed,
            _activeChatTaskSessionId: 'case-a', _activeChatTaskId: 'new-task',
        });
        context.window._sessionChatTaskIds['case-a'] = 'new-task';
        context.window._sessionChatTaskStatuses['case-a'] = completed ? 'completed' : 'running';
    }
    return { context, header, effects, startNewTurn };
}
async function testRecoveryRaces() {
    for (const status of [null, 'completed', 'failed', 'running', 'http-error', 'network-error']) {
        for (const completed of [false, true]) {
            const h = recoveryContext();
            const pending = h.context.window.resumeSessionChatTask();
            h.startNewTurn(completed);
            if (status === 'network-error') h.header.reject(new Error('offline'));
            else h.header.resolve({
                ok: status !== 'http-error',
                json: async () => ({ task: status ? { task_id: 'old-task', status } : null }),
            });
            await pending;
            assert.equal(h.context.window._activeChatTaskId, 'new-task', String(status));
            assert.equal(h.context.window._chatTurnActive, !completed, String(status));
            assert.equal(h.context.window._sessionChatTaskIds['case-a'], 'new-task');
            assert.deepEqual(h.effects, [], 'stale status must not change current turn');
        }
    }
    // Starting a turn during JSON decoding is another asynchronous boundary.
    const h = recoveryContext();
    const body = deferred();
    const decoding = deferred();
    const pending = h.context.window.resumeSessionChatTask();
    h.header.resolve({ ok: true, json() { decoding.resolve(); return body.promise; } });
    await decoding.promise;
    h.startNewTurn();
    body.resolve({ task: { status: 'completed' } });
    await pending;
    assert.equal(h.context.window._chatTurnActive, true);
    assert.deepEqual(h.effects, []);

    const switched = recoveryContext();
    const oldCase = switched.context.window.resumeSessionChatTask();
    switched.context.activeSessionId = 'case-b';
    switched.header.resolve({ ok: false });
    await oldCase;
    assert.deepEqual(switched.effects, [], 'old-case failure must not alter the selected case');

    const refreshing = recoveryContext();
    const refresh = deferred();
    const refreshStarted = deferred();
    refreshing.context.window.refreshSessionAfterTaskCompletion = () => {
        refreshStarted.resolve();
        return refresh.promise;
    };
    const restoringCompleted = refreshing.context.window.resumeSessionChatTask();
    refreshing.header.resolve({ ok: true, json: async () => ({ task: { status: 'completed' } }) });
    await refreshStarted.promise;
    refreshing.startNewTurn();
    refresh.resolve();
    await restoringCompleted;
    assert.equal(refreshing.context.window._chatTurnActive, true);
    assert.deepEqual(refreshing.effects, []);

    // A real idle restore must still attach to its server task.
    const idle = recoveryContext();
    const restoring = idle.context.window.resumeSessionChatTask();
    idle.header.resolve({ ok: true, json: async () => ({ task: { status: 'running', task_id: 'restore-me' } }) });
    assert.equal(await restoring, true);
    assert(idle.effects.includes('replay'));
}
function traceContext() {
    const context = vm.createContext({
        window: {}, activeSessionId: 'case-a', steps: [], deferredFinalSteps: [],
        optimisticTraceStepIds: { user: 'optimistic-user', router: 'optimistic-router' },
        _optimisticRouterConsumed: true,
    });
    for (const [start, end] of [
        ['function _isFinalResponseTraceStep(', '\nfunction _finalResponseTraceContent('],
        ['function _finalResponseTraceContent(', '\nfunction _setFinalResponseTraceStep('],
        ['function _setFinalResponseTraceStep(', '\nfunction _ensureFinalResponseTraceStep('],
        ['function _ensureFinalResponseTraceStep(', '\nfunction _pendingVisualFinalResponseMap('],
        ['function _finishFinalResponseTraceSteps(', '\nfunction _isScreenshotAckResponse('],
    ]) vm.runInContext(between(start, end), context);
    vm.runInContext(between('const reconcileOptimisticTraceStep = step => {', '\n    // Do not infer planning completion'), context);
    return context;
}
function testFinalStepIdentity() {
    const context = traceContext();
    vm.runInContext(`
        steps.push({ id: 7, type: 'assistant', phase: 'final_response', title: 'Final Response', status: 'pending' });
        _ensureFinalResponseTraceStep(steps, deferredFinalSteps, 'request', 'zh');
        for (let replay = 0; replay < 3; replay++) {
            const traced = reconcileOptimisticTraceStep({ id: 7, type: 'assistant', phase: 'final_response', status: 'done' });
            _setFinalResponseTraceStep(traced.step, 'pending', 'zh');
        }
        _ensureFinalResponseTraceStep(steps, deferredFinalSteps, 'request', 'zh');
        _finishFinalResponseTraceSteps(steps, deferredFinalSteps, 'done', 'zh', '');
    `, context);
    assert.equal(context.steps.length, 1);
    assert.equal(context.deferredFinalSteps.length, 1);
    assert.equal(context.steps[0], context.deferredFinalSteps[0]);
    assert.equal(context.steps[0].status, 'done');
}
async function testFinalCleanup(rendererThrows = false, newerTurn = false) {
    const context = traceContext();
    const finalStep = { id: 7, type: 'assistant', phase: 'final_response', status: 'pending' };
    const cancel = () => {};
    const buttons = [];
    Object.assign(context, {
        isInternalFollowup: false, turnDetached: false, reconnectNeeded: false,
        turnCompleted: true, turnFailed: false, turnCancelled: false,
        finalReplyCommitted: true, finalResponsePaintWaited: false,
        visualFinalResponsePending: false, finalResponseStep: finalStep,
        steps: [finalStep], deferredFinalSteps: [finalStep], chainEl: {}, headerEl: {}, stepsDiv: null,
        turnIdentity: { responseLanguage: 'zh' }, turnSessionId: 'case-a', turnRequestId: 'request',
        turnAssistantMessageId: 'answer', reportUiActionRequested: false, responseText: 'Hello',
        turnGeneration: 1, todo: null, cancelTurnUi: cancel,
        chatAbortController: null, turnAbortController: null,
        _waitForFinalReplyPaint: async () => {},
        finalizeThinkingChain: () => { if (rendererThrows) throw new Error('renderer failed'); },
        saveSessionMessage() {}, setTimeout() {},
        setStreamingState: value => buttons.push(value), console: { warn() {} },
    });
    Object.assign(context.window, {
        _chatTurnCancelUi: cancel, _chatTurnActive: true, _chatStreaming: true,
        _activeChatTaskSessionId: 'case-a', _activeChatTurnGeneration: 1,
        _activeChatTaskId: 'task', notifyAssistantFinalResponseMounted() {},
    });
    if (newerTurn) {
        context.window._chatTurnCancelUi = () => {};
        context.window._activeChatTurnGeneration = 2;
        context.window._activeChatTaskId = 'newer-task';
    }
    const cleanup = source.indexOf('const isCurrentTurn = window._chatTurnCancelUi');
    const finalizer = source.lastIndexOf('    } finally {', cleanup);
    const tail = source.slice(finalizer, source.indexOf('\nfunction _traceStepForDisplay(', finalizer));
    const body = tail.slice(tail.indexOf('{') + 1, tail.lastIndexOf('    }\n}'));
    // Keep reply formatting variables in their real try-block scope. The
    // finalizer must work without accidentally relying on global test stubs.
    vm.runInContext(`async function finishTurn() {
        try { const suppressScreenshotAck = false; let renderedFinalText = 'Hello'; }
        finally { ${body} }
    }`, context);
    if (rendererThrows) await assert.rejects(context.finishTurn(), /renderer failed/);
    else await context.finishTurn();
    assert.equal(finalStep.status, 'done');
    if (newerTurn) {
        assert.equal(context.window._chatTurnActive, true);
        assert.equal(context.window._chatStreaming, true);
        assert.equal(context.window._activeChatTaskId, 'newer-task');
        assert.deepEqual(buttons, []);
        return;
    }
    assert.equal(context.window._chatTurnActive, false);
    assert.equal(context.window._chatStreaming, false);
    assert.deepEqual(buttons, [false]);
}
(async () => {
    const only = process.argv[3];
    if (!only || only === 'recovery') await testRecoveryRaces();
    if (!only || only === 'identity') testFinalStepIdentity();
    if (!only || only === 'cleanup') {
        await testFinalCleanup();
        await testFinalCleanup(true);
        await testFinalCleanup(false, true);
    }
    console.log('PASS: stale recovery isolation, final-step identity, terminal cleanup and rendering failure');
})().catch(error => { console.error(error); process.exitCode = 1; });
