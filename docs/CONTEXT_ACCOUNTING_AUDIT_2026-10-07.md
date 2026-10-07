# Context Accounting and Manual Compression Audit

## Scope and baseline

This repair targets the LAN checkout at `/home/lht/snap/brachyplan/BrachyBot`,
HEAD `e20289fc23e8d8d087222c27ded6ee01d105641d`. The existing, uncommitted
intent-chain changes are part of the baseline and must remain intact. No
public-release checkout, case resources, provider credentials, or clinical
planning data are changed. No provider request is needed for validation.

## Interpretation of the reported conversation

The reported numbers are:

| Quantity | Reported value | Interpretation |
| --- | ---: | --- |
| Turn input | 116,020 | Input accumulated across dialogue-model requests |
| Turn output | 2,626 | Output accumulated across those requests |
| Turn total | 118,646 | 116,020 + 2,626 |
| Context | 31,139 | Old runtime preferred the FIRST measured prompt of the turn |
| Tools | 14 | Tool executions, not necessarily 14 model requests |

Accumulated input re-counts overlapping system, tools, history and evidence
each time a request is sent. It is not the number of distinct tokens occupying
one context window. Thus a large accumulated input and a much smaller context
are not inherently contradictory. The last request cannot be reconstructed
from these aggregate values alone.
The old algorithm explains a possible source of the displayed context value;
the pasted transcript alone does not prove which individual provider request
produced 31,139, nor does it recover the last request's usage.

Long conversations do not necessarily fill a large window. The existing
runtime deliberately selects relevant history through SmartContext, uses
the last 12 messages as its fallback, and folds history once the internal
conversation exceeds 12 messages, retaining six recent messages. Old messages
are reduced to extractive excerpts and a bounded summary. Tool evidence in
later rounds is also bounded. Internal messages include tool receipts, so
12 messages does NOT mean 12 human questions. A low percentage does not prove
that the complete original history remains available to the model. This
repair does not silently replace that history-selection policy.

If the configured window is 1,048,576 tokens, 31,139 represents approximately
2.97%. Whether that window is truly supported by a deployed provider remains
a provider configuration concern; the UI is not an independent capability
probe. Unknown models use a clearly bounded registry/default estimate.

## Verified defects and repairs

1. **First-call value mislabeled current.** `_durable_context_tokens` preferred
   the first prompt regardless of later, larger requests. That input did not
   prove the durable next prompt either. The new snapshot records the latest
   request's input plus reported output, with input/output separately exposed.
   Decreases after context selection or compression are permitted, not hidden
   by enforcing artificial monotonic growth. A separate turn peak is available.
2. **Separate token ledgers disagreed.** Main tool loops, lightweight chat,
   grounded reads and synthesis fallbacks did not all feed the same status
   ledger. Recording is now shared, starts at the human/worker turn boundary,
   and does not reset when a grounded read falls through to tool execution.
   Final synchronous and SSE metadata are projected from this ledger.
3. **Missing usage confused with zero.** Normalization keeps availability
   flags. Invalid/negative/non-finite counts are unavailable. Missing input
   uses the current request estimate rather than an earlier measured prompt.
   Turn usage with missing measurements is labeled a reported lower bound.
   A usage-less fallback still carries its actual provider/window identity,
   clears the previous measured input, and applies that window's budget.
4. **Anthropic stream lost input.** Input arrives in `message_start`; later
   `message_delta` commonly reports output only. The provider now merges
   cumulative snapshots instead of replacing or summing them. Cache creation
   and cache read input are included once in the prompt. Reasoning/cached
   detail subsets are never added again to their parent totals.
5. **Model/route identity mismatch.** The runtime used the router's default
   rather than the selected general route for its budget. Usage now carries
   the actual provider/model/configured window, including a successful
   fallback. A recorded snapshot uses that request's window denominator.
6. **Estimator feedback bias.** Calibration used an already-calibrated
   estimate as its denominator. It now uses the raw canonical estimate;
   repeated measurements converge to the observed scale. The portable packer
   delegates message overhead, tool arguments and image detail accounting to
   the same estimator. Small configured windows are not enlarged to 8,192.
7. **UI inconsistencies.** The ring calculates its percentage from the same
   numerator/denominator as the footer, labels estimates, distinguishes usage
   from accumulated consumption, accepts the final SSE snapshot immediately,
   rejects older status responses, and refreshes explanatory text with the
   global UI language. Over-window ratios are not hidden as exactly 100%.
   Historical v1 footers are identified as legacy; they are not retrospectively
   fabricated as latest-request measurements.
8. **Compression control defects.** A confirmation implementation already
   existed in source, but awaited the status endpoint before showing itself.
   It also captured language too early, allowed duplicate dialogs, did not
   bind the eventual POST to the confirmed case, leaked key listeners, and
   lacked a server-side chat/cleanup barrier. These are repaired below.

## Canonical contract (accounting_version = 2)

