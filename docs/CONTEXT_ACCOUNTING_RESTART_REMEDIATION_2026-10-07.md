# Context and token accounting restart remediation — 2026-10-07

## Scope and evidence

Canonical checkout: `/home/lht/snap/brachyplan/BrachyBot`.
Inspected HEAD: `43e030171a2d6bfd16dca4ed964ef47122c8327e`.
Existing Input/Viewers control fixes were retained as the baseline, not reset.
The independent public-release checkout and service were not modified.
The earlier `docs/CONTEXT_ACCOUNTING_AUDIT_2026-10-07.md` is preserved unchanged;
this report records the subsequent restart/durability remediation.

The reported symptom is a context ring decreasing from 4% to 3% after another
question, then to 1% after a server restart, without explicit compression.
This audit examined request packing, provider usage normalization, runtime
accounting, durable workspace restoration, SSE, polling, footers and the
compression controls. It did not inspect patient content or call a paid model.

The code defects below are reproducible with synthetic conversations. A
screenshot alone cannot establish the exact prompts or compaction event that
produced the historical 4% and 3% readings; that specific causal attribution
would require contemporaneous call records. The restart basis-switch defect
and the unconditional age-based folding path were directly verified in code.

## Confirmed root causes

1. `_ctx_current`, model-window/calibration metadata and turn counters lived
   only on the process-local agent. `WorkspaceStore` saved conversation and
   summaries but not this accounting state. On restart, `context_status()`
   fell back to a different retained-history estimate, initially without the
   known system/tool/runtime overhead or calibrated estimator.
2. Both provider execution paths automatically folded conversations after
   more than 12 messages, keeping only the latest 6. This policy did not depend
   on token volume or the selected model's window. Thus “I did not compress”
   did not mean the software had not automatically folded history.
3. The ring was presented as current/global context but normally measured the
   latest **single** provider request, whereas input/output footers accumulated
   multiple calls. Request-dependent history selection and temporary tool
   results can make the latest request smaller even without any compression.
4. Polling only rejected older observations when the incoming observation
   timestamp was positive. An unmeasured cold snapshot could overwrite a newer
   measured one. A turn start also changed the observation timestamp even
   though no new context measurement had occurred.
5. Completing an answer does not imply its heavy Agent checkpoint has finished.
   Sending numeric accounting through the same debounced CT/plan checkpoint
   leaves a restart window. A metadata-only write is needed independently of
   clinical array serialization and background resource hydration.

## Accounting contract, version 3

| Quantity | Definition | Can decrease? |
|---|---|---|
| Latest request occupancy | Latest provider input + reported output, divided by that request's model window | Yes, for a genuinely smaller new request |
| Per-turn consumption | Sum of normalized input/output usage from recorded model calls in that human turn | No within a turn; resets at a new human turn |
| Recorded session consumption | Sum of recorded usage since this accounting epoch started | Not during ordinary requests, compression or restart |
| Retained conversation estimate | Estimated stored conversation + summary, excluding system, schemas and case facts | Yes, after explicit or pressure-triggered folding |
| Pending request estimate | Estimated actual packed request when provider input usage is unavailable | Approximate; explicitly marked as estimated |

For complete provider measurements:

```text
request_context_tokens = prompt_tokens + completion_tokens
request_context_ratio  = request_context_tokens / actual_request_window
turn_tokens            = sum(normalized_call_total for recorded calls in the turn)
session_tokens         = sum(normalized_call_total for recorded calls in the epoch)
```

These are not interchangeable. For example, 118,646 turn tokens consisting of
116,020 input and 2,626 output across repeated requests do not mean 118,646 new
tokens have been permanently appended to conversation memory. Repeated input
is consumed again on each call. The existing canonical normalization retains
Anthropic cache-read/cache-creation accounting and merges streaming snapshots
before recording a completed call; the repair does not add cache totals twice.

If a provider omits usage, the request is estimated and consumption is a
reported lower bound, not a fabricated measured zero. Invalid or nonfinite
durable values cannot restore a measured zero. A conflicting reported total
does not replace input + output when both are available.

The denominator belongs to the actual request route. Restoring a fallback
request does not relabel it with the default model's larger window. Estimator
calibration is reused only for an identical model/window/tuning signature.
Unreported route identity does not reuse a previous fallback model's window.
Configured windows are configuration/registry facts, not a probe of the
upstream provider's implementation; a misconfigured window still needs a
configuration correction.

## Implementation

- `agent_runtime/context_accounting.py` defines a numeric-only, whitelisted
  ledger, finite counters, bounded identities, epochs, revisions, explicit
  clear tombstones and freshness comparisons. No prompt, image, PHI payload,
  tool result or credential is copied into the ledger.
- `AgentMemory.context_accounting` belongs to the durable control plane.
  Conversation revisions invalidate a cached retained-history estimate.
- `LLMRuntimeMixin` restores the ledger before use, records a call once,
  separates request/turn/session values, persists calibration, and serializes
  numeric updates against status polling with a short reentrant lock. No
  network/model execution occurs under that lock.
- Automatic durable folding now depends on the calibrated retained token
  estimate plus known overhead reaching the same model-window trigger used
  for request budgeting. Merely crossing 12 messages no longer folds history.
  Exact packed requests retain their separate budget/compression guard.
