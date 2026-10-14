# Implanted-seed correction, reconstruction and source-set-specific CNN dose

Date: 2026-10-11 (Asia/Shanghai).

Status: **implemented candidate in an isolated checkout; not deployed to the LAN or public service**. This follow-up does not claim that the complete multi-timepoint product refactor is finished. It supplements `INTRAOPERATIVE_PLAN_VERIFICATION_2026-10-10.md` and `INTRAOPERATIVE_TARGET_LANGUAGE_VERIFICATION_2026-10-11.md`.

## 1. User requirements and scope

Detection must continuously deliver a reconstructed observation set to the Data Tree and Viewer. Every observation has an individual identity, appearance and correction controls. False-positive exclusion, missed-seed addition and center refinement must not edit future planned sources or imply that an implanted physical source has been removed.

After those corrections, a natural-language request must be able to recompute the dose of **currently included implanted observations only**. This is not permission to add sources, optimize trajectories, generate another guide, regenerate a report or overwrite a future plan's dose. The current mounted Table Viewer is captured at submission; a late response cannot adopt a different mounted workspace.

The implemented observation workflow supports CT. It does not pretend that the supplied SeedFinder is validated for other modalities or that multiple image candidates inside a timepoint can be guessed without an explicit reference resolver.

## 2. Original gaps and root-cause repairs

1. The immutable detection service existed, but no product consumer rendered its current observation revision as individually editable objects. Original detector STL files cannot represent later corrections. The new consumer renders current observation records, not stale raw artifacts.
2. Existing manual-seed controls operate on future planning geometry. Reusing those identities would conflate an observation correction with a new implantation decision. The new observation namespace and routes are separate.
3. Moving a detected center invalidates its estimated orientation and local association. The correction clears those dependencies. Recalculation re-estimates an unavailable axis using the pinned supplied direction code; it does not borrow a matched preoperative direction.
4. A dose request previously had only a current-plan recompute path. `dose_recompute.source_set` now distinguishes `planned` from `implanted` at the tool contract and numerical executor. When both sets exist and the source set is unspecified, execution requires clarification.
5. Existing default-workspace checkpoints walk and save the full Agent. A dose-only result now uses an encoded numerical delta and revision check, preserving all unrelated saved clinical keys and array references.
6. The source settings require an explicit current-timepoint confirmation. The software cannot silently borrow dimensions from a different scan or call software confirmation clinical approval. A source-settings modal exposes dimensions and the server-owned CNN calibration/model binding.
7. Existing needle/seed drag handlers could consume the same pointer as an observed-source edit. They now yield only when an observation gesture owns that pointer; ordinary planned-geometry editing remains available otherwise.
8. Tool/browser retries must not repeat a correction or restore an old detection head. Requests have stable UUIDs and exact observation-revision fences. Retried receipts are reconciled to the current journal head.
9. A schema parameter alone is insufficient when the tool's main description still describes only future-plan DVH. The description/output contract now explicitly distinguishes implanted-observation dose from planned-source Dose/DVH and identifies the limitations of each branch.

## 3. Implementation map

| Component | Responsibility |
|---|---|
| `web/implant_service.py` | Owned immutable reconstruction/correction journal, exact head CAS, original evidence preservation, bounded history and correction validation |
| `web/implant_workspace.py` | Owned image input, journal-to-saved-state projection, current public observation view, persistent per-item/group presentation and common tool binding |
| `web/routes/implant_routes.py` | Authenticated CT detection jobs, current views, corrections, appearance and source-profile confirmation; explicit target/editor/CSRF checks |
| `web/implanted_dose.py` | Current included observation set, axis estimation, current CNN checkpoint and calibration, source-only dose aggregation and fenced publication |
| `web/workspace_store.py` | Encoded numerical delta for the legacy default workspace; unchanged saved keys are not copied from stale Agent aliases |
| `tool_factory/dose_recompute.py` | Semantic source-set capability, without a natural-language phrase whitelist |
| `tool_factory/seed_seg/__init__.py` and `AgenticSys.py` | Same detection/correction entrypoints for scope-bound chat and manual UI |
| `web/timepoint_chat.py` | Named target clinical publication under CAS and observation-head protection |
| `brachybot-implant-observations.js` / `.css` | Data Tree, 2D/3D observation interaction, drafts, progress, appearance, settings and tool-result consumption |
| `web/timepoint_messages.py` / existing global i18n | Shared safe zh/en codes, controls and status presentation |

## 4. Interaction contract

### 4.1 Continuous detection and display

