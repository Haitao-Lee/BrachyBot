# Structured Data Tree for artifacts and annotations

## Problem and root cause

The screenshot accurately shows a flat dump of report form data, report
figures, original captures and annotated derivatives. Artifact hydration used
list-index node IDs (`artifact_1`, etc.), so adding/removing an image could also
change another image's presentation identity. The catalog attached the active
Planning ID to every item, including old/unknown captures; that is not evidence
of capture ownership.

## New hierarchy

```text
Artifacts & Annotations
  Planning annotations
    Guide mouths · From needle tip · vN
      Needle 1 → Guide mouth distance
    Seeds · From needle tip
      Needle 1 → Individual seed distances
  Manual measurements & prompts
    Line measurements
    Angles
    Rectangle measurements
    SAT3D prompts
    Other manual annotations
  Reports & figures
    Report data & files
    Current planning figures / Other planning figures / Unrecorded ownership
      Figure 1 → (a), (b)
      Figure 2 → (a), (b), ...
  Chat captures · By request
    Capture record · capture time
      3D Viewer / Data Tree / other capture view
        Annotated image
        Original capture
  Other saved attachments
```

Empty categories are omitted. Capture records are ordered newest first; source
and derived files stay independently addressable/exportable/deletable. A file
without reliable metadata remains in Other saved attachments, not falsely
assigned to a clinical view or request. No existing file is moved or deleted.

## Source relationships and stable identity

- Catalog metadata is projected from the Session-owned chat attachment
  registry, then message attachments for legacy recovery. It records request,
  message, capture source ID, original/annotated variant, view, capture time,
  original Planning ownership and version, where actually available.
- Explicit foreign attachment ownership and foreign Session screenshot URLs
  are not used. Raw user question text is not copied into the catalog simply
  to label a folder.
- A narrow legacy fallback recognizes only the application's generated
  `chat_screenshot_<id>` / `annotated_chat_screenshot_<id>_<hash>` naming
  convention. Arbitrary filenames are not assumed to have a parent capture.
- Artifact Data Tree IDs now derive from stable server Object IDs, not list
  positions. Changing sort/order does not change the selected object.
- Old/unknown capture Planning IDs are no longer overwritten by the active
  plan on listing. A previously broad test asserted that every item belonged
  to the current plan; that assertion was updated to this source-owned contract
  and an independent historical-capture regression was added.

## Interaction and persistence

A search input matches readable labels, source filenames, needle/seed IDs,
figure numbers and capture/reference identifiers. Search opens matching paths,
shows a match count and preserves the actual leaf Object IDs. Original long
filenames remain in tooltips and search without dominating every visible row.
User aliases stay searchable beside filenames.

Fold/search preferences are stored under the existing case-owned Data Tree
presentation (`artifactBrowser`). Workspace restore copies them independently
of clinical arrays, and case reset clears the prior case's browser state.
Global language events relocalize categories, variants, search and known
standard report figures; custom labels are retained, not guessed/transformed.

Group context menus export exactly the group's descendants, not the entire
Session. Nonvisual report/capture groups do not advertise dead 2D/3D, colour
or opacity operations. Automatic annotation groups offer Show/Hide and Export,
not destructive deletion; deleting a mixed selection that includes derived
distances is rejected before the mutation. Manual measurement Undo/clear and
ordinary artifact deletion keep their existing executors.

## Scope and verification

This is a durable semantic index and presentation hierarchy, not an on-disk
folder migration. Existing server Object IDs, URLs, file serializers, quota
transactions and deletion targets stay intact.

Tests cover registry/legacy pairing, original capture ownership, cross-case
references, no file mutation, real DOM classification, no duplicate leaf IDs,
search, exact group export, persisted expansion, locale, generated annotation
menus and user-string escaping. All evidence is synthetic, not inspection or
modification of a real patient's data.

The related numerical/display contract is documented in
`PLANNING_DISTANCE_ANNOTATIONS_2026-10-09.md`. Final suite/delivery/activation
results are recorded in the private task evidence and the acceptance section
below; source delivery must not be confused with a running Python daemon
having loaded the new modules.
