"""Runtime regression coverage for durable browser case transitions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for browser bridge runtime coverage")
def test_reconcile_active_session_replaces_a_stale_browser_case():
    """A deleted/stale local case must be replaced before an upload starts."""

    bridge = (ROOT / "web/app/static/js/brachybot-workspace.js").as_posix()
    script = rf"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const stale = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const durable = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
global.window = {{}};
global.document = {{
  body: {{ classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }} }},
  getElementById() {{ return null; }},
  querySelectorAll() {{ return []; }},
}};
global.sessions = {{ [stale]: {{ id: stale, title: 'Stale case', messages: [] }} }};
global.activeSessionId = stale;
global.state = {{ sessionId: stale }};
global.renderSessionList = () => {{}};
global.fetch = async (url) => {{
  assert.strictEqual(url, '/api/sessions');
  return {{ ok: true, json: async () => ({{
    active_session_id: durable,
    sessions: [{{ id: durable, title: 'Durable case', created_at: 1, updated_at: 2 }}],
    trashed_count: 0,
  }}) }};
}};

vm.runInThisContext(fs.readFileSync('{bridge}', 'utf8'), {{ filename: 'brachybot-workspace.js' }});
(async () => {{
  const resolved = await window.reconcileActiveSession(stale);
  assert.strictEqual(resolved, durable);
  assert.strictEqual(activeSessionId, durable);
  assert.strictEqual(state.sessionId, durable);
  assert.deepStrictEqual(Object.keys(sessions), [durable]);
  process.exit(0);
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for browser bridge runtime coverage")
def test_second_case_transition_cannot_overtake_first_request():
    """A slow create cannot be overtaken by a second sidebar click.

    This uses the real browser bridge in a small DOM/fetch harness. Source
    assertions alone would not prove that the asynchronous gate is held while
    the first network request is unresolved.
    """

    bridge = (ROOT / "web/app/static/js/brachybot-workspace.js").as_posix()
    script = rf"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

let releaseCreate;
const createGate = new Promise(resolve => {{ releaseCreate = resolve; }});
let oldCaseFlushStarted = false;
const bodyClasses = new Set();
const sidebar = {{ setAttribute() {{}} }};
global.window = {{ _chatTurnActive: false, _chatStreaming: false }};
global.document = {{
  body: {{ classList: {{ toggle(name, active) {{ active ? bodyClasses.add(name) : bodyClasses.delete(name); }}, add(name) {{ bodyClasses.add(name); }}, remove(name) {{ bodyClasses.delete(name); }} }} }},
  getElementById(id) {{ return id === 'sessionSidebar' ? sidebar : null; }},
  querySelectorAll() {{ return []; }},
}};
global.sessions = {{ old: {{ id: 'old', title: 'Existing case', messages: [] }} }};
global.activeSessionId = 'old';
global.renderSessionList = () => {{}};
global.loadSessionChat = () => {{}};
global.flushActiveReportState = () => {{
  oldCaseFlushStarted = true;
  return new Promise(() => {{}});
}};
global.fetch = async (url, options = {{}}) => {{
  if (url === '/api/sessions' && options.method === 'POST') {{
    await createGate;
    return {{ ok: true, json: async () => ({{
      success: true,
      session: {{ id: 'new', title: 'New case', created_at: 2, updated_at: 2 }},
      active_session_id: 'new',
      workspace: {{ session_id: 'new', session: {{ id: 'new', revision: 1 }} }},
    }}) }};
  }}
  if (url === '/api/sessions') {{
    return {{ ok: true, json: async () => ({{
      active_session_id: 'new',
      sessions: [
        {{ id: 'old', title: 'Existing case', created_at: 1, updated_at: 1 }},
        {{ id: 'new', title: 'New case', created_at: 2, updated_at: 2 }},
      ],
    }}) }};
  }}
  if (url === '/api/workspace/snapshot') {{
    return {{ ok: true, json: async () => ({{ workspace: {{ session_id: 'new', session: {{ id: 'new', revision: 1 }} }} }}) }};
  }}
  throw new Error('Unexpected request: ' + url);
}};

vm.runInThisContext(fs.readFileSync('{bridge}', 'utf8'), {{ filename: 'brachybot-workspace.js' }});
async function waitFor(predicate, timeoutMs = 100) {{
  const deadline = Date.now() + timeoutMs;
  while (!predicate() && Date.now() < deadline) {{
    await new Promise(resolve => setTimeout(resolve, 1));
  }}
  return predicate();
}}
(async () => {{
  const first = window.newChat();
  // The bridge intentionally yields an animation-frame/task boundary so the
  // new shell can paint before it serializes the previous case. Await the
  // resulting state transition instead of imposing a platform-specific tick.
  assert.strictEqual(
    await waitFor(() => oldCaseFlushStarted),
    true,
    'old-case flush did not start after the first-paint boundary',
  );
  assert(bodyClasses.has('workspace-transitioning'), 'first transition should mark the sidebar busy');
  const second = await window.newChat();
  assert.strictEqual(second.success, false);
  assert.strictEqual(second.busy, true);
  releaseCreate();
  const result = await Promise.race([
    first,
    new Promise((_, reject) => setTimeout(() => reject(new Error('first transition timed out')), 2000)),
  ]);
  assert.strictEqual(result.success, true, 'first transition result: ' + JSON.stringify(result));
  assert.strictEqual(activeSessionId, 'new');
  assert(!bodyClasses.has('workspace-transitioning'), 'busy state should clear after completion');
  // The real bridge intentionally owns deferred UI timers. Explicitly finish
  // this isolated Node harness once its assertions have completed.
  process.exit(0);
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for browser bridge runtime coverage")
def test_late_scene_restore_cannot_repaint_newer_case():
    """Delayed viewer restoration must be cancelled when another case wins."""

    bridge = (ROOT / "web/app/static/js/brachybot-workspace.js").as_posix()
    script = rf"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const nativeSetTimeout = global.setTimeout;
global.setTimeout = (callback, delay) => nativeSetTimeout(callback, Math.min(Number(delay) || 0, 5));
global.window = {{}};
global.document = {{
  body: {{ classList: {{ toggle() {{}} }} }},
  getElementById() {{ return null; }},
  querySelectorAll() {{ return []; }},
}};
global.state = {{ slices: {{}}, viewerSettings: {{}}, doseTexture: {{ enabled: false }} }};
global.sessions = {{
  a: {{ id: 'a', title: 'Case A', messages: [] }},
  b: {{ id: 'b', title: 'Case B', messages: [] }},
}};
global.activeSessionId = 'a';
global.scene3D = {{
  camera: {{
    position: {{ values: [0, 0, 0], fromArray(value) {{ this.values = value.slice(); }} }},
    quaternion: {{ fromArray() {{}} }},
    updateProjectionMatrix() {{}}
  }},
  controls: {{
    target: {{ fromArray() {{}} }}, update() {{}}, addEventListener() {{}}
  }},
  requestRender() {{}}
}};
global.renderDataTree = () => {{}};

vm.runInThisContext(fs.readFileSync('{bridge}', 'utf8'), {{ filename: 'brachybot-workspace.js' }});
(async () => {{
  await window.applyWorkspaceSnapshot({{
    session_id: 'a',
    session: {{ id: 'a', revision: 1 }},
    ui: {{ state: {{ viewer: {{ scene: {{ camera_position: [1, 1, 1] }} }} }} }},
  }});
  global.activeSessionId = 'b';
  await window.applyWorkspaceSnapshot({{
    session_id: 'b',
    session: {{ id: 'b', revision: 1 }},
    ui: {{ state: {{ viewer: {{ scene: {{ camera_position: [9, 8, 7] }} }} }} }},
  }});
  await new Promise(resolve => nativeSetTimeout(resolve, 30));
  assert.deepStrictEqual(scene3D.camera.position.values, [9, 8, 7]);
  process.exit(0);
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for browser bridge runtime coverage")
def test_delayed_workspace_save_remains_bound_to_origin_case():
    """A save started in case A must not become a save for case B."""

    bridge = (ROOT / "web/app/static/js/brachybot-workspace.js").as_posix()
    script = rf"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

let releaseSave;
const saveGate = new Promise(resolve => {{ releaseSave = resolve; }});
let captured = null;
global.window = {{ brachybotAuth: {{ user: {{ id: 'u1' }} }} }};
global.document = {{
  body: {{ classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }} }},
  getElementById() {{ return null; }},
  querySelectorAll() {{ return []; }},
}};
global.sessions = {{
  a: {{ id: 'a', title: 'Case A', messages: [] }},
  b: {{ id: 'b', title: 'Case B', messages: [] }},
}};
global.activeSessionId = 'a';
global.fetch = async (url, options = {{}}) => {{
  if (url !== '/api/workspace/state') throw new Error('Unexpected request: ' + url);
  captured = {{ options, body: JSON.parse(options.body) }};
  await saveGate;
  return {{ ok: true, status: 200, json: async () => ({{ success: true, revision: 2 }}) }};
}};

vm.runInThisContext(fs.readFileSync('{bridge}', 'utf8'), {{ filename: 'brachybot-workspace.js' }});
(async () => {{
  const pending = window.persistWorkspace('runtime.test');
  global.activeSessionId = 'b';
  releaseSave();
  await pending;
  assert(captured, 'workspace save was not issued');
  assert.strictEqual(captured.options.headers['X-BrachyBot-Session'], 'a');
  assert.strictEqual(captured.body.session_id, 'a');
  process.exit(0);
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for browser bridge runtime coverage")
def test_workspace_save_retries_once_after_checkpoint_revision_conflict():
    """A checkpoint race must refresh the CAS revision instead of stranding UI saves."""

    bridge = (ROOT / "web/app/static/js/brachybot-workspace.js").as_posix()
    script = rf"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const requests = [];
global.window = {{ brachybotAuth: {{ user: {{ id: 'u1' }} }} }};
global.document = {{
  body: {{ classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }} }},
  getElementById() {{ return null; }},
  querySelectorAll() {{ return []; }},
}};
global.sessions = {{ a: {{ id: 'a', title: 'Case A', messages: [] }} }};
global.activeSessionId = 'a';
global.fetch = async (url, options = {{}}) => {{
  if (url !== '/api/workspace/state') throw new Error('Unexpected request: ' + url);
  const body = JSON.parse(options.body);
  requests.push(body);
  if (requests.length === 1) {{
    // A real Session switch can happen while the first request is waiting on
    // a server checkpoint. The retry must retain A's complete payload.
    global.activeSessionId = 'b';
    return {{ ok: false, status: 409, json: async () => ({{
      code: 'stale_workspace', current_revision: 17,
    }}) }};
  }}
  return {{ ok: true, status: 200, json: async () => ({{ success: true, revision: 18 }}) }};
}};

vm.runInThisContext(fs.readFileSync('{bridge}', 'utf8'), {{ filename: 'brachybot-workspace.js' }});
(async () => {{
  const saved = await window.persistWorkspace('runtime.revision-race');
  assert.strictEqual(saved, true);
  assert.strictEqual(requests.length, 2, 'only one controlled retry is allowed');
  assert.strictEqual(requests[1].revision, 17, 'retry must use the authoritative revision');
  assert.strictEqual(requests[1].session_id, 'a', 'retry must retain the owner case');
  assert.deepStrictEqual(requests[1].ui_state, requests[0].ui_state);
  assert.deepStrictEqual(requests[1].report, requests[0].report);
  assert.deepStrictEqual(requests[1].chat, requests[0].chat);
  process.exit(0);
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for browser bridge runtime coverage")
def test_chat_waits_for_authoritative_new_case_without_duplicate_submit():
    """A message entered during New Case must never target the optimistic ID."""

    bridge = (ROOT / "web/app/static/js/brachybot-workspace.js").as_posix()
    chat = (ROOT / "web/app/static/js/brachybot-chat-todo.js").as_posix()
    script = rf"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

let releaseCreate;
const createGate = new Promise(resolve => {{ releaseCreate = resolve; }});
const classNames = new Set();
const input = {{ value: '', readOnly: false, placeholder: 'Message', dataset: {{}} }};
const button = {{ disabled: false, title: '', classList: {{
  toggle(name, active) {{ active ? classNames.add(name) : classNames.delete(name); }},
  contains(name) {{ return classNames.has(name); }},
}} }};
const sidebar = {{ setAttribute() {{}} }};
let chatPosts = 0;
let errors = 0;
global.window = {{
  _chatTurnActive: false,
  _chatStreaming: false,
  dispatchEvent() {{}},
}};
global.document = {{
  body: {{ classList: {{
    toggle(name, active) {{ active ? classNames.add(name) : classNames.delete(name); }},
    add(name) {{ classNames.add(name); }},
    remove(name) {{ classNames.delete(name); }},
  }} }},
  addEventListener() {{}},
  getElementById(id) {{
    if (id === 'sessionSidebar') return sidebar;
    if (id === 'chatInput') return input;
    if (id === 'chatSendBtn') return button;
    return null;
  }},
  querySelectorAll() {{ return []; }},
}};
global.CustomEvent = function CustomEvent(name, init) {{ this.type = name; this.detail = init?.detail; }};
global._activeTodoLang = 'en';
global._TODO_I18N = {{
  en: {{ header: 'Progress', tools: {{}}, call_prefix: 'Calling ', thinking: 'Thinking', memory: 'Memory', default_processing: 'Processing' }},
  zh: {{ header: '进度', tools: {{}}, call_prefix: '调用 ', thinking: '思考', memory: '记忆', default_processing: '处理中' }},
}};
global.API = '/api';
global.trainingMonitorState = {{ active: false }};
global.sessions = {{ old: {{ id: 'old', title: 'Existing case', messages: [] }} }};
global.activeSessionId = 'old';
global.state = {{ sessionId: 'old' }};
global.collectUIState = () => {{ throw new Error('optional ui state failure'); }};
global.renderSessionList = () => {{}};
global.loadSessionChat = () => {{}};
global.clearClientWorkspace = () => {{}};
global.detectConversationLanguage = () => 'zh';
global.addChat = type => {{ if (type === 'error') errors += 1; }};
global.setStreamingState = () => {{}};
global.fetch = async (url, options = {{}}) => {{
  if (url === '/api/sessions' && options.method === 'POST') {{
    await createGate;
    return {{ ok: true, json: async () => ({{
      success: true,
      session: {{ id: '0123456789abcdef0123456789abcdef', title: 'New case', created_at: 2, updated_at: 2 }},
      active_session_id: '0123456789abcdef0123456789abcdef',
      workspace: {{ session_id: '0123456789abcdef0123456789abcdef', session: {{ id: '0123456789abcdef0123456789abcdef', revision: 1 }} }},
    }}) }};
  }}
  if (url.endsWith('/chat')) {{ chatPosts += 1; throw new Error('chat sentinel'); }}
  throw new Error('Unexpected request: ' + url);
}};

vm.runInThisContext(fs.readFileSync('{bridge}', 'utf8'), {{ filename: 'brachybot-workspace.js' }});
vm.runInThisContext(fs.readFileSync('{chat}', 'utf8'), {{ filename: 'brachybot-chat-todo.js' }});

(async () => {{
  const creating = window.newChat();
  await new Promise(resolve => setImmediate(resolve));
  const optimistic = window.activeSessionReadiness();
  assert.strictEqual(optimistic.pending, true);
  assert.strictEqual(optimistic.ready, false);

  input.value = '你好';
  const first = sendChat();
  input.value = '你好';
  const repeated = sendChat();
  assert.strictEqual(button.disabled, true);
  assert.strictEqual(window._chatSessionReadinessSubmission.text, '你好');
  releaseCreate();
  const created = await creating;
  assert.strictEqual(created.success, true);
  assert.strictEqual(await window.awaitActiveSessionReady(), '0123456789abcdef0123456789abcdef');
  await Promise.all([first, repeated]);
  assert.strictEqual(chatPosts, 1, 'one user intent must create one HTTP chat request');
  assert.strictEqual(errors, 1, 'the synthetic chat sentinel should surface only once');
  assert.strictEqual(button.disabled, false);
  process.exit(0);
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
