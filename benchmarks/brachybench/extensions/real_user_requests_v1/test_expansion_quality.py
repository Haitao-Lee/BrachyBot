"""Offline authoring and checker controls, never agent performance results."""
from copy import deepcopy

import pytest

from .catalog import PACK
from .contracts import compile_contract
from .environment import Environment
from .fixtures_runtime import materialize
from .oracle_runtime import RealUserRequestOracle, _match

ADDED = [c for f in PACK["families"] for c in f["cases"] if c.get("design_version") == "state-contrast-2026-10-04"]


def test_original_identity_and_expansion_inventory():
    original = [c for f in PACK["families"] for c in f["cases"] if "design_version" not in c]
    assert len(original) == 82 and len(ADDED) == 48
    assert len({c["family_id"] for c in ADDED}) == 24
    assert all(c["split_group"] == c["family_id"] for c in ADDED)


@pytest.mark.parametrize("family", PACK["families"][40:64], ids=lambda f: f["id"])
def test_added_pair_changes_state_action_or_response_decision(family):
    left, right = family["cases"]
    assert left["initial_state"] != right["initial_state"] or left["steps"] != right["steps"]
    a, b = compile_contract(left), compile_contract(right)
    fields = ("rules", "effects", "response_facts", "acceptable_outcomes")
    assert any(a[k] != b[k] for k in fields)
    assert family["gap"] and all(len(c["negative_controls"]) == 3 for c in family["cases"])


@pytest.mark.parametrize("case", [c for f in PACK["families"] for c in f["cases"]], ids=lambda c: c["id"])
def test_new_setters_are_value_bound(case):
    for effect in compile_contract(case)["effects"]:
        if effect["operation"] == "set":
            assert "value" in effect
            wrong = not effect["value"] if type(effect["value"]) is bool else .99
            assert not _match({"operation": "set", "args": {"path": effect["path"], "value": wrong}}, effect)


def test_matching_does_not_equate_boolean_and_number():
    assert not _match({"operation": "set", "args": {"path": "objects.ctv-A.visible", "value": 1}},
                      {"operation": "set", "path": "objects.ctv-A.visible", "value": True})


def test_wrong_transient_value_cannot_be_hidden_by_correct_terminal_state(tmp_path):
    case = next(c for c in ADDED if c["id"] == "RUR-51-001")
    contract = compile_contract(case)
    contract["effects"][0]["max"] = 2
    env = Environment(case, tmp_path)
    env.begin_turn(case["steps"][0]["text"], "zh")
    env.call("set", {"path": "objects.ctv-A.opacity", "value": .9})
    env.call("set", {"path": "objects.ctv-A.opacity", "value": .3})
    env.deliver_response("Component counterexample, not an agent response.")
    result = RealUserRequestOracle().check(contract=contract, observation=env.collect())
    assert any(v.code == "unauthorised_effect_attempt" for v in result.violations)


def test_guide_fixture_preserves_authored_version_and_geometry():
    case = deepcopy(next(c for c in ADDED if c["id"] == "RUR-42-001"))
    case["initial_state"]["objects"]["guide-B"]["position_mm"] = [9, 8, 7]
    state = materialize(case)
    assert state["objects"]["guide-B"]["version"] == 2
    assert state["objects"]["guide-B"]["position_mm"] == [9, 8, 7]
    assert state["objects"]["guide-A"]["position_mm"] == [0, 0, 20]
