"""Deterministic build/validation entry. Never launches a SUT or network call."""
import argparse
from copy import deepcopy
import json
from hashlib import sha256
from pathlib import Path

from .catalog import PACK
from .contracts import SPECS, compile_contract
from .event_driver import EVENTS
from .fixtures_runtime import digest, materialize
from .quality_gate import validate

ROOT=Path(__file__).resolve().parent


def cases():
    return [c for f in PACK["families"] for c in f["cases"]]


def task_for(case):
    turns=[{"role":"user","text":s["text"],"lang":s["language"]}
           for s in case["steps"] if s["kind"]=="user"]
    if not turns:
        # Genuine subscribed events, NOT a fabricated user instruction.
        turns=[{"role":"system","text":"Subscribed Monitor environment event; no new user command."}]
    return {
        "schema_version":"1.0","id":case["id"],"track":case["primary_track"],
        "layers":["L2","L4"],"comparability":["alpha","beta"],
        "construct":case["family_id"],"cost_class":"light_compute",
        "power_role":"exploratory","clinical_intent":case["title"],
        "fixture":{"case_family":case["family_id"],
                   "setup_script":f"extensions/real_user_requests_v1/compiled/fixtures/{case['id']}.json",
                   "initial_state_hash":"sha256:"+digest(materialize(case))},
        "unit":{"kind":"task_scenario","group_type":"G-CTX","contrast_family_id":case["family_id"]},
        "protocol":{"mode":"multi_turn" if len(turns)>1 else "single_turn","turns":turns,
                    "budget":{"wall_clock_s":120,"turns":sum(t["role"]=="user" for t in turns),"tool_calls":96},
                    "audit_required":True,"allowed_intermediates":[],"n_runs":1,"ui_counterpart":None},
        "oracle":{"kind":"program","check":"real_user_request","constraint_class":"none",
                  "independent_check":True,"gold":f"contracts/{case['id']}.json","expect":None},
        "scoring":{"primary_metric":"verified_task_goal","gate_refs":[],"weight":1.,"difficulty_target":"medium"},
        "anti_gaming":{"paraphrase_group":case["family_id"],"contrast_family_id":case["family_id"],"hidden":False},
        "provenance":{"source":"audit_derived","derived_from":f"real_user_requests_v1:{case['id']}",
                      "authored_on":"2026-10-03","reviewers":["authoring-only; independent review pending"],"guideline_ref":None,"deprecated":None},
    }


def products():
    report=validate(PACK)
    if not report["structural_ok"]: raise ValueError(report["errors"])
    assert set(SPECS)=={c["id"][4:] for c in cases()},"contract index mismatch"
    result={}
    rows=[]
    for case in cases():
        sid=case["id"]; contract=compile_contract(case); state=materialize(case)
        family=next(f for f in PACK["families"] if f["id"]==case["family_id"])
        assert all(s["event"] in EVENTS for s in case["steps"] if s["kind"]=="environment_event")
        result[f"tasks/{sid}.json"]=task_for(case)
        result[f"fixtures/{sid}.json"]=state
        result[f"contracts/{sid}.json"]=contract
        result[f"events/{sid}.json"]=[s for s in case["steps"] if s["kind"]=="environment_event"]
        result[f"review_cards/{sid}.json"]={"id":sid,"title":case["title"],"meaning":family["gap"],
                "family_title":family["title"],"priority":family["priority"],"user_protocol":deepcopy(case["steps"]),
                "initial_state":state,"source_acceptance":case["acceptance"],"allowed_effects":contract["effects"],
                "goals":contract["rules"],"facts":contract["response_facts"],
                "negative_control_specs":case["negative_controls"],"adapter_requirements":case["adapter_requirements"],
                "review_status":"pending_independent_review","split":"development",
                "questions":["Does the context support the gold without guessing?",
                             "Is each requirement relevant to BrachyBot?",
                             "Are legitimate alternate tool paths allowed?",
                             "Do the controls genuinely contradict this criterion?",
                             "What wording/clinical ambiguity needs adjudication?"]}
        rows.append({"id":sid,"title":case["title"],"family":case["family_id"],"primary_track":case["primary_track"],
                     "secondary_tracks":case["secondary_tracks"],"machine_rule_count":len(contract["rules"]),
                     "semantic_criterion_count":len(contract["response_rubric"]),"split":"development",
                     "runtime_ready":True,"semantic_review":"pending_independent_review",
                     "confirmatory_eligible":False,"profile":"decision_sandbox"})
    result["index.json"]={"schema":"rur-executable-1","family_count":40,"scenario_count":len(rows),
                          "task_rows":rows,"sut_runs":0,"sut_results":"not_collected",
                          "confirmatory_ready":False,"split_policy":"All current tasks are public development; no sealed claim.",
                          "shared_fixture_lineage":"synthetic-rur-base-v1; not independent clinical cases"}
    result["manifest.json"]={"schema":"rur-build-manifest-1","files":{k:digest(v) for k,v in sorted(result.items())},
                             "source_files":{p.name:sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob("*.py"))},
                             "sut_results":0,"formal_ready":False,"environment":"synthetic decision sandbox, no real clinical computation"}
    return result


def build(out=ROOT/"compiled", *, check=False):
    out=Path(out); data=products(); drift=[]
    for rel,value in data.items():
        text=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
        path=out/rel
        if check:
            if not path.exists() or path.read_text(encoding="utf-8")!=text: drift.append(rel)
        else:
            path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text,encoding="utf-8")
    expected=set(data)
    if out.exists():
        extras={str(p.relative_to(out)).replace("\\","/") for p in out.rglob("*.json")}-expected
        drift.extend(sorted(extras))
    return {"build_ok":not drift,"drift":drift,"scenarios":len(cases()),"sut_runs":0,
            "confirmatory_ready":False,"runtime_profile":"decision_sandbox"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,default=ROOT/"compiled")
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args(argv); report=build(args.out,check=args.check)
    print(json.dumps(report,ensure_ascii=False)); return 0 if report["build_ok"] else 1


if __name__=="__main__": raise SystemExit(main())
