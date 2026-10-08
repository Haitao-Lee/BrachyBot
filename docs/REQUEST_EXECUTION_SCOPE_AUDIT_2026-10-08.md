# Request execution scope audit and remediation

Date: 2026-10-08  
Product checkout: `/home/lht/snap/brachyplan/BrachyBot`  
Audited baseline: `f9864f5791f5a7abcf05ea64b8f638babe9bafbc`

## 1. Finding and scope

The reported question was whether “仅作重新规划” can perform replanning without rebuilding a guide or launching unrelated downstream work. The follow-up explicitly broadened the investigation to similar restrictions on other tasks.

The exact phrase was not uniformly broken at baseline: it reached the default semantic route, and the existing second-line parser admitted planning but rejected guide generation. That fact does not establish an end-to-end guarantee or general semantic correctness. Adjacent paths were inconsistent:

1. The legacy replanning action plan included `surgical_guide` even without a guide request. Its comment incorrectly equated guide invalidation with mandatory regeneration.
2. A postposed restriction could negate its positive antecedent. `Replan without regenerating the guide` denied planning and failed to associate the exclusion with the guide.
3. `Only recompute the current plan's dose` / `只重新计算当前规划方案的剂量` selected planning instead of dose. The owning-plan noun was treated as a second operation rather than a possessive/source reference.
4. `Only update the dose` / `只更新剂量` parsed a dose goal but failed the tool's action-family check.
5. Consent timing such as `update the report after I approve` could acquire immediate write authorization.
6. A part-only report edit could be substituted with full autofill. The whole artifact and its internal field/table were not distinguished at the effect boundary.
7. Provider proposals, name grants, call grants, normalization, recovery and the final executor lacked one immutable denial-only ceiling. A broad grant could therefore conflict with a restriction checked elsewhere.

This change repairs execution scope, not all natural-language comprehension. The configured primary model remains responsible for interpreting unfamiliar language, resolving identities and choosing valid operations. Unknown or unsupported precise operations must be clarified rather than approximated with a broader write.

## 2. Execution design

### 2.1 Three different sets

- Requested outcomes: actions actually requested by the current human.
- Mandatory inputs: prerequisites needed by an admitted operation, reused when already valid.
- Optional outputs: guide regeneration, report autofill, exports, UI rearrangement and other follow-ups. Staleness alone grants none of these.

A full replanning operation intrinsically runs its trajectory, seed, dose and dose-evaluation stages. “Only replan” does not mean suppressing those internal stages and publishing an unevaluated geometry as a completed plan. It means no separate optional downstream task is appended.

Existing masks are reused by the clinical normalizer. If a required mask is missing and the human prohibited replacing/creating it, the prerequisite remains blocked; neither a workflow grant nor a recovery path may override that prohibition. Planning/report/guide freshness must continue to be updated honestly. Old guide/report artifacts are not deleted or falsely marked current merely because regeneration was excluded.

### 2.2 Immutable effect ceiling

`agent_runtime/execution_scope.py` introduces a turn-local `ExecutionScope`:

- Source is the original current-human message, bound before routing or model grants.
- Restrictions can deny operations but cannot grant them.
- Explicit exclusions and preservation frames identify effects that must remain untouched.
- Positive exclusive clauses bound writes to their finite targets. A separately authorized sibling command remains valid.
- A partial-object request cannot authorize a whole-object producer. A registered report field setter can remain eligible, subject to its existing field/value validator; full report generation/autofill is rejected.
- Registered capability effects describe what tools do. They are not a list of accepted user sentences.
- Read-only metric/status/inspection calls remain available. The ceiling does not pretend that every read is unnecessary.
- The scope cannot be rebound by a later tool receipt, routing hint, assistant plan or follow-up model round in the same turn.

The same ceiling is consulted by name grants, call grants, workflow permission, ordered provider plans, recovery guide checks and the shared final execution entry. A scoped read action does not become permission for the mixed-effect tool's generation action.

### 2.3 Request structure, not sentence whitelists

The existing clause parser is strengthened for grammatical operators and relationships:

- Postposed exclusion/preservation is associated with its own following object rather than the preceding requested task.
- Possessive/source planning-dose phrases distinguish dose recomputation from replanning.
- Dose update/refresh and dose recomputation can select the same dose-only capability; neither grants geometry optimization.
- Waiting for human confirmation is a condition, not an immediately executable sibling.
- A named internal field/part is distinct from its whole owning artifact.
- An output-style modifier such as “without abbreviations” does not prohibit report generation merely because it contains an exclusion word.

Quoted, attributed, hypothetical, interrogative and completed-action protections remain in place. The structural scope projection is deliberately conservative and does not claim to parse every possible paraphrase. Unresolved references or unsupported partial writes do not acquire broader permissions.

### 2.4 Semantic interpretation and feedback

The first existing function-calling model request receives the original utterance, bounded passive clause references and a compact structural ceiling. The instruction distinguishes intrinsic outputs, prerequisites and optional downstream work. There is no extra classifier/model call.

