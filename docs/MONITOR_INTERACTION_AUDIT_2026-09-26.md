# Monitor Interaction Experience In-Depth Audit Report

**Date**: 2026-09-26
**Scope**: End-to-end Monitor interaction experience—frontend UI, backend engine, agent integration, data flow
**Nature**: Diagnosis of fundamental problems at the interaction-paradigm level and directions for systemic improvement

---

## 0. Vision Recap

> The user lets BrachyBot **supervise** the manual/automatic planning process, **receives real-time feedback** after key interactions, **automatically captures screenshots as evidence** at high-value checkpoints, **can request detailed advice at any time**, and **generates a final workflow report** on stop.

Core words: **real-time**, **feedback**, **supervision**, **coaching**.

These five words point to a product experience: **a quiet, continuous, trustworthy practice coach**—it watches you plan from the side, occasionally reminding you "these two seeds are too close" or "this edit improved V100 by 2%", rather than a logging system that dumps all observations into a chat window.

---

## 1. Root Problem One: The Paradigm Error of Chat-as-Dashboard

### 1.1 Current State

**All of Monitor's output**—startup confirmation, spacing violation warnings, dose comparisons, edit evidence cards, screenshots, stop summaries—is rendered in the **chat message stream**. The frontend has no independent monitoring panel, HUD, or dashboard.

**Code evidence**:
- `brachybot-monitor-interaction.js:67`: checkpoint cards are injected into the chat stream via `addChat('bot-response', ...)`
- `brachybot-ui-api.js:1777-1827` (`_flushMonitorFeedback`): batches of feedback are merged into a "phase monitoring" chat message
- `brachybot-ui-api.js:1875-1908` (`_queueMonitorFeedback`): immediate/aggregated feedback ultimately all use `addChat`
- `brachybot-3d-manual.js:2485-2498`: the startup guidance message also uses `addChat`
- `brachybot-3d-manual.js:2664-2681`: the stop summary (including screenshot attachments) also uses `addChat`

### 1.2 Why This Is a Root Problem

**Chat is a "request-response" conversation paradigm**, not a "continuous state monitoring" dashboard paradigm:

| Dimension | Chat (conversation) | Dashboard |
|---|---|---|
| Time model | Discrete turns | Continuous stream |
| Attention model | User actively reads | System actively pushes |
| Spatial model | Vertical scrolling, new pushing out old | Fixed regions, state persists |
| Information density | One block of text at a time | Multiple dimensions side by side |
| Accumulation | Lost (pushed away) | Retained (persistent) |

Monitor's essence is the **second**, but it is forced into the container of the **first**. Consequences:

1. **Feedback gets pushed away**: after three consecutive seed edits, the first two pieces of feedback have already been pushed outside the scroll area. The user must scroll up to review them—in a 3D planning workflow, this severely interrupts their train of thought.
2. **No at-a-glance view**: while looking at geometry in the 3D view, the user wants to know "what is V100 right now? Are there spacing problems? Which step am I on?"—they must move their gaze from the 3D view to the chat area and scroll to find out.
3. **Screenshots/cards occlude each other**: screenshots are attached to chat messages, edit cards are also in chat, and historical messages get squeezed out of view.
4. **No comparison**: to see "the dose difference between edit 1 vs edit 2", the user can only switch back and forth between two chat messages.

### 1.3 Directions for Systemic Improvement

**A persistent monitoring panel (Monitor HUD) must be introduced**, coexisting with—not replacing—the chat stream. The panel should at minimum contain:
- **Current plan metrics card**: V100 / D90 / V200 / OAR Dmax, with trend arrows
- **Workflow progress**: current phase, completed steps, next-step suggestions (checklist style)
- **Recent events timeline**: a scrolling list with severity color coding (info/warn/blocking)
- **Pending operations**: undecided edits (restore/keep), unviewed screenshots

The chat stream retains **conversational content** (startup confirmation, stop summary, user-initiated Q&A), but **stateful feedback** migrates to the HUD.

**This is not a "nice-to-have" but the root cause of the current experience being unusable.** Without a HUD, no matter how accurate monitor feedback is, it cannot be conveyed.

---

## 2. Root Problem Two: Broken Spatial Feedback Chain—Talking About Location Without Pointing to It

### 2.1 Current State

