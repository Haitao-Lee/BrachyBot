"""Opt-in JSONL worker runner and existing evaluator integration.

Default is validate-only. --execute is deliberately required for any SUT work.
The child sees only user turns, observable synthetic state and semantic tools.
No private task file, gold, scripted fault schedule or reviewer output is sent.
This is API isolation, NOT a hostile-code/container security boundary.
"""
import argparse
from copy import deepcopy
import json
import hmac
from hashlib import sha256
import os
from pathlib import Path
import queue
import shlex
import subprocess
import tempfile
import threading
import time

from tools.evaluator_contract import EvaluatorContext
from tools.run_task import evaluate
from .contracts import compile_contract
from .environment import Environment, OPERATIONS
from .fixtures_runtime import digest, materialize
from .oracle_runtime import review_response  # registers oracle
from .prepare import cases, task_for, build


class ProtocolError(RuntimeError): pass


def safe_public_state(state):
    # Authoritative observable state is intentionally available. No future
    # fault schedule, gold or secret reviewer policy lives in this dictionary.
    private={"mask_file","mask_sha256","annotation_hits_mask","target_pixels","full_pixels","render_reference","case_B_camera"}
    def strip(v):
        if isinstance(v,dict): return {k:strip(x) for k,x in v.items() if k not in private}
        if isinstance(v,list): return [strip(x) for x in v]
        return deepcopy(v)
    out=strip(state); out.pop("execution_id",None); return out


def sign_recording(recording, key):
    payload={k:v for k,v in recording.items() if k!="collector_signature"}
    return hmac.new(key,digest(payload).encode(),sha256).hexdigest()


def execute(case, command, artifact_root, *, timeout_s=120, collector_key=None, pass_env=()):
    """Produce an independently collected recording, NOT a scored result."""
    if not command or timeout_s<=0: raise ValueError("explicit command/deadline required")
    environment=Environment(case,artifact_root)
    messages=queue.Queue()
    clean_env={k:v for k,v in os.environ.items() if k in {"PATH","SYSTEMROOT","WINDIR","LANG","LC_ALL","PYTHONIOENCODING"}}
    clean_env.update(PYTHONIOENCODING="utf-8",PYTHONDONTWRITEBYTECODE="1")
    for name in pass_env:
        if not isinstance(name,str) or not name.replace("_","").isalnum(): raise ValueError("invalid explicit environment name")
        if name in os.environ: clean_env[name]=os.environ[name]
    with tempfile.TemporaryDirectory(prefix="rur-worker-") as cwd:
        proc=subprocess.Popen(command,cwd=cwd,env=clean_env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,text=True,encoding="utf-8",bufsize=1)
        def read():
            try:
                while True:
                    line=proc.stdout.readline(65537)
                    if not line: messages.put(None); break
                    if len(line)>65536 or not line.endswith("\n"):
                        messages.put(ProtocolError("worker message exceeded 64 KiB")); break
                    messages.put(json.loads(line))
            except Exception as exc: messages.put(ProtocolError(str(exc)))
        threading.Thread(target=read,daemon=True).start()
        deadline=time.monotonic()+timeout_s; call_count=0
        def send(msg):
            proc.stdin.write(json.dumps(msg,ensure_ascii=False,allow_nan=False)+"\n"); proc.stdin.flush()
        def receive():
            left=deadline-time.monotonic()
            if left<=0: raise ProtocolError("worker deadline exceeded")
            try: msg=messages.get(timeout=left)
            except queue.Empty: raise ProtocolError("worker deadline exceeded")
            if msg is None: raise ProtocolError("worker exited before protocol terminal")
            if isinstance(msg,Exception): raise msg
            if not isinstance(msg,dict): raise ProtocolError("message must be object")
            return msg
        def drive():
            nonlocal call_count
            while True:
                msg=receive(); kind=msg.get("type")
                if kind=="call":
                    call_count+=1
                    if call_count>96: raise ProtocolError("operation budget exceeded")
                    args=msg.get("arguments",{})
                    if not isinstance(args,dict): raise ProtocolError("arguments must be object")
                    if not isinstance(msg.get("operation"),str): raise ProtocolError("operation must be a string")
                    result=environment.call(msg.get("operation"),args)
                    send({"type":"result","id":msg.get("id"),"result":safe_public_state(result)})
                elif kind=="response":
                    if type(msg.get("final",True)) is not bool: raise ProtocolError("final must be boolean")
                    environment.deliver_response(msg.get("text"),final=msg.get("final",True),
                                                 outcome=msg.get("outcome","COMPLETED"),stage=msg.get("stage","final"),turn=msg.get("turn_id"),
                                                 attachments=msg.get("attachments",[]),downloads=msg.get("downloads",[]))
                elif kind=="yield": return
                else: raise ProtocolError(f"unexpected worker message {kind!r}")
        try:
            send({"type":"start","execution_id":environment.execution_id,
                  "operations":sorted(OPERATIONS),"profile":"decision_sandbox",
                  "state":safe_public_state(environment.state)})
            if receive().get("type")!="ready": raise ProtocolError("ready handshake required")
            users=[s for s in case["steps"] if s["kind"]=="user"]
            if not users:
                send({"type":"environment_update","state":safe_public_state(environment.state)})
                drive()
            else:
                for user in users:
                    environment.begin_turn(user["text"],user["language"])
                    send({"type":"user","turn_id":environment.current_turn,"text":user["text"],"language":user["language"]})
                    drive()
            send({"type":"finish"}); drive()
            recording=environment.collect(); recording["transport_status"]="completed"
        except (ProtocolError,BrokenPipeError,ValueError) as exc:
            recording=environment.collect(); recording.update(transport_status="failed",transport_error=str(exc))
        finally:
            if proc.poll() is None: proc.terminate()
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=3)
            for stream in (proc.stdin,proc.stdout):
                if stream: stream.close()
    recording.pop("observation_sha256",None); recording["observation_sha256"]=digest(recording)
    recording["contract_sha256"]=digest(compile_contract(case))
    recording.pop("observation_sha256",None); recording["observation_sha256"]=digest(recording)
    if collector_key: recording["collector_signature"]=sign_recording(recording,collector_key)
    return recording


