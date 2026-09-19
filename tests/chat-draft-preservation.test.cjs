const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const root = process.argv[2] || path.resolve(__dirname, '../web/app/static/js');
const source = fs.readFileSync(path.join(root, 'brachybot-chat-core.js'), 'utf8');
const start = source.indexOf('function loadSessionChat(');
const end = source.indexOf('\nfunction saveSessionMessage', start);
assert(start >= 0 && end > start);

const input = {
    value: '请保留这段尚未发送的内容',
    dataset: { historySession: 'case-1', draftSession: 'case-1', draftDirty: '1' },
    style: {},
};
const context = vm.createContext({
    setTimeout,
    sessions: {
        'case-1': { messages: [] },
        'case-2': { messages: [] },
    },
    activeSessionId: 'case-1',
    document: {
        getElementById(id) {
            if (id === 'chatInput') return input;
            if (id === 'chatMessages') return { innerHTML: '', appendChild() {} };
            return { textContent: '', classList: { add() {}, remove() {} } };
        },
    },
    window: { resizeChatInput() {} },
    markChatInputDraft(input) {
        if (input.value) input.dataset.draftSession = context.activeSessionId;
    },
    clearChatInputDraft(input) {
        delete input.dataset.draftSession;
        delete input.dataset.draftDirty;
    },
    normalizeSessionMessageIdentities(id, messages) { return messages || []; },
    syncChatHistoryForSession() {},
    escHtml(value) { return String(value || ''); },
    scrollToBottom() {},
    renderChatMessages() {},
    console,
});
vm.runInContext(source.slice(start, end), context);

// Same-session repaint, which models post-restart resource hydration.
context.loadSessionChat('case-1');
assert.equal(input.value, '请保留这段尚未发送的内容');

// Cold startup: the user can type before the first resource snapshot sets
// historySession. The selected case still owns the draft and must preserve it.
input.value = '冷启动期间输入的内容';
delete input.dataset.historySession;
delete input.dataset.draftSession;
context.loadSessionChat('case-1');
assert.equal(input.value, '冷启动期间输入的内容');
assert.equal(input.dataset.draftSession, 'case-1');

// Explicit chat-history clearing remains allowed to clear the composer.
context.loadSessionChat('case-1', { preserveDraft: false });
assert.equal(input.value, '');

// A real session switch must not carry the old draft across cases.
input.value = '旧病例草稿';
input.dataset.historySession = 'case-1';
input.dataset.draftSession = 'case-1';
context.loadSessionChat('case-2');
assert.equal(input.value, '');
assert.equal(input.dataset.historySession, 'case-2');

console.log('PASS: same-session hydration preserves draft; explicit clear and session switch clear it');