Monitoring feedback says "seed-123 and seed-456 have a surface gap of 1.2mm", but **no visual change occurs in the 3D Viewer**—it does not highlight these two seeds, flash, or focus. The user must manually find them in the Data Tree and manually rotate the view.

**Code evidence**:
- `monitor_engine.py:246-255`: the feedback text contains `worst.get('first_id')` and `worst.get('second_id')`—plain-text IDs
- `brachybot-monitor-interaction.js:38-43`: conflict pairs are rendered as markdown text
- `monitor_changes.py:343-363` (`screenshot()`): the screenshot instruction carries `focus_seed_ids`, but this only affects **screenshot framing**, not the Viewer state during interaction

### 2.2 Why This Is a Root Problem

Clinical planning is a **highly spatial** activity. The user's mental model is "this seed is here, that needle is there, and the distance between them is…". Monitoring feedback translates spatial problems into **text symbols** (ID + number), so the user must reverse-map them back into 3D space in their head—increasing cognitive load and reducing the actionability of the feedback.

Contrast the experiences:
- **Current**: "seed-123 and seed-456 are 1.2mm apart" -> the user thinks "which two? where?" -> manual search
- **Desired**: in the 3D view, seed-123 and seed-456 are **highlighted simultaneously** (red pulse), a **red connecting line** labels 1.2mm, and the camera automatically **focuses on this conflicting pair**

### 2.3 Directions for Systemic Improvement

A **Spatial Annotation Layer** is needed, which listens to object IDs in monitoring feedback and, in the 3D Viewer:
- highlights the objects involved (color = severity)
- draws distance annotation lines between objects
- provides a one-click "jump to conflicting pair" button (clicking feedback text -> the camera focuses on the corresponding objects)
- keeps displaying until the user confirms or the next edit overrides it

**This cannot rely on screenshots alone.** Screenshots are static, lagging, and one-off; what the user needs is **live 3D spatial annotation**.

---

## 3. Root Problem Three: Feedback Is Plain Text, Not Structured Decision Support

### 3.1 Current State

The feedback engine (`monitor_engine.py:218-311`) outputs **a sentence in English/Chinese**, which is then translated into Chinese by `_localize_monitor_text`. After receiving it, the frontend renders it as markdown text.

**Key gaps**:
- No severity grading (info / warn / blocking)—all feedback looks equally important
- No color coding—users cannot quickly identify serious problems
- No actionable inline actions—feedback says "please adjust the spacing" but gives no "jump to this seed pair" button
- No numerical visualization—"V100=92.3%" is text, not a needle on a gauge

**Code evidence**:
- `monitor_engine.py:218-311`: returns `Optional[str]`—a plain string
- `monitor_changes.py:366-435` (`interaction()`): has a `priority: attention/review/info` field, but the frontend only uses it to control the title text, not color/icon/layout
- `brachybot-monitor-interaction.js:31-72` (`render`): all content is flattened into markdown lines, with no visual hierarchy

### 3.2 Directions for Systemic Improvement

Feedback needs a **structured schema** (rather than a plain-text string), containing at minimum severity, category, headline, spatial_refs, and action. The frontend controls color/icon/position based on severity, controls 3D highlighting based on spatial_refs, and generates buttons based on action.

---

## 4. Root Problem Four: The Workflow Is Invisible—Users Don't Know "Where They Are"

### 4.1 Current State

Monitor's startup message says "you can select a seed or a needle endpoint to fine-tune", but **does not tell the user which stage of the workflow they are currently in**. The user doesn't know: is CTV segmentation done? How many needles did trajectory planning produce? How many seeds did seed placement produce? Has the dose been computed? What should be done now?

**Code evidence**:
- `monitor_engine.py:6-28` (`_monitor_step_label`): **the engine knows** the stage (ctv/oar/trajectory_init/trajectory_refine/seed_planning/dose_calc/dose_eval/full)
- `monitor_engine.py:276-284`: feedback for the `planning.step` event only says "CTV Segmentation is running/completed"—it is an **event description**, not **workflow progress**
- The frontend has no workflow checklist/progress bar/step indicator

### 4.2 Why This Is a Root Problem

The opposite of "supervision" is "letting things drift". If monitor doesn't tell you "what to do next", it is just a logger, not a coach. A good coach would say: "You have completed CTV and OAR segmentation; now you should plan the puncture trajectory—first determine the entry point, and be careful to avoid these non-puncturable structures."

### 4.3 Directions for Systemic Improvement

