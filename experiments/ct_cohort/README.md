# BrachyBot CT cohort experiments

This is a standalone, NAS-backed research experiment runner, not a change to
BrachyBot's treatment-planning algorithms or a clinical deployment. It measures
real browser workflows with supplied targets and preserves verifiable artifacts.
The accompanying scientific protocol is
`docs/CT_COHORT_PLANNING_EXPERIMENT_DESIGN_2026-10-04.md` in the product repository.

**Default state: execution disabled.** The provided profiles, governance,
acceptance, case and resource documents are drafts, not approvals. No clinical
prescription, source calibration, manufacturing tolerance or ethics approval is
inferred from a dataset name. There are currently zero approved primary cases in
the supplied configuration. A closed dry run is the expected result.

## 1. What is implemented

| Component | Behavior |
|---|---|
| Registry | Reads the existing compressed JSONL inventory, keeping exact CT/label paths, source-specific target values and semantics |
| NIfTI preflight | Full payload checks, qform/sform agreement, units, finite values, matching physical grid, integer-label policy, exact target union, connected components, source/derivative hashes |
| DICOM | Regular native CT/PET and explicitly geometric binary SEG conversion; same FrameOfReference, referenced PET series, orientation, slice positions and selected segment checks; nearest-neighbor physical resampling followed by mandatory human review |
| Clinical profile | Approved applicability, evidence, source, calibration and settings; no fallback to a generic 120 Gy profile or another tumor model |
| Browser-chat arm | New case, CT upload, staged mask upload, actual Data Tree Move to CTV, profile controls, real text entry and Send button, case-owned task observation |
| Manual-UI arm | Same uploads/target/profile, then the ordinary planning, guide and report controls; no private mutation API shortcut |
| Observation | Read-only endpoints and safe checkpoint-array decoding; current object IDs, exact effective target, consumed settings, actual planner mode and plan/export versions |
| Artifacts | Real UI PDF and Session export downloads, bounded ZIP extraction, source-backed backup, geometry/dose/DVH/OAR records, mesh/PDF byte checks and SHA256 manifests |
| Recovery | Repeating the same run command skips recorded cases, waits/collects interrupted server jobs, and retries only an interrupted incomplete case; recovery remains separate from first-attempt outcomes |
| Adjudication | Qualified hash-bound review updates the interpretation of the same first-attempt artifacts; never overwrites the original terminal result |
| Analysis | Screening funnel, all-started-attempt denominator, paired descriptive analysis, optional frozen stratified paired analysis, and long-format data tables |

There is no pretend TG-43 or Monte Carlo engine. `verify-reference` accepts a
separately generated, qualified independent reference with the same source/time,
geometry, target, units and dose-file hashes. It measures disagreement; a PASS
for this contract is not a clinical dose-acceptance verdict.

### Full-cohort execution (2026-10-04 extension)

There is **no 800-case program cap**. N=800 is an unvalidated paired-study
design assumption, not the size of the engineering census. Use
`configs/experiment.census.example.json` and `configs/protocol.census.draft.json`
as configuration templates, not executable approvals. The census includes all
eligible, reviewed target rows; its realized size is measured after preflight,
not equated with the 40,299 inventory records or the number of CT acquisitions.

The production dose engine remains the existing spacing-normalized DoseUNet
CNN. This extension neither replaces it with TG-43/Monte Carlo nor requires an
independent dose field to execute the census. Source/calibration compatibility
still requires review; an external physics reference is a separate substudy.

There are two explicit endpoints:

| Endpoint | Required evidence | Supported use |
|---|---|---|
| `software_workflow_completion_within_budget` | Effective target, consumed settings, current nonempty geometry/dose/DVH/quality export, mesh/PDF checks, budgets, archive and preserved sources | Descriptive engineering census; no clinical or manufacturing acceptance |
| `first_attempt_verified_software_workflow_completion_within_budget` | All software checks plus qualified hash-bound artifact review | Existing reviewed workflow endpoint and paired cluster study |

