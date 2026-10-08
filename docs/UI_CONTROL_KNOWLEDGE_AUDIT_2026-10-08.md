# UI Control Knowledge and Guided Usage Audit

## Measurement cleanup follow-up

The measurement cleanup follow-up adds **Clear measurements**, repairs
annotation Tree identities/deletion and registers the same executor for natural
conversation. Current manual version is `2026-10-08.2`, with **220 source-bound
static controls and 67 cards** (60 usage contracts, 7 basic-input families).
The initial 219/66 inventory and validation below are the earlier audit
baseline, not current counts. See
`MEASUREMENT_ANNOTATION_CLEANUP_2026-10-08.md` for the current repair and evidence.

## Scope and root cause

The motivating request asks how to use **Line and Angle** in Viewers. It is a
usage question, not a request to click tools, inspect tumor location, delete an
object, or modify a plan. Its previous five Inspector reads ended in an unrelated
hidden-object fallback. The trace reported approximately 60–85 seconds and 97k
cumulative input tokens; those are the user's observations, not a new benchmark.

Verified causes in the current source:

1. Capability discovery described controller calls, not human interaction. A
   handler named `setViewerTool` does not describe a drag or a three-point angle.
2. Component search concatenated the entire HTML and split JavaScript and used
   substring matches. `Line` could match pipeline implementation text. Repeated
   searches mixed controls, comments, IDs and functions without identity ranking.
3. Successful Inspector results could reach the provider as only `Found N
   matching items` or `Getting current UI state`. The structured data alone did
   not guarantee a meaningful provider-facing result in the function-call loop.
4. Inspector defaulted to `state` even when a caller supplied `component` without
   `query`. Sibling controls could be fetched in separate rounds unnecessarily.
5. A blank response fallback keyed on terms such as `Viewer` and gave unrelated
   hidden-object advice, including unsupported assertions that no mutation had
   occurred. Answer failure cannot prove that prior tool actions did not occur.
6. `brain/knowledge/ui_knowledge.json` is an old, unconnected source, with obsolete
   layout/workflow claims. It is not used as the authoritative manual here.

The fix is not a sentence-to-action whitelist or an extra intent-classifier
model. The existing semantic model retains whole-request interpretation and the
existing execution authorization/receipt boundaries.

## Architecture

`agent_runtime/ui_control_manual.py` is the shared, versioned manual. Cards bind
to actual DOM IDs or handler families, with bilingual purpose, steps,
prerequisites, observable outcome, cancellation/limits and source anchors.
Deleted/unmounted static controls do not remain current knowledge. Dynamic Data
Tree families describe usage but require live object refs for execution.

The initial audit snapshot had **219 interactive button/input/select/textarea
elements**. All are bound to a manual contract; **66 cards** cover static control
families and five dynamic Data Tree usage families. These counts are not the old
Inspector's 279 action entries: action variants, status elements and controls
are different denominators. `basic_input` cards explicitly provide form-editing
semantics, **not** validated scientific explanations of every hyperparameter or
clinical recommendations. This distinction is preserved in provider evidence.

The generated `UI_CONTROL_USAGE_CATALOG_2026-10-08.json` lists coverage, bindings,
constraints and bilingual cards. It is an audit snapshot; the runtime module
rebuilds bindings from the current HTML and caches by source modification time.
Do not manually edit the generated JSON as if it were the runtime authority.

### Retrieval and interpretation

- Stable ID/exact label/alias outranks word-level family matches. `Line` does
  not match `pipeline`, `outline`, `autoLine` or `LineWhatever`.
- Batch usage query: `ui_inspector(query="usage", components=["toolMeasure",
  "toolAngle"], panel="Viewers")`. Language follows the current user language.
- Implicit `component` queries inspect the requested component, not global state.
- Source-code substring search is no longer the default control lookup.
- Successful component reads expose exact action evidence and reviewed usage,
  distinguishing static shell bindings from last-browser live availability.
- State reads give bounded valid JSON facts and explicit catalogue truncation,
  not a meaningless count. Sensitive control values/raw handlers are omitted
  from the provider projection. The full typed result remains available to the
  existing state contract.
