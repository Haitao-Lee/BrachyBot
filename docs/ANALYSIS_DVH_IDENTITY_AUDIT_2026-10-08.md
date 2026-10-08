# Analysis DVH identity and completeness audit — 2026-10-08

## Scope and outcome

The user's Analysis screenshot showed anatomical metric rows replaced by
`Unmapped structure (label N)`, despite named Data Tree structures and named
DVH curves. This was a real presentation-contract failure, not evidence that
the segmentation had disappeared. The LAN checkout is
`/home/lht/snap/brachyplan/BrachyBot`. The independent release is out of scope.

This change aligns current Data Tree, Analysis curves, legends and metric-row
presentation by stable structure identity. It also audits completeness against
the classified CTV/OAR Structure Set and supplements missing curves from saved
dose. It does not rerun inference, replan, modify source masks, overwrite
clinical plan metrics, or declare clinical approval.

## Confirmed root causes

1. `_resolveOARDisplayName` treated `label_id` as a reason to discard an already
   meaningful metric key. Missing asynchronous metadata then converted `brain`
   and other valid names into unmapped placeholders. Tree matches and saved
   names now precede unknown-label fallback.
2. `_getOrganColor` used name substring matching, which can confuse laterality
   or similarly named structures. The new resolver uses object ID, typed label
   identity, or an unambiguous exact normalized name. Numeric CTV/OAR labels
   belong to different namespaces; an explicit stale object ID is not joined
   to a recycled numeric label.
3. DVH render signatures contained dose arrays and prescription, but not
   structure presentation. Color changes did not invalidate the chart.
   Signatures now include name/color/identity, and tree rendering schedules a
   coalesced, case-fenced presentation update without dose or mesh requests.
4. A color update reset a manually zoomed Plotly view. Presentation-only
   redraws now preserve ranges and use stable trace identities.
5. Payload normalization stripped structure metadata. Nested/direct curves
   now retain their object ID, classification, label and display name.
6. Legacy curve dictionaries are keyed by names and generally contain a
   union CTV curve, not every CTV child. Duplicate names and even an OAR named
   `CTV` can overwrite distinct objects. Rendering every dictionary entry is
   therefore not proof of Structure Set completeness.
7. Missing numeric table fields were rendered as `0.0`. Missing or invalid
   values now display `--`; measured zero remains `0.0`. Explicit volume
   fraction/percent declarations are respected. The name column has a usable
   minimum width and retains full-name tooltips.
8. The report's offscreen fallback independently used raw dictionary keys
   and name-based palette lookup. It now uses the same metadata-aware name
   and color resolver. Existing static report images are not silently
   recaptured on every color adjustment.

## Read-only completeness service

`GET /api/planning/structure-analysis` is authenticated and rate-limited, and
uses the current case agent. The optional `planning_id` must match the active
plan. It returns identity-owned DVH, OAR metric rows, dose provenance and a
coverage inventory. Case/plan/input generations are checked before publishing
the derivative result. A single-entry per-agent cache and a per-agent lock
prevent repeated expensive sampling; derived results are not clinical-memory
writes.

The service uses the same CT-aligned label resolver as the Viewer. Registry
objects retain their own ROI masks: overlapping transport labels must not
truncate individual organ dosimetry. Legacy model source semantics distinguish
head/neck nodal GTV from pancreatic embedded anatomy.

### Inclusion and identity

- Every nonempty, classified OAR and CTV object is inventoried independently.
- Multi-target CTV has one curve per target plus a separately identified union.
- A single-target CTV reuses the existing union curve without a duplicate.
- OARs are not limited to a top-N subset or traversability category.
- Duplicate names, shared numeric CTV/OAR labels, reserved names and recycled
  transport labels do not merge distinct object identities.
- Unclassified uploaded/preview masks, skin, seeds and guide meshes are not
  clinical CTV/OAR and are excluded from the denominator. Promote an uploaded
  mask to CTV/OAR before expecting a clinical DVH.
- Missing or stale dose is explicitly unassessed, never fabricated as zero.

### Dose and metric provenance