The Monitor HUD needs a **workflow checklist**, where each step can expand to show its current status and next-step suggestions. The engine already knows the stage—what's missing is rendering the stage information as a visual progress checklist.

---

## 5. Root Problem Five: A Fragile Evidence Chain—Users See Too Many Error States

### 5.1 Current State

The screenshot/evidence state machine has four states, `pending -> ready | failed | none`, plus `superseded`. Users may see 5 different error messages: tab hidden / superseded / monitor stopped / unknown / retry.

**Code evidence**:
- `brachybot-monitor-interaction.js:17-29`: text for 5 error codes
- `brachybot-ui-api.js:2337-2360`: throttling/queueing/superseded logic for screenshot scheduling
- `brachybot-ui-api.js:2535-2564`: 5 categories of error notifications

### 5.2 Why This Is a Root Problem

In a "real-time monitoring" experience, **failure states should not become the norm**. Browser in the background -> screenshot fails; rapid consecutive edits -> old screenshots are superseded; monitoring stops -> pending screenshots are marked failed; network jitter -> screenshot upload fails. The user must **click "retry screenshot"**—a manual action that should not exist.

### 5.3 Directions for Systemic Improvement

1. **Automatic retry**: automatically retry after a screenshot failure (exponential backoff), without requiring a user click
2. **Graceful degradation**: when a screenshot fails, the card still fully displays the text feedback, and the screenshot area shows "temporarily unavailable" rather than error details
3. **Background queueing**: when the tab is hidden, screenshots are queued and automatically recaptured when the page becomes visible
4. **Merged display**: only the final state of a screenshot for the same edit is shown, not intermediate states

---

## 6. Root Problem Six: Too Many Interaction Channels—Users Don't Know Which to Use

### 6.1 Current State

Users can interact with monitor in **at least 5 ways**: card buttons (monitor-interaction.js:74-119), chat edit buttons (ui-api.js:1829-1865), chat token commands (ui-api.js:2153-2269), UI buttons (index.html:909-913), Agent tools (ui_controller:413-417).

Problems:
- **Restore/keep** has two entry points (card buttons vs chat buttons), with identical semantics but different appearances
- **Stop monitoring** has three entry points with subtly different behaviors
- Card buttons gray out after the card is `superseded` but **do not explain why**
- Chat commands require a 12-digit hex token—users cannot possibly type it by hand and can only trigger it via buttons

### 6.2 Directions for Systemic Improvement

**Unify into two interaction modes**:
1. **Panel/card operations** (mouse): buttons on the HUD and cards, the primary interaction method
2. **Natural-language conversation** (keyboard): telling BrachyBot "help me restore the previous edit", routed by the LLM

**Eliminate the intermediate state**: do not expose token-based chat commands to users. Button clicks directly call the API, without going through chat text.

---

## 7. Root Problem Seven: Dose Comparison Requires Manual Triggering—the Most Valuable Feedback Is Buried

### 7.1 Current State

After each edit, the card shows geometric changes, but **dose comparison requires the user to click the "Recompute and compare" button**.

**Code evidence**:
- `monitor-interaction.js:98-109`: `if (!card.data.interaction?.dose_current) add('Recompute and compare', ...)`
- `3d-manual.js:1956-1958`: **does not automatically recompute dose** during monitoring

### 7.2 Why This Is a Root Problem

Dose coverage (V100/D90) is the most core quality metric of a radiotherapy plan. What users care about most is "did this edit make the plan better or worse". Hiding this feedback **behind a button** amounts to hiding the most important information.

Contrast the experiences:
- **Current**: edit -> card shows "moved 3.2mm" -> user wants to know the V100 change -> manual click -> wait 10-30 seconds -> see the result
- **Desired**: edit -> card immediately shows the geometric change + automatically triggers dose recomputation -> when done, the card updates the dose comparison in place

### 7.3 Directions for Systemic Improvement

In monitoring mode, a successful geometric edit should **automatically trigger dose recomputation**, and when done, update the card's dose comparison table in place. At minimum, a prominent "auto-compare" toggle should be provided.

---

## 8. Root Problem Eight: The LLM Is Marginalized—the Coach Has No Brain

### 8.1 Current State

The LLM does only three things in monitor:
1. Routes chat commands ("stop monitoring" -> `ui_control` intent)
2. Reads the evidence bundle (`monitor_edit_evidence` injected into context)
3. Answers "detailed advice" (`/training/advice` -> `agent._answer_local_read_query`)

