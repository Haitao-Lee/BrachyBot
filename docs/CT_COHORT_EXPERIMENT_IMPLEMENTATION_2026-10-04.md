# CT cohort experiment implementation and verification

Date: 2026-10-04. This is an engineering handoff, not a report of patient
experiments, benchmark performance or clinical validation.

## Extension: full eligible census and CNN scope

### Case-level interruption resumption (package 0.2.1)

Repeating the same `run --execute --max-cases ... --arm ...` command with the same
private config, frozen frame, experiment ID and NAS result root now resumes the
queue after a stopped/killed runner. Earlier recorded cases are skipped. The runner
first reattaches an interrupted original case, waits for BOTH chat-task and server
operation completion, and collects finished products without repeating planning.
If the server is idle and the interrupted workflow is incomplete, only that
case/arm is retried; ordinary recorded failures are not retried until successful.

Case identity is committed inside the browser control before uploading/launching
planning, not only after control returns to the caller. Published attempt
directories always include their durable identity/recipe record. Same-host stale
runner leases can be retired only with proof of process exit, PID reuse or reboot;
live/foreign/ambiguous owners are not expired by age. Retained lease receipts and
hashed recovery settlements support repeated interruptions without lock deletion.

Primary analysis still has one first attempt per target/arm. Linked case retries
and recovered collections appear separately in `recovery_attempts.csv`, with
eventual completion and artifact paths alongside (not instead of) first-attempt
outcomes. The original first-attempt artifacts/results are not overwritten.
Resumption is at CASE level, not an in-memory CNN/RL optimizer iteration checkpoint.
An unfinished case may rerun, but completed earlier cases do not.

The original isolated service must be available (restart that service if it stopped).
Unavailable NAS, changed recipes, corrupt/ambiguous state, expired approvals or
exhausted attempt/deadline/storage budgets remain explicit blockers. No real cohort
was started for this extension; validation uses targeted synthetic fault injection
and actual Chromium on a synthetic HTTP fixture. See README and VALIDATION.md.

The prior N=800/40/200 statements were provisional study-design assumptions,
not an 800-case runtime cap. The implementation now offers full eligible census
frames (`build-frame --target-policy all-targets`), streaming all-records
preflight, resumable new-case batching and an explicitly bounded `--all-pending`
mode. The exact eligible frame records CT path, label path, label values,
target/source hashes, profile, site and cluster identity. Multiple targets per
cluster are valid for descriptive target-run stress tests, not independent
patients or the paired primary study. Draft selections still confer no approval.

The default product engine remains the existing CNN DoseUNet. No planner/model
change is included in this extension. `verify-reference` is an **importer and
comparison checker**, not an implemented TG-43/Monte Carlo solver, and it is
not a prerequisite for CNN cohort execution. Scientific reports distinguish
CNN-field measurements, saved-artifact/internal consistency, qualified artifact
review and separately supplied independent physics. No independent physics
results currently exist merely because the integration code exists.

A descriptive census can freeze the new software-completion endpoint without
requiring per-output clinical/manufacturing review to count engineering
completion; both software and reviewed outcomes are stored. Paired protocols
keep the old reviewed endpoint. Clinical approval and physical validation are
never inferred from software PASS. Applicable profiles, exact inclusion,
governance, calibration compatibility and budgets remain fail-closed.

The runner advances beyond terminal prefix cases, counts only actual pending
arms against attempt budgets, preserves partial pairs and first-attempt failures,
and stops on unresolved in-flight work rather than replaying it. Batch allocation
and outcomes are persisted. `analyze` emits every allocated target/arm, including
NOT_STARTED/INCOMPLETE, and separates software from reviewed success. The full
frame is loaded once per batch; small signed gate documents/deadlines remain
checked before each case. Model weights are not rehashed for every case.

See the README extension for commands and `configs/protocol.census.draft.json`
for a draft census protocol. These templates contain no guessed prescriptions,
source strengths, reviewer identities, approval dates or feasibility estimates.

## 1. Deliverables

- Revised scientific design:
  `/home/lht/snap/brachyplan/BrachyBot/docs/CT_COHORT_PLANNING_EXPERIMENT_DESIGN_2026-10-04.md`.
- Standalone implementation:
  `/home/lht/snap/brachyplan/BrachyBot/experiments/ct_cohort/`.
- Full English installation, configuration, run, review/recovery and analysis
  instructions: `experiments/ct_cohort/README.md`.
- Draft documents: `experiments/ct_cohort/configs/`; these do not confer approval.
- Tests: `experiments/ct_cohort/tests/`.
- Code-validation scope and references: `experiments/ct_cohort/VALIDATION.md`.

The source product HEAD is `0d1dbffe4de291b39737b87ea44961429b12748c`.
No production algorithm, frontend, source patient CT/label, LAN account database
or public-release configuration is changed by this implementation.

## 2. Scientific corrections

