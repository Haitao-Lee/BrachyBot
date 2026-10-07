# Intent, Execution, and Response Contract Audit

Date: 2026-10-07

## 1. Scope and claims

This review addresses the full conversation chain, not a list of special-case user phrases: original human input, discourse references, routing, provider schemas, proposed operations, authorization, dependencies, execution receipts, fact availability, asynchronous presentation, and final-answer synthesis. The implementation targets the LAN checkout at `/home/lht/snap/brachyplan/BrachyBot`, based on commit `e20289fc23e8d8d087222c27ded6ee01d105641d`.

The public-release checkout and service are outside this change. No real patient planning, GPU inference, clinical approval, production browser mutation, Git commit, or push is part of validation. No provider credential is written to this report or the synthetic evidence.

The result is a substantially stronger decision and execution contract. It is **not** a proof that a configured language model correctly understands every possible request. In particular, a validated model proposal is neither human authorization nor a semantic truth oracle. Runtime audit output deliberately retains `semantic_accuracy_verified: false`.

## 2. Why keyword fixes were insufficient

There were several independent causes of apparently poor understanding:

1. A routing label could replace the complete request and its restrictions.
2. Tool receipts and generated screenshot-child instructions were stored under historical user roles. Reference resolution could mistake transport text for the latest human instruction.
3. A tool-name grant could authorize a different action or parameter set on the same tool.
4. A manual planning step could inherit full-workflow prerequisite authority.
5. A successful read of the wrong subject could satisfy a loosely defined factual goal.
6. One of several requested capabilities could be mistaken for completion of the whole request.
7. Browser dispatch, factual reads, visual analysis, and saved-content presentation were conflated.
8. UI success prose could say an operation was completed before a browser receipt existed.
9. A report-content question had no compact direct read of the saved report fields. Reading current dose was not evidence of what the report contained.
10. Equivalent reads were repeated, while normalized-away or refused calls could disappear from model context.
11. A previous confirmation-like conversation could be interpreted as current execution permission.
12. Legacy `D90/V100` metric casing disappeared from the first-pass fact envelope, even though the measurement tool could read it.

These causes interact. Replacing one classifier prompt or adding phrases such as “show guide” would leave the other failures intact.

## 3. Decision architecture

The normal semantic path now follows this separation:

```text
Immutable human request + real nearby dialogue
                  |
                  v
Same primary function-calling model pass
  - requested outcomes and constraints
  - passive record_request_plan, alongside necessary evidence calls
                  |
                  v
Operation/schema/target validation and independent authorization
                  |
                  v
Admitted dependency graph -> actual executors -> typed receipts
                  |
                  v
Selector-bound facts + field availability + pending/failed outcomes
                  |
                  v
Answer the original request, preserving partial results and uncertainty
```

Lexical hints remain useful for stable operational shortcuts, but do not establish permission or answer coverage. A content topic alone no longer bypasses primary semantic interpretation. Direct, proved display commands and native visual transport remain compatible. The new mechanism does not add a separate model classifier to every turn.

### 3.1 Requested outcomes are passive

`record_request_plan` records bounded goals with clause identities, mode, outcome, evidence source, and necessary capabilities. It covers restrictions and context as well as actionable clauses. It cannot execute an operation or grant a write.

Factual read requirements bind the actual operation selectors, such as `metric_type`, `target`, `action`, or `planning_id`. All listed capabilities and requirements are necessary, not alternatives. Optional field paths and returned contract aspects must be actual observed schema paths, not descriptions invented by the model.

Invalid proposals receive visible failure receipts and one bounded repair opportunity; they do not erase an earlier valid plan. A malformed dependency graph does not poison the next corrected call. Pending browser work is not redispatched merely to obtain a missing synchronous result.

If the production semantic frame offers multiple clauses and the model omits the outcome proposal entirely, the final boundary requests one bounded reconciliation. The audit distinguishes required/recorded plans explicitly. A single uncomplicated saved-fact answer keeps its existing one-model-round path; this guard must not impose a mandatory classifier or synthesis round on every greeting or numeric question.