def evaluate_recording(case, recording, *, reviews=(), sut_id="unspecified", source_sha256=None, collector_key=None):
    """Use existing gate/item-scoring; private contract not taken from a SUT."""
    if not collector_key or not hmac.compare_digest(recording.get("collector_signature",""),sign_recording(recording,collector_key)):
        raise ValueError("recording needs evaluator-owned collector signature; a SUT-authored JSON is not evidence")
    recording={k:v for k,v in recording.items() if k!="collector_signature"}
    contract=compile_contract(case)
    if recording.get("contract_sha256")!=digest(contract):
        raise ValueError("contract changed after collection; do not score against unfrozen new gold")
    if digest(recording.get("initial_state"))!=digest(materialize(case)):
        raise ValueError("fixture differs from the task-owned frozen reference")
    actual=[(row["args"].get("text"),row["args"].get("language")) for row in recording.get("audit",[]) if row["kind"]=="user"]
    wanted=[(s["text"],s["language"]) for s in case["steps"] if s["kind"]=="user"]
    if actual!=wanted: raise ValueError("collected dialogue differs from the task protocol")
    replies=[r for r in recording.get("turn_responses",[]) if r["final"]]
    obs={"oracle_inputs":{"real_user_request":{"observation":recording}},
         "response":replies[-1]["text"] if replies else "", "partial_status":"PARTIAL"}
    context=EvaluatorContext(inputs={"real_user_request":{"contract":contract}},
            observed_keys={"real_user_request":("observation",)},independently_observed=True,
            audit_complete=False, scenario_id=case["id"],mode="development",
            identity={"sut_id":sut_id,"source_sha256":source_sha256,"profile":"decision_sandbox",
                      "semantic_review":"pending_independent_review","clinical_validation":False},
            response_checker=lambda text,observed,task:review_response(contract,recording,list(reviews)))
    result=evaluate(task_for(case),obs,recording.get("initial_state",{}),context=context)
    result.update(evaluation_mode="development_only",comparable_sut_result=False,
                  confirmatory_eligible=False,real_browser_observed=False)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case",choices=[c["id"] for c in cases()])
    parser.add_argument("--execute",action="store_true")
    parser.add_argument("--worker",help="Explicit trusted worker command, JSONL protocol")
    parser.add_argument("--out",type=Path)
    parser.add_argument("--timeout-s",type=float,default=120)
    parser.add_argument("--pass-env",action="append",default=[],help="Explicit worker credential/config variable name; values are not logged")
    args=parser.parse_args(argv)
    if not args.execute:
        report=build(check=True); print(json.dumps(report,ensure_ascii=False)); return 0 if report["build_ok"] else 1
    if not args.case or not args.worker or not args.out: parser.error("execution requires --case --worker --out")
    if not build(check=True)["build_ok"]: parser.error("compiled source/fixture/gold manifest drift; rebuild and review before execution")
    case=next(c for c in cases() if c["id"]==args.case)
    args.out.mkdir(parents=True,exist_ok=False)
    key=os.urandom(32)
    secret=args.out/"collector.key"; secret.write_bytes(key); secret.chmod(0o600)
    recording=execute(case,shlex.split(args.worker),args.out/"artifacts",timeout_s=args.timeout_s,collector_key=key,pass_env=args.pass_env)
    (args.out/"recording.json").write_text(json.dumps(recording,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"recording":str(args.out/"recording.json"),"status":recording["transport_status"],
                      "scored":False,"requires_independent_response_review":True}))
    return 0 if recording["transport_status"]=="completed" else 2


if __name__=="__main__": raise SystemExit(main())