| Audit concern | Resolution |
|---|---|
| Descriptive engineering audit presented as a comparative experiment | Separate conditional feasibility/pilot from a proposed paired browser-chat vs prescribed manual-UI study; state hypothesis, estimand, margin and missingness |
| No N, precision or budget | Add auditable proposed planning assumptions, sensitivity, independent-cluster precision and time/storage examples; require measured pilot budget before main freeze |
| Unapproved prescriptions/OAR/guide criteria | Execution defaults CLOSED; require institution/profile/case/endpoint/resource approvals, no default clinical profile |
| CNN validating itself | Classify saved-field arithmetic separately from independent physics; headline physical-quality conclusions require the reference-evaluable subset |
| “Independent observer” actually internal product state | Label internal consistency, external saved-artifact verification and independent physics distinctly |
| Candidate pairs called target-bearing | Correct terminology; preserve original inventory counts and require payload preflight for positivity |
| Target rows treated as independent patients | Freeze one target/acquisition per resolved cluster; unknown linkage supports CT-content-cluster technical results only |
| Vague artifact acceptance | Freeze method/pass rule/owner/evidence for every criterion; topology/PDF parser alone cannot complete the endpoint |
| Clinical indication/ethics assumed from dataset | Named reviewers and institutional determination, dataset permissions, source/model compatibility, model data flow and server ACL gates |

The proposed N=800/40/200 are not approved counts. The implementation's guarded
paired interval is not validated power for N=800. Main-study sample size and
analysis need investigator validation and a signed freeze after a separate pilot.

## 3. Implementation contracts

### 3.1 Exact inputs and target semantics

Registry rows retain original CT/label paths, source label values, phase and
semantics. NIfTI preflight reads payloads, checks geometry/units/finite values,
derives the selected binary union without a margin and rereads it. It records
source/derivative hashes, connected components, target volume and FOV contact.
Wrong histology/site/component policy is not resolved by a positive voxel count.

`CT_DICOM` is a distinct registry modality. DICOM conversion validates regular
native CT/PET, reference frame/series, SEG functional-group geometry and segments,
then resamples PET-referenced binary SEG to native CT in patient coordinates.
Conversion is not eligibility: a hash-bound registration/target/resampling review
is required before preflight. Enhanced/ambiguous/irregular/unsupported inputs
remain blocked rather than silently approximated.

Browser mutations use real UI controls. Uploaded masks are staged generic data;
the runner clicks the actual Data Tree Move to CTV operation, binds stable object
IDs, checks the effective binary target in physical space and verifies persistence
after reload. Original input hashes are rechecked after the attempt.

### 3.2 Actual settings and task completion

Approved profile parameters are applied through UI controls before the request.
The browser-chat arm sends a fixed English natural-language request; the
manual-UI arm clicks the prescribed ordinary controls. Both preserve the supplied
target and share approved settings/model recipes, not mutable clinical artifacts.

Observed consumed settings, target fingerprint/object references and actual
planner mode are compared with the recipe. An unregistered RL fallback fails
that check. Scheduling seed is not falsely reported as a deterministic planner
seed. Saved bytes/current plan identity matter more than chat claims or an idle
button. Report capture/save completion is observed separately from its initial
server field-preparation receipt.

### 3.3 Archiving, outcome and recovery

NAS archives include immutable first-attempt recipes, case/task identity, raw
receipts, visible chat when exposed, screenshots, geometry, target/OAR metrics,
DVH/dose, current guide, real downloaded PDF, Session ZIP, safely decoded backup,
resource samples and SHA256 artifact manifests. JSON/CSV exports do not relabel
the custom product CI/HI as externally validated clinical indices.

Outcome is PASS/FAIL/UNKNOWN. Empty/NaN/duplicate geometry, stale/missing exports,
incorrect consumed parameters or source changes cannot pass. Grid/quality/source
calibration uncertainties remain unknown, not clinically approved. Guide channel,
wall, fit, manufacturing and report figure/readability judgments require qualified
review of hash-bound actual artifacts. A finished file is not a finished endpoint.

Explicit `resume-collection` selects an existing case and collects only; it does
not rerun planning, upload a replacement target or regenerate a failed branch.
Automatic queue resumption additionally permits a linked retry of an interrupted,
incomplete case only after the original server operation is verified idle.
Recovery evidence is secondary and does not overwrite first-attempt outcomes. Post-run adjudication
can update the interpretation of the original bytes with a linked review, even
after the execution deadline; it cannot reopen permission to execute.

### 3.4 Isolation and resource controls

Large results, derivatives, copied workspace artifacts, uploads, temporary
outputs, archives and logs are NAS-backed. The actual CIFS mount lacks symlinks;
small code and SQLite metadata are isolated locally, while browser profile/scratch
uses checked volatile tmpfs. SQLite/WAL is not put on the network mount.