### 3.2 Safe ambiguity handling

A pure clarification can carry one bounded `clarification_question` in the passive goal. If there are no independent factual/action outcomes or other operation receipts, the runtime returns that question directly without another synthesis call. It cannot hide a successful partial operation, failure, independent answer, or unsupported outcome.

This contract removes an unnecessary generation round. It does not independently prove the model selected the best question; question quality still requires human and held-out evaluation.

## 4. Verified defects and repairs

| Area | Root cause | Repair | Main implementation |
|---|---|---|---|
| Original request | Last historical user-role entry could be a tool receipt | Separate transport from human discourse; keep the current request immutable and thread-local | `discourse.py`, `chat_workflows.py`, `request_parse.py`, `artifact_analysis.py` |
| Whole request | Clause restrictions and sibling outcomes could disappear | Passive clause frame and same-pass outcome ledger; bounded factual repair | `request_frame.py`, `semantic_kernel.py`, `llm_runtime.py` |
| Content routing | Content classification alone could select a presentation shortcut | Require an admitted operational shortcut; otherwise retain semantic interpretation | `semantic_kernel.py` |
| Parameters and authority | Approval of a name could authorize another operation | Frozen finite-JSON call grants; protected selectors cannot be substituted; deny scoped mismatch without broad fallback | `execution_authorization.py`, `response_tools.py` |
| Workflow scope | Manual/dose operations could grant a full planning workflow | Full planning alone grants its prerequisite workflow | `AgenticSys.py`, `response_tools.py` |
| Aggregate references | Default “all” or an incorrect cardinality could broaden scope | Named objects or sourced ellipsis only; enforce exact distinct-object counts | `request_parse.py` |
| Reported completion | “You said it was updated” could be read as an update command | Separate attributed and accomplished speech from independent later imperatives | `request_parse.py` |
| Confirmation | Assistant prose or stale proposals could authorize a write | Server-bound, deep-frozen, expiring, immediate-next-turn proposal fenced by case/CT/plan/version; no replay | `confirmation.py`, `chat_workflows.py` |
| Concurrent turns | Shared blocked-call lists could mix pending proposals | Thread-local proposals and blocked-name accessors | `chat_workflows.py`, `response_tools.py`, `llm_runtime.py` |
| Provider boundary | Malformed arguments could silently become defaults | Reject non-object/non-finite JSON; preserve rejected-call identity and failure receipt | `step_execution.py`, `semantic_kernel.py` |
| Dependencies | UI “done” or ordering could stand in for success | Depend on executor receipts; failures block dependents, not unrelated siblings | `step_execution.py`, `llm_runtime.py` |
| Evidence coverage | Wrong-subject, partial, unavailable, or pre-write facts could count | Selector fingerprints, returned aspect/field states, all-required matching, state epochs | `step_execution.py`, `semantic_kernel.py` |
| Repetition | Duplicate reads lost the original facts or pending status | Reuse unchanged same-turn results with original text and status; invalidate after writes | `step_execution.py`, `llm_runtime.py` |
| Saved report | Plan metrics were treated as report contents or screenshots | Compact authenticated direct saved-field read using `analysis_basis=structured` | `ui_content/__init__.py`, `AgenticSys.py`, `core.py` |
| Browser presentation | Ordinary presentation could replace the answer with screenshot acknowledgment | Wait for actual visual callbacks only; ordinary presentation/structured reads continue answer synthesis | `llm_runtime.py`, `ui_content/__init__.py`, `ui_screenshot/__init__.py` |
| False completion | Accepted UI requests were described in the past tense | Executor-owned pending prefix, localized pending trace, final-round outstanding-receipt context | `step_execution.py`, `core.py`, `llm_runtime.py` |
| False approval | Unqueried approval had been represented as `false` | Explicit unknown/not-queried scope; no inferred approval or rejection | `ui_content/__init__.py`, `request_frame.py` |
| Version comparisons | Different counter namespaces could be compared | Explicit comparison limitations; use actual freshness/provenance or comparable values | `ui_content/__init__.py`, `request_frame.py` |
| First-pass facts | Uppercase legacy metric keys appeared absent | Unambiguous case-insensitive projection; explicit canonical absence wins | `workspace_readiness.py` |

