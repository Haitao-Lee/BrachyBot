# Whole-request semantic interpretation: audit and remediation

## Objective and limits

The objective is to preserve an actual user's requested outcomes through interpretation, tool selection, authorization, evidence collection and final synthesis. This is not a claim that a language model can correctly interpret every possible utterance. Nor is a deterministic contract test a measurement of production-model understanding accuracy. Source changes must not change prescriptions, geometries, patient records, or independent public deployment state.

## Architecture assessment

The system already has a primary function-calling model, conservative shortcut acceptance, a separate execution-authorization ledger, ordered action plans and scoped evidence. Replacing it with another keyword classifier or an unconditional second model-based router would duplicate decisions, add latency and create more divergence. The appropriate architecture is:

1. Preserve the current human message and bounded relevant discourse as the semantic authority.
2. Use local parsers only as fallible structural hints and positive shortcut proofs. Abstain when a shortcut cannot cover the whole request.
3. Resolve outcomes, references, restrictions, dependencies and evidence needs in the existing primary model call. Do not output private reasoning.
4. Allow evidence gathering appropriate to the requested outcome; a topic label is not permission and must not silently hide the evidence needed for another clause.
5. Validate tool arguments, Session ownership, backend prerequisites, action-specific authorization, and receipts independently of the model.
6. Treat intermediate tool-round text as progress. The terminal answer must reconcile all requested outcomes with returned evidence, partial failures and unknowns.

## Reproduced defects

- `If I regenerate the surgical guide, will the report change?` could enter the local guide-existence shortcut. Its status regex accepted a generation word near a question marker but did not reject a hypothetical or another artifact subject.
- Compound-read resolution discarded clauses flagged negated/conditional/quoted. In `当前剂量是多少，请对照报告看看有没有漏写`, a still-relevant report question was dropped and only the dose read survived. Inability to authorize a write is not absence of a question.
- Chinese quantity/extent/time forms (`多少`, `多大`, `多久`, `怎样`) were missing from the shared interrogative boundary, despite being recognized by other topic detectors.
- Polite modal display requests were not considered actions because display/UI-change are outside the clinical write-action set. Presentation and routing therefore disagreed about `Can you show the guide?`.
- A UI topic candidate exposed only a small UI surface, even for a user who requested UI interaction plus case/knowledge interpretation.
- Undeclared direct-read coverage could be treated as proof of complete coverage and even erase a sibling metric gap. Unmodeled requests could also receive a deterministic completeness bypass.
- Streaming final synthesis preferred concatenated text from all previous tool rounds over the terminal model text. This could reintroduce an earlier “no data” statement after a later tool returned those data. A tool failure could also promote pre-tool progress into the final fallback.
- The plain `chat()` Session-content branch referenced undefined `steps`/`step_id` variables.
- The ambiguity prompt prohibited even useful read-only discovery, encouraging avoidable clarification questions.

## Implementation

### Shared whole-request frame

`agent_runtime/request_frame.py` creates stable clause IDs and source offsets directly from the human's original string. Unknown clauses remain present. Quotes are not split into executable commands. Excerpts and prior discourse are bounded; omitted/truncated content is explicitly declared, and the full original message remains the actual provider user message. Historical receipts are excluded; history has reference-only authority. The frame itself never grants execution, calls a provider, performs I/O, or loads a UI/patient snapshot.

The existing streaming and non-streaming provider calls receive the same interpretation/completion contract at their shared context-packing boundary, once per initial provider request. Trusted instructions remain in the system role; original human excerpts stay in a separate passive user-role record. The original, possibly multimodal, request remains the last user message. This replaces the earlier generic whole-request instructions rather than accumulating a second classifier prompt in each transport. It requires outcome-level interpretation, contextual reference resolution, restriction preservation, source selection, minimal discovery, and coverage of every requested outcome in the final answer. It does not require a separate router call, a visible reasoning trace, or a canned response format.

### Shortcut abstention and capability access

Hypothetical, attributed, quoted or cross-artifact guide questions no longer enter the guide-status shortcut. A current-plan ownership qualifier is distinguished from coordinated plan/guide subjects. Compound-read planning abstains instead of dropping uncertain substantive clauses. A polar negative status question remains a question; a pure prohibition remains a restriction in the original request and contributes no operation. Straightforward status questions retain their verified read path. UI semantic interpretation can access the existing semantic capability surface so a UI noun cannot erase a fact/knowledge subquestion; mutation authorization and backend validators remain independent and unchanged.

### Speech acts and evidence coverage

The shared parser recognizes ordinary quantity/time/extent questions. A dose quantity is not an organ count, and per-needle count coverage includes the ordinary Chinese needle measure word. Modal display requests are recognized as requests, while how-to/conditional questions remain information-seeking. Unknown read coverage no longer proves completion. Modeled metric coverage is still computed over the union of returned declared aspects; unfamiliar requests require semantic synthesis instead of assuming a small metric payload answered everything.

### Final synthesis and error handling

Streaming synthesis uses terminal-iteration text rather than accumulated pre-tool progress. With executed tools, unavailable evidence cannot be substituted by earlier optimistic model prose. Honest partial failure remains possible. The plain-chat content branch supplies explicit local trace containers instead of undefined variables.

## Efficiency policy

No additional interpretation-provider call is introduced. Frames contain at most 12 clause excerpts totalling 2,400 characters and four nearby discourse excerpts; parser hints inspect only those bounded excerpts. The existing bounded tool/model budgets remain. The contract recommends compact authoritative reads, avoiding repeated equivalent calls, and focused clarification only for ambiguity that changes an operation. Broader UI semantic capability access adds schema cost; it is not a guarantee of lower wall-clock latency. A model latency/accuracy study remains necessary.

## Validation plan and release boundary