The dedicated SUT must use a new loopback port, its own copied code/runtime/cookie
and newly registered account. No production account migration or shared writable
runtime is performed. Listener/process creation time/cwd/command/runtime and
file/model hashes are checked. Quota setup is explicit and isolated; it never
reads password hashes. Product startup and graceful shutdown are retained.
Active operations are not automatically SIGKILLed after the supervisor timeout;
pending shutdown blocks new run mutations until reconciliation.

Approved stage/overall/deadline, capacity, retained-byte and account quota bounds
are checked. GPU/account runner leases do not authorize stealing a live task.
The NAS free-space budget and product account quota are different controls.

### 3.5 Analysis and scale

Generated tables: attempts, target metrics, OAR metrics, seeds, needles, measured
browser stage times and resources. Large seed/organ/event tables are streamed
instead of constructing millions of dictionaries in RAM. Raw observations retain
actual per-tool timing when exposed; unknown GPU/substep timing is not invented.

Missing terminal records remain in the started-attempt denominator. Frozen but
unfinished/undispatched paired allocations prevent a final primary estimate.
Unregistered analysis is descriptive. The optional locked method uses paired
cluster differences and prespecified dataset/approved-site weights, blocks
duplicates and sparse/unknown strata, and records both bootstrap and guarded
intervals. The conservative Hoeffding envelope prevents an all-ties bootstrap
from producing unjustified zero-uncertainty noninferiority. Its sample size must
be recalculated; it does not establish clinical equivalence or superiority.

## 4. Validation performed

Remote runner environment:
`/home/lht/.local/share/brachybot-ct-cohort/code-validation/venv`.

```bash
cd /home/lht/snap/brachyplan/BrachyBot/experiments/ct_cohort
PYTHONPATH=. /home/lht/.local/share/brachybot-ct-cohort/code-validation/venv/bin/python \
  -m pytest -q \
  --basetemp=/home/lht/nas/LHT_workspace/Brachytherapy/BrachyBot_CT_Cohort_Experiments/ct-cohort-code-validation/tests-final
```

Final delivered suite: **134 passed, 0 failed**. Three warnings are upstream
SimpleITK/SWIG deprecation warnings. This is the standalone experiment package's
suite, not a claim that the entire BrachyBot/benchmark repository suite was run.

Tests include actual Chromium against a synthetic HTTP application for both arms,
and whole-attempt execution/export/collection. The latter deliberately generates
valid dose/guide/PDF artifacts without qualified review and must remain
UNKNOWN/partial rather than VERIFIED_SUCCESS. Additional cases test full label
payloads/physical reorientation, DICOM frame/series/grid/encoding errors, false
provenance, parameter mismatch, fallback, fake PDFs, broken meshes, ZIP traversal,
frozen approval drift, expired execution versus offline review, missingness,
adjudication and process/account metadata isolation.

Read-only smoke checks:

- Inventory: 40,299 rows; manifest SHA256
  `9b2cefc9a60d9ddb864779c3988230b4ce5f923f3b6e956fd6010c9cd2916b06`.
- Dry run: CLOSED / `GOVERNANCE_UNRESOLVED`, zero product mutations.
- Doctor: all runner dependencies found; expected CIFS mount verified; experimental
  deployment NOT_READY because it has not been provisioned/started.
- Existing LAN/public listeners were observed on 8080/18082; no 18086 experiment
  service was started. No restart or production job cancellation was performed.
- Python/JSON syntax and new-file whitespace checked; transferred-file integrity
  checked against the package manifest.

## 5. What has NOT been run or approved

No real-case cohort planning, pilot outcome, benchmark score, physician/physics
approval, TG-43/MC reference calculation, actual manufacturing acceptance or
clinical efficacy result is produced by this work. No exact planner RNG guarantee
or whole-cohort feasible runtime/storage claim is made. The isolated SUT has not
been launched in this turn. The supplied configuration intentionally has zero
approved primary cases.

## 6. Next operator actions

Follow the README: private reviewed config; institutional/data-flow/ACL approval;
approved model/source/profile and actual model asset mapping; bounded preflight;
case review and unique cluster frame; frozen endpoint/rules/budget/analysis;
isolated provision/account/quota; reviewed real-product pilot; then a separately
frozen limited main batch. The pilot must test the real pinned UI, source/model
consumption, physical dose/target export grids, guide/report evidence, interruption
and measured cost. A current export-grid mismatch remains UNKNOWN until a
validated mapping/observer contract is approved, not interpolated away by default.

Independent-reference generation is delegated to a qualified external physics
engine selected and validated by the investigators. `verify-reference` is an
evidence adapter for such results, not a replacement source-dose calculation.

## References

- [SQLite WAL network-filesystem limitation](https://www.sqlite.org/wal.html)
  supports the small local metadata / bulk NAS split.
- [Playwright Python inputs](https://playwright.dev/python/docs/input) documents
  ordinary file/input/button interaction used for mutations.
- [AAPM TG-43U1](https://www.aapm.org/pubs/reports/detail.asp?docid=85) is an
  independent-source-dose framework reference, not site-specific prescriptions.