Both results are saved separately as `software_completion` and
`reviewed_completion`. A software PASS with missing review is `SOFTWARE_SUCCESS`,
not `VERIFIED_SUCCESS`. Neither endpoint is independent physical-dose validation.
Existing row-ID-only protocols retain their old reviewed endpoint by default.

With a private reviewed `CFG` and isolated runner `PY` as described below:

```bash
# No planning. This reads full source volumes and writes preflight derivatives
# to NAS, so schedule its IO/memory budget separately.
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" preflight \
  --all-records --allow-offline-data-access

# After exact source/target/profile approvals: no numerical sample cap.
# A new frame is DRAFT and does not grant any approval.
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" build-frame \
  --target-policy all-targets
```

Review the printed counts, exclusions and actual CT/label/label-value records.
Copy the printed `cohort_frame.path` and `cohort_frame.sha256` into the private
protocol, set `study_kind=descriptive_stress`, use the software endpoint, and
freeze the protocol with the required named investigator and signed gates.
Frame inputs bind the registry, case approvals, profiles, preflight policy and
model recipe. Later batches must match those recipes and every resolved row.
Frames are never overwritten. A changed selection requires a new experiment.

`all-targets` permits multiple eligible targets/acquisitions per resolved
cluster for engineering stress tests, reporting **target-run**, not patient,
rates. `one-per-cluster` deterministically chooses one eligible target per
cluster and can be used with `--limit` for a separately registered comparison
subset. Paired studies still require one per cluster and the reviewed endpoint;
increasing census volume does not justify or change the paired-study power.

```bash
# No product mutation. Optional pilot-measurements.json contains actual
# elapsed_s and retained_bytes arrays from complete retained attempts.
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" schedule \
  --arm browser-chat --measurements /private/pilot-measurements.json

# Each invocation dispatches up to 100 NEW cases, passing completed batches.
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" run \
  --execute --max-cases 100 --arm browser-chat

# Explicit alternative: all pending allocations, still bounded by the frozen
# attempt/storage/deadline/account quota. It never means unlimited execution.
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" run \
  --execute --all-pending --arm browser-chat

PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" analyze
```

Resumption does not replay an ordinary failed first attempt. A terminal independent
case does not block other cases; an unresolved in-flight operation does. A partial
pair dispatches only its missing arm. Incomplete records are automatically reconciled
before any new planning submission; ambiguous records still fail closed. Admission counts
actual new attempts rather than multiplying the requested ceiling, so a final
small batch can finish within the approved attempt budget. Each batch saves its
allocation, outcomes and summary under `tables/batches/`.

`tables/cohort_status.csv` includes every allocated target/arm and its exact
original CT path, label path and selected label values. NOT_STARTED, INCOMPLETE,
PASS, FAIL and UNKNOWN remain distinct. Analysis reports allocation counts,
pending allocations, software and reviewed success separately, per-dataset
results, long-format geometry/dose/OAR/resource/stage-time tables, and existing
CNN proxy metrics. It does not count targets as independent patients or present
an unfinished census as a final clinical comparison.

Runtime is projected from actual pilot p50/p95 samples when provided; otherwise
only a timeout ceiling is shown. Storage projections exclude unmeasured costs
and never approve capacity automatically. Retained bytes include backups,
downloads and failed attempts; no automatic deletion is introduced. Browser
jobs remain sequential under account/GPU leases. An all-records preflight or
all-pending run is available, but neither was executed during this extension.

## 2. Storage and isolation

The source dataset remains read-only:

```text
/home/lht/nas/LHT_workspace/Brachytherapy/CT
```

All large experiment data go to a sibling NAS directory:

