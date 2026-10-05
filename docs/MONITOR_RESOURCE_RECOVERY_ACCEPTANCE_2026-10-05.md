# Monitor: precise recovery and late-resource acceptance

## Scope and status

This increment extends the calm coaching and closed-loop work rather than
replacing the Monitor engine. Its product goal is concrete: an operator should
not need to search forty needle IDs, repeatedly request a missing screenshot,
or guess whether an object is hidden or not loaded.

The LAN/debug checkout is `/home/lht/snap/brachyplan/BrachyBot`. The independent
public-release checkout and service are out of scope. No patient geometry is
changed as an implementation or validation step. Production login and an
operator-designated de-identified test case remain prerequisites for a real
case acceptance journey; browser fixtures are not substitutes for those checks.

## Verified source-level gaps

1. Failed focus previously returned a generic instruction to check Data Tree.
   It did not expose the exact row, distinguish loading from hiding, or offer
   a deliberately requested presentation-only recovery operation.
2. Image recovery used two bounded timer retries. If meshes became available
   after those retries, resource completion did not resume the same checkpoint.
3. Automatic helper placement requested every reference together. One missing
   object could suppress a useful marker on another already visible object.
4. A later delivery for the same checkpoint did not merge delivered-view
   metadata into its existing capture record.
5. Hiding a previously annotated object could leave its detached helper label
   and a past display-success notice visible. Live presentation must invalidate
   those, not merely stop claiming location in a text status.

These are engineering defects and interaction gaps, not evidence that a
particular patient plan or clinical outcome was incorrect.

## Implemented interaction contract

### Exact object recovery

- A/B/C remain stable across prose, Viewer helpers and image annotations.
  The availability projection distinguishes visible, hidden, loading,
  not-loaded, non-renderable and unavailable targets.
- **Find A/B/C in Data Tree** uses the existing live-row resolver followed by
  an additional exact identity check. History rows and similarly prefixed IDs
  are rejected. Only the row's ancestor groups expand; the row receives a
  keyboard-focusable outline and scrolls into view. Clinical selection,
  geometry, visibility, color and opacity are not changed.
- **Show and locate A/B/C** is offered only for an already loaded leaf hidden
  by its own visibility switches, with no hidden ancestor. It invokes the
  same `node_show` and `node_show_3d` executors as the UI command bridge.
  Success requires a fresh visibility observation and actual successful focus.
  Color, opacity and patient geometry are preserved.
- Hidden parent groups, transparent/non-renderable objects and missing meshes
  are not automatically revealed, recolored, made opaque, reconstructed or
  regenerated. The exact-row control remains the recovery route where useful.
- Display recovery is blocked while an image transaction or presentation-write
  lock owns the scene. No optimistic success claim is made.
- Availability is not spatial evidence. A visible or loaded object is not
  declared located until the existing patient-space anchor/in-frame checks pass.

### Resource-driven image recovery

`brachybot:monitor-resources-ready` is emitted after planning geometry is
loaded and when the active workspace visual-readiness transaction completes.
Partial completion also emits a progress notice without changing its failed
global-readiness status; only newly verified requested geometry can resume an
image, through the existing live-clinical-state and grounding guards.
It carries session ownership and, for planning geometry, planning ID/version.
Image transaction completion also checks for progress that arrived while busy.

The receiver coalesces notices for 120 ms and observes exact requested live
geometry, not a loading flag. It resumes a failed/deferred/partial current
checkpoint only if a newly available reference is observed. Identical readiness
events do not trigger repeated capture. This pathway is bounded to two
resumptions per checkpoint in addition to the existing two timer retries.

Case/session, Monitor run, planning ID/version, geometry, drag state, document
visibility, report-capture ownership and presentation locks remain mandatory
fences. A newer edit invalidates old recovery work. No regeneration, dose job,
model call or resource polling is introduced. Background completion waits for
foreground visibility; camera interaction waits for idle.