Run existing authorization, whole-request, answer-coverage, tool fallback, streaming, plain-chat and visual-delivery regressions plus the new request-frame suite in a private source stage. Preserve existing unrelated edits and the previous report-answer repair. Verify selected-file hashes before delivery; do not blindly renew frozen guide evidence (this patch does not change planning geometry or guide dependencies).

These tests validate structural safety and observed code behavior, not production-provider semantics. No real patient workflow, external search, LLM request, clinical prescription, dose computation or production restart is required for this regression suite. Neither the provider's actual error rate nor “understands every request” is established. Deployment activation and a de-identified, held-out conversational evaluation should follow separately.

## Remaining evaluation work

- Measure outcome coverage, action correctness, evidence/answer agreement, unnecessary clarification, wrong-task execution, failure recovery, latency and schema/token cost on held-out real-user scenarios, not just paraphrases of repaired cases.
- Include unseen object names, multiple active plans, ambiguous antecedents, task cancellation, corrections, quoted logs, conditional instructions, partial approvals, asynchronous callbacks, multilingual turns and conflicting format instructions.
- Inspect primary-model decisions and backend refusals separately: an incorrect proposal safely refused is not successful task completion.
- Keep a real clinician's approved prescription/source/constraints separate from semantic interpretation. A better conversational contract is not independent physics validation or clinical approval.

## Verification evidence (2026-10-06)

The final private stage is `/tmp/brachybot-monitor-closed-loop-stage-20261005-mlccjofi`, based on authoritative checkout HEAD `8fddd02ea769925fb8baa5e29df510e2d937936f`. It includes current uncommitted source edits, including the preceding report-dose answer repair and the unrelated `web/routes/planning_routes.py` edit. No patient runtime directory is copied. Model directories are linked for read-only use by the contract tests; no inference or checkpoint write is run. The existing external liver/kidney adapter paths are supplied explicitly so changing the stage's parent directory does not create a false missing-model regression.

- Full top-level product suite: `python -m pytest -q tests/ --tb=short` — **2,363 passed, 2 skipped, 31 warnings; 4 subtests passed**, 62.19 seconds. Log: `/tmp/intent-full-final-20261006.txt`.
- Focused interpretation, whole-request routing, shortcuts, authorization, evidence coverage, case response and tool-fallback suite: **347 passed, 3 warnings**, 4.37 seconds. Log: `/tmp/intent-targeted-final-20261006.txt`.
- These are product regression suites, not benchmark-model evaluation results, provider accuracy measurements or real-patient/GPU runs. Skipped tests are not counted as validated coverage. Existing SWIG and naive-UTC deprecation warnings remain outside this patch.
- A CPU-only request-frame construction probe (1,000 repetitions of a two-clause request) averaged approximately **1.238 ms per frame**. This is not a model, network or end-to-end latency measurement. No separate model-based classifier is introduced; the mounted UI semantic palette has additional schema cost, and necessary completeness checks must not be skipped merely to reduce latency.

Initial validation did expose regressions: a current-plan qualifier was mistaken for another subject; an organ-dose quantity could enter the count detector after expanding the interrogative grammar; and a pure prohibited screenshot incorrectly cancelled the permitted sibling screenshot. They were repaired and retained as contract regressions before the final green run. Existing safety assertions were not weakened to obtain a green suite.

| Input | Verified routing/contract behavior (not a live provider response) |
|---|---|
| `当前剂量是多少，请对照报告看看有没有漏写` | Full semantic path; the report clause is retained; no direct execution grant |
| `如果我重新生成导板会影响报告吗` | Full semantic path; not a guide-existence shortcut or generation grant |
| `当前规划结果生成导板了吗` | Read-only guide status fast path; no generation grant |
| `现在把导板恢复显示，但别改它的颜色` | UI semantic path with available fact/knowledge capabilities; no clinical execution grant |
| `每个器官的剂量是多少` | Current case-dose fact path, not an organ inventory |
| `不要截图导板；请截图肿瘤在哪里` | Only the permitted CTV screenshot is materialized; the prohibited guide target is not included |
| `Can you show the guide without regenerating it?` | Display request, not an information-only capability question; no generation grant |

## Delivery scope

Selected source files are hash-checked against their pre-edit versions before atomic delivery. The selected set contains seven runtime modules, two test files and this document. Existing unrelated edits must be preserved. Neither the independent `BrachyBot-release` source tree nor any service credentials, clinical inputs, planning outputs, database state or model weights are changed. No commit or push is part of this delivery. Python source installation alone is not proof that an already-running worker has reloaded the changes; runtime activation and a held-out provider/browser acceptance run are separate steps.

Delivery completed to `/home/lht/snap/brachyplan/BrachyBot`. The recoverable pre-edit backup is `/tmp/brachybot-monitor-closed-loop-backup-20261005-a53lyt7f` (private directory; its naming prefix belongs to the reused checked-delivery helper, not the date of this change). All ten selected source hashes were verified after installation. The focused suite was repeated in the authoritative checkout: **347 passed**, 4.51 seconds; log `/tmp/intent-delivered-targeted-20261006.txt`. Both `node tests/report_dose_answer.cjs` and `node tests/chat_screenshot_delivery.cjs` passed. Python compilation and `git diff --check` passed. Selected public-source fingerprints remained unchanged, and the unrelated planning-routes edit retained SHA-256 `5d7bd937ec996858c468c80e96a87d2b44989686cce1b9e69254f9f30f2e0795`.

At the post-delivery listener check, LAN 8080 remained PID `1326660` and public 18082 remained PID `1327750`. This turn has not restarted either service. These are point-in-time observations, not guarantees about subsequent concurrent operations. The installed Python changes require controlled worker activation; do not treat the existing page or an HTTP success as evidence that the new interpretation contract is active.