Rejected scope proposals retain their identities and yield explicit not-executed receipts. They do not silently disappear, execute, or become pending confirmations. Independent admitted actions continue. Final synthesis must distinguish verified completion, missing prerequisites, excluded follow-ups and stale artifacts.

## 3. Behavioral examples

| Current request | Permitted operation | Not implied |
|---|---|---|
| Only replan | Existing-mask reuse; full planning's intrinsic stages | New guide, report autofill, export |
| Only recompute the current plan's dose | Current-plan dose/DVH recomputation | New trajectories, new segmentation, new guide/report |
| Only update the report; leave the guide unchanged | Authorized report update | Guide rebuild or replanning |
| Only segment CTV; keep OAR | CTV segmentation with a validated case-bound model selection | OAR replacement, planning, guide generation |
| Only generate the guide; do not recompute dose | Guide generation with existing required valid inputs | Dose/geometry recomputation |
| Only update the report's title | Registered precise field update, if resolvable | Full report autofill |
| Recompute dose; update report after I approve | Dose now; report remains conditional | Immediate report write or invented approval |
| Only replan; then generate report; keep guide | Two separately requested outcomes | Guide rebuild |
| Explain why guide is stale; do not replan | Read/answer | Clinical mutation |

These are examples and regression inputs, not a production sentence-routing whitelist.

## 4. Files and compatibility

- `agent_runtime/request_parse.py`: structural scope, exclusions, preservation, source/possessive relation and deferred consent.
- `agent_runtime/execution_scope.py`: immutable denial-only effect contract and visible proposal denials.
- `agent_runtime/execution_authorization.py`: scope-aware grants and workflow permission.
- `agent_runtime/chat_workflows.py`: early binding, no forbidden pending-confirmation fallback, action-aware recovery guide check.
- `agent_runtime/turn_policy.py`: replan dependency plan no longer includes an unrequested guide. Explicit planning-plus-guide requests retain the dependency sequence.
- `agent_runtime/request_frame.py`: compact first-call scope projection and outcome instructions.
- `agent_runtime/llm_runtime.py`: both real provider loops use the shared proposal-plan gate.
- `agent_runtime/semantic_kernel.py`: localized scope-denial feedback.
- `AgenticSys.py`: final execution denial before resource loading/registry dispatch; action-aware guide permission.
- `tests/test_exclusive_execution_scope.py`: positive and negative synthetic controls, including both actual provider loops.
- `tests/test_semantic_execution_authorization.py`, `tests/test_round7_regressions.py`: replace obsolete assumptions that a replan necessarily rebuilds a guide; preserve explicit guide-generation tests.

The existing unqualified initial full-workflow legacy shortcut is preserved. Explicit “only” constraints stay on semantic interpretation and cannot inherit its broader name grants. Clinical kernels, source/geometry contracts, default guide geometry, report templates and dose calibration are not changed.

Non-chat backend/API callers retain their existing authentication, ownership and validator contracts. This change does not install a conversation permission grant in unrelated APIs.

## 5. Verification

Verification is performed in isolated checkout `/tmp/brachybot-replan-scope-20261008-vXJR2A`, with the existing product Python environment and no patient planning, GPU inference, paid-provider calls, or mutations to live cases.

- Targeted request/routing/authorization/provider-loop regression: **636 passed**.
- Final full product `tests/`: **3,140 passed, 2 skipped, 31 warnings, 4 subtests passed**, in **215.97 seconds**. No failures or collection errors. Evidence: `/tmp/brachybot-replan-scope-final-full-20261008.xml`. The two skips require a real public origin/deployment dependencies and an explicit Nginx binary; they are not scope-test skips. An exploratory run exposed one obsolete guide-after-replan assertion and one missing-Node environment error; neither was concealed. The assertion was updated to the requested behavior, and the final run supplies the existing Node runtime instead of skipping its browser contracts.
- CPU-only scope timing on 550 projections: median **1.285 ms**, P95 **1.790 ms**. Maximum additional passive ceiling serialization in those examples: **111 JSON characters**. These are not real-model latency or clinical workload measurements.
- No added classifier call; no unbounded retry, extra approval interaction or hidden clinical computation is introduced by this scope layer.

Synthetic function-calling replay validates the execution contract even when a simulated model proposes extra guide/report/UI operations. It does not measure the live configured model's comprehension accuracy. Real-model/user acceptance should additionally test paraphrases, ambiguous pronouns, mixed read/write turns, field-only edits and long multi-turn corrections.

## 6. Delivery and remaining limits

Delivery must validate the baseline HEAD and every selected file's pre-change hash, preserve unrelated changes, keep a private recoverable backup, and verify after-change hashes. LAN activation must be deferred while cases/edit leases are active and must not modify or restart the independent public deployment.

This is not a claim that BrachyBot now understands every conceivable request. The hard improvement is that a plausible plan or generic workflow cannot override an explicit current-human effect boundary. Precise unsupported operations must remain unsupported/clarified; no full-artifact rewrite is passed off as a successful partial edit.
