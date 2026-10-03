# Monitor Update Audit Verification and Remediation (2026-09-28)

## 1. Scope, Baseline, and Conclusions

This report corresponds to the "Implementation Status Review (Second Round)" beginning at line 350 of `MONITOR_INTERACTION_AUDIT_2026-09-26.md`. After reading the original report, I checked each item against the actual backend, browser executor, HUD, screenshots, and test code, rather than modifying directly based on the completion percentages in the report.

The review's starting baseline was the current working tree at `a3aa976844526195756a36beebc2828b165e9c33`, in which the original audit report had uncommitted updates; during implementation, other agents committed natural-language/UI contract fixes. The final merge and verification baseline was `a0aaa2cb4467a7762b37620f53749bf700b360c7`. These parallel changes were preserved; no new code in `brachybot-ui-api.js`, `brachybot-chat-todo.js`, or the agent execution layer was overwritten.

Conclusion: The gaps described in the second round regarding HUD display, workflow guidance, spatial spacing annotation, single-object localization, and cumulative perspective are real; "roughly 50%/55% complete" is a product assessment and cannot serve as a verifiable software metric. The existing lifecycle and evidence-gathering mechanisms were retained, and interaction was extended on the same committed evidence and executor, without establishing a second planning state.

## 2. Item-by-Item Verification and Handling

| Original report item | Verification and remediation |
|---|---|
| 1. Chat-as-Dashboard | The HUD indeed lacked scores, delta arrows, aggregated to-dos, and unseen-screenshot indicators. Added four metric cards, comparable deltas, a V100 measurement bar, an OAR Dmax expansion area, and evidence entry points; metrics can only come from valid results of the current planning version. |
| 2. Spatial feedback | Originally there were only outline boxes and return arrows, with no spacing measurement lines. The safety check now returns the closest axis points, and measurement lines/labels are drawn during HUD localization; clicking an object ID localizes it individually, and clicking "View spacing" localizes the corresponding object pair. Newly arising/worsened overlaps use a stable red outline rather than continuous flashing. |
| 3. Plain text/severity | The original structured feedback already existed and was not rewritten. Added geometric `blocking`, triggered only by measured newly arising/worsened physical overlap; default clinical thresholds or unrecomputed doses are not judged as clinical failure. |
| 4. Workflow | The original badge lacked prioritized steps and suggestions. Changed to an ordered checklist that highlights the running or first-to-verify unverified/stale/failed stages and shows the corresponding next step. A checkmark means usable data is available, not that a physician approved or the user has completed review. |
| 5. Evidence chain | Bounded retries, background re-capture, and version isolation already existed, and the report's assessment of this was largely accurate. The existing mechanisms were retained, and an "unseen" marker was added to successful screenshots, set to viewed only after jumping to the exact chat record. Evidence is not fabricated through repeated screenshots. |
| 6. Multi-channel | The reset token did indeed still appear in the new feedback body; it was removed and replaced with a direct button pointing to this edit card. Legacy token parsing and the fallback button when there is no structured card were retained for compatibility, still entering the same authorized executor, rather than being deleted outright and causing old sessions to be unable to reset. |
| 7. Automatic dose | Being off by default is a fact, but it is a deliberate performance/operation authorization choice, not a failure. The opt-in debounce, consecutive-edit coalescing, and drag/busy-time avoidance were retained; expensive computation is not initiated on every drag by default. |
| 8. LLM explanation | The existing on-demand explanation entry point is real. The evidence-based explanation for an explicit request was retained; the model is not called on every edit by default, and a "dose-optimal direction" is not generated from a scalar score. Automatic personalized clinical coaching is still not implemented and cannot be claimed as complete. |
| 9. Lifecycle | stop_error recovery and run_mismatch isolation were already implemented and were not replaced this round; the original end/retry/new-run ownership protections were restored. |
| 10. Cumulative perspective | The lack of graphical trends and timeline integration is real. Added V100/D90/effective-score trends and this round's event statistics, integrated into a compact timeline. Different plan/anatomy/config baselines are not connected; the "edit event count" does not masquerade as the number of independent drags. |

## 3. Scientific Meaning of Spatial Evidence

