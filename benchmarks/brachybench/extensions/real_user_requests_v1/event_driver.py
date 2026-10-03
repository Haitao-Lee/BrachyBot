"""Evaluator-owned event barriers. Arming precedes SUT dispatch, not reply.

Every catalog event has a concrete handler. The script is never sent to the
agent. Unhit barriers are preserved as explicit evidence, not silently skipped.
"""
from copy import deepcopy


EVENTS = {
 "dose_job_running","dose_result","guide_failed","dose_failed","delay_attachment_delivery",
 "attachment_delivered","hold_job_before_commit","hold_report","drop_http_ack","switch_case",
 "capture_arrives","external_tab_commits_geometry","malformed_arguments","contradictory_tool_result",
 "browser_reload","report_completed","restore_saved_session","deliver_two_target_images",
 "capture_partial","observe_intermediate_artifacts","commit_seed_edit","recompute_completes",
 "commit_needle_edit","deliver_conflict_image","capture_deferred","drop_stop_ack",
 "provider_transient_error","compact_prior_history_preserving_provenance",
}


class EventDriver:
    def __init__(self, steps):
        self.pending=[deepcopy(s) for s in steps if s["kind"]=="environment_event"]
        unknown={s["event"] for s in self.pending}-EVENTS
        if unknown: raise ValueError(f"unimplemented events: {sorted(unknown)}")
        self.fired=[]

    def emit(self, barrier, env):
        for event in list(self.pending):
            if event["trigger"] != barrier: continue
            self.pending.remove(event)
            self.fired.append({**event,"at":env.sequence+1})
            env.record("environment_event",event["event"],event["payload"],source="environment")
            self.apply(event["event"],event["payload"],env)

    def apply(self, name, p, env):
        s=env.state
        if name in ("drop_http_ack","drop_stop_ack"):
            env.next_result_override={"status":"unknown","code":"ACK_LOST"}
        elif name in ("hold_job_before_commit","hold_report"):
            kind="report" if name=="hold_report" else "guide"
            env.held.add(kind)
        elif name=="dose_job_running":
            # Accepted is not completed; the next explicit tick may finish it.
            pass
        elif name in ("guide_failed","dose_failed"):
            env.fail_job("guide" if name=="guide_failed" else "dose",p.get("code","TOOL_FAILED"))
        elif name=="contradictory_tool_result":
            env.fail_job("report","CONTRADICTORY_RESULT")
            env.next_result_override={"success":True,"receipt_status":"failed","artifact_id":None}
        elif name=="malformed_arguments":
            env.provider_fault={"kind":name,**p}
        elif name=="provider_transient_error":
            env.provider_fault={"kind":name,**p}
        elif name=="external_tab_commits_geometry":
            s["planning_version"]=s["geometry_revision"]=p["revision"]
            s["objects"]["seed-A"]["position_mm"]=[8,0,0]
            env.invalidate()
            env.sync_display()
        elif name=="switch_case":
            # New isolated case: never transplant old camera or attachments.
            env.origin_state=deepcopy(s)
            s.update(case_id=p["case_id"],session_id=p["session_id"],planning_id=None,
                     planning_version=0,geometry_revision=0,objects={},selection=None,
                     artifact_records={},metrics={},attachments=[],downloads=[])
            s["available_captures"]=[]; s["available_downloads"]=[]
            s["viewer"]["camera"]=deepcopy(s["case_B_camera"])
            env.sync_display()
            self.emit("case.switched",env)
        elif name=="capture_arrives":
            env.delivery_scope={"case_id":p["case_id"],"revision":p["revision"],"superseded":True}
        elif name=="browser_reload":
            s["browser_epoch"]=s.get("browser_epoch",0)+1
            env.record("browser","reconnected",{},source="environment")
            self.emit("browser.reconnected",env)
        elif name=="report_completed":
            env.held.discard("report")
            env.complete_job("report")
        elif name=="restore_saved_session":
            s["session_restored"]=True
        elif name=="compact_prior_history_preserving_provenance":
            s["compaction_receipt"]={"source_turns":deepcopy(s["history_summary"]["source_turns"]),
                                     "excluded":deepcopy(s["history_summary"]["excluded"])}
        elif name in ("commit_seed_edit","commit_needle_edit"):
            target=p["target"]; obj=s["objects"][target]
            prior=deepcopy(obj["position_mm"])
            peer=p.get("new_conflict",{}).get("peer") or p.get("conflicting_peer")
            if peer:
                s["objects"].setdefault(peer,{"label":peer,"type":obj["type"],"visible":True,
                                            "opacity":1.,"color":"cyan","position_mm":[5,0,0],"radius_mm":.4})
            obj["position_mm"]=[4.4,0,0] if peer else [2,0,0]
            if obj["type"]=="needle":
                displacement=[obj["position_mm"][i]-prior[i] for i in range(3)]
                obj["endpoints_mm"]=[[endpoint[i]+displacement[i] for i in range(3)] for endpoint in obj["endpoints_mm"]]
                if peer:
                    s["objects"][peer]["endpoints_mm"]=[[5+v[0],v[1],v[2]] for v in ([-15,-8,-5],[15,8,5])]
            old=s["geometry_revision"]; revision=p.get("to_revision",p.get("revision",old+1))
            s["geometry_revision"]=s["planning_version"]=revision
            edit={"id":p.get("id","edit-event"),"target":target,"from":old,"to":revision,
                  "before_position_mm":prior,"consumed":False,"case_id":s["case_id"],
                  "session_id":s["session_id"],"planning_id":s["planning_id"]}
            s["edit_log"].append(edit)
            s["last_edit"]={**edit,"displacement_mm":[obj["position_mm"][i]-prior[i] for i in range(3)],
                            "new_conflicts":[{"target":target,"peer":peer,"surface_gap_mm":p.get("new_conflict",{}).get("surface_gap_mm",-.2)}] if peer else []}
            env.invalidate(); env.sync_display()
        elif name=="recompute_completes":
            s["geometry_revision"]=s["planning_version"]=p["after_revision"]
            s["comparison"]={**p,"same_anatomy":True,"score":None}
            s["artifacts"]["dose"]=s["artifacts"]["dvh"]="current"
            env.install_artifact("dose",source="environment")
        elif name=="capture_partial":
            env.capture_views=set(p["delivered_views"])
        elif name=="capture_deferred":
            env.deferred_reason=p["reason"]
        elif name=="delay_attachment_delivery":
            env.delivery_held=True
        elif name=="attachment_delivered":
            env.delivery_held=False
        elif name=="deliver_two_target_images":
            # This authorizes no capture. Only already requested capture jobs
            # can produce images; a no-op SUT cannot receive free gold images.
            env.expected_delivery_targets=set(p["targets"])
        elif name=="deliver_conflict_image":
            env.expected_delivery_targets=set(p["targets"])
        elif name=="observe_intermediate_artifacts":
            env.record("inspection","intermediate",deepcopy(s.get("intermediate_node")),source="environment")
        elif name=="dose_result":
            env.held.discard("dose")
            if s["artifact_records"].get("dose",{}).get("revision")!=p["revision"]:
                raise ValueError("injected dose result has wrong revision")
        else:
            raise AssertionError(f"event handler missing: {name}")
