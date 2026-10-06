# Accuracy-first semantic decision latency optimization

Date: 2026-10-06  
Scope: the LAN BrachyBot source checkout at `/home/lht/snap/brachyplan/BrachyBot`  
Baseline HEAD: `476474f400a700f71121c3e63e4380e4dc03bbf6`

## 1. Outcome and limits

This change removes unnecessary resource waits from the normal streamed chat
path and supplies bounded, saved active-plan facts to the first semantic model
round. It does not add a mandatory intent-classification model call, convert
keywords into clinical authority, or trade missing evidence for a faster answer.

The priority is correctness, followed by interaction efficiency. A request that
needs decoded images, geometry, or a mutation must still cross the full-resource
barrier. A request that can be answered from saved metadata need not wait for
unrelated CT/dose sidecars to finish decoding. Mixed requests resolve dependencies
per selected operation rather than being routed by the presence of words such
as "dose", "report", "CTV", or "guide".

This is an implementation and contract-test result, not a live-provider speed or
clinical-accuracy result. No patient planning, paid model benchmark, server
restart, public-release change, commit, or push is part of this delivery. The
already-running Python server must load the updated source before the behavior
can be assessed in the real UI. Repository test durations below are not chat
response durations.

## 2. Root causes addressed

### 2.1 Language-based hydration imposed the wrong dependency

The streamed chat supplier used `_chat_requires_full_workspace`, including
`_FULL_WORKSPACE_CHAT_TERMS` and `_FULL_WORKSPACE_CHAT_INTENTS`, to decide whether
to delay a turn until the complete workspace was restored. A question containing
a domain word could therefore wait for heavy arrays even when it only needed
saved dose metrics, report text/attachments, or guide status. Conversely, matching
language is not a reliable substitute for knowing an operation's input contract.

That gate is removed. The supplier publishes the lightweight case Agent promptly;
the selected tool operation owns the resource requirement.

### 2.2 Moving only the tool gate would leave a correctness bug

The model loops inspect clinical prerequisites before executing a tool. A cold
metadata Agent has undecoded arrays, which must not be interpreted as evidence
that a saved segmentation or plan does not exist. Waiting only inside the final
tool executor could allow prerequisite normalization to propose replacement
segmentation before the existing data had loaded.

Both provider loops now prepare the resources for admitted tool proposals before
clinical prerequisite inspection. Verified direct workflows also cross their
resource barrier before inspecting prerequisites. Final execution has guards
before memory injection and at the registry boundary. These checks do not replace
the existing schema, palette, path-security, authorization, or receipt checks.

### 2.3 An extra metric round was often structurally unnecessary

The primary semantic model could lack small saved facts even though they were
already in the current case memory. It then needed to request identical metrics
and make another provider round just to repeat those values. A bounded active-run
evidence packet makes relevant saved facts available on the first round, without
a separate intent model or natural-language special-case answer.

### 2.4 Background restore could overwrite a live interaction

The array-hydration publish path could restore an older snapshot of conversation,
tool results, summary, locale, UI state, config, and run ledger while a new turn
or UI change was taking place. Starting chat before the arrays were ready would
expose this race more often.

Background publication now preserves the already-installed live control plane.
The initial restoration of a new Agent still restores those durable fields;
subsequent array decoding publishes clinical results and their existing repairs
without resetting the ongoing interaction.

## 3. Design

### 3.1 Operation-level resource contract

`agent_runtime/workspace_readiness.py` defines a shared resource contract. It does
not interpret user text, authorize a write, or start a second hydration job.

| Actual operation | Full decoded workspace required? | Reason |
| --- | --- | --- |
| `query_metrics`: saved dose/OAR tables, score, counts, planning method, spacing metadata | No | Uses saved case state rather than recomputation |
| `query_metrics`: HU, CTV/OAR volumes, per-needle distributions, all metrics | Yes | May inspect arrays or detailed geometry |
| `surgical_guide(action="status")` | No | Reads saved status |
| Guide analyze/generate, dose recompute, planning, segmentation, mutations | Yes | Requires complete clinical inputs or changes case/UI state |
| Explicit `case_memory` / `clinical_kb` reads | No | Action-sensitive read contract |
| `case_memory(save)` / `clinical_kb(add)` / missing mixed-effect action | Yes | Not treated as an implicitly safe read |
| Browser presentation/read requests and external retrieval tools reviewed as metadata-only | No | Server operation prepares presentation/retrieval; browser evidence remains independently gated |
| Unknown tool, unknown metric type, missing metric type | Yes | Conservative default; model arguments cannot opt out |