1. `_segment_segment_closest_points` returns the closest points of finite segments; `_segment_segment_distance` computes distance using the same pair of points. Parallel, intersecting, endpoint, and degenerate point-segment cases are handled, without replacing the physical thresholds of the original check.
2. Seed evidence provides the closest axis points, the axis distance, and the signed surface clearance defined by the safety model. Labels clearly distinguish axis distance from surface clearance, and center distance is not mislabeled as surface clearance.
3. Needle-track evidence provides the closest axis points, the distance, and whether physical overlap occurs given the current needle diameter. Labels do not claim to have localized an anatomical tissue contact point.
4. Localization is possible only when the object reference is verifiable, both objects are visible, the case/plan/version/geometry match, and no drag, report evidence-gathering, or other screenshot occupation is in progress.
5. Before drawing a line, verify patient world coordinates, finite 3D coordinates, and that the point distance matches the evidence value; when evidence is missing, only existing text is retained and no fake measurement line is generated.
6. Lines, boxes, and labels are temporary overlay objects and do not change seed or needle-track material, opacity, visibility, geometry, or the Data Tree. Clearing localization restores the camera; consecutive localization first restores the previous original camera, then opens a new transaction.
7. Distance labels adapt to the current projection and window size, avoiding a fixed millimeter size that would occlude the entire object in a seed close-up. Overlays release textures, materials, and geometry without affecting shared ArrowHelper resources.

## 4. Boundaries Between HUD Data and History

- Missing scores display "—"; old-version scores are not reused, and a score increase is not treated as overall clinical improvement.
- Arrows display only existing valid before/after comparisons; the V100 bar is only a measured value and is not colored as "clinically acceptable".
- The current OAR display shows at most five valid, finite highest-Dmax records; full OAR statistics are still provided by the existing Analysis/query interface.
- Coverage distance uses only the case's saved and valid `plan_config.DVH_rate`; if there is no explicit configuration, no target is displayed; software defaults are not supplied as clinical standards.
- Current HUD data is protected by case, run, planning ID, planning version, and drag state. Historical trends are explicitly records from their time and are not treated as current dose results.
- The trend continuity key includes plan, anatomy, and dose configuration. When the anatomy baseline or a compatible key is missing, no line is drawn; when switching baselines, that legitimate before/after segment can be drawn independently, but different baselines cannot be connected into a single edit improvement.
- The timeline shows the total number of events this round and the most recent 40 events. When old records exceed the retention range, this is indicated; the edit count is labeled "edit events" and does not count associated seed reprojections or each sample point as an independent user drag.
- Unseen screenshots, in-preparation screenshots, and currently executable edit decisions are counted separately. The unseen indicator is cleared only after jumping to the corresponding message; an image is not declared present merely because a screenshot task was created.

## 5. Interface and Timing Control

What was added is a `compact=1` projection of the existing `/api/training/timeline`; no external dependencies or tool names were added. The original full-export behavior is unchanged.

- The compact response is capped at 80 events, and the HUD requests 40; it only reads this case's bridge records, without hydrating the Agent, CT, or the entire case, and without invoking model/dose/geometry QA.
- Must match the monitor run; a mismatch returns 409, and an invalid limit returns 400.
- Raw scene arrays, inverse-operation geometry, or reset tokens are not returned; only event metadata and small dose samples from committed evidence are provided.
- The HUD reads in parallel with the existing overview, sharing the 5-second cancellation, sequence, and owner fence; 250 ms debounce, no per-object requests, and no per-event LLM calls.
- A failure of one independent read does not block the other read, manual editing, or stopping monitoring.

## 6. Change Points

Production code:

- `web/server_support.py`: finite-segment closest points and seed-spacing witness.
- `web/monitor_changes.py`: needle-track witness, blocking, score/OAR/target projection, trend baseline key, compact timeline, user feedback copy.
- `web/routes/planning_routes.py`: read-only compact timeline branch, retaining the parallel agent's UI-state versioning changes.
- `web/app/static/js/brachybot-monitor-interaction.js`: child-object localization reference authorization and evidence-viewed marker.
- `web/app/static/js/brachybot-monitor-dashboard.js`: measurement overlay, trends, checklist, metrics, and to-dos.
- `web/app/static/css/brachybot-monitor-dashboard.css`: responsive metric grid, hierarchy/severity, trend/checklist styles.
- `web/app/index.html`: only updated this round's Monitor static asset versions, retaining chat-todo v73 and ui-api v122.

New risk coverage was placed in the existing `tests/test_monitor_dashboard.py` and `tests/monitor-dashboard-browser.test.cjs`; old guards were not relaxed, unrelated files were not cleaned up, and the public release deployment was not modified.

