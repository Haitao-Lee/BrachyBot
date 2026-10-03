"""Prepare independent review forms or evaluate an authenticated recording.

Neither operation runs a model. A blank form never supplies true judgements.
"""
import argparse
import hmac
import json
from pathlib import Path

from .contracts import compile_contract
from .prepare import cases
from .runner import evaluate_recording, sign_recording


def review_form(case,recording,sut_id):
    contract=compile_contract(case)
    finals=[r for r in recording["turn_responses"] if r["final"]]
    rows=[]
    for index,reply in enumerate(finals):
        criteria=contract["response_rubric"] if index==len(finals)-1 else [{"id":"turn-fulfillment",
                "statement":"Fulfil this turn's local scope, pending/terminal facts, and corrections."}]
        for criterion in criteria:
            rows.append({"scenario_id":case["id"],"execution_id":recording["execution_id"],
                    "criterion_id":criterion["id"],"criterion":criterion["statement"],"turn":reply["turn"],
                    "sut_id":sut_id,"response_text":reply["text"],"response_sha256":reply["sha256"],
                    "response_span":None,"reviewer_id":None,"reviewer_role":None,"passed":None,"reason":None})
    return {"status":"PENDING_INDEPENDENT_REVIEW","observation_sha256":recording["observation_sha256"],
            "response_facts":contract["response_facts"],"review_rows":rows,
            "warning":"Do not replace semantic judgement with keyword matching; machine truth and delivered response may disagree."}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=["form","evaluate"])
    parser.add_argument("--case",required=True,choices=[c["id"] for c in cases()])
    parser.add_argument("--recording",required=True,type=Path)
    parser.add_argument("--collector-key",required=True,type=Path)
    parser.add_argument("--sut-id",required=True)
    parser.add_argument("--source-sha256")
    parser.add_argument("--reviews",type=Path)
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args(argv)
    recording=json.loads(args.recording.read_text(encoding="utf-8")); key=args.collector_key.read_bytes()
    if not hmac.compare_digest(recording.get("collector_signature",""),sign_recording(recording,key)):
        parser.error("unauthenticated collector recording")
    case=next(c for c in cases() if c["id"]==args.case)
    if args.mode=="form": result=review_form(case,recording,args.sut_id)
    else:
        reviews=json.loads(args.reviews.read_text(encoding="utf-8"))["review_rows"] if args.reviews else []
        result=evaluate_recording(case,recording,reviews=reviews,sut_id=args.sut_id,
                                  source_sha256=args.source_sha256,collector_key=key)
    if args.out.exists(): parser.error("output exists; refusing to overwrite a review/result")
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(args.out),"mode":args.mode,"sut_executed":False}))
    return 0


if __name__=="__main__": raise SystemExit(main())