The explicit Detect and reconstruct action captures the owned Session, timepoint and observation head before starting work. It validates the configured supplied runtime and returns a bounded background-job identity. The UI shows live elapsed progress while polling. On completion it receives the current observation view and renders Data Tree entries and 2D/3D objects together.

A late result for another timepoint may remain saved, but cannot paint over the current scene. Raw detector mask/CSV/Markups/STL remain evidence artifacts. A corrected Viewer object is never rendered from the old detector STL.

### 4.2 Data Tree organization and controls

Observed objects live in a dedicated Implanted observations group under Planning, with stable per-observation IDs. Included observations and excluded observations remain distinguishable. Excluded items can be restored; exclusion does not erase original detection evidence.

Each observation supports:

- Combined visibility and independent 2D/3D visibility.
- RGB color and finite opacity in `[0, 1]`.
- Locate, refine center and exclude/restore actions.
- Group Show all / Hide all without replacing individual clinical identities.

Implanted observations default to vivid cyan (`#22D3EE`); future planned sources default to bright gold (`#FBBF24`). A user-selected source color remains respected. Appearance lives in a separate versioned record and does not create a clinical geometry revision or trigger a CNN recomputation.

Opacity dragging updates existing objects immediately; it does not rebuild every mesh or replace the active HTML slider on each input event. Appearance writes are debounced, serialized and preserve changes queued behind an in-flight save.

### 4.3 False positives and missed seeds

Exclusion is available from a Data Tree item or an actual 3D object hit. Confirmation explicitly concerns an observation record, not physical source removal.

Add missed seed opens placement mode. A valid 2D click is transformed using the product's MPR orientation and the current CT spacing, origin and direction into LPS millimeters. Clicks outside the image are rejected rather than clamped onto the border. A distinct draft marker appears in 3D. The user may drag it on a camera-facing plane to refine position, then choose Save or Cancel. No authoritative geometry changes before Save.

The same draft and Save/Cancel behavior applies to refining an existing observation. Escape cancels; pointer capture/cancellation restores owned camera controls. A stale revision rejects publication and retains a recoverable draft instead of overwriting a newer edit.

Center edits invalidate estimated orientation/local-association dependencies. Known capsule dimensions and an available axis permit a capsule glyph. Otherwise a point/halo is used; the UI does not invent a physically meaningful capsule or STL.

### 4.4 Source settings

The source-settings modal uses the application's timepoint dialog style and top-level language manager. It preserves entered numbers and its captured target when the language changes. It does not initialize unknown dimensions with a fabricated clinical default.

The user confirms the current source length/radius. Calibration and checkpoint identity are owned by the installed dose model and are not inferred from prescription dose or source appearance. Length must exceed diameter; numeric values must be finite and positive. The saved profile states `software_estimated_dose_settings_not_clinical_approval`.

The default-workspace profile save checks its exact revision inside the save operation, not only before entering it. Named workspaces retain their state/clinical CAS.

## 5. Natural-language dose contract

The semantic tool call is:

```json
{
  "tool": "dose_recompute",
  "params": {
    "source_set": "implanted"
  }
}
```

An optional `expected_observation_revision_id` can bind an already displayed revision. The runtime always captures an owned target and reads its current journal head; a provider-supplied identifier is not authority to mutate another timepoint.

Requests such as “recompute the dose of the implanted seeds after these corrections,” “only calculate the existing source dose; do not replan,” and analogous wording select the same capability. These examples are documentation, not a parser allowlist. A semantic model is still responsible for understanding the user's reference. Structural tests do not prove perfect understanding of arbitrary unseen utterances or deployed provider performance.

The Recompute implanted dose button sends an explicit natural-language request through the ordinary chat path, using the same source-set executor rather than a second dose implementation.

### 5.1 Numerical inputs and output

1. Load current owned CT and verify its content hash/physical grid against the observation reference.
2. Select current non-rejected observations only. Future planned/manual seeds do not radiate in this calculation.
3. Resolve dimensions and calibration from the current timepoint's explicit profile or compatible current saved source configuration, never a different preoperative workspace.
4. When an edited axis is unavailable, run the pinned supplied orientation routine on current observed centers. Record estimated axes as estimates, not measurements.
5. Use the existing authoritative world-space DoseUNet aggregation with strict source acceptance, a device lease and the cross-process GPU lock. Do not invoke a trajectory optimizer.
6. Convert normalized model output to physical Gy exactly once using the recorded model calibration. For the installed default DoseUNet this scale is `190.8 Gy / model unit`; prescription dose is not the conversion factor.
7. Before publication, recheck image/checkpoint, source profile, observation head and captured target/clinical revision. A geometry or source-setting edit during a long calculation cannot publish the old result as current.
8. Save a separate `implanted_dose_record`, including the physical dose grid, exact source geometry, source count, estimated-axis count, image/checkpoint identity and source-profile binding.

