"""Authoritative isolated decision sandbox with out-of-band observation.

It executes common semantic effects, records attempts/commits separately, and
owns fixtures, fault barriers, persistence, receipts and delivered attachments.
It never loads gold or enforces a scenario-specific expected-action whitelist.
Clinical computation outputs are explicit synthetic fixtures, not real doses.
"""
from copy import deepcopy
from hashlib import sha256
import base64
import io
import json
from pathlib import Path
import time
import uuid

from .event_driver import EventDriver
from .fixtures_runtime import annotate_ppm, camera, digest, localize_report, materialize, pdf_bytes, render, render_tree


READ_ONLY = {"read","read_artifact","poll","advance","provider","capabilities"}
OPERATIONS = READ_ONLY | {"set","submit","cancel","restore","cancel_preview","capture",
                         "monitor_stop","refresh","export","language"}


class Environment:
    def __init__(self, case, root, execution_id=None):
        self.execution_id=execution_id or uuid.uuid4().hex
        self.state=materialize(case)
        self.initial=deepcopy(self.state)
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.journal=[]; self.responses=[]; self.sequence=0; self.started=time.monotonic()
        self.events=EventDriver(case["steps"])
        self.held=set(); self.delivery_held=False; self.capture_views=None
        self.next_result_override=None; self.origin_state=None; self.delivery_scope=None
        self.provider_fault=None; self.deferred_reason=None; self.pending_captures=[]
        self.operations={}; self.current_turn=0
        self.state["execution_id"]=self.execution_id
        self.events.emit("start",self)

    def scope(self):
        return {k:self.state.get(k) for k in ("case_id","session_id","planning_id","geometry_revision")}

    def record(self, kind, operation, payload=None, *, source="sut", status=None):
        self.sequence+=1
        row={"seq":self.sequence,"time_s":time.monotonic()-self.started,"kind":kind,
             "operation":operation,"args":deepcopy(payload or {}),"source":source,
             "status":status,"scope":self.scope(),"turn":self.current_turn,
             "execution_id":self.execution_id}
        self.journal.append(row)
        return row

    def sync_display(self):
        for key in ("tree_state","render_state","saved_state"):
            self.state[key]=deepcopy(self.state["objects"])
        # Actual serialization/reload, not a success flag pretending to persist.
        self._persist()
        restored=json.loads((self.root/"persisted-state.json").read_text(encoding="utf-8"))
        self.state["saved_state"]=restored["objects"]

    def _persist(self):
        (self.root/"persisted-state.json").write_text(json.dumps(self.state,ensure_ascii=False,sort_keys=True,allow_nan=False),encoding="utf-8")

    def invalidate(self):
        for k in self.state["artifacts"]: self.state["artifacts"][k]="stale"

    def begin_turn(self, text, language):
        self.current_turn+=1
        self.state["request"]={"status":"running","send_enabled":False,"final_count":0}
        self.record("user","input",{"text":text,"language":language},source="user")

    def deliver_response(self, text, *, final=True, outcome="COMPLETED", stage="final", turn=None, attachments=(), downloads=()):
        if not isinstance(text,str) or not text.strip(): raise ValueError("empty delivered reply")
        owner=self.current_turn if turn is None else turn
        if type(owner) is not int or not 0<=owner<=self.current_turn: raise ValueError("invalid reply owner")
        for refs,pool,destination in ((attachments,"available_captures","attachments"),(downloads,"available_downloads","downloads")):
            if not isinstance(refs,(list,tuple)) or any(not isinstance(ref,str) for ref in refs): raise ValueError("delivery references must be IDs")
            if len(set(refs))!=len(refs): raise ValueError("duplicate delivery references")
            for ref in refs:
                item=next((f for f in self.state[pool] if f["id"]==ref),None)
                if not item or not item.get("decoded",True) or item.get("superseded") or item["scope"]!=self.scope():
                    raise ValueError("delivery reference unavailable or superseded")
                if not any(f["id"]==ref for f in self.state[destination]):
                    delivered=deepcopy(item); delivered.update(delivered=True,delivered_at=self.sequence+1)
                    self.state[destination].append(delivered)
                    self.record("attachment" if destination=="attachments" else "download","delivered",{"id":ref},source="transport")
        previous=self.current_turn; self.current_turn=owner
        row=self.record("response","deliver",{"text":text,"final":final,"outcome":outcome,"stage":stage,"attachments":list(attachments),"downloads":list(downloads)},source="transport")
        self.responses.append({"text":text,"final":final,"outcome":outcome,"stage":stage,
                               "turn":self.current_turn,"at":row["seq"],"sha256":sha256(text.encode()).hexdigest(),
                               "state_at_delivery":{key:deepcopy(self.state.get(key)) for key in
                                   ("objects","artifacts","geometry_revision","planning_version",
                                    "monitor","language","viewer","viewers","report")}})
        if final and owner==previous:
            r=self.state["request"]; r["final_count"]+=1; r.update(status="terminal",send_enabled=True)
            self.record("lifecycle","final",{"outcome":outcome,"final_count":r["final_count"]},source="transport")
        elif final:
            self.record("lifecycle","final",{"outcome":outcome,"late_owner":owner},source="transport")
        self.current_turn=previous

    def call(self, operation, args=None):
        args=deepcopy(args or {})
        if not isinstance(args,dict): raise ValueError("arguments must be object")
        self.record("call",operation,args,status="attempted")
        if any(k in args and args[k]!=self.state.get(k) for k in ("tenant_id","case_id","session_id","planning_id")):
            self.record("effect",operation,args,status="rejected")
            return {"status":"failed","code":"OWNER_SCOPE_MISMATCH"}
        if operation not in OPERATIONS:
            self.record("effect",operation,args,status="rejected")
            return {"status":"failed","code":"UNSUPPORTED_OPERATION"}
        # API-level idempotency uses identity + exact operation fingerprint,
        # not just a tool name. Collisions reject, never reuse another effect.
        op_id=args.get("op_id")
        signature=digest({"operation":operation,"args":{k:v for k,v in args.items() if k!="op_id"},"scope":self.scope()})
        if op_id and op_id in self.operations:
            old=self.operations[op_id]
            if old["signature"]!=signature:
                return {"status":"failed","code":"IDEMPOTENCY_CONFLICT"}
            return deepcopy(old["result"])
        try:
            result=getattr(self,"_"+operation)(args)
        except (KeyError,ValueError,TypeError) as exc:
            self.record("effect",operation,args,status="rejected")
            result={"status":"failed","code":"INVALID_ARGUMENTS","detail":str(exc)}
        if op_id: self.operations[op_id]={"signature":signature,"result":deepcopy(result)}
        if self.next_result_override:
            result=deepcopy(self.next_result_override); self.next_result_override=None
        return result

    def _read(self,a):
        value=self.state
        for part in a.get("path","").split(".") if a.get("path") else []: value=value[part]
        result=deepcopy(value)
        self.record("read","state",{"path":a.get("path",""),"bytes":len(json.dumps(result,ensure_ascii=False))})
        return {"status":"completed","data":result}

    def _capabilities(self,a):
        return {"status":"completed","operations":sorted(OPERATIONS),"clinical_engine":"synthetic_only",
                "unsupported":["approve","printer","cross_tenant_access"],"environment_profile":"decision_sandbox"}

    def _read_artifact(self,a):
        records=self.state["available_captures"]+self.state["available_downloads"]
        record=next((r for r in records if r["id"]==a["id"]),None)
        if not record or record["scope"]!=self.scope() or not record.get("decoded",True): raise ValueError("artifact unavailable")
        data=(self.root/record["file"]).read_bytes()
        if data.startswith(b"P6"):
            from PIL import Image
            image=Image.open(io.BytesIO(data)); encoded=io.BytesIO(); image.save(encoded,format="PNG")
            return {"status":"completed","mime_type":"image/png","base64":base64.b64encode(encoded.getvalue()).decode()}
        offset=a.get("offset",0)
        if type(offset) is not int or not 0<=offset<=len(data): raise ValueError("bad chunk offset")
        chunk=data[offset:offset+12288]
        return {"status":"completed","mime_type":"application/pdf","size_bytes":len(data),
                "offset":offset,"next_offset":offset+len(chunk),"base64":base64.b64encode(chunk).decode()}

    def _set(self,a):
        path=a["path"]; parts=path.split(".")
        if parts[0]=="objects":
            if len(parts)!=3 or parts[2] not in {"visible","opacity","color"}: raise ValueError("unsupported object field")
            if self.state["viewer"].get("status") in {"unavailable","loading"}: raise ValueError("VIEWER_UNAVAILABLE")
            value=a["value"]
            if parts[2]=="visible" and type(value) is not bool: raise ValueError("visibility is boolean")
            if parts[2]=="opacity" and (type(value) not in (int,float) or not 0<=value<=1): raise ValueError("opacity outside [0,1]")
            if parts[2]=="color" and value not in {"red","blue","cyan","green"}: raise ValueError("unknown color")
        elif len(parts)==3 and parts[0]=="viewers" and parts[2] in {"zoom","pan"}:
            value=a["value"]
            if parts[2]=="zoom" and (type(value) not in (float,int) or not 0<value<=16): raise ValueError("bad zoom")
        else: raise ValueError("unsupported mutable path")
        owner=self.state
        for part in parts[:-1]: owner=owner[part]
        before=deepcopy(owner.get(parts[-1])); owner[parts[-1]]=deepcopy(value)
        self.sync_display()
        self.record("effect","set",{**a,"before":before},status="committed")
        self.events.emit("visibility.committed" if parts[-1]=="visible" else "opacity.committed" if parts[-1]=="opacity" else "color.committed",self)
        return {"status":"completed","value":value,"scope":self.scope()}

    def _submit(self,a):
        kind=a["kind"]
        if kind not in {"dose","quality","guide","report","report_figures","segmentation","trajectory_init","manual_next"}: raise ValueError("unsupported job")
        if self.state["planning_id"] is None and kind!="segmentation": raise ValueError("NO_CURRENT_PLAN")
        if kind=="segmentation":
            model=self.state.get("model_catalog",{}).get(self.state.get("site"))
            if not model or not a.get("model") or a["model"]!=model: raise ValueError("explicit verified model required")
        active=[j for j in self.state["jobs"] if j["kind"]==kind and j["status"] in {"queued","running"}]
        if active: return {"status":"running","job_id":active[0]["id"],"deduplicated":True}
        jid=f"{self.execution_id}-job-{len(self.state['jobs'])}"
        j={"id":jid,"kind":kind,"status":"queued","scope":self.scope(),"args":a,
           "requested_at":self.sequence,"execution_id":self.execution_id}
        input_kinds={"quality":("dose",), "report":("dose","quality"),
                     "report_figures":("dose",)}.get(kind,())
        j["inputs"]={key:deepcopy(self.state["artifact_records"].get(key)) for key in input_kinds}
        self.state["jobs"].append(j); self.record("effect","submit",a,status="committed")
        self.events.emit(f"{kind}.queued",self)
        self.events.emit(f"{kind}.accepted",self)
        if j["status"]=="queued": j["status"]="running"
        self.events.emit(f"{kind}.running",self)
        return {"status":j["status"],"job_id":jid,"scope":j["scope"]}

    def fail_job(self,kind,code):
        for j in self.state["jobs"]:
            if j["kind"]==kind and j["status"] in {"queued","running"}:
                j.update(status="failed",code=code)
                self.record("job","failed",{"kind":kind,"job_id":j["id"],"code":code},source="environment")

    def install_artifact(self,kind,source="job",job_id=None):
        a={"id":f"{self.execution_id}-{kind}-{self.sequence}","kind":kind,"status":"completed",
           "case_id":self.state["case_id"],"planning_id":self.state["planning_id"],
           "revision":self.state["geometry_revision"],"execution_id":self.execution_id,
           "source":source,"job_id":job_id,"created_at":self.sequence,"synthetic":True}
        self.state["artifact_records"][kind]=a
        if kind in self.state["artifacts"]: self.state["artifacts"][kind]="current"
        return a

    def complete_job(self,kind):
        j=next((j for j in self.state["jobs"] if j["kind"]==kind and j["status"] in {"queued","running"}),None)
        if j is None: return
        if j["scope"]!=self.scope():
            j.update(status="failed",code="SUPERSEDED"); return
        self.events.emit(f"{kind}.result",self)
        if j["status"]=="failed": return
        a=self.install_artifact(kind,job_id=j["id"])
        a["sources"]=deepcopy(j["inputs"])
        if kind=="dose": self.state["artifacts"]["dvh"]="current"
        if kind=="segmentation":
            a["label_semantics"]={"1":"GTVp","2":"GTVn"}; a["model"]=j["args"]["model"]
        if kind=="report":
            payload=pdf_bytes(self.state); self._save_artifact(a,"report.pdf",payload)
        if kind=="trajectory_init":
            self.state.update(manual_stage=1,intermediate_node={"id":"init-group","visible":True,
                  "trajectories":[[[-10,0,-10],[10,0,10]]],"close_points_mm":[[0,0,0]],"rendered":True})
        if kind=="manual_next":
            self.state["manual_stage"]+=1
            self.state["intermediate_node"]["visible"]=False
        if kind=="report_figures":
            figures=[]; original=deepcopy(self.state["viewer"])
            try:
                for role,span in (("global",60),("CTV_closeup",32)):
                    self.state["viewer"]["camera"]=camera(role)
                    self.state["viewer"]["camera"]["vertical_span_mm"]=span
                    f=self._capture({"target":"ctv-A","views":["viewer-3d"],"role":role})
                    figures.extend(f.get("attachments",[]))
            finally: self.state["viewer"]=original
            a["figures"]=figures
            payload=pdf_bytes(self.state,figures=[{**f,"data":(self.root/f["file"]).read_bytes()} for f in figures])
            self._save_artifact(a,"report-figures.pdf",payload)
        j.update(status="completed",artifact_id=a["id"])
        self.record("job","completed",{"kind":kind,"job_id":j["id"],"artifact_id":a["id"]},source="environment")
        self.events.emit(f"{kind}.completed",self)
        if kind=="trajectory_init": self.events.emit("init.completed",self)

    def _advance(self,a):
        # One deterministic tick, NOT an arbitrary sleep or unlimited loop.
        for j in list(self.state["jobs"]):
            if j["status"] in {"queued","running"}:
                if j["kind"] not in self.held: self.complete_job(j["kind"])
        if self.pending_captures:
            self.events.emit("attachment.decoded",self)
            if not self.delivery_held:
                for attachment in self.pending_captures: attachment["decoded"]=True
                self.state["available_captures"].extend(self.pending_captures); self.pending_captures=[]
                self.record("attachment","decoded",{},source="environment")
        return {"status":"completed","jobs":deepcopy(self.state["jobs"])}

    def _poll(self,a):
        return {"status":"completed","jobs":deepcopy(self.state["jobs"]),"monitor":deepcopy(self.state["monitor"]),"attachments":deepcopy(self.state["attachments"])}

    def _cancel(self,a):
        matches=[j for j in self.state["jobs"] if j["kind"]==a["kind"] and j["scope"]==self.scope() and j["status"] in {"queued","running"}]
        for j in matches:
            j["status"]="cancelled"; self.record("effect","cancel",a,status="committed")
        return {"status":"completed","cancelled":[j["id"] for j in matches]}

    def _restore(self,a):
        self.events.emit("restore.precommit",self)
        token=next((e for e in self.state["edit_log"] if e["id"]==a["token"]),None)
        if not token or token["consumed"] or token["to"]!=self.state["geometry_revision"]:
            self.record("effect","restore",a,status="rejected"); return {"status":"failed","code":"STALE_TOKEN"}
        if any(token.get(k)!=self.state.get(k) for k in ("case_id","session_id","planning_id")):
            raise ValueError("TOKEN_OWNER_MISMATCH")
        self.state["objects"][token["target"]]["position_mm"]=deepcopy(token["before_position_mm"])
        token["consumed"]=True; self.state["geometry_revision"]+=1; self.state["planning_version"]+=1
        self.invalidate(); self.sync_display(); self.record("effect","restore",a,status="committed")
        return {"status":"completed","scope":self.scope()}

    def _cancel_preview(self,a):
        self.state["preview"]=None; self.state["viewer"]["dragging"]=False
        self.record("effect","cancel_preview",a,status="committed")
        return {"status":"completed"}

    def _save_artifact(self,record,name,payload):
        # Names are generated by evaluator code, never SUT-supplied paths.
        name=f"{self.sequence}-{name}"; dest=self.root/name; dest.write_bytes(payload)
        record.update(file=name,sha256=sha256(payload).hexdigest(),size_bytes=len(payload))

    def _capture(self,a):
        target=a["target"]; views=a.get("views",["data-tree","viewer-3d"])
        if not views or set(views)-{"data-tree","viewer-3d"}: raise ValueError("unsupported views")
        source_state=deepcopy(self.state); original_scope=self.scope()
        original=deepcopy({"objects":self.state["objects"],"viewer":self.state["viewer"]})
        if target not in source_state["objects"]: raise ValueError("unknown target")
        self.record("effect","capture",a,status="committed")
        self.events.emit("capture.dispatched",self); self.events.emit("captures.dispatched",self)
        if source_state["monitor"].get("active"): self.events.emit("monitor.capture.dispatched",self)
        self.events.emit("capture.attempted",self)
        delivered=[]
        try:
            if source_state["viewer"].get("status") in {"loading","unavailable"} or self.deferred_reason:
                self.record("capture","deferred",{"target":target,"reason":self.deferred_reason or "viewer_unavailable"},source="environment")
                return {"status":"deferred","reason":self.deferred_reason or "viewer_unavailable","retry":"same_scope_only"}
            source_state["objects"][target]["visible"]=True
            for other in a.get("hide",[]): source_state["objects"][other]["visible"]=False
            if "camera" in a: source_state["viewer"]["camera"]=deepcopy(a["camera"])
            for view in views:
                if self.capture_views is not None and view not in self.capture_views: continue
                attach={"id":f"{self.execution_id}-image-{self.sequence}-{len(delivered)}",
                        "target":target,"view":view,"role":a.get("role"),"scope":original_scope,
                        "execution_id":self.execution_id,"created_at":self.sequence,"delivered":False,
                        "camera":deepcopy(source_state["viewer"]["camera"]),"hidden":a.get("hide",[])}
                if view in ("viewer-3d","data-tree"):
                    image=render(source_state,target) if view=="viewer-3d" else render_tree({"objects":original["objects"]},target)
                    attach.update({k:image[k] for k in ("width","height","target_pixels","full_pixels","bbox","clipped")})
                    points=[(i%image["width"],i//image["width"]) for i,v in enumerate(image["visible_mask"]) if v]
                    anchor=a.get("annotation_anchor",list(points[len(points)//2]) if points else None)
                    attach["annotation_anchor"]=anchor
                    attach["annotation_hits_mask"]=bool(anchor and len(anchor)==2 and all(type(q)==int for q in anchor)
                        and 0<=anchor[0]<image["width"] and 0<=anchor[1]<image["height"]
                        and image["visible_mask"][anchor[1]*image["width"]+anchor[0]])
                    annotated=annotate_ppm(image["ppm"],image["width"],image["height"],anchor,target)
                    self._save_artifact(attach,f"{target}-{view}.ppm",annotated)
                    mask_name=attach["file"]+".mask.pgm"; (self.root/mask_name).write_bytes(image["pgm"])
                    attach.update(mask_file=mask_name,mask_sha256=sha256(image["pgm"]).hexdigest())
                attach["decoded"]=not self.delivery_held
                if self.delivery_scope: attach.update(superseded=True)
                if not attach.get("superseded"):
                    (self.pending_captures if self.delivery_held else self.state["available_captures"]).append(attach)
                delivered.append(attach)
            self.record("attachment","decoded" if not self.delivery_held else "pending",{"ids":[f["id"] for f in delivered]},source="environment")
            return {"status":"pending" if self.delivery_held else "completed","attachments":delivered}
        finally:
            # Nothing from an originating case may restore into a successor.
            if self.scope()==original_scope:
                self.state["objects"]=original["objects"]; self.state["viewer"]=original["viewer"]
                self.sync_display()
            self.record("capture","restored",{"original_scope":original_scope,"active_scope":self.scope()},source="environment")

    def _monitor_stop(self,a):
        self.events.emit("monitor.stop.requested",self)
        if a["run_id"]!=self.state["monitor"].get("run_id"): raise ValueError("RUN_OWNER_MISMATCH")
        self.state["monitor"]["active"]=False
        self.record("effect","monitor_stop",a,status="committed")
        return {"status":"completed","active":False}

    def _refresh(self,a):
        self.sync_display(); self.record("effect","refresh",a,status="committed")
        return {"status":"completed"}

    def _export(self,a):
        if a.get("kind")!="report": raise ValueError("unsupported export")
        record=self.state["artifact_records"].get("report",{})
        if record.get("revision")!=self.state["geometry_revision"]: raise ValueError("STALE_REPORT")
        receipt={"id":f"{self.execution_id}-download-{self.sequence}","scope":self.scope(),"delivered":False}
        self._save_artifact(receipt,"report.pdf",pdf_bytes(self.state))
        self.state["available_downloads"].append(receipt); self.record("effect","export",a,status="committed")
        return {"status":"completed","download":receipt}

    def _language(self,a):
        if a["value"] not in {"zh","en"}: raise ValueError("language unsupported")
        self.state["language"]=a["value"]
        self.state["report"].update(body_language=a["value"],captions_language=a["value"])
        localize_report(self.state["report"])
        self._persist()
        self.state["saved_report"]=json.loads((self.root/"persisted-state.json").read_text(encoding="utf-8"))["report"]
        self.record("effect","language",a,status="committed")
        return {"status":"completed"}

    def _provider(self,a):
        self.events.emit("provider.tool_call",self)
        self.events.emit("provider.called",self)
        item={"call":len(self.state["provider_records"])+1,"fault":deepcopy(self.provider_fault)}
        self.state["provider_records"].append(item)
        return {"status":"failed" if self.provider_fault else "completed",**item}

    def collect(self):
        # Sole source of audit/terminal fields; ignore worker self-report fields.
        payload={"execution_id":self.execution_id,"initial_state":deepcopy(self.initial),
                 "terminal_state":deepcopy(self.state),"audit":deepcopy(self.journal),
                 "turn_responses":deepcopy(self.responses),"events_fired":deepcopy(self.events.fired),
                 "events_unhit":deepcopy(self.events.pending),"artifact_root":str(self.root),
                 "environment_profile":"decision_sandbox","clinical_engine":False,
                 "real_browser_observed":False,"collector_id":"rur-authoritative-environment-v1"}
        payload["observation_sha256"]=digest(payload)
        return payload
