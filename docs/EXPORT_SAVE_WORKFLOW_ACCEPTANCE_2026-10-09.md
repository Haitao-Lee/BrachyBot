# Export Save Data final acceptance

Date: 2026-10-09, Asia/Shanghai. Scope: LAN/debug BrachyBot only.

## Delivered behavior

Conversational export proposals and existing Input/Report/Guide/Data Tree/Session
export entry points use one Save Data chooser. It supports real catalog IDs,
exact names, groups, data types, structural exclusions, mixed per-type/per-object
formats, exact saved guide versions, editable filenames and folder/ZIP names.
An unresolved conversational scope does not default to the entire Session.
Unsupported formats and incomplete selections are not silently substituted.

The chooser requests a separate human confirmation. Native file/directory
access is used only when the browser supports it; otherwise browser downloads
are explicitly identified as downloads, not verified filesystem saves. Current
needles and seeds have actual patient-coordinate STL serializers. Folder mode
preserves the hierarchy and refuses existing subfolders before expensive file
generation. Browser report HTML/Markdown/JSON can also be written into a folder;
PDF uses the system Print/Save as PDF destination rather than pretending the
chosen directory handle controls a printer's output location.

The initial chooser receipt, cancellation, successful file close, download
request, print-dialog opening and failure are different outcomes. Late outcomes
update their original request trace. They cannot migrate into a new case or
silently replace another pending chooser. A refused sibling export is retained
in the final response. Report ownership is checked before serialization and
again before writing an asynchronously prepared browser report.

Case metadata remains readable during restoration, preserving Data Tree/Viewer
loading. Exports are sealed only after resource restoration completes; a partial
catalog cannot be presented as Export All. JSON retains NumPy arrays/scalars as
actual JSON numbers and arrays, and rejects NaN/infinite values. Markdown
formatting operates on a copy, preserving the operator's report state.

## Evidence

- Final isolated product suite: **3,222 passed, 2 skipped, 31 warnings,
  4 subtests passed**, 228.94 seconds.
- Final deployed-source export/report/capture subset: **121 passed**, 14.91 seconds.
- New export regression cases: **82**, including parametrized cases; not 82
  independent benchmark scenarios or a live-model accuracy estimate.
- All twenty selected source/test/audit-document files match the final manifest
  and the bytes used for the isolated validation.
- Final source passed `git diff --check`; changed JavaScript syntax checks passed.
- Top-router checks for six representative requests remained semantic proposals
  with no planning, guide-generation or report-regeneration grants.
- Native OS picker tests use simulated File System Access handles. Actual
  Chromium tests cover rendering, selection, focus, keyboard, downloads, timers,
  trace receipts and cancellations. Actual serializers are decoded and checked
  against synthetic source geometry/dose. No paid provider call, real-patient
  inference/planning, report recapture or guide regeneration was performed.
- The two skips are public-origin and nginx/TLS deployment tests. These do not
  claim an external deployment was validated.

Evidence directory:
`/home/lht/.local/share/brachybot-export-workflow/validation-20261008-fgcn5N`.
It retains the initial and final manifests/full-suite XML, delivery records,
initial/final activation records and the read-only route verification.

Initial recovery copy: `/tmp/brachybot-export-backup-20261008-jken3cyd`.
Follow-up recovery copy: `/tmp/brachybot-export-followup-backup-20261009-wsfav36q`.
Both recovery directories are private, mode `0700`.

## Runtime activation

- Final LAN listener: PID `3057073`, `192.168.1.113:8080`.
- Working directory: `/home/lht/snap/brachyplan/BrachyBot`.
- `/api/healthz`: `ok=true`; final JS asset: HTTP 200, `Cache-Control: no-cache`.
- No running case or valid editing lease existed before the controlled restart.
- No force termination was used. Normal shutdown/startup may checkpoint existing
  workspace state; this is not a clinical plan/report mutation performed for testing.
- Independent public listener remained PID `2878061`, `127.0.0.1:18082`.
- No commit or push was made; the public-release checkout was not modified.

Refresh an already-open page to load the new frontend. The existing trusted-LAN
HTTP configuration is unchanged. Native filesystem access may be unavailable
on an insecure LAN origin; the explicit download/ZIP fallback remains available.

## Boundaries

Formats are supported per registered data type, not arbitrary suffixes. The
Session output is a selected-available-data exchange bundle, not a complete
native application backup or Slicer MRB restore format. It does not include
credentials, model weights, the service database or all hidden historic planning
runs. STL files use LPS/mm but are not manufacturing/clinical approval. Linked
DICOM-RT requires matched geometry and verified seed ownership; unsupported or
ambiguous grids fail instead of receiving invented registration. A printer or
download request does not prove a final saved file. Browser/OS and real-case
interactive acceptance are distinct from these automated contract tests.

See [the design audit](EXPORT_SAVE_WORKFLOW_AUDIT_2026-10-08.md) for supported
objects, codec choices, directory layout, security and interaction details.
