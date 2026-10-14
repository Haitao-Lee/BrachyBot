# Five reported product issues — repair and verification, 2026-10-14

Scope: the five UI/resource-restoration/Session/default-presentation issues reported on October 14. Work was performed by the main agent without delegated agents. This record does not assert that every clinical case or all earlier a–i clinical workflows have undergone patient-level validation.

## Checklist

| Reported issue | Implemented paths | Verification |
|---|---|---|
| Unified, consistent Viewer toolbar | `web/app/static/js/brachybot-timepoint-workspace.js::mountControls`, `web/app/static/css/brachybot-workspace-refinement.css`, versioned assets in `web/app/index.html` | Real page: native handlers retained, dose selection and implanted-source actions inside the same toolbar, horizontal overflow rather than compressed controls; desktop/narrow viewport checks; dose popover remains outside the scrolling bar and opens/closes correctly. |
| Old/current/cooled case resources fail to load | `web/timepoint_images.py::adopt_saved_reference/_saved_source_image`, `web/routes/planning_routes.py::api_config_get`, `web/timepoints.py::load_timepoint_snapshot`, `web/workspace_store.py::load_snapshot(shared_only=True)`, `web/timepoint_chat.py::_state_token` | Source-only legacy NIfTI fixtures on native and LPI grids, ownership/geometry rejection tests, mask/plan/revision preservation, complete real-browser cold restore; isolated same-host copy of an existing approximately 15 MB snapshot reaches final resource-ready state with actual CT, saved structures, needles/seeds and Gy dose. No original patient data or accounts were edited by this probe. |
| Session switch lingers or loses later click | `brachybot-workspace.js::switchSession/newChat/paintSessionShell`, `brachybot-report-export.js::flushActiveReportState`, `brachybot-timepoint-workspace.js::persistPresentation`, `brachybot-timepoints.js::savePresentation` | Actual server with deliberately delayed selection transport: clicked shell paints immediately, old clinical view clears, final click wins, switching back restores original settings. Outgoing state is captured before asynchronous work and written with the original owner and clinical/lifecycle CAS. No chat-task abort endpoint is called merely for navigation. |
| Inconsistent/unstructured Data Tree | `brachybot-timepoint-workspace.js::renderImages/imageRow/renderDoseControls`, refinement stylesheet | Actual computed label font sizes equal 12 px; groups/rows/status/metadata use defined hierarchy; empty groups omitted, empty messages are compact nodes, inactive-image names and controls have structural grid layout, dose modes use vertically arranged tree nodes. Status text cannot wrap one character per line. |
| Default annotations/CTV/OAR | `web/planning_distance_annotations.py`, `brachybot-planning-distance-annotations.js::accept`, initial/reset paths in `brachybot-ui-api.js`, `brachybot-viewer-layout.js`, `index.html` | Automatic seed/needle distance records default to hidden, 3D label master defaults unchecked, top CTV/OAR controls default checked. Existing explicit saved presentation is retained rather than forcibly reset. Backend annotation tests and real-page checkbox assertions pass. |

## Root causes

Legacy durable snapshots intentionally omitted transient `ct_data`, but image-collection adoption only handled persisted pixels. The uploaded owned CT file was still present, yet migration returned an empty collection. Recovery now decodes that owned source on the exact persisted clinical grid, rejecting missing/out-of-owner/link-traversing sources and mismatched geometry. DICOM source recovery requires an unambiguous owned acquisition; it does not guess among multiple series.

Large-case restoration also repeatedly copied the entire legacy clinical/UI history solely to obtain shared conversation fields, and recursively built enormous state-token tuples for ordinary DVH/history JSON on every Viewer request. Shared projection excludes clinical/UI sections; canonical state tokens retain nested-mutation detection and array-identity fencing. The redundant second copy of a freshly checksum-verified JSON state is removed. Input configuration reads durable metadata without constructing a clinical Agent. Workspace/config request timeouts allow large-case restore without the earlier fixed 15-second cutoff.

