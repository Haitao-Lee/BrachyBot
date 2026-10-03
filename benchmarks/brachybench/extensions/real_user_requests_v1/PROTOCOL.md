# Real User Requests development execution protocol

## Scope and isolation

The 210 scenarios are exploratory development items. `decision_sandbox` uses
synthetic measurements and world state, not patient data, clinical inference or
production DOM. Display mirrors are sandbox observations, not proof that
BrachyBot's Viewer is correct. Component tests never establish formal results.

Formal product comparisons must use the actual chat-input path, as required by
`docs/BENCHMARK_USER_CHAT_EXECUTION_CONTRACT_2026-10-04.md`. The opt-in JSONL
worker described below is **only a component development interface**. It must
not be presented as a substitute for submitting the user's question in the UI.

The evaluator owns fixture installation, gold, event triggers, observation,
artifact storage, collector keys and review. The worker receives user messages
and permitted public observations only. Do not expose entire task or gold.
Use isolated fixtures, runtime and output directories; never clinical accounts
or shared production state. Credentials require explicit `--pass-env` names;
their values must not be logged. Consult `runner.py` for the authoritative
JSONL wire schema, timeouts and process teardown.

## Semantic operations in the synthetic environment

| Operation | Contract |
|---|---|
| `read` | Optional path into current authoritative state; missing is not zero |
| `read_artifact` | `id`, optional offset; bounded actual PNG/PDF data, not private reference masks |
| `capabilities` | Discover supported actions; this does not grant authorization |
| `set` | `path,value,op_id?`; object visibility/opacity/color or independent 2D zoom/pan |
| `submit` | Job kind: dose, quality, guide, report, report_figures, segmentation, trajectory_init, manual_next; segmentation also needs model |
| `poll` | Observe actual pending/completed jobs, Monitor and attachments |
| `advance` | One deterministic environment tick; not clinical computation or unlimited retry |
| `cancel` | Cancel a current owned uncommitted job without deleting its prior artifact |
| `restore` | Version-fenced edit token; restore one edit and create a new geometry revision |
| `cancel_preview` | Cancel an uncommitted preview, not historical edits |
| `capture` | Stable target, optional views/hide/camera/annotation/role; real raster, mask and immutable attachment, with restoration |
| `monitor_stop` | Stop a named owned run; actual server state remains observable after an ACK loss |
| `refresh` | Synchronize display mirrors; no clinical recalculation |
| `export` | Existing current report PDF; explicit delivery is still required |
| `language` | Global zh/en report body and caption localization, distinct from answer language |
| `provider` | Controlled provider-boundary fault; not implicit permission for provider calls |

The environment does not read gold to block mistakes. Rejected unauthorized
attempts remain in the audit. Requested work is not completed work. Dependencies
require completion barriers and matching input revisions, not submission order.
Independent branches may continue after failure; dependent branches must not.
Jobs freeze upstream artifact inputs at submission and store those identities
at completion. Later upstream results cannot retroactively become their inputs.
Multi-turn effects carry evaluator-owned turn scope; they cannot run before that
user turn. State snapshots at response delivery permit independent per-turn
checks, including pending/clarification outcomes and later corrections.
New fault-bearing contracts also require their declared barrier to have fired;
an unexercised recovery path is not recorded as fault coverage.
New setters bind exact values; Boolean and numeric values are not interchangeable.
Alternate legitimate implementations are allowed within scoped effects and
budgets, not a prescribed natural-language keyword or fixed tool name sequence.

## Observation and adjudication

Each recording includes independently collected before/after state, immutable
artifact records, attempted/committed effects, case/session/version fences,
per-turn delivered responses and terminal state. Environment events are genuine
subscription events with explicit barriers, not fabricated user messages.
Prior exchanges are visible fixture history, not forced SUT responses.

`real_user_request` checks actual effects, artifact execution provenance,
geometry/version fences, dependency completion, attachment masks and delivery,
PDF parseability, language persistence and request lifecycle. Known breaches
survive missing semantic evidence. Empty observations and no delivered response
do not pass. A genuine requested no-op (already visible/current) may succeed
only with the corresponding state and an independently reviewed truthful reply.

Response accuracy, usefulness, language and clarity require independent human
review or calibrated judges. Review records include scenario/execution/turn
identity, response hash, evidence spans, reasons, real Boolean decisions and
reviewer identity. `passed=null` means pending, not success. Each user turn must
be accounted for; the final review considers the entire scenario. A synthetic
checker witness must never be used as semantic calibration ground truth.

All items remain `development_only`, `power_role=exploratory` and
`confirmatory_eligible=false`. Shared fixture and contrast lineage must be
clustered. No sealed split or production correctness claim is established.
Actual browser gamma validation requires DOM/SSE, rendered pixels/depth,
attachments/downloads, persistence and state fences collected out of band.

## Offline commands and explicit future collection

From `benchmarks/brachybench`:

```bash
python -m extensions.real_user_requests_v1.build --check
python -m extensions.real_user_requests_v1.prepare --check
python -m extensions.real_user_requests_v1.runner
python -m pytest -q extensions/real_user_requests_v1/
```

These do not execute a SUT. Only explicit future opt-in starts a trusted sandbox
worker, collecting an authenticated recording without an automatic score:

```bash
python -m extensions.real_user_requests_v1.runner --execute \
  --case RUR-02-001 --worker '/absolute/path/to/trusted-adapter' \
  --out /absolute/path/to/new-recording-directory
```

Independent review does not launch a SUT:

```bash
python -m extensions.real_user_requests_v1.review_cli form --case RUR-02-001 \
  --recording /path/recording.json --collector-key /private/path/collector.key \
  --sut-id registered-system --out /path/new-review-form.json
```

After actual independent review, `review_cli evaluate` accepts the recording,
key, `--reviews` and verified `--source-sha256`, using the existing three-state
gate. It does not silently promote development records into main experiments.
Output directories and review/result files refuse overwrite. Existing core
tasks, results, splits and MANIFEST are not rewritten.
