# BrachyBot Benchmarks

> **Execution policy effective 2026-10-04:** every future formal BrachyBot PRV/EXT evaluation submits the task through the real browser user input and Send button. Direct model/`chat_with_trace`/API-only runs are not equivalent. Replay is component self-test only. See `execution_policy.json` and [the user-chat contract](../docs/BENCHMARK_USER_CHAT_EXECUTION_CONTRACT_2026-10-04.md). Historical construction counts below are not product scores.

This directory contains **only the currently valid dual-track evaluation system**. The **single implementation specification** is in
[`docs/BENCHMARK_TOP_LEVEL_DESIGN_2026-09-29.md`](../docs/BENCHMARK_TOP_LEVEL_DESIGN_2026-09-29.md);
the EXT track selection rationale is in
[`docs/BENCHMARK_EXTERNAL_SELECTION_2026-09-29.md`](../docs/BENCHMARK_EXTERNAL_SELECTION_2026-09-29.md).

## Dual-track overview (DESIGN §0.9)

| Track | Directory | Question answered | Scoring source | Experiment flow |
|---|---|---|---|---|
| **EXT** external public benchmarks | [`external/`](external/) | Whether general Agent capability reaches a **comparable level** | **Upstream verifier/rubric** (scoring unchanged) | E0 smoke → E1 panel |
| **PRV** BrachyBench | [`brachybench/`](brachybench/) | Whether it **truly** understands and reliably executes the brachytherapy workflow | **Self-built O1–O5 oracle** | P1–P10 Phase |

> **The two are complementary; neither can replace the other, and they cannot be combined into a single total score** (DESIGN §1.3, four prohibited-merge rules).
> The paper presents **Table X (External Capability Anchors)** and **Table Y (BrachyBench main table)** side by side.

## Contents

```
benchmarks/
├── README.md               ← this file
├── external/               ← EXT track: contains only public benchmarks BrachyBot can participate in (EXT-1..4 + EXT-9..15)
│   ├── manifest.yaml       ← inclusion index + excluded_candidates + E0 conclusions
│   ├── acquisition/        ← acquisition manifest for included benchmarks (commit/revision/sha256/license filled in)
│   ├── excluded/           ← non-included candidates (EXT-5..8) + exclusion rationale (BrachyBot has no FHIR/EHR capability)
│   ├── fetch_all.sh        ← one-shot rebuild of vendor/ + data/ (by pinned commit/revision, reproducible)
│   ├── e0_smoke.py         ← E0 minimal smoke gate (offline, no paid API usage)
│   ├── ext_common.py / adapter_base.py / replay_adapter.py
│   └── EXT-N/{adapter,vendor,data,results}
└── brachybench/            ← PRV track: self-built BrachyBench
    ├── schema/             ← task · cws · run_manifest · acquisition
    ├── oracles/            ← 43 O1 scorer ids + tolerance table + evidence keys + named predicates + expression invariance + _selftest
    ├── fixtures/           ← author fixtures + 150 analytic physics probes + initial-state hashes
    ├── tools/              ← run_task · run_suite · group · coverage · observe · analysis · splits · validate · hash_manifest · gen_physics_fixtures · jsonschema_lite · build_expansion · quality_audit · adapters/ · bcp/ · specs/ (generation sources)
    ├── capabilities/       ← registry.yaml (survey of 99 capabilities) + coverage.json (coverage ledger, DESIGN §32)
    ├── corpus/             ← BCP artifacts: intents/ (1765 de-identified intents) + templates/ (candidate templates)
    ├── tasks/              ← 11819 author tasks (10355 audit-derived/curated + 1464 migrated real intents; including 768 scoring-type) + 150 generated physics probes (6 families, positive/negative polarity, claimed_verdict three-way runnable) = 11969
    ├── migration/          ← legacy intent library archive (DESIGN §20 migration source)
    ├── tests/              ← pytest (24131) + replay/ (CI replay observations + discriminant counter-examples, not benchmark data)
    ├── freeze_checklist.yaml
    └── MANIFEST.sha256
```

## legacy deprecated and deleted (2026-09-30)

The historical versions `benchmarks/v1` (36 classes / 1,149 cases), `benchmarks/v2` (30 classes / 475 cases + smoke 64 + `_legacy` 77)
and their runners (`aligned_benchmark.py`, `run_aligned_agents.sh`, `auto_monitor.py`, `generate_final_report.py`,
`benchmarks/archive/`) have been **deprecated and deleted**. Rationale (DESIGN §20.2):