Session switching previously painted after asynchronous preparation and could suppress a queued target as already selected. Immediate owner-bound shell painting, forced queued selection and late-response rejection address this. Capturing the old presentation before awaiting an image/config save prevents reading a cleared or newly selected workspace into the old case.

## Test evidence

- Targeted store/ownership/migration/chat/HTTP/frontend/annotation suite: **197 passed, 3 skipped**, with the configured real dose-model path. Skips were optional runtime/browser cases in that invocation; no skipped item is represented as a pass.
- Dedicated real-browser chrome/popover/desktop/narrow/default checks plus Session transition runtime regressions: **9 passed**. Includes two ownership/nested-token regression tests; overlapping counts are not summed.
- Complete actual-product two-timepoint upload, switch, cold restore, complete-workspace export/import, rapid delayed Session switching and return-state preservation: **1 passed**, 132.97 seconds. A final expanded rerun also verifies changing W/L to 711/55 immediately before rapid navigation and retaining those newly changed values on return: **1 passed**, 125.63 seconds. These are repeated acceptance runs, not independent totals.
- Existing-case isolated full-page probe: final `resourceReady=true`, CT shape `[10,512,512]`, image collection count 1, selected dose loaded in Gy, no page JavaScript exceptions. Some isolated-copy attachment requests were rejected by ownership checks; this is not evidence that every original report attachment was verified. Late nonessential rendering requests may remain after the final clinical resource barrier.
- Python AST and Node syntax checks cover every installed Python/JavaScript source in the patch.

## Formal deployment

Both formal deployments received separately prepared packages: **16 product files plus 6 tests each**. LAN differences were preserved through three-way source merging; its HTML patch only updates the changed controls, stylesheet and asset counters. No public authentication/enrollment scripts were copied into the LAN HTML.

- LAN: `/home/lht/snap/brachyplan/BrachyBot`, runtime `.runtime`; reloaded existing trusted-LAN listener at `192.168.1.113:8080`.
- Public: `/home/lht/snap/brachyplan/BrachyBot-release`, runtime `release-state/runtime`; reloaded only `brachybot-public.service`, listener `127.0.0.1:18082`, HTTPS entry `https://app.brachybot.com`.
- Before-hash CAS, recoverable source archives and SQLite backups were created independently. Neither case store nor authentication configuration was copied between deployments. Four protected auth modules and `config/user_config.json` remained byte-identical within each deployment. Runtime skill statistics were not included.
- After-install verification: **zero mismatches for all 22 package files in each formal directory**. LAN page and public HTTPS page/new stylesheet return 200; unauthenticated public workspace access remains 401. Local public `/` without the public-origin Host context returns 400 by its existing origin protection; this was not bypassed.
- Source backup directories: `/home/lht/snap/brachyplan/backups/brachybot-five-issues-public-20261014-e1wvrfz1` and `/home/lht/snap/brachyplan/backups/brachybot-five-issues-lan-20261014-ar39tmy3`.
- The final outgoing-image-save race hardening is static JavaScript only; it was installed without another backend restart after the expanded W/L navigation test passed. The final package remains 16 product files and 6 tests per deployment, with timepoint controller/workspace asset counters 3/4. Follow-up source/database backups are `/home/lht/snap/brachyplan/backups/brachybot-five-issues-public-20261014-tz39hk56` and `/home/lht/snap/brachyplan/backups/brachybot-five-issues-lan-20261014-0egp0mdn`.

Refresh an already-open page to load the incremented asset versions. Newly loaded pages use the updated modules. This patch adds no fake clinical results, weakens no public authentication and does not replan or overwrite patient cases as part of acceptance testing.

After acceptance, the private temporary copy of the existing case and its before/after case screenshots were removed from the isolated stage. The original case, deployment rollback backups, synthetic UI screenshots, test scripts and verification receipts remain intact.