## 5. Saved-report read contract

The new direct read is separate from existing visual report presentation:

```json
{
  "target": "report",
  "analysis_basis": "structured",
  "question": "Verify whether the requested metrics are present in the saved report"
}
```

The server resolves the authenticated workspace; the model cannot supply `_agent` or a different workspace root. A configured durable `snapshot.json` is preferred over memory. Reads are bounded to 8 MiB and require the matching case identifier. Parse failure, wrong case, or a requested planning ID not matching the saved report returns explicit unavailability, not inferred contents from current dose.

Only selected report fields, bounded metrics/OAR rows, quality fields, and relevant provenance enter a bounded 24,000-character envelope. Sensitive path/token/password/patient/email/phone keys are excluded. Truncation is explicit. The result does not include patient arrays, screenshot bytes, or unsaved editor text.

`field_read_contract` records the selected top-level fields, their explicit absence, the count of unselected fields, and any fields dropped for the output budget. It explicitly states that whole report text was not inspected. Absence from this projection cannot establish absence everywhere in the report. Missing D90 in an inspected metrics object and an empty inspected OAR section are narrower findings than a claim that the entire document lacks prescription or OAR information.

Unknown freshness is neither current nor stale. Report version, snapshot revision, source data version, and planning data version are not automatically interchangeable. Clinical approval records are not queried by this field read; `clinical_approval_status=unknown` must not be interpreted as approval denied or no approval exists.

`analysis_basis=visual` still uses the browser visual callback. Other content targets are not falsely converted into synchronous reads.

## 6. Execution and response semantics

The important distinctions are:

| Runtime fact | What may be stated | What must not be inferred |
|---|---|---|
| Accepted/queued UI action | Request submitted; awaiting browser receipt | Report updated or object displayed |
| Successful read | Returned fields and their actual scope | All requested sibling facts are available |
| Reused pending result | Same request is still pending | Reuse completed the operation |
| Failed/not-admitted call | Specific operation did not succeed/was not attempted | No other independent action occurred |
| Empty saved OAR report section | That saved section contains no rows | Current plan has no OAR dose |
| Unavailable field | This read did not establish the field | Field value is zero |
| Zero returned measurement | Valid zero-valued observation | Missing data |
| Existing plan/guide | Artifact exists in the identified scope | Reviewed, approved, printable, or clinically safe |

The final-round context puts pending execution state adjacent to the answer instruction and explains that observing an existing receipt is the next step, not retrying a still-pending operation. This is a general executor contract, not a phrase-specific final-response rewrite.

Deterministic state enforcement reduces contradictions but does not establish that every generated sentence is factually grounded. Numeric, physical-mechanism, and clinical-interpretation claims still require actual evidence and an appropriate evaluator.

## 7. Regression scenarios

The new `tests/test_intent_chain_adversarial.py` contains 107 collected test cases. The count includes parameterized engineering cases, not 107 independently sampled natural-language benchmark items.

Realistic request families include:

- Dose distribution plus whether those values were actually saved in the report.
- A correction asking for organ dose instead of organ volume.
- Reported previous completion contradicted by saved state, with an explicit prohibition on regeneration.
- A guide-status or location question that must not generate a new guide.
- Hypothetical needle restoration with explanation only, not execution.
- Updating named downstream artifacts while excluding planning, dose recomputation, and geometry edits.
- Ambiguous “all of them” with multiple plans and no clinically approved target values.
- Attribution of one needle edit versus linked seed reprojection.
- Quoted log instructions, nested external material, and hidden visual-child transport.
- Chinese/English requests, ordinary references, cardinality mismatches, and compound restrictions.

Additional adversarial contracts exercise malformed provider JSON, NaN/infinity, numeric/boolean substitutions, confirmation expiry/replay/case switches, concurrent turns, partial batches, wrong metric selectors, missing fields, explicit zero, stale facts after writes, invalid dependency graphs, duplicate reads, failed-call repetition, and both streaming/non-streaming loops.