```text
/home/lht/nas/LHT_workspace/Brachytherapy/BrachyBot_CT_Cohort_Experiments/<experiment_id>/
  protocol/     frozen governance, protocol, rules and budget
  resolved/     per-record preflight status and exact source/target identity
  derived/      binary supplied targets and reviewed DICOM derivatives
  backend/      dedicated workspaces, uploads, cache, exports and service logs
  archive/      dedicated product archive
  runs/<recipe_hash>/<attempt_id>/
  tables/       analysis, review rendering, adjudications and recovery evidence
  tmp/          product temporary files
  deployment/   copied-code/model hash manifest, not a production checkout
  locks/        owned experiment leases
```

The NAS is CIFS and does not support the symlinks required by Chromium and the
product's isolated path redirection. Therefore small code and SQLite metadata
remain on the local disk:

```text
/home/lht/.local/share/brachybot-ct-cohort/<experiment_id>/product
/home/lht/.local/share/brachybot-ct-cohort/<experiment_id>/runtime
```

The local runtime's workspaces/staging/trash, and the copied product's legacy
output/runtime directories, point to this experiment's NAS paths. SQLite/WAL is
never placed on CIFS/NFS. Chromium scratch/profile uses verified `/dev/shm`
tmpfs, not a persistent disk cache; downloads are copied to NAS. Small dependency
environments are local. These exceptions do not store the cohort's large results
on the repository disk.

Mount source, filesystem, mount identity, free capacity, retained-byte budget,
local metadata location and source/output overlap are checked. Retained-byte
scans are cached for 30 seconds to avoid an expensive CIFS tree walk on every
status poll; admission performs a fresh scan and reserves space. Caps are safe
stop/admission controls, not an exact filesystem quota. Budget adequate headroom
and use a NAS server quota if a hard upper limit is required. No retention/delete
policy silently removes unsuccessful cases.

The experimental server is loopback-only on a new port, default `18086`, with a
separate checkout, runtime, cookie and account database. Ports `8080` and `18082`
are forbidden. Listener PID, process creation time, working directory, command,
runtime environment and code/model hashes must agree before execution. The
package never restarts or copies production accounts/data. A live server status
and an HTTP 200 alone are not accepted as identity evidence.

NAS permissions must be verified at the server ACL level: this CIFS mount's
0777 presentation does not prove access control. Facial anatomy, screenshots,
reports and geometry remain restricted imaging data, even after header cleanup.
Do not deface the original planning inputs merely to prepare a public figure.

## 3. Installation

Run on the remote Linux host, not the Windows desktop:

```bash
cd /home/lht/snap/brachyplan/BrachyBot/experiments/ct_cohort
/home/lht/.conda/envs/brachytherapy/bin/python -m venv --system-site-packages \
  /home/lht/.local/share/brachybot-ct-cohort/experiment-tools/venv
/home/lht/.local/share/brachybot-ct-cohort/experiment-tools/venv/bin/python \
  -m pip install -e '.[test]'
/home/lht/.local/share/brachybot-ct-cohort/experiment-tools/venv/bin/python \
  -m playwright install chromium
```

Use an isolated environment; do not upgrade the active production environment.
The real SUT service uses the approved `product_python`; the runner tools use
their own environment. `pdftoppm` is required for `render-pdf`. Install it through
the approved host administration process if absent. CUDA/product models are not
downloaded or reimplemented by this package.

For this implementation's code validation, an environment already exists at:

```text
/home/lht/.local/share/brachybot-ct-cohort/code-validation/venv
```

It is a validation environment, not a clinical/model configuration approval.
`PYTHONPATH=.` allows running from the source without installing into production.

## 4. Configuration and approval sequence

Copy `configs/experiment.example.json` and the draft documents to a private
configuration directory and edit that copy. Use a new experiment ID for a new
protocol or revised preflight recipe. Keep all changed code and documentation in
English. Absolute config paths are intentional.

Before a planning run, supply:

1. **Governance:** institutional determination/approval or documented exemption,
   data steward, permitted datasets/licenses, verified NAS ACL and approved model
   data flow. Approval must cover any external LLM provider and screenshots.