- Every Inspector read mode now supplies a meaningful provider projection,
  rather than just its success/count message. Internal function-call loops cap
  tool text at 4,000 characters. Projections are bounded to 3,800 characters
  **before** that boundary, dropping whole entries and disclosing omission, not
  cutting instructions, action arguments or stable refs mid-value. Passive
  first-call evidence is bounded to 6,000 characters. Full typed data remains
  separate. An oversized scalar-only projection fails closed with an explicit
  narrower-read instruction, never an invented empty state.
- At the shared provider boundary, at most five relevant manual cards are
  retrieved locally before the **first existing** model call. The original user
  request stays the last user message. Cards are passive evidence, not policy,
  permission, completion, clinical validation or current-case geometry.
- Mixed questions/actions keep all clauses and remain governed by semantic
  planning and operation-level authorization. Retrieval never dispatches a tool.
- When the model produces no answer, a conservative usage-only fallback can
  render verified cards. It cannot replace mixed actions, diagnostics, clinical
  dose guidance or a turn that attempted a mutation. Generic failure text refers
  to actual trace receipts instead of guessing hidden objects or no writes.

### Correct Line and Angle contract

| Control | Prerequisite | Gesture | Observable result | Limits |
|---|---|---|---|---|
| Line (`toolMeasure`, mode `measure`) | CT and a 2D slice | Hold left mouse button at the start, drag to the end, release | Slice line and physical distance in mm | Not a 3D needle distance; image spacing/display scale apply |
| Angle (`toolAngle`, mode `angle`) | CT and a 2D slice | Left-click arm point, vertex, second arm point | Angle in degrees after the third point | Second point is vertex; keep all points on the same axis/slice |

Click an active non-crosshair tool again to deselect it. Changing tools clears
unfinished points. Undo handles completed measurements; Erase edits an active
mask and is not a Line/Angle eraser. Draw edits actual voxels. SAT3D prompt
selection is not inference completion or a guarantee for arbitrary tumors.

## Monitor UX integration

`brachybot-control-guide.js` reads the same manual from authenticated/rate-limited
`GET /api/ui/manual`. This endpoint does not instantiate/hydrate an agent or read
case arrays. The browser caches documentation; no periodic network or LLM call
is required for hints. A four-second documentation fetch timeout cannot block
the actual toolbar action.

While Monitor is active, selecting a supported 2D mode shows a dismissible,
text-only usage hint **below the toolbar and before the viewer workspace**.
It does not cover anatomy or append repeated chat messages. Angle's point count
comes from the actual annotation tool state, not imagined task completion.
Language changes re-render using the top-level language. Hint ownership includes
case/session, monitor run and actual active mode; delayed responses cannot attach
to another case. Stop, mode deselection, run/case changes and hidden-page events
remove the hint. Dismissing the hint does not disable the measurement tool.
Programmatic mode selection and Monitor phase changes use the same hook as
mouse selection. The guide uses the real global light/dark theme tokens and
does not re-announce identical text during idle ownership checks. A completed
angle is read from actual annotations on the matching axis/slice; Undo removes
that completion display. Pending points from a different slice are not reused.

This is UI usage guidance, not a new clinical Monitor engine. Geometry/dose
feedback retains the existing version-fenced evidence and edit decision system.
The hint does not claim it has measured anything or approved a plan. If manual
loading fails, the existing tool still works and no invented hint is shown.

## Validation protocol

New backend contracts test exact/batch retrieval, original Chinese wording,
unknown controls, substring negatives, coverage drift, source anchors, sensitive
value omission, immutable cached knowledge, mixed-request abstention and honest
fallbacks. Both real plain and streaming provider loops are exercised with a
fake provider: cards are present on the first call, with no classifier call or
case write; an empty answer is recoverable for the original usage question.

New Chromium tests use real product DOM and annotation functions on synthetic
CT geometry. They check a true left-button interaction, three-point angle and
anisotropic physical calculation, point count, global language, dismissal,
monitor-off behavior, delayed-response fencing and documentation-fetch failure.
Existing toolbar/annotation tests continue to cover transforms, undo/redo,
SAT3D prompts and mask editing. These are not patient, GPU or paid-provider tests.

