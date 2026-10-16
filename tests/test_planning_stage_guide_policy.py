from types import SimpleNamespace

from agent_runtime.planning_stage import active_planning_stage, should_auto_generate_guide


def _owner(stage):
    return SimpleNamespace(
        _workspace_timepoint_context=SimpleNamespace(
            target=SimpleNamespace(stage=stage),
        ),
    )


def test_preoperative_planning_derives_guide():
    owner = _owner("preoperative")
    assert active_planning_stage(owner) == "preoperative"
    assert should_auto_generate_guide(owner, "请重新执行规划") is True


def test_intraoperative_replan_does_not_derive_guide():
    owner = _owner("intraoperative")
    assert active_planning_stage(owner) == "intraoperative"
    assert should_auto_generate_guide(owner, "请重新执行规划") is False


def test_explicit_intraoperative_guide_request_is_preserved():
    owner = _owner("intraoperative")
    assert should_auto_generate_guide(owner, "请重新生成手术导板") is True


def test_legacy_workspace_keeps_preoperative_compatibility():
    owner = SimpleNamespace()
    assert active_planning_stage(owner) == ""
    assert should_auto_generate_guide(owner, "run the treatment plan") is True

