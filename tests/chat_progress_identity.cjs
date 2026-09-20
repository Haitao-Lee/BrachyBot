// Regression coverage for Progress-dock milestone identity.
//
// A final-response milestone can arrive as a client-synthesised row, a server
// SSE step, a replayed event and a restored snapshot, each with a different
// server id. They must all merge into one dock row instead of stacking two
// identical "Final response" entries.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const root = process.argv[2] || path.resolve(__dirname, '../web/app/static/js');
const source = fs.readFileSync(path.join(root, 'brachybot-chat-todo.js'), 'utf8');
const start = source.indexOf('function _todoStepIdentity(');
const end = source.indexOf('\nfunction _planningTemplates(', start);
assert(start >= 0 && end > start, 'todo identity helpers not found');

function isFinalResponseTraceStep(step) {
    const phase = String(step.phase || (step.metadata && step.metadata.phase) || '')
        .trim().toLowerCase().replace(/[\s-]+/g, '_');
    if (phase === 'final_response') return true;
    const title = String(step.title || '').trim().toLowerCase();
    return ['final response', 'final answer', '最终回复', '最终响应'].includes(title);
}

function makeTodo() {
    return {
        items: [],
        root: null,
        addPending(step) {
            const milestoneKey = context._todoStepIdentity(step);
            if (milestoneKey && this.items.some(i => i.milestoneKey === milestoneKey)) {
                return this.items.find(i => i.milestoneKey === milestoneKey);
            }
            const id = (step.id != null && step.id !== '')
                ? String(step.id)
                : ('s' + (this.items.length + 1));
            const item = {
                id,
                label: labelForStep(step),
                toolName: step.tool || null,
                milestoneKey: milestoneKey || null,
                status: 'pending',
                step,
                node: null,
            };
            this.items.push(item);
            return item;
        },
        markActive(item) { if (item.status !== 'done' && item.status !== 'error') item.status = 'active'; },
        markDone(item) { item.status = 'done'; },
        reopenSeeded(item) { item.status = 'active'; },
    };
}

function labelForStep(step) {
    if (step.type === 'assistant' && step.title) return String(step.title);
    return step.tool || step.title || 'row';
}

const context = vm.createContext({
    console,
    document: null,
    _isFinalResponseTraceStep: isFinalResponseTraceStep,
    _todoFindPredicted: () => null,
    _todoLabelForStep: labelForStep,
    _brachyOperationName: value => String(value || ''),
    _isTerminalToolStatus: status => ['done', 'completed', 'success', 'complete'].includes(String(status)),
    _isFailedToolStatus: status => ['error', 'failed'].includes(String(status)),
    _isInFlightToolStatus: status => ['pending', 'running', 'active', 'in_progress'].includes(String(status)),
});
vm.runInContext(source.slice(start, end), context);
const update = context._todoUpdateFromStep;
assert.equal(typeof update, 'function', '_todoUpdateFromStep not extracted');

// 1. Same server step pending -> done: one row, correct terminal status.
{
    const todo = makeTodo();
    const pending = { id: 7, type: 'assistant', title: 'Final Response', phase: 'final_response', status: 'pending' };
    const done = Object.assign({}, pending, { status: 'done' });
    update(todo, pending);
    update(todo, done);
    assert.equal(todo.items.length, 1, 'pending -> done must keep one row');
    assert.equal(todo.items[0].status, 'done', 'terminal status must be applied');
}

// 2. Client-synthesised row and server step with different ids, both orders.
for (const order of [['client', 'server'], ['server', 'client']]) {
    const todo = makeTodo();
    const client = { id: 'client-final-response-req-1', type: 'assistant', title: 'Final Response', phase: 'final_response', status: 'pending' };
    const server = { id: 42, type: 'assistant', title: '最终回复', phase: 'final_response', status: 'pending' };
    for (const which of order) update(todo, which === 'client' ? client : server);
    assert.equal(todo.items.length, 1, `client/server (${order.join('->')}) must merge to one row`);
    assert.equal(todo.items[0].milestoneKey, 'phase:final_response');
}

// 3. A restored row merges with a replayed event.
{
    const todo = makeTodo();
    const restored = {
        id: 'milestone-phase_final_response',
        label: '最终回复',
        toolName: null,
        milestoneKey: 'phase:final_response',
        status: 'active',
        node: null,
    };
    todo.items.push(restored);
    update(todo, { id: 99, type: 'assistant', title: 'Final Response', phase: 'final_response', status: 'done' });
    assert.equal(todo.items.length, 1, 'restored + replay must merge');
    assert.equal(todo.items[0].status, 'done');
}

// 4. Different requests each keep their own final-response row.
{
    const a = makeTodo();
    const b = makeTodo();
    update(a, { id: 1, type: 'assistant', title: 'Final Response', phase: 'final_response', status: 'pending' });
    update(b, { id: 2, type: 'assistant', title: 'Final Response', phase: 'final_response', status: 'pending' });
    assert.equal(a.items.length, 1);
    assert.equal(b.items.length, 1);
    assert.notEqual(a.items[0].id, b.items[0].id);
}

// 5. A distinct assistant milestone (Response Synthesis) stays its own row and
//    does not inherit the final-response identity.
{
    const todo = makeTodo();
    update(todo, { id: 3, type: 'assistant', title: 'Response Synthesis', status: 'pending' });
    update(todo, { id: 4, type: 'assistant', title: 'Final Response', phase: 'final_response', status: 'pending' });
    assert.equal(todo.items.length, 2, 'synthesis and final response are distinct milestones');
    assert.notEqual(todo.items[0].label, todo.items[1].label, 'labels must be distinguishable');
    assert.equal(todo.items[1].milestoneKey, 'phase:final_response');
}

console.log('chat progress identity regression tests passed');
