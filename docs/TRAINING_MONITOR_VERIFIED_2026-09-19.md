# Planning Monitor: verified audit and implementation

Reviewed 2026-09-19 against the internal BrachyBot working tree at `fdc64cbb0`, including its existing uncommitted changes. The original analysis is retained unchanged as review input. This file records the implemented outcome rather than treating the proposed roadmap as validated requirements.

## Findings and disposition

| Original finding | Verification and action |
|---|---|
| S1-1: duplicate engines | Confirmed. Removed the original and shadow generations; the six presentation/feedback helpers now have one implementation in `web/monitor_engine.py`, re-exported by `web/server_support.py`. Unrelated readiness and geometry helpers remain in support. |
| S1-2: mismatched run append/liveness | Confirmed. Browser telemetry must match the active run before it can enter training history or refresh its activity. Backend mutation events are tagged with the active run at their commit boundary. Stale leases are normalized when the bucket is read. |
| S1-3: unbounded history | Confirmed. `BRACHYBOT_MONITOR_MAX_EVENTS` defaults to 1000 retained details. Full-run `event_counts` and `dropped_event_count` survive trimming; summaries disclose the retained window. |
| S1-4 / S2-6: close durability | Confirmed. All lease closes use the same summary-building helper. Shutdown flushes known case-owned bridges, including already-stopped runs with pending summaries. Eviction flushes a detached bridge asynchronously; a newer live bridge supersedes that old save. Sidecar writers serialize close against pending writes. |
| S1-5: incomplete Chinese | Confirmed. Added guide restore/unavailable/failure, loading, hotspot, seed-interference aggregate, and dose-summary translations. Added generated-message regression cases. |
| S1-6: client attestation | Confirmed, with a stronger issue than merely missing fields: a client could supply a fabricated committed event. Mutation-side append now owns commit status and a unique event ID. Browser replays resolve that ID against this case's server history; unknown records fail explicitly and repeated feedback is deduplicated. Ordinary client manual telemetry is unverified and excluded from training counts. |
| S2-1: event scope | Confirmed. Advice uses the active run's window; stop passes its captured run window explicitly, including an empty run. |
| S2-2 / S2-3 | Confirmed. Blank IDs become generated IDs; length/control characters are checked. Stale stop requests report that a different run is active without echoing that run's record. |
| S2-4 / S2-5 | Confirmed. Orderly stop records a non-counted lifecycle event; restore/error activity labels added. Raw feedback is English; localized feedback follows the requested language. |
| S2-7 / S2-8 | Confirmed. Readiness derives from all blockers. Inspector reads live viewer/overlay state; absent state remains unknown instead of inventing vertical layout and disabled overlays. |
| S2-9 | Confirmed. Training/manual actions have Chinese descriptions; new descriptions say requested because the frontend still needs to execute them. |
| S3-1 / S3-2 | Separate download/controller and structured evidence paths exist. Their removal changes caller behavior and is not needed to fix monitor correctness; retained. The phase field is retained for record compatibility. Shared unauthenticated debug fallback remains a separate authentication contract. |
| S3-3 | The unused performance tracker is not evidence of an available validated competency system. It was not registered or removed as part of this repair. |
| S3-4 / S4-1 / S4-2 | Confirmed. Monitor plans send schema 5. Capture success alone starts the cooldown, pending captures are deduplicated, repeated failures are visible, hidden tabs skip monitoring capture, and frame waits reject after 8 seconds. Next checkpoints can retry failed captures immediately. |
| S4-3 / S4-4 | Confirmed. Dose/DVH checkpoints no longer inherit unrelated seed close-up focus. Explicit planning/segmentation error events produce feedback. The original assertion that the step error branch was unreachable was too broad: a `.step` event can already carry error status. |
| Timestamp suspicion | Confirmed by counterexample: old event time 10 flushed at 30 displaced snapshot event time 20. Prefer comparable `updated_at`, with `saved_at` only for legacy records lacking it. |
| Invalid ui_state / cold advice | Confirmed. Start/stop/advice now guard non-object UI state; cold advice returns explicit loading status rather than HTTP 500. |
| Expensive event checks | Confirmed. Ordinary clicks/sliders do not scan geometry; one manual event shares a snapshot between feedback and capture selection, with volume obstacle scans deferred to detailed advice. No cross-version clinical cache was added, avoiding stale geometric findings. |
| Documentation references | `docs/ARCHITECTURE.md` has been superseded by `ARCHITECTURE_AND_MAINTENANCE.md`. Links were added there and in the full specification. Public-tree equivalence was not assumed or used as a deployment target. |

## Runtime contract

The monitor observes a case; it does not authorize or execute treatment changes. Deterministic advice continues to work without an LLM. The optional free-text advice answerer can still call the agent's natural-language path, so the entire advice endpoint is not unconditionally LLM-independent.

