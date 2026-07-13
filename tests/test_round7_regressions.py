from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_replan_reverses_current_ui_direction_and_reuses_masks():
    from AgenticSys import BrachyAgent

    class Memory:
        def __init__(self):
            self.ui = {"planning": {"reference_direc": [1, 0, 0]}}

        def retrieve(self, key, default=None):
            if key == "ctv_array":
                return [1]
            if key == "oar_array":
                return [1]
            if key == "oar_is_full":
                return True
            return default

        def get_ui_state(self):
            return self.ui

    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    agent.config = {"reference_direc": [0, -1, 0]}
    agent._has_completed_planning = lambda *_args, **_kwargs: True
    agent._current_ct_path = lambda *_args, **_kwargs: "/tmp/case.nii.gz"

    calls = [{"tool": "planning_pipeline", "params": {"step": "full"}}]
    routed = agent._normalize_clinical_tool_calls(calls, "请把 reference direction 反向再规划一遍")

    assert [call["tool"] for call in routed] == ["planning_pipeline"]
    assert routed[0]["params"]["ref_direc"] == [-1.0, 0.0, 0.0]
    assert agent._is_replan_request("请重新规划") is True
    assert agent._is_replan_request("介绍放射性粒子植入的好处") is False

    injected = agent._normalize_clinical_tool_calls(
        [{"tool": "completeness_checker", "params": {}}], "请重新规划"
    )
    assert injected[0]["tool"] == "planning_pipeline"


def test_chat_renders_only_reviewed_response_event():
    source = (ROOT / "web/app/static/js/brachybot-chat-todo.js").read_text(encoding="utf-8")
    assert "let finalResponseReceived = false;" in source
    assert "if (!finalResponseReceived)" in source
    assert "finalResponseReceived = true;" in source
    assert "const finalText = finalResponseReceived" in source


def test_viewer_and_data_tree_regressions_are_explicitly_covered():
    index = (ROOT / "web/app/index.html").read_text(encoding="utf-8")
    ui_api = (ROOT / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    viewer = (ROOT / "web/app/static/js/brachybot-viewer-volume.js").read_text(encoding="utf-8")
    layout = (ROOT / "web/app/static/js/brachybot-viewer-layout.js").read_text(encoding="utf-8")
    manual_3d = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    dvh = (ROOT / "web/app/static/js/brachybot-dvh-planning.js").read_text(encoding="utf-8")

    assert '<html lang="en" data-theme="dark">' in index
    assert "reference_direc:" in ui_api
    assert "state.viewerSettings.threshold = null" in viewer
    assert "const raw = document.getElementById('viewerThreshold')?.value?.trim() || ''" in viewer
    assert "category === 'planning'" in viewer
    assert "category === 'planning_trajectories'" in viewer
    assert "async function loadLabelVolumes()" in viewer
    assert "opts.allOAR" in manual_3d
    assert "const doseFraction" not in dvh
    assert "const cursorDose =" in dvh
    assert "_interpolateDvhAtDose(best.traceX, best.traceY, displayDose)" in dvh