## 7. Verified and Unverified Scope

Verification baseline: an isolated copy of the latest source and the remote working tree after the fixes were applied; all tests use isolated/synthetic fixtures and do not use real cases.

- Python isolated-copy related regression **253 passed**; after adding `test_workspace_frontend.py`, the final regression on the remote actual working tree was **405 passed**: Monitor HUD, edit evidence, lifecycle, training audit, manual seed transactions, needle spacing, obstacle safety, Viewer geometry, manual stepwise display, frontend assets, and the parallel fixes to the UI state/authorization/parameter-binding/step-identity contracts.
- 11 Node/browser scripts passed: dashboard-state, checkpoint-cards, dashboard-browser, coaching-browser, capture, edit-interaction, advice-ownership, recovery-state, stop-recovery, intent-routing, stop-presentation.
- Real Chrome headless WebGL + synthetic objects: direct button execution, object/object-pair localization, precise measurement labels, label close-up adaptation, no color change, camera restoration, cross-case/plan/drag isolation, unseen screenshots, and trend line breaks.
- The existing SWIG and `datetime.utcnow` deprecation warnings were not expanded or modified this round.
- No claim is made that the entire repository is green; real-case GPU recomputation, real physician operation, external clinical threshold validity, or end-to-end screenshot network integration testing were not performed. The browser tests above are synthetic fixtures on a real rendering engine, not patient production screenshots.

## 8. Release Record

Completed:

- Each of the nine existing target files was checked one by one to confirm its Git content hash matched the merge baseline, and the change package was applied only after confirming there were no parallel uncommitted modifications; this was not a whole-repo overwrite.
- The original backup is located at `/tmp/brachybot-monitor-originals.JbijOA/originals.tar`. This is a temporary recovery backup and does not replace long-term Git history; no commit was created this round.
- `git diff --check`, Python AST, and Node syntax checks on the two modified JS files passed.
- Before restarting, a read-only check of persistent case run states showed running = 0. Then LAN 8080 was restarted according to the existing post-test release convention; the separate public-release was not touched.
- The new listener on 8080 has PID `3564682`, with cwd `/home/lht/snap/brachyplan/BrachyBot`. `/api/healthz` returned HTTP 200, `ok=true`, returning the same PID; the startup log shows Flask started.
- Three Monitor static assets returned HTTP 200, and their response byte hashes match the current working tree; the home page actually references CSS v2, interaction v3, dashboard v2, and retains ui-api v122.
- The original audit report is left as-is. This file records verification and remediation, avoiding rewriting subjective completion levels as verified facts. New scripts are loaded only after the browser is refreshed; the in-memory state of old pages does not automatically change due to a backend restart.

---

# Independent Review (Third-Party Verification Round)

