# Complete Organ Dose and Needle-Tip-Referenced Implant Tables

Date: 2026-10-08

## 1. Scope and corrected reference

This change adds complete organ dose tables and a per-needle implant schedule
to the existing report form, preview, HTML/PDF export, and Markdown export.
The operator corrected the requested seed-distance reference: **use the needle
tip, not the skin entry**. Skin-entry and tip coordinates remain separate
needle-level fields.

This is a reporting change. It does not run planning, add or move a seed,
recalculate CNN dose, regenerate a guide, modify segmentation, or certify a
plan for clinical use. Tests use synthetic data, not patient cases.

## 2. Root causes addressed

1. The server API, direct report tool, and legacy frontend autofill selected
   only the first 12 organs. Some fallback paths also discarded all-zero organ
   rows. Consequently, a report could silently omit most segmented organs.
2. Existing report tables exposed only a small subset of OAR metrics, while
   Markdown export omitted the organ table entirely.
3. There was no persisted, needle-owned seed-position schedule. Reusing the
   external trajectory endpoint as skin entry would have introduced a false
   measurement: planner endpoints include an external extension/drag handle.
4. Report generation is asynchronous. A response arriving after a case,
   report-form, planning ID, or geometry revision change must not be applied
   to a different report.
5. An explicitly owned direct tool failure previously fell back to an
   unscoped local/HTTP agent. A generation/version error now fails closed for
   that owner instead of obtaining potentially unrelated report data.

## 3. Organ table contract

`web/report_plan_tables.py` provides the shared numerical report derivative.
`report_table_patch()` is called by both `/api/report/auto-fill` and
`ReportAutoFillTool`. It reuses the current classified Structure Set and the
saved dose through `web/structure_dvh.py`, including its existing cache. It
does not create an additional inference job.

The table retains every readable OAR record, including measured zero dose.
Missing/non-finite values are `null`, rendered as an em dash, never fabricated
zero. Explicit volume-metric units are respected; fraction and percent values
are not converted twice.
Boolean measurements/coordinates are invalid records, not numeric 1 or 0.

Each row includes:

- Stable object ID and label ID where available, and the structure name.
- Dmax, Dmean, D0.1cc, D1cc, D2cc, D90, and D95 in physical Gy.
- V100 in percent and structure volume in cm3.
- Review order, its basis, and any source-backed comparable reference.

The print layout uses two associated tables per organ group: high-dose/mean
metrics and coverage/volume metrics. Both retain the same row numbers and
structure identities. This avoids an unreadable eleven-column A4 table.

### Review priority, not an invented universal importance rank

Ordering is deterministic:

1. Recorded source-backed **comparable physical-dose** criterion review.
2. An explicit case priority list in `plan_config.oar_review_priorities`
   (exact names or object IDs).
3. Source-backed site-criterion organs and comparable limit utilization.
4. Observed D2cc, then Dmax, followed by stable name/ID tie-breaks.

Criteria require exact normalized structure-name or explicit object-ID
matching and recorded sources. Unconverted EQD2, BED, and cGy criteria do not
produce a physical-Gy utilization comparison. Defaults without sources do
not establish a limit. Stale dose does not produce a current limit
comparison. A ratio above a recorded comparable limit is a **review item**,
not an automatic clinical failure declaration.

When applicable criteria or a case priority list are absent, the report says
that its order is observed-dose order, not clinical importance. Unloaded or
unassessed structures are not asserted to have been completely evaluated.
Source names/colors follow the existing identity resolver; name similarity
does not create an anatomical match.

Manual organ-table edits are marked as manual report records, preserved by
autofill, and do not retain obsolete automatic comparison labels for the
edited row. Manual report edits are not new dose calculations.

## 4. Implant schedule contract

### 4.1 Current saved geometry

The read-only snapshot uses:

1. The explicit active manual plan, **including an empty manual plan**.
2. Serialized automatic geometry with its public one-based IDs and verified
   needle endpoints.
3. The immutable algorithm snapshot only as a legacy fallback.

No seed is dropped for a malformed position or missing direction. Duplicate
IDs and ambiguous/missing needle ownership remain visible as review records;
unassigned seeds have their own table. Nearest-needle assignment, axis
snapping, identity deduplication, and hidden coordinate reconstruction are
not performed.

