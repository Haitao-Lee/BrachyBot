"""Evaluator-private executable goal contracts. Never import a SUT parser.

Effects are semantic operations on stable objects, not tool-name whitelists.
The prose criteria remain separate independent response/visual review rubrics.
These contracts are development gold, not independently approved clinical gold.
"""
from copy import deepcopy


def eq(path, value):
    return {"op": "equals", "path": path, "value": value}


def keep(path):
    return {"op": "preserve", "path": path}


def done(kind):
    return {"op": "artifact", "kind": kind, "status": "completed"}


def attempt(kind):
    return {"op": "attempt", "operation": "submit", "kind": kind, "min": 1, "max": 1}


def images(*targets, views=("data-tree", "viewer-3d")):
    return {"op": "attachments", "targets": list(targets), "views": list(views)}


def display(target, field="visible"):
    return {"operation": "set", "path": f"objects.{target}.{field}", "max": 1}


def job(kind):
    return {"operation": "submit", "kind": kind, "max": 1}


def capture(*targets, hide=()):
    return {"operation": "capture", "targets": list(targets), "hide": list(hide), "max": len(targets) * 2}


def spec(rules=(), effects=(), *, facts=None, dependencies=(), outcome="COMPLETED"):
    return {"rules": list(rules), "effects": list(effects), "response_facts": facts or {},
            "dependencies": list(dependencies), "acceptable_outcomes": outcome.split("|"),
            "max_provider_calls": 4, "max_operations": 96}