**Trigger**: Verify whether the remediations listed in the above "Implementation Status Review" have been resolved and are correct.
**Method**: Without taking this file's self-report at face value, read the actual code item by item and independently run calculations/re-run tests. The review baseline is the
`a0aaa2cb4` working tree described in this file (including the uncommitted 9-file changes, consistent with §8's "no commit was created this round").
**Conclusion**: The 10 remediations in §2 were reviewed item by item, plus §3 spatial evidence and the §7/§8 release claims:
- **All 9 check rows are accurate and correctly implemented** (§A, covering original items 1/2/4/5/6/10 and the release items);
- **1 item is incorrect** (the blocking geometric criterion of original item 3 produces a false positive in endpoint scenarios, §B);
- **3 claims cannot be verified in this environment** (browser acceptance, test counts, some Node invocation methods, §C);
- Original items 7/8/9 (automatic dose opt-in, on-demand LLM, lifecycle) are **deliberate design choices** rather than defects,
  and the claims match the code, so they are not counted as "not meeting the bar".

## A. Items That Passed Review (9 Check Rows)

| Item | Review method and evidence | Verdict |
|---|---|---|
| §3.1 Segment closest-point algorithm | I independently implemented a brute-force sampling reference (dense two-parameter sampling) and compared `_segment_segment_closest_points` against three groups: **17 structured cases** (intersecting/parallel/collinear separated/collinear overlapping/anti-parallel/oblique 3D crossing/oblique 3D offset/T-junction/point-segment/point-point/near-degenerate/L-corner/endpoint-endpoint) + **300 random segment pairs** + **120 endpoint-dense pairs**. Maximum deviation 1.1e-3 / 4.1e-3 (within sampling resolution); **number of times the witness fell outside its own segment = 0**; `_segment_segment_distance` matched the witness distance in every case. Parallel, intersecting, endpoint, and degenerate point-segment cases are all correct, and the projection parameter derivations for the degenerate branches (`a<=1e-12`, `c<=1e-12`) are correct (`t=e/c`, `s=-d/a`) | ✅ Correct |
| Axis distance vs center distance | Coaxial seeds with center=5.0mm, axis=0.5mm; `measurement.value_mm` takes axis, and the test asserts `!= center_distance_mm` | ✅ |
| Labels distinguish axis/surface clearance, close-up size adaptation | `monitor-dashboard.js:339-357`; `visibleHeight` (orthographic/perspective branches) determines sprite size | ✅ |
| Does not alter seed/needle-track materials | The overlay is an independent `THREE.Group('monitor-focus')` + `userData.monitorAnnotation`; `clearMonitorFocus` (:286-294) only disposes the overlay's geometry/material/map and does not touch the materials of `scene3D.meshes` | ✅ |
| §3.4 Localization precondition gate | `focusMonitorCheckpoint` (:301-312) checks in order: not dragging (`monitorInteractionActive`), not screenshot-occupied, not report evidence-gathering, `planning_id` match, `after_version` match, `geometry_key` match, each ref `locatable`, and all `refs` hit | ✅ |
| Token removed from new feedback body | `monitor_changes.py describe()` has been changed to "select on this edit card…", no longer outputting the code; the token parsing in `_attachMonitorEditChoices` and `handleMonitorConversation` retains compatibility as claimed | ✅ |
| Unseen-screenshot marker | Determined by `markMonitorEvidenceViewed` + `viewedCaptureEventId !== lastEventId`; set to viewed only after jumping to the corresponding `[data-message-id]` | ✅ |
| Checklist/sparkline/compact timeline/coverage target/score display | `aria-current="step"`, `✓/→/·`, per-step tips, disclaimer "data availability does not imply clinical approval"; `series_key` with different baselines are not connected; compact 80/40 cap, 409/400, no geometry arrays and no token, monkeypatch prevents `_ui_bridge_snapshot` from passing; coverage target is taken only from `plan_config.DVH_rate`; missing scores display `—` | ✅ |
| Version/release/syntax | `index.html` references CSS v2, interaction v3, dashboard v2, retaining ui-api v122, chat-todo v73; PID `3564682` is running, `/api/healthz` `ok=true` with the same PID; the server-side `monitor-dashboard.js` md5 matches the working tree; `originals.tar` contains and only contains the 9 target files; `git diff --check`, 4 Python ASTs, and 4 JS `node --check` all pass; the physical threshold `threshold_mm`/`risk` formulas are word-for-word identical to HEAD | ✅ |

## B. The Incorrect Item: `blocking` "Physical Geometry Overlap" False Positive in Endpoint Scenarios

### B.1 Problem

`surface_clearance_mm = axis_distance − 2·seed_radius` (`web/server_support.py:958`) is the **lateral clearance between two infinite cylindrical surfaces**.
Only when the closest axis point **falls inside both segments** does it equal the solid surface clearance. When the closest point falls on an **endpoint**, the true solid clearance is
the end-face spacing, which may be positive while that formula yields a negative value; `risk='overlap'` (`:959`, criterion `axis_distance < 2R`) is then misjudged.

This round upgraded that criterion to `severity='blocking'` + `blocking_scope='physical_geometry'` and rendered the banner
**"Requires handling first: physical geometry overlap"** (`brachybot-monitor-dashboard.js:161`) — this is a **factual assertion** that
does not hold in endpoint configurations.

### B.2 Reproduction (default length 4.5mm / radius 0.4mm)

```
Adjacent seeds in the same needle track, center distance 5.0mm (end-face clearance +0.50mm, solids do not touch)
  center_distance_mm = 5.0
  axis_distance_mm   = 0.5
  surface_clearance  = -0.3        <-- negative, but the solids have 0.5mm clearance
  risk               = 'overlap'
  -> severity        = 'blocking'  blocking_scope='physical_geometry'
  -> banner          = "Requires handling first: physical geometry overlap"   <-- assertion does not hold
```

Step-distance sweep (3 seeds in the same needle track):

| Center distance | End-face clearance | Reported axis | Reported "surface clearance" | risk | severity | Solid contact? |
|---|---|---|---|---|---|---|
| 5.00mm | +0.50mm | 0.5 | −0.3 | overlap | **blocking** | No |
| 4.70mm | +0.20mm | 0.2 | −0.6 | overlap | **blocking** | No |
| 4.55mm | +0.05mm | 0.05 | −0.75 | overlap | **blocking** | No |
| 6.00mm | +1.50mm | — | — | no alarm | — | No |
| 10.00mm | +5.50mm | — | — | no alarm | — | No |

That is, a 4.5–5.0mm step distance (common source arrangement for PDR/HDR) will **stably false-positive as blocking**. This configuration is rare in random-configuration Monte Carlo
(near-coaxial adjacent endpoints), so random testing cannot prove it harmless; the false positive is determined by the configuration geometry and is deterministically reproducible.

### B.3 Root Cause

- The formula and criterion are **pre-existing** (this round's `git diff` only **adds** the `measurement`
  dictionary to `risk`/`surface_clearance_mm`, without changing the formula; the thresholds are word-for-word identical to HEAD, consistent with "not replacing the physical thresholds of the original check").
- But this round **upgraded it to blocking + a factual assertion**. The old copy only called it a "spacing issue" (broad semantics, able to accommodate endpoint proximity),
  while the new copy asserts "physical geometry overlap" (narrow semantics, requiring solid intersection). **The impact therefore expands from "suggest review" to "blocking-level error message"**.
- Report §3.2 qualified it with "the signed surface clearance defined by the safety model"; **the UI banner lacks this qualification**.
- §3.2's "labels clearly distinguish axis distance from surface clearance" — distinguishing the two numbers is accurate; but the second number in endpoint scenarios
  is **not** surface clearance, so the naming itself remains inaccurate.

### B.4 Test Coverage Gap

The 7 test cases added this round:
`test_blocking_is_measured_geometry_not_unsupported_clinical_threshold`,
`test_overview_oar_cards_and_configured_target_are_current_only`,
`test_timeline_projection_is_bounded_token_free_and_cannot_attest_a_preview`,
`test_dose_trends_change_series_when_anatomy_or_prescription_changes`,
`test_spacing_witness_matches_finite_segment_check` (5 parameterized cases),
`test_seed_annotation_measures_axes_not_centroid_distance`,
`test_compact_timeline_checks_run_and_never_copies_full_case_bridge`.

Among them, the 5 cases of `test_spacing_witness_matches_finite_segment_check` cover collinear/point-segment/endpoint,
**with no gap at the algorithm layer**; `test_seed_annotation_measures_axes_not_centroid_distance` uses
coaxial seeds at z=0 and z=5, **only asserting axis≠center**, not asserting `risk`/`severity` semantics;
`test_blocking_…` feeds a synthetic `risk:'overlap'` directly into `interaction()`, **without going through
the geometric determination of `_seed_interference_report`**. Therefore the endpoint false positive of B.2 is not within the assertion surface of any test case.

### B.5 Proposed Criterion (not implemented, pending)

Use `axis_distance < 2R` to judge solid overlap only when the **closest point pair falls inside both segments simultaneously** (parameters `s,t ∈ (ε, 1−ε)`);
when endpoints dominate, downgrade to `warning`, change the copy to "axial end-face clearance ≈ X mm (the safety model's lateral gauge is
Y mm)", and narrow `blocking_scope` accordingly to `physical_geometry_interior`. A same-needle-track 5.0mm step-distance regression
case should be added (expected **not** blocking). This change touches the `risk` semantics of `_seed_interference_report`,
which is part of the existing check's gauge, and should be implemented after separate review.

