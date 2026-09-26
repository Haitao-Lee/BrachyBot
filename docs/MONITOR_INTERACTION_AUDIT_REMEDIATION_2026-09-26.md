# Monitor interaction audit: verification and remediation

## Scope and baseline

Reviewed `MONITOR_INTERACTION_AUDIT_2026-09-26.md` against the actual working tree at HEAD `eae7edb50`, including uncommitted Monitor and manual-step lifecycle changes. Original files were copied and their SHA-256 hashes rechecked before applying changes. No unrelated working-tree changes were reverted. The public-release checkout/process was not modified.

## Audit disposition

| Claim | Verification | Implemented response / design decision |
|---|---|---|
| 1. Feedback lives only in chat | True as an interaction limitation; “unusable without HUD” is a product judgment, not a proven defect | Added a collapsible, resident Monitor workspace above chat. Existing chat records and evidence remain durable; the workspace projects the latest evidence without replacing it. |
| 2. Spatial feedback is disconnected | True: previous focus was limited to screenshot transactions | Added explicit Locate objects and Clear focus actions, using stable IDs, verified visible meshes and reversible framing. Separate wireframe outlines do not recolor meshes or change opacity/visibility. Hidden/missing members of a requested pair prevent a false “located” result. |
| 3. No structured feedback or severity | Partly false: `interaction()` already supplied objects, conflicts, metric rows, priority and next step | Extended that schema with severity/category/spatial references/counts; used warning presentation and actions in the workspace. No second feedback engine was introduced. |
| 4. No visible workflow state | True | Added a compact, opt-in projection to the existing status endpoint: CT/CTV/OAR, geometry availability, dose, QA, guide and report. Unknown remains unverified; available is not clinical approval. Status reads use the cached agent and never wait on a dose transaction. |
| 5. Evidence recovery requires manual retries | True for transient/hidden-tab failures; supersession is not a recoverable error | Added two bounded transient retries and visibility-triggered resume. Case/run/plan/version/geometry fences remain enforced. Superseded geometry is never re-photographed using newer geometry. Text evidence survives image failure. |
| 6. Too many interaction channels | Partly true; several routes already converged on existing lifecycle functions | Card/workspace/legacy buttons now call the same decision executor directly, without injecting opaque token commands into chat. Explicit text-token commands remain backward compatible and use that executor. Server-issued tokens, pending inverse, version validation and safety validation are unchanged. No permissive natural-language authorization shortcuts were added. |
| 7. Dose comparison is hidden behind manual action | True | Added a visible Auto compare switch, off by default per run. When enabled, committed edits are coalesced after 1.8 s idle; no work during a drag, existing dose job or evidence capture, no duplicate attempt per revision. Only dose comparison is requested, not guide/report regeneration. Explicit Compare now remains available. |
| 8. LLM absence makes monitoring unintelligent | The limited participation is factual; the causal claim is not established | Reused the grounded on-demand advice endpoint behind Explain these changes. No per-drag model calls, automatic clinical conclusions, invented optimal displacement, or unsupported user profiling. Added compact request payloads, a 45 s client timeout, duplicate-click protection and case/plan/version/request ownership checks. |
| 9. Recovery requires manual intervention | True after an uncertain stop | Added up to two automatic retries for the explicitly requested stop of the same owned run. A successor run or mismatch terminates automatic recovery. Unconfirmed state remains visible; it is not mislabeled inactive. |
| 10. No in-run cumulative view | Partly true: edit deltas already existed but were scattered | Added a bounded retained-edit view and comparable V100/D90 sequences, with full metric/OAR differences available in the current panel. Counts are explicitly retained-page records, not fabricated all-run totals. No cross-baseline cumulative sum or invented target threshold. |

## Scientific and interaction boundaries

- Outlines identify objects; they do not claim to identify the exact collision point. No line between object centroids is mislabeled as a measured surface clearance. Precise collision witnesses/optimal placement remain outside this patch.
- Focusing is a deliberate user action, never automatic camera theft during dragging. New edits, workspace clear, screenshot capture and report capture remove the transient annotation layer. Clear focus restores the saved camera pose.
- Screenshots retain their existing immutable per-edit attachment ownership. The resident panel links back to the same historical message.
- Current dose values are withheld when stale; OAR maximum is labeled as highest **recorded** Dmax, not as a clinical risk classification. Explicit volume-unit declarations are honored, including values below 1 percent.
- The overview uses a nonblocking planning lock, cached state, and a compact projection. It does not serialize arrays, run geometry QA, hydrate a cold case or invoke a model. Lightweight identity observation refreshes only when the selected planning identity/version changes.
- Auto comparison is opt-in and retains ordinary backend safety/commit checks. Turning it off or stopping monitoring cancels pending automatic scheduling; already committed server work is not falsely reported as cancelled.
- Advice responses that arrive after a case, plan, version or newer advice request change are discarded rather than presented as current findings. No automatic personalized clinical coaching has been enabled.

## Validation

- Targeted Python Monitor suite: 77 passed.
- Broader Python run, excluding the reference-guard collection failure: 1858 passed, 4 failed, 8 skipped; 4 subtests passed. All four failures were reproduced with pre-change source substitution, without modifying the running checkout:
  - `test_round7_regressions.py::test_dose_overlay_opacity_is_invariant_during_slice_scrubbing`: old annotation asset version assertion.
  - `test_round9_regressions.py::Round9RegressionTests::test_report_3d_panels_use_reference_direction_and_tight_panel_framing`: old report-editor asset version assertion.
  - `test_viewer_coordinate_contract.py::test_frontend_uses_one_mapping_for_pointer_navigation_and_annotations`: old annotation asset version assertion.
  - `test_visual_annotation_contract.py::test_screenshot_autoframing_is_target_derived_verified_and_reversible`: source-string assertion predates the manual-step visibility integration.
- Unfiltered collection still fails in `test_surgical_guide_latency.py`: `planning_pipeline.py` differs from the paired latency-reference hash. This patch does not change that pipeline or silently renew the performance reference.
- Eleven Node/browser scripts cover cards, bounded retries, background resume, case/run/version fencing, direct decisions, monitor intent routing, bounded stop recovery, advice ownership and real Three.js framing/outline/camera restoration.
- Browser tests use synthetic geometry and no patient session. No real patient edit, real GPU recomputation or clinically calibrated “better/worse” threshold was validated by this patch.
- JavaScript syntax, Python compilation and `git diff --check` pass.

## Files

Primary new UI modules: `web/app/static/js/brachybot-monitor-dashboard.js`, `web/app/static/css/brachybot-monitor-dashboard.css`.

Shared contracts: `web/monitor_changes.py`, `web/routes/planning_routes.py`, `brachybot-monitor-interaction.js`, `brachybot-ui-api.js`, `brachybot-3d-manual.js`; report-capture cleanup in `brachybot-report-editor.js`. Entry point cache versions updated in `web/app/index.html`.

## Deployment verification

LAN service restarted at 2026-09-26 20:29:17 +0800, PID 2876365. Verified listener `192.168.1.113:8080`, process arguments, working directory `/home/lht/snap/brachyplan/BrachyBot`, startup log, root HTTP 200 and `/api/healthz` HTTP 200. New dashboard JavaScript and stylesheet return HTTP 200; served HTML references updated assets (UI API 120, interaction 2, dashboard 1, 3D/manual 114, report editor 55).

Independent public-release PID 2746992 remains running with its original 14:21:52 start time. No patient planning/edit/GPU job was launched for validation. Reload the browser page to load the updated scripts; enable Monitor to see the workspace. Auto compare must be explicitly enabled for each run.