### Measured retrieval overhead

For the original Chinese request, a fresh validation process measured **90.928
ms** on its first local retrieval. Over 200 cached retrievals, the median was
**11.964 ms**, with **12.876 ms** at the empirical 95th percentile. The injected
packet including its marker was **1,322 characters**. These are local retrieval
measurements, not token counts, paid-provider latency, time to first answer or
an online before/after benchmark. No additional model classification call is
introduced by this repair. Documentation hints do not call a model.

### Test execution and regression accounting

The targeted source/provider/browser/Monitor regression set completed with
**156 passed**, including the new contracts and existing annotation/toolbar,
mask-staging and Monitor tests. Three stale assertions identified by the first
full run were corrected: two referenced the old viewer-layout cache revision
48 instead of the new revision 49; one required an unsupported no-deletion
claim and hidden-object diagnosis in a generic failed-answer fallback. Their
other behavior assertions were preserved; guards were not weakened.

An initial follow-up full run reported **2 failed, 3,007 passed, 2 skipped**, with
four passing subtests. Both failures were deployment-resource checks: a `/tmp`
validation checkout derived a `/tmp` cascade-model root, while the real liver
and kidney resources are under `/home/lht/snap/brachyplan`. Both were read-only
verified as available in the LAN checkout. The final full run with the explicit
production resource root completed with **3,009 passed, 2 skipped, 31 warnings
and 4 passing subtests in 184.69 seconds**, with no failures or collection
errors. This environment correction does not change a model,
checkpoint, availability assertion or inference adapter.

Reproduction environment:

```bash
cd /tmp/brachybot-control-knowledge-20261008-GT7yyE
export PYTHONPATH=.
export BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan
export PATH=/home/lht/.vscode-server/cli/servers/Stable-04c0d99f4fb0d8afe6ce4f0c58e31e183ac3e4b1/server:$PATH
/home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q tests/ \
  --junitxml=/tmp/brachybot-control-knowledge-full-20261008.xml
```

Node syntax checks passed for all three changed JavaScript files; Python
compilation passed for the manual, shared LLM runtime, Inspector and routes.
The final XML and selected-file SHA manifest are retained under
`/home/lht/.local/share/brachybot-control-knowledge/validation-20261008`.
The new regression cases are synthetic/provider-contract tests, not results
from a paid model or a real patient. Remaining warnings concern existing
SimpleITK binding types and existing UTC datetime deprecations.
The two skips are the public HTTP origin integration test (separate deployment
requirements not installed in this interpreter) and the real Nginx proxy test
(`NGINX_TEST_BINARY` not configured). The new manual and browser suites have
**50 and 13 passing cases**, respectively, with no skips.

No production case was modified as a test. Code delivery does not by itself
activate a new backend route in an already-running server.

## Control inventory and knowledge levels

| Panel/domain | Contract cards | Representative coverage |
|---|---:|---|
| Viewers and dynamic Data Tree | 30 | Measurement gestures, drawing/erasing, SAT3D prompts/inference distinction, overlays, transforms, layout, dose presentation, structure management |
| Input and planning | 24 | Upload/staging/classification distinction, modality/model selection, prerequisite-ordered stages, editing, dose, guide, export, parameter input families |
| Report | 5 | Auto-fill, preview/template/zoom, export, review/provenance/snapshots, clear/import |
| Global | 7 | Navigation/context, chat, language/theme, account boundaries, editing lease |
| Total | 66 | 59 usage contracts and 7 intentionally basic native-input families |

The 219-element denominator is **static** `button/input/select/textarea` shell
coverage. It is not all runtime Plotly legend entries, generated report editor
fields, context menus, plug-in canvases or object instances. Those remain
discoverable through the mounted live operation catalogue, with stable refs,
actual actions and enabled state. Five Data Tree families provide reviewed
usage without fabricating per-object bindings. Unknown plug-in gestures are
explicitly unknown. A future dynamic feature should register its usage
contract as well as its action, rather than infer gestures from a label.