The physical grid is saved through the normal array encoder, not `_safe_json` object conversion. The legacy default writes only the result delta; named scoped chat writes changed keys under its clinical CAS and journal-head guard. Future plan dose/DVH/geometry aliases remain unchanged.

If the included observation set is empty, the selected-source contribution is a zero grid without CNN inference. This does not assert that a patient has received no radiation or that no undetected sources exist.

### 5.2 Freshness and interpretation

Changing observations or the source profile makes the saved implanted-source dose stale. A display-only color/opacity/visibility change does not. The Data Tree marks saved versus stale observation dose. A stale grid cannot be silently promoted as a valid continuation baseline.

This is the existing **CNN-estimated projected source-dose distribution**, not independent TG-43/Monte Carlo validation and not dose already delivered over elapsed time. No clinical acceptance, source-strength commissioning or axis-certainty approval is inferred. The formatter explicitly states that no new sources or downstream planning/guide/report actions were executed.

The new source record is not yet connected to a dedicated implanted-dose heatmap/DVH selector in the production panels. Do not claim that the new calculation replaces the currently shown future-plan heatmap or automatically updates a surgical report.

## 6. Safety and persistence

- Authentication, owned Session/timepoint checks, CSRF and the established editing lease apply to mutations.
- Service/input/review objects are server-bound; tool JSON cannot construct approval objects or inject another input image.
- Finite LPS coordinates are checked against the referenced physical CT bounds. Duplicate centers and unknown observation IDs are rejected.
- Corrections retain original detection artifacts and immutable parent revisions; they do not physically delete prior evidence.
- Correction retries use the same request UUID and revision. Network retries are not fresh user authorizations.
- Job polling is bounded and reports typed safe errors, not raw filesystem/model exceptions. Malformed or missing job-request UUIDs are rejected before starting work.
- Source fencing compares the actual dimensions/calibration/model inputs, not unrelated DVH arrays or scores. It uses fresh saved settings preferentially and detects changes to either the saved contract or current invocation's source settings before publication.
- Source settings and numerical sidecars are retained in the owned workspace. A reload restores the current journal head and appearance, rather than replaying an old raw STL.
- The detection worker registry is process-local. Committed journal revisions are durable, but automatic recovery/resumption of a killed in-flight inference worker remains a whole-workflow integration task.

## 7. Verification evidence

All tests use synthetic owned volumes, inert worker/model seams or actual headless browser/THREE interaction. No patient image, supplied neural model or GPU inference was run for this follow-up. This is contract and interaction evidence, not clinical or real-operator acceptance.

The new focused suites cover immutable correction history, cross-owner denial, stale-head rejection, finite/bounded physical coordinates, persistent appearance, source-set selection, source-only CNN aggregation, exactly-once Gy conversion, separate saved dose, mutation during inference, empty included sets and source settings changing at publication.

The actual headless-browser test uses the new product JS and THREE meshes/camera/raycast with an in-memory HTTP fixture. It covers individual visibility/color/opacity, source confirmation and live language changes, 2D placement, 3D preview/drag/Save, false-positive exclusion and late-target fencing. It does not load patient resources or exercise a WebGL GPU renderer inside the complete deployed application.

The initial latest focused preflight passed 62 tests. Further publication and malformed-request negative controls were subsequently added. Overlapping runs must not be added together. The final frozen-candidate result and exact artifact hashes are recorded after verification completes.

An intermediate complete run with missing test-runtime environment reported 3 failures / 3,731 passes / 22 skips in 392.21 seconds. Its failures were missing dedicated cascade resources under the isolated default deploy root and missing Node on PATH; the missing browser runtime also produced additional skips. No product or test assertion was relaxed. Subsequent verification explicitly uses the real resource deploy root and installed Node/Playwright runtime, without inference or service changes.

### 7.1 Final frozen-candidate result

- Final focused suite: **73 passed**, three SimpleITK/SWIG deprecation warnings, **13.93 seconds**. Evidence: `implant-contract-final-preflight-20261011.xml`.
- Complete unfiltered root `tests/`: **3,765 passed / 2 skipped / 0 failures / 0 collection errors**, four passing subtests, 31 existing deprecation warnings, **407.47 seconds**. Evidence: `full-implant-contract-final-frozen-20261011.xml`.
- Frozen candidate: **101 changed/new product, test and paired-evidence files**, consisting of **45 existing modified files and 56 new files**. The candidate contains the earlier multi-timepoint foundation as well as this follow-up; 101 is not a claim that all those files were newly authored for the dose-only feature.
- All **80** changed/new Python files compiled; all **10** changed JavaScript files passed `node --check`.
- All stage `after_sha256` values match. All 45 live `before_sha256` values match, and none of the 56 new candidate paths is already live.
- The existing paired guide dependency guard passes without a hash-only renewal or another change to the numerical planning pipeline for this follow-up.

