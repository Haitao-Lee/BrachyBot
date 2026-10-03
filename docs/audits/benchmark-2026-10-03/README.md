# Audit evidence: 2026-10-03

Scope: read-only audit of the remote working tree, HEAD 7aa6d23086072b593beba069f8c2116d01c3c0f3. The working tree was dirty; HEAD alone does not identify the evaluated source. source_snapshot_hashes.json.gz identifies the inspected authored snapshot. Large external vendor/data/model assets were outside this snapshot and were not run.

The report is ../../BENCHMARK_INDEPENDENT_AUDIT_2026-10-03.md. All 11,969 task records were read programmatically. Manual analysis covers evaluator mechanisms and representative families, NOT 11,969 independent clinical adjudications. Automated flags are triage, not final item-error labels.

Files:
- per_item_recommendations.jsonl.gz: one record per task, including request, file, checker, flags, actual counterexample verdicts, and recommendations.
- per_item_index.csv.gz: compact UTF-8 BOM CSV index for filtering; 325 state_diff records, 324 with both_noop_verdict=Meets.
- counterexamples_verified.json: successfully executed probes; exploratory failed-call probes removed.
- inventory_deep.json and audit_extra.json: inventory and grouping/split details; candidate contradictions require human adjudication.
- audit_final.json and *_stdout/stderr.txt: final supplementary probes and four native validation command results.
- audit_deep.py / audit_extra.py / audit_finalize.py: read-only derived-audit scripts. They write only into a separately supplied audit output directory. Do not point that output at tasks, gold, source, or historical results.
- source_snapshot_hashes.json.gz and MANIFEST.json: provenance, scope and SHA-256 hashes.

Reproduction in a separate temporary directory with numpy/scipy available:
1. mkdir -p /tmp/brachybench-independent-audit-reproduction
2. python audit_deep.py /home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench /tmp/brachybench-independent-audit-reproduction
3. python audit_extra.py /home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench /tmp/brachybench-independent-audit-reproduction
4. python audit_finalize.py /home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench /tmp/brachybench-independent-audit-reproduction

Inspect each script's positional argument contract before reuse; run against the recorded snapshot or explicitly disclose subsequent drift. No live agent/provider/GPU/browser evaluation was performed. No source, existing benchmark items, existing scores, or services were changed. audit_package.py is the one-time no-overwrite publisher for this report, not a benchmark runner.
