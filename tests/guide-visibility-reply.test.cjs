const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
    process.env.BRACHYBOT_CHAT_SOURCE
        || path.join(__dirname, '..', 'web', 'app', 'static', 'js', 'brachybot-chat-todo.js'),
    'utf8',
);
const start = source.indexOf('function _verifiedTreeVisibilityReply(');
const end = source.indexOf('function _hasReportGenerationAction(', start);
assert.ok(start >= 0 && end > start);
const context = { _isTerminalToolStatus: status => ['done', 'error'].includes(status) };
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

const steps = [{
    tool: 'ui_controller', status: 'done',
    metadata: { actions: [
        { target: 'tree.visibility', command: 'set', value: 'guide_mesh_v1,on' },
    ] },
}];
const state = { ui_operation_catalog: [{
    node_id: 'guide_mesh_v1', label: 'Puncture guide v1 — Show / hide',
    action: { target: 'tree.visibility' },
}] };
const applied = context._verifiedTreeVisibilityReply(
    steps, [{ success: true, target: 'tree.visibility', node_id: 'guide_mesh_v1', visible: true,
        effective_visible_3d: true }], state, 'zh',
);
assert.equal(applied.success, true);
assert.match(applied.text, /Puncture guide v1/);
assert.match(applied.text, /显示/);
assert.doesNotMatch(applied.text, /重新生成导板.*已/);

const failed = context._verifiedTreeVisibilityReply(
    steps, [{ success: false, error: 'missing' }], state, 'zh',
);
assert.equal(failed.success, false);
assert.match(failed.text, /未能显示/);

const parentHidden = context._verifiedTreeVisibilityReply(
    steps, [{ success: true, node_id: 'guide_mesh_v1', visible: true,
        effective_visible_3d: false }], state, 'zh',
);
assert.equal(parentHidden.success, true);
assert.match(parentHidden.text, /还没有出现在 3D Viewer/);

console.log('guide visibility browser reply: passed');