The two skips are public-origin/proxy deployment checks requiring actual deployment dependencies and `NGINX_TEST_BINARY`. They remain unfulfilled operational validation, not passing release checks. Pytest's summary is the pass-count authority; JUnit includes the four subtests in testcase accounting.

The code was frozen before this final run; only delivery documentation was edited during it. The previous complete numerical/interaction run passed 3,764 tests in 405.42 seconds before the final tool-description/output-schema follow-up; it is not substituted for the final current-candidate run.

### 7.2 Reproduction and artifact identity

The final command ran in `/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/checkout` with:

```bash
export BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan
export BRACHYBOT_NODE=/home/lht/.vscode-server/cli/servers/Stable-04c0d99f4fb0d8afe6ce4f0c58e31e183ac3e4b1/server/node
export PATH="$(dirname "$BRACHYBOT_NODE"):$PATH"
export PLAYWRIGHT_MODULE=/home/lht/.conda/envs/brachytherapy/lib/python3.12/site-packages/playwright/driver/package
PYTHONPATH=. /home/lht/.conda/envs/brachytherapy/bin/python -m pytest tests/ -q \
  --junitxml=../full-implant-contract-final-frozen-20261011.xml
```

These environment values expose existing runtime/resource paths to tests. They do not start clinical inference, change the live service environment or install packages.

- Candidate manifest SHA-256: `c9816bf6ee71495aa410827f2b4711807369b76c7a3f15c065f37137582d3342`.
- Candidate archive SHA-256: `4942550a3e9c017175db0d5ed7caaba54d2cf13041b0d4467fad24d2fe657f8b`.
- Focused JUnit SHA-256: `61a97e53c65337742ebeafa7888bec927b0f390a1ca25ae10254f93c61966ab5`.
- Full JUnit SHA-256: `9e5b33bf2ed42e5497d69362c432aeac3e441a57a0c773dc42dd47b66775288f`.
- Persistent delivery: `/home/lht/.local/share/brachybot-intraoperative-development/20261010-E1Rvjz/implant-interaction-20261011-c9816bf6ee71` (private directory, mode `0700`).

The final read-only runtime inspection still found LAN PID **3386575** on `192.168.1.113:8080` and separate public PID **3693000** on `127.0.0.1:18082`, with HEAD `0d840e38bea3fb36b8e9b3cf3acb33220062f3bc`. This is a point-in-time observation, not a future process-state guarantee.

## 8. Operational and remaining integration boundaries

Candidate source: `C:/Users/hunte/OneDrive/Dokumen/ssh/timepoints-implementation-20261010`.

Isolated test source: `/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/checkout`.

Private resumable checkpoint: `/home/lht/.local/share/brachybot-intraoperative-development/20261010-E1Rvjz`.

Live LAN source: `/home/lht/snap/brachyplan/BrachyBot`. Separate public source: `/home/lht/snap/brachyplan/BrachyBot-release`.

Neither service is restarted or updated by this follow-up. The shared multi-timepoint production restoration bridge, complete HTTP/UI/Monitor/export scoping, explicit multi-image reference resolution, authenticated noncurrent-write confirmation, durable stage/job recovery and clinically reviewed continuation acceptance remain unfinished. Runtime `execution_scope` and the general production frontend bridge remain disabled. Narrow observation routes do not grant broad legacy API access to a nondefault workspace.

The supplied direction routine remains an estimate with a native XY-plane restriction and singleton/global fallback. Its raw zero-detection artifact behavior (including whether an empty run emits the required STL) still requires real supplied-runtime validation; an upstream incomplete artifact set must not be presented as a successful clinical reconstruction.

The pinned Linux runtime is configured using `BRACHYBOT_SEEDFINDER_BUNDLE`, `BRACHYBOT_SEEDFINDER_PYTHON` and optionally `BRACHYBOT_SEEDFINDER_DEVICE`. Candidate tests do not set those variables in the live service or automatically install a model. A configured path alone is not end-to-end inference evidence.

Before rollout: integrate the production resource bridge; recheck all live-before hashes; selectively back up only the exact scoped product files; configure the pinned SeedFinder runtime and approved source parameters; perform a bounded current-CT detection/correction/dose smoke test and an actual browser old/new workspace regression; then obtain deployment authority for the intended service. Do not copy or restart the separate public checkout as a side effect.
