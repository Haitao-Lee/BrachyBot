# Version-locked public capability collection

> **2026-10-04 execution requirement:** every future formal BrachyBot test must submit the current task through the actual browser chat input and Send button. This collection is still data/protocol construction, not a runner or a score. The common-harness descriptions below identify original protocol assets only, not permission to bypass the product. See `user_chat_eligibility.json`, `../../execution_policy.json` and [the contract](../../../docs/BENCHMARK_USER_CHAT_EXECUTION_CONTRACT_2026-10-04.md). Foreign-tool/RAG/attachment protocols are BLOCKED until integrated; adaptations need a distinct name.

This folder contains **12 new collections**, EXT-16 through EXT-27, beside the 11 legacy adapters. It is a reproducible data/protocol construction, **not a set of BrachyBot scores**. Source audit: 2026-10-03; completion: 2026-10-04.

## Inventory and meaningful use

| ID | Collection | Eligible units in pinned assets | Experimental role |
|---|---|---:|---|
| 16 | When2Call | 3,652 MCQ + 300 judge views; 1,295 source clusters | Call vs clarify vs answer vs acknowledge unavailable tools |
| 17 | BFCL v3 static AST/irrelevance | 3,472; one orphan blocked | Structured tool/argument selection; multiple/parallel calls |
| 18 | MedXpertQA | 2,450 Text + 2,000 MM; 2,852 test image files | Hard medical reasoning and auxiliary image interpretation |
| 19 | CMB-Clin | 74 case clusters / 208 ordered turns | Chinese clinical follow-ups and grounded communication |
| 20 | MEDEC-MS | 597 MS test texts | Clinical error identification, location and correction |
| 21 | MedHALT | 41,816 test views / 15,991 source clusters | False confidence, NOTA and fabricated/reference mapping |
| 22 | MedRGB | 3,680 source questions, five subsets | **Data ready; native context/judge protocol blocked** |
| 23 | R2MED clinical retrieval | 511 queries in four subsets | Treatment/clinical evidence retrieval with task-owned qrels |
| 24 | NFCorpus / BEIR | 323 test queries / 3,633 documents | Reproducible medical search with graded relevance |
| 25 | SciFact / BEIR | 300 test queries / 5,183 documents | Scientific evidence **retrieval only**, not entailment |
| 26 | LongHealth task1 base | 400 questions / 20 case clusters | Long clinical context, temporal facts, distractors |
| 27 | InjecAgent | 1,054 base scenarios + enhanced repeated views | Untrusted tool-return injection; first-stage typed scenes |

These are **not independent samples to be summed**. View/case/source clustering and overlap edges are recorded in `selection.json`. Knowledge/diagnosis questions are auxiliary anchors, not proof of brachy planning skill or clinical approval.

## Interfaces and boundaries

`PublicPool(id).list_tasks()` / `.build_input(task_id)` separate the model-facing public schema from private task-owned labels. CMB default input is the first user turn only; the future schedule remains in the evaluator. `cmb_messages()` appends actual prior model outputs, never reference answers or future turns. `image_bytes()` materializes actual test images. Fixed-corpus retrieval uses public query/corpus inputs; private qrels never enter the bundle. InjecAgent preserves `user → assistant tool call → tool` roles and never exposes attacker goal labels or executes foreign tools.

Audited original source hooks: `when2call_prompt()`, `longhealth_prompt()`, `score_bfcl()`, `score_medxpert()`, `score_retrieval()`. BFCL accepts **canonical parsed calls**, not prose. BEIR validates complete query coverage and finite scores. Before explicit source imports, vendored Python source hashes are checked. Native output parsing/prompts, graders, budgets and model access still require per-experiment certification; the hooks are not an automatic leaderboard runner.

**Protocol limits are deliberate:** no fabricated MedRGB context; no MEDEC UW DUA bypass; no MedHALT train-only fake questions presented as tests; no CMB-Exam score masquerading as CMB-Clin; no SciFact claim-label score from retrieval data; no first-stage InjecAgent result masquerading as full two-stage ASR; no LongHealth task2/3 claimed without its original composition.

The native MedXpert parser matches the capital English pronoun `I` as choice I in some abstentions; a regression reproduces this upstream limitation. Preserve native scores for comparability and record raw/strict abstention separately in future experiments rather than silently changing the metric.

## Rebuild, validate and export — zero model calls

From `benchmarks/external`, in a dedicated environment:

```bash
python -m pip install -r public_collection/requirements-validation.txt
python -m public_collection.collect fetch
python -m public_collection.collect verify
python -m public_collection.pool inventory
python -m pytest public_collection/tests -q
python -m public_collection.pool export --id EXT-20 --out /tmp/medec-public-new
```

Assets are ignored in Git. Checked-in catalog/lock/selection inventory is small; acquisition downloads public pinned sources and safely extracts only declared members. `--hf-host hf-mirror.com` is an explicit public mirror option; canonical and actual URLs remain in the lock. No authentication gates are bypassed. Only a reviewed upstream upgrade should use `--bootstrap-lock`; a hash mismatch is never silently accepted.

Export a **new** public bundle, not the raw assets folder. The model/terminal sandbox must mount only that bundle; the evaluator privately retains references. Public images and corpus records are included when required. MedRGB export fails closed until native context composition is known.

`construction_validation.json` is an inventory/provenance/contract check with `sut_runs: 0`. It contains no model ranking. The latest construction tests are 48 passed; the benchmark-wide regression was 24,256 passed / 2 skipped (missing pypdf). Last CMB scheduling changes were rechecked in the 48 targeted tests. Fifteen large assets also match official HF revision LFS SHA256 metadata (`official_hf_checksum_crosscheck.json`). Do not mistake positive-control scorer tests for agent task success.

## Fair comparison contract

Pre-register benchmark revision, subset, original/adapted protocol name, model and tokenizer version, context and image budget, tool access/mocks, prompt, output parser, judge version and rubric, repetitions, time/cost limits, clustering and overlap exclusions. All systems receive the same public inputs and public corpus under the same resource policy. Native BrachyBot tests, shared-harness models/agents and native public leaderboard results must be separate tables.

Do not train on test assets. Honor source notices; LongHealth asks that examples not be republished in public prose. Licenses for assets and source code are tracked independently in `catalog.json`; copied corpus licenses do not automatically confer rights to every cited source.
