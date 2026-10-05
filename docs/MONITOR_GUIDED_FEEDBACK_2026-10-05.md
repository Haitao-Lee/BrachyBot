# Monitor Guided Feedback

Date: 2026-10-05. Scope: the LAN/debug BrachyBot checkout, on top of the
closed-loop Monitor changes documented in
`MONITOR_CLOSED_LOOP_IMPLEMENTATION_2026-10-05.md`. Public-release is unchanged.

## User-facing contract

Feedback must help a user decide and act, not merely list measurements. The
server now derives a bounded bilingual coaching record from the same committed
edit evidence used by Monitor checks:

1. **Your edit:** the specific independently edited object and measured motion;
   needle motion is labelled maximum endpoint displacement, not whole-needle
   translation. Derived seed updates are not presented as independent drags.
2. **What it means:** measured spacing or dose changes and their actual scope.
3. **Recommended next step:** a prioritized action and the condition for choosing
   it; an unintended drag and an intentional adjustment are not treated alike.
4. **How to verify:** what to inspect after a correction or restoration.

Chat and the resident dashboard share a text-only renderer. Default feedback
keeps the recommendation visible; full technical records stay expandable. Action
outcomes, request failures and missing images remain visible rather than hidden
inside the collapsed record. Existing ownership checks guard every action.
Prioritized read/preview actions are placed adjacent to their recommendation,
not duplicated at the bottom of a long technical block. No recommendation
automatically executes a calculation, restoration or candidate application.

## Evidence-driven branches, not user-intent keyword rules

| Evidence state | Guidance and available next action |
| --- | --- |
| New/worsened related spacing conflict | Name the exact pair and gap/requirement; locate it first. An independently edited seed can request local spacing candidates. An unintended edit can be previewed before explicit restoration. |
| Spacing improved but remains conflicting | Acknowledge improvement without claiming clearance; locate the remaining pair. Do not count this as a routine keep-confirmation requirement. |
| Pre-existing related conflict | Explain that it predates the edit; do not blame the user for introducing it. Unchanged dependent-seed conflicts do not eclipse the initiating needle edit; directly edited members can still receive targeted review. |
| Geometry saved, current dose unavailable | Offer recomputation explicitly. If a valid baseline is missing, explain that it establishes a future baseline rather than recreating past dose. |
| Current dose without valid pre-edit baseline | Review current results; do not recommend another recomputation merely to fabricate the baseline. |
| Comparable dose | Show coverage, high-dose volume and an observed organ-dose cost. Recommendations are conditional on the user's intended goal and confirmed case constraints, never a clinical verdict. |
| Multi-edit comparison | State the number of edits represented; do not attribute the measured sequence change to the final drag alone. |
| Superseded record | Retain historical observations but remove current recommendations and executable old steps. |

The compact agent facts include the same recommendation/verification context,
without restore tokens, raw coordinates or full bilingual copy. The on-demand
explanation prompt requests specific effects, choices and verification rather
than another generic checklist. It remains on demand; no extra LLM/GPU request
is launched for routine feedback.

## Measurement and safety boundaries

- A clearance shortfall is not a prescribed drag distance. Conservative
  axis-model bounds are not relabelled as exact physical overlap.
- Local geometric candidates remain explicitly requested and confirmed;
  their previous spacing/CTV-sampling checks do not prove dose optimality,
  clinical acceptance or comprehensive OAR safety.
- Organ comparisons are bounded. Observed increases are prioritized so large
  decreases elsewhere cannot hide every measured increase. The UI states that
  only a subset of organ metrics is displayed.
- A 0.005 cutoff is used only to describe rounding at the existing two-decimal
  display precision. It is not model noise, statistical significance or a
  clinical threshold.
- Geometry, dose, image delivery and clinical acceptance remain separate. A
  missing image does not invalidate committed textual measurements; a text
  measurement is not visual proof of spatial location.
- Both languages are available in the coaching contract; text is assigned with
  DOM text nodes, not interpreted as HTML. Static resource versions are bumped.
- Prior closed-loop changes, Auto Compare opt-in, clinical CNN dose computation
  and the independent public-release runtime are preserved.

## Validation and activation

Validation covers specific conflict guidance, incomplete baselines, multi-edit
trade-offs, conflicting V100/D90 directions, V150-only costs, hidden OAR rises,
display precision, historical suppression and compact-fact privacy. Browser
checks cover recommendation visibility, shared chat/HUD copy, exact pair
actions, revision updates, bilingual rendering, text safety and narrow layouts.

Final isolated application suite: **2,224 passed, 2 skipped, 31 warnings,
4 subtests passed**, 51.07 seconds. The two skips are the existing public HTTP
dependency and real NGINX-binary prerequisites, not Monitor checks. All fifteen
Monitor Node/browser scripts passed against the final frontend payload; four
use real Chrome (three include WebGL and the new guidance test uses the DOM).
The browser transports and geometry are synthetic, not patient acceptance.

The final application suite on the actual delivered working tree also passed:
**2,224 passed, 2 skipped, 31 warnings, 4 subtests passed**, 52.23 seconds,
recorded in `actual-delivered-tests.log`. No test assertions or latency evidence
guards were weakened. JavaScript syntax and `git diff --check` passed. All
eight increment files passed the selected-file hash guard; original bytes were
retained privately in
`/tmp/brachybot-monitor-closed-loop-backup-20261005-r7qyte64` (mode 0700).
The served HTML and the two changed scripts/CSS were checked against their
working-tree content hashes. This proves static publication, not an
authenticated Monitor session or backend activation.

The unchanged dependent-seed conflict contract caught an intermediate priority
regression, which was corrected in the implementation rather than by weakening
the existing test. The final screenshot/guide pair selection shares one helper.

Evidence: `/tmp/brachybot-monitor-guidance-delivery-20261005`, including
`full-final-stage-tests.log`. Selected-file delivery uses current-source hash
checks and private originals; all earlier closed-loop changes remain in place.
Synthetic events/geometry are used; no patient plan is edited and no model job is launched.
Backend activation still requires a scheduled LAN 8080 restart. The service has
not been restarted as part of this work; public-release must not be restarted.
During the read-only runtime check the LAN listener was PID 1077724 (different
from the previous turn); public-release remained PID 1047604. This was observed
concurrent maintenance, not a restart performed here. LAN cwd was verified as
the authoritative checkout. The protected health endpoint returned HTTP 401
without authentication; this is not an authenticated health or patient smoke
test. Process IDs are point-in-time evidence only.

This is a concrete coaching improvement, not a claim that the full long-term
Monitor vision or real-patient usability acceptance is complete. Needle
relocation search and dose-verified candidate optimization remain unimplemented.
