# Monitor calm coaching refinement — 2026-10-05

## Scope and acceptance standard

This increment changes the LAN/debug Monitor experience. It is not a clinical
optimizer, a public-release deployment, or a claim that clinical usability is
proven. It builds on the existing committed-edit evidence, shared executors,
global locale, bounded screenshot delivery, and camera ownership contracts.

The acceptance question is whether a person can identify the current issue,
find its real Viewer objects, choose a clearly described action, and see its
verified outcome without reading a repeated technical report.

## Root causes addressed

1. The resident workspace and chat expanded essentially the same full coaching
   panel and toolbar. Increasing event frequency increased repeated reading.
2. Guidance lived in the chat column even when the user was working in the 3D
   Viewer. IDs and spatial markers alone did not connect the next action to
   the user's working surface.
3. A read-only position preview did not change the main action. The interface
   continued to recommend locating an object after the user had already chosen
   to inspect its pre-edit position.
4. Returning from explicit camera focus was buried in other actions. Clearing
   focus was not an obvious way to return to the user's prior camera.
5. Comparable metric rows and multi-edit attribution were too easy to miss in
   disclosures. A shortened sentence could hide the attribution caveat.
6. A mutation executor returning `success: false` without throwing left no
   visible failure explanation in this action path.
7. Secondary text and control colors were not tested with the actual product
   theme tokens. Small, low-contrast text is not a valid form of decluttering.

## Interaction design

### One current coach, durable receipts

- The resident workspace is the current coach. It retains observation, measured
  meaning, recommended next step, one primary action, and lettered references.
- Chat defaults to a concise edit receipt. Full coaching and the complete
  technical record remain separately expandable and are not deleted.
- A receipt can reopen the current workspace and focus its heading. It does not
  run a tool, recalculate dose, alter geometry, or jump to a newer case.
- If the workspace is absent, the existing full chat coaching fallback remains.
- Historical cards never acquire a current recommendation or executable action.

### A guide beside the Viewer, not over it

- A small normal-flow rail is added beside the 3D image's controls, outside
  `#canvas3D`. It shows the current issue, its first measured meaning or action
  status, the current primary action, and a link to detailed guidance.
- This is a projection of the same current card, not another planning store.
- It is removed from executable use on version/geometry drift, drag preview,
  stop recovery, case/run change, or absent guidance.
- It is not a popup, does not auto-frame the camera, and covers no diagnostic
  pixels. It also carries `data-html2canvas-ignore` for broader DOM captures.
- Existing Viewer layout observation already observes the Viewer and its 3D
  canvas; the rail does not install another resize observer or model job.

### Preview, choice and outcome

- A valid previous-position preview replaces the primary action with explicit
  restoration confirmation. A selected candidate replaces it with explicit
  candidate confirmation. A nearby dismissal makes no plan change.
- The rail names preview as preview and explicitly says the plan is unchanged.
- Original focus/dose choices remain available in the disclosure rather than
  competing with preview confirmation.
- Explicit focus exposes "Return to my view" only while the saved camera is
  still owned. A later manual camera gesture revokes that restoration, as before.
- A false executor result is shown as unconfirmed, not silently accepted.
- The server's restore token, candidate checks, optimistic version and geometry
  fencing remain the authority for any mutation. No authorization is broadened.

### Measured changes, not a fabricated verdict

- The first view distinguishes saved geometry from current/stale dose.
- Comparable dose results show a bounded table of finite V100, D90 and V200
  rows (V150 fallback) and one recorded OAR row where available. Full rows stay
  in the detailed record. Missing or nonfinite rows are not filled in.
- Differences are neutral measurements, not red/green clinical pass/fail or a
  claim that increased coverage is overall improvement.
- Effects spanning several edits are visibly labeled as combined effects.
- Sub-0.01 differences are labeled as display precision, not "no effect" or
  established model noise. No new clinical or significance threshold is invented.
- Geometry conflicts still have priority under the server's existing guidance;
  a fresh dose does not resolve a spacing conflict.

### Calm visual and accessibility rules

- Less duplicate prose; smaller, bounded A/B/C badges; concise location status.
- Occlusion and arrow semantics remain available, with the "recorded move, not
  recommended next direction" warning visible when relevant.
- Current guide action is reachable above the fold in the tested geometry
  journey at desktop and narrow widths; longer data remains scrollable.
- Scoped control styling follows actual product theme tokens. Secondary status
  text and enabled visible control labels are contrast-tested at >= 4.5:1 in
  both themes. This is not an assertion of whole-product WCAG conformance.
- Focus/open-state retention, global language, keyboard controls and reduced
  motion behavior are preserved. No sound, focus theft or automatic modal added.

## Iterations and verification

The browser journey uses synthetic geometry: 40 distracting needles, an edited
needle endpoint, associated seeds, finite spacing witnesses and controlled
executor responses. It does not authenticate to or mutate a patient case.

The expanded real-DOM/WebGL journey checks:

- quiet chat receipts and a single visible workspace primary action;
- a rail outside the canvas and no diagnostic-pixel obstruction;
- stable A/B/C identity without exposing tree IDs in first-view prose;
- workspace reopening, reversible owned camera focus, and later gesture ownership;
- preview-specific confirmation and mutation-free dismissal;
- unconfirmed executor outcomes;
- bounded measured tables, nonfinite rejection and visible sequence attribution;
- global EN/Chinese projection with no extra inference or mutation;
- stale, drag, stop-recovery and case/run fences;
- actual product CSS, both themes, readable statuses/buttons and narrow layouts;
- earlier image evidence not silently becoming current evidence.

An early local test attempt lacked the unchanged `brachybot-chat-todo.js` fixture
and could not run the intent-routing test. The real current file was fetched and
the test then passed; this was not a product regression. Contrast checks also
wait for the newly inserted stylesheet/theme to actually apply before measuring.

Validation results and delivery hashes are recorded in the delivery evidence
directory and should be read with the final handoff. Passing these checks is a
bounded engineering acceptance, not a measured human-factors or clinical study.

Staged full-root regression: **2,228 passed, 2 skipped, 31 warnings, 4 subtests
passed (49.53 seconds)**. The skips require the optional public deployment
dependencies and a real Nginx test binary. Existing warnings concern SWIG and
`datetime.utcnow()`. All 18 Monitor JavaScript regression scripts passed in the
local runtime, including five real-Chrome browser journeys. The final archive
is also rechecked in the authoritative checkout after guarded delivery.

Evidence directory:
`/tmp/brachybot-monitor-refinement-delivery-20261005`.

## Deployment and remaining boundaries

This increment is frontend-only and can be loaded by refreshing the LAN web
page; it does not require another backend restart. Earlier backend bilingual
changes still require a separately authorized controlled restart to take full
effect. An active page keeps its old loaded scripts until refreshed.

No active planning job is interrupted, and the independent public-release
checkout/process is not modified. No commit or push is part of this delivery.

The remaining acceptance work is an authorized live authenticated case journey
with the actual anatomy, viewport sizes, loading state, screenshot callbacks and
human operator. Synthetic stubs cannot prove runtime screenshot delivery,
patient-specific optimal movement, clinical safety, or user satisfaction. A
local geometric candidate is still not a dose-optimal or clinically approved
destination. No guarantee of an "Apple-level" or "OpenAI-level" certification is
made.