2. **Frozen protocol:** exact row IDs, investigator, freeze time, study kind,
   arms, sampling seed, sample-size basis, analysis, independent-reference subset,
   pilot/main separation, exclusions and stopping/missingness policy. Proposed
   N=800/40/200 in the design are not approved sample sizes.
3. **Acceptance rules:** every guide/report check has a method, pass rule, owner
   and evidence requirement under `criteria`. Qualified reviewers freeze actual
   numerical wall/clearance/fit/registration/readability rules; the software does
   not invent manufacturing or clinical tolerances. Include
   `current_quality_evaluation` and `source_model_and_dose_calibration` for the
   provided first-attempt endpoint.
4. **Resource budget:** approved maximum attempts, retained bytes, deadline and
   dedicated account quota. Fill timeout caps and reserve values from the pilot;
   examples are not measured runtimes. Set `max_experiment_bytes` equal to the
   approved retained-byte budget.
5. **Profiles:** `APPROVED_RESEARCH`, named clinical and physics reviewers,
   source-backed applicability, supported source/calibration/model, prescription
   Gy, upper-dose Gy, coverage fraction, iteration count and mode. Current runner
   supports supplied union without a margin and standard OAR inference.
6. **Model assets:** exact individual source file, destination relative path and
   SHA256. `model_recipe.dose_engine` and `.source` must exactly match the selected
   profile, and its weight hash must be pinned. Configure all other OAR/RL/model
   dependencies in the copied product according to its documented setup. Never
   link a whole production directory or a writable patient runtime.
7. **Case approvals:** JSONL, one row per exact `row_id`, with approved target and
   source hashes and applicable profile ID. Resolve phase/site/histology and
   component inclusion where needed; a metadata-positive lesion is not proof of
   malignancy or suitability for permanent seed implantation. Use a reviewed
   cluster ID if legitimate linkage is available. Otherwise only CT-content
   clusters, not patient-level inference, may be reported.

Supported settings are applied through the UI and subsequently checked against
the consumed planning provenance. Unsupported model/source recipes do not become
valid because the prompt requests them. The actual `effective_mode` is recorded;
an unregistered RL-to-rule-based fallback cannot silently pass. The scheduling
seed counterbalances AB/BA order; it is **not** a claim that the internal planner
or GPU kernels are deterministically seeded. Freeze and validate any supported
planner RNG controls separately. Both arms use fresh case state; cache and
cold/warm conditions must be reported, not silently treated as identical.

For paired analysis, `analysis` can contain:

```json
{
  "method": "stratified_paired_cluster_bootstrap_v1",
  "stratum_field": "approved_site",
  "stratum_weights": {"COPY_APPROVED_SITE": 1.0},
  "noninferiority_margin": 0.05,
  "alpha": 0.025,
  "bootstrap_replicates": 10000,
  "minimum_clusters_per_stratum": 50
}
```

This example is not a scientific freeze. Weights must be prespecified, positive
and sum to one. `stratum_field` supports `dataset` or `approved_site`. One target
per resolved cluster is required. The bootstrap is paired and stratified; sparse
strata are exploratory, duplicate attempts block inference, and unfinished or
undispatched allocations prevent a final primary estimate. FAIL/UNKNOWN terminal
attempts count as unsuccessful, not dropped. Investigators must validate the
chosen interval/sample-size method before a confirmatory publication. No
post-hoc superiority claim or clinical equivalence is generated.

The decision interval conservatively envelopes the stratified bootstrap with a
finite-sample Hoeffding bound for weighted paired differences in [-1, 1]. This
prevents a zero-width all-ties bootstrap from spuriously establishing
noninferiority. Freeze this guard before execution and recalculate required N
for the resulting conservative method; the design's provisional normal-method
N=800 is not validated power for this implementation. Both intervals are saved.
An investigator-approved more efficient validated paired interval requires a
new preregistered analysis implementation, not removing the guard after results.

## 5. Inventory and preflight (no planning)