## C. Claims That Cannot Be Verified in This Environment (3 items)

| # | Report claim | Actual measurement | Verdict |
|---|---|---|---|
| C.1 | §7's "11 Node/browser scripts passed: … dashboard-browser, coaching-browser …" and "real Chrome headless WebGL + synthetic objects: direct button execution, object/object-pair localization, precise measurement labels, label close-up adaptation, no color change, camera restoration, cross-case/plan/drag isolation, unseen screenshots, and trend line breaks" | Neither the repository nor `/home/lht/.conda/envs/brachytherapy` **has a `playwright` module**, and there is no `tests/test-runtime/`. `monitor-dashboard-browser.test.cjs` and `monitor-coaching-browser.test.cjs` fail at the `require` stage with `Cannot find module 'playwright'` | **Cannot be confirmed or refuted**. §3's measurement labels/close-up adaptation/no color change, etc. **have been checked item by item at the code layer and found correct** (see A), but the runtime evidence for "synthetic fixtures on a real rendering engine" is missing. Please supply the runtime environment and logs |
| C.2 | §7's "Python isolated-copy related regression **253 passed**…final regression **405 passed**" | Reproducible actual measurement counts: `test_monitor_dashboard + test_monitor_edit_evidence + test_training_monitor_audit = 62 collected`; the above three + `test_surgical_guide` + `test_workspace_frontend` = **273 passed**; `-k "monitor or training or manual or guide or needle or seed or dashboard or spacing or obstacle"` = **319 collected**; full run `--ignore=test_release_access` = **1982 passed / 8 skipped / 2 failed** | **Cannot reproduce 253/405**. The report did not list the file set, so it cannot be refuted. Please supply the file list |
| C.3 | §7 lists `stop-recovery`, `intent-routing`, `stop-presentation` as "passed" | The three scripts **require explicit argv** (passing `brachybot-3d-manual.js`, `brachybot-chat-todo.js`, `brachybot-ui-api.js` respectively); running them bare errors out. With the correct arguments: all three pass | **Valid but the invocation method was not recorded**. It is recommended to state the command line in the report |

