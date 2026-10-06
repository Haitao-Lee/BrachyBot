const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const core = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-chat-core.js'), 'utf8');
const todo = fs.readFileSync(path.join(root, 'web/app/static/js/brachybot-chat-todo.js'), 'utf8');
function between(source, start, end) {
    const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
    assert(a >= 0 && b > a, start);
    return source.slice(a, b);
}
const clears = [], painted = [];
const label = {}, time = {textContent:'43.5s', style:{}}, toggle = {classList:{remove(){}}};
const body = {classList:{remove(){}}, querySelectorAll(){return []}};
const header = { _timer: 17, _startTime: 1000, querySelector(s) {
    return s === '.thinking-label' ? label : s === '.thinking-time' ? time : null;
}};
const chain = {dataset:{requestId:'parent',live:'1'}, querySelector(s) {
    return s === '.thinking-toggle' ? toggle : s === '.thinking-time' ? time : body;
}, querySelectorAll(){return []}};
const context = vm.createContext({window:{}, document:{querySelectorAll(){return []}},
    activeSessionId:'case-a', Date:{now:()=>90000}, clearInterval:id=>clears.push(id),
    _normalizeTraceLanguage:v=>v, _chainI18n:key=>key, updateChainHeader(){},
    _mountedAssistantFinalRequestIds:new Set(), _collapseThinkingChainAfterReplyPaint:c=>painted.push(c),
    requestChatScrollToBottom(){}, console,
});
vm.runInContext(between(core, 'function finalizeThinkingChain(', '\nfunction cancelThinkingChain('), context);
vm.runInContext(between(core, 'function cancelThinkingChain(', '\nfunction createStreamingResponse('), context);
context.chain = chain; context.header = header;
context.steps = [{phase:'final_response',status:'pending'}];
vm.runInContext('finalizeThinkingChain(chain, header, steps)', context);
assert.equal(header._timer, 17, 'parent SSE completion must not freeze delivery time');
assert.equal(chain.dataset.live, '1');
assert.equal(chain.dataset.deliveryPending, '1');
assert.deepEqual(clears, []);
context.steps[0].status = 'done';
vm.runInContext('finalizeThinkingChain(chain, header, steps)', context);
assert.equal(header._timer, null);
assert.equal(time.textContent, '89.0s', 'duration includes capture, analysis and actual delivery');
assert.equal(chain.dataset.deliveryPending, undefined);
assert.equal(chain.dataset.live, '0');
assert.deepEqual(clears, [17]);
header._timer = 18;
chain.dataset.deliveryPending = '1'; chain.dataset.live = '1';
vm.runInContext('cancelThinkingChain(chain, header)', context);
assert.equal(header._timer, null);
assert.equal(chain.dataset.deliveryPending, undefined);
assert.equal(chain.dataset.live, '0');
assert.deepEqual(clears, [17,18]);
// The visual child must terminalize the original trace, not leave the parent's
// pending timer alive; other Sessions must not receive a status card.
const statusCalls = [], saved = [];
context._pendingVisualFinalResponseMap = () => registry;
context._visualFinalResponseKey = (s,r) => JSON.stringify([s,r]);
context._setFinalResponseTraceStep = (step,status)=>step.status=status;
context._refreshFinalResponseTrace = record=>saved.push(record);
context._updateVisualDeliveryStatus = (record,status)=>statusCalls.push(status);
vm.runInContext(between(todo, 'function _settlePendingVisualFinalResponse(', '\nfunction _updateVisualDeliveryStatus('), context);
const record = {sessionId:'case-a',requestId:'parent',headerEl:header,step:context.steps[0],
    steps:context.steps, stepsDiv:{closest:()=>chain}};
const registry = new Map([[JSON.stringify(['case-a','parent']),record]]);
header._timer = 19; chain.dataset.deliveryPending = '1';
assert.equal(context._settlePendingVisualFinalResponse('case-a','parent','done'), true);
assert.equal(registry.size,0); assert.equal(header._timer,null);
assert.deepEqual(statusCalls,['done']);
assert.equal(context._settlePendingVisualFinalResponse('case-a','parent','done'),false);
assert.equal(context._settlePendingVisualFinalResponse('case-b','parent','done'),false);
console.log('PASS: continuous parent clock, receipt terminalization, cancellation and no double settlement');