## User-facing answer contract and acceptance scenarios

A grounded answer to the motivating request should explain:

- **Line:** select it, hold the left button at a starting point on one 2D
  slice, drag to the end and release; the result is a distance in millimeters.
- **Angle:** select it, click an arm point, the vertex and the other arm point;
  the second point is the vertex and all three must be on one view/slice.
- Click the active tool again to exit. Undo handles completed measurements.
  Erase targets an active mask, not a measurement. These are 2D measurements,
  not 3D needle measurements or clinical approval.

It must not inspect an unrelated surgical guide, generate a plan, promise a
segmentation merely from a prompt click, or claim no mutation solely because
its final answer failed. Mixed requests must retain their requested action;
usage evidence is not action authorization.

Real-provider and real-case acceptance should include at least:

1. The exact motivating question in both languages; no repeated global scan
   when the needed cards are already present.
2. A paraphrase without English labels, and a request involving more than two
   related controls; explicitly retrieve any omitted/unknown siblings.
3. Help plus a requested action, help plus a clinical question, and a runtime
   failure question; do not silently turn any of these into pure usage help.
4. A disabled control, missing model, unknown plug-in button and ambiguous
   duplicate label; distinguish source knowledge from runtime availability.
5. Monitor selecting Line/Angle by mouse and conversation, starting/stopping,
   switching cases during a delayed documentation fetch and changing language.
6. A measurement on a real CT with known spacing, a slice change mid-angle,
   Undo/Redo and a narrow screen. Compare the measured value independently;
   matching source text is not sufficient evidence of physical accuracy.

These live acceptance scenarios are not reported as completed by the isolated
tests. Do not turn a future runtime/model failure into a source-coverage pass.

## Maintenance and acceptance criteria

1. Every new static interactive control needs a manual binding, or coverage
   fails with its exact unknown identity. Do not make the test green by labeling
   an unknown medical feature as fully understood.
2. Bind a new control by stable identity and actual handler. Document gestures,
   prerequisites, observable outcomes, failure/cancel behavior and write scope.
3. A new clinical parameter can first have a `basic_input` contract. Upgrade it
   only after checking real algorithm semantics, units and supported range.
4. Add browser behavior tests when gestures or coordinate transforms change.
   Source anchors alone do not prove those behaviors remain correct.
5. Dynamic/plugin objects must publish live operation/visual refs and enabled
   state. Family documentation must not invent a binding to an unseen object.
6. A future contextual teaching stage should choose guidance from this source
   using committed events and real prerequisites, not maintain a second copied
   manual in Monitor prompts. Clinical advice needs clinical evidence separately.
7. Re-run both provider-loop and browser tests when changing reply formatting,
   context packing, authorization, language management or UI registration.

## Limits

Static knowledge coverage does not prove every feature works on every real case
or every model deployment. A source-bound instruction is distinct from live
availability and a completion receipt. Foundation repair cannot guarantee that
an arbitrary underlying LLM will correctly interpret every possible request.
Real-provider wording/latency, real-case resource hydration and clinician-facing
teaching remain additional acceptance dimensions. This audit does not claim
clinical validation, zero remaining bugs, or fully autonomous teaching.

Existing LAN/release deployments and all pre-existing edits are preserved. No
commit, push, public-release mutation or production restart is part of validation.

## Delivery and activation

The selected delivery contains **16 files**. Existing files are checked against
their exact pre-change SHA-256, including prior report/DVH edits. Every original
selected file is backed up in a private mode-700 directory before writes;
replacement is atomic per file and the HTML entry is delivered last. Delivery
aborts on a concurrent change instead of overwriting it. The delivery manifest
records before/after hashes; new files have a null before hash.

The existing LAN process and the independent public-release checkout are not
restarted or modified as part of activation. The running LAN backend needs a
controlled restart before its in-memory LLM code and `/api/ui/manual` route
become current; reload the browser afterward to use the versioned frontend.
Until then, optional manual-fetch failure remains non-blocking. A source/test
delivery is not a claim that the current running backend has already reloaded.
