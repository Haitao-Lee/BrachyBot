# Planning and guide distance companion annotations

## User-facing contract

- Distances use **mm**, not metres. The user's phrase meant distance rather
  than a mandatory unit.
- Saved seed centres are annotated by signed axial projection from needle
  tip, consistent with the implantation report. Actual centres are not snapped
  to a line. Negative distances and off-axis geometry remain recorded.
- Guide labels refer to the generated primary sleeve's nominal **outer mouth
  axis centre**, not skin entry or the external drag handle. Its construction
  is `skin_entry - inward * (skin_clearance + plate_thickness + sleeve_outward)`.
  The label is construction geometry, not independent mesh metrology or a
  manufacturing/clinical acceptance claim.
- The companion is read-only. It never replans, recomputes dose, generates a
  guide, captures a report, or calls a model. Existing completion/restore Viewer
  loads deliver the numerical records; guide load refreshes the selected
  version's annotation packet.

## Ownership and invalidation

Each record has a stable annotation ID, source object and owning needle,
trajectory, Planning ID/version, guide version where applicable, physical
anchor/tip/external points, distance reference, unit and source definition.
The endpoint is authenticated and case scoped. Planning geometry and guide
identity are fenced across computation; changed-source replies are rejected.

The browser additionally fences session, Planning ID/version, current saved
needle endpoints, seed position, mesh drag preview and displayed guide version.
It clears overlays on case reset. Old, missing, malformed, duplicate or ambiguous
geometry is not replaced with invented coordinates. Selected historical guide
versions can have labels only when they still match the current saved needle
geometry/revision; otherwise they are not represented as current distances.

## Presentation and persistence

The records join the existing durable `viewer.annotations` and corresponding
Data Tree annotation records. Manual Line/Angle/Rectangle/SAT3D records are kept
intact. Automatic updates wait for an in-flight manual annotation save, and
are flushed after that transaction finishes. Identical source packets do not
repeatedly schedule workspace saves.

Data Tree hierarchy:

```text
Artifacts & Annotations
  Guide mouths · From needle tip · vN
    Needle 1
      Guide mouth                 50.0 mm
  Seeds · From needle tip
    Needle 1
      Seed 1                      15.0 mm
      Seed 2                      20.0 mm
```

All generated leaves default to enabled. Every leaf has individual Show/Hide,
3D visibility, opacity and colour; aliases do not change numerical values.
Source geometry is not editable through annotations. A right-click on only
automatic distances offers Hide, not deletion of source data. Mixed selections
containing automatic distances cannot masquerade as one destructive delete.
Manual measurement deletion/Undo and measurement-clear retain their existing
contracts. Distances are 3D annotations; an unsupported 2D show request is not
reported as successful.

Current-case preferences persist via the existing workspace/presentation
mechanisms. Stable source IDs retain preferences across reloads; a new guide
version receives its own IDs. Open Data Tree branches remain open across a
visibility/colour update.

The overlay uses 13 CSS-pixel, weight-700 text, a high-contrast dark background,
warm seed accents and cyan guide accents, real projected anchors and leaders.
It avoids label-box overlap, the orientation indicator and dose scale. All
records remain enabled in a dense scene; labels that cannot fit are represented
by one explicit expandable overflow control, rather than silently omitted or
drawn on top of one another. The list contains every leaf and independent
visibility controls. Selecting a label marks its actual needle axis and seed
anchor without changing geometry, materials or camera pose. Global `i18nchange`
relocalizes generated text; values and mm units do not change.

## Implementation

- `web/planning_distance_annotations.py`: pure numerical projection and
  version-owned read packet; no migration or planning activation on a read.
- `/api/planning/distance-annotations`: authenticated read endpoint; optional
  positive `guide_version` resolves an explicit saved version.
- `/api/planning/seeds_3d`: includes the companion packet for exactly the
  published seed/needle geometry.
- `brachybot-planning-distance-annotations.js` and its CSS: presentation,
  decluttering, selection, ownership and preference management.
- Existing Viewer, guide, Data Tree, UI and manual-annotation entry points:
  narrow lifecycle/presentation hooks only.

The previous report-restoration fix is preserved. No guide/physics kernel,
5-mm cropping rule, model dependency, authorization policy or public-release
checkout is changed.

## Validation and limits

Validation uses synthetic data and the actual Three.js projection, production
Data Tree handlers, workspace artifact encoder/decoder and authenticated API.
It covers numerical units/reference, rotated world geometry, malformed and
ambiguous inputs, stable identities, guide versions, defaults, individual/batch
visibility, opacity/colour/alias, source hiding, drag previews, case changes,
late replies, save serialization, locale, dense layout, expansion and selection.

The first broad development snapshot passed **3,276 tests with 2 skips**. Final
post-refinement regression and deployment results are recorded in the delivery
evidence. This is not a real-patient clinical, manufacturing, physical metrology
or full operator-usability validation. Dense-scene decluttering is explicit:
"enabled" does not mean hundreds of overlapping labels are all drawn at once.

Refreshing an already-open page is needed to load the new frontend assets;
the backend process must also load the updated route. No unsafe restart is
performed while case editing or planning is active. Deployment/activation
status is point-in-time evidence, not an assumption from HTTP 200 alone.