Reproducible actual results for the 9/11 verifiable scripts in C.1:

| Script | Result |
|---|---|
| monitor-dashboard-state / checkpoint-cards / capture / edit-interaction / advice-ownership / recovery-state | passed (bare run) |
| monitor-stop-recovery / monitor-intent-routing / monitor-stop-presentation | passed (requires argv, see C.3) |
| monitor-dashboard-browser / monitor-coaching-browser | **blocked**: missing `playwright` |

## D. Wording Residual (minor)

`web/app/static/js/brachybot-ui-api.js:2328` still retains the wording "you may use the reset token in the monitoring prompt"
(not containing the code itself, only pointing the way). §2 item 6 says "the reset token did indeed still appear in the new feedback body; it was removed"
— this is true as far as `describe()` is concerned, but the residual wording still guides users to look for the token, contrary to the direction of "converging interaction channels".

## E. Review Conclusions

1. **The spatial geometry primitive `_segment_segment_closest_points` is correct** (independent brute-force sampling comparison over 400+ cases,
   with the witness landing correctly in all), and the scientific statement in report §3.1 holds.
2. **The blocking false positive in §B is a real semantic error introduced this round** (pre-existing approximation + newly added assertion-level upgrade); for
   the common 4.5–5.0mm step distance it stably false-positives as "physical geometry overlap", and **it is recommended to fix or narrow the copy before wrapping up**.
3. **The three items in §C require additional evidence** before they can be counted as "accepted"; until then, the browser/count statements in §7 should not
   be treated as completed real end-to-end acceptance.
4. The remaining **9 check rows are all accurate and correctly implemented**, with no conflict with the existing lifecycle/evidence-gathering mechanisms; original items 7/8/9 are
   deliberate design choices (automatic dose opt-in, on-demand LLM, lifecycle not replaced), and the claims match the code.

## F. Remediation and Supplementary Evidence After Third-Party Review (2026-09-28)

This section records the actual fixes after the above independent review. §B–§E are pre-fix evidence, and their "pending implementation" and "missing Playwright" should no longer be treated as the final state of this round. The working tree also contains other agents' modifications to the natural-language execution layer; this round only changed Monitor-related files and did not overwrite those parallel modifications.

### F.1 The Endpoint False Overlap in §B Has Been Fixed

`web/server_support.py` adds `_finite_cylinder_spacing`, explicitly separating **axis distance** from **finite solid surface clearance**:

