"""Controls for actual per-turn execution and frozen-input provenance."""
from copy import deepcopy

import pytest

from .catalog import PACK
from .contracts import compile_contract
from .environment import Environment
from .oracle_runtime import RealUserRequestOracle, rule_check
from .test_runtime_contract import witness

CASES=[c for f in PACK["families"] for c in f["cases"]
       if c.get("design_version")=="workflow-completion-2026-10-04"]


def test_inventory_is_eighty_authored_workflow_cases():
    assert len(CASES)==80
    assert len({c["family_id"] for c in CASES})==20
    assert all(len(c["negative_controls"])==3 for c in CASES)


@pytest.mark.parametrize("family",PACK["families"][64:],ids=lambda f:f["id"])
def test_contexts_change_decision_or_required_answer(family):
    cases=family["cases"]
    assert len(cases)==4
    assert len({str(c["steps"]) for c in cases})==4
    assert len({str((compile_contract(c)["rules"],compile_contract(c)["effects"],c["acceptance"][0])) for c in cases})==4
    assert all(c["split_group"]==family["id"] for c in cases)


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["id"])
def test_scoped_effects_never_authorize_future_turn(case,tmp_path):
    contract=compile_contract(case)
    assert all(1<=e["turn"]<=contract["protocol_user_turns"] for e in contract["effects"])
    future=next((e for e in contract["effects"] if e["turn"]>1),None)
    if future is None:
        assert all(e["turn"]==1 for e in contract["effects"])
        return
    env=Environment(case,tmp_path)
    user=next(s for s in case["steps"] if s["kind"]=="user")
    env.begin_turn(user["text"],user["language"])
    args={k:v for k,v in future.items() if k not in {"operation","turn","max","targets","hide"}}
    if future["operation"]=="capture": args={"target":future["targets"][0],"hide":future["hide"]}
    env.call(future["operation"],args)
    env.deliver_response("Component premature-action counterexample.")
    result=RealUserRequestOracle().check(contract=contract,observation=env.collect())
    assert any(v.code=="unauthorised_effect_attempt" for v in result.violations)


def test_per_turn_snapshot_survives_later_correct_terminal_state(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-65-001")
    env,contract=witness(case,tmp_path)
    observation=env.collect()
    assert env.state["objects"]["guide-A"]["visible"] is False
    assert observation["turn_responses"][0]["state_at_delivery"]["objects"]["guide-A"]["visible"] is True
    bad=deepcopy(observation)
    bad["turn_responses"][0]["state_at_delivery"]["objects"]["guide-A"]["visible"]=False
    assert not rule_check(contract["rules"][0],bad)


def test_duplicate_final_cannot_satisfy_turn_state(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-65-001")
    env,contract=witness(case,tmp_path)
    observation=env.collect()
    observation["turn_responses"].append(deepcopy(observation["turn_responses"][0]))
    assert not rule_check(contract["rules"][0],observation)


def test_missing_fault_barrier_is_not_exercised_recovery(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-73-004")
    env,contract=witness(case,tmp_path)
    observation=env.collect()
    rule=next(r for r in contract["rules"] if r["op"]=="event_fired")
    assert rule_check(rule,observation)
    observation["events_fired"]=[]
    assert not rule_check(rule,observation)


def test_quality_records_completed_dose_input_identity(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-72-002")
    env,contract=witness(case,tmp_path)
    quality=env.state["artifact_records"]["quality"]
    assert quality["sources"]["dose"]["id"]==env.state["artifact_records"]["dose"]["id"]
    assert RealUserRequestOracle().check(contract=contract,observation=env.collect()).passed


def test_source_input_does_not_rebind_at_job_completion(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-72-002")
    env=Environment(case,tmp_path)
    env.begin_turn("Component source-input counterexample.","en")
    before=env.state["artifact_records"]["dose"]["id"]
    env.call("submit",{"kind":"quality"})
    env.call("submit",{"kind":"dose"})
    env.complete_job("dose")
    env.complete_job("quality")
    assert env.state["artifact_records"]["quality"]["sources"]["dose"]["id"]==before
    assert before!=env.state["artifact_records"]["dose"]["id"]
