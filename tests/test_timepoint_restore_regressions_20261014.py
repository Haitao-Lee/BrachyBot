"""Ownership and nested-mutation safeguards for the large-case restore fixes."""
import numpy as np
from web.timepoint_chat import _state_token
from web.workspace_store import WorkspaceStore


def test_fast_state_tokens_still_detect_nested_edits_and_array_replacement():
    array = np.ones((2, 3), np.float32)
    values = {"dvh": {"bins": [1., 2., 3.]}, "mask": array, "tuple": (2, 4)}
    original = _state_token(values)
    assert original == _state_token(values)
    values["dvh"]["bins"][1] = 5.
    assert original != _state_token(values)
    changed = _state_token(values)
    values["mask"] = array.copy()
    assert changed != _state_token(values)
    assert _state_token({"a": 1, "b": 2}) == _state_token({"b": 2, "a": 1})


def test_shared_projection_never_exposes_or_mutates_other_clinical_state(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    store = WorkspaceStore(tmp_path / "runtime")
    uid = store.create_user("restore_owner", "synthetic-hash")["id"]
    sid = store.create_session(uid, "Synthetic source").id
    store.save_snapshot_patch(uid, sid, {"agent": {"planning_results": {"dose_metrics": {"v100": .91}},
        "context_summary": "Synthetic shared context"}, "ui": {"state": {"marker": "retain"}},
        "chat": {"messages": [{"type": "user", "content": "Synthetic message"}]}})
    # Browser patching intentionally cannot write clinical Agent results.
    # Set up that pre-existing durable clinical section through the store.
    saved = store.load_snapshot(uid, sid)
    saved["agent"]["planning_results"] = {"dose_metrics": {"v100": .91}}
    store._write_snapshot(uid, store._snapshot_path(uid, sid), saved)
    for _ in range(2):
        projected = store.load_snapshot(uid, sid, shared_only=True)
        assert "planning_results" not in projected["agent"]
        assert "ui" not in projected
        projected["chat"]["messages"][0]["content"] = "Modified detached projection"
    full = store.load_snapshot(uid, sid)
    assert full["agent"]["planning_results"]["dose_metrics"]["v100"] == .91
    assert full["ui"]["state"]["marker"] == "retain"
    assert full["chat"]["messages"][0]["content"] == "Synthetic message"


def test_actual_empty_workspace_chrome_and_defaults(tmp_path, monkeypatch):
    import os, subprocess, threading
    from pathlib import Path
    from werkzeug.serving import make_server
    from web.server import create_app
    import pytest
    node = os.environ.get("BRACHYBOT_NODE")
    if not node or not os.environ.get("PLAYWRIGHT_MODULE"):
        pytest.skip("Actual browser chrome requires the installed Playwright runtime")
    monkeypatch.setenv("BRACHYBOT_ALLOW_SELF_REGISTRATION", "1")
    monkeypatch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(tmp_path / "archive"))
    for key in ("BRACHYBOT_API_KEY", "BRACHYBOT_REQUIRE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    app = create_app({"runtime_dir": str(tmp_path / "runtime"), "secret_key": "synthetic-chrome-test", "workspace_maintenance": False})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        result = subprocess.run([node, str(Path(__file__).with_name("five-issues-chrome.test.cjs")),
            f"http://127.0.0.1:{server.server_port}"], capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown(); thread.join(5)
