# BrachyBot · Public Benchmark Collection

> **2026-10-04 update:** All future formal BrachyBot evaluations must submit each task through the real browser chat input and activate the Send button. Arbitrary model callbacks are rejected by default; E0 and regression runs must explicitly declare `component_self_test`. See the [unified execution contract](../../docs/BENCHMARK_USER_CHAT_EXECUTION_CONTRACT_2026-10-04.md) and `public_collection/user_chat_eligibility.json`. The common-harness categories below describe source assets and protocols; they do not authorize bypassing the product entry point.

This directory provides public capability anchors. It does not replace the native brachytherapy, Viewer, Monitor, or artifact-state evaluations in `../brachybench/`. **Successful data acquisition, passing offline scorer tests, an executable original protocol, and measured model results are four different things.** Do not combine them into a single cross-benchmark score.

The collection/review baseline is 2026-10-03, with work completed on 2026-10-04. The 11 legacy adapters remain in place. The new collection is in [`public_collection/`](public_collection/README.md) and adds 12 items, EXT-16 through EXT-27. See the [review report](../../docs/BENCHMARK_PUBLIC_COLLECTION_AUDIT_2026-10-03.md) for selection criteria, original-protocol limitations, and issues with earlier entries. **This work made zero SUT, model, or judge calls.**

## Two directory layers, two distinct experimental identities

| Layer | Entry point | Meaning |
|---|---|---|
| Existing adapters | `manifest.yaml`, `acquisition/*.yaml`, `EXT-N/adapter/` | Historical construction status; `active` or E0 PASS does not certify eligibility for public comparison |
| New public collection | `public_collection/catalog.json`, `assets.lock.json`, `pool.py` | Pinned upstream versions, test data, separation of private references from public inputs, and original scorer/renderer interfaces |
| Selection and reuse rules | `public_collection/selection.json` | Purpose, conditions, exclusions, and overlap rationale for each item; only meaningful directions are retained |

The new collection can provide common-harness inputs for evaluating models or decision components used by BrachyBot, but does not automatically give the product capabilities in external tools, EHRs, pathology systems, or hospital systems. Report results for **native BrachyBot**, **models/agents using the same mock-tool harness**, and **original public leaderboards** separately.

## Repositioning the 11 existing entries

| ID | Benchmark | Position after this review |
|---|---|---|
| EXT-1 | ABRA | Imaging-software interaction methodology / conditional experiment; 353 of 655 generated tasks. Do not claim execution in the original OHIF/Orthanc environment. |
| EXT-2 | HealthBench | Auxiliary anchor for medical communication, grounding, and honesty; requires a genuinely independent rubric judge. Hard/consensus variants are not new independent task sets. |
| EXT-3 | MedSafetyBench-BrachyAdapted | Report original safety data separately from Brachy-adapted tasks. Adaptations require expert sign-off and must not be reported as original benchmark scores. |
| EXT-4 | MedMemoryBench | Auxiliary medical-dialogue memory anchor; fix zh/en, persona, and session-duration settings. Never use reference answers to generate SUT outputs. |
| EXT-9 | LongMemEval | Report oracle, `s`, and `m` tracks separately. Oracle-mode results do not establish long-history capability; an independent judge remains a dependency. |
| EXT-10 | MedHallu | Auxiliary medical hallucination-detection anchor; the upstream parser has empty-answer/abstention parsing issues. Preserve raw responses and disclose the protocol version. |
| EXT-11 | MedCalc-Bench | Auxiliary clinical-calculation anchor; it is not validation of the brachytherapy source-dose engine. |
| EXT-12 | AgentClinic | **Quarantined: the legacy single-turn adapter must not produce AgentClinic scores.** The original patient/test multi-turn environment is missing; status is explicitly BLOCKED. |
| EXT-13 | AMEGA | Auxiliary guideline-adherence anchor; a weighted sum does not mean criteria were independently assessed. Requires a judge or human review. |
| EXT-14 | MedPhysBench | One of the closest public anchors for medical physics; 97 questions. It does not establish clinical approval of a plan produced by this product. |
| EXT-15 | MedicalAgentsBench | The current nine complete source sets are not the original ten-slice `test_hard` protocol. Treat them only as an explicitly labeled auxiliary baseline; verify licenses and overlap for every underlying dataset. |

This round also fixed reference-answer exposure at the existing adapters' direct `build_input` and invocation boundaries, including EXT-15's `reference_letter` and `reference_content`. The implementation uses an explicit per-item public-field contract. It preserves legitimate clinical content and candidate answers that the model is supposed to assess; it does not recursively remove every field or text fragment named `answer` or `expected`.

## Reproduction commands without model calls

Use a dedicated benchmark Python environment from `benchmarks/external/`:

```bash
python -m public_collection.collect fetch
python -m public_collection.collect verify
python -m public_collection.pool inventory
python -m pytest public_collection/tests -q
python -m public_collection.pool export --id EXT-20 --out /tmp/medec-public-new
```

These commands respectively fetch sources by reviewed SHA256, verify integrity, inventory the task pool, run construction/contract/scorer positive and negative controls, and export public inputs. None calls a model.

`fetch_all.sh --public-collection` fetches only the new collection according to its lock and does not touch existing vendor data. **Do not run the legacy `fetch_all.sh` without arguments just to reuse the new task set:** the legacy script rebuilds old vendor/data directories and contains historical sections that do not pin Hugging Face `main`. The new lock records canonical and actual download URLs, byte counts, and SHA256 hashes. Public mirrors do not bypass authentication or data-use agreements.

Mount only the exported public bundle for the SUT. Do not expose the full repository or assets directory containing gold labels, qrels, or scorers to a terminal agent. `--bootstrap-lock` is only for an explicitly reviewed upstream update; the lock has already been generated for this collection, so routine reproduction does not need it.

This work did not modify clinical reasoning, planning, Viewer, or Monitor code; restart a service; create a patient experiment; or call a paid judge. The historical `results/e0_summary.json` remains a component record and is not reclassified as a model result from this round.
