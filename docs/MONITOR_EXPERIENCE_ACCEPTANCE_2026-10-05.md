# Monitor experience: spatial guidance and interaction acceptance

Date: 2026-10-05. Scope: the LAN/debug BrachyBot checkout at
`/home/lht/snap/brachyplan/BrachyBot`. The independent public-release checkout
is not part of this delivery. This is an incremental revision of the closed-loop
and guided-feedback work, not a new planning or clinical decision engine.

## 1. The acceptance problem

Naming a needle or seed by its internal ID does not let an operator recognize
it among dozens of objects. Likewise, a correct numerical report is not an
effective guide if its next action is below the fold, a background update closes
the explanation being read, or old images appear to support new geometry.

The user-facing acceptance unit is therefore a journey, not a tooltip or an
individual passing unit test:

1. Save a manual edit without losing control of the camera.
2. Recognize the actual edited object and the current spacing issue.
3. Understand the measured change and its limitations.
4. See one prioritized next action and reach alternatives when needed.
5. Preview before making an explicit geometry decision.
6. Receive asynchronous images and dose results without losing reading position.
7. Stop monitoring with truthful confirmation and a recoverable failure state.

The design takes integrated, proportionate feedback from
[Apple's Feedback guidance](https://developer.apple.com/design/human-interface-guidelines/feedback)
and truthful task-state communication from
[Apple's Progress Indicators guidance](https://developer.apple.com/design/human-interface-guidelines/progress-indicators).
Keyboard focus, target sizing and announcements are checked against relevant
[WCAG focus guidance](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html),
[target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
and [status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).
These references are design inputs, not an Apple/OpenAI endorsement, a WCAG
conformance certification, or a clinical usability validation.

## 2. Verified implementation-level causes

| Previous behavior | Why it failed the journey | Revision |
| --- | --- | --- |
| Internal IDs and bounding boxes dominated feedback | Object recognition still required searching the tree | Lettered patient-space anchors and matching controls |
| All scene references were marked together | Multiple problems diluted the immediate next step | At most three labels: the edited object and the priority pair |
| Metrics and workflow preceded the recommendation | The first action required inner-panel scrolling | Guidance first; workflow and full metrics progressively disclosed |
| Several equivalent-looking action buttons | The operator had to plan the next interaction | One visible primary action, other choices in disclosures |
| `replaceChildren` ran on unchanged dashboard polls | Focused controls were destroyed without a meaningful update | Semantic view signature and focused-control/open-state restoration |
| Image state was generally called 'processing' | Failed, deferred and unscheduled captures looked alike | Distinct actual capture states; no completion claim from a plan |
| Technical details action relied on a full chat rewrite | Optimized rendering could leave a disclosure closed | Explicitly reveal the requested chat or dashboard record |
| Existing pictures remained on an enriched edit card | Prior checkpoint images could be mistaken for current evidence | Visible prior-image warning and immutable capture label metadata |
| Needle preview used its first endpoint as the arrow origin | Moving endpoint two could produce no meaningful return arrow | Per-endpoint verified return arrows |

## 3. Spatial contract

`monitorSpatialGuide` projects server-owned object references and independently
edited objects into a bounded presentation model. It does not infer authorization,
invent coordinates, pick a clinical target, or classify intent by a keyword.

- A, B and C are presentation references for one checkpoint, not new object IDs.
- The independently edited object is prioritized. Associated seeds marked as
  dependent on a needle or normalization are not called independent user drags.
- The priority pair remains complete even when more than one changed object is
  present. Remaining references stay in the detailed record.
- Lettered badges, same-colored outlines and leader lines refer to the verified
  live object. For a moved needle the badge anchors at its most-displaced endpoint.
- Blue/amber/pink arrows describe the measured **past** displacement. Purple
  arrows describe a read-only preview destination. Neither is a computed
  dose-optimal recommendation.
- A spacing witness is drawn only from finite, patient-world-mm evidence whose
  point distance agrees with the recorded measurement. Axis-model bounds are
  not relabeled as exact surface clearances.
- Overlay materials can show through an occluder. The UI explicitly describes
  this as a location aid, not evidence that the physical occlusion is gone.
- Clinical mesh colors, opacity, positions and visibility are not modified by
  these helpers. Edge overlays have their own disposable geometry and bounded
  work: at most four small mesh geometries per selected object, no geometry
  above 5,000 vertices for edge construction.
- Automatic feedback does not reframe the camera. An explicit Locate action
  uses the established framing executor. A later camera gesture revokes the
  old camera-restoration callback.
- A loaded mesh alone does not establish an on-screen location. Claims also
  require current case/run/plan/version/geometry, visible targets and an in-frame
  patient-space anchor. Partially located groups disclose the missing letters.

## 4. Immutable screenshot identity

Monitor captures prioritize the same bounded references. Their metadata records
`monitor_spatial_labels` with exact refs, unique letters, semantic kind and role.
The deterministic annotation renderer uses this mapping only **after** its normal
capture/current-state grounding checks pass. A letter changes a label and color,
never bounds, coordinates, target identity or a verification outcome.

Ambiguous mappings, duplicate letters/refs, unknown roles, mismatched refs and
non-monitor images fall back to the existing annotation behavior. Ordinary chat
screenshots and report captions are not assigned Monitor letters.

Live spatial helpers are temporarily suspended during capture, so a later or
stale ghost cannot contaminate the immutable source image. The existing
checkpoint return-position overlay remains independently evidence-owned. Live
helpers are restored after pixels and grounding freeze, before network upload,
and on error cleanup. Restoration is fenced against a different case/run/layer.

This revision does not remove the established screenshot ownership, partial
delivery, visibility restoration, serialized capture or attachment verification
contracts. Earlier checkpoint images remain available, with a visible warning
when an evolving feedback card advances beyond them.

## 5. Presentation and accessibility

- First view: measured edit, immediate implication and one primary next action.
  The full meaning/recommendation is retained; only the first complete sentence
  appears initially. Other choices, verification and limitations remain in an
  adjacent disclosure and the persisted full record.
- Location chips are navigational aids, not alternative mutation decisions.
- Routine saves do not demand Keep confirmation. Restore/apply remain explicit
  operations through the existing authoritative executors and server guards.
- Metrics, workflow state, Auto Compare and technical identifiers remain available
  but no longer precede the current guidance. Auto Compare remains opt-in.
- A preview exposes its confirmation and dismissal near the preview rather than
  requiring an operator to rediscover a hidden Restore command.
- Unchanged polls preserve DOM identity. Changed views preserve same-checkpoint
  disclosures, scroll positions and valid keyboard focus; a removed or stale
  executable control is never reactivated by focus restoration.
- Historical cards retain a brief observation and a full record, not another
  current-looking instruction block.
- Desktop controls have at least 36px targets; coarse-pointer controls use 44px.
  Focus indicators, scroll padding and reduced-motion overrides are scoped to
  Monitor components. This is not a claim that the whole application meets WCAG.
- One polite, stable live region coalesces rapid saved-edit announcements. It does
  not move focus or announce an entire report on every image update.
- Finish is reachable at the top. An unconfirmed stop remains explicit and
  retryable, rather than looking successfully terminated.

## 6. Global locale, bilingual projections and visual consistency

Monitor belongs to the global `setUiLanguage`/`i18nchange` contract. The old
compatibility function `monitorConversationLanguage` now reads only the global
UI language. Neither the most recent utterance, an LLM response, a restored
snapshot nor the locale frozen at run start can override it.

- Both deterministic interaction projections are derived from the same committed
  evidence. Technical notes, metric labels/units and structured assessments are
  localized together; guidance already contains both copies.
- Stage feedback, advice and persisted close-out summaries carry bilingual
  display projections. Generating the second wording does not recompute dose,
  repeat safety checks or call a translation model.
- In-flight request delivery uses the current UI language. Pending card states
  retain explicit bilingual copies, so a switch while computing also updates
  the busy message and a later failure message.
- The resident panel and owned edit cards redraw without duplicating a card or
  losing same-checkpoint disclosures, valid focus or scroll position.
- Viewer object and measurement text textures repaint in place. Camera ownership,
  ghost previews, object geometry, material colors and helper identities survive.
- New Monitor image annotations use the global locale, independently of ordinary
  chat/report artifacts, whose existing turn-language contract is preserved.
- Previously captured pixels are immutable evidence. An older image containing
  English raster labels is not claimed to have become Chinese merely by changing
  captions. This increment does not recapture an old checkpoint during a switch.
- Pre-upgrade free-form records that never stored a bilingual projection cannot
  be faithfully retranslated by a UI-only switch. Their original evidence is
  retained; the product must not invent a translation or silently reanalyse them.

The visual hierarchy uses a restrained dark surface, a single primary-action
accent, limited warning color, consistent body typography, readable line height,
and explicit space around findings. Technical identifiers and dense status/metric
controls are disclosed on demand. A/B/C colors connect text to the Viewer without
changing clinical meshes. Both Chinese and longer English layouts are checked at
390px; the operator's next action must stay above the resident panel fold.

## 7. Iterations and acceptance evidence

The current browser fixture uses real Chrome DOM and WebGL with forty distractor
needles, one edited needle and two spacing-reference seeds. Network/model/edit
executors are controlled test doubles; no patient case is opened or modified.

Iteration 1 exposed focus replacement on semantically equal preference updates.
The signature now normalizes the actual Auto Compare value. Iteration 2 exposed
measurement/object-label collision and preview endpoint/letter inconsistencies;
these were corrected and the journey replayed. Iteration 3 covered screenshot
snapshot letters, stale attachments and disclosure actions under optimized rendering.
Iteration 4 exercised the actual global setter in Chrome, including a locale
switch with an existing ghost preview. It also exposed and corrected unsafe
substring substitution for short identifiers in English prose. Regression tests
now match complete identifiers and reject ambiguous one-letter replacements.

Acceptance checks include:

| Check | Evidence |
| --- | --- |
| Recognize the edited needle without searching IDs | Exact A/B/C refs, edited-endpoint anchor, forty distractor needles |
| Do not describe dependent seeds as user drags | Dependent objects use spacing roles; only the needle has a measured-move trace |
| First action visible without panel scrolling | Real bounding-box assertions at desktop and 390px width |
| No hidden geometry/dose work | Journey command log remains empty until explicit choices |
| No false location claim | Hidden targets, off-screen anchors, stale version and geometry fences |
| Non-disruptive updates | DOM identity on unchanged redraw; focus, scroll and open disclosures on changed redraw |
| Correct second-endpoint preview | Only the actual moved endpoint has a return arrow |
| Same identities in capture and live view | Bilingual snapshot-label tests; exact-ref/mode/duplicate-negative controls |
| Keep ordinary behavior intact | Existing Monitor, screenshot, report and language regression suites |
| Truthful termination | Stop-error state retains an enabled Retry Finish control |
| Global locale ownership | Frozen-run/turn overrides rejected; late packets, pending messages and errors switch in place |
| No work hidden behind language switching | No recapture, recomputation, geometry mutation or camera/preview reset |

Validation results and delivery hashes are recorded with the release evidence.
No benchmark performance or clinical outcome is inferred from these component
and synthetic-journey tests.

### Validation record

- The complete root `tests/` suite in a private current-source staging checkout
  passed: **2,228 passed, 2 skipped, 31 warnings, 4 subtests passed**, 51.79s.
  The two skips require public-deployment dependencies and a real Nginx binary;
  they are not completed deployment/security validations. Warnings are existing
  SWIG and `datetime.utcnow` deprecations, not hidden failures.
- All 18 Monitor JavaScript contract/journey scripts were exercised; five use
  real headless Chrome. The new journey covers real DOM and WebGL, forty
  distractor needles, both locales, 390px layout, explicit actions, focus,
  asynchronous delivery and preview/camera preservation.
- Counterexamples cover a Chinese global UI with English run/response/input,
  the reverse, language switching during a requested computation, late errors,
  same-message summary updates, and old-case fencing.
- Early full runs caught an outdated asset-version assertion and the old
  conversation-owned Monitor contract. Those assertions were migrated to the
  requested global-UI policy, with executable negative controls retained. A
  new summary-test DOM double was also corrected; no production guard was
  relaxed to obtain the final green run.
- Evidence directory:
  `/tmp/brachybot-monitor-experience-delivery-20261005`.
  `staged-pytest-verified.txt` contains the full green staging log. Delivery uses
  before/after SHA-256 guards and a private backup, with index versions last.

## 8. Deployment and remaining validation boundary

This increment changes frontend assets, deterministic Monitor display payloads
and tests. Index asset versions are advanced so a page reload requests the new
scripts. An already-running schema-3 server supports the bilingual-guidance
fallback for edit cards, but the added full interaction, stage-feedback and
persisted-summary language maps require loading the updated Python code through
an orderly LAN/debug service restart. This delivery does not restart either
deployment or modify the independent public-release checkout.

The following are **not** completed by the synthetic acceptance journey:

- An authenticated, real-case end-to-end browser test with production latency,
  current meshes, real uploads and a real dose job.
- A clinician/physicist usability study or clinical acceptance review.
- A clinical optimizer that computes where a needle should be moved.
- A guarantee of exact per-edit dose causality when the comparison spans several
  edits, or reconstruction of a missing pre-edit dose baseline.
- A screen-reader user study or whole-application accessibility certification.

These boundaries must remain visible in any release claim. The revised interaction
is accepted for the bounded journeys described above; it is not proof that every
real-case experience, or the clinical planning system, is validated.