- Relevant-history selection remains enabled. Stored history and history
  actually selected for a request are deliberately different measurements.
  This change does not send an entire large transcript on every call.
- A visual analysis child with a matching parent request ID contributes to
  its human parent's turn ledger. Unrelated parents cannot merge bills.
  Numeric child consumption is checkpointed after restoring parent memory,
  including cancellation, without persisting its ephemeral image prompt.
- `WorkspaceStore.context_token_accounting` is a small SQLite table: one
  bounded (maximum 16 KiB) ledger per account-owned case, with foreign keys
  and explicit ownership checks. Its synchronous atomic transaction does not
  serialize CT, dose or meshes, wait for an Agent snapshot, or bump the case's
  editing revision. Stale same-epoch revisions and older epoch writes are
  rejected. Account/case deletion cascades remove the record.
- `_persist_agent_change` commits these numeric events even while clinical
  arrays are hydrating, then returns without scheduling a heavy checkpoint.
  Existing conversation/clinical persistence behavior remains separate.
- Full Agent snapshots also include the ledger for compatibility/portability.
  Fresh metadata hydration selects the newer compact ledger or snapshot.
  A later array hydration pass does not replace live accounting. A clear
  tombstone prevents an older heavy snapshot from resurrecting cleared history.
- The UI uses server counts, not an inconsistent supplied percentage; shows
  one decimal when useful; labels measured/estimated/lower-bound values;
  explains smaller new requests; exposes retained history and session totals;
  and marks restored measurements as restored, not re-estimated.
- Case identity, ledger epoch/revision and observation timestamps fence late
  polling/SSE updates. A case-shell switch clears another case's ring while
  waiting for its own status. The footer recognizes accounting version 3.
- The existing compression confirmation dialog, focus handling and global
  Chinese/English behavior are preserved. It explains that compression
  changes retained context, not already consumed tokens. Script cache versions
  were incremented without modifying unrelated control fixes.

## Validation

Synthetic-only validation in an isolated checkout; no GPU inference, patient
planning, destructive deployment action or paid provider call was performed.

- Initial focused existing tests: **95 passed**.
- Expanded focused atomic-accounting and checkpoint tests: **166 passed**.
- Final full-suite result: **2,826 passed, 2 skipped, 4 subtests passed**
  in 114.87 seconds; 31 existing deprecation warnings.
- Python compilation and all three changed JavaScript syntax checks passed.
  Selected-file byte hashes and diff checks are verified at checked delivery.

The first broad run without the Node runtime on PATH reported one environment
failure (`test_monitor_global_locale_runtime_counterexamples`) and 11 skips.
No assertion was relaxed. The run with the bundled Node runtime passed
**2,822 tests, 2 skips, 4 subtests** before the final compact-ledger addition;
the final source was subsequently re-run, rather than reusing that result.

New counterexamples cover actual SQLite/disk reopening, metadata-first
hydration, stale full checkpoints, background array hydration, legitimate
decreases, low-volume long conversations, actual token pressure, model changes,
missing usage, explicit clears, stale revision/epoch writes, account ownership,
visual children/cancellation, concurrent polling, estimated-value caching,
case switches, Chromium rendering, localization and footer consistency.

A synthetic 100-commit microcheck of the isolated SQLite metadata path measured
5.652 ms median, 6.711 ms p95 and 17.0 ms maximum per commit on this host. This
measures the small ledger write only, not production end-to-end response
latency. No additional model calls are introduced. Idle status queries reuse
the retained-history estimate and do not schedule writes.

## Activation and limits

- The implementation is in the canonical LAN checkout. Loading Python
  changes requires restarting that LAN process; frontend assets require a
  browser reload. The public-release service is independent.
- No live deployment restart is included in this audit. Tests of persistence
  use the real workspace implementation with synthetic temporary databases,
  not a restart of the user's running patient workspace.
- Old sessions without a saved ledger remain explicitly estimated until a
  new request supplies usage. Past usage is not inferred from message length,
  historical percentages or invented call records. Session totals clearly
  state that their coverage begins with the new accounting epoch.
- Explicit conversation clear starts a new epoch. Ordinary compression and
  server restart do not reset recorded consumption.
- A completed provider response whose numeric transaction has committed is
  durable independently of heavy checkpoints. This is not a claim to recover
  provider usage that was never returned, or to guarantee persistence after
  storage failure. Interrupted calls without returned usage remain unknown.
- Retained/pending token estimates are not exact upstream tokenizer counts.
  The measured request is authoritative when available. The ring is not
  forced to increase monotonically or pinned to a historical maximum.
- Preserving a saved measurement is not a promise that the next rebuilt
  prompt is identical. Relevance selection, current tools/facts and provider
  routing may change that next request; its new measured value is published.

## Suggested acceptance sequence

1. When idle, load the changes in the LAN server and refresh the browser.
2. Complete one new turn; record the ring numerator/window/source/revision and
   session total from `/api/chat/context` for that authenticated case.
3. Restart the LAN server without compressing. Select the same case. Its
   latest saved measurement must retain the numerator, window and source.
4. Ask a short follow-up. Its latest request may be smaller, but session
   consumption must increase and the tooltip must explain the different basis.
5. Switch to another case and back. Neither case may display the other's ledger.
6. Click compression and cancel: no mutation. Confirm while idle: retained
   context changes, accumulated consumption does not. Reopen the case and
   verify both values retain their respective scopes.