In the examples below set `PY` to your isolated runner Python and `CFG` to your
reviewed config. Never point `metadata_runtime` to production.

```bash
PY=/home/lht/.local/share/brachybot-ct-cohort/experiment-tools/venv/bin/python
CFG=/absolute/private/path/experiment.json
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" inventory
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" doctor
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" validate-profiles
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" dry-run
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" preflight \
  --dataset 'MSD:Task06_Lung' --limit 5 --allow-offline-data-access
```

`--row-id` can be repeated to inspect specific frozen records. A positive limit
and explicit offline-access acknowledgement are mandatory. Missing images,
missing targets, MRI prostate zones, empty selected labels, conflicting grids or
unresolved spatial units remain blocked. A spatial-unit override needs documented
evidence; do not assign millimeters simply to make a record pass. Near-integer
repair requires the registered label alphabet and is not a probability-mask
threshold. Derivatives preserve exact selected voxels and are reread for physical
and array equality. Source files are never overwritten.

Existing resolved records are cached only under the same policy/source identity.
For a changed policy or an earlier blocked record that now has new review/input,
use a new experiment ID and rerun preflight; do not rewrite frozen rows belonging
to an attempted recipe. Case approval follows successful preflight, not the
reverse. Dry run displays eligibility and the exact natural-language request
without product mutations.

The current registry contains 40,299 candidate records, not 40,299 usable tumors.
Its distinct CT counts, target-bearing subset and exclusions are explained in the
design and inventory JSON files. The registry also contains `CT_DICOM` and
`MRI_T2_ADC`, which are not interchangeable with ordinary NIfTI CT.

### DICOM branch

```bash
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" convert-dicom \
  --row-id 'COPY_EXACT_PSMA_ROW_ID' --allow-offline-data-access
```

Review the generated `conversion.json`, native CT/SEG overlay, selected segment
meaning, residual registration, component policy and resampling volume change.
Create a hash-bound JSONL receipt following `conversion_approval.example.json`,
set `conversion_approvals_path`, and run preflight for the row in the intended new
experiment. The conversion preserves original CT and PET-referenced SEG hashes,
then derives a binary target on the native CT grid. Frame UID equality is only a
necessary condition; PET lesion identity is not a brachytherapy indication.
Irregular/enhanced/ambiguous series and unsupported encodings are blocked for
separate expert handling, never array-copied onto CT.

## 6. Provision a dedicated SUT

```bash
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" provision
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" serve
```

Provisioning requires the exact reviewed product HEAD and no tracked dirty code.
It copies tracked product files, verifies hashes and links only explicitly pinned
models. Untracked local model/config resources must be supplied explicitly;
secrets are configured privately by the operator, not copied from production.
Provisioning does not grant case eligibility or start planning.

`serve` runs in the foreground and supervises only its own process group. Use a
reviewed user-service wrapper if persistent operation is required. Register a
new **experiment-only** account in the isolated UI, not a production account
migration. An SSH port forward can expose the loopback service for setup. Keep
credentials in `COHORT_USERNAME` and `COHORT_PASSWORD`, never JSON, command-line
arguments, repository files or experiment result tables.

The service retains the product's normal startup and graceful-shutdown handlers.
If an active operation defers shutdown beyond 30 seconds, the launcher records
PENDING and refuses new run mutations; it does not automatically escalate to
SIGKILL. Observe/collect the existing task and follow the approved operator stop
procedure. This is intentional data preservation, not successful cancellation.

If the approved cohort exceeds the product's default account quota, stop only
the isolated service and configure the approved quota:

```bash
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" set-account-quota --execute
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" serve
```

This explicit setup command only updates quota metadata in the owned isolated
database after checking a named approved budget. It refuses a running isolated
server, does not retrieve password hashes, and does not touch production users.
The runner verifies actual account quota again before planning. NAS free space
does not bypass account quota.

## 7. Execute an explicitly bounded batch

Only after all gates are open:

