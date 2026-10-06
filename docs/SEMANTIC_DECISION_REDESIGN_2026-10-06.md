# Semantic-first decision runtime: design and verification

## 1. Scope and conclusion

This change repairs architectural causes of mismatched replies. It does not
claim that a language model can correctly interpret every possible request,
that mocked provider tests establish semantic accuracy, or that clinical
operations may be authorized by model confidence.

The LAN checkout is `/home/lht/snap/brachyplan/BrachyBot`. The separate public
checkout and its runtime are outside this delivery. The source baseline is
`476474f400a700f71121c3e63e4380e4dc03bbf6`. No patient case, live provider, GPU
planning, server restart, commit or push is needed for source validation.

## 2. Root causes, not another expression list

The prior implementation already provided whole-request instructions and
guarded local shortcuts. However, several mechanisms still contradicted
those instructions:

1. A lexical candidate could select a canned fact packet before the primary
   model chose evidence. A dose/report compound question could consequently
   inherit a single-source route despite requiring two independent reads.
2. Candidate-specific tool palettes could hide a legitimate capability.
   Improving the model could not recover information from a hidden tool.
3. Normalization, admission and clinical guards could discard a proposed call
   without returning a tool receipt. The model could not distinguish an
   invalid target, unauthorized write, unavailable tool or execution failure.
4. An ordered action plan tracked operation dependencies, not all requested
   information outcomes, restrictions and conversational context.
5. Name-only state-change classification treated read operations of mixed
   tools as writes, invalidating otherwise reusable evidence.
6. A UI `done` label is not proof that an asynchronous browser operation
   completed. Tool success is also not proof that its payload answers the
   user's question.

The repair targets those boundaries rather than enumerating more sentences.

## 3. Decision flow

```
Original request and bounded dialogue references
  -> optional proved fast path OR primary semantic function-calling turn
  -> optional outcome proposal + evidence calls in the same model response
  -> argument/target/scope/authorization/prerequisite validators
  -> execution receipts, including not-attempted denials
  -> bounded evidence repair and grounded synthesis
  -> terminal reply + privacy-minimized decision metadata
```

Understanding, authorization, execution and completion are different states.
Neither the passive request frame nor the outcome proposal grants execution.

## 4. Runtime routing and compatibility

Real configured agents default to `semantic_first`. Ordinary information,
analysis, uncertain and mixed requests reach the primary model with the
established semantic capability palette. The legacy candidate remains an
observable hint, not a final interpretation of the request.

Retained special paths are proved whole-command fast paths, simple greetings,
isolated external-project requests, visual analysis children and saved-content
transport. A direct compound route containing ordinary information reads is
returned to semantic interpretation; established multi-object visual/status
capture contracts remain compatible.

This is not a replacement of clinical authorization with an LLM. Existing
positive-command, destructive-control, ownership, image-input, model-selection
and backend validation gates remain enforced. Existing review/completeness
requirements are preserved; routing does not waive clinical review.
Unrecognized write requests
must produce a visible denial and a useful next decision, not execute merely
because the model proposed a write.

Rollback configuration:

```json
{"agent_runtime": {"intent_mode": "legacy"}}
```

Configuration changes require the usual process lifecycle. Config-less legacy
mixin test harnesses retain their prior behavior; production agents install a
configuration mapping.

## 5. Capability projection

The existing installed semantic tools remain available. New read capabilities
may explicitly opt in by setting `conversation_access = "read"` on their
server-owned registered tool object. Client fields and model-generated schema
annotations cannot opt in a tool. Known writers and execution tools cannot
use this extension to acquire read authority. Unavailable registry tools and
upstream CT/child-boundary filters remain excluded.

Provider schemas are deep-copied before projection. Narrowing a turn must not
modify cached registry schemas used by later turns.

For mixed-effect tools, operation selection is explicit: mutating defaults are
removed and `action` is required. Shared `clinical_kb` writes are not exposed
through this conversational projection. Case-memory saves and guide generation
still require their existing action-sensitive execution gates.

## 6. Outcome proposal

`record_request_plan` is a turn-local virtual bookkeeping tool, not a product
mutation. The model can emit it alongside necessary evidence calls, avoiding
a separate classifier/planner round. Simple replies need no plan.

The bounded proposal contains at most 12 goals, each with clause references,
requested outcome, discourse mode, intended evidence source and registered
capability names. It accounts for every retained original clause, including
restrictions/context. Invalid identities, unknown capabilities, omitted
clauses, over-budget lists and truncated frames are refused atomically.

Restriction/context/clarification/unsupported goals cannot propose tools. The
proposal is excluded from the business action plan, execution grants and
clinical evidence digest. Audit metadata records counts and a request hash,
not raw patient request text or model reasoning.

Structural coverage is NOT semantic correctness: the model can still attach
the wrong meaning to a clause or select a tool that returns irrelevant data.
Instructions require field-level reconciliation, but a successful receipt is
only evidence that a read ran, not that the answer is correct.

## 7. Visible admission and outcome receipts

The plain and streaming loops preserve original call identities. Calls lost
at normalization, mounted-capability checks, CT guards, redundant-work guards
or authorization filtering become not-attempted failure receipts. They do not
grant permission, execute, advance the mutation epoch or erase valid siblings.