| Field | Contract |
| --- | --- |
| `used_tokens` | Latest request input + reported output; otherwise explicitly estimated |
| `scope` | `latest_request`, `request_estimate`, or `retained_context_estimate` |
| `source` | Provider usage, pending request estimate, or retained-history estimate |
| `window` | Window associated with the actual measured provider request or current estimator |
| `ratio` | `used_tokens / window`; never the accumulated input divided by window |
| `input_tokens`, `output_tokens` | Latest request's reported components, when available |
| `context_complete` | Whether both latest-call components were reported |
| `turn_input_tokens` | Sum of reported input for completed dialogue-model calls in the turn |
| `turn_output_tokens` | Sum of reported output for those calls |
| `turn_total_tokens` | Sum of canonical per-call totals |
| `missing_usage_calls` | Calls for which complete usage was unavailable |
| `llm_calls` | Completed provider requests recorded by dialogue orchestration, not tool count |
| `turn_peak_context_tokens` | Largest recorded per-request occupancy this turn |
| `components` | Estimated INPUT decomposition, not a measured decomposition of input + output |
| `reserve_output_tokens` | Budget reservation, not tokens already consumed |
| `history_policy` | Existing relevance/age-compaction policy, made explicit |
| `observed_at_ms` | Snapshot ordering fence for delayed status responses |

The per-call total is input + output when both are reported, even if a
provider's total field is inconsistent. A total-only response is retained as
incomplete; input is not inferred from it. Output may include provider-reported
reasoning. Cache input contributes to context and token counts, but may have
different pricing. These counts are NOT monetary billing calculations.

Transport failures without returned usage cannot be billed exactly. Nested
tools or independently hosted agents that do not expose their own model usage
are outside the dialogue ledger; no unreported cost is invented. The wording
does not claim an account-wide, lifetime, or vendor invoice total.

## Manual compression interaction

1. Clicking the ring or entering the exact compression command opens the
   confirmation immediately. The status GET is asynchronous and bounded to
   five seconds; waiting for statistics never authorizes compression.
2. The global `rp-modal-overlay`/`rp-modal-dialog`, theme variables and button
   classes are reused. Both Chinese and English follow `effectiveUiLanguage`,
   including changes made while the dialog is open.
3. Initial focus is Cancel. Tab stays inside; Escape, the close button,
   Cancel, and clicking outside all settle false. Focus is restored. Listeners
   are removed. Multiple clicks share one pending confirmation operation.
4. Updating status or language preserves the actual button DOM and focus,
   avoiding interrupted pointer/keyboard interactions.
5. Only Yes sends a POST, with `confirmed: true` and the captured case header.
   Changing cases before Yes prevents the POST; responses after a later
   switch do not update another case's indicator or transcript.
6. The endpoint rejects absent/false/string confirmations. Compression is
   serialized against chat admission. Running and cancelled-but-unwinding
   workers block it with HTTP 409, preventing snapshot cleanup from undoing
   compression.
7. Compression invalidates the old provider measurement, estimates remaining
   context, and does NOT erase the completed turn's cumulative token ledger.
   Case data/plan/report are not edited. Older dialogue details may be lost
   from the prompt; the dialog says so rather than promising verbatim history.
8. A checkpoint is flushed. If persistence fails, the UI explicitly reports
   in-memory-only compression; a successful HTTP response is not presented as
   a durable save when `persisted` is false.

## Validation and limitations

Validation uses a private copy of current source, including the earlier dirty
intent fixes, and synthetic credentials/provider responses/workspaces only.
The real Chromium tests load the actual product control source and stylesheet,
not a replacement modal. They intercept all network calls and never touch a
patient case or compress a user's real conversation.

The first expanded pass exposed compatibility regressions in adapters that
override usage recording as a void method and instantiate only the workflow
mixin. Recording and normalization were decoupled and optional mixin boundaries
preserved. A test expecting rejected synthesis to consume zero calls was
corrected: rejected content still consumed a provider request. The existing
frontend style-cache assertion was updated to the new cache version.

One validation pass incorrectly set `BRACHYBOT_DEPLOY_ROOT` to the private
checkout rather than the deployment parent containing the supplied cascade
models. Two existing model-availability tests failed. The correct deployment
parent was restored without changing those tests or running inference.

### Final validation (2026-10-07)

- Current product/test overlay: `pytest tests/ -q -ra` produced **2,658 passed,
  2 skipped, 4 subtests passed**, in 71.68 seconds. The 31 warnings are existing
  SWIG and `datetime.utcnow()` deprecations. The log is
  `/tmp/context-accounting-verified-tests-20261007.log`.
- The two skipped checks require the public-deployment dependency set and
  `NGINX_TEST_BINARY`, respectively. They are not passed deployment checks.
- Nine changed Python modules compile; three changed JavaScript files pass
  `node --check`.
- Eight real Chromium tests exercise immediate confirmation, Cancel/Escape,
  single Yes submission, case switching, global language updates, keyboard
  focus, delayed status ordering, and partial usage labels. Synthetic modal
  images were captured only after the shared CSS opening transition settled
  and visually checked in Chinese and English. These are isolated controls,
  not screenshots of a real patient's application.
- Provider tests include cached Anthropic input, output-only stream snapshots,
  latest-request versus turn-sum arithmetic, missing usage, selected/fallback
  windows, calibration convergence, manual compaction ledger retention, and
  the real Flask confirmation/active-worker endpoint barrier.

### Delivery and activation

Selected files are delivered with baseline and payload SHA-256 checks and a
private, recoverable backup. Existing dirty files outside this overlay remain
untouched; the earlier intent fixes in overlapping files are retained. No
commit, push, live provider call, real-case compression, or service restart
is part of this delivery. Cache versions are updated for the changed frontend
assets, but the existing LAN Python process must be restarted in a safe window
before it loads the new backend accounting. A frontend refresh alone is not
proof that the new Python implementation is active. The public-release
checkout and process are outside scope.

No real provider latency, model capability, token invoice, clinical/GPU, or
public-release end-to-end claim follows from these tests.