```bash
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" run \
  --execute --max-cases 1 --arm paired
```

Start with the approved pilot, not a census. Alternatives are `browser-chat` and
`manual-ui`, if registered. Paired execution uses separate cases with the same
supplied CT/target/profile and counterbalanced order; it is not a human expert
study. The whole frozen frame is checked for eligibility and duplicate clusters
before the first case is dispatched. No random case is substituted when an
allocated record is unavailable.

The upload sequence is intentionally strict:

```text
real New Case → CT file input → mask file input (staged only)
→ stable Data Tree row → real Move to CTV
→ checkpoint object IDs + exact physical target verification
→ reload and verify durable CTV → approved controls
→ real chat Send OR prescribed manual controls
→ actual case/task completion and browser completion
→ saved current plan + report → UI PDF/Session export
→ independent byte/value checks → qualified review
```

An upload success receipt does not mean the effective CTV is ready. A reply,
idle indicator, score, STL existence or PDF magic bytes does not mean the whole
workflow completed. The script never bypasses a confirmation/safety gate by
invoking a private mutation endpoint. If the ordinary UI asks for clarification
or cannot consume the supplied profile, the attempt remains partial/failed and
the response/evidence is retained. Ordinary failures are not retried until lucky.

GPU and account dispatch are serialized with owned leases. An unresolved
timeout/cancellation stops further mutations. The next run can retire a proven-dead
local runner lease, but cannot steal a live/foreign/unknown lease or blindly replay
the recipe. Owner PID, process creation time and boot ID protect against PID reuse.
Reclaim/release evidence is retained under the lock root's `retired/` directory.
Cross-experiment leases coordinate runners
under the same result root; they do not replace the product GPU lease or prevent
unrelated jobs outside this root. Freeze and reserve GPU resources operationally.

## 8. Results and verifiable completion

Per attempt, inspect:

- `attempt.json`, `planning_recipe.json`, `session.json`, `selected_target.json`;
- `chat_task.json`, `user_visible_chat.json` when available;
- `planning_results.json`, `target_metrics.json`, `oar_metrics.json`,
  `plan_geometry.json`, `engine_execution.json`;
- `report.pdf`, `session-export.zip`, extracted `export/`, `observer-backup/`;
- `screenshots/`, `events/`, `mutation_transport_log.json`;
- `artifact_manifest.json` and immutable `terminal_result.json`.

Outcome checks are PASS / FAIL / UNKNOWN. Missing observations cannot pass.
`workflow_completion` requires exact target, nonempty finite seed/needle
geometry, consumed recipe and actual mode, current/export-complete artifacts,
finite physical-grid dose, saved DVH, quality review, guide topology, parseable
PDF, budget, qualified source/calibration/guide/report review and archive hashes.
Topology does not establish safe channels/walls/skin fit; PDF parsing does not
establish readable figures. A quality score alone is not quality evaluation.

`software_artifacts_present` is an existence description only. `VERIFIED_SUCCESS`
is reserved for the full software endpoint; it is not clinical approval.
Incomplete or stale artifacts, missing review or inaccessible data are retained.
The frozen account/compute/time/storage budget is part of the endpoint.

### Render and adjudicate the same first-attempt bytes

```bash
ATTEMPT=/absolute/NAS/path/runs/RECIPE_HASH/ATTEMPT_ID
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" verify --attempt "$ATTEMPT"
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" render-pdf --attempt "$ATTEMPT"
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" finalize-review --attempt "$ATTEMPT"
```

Use `artifact_review.example.json` to write
`<review_directory>/<recipe_hash>.json`, status `APPROVED_RESEARCH_REVIEW`, with
exact attempt/recipe/rules hashes, artifact hashes, reviewer/time and every frozen
check. The draft is not accepted. Inspect the actual guide channels, native skin,
source/calibration, current quality record, report versions, figures, annotations
and restored Viewer state. Never fill PASS from a chat claim. Rendered PDF pages
go to separate NAS review storage, leaving first-attempt artifacts immutable.