* All scoring methods were discarded — keyword / length / tool-name heuristics (`_TOOL_MARKERS`, literal containment of `expected_answer`,
  `len(response)` completeness scoring, two coexisting weight sets of 6 and 7 dimensions);
* they would incentivize templated test-taking (DESIGN §2.2 D1/D3/D8/D11).

**Preservation measures:** the clinical **intent library** (containing no scorer) has been recursively archived to
[`brachybench/migration/legacy_intents.jsonl`](brachybench/migration/legacy_intents.jsonl)
(**1,765 entries**, comprising v1 1,149 + v2 475 + smoke 64 + `_legacy` 77), accompanied by
`legacy_intents.meta.json` (with SHA-256 and source details).
The migration mapping table is in **DESIGN §20.1**; this archive must not be deleted before migration is complete.

Deletion is recoverable: `git show HEAD:benchmarks/v2/<file>` (106 tracked files have been `git rm`'d).

## Quick start

### PRV track · scorer self-justification (pre-release, F11/F12)

```bash
cd benchmarks/brachybench
env -u BRACHYBOT_API_KEY python -m pytest tests -q          # 1988 tests
python tools/build_fixtures.py --check                       # no fixture hash drift
```

A scorer must first justify itself: curated corpus **90 faults, 0 missed / 11 legitimate boundary cases, 0 false alarms**;
the external holdout set per DESIGN §23.A uses **TPR ≥ 0.95 / FPR ≤ 0.05**. Falling short ⇒ this evaluation is void, not a footnote.

### PRV track · schema validation

```bash
cd benchmarks/brachybench
python tools/validate.py tasks --root .                       # validate tasks/*.json
python tools/validate.py task --file tasks/D1-SA-007.json
```

### PRV track · checksums and freezing

```bash
cd benchmarks/brachybench
python tools/hash_manifest.py build --root . --exclude results
python tools/hash_manifest.py check --root .                  # CI gate, non-zero means failure
```

### PRV track · run a single task (`run_task.py`, DESIGN §26)

`tools/run_task.py` is the previously missing **execution chain**: task → SUT adapter → observation → O1 scorer
→ three-outcome verdict → `run_manifest.json`. The SUT is pluggable:

```bash
cd benchmarks/brachybench
# 1) replay adapter (deterministic CI / regression; observations in tests/replay/, not benchmark data)
python tools/run_task.py --task tasks/D1-SA-007.json \
    --adapter replay --replay-dir tests/replay --out results/

# 2) real product SUT: configure an isolated browser, fixtures and independent assessors
python tools/run_task.py --task tasks/D1-SA-007.json \
    --adapter browser-user-chat --out results/ \
    --evaluator-config /private/evaluator.json --collector my_eval.evidence:collect \
    --response-checker my_eval.grade:answer --completion-checker my_eval.grade:completion
```

The field contract of the observation dict is in the module docstring; `infra_failed=True` is always mapped to
`INSUFFICIENT_EVIDENCE`, never treated as a model failure.

PRV track E0 smoke (runs all author tasks that have replay observations):

```bash
python tools/run_suite.py --out results/   # returns 0 only if all Meets; missing replays marked SKIPPED-live
```

Expression robustness (DESIGN §31): multiple phrasings of the same intent must yield the **same decision**:

```bash
python tools/group.py --group D1-SA-P03 --replay-dir tests/replay   # consistent=Meets; decision drift on any phrasing=Does not meet
```

Capability full-coverage ledger (DESIGN §32): coverage matrix and gaps across 99 capabilities × 7 dimensions:

```bash
python tools/coverage.py                       # report + gap list (currently 26.9%)
python tools/coverage.py --strict --min 0.80   # CI gate, fails if not met
```

Corpus construction (DESIGN §30, BCP):

```bash
python tools/bcp/harvest.py                    # legacy intents → de-identified intent_record
python tools/bcp/cluster.py --threshold 0.35   # → candidate templates (for expert authoring)
```

Per-question subscores (DESIGN §10.5, scheme in [`../docs/BENCHMARK_SCORING_DESIGN_2026-10-01.md`](../docs/BENCHMARK_SCORING_DESIGN_2026-10-01.md)):
the three-outcome gate is unchanged; each question additionally produces a `[0,1]` subscore (track-dimension template + per-assertion weights); invariant violations score zero,
coverage<0.80 or uncalibrated judges are recorded as N/A, penalties only lower the score and do not change the gate.

```bash
python tools/run_suite.py --tasks-dir tasks --replay-dir tests/replay --out results   # per-track subscore table + results/pilot_report.md
python tools/score_report.py results/            # aggregate per-question subscores from existing run_task outputs
python tools/panel_report.py results/ --markdown pilot_report.md   # panel three-outcome + scenario-level cluster-bootstrap CI + safety UCB
```

Judge calibration is registered in `calibrations.json` (O3/O4/O5 subscores are recorded as N/A until they pass calibration, see §8.5).

### EXT track · rebuild + E0 smoke (landed 2026-10-01)

```bash
bash benchmarks/external/fetch_all.sh          # vendor/ + data/ (pinned commit/revision)
python benchmarks/external/e0_smoke.py         # E0 skeleton (offline, no paid API needed)
cd benchmarks/brachybench
for f in ../external/acquisition/EXT-*.yaml; do
  python tools/validate.py acquisition --file "$f"   # 8/8 OK, no placeholders
done
```

**Inclusion criteria**: include only public benchmarks that BrachyBot can participate in as a SUT and that are suitable for evaluating it.
BrachyBot has no FHIR/EHR/HL7/terminal capability (source grep = 0), so MedAgentBench / MedCTA /
PhysicianBench / HealthAgentBench are excluded (see `external/excluded/`).

E0 conclusions (see [`external/README.md`](external/README.md) and `external/results/e0_summary.json` for details):

| # | Benchmark | E0 | Notes |
|---|---|---|---|
| EXT-1 ABRA | BLOCKED | 353 tasks generated offline (easy 249+hard 104) + upstream scorer runs; §25.6 Viewer/Docker outcome not run |
| EXT-2 HealthBench | PASS | full set of 4 jsonl (including meta_eval); upstream `calculate_score` runs |
| EXT-3 MedSafety-Brachy | BLOCKED | official evaluator requires OpenAI; clinical adaptation requires reviewer (authoring package delivered) |
| EXT-4 MedMemoryBench | PASS | full set zh+en (3878 query/40 persona); upstream `string_contain` runs |
| EXT-9 LongMemEval | BLOCKED | 500 memory questions; QA scoring requires LLM judge |
| EXT-10 MedHallu | PASS | 20000 hallucination detection tasks; deterministic accuracy |
| EXT-11 MedCalc-Bench | PASS | 1100 clinical calculations; upstream `check_correctness` runs |
| EXT-12 AgentClinic | BLOCKED | 321 consultation scenarios; diagnostic scoring requires LLM moderator |
| EXT-13 AMEGA | PASS | 162 guideline-adherence questions; upstream weighted aggregation runs |
| EXT-14 MedPhysBench | PASS | 97 medical physics tasks (including **brachytherapy**/TG-263/safety escalation); upstream deterministic scoring runs |
| EXT-15 MedicalAgentsBench | PASS | 9274 medical reasoning MCQs; deterministic accuracy runs |

4 repositories are vendored to pinned commits; public data is fetched and pinned by sha256; 4 adapters
implement the §25.5 contract (`score()` calls only the upstream evaluator, never recomputes).

### EXT track · adapter contract

`external/adapter_base.py` defines the `ExtAdapter` contract and unified record (§25.5);
`external/replay_adapter.py` is the contract reference implementation: `score()` **returns the upstream verdict as-is**,
and `audit_isolation()` voids the current run if any `forbidden_write_roots` is hit (§25.8).
Each real benchmark's adapter lives at `external/<ext_id>/adapter/adapter.py` and performs only protocol conversion.


## Pre-freeze checklist (32 items)

See [`brachybench/freeze_checklist.yaml`](brachybench/freeze_checklist.yaml).

* **All 32 pass** ⇒ confirmatory run may start (EXT's E1 formal + PRV sealed formal set)
* **Any fail** ⇒ only Dev/Pilot/E0 may run, and the report must be labeled
  `PROTOCOL NOT FROZEN — confirmatory claims withheld`
* **8 hard prerequisites**: `F05 F06 F11 F12 F17 F21 F28 F31`

## Hard isolation (DESIGN §25.8)

| Rule | Content |
|---|---|
| EXT result directory **must not write to** | `BrachyBot/{session,case,runtime,report}/` |
| PRV result directory **must not write to** | `benchmarks/external/*/results/` |
| Upstream code | `benchmarks/external/*/vendor/` is **read-only**; adapters only perform protocol conversion |
| License | `vendor/` retains `LICENSE.UPSTREAM`, not merged into the main repo's Apache-2.0 notice |

## Build audit (five rounds, 2026-09-30 → 2026-10-01)

The deliverables in this directory have undergone independent review (adversarial probes, not just running the bundled tests).

| Round | Result |
|---|---|
| Round 1 (audit) | 51 tests / schema / freeze OK, but adversarial probes found **BA-1 empty pass when audit is missing, BA-2 three-outcome gate not implemented** (P0), BA-3..6/15/16 (P1), BA-7..14/17..22 (P2) |
| Round 2 (fix) | **all 22 items addressed**; curated fault corpus **90 entries, 0 missed** (including 50 subtle), legitimate boundaries **11 entries, 0 false alarms** |
| Round 3 (review, this round) | Fixed **BA-4 residue** (unverifiable seed list still counted as violation ⇒ should be evidence gap), `OracleResult.merge` no longer upgrades constraint classes, malformed `allowed_intermediates` entries no longer silently become globs, `needle_interference` physics task was mislabeled D1, generator losing `oracle.config.mechanism` caused N7 split degradation, `splits.py` missing `import sys`, `jsonschema_lite`'s `oneOf`/`$ref` semantics; **added execution chain `tools/run_task.py` + real SUT adapter contract + EXT reference adapter + 11 author tasks**; **3506 tests** all green |
| Round 4 (quality audit, evening of 2026-09-30) | Fixed four P0s: **① observation-layer degradation** (770 tasks previously shared 43 fixed oracle_inputs → per-task parameterization + generation-time self-justifying crisp-pair gate, now 669 kinds of observations); **② prompt↔oracle semantic misalignment** (expand rewritten: category→scorer→adapter extraction contract documented); **③ 21 empty-prompt tasks** (empty-text filtering, now 0); **④ `obeyed/executed` self-reported booleans** (injection switched to `actions_after` independent action stream). Fixed P1s: physics-track dispatch aliases (5 families of check names ↔ registered ids) + `oracle_verdict_match` three-way scoring + `expect` consumption; dose_additivity/dose_quantisation fault-injection variants (both families went from all-pass → 12/13 and 18/7 positive/negative); 33 handwritten task negatives completed + **100% negative coverage became a test gate**; scorer fixes (`param_binding` accepts %/Gy(RBE) and validates units by metric-scope, missing `exec/path` policy = evidence gap, `session_isolation` criteria rewritten, `dice _hd95` rank mismatch no longer crashes, missing evidence changed from crash to evidence gap). **1988 tests** all green; E0 903/903; splits 903 tasks / 78 connected components with no leakage |

| Round 5 (EXT track build + expansion, 2026-10-01) | 8 public benchmark repositories vendored to pinned commits; public data fetched and pinned by sha256; the "BrachyBot can participate" inclusion criterion converged to **9** (EXT-1..4 + EXT-9..13), 4 FHIR/EHR candidates excluded into `external/excluded/`; 9 adapters implement the §25.5 contract; acquisition 9/9 pass schema validation, no placeholders; E0: EXT-2/4/10/11/13 PASS, EXT-1/3/9/12 BLOCKED (external dependencies). See `external/README.md` |

* The full list, reproduction method, and item-by-item disposition are in **DESIGN §29 Build Audit** (§29.2 problems / §29.4 disposition / §29.5 Round 3); EXT convergence is in DESIGN §25.2.5 and appendix Z of `docs/BENCHMARK_EXTERNAL_SELECTION_2026-09-29.md`.
* **Scorer self-justification (F11/F12) is viable**: curated corpus uses the 1.0/0.0 hard standard (the 0.95/0.05 floors are reserved for the external holdout set).
* **Execution chain is in place (`run_task.py`)**; the EXT track's 9 adapters are wired in (`external/EXT-*/adapter/`); the **real SUT (BrachyBot) adapter** is pending (F17/E0-live).
* **F28 (E0 smoke)**: 9 included items, the 5 offline-decidable ones PASS; the other 4 are external dependencies (judge / Docker-Viewer / clinical reviewer) and are truthfully BLOCKED; `external/results/e0_summary.json` is the evidence.

## Disclaimer

This benchmark is a **research-and-development quality tool** and does not constitute medical advice, clinical validation, or registration evidence.
Real cases are not distributed with the package; the public portion is mainly analytic phantoms and synthetic data (DESIGN §14).
