# BrachyBot Full Feature Specification and Implementation Status

For the latest run contract, timeline export, and audit fixes for planning monitoring, see [Monitor architecture and verified audit](TRAINING_MONITOR_VERIFIED_2026-09-19.md).

> Last updated: 2026-06-22
> This document covers all feature modules, interaction expectations, fixed bugs, and API endpoints of the project.

---

## Table of Contents

- [I. Feature Modules Overview](#i-feature-modules-overview)
  - [1. LLM Chat System](#1-llm-chat-system)
  - [2. CTV Target Segmentation](#2-ctv-target-segmentation)
  - [3. OAR Organ-at-Risk Segmentation](#3-oar-organ-at-risk-segmentation)
  - [4. Planning Pipeline](#4-planning-pipeline)
  - [5. Dose Evaluation](#5-dose-evaluation)
  - [6. 2D Image Viewer](#6-2d-image-viewer)
  - [7. 3D Visualization](#7-3d-visualization)
  - [8. Data Tree](#8-data-tree)
  - [9. DVH Dose-Volume Histogram](#9-dvh-dose-volume-histogram)
  - [10. Report Panel](#10-report-panel)
  - [11. Todo Execution Progress](#11-todo-execution-progress)
  - [12. Thinking Chain](#12-thinking-chain)
  - [13. Multilingual System](#13-multilingual-system)
  - [14. Panel Layout and Dragging](#14-panel-layout-and-dragging)
  - [15. Session Management](#15-session-management)
  - [16. Web Search](#16-web-search)
  - [17. Quality Review](#17-quality-review)
- [II. Interaction Flows and Expected Behavior](#ii-interaction-flows-and-expected-behavior)
  - [1. Main Planning Flow](#1-main-planning-flow)
  - [2. Chat Interaction](#2-chat-interaction)
  - [3. 2D Viewer Interaction](#3-2d-viewer-interaction)
  - [4. 3D Viewer Interaction](#4-3d-viewer-interaction)
  - [5. Data Tree Interaction](#5-data-tree-interaction)
  - [6. DVH Interaction](#6-dvh-interaction)
  - [7. Report Panel Interaction](#7-report-panel-interaction)
  - [8. Panel Switching Interaction](#8-panel-switching-interaction)
  - [9. Global Controls Interaction](#9-global-controls-interaction)
- [III. Planning Pipeline in Detail](#iii-planning-pipeline-in-detail)
  - [1. Flow Overview](#1-flow-overview)
  - [2. SSE Event Stream](#2-sse-event-stream)
  - [3. step_callback Mechanism](#3-step_callback-mechanism)
  - [4. Automatic OAR Trigger](#4-automatic-oar-trigger)
  - [5. Frontend Response Chain](#5-frontend-response-chain)
  - [6. Planning Results API](#6-planning-results-api)
  - [7. 3D Mesh Data](#7-3d-mesh-data)
  - [8. Dose Evaluation Details](#8-dose-evaluation-details)
- [IV. Report Panel in Detail](#iv-report-panel-in-detail)
  - [1. Panel Layout](#1-panel-layout)
  - [2. Data Sources](#2-data-sources)
  - [3. Screenshot System](#3-screenshot-system)
  - [4. Language System](#4-language-system)
  - [5. Version Management](#5-version-management)
  - [6. Modal System](#6-modal-system)
  - [7. PDF Export](#7-pdf-export)
  - [8. BrachyBot Auto-fill](#8-brachybot-auto-fill)
- [V. List of Fixed Bugs](#v-list-of-fixed-bugs)
  - [1. Report Language Issue](#1-report-language-issue)
  - [2. 3D Viewer Blank](#2-3d-viewer-blank)
  - [3. DVH Tooltip Overflow](#3-dvh-tooltip-overflow)
  - [4. CTV Color Change Not Working](#4-ctv-color-change-not-working)
  - [5. Missing Report Auto-screenshots](#5-missing-report-auto-screenshots)
  - [6. Secondary UI Style Issue](#6-secondary-ui-style-issue)
  - [7. Quality Review Retry](#7-quality-review-retry)
  - [8. Todo Merge Logic](#8-todo-merge-logic)
  - [9. Todo Final Reply Count](#9-todo-final-reply-count)
  - [10. Heading Typography](#10-heading-typography)
- [VI. API Endpoint Reference](#vi-api-endpoint-reference)
- [VII. Tech Stack](#vii-tech-stack)

---

# I. Feature Modules Overview

## 1. LLM Chat System

### 1.1 Sending a Chat

| Item | Description |
|------|------|
| **Expected behavior** | User enters a message → sent to `/api/chat` → streamed back via SSE → reply displayed in real time |
| **Input method** | Text box + Enter to send / button click |
| **Streaming** | SSE (Server-Sent Events), `stream: true` |
| **Stop** | Clicking the button again while sending → abort via AbortController |
| **Implementation status** | ✅ Implemented |

### 1.2 Tool Call Display

| Item | Description |
|------|------|
| **Expected behavior** | When the LLM calls a tool, the Thinking Chain shows the tool name, parameters, and result |
| **Step status** | pending → done / error, with corresponding icon (⚙/✓/✕) |
| **Tool progress** | Shows a progress bar and percentage while the tool is executing |
| **Implementation status** | ✅ Implemented |

### 1.3 AI Reply Rendering

| Item | Description |
|------|------|
| **Expected behavior** | Markdown rendering: headings, tables, lists, code blocks, links |
| **Heading style** | ChatGPT style: H2 bottom divider, no left vertical bar, no emoji icon |
| **Table style** | Dark-theme table with the `.md-table` class name |
| **Links** | Open in a new window (`target="_blank"`) |
| **Implementation status** | ✅ Implemented (fixed 2026-06-22) |

### 1.4 Reply Footer

| Item | Description |
|------|------|
| **Expected behavior** | Shows at the bottom of the reply: elapsed time / input tokens / output tokens / tool call count |
| **Multilingual** | Shows Chinese/English labels according to the global language |
| **Implementation status** | ✅ Implemented |

---

## 2. CTV Target Segmentation

| Item | Description |
|------|------|
| **Expected behavior** | Upload CT → call the nnUNet segmentation model → return the CTV label map |
| **Input** | CT NIfTI file path + tumor type (`nnunet_pancreatic`, etc.) |
| **Output** | Multi-label segmentation result: label 1=tumor, 2=artery, 3=vein, 4=pancreas, etc. |
| **Post-processing** | Store `ctv_array`, `ctv_label_names`, `labelColorLUT` in memory |
| **Automatic trigger** | Called automatically when the planning pipeline detects that no CTV exists |
| **Data Tree** | Under the CTV node, tumor sub-labels are shown, each with its own color and 3D reconstruction button |
| **Implementation status** | ✅ Implemented |

---

## 3. OAR Organ-at-Risk Segmentation

| Item | Description |
|------|------|
| **Expected behavior** | Call TotalSegmentator on the CT → return 57+ organ labels |
| **Output** | `organ_names` dictionary: {label_id: organ_name} |
| **Categories** | Non-traversable (vessels, bones) / Traversable (soft-tissue organs) |
| **Automatic trigger** | After CTV segmentation, automatically checks the OAR count and calls when < 5 |
| **CTV label exclusion** | When loading OAR, exclude label IDs already belonging to the CTV (e.g. artery=2, vein=3) |
| **Implementation status** | ✅ Implemented |

---

## 4. Planning Pipeline

### 4.1 Overall Flow

```
CTV segmentation → OAR segmentation → planning_pipeline(step="full") → dose evaluation
```

| Step | Sub-step | Description | Implementation status |
|------|--------|------|----------|
| `ctv_segmentation` | — | CTV target segmentation | ✅ |
| `oar_segmentation` | — | OAR organ-at-risk segmentation (automatic/manual) | ✅ |
| `planning_pipeline` | `trajectory_init` | Trajectory initialization (130 candidates) | ✅ |
| | `trajectory_refine` | Trajectory refinement | ✅ |
| | `seed_planning` | Seed position optimization (14 seeds) | ✅ |
| | `dose_calc` | Dose calculation | ✅ |
| | `dose_eval` | Dosimetric evaluation | ✅ |

### 4.2 step_callback Mechanism

| Item | Description |
|------|------|
| **Expected behavior** | Each sub-step sends pending/done SSE events via `step_callback` |
| **Todo integration** | The Todo list shows a breathing animation for each sub-step in real time |
| **DRAIN mechanism** | DRAIN-1 (after tool execution) + DRAIN-2 (after store) ensure no events are lost |
| **Implementation status** | ✅ Implemented |

### 4.3 Automatic OAR

| Item | Description |
|------|------|
| **Trigger condition** | After CTV segmentation completes, the number of organs in the OAR map is < 5 |
| **Effect** | Automatically calls `oar_segmentation` and merges it into the CTV Todo item |
| **SSE event** | `oar_segmentation pending` → `oar_segmentation done` |
| **Todo display** | Merged into a single "CTV + OAR segmentation" item |
| **Implementation status** | ✅ Implemented (merge logic fixed 2026-06-22) |

### 4.4 Planning Result Metrics

| Metric | Description | Target value |
|------|------|--------|
| V100 | Target coverage | ≥ 90% |
| D90 | Minimum dose received by 90% of the target | ≥ 100 Gy |
| V150/V200 | High-dose volume ratio | ≤ 50% / ≤ 20% |
| CI | Conformity index | ≥ 0.6 |
| HI | Homogeneity index | ≤ 0.35 |
| Score | Overall score (0-100) | ≥ 80 |
| Seeds | Number of seeds | — |
| Trajectories | Number of needle tracks | — |

---

## 5. Dose Evaluation

| Item | Description |
|------|------|
| **Expected behavior** | Compute dose metrics for the CTV and all OARs |
| **CTV metrics** | Dmax, Dmin, Dmean, D98, D90, D2, V100, V150, V200, CI, HI |
| **OAR metrics** | D2cc, D1cc, D0.1cc, Max dose |
| **Output** | Stored in `dose_metrics` / `metrics` memory |
| **Implementation status** | ✅ Implemented |

---

## 6. 2D Image Viewer

### 6.1 Three Views

| View | Description | Implementation status |
|------|------|----------|
| Axial | Axial view (default) | ✅ |
| Sagittal | Sagittal view | ✅ |
| Coronal | Coronal view | ✅ |

### 6.2 Slice Dragging

| Item | Description |
|------|------|
| **Expected behavior** | Drag the slider → switch slice → re-render CT + overlay |
| **Mouse wheel** | Wheel switches slices |
| **Implementation status** | ✅ Implemented |

### 6.3 Label Overlay

| Item | Description |
|------|------|
| **Expected behavior** | CTV/OAR labels are overlaid on the CT slice in semi-transparent colors |
| **Colors** | From `labelColorLUT`; each label has its own RGB |
| **Toggleable** | Controlled via Data Tree visibility |
| **Implementation status** | ✅ Implemented |

### 6.4 Dose Overlay

| Item | Description |
|------|------|
| **Expected behavior** | Dose distribution is overlaid on the CT slice as a heatmap |
| **Color mapping** | Warm colors = high dose, cool colors = low dose |
| **Prescription line** | 120 Gy isodose line |
| **Toggle** | Dose overlay switch |
| **Implementation status** | ✅ Implemented |

---

## 7. 3D Visualization

### 7.1 Initialization

| Item | Description |
|------|------|
| **Expected behavior** | Initializes the Three.js scene when switching to the Viewers panel for the first time |
| **Camera** | PerspectiveCamera, initial position (0,0,300) |
| **Lights** | AmbientLight (0.6) + 3 DirectionalLights |
| **Controls** | OrbitControls: left-drag rotate, right-drag pan, wheel zoom |
| **Background** | Transparent (black CSS background) |
| **preserveDrawingBuffer** | `true` (ensures screenshots work) |
| **Implementation status** | ✅ Implemented (fixed 2026-06-22) |

### 7.2 Mesh Loading

| Mesh type | organ_id format | Source | Implementation status |
|----------|--------------|------|----------|
| CTV tumor | `ctv_1` | CTV segmentation label 1 | ✅ |
| CTV artery | `ctv_2` | CTV segmentation label 2 | ✅ |
| CTV vein | `ctv_3` | CTV segmentation label 3 | ✅ |
| CTV pancreas | `ctv_4` | CTV segmentation label 4 | ✅ |
| OAR non-traversable | `organ_{labelId}` | OAR segmentation (excluding CTV labels) | ✅ |
| OAR traversable | `organ_{labelId}` | OAR segmentation | ✅ |
| Seeds | `seed_{idx}` | Planning results | ✅ |
| Needles | `needle_{idx}` | Planning results | ✅ |
| Dose isosurfaces | `dose_iso_{threshold}` | Dose calculation | ✅ |

### 7.3 Automatic Loading and Reconstruction Consistency

| Item | Description |
|------|------|
| **Expected behavior** | Automatic loading = right-click 3D Reconstruction = Data Tree control |
| **Unified organ_id** | CTV: `ctv_{lid}`, OAR: `organ_{lid}` |
| **Color source** | `labelColorLUT` / `dataTreeState` |
| **Duplicate prevention** | CTV label IDs are excluded from non-traversable OAR loading |
| **Camera fitting** | `fitCameraToScene()` automatically adjusts the camera to the mesh bounding box |
| **Panel switching** | `forceRender3DViewer()` re-initializes when switching to the Viewers panel |
| **Implementation status** | ✅ Implemented (panel switching fixed 2026-06-22) |

### 7.4 Orientation Axes

| Item | Description |
|------|------|
| **Expected behavior** | Shows R/A/S orientation axes in the lower-left corner, rotating with the main camera |
| **Implementation status** | ✅ Implemented |

---

## 8. Data Tree

### 8.1 Structure

```
Segmentation
├── CTV
│   └── pancreatic tumor (ctv_1)
│   └── artery (ctv_2)
│   └── vein (ctv_3)
│   └── pancreas (ctv_4)
├── OAR (57)
│   ├── Non-traversable
│   │   ├── aorta (organ_X)
│   │   └── vertebrae_* (organ_X)
│   └── Traversable
│       ├── stomach (organ_X)
│       └── liver (organ_X)
Planning
├── Seeds (seed_0, seed_1, ...)
├── Needles (needle_0, needle_1, ...)
└── Dose Isosurfaces (dose_iso_120, dose_iso_180, ...)
```

### 8.2 Context Menu

| Menu item | Applies to | Function | Implementation status |
|--------|---------|------|----------|
| 3D Reconstruct | Organ/CTV | 3D-reconstruct a single organ | ✅ |
| 3D Reconstruct All | Multi-select | Batch 3D reconstruction | ✅ |
| Change Color | Single organ/CTV/seed/needle track | Opens the color picker | ✅ (CTV fixed 2026-06-22) |
| Move to Category | OAR organ | Move to traversable/non-traversable | ✅ |
| Show Selected | Multi-select | Show selected items | ✅ |
| Hide Selected | Multi-select | Hide selected items | ✅ |
| Solo Selected | Multi-select | Show only selected items | ✅ |
| Opacity | Multi-select | Set opacity (100/75/50/25%) | ✅ |
| Show All | All | Show all organs | ✅ |

### 8.3 Color Picker

| Item | Description |
|------|------|
| **Expected behavior** | HSV sliders + preset swatches + live preview |
| **2D sync** | After a change, updates `labelColorLUT` → 2D overlay redraws |
| **3D sync** | After a change, updates `mesh.material.color` → 3D mesh changes color immediately |
| **Supported objects** | organ_* , ctv_* , seed_* , needle_* , dose_iso_* |
| **Implementation status** | ✅ Implemented (CTV + 3D sync fixed 2026-06-22) |

### 8.4 Visibility Control

| Item | Description |
|------|------|
| **Eye icon** | Click to toggle a single organ's visibility |
| **Group toggle** | Group-level toggle for CTV/OAR/Planning |
| **3D sync** | Visibility changes sync to the 3D mesh |
| **Implementation status** | ✅ Implemented |

---

## 9. DVH Dose-Volume Histogram

### 9.1 Rendering

| Item | Description |
|------|------|
| **Expected behavior** | Plotly.js renders dose-volume curves for the CTV + all OARs |
| **X axis** | Dose (Gy) |
| **Y axis** | Volume (%) |
| **Number of curves** | 1 (CTV) + N (OARs) |
| **Prescription line** | 120 Gy vertical dashed line |
| **Implementation status** | ✅ Implemented |

### 9.2 Tooltip

| Item | Description |
|------|------|
| **Expected behavior** | Hovering shows the organ name + dose value + volume value |
| **Style** | Dark background (`rgba(15,23,42,0.95)`) + light text |
| **Overflow protection** | SVG viewBox coordinate clamp; the tooltip does not exceed the chart area |
| **CJK font** | Microsoft YaHei / PingFang SC / Noto Sans CJK SC |
| **Implementation status** | ✅ Implemented (clamp fixed 2026-06-22) |

### 9.3 Click-to-Pick

| Item | Description |
|------|------|
| **Expected behavior** | Click a curve → place a marker at that point (dose, volume, organ name) |
| **Implementation status** | ✅ Implemented |

---

## 10. Report Panel

### 10.1 Editor

| Item | Description |
|------|------|
| **Expected behavior** | Sectioned editing: patient information / imaging / planning / dose / OAR / interpretation / references |
| **Auto-fill** | Pulls data from the server-side `/api/report/auto-fill` |
| **Live preview** | The PDF preview on the right updates in real time |
| **Implementation status** | ✅ Implemented |

### 10.2 Language

| Item | Description |
|------|------|
| **Expected behavior** | Follows the global EN/中 button; does not infer from the user's input language |
| **Fix** | `refreshFinalReport` / `reportAutoFill` prioritize `window._i18nLang` |
| **Implementation status** | ✅ Fixed (2026-06-22) |

### 10.3 Automatic Screenshot Capture

| Screenshot | Source | Implementation status |
|------|------|----------|
| CTV/OAR segmentation overlay | 2D viewer canvas (axial) | ✅ |
| Dose distribution heatmap | 2D viewer canvas (if dose overlay is on) | ✅ |
| 3D treatment plan | Three.js canvas (`preserveDrawingBuffer`) | ✅ (fixed 2026-06-22) |
| DVH curves | `Plotly.toImage()` | ✅ |

**Trigger timing**:
1. After `refreshPlanningUI` completes (planning finished)
2. When the Report panel is opened
3. When Auto-fill is clicked
4. When exporting a PDF

### 10.4 PDF Export

| Item | Description |
|------|------|
| **Expected behavior** | html2canvas renders the report page → generates a PDF |
| **Language** | Follows `reportForm.language` |
| **Implementation status** | ✅ Implemented |

### 10.5 Version Snapshots

| Item | Description |
|------|------|
| **Save** | 📸 Snapshot → stores the current form in localStorage |
| **Restore** | 📜 History → lists historical snapshots → Restore |
| **Implementation status** | ✅ Implemented |

### 10.6 Audit Log

| Item | Description |
|------|------|
| **Expected behavior** | 🔍 Audit → shows timestamps and details of all editing operations |
| **Implementation status** | ✅ Implemented |

### 10.7 Field Validation

| Item | Description |
|------|------|
| **Expected behavior** | ✅ Validate → checks required fields and dose ranges |
| **Checked items** | Patient name/sex/ID, diagnosis, D90 range, V100 range, CI range |
| **Implementation status** | ✅ Implemented |

---

## 11. Todo Execution Progress

### 11.1 Display

| Item | Description |
|------|------|
| **Expected behavior** | The bottom Dock shows the current workflow steps and completion status |
| **Pre-fill** | Pre-fills 3 steps on a planning request: CTV → OAR → Planning |
| **Status** | Predicted (hollow) → active (breathing animation) → done (✓) → error (✕) |
| **Count** | The header shows "(done/total)" |
| **GPU status** | Shows GPU usage information next to the active step |
| **Implementation status** | ✅ Implemented |

### 11.2 Merge Logic

| Item | Description |
|------|------|
| **CTV + OAR merge** | Automatic OAR is merged into the CTV item; the label becomes "CTV + OAR segmentation" |
| **Completion condition** | Marked done only after both CTV and OAR are done |
| **dedup path** | When dedup finds a merged item, it also follows the `_mergedDone` logic |
| **Implementation status** | ✅ Fixed (2026-06-22) |

### 11.3 Collapse and Hide

| Item | Description |
|------|------|
| **Auto-collapse** | Collapses to the header after the AI reply completes |
| **Auto-hide** | Fades out 4 seconds after collapsing |
| **Manual expand** | Click the header to expand and view details |
| **Clear on new message** | Clears the old todo each time a new message begins |
| **Implementation status** | ✅ Implemented |

---

## 12. Thinking Chain

| Item | Description |
|------|------|
| **Expected behavior** | Shows the LLM call chain: user input → LLM thinking → tool call → result → reply |
| **Real-time updates** | SSE events append steps in real time |
| **Collapse/expand** | Click the header to collapse/expand |
| **Step details** | Click a single step to expand and view parameters and results |
| **Timing** | The header shows the total elapsed time |
| **Auto-collapse** | Automatically collapses after the AI reply |
| **Implementation status** | ✅ Implemented |

---

## 13. Multilingual System

### 13.1 Global Language

| Item | Description |
|------|------|
| **Toggle** | EN/中 chip button in the upper-right corner |
| **Storage** | `window._i18nLang` + localStorage |
| **Scope** | Todo labels / tool progress / report / status messages |
| **Implementation status** | ✅ Implemented |

### 13.2 LLM Reply Language

| Item | Description |
|------|------|
| **Expected behavior** | The LLM reply language matches the user's input language |
| **Implementation** | `memory/language.py` detects the input language → injects a system prompt clause |
| **Implementation status** | ✅ Implemented |

### 13.3 Report Language

| Item | Description |
|------|------|
| **Expected behavior** | Follows the global language button; does not infer from user input |
| **Fix** | `refreshFinalReport` / `reportAutoFill` prioritize `window._i18nLang` |
| **Implementation status** | ✅ Fixed (2026-06-22) |

---

## 14. Panel Layout and Dragging

### 14.1 Panel Switching

| Panel | Tab name | Content | Implementation status |
|------|--------|------|----------|
| Input | 📁 Input | CT upload + tumor type selection | ✅ |
| Metrics | 📊 Metrics | Planning metrics + DVH + OAR table | ✅ |
| Viewers | 🖼️ Viewers | 2D three views + 3D visualization | ✅ |
| Report | 📋 Report | Report editor + PDF preview | ✅ |

### 14.2 Draggable Dividers

| Item | Description |
|------|------|
| **Expected behavior** | The three-column layout (left/center/right) can be resized by dragging dividers |
| **Persistence** | Widths are saved to localStorage |
| **Cursor** | Shows `col-resize` while dragging |
| **Implementation status** | ✅ Implemented |

---

## 15. Session Management

| Item | Description |
|------|------|
| **Auto-create** | Automatically creates a "New chat" session when the first message is sent |
| **Persistence** | Sessions are saved to localStorage and restored after refresh |
| **Switch** | Click a session in the left-hand list to switch |
| **Clear** | The "Clear" button clears the current session |
| **Implementation status** | ✅ Implemented |

---

## 16. Web Search

| Item | Description |
|------|------|
| **Expected behavior** | Calls the `web_search` tool when the LLM determines web access is needed |
| **Search sources** | DuckDuckGo / Wikipedia / arXiv, etc. |
| **Result display** | Summary + source links |
| **Implementation status** | ✅ Implemented |

---

## 17. Quality Review

| Item | Description |
|------|------|
| **Expected behavior** | Multi-agent (PlanReviewer + FactChecker + SafetyGuardian) review of planning results |
| **Review result** | PASS / CONDITIONAL / REJECT / ESCALATE |
| **Current status** | ⚠️ Disabled (2026-06-22) |
| **Reason for disabling** | After review, a mysterious "Review Feedback" retry was triggered, generating an English stub that overwrote the Chinese report |
| **Follow-up plan** | Re-enable after locating the source of the retry |

---

# II. Interaction Flows and Expected Behavior

## 1. Main Planning Flow

```
User input: "请执行放射性粒子植入规划"
         ↓
sendChat() → POST /api/chat (stream: true)
         ↓
SSE event stream:
  1. start (language detection)
  2. step: Crystallized Skill (memory matching)
  3. step: Experience Recall (experience recall)
  4. step: LLM Call 1 (routing decision)
  5. step: ctv_segmentation pending → done
  6. step: oar_segmentation pending → done (automatic trigger)
  7. step: LLM Call 2 (decides to call planning_pipeline)
  8. step: planning_pipeline pending
     8a. step: trajectory_init pending → done
     8b. step: trajectory_refine pending → done
     8c. step: seed_planning pending → done
     8d. step: dose_calc pending → done
     8e. step: dose_eval pending → done
  9. step: planning_pipeline done
  10. step: LLM Call 3 (generates reply)
  11. text_chunk: streaming reply text
  12. step: AI Response done
  13. response: final reply
  14. done
```

**Expected behavior**:
- The Todo list updates each step's status in real time
- The Thinking Chain shows the complete call chain
- The final reply is a complete Chinese planning report
- The Metrics panel automatically updates the metrics
- DVH is drawn automatically
- 3D meshes are loaded automatically
- Report screenshots are captured automatically

**Current status**: ✅ Correctly implemented

---

## 2. Chat Interaction

| Action | Expected behavior | Status |
|------|---------|------|
| Enter | Send message | ✅ |
| Click send button | Send message | ✅ |
| Shift+Enter | New line without sending | ✅ |
| Click again while sending | Abort the current request | ✅ |
| Up/Down arrows | Browse message history | ✅ |
| First step event | Replaces with the Thinking Chain | ✅ |
| text_chunk | Appends to the reply bubble in a stream | ✅ |
| AI Response done | Renders Markdown, collapses the Thinking Chain | ✅ |
| done | Shows the Footer (elapsed time/tokens/tool count) | ✅ |
| Todo pending | Breathing animation, timer starts | ✅ |
| Todo done | ✓ marker, shows elapsed time | ✅ |
| AI Response done | Marks all incomplete items done, collapses | ✅ (fixed 2026-06-22) |
| Collapsed 4s | Fades out and hides | ✅ |
| New message | Clears the old Todo | ✅ |

---

## 3. 2D Viewer Interaction

| Action | Expected behavior | Status |
|------|---------|------|
| Drag slider | Switch slice, render in real time | ✅ |
| Mouse wheel | Switch slice | ✅ |
| Keyboard ←/→ | Previous/next slice | ✅ |
| Window input | Adjust window width | ✅ |
| Level input | Adjust window level | ✅ |
| Mouse drag (left button) | Adjust window width/level | ✅ |
| Wheel | Zoom | ✅ |
| Right-drag | Pan | ✅ |
| Double-click | Reset zoom | ✅ |
| Label overlay toggle | Show/hide CTV/OAR contours | ✅ |
| Dose overlay toggle | Show/hide the dose heatmap | ✅ |
| Dose threshold slider | Adjust the dose display threshold | ✅ |

---

## 4. 3D Viewer Interaction

| Action | Expected behavior | Status |
|------|---------|------|
| Left-drag | Rotate | ✅ |
| Right-drag | Pan | ✅ |
| Wheel | Zoom | ✅ |
| 3D.fit button | Reset the camera to the mesh bounding box | ✅ |
| Opacity slider | Adjust the opacity of all meshes | ✅ |
| Wireframe toggle | Toggle wireframe mode | ✅ |
| Skin toggle | Show/hide the CT skin | ✅ |

---

## 5. Data Tree Interaction

| Action | Expected behavior | Status |
|------|---------|------|
| Single click | Select item | ✅ |
| Ctrl+click | Multi-select/deselect | ✅ |
| Shift+click | Range select (within the same group) | ✅ |
| Click eye icon | Toggle a single item's visibility | ✅ |
| Group eye icon | Toggle the whole group's visibility | ✅ |
| Right-click 3D Reconstruct | 3D-reconstruct the selected organ | ✅ |
| Right-click Change Color | Open the color picker | ✅ (CTV fixed 2026-06-22) |
| Right-click Show/Hide Selected | Show/hide selected items | ✅ |
| Right-click Solo Selected | Show only selected items | ✅ |
| Right-click Opacity | Set opacity | ✅ |

---

## 6. DVH Interaction

| Action | Expected behavior | Status |
|------|---------|------|
| Hover over a curve | Show tooltip (organ name + dose + volume) | ✅ |
| Tooltip stays within the chart | SVG viewBox coordinate clamp | ✅ (fixed 2026-06-22) |
| Click a curve | Place a marker (dose, volume, organ name) | ✅ |
| Click a marker | Remove the marker | ✅ |
| Wheel/drag | Zoom/pan | ✅ |
| Double-click | Reset | ✅ |

---

## 7. Report Panel Interaction

| Action | Expected behavior | Status |
|------|---------|------|
| Click a field | Edit mode | ✅ |
| Enter content | Update the preview in real time | ✅ |
| Auto-fill | Auto-fill from the server | ✅ |
| 📷 Capture 2D/3D/DVH | Capture screenshots | ✅ |
| Upload | Upload a custom image | ✅ |
| 📸 Snapshot | Save the current version | ✅ |
| 📜 History | View/restore historical versions | ✅ |
| 📋 Audit | View editing history | ✅ |
| ✅ Validate | Validate required fields | ✅ |
| Export PDF | Generate a PDF | ✅ |

---

## 8. Panel Switching Interaction

| Action | Expected behavior | Status |
|------|---------|------|
| Click the Input tab | Show the input panel | ✅ |
| Click the Metrics tab | Show the metrics panel + DVH | ✅ |
| Click the Viewers tab | Show the 2D/3D viewers, re-initialize 3D | ✅ (fixed 2026-06-22) |
| Click the Report tab | Show the report editor, auto-capture screenshots on first open | ✅ |

---

## 9. Global Controls Interaction

| Action | Expected behavior | Status |
|------|---------|------|
| Click EN/中 | Toggle the global language | ✅ |
| Todo after switching | Labels update to the new language | ✅ |
| Report after switching | Report language updates | ✅ (fixed 2026-06-22) |
| Footer after switching | Footer labels update | ✅ |
| Drag dividers | Adjust panel widths, saved to localStorage | ✅ |
| Clear button | Clear the current session | ✅ |
| Refresh page | Restore the last session | ✅ |

---

# III. Planning Pipeline in Detail

## 1. Flow Overview

```
User: "请执行放射性粒子植入规划"
    │
    ├─→ [1] CTV segmentation (ctv_segmentation)
    │       ├─ nnUNet inference
    │       ├─ Return multi-label mask (tumor/artery/vein/pancreas)
    │       └─ Store ctv_array, ctv_label_names, labelColorLUT
    │
    ├─→ [2] OAR segmentation (oar_segmentation) [automatic trigger]
    │       ├─ TotalSegmentator inference
    │       ├─ Return 57+ organ labels
    │       └─ Store oar_array, organ_names
    │
    ├─→ [3] Planning pipeline (planning_pipeline, step="full")
    │       ├─ 3a. Trajectory initialization (trajectory_init) → 130 candidates
    │       ├─ 3b. Trajectory refinement (trajectory_refine) → select the best
    │       ├─ 3c. Seed planning (seed_planning) → 14 seeds
    │       ├─ 3d. Dose calculation (dose_calc) → 3D dose distribution
    │       └─ 3e. Dose evaluation (dose_eval) → V100/D90/CI/HI
    │
    └─→ [4] LLM generates the final reply
            └─ 10-section structured report (Chinese/English)
```

---

## 2. SSE Event Stream

### 2.1 Event Types

| Event | Format | Description |
|------|------|------|
| `start` | `{language: {code: "zh"/"en"}}` | Session start, contains the detected language |
| `step` | `{id, type, title, content, status, tool, params, result}` | Step event |
| `text_chunk` | `{text: "..."}` | LLM reply text stream |
| `response` | `{response: "...", llm_meta: {...}}` | Final reply |
| `done` | `{context: {...}}` | End of stream |
| `error` | `{message: "..."}` | Error |

### 2.2 Complete Event Sequence

```
event: start
data: {"language": {"code": "zh"}}

event: step
data: {"id": 1, "type": "user", "title": "User Input", "status": "done"}

event: step
data: {"id": 2, "type": "memory", "title": "Crystallized Skill", "status": "done"}

event: step
data: {"id": 3, "type": "thinking", "title": "LLM Call 1", "status": "done"}

event: step
data: {"id": 4, "type": "tool", "tool": "ctv_segmentation", "status": "pending"}

event: step
data: {"id": 4, "type": "tool", "tool": "ctv_segmentation", "status": "done",
       "result": "CTV segmentation completed. Volume: 26197.3 mm3"}

event: step
data: {"id": 5, "type": "tool", "tool": "oar_segmentation", "status": "pending",
       "parent_tool": "ctv_segmentation"}

event: step
data: {"id": 5, "type": "tool", "tool": "oar_segmentation", "status": "done",
       "result": "57 organs", "parent_tool": "ctv_segmentation"}

event: step
data: {"id": 6, "type": "tool", "tool": "planning_pipeline", "status": "pending"}

event: step
data: {"id": 7, "type": "tool", "tool": "trajectory_init", "status": "pending",
       "parent_tool": "planning_pipeline"}

event: step
data: {"id": 7, "type": "tool", "tool": "trajectory_init", "status": "done",
       "result": "130 trajectories", "parent_tool": "planning_pipeline"}

... (trajectory_refine, seed_planning, dose_calc, dose_eval same as above)

event: step
data: {"id": 6, "type": "tool", "tool": "planning_pipeline", "status": "done",
       "result": "Planning completed: 14 seeds. V100=91.0%..."}

event: step
data: {"id": 12, "type": "thinking", "title": "LLM Call 3", "status": "done"}

event: text_chunk
data: {"text": "## 1. 流程总结\n\n已完成放射性粒子植入规划全流程..."}

event: step
data: {"id": 13, "type": "assistant", "title": "AI Response", "status": "done"}

event: response
data: {"response": "## 1. 流程总结\n\n...", "llm_meta": {...}}

event: done
data: {"context": {...}}
```

---

## 3. step_callback Mechanism

### 3.1 Purpose

Expose the 5 sub-steps inside `planning_pipeline` as independent SSE step events, so the Todo list can show the progress of each sub-step in real time.

### 3.2 Implementation

```python
# Called inside the tool:
step_callback("trajectory_init", "pending", "Generating candidate trajectories")
# ... execute ...
step_callback("trajectory_init", "done", "130 trajectories")
```

### 3.3 DRAIN Timing

| DRAIN | Position | Purpose |
|-------|------|------|
| DRAIN-1 | After `_execute_tool_with_memory` returns | Flush sub-step events generated during tool execution |
| DRAIN-2 | After `_store_tool_result` returns | Flush events triggered by auto-OAR, etc. |

---

## 4. Automatic OAR Trigger

### 4.1 Trigger Condition

After CTV segmentation completes, `oar_segmentation` is called automatically when the number of organs in the OAR map is < 5.

### 4.2 Todo Merge

```javascript
if (step.tool === 'oar_segmentation' && step.parent_tool === 'ctv_segmentation') {
    ctvItem.label = 'CTV + OAR segmentation';
    ctvItem._mergedOAR = true;
    // Remove the predicted OAR item
}
```

### 4.3 Completion Condition

```javascript
if (item._mergedOAR) {
    item._mergedDone[step.tool] = true;
    if (item._mergedDone['ctv_segmentation']
        && item._mergedDone['oar_segmentation']) {
        todo.markDone(item);
    }
}
```

---

## 5. Frontend Response Chain

### 5.1 refreshPlanningUI Execution Order

```
1. fetch /api/planning/results
2. updateMetrics (metric cards)
3. drawDVH (DVH curves)
4. updateImageAnalysis (image analysis)
5. loadCTVAndObstacleMeshes (CTV + OAR 3D meshes)
6. loadSeeds3D (3D seeds)
7. loadAllIsoSurfaces (isodose surfaces)
8. reportAutoFill (report auto-fill)
9. await Promise.all (wait for all meshes to load)
10. forceRender3DViewer (re-render 3D)
11. updateClinicalEvaluation (clinical evaluation)
12. autoCaptureReportFigures (report screenshots)
```

---

## 6. Planning Results API

### GET /api/planning/results

```json
{
    "success": true,
    "metrics": {
        "v100": 91.0, "d90": 123.22, "v150": 80.7, "v200": 69.0,
        "ci": 0.828, "hi": 93.638, "plan_score": 73,
        "oar_metrics": {
            "stomach": {"d2cc": 92.68, "d1cc": 108.19},
            "liver": {"d2cc": 25.16, "d1cc": 38.37}
        }
    },
    "dvh": {
        "CTV": {"dose": [...], "volume": [...]},
        "stomach": {"dose": [...], "volume": [...]}
    },
    "seeds": [{"x": 1.2, "y": 3.4, "z": 5.6}],
    "needles": [{"start": [...], "end": [...]}],
    "total_seeds": 14,
    "num_trajectories": 2,
    "has_dose": true
}
```

---

## 7. 3D Mesh Data

### GET /api/viewer/3d_mask

```json
{
    "success": true,
    "vertices": [[x, y, z], ...],
    "faces": [[i, j, k], ...],
    "color": [255, 0, 0],
    "label_name": "pancreatic tumor",
    "label_id": 1
}
```

---

## 8. Dose Evaluation Details

### OAR Dose Constraints (Pancreatic Cancer)

| Organ | D2cc constraint | Source |
|------|----------|------|
| stomach | < 90 Gy | GEC-ESTRO |
| duodenum | < 90 Gy | GEC-ESTRO |
| small_bowel | < 90 Gy | GEC-ESTRO |
| kidney | < 50 Gy | GEC-ESTRO |
| spinal cord | < 50 Gy | GEC-ESTRO |
| liver | < 60 Gy | GEC-ESTRO |

---

# IV. Report Panel in Detail

## 1. Panel Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Report Toolbar                                              │
│  📷 Capture | ✨ Auto-fill | 📸 Snapshot | 📜 History       │
│  🔍 Audit | ✅ Validate | 📤 Export PDF | EN/中 | Zoom      │
│                                                              │
│  ┌──────────────────────────┐ ┌────────────────────────────┐│
│  │  Editor (top)            │ │  Preview (bottom)          ││
│  │  [Patient] [Imaging]     │ │  [PDF Preview]             ││
│  │  [Planning] [Dose]       │ │  [DVH Figure]              ││
│  │  [OAR] [Interpretation]  │ │  [3D Figure]               ││
│  │  [References] [Figures]  │ │                            ││
│  └──────────────────────────┘ └────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Data Sources

| Field | Source | API |
|------|------|-----|
| Patient ID | CT file name | — |
| Imaging modality | DICOM tags | `/api/header/info` |
| Slice count/spacing/slice thickness | CT shape/spacing | `/api/header/info` |
| CTV volume | CTV segmentation result | `/api/report/auto-fill` |
| OAR count | Data Tree | `/api/report/auto-fill` |
| Total seed count | planning results | `/api/report/auto-fill` |
| V100/D90/CI/HI | dose_metrics | `/api/report/auto-fill` |
| OAR D2cc/D1cc | oar_metrics | `/api/report/auto-fill` |

---

## 3. Screenshot System

### 3.1 Screenshot Types

| Type | Source | Title (EN) | Title (ZH) |
|------|------|-----------|-----------|
| Segmentation | 2D viewer (axial) | CTV and OAR segmentation overlay | 靶区与危及器官分割重建 |
| Dose | 2D viewer (dose overlay) | Dose distribution heatmap | 剂量分布热图 |
| 3D Plan | Three.js canvas | 3D treatment plan | 三维规划方案 |
| DVH | Plotly.toImage | DVH — Dose Volume Histogram | DVH 剂量体积直方图 |

### 3.2 Special Handling for 3D Screenshots

```javascript
// preserveDrawingBuffer: true ensures the hidden canvas can be captured
scene3D.renderer.render(scene3D.scene, scene3D.camera);  // explicit render
const dataUrl = canvas3d.toDataURL('image/png');
if (dataUrl.length > 1000) { ... }  // check for non-blank
```

### 3.3 Deduplication Logic

```javascript
const _lastPlan = window.state.lastPlanTimestamp;
if (_lastPlan) {
    figures = figures.filter(f => {
        if (f.type === 'upload') return true;  // keep user uploads
        return f.capturedAt >= _lastPlan;       // discard old screenshots
    });
}
if (figures.length > 0) return;  // only capture when there are no screenshots
```

---

## 4. Language System

### 4.1 Language Source Priority

```
1. window._i18nLang (global EN/中 button)
2. window.reportForm.language (restored from localStorage)
3. 'en' (hard-coded default)
```

### 4.2 Language Switching Flow

```
User clicks EN/中
    ↓
window._i18nLang = 'en'
    ↓
reportForm.language = 'en'
    ↓
_autoFillInterpretation()    // regenerate interpretation
renderReportEditor()          // re-render editor
_updateReportPreview()        // re-render preview
    ↓
Clear old screenshots (keep user uploads)
autoCaptureReportFigures()    // re-capture screenshots with new-language titles
```

---

## 5. Version Management

### 5.1 Snapshots

```javascript
Report.snapshots.save(label)     // save to localStorage
Report.snapshots.restore(idx)    // restore the specified version
Report.snapshots.list()          // list all snapshots
```

### 5.2 Validation Rules

```javascript
const THRESHOLDS = {
    'metrics.v100':  { ok: v => v >= 90,  warn: v => v >= 80 },
    'metrics.d90':   { ok: v => v >= 100, warn: v => v >= 85 },
    'metrics.v150':  { ok: v => v <= 50,  warn: v => v <= 70 },
    'metrics.v200':  { ok: v => v <= 20,  warn: v => v <= 30 },
    'metrics.ci':    { ok: v => v >= 0.6, warn: v => v >= 0.4 },
    'metrics.hi':    { ok: v => v <= 0.35, warn: v => v <= 0.5 },
    'metrics.score': { ok: v => v >= 80,  warn: v => v >= 60 },
};
```

---

## 6. Modal System

```javascript
function _showModal(title, body) {
    // dark theme styling (fixed 2026-06-22)
    overlay: position:fixed; inset:0; background:rgba(15,23,42,0.6);
    dialog: background:var(--bg-2,#1e293b); border:1px solid var(--card-border,#334155);
    text: color:var(--text,#e2e8f0);
}
```

---

## 7. PDF Export

```javascript
async function exportReportPDF() {
    await autoCaptureReportFigures();  // 1. auto-capture screenshots
    _updateReportPreview();             // 2. re-render preview
    await new Promise(r => setTimeout(r, 200));  // 3. wait for DOM
    // 4. html2canvas renders each page
    // 5. save PDF: BrachyPlan_Report_{PatientID}_{date}.pdf
}
```

---

## 8. BrachyBot Auto-fill

### Fill Scope

| scope | Fill content |
|-------|---------|
| `all` | All fields |
| `patient` | Patient information |
| `metrics` | Planning metrics |
| `oar` | OAR dose table |
| `interpretation` | Clinical interpretation |
| `safety` | Safety warnings |

---

# V. List of Fixed Bugs

## 1. Report Language Issue

**User feedback**: The global button was English, but after planning finished the report PDF automatically switched to Chinese.

**Root cause**: In `refreshFinalReport()` and `reportAutoFill()`, `_detectLanguageFromText(window._lastUserMessage)` overwrote `reportForm.language = 'zh'` whenever Chinese input was detected, ignoring the global English setting.

**Fix**: Both places were changed to prioritize `window._i18nLang`.

```javascript
// Before (broken):
const detected = _detectLanguageFromText(window._lastUserMessage);
if (detected) window.reportForm.language = detected;

// After (fixed):
if (typeof window._i18nLang === 'string') {
    window.reportForm.language = window._i18nLang;
} else if (window._lastUserMessage) {
    const detected = _detectLanguageFromText(window._lastUserMessage);
    if (detected) window.reportForm.language = detected;
}
```

**Status**: ✅ Fixed

---

## 2. 3D Viewer Blank

**User feedback**: After planning finished, the 3D window was pitch black.

**Root cause**: Three overlapping issues:
1. WebGLRenderer had no `preserveDrawingBuffer`, so `toDataURL` on the hidden canvas returned blank
2. `forceRender3DViewer()` was not called when switching to the Viewers panel
3. Screenshot capture did not force a render frame

**Fix**:
- `preserveDrawingBuffer: true`
- Call `forceRender3DViewer()` in `switchPanel('viewers')`
- Explicit `renderer.render()` before capturing

**Status**: ✅ Fixed

---

## 3. DVH Tooltip Overflow

**User feedback**: The DVH curve tooltip text floated directly above the chart.

**Root cause**: `_clampDvhTooltip` ran before Plotly positioning and mixed screen coordinates with SVG coordinates.

**Fix**: Deferred execution with `requestAnimationFrame` and clamped using the SVG `viewBox` coordinate system.

```javascript
function _clampDvhTooltip() {
    requestAnimationFrame(() => {
        const mainSvg = dvhEl.querySelector('.main-svg');
        const vb = mainSvg.viewBox.baseVal;
        const svgW = vb.width || mainSvg.clientWidth;
        // ... clamp x,y to the range [0, svgW-tw]
    });
}
```

**Status**: ✅ Fixed

---

## 4. CTV Color Change Not Working

**User feedback**: Right-clicking a CTV mask in the Data Tree and clicking Change Color had no effect.

**Root cause**: `openColorPicker()` did not handle `ctv_*` IDs. At the end of `applyColor()`, an undefined `input.click()` threw a ReferenceError.

**Fix**:
- Added a `ctv_*` branch that reads state from `dataTreeState.ctvLabels`
- Added 3D mesh color updates to `applyColor()`
- Removed `input.click()`

**Status**: ✅ Fixed

---

## 5. Missing Report Auto-screenshots

**User feedback**: After planning finished, DVH/3D screenshots were not automatically placed in the Report.

**Root cause**: `autoCaptureReportFigures` was not called after `refreshPlanningUI` completed.

**Fix**: Added `await autoCaptureReportFigures()` at the end of `refreshPlanningUI`.

**Timing**: drawDVH → await meshes → forceRender3DViewer → autoCaptureReportFigures

**Status**: ✅ Fixed

---

## 6. Secondary UI Style Issue

**User feedback**: In secondary screens such as History/Audit/Validate, light-colored text on a light-colored background was hard to read.

**Root cause**: `_showModal()` used `background:#fff` (white background) while the content used dark-theme colors.

**Fix**: Changed all modals to the dark theme (`var(--bg-2)`); content uses CSS variables + fallback.

**Status**: ✅ Fixed

---

## 7. Quality Review Retry

**User feedback**: After the answer finished, a new, perfunctory English answer appeared.

**Root cause**: After a Quality Review REJECT, a "Review Feedback" retry was triggered, and the LLM generated a short English stub that overwrote the Chinese report.

**Fix**: Disabled all 3 Quality Review call sites.

**Status**: ⚠️ Disabled (re-enable after locating the source of the retry)

---

## 8. Todo Merge Logic

**User feedback**: The Todo showed "CTV segmentation running → OAR segmentation completed", missing CTV completed.

**Root cause**: The dedup path called `markDone(existing)` directly, bypassing `_mergedDone` tracking.

**Fix**: Added a merge check in the dedup path so it is marked done only when both CTV and OAR are complete.

**Status**: ✅ Fixed

---

## 9. Todo Final Reply Count

**User feedback**: After the answer finished, the todo showed "1/2" and the web search was still spinning.

**Root cause**: `fold()` only collapsed the UI and did not mark pending items as done.

**Fix**: `fold()` now marks all incomplete items as done before collapsing.

**Status**: ✅ Fixed

---

## 10. Heading Typography

**User feedback**: Every heading had a vertical bar on the left and a 📌 icon, which looked unattractive.

**Root cause**: CSS `border-left: 3px solid` + the marked renderer injecting the 📌 icon.

**Fix**: Changed H2 to a `border-bottom` divider, removed `border-left` from H3, and removed the icon injection from the renderer.

**Status**: ✅ Fixed

---

# VI. API Endpoint Reference

| Endpoint | Method | Description |
|------|------|------|
| `/api/chat` | POST | LLM chat (SSE stream) |
| `/api/upload` | POST | Upload a CT file |
| `/api/segmentation` | POST | CTV/OAR segmentation |
| `/api/planning/results` | GET | Get planning results |
| `/api/planning/seeds_3d` | GET | Get 3D seed/needle data |
| `/api/planning/clear` | POST | Clear planning results |
| `/api/planning/show_step` | POST | Show planning steps |
| `/api/viewer/image` | GET | Get a 2D slice image |
| `/api/viewer/overlay` | POST | Get the label overlay |
| `/api/viewer/3d_mask` | POST | Get 3D mesh data |
| `/api/viewer/3d_skin` | POST | Get the CT skin mesh |
| `/api/viewer/load` | POST | Load a CT file |
| `/api/viewer/slice` | POST | Get slice data |
| `/api/viewer/volume` | GET | Get volume data |
| `/api/viewer/label_volume` | GET | Get the label volume |
| `/api/viewer/organs` | GET | Get the organ list |
| `/api/viewer/threshold` | POST | Set the threshold |
| `/api/viewer/hu` | POST | Set the HU window width/level |
| `/api/header/info` | POST | Get DICOM metadata |
| `/api/report/auto-fill` | POST | Report auto-fill |
| `/api/device/status` | GET | GPU status |

---

# VII. Tech Stack

| Layer | Technology |
|----|------|
| Backend | Python / Flask |
| LLM | OpenAI-compatible API (MiMo v2.5) |
| Frontend | Vanilla JS / HTML / CSS |
| 2D rendering | Canvas 2D |
| 3D rendering | Three.js + OrbitControls |
| DVH chart | Plotly.js |
| PDF generation | html2canvas + jsPDF |
| Medical imaging | SimpleITK / NiBabel |
| Segmentation models | nnUNet / TotalSegmentator |
| GPU scheduling | device_manager.py |
| Multi-agent | PlanReviewer + FactChecker + SafetyGuardian |
| Memory system | 5-layer hierarchical memory + experience learning |
