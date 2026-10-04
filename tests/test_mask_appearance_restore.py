"""Durable appearance and actual cross-module browser restoration contracts."""
import copy
from pathlib import Path
import shutil
import subprocess

import pytest

from web.workspace_store import WorkspaceStore


ROOT = Path(__file__).resolve().parents[1]


def test_real_mask_presentation_restore_runtime():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the cross-module mask restore harness")
    result = subprocess.run(
        [node, str(ROOT / "tests/mask-appearance-restore.test.cjs"), str(ROOT)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"passed":14,"failed":0' in result.stdout


def test_saved_mask_appearance_survives_cold_store_reload_and_case_switch(tmp_path):
    """Use private synthetic storage; never inspect or mutate a patient case."""
    runtime = tmp_path / "isolated-runtime"
    store = WorkspaceStore(runtime)
    user = store.create_user("mask-appearance-test", "synthetic-password-hash")
    case_a = store.create_session(user["id"], "Appearance A")
    case_b = store.create_session(user["id"], "Appearance B")
    masks = {
        "upload_a_label_2": {"mask_id": "upload_a_label_2", "name": "Label 2",
                             "color": "#112233", "opacity": 0.0, "visible3D": False},
        "upload_b_label_2": {"mask_id": "upload_b_label_2", "name": "Label 2",
                             "color": "#445566", "opacity": 0.91, "visible2D": False},
    }
    original = copy.deepcopy(masks)
    store.save_snapshot_patch(user["id"], case_a.id, {
        "ui": {"state": {"viewer": {"masks": {"labels": masks}}}},
    })
    store.save_snapshot_patch(user["id"], case_b.id, {
        "ui": {"state": {"viewer": {"masks": {"labels": {
            "upload_a_label_2": {"color": "#abcdef", "opacity": 0.72},
        }}}}},
    })
    # Closing the old store object is not assumed to serialize browser state;
    # the completed writes themselves are what a restarted process can read.
    fresh = WorkspaceStore(runtime)
    for case_id in (case_b.id, case_a.id, case_b.id, case_a.id):
        saved = fresh.load_snapshot(user["id"], case_id)
        labels = saved["ui"]["state"]["viewer"]["masks"]["labels"]
        if case_id == case_a.id:
            assert labels == original
        else:
            assert labels["upload_a_label_2"]["color"] == "#abcdef"
    # A chat-only patch during resource loading must not erase stored styles.
    fresh.save_snapshot_patch(user["id"], case_a.id, {"chat": {"messages": []}})
    assert fresh.load_snapshot(user["id"], case_a.id)["ui"]["state"]["viewer"]["masks"]["labels"] == original
