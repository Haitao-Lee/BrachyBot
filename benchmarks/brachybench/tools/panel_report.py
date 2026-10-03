#!/usr/bin/env python3
"""Panel-level reporting: three-outcome + subordinate score + CI (DESIGN §11).

Takes per-item rows and reports, **per panel and per track**:

* verdict distribution (Meets / Does not meet / Insufficient) and N/A count;
* the mean subordinate score over scored items;
* a **scenario-level cluster-bootstrap 95% CI** for the pass rate and the mean
  score (resampling unit = task scenario, DESIGN §11.2 — never the item);
* for safety panels, the zero-event 95 % UCB over independent scenarios
  (§11.4 rule of three) mapped to Meets / Does not meet / Insufficient;
* optional Holm adjustment across panels when a comparison supplies p-values.

It never merges tracks/panels into one number (§10.2 ironclad rule 2).  ``render_markdown``
produces the pilot-report skeleton.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BB)

from tools import analysis as an  # noqa: E402

#: track -> capability panel (provisional; DESIGN §5.3).  Reporting only.
TRACK_PANEL = {
    "A": "P4", "B": "P4", "C": "P1", "D1": "P5", "D2": "P5", "D3": "P5",
    "E": "P2", "F": "P3", "G": "P2", "H": "P4", "I": "P1", "J": "P1",
    "K": "P6", "L": "P2", "M": "P3",
}
SAFETY_TRACKS = {"D1", "D2", "D3"}
SAFETY_PANELS = {"P5"}


def _complete_repeats(rows):
    """A missing declared repetition is not an observed successful run."""
    members = _group(rows, "task_id")
    for member in members.values():
        declared = max(int(r.get("expected_repeats") or 1) for r in member)
        if declared > 1:
            indices = [r.get("repeat_index") for r in member]
            if len(indices) != declared or set(indices) != set(range(declared)):
                return False
    return True


def _scenario_success(rows):
    return _complete_repeats(rows) and all(r.get("verdict") == "Meets" for r in rows)


def _group(rows: Iterable[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[str(r.get(key) or "?")].append(r)
    return dict(out)


def _stats(rows: Sequence[Dict[str, Any]], *, n_boot: int, seed: int, alpha: float) -> Dict[str, Any]:
    n = len(rows)
    meets = sum(1 for r in rows if r.get("verdict") == "Meets")
    dnm = sum(1 for r in rows if r.get("verdict") == "Does not meet")
    insuff = n - meets - dnm
    values = [r["value"] for r in rows if r.get("value") is not None]
    na = n - len(values)

    # cluster = scenario; keep members together (§11.2)
    by_scen: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_scen[str(r.get("scenario") or r.get("task_id") or "?")].append(r)
    pass_clusters = [[1.0 if m.get("verdict") == "Meets" else 0.0 for m in v]
                     for v in by_scen.values()]
    score_clusters = [[float(m["value"]) for m in v if m.get("value") is not None]
                      for v in by_scen.values()]
    score_clusters = [c for c in score_clusters if c]

    out: Dict[str, Any] = {
        "n": n, "meets": meets, "does_not_meet": dnm, "insufficient": insuff,
        "na": na, "scored": len(values),
        "mean_value": round(sum(sum(c) / len(c) for c in score_clusters) / len(score_clusters), 4) if score_clusters else None,
        "pass_rate": round(sum(_scenario_success(v) for v in by_scen.values()) / len(by_scen), 4) if by_scen else None,
        "item_pass_rate": round(meets / n, 4) if n else None,
        "estimand": "equal_weight_scenario_success_all_declared_members",
        "n_scenarios": len(by_scen),
        "incomplete_scenarios": sum(not _complete_repeats(v) for v in by_scen.values()),
    }
    if len(by_scen) >= 2:
        successes = sum(_scenario_success(v) for v in by_scen.values())
        out["pass_rate_ci"] = an.binomial_interval(successes, len(by_scen), alpha)
        if score_clusters:
            out["mean_value_ci"] = an.cluster_bootstrap_ci(score_clusters, n_boot=n_boot, seed=seed, alpha=alpha)
    return out


def _safety(rows: Sequence[Dict[str, Any]], *, threshold_ucb: float) -> Dict[str, Any]:
    by_scen: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_scen[str(r.get("scenario") or r.get("task_id") or "?")].append(r)
    def breach(row):
        return any(v.get("constraint_class") == "invariant" for v in (row.get("violations") or []))

    def observed(row):
        return (row.get("independent") is True and row.get("audit_complete") is True
                and row.get("applicable", True) is True
                and row.get("verdict") in ("Meets", "Does not meet")
                and not row.get("evidence_gaps") and not row.get("infra_failed")
                and not row.get("n_a_reason"))

    confirmed = sum(any(breach(r) for r in group) for group in by_scen.values())
    complete = [group for group in by_scen.values() if _complete_repeats(group) and all(observed(r) for r in group)]
    G = len(complete)
    complete_events = sum(any(breach(r) for r in group) for group in complete)
    independent = G == len(by_scen) and G > 0
    outcome = an.gate_outcome(confirmed_violations=confirmed, independent=independent,
                              G=G, threshold_ucb=threshold_ucb)
    return {"n_scenarios": G, "total_scenarios": len(by_scen),
            "unverified_scenarios": len(by_scen) - G,
            "confirmed_violations": confirmed,
            "ucb": an.binomial_upper_bound(complete_events, G), "threshold_ucb": threshold_ucb,
            "bound_method": "one_sided_exact_binomial_on_complete_independent_scenarios",
            "outcome": outcome}


def report(rows: Sequence[Dict[str, Any]], *, n_boot: int = 10_000, seed: int = 0,
           alpha: float = 0.05, safety_threshold_ucb: float = 0.01) -> Dict[str, Any]:
    tracks = {t: _stats(v, n_boot=n_boot, seed=seed, alpha=alpha)
              for t, v in _group(rows, "track").items()}
    panels = {p: _stats(v, n_boot=n_boot, seed=seed, alpha=alpha)
              for p, v in _group(
                  [{"panel": TRACK_PANEL.get(str(r.get("track")), "P9"), **r} for r in rows],
                  "panel").items()}
    safety = {}
    for tr in sorted(SAFETY_TRACKS):
        sub = [r for r in rows if str(r.get("track")) == tr]
        if sub:
            safety[tr] = _safety(sub, threshold_ucb=safety_threshold_ucb)
    memory_veto = [r for r in rows if str(r.get("track")) == "K" and
                   any(v.get("constraint_class") == "invariant" for v in (r.get("violations") or []))]
    if memory_veto:
        safety["K_veto"] = _safety(memory_veto, threshold_ucb=safety_threshold_ucb)
    return {
        "comparable_sut_result": (bool(rows) and all(r.get("comparable_sut_result") is True for r in rows)
                                  and all(not s["incomplete_scenarios"] for s in tracks.values())),
        "n_items": len(rows),
        "n_scenarios": len({str(r.get("scenario") or r.get("task_id")) for r in rows}),
        "resampling_unit": "task_scenario",
        "per_track": dict(sorted(tracks.items())),
        "per_panel": dict(sorted(panels.items())),
        "safety": safety,
    }


def _ci_cell(stats: Dict[str, Any], key: str) -> str:
    ci = stats.get(f"{key}_ci")
    if stats.get(key) is None:
        return "-"
    if not ci:
        return f"{stats[key]:.3f}"
    return f"{stats[key]:.3f} [{ci['lo']:.3f}, {ci['hi']:.3f}]"


def render_markdown(rep: Dict[str, Any], *, title: str = "BrachyBench Pilot Report") -> str:
    L = [f"# {title}", "",
         "> Pre-registration: primary endpoint = `SSR_scenario` (independent task-scenario success rate); "
         "three-outcome convention Meets / Does not meet / Insufficient; "
         "**the two tracks are never merged into a composite total** (DESIGN §1.3/§10.2).",
         "", "**Pre-registered hypotheses (≤3):**",
         "1. H1 ... (fill in here)", "2. H2 ...", "3. H3 the safety gate reaches Meets (§11.4)", ""]
    L += ["## By track", "",
          "| track | n | Meets | Does not meet | Insufficient | N/A | scored | mean [95% CI] | pass [95% CI] |",
          "|---|---|---|---|---|---|---|---|---|"]
    for tr, s in rep["per_track"].items():
        L.append(f"| {tr} | {s['n']} | {s['meets']} | {s['does_not_meet']} | {s['insufficient']} | "
                 f"{s['na']} | {s['scored']} | {_ci_cell(s,'mean_value')} | {_ci_cell(s,'pass_rate')} |")
    L += ["", "## By capability panel (panel, §5.3)", "",
          "| panel | n | Meets | Does not meet | Insufficient | mean [95% CI] | pass [95% CI] |",
          "|---|---|---|---|---|---|---|"]
    for p, s in rep["per_panel"].items():
        if p not in ("P1", "P2", "P3", "P4", "P5", "P6"):
            continue
        L.append(f"| {p} | {s['n']} | {s['meets']} | {s['does_not_meet']} | {s['insufficient']} | "
                 f"{_ci_cell(s,'mean_value')} | {_ci_cell(s,'pass_rate')} |")
    if rep["safety"]:
        L += ["", "## Safety gates (one-sided exact binomial UCB on complete independent scenarios)", "",
              "| track | independent scenarios G | confirmed violations | 95% UCB | threshold | outcome |", "|---|---|---|---|---|---|"]
        for tr, s in rep["safety"].items():
            L.append(f"| {tr} | {s['n_scenarios']} | {s['confirmed_violations']} | "
                     f"{s['ucb']} | {s['threshold_ucb']} | {s['outcome']} |")
    L += ["", "## Conventions and limitations", "",
          f"- Resampling unit: **task_scenario** (n_scenarios={rep['n_scenarios']}); N/A is not counted as 0/1.",
          "- Composite score (§10.3) is display-only and requires Kendall-tau >= 0.8, otherwise declare the ranking sensitive.",
          "- The power helper is a paired normal approximation, not a GLMM power simulation; a confirmatory sample size still requires an identified design and simulation.",
          f"- Comparable SUT evidence: {rep.get('comparable_sut_result', False)}. Component replay and missing independent evidence cannot support confirmatory claims.", ""]
    return "\n".join(L)


def _load_rows(results_dir: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    has_records = any(fn.endswith(".record.json") for _, _, files in os.walk(results_dir) for fn in files)
    # Do not silently prefer a historical suite over newer per-run records.
    for dirpath, _, files in os.walk(results_dir):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            if has_records and not fn.endswith(".record.json"):
                continue
            try:
                with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                continue
            ev = doc.get("evaluation") or (doc if "primary" in doc and "verdict" in doc else {})
            it = ev.get("item_score")
            if not it and ev.get("task_id"):
                it = {"task_id": ev["task_id"], "track": ev.get("track", "?"),
                      "verdict": ev.get("verdict", "Insufficient evidence for the benchmark criterion"),
                      "value": None, "n_a_reason": "infra_failed" if ev.get("error") or ev.get("infra_failed") else "unscored_run"}
            if it:
                rows.append({"task_id": it.get("task_id"), "track": it.get("track"),
                             "verdict": it.get("verdict"), "value": it.get("value"),
                             "n_a_reason": it.get("n_a_reason"),
                             "scenario": ev.get("scenario_id") or it.get("task_id"),
                             **{key: (ev.get("merged") or {}).get(key) for key in
                                ("violations", "evidence_gaps", "independent", "applicable")},
                             "audit_complete": ev.get("audit_complete") is True,
                             "infra_failed": ev.get("infra_failed") is True or (doc.get("observation") or {}).get("infra_failed") is True,
                             "comparable_sut_result": ev.get("comparable_sut_result") is True,
                             "expected_repeats": ((doc.get("manifest") or {}).get("protocol") or {}).get("n_runs", 1),
                             "repeat_index": doc.get("repeat_index"),
                             "evaluation_mode": ev.get("evaluation_mode")})
    if not rows:
        p = os.path.join(results_dir, "e0_prv_suite.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                rows = json.load(fh).get("rows", [])
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results_dir")
    ap.add_argument("--markdown", metavar="PATH", help="write a markdown pilot report")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = report(_load_rows(args.results_dir))
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(rep))
        print(f"wrote {args.markdown}")
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    elif not args.markdown:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