**The LLM does not participate in**:
- feedback generation (pure rule engine)
- workflow guidance (none)
- clinical explanation (none)
- personalization (none)

**Code evidence**:
- `monitor_engine.py`: no LLM calls anywhere in the file
- `monitor_changes.py:2`: "No model inference or dose prediction"
- `planning_routes.py:5662-5670`: the natural-language part of advice goes through `agent._answer_local_read_query`, but this is **retrospective**, not real-time

### 8.2 Why This Is a Root Problem

If a "coach" can only recite a checklist without explaining "why this matters", "what this means clinically", or "what characterizes your planning style", then it is just a **rule-based alarm**, not a coach.

The word "training" in the vision's "real-time training/monitoring" implies **teaching**—explaining clinical principles, pointing out planning patterns, recommending directions for improvement. This requires the LLM's understanding and expression abilities.

### 8.3 Directions for Systemic Improvement

On top of the deterministic engine, add an **LLM coaching layer**:
- **Post-hoc explanation**: after each checkpoint, the LLM generates a brief clinical explanation based on the evidence bundle (why spacing matters, the clinical consequences of V100 below target)
- **Pattern recognition**: the LLM observes the edit sequence and identifies the user's planning patterns (e.g., "you tend to concentrate seeds in the center, which may cause insufficient peripheral dose")
- **Personalized advice**: adjust the level of detail of feedback based on the user's historical behavior

**Note**: The LLM layer should **augment** rather than replace—the deterministic engine guarantees the safety baseline, and the LLM provides teaching value. This aligns with the design document's "Augment, don't replace" principle.

---

## 9. Root Problem Nine: The State Machine Is Too Complex, and Edge Cases Leak into the UX

### 9.1 Current State

Monitor's frontend state machine has 6 phases (`inactive/starting/active/stopping/stop_error/error`), plus the card's `pending/ready/failed/none/superseded`, the screenshot's `monitor_stopped/checkpoint_superseded/viewer_tab_hidden`, etc. The combinations of these states produce a large number of edge cases that directly affect user experience.

**States the user may see**:
- "上一轮监测的结束尚未确认。请先点击结束监测重试" (stop_error)
- "该病例已有监测任务；请先结束它" (409)
- "Stop not confirmed; retry" (stop_error, in English)
- "run_mismatch" (task swapped elsewhere)
- "closing" (summary generating)
- "already_closed" (already ended on server)

**Code evidence**:
- `3d-manual.js:2382-2388`: refuses to start on stop_error
- `3d-manual.js:2442-2456`: displays an error on 409
- `3d-manual.js:2626-2651`: handling of run_mismatch and closing
- `monitor-stop-presentation.test.cjs`, `monitor-stop-recovery.test.cjs`: extensive tests covering these edges

### 9.2 Why This Is a Root Problem

Users should not care about "run_mismatch" or "stop_error". These are **system-internal states**, not user concepts. A good UX should translate these into language users can understand:

- "上一轮监测的结束尚未确认" -> "Ending the previous monitoring session… (click retry)"
- "run_mismatch" -> "The monitoring task has switched; please refresh the page"
- "stop_error" -> "Ending monitoring… (if it persists, click retry)"

### 9.3 Directions for Systemic Improvement

1. **Automatic recovery**: stop_error should retry automatically rather than requiring a manual user click
2. **Hide internal states**: internal states such as run_mismatch and closing should not be directly exposed to users
3. **Unify error copy**: all error messages should be translated into user language rather than system jargon

---

## 10. Root Problem Ten: No Cumulative Perspective—Users Can't See Trends

### 10.1 Current State

Monitor generates a summary report (`monitor_summary`) **on stop**, containing event counts, strengths, problems, and suggestions. But **during monitoring**, users cannot see:
- how many edits have accumulated
- the dose trend (is V100 rising or falling)
- the problem trend (are spacing violations increasing or decreasing)
- how far there is to go to the target

### 10.2 Why This Is a Root Problem

"Supervision" means **continuous assessment**, not a **final exam**. If users can only see the summary on stop, then monitor is just a logger, not a real-time coach.

Contrast the experiences:
- **Current**: the user edits 20 times in a row, sees one independent piece of feedback each time, and only on stop sees "your plan has 3 spacing violations, V100 is 5% below target"
- **Desired**: the HUD displays in real time "edited 20 times | V100 trend: +2.3% | spacing violations: 2 (decreasing) | distance to target: 3% to go"