Valid saved curves and existing numeric OAR metrics are retained. Missing
curves/metric fields are derived from the saved normalized dose converted by
the persisted Gy calibration, resampled to the CT grid through the existing
physical-geometry resolver when needed. A physical-Gy-only snapshot follows
the same existing display-unit conversion contract. Supplemental fields are
marked with `computed_fields`; the source curve basis is included in coverage.
This is additional evaluation of the same saved dose, **not independent
TG-43/Monte Carlo validation**. Existing plan scores and target scalars are not
overwritten by this display-completion service.

Supplemental curves use cumulative `dose >= threshold` counting, exact Rx
anchors when the physical Rx is known, and a single sort plus `searchsorted`.
Volumes and Dxcc use CT physical voxel volume. Non-finite/negative dose,
incompatible geometry or mid-computation input changes are rejected/marked
unavailable. A stale baseline can remain a clearly stale reference, but does
not generate current missing curves.

## Client lifecycle and UX

- Analysis activation, planning-result delivery and manual dose refresh request
  completeness in the background, without rebuilding meshes or blocking the
  existing chart. Duplicate concurrent client requests are coalesced.
- Network completion is fenced to case ID, viewer generation, planning ID and
  the owning metrics object. A response from another case/revision cannot
  repaint the active Analysis.
- A quiet, globally localized status line displays available/expected CTV/OAR
  curves, distinguishes stale/incomplete/unverified results, and exposes omitted
  objects in a tooltip. It does not claim completeness from dictionary size.
- Color/name changes only repaint presentation; global language changes use
  the existing `i18nchange` event. Curves remain independent of 3D hide state.
- Every supplied curve is rendered, including zero-dose structures. The
  existing default 0–400 Gy viewport is preserved; the underlying tails are
  retained and are not a top-N/data truncation.

## Verification

Tests use synthetic CT/masks and real headless Chromium with the vendored
Plotly library, not patient data, paid providers or GPU inference.

Initial implementation: 33 new tests passed; complete product regression:
2905 passed, 2 skipped, 4 subtests passed. Final validation after additional
API/unit/grid, ROI-overlap, reserved-name and report-fallback cases is recorded
below after completion. A skip is not claimed as a pass.

Final isolated validation on the complete patch:

- New targeted tests: **45 passed**, 3 dependency warnings, 27.01 seconds.
- Complete product `tests/`: **2917 passed, 2 skipped, 4 subtests passed**,
  31 warnings, 153.37 seconds. The skipped tests and dependency/deprecation
  warnings are not counted as successful checks.
- Logs: `/tmp/analysis-final-targeted-20261008.log` and
  `/tmp/analysis-final-full-tests-20261008.log`.
- Validation checkout: `/tmp/brachybot-analysis-audit-20261008-s2bhos`.

The earlier MPR repair was committed concurrently as
`7f1fd13ca626e7d68dafe3a657fc1030514f9164`. Before delivery, all six existing
selected source files were independently confirmed to still match their
original before-SHA-256 values. The checked delivery manifest uses this current
HEAD and preserves that repair; it does not relax a changed-source guard.

Important checks include named metrics with missing metadata, exact color
identity, CTV/OAR shared labels, meaningful unknown names, laterality,
individual/group color executors, metadata arriving late, preserved zoom,
global localization, >53 curves, real zero versus missing values, old-case
network replies, direct/nested curve metadata, physical calibration across
all supported dose aliases, ROI overlaps, cache generation/geometry changes,
no clinical-memory writes, mismatched-plan rejection, and incomplete mask
sidecar hydration. Dose loading before masks cannot claim a partial Structure
Set is complete; existing results remain available with unverified completeness.

## Deployment and limits

Existing unrelated working-tree changes and the previous MPR repairs must be
preserved. Delivery uses baseline/after SHA-256 checks and a recoverable backup.
No commit, push, public-release edit or automatic server restart is part of
this patch. Backend endpoint availability requires a safe LAN server restart;
the changed versioned JS assets then require a browser reload.

Synthetic regression proves the exercised contracts, not a live patient's
clinical correctness or universal freedom from display bugs. Cold completion
cost depends on CT size and missing structures; warm requests are cached.
