#!/usr/bin/env python3
"""BCP · multi-turn dialogues from real intents (DESIGN §30.2 D9).

Pairs consecutive real follow-up questions (from follow-up-prone categories)
into 2-turn Task Scenarios, so the bank exercises conversation continuity, not
only single-shot prompts.

Quality gates (round 4):

* both turns must carry real text (``MIN_TEXT``) -- an empty turn is an
  unanswerable task, never shipped;
* per-task before/after states, verified at generation time by the real
  ``state_invariant`` checker (positive passes, negative trips).

    python tools/bcp/multiturn.py --n 40
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, BB)

from oracles import get_oracle  # noqa: E402  (real checker: the self-proof)

PRO = "fixtures/setup/prostate_s02_full_pipeline.py"
FOLLOWUP_CATS = ("multi_turn", "workflow", "medium_complexity", "treatment_planning",
                 "clinical_workflow", "advanced_workflows", "multi_step")
MIN_TEXT = 10


def _rng_for(intent_id: str) -> random.Random:
    return random.Random(hashlib.sha256(("mt:" + intent_id).encode("utf-8")).hexdigest())


def _pair(rng: random.Random, n: int) -> Dict[str, Dict[str, Any]]:
    k = rng.randrange(1, 4)
    before = {"plan": {"status": "ready", "seeds": [f"s{i}" for i in range(k)],
                       "planning_version": rng.randrange(1, 9),
                       "planning_id": f"plan_{n:03d}"}}
    pos = {"before": before, "after": before}
    after = {"plan": dict(before["plan"])}
    after["plan"]["status"] = rng.choice(["draft", "corrupted"])
    neg = {"before": before, "after": after}
    return pos, neg


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--intents", default=os.path.join(BB, "corpus", "intents", "intents.jsonl"))
    ap.add_argument("--out-tasks", default=os.path.join(BB, "tasks"))
    ap.add_argument("--out-replay", default=os.path.join(BB, "tests", "replay"))
    ap.add_argument("--n", type=int, default=40)
    args = ap.parse_args(argv)

    by_cat: Dict[str, List[Dict]] = {}
    skipped_empty = 0
    for line in open(args.intents, encoding="utf-8"):
        r = json.loads(line)
        if r["category"] in FOLLOWUP_CATS and len((r.get("redacted_text") or "").strip()) >= MIN_TEXT:
            by_cat.setdefault(r["category"], []).append(r)
        elif r["category"] in FOLLOWUP_CATS:
            skipped_empty += 1

    seq: List[Dict] = []
    for cat in FOLLOWUP_CATS:
        seq.extend(sorted(by_cat.get(cat, []), key=lambda r: r["intent_id"]))

    neg_path = os.path.join(args.out_replay, "_negatives.json")
    all_neg = json.load(open(neg_path, encoding="utf-8")) if os.path.isfile(neg_path) else {}

    made = 0
    i = 0
    n = 0
    while made < args.n and i + 1 < len(seq):
        a, b = seq[i], seq[i + 1]
        i += 2
        if a["intent_id"] == b["intent_id"]:
            continue
        n += 1
        tid = f"B-MTURN-{n:04d}"
        rng = _rng_for(a["intent_id"])
        pos, neg = _pair(rng, n)
        r_pos = get_oracle("state_invariant")().check(**pos)
        r_neg = get_oracle("state_invariant")().check(**neg)
        if not r_pos.passed or r_neg.passed or not r_neg.violations:
            print(f"REJECT multiturn #{n}: self-proof failed", file=sys.stderr)
            continue
        task = {
            "schema_version": "1.0", "id": tid, "track": "B", "layers": ["L4"],
            "comparability": ["alpha", "beta"], "construct": "multi_turn_continuity",
            "cost_class": "state_only", "power_role": "exploratory",
            "clinical_intent": f"Multi-turn session: {a['redacted_text'][:40]} ... then follow up with {b['redacted_text'][:40]}",
            "fixture": {"case_family": "legacy/multiturn", "setup_script": PRO,
                        "initial_state_hash": "sha256:" + "0" * 64},
            "unit": {"kind": "task_scenario", "group_type": "G-CTX",
                     "contrast_family_id": "legacy/multiturn"},
            "protocol": {"mode": "multi_turn",
                         "turns": [{"role": "user", "text": a["redacted_text"], "lang": a["lang"]},
                                   {"role": "user", "text": b["redacted_text"], "lang": b["lang"]}],
                         "ui_counterpart": None, "budget": {"wall_clock_s": 120, "turns": 2, "tool_calls": 12},
                         "allowed_intermediates": [], "audit_required": False, "n_runs": 3},
            "oracle": {"kind": "program", "check": "state_invariant", "constraint_class": "postcondition",
                       "expect": None, "tolerance": None, "assist_only": False,
                       "independent_check": True, "evidence_keys": [], "gold": None},
            "scoring": {"primary_metric": "multi_turn_state_ok", "gate_refs": [], "weight": 1.0,
                        "difficulty_target": "medium"},
            "anti_gaming": {"paraphrase_group": f"MTURN-{n:04d}", "hidden": False,
                            "generation_seed": 2026, "canary_class": None,
                            "behavioral_probes": ["multi_turn"], "contrast_family_id": "legacy/multiturn"},
            "provenance": {"source": "legacy_migrated",
                           "derived_from": f"legacy:{a['source']}#{a['legacy_id']}+{b['source']}#{b['legacy_id']}",
                           "guideline_ref": None, "reviewers": ["auto-verifier"], "authored_on": "2026-09-30",
                           "deprecated": None},
        }
        json.dump(task, open(os.path.join(args.out_tasks, tid + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        json.dump({"sut_id": "BrachyBot-replay", "intent_class": "imperative",
                   "partial_status": "COMPLETED", "oracle_inputs": {"state_invariant": pos},
                   "_comment": f"CI replay for {tid}: 2-turn continuity, state intact. NOT benchmark data."},
                  open(os.path.join(args.out_replay, tid + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        all_neg[tid] = {"oracle_inputs": {"state_invariant": neg}}
        made += 1

    json.dump(all_neg, open(neg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"created {made} multi-turn dialogues (skipped {skipped_empty} empty-text intents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