### 10.3 Directions for Systemic Improvement

The Monitor HUD needs a **trend panel**:
- edit count and frequency
- time series of key metrics (V100/D90/plan_score)
- problem counts and trends
- a progress bar toward the target

---

## 11. Summary of Systemic Improvement Priorities

### P0: Experience Unusable (must be done first)

| # | Problem | Improvement | Impact |
|---|---|---|---|
| 1 | Chat-as-Dashboard | **Monitor HUD panel** | How all feedback is conveyed |
| 2 | Broken spatial feedback chain | **3D spatial annotation layer** | Actionability of feedback |
| 3 | Plain-text feedback | **Structured schema + severity** | Readability of feedback |

### P1: Experience Usable but Not Smooth

| # | Problem | Improvement | Impact |
|---|---|---|---|
| 4 | Workflow invisible | **Workflow checklist** | User's sense of direction |
| 5 | Fragile evidence chain | **Automatic retry + graceful degradation** | Reduce distractions |
| 6 | Too many interaction channels | **Unify into panel + conversation** | Reduce cognitive load |
| 7 | Manual dose comparison | **Automatic dose recomputation** | Timeliness of core feedback |

### P2: Experience Smooth but Not Smart Enough

| # | Problem | Improvement | Impact |
|---|---|---|---|
| 8 | LLM marginalized | **LLM coaching layer** | Teaching value |
| 9 | State machine leaks | **Automatic recovery + hide internal states** | Reduce confusion |
| 10 | No cumulative perspective | **Trend panel** | Sense of continuous assessment |

---

## 12. Relationship to the Existing Roadmap

The findings in this document are highly consistent with `TRAINING_MONITOR_ANALYSIS_2026-09-19.md` §8 Phase C (HUD panel, structured feedback cards, coaching mode), but:

1. **Higher priority**: Phase C was listed as an enhancement "from passive glow to actionable coaching", but this document argues that **without a HUD, the current experience is simply unusable**—it should be moved ahead of Phase A/B.
2. **More emphasis on spatial feedback**: the existing roadmap does not sufficiently emphasize the importance of 3D spatial annotation. Plain-text feedback is insufficient for spatial work.
3. **More emphasis on the LLM's teaching value**: the existing roadmap positions the LLM as an "enhancement" but does not sufficiently exploit the LLM's potential in **clinical explanation and personalization**.
4. **More emphasis on automatic dose comparison**: the existing roadmap does not list "automatic dose recomputation" as a priority, but this is the feedback users care about most.

**Conclusion**: Monitor's deterministic engine and lifecycle management are already quite robust (Phase A/B essentially complete), but the **interaction experience layer (Phase C) is the current bottleneck**. It is recommended to move forward the core items of Phase C (HUD, spatial annotation, structured feedback) as the focus of the next development round.

---

# Implementation Status Review (2026-09-26, Second Round)

**Trigger**: after remediation implementation, verify item by item against the 10 root problems in this report.

**Overall assessment**: All three P0 items (HUD, spatial annotation, structured feedback) have made substantial progress but **none fully meet the bar**. Among the three P1 items, state machine simplification and the evidence chain meet the bar; automatic dose and interaction channel streamlining do not. All three P2 items are partially implemented.

---

## A. Item-by-Item Comparison (10 Root Problems)

### Problem 1: Chat-as-Dashboard — **Partially Implemented (~55%)**

**Delivered**: a new persistent `#monitorDashboard` panel (`brachybot-monitor-dashboard.js`), containing a metrics grid (V100/D90/V200 + OAR Dmax text), a workflow badge row, finding cards (severity border + conflicts + next_step), an action button group, and a collapsible edit history. The data flow is push (checkpoint publish) + pull (`/api/training/status?overview=1`, 250ms debounce).

**Not meeting the bar**:
- The metrics card has **no trend arrows**, OAR Dmax is a line of text rather than a card, and **plan_score is not displayed**
- The workflow is a **flat badge row** (data availability status), not a checklist-style progress (no "current step" highlight, no completion checkmarks, no per-step next-step suggestions)
- The event timeline only has **edit history** (8 entries), not the full set of monitoring events; **no severity color coding**; no blocking level exists
- Pending operations only have buttons for the latest card, **no unviewed-screenshot indicator**, and no cross-card aggregated queue