This is a registry of data dependencies, not a whitelist of user phrases. A
metadata-only classification is not proof that a tool succeeded or that its
returned evidence is complete. Existing read-contract and visual-result checks
remain necessary.

### 3.2 Task-owned barrier and scope checks

The normal `/api/chat` streamed task installs a resource waiter bound to the
originating owner and case. It checks task cancellation and case availability
even for warm tools, rejects archived/detached cases and changed CT input, and
waits through the existing bounded/cancellable restore only when required.

The closure does not infer case identity from whatever cookie happens to be
active after browser navigation. It is removed/restored when the task exits.
An explicit CT import legitimately marks a previous restore as superseded; this
flag alone does not permanently disable future chats against that same live,
ready Agent. A replaced Agent or mid-turn input change is still rejected.

Resource failure produces a not-executed operation failure instead of silently
dropping the user's requested action or blaming an empty provider response.
Independent metadata siblings in a mixed batch are not automatically discarded.
No resource-failure proposal becomes an execution grant.

Non-chat callers with an explicitly cold Agent and no waiter cannot execute
array-dependent operations. Legacy CLI/test Agents without a readiness flag keep
their existing warm behavior. The legacy non-streaming HTTP route remains
conservative and waits for full resources before running chat; this delivery does
not claim that route has the same cold-start speedup as the normal streamed UI.

### 3.3 Bounded first-round saved evidence

The shared provider-packing boundary inserts an explicitly marked passive-data
packet before the actual user request for semantic-first, non-hidden-child turns.
The packet:

- reads the server-owned active-plan boundary under the memory lock;
- follows the existing same-run live-alias / active-snapshot selection rules;
- does not resurrect a stale snapshot when an explicit empty live metric state
  indicates invalidation;
- includes only finite saved CTV dose/quality fields, positive saved seed/needle
  counts, selected artifact-status/version fields, and at most eight OAR rows;
- explicitly marks OAR truncation and the number of available rows;
- labels data as saved, not freshly calculated or independently validated;
- does not include CT/dose arrays, meshes, patient identifiers, report contents,
  image attachments, execution receipts, or an assertion of clinical approval;
- preserves stored volume-fraction representation instead of inventing a
  fraction/percentage conversion;
- refuses an oversized packet rather than clipping JSON into misleading data;
- refreshes the existing packet in place before each provider round after tools
  or restore repairs, rather than accumulating copies or retaining pre-write facts.

The model still decides relevance. Missing, stale, required-fresh, spatial, report
content, or truncated evidence must be retrieved. Saved metrics cannot establish
that values appear in the report, and neither metrics nor a saved existence flag
can establish a visual location or completed mutation. Existing answer coverage,
authorization, execution receipts, and semantic repair remain in place.

### 3.4 User-visible progress

No fake pending resource step is inserted for a metadata operation. Actual waits
receive a stable task-scoped trace step, localized using the task language:
"Preparing resources for the operation" / "准备操作所需资源". Repeated unchanged
updates use the existing heartbeat interval. Success closes the step; failure
marks it as an error. Internal reasoning is not emitted as a final answer.

Existing turn timing metadata also records `saved_evidence_ms` and, on successful
full waits during instrumented turns, accumulated `workspace_wait_ms`. These are
diagnostic phases, not a measured guarantee of end-to-end response latency.

## 4. Files changed

| File | Change |
| --- | --- |
| `agent_runtime/workspace_readiness.py` | Shared operation dependency contract, saved evidence, and resource preparation |
| `AgenticSys.py` | Attach the case Agent to its registry; guard before memory injection |
| `agent_runtime/core.py` | Guard direct registry execution against cold workspace bypass |
| `agent_runtime/llm_runtime.py` | First-round evidence and per-round refresh; prerequisite-safe barriers in both provider loops |
| `agent_runtime/chat_workflows.py` | Resource barrier before verified direct workflows inspect clinical prerequisites |
| `web/chat_tasks.py` | Install/clean up task-owned waiter; localized progress for actual waits |
| `web/routes/planning_routes.py` | Remove language-based blanket wait; bind operation wait to owner/case/task |
| `web/workspace_store.py` | Preserve live dialogue/UI/locale/config/ledger during background array publication |
| `tests/test_chat_case_resources_wait.py` | Replace language-routing assertions with actual operation contracts; retain wait failure/cancellation coverage |
| `tests/test_accuracy_first_latency.py` | New synthetic counterexamples and integration contracts |