These tests intentionally run production guards and provider-loop code with deterministic providers. They do not measure the semantic accuracy of a real language model.

## 8. Product-suite validation

Final candidate: **2,630 passed, 2 skipped, 31 warnings, and 4 subtests passed in 65.62 seconds**. Validation used `/tmp/brachybot-monitor-closed-loop-stage-20261005-24pzsybn`, a private current-source stage with no live `.runtime` or patient directory. The older date in the stage prefix is inherited from the staging helper, not the validation date. Read-only model availability paths point to the existing deployment parent so staging does not invent missing model failures.

Full log: `/tmp/brachybot-intent-full-tests-final-confirmed-20261007.log`.

The 107 new adversarial cases are included in that suite. Python compilation of selected implementation files and the new test module also passed. The two skips are explicit integration prerequisites: `test_public_http.py` requires the public deployment extras, and `test_public_proxy.py` requires `NGINX_TEST_BINARY`. The warnings are existing SWIG and `datetime.utcnow()` deprecations; they are not interpreted as passing deployment checks.

Earlier iteration failures were repaired rather than hidden. Old aggregate-scope fixtures were corrected to provide actual named prior objects instead of granting default “all”; the source-string presentation assertion was replaced by behavior checks; the old content-topic bypass expectation was replaced by a primary-semantic negative control. The one-round saved-fact latency test remains unchanged and passes. No guard was relaxed to count missing fields, no-op actions, pending dispatches, or malformed proposals as success.

Reproduction command:

```bash
cd /home/lht/snap/brachyplan/BrachyBot
export BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan
export PATH=/home/lht/.vscode-server/cli/servers/Stable-04c0d99f4fb0d8afe6ce4f0c58e31e183ac3e4b1/server:$PATH
/home/lht/.conda/envs/brachytherapy/bin/python -m pytest tests/ -q --tb=short -rs
```

This is the product `tests/` suite, not the separate large benchmark suite. A passing suite is not a clinical validation, GPU compatibility test, real-proxy validation, or browser acceptance test. Skipped integration prerequisites must be reported explicitly.

## 9. Configured-provider qualitative probes

The private smoke helper uses the configured provider/model, the production prompt packing and normalization, real read-only measurement/report tool contracts over synthetic facts, and real UI-action validation/queueing. Guide-generation output is deliberately simulated, without patient, GPU, application endpoint, or browser execution. It must not count as a successful guide or a clinical experiment.

Six fixed scenarios are used: dose/report reconciliation, OAR dose correction, disputed report freshness, hypothetical edit, scoped downstream updates, and ambiguous aggregate changes. Calls have explicit retry/time/output budgets. Provider credentials remain in memory; only synthetic requests, results, operation proposals, and non-secret audit data are saved privately.

Repeated probe iterations exposed real defects that deterministic tests alone missed: unqueried approval encoded as false, pending dispatch narrated as completion, disappearing legacy metric casing, and unnecessary clarification synthesis. These led to contract repairs and new negative controls.

The last six-scenario batch used `generic / deepseek-v4.1-flash` and produced the following qualitative observations. Later changes to compound-plan enforcement were rechecked separately on the explanatory case and in both deterministic provider loops; do not treat these rows as a final-version six-item accuracy score.

| Synthetic request | Provider calls | Observed time | Observed behavior |
|---|---:|---:|---|
| Current dose plus saved-report omissions | 2 | 10.980 s | Read current target/OAR values and the actual saved report; identified changed coverage values and missing D90/OAR rows in selected fields |
| OAR dose, not volume | 2 | 6.419 s | Returned spinal-cord/brain Dmax and D2cc; did not substitute volumes |
| Disputed report freshness, no regeneration | 2 | 9.965 s | Read saved report; preserved read-only scope and explicit stale provenance |
| Hypothetical needle restoration, explain only | 2 | 28.214 s | No mutation; exposed an unsupported claim about automatic optimization, which triggered further contract clarification |
| Update report/guide, exclude planning/geometry | 3 | 16.504 s | Queued report honestly as pending; did not mistake simulated guide output for a verified artifact; queried guide status |
| Ambiguous aggregate changes | 1 | 5.153 s | Asked a structured clarification without mutation or an additional synthesis call; question wording remained broader than ideal |