`finalize-review` verifies original archive hashes and stores a linked
adjudication in `tables/adjudications/`; it does not rerun the SUT or overwrite
the terminal record. Analysis can use an approved interpretation of those exact
first-attempt bytes. Recovered or regenerated artifacts are not retroactively
counted as first-attempt success.

### Pause and resume a large cohort

There is no requirement to finish the cohort in one invocation. Run 100 cases today,
stop, and run the **same command with the same private config and experiment ID**
tomorrow. `--max-cases` counts pending cases, not the first 100 rows of the inventory.
The frozen frame/recipe hashes and durable NAS records are the cursor, not a
manually entered row number. Do not remove earlier outputs or create a new experiment ID.

```bash
cd /home/lht/snap/brachyplan/BrachyBot/experiments/ct_cohort
PY=/home/lht/.local/share/brachybot-ct-cohort/code-validation/venv/bin/python
CFG=/private/reviewed-experiment.json  # operator-provided approved config, not a draft
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" run \
  --execute --max-cases 100 --arm browser-chat
# Later: execute exactly the same command to continue.
```

After Ctrl+C, a killed runner, dropped SSH session or reboot:

1. Already recorded cases (including recorded ordinary failures) are skipped.
2. An interrupted case is selected through the original owned case UI. The runner
   waits until **both** its chat task and server operation are terminal/idle; it
   does not assume a closed browser means a stopped GPU job.
3. Finished dose/guide/report products are collected into a new recovery directory.
   Recorded verification FAIL/UNKNOWN remains visible; it is not retried until PASS.
4. If the original server is idle but the interrupted case is incomplete, only that
   target/arm is retried in a new isolated case. Earlier completed cases are untouched.
5. The rest of the pending queue continues. Repeated interruptions use linked retries.

This is **case-level** resumption, not restoration of an in-memory CNN/RL iteration.
An unfinished case may have to run again; it does not force earlier cases to run again.
A clean Ctrl+C records interruption and releases runner leases without declaring the
server cancelled. An abrupt kill leaves durable records and a recoverable dead-owner
lease. An old pre-0.2.1 attempt without a recorded case identity remains blocked for
explicit operator reconciliation rather than guessing an unrelated case.

Keep the same NAS mount and persistent isolated metadata/runtime. If the isolated
service itself stopped, restart **that experiment service** using the existing
`serve --execute` procedure, then repeat `run`; the LAN/public services are not
restart targets. Unavailable NAS, corrupt/ambiguous records, live foreign owners,
changed recipes/profiles, or expired approvals/deadlines remain explicit blockers.
Continuation does not silently extend budgets or approvals. Additional interrupted-case
retries consume the approved `max_attempts` allowance; reserve headroom prospectively.

Original first-attempt records are never overwritten. New collections are under
`runs/<recipe_hash>/<attempt_id>/recoveries/<recovery_id>/`; case retries have their
own attempt directory, `retry_of` and `first_attempt_id`. `recovery_state.json`
binds the scheduler settlement to a hashed receipt. Analysis reports first-attempt
and eventual recovered outcomes separately, so interruption does not inflate results.

### Read-only diagnostics and explicit collect-only recovery

```bash
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" reconcile
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" resume-collection \
  --attempt "$ATTEMPT" --execute
```

`reconcile` is file/checkpoint-only and never marks replay safe. `resume-collection` selects the
existing owned case through UI, checks current task/operation, and only exports
what is already there. It refuses a live/changed task. New evidence is stored in
`tables/recovery/`, separately labeled; no CT upload, CTV transformation, dose,
planning, guide or report regeneration is repeated. This diagnostic command does
not advance the automatic scheduler; repeating `run` performs the fenced settlement.
Do not manually delete locks/results merely because the browser disappeared.

## 9. Independent physics reference

