# Unified conversational export and Save Data workflow

Date: 2026-10-08 (Asia/Shanghai). Scope: LAN/debug BrachyBot checkout only.

## Outcome and original defects

The product already had a hierarchical Session export catalog, an asynchronous
export worker, private quota-controlled staging, and a browser directory/ZIP
dialog. It did **not** have a coherent conversational Save Data capability.
The provider boundary admitted UI actions only when a local resolver produced
an identical action signature. A semantically valid generic export proposal
could disappear. Report, guide, seed STL and Session actions used different
executors and different completion semantics. The existing scene catalog only
offered JSON for needles and seeds. The old Input STL button exported seeds,
not both current needles and seeds. PDF printing was incorrectly labelled
"Saved PDF" although the browser cannot observe the user's final save decision.
The old scene export path also accepted a reduced subset of malformed/stale
selections without notifying the caller, lacked editable leaf filenames, and
could overwrite an existing local directory tree.

The repair is a capability and receipt contract, not a table of user sentences.
The primary model interprets the complete request and proposes structured
selectors. Existing clause-local question, negation, quote, condition and
completed-action guards still apply. The chooser never performs a clinical
mutation or generates export files without a separate human browser gesture.

## Shared public capability

`ui_controller` accepts `target=data.export`, `command=run`, with an object value:

```json
{
  "data_types": ["needle", "seed"],
  "format": "stl",
  "bundle_name": "Implant-models",
  "filenames": {"needle:needle_1": "Needle-one.stl"}
}
```

Selectors include `all`, `object_ids`, `group_ids`, `data_types`, and exact
`names`. `guide_version` selects an exact saved guide and never promotes it or
substitutes the current guide. Historical guides obey the same lifecycle and
QA checks as the existing guide exporter. Object/group identities come from the actual catalog; no fuzzy match
can silently pick a nearby structure. `all=true` is incompatible with subset
selectors. Unknown keys, paths and automatic-confirmation flags are rejected.
Missing or ambiguous objects leave the chooser unresolved rather than turning
into Export All. Unsupported formats remain visible and unselected until the
operator explicitly chooses a supported format. Formats are capabilities of
each object, not merely filename suffixes. The server rejects the entire
malformed selection rather than executing its apparently valid rows.

`report.export` is retained as a compatibility capability and opens the same
chooser. Existing Input Report/STL/DICOM-RT, Report PDF/HTML/Markdown/JSON, guide
STL, Data Tree node/group export and Session context-menu entry points converge
on the Save Data UI. Export does not imply report autofill, guide regeneration,
dose recomputation, or planning. The current-turn execution boundary exempts
only a batch entirely composed of chooser-opening actions, never arbitrary or
mixed UI mutations. Questions about export do not trigger the chooser.

## Supported data and formats

| Data | Supported exchange formats | Important contract |
| --- | --- | --- |
| CT, CTV, OAR, generic/uploaded-mask child, skin mask | NIfTI; surfaces additionally STL | Verified CT geometry; mask semantics are retained by the catalog |
| Current needles and seeds | JSON and STL, per real object | Current committed patient LPS geometry, millimetres; manual plan preferred |
| Planning parameters | JSON | Current geometry and configuration, not a replan |
| Dose volume | NIfTI | Physical Gy, never normalized CNN numbers labelled Gy |
| Dose iso-surfaces | STL | Physical prescription thresholds |
| DVH values / curve | CSV, XLSX, JSON / PNG | Saved observed values, no new clinical conclusions |
| Current guide | STL | Current lifecycle, current bore-wall policy, validated closed mesh; stale/legacy guides fail explicitly |
| Current on-screen report | HTML, Markdown, JSON; PDF through Print/Save as PDF | No automatic autofill/recapture; separate from saved report artifacts |
| Existing report PDF / report state / figures | PDF / JSON / PNG | Existing owned Session artifacts |
| Linked DICOM-RT plan | ZIP containing RTSTRUCT/RTPLAN/RTDOSE | Reuses the existing exporter, physical Gy, explicit needle ownership, matched grids; research interoperability output requiring review |
| Chat, tool/trace history, annotations, Session UI settings | JSON; saved screenshots PNG | Current Session ownership, selected scope |

Needle STL reproduces the viewer's 0.28 mm display radius; this is **not** an
assertion of the manufactured needle diameter. Seed dimensions use the saved
seed configuration with existing display defaults (4.5 mm length, 0.4 mm
radius) where absent. STL does not intrinsically encode units, so the exchange
manifest records LPS and mm and marks these as viewer models rather than
manufacturing specifications. Multi-segment needle models contain closed
segment cylinders, not a newly optimized or fabricated surgical trajectory.
Non-finite coordinates, zero directions/lengths and invalid surfaces cannot
be exported as apparently valid models.

Linked DICOM-RT exports require all relevant source grids to match the CT
reference and every seed to have unambiguous channel ownership. They do not
guess a registration or silently resample. Format support is intentionally
explicit: arbitrary requested codecs are not promised. Neither STL nor
DICOM-RT file validity proves clinical suitability.