- When the axes are parallel, the signed solid clearance is computed from the radial disk distance and the two finite axial intervals. With adjacent seeds at center distance 5.00 mm and length 4.50 mm, the end-face clearance is **+0.50 mm**, reaching the current minimum clearance and no longer producing a conflict; 4.70/4.55 mm are **+0.20/+0.05 mm** respectively, which is insufficient spacing but not solid overlap; at 4.40 mm it is **−0.10 mm**, which is when solid overlap is confirmed.
- When the closest axis points of non-parallel segments are both interior and the distance is less than the diameter, side-wall overlap can be confirmed. When endpoints dominate, axis distance minus diameter is only a **model clearance lower bound** and cannot prove solid collision; such cases retain a conservative spacing notice with `physical_overlap=None`, and are not escalated to the blocking-level "physical geometry overlap" description. Unknown configurations are not falsely reported as already safe.
- The seed report retains the original `surface_clearance_mm` numeric field for compatibility with old callers, while adding `clearance_basis` and `physical_overlap`; UI/text for non-exact cases must use the name "axis model clearance lower bound". `overlap_count` counts only confirmed overlaps, with `possible_overlap_count` listed separately. The Monitor physical-overlap notice for needle-track pairs likewise uses solid provability and is no longer determined solely by endpoint axis distance.
- The before/after comparison for manual edits now uses solid surface clearance when both are parallel cylinders. This way, moving from end faces just touching to actual overlap is still judged as a newly arising/worsened issue even if both axis distances are 0, preserving the original safety blocking. Solid collision notices and dose/clinical conclusions remain separate.

The blocking in `web/monitor_changes.py` is based only on `physical_overlap is True`; the red outline, labels, and card copy in `web/app/static/js/brachybot-monitor-dashboard.js` use the same evidence. `web/app/static/js/brachybot-monitor-interaction.js`, `web/app/static/js/brachybot-3d-manual.js`, `web/monitor_engine.py`, and the Chinese/English text of the planning suggestions all distinguish between exact values and lower bounds. The static JS version has been updated in `web/app/index.html`.

**Scope boundary**: Exact solid clearance for non-parallel endpoints is not solved by this lightweight checker; possible collisions still go through the conservative notice and the original manual review/safety process. Unknowns are not treated as no-collision here, and no hidden dose recomputation was introduced. This fix cannot replace independent geometry QA or clinical confirmation.

### F.2 Supplementary Verification for §C

- **C.1 environmental blocker resolved**: The bundled Playwright runtime and Chrome are available on this machine. `monitor-dashboard-browser.test.cjs` and `monitor-coaching-browser.test.cjs` have been run and passed on real headless Chrome/WebGL with synthetic fixtures. The first fixture originally called the old number without `clearance_basis` the solid surface clearance; it passed after adding parallel-cylinder and confirmed-overlap evidence. Real-patient browser network integration testing is still not done.
- **C.2 remains cautious**: The previous round's "405 passed" has no reproducible exact file list and is still treated as a historical record; **this number is not re-claimed this round**. The explicit 8-file set run remotely this round: `test_monitor_dashboard.py`, `test_manual_seed_transactions.py`, `test_monitor_edit_evidence.py`, `test_training_monitor_audit.py`, `test_monitor_lifecycle_behavior.py`, `test_needle_obstacle_safety.py`, `test_seed_coordinate_contract.py`, `test_workspace_frontend.py`, with a result of **316 passed** and 17 existing deprecation warnings. This is not the entire repository being green.
- **C.3 invocation parameters verified**: All 11 Monitor Node/browser scripts on this machine were run one by one on the modified source and passed. `monitor-stop-recovery.test.cjs` is passed `web/app/static/js/brachybot-3d-manual.js`; `monitor-intent-routing.test.cjs` is passed `web/app/static/js/brachybot-chat-todo.js`; `monitor-stop-presentation.test.cjs` is passed `web/app/static/js/brachybot-ui-api.js`. The remaining scripts run with default paths.

### F.3 The Copy in §D

The residual sentence in `brachybot-ui-api.js` saying "go to the monitoring prompt to find the reset token" has been changed to point to the "restore pre-edit position" button on the corresponding monitoring card; legacy-session token parsing capability has not been removed. If a card/version has expired, the original executor's ownership and safety validation continue to reject expired restoration.

### F.4 Release Verification

Before the fix, SHA-256 of each target file was verified one by one, and a recoverable backup was left at `/tmp/monitor-spacing-originals.hlmbCE/originals.tar`. The related Python regression passed 316 items, and all 11 Node/browser scripts on this machine passed; the JS syntax check and `git diff --check` passed. Real-case GPU recomputation, patient screenshots, and clinical threshold validity remain unverified. The actual state of the release listener process and static assets is subject to the runtime verification results later in this section; an HTTP 200 alone cannot be used to claim the service has loaded the new code.

### F.5 Same-Root Misjudgment for Needle Tracks and Current Deployment State (continued investigation)

