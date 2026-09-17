# Whole-request routing audit and acceptance boundary

## Scope and findings

Audited plain, traced and streaming chat entrypoints, local candidate routing,
execution grants/action plans, legacy direct tool detection, provider context,
tool normalization, resource delivery and current-case grounded-answer paths.
This extends the earlier report read/clear fix.

1. Legacy lexical routing can propose Viewer display from three topic words.
2. Planning dependencies can carry execution grants even with direct_execution
   false. Testing that boolean alone does not prevent unintended execution.
3. The legacy tool detector can be called independently of the chat policy.
4. Raw-text overwrite detection and current-dose normalization can revive an
   action downstream. The latter could fabricate a dose call for an empty list
   or replace an unrelated query call.
5. Partial small-talk matches can suppress another action in the same message.
6. Topic-based tool filtering can unnecessarily hide UI/context inspection.

## Implemented design

Legacy detectors now propose a candidate. Public classify_local_turn applies a
shared whole-request acceptance contract before preserving direct execution,
execution grants, workflow grants or an action plan. Rejection removes all four
and uses the existing primary semantic model, not an additional remote router.
Exact registered/canonical commands remain fast. Unknown expressions are not
rejected as unsupported: they go to semantic interpretation with original text.

The explicit grammars are intentionally incomplete. They recognize complete
commands, not arbitrary sentences containing matching nouns. Capability catalog
labels are escaped and require complete interaction syntax. Unsupported syntax
abstains instead of guessing. Existing context-backed segmentation continuation,
focused reconstruction, DVH recomputation, screenshots and planning dependencies
were kept through regression tests, without relaxing existing assertions.

The independent direct detector uses the same acceptance policy, with explicit
legacy contracts for bounded segmentation commands and persisted clarification.
Overwrite inference no longer uses unrestricted substring search. Current-dose
normalization requires an accepted dose request and an existing related call;
it does not invent a call or replace unrelated inspection.

Primary model instructions are shared at the ordinary/streaming context packing
entrypoint. They preserve operation, object, scope, negation, conditions, order,
references and all requested actions, and prohibit completion claims without
evidence. Input messages are copied, not mutated. No extra inference request is
added. Existing clinical validators and destructive confirmation remain intact.

Routing logs record candidate, selected intent, acceptance source, rejection
reason and direct-execution state, without logging raw patient requests.

## Verification

Combined regression: 317 passed, 3 SWIG dependency deprecation warnings. Includes
whole-request adversarial tests, prior report boundary tests, semantic grants,
runtime contracts, screenshot routing, segmentation overrides, dose recomputation,
uploaded masks, round7, lightweight streaming, presentation and planning delivery.
git diff --check passed for modified production files.

Additional review_round6 regression: 81 passed, 1 failed at the CTV legacy alias
mapping assertion. The failing test was rerun with all five modified existing
modules loaded from their pre-change backups in an isolated Python process;
the same assertion failed. Production files were not rolled back for this check.
Combined coverage is 398 passed and one confirmed pre-existing failure.

Remote local-only microbenchmark: 1,000 decisions across five sample expressions
took 0.1747 seconds, excluding Python imports and model/tool/browser work. This
is not an end-to-end latency guarantee or accuracy measurement.

## Remaining boundaries and deployment

No claim of perfect language understanding or elimination of every legacy
lexical helper. Current-case read routes still select evidence families locally,
then use the existing grounded model answer and scope checks. Some specialist
normalizers still use bounded domain interpretation; model behavior and broad
clinical end-to-end accuracy need a larger labeled corpus and live evaluation.

Unfamiliar command phrasing may require a primary-model call where an older
heuristic skipped it. Exact commands retain shortcuts; correctness takes priority
over an incorrect immediate acknowledgement. Provider latency remains external.

Changes were merged into the current remote dirty worktree with original-file
hash/cmp checks, preserving unrelated changes. No service restart, commit or push
was performed. Backend processes must be reloaded/restarted to use the changes.
No real patient data was deleted or planning run started for verification.
