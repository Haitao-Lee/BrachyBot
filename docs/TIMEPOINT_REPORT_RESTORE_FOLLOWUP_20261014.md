# 2026-10-14 Timepoint load failure and presentation follow-up

## Confirmed cause and correction

The LAN screenshot's `timepoint_request_failed` was reproduced using an isolated copy of an existing case. Its browser console reported `TypeError: object is not iterable` at `new Set` inside `applyWorkspaceSnapshot`. Report restoration reused a snapshot form object and changed `editedFields` from a JSON array into a mutable Set; plain JSON copies in the timepoint bridges then serialized that Set to `{}`. A subsequent mount could not restore that object.

Corrections:

- Restore detached report forms; never mutate the source snapshot. Normalize edited-field arrays, Sets, empty legacy objects, and boolean membership maps.
- Preserve Sets as arrays in workspace/timepoint copies, exports, imports and report version restoration.
- Provide the previously missing `--card-border` theme alias. The timepoint separator is a one-pixel `--border-hairline` border, not inherited white text color.
- Migrate legacy presentation once using `planning_presentation_defaults_version: 1`: CTV/OAR checked; generated planning-distance annotations hidden. Manual annotations, colors, opacity and other presentation remain intact. Versioned user choices are retained on subsequent restores.
- Run the same migration in synchronous mounting, shared snapshot application and later hydration. Completion defaults do not depend on successful asynchronous dose loading.

## Files installed

Nine product files: index HTML; workspace refinement CSS; workspace, timepoints, timepoint workspace, UI API, DVH planning, report export and report shell JavaScript. One actual-Chromium regression file is also installed. No Python backend changes, authentication edits, database changes or service restarts are part of this installation.

Both formal trees installed and hash-checked:

- LAN: `/home/lht/snap/brachyplan/BrachyBot`; backup `/home/lht/snap/brachyplan/backups/brachybot-report-restore-lan-20261014-l8nfqji3`.
- Public: `/home/lht/snap/brachyplan/BrachyBot-release`; backup `/home/lht/snap/brachyplan/backups/brachybot-report-restore-public-20261014-_drjmzou`.

The existing independent code differences were preserved by three-way merging against freshly fetched formal baselines; installation checked before-hashes to reject concurrent changes.

## Verification evidence

- Actual browser regression: **3 passed** (latest run 9.10 seconds), including legacy report objects, detached snapshots, Set-aware copying, late restore defaults, retained explicit versioned choices, generated-versus-manual annotation behavior, separator computed color, and native confirmation for report-version restoration.
- Full product acceptance: **1 passed**, 154.98 seconds. Actual HTTP/store, NIfTI upload, two timepoints, reference/config isolation, switching, persistence, export/import and cold restoration; no mocked planning output.
- Wider targeted run: **195 passed, 11 failed**. Paired pre-fix baseline has the same 11 failing tests (190 passed, 2 skipped without the browser environment). These are recorded as existing source-contract/version assertions, not counted as green or hidden.
- Running LAN HTTP and public backend (with its normal HTTPS proxy origin headers): all nine product responses match installed SHA-256 hashes. Anonymous workspace requests remain **401** for both. The LAN and public process PIDs remain unchanged.
- Real large legacy-case full restoration: **passed**, on an isolated same-host copy. Actual browser state: mounted=true, requestReady=true, resourceReady=true, CT shape=[24,512,512], one registered image, runtime report editedFields is a Set, CTV=true, OAR=true, label control=false, separator color=rgba(120,140,200,0.08), zero JavaScript page errors. It is a large-mesh software-rendered acceptance run, not a production latency benchmark. Nonfatal 404/403 console warnings and software-WebGL ReadPixels warnings were observed; this is not a claim that every network request was error-free.

## Scope

This document concerns the latest reported load error, separators and planning presentation defaults. It is not a declaration that every historical a–i clinical requirement has been newly revalidated. Isolated legacy-case data and screenshots are not included in delivered source or public artifacts.
