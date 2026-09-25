"""Visibility uses a live leaf identity, not a guide-generation or group shortcut."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent_runtime.turn_policy import classify_local_turn
from agent_runtime.ui_operations import resolve_ui_operation_request
from agent_runtime.response_tools import ResponseToolMixin


def _catalog(*guide_ids):
    leaves = [
        {
            "ref": f"data-tree:{node_id}:visibility",
            "node_id": node_id,
            "label": f"Puncture guide {index} — Show / hide",
            "aliases": [
                node_id, "surgical_guide", "planning_meshes", "导板",
                "手术导板", "穿刺导板", "surgical guide", "puncture guide",
            ],
            "kind": "data-tree-virtual",
            "panel": "viewers",
            "scope": "leaf",
            "visible": True,  # the row is actionable even when its mesh is hidden
            "object_visible": False,
            "enabled": True,
            "available": True,
            "action": {
                "target": "tree.visibility", "command": "set",
                "value": f"{node_id},on", "semantic_property": "visibility",
                "node_id": node_id,
            },
        }
        for index, node_id in enumerate(guide_ids, 1)
    ]
    group = {
        "ref": "data-tree-group:planning_meshes:visibility",
        "label": "Planning meshes — Show / hide",
        "aliases": ["planning_meshes", "导板"],
        "kind": "data-tree-group-virtual", "group": "planning_meshes",
        "scope": "group", "visible": True, "enabled": True,
        "available": True,
        "action": {
            "target": "tree.group.visibility", "command": "set",
            "value_template": "planning_meshes,{value}",
            "semantic_property": "visibility", "group": "planning_meshes",
        },
    }
    return {"ui_operation_catalog": [*leaves, group]}


@pytest.mark.parametrize("message", [
    "ok，帮我把导板显示出来把", "ok，帮我把导板显示出来",
    "请显示导板", "请把手术导板显示出来", "Show the surgical guide",
])
def test_single_hidden_guide_is_shown_by_its_own_live_node(message):
    ui_state = _catalog("guide_mesh_v1")
    operation = resolve_ui_operation_request(message, ui_state)
    assert operation["actions"] == [
        {"target": "tree.visibility", "command": "set", "value": "guide_mesh_v1,on"}
    ]
    policy = classify_local_turn(message, ui_state=ui_state)
    assert policy.intent == "ui_operation"
    assert policy.direct_execution
    assert policy.ui_operation["actions"] == operation["actions"]
    assert "surgical_guide" not in policy.execution_grants


def test_hiding_one_guide_does_not_hide_other_planning_meshes():
    ui_state = _catalog("guide_mesh_v1")
    operation = resolve_ui_operation_request("请隐藏导板", ui_state)
    assert operation["actions"] == [
        {"target": "tree.visibility", "command": "set", "value": "guide_mesh_v1,off"}
    ]
    assert classify_local_turn("请隐藏导板", ui_state=ui_state).direct_execution


def test_visibility_request_materializes_only_one_controller_action():
    ui_state = _catalog("guide_mesh_v1")
    agent = ResponseToolMixin()
    agent.memory = SimpleNamespace(
        get_ui_state=lambda: ui_state,
        retrieve=lambda _key: None,
        conversation=[],
    )
    agent._active_turn_policy = classify_local_turn(
        "ok，帮我把导板显示出来", ui_state=ui_state,
    )
    calls = agent._detect_tool_request("ok，帮我把导板显示出来")
    assert calls == [{
        "id": "tool_direct_ui_operation",
        "tool": "ui_controller",
        "params": {"actions": [
            {"target": "tree.visibility", "command": "set", "value": "guide_mesh_v1,on"},
        ]},
    }]


def test_unloaded_guide_does_not_fall_back_to_showing_all_meshes():
    ui_state = _catalog()
    operation = resolve_ui_operation_request("请显示导板", ui_state)
    assert not operation["actions"]
    assert operation["ambiguous"]
    policy = classify_local_turn("请显示导板", ui_state=ui_state)
    assert not policy.direct_execution
    assert not policy.execution_grants


def test_two_matching_guides_require_disambiguation():
    ui_state = _catalog("guide_mesh_v1", "guide_mesh_v2")
    operation = resolve_ui_operation_request("请显示导板", ui_state)
    assert operation["ambiguous"]
    assert not operation["actions"]
    assert not classify_local_turn("请显示导板", ui_state=ui_state).direct_execution


@pytest.mark.parametrize("message", [
    "导板在哪里", "不要显示导板", "如果有导板就显示出来",
    "‘请显示导板’这句话什么意思？",
])
def test_location_negation_condition_and_quotation_do_not_change_visibility(message):
    policy = classify_local_turn(message, ui_state=_catalog("guide_mesh_v1"))
    assert not (policy.intent == "ui_operation" and policy.direct_execution)


def test_explicit_group_request_remains_a_group_operation():
    ui_state = _catalog("guide_mesh_v1")
    operation = resolve_ui_operation_request("请显示所有导板", ui_state)
    assert operation["actions"] == [
        {"target": "tree.group.visibility", "command": "set", "value": "planning_meshes,show"}
    ]
    # A broad group operation is deliberately not promoted to the leaf-only
    # fast path merely because the same catalogue also contains one guide.
    assert not classify_local_turn("请显示所有导板", ui_state=ui_state).direct_execution


def test_disabled_leaf_cannot_be_executed():
    ui_state = deepcopy(_catalog("guide_mesh_v1"))
    ui_state["ui_operation_catalog"][0]["available"] = False
    policy = classify_local_turn("请显示导板", ui_state=ui_state)
    assert not policy.direct_execution