### Problem 2: Broken Spatial Feedback Chain — **Partially Implemented (~50%)**

**Delivered**: `focusMonitorCheckpoint()` uses `Box3Helper` to outline-highlight conflict/edit objects (orange, without changing materials), paired with camera focus (`focusPlanningObjectsForScreenshot`, with restorable pose); a purple return arrow (`_monitorReturnPositionOverlay`, ArrowHelper).

**Not meeting the bar**:
- **3D distance annotation lines are completely unimplemented**—conflict spacing is still presented only as text ("seed-123 ↔ seed-456: 1.20 mm"), with no measurement line/label connecting the two objects in 3D
- Object IDs are **not clickable**—you cannot click a single ID in the feedback to jump to a single object; only button-level "locate all edited objects" is possible
- Highlighting uses a Box3Helper wireframe, not a "red pulse"-style visually prominent annotation

### Problem 3: Plain-Text Feedback — **Implemented (~85%)**

**Delivered**: `monitor_changes.py interaction()` returns a `schema_version:2` structured dict (priority/severity/category/spatial_refs/conflicts/metric_rows/dose_note/next_step/dose_current/dose_comparable), and the frontend renders the card field by field, with text only as a fallback.

**Not meeting the bar**:
- severity has only two levels, `info`/`warning`, with **no blocking level** (`monitor_changes.py:429-431`)
- CSS has only one style, `[data-severity=warning]` (`monitor-dashboard.css:16`), with no style difference for info
- Feedback is still **text-centric**, with no numerical visualization (V100 has no gauge/progress bar/color band)

### Problem 4: Workflow Invisible — **Partially Implemented (~40%)**

**Delivered**: an 8-stage badge row (CT/CTV/OAR/needle-seed/dose/QA/guide/report), status labels (data available/needs updating/running/failed/unverified), with the disclaimer "数据可用不代表临床通过".

**Not meeting the bar**:
- No checklist-style progress (no checkboxes, no step ordering, no "which step we're currently on" highlight)
- The status is essentially **data availability**, not **step completion**
- No next-step suggestion for each step

### Problem 5: Fragile Evidence Chain — **Implemented (~85%)**

**Delivered**: transient screenshot failures are automatically retried (≤2 times, 1.5s/3s backoff); background tabs are deferred + automatically recaptured on visibilitychange; new edits cancel old retries; text evidence is retained when images fail; failure copy is honestly differentiated by error category.

**Not meeting the bar**:
- Cards still display 5 kinds of error copy (although merged into bounded retries + automatic recovery, users still see error-code descriptions at the level of system jargon such as "viewer_tab_hidden")
- Not retrying permanent errors (superseded/monitor_stopped) is a reasonable design, but the UI does not distinguish the visual weight of "temporary failure" and "permanent failure"

### Problem 6: Too Many Interaction Channels — **Not Implemented (~20%)**

**Delivered**: card buttons and HUD buttons are unified through the `runMonitorCheckpointAction` executor; keep/restore directly call `performMonitorEditDecision` (without injecting a token).

**Not meeting the bar**:
- **Token chat commands are fully retained** (`handleMonitorConversation` still parses `复位 abc123def456`)
- `_attachMonitorEditChoices` still injects undo/keep buttons under batch feedback messages
- `monitor_changes.py:331-334` describe() text still outputs "Reply 'undo {code}' or 'keep {code}'"
- The three channels (card buttons, batch feedback buttons, token commands) **coexist** and have not converged

### Problem 7: Manual Dose Comparison Triggering — **Partially Implemented (~60%)**

**Delivered**: the HUD has an "auto-recompute and compare" checkbox (`setMonitorAutoCompare`, 1800ms debounce merging consecutive edits); cards have a manual "Recompute and compare" button; automatic avoidance when dragging/GPU is busy.

**Not meeting the bar**:
- **Off by default**—users must manually check it to get automatic dose comparison, whereas the audit report's core demand is that "the most valuable feedback should be available by default"
- In monitoring mode, dragging a seed still **skips automatic recomputation** (the gate condition at `3d-manual.js:1952-1958` is `!monitoringEdit || options.doseRecomputeDecision === 'yes'`); the comment says "Recompute is an explicit operator decision"

### Problem 8: LLM Marginalized — **Partially Implemented (~30%)**

