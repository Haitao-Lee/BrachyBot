# BrachyBot browser interaction performance: root causes and verification

Date: 2026-10-14. Scope: browser-side report zoom/split, presentation persistence, and hidden Viewer scheduling. This is a scoped performance patch, not a replacement or re-certification of the complete multi-timepoint clinical implementation.

## Findings and implemented corrections

Server-side inference does not remove browser-side JavaScript, DOM layout, image decoding, rendering, JSON parsing, or state copying. The following production code paths caused unnecessary work on the browser's main thread:

1. **Every report zoom/split refresh repeated physical A4 pagination.** `web/app/static/js/brachybot-report-shell.js` preview refresh called the paginator; `brachybot-report-export.js` repeatedly cloned report sections and performed trial layout measurements. Cache completed pagination and physical paper geometry. Zoom and available panel width change only preview transforms. Content replacement, loaded fonts, changed text-flow image dimensions, or genuine paper-size changes invalidate the cache. Hidden reports retry after becoming measurable. Printing retains physical A4 dimensions and original figures.
2. **Split dragging modified an inherited variable on the entire document body.** Setting `--rp-editor-width` on `<body>` invalidated styles across unrelated Viewer, Data Tree, and chat subtrees. Set the non-inherited `grid-template-columns` property only on the report grid, preserving bounded ratios, keyboard operation, and responsive fallback.
3. **Presentation-save debouncing postponed HTTP, but not expensive state capture.** `brachybot-timepoints.js` copied state and rebuilt the timepoint strip for every interaction. Defer capture until the 700 ms debounce settles; paint the unsaved state only on the clean-to-dirty transition. Navigation still captures the outgoing owner's state synchronously before clearing its DOM. Detached/stale timers cannot capture another owner.
4. **A presentation save returned the entire clinical snapshot.** The real private-case probe measured 14,639,977 response bytes for the full workspace, versus 413,449 bytes for the new compact response (approximately 97.2% fewer bytes). `web/routes/timepoint_routes.py` retains the same actual save transaction and authorization checks. Opt-in `response_mode: presentation_receipt` returns canonical touched presentation plus owner/version receipt, not unrelated clinical results or chat. Legacy callers and mixed asset/API revisions retain full-response compatibility. The frontend checks Session/timepoint identity, clinical and lifecycle revisions before merging the receipt; no copying of the large unrelated clinical cache is needed. Clinical revision was unchanged in the probe.
5. **The hidden 3D Viewer polled for usable geometry every 50 ms.** `brachybot-3d-manual.js` now waits for existing resize/activation/visibility events, retaining pending frame requests. Executed scheduler tests verify no hidden polling, resumption on visibility, and preserved full-quality report capture. This is not a hardware/GPU commissioning test.
6. **Report presentation saves confused finalized restore metadata with an active write lock.** Zoom, split ratio, reset, and two-column layout now check the actual active restore/write lock. The read registry remains available for late resource restoration, without suppressing subsequent user edits.

## Browser measurements

Private copied case, 12 report pages, 7 figures, 2 mask labels; real Chromium, 1440 x 1000 viewport, 4x CPU slowdown. No production patient/account state was changed. Page errors: zero; report page count remained 12. Measurements concern repeated interactions after hydration, not cold initial-case load.

| 12 repeated actions | Before | Optimized | Additional observation |
| --- | ---: | ---: | --- |
| Zoom without save | 3,575.4 ms | 465.9 ms | 12 repeated paginations became zero; observed long tasks became zero |
| Zoom with normal presentation-save entry | 3,799.5 ms | 520.2 ms | Capture calls reduced from 12 to 1 |
| Report/editor split changes | 4,067.7 ms | 756.0 ms | Repeated physical pagination removed; one deferred capture |

Zoom comparison uses the same interaction script. Baseline split measurement applied the original inherited body variable and refresh at matched ratios; optimized split measurement dispatched actual pointer events through the production splitter at those ratios. Therefore this is diagnostic comparative evidence, not a perfectly identical-event benchmark or a universal client-hardware performance guarantee. Report zoom/split remain subject to device, compositor, network, and content-size differences. Optimized save and split runs still observed some deferred long tasks, with maximum frames around 200 ms at 4x CPU slowdown; do not claim universal 60 fps or zero lag.

## Compatibility and regression checks

- Final LAN targeted regression: **62 passed, 3 warnings**, including real report browser/PDF tests, native report figure contracts, physical geometry tests, timepoint frontend/route tests, and executed hidden scheduler test.
- Final public targeted regression: **68 passed, 5 warnings**, including public Access, hybrid/email authentication, and existing public checkpoint tests. Public self-registration production policy is unchanged; synthetic account fixtures explicitly enable it only inside tests.
- Initial complete LAN regression: **1 failed, 4537 passed, 5 skipped, 34 warnings, 4 subtests passed**. Sole failure required the widest-paper calculation expression. The equivalent cached calculation now preserves that expression. Final complete rerun on the final source: **4538 passed, 5 skipped, 34 warnings, 4 subtests passed in 712.89 seconds (11:52)**; no failures. Warnings are existing SWIG and datetime deprecations. These tests ran in isolated candidates, not against writable production clinical accounts.
- Report tests exercise unchanged DOM/text/page count during zoom; hidden-to-visible recovery; font/paper invalidation; fixed-evidence-image load behavior; finalized-read-registry versus active restore; actual A4 PDF readability and complete organ/seed rows.
- Timepoint tests exercise deferred capture, navigation capture ownership, compact acknowledgment, legacy full response, and version conflict behavior. Authorization/CSRF/owner/clinical/lifecycle/editor checks remain in existing production save paths.
- Scope: six product files, seven test files, this acceptance record (**14 files per deployment**). No model, runtime database, account, secret, auth configuration, dose, planning algorithm, or unrelated dirty-worktree file is replaced.
- Public index and report shell are separately merged from the real public baseline, preserving public-specific authentication bootstrapping and localization/narrative behavior.

## Installation and live checks

Formal targets: LAN `/home/lht/snap/brachyplan/BrachyBot` and public `/home/lht/snap/brachyplan/BrachyBot-release`. Validate both sets against captured baseline hashes before the first write, recheck each file before replacement, back up originals, and use atomic replacements. No whole-worktree commit or blanket synchronization.

Asset revisions: LAN 3d-manual 125, public 3d-manual 127; both report-shell 39, timepoints 5, report-export 50. Preserve all other independent entrypoint assets.

Installation and live verification have separate authoritative receipts: `install-receipts.json`, `lan-reload-receipt.json`, `public-reload-receipt.json`, and `live-verification.json` in the restricted staging directory `/tmp/brachybot-browser-perf-20261014`. Do not infer live deployment solely from this source document or test success. Graceful reload must preserve each process's own arguments, cwd, and environment. Never force terminate a refused shutdown. Verify listener/PID/cwd, health JSON, anonymous protected API rejection, and HTTP-delivered asset hashes after reload. Authenticated public external-browser/Cloudflare commissioning is outside this isolated regression; do not represent local health and auth tests as that result.

The private copied-case profiling directory was removed after the last private probe, with its exact absolute target validated. Only aggregate measurements and test/deployment receipts are exported. The original case was not altered or deleted.