# Explicit per-scenario reference intent. No keyword-derived task gold.
SPECS = {
 "01-001": spec([done("quality"), done("report"), done("guide")], [job("quality"), job("report"), job("guide"), {"operation":"refresh"}], dependencies=[("report","quality")]),
 "01-002": spec(),
 "02-001": spec([eq("objects.guide-A.visible",True)], [display("guide-A")]),
 "02-002": spec(),
 "03-001": spec([eq("objects.guide-A.visible",True)], [display("guide-A")], facts={"guide_version":1}),
 "03-002": spec(),
 "03-003": spec([eq("objects.guide-A.visible",True)], [display("guide-A")]),
 "03-004": spec(facts={"guide_exists":False}),
 "04-001": spec([images("guide-A","ctv-A"), keep("objects"),keep("viewer")], [capture("guide-A","ctv-A")]),
 "04-002": spec([done("report")], [job("report")]),
 "05-001": spec([eq("objects.ctv-A.opacity",.3),eq("objects.needle-A.opacity",.3),keep("objects.guide-A")], [display("ctv-A","opacity"),display("needle-A","opacity")]),
 "05-002": spec([eq("objects.oar-cord.visible",False),eq("objects.oar-brain.visible",False)], [display("oar-cord"),display("oar-brain")]),
 "06-001": spec([eq("objects.seed-A.position_mm",[0,0,0]),eq("objects.needle-A.position_mm",[4,0,0]),{"op":"greater","path":"planning_version","value":9},eq("artifacts.dose","stale")], [{"operation":"restore","token":"edit-2","max":1}]),
 "06-002": spec([eq("preview",None),keep("geometry_revision")], [{"operation":"cancel_preview","max":1}]),
 "07-001": spec([eq("objects.guide-B.visible",True),keep("objects.guide-A")], [display("guide-B")]),
 "07-002": spec(outcome="NEEDS_CLARIFICATION"),
 "08-001": spec([eq("objects.guide-A.visible",True)], [display("guide-A")]),
 "08-002": spec(outcome="NEEDS_CLARIFICATION"),
 "09-001": spec([eq("viewers.sagittal.zoom",2),keep("viewers.axial"),keep("viewers.coronal"),keep("patient_crosshair_mm")], [{"operation":"set","path":"viewers.sagittal.zoom","max":1}]),
 "09-002": spec(outcome="NEEDS_CLARIFICATION"),
 "10-001": spec(facts={"V100_delta_pp":-.2,"V200_delta_pp":3.4}),
 "10-002": spec(outcome="NEEDS_CLARIFICATION|COMPLETED"),
 "11-001": spec(facts={"spinal_cord.D2cc_Gy":7.3,"brain.D2cc_Gy":4.8}),
 "11-002": spec(facts={"esophagus.D2cc_Gy":0,"trachea.D2cc_Gy":None,"brain.status":"stale"}),
 "12-001": spec(facts={"current.V100_percent":90.1,"previous.V100_percent":95,"previous.revision":6}),
 "12-002": spec(facts={"guide.status":"stale"}, outcome="REFUSED_FOR_SAFETY|COMPLETED"),
 "13-001": spec([done("segmentation"),{"op":"labels","expected":{"1":"GTVp","2":"GTVn"}}], [job("segmentation")]),
 "13-002": spec(outcome="NEEDS_CLARIFICATION"),
 "14-001": spec([done("quality"),done("report"),done("guide")], [job("quality"),job("guide"),job("report"),{"operation":"refresh"}], dependencies=[("report","quality")]),
 "14-002": spec([done("dose"),done("report")], [job("dose"),job("report")], dependencies=[("report","dose")]),
 "15-001": spec([attempt("guide"),{"op":"job_status","kind":"guide","status":"failed"},keep("artifact_records.guide")], [job("guide")], facts={"spinal_cord.D2cc_Gy":7.3,"brain.D2cc_Gy":4.8}, outcome="PARTIAL|FAILED_TOOL"),
 "15-002": spec([attempt("dose"),{"op":"job_status","kind":"dose","status":"failed"},eq("objects.guide-A.visible",True)], [job("dose"),display("guide-A")], outcome="PARTIAL|BLOCKED_BY_DEPENDENCY"),
 "16-001": spec([{"op":"lifecycle"}]),
 "16-002": spec([images("guide-A",views=("viewer-3d",)),{"op":"lifecycle"}], [capture("guide-A")]),
 "17-001": spec([eq("objects.guide-A.visible",True),{"op":"job_status","kind":"guide","status":"cancelled"},keep("artifact_records.guide")], [job("guide"),{"operation":"cancel","kind":"guide","max":1},display("guide-A")]),
 "17-002": spec([done("guide"),{"op":"job_status","kind":"report","status":"cancelled"},keep("artifact_records.report")], [job("report"),job("guide"),{"operation":"cancel","kind":"report","max":1}]),
 "18-001": spec([eq("objects.guide-A.visible",True)], [display("guide-A")]),
 "18-002": spec([done("dose")], [job("dose")]),
 "19-001": spec([eq("case_id","case-B"),eq("objects",{}),keep("case_B_camera")], [capture("guide-A")], outcome="PARTIAL|COMPLETED"),
 "19-002": spec([eq("planning_version",8),eq("geometry_revision",8),eq("objects.seed-A.position_mm",[8,0,0]),{"op":"rejected","operation":"restore"}], [{"operation":"restore","token":"cp-7","max":1}], outcome="FAILED_VERIFICATION|PARTIAL"),
 "20-001": spec([{"op":"lifecycle"}], facts={"ct_loaded":False}),
 "20-002": spec(facts={"spinal_cord.D2cc_Gy":7.3,"brain.D2cc_Gy":4.8,"viewer_available":False},outcome="PARTIAL"),
 "21-001": spec([{"op":"provider_fault_seen"}], [{**display("guide-A"), "value":True}],outcome="COMPLETED|FAILED_TOOL|PARTIAL"),
 "21-002": spec([attempt("report"),{"op":"job_status","kind":"report","status":"failed"},keep("artifact_records.report")], [job("report")], outcome="FAILED_TOOL|PARTIAL"),
 "22-001": spec([done("report"),{"op":"lifecycle"}], [job("report")]),
 "22-002": spec(facts={"archived_operation":"guide-done-7","archived_revision":7}),
 "23-001": spec([images("guide-A","ctv-A"),{"op":"lifecycle"}], [capture("guide-A","ctv-A")]),
 "23-002": spec([images("guide-A",views=("data-tree",)),{"op":"no_attachment_view","view":"viewer-3d"}], [capture("guide-A")], outcome="PARTIAL|COMPLETED"),
 "24-001": spec([images("ctv-A",views=("viewer-3d",)),keep("objects"),keep("viewer")], [capture("ctv-A",hide=("guide-A",))]),
 "24-002": spec([done("report_figures"),{"op":"figure_roles","roles":["global","CTV_closeup"]},keep("viewer")], [job("report_figures"),capture("ctv-A")]),
 "25-001": spec(),
 "25-002": spec(facts={"old_image_revision":6,"current_revision":7,"guide_visible":False}),
 "26-001": spec([eq("objects.ctv-A.color","blue"),{"op":"mirrors","target":"ctv-A","field":"color","value":"blue"}], [display("ctv-A","color")]),
 "26-002": spec([done("trajectory_init"),done("manual_next"),{"op":"intermediate_inspection"},eq("manual_stage",2)], [job("trajectory_init"),job("manual_next")]),
 "27-001": spec(facts={"edited_target":"seed-A","new_peer":"seed-B","surface_gap_mm":-.2,"dose_current":False}),
 "27-002": spec(facts={"covers_edits":["edit-A","edit-B"],"V100_delta_pp":-.2,"V200_delta_pp":3.4,"current_score":None}),
 "28-001": spec([images("needle-A","needle-B",views=("viewer-3d",)),keep("viewer"),eq("monitor.auto_compare",False)], [capture("needle-A","needle-B")]),
 "28-002": spec([{"op":"capture_deferred_visible"}], [capture("seed-A")], outcome="PARTIAL|COMPLETED"),
 "29-001": spec([eq("monitor.active",False),{"op":"lifecycle"}], [{"operation":"monitor_stop","run_id":"run-A","max":1}]),
 "29-002": spec([keep("decision_tokens"),keep("geometry_revision")], facts={"checkpoint_consumed":True}),
 "30-001": spec([eq("objects.guide-A.visible",True)], [display("guide-A")], outcome="PARTIAL|REFUSED_FOR_SAFETY|COMPLETED"),
 "30-002": spec([eq("objects.guide-A.visible",True)], [display("guide-A")], outcome="PARTIAL|REFUSED_FOR_SAFETY|COMPLETED"),
 "31-001": spec(facts={"V100_percent":90.1}),
 "31-002": spec([{"op":"provider_fault_seen"},{"op":"lifecycle"}], facts={"report.status":"current","score":None}, outcome="PARTIAL|FAILED_TOOL"),
 "32-001": spec(facts={"V100_percent":90.1,"spinal_cord.D2cc_Gy":7.3,"guide_visible":False}),
 "32-002": spec(facts={"report.status":"stale"}),
 "33-001": spec([{"op":"pdf_download"}], [{"operation":"export","kind":"report","max":1}]),
 "33-002": spec([eq("language","zh"),eq("report.body_language","zh"),eq("report.captions_language","zh"),{"op":"report_locale"}], [{"operation":"language","value":"zh","max":1}]),
 "34-001": spec(facts={"spinal_cord.D2cc_Gy":7.3,"verified_limit":None}),
 "34-002": spec(facts={"measured_Gy":7.3,"demo_limit_Gy":8,"margin_Gy":.7,"protocol_id":"protocol-demo"}),
 "35-001": spec(outcome="NEEDS_CLARIFICATION"),
 "35-002": spec(facts={"V100_percent":90.1,"printer_control":False},outcome="PARTIAL|COMPLETED"),
 "36-001": spec([eq("objects.guide-A.visible",True),eq("objects.ctv-A.visible",True),eq("objects.ctv-A.opacity",.4),{"op":"per_turn","count":4}], [display("guide-A"),display("ctv-A"),display("ctv-A","opacity")], facts={"spinal_cord.D2cc_Gy":7.3}),
 "36-002": spec(outcome="NEEDS_CLARIFICATION"),
 "37-001": spec([done("report")], [job("report")]),
 "37-002": spec([{"op":"context_accounting","retained":22918,"capacity":1048576}], facts={"turn_total":39166,"retained":22918,"capacity":1048576}),
 "38-001": spec(facts={"guide_visible":False}),
 "38-002": spec([eq("geometry_revision",8)], facts={"dose_current":False}),
 "39-001": spec([eq("objects.guide-A.opacity",.35),eq("objects.guide-A.visible",False)], [display("guide-A","opacity")]),
 "39-002": spec([eq("objects.ctv-A.opacity",.25),eq("objects.dose-overlay.opacity",.4),keep("prescription_Gy")], [display("ctv-A","opacity"),display("dose-overlay","opacity")]),
 "40-001": spec([{"op":"organ_rows","count":53}], facts={"no_silent_truncation":True}),
 "40-002": spec(facts={"spinal_cord.D2cc_Gy":7.3,"brain.D2cc_Gy":4.8,"distance_available":False}),
}


