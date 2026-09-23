"""Contract for reversible, non-absolute path presentation in the browser."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from utils.display_paths import (
    APP_TOKEN,
    GENERIC_TOKEN,
    RUNTIME_TOKEN,
    WORKSPACE_TOKEN,
    DisplayRoots,
    relativize_text,
    relativize_value,
    resolve_user_path,
    restore_value_in_place,
    roots_from_config,
    roots_from_workspace,
)


def _roots(tmp_path: Path) -> DisplayRoots:
    app = tmp_path / "BrachyBot"
    runtime = app / ".runtime"
    workspace = runtime / "workspaces" / "user1" / "session1"
    (workspace / "inputs").mkdir(parents=True)
    return roots_from_workspace(str(workspace))


def test_workspace_path_becomes_workspace_token(tmp_path):
    roots = _roots(tmp_path)
    ct = os.path.join(roots.workspace_root, "inputs", "CTzhouqun.nii")
    assert relativize_text(ct, roots) == f"{WORKSPACE_TOKEN}/inputs/CTzhouqun.nii"


def test_longest_prefix_wins(tmp_path):
    roots = _roots(tmp_path)
    # A workspace path is also under the runtime and app trees; the workspace
    # token must win.
    ct = os.path.join(roots.workspace_root, "inputs", "CT.nii")
    rendered = relativize_text(ct, roots)
    assert rendered.startswith(WORKSPACE_TOKEN)
    assert RUNTIME_TOKEN not in rendered and APP_TOKEN not in rendered


def test_runtime_and_app_paths_use_their_tokens(tmp_path):
    roots = _roots(tmp_path)
    runtime_file = os.path.join(roots.runtime_dir, "logs", "server.log")
    app_file = os.path.join(roots.app_root, "web", "server.py")
    assert relativize_text(runtime_file, roots) == f"{RUNTIME_TOKEN}/logs/server.log"
    assert relativize_text(app_file, roots) == f"{APP_TOKEN}/web/server.py"


def test_embedded_path_inside_longer_message(tmp_path):
    roots = _roots(tmp_path)
    ct = os.path.join(roots.workspace_root, "inputs", "CT.nii")
    message = f"Path does not exist: {ct} (retry)"
    assert relativize_text(message, roots) == (
        f"Path does not exist: {WORKSPACE_TOKEN}/inputs/CT.nii (retry)"
    )


def test_unknown_absolute_path_keeps_only_basename():
    assert relativize_text("/opt/vendor/lib/model.bin") == f"{GENERIC_TOKEN}/model.bin"
    assert relativize_text("see /tmp/scratch/output.nii.gz now") == (
        f"see {GENERIC_TOKEN}/output.nii.gz now"
    )


def test_fraction_and_url_are_left_alone():
    assert relativize_text("DVH 0.9/1.0 target") == "DVH 0.9/1.0 target"
    assert relativize_text("https://example.com/a/b") == "https://example.com/a/b"


def test_relativize_value_walks_containers(tmp_path):
    roots = _roots(tmp_path)
    ct = os.path.join(roots.workspace_root, "inputs", "CT.nii")
    payload = {
        "step": "full",
        "ct_image_path": ct,
        "seed_info": {"note": f"loaded {ct}"},
        "paths": [ct, "/tmp/other.nii"],
    }
    rendered = relativize_value(payload, roots)
    assert rendered["ct_image_path"] == f"{WORKSPACE_TOKEN}/inputs/CT.nii"
    assert rendered["seed_info"]["note"] == f"loaded {WORKSPACE_TOKEN}/inputs/CT.nii"
    assert rendered["paths"] == [
        f"{WORKSPACE_TOKEN}/inputs/CT.nii",
        f"{GENERIC_TOKEN}/other.nii",
    ]


def test_resolve_round_trips_known_tokens(tmp_path):
    roots = _roots(tmp_path)
    ct = os.path.join(roots.workspace_root, "inputs", "CT.nii")
    rendered = relativize_text(ct, roots)
    assert resolve_user_path(rendered, roots) == ct
    assert resolve_user_path(WORKSPACE_TOKEN, roots) == roots.workspace_root
    assert resolve_user_path(f"{RUNTIME_TOKEN}/logs/server.log", roots) == os.path.join(
        roots.runtime_dir, "logs", "server.log"
    )
    assert resolve_user_path(f"{APP_TOKEN}/web/server.py", roots) == os.path.join(
        roots.app_root, "web", "server.py"
    )


def test_resolve_plain_path_is_unchanged(tmp_path):
    roots = _roots(tmp_path)
    plain = os.path.join(roots.workspace_root, "inputs", "CT.nii")
    assert resolve_user_path(plain, roots) == plain
    assert resolve_user_path("outputs/plan.json", roots) == "outputs/plan.json"


def test_restore_value_in_place_round_trips_nested(tmp_path):
    roots = _roots(tmp_path)
    ct = os.path.join(roots.workspace_root, "inputs", "CT.nii")
    payload = {"a": [{"p": ct, "note": f"loaded {ct}"}], "b": {"q": [ct]}}
    rendered = relativize_value(payload, roots)
    assert ct not in str(rendered)
    restored = restore_value_in_place(rendered, roots)
    assert restored is rendered
    assert restored["a"][0]["p"] == ct
    # Free text keeps its token form; only whole-value path fields round-trip.
    assert restored["a"][0]["note"] == f"loaded {WORKSPACE_TOKEN}/inputs/CT.nii"
    assert restored["b"]["q"] == [ct]


def test_resolve_generic_token_by_unique_basename(tmp_path):
    roots = _roots(tmp_path)
    target = Path(roots.workspace_root) / "outputs" / "report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    assert resolve_user_path(f"{GENERIC_TOKEN}/report.json", roots) == str(target)


def test_resolve_ambiguous_generic_token_is_returned_unchanged(tmp_path):
    roots = _roots(tmp_path)
    for name in ("a", "b"):
        folder = Path(roots.workspace_root) / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "dup.nii").write_text("x", encoding="utf-8")
    assert resolve_user_path(f"{GENERIC_TOKEN}/dup.nii", roots) == f"{GENERIC_TOKEN}/dup.nii"


def test_missing_roots_only_apply_generic_fallback():
    ct = "/home/someone/case/inputs/CT.nii"
    assert relativize_text(ct, DisplayRoots()) == f"{GENERIC_TOKEN}/CT.nii"


def test_roots_from_config_reads_workspace_root(tmp_path):
    roots = _roots(tmp_path)
    derived = roots_from_config({"_workspace_root": roots.workspace_root})
    assert derived.workspace_root == roots.workspace_root
    assert derived.runtime_dir == roots.runtime_dir
    assert derived.app_root == roots.app_root


def test_server_hooks_relativize_and_restore(tmp_path):
    """The Flask before/after hooks must tokenize out and resolve in."""
    from flask import jsonify, request as flask_request

    from web.server import create_app

    app = create_app({
        "runtime_dir": str(tmp_path / "runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })

    @app.route("/api/_display_echo", methods=["POST"])
    def _echo():
        body = flask_request.get_json() or {}
        value = str(body.get("p") or "")
        return jsonify({"seen": value, "exists": os.path.exists(value)})

    client = app.test_client()
    registration = client.post(
        "/api/auth/register",
        json={"username": "tester01", "password": "bridge-password-123"},
    ).get_json()
    response = client.post(
        "/api/_display_echo",
        json={"p": f"{APP_TOKEN}/web/server.py"},
        headers={"X-CSRF-Token": registration["csrf_token"]},
    )
    payload = response.get_json()
    # Inbound: the token was resolved to the real file before the route ran.
    assert payload["exists"] is True
    # Outbound: the absolute path in the response was tokenized again.
    assert payload["seen"] == f"{APP_TOKEN}/web/server.py"


def test_publish_relativizes_step_events(tmp_path):
    from web.chat_tasks import ChatTask

    roots = _roots(tmp_path)
    ct = os.path.join(roots.workspace_root, "inputs", "CT.nii")

    class _Agent:
        config = {"_workspace_root": roots.workspace_root}

    task = ChatTask(
        task_id="t1", user_id="u1", session_id="s1", agent=_Agent(), message="hi"
    )
    task.publish(task.encode_event("step", {
        "id": 1,
        "type": "tool",
        "tool": "planning_pipeline",
        "params": {"ct_image_path": ct, "mode": "rl"},
    }))
    assert task.steps[0]["params"]["ct_image_path"] == f"{WORKSPACE_TOKEN}/inputs/CT.nii"
    # The replay journal must match the stored step, not the leaked original.
    assert ct not in task._events[-1]
    assert f"{WORKSPACE_TOKEN}/inputs/CT.nii" in task._events[-1]

