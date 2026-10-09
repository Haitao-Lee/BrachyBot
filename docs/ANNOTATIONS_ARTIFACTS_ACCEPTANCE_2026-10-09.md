# Annotation and artifact hierarchy acceptance

## Delivered result

Both requests were implemented together: version-owned 3D needle-tip distances
for seeds/guide mouths, and a structured searchable artifact/annotation tree.
Units are mm. The implementation, definitions, ownership checks and limits are
documented in:

- `PLANNING_DISTANCE_ANNOTATIONS_2026-10-09.md`
- `STRUCTURED_ARTIFACT_TREE_2026-10-09.md`

The initial authoritative checkout was
`b8f188659a6d890e260487deb0fa736a9ca51409` with the prior report-restoration fix
already uncommitted. That prior work was retained. Only 21 selected files were
delivered after before/after SHA256 and tested-stage verification. No commit or
push was created, and no public-release file or process was modified.

Private backup:

`/tmp/brachybot-distance-annotations-backup-20261009-kh2za8mh`

Private validation evidence (mode 0700):

`/home/lht/.local/share/brachybot-distance-annotations/validation-20261009-61B8i2/`

It contains the 21-file manifest, delivery record, full/deployed JUnit evidence,
synthetic visual QA and the activation preflight. This acceptance note is an
additional documentation-only file, not one of those 21 tested source files.

## Validation

- Final full `tests/`: **3,302 passed, 2 skipped, 31 warnings, 4 subtests
  passed**, in 236.29 seconds. JUnit reports 3,308 tests because skipped tests
  and subtests are included in that XML count; it is not a contradictory pass
  count.
- Deployment-directory combined specialty regression: **87 passed** in 18.49
  seconds, including the new numerical/browser/ownership tests and existing
  export/annotation transaction tests.
- The new families add 63 test cases relative to the 3,239-pass report-fix
  baseline. Earlier development iterations and fixture errors were repaired;
  no product validator was relaxed to hide a failure.
- Python compilation, changed-JavaScript syntax checks and `git diff --check`
  passed. The guide/physics kernels and their frozen latency dependencies were
  not modified.
- Visual QA used real Three.js camera projection and production DOM leaf
  renderers in Chromium with synthetic geometry and the existing theme styles.
  Dark/light token inheritance, locale, label-box fitting, dense overlap
  expansion and exact group export were tested.
- A bounded synthetic 181-record overlay micro-profile measured a median
  1.90 ms / p95 3.30 ms for the label pass in that local headless environment.
  It is not end-to-end clinical workflow latency or a performance guarantee on
  the user's machine. Nine labels were individually placed in that tightly
  overlapping test view; 172 were explicitly clustered and all 181 remained
  available in the expandable list.

No real-patient plan, dose inference, guide regeneration, paid model request,
clinical/manufacturing validation or full human usability study was run.

## Online activation is pending

The post-delivery read-only preflight found:

- Running case tasks: **0**
- Active editing leases: **1**
- LAN listener: PID **3087921**, `192.168.1.113:8080`, authoritative LAN checkout
- Independent public listener: PID **3063784**, `127.0.0.1:18082`, unchanged

The activation helper stopped before sending any signal. Therefore the source
is delivered and tested, but the existing Python daemon is **not** claimed to
have loaded the new routes or the preceding report-reader repair. New frontend
assets alone are not end-to-end activation evidence.

Save and close the active editing page, then repeat the idle preflight and
controlled LAN-only activation. There is no forced termination path. After
activation, refresh the browser and allow the current case's resources to load.
Existing plans receive companion annotations from the normal Viewer load;
there is no need to replan or regenerate a current guide solely to get labels.
Missing/invalid/old unmatched source geometry remains explicitly unassessed.
