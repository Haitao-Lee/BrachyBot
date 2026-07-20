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


def test_review_feedback_stays_internal_and_needle_overlay_is_entry_clipped():
    workflows = (ROOT / "agent_runtime/chat_workflows.py").read_text(encoding="utf-8")
    overlay = (ROOT / "web/app/static/js/brachybot-manual-annotation.js").read_text(encoding="utf-8")
    assert "review_feedback = []" in workflows
    assert 'self.memory.store("last_review_feedback", review_feedback)' in workflows
    assert "response += \"\\n\\n---\\n\"" not in workflows
    assert "const segmentStart = p1" in overlay
    assert "const segmentEnd = hit" in overlay
    assert "ctx.arc(hit.x" not in overlay


def test_reference_direction_mode_is_explicit_and_auto_wins_stale_vectors():
    core = (ROOT / "agent_runtime/core.py").read_text(encoding="utf-8")
    ui_api = (ROOT / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    routes = (ROOT / "web/routes/planning_routes.py").read_text(encoding="utf-8")
    assert "def resolve_reference_direction_input" in core
    assert "ref_direc_auto: refAuto" in (ROOT / "web/app/static/js/brachybot-manual-annotation.js").read_text(encoding="utf-8")
    assert "reference_direc_mode" in ui_api
    assert "resolve_reference_direction_input(" in routes


def test_planning_pipeline_reads_live_ui_direction_before_provider_vector():
    from tool_factory.seed_plan.planning_pipeline import _ui_reference_direction_input

    class Memory:
        def __init__(self, state):
            self.state = state

        def get_ui_state(self):
            return self.state

    class Agent:
        def __init__(self, state):
            self.memory = Memory(state)

    assert _ui_reference_direction_input(Agent({
        "planning": {
            "ref_direc_auto": True,
            "reference_direc": [0, -1, 0],
            "reference_direc_mode": "auto",
        }
    })) == "auto"
    assert _ui_reference_direction_input(Agent({
        "planning": {
            "ref_direc_auto": False,
            "reference_direc": [0, -1, 0],
            "reference_direc_mode": "manual",
        }
    })) == [0.0, -1.0, 0.0]
    assert _ui_reference_direction_input(Agent({})) is None


def test_reference_direction_schema_accepts_auto_and_numeric_vectors():
    source = (ROOT / "tool_factory/seed_plan/planning_pipeline.py").read_text(encoding="utf-8")
    assert '"oneOf": [' in source
    assert '"enum": ["auto", "auto_detect"]' in source
    assert "_reference_direction_user_override" in source
    ui_api = (ROOT / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    assert "referenceDirectionSyncBound" in ui_api


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
