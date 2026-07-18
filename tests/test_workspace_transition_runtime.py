"""Runtime regression coverage for durable browser case transitions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


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
const bodyClasses = new Set();
const sidebar = {{ setAttribute() {{}} }};
global.window = {{ _chatTurnActive: false, _chatStreaming: false }};
global.document = {{
  body: {{ classList: {{ toggle(name, active) {{ active ? bodyClasses.add(name) : bodyClasses.delete(name); }} }} }},
  getElementById(id) {{ return id === 'sessionSidebar' ? sidebar : null; }},
  querySelectorAll() {{ return []; }},
}};
global.sessions = {{ old: {{ id: 'old', title: 'Existing case', messages: [] }} }};
global.activeSessionId = 'old';
global.renderSessionList = () => {{}};
global.loadSessionChat = () => {{}};
global.fetch = async (url, options = {{}}) => {{
  if (url === '/api/sessions' && options.method === 'POST') {{
    await createGate;
    return {{ ok: true, json: async () => ({{ success: true }}) }};
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
    return {{ ok: true, json: async () => ({{ workspace: {{ session: {{ revision: 1 }} }} }}) }};
  }}
  throw new Error('Unexpected request: ' + url);
}};

vm.runInThisContext(fs.readFileSync('{bridge}', 'utf8'), {{ filename: 'brachybot-workspace.js' }});
(async () => {{
  const first = window.newChat();
  await new Promise(resolve => setImmediate(resolve));
  assert(bodyClasses.has('workspace-transitioning'), 'first transition should mark the sidebar busy');
  const second = await window.newChat();
  assert.strictEqual(second.success, false);
  assert.strictEqual(second.busy, true);
  releaseCreate();
  const result = await Promise.race([
    first,
    new Promise((_, reject) => setTimeout(() => reject(new Error('first transition timed out')), 2000)),
  ]);
  assert.strictEqual(result.success, true);
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
  await window.applyWorkspaceSnapshot({{ ui: {{ state: {{ viewer: {{ scene: {{ camera_position: [1, 1, 1] }} }} }} }} }});
  await window.applyWorkspaceSnapshot({{ ui: {{ state: {{ viewer: {{ scene: {{ camera_position: [9, 8, 7] }} }} }} }} }});
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