Legacy planning-registry lookup may hydrate existing registry metadata via
the product's existing `active_planning_id()` migration. The new table
builder does not alter source seed/needle geometry or dose. Derived structure
analysis may populate its existing cache.

### 4.2 Needle tip distance

For saved tip `T`, external endpoint `E`, and actual seed center `S`:

```text
u = (T - E) / ||T - E||
tip_distance_mm = dot(T - S, u)
axis_offset_mm = ||(T - S) - tip_distance_mm * u||
```

The tip is zero. Positive distance runs backward from the tip toward skin;
negative distance means the seed center projects beyond the tip. Negative
values are not converted to absolute values or clamped. Seeds are ordered
by increasing signed axial tip distance, with stable tie-breaks.

The schedule lists each seed's ID, tip distance, adjacent axial center
spacing, axis offset, actual saved XYZ, and geometry-record flags. Adjacent
spacing is center-to-center axial spacing, not a surface clearance. An
offset above 0.10 mm is a reporting review flag, not a clinical acceptance
threshold. XYZ values are not changed to hide an offset.

If the needle axis is invalid, distance/offset are unavailable while actual
valid XYZ remains visible. A valid tip and axis still support tip distances
when skin entry cannot be confirmed.

### 4.3 Skin entry and insertion length

The first saved needle endpoint is the deep tip; the external endpoint is
**not** assumed to be skin entry. Entry is sampled only from the saved guide
skin envelope when its array shape and recorded spacing/origin/direction
match the CT. It reuses the guide's physical entry sampling and truncated-FOV
guards. No new HU threshold or skin surface is generated as a report side
effect. The existing 5 mm guide truncation is unchanged.

Each needle section contains skin-entry XYZ, tip XYZ, and axial skin-to-tip
length. If entry cannot be confirmed, those entry-dependent values are
missing with a localized reason. Skin entry is explicitly described as a
sampled planning-envelope intersection, not an intraoperative measurement.

Coordinate units are mm. The saved coordinate-system identifier is retained:
explicit `patient_world_lps` is described as LPS; legacy `patient_world_mm`
is not silently asserted to have a known LPS/RAS convention. No Viewer
rotation/flip is applied to patient coordinates.

## 5. Persistence, ownership, and presentation

`implantPlan` and `oarDoseOrdering` are structured report-form fields;
numeric source data is persisted rather than translated strings. Rendering
localizes labels, explanatory notes, geometry flags, coordinate descriptions,
and missing-entry reasons according to the report/global language.

The backend and frontend legacy direct-form allowlists include both new
fields. Metadata-only merges retain them; full-form saves normalize them
under `report.form`. Both legacy and current nested snapshots are covered by
round-trip tests, preventing a case switch from silently losing the schedule.

The shared builder checks planning ID, manual geometry revision, and geometry
signature again before returning. The API accepts optional expected planning
ID/revision fields and returns a conflict rather than a mismatched patch.
Frontend autofill also fences its response by case, form object, planning ID,
and available geometry revision. A direct tool with an explicit agent does
not switch to a different agent on failure.

The implant sections use separate stable flow keys per needle. Measured A4
pagination preserves all rows, repeats table headings and the owning needle
caption, and renumbers sheets. Needle headings and endpoint summaries are
kept with the first seed-table fragment rather than stranded on an earlier
sheet. Detail tables use 9 pt text with explicit, matching screen/print line
height, wrapping coordinates and structure names instead of shrinking text.
Actual PDF export prints report sheets only, not the editor panel. HTML,
PDF, and Markdown carry the same tip-reference definition and row data.
HTML output escapes structure/needle/seed text.

## 6. Validation and limits

Targeted numerical/browser tests cover complete organ retention, explicit
units, zero versus missing values, sourced exact-name criteria, EQD2/BED
non-comparability, manual-empty authority, invalid/duplicate/unassigned
records, signed tip distances, unsnapped actual positions, physical CT entry
sampling with anisotropic spacing and rotated direction, revision conflicts,
direct-tool ownership, manual report edits, language switching, HTML
escaping, and real Chromium PDF pagination.

