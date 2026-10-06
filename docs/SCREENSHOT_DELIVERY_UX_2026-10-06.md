# Screenshot delivery latency and presentation repair

Date: 2026-10-06 (Asia/Shanghai). Scope: LAN/debug BrachyBot only.
Baseline commit: `13f92dc06fd11b1e575f68b77c89031b99ca80fa`.

## Outcome and limits

Pure object-location requests with complete, current, persisted capture and
annotation receipts can finish without a second multimodal model call. The
remaining screenshot-analysis flow keeps its original visible turn clock
running until actual reply delivery, error, or cancellation. Completed images
remain visible while a compact, accessible status explains the remaining work.

This is a source/contract and synthetic-browser delivery. It is not a claim
that an authenticated real patient journey or current provider p50/p95 has been
measured, nor a promise that every screenshot request bypasses image analysis.
No service restart, paid provider call, patient planning, commit, push, or public
release modification is part of this change.

## Confirmed root causes

1. Required `locate` screenshots were deterministically annotated before
   display, but `_queueVisualAnalysisFollowUp` still queued a hidden model
   child for them. The current image and mark receipts already establish the
   bounded location facts eventually shown to the user. Repeated model work
   adds provider queue/inference latency without establishing new coordinates.
2. `finalizeThinkingChain` stopped the original trace timer when the parent SSE
   completed, despite the browser keeping its final-response step pending
   through capture, upload, and the hidden analysis child. The frozen clock
   represented the first server task, not visible turn completion.
3. Waiting images had no concise delivery-stage explanation next to the
   gallery. The generic final-response wait concealed the distinction between
   capture, evidence verification, and image interpretation.
4. Hidden children could re-enter annotation rendering after the same marks
   had already been persisted before display. Receipt-delivered replies now
   retain those immutable images and avoid redundant annotation uploads.

## Accuracy-first receipt delivery

The normal browser capture and annotation API remain unchanged. The hidden
continuation is still a cancellable, case-owned server task and retains its
existing durable transcript finalizer. A server-side response factory checks
whether it can answer purely from receipts before calling the Agent/model.

All of the following are required:

- The authenticated selected Session and parent request ID are exact matches.
- Exactly one persisted user request owns the trace and matches the submitted
  parent request; the existing request parser classifies it as a pure object
  location request, not a mixed, clinical, reporting, or explanatory request.
- Every completed tool in that trace is a locating `ui_screenshot` plan. The
  persisted safe plan retains semantic target identifiers.
- Every planned view is represented, no evidence was omitted, and attachment
  IDs are unique. Unknown/partial protocols fail closed to normal analysis.
- The evidence comes from the Session's persisted attachment registry or the
  owning message, not submitted target labels, coordinates, annotation flags,
  preliminary text, or case-state claims.
- Each image has persisted server-validated annotation marks bound to its
  source digest; both source and derived image SHA-256 hashes match the actual
  artifacts read through the Session artifact accessor.
- Planning ID and data generation exactly match current durable state. They
  are checked again after receipt verification. Unknown identity/generation
  never substitutes for a non-empty submitted value.
- Manifest visibility, in-view status, target semantics, mark references and
  loaded 3D presentation agree. Verified stale objects remain explicitly stale
  in the reply; a capture does not certify clinical validity or the latest
  regenerated guide.

The response uses the existing `grounded_location_answer` builder, in the
owning turn language. It can describe the verified Data Tree row/marked Viewer
object and recorded temporary visibility/camera restoration. It does not infer
anatomical diagnosis, pixel coordinates, dose quality, clinical approval, or
report completeness. No new natural-language keyword whitelist was added.

Ineligible requests continue through the existing multimodal analysis path.
Examples include dose interpretation, report verification, mixed requests,
missing images/marks, mismatched versions, unresolved custom/deictic targets,
and selections larger than the four-image visual envelope. The conservative
fallback preserves accuracy at the cost of potential provider latency.

## Visible delivery lifecycle

1. Capture begins: `Framing, marking and saving the images` (localized).
2. Images are ready: `Images ready · Checking the evidence`, with a short note
   that the user can already open the pictures. No fake percentage or ETA.
3. The parent's total elapsed time keeps advancing through the continuation.
   The trace cannot fold merely because an attachment or parent SSE exists.
