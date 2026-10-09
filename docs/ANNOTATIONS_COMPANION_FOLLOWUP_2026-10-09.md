# Distance annotation companion follow-up

## Why this follow-up was needed

The initial distance-annotation feature was delivered and tested but the LAN
daemon had not been restarted because one case still held a valid editing
lease. A fresh preflight for this continuation confirmed the same live process
and busy editing condition. Source delivery is not online activation.

The follow-up also examined the companion behaviour beyond its first display
and found two actual lifecycle gaps:

1. The general workspace presentation index stores annotation records under
   the `annotation` family. The new distance setters used
   `planning_annotation`. Reads could sometimes recover through a global ID
   fallback, but writes did not update the indexed record. A late reload could
   consequently reapply older preferences. Furthermore, an already-inserted
   default annotation masked a saved preference because the code selected the
   local record instead of merging the indexed presentation.
2. The shared `_applyAuthoritativeManualSeeds` commit handler updated committed
   seed/needle geometry but did not refresh derived distances. Old distances
   were correctly suppressed by the geometry/version fences, but updated ones
   could remain absent until another full Viewer reload.

## Repair

- Resolve and update the existing `annotation` presentation family by stable
  annotation ID/Object ID and explicit Session identity.
- Merge indexed presentation over a local placeholder. Individual and batch
  visibility edits update that same authoritative index so a later resource
  load keeps the new preference.
- After a server-confirmed manual geometry commit, refresh distance records
  through the existing authenticated, read-only endpoint once. Pointer-move
  previews still launch no annotation reads, and stale geometry stays
  suppressed. No dose computation, replanning, guide generation or report
  capture is added.
- Retain all existing manual measurements, structured artifact organization,
  numerical mm reference, global language, guide-version fencing and source
  ownership checks.

## Additional tests

Four regression cases use the actual workspace presentation lookup/write
functions and the production manual-commit handler, not an alternate executor:

- Saved hidden/colour/opacity state wins over a default placeholder, and live
  edits update the real index.
- Batch hiding remains hidden after a late packet reload.
- An index from another Session cannot supply current-case preferences.
- The authoritative manual-commit path requests updated distances once and
  retains unrelated manual measurements.

The distance browser suite passed **25 tests** after these changes. The initial
test harness had included a presentation constant twice when extracting a
function plus its following declarations; the harness was corrected to extract
only the production function body. No product validator was relaxed.

Final complete-regression and deployed-specialty results are stored alongside
the follow-up manifest in the private validation directory. The prior 3,302
pass result remains initial-delivery evidence, not evidence for untested later
edits.

The final full regression for this follow-up passed **3,306 tests with 2 skips,
31 warnings and 4 passing subtests**, in 234.98 seconds. An independent synthetic
before-control loaded the previous delivered browser implementation without
changing product files: saved `visible=false`, colour `#123456`, opacity `0.35`
were incorrectly displayed as visible, colour `#fde68a`, opacity `1`. This
confirms that the restored-placeholder counterexample was a real product
regression rather than a hypothetical concern. The corrected implementation
passes the corresponding real-index browser test.

## Online loading

Save and close all active BrachyBot case pages before controlled LAN-only
activation. The helper checks the exact listener/cwd, running task count and
unexpired editing leases. It sends no signal while either is nonzero and never
uses a forced kill. The public-release checkout and its listener remain out of
scope. After activation, refresh the page and load the case resources; the
normal planning/guide Viewer lifecycle creates the companion labels without
requiring another plan or guide generation.

## Post-delivery result

The deployed-directory combined annotation/artifact/export suites passed
**91 tests** in 19.66 seconds. The controlled activation helper was then
invoked again and stopped at its preflight: zero running case tasks, one
unexpired editing lease, LAN PID 3087921 and public PID 3063784 unchanged.
No stop signal was sent. The new source is delivered, but online backend
activation remains pending until the active editing pages are saved/closed.
