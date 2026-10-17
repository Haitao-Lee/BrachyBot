from pathlib import Path

from agent_runtime.timepoint_tools import owned_tool_arguments
from test_agent_timepoint_boundary import activate


pytest_plugins = ["test_agent_timepoint_boundary"]


ROOT = Path(__file__).resolve().parents[1]


def test_scoped_planning_drops_transport_paths(owned):
    """A detached timepoint must use its captured clinical inputs."""
    runtime = activate(owned)
    runtime._waiter(True)
    try:
        args = owned_tool_arguments(runtime.view, "planning_pipeline", {
            "ct_image_path": "inputs/timepoints/owned/images/ct/volume.nii.gz",
            "ctv_mask_path": "inputs/timepoints/owned/masks/ctv.nii.gz",
            "oar_mask_path": "inputs/timepoints/owned/masks/oar.nii.gz",
            "step": "full",
            "mode": "rule_based",
        })
        assert args["step"] == "full"
        assert args["mode"] == "rule_based"
        assert args["_agent"] is runtime.view
        assert "ct_image_path" not in args
        assert "ctv_mask_path" not in args
        assert "oar_mask_path" not in args
    finally:
        runtime.close()


def test_scoped_ct_segmentation_drops_legacy_image_selector(owned):
    runtime = activate(owned)
    runtime._waiter(True)
    try:
        args = owned_tool_arguments(runtime.view, "ctv_segmentation", {
            "image_path": "inputs/timepoints/owned/images/ct/volume.nii.gz",
            "tumor_type": "liver",
        })
        assert args["tumor_type"] == "liver"
        assert "image_path" not in args
    finally:
        runtime.close()


def test_terminal_planning_refresh_is_background_restore():
    chat = (ROOT / "web/app/static/js/brachybot-chat-todo.js").read_text(encoding="utf-8")
    assert "backgroundRestore: true" in chat
    assert "optional 3D meshes hydrate in the background" in chat
    assert "Do not await this promise here" in chat
    assert "await outcome.backgroundCompletion" not in chat


def test_background_restore_does_not_hold_global_3d_spinner():
    planning = (ROOT / "web/app/static/js/brachybot-dvh-planning.js").read_text(encoding="utf-8")
    expected = "!options.hydrationScope && options.backgroundRestore !== true"
    assert planning.count(expected) >= 3


def test_viewer_discards_stale_loading_tokens_and_silent_tokens_are_nonblocking():
    layout = (ROOT / "web/app/static/js/brachybot-viewer-layout.js").read_text(encoding="utf-8")
    assert "tokenGenerations: new Map()" in layout
    assert "_viewer3DLoadingState.tokenGenerations.delete(token)" in layout
    assert "if (generation < _viewer3DRequestGeneration)" in layout
    assert "const loadingToken = !silent" in layout