from .catalog import PACK
for _family in PACK["families"]:
    for _case in _family["cases"]:
        if "runtime_contract" in _case:
            SPECS[_case["id"][4:]] = deepcopy(_case["runtime_contract"])


def compile_contract(case):
    key = case["id"][4:]
    if key not in SPECS:
        raise ValueError(f"no manually authored contract for {case['id']}")
    result = deepcopy(SPECS[key])
    legacy_turns={"17-001":(1,2,2), "17-002":(1,1,2), "18-001":(1,),
                  "26-002":(1,2), "36-001":(1,1,2), "39-001":(1,)}
    if key in legacy_turns:
        for effect,owner in zip(result["effects"],legacy_turns[key],strict=True):
            effect["turn"]=owner
        result["turn_scoped"]=True
    if key in {"17-001","17-002"}:
        result["turn_outcomes"]={1:"PARTIAL",2:"COMPLETED"}
    if key=="36-001":
        result["rules"].append({"op":"turn_state","turn":1,"path":"objects.ctv-A.opacity","value":.5})
        result["rules"].append({"op":"turn_state","turn":2,"path":"objects.ctv-A.opacity","value":.4})
    # Bind parameters to authored goals, not merely the operation and target.
    # This compilation is private and never derives a value from a SUT reply.
    for effect in result["effects"]:
        if effect["operation"] == "set" and "value" not in effect:
            goals = [r for r in result["rules"]
                     if r["op"] == "equals" and r["path"] == effect["path"]]
            if len(goals) != 1:
                raise ValueError(f"explicit setter value required for {case['id']}: {effect['path']}")
            effect["value"] = deepcopy(goals[0]["value"])
    result.update(scenario_id=case["id"], source_acceptance=deepcopy(case["acceptance"]),
                  semantic_review="pending_independent_review", clinical_validation=False)
    result["response_rubric"] = [{"id":f"criterion-{i}", **a}
        for i,a in enumerate(case["acceptance"])]
    result["protocol_user_turns"] = sum(s["kind"] == "user" for s in case["steps"])
    for effect in result["effects"]:
        if "turn" in effect and (type(effect["turn"]) is not int or not 1<=effect["turn"]<=result["protocol_user_turns"]):
            raise ValueError(f"invalid effect turn owner for {case['id']}")
    # Do not impose one response language on event-only proactive scenarios.
    result["requested_language"] = next((s["language"] for s in reversed(case["steps"])
                                          if s["kind"] == "user"), case["initial_state"].get("language"))
    result["requested_languages"] = [s["language"] for s in case["steps"] if s["kind"]=="user"]
    result["max_clarification_turns"] = case["budget"].get("max_clarification_turns",1)
    return result