Generate an independent dose field using a validated engine selected by the
physics reviewers, outside the agent/product being tested. The reference recipe
must bind isotope/model/strength/unit/time, engine/version, reference dose hash,
SUT dose hash, target hash and exact geometry path/hash, all in Gy on a validated
physical grid. No automatic registration/resampling hides a grid mismatch.

```bash
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" verify-reference \
  --dose /NAS/current-dose.nii.gz --reference-dose /NAS/reference-dose.nii.gz \
  --target /NAS/verified-target.nii.gz --profile-id APPROVED_PROFILE_ID \
  --reference-recipe /private/approved-reference-recipe.json
```

The output includes mean, 95th-percentile and maximum target absolute dose error.
Agreement tolerances and clinical interpretation require the frozen qualified
physics protocol. Whole-cohort CNN DVH is descriptive; headline physical-quality
claims must be based on the preregistered reference-evaluable subset. This runner
does not manufacture an independent engine, an approval or reference result.

## 10. Analysis and exports

```bash
PYTHONPATH=. "$PY" -m brachycohort --config "$CFG" analyze
```

Produces `analysis.json` and:

| Table | Meaning |
|---|---|
| `attempts.csv` | All started first attempts, including missing terminal records |
| `recovery_attempts.csv` | Linked interrupted-case retries and existing-case reconciliation; excluded from primary first-attempt denominators |
| `target_metrics.csv` | Saved product proxy metrics, not independent dose truth |
| `oar_metrics.csv` | Organ-specific saved numeric values, with source basis |
| `seeds.csv` | Stable seed/trajectory references and patient LPS-mm positions |
| `needles.csv` | Needle references, endpoints and length |
| `stage_times.csv` | Measured browser stage completion/failure durations |
| `resources.csv` | Runner RAM, host availability and GPU metadata samples |

`attempts.csv` additionally exposes `case_progress`, `recovery_attempts`,
`eventual_software_completion` and `eventual_artifact_directory`. Raw recovered
metrics/geometry/report/dose exports are in that explicitly linked directory;
primary long-format tables continue to describe original first attempts.

Raw server receipts, event payloads, task/checkpoint data and service logs retain
additional substep timings when the product actually exposes them. UI transport
duration is not relabeled as GPU kernel time. Missing per-tool times are unknown,
not zero. Failed/unfinished attempts remain in all-attempt summaries. Exported
CI/HI preserve the product's custom definitions; do not label them as standard
clinical conformity/homogeneity indices without independent validation.

For a registered paired protocol the locked analysis requires all allocated
pairs to reach adjudicated terminal observations, fixed weights and sufficient
clusters. It reports a design-weighted paired interval and the prespecified
noninferiority comparison; it does not claim validated power merely because
the code returns an interval. Unregistered analysis remains descriptive.

## 11. Validation and limits

```bash
PYTHONPATH=. "$PY" -m pytest -q \
  --basetemp=/home/lht/nas/LHT_workspace/Brachytherapy/BrachyBot_CT_Cohort_Experiments/ct-cohort-code-validation/tests-final
```

Use only an owned validation directory as `--basetemp`; pytest clears its prior
contents. Tests include actual Chromium interacting with a synthetic HTTP UI,
not an approved medical SUT run. They verify control ordering, CT/mask upload,
real Move to CTV, consumed provenance, downloads, DICOM conversion, negative
geometry/authorization contracts, missingness and artifact evidence. Small
symlink-safety fixtures use volatile tmpfs because CIFS lacks symlinks.

Before production-scale research, the approved pilot must validate the pinned
real product UI, model/source compatibility, dose and target-grid exports,
actual stage timing availability, report/guide acceptance, cancellation/recovery,
cost/storage estimates and statistical protocol. The package does not claim
that thousands of cases have been run or that draft clinical gates are open.

Follow `docs/CT_COHORT_EXPERIMENT_IMPLEMENTATION_2026-10-04.md` for the delivered
code-validation evidence and the separation between implementation completion
and approval to begin the experiment.