Continuing from the seed fix in F.1, an inspection of `web/monitor_changes.py` found that although needle-track pairs already distinguish `physical_overlap`, conflict filtering and the "worsened" comparison still rely on axis distance. When the end faces of two parallel finite needle tracks are 1.50 mm apart with a configured diameter of 1.20 mm/extra clearance of 1.00 mm, the solid clearance already meets the requirement, but the old rule `axis_distance < diameter + clearance` incorrectly lists it as a conflict; when two needles go from end-face contact to penetration, both axis distances may be 0, and the old comparison again misses the worsening. This is the same class of "infinite axis model replacing finite solids" problem as §B.

Needle-track conflict filtering, before/after deltas, and monitoring copy now use the finite-solid `clearance_mm` and `clearance_basis`; `distance_mm`/`minimum_distance_mm` are retained as compatibility fields. Parallel axes compute exact solid clearance, while non-parallel endpoints remain only a conservative lower bound and cannot be called a confirmed collision. New regression coverage includes: 1.50 mm end-face clearance raising no alarm, 0.50 mm end-face clearance being a non-blocking notice, and penetration after end-face contact being judged as worsening and blocking.

During the continued investigation, seven directly related test files on the remote ran **165 passed**. The eight-file set with `test_workspace_frontend.py` added was **316 passed / 1 failed**; the failure was the old static-string assertion in `test_guide_progress_uses_one_clock_and_hides_background_auto_generation`, which expected the receipt `{ dispatched: true, completed: false }`, while the parallel modification to `brachybot-ui-api.js` had added the `status: 'dispatched'` field. This assertion is unrelated to the current finite-cylinder computation and Monitor interaction; the parallel agent's code was not reverted nor its guard weakened in order to claim all-green. The "316 passed" in F.2 corresponds to the run before the parallel modifications and does not represent the eight-file set result after the continued investigation. `git diff --check` still passes.

8080 is actually listening on `192.168.1.113:8080`, process PID 3564682 started at 14:05:13, working directory is this repository, and both `/api/healthz` and the home page return HTTP 200. However, this process predates this section's Python modifications, so **it cannot be assumed that the running backend has loaded the new geometry code**. At the same time, multiple files in the working tree's `agent_runtime/` are being modified in parallel by another task and have not yet completed overall verification together with this fix; to avoid loading a half-finished product on restart or interrupting unverified case tasks, 8080 was not restarted this round. Subsequent deployment should restart after the parallel modifications stabilize and it is confirmed there are no in-flight planning/guide tasks, then verify the new PID/startup log/health endpoint/actual Monitor receipt. Real-case browser integration testing and clinical geometry QA remain uncompleted acceptance items.

### F.6 Final Regression After Unifying the Two Needle-Track Evidence Paths

After F.5 was completed, it was further found that `_latest_plan_snapshot` in `web/server_support.py` independently used the old axis-distance threshold to generate `needle_geometry.close_pairs`, which would continue to write the same configuration into staging monitoring and the final summary. Therefore `_needle_interference_report` was added as the **single needle-track entry point for the same geometric criterion**: both the snapshot suggestion and the before/after edit comparison in `web/monitor_changes.py` call it; `web/monitor_engine.py` and the summary copy distinguish exact solid surface clearance from the conservative axis-model lower bound. The risk for non-parallel endpoints is still labeled `possible_intersection` and cannot be written as confirmed solid intersection. The old axis-distance and center-distance threshold fields are retained as compatibility evidence, but no longer directly determine end-face collision.

The new entry-point test directly calls `_latest_plan_snapshot`, verifying that a 1.50 mm end-face clearance does not enter `close_pairs` and that a 0.50 mm clearance enters only `too_close` with `physical_overlap=False`; the edit comparison test verifies that contact progressing to penetration is still escalated to blocking. The `status` field added to the receipt by the parallel frontend change caused the old static-string test recorded in F.5 to fail; only the static guard was adjusted to allow additional metadata, still strictly requiring `dispatched: true` and `completed: false`, without modifying business receipt behavior. Finally, the eight-file set listed in F.2 was run remotely, resulting in **318 passed, 17 existing deprecation warnings**; `git diff --check` passes. This is the currently reproducible **targeted test** result and does not mean the entire repository or real-patient end-to-end acceptance passed. The 316/1 in F.5 is an intermediate state and has been superseded by the 318/0 in this section. The 8080 service has still not been restarted, and the runtime effective state is still interpreted under the F.5 limitation.
