// Pure request-capture protocol. No patient, server, DOM or model calls.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const a = 'a'.repeat(32), b = 'b'.repeat(32), sid = '1'.repeat(32);
let mounted = a, generation = 1;
const window = { activeSessionId: sid, _i18nLang: 'en', BrachyBotTimepoints: {
    captureSubmission: () => ({ sessionId: sid, timepointId: mounted, generation, uiLanguage: window._i18nLang }),
    isSubmissionCurrent: scope => scope.sessionId === sid && scope.timepointId === mounted && scope.generation === generation,
} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/app/static/js/brachybot-chat-target.js'), 'utf8'), { window, Headers });
const targets = window.BrachyBotChatTargets;
const first = targets.capture();
assert(Object.isFrozen(first));
targets.remember('parent', first);
mounted = b; generation = 2; window._i18nLang = 'zh';
const queued = targets.capture({ timepointScope: first });
const child = targets.capture({ timepointScope: targets.parent(sid, 'parent') });
assert.equal(queued.timepointId, a); assert.equal(child.timepointId, a);
assert.equal(targets.headers(first).get('X-BrachyBot-Timepoint'), a);
assert.equal(targets.headers(first).get('X-BrachyBot-Language'), 'en');
assert.equal(targets.capture().timepointId, b); assert.equal(targets.capture().uiLanguage, 'zh');
assert.equal(targets.isMounted(first), false);
assert.equal(targets.parent('2'.repeat(32), 'parent'), null);
assert.throws(() => targets.capture({ timepointScope: { sessionId: sid, timepointId: '../bad' } }));
const old = targets.capture({ timepointScope: { sessionId: sid, timepointId: null, legacyDefault: true } });
assert(targets.headers(old).has('X-BrachyBot-Timepoint'));
assert.equal(targets.headers(old).get('X-BrachyBot-Timepoint'), '');
console.log('chat target capture, queue, retry, parent, locale and late-paint fences passed');