### Partial assistance and durable evidence

Automatic helpers may mark a verified visible subset while keeping the full
immutable A/B/C mapping. Missing letters are explicitly unlocated. Explicit
pair focus still fails closed unless every requested object can be located;
pair measurement lines still require both exact references and valid witnesses.

Delivered views for the same event merge into one capture record. Old image
versions remain labelled as old; text, current evidence status and attachment
delivery are not conflated. Resource recovery keeps the original chat/card ID.

The shared visibility and opacity-refresh executors now coalesce a
presentation-only invalidation. Helpers whose requested objects cease to be
locatable are disposed; display-success notices are cleared when their verified
availability changes. They are not left floating over a newly hidden object.
This invalidation does not take screenshots, change geometry or start GPU jobs.

### Presentation and performance

Recovery controls use the existing themes, bounded typography, keyboard focus,
touch affordances and global locale. No new modal, flashing notification,
full-screen overlay, duplicate advice engine or hidden GPU work is added.
The 80-edit repaint contract remains unchanged: at most 240 chat upserts,
40 retained cards and one retained retry timer in that regression scenario.

## Validation and limits

- `tests/monitor-resource-readiness.test.cjs` checks late completion after timer
  exhaustion, partial completion, duplicate notices, real geometry versus
  loading flags, wrong case/version, stale geometry, stop/drag cancellation,
  background deferral and explicit visibility-operation fencing.
- `tests/monitor-experience-browser.test.cjs` now includes hidden-object
  recovery in real DOM/Three.js: exact current row versus history/prefix aliases,
  ancestor expansion, keyboard focus, explicit shared display commands, hidden
  group preservation and global-language consistency. It also retains the
  existing narrow-layout, product-theme, preview, camera and no-hidden-job checks.
- The production resolver and expansion helpers are exercised. The synthetic
  display executor and event transport remain stubs: these browser results do
  not establish authenticated API operation or clinical correctness.
- All 19 standalone Monitor JavaScript regression scripts, including five
  real-Chrome journeys, pass on the final implementation. The repeated repaint
  regression was fixed at source rather than relaxing its assertion.
- Full root Python-suite and post-delivery integrity results are recorded in
  `/tmp/brachybot-monitor-recovery-delivery-20261005/`, including the guarded
  overlay, logs, backup path and final manifest. Those results must be read as
  code-level regression evidence, not real patient usability certification.

## Remaining real-product acceptance journey

The actual LAN page was opened through the existing local tunnel at
`http://127.0.0.1:8080/`. It showed the login overlay; no credentials were read
or entered, no account was created and no authentication was bypassed.

Once the operator logs in and designates a de-identified test case:

1. Check a loaded completed plan with many needles; a newly committed edit must
   yield one current guide, recognisable letters and a verified attachment.
2. Hide a test leaf, then exercise exact-row navigation and explicitly requested
   display recovery. Confirm original color/opacity and no geometry change.
3. Observe resource loading slow enough to exceed timer retries. Current images
   must resume on readiness without duplicating edits or attaching newer
   geometry to an older checkpoint.
4. Switch session/stop/perform another edit before completion. Late results must
   not gain current actions, evidence status or scene ownership.
5. Verify global language, both themes, keyboard/touch access, narrow layouts,
   unobscured Viewer and user-owned camera throughout the real journey.

Patient treatment decisions and test geometry edits are operator actions, not
automatic UI probes. Real feedback quality also needs operator review: no code
test proves that a recommendation is clinically optimal or that the entire
Monitor experience satisfies a company's human-factors standard.

## Delivery boundaries

This increment is frontend-only. Changed asset URLs invalidate the affected
frontend bundles. No server restart, public deployment, commit or push is part
of this delivery. Earlier backend additions remain subject to their own safe
activation and acceptance requirements. A refreshed page must be checked for
the new asset versions before real-case acceptance.
