#!/usr/bin/env python3
"""BCP · bank open-ended real intents as rubric-scored (assist) scenarios.

DESIGN §30 / §8.5.  The remaining real questions (greeting / reasoning /
communication / multilingual / UI …) have **no deterministic program oracle**,
and §12.4 forbids keyword scoring.  They are banked as ``judge_rubric`` (O5
assist-only) items with an explicit rubric, so the question bank covers the
entire archived intent set.

    python tools/bcp/expand_open.py --cap 1000
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, BB)

PRO = "fixtures/setup/prostate_s02_full_pipeline.py"

# category -> (track, criteria, min_criteria_met)
RUBRIC: Dict[str, Dict[str, Any]] = {
    "greeting":              ("I", ["answers_greeting", "describes_capabilities", "asks_context"], 2),
    "medical_reasoning":     ("C", ["answers_question", "no_hallucination", "cites_basis", "actionable"], 3),
    "response_quality":      ("I", ["answers_question", "clear", "accurate"], 2),
    "language":              ("I", ["answers_question", "correct_language", "no_hallucination"], 2),
    "multilingual":          ("I", ["answers_question", "correct_language", "no_hallucination"], 2),
    "clarification":         ("I", ["asks_clarification", "relevant"], 2),
    "skill_selection":       ("I", ["selects_relevant_skill", "explains_choice"], 2),
    "hallucination":         ("C", ["no_hallucination", "cites_basis"], 2),
    "regression":            ("I", ["answers_question", "no_regression"], 2),
    "stress":                ("I", ["handles_gracefully", "no_crash"], 2),
    "ui_control":            ("I", ["acts_correctly", "reports_state"], 2),
    "ui_interaction":        ("I", ["acts_correctly", "reports_state"], 2),
    "medium_complexity":     ("I", ["answers_question", "multi_step_ok"], 2),
    "workflow":              ("I", ["follows_workflow", "ok"], 2),
    "treatment_planning":    ("I", ["plans_correctly", "reports_plan"], 2),
    "multi_turn":            ("I", ["answers_question", "maintains_context"], 2),
    "input_variations":      ("I", ["parses_correctly", "answers_question"], 2),
    "input_variations_all":  ("I", ["parses_correctly", "answers_question"], 2),
    "clinical_kb":           ("C", ["retrieves_relevant", "accurate"], 2),
    "performance_tracker":   ("C", ["reports_metrics", "accurate"], 2),
    "smoke":                 ("I", ["answers_question", "ok"], 2),
    "weighted_keywords":     ("I", ["answers_question", "ok"], 1),
    "streaming_sse":         ("I", ["streams_correctly", "ok"], 2),
    "tool_calling":          ("I", ["calls_correct_tool", "reports_result"], 2),
    "clinical_scenarios":    ("C", ["answers_question", "no_hallucination", "safe"], 2),
    "e2e_clinical_validation": ("C", ["answers_question", "safe", "complete"], 2),
    "advanced_workflows":    ("I", ["follows_workflow", "complete"], 2),
    "clinical_workflow":     ("I", ["follows_workflow", "ok"], 2),
    "planning_pipeline_stages": ("I", ["follows_workflow", "reports_state"], 2),
}


def _san(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--intents", default=os.path.join(BB, "corpus", "intents", "intents.jsonl"))
    ap.add_argument("--out-tasks", default=os.path.join(BB, "tasks"))
    ap.add_argument("--out-replay", default=os.path.join(BB, "tests", "replay"))
    ap.add_argument("--cap", type=int, default=10**9)
    args = ap.parse_args(argv)

    recs = [json.loads(l) for l in open(args.intents, encoding="utf-8")]
    # intents already banked by expand.py / multiturn.py
    existing: set = set()
    for fn in os.listdir(args.out_tasks):
        if fn.endswith(".json"):
            d = json.load(open(os.path.join(args.out_tasks, fn), encoding="utf-8"))
            dv = d.get("provenance", {}).get("derived_from") or ""
            if dv.startswith("legacy:"):
                for seg in dv.split("#")[1:]:
                    existing.add(seg)

    per_cat: Dict[str, int] = defaultdict(int)
    written = 0
    neg_path = os.path.join(args.out_replay, "_negatives.json")
    all_neg = json.load(open(neg_path, encoding="utf-8")) if os.path.isfile(neg_path) else {}

    for r in recs:
        cat = r["category"]
        if cat not in RUBRIC:
            continue
        if r["legacy_id"] in existing:
            continue
        if per_cat[cat] >= args.cap:
            continue
        per_cat[cat] += 1
        n = per_cat[cat]
        track, crit, need = RUBRIC[cat]
        tid = f"{track}-{_san(cat)}-{n:04d}"
        text = r["redacted_text"]
        task = {
            "schema_version": "1.0", "id": tid, "track": track, "layers": ["L3"],
            "comparability": ["alpha", "beta"], "construct": f"{cat}.open_intent",
            "cost_class": "state_only", "power_role": "exploratory", "clinical_intent": text,
            "fixture": {"case_family": f"legacy/{cat}", "setup_script": PRO,
                        "initial_state_hash": "sha256:" + "0" * 64},
            "unit": {"kind": "task_scenario", "group_type": "G-EQ", "contrast_family_id": f"legacy/{cat}"},
            "protocol": {"mode": "single_turn", "turns": [{"role": "user", "text": text, "lang": r["lang"]}],
                         "ui_counterpart": None, "budget": {"wall_clock_s": 60, "turns": 1, "tool_calls": 4},
                         "allowed_intermediates": [], "audit_required": False, "n_runs": 3},
            "oracle": {"kind": "judge", "check": "judge_rubric", "constraint_class": "none",
                       "expect": None, "tolerance": None, "assist_only": True,
                       "independent_check": False, "evidence_keys": [], "gold": f"rubric:{cat}"},
            "scoring": {"primary_metric": "rubric_met", "gate_refs": [], "weight": 0.5,
                        "difficulty_target": "medium"},
            "anti_gaming": {"paraphrase_group": f"OPEN-{_san(cat)}-{n:04d}", "hidden": False,
                            "generation_seed": 2026, "canary_class": None,
                            "behavioral_probes": [r["lang"]], "contrast_family_id": f"legacy/{cat}"},
            "provenance": {"source": "legacy_migrated",
                           "derived_from": f"legacy:{r['source']}#{r['legacy_id']}",
                           "guideline_ref": None, "reviewers": ["auto"], "authored_on": "2026-09-30",
                           "deprecated": None},
        }
        json.dump(task, open(os.path.join(args.out_tasks, tid + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        obs = {"sut_id": "BrachyBot-replay", "intent_class": "question", "partial_status": "COMPLETED",
               "oracle_inputs": {"judge_rubric": {
                   "judgments": [{"item_id": tid,
                                  "criteria_scores": {c: 1 for c in crit},
                                  "judge_id": "scripted-judge"}],
                   "rubric": {"criteria": crit, "min_criteria_met": need},
                   "human_reviewed": {tid: True}}},
               "_comment": f"CI replay for {tid} ({cat}); rubric met + human-corroborated."}
        json.dump(obs, open(os.path.join(args.out_replay, tid + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        # negative: judge says pass but human corroboration disagrees
        all_neg[tid] = {
            "judgments": [{"item_id": tid, "criteria_scores": {c: 1 for c in crit},
                           "judge_id": "scripted-judge"}],
            "rubric": {"criteria": crit, "min_criteria_met": need},
            "human_reviewed": {tid: False},
        }
        written += 1

    json.dump(all_neg, open(neg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump({"n": written, "by_category": dict(per_cat)},
              open(os.path.join(args.out_replay, "_open_summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"banked {written} open-ended scenarios as judge_rubric (assist-only)")
    for cat in sorted(per_cat):
        print(f"  {cat:26s} {per_cat[cat]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
