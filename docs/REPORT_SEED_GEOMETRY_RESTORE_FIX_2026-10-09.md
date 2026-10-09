# Report seed geometry after Session restore

## Scope and finding

The reported failure is real. The surgical report contained saved seed XYZ
positions but treated the owning needle axis as unavailable, leaving the tip
distance, axial spacing, axis offset and endpoint fields blank.

The defect is in the report's read-only geometry projection, not in PDF font
formatting or dose computation:

1. `web.workspace_store._restore_json` restores numeric JSON keys as integers.
   A persisted `verified_needle_geometry["0"]` becomes
   `verified_needle_geometry[0]` after decoding a Session checkpoint.
2. `web.report_plan_tables.report_snapshot` looked up only the string key.
   The Viewer already reads both string and integer keys. A restored case could
   therefore display the needle while its report claimed invalid geometry.
3. `build_implant_table` accepted only list/tuple endpoint containers, although
   the checkpoint artifact decoder also legitimately returns NumPy arrays.

Three added negative controls failed against the unmodified product code:
restored list endpoints, restored ndarray endpoints, and manual ndarray
endpoints. All three produced a null tip despite finite saved coordinates.

## Repair

- Read the current string-keyed geometry first, then the restored integer key,
  matching the Viewer's lookup precedence. A newer string-keyed canonical repair
  is not replaced with a stale integer-keyed record.
- Accept two-dimensional NumPy endpoint arrays as well as lists and tuples.
  Continue checking finite three-component points, nonzero axis length, unique
  ownership and signed projection geometry.
- Do not infer a missing needle tip from the seed cloud, substitute another
  planning revision, change seed positions, or modify the saved planning memory.
- Record `spacing_status` separately from the numerical spacing. The first valid
  seed nearest the needle tip has no preceding seed, so its spacing is
  `not_applicable_first`, not a fabricated zero and not a missing measurement.
- Render that first spacing as `N/A` / `不适用` in HTML/print and Markdown, with
  a localized explanatory note. Other truly unavailable fields remain `—`.

The distance convention is unchanged: the needle tip is zero; distance is the
signed projection from the tip back along the axis toward the skin. The report
sorts seeds by this distance. Axis offset is a perpendicular center-to-axis
distance; axial spacing is center-to-center spacing, not surface clearance.

## What can still legitimately be unavailable

- Skin entry requires the existing saved, grid-matching skin envelope. An
  external manipulation handle is not a skin-entry measurement.
- A missing, nonfinite or degenerate needle axis still cannot establish a tip
  distance. Duplicate/ambiguous ownership is not repaired by nearest-needle
  guessing.
- A previously exported PDF is immutable. This fix affects regenerated tables;
  it does not rewrite already downloaded files or silently replace a user's
  saved report edits.

For an existing report, refresh the page to load the updated script, wait for
the case resources, use **Report > Auto-fill**, inspect the position schedule,
and export a new report. **Refresh preview** alone only renders the already
saved form and cannot replace old null derived values.

## Validation

- Added 17 regression cases covering checkpoint encode/decode, list/tuple/array
  endpoints, string-key repair precedence, malformed/NaN/boolean/degenerate
  geometry, missing geometry without stale-baseline substitution, an
  authenticated restored-plan report API, and bilingual real-browser rendering
  with 12 numerically derived seeds.
- Targeted report suites: **46 passed**. The old suite's 21 backend cases also
  passed before applying the repair; the new negative controls independently
  demonstrated the missing coverage.
- Browser assertions check all 12 rows, known tip distances, zero offsets,
  adjacent spacing, skin/tip coordinates, insertion length, Markdown values,
  global language and table width. Existing long-table PDF tests additionally
  exercise repeated headers, row completeness, footer clearance and pagination.
- Visual review uses synthetic test reports only. No patient planning, dose
  inference, guide generation, paid model call, or clinical validation is part
  of this repair.

Full `tests/` regression with the existing remote Node.js runtime on PATH:
**3,239 passed, 2 skipped, 31 warnings, 4 subtests passed**, in 245.08 seconds.
Python compilation and the changed JavaScript's `node --check` also passed.
The first broad run lacked Node on PATH (one required-JavaScript test failed,
3,221 passed and 19 skipped). That environment issue was corrected without
changing the test or product code; both JUnit records are preserved.

The authoritative checkout baseline is
`b8f188659a6d890e260487deb0fa736a9ca51409`. Delivery checks each target's baseline
hash, saves a private backup, copies only the five listed files, and records
final source hashes and JUnit evidence under:

`/home/lht/.local/share/brachybot-report-seed/validation-20261009-uc8HE0/`

`delivery.json` records the backup and exact file inventory. `activation.json`,
when present, records the idle-case/lease preflight, the old/new LAN listener,
the unchanged public listener, health and served-JavaScript hash verification.
No forced termination, commit or push is part of this procedure.

Deployment-directory report regression also passed: **46 passed** in 18.73
seconds. Backend activation was deferred before sending any stop signal:
the aggregate read-only preflight found zero running cases but one active
editing lease; a second check found that lease was still being renewed.
At that check, LAN PID 3087921 and public PID 3063784 were unchanged. The new
source files are delivered, but the existing daemon is not claimed to have
loaded the new report reader. Save and close the editing page, repeat the
idle preflight and perform controlled LAN-only activation before accepting
new live report output as evidence. `activation-preflight.json` records this
point-in-time pending status without account or case identifiers.

## Changed files

1. `web/report_plan_tables.py`
2. `web/app/static/js/brachybot-report-plan-tables.js`
3. `tests/test_report_plan_tables.py`
4. `tests/test_report_plan_tables_browser.py`
5. This audit note.

No changes are made to checkpoint serialization globally, the planning/dose
engine, guide geometry, authorization policy, or the independent public-release
checkout. Numeric-key restoration remains necessary for existing label maps;
the consumer is repaired instead of weakening that persistence contract.