An earlier explanatory probe took 52.977 s. The later explanatory recheck took 14.849 s and recorded its outcome plan. This variation is not evidence of a measured speedup: provider response time, generation length, and network behavior were not controlled in a paired latency experiment.

The smoke is explicitly `comparable_benchmark_result=false`. It is not a held-out aggregate accuracy estimate or a latency comparison with the old version. It also reveals residual response-quality limitations: models can over-explain, ask a broader clarification than necessary, infer an unsupported physical explanation, or suggest an unnecessary next action despite correct operation admission. These must not be concealed by a green engineering suite.

Private synthetic evidence paths include `/tmp/brachybot-intent-live-results-delivered-20261007.json` and `/tmp/brachybot-intent-live-results-hypothesis-verified-20261007.json`. The latter records `outcome_plan_required=true`, `outcome_plan_recorded=true`, one planned goal, no mutation, and a 14.849-second two-call explanatory response. These contain no real case data or provider credentials.

## 10. Efficiency and user experience

- Original-request framing, selector fingerprints, receipt matching, casing compatibility, and proposal validation are local bounded operations.
- The requested-outcome ledger is emitted in the same primary model batch as evidence calls; there is no mandatory extra intent-classifier model call.
- A pure structured clarification can end after the first provider call.
- Unchanged same-turn reads retain factual payloads rather than being executed again.
- Structured report verification does not capture images or wait for a visual-analysis callback.
- A single bounded factual/plan repair is used instead of an unbounded retry loop.
- Actual image interpretation remains asynchronous and cannot be replaced by fabricated visual evidence.

Accuracy takes priority over saving a necessary measurement or provenance read. No percentage improvement, P95 claim, or universal speed claim is supported by these six probes. Production end-to-end latency includes resource readiness, browser capture/upload, provider variance, and downstream jobs not exercised here.

## 11. Delivery, activation, and isolation

Delivery is guarded by the exact baseline commit and selected before-hashes. Changed existing files receive a recoverable restricted backup. Archive inventory, post-delivery hashes, compilation, and whitespace checks are verified. Concurrent edits must abort delivery rather than overwrite another worker.

The selected delivery consists of 22 files: 18 modified existing files and four new files (`discourse.py`, `confirmation.py`, the adversarial test module, and this report). No planning-engine or surgical-guide geometry algorithm is changed.

The LAN Python process is not automatically restarted as part of this patch. Therefore validation of new code in a private stage must not be described as activation in the running service. A controlled LAN restart, after checking active work and preserving session/runtime data, is required to load changed Python modules. The independent public service must not be restarted or overwritten as a side effect.

## 12. Remaining acceptance work

1. Run a separately labeled live-browser acceptance set on the newly activated LAN process: hidden/loaded guide display, report content versus figures, visual capture follow-up, monitor stop/start, pending report callbacks, and concurrent case switches.
2. Run a held-out natural-language set through the actual user endpoint with independent expected outcomes, including paraphrases and multi-turn corrections. Score request understanding, exact operation scope, observed task completion, factual response accuracy, unnecessary clarification, and latency separately.
3. Test provider failure, output truncation, unavailable tools, cold resource hydration, and late browser receipts without weakening admission or receipt contracts.
4. Judge unsupported clinical/physical claims independently. Current-dose measures, planning-quality claims, manufacturability, approval, and patient benefit must remain distinct.
5. Keep ambiguous/high-risk actions bounded. A system that confidently guesses a missing patient, plan, object, or clinical parameter is not a smarter system.

The implemented contract repairs are reusable across requests and capabilities. Further semantic-quality claims require empirical evaluation, not more keyword lists or a self-reported completion flag.
