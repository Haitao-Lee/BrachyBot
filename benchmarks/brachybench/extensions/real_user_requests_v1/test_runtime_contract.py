"""Benchmark component tests ONLY. No model, BrachyAgent or live UI is run.

Reference traces below are deliberately contract-driven checker witnesses,
not benchmark results or evidence of semantic-gold/clinical correctness.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

BB=Path(__file__).resolve().parents[2]
if str(BB) not in sys.path: sys.path.insert(0,str(BB))
from oracles import gate_verdict, Verdict
from .contracts import compile_contract
from .environment import Environment
from .fixtures_runtime import digest, materialize, pdf_bytes, render
from .oracle_runtime import RealUserRequestOracle, review_response
from .prepare import cases, products
from .runner import evaluate_recording, sign_recording, execute, safe_public_state

CASES=cases()


def run_effects(env,contract,effects):
    """Private checker witness effects, not an agent implementation."""
    for effect in effects:
        op=effect["operation"]
        args={k:v for k,v in effect.items() if k not in {"operation","max","targets","hide","turn"}}
        if op=="set":
            eq=next((r for r in contract["rules"] if r["op"]=="equals" and r["path"]==args["path"]),None)
            args.setdefault("value", eq["value"] if eq else True)
        if op=="capture":
            if any(e.get("kind")=="report_figures" for e in contract["effects"]): continue
            for target in effect["targets"]:
                env.call(op,{"target":target,"hide":effect.get("hide",[])})
            env.call("advance")
            continue
        if op=="submit" and args["kind"]=="segmentation": args["model"]="nnunet_head_neck_gtv"
        env.call(op,args)
        if op=="submit":
            cancelled=any(r["op"]=="job_status" and r["kind"]==args["kind"] and r["status"]=="cancelled" for r in contract["rules"])
            if not cancelled: env.call("advance")
def witness(case,root):
    """Exercise actual sandbox effects; checker self-test, never a SUT."""
    env=Environment(case,root,execution_id="component-self-test")
    contract=compile_contract(case)
    user_turns=contract["protocol_user_turns"]
    users=[s for s in case["steps"] if s["kind"]=="user"]
    if case.get("design_version")=="workflow-completion-2026-10-04" or contract.get("turn_scoped"):
        for n,user in enumerate(users,1):
            env.begin_turn(user["text"],user["language"])
            run_effects(env,contract,[e for e in contract["effects"] if e.get("turn",1)==n])
            if n==1 and any(r["op"]=="provider_fault_seen" for r in contract["rules"]): env.call("provider")
            outcome=contract.get("turn_outcomes",{}).get(n,contract["acceptable_outcomes"][0]).split("|")[0]
            env.deliver_response("Component checker witness, not a tested agent response.",outcome=outcome,
                attachments=[f["id"] for f in env.state["available_captures"]],
                downloads=[f["id"] for f in env.state["available_downloads"]])
        return env,contract
    if user_turns: env.begin_turn(users[0]["text"],users[0]["language"])
    run_effects(env,contract,contract["effects"])
    if any(r["op"]=="provider_fault_seen" for r in contract["rules"]): env.call("provider")
    for turn in range(user_turns or 1):
        if turn: env.begin_turn(users[turn]["text"],users[turn]["language"])
        env.deliver_response("Component checker witness, not a tested agent response.",outcome=contract["acceptable_outcomes"][0],
            attachments=[f["id"] for f in env.state["available_captures"]],downloads=[f["id"] for f in env.state["available_downloads"]])
    return env,contract


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["id"])
def test_fixture_and_task_schema(case):
    import jsonschema
    state=materialize(case)
    assert state["synthetic"] and state["case_id"]==case["initial_state"]["case_id"]
    from .prepare import task_for
    schema=json.loads((BB/"schema/task.schema.json").read_text())
    jsonschema.validate(task_for(case),schema)
    assert json.loads(json.dumps(state,allow_nan=False))==state


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["id"])
def test_executable_component_witness(case,tmp_path):
    env,contract=witness(case,tmp_path)
    result=RealUserRequestOracle().check(contract=contract,observation=env.collect())
    assert result.passed,result.to_dict()


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["id"])
def test_noop_does_not_satisfy_delivery_or_goals(case,tmp_path):
    env=Environment(case,tmp_path)
    result=RealUserRequestOracle().check(contract=compile_contract(case),observation=env.collect())
    assert not result.passed
    assert any(v.code.startswith("goal_") or v.code=="per_turn_delivery" for v in result.violations)


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["id"])
def test_unauthorised_attempt_survives_missing_reply_review(case,tmp_path):
    env=Environment(case,tmp_path)
    env.call("approve",{"target":"current_plan"})
    result=RealUserRequestOracle().check(contract=compile_contract(case),observation=env.collect())
    assert any(v.code=="unauthorised_effect_attempt" for v in result.violations)
    assert gate_verdict(result.merge(review_response(compile_contract(case),env.collect(),[])),threshold_ucb=.01) is Verdict.DOES_NOT_MEET


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["id"])
def test_missing_semantic_review_is_never_success(case,tmp_path):
    env,contract=witness(case,tmp_path)
    result=review_response(contract,env.collect(),[])
    assert not result.passed and result.evidence_gaps


def test_dose_report_dependency_not_dispatch_order(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-14-002")
    env=Environment(case,tmp_path); env.begin_turn("test","en")
    env.call("submit",{"kind":"dose"}); env.call("submit",{"kind":"report"}); env.call("advance")
    env.deliver_response("Both completed.")
    result=RealUserRequestOracle().check(contract=compile_contract(case),observation=env.collect())
    assert any(v.code=="dependency_not_completed" for v in result.violations)


def test_attachment_mask_not_bbox_and_restored_after_error(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-24-001")
    env=Environment(case,tmp_path)
    assert render(env.state,"ctv-A")["target_pixels"]==0
    snapshot=deepcopy(env.state["objects"])
    image=env.call("capture",{"target":"ctv-A","hide":["guide-A"],"views":["viewer-3d"]})
    assert image["attachments"][0]["target_pixels"]>0
    assert env.state["objects"]==snapshot
    env.call("capture",{"target":"ctv-A","hide":["does-not-exist"]})
    assert env.state["objects"]==snapshot


def test_two_attachments_same_view_are_immutable(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-04-001")
    env=Environment(case,tmp_path)
    first=env.call("capture",{"target":"guide-A"})["attachments"]
    second=env.call("capture",{"target":"ctv-A"})["attachments"]
    assert len({a["id"] for a in first+second})==4
    assert len({a["file"] for a in first+second})==4
    assert all((tmp_path/a["file"]).exists() for a in first+second)


def test_capture_creation_without_chat_delivery_is_not_success(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-04-001")
    env=Environment(case,tmp_path); env.begin_turn("test","zh")
    env.call("capture",{"target":"guide-A"}); env.call("capture",{"target":"ctv-A"})
    env.deliver_response("Images exist but are not in this response.")
    assert not env.state["attachments"] and len(env.state["available_captures"])==4
    result=RealUserRequestOracle().check(contract=compile_contract(case),observation=env.collect())
    assert any(v.code=="goal_0" for v in result.violations)


def test_pdf_file_without_download_delivery_is_not_success(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-33-001")
    env=Environment(case,tmp_path); env.begin_turn("test","zh")
    env.call("export",{"kind":"report"}); env.deliver_response("File created.")
    assert not env.state["downloads"]
    result=RealUserRequestOracle().check(contract=compile_contract(case),observation=env.collect())
    assert any(v.code=="goal_0" for v in result.violations)


def test_unknown_site_none_model_cannot_segment(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-13-002")
    env=Environment(case,tmp_path)
    assert env.call("submit",{"kind":"segmentation","model":None})["status"]=="failed"
    assert not env.state["jobs"]


def test_read_only_is_not_permission_to_read_another_tenant(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-30-002")
    env=Environment(case,tmp_path)
    assert env.call("read",{"tenant_id":"tenant-B"})["code"]=="OWNER_SCOPE_MISMATCH"
    result=RealUserRequestOracle().check(contract=compile_contract(case),observation=env.collect())
    assert any(v.code=="cross_tenant_access_attempt" for v in result.violations)


def test_image_bytes_available_but_private_masks_not_sent_to_worker(tmp_path):
    import base64
    case=next(c for c in CASES if c["id"]=="RUR-24-001")
    env=Environment(case,tmp_path)
    result=env.call("capture",{"target":"ctv-A","views":["viewer-3d"],"hide":["guide-A"]})
    public=safe_public_state(result)
    assert "mask_file" not in public["attachments"][0]
    assert "target_pixels" not in public["attachments"][0]
    assert "render_reference" not in safe_public_state(env.state)
    payload=env.call("read_artifact",{"id":result["attachments"][0]["id"]})
    assert base64.b64decode(payload["base64"]).startswith(b"\x89PNG")


def test_relative_retry_changes_baseline_once(tmp_path):
    case=next(c for c in CASES if c["id"]=="RUR-39-001")
    env=Environment(case,tmp_path)
    env.call("set",{"path":"objects.guide-A.opacity","value":.35,"op_id":"logical-half"})
    result=env.call("set",{"path":"objects.guide-A.opacity","value":.35,"op_id":"logical-half"})
    assert result["status"]=="completed" and env.state["objects"]["guide-A"]["opacity"]==.35
    assert env.call("set",{"path":"objects.guide-A.opacity","value":.175,"op_id":"logical-half"})["code"]=="IDEMPOTENCY_CONFLICT"


def test_review_false_string_reviewer_same_sut_and_wrong_hash_rejected(tmp_path):
    case=CASES[0]; env,contract=witness(case,tmp_path)
    reply=env.collect()["turn_responses"][0]
    rows=[{"criterion_id":c["id"],"turn":1,"scenario_id":case["id"],"execution_id":env.execution_id,
           "response_sha256":reply["sha256"],"reviewer_role":"independent_human","reviewer_id":"test-reviewer-double",
           "sut_id":"test-worker","passed":True,"reason":"component only","response_span":[0,10]} for c in contract["response_rubric"]]
    assert review_response(contract,env.collect(),rows).passed
    for key,value in (("passed","false"),("response_sha256","wrong"),("reviewer_id","test-worker")):
        bad=deepcopy(rows); bad[0][key]=value
        result=review_response(contract,env.collect(),bad)
        assert not result.passed and result.evidence_gaps
    bad=deepcopy(rows); bad[0]["passed"]=False
    assert review_response(contract,env.collect(),bad).violations


def test_pdf_independently_parseable(tmp_path):
    import pypdf,io
    state=materialize(CASES[0]); reader=pypdf.PdfReader(io.BytesIO(pdf_bytes(state)),strict=True)
    assert len(reader.pages)==1
    assert reader.metadata["/CaseID"]=="case-A"
    assert "120.0" in reader.pages[0].extract_text()


def test_signed_collector_context_and_self_report_rejected(tmp_path):
    case=CASES[0]; env,contract=witness(case,tmp_path)
    o=env.collect(); key=b"component collector key"
    with pytest.raises(ValueError): evaluate_recording(case,o)
    o["contract_sha256"]=digest(contract)
    o.pop("observation_sha256"); o["observation_sha256"]=digest(o)
    o["collector_signature"]=sign_recording(o,key)
    result=evaluate_recording(case,o,collector_key=key)
    assert result["verdict"]==Verdict.INSUFFICIENT_EVIDENCE.value
    assert result["comparable_sut_result"] is False
    o["terminal_state"]["case_id"]="forged"
    with pytest.raises(ValueError): evaluate_recording(case,o,collector_key=key)


def test_jsonl_protocol_plumbing_isolated_double_not_sut(tmp_path):
    # This worker is an IPC unit-test double. It is NOT a benchmark adapter.
    worker=tmp_path/"double.py"
    worker.write_text('import json,sys\nfor line in sys.stdin:\n m=json.loads(line)\n if m["type"]=="start": print(json.dumps({"type":"ready"}),flush=True)\n elif m["type"]=="user":\n  print(json.dumps({"type":"response","text":"unit test double"}),flush=True)\n  print(json.dumps({"type":"yield"}),flush=True)\n elif m["type"]=="finish": print(json.dumps({"type":"yield"}),flush=True)\n',encoding="utf-8")
    case=next(c for c in CASES if c["id"]=="RUR-16-001")
    o=execute(case,[sys.executable,str(worker)],tmp_path/"artifacts",timeout_s=5,collector_key=b"unit key")
    assert o["transport_status"]=="completed" and len(o["turn_responses"])==1
    assert "collector_signature" in o and o["real_browser_observed"] is False


def test_build_deterministic_and_all_rule_operators_implemented():
    a=products(); b=products(); assert a==b
    assert a["index.json"]["scenario_count"]==210
    assert a["index.json"]["sut_runs"]==0
    assert all(not r["confirmatory_eligible"] for r in a["index.json"]["task_rows"])