## 5. Validation evidence

All runtime-code validation took place in a private source stage before guarded
delivery, not in the public-release checkout. External model assets were resolved
read-only from the existing deployment. Tests did not run real patient planning
or paid model inference.

Stage:
`/tmp/brachybot-monitor-closed-loop-stage-20261005-imscxicl`

Validation-only environment:

```bash
export BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan
export PATH=/home/lht/.vscode-server/cli/servers/Stable-04c0d99f4fb0d8afe6ce4f0c58e31e183ac3e4b1/server:$PATH
PY=/home/lht/.conda/envs/brachytherapy/bin/python
```

Targeted command:

```bash
"$PY" -m pytest -q \
  tests/test_accuracy_first_latency.py \
  tests/test_chat_case_resources_wait.py \
  tests/test_semantic_kernel.py \
  tests/test_chat_tasks.py \
  tests/test_workspace_store.py \
  tests/test_request_parse_contract.py
```

Result: **319 passed, 3 warnings in 10.81 s**.

Full top-level product suite:

```bash
"$PY" -m pytest -q tests
```

Result: **2,491 passed, 2 skipped, 31 warnings, 4 subtests passed in 52.59 s**.
Logs: `accuracy-latency-targeted.log` and `accuracy-latency-full.log` in that stage.
This does not include the separate benchmark/experiment suites.

The two skips are reported by the existing suite, not introduced as a workaround
for this change. Warnings include existing SWIG and `datetime.utcnow()`
deprecations. An earlier private-stage run without the validation environment
reported three failures (model catalog, external cascade resources, Node locale
counterexamples). The temporary directory changed the default external model
root and Node was absent from PATH. Correcting validation-only paths resolved
those failures; no product assertion or dependency guard was weakened.

New coverage includes cold and failed-hydration metadata reads, protected array
operations, unknown/mixed-effect tools, direct registry bypass, barrier before
memory injection, same-plan evidence, stale/empty state, finite values, privacy,
truncation, post-write packet refresh, background interaction preservation,
localized wait progress, cleanup, and six synthetic tests through the real
Flask chat route. The one-provider-round tests use deterministic provider
doubles with the real packing path: they establish that the architecture does
not require an extra metric call, not that every live model will answer correctly
in one call.

## 6. Runtime acceptance still required

After an idle-time LAN restart or equivalent approved source reload, evaluate a
held-out, de-identified request set against the actual configured model and UI.
Keep correctness as the primary acceptance criterion; report latency second.

Use matched model/provider configuration and compare warm versus cold cases:

1. Saved dose question: answer the actual requested fields without unnecessary
   full-image wait; disclose stale state where applicable.
2. Dose plus report question: verify report text/attachments separately; do not
   infer report coverage from saved metrics.
3. Guide status versus guide regeneration: status stays read-only; regeneration
   waits for required inputs and obtains verifiable execution evidence.
4. Unknown/compound requests: preserve all subgoals and reject out-of-scope writes;
   do not drop a dependent subgoal solely to make the turn faster.
5. Cancel, archive, CT replacement, case navigation, and background restoration:
   no wrong-case result, stale action, lost dialogue, locale reset, or forever
   pending resource step.
6. Incomplete/truncated/stale facts: the agent retrieves the missing evidence or
   states a precise gap instead of fabricating values or claiming completion.

Measure task acceptance to first meaningful feedback and verified final response,
provider rounds, tool rounds, resource wait, and failure/repair rates. Stratify
read-only, presentation, and clinical-mutation tasks. Report p50/p95 together
with correctness and known failure cases; do not substitute test-suite runtime
or the duration of a deterministic model double for those results.

No live end-to-end latency delta, comprehensive natural-language accuracy rate,
clinical validity, or universal "understands every input" guarantee is established
by this code/test delivery.