4. Verified answer/failure/cancellation: the original final-response step
   becomes terminal, the original clock stops, and the temporary status is
   removed. A second clock, visible hidden-child turn, or duplicate final row
   is not created.

Status rendering is case/request bound and uses text nodes rather than HTML
interpolation. It uses a subdued surface, restrained typography, one small
activity dot, a polite live region, and reduced-motion support. A detached DOM
trace cleans up its interval. Terminal status removal does not create a blank
assistant bubble on unrelated ordinary turns.

The global UI locale and owning dialogue language retain their existing
separation: screenshot feedback follows its parent dialogue. A late language
toggle or another Session's turn cannot relabel the pending parent response.

## Changed files

| File | Change |
| --- | --- |
| `web/visual_location_delivery.py` | Conservative persisted receipt eligibility and integrity checks |
| `web/routes/planning_routes.py` | Case-scoped receipt response factory, generation recheck, semantic IDs in safe trace persistence |
| `web/chat_tasks.py` | Optional direct response factory before model streaming, shared cancellation/commit lifecycle |
| `web/app/static/js/brachybot-chat-core.js` | Original clock continues through pending delivery; terminal and detached cleanup |
| `web/app/static/js/brachybot-chat-todo.js` | Capture/checking status, original parent trace settlement, no duplicate annotation for receipt responses |
| `web/app/static/css/brachybot-chat-status.css` | Compact responsive status styling and reduced motion |
| `tests/test_screenshot_delivery_latency.py` | Positive/negative receipts, real worker, authenticated Flask route and durable response tests |
| `tests/chat_visual_delivery_clock.cjs` | Actual JS clock/finalization/cancellation regressions |
| `tests/test_screenshot_delivery_browser.py` | Actual DOM/CSS clock, status, locale, reduced-motion and narrow viewport checks |
| `tests/chat_turn_lifecycle.cjs` | New status dependency explicitly stubbed in the existing isolated cleanup fixture; assertions retained |

## Validation

Private current-source validation tree:
`/tmp/brachybot-monitor-closed-loop-stage-20261005-vfeyap3f`.
The helper name is inherited; this is the current 2026-10-06 overlay.

- Targeted six-file Python/real-browser suite: **216 passed**, 3 existing SWIG
  warnings, 8.65 s. Log: `screenshot-ux-targeted.log`.
- Three standalone Node checks passed: `chat_screenshot_delivery.cjs`,
  `chat_turn_lifecycle.cjs`, `chat_visual_delivery_clock.cjs`.
- Full top-level product `tests/`: **2523 passed, 2 skipped, 31 existing
  warnings, 4 subtests passed**, 61.00 s. Log: `screenshot-ux-full.log` in the
  same private validation tree. This is not the separate benchmark/cohort
  experimental suite and does not involve real provider/patient planning.
- Real `/api/chat` tests verify zero model calls only for complete eligible
  receipts; changed versions and mixed questions still invoke normal analysis.
- Negative controls cover other Session/request, changed question, missing
  trace/annotation/image, source/derived hash changes, partial/duplicate/omitted
  evidence, other tools, failed tools, hidden/unloaded 3D objects, wrong target
  semantics, mismatched marks and planning generations.
- Browser evidence uses synthetic placeholders, not patient images or the
  authenticated live UI. `screenshot-ux-component.png` is a presentation/DOM
  check only. The complete live page, real capture/annotation uploads and
  provider-dependent latency still need idle-service acceptance after reload.

Test environment: existing Python environment
`/home/lht/.conda/envs/brachytherapy/bin/python`; existing VS Code Node runtime
on PATH; `BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan` for read-only bundled
model catalog resolution in the temporary tree; existing Chromium explicitly
selected through `SCREENSHOT_UX_CHROME`. No dependency/model installation.

## Activation and live acceptance

Reload backend source during an idle LAN service window, then refresh frontend
assets. Do not restart the independent public-release service or interrupt an
active planning/Monitor/chat task. The source delivery is not a service reload.

After reload, use de-identified held-out requests to measure capture-ready,
annotation-ready, evidence-verification, model queue/inference (when needed),
durable final reply and total user-visible latency. Report p50/p95 separately
for warm/cold and receipt/analysis paths. Check simple location, multiple
objects, intentionally hidden guide/CTV, stale guide, mixed location+dose+
report, cancellation, Session switching/replay and a geometry edit during
verification. A zero-call synthetic contract result is not a real-provider
speedup measurement.