The model receives those receipts in a valid assistant-tool pairing. It can
perform a bounded discovery read, choose an available alternative, ask one
focused clarification or explain a real limitation. Repeating the unchanged
rejected operation is discouraged. The rejection describes that operation,
not an incorrect blanket claim that no other operation ran.

Text-format calls receive stable per-batch identities before normalization,
so two parameter variants of the same tool cannot hide one another's denial.
Duplicate explicit provider identities are refused with unique failure-receipt
identities. This changes bookkeeping, not execution authority.

If UI normalization reduces a proposed action array, the model receives the
original and admitted entry counts alongside the execution result. That result
applies only to the admitted batch. A reduction can include rejection or
consolidation; counts alone do not identify which requested outcome failed.
The model must reconcile the actual payload against the request rather than
claim that all original entries executed independently. Runtime notices survive
subsequent admission stages; model-supplied notices are not trusted.

For planned factual reads, reconciliation consumes executor receipts, not UI
trace labels. Failed, pending, dispatched and queued outcomes cannot satisfy a
read. Reads before an attempted write cannot satisfy a post-write read goal.
Mixed-effect read actions do not spuriously invalidate the evidence cache.

One evidence-repair opportunity is allowed inside the existing model-round
budget. An unresolved goal remains disclosed in decision metadata; there is
no unbounded self-correction loop or fabricated completion certificate.

## 8. Latency and user experience

- No separate semantic-classifier model call is added.
- No extra model call is required merely to record a compound outcome plan.
- Low-complexity semantic requests have three tool-capable rounds; other
  semantic requests have five. Existing terminal synthesis fallback can use
  one tool-free call when necessary. These are call limits, not promised
  wall-clock latency.
- One evidence repair is budgeted, not recursively repeated.
- Shortcuts and turn-local read reuse remain available.
- No automatic dose recomputation, screenshot, clinical search or patient
  data upload is added by this redesign.

A semantic-first question may need a read+answer pair where a correct legacy
prefetch required only an answer round. This is an explicit accuracy/latency
tradeoff; report actual p50/p95, provider calls and unnecessary work before
claiming the change is faster.

## 9. Verification and remaining limits

`tests/test_semantic_kernel.py` covers shared policy, schema-cache isolation,
extension admission, mixed-effect operations, malformed/incomplete outcome
plans, denials, independent siblings, pending receipts, mutation epochs and
both real provider loops using deterministic replay. This is infrastructure
verification, not a benchmark result for the configured language model.

The following require additional real-product evaluation:

1. Held-out natural expressions, corrections, ambiguous references, quoted
   logs, code-switching, interruptions and unfamiliar but supported requests.
2. Whether selected evidence actually contains the requested fields; a
   successful read is insufficient for dose/report equality or OAR completeness.
3. End-to-end browser acknowledgements, ownership/session/version fencing and
   UI result matching. The virtual plan does not replace those contracts.
4. Requests that existing clinical/UI authorizers cannot parse. Denial feedback
   improves recovery but does not magically authorize every paraphrase. A
   future broader write protocol needs server-owned, scoped, expiring and
   version-fenced confirmation, not model-only permission.
5. Actual semantic quality and latency for each configured provider/model.
6. The separate HTTP workspace-hydration heuristic in
   `web/routes/planning_routes.py::_chat_requires_full_workspace` still uses
   domain terms to decide whether decoded arrays are needed before a turn.
   It is a resource-readiness gate, not semantic authority, but can cause
   unnecessary waiting for an information-only question. This delivery does
   not replace it with unsafe metadata-only clinical execution. A future
   lazy-hydration redesign must preserve case/version fencing and validate
   actual array-dependent operations before making latency claims.

Do not turn the regression examples into a model-selection whitelist. Use
held-out scenario families and independently observed expected outcomes.
Score intent, target, authorization, necessary evidence, tool schedule and
terminal answer separately. Wrong-action rates must include negated,
hypothetical and quoted instructions. Compare legacy/semantic-first on the
same provider and frozen state, and measure latency and call count alongside
task completion. Source tests do not establish a clinical safety claim.

## 10. Delivery evidence

The final private current-source validation run reported:

```
2437 passed, 2 skipped, 31 warnings, 4 subtests passed in 48.30s
```

The new semantic contract file contributes 74 tests. The full run is the
product's top-level `tests/` suite, not all external benchmark experiments,
a live-provider accuracy test, real browser acceptance or GPU/clinical physics
validation. Existing review requirements and authorization tests remain intact.

Validation source: `/tmp/brachybot-monitor-closed-loop-stage-20261005-bj5hacbc`.
Its `semantic-regression-final.log` contains the final run output. The old date
in this private directory prefix comes from the reused staging utility; it
does not identify a previous source baseline or imply an old test run.
Read-only external model lookup roots and the bundled Node executable were
configured for existing contract tests; no live workspace was linked.

The selected-file before/after hashes and private backup path are recorded by
the guarded delivery manifest. At the last pre-delivery read-only observation,
LAN port 8080 was PID 1366011 at the LAN checkout and public port 18082 was
PID 1364997. No restart was performed by this work. Process state is a
point-in-time observation, not a persistent guarantee.

Only a verified process restart or subsequent runtime/version observation can
establish activation of new Python source in the running server. A successful
source overlay does not establish that activation.