The synthetic layout case contains 55 organ rows and 63 seed records across
three needles plus an unassigned record. The two OAR metric tables retain
110 rows in total; all 63 seed records must appear. PDF text extraction and
DOM layout assertions check terminal rows, repeated headers, no overflow,
and correspondence between printed sheets and the approved preview.

### 6.1 Reproducible evidence and scope

The isolated checkout used the same working source as the LAN baseline,
including the pre-existing Analysis/DVH changes. The Python runtime was
`/home/lht/.conda/envs/brachytherapy/bin/python`; real Chromium was used for
the browser cases. This is product regression validation, not a benchmark
evaluation or clinical validation.

- Complete product Python suite on the final isolated source:
  **2,946 passed, 2 skipped, 4 subtests passed**, in 172.33 seconds.
  The skips are the optional public HTTP dependency suite and a real NGINX
  proxy validation requiring `NGINX_TEST_BINARY`; neither is a report-table
  case. There were 31 existing SWIG/datetime deprecation warnings.
- Numerical/API/persistence tests: 21 passed. The API case retains real
  authentication and CSRF handling in an isolated temporary runtime; it
  substitutes only that test app's synthetic agent provider.
- Browser cases: eight tests cover actual report scripts and production
  screen/print CSS, English/Chinese export, editing, injection escaping,
  ownership fences, and all table rows. Both synthetic PDFs contain 13 A4
  sheets, 55 organ records, and 63 seed records. Print-window assertions
  check that data rows remain above the footer; rendered PNGs were visually
  inspected, not merely text-extracted.
- Nine standalone JavaScript checks passed: caption language, capture
  diagnostics, dose-answer integrity, renderer restoration, planning state,
  read-only capture, workflow completion, workspace presentation, and
  workspace restore ownership.
- Obsolete product-test assertions for the top-12 organ cap, old table
  prechunking, and old base-page count were replaced with the new complete
  table contract. Physical-dose or geometry acceptance was not relaxed.

Known limits of the supplementary JavaScript checks are disclosed separately:
`tests/test-report-lifecycle.cjs` fails its line-15 assertion on the unchanged
baseline editor as well as the updated editor; its synthetic context does
not supply the state now required by the existing capture contract. That
unrelated standalone baseline test was not changed or counted as passing.
`tests/report-hidden-viewer.test.cjs` was not run because the standalone Node
Playwright package is absent; the eight Python-Playwright browser cases above
did run with real Chromium. No real patient, live report, GPU inference,
independent dose validation, or server restart was used for these tests.

### 6.2 Delivery controls

The selected delivery covers 16 existing/new source, test, and documentation
files. Every existing selected file must still match its captured baseline
SHA-256 before replacement; HEAD must remain
`7f1fd13ca626e7d68dafe3a657fc1030514f9164`. A concurrent edit aborts delivery.
Unrelated files are not copied, reset, or removed. Replacement is atomic per
file, with the HTML asset entrypoint written last and a private mode-0700
backup of originals plus a before/after hash manifest retained under
`/tmp/brachybot-report-tables-backup-20261008-*`.

Final syntax, hash, diff, and installed-checkout regression checks must be
performed after delivery. A code/test pass does not mean that the running
Python server has already reloaded the new handler.

Useful targeted recheck (with the existing Node executable on PATH):

```bash
cd /home/lht/snap/brachyplan/BrachyBot
export PYTHONPATH=.
export BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan
export SAT3D_ROOT=/home/lht/snap/brachyplan/SAT3D
/home/lht/.conda/envs/brachytherapy/bin/python -m pytest \
  tests/test_report_plan_tables.py tests/test_report_plan_tables_browser.py \
  tests/test_workspace_store.py tests/test_workspace_frontend.py \
  tests/test_report_capture_and_progress.py tests/test_report_two_column_layout.py \
  tests/test_report_pagination_contract.py -q
```

## 7. Activation

Only the LAN checkout is updated. The independent public-release checkout,
its runtime, and its process are not modified. No commit or push is made.
Existing unrelated dirty-tree changes are preserved.

Python route/tool changes require the usual controlled LAN server restart;
frontend assets use updated cache versions. After activation, refresh the
browser and regenerate/autofill the current report. Existing stored PDFs
are not rewritten, and old stored reports do not acquire measurements that
were never recorded. No live patient report is regenerated by this change.