## Save interaction and completion semantics

Compound export requests can use one chooser with `formats_by_type` and
`formats_by_object`, for example dose as NIfTI and OAR surfaces as STL.
`exclude_object_ids`, `exclude_group_ids`, `exclude_data_types` and
`exclude_names` express omissions structurally, including Export All except
chat/history. An unresolved exclusion is not ignored. A later model proposal
cannot silently replace an already-open chat save dialog or the user's edits.

The dialog retains the real hierarchy and exposes checkboxes, object names,
formats, editable filenames, and an editable folder/ZIP name. Only the
requested objects are preselected; the rest remain available for deliberate
correction. Generated duplicate suggestions are disambiguated visibly.
Explicit duplicate destination names, reserved names, path traversal, suffix
mismatches and operating-system-invalid characters are rejected. Unicode
leaf filenames are supported.

1. **One selected object:** save the actual object file, not an unnecessary ZIP.
2. **Multiple objects:** download/save a hierarchical ZIP with its manifest.
3. **Folder mode:** the operator first chooses a directory; files go into a
   newly named child directory. An existing child directory is never overwritten.
4. **Secure supported browsers:** the confirmation click invokes the native
   save-file picker before asynchronous generation. Cancelling it starts no
   export job. Directory selection likewise requires a browser gesture.
5. **Unsupported/insecure browsers:** show an explicit browser-download/ZIP
   fallback. On LAN HTTP, the application cannot force arbitrary local paths or
   bypass browser restrictions. Enable HTTPS or the browser's ask-for-download-
   location setting if a system destination dialog is required.
6. **PDF:** the confirmation click opens a print window. The user chooses Save
   as PDF and a destination. Cancellation/printing cannot be reported as a
   verified PDF save. Existing PDF artifacts can instead be saved as files.

`awaiting_user_confirmation`, `print_dialog_opened`, `download_requested` and
successful writable-file close are different states. The trace keeps the
chooser pending and blocks dependent actions; the chat text explicitly says
that opening the chooser has not saved anything. A successful download request
is not proof of its final filesystem location. File/folder save failures do
not produce a success claim. Folder saves may leave already-written files if
cancelled mid-save, which is disclosed rather than hidden.

The operation has one busy owner, a live elapsed timer, generation fencing,
disabled mutable controls, cancellation during preparation/polling, and no
concurrent replacement dialog. Chat-originated delayed choosers are fenced to
their original active case. Browser report generation refuses a changed case.
Keyboard focus trapping, Escape, focus restoration, global locale changes,
shared theme tokens, privacy guidance and per-item failure details are included.

## Bundle structure, security and performance

Typical output:

```text
Implant-models/
  session_manifest.json
  Images/
  Structures/{CTV,OAR,Skin,AdditionalMasks}/
  Planning/{Needles,Seeds,Trajectories}/
  Dose/
  DVH/
  DICOM-RT/
  SurgicalGuide/
  Report/
  Figures/
  Annotations/
  Chat/
  Session/
```

Only selected available catalog data are serialized. The manifest records
actual filenames, byte lengths, SHA-256 hashes, source versions, planning
identity, coordinate convention, failures and skipped objects. Session UI
settings are included as an independently selectable object. This is a
**data-exchange bundle**, not a native full-workspace backup/import format. It
does not contain credentials, model checkpoints, the service database or all
historic hidden planning runs. No native restoration guarantee or Slicer MRB
compatibility is claimed. Source medical data and patient identifiers may be
present; the operator must choose an authorized storage/sharing destination.

Export jobs keep ownership checks, account quota transactions, retention,
bounded concurrency and server-owned staging. Downloads cannot read unfinished
job files. A bounded 10,000-object scene limit replaces the old 512-object
ceiling, which was insufficient for some otherwise ordinary seed-heavy scenes.
The operator sees failures rather than a truncated success.

A worker projects effective structure masks once, with source-version fencing,
instead of rebuilding every OAR volume for every exported object. No new intent
classifier, paid provider call, GPU inference or clinical downstream work is
added by opening or saving the chooser. Large data still require real I/O and
compression time; a fake progress percentage or latency guarantee is not used.

## Validation and deployment evidence

The companion activation record documents the final tested payload hashes,
test totals, backup location and LAN service activation. Tests cover real
provider-call normalization (synthetic primary proposals), rejected discourse
acts, strict options, filenames and selectors, actual STL round trips,
DICOM-RT linked objects and physical dose, quotas, report capture regressions,
and headless Chromium Save Data interactions. These are product-contract tests,
not a live paid-model semantic benchmark or real-patient clinical validation.
No real patient plan/guide/report is regenerated for acceptance.

The design borrows selection, format, filename and directory concepts from
[3D Slicer Data Loading and Saving](https://slicer.readthedocs.io/en/latest/user_guide/data_loading_and_saving.html).
Browser capability checks intentionally replace assumptions of desktop-native
filesystem access. No Slicer scene-format compatibility is implied.
