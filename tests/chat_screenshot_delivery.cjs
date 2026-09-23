const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const filename = process.argv[2]
    || path.resolve(__dirname, '../web/app/static/js/brachybot-chat-todo.js');
const source = fs.readFileSync(filename, 'utf8');
function between(start, end) {
    const from = source.indexOf(start);
    const to = source.indexOf(end, from + start.length);
    assert(from >= 0 && to > from, `missing ${start}`);
    return source.slice(from, to);
}
const helper = between('function _turnHasScreenshotPlan(', '\nfunction _normalizeScreenshotRequestTarget(');
const chunkBranch = between(
    "} else if (currentEvent === 'final_text_chunk'",
    "} else if (currentEvent === 'response'",
).replace(/^} else if/, 'if') + '}';
const responseBranch = between(
    "} else if (currentEvent === 'response'",
    "} else if (currentEvent === 'error'",
).replace(/^} else if/, 'if') + '}';

function contextFor(steps, keys = new Set()) {
    const rendered = [];
    const bubble = {
        classList: { add() {}, remove() {} },
        setAttribute() {}, removeAttribute() {},
    };
    const context = vm.createContext({
        steps, screenshotTaskKeys: keys,
        data: null, currentEvent: '', responseText: '', responseEl: null,
        finalTextStreamStarted: false, finalResponseReceived: false,
        isInternalFollowup: false, reportUiActionRequested: false,
        thinkingEl: null, turnRequestId: 'request', turnAssistantMessageId: 'answer',
        turnIdentity: { responseLanguage: 'zh' },
        deferredFinalSteps: [], stepsDiv: null, headerEl: null,
        turnSawPlanningWork: false, turnSawSurgicalGuideWork: false,
        window: {},
        _hasReportGenerationAction: () => false,
        _ensureFinalResponseTraceStep: () => ({}),
        createStreamingResponse: () => { rendered.push('create'); return bubble; },
        updateStreamingResponse: (_element, value) => rendered.push(value),
        scrollToBottom() {},
    });
    vm.runInContext(helper, context);
    vm.runInContext(`function onChunk() { for (let i = 0; i < 1; i++) { ${chunkBranch} } }`, context);
    vm.runInContext(`function onResponse() { for (let i = 0; i < 1; i++) { ${responseBranch} } }`, context);
    return { context, rendered };
}

const screenshot = contextFor([{ type: 'tool', tool: 'ui_screenshot', status: 'done' }]);
screenshot.context.currentEvent = 'final_text_chunk';
screenshot.context.data = { text: '图像还没有回传，无法定位' };
screenshot.context.onChunk();
assert.equal(screenshot.context.responseText, '图像还没有回传，无法定位');
assert.deepEqual(screenshot.rendered, [], 'capture-phase prose must not flash as the answer');
screenshot.context.currentEvent = 'response';
screenshot.context.data = { response: '图像还没有回传，无法定位' };
screenshot.context.onResponse();
assert.deepEqual(screenshot.rendered, [], 'the server response still precedes browser evidence');
assert.equal(screenshot.context.responseEl, null);

const replay = contextFor([], new Set(['request|capture-plan']));
assert.equal(replay.context._turnHasScreenshotPlan([], replay.context.screenshotTaskKeys), true,
    'replayed capture plans also defer their acknowledgement');

const ordinary = contextFor([]);
ordinary.context.currentEvent = 'final_text_chunk';
ordinary.context.data = { text: '正常回答' };
ordinary.context.onChunk();
assert.deepEqual(ordinary.rendered, ['create', '正常回答'],
    'ordinary answers keep progressive rendering');
ordinary.context.currentEvent = 'response';
ordinary.context.data = { response: '正常回答' };
ordinary.context.onResponse();
assert.deepEqual(ordinary.rendered, ['create', '正常回答', '正常回答']);

console.log('PASS: screenshot final text waits for browser evidence; ordinary streaming remains progressive');