Start creates a case-owned run. Same-ID retries succeed; a different live ID conflicts. Browser events require an exact matching run. Geometry mutation events are authoritative only at server commit. Read/append normalizes expired leases. Stop, restore, eviction and shutdown all leave an inactive record with a summary envelope. A refresh does not silently resume an old subscription.

Storage is bounded: 500 global events by default, 1000 run details, 100 feedback messages, 1000 replay IDs. Record schema version 2 adds `event_counts` and `dropped_event_count`; legacy records derive counts from available details. Truncation does not claim a complete raw audit trail. Event dictionaries include `event_id` and `monitor_run_id`.

`GET /api/training/timeline` exports JSON for the selected authenticated case with run identity, retained events, complete accumulated counts, dropped count, and summary. It uses the same selected-case ownership as existing monitor routes and never accepts a caller-supplied patient path. This implements a lightweight part of the proposed audit-export improvement without adding a second live panel.

Frontend monitoring capture is case/run fenced, skips hidden tabs, has one pending capture, and only consumes its ordinary 45-second throttle after successful image attachment. Stage/dose checkpoints retain their existing throttle bypass. Failures preserve the ability to capture at the next checkpoint; the second consecutive failure emits a localized notice. Frame timeout is an explicit failure, not fabricated render readiness.

## Suggestions accepted and deferred

Accepted: one deterministic engine, bounded/versioned records, full-run counters, behavioral route tests, localization coverage, event-path scan reduction, robust capture failure behavior, and case-owned timeline export.

Deferred: per-site rubrics, competency grades, quiz grading, cold-spot seed proposals and multi-user supervisor review. The report supplies no confirmed site-specific grading rules or validation dataset proving a positive effect. Registering the orphaned score tool would expose unvalidated scoring. A new HUD, coaching presets and automatic reload-resume also require product behavior choices and browser integration evaluation; none is necessary to preserve existing monitor functionality.

No model weights, Python packages, clinical thresholds or unrelated backup files were changed. The public release tree was not modified. Python source deployment requires a server restart; existing browser pages require refresh for JS changes.

## Validation

The final targeted Python regression suite passed 362 tests (monitor lifecycle/audit, manual seed transactions, UI sidecar persistence, runtime contracts, workspace frontend and screenshot trace integration). Node syntax and monitor-capture behavior checks passed; `git diff --check` passed. The existing SWIG and `datetime.utcnow` deprecation warnings remain unrelated.

Behavioral tests cover same-run replay/different-run conflict, stale and mismatched events, malformed state, forged/replayed commits, bounded history/full counts, shutdown sidecar summary, cold advice, event-clock ordering, multi-case isolation, real viewer state, translations and timeline export.

`tests/monitor-capture.test.cjs` executes the actual browser functions in a mocked event loop to check burst deduplication, failure retry availability, success-only cooldown, repeated failure notice, hidden-tab behavior and bounded render-frame waiting. It can run with Node and the path to `web/app/static/js/brachybot-ui-api.js`.

These are code-level and simulated-browser checks. A real GPU/browser live monitor run, pixel-level screenshot quality and clinical threshold validity are not established by them.

## Follow-up audit on the seven additional findings

All seven findings were confirmed against the same remote tree and corrected:

1. `captureFailures` now resets both when a run starts and when local monitor state is cleared, so failure notices are independent per run.
2. `/api/ui/event` returns a bounded status projection (phase, run ID, counts and timestamps), never the retained event bodies, feedback messages, or replay-ID fence. Timeline export remains the explicit history path.
3. Read-time stale closure emits a `training.stop` lifecycle event and schedules the authenticated case sidecar checkpoint. Read-only advice/state paths now persist the inactive summary without waiting for an unrelated future interaction.
4. The deterministic feedback generator now runs once and returns its English source and localized presentation from that single result. Added localized forms for every emitted feedback family used by this response path.
5. The six confirmed stale `agent_runtime` patch artifacts are ignored by exact path in `.gitignore`: four `.orig` files and two `.rej` files. They remain available on disk for recovery; other `.orig` files outside this reported set are untouched.
6. Equal event timestamps no longer automatically allow a different live bridge to be overwritten. An identical same-clock snapshot may still flush, preserving orderly shutdown persistence.
7. `/api/ui/capabilities` advertises the timeline endpoint, JSON format, and retention bound; the README's training-monitor entry documents the export.

The expanded follow-up regression suite covers compact responses, read-time sidecar persistence, one-pass feedback localization, equal-clock write behavior and all earlier lifecycle cases. The broader non-monitor failures reported by the user are outside these seven fixes and were not used to characterize monitor regressions.