**Delivered**: the HUD has an "Explain these changes" button -> `requestPlanningAdvice` -> `agent._answer_local_read_query` (LLM-grounded explanation), with a 45s timeout + repeated-click protection.

**Not meeting the bar**:
- **No automatic clinical explanation**—the feedback itself is still pure rule text, with no automatic LLM "why this matters" attached
- **No pattern recognition**—the LLM does not observe the edit sequence or identify planning patterns
- **No personalization**—it does not adjust the level of detail of feedback based on user behavior
- The remediation document explicitly states "No automatic personalized clinical coaching has been enabled"—this is an intentional boundary, but it falls short of the audit report's "coach" vision

### Problem 9: State Machine Leaks — **Implemented (~80%)**

**Delivered**: stop_error has bounded automatic retries (≤2 times, 2s/4s delay); automatic close reconciliation on page recovery; run_mismatch terminates automatic recovery by design (reasonable).

**Not meeting the bar**:
- run_mismatch still requires the user to manually click "end monitoring" (a design decision, but from a UX standpoint it is still system jargon)
- Starting a new run is prohibited during stop_error (reasonable, but the copy is still system jargon: "上一轮监测的结束尚未确认")

### Problem 10: No Cumulative Perspective — **Partially Implemented (~35%)**

**Delivered**: collapsible edit history (most recent 8, with V100/D90 before-after deltas); metric/organ delta tables within a single card; an "N edits retained on this page" count.

**Not meeting the bar**:
- **No graphical trends** (sparkline/chart/canvas have zero hits in the dashboard)—trends are plain-text lines
- No full-run cumulative metrics ("edited N times | V100 trend: +2.3% | spacing violations: 2")
- The `/api/training/timeline` export endpoint is not wired into the HUD
- No progress bar for "how far to the target"

---

## B. Remaining Problem Priorities

### High Priority (root causes of the experience still not meeting the bar)

| # | Problem | Gap | Suggestion |
|---|---|---|---|
| 1 | **3D distance annotation lines** | conflict spacing has no spatial visualization | add `Line2` + `CSS2DRenderer` distance labels in `focusMonitorCheckpoint` |
| 2 | **Checklist-style workflow progress** | badge row ≠ progress checklist | render `stages` as a checkbox list + "current step" highlight |
| 3 | **Interaction channel convergence** | token commands are still exposed to users | remove the `handleMonitorConversation` token path and `_attachMonitorEditChoices` |
| 4 | **Graphical trends** | plain-text lines ≠ trends | add sparklines (V100/D90 time series) |
| 5 | **Auto dose on by default** | core feedback requires manual triggering | enable auto-compare by default in monitoring mode |

### Medium Priority (experience can be improved)

| # | Problem | Gap | Suggestion |
|---|---|---|---|
| 6 | severity blocking level | only 2 levels | add a blocking level + CSS styling |
| 7 | OAR Dmax as a card | one line of text ≠ a card | display a list of Dmax per organ |
| 8 | plan_score display | not displayed | add to the metrics grid |
| 9 | Unviewed-screenshot indicator | entirely absent | add a pending-screenshot count to the HUD |
| 10 | Clickable object IDs | only button-level locating | render IDs as clickable links |

### Low Priority (requires product decisions)

| # | Problem | Gap | Suggestion |
|---|---|---|---|
| 11 | Automatic LLM clinical explanation | only an on-demand "Explain" button | requires product decision: whether to automatically attach an LLM explanation at each checkpoint |
| 12 | Edit pattern recognition | none | requires product decision: whether the LLM should observe the edit sequence and give pattern feedback |
| 13 | Personalized feedback | none | requires product decision: whether to adjust the level of detail based on user behavior |

---

## C. Conclusion

**Highlights of this remediation round**: the structured schema (Problem 3), evidence chain automatic retry (Problem 5), and state machine automatic recovery (Problem 9) essentially meet the bar; the Monitor HUD going from nothing to something is a qualitative leap.

**Core gaps**: spatial visualization (distance annotation lines), checklist-style workflow, interaction channel convergence, and graphical trends—these four are the key to going "from usable to good" and currently none meet the bar.

**Vision-to-implementation distance**: the "quiet, continuous, trustworthy practice coach" experience described in the audit report is currently about **50%** implemented. The deterministic engine and lifecycle management have reached production quality (Phase A/B complete), but the interaction experience layer (Phase C) still has significant gaps, especially in the two dimensions of spatial feedback and workflow guidance.
