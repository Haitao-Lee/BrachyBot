# Real User Requests v1: completed 210-item development construction

## 1. Deliverable and boundaries

This release completes a quality-controlled development expansion to **84
scenario families / 210 scenarios / 630 distinct negative-control
specifications**. It preserves the original 82 user protocols and adds 48
state-contrast scenarios followed by 80 workflow scenarios. Existing original
multi-turn contracts are also strengthened; their user wording and IDs remain
unchanged. The earlier 130-item expansion report is a historical phase record.

The construction includes hand-authored requests, synthetic case fixtures,
private executable effect/goal contracts, event scripts, independent response
rubrics, per-item review cards, deterministic task projections, inventory,
source/product manifests, environment executors, collector checks, component
controls and English developer documentation. No SUT is evaluated in this work.

"Completed development construction" does **not** mean independently approved
semantic gold, patient validation, real product-browser validation or formal
leaderboard readiness. All items remain exploratory, public development and
`formal_eligible=false`. A correct machine witness is not an intelligent agent,
and no component test is a measured BrachyBot result.

The original core benchmark tasks, splits, MANIFEST and experiment results are
unchanged. No clinical planning, dose calculation, provider run, production UI
submission, model score or service restart is performed. Installation of pypdf
for offline validation is isolated from the production environment.

## 2. Construction inventory

| Phase | Families | Scenarios | Negative-control specifications |
|---|---:|---:|---:|
| Original development catalog | 40 | 82 | 246 |
| State-contrast addition, RUR-41 through RUR-64 | 24 | 48 | 144 |
| Workflow addition, RUR-65 through RUR-84 | 20 | 80 | 240 |
| Total | 84 | 210 | 630 |

Each scenario has a concrete goal, plausible BrachyBot state, explicitly scoped
effects, useful-response requirement, three different failure specifications,
independent evidence requirements and a shared family split identity. The new
workflow families contain four decision-relevant contexts each, not four
synonyms of one request. Machine state rules and independent semantic criteria
are deliberately separate; neither can substitute for the other.

`compiled/coverage.json` provides exact multi-turn, event and phase counts.
Every family row carries its meaning and explicit pending review/live gates.
Counts describe design inventory, not percentages of all possible requests.
All synthetic fixtures share lineage and are not independent patients.

The inventory contains **233 user turns**, including **59 Chinese and 174
English turns**, **22 multi-turn scenarios**, and **35 scenarios with scripted
environment events**. Proactive event-only cases are not fabricated user turns.
These are counts, not a claim of matched bilingual difficulty or language parity.

## 3. Added workflow families and all four contexts

The four contexts in each row correspond in order to IDs `-001` through `-004`.
Full requests, states, private rules and counterexamples live in
`compiled/review_cards/RUR-xx-yyy.json`.

| Family | Four contexts | Distinct failure mechanism |
|---|---|---|
| RUR-65 Corrections | Show then hide; opacity correction; add a target without reversing prior display; read-only follow-up | Correct terminal state cannot excuse premature actions or dropped first-turn fulfillment |
| RUR-66 Clarification | Unselected pronoun; duplicate guide version; ambiguous opacity; ambiguous group then exclusions | Clarification must precede execution and the resolving answer must actually bind scope |
| RUR-67 Communication | Chinese then English; concise then table; plain text rather than raw state; table with missing data | Answer language, format and completeness do not authorize global state changes |
| RUR-68 Target-action binding | Show guide/read CTV volume; hide needle/explain generation; color CTV/read brain dose; show guide/query stale report | Separate clauses cannot lend their authorization to a different target or action |
| RUR-69 Parameter boundaries | Zero opacity; full opacity; out-of-range 140%; unsupported millimeter movement | Explicit values and physical/display units must be interpreted without silent clipping or substitute mutation |
| RUR-70 OAR metrics | Dmax versus D2cc; missing Dmean; stale organ row; measured zero with nonzero Dmax | Statistic, missingness, revision and organ identity are independent dimensions |
| RUR-71 Comparison | Single-edit matched deltas; aggregate two-edit deltas; changed anatomy; missing current score | Numerical changes do not by themselves establish causal attribution or global clinical improvement |
| RUR-72 Dependencies | Quality then report; dose then quality then report; independent guide/report; guide display plus report refresh | Input identity and completion barriers matter, not submission order or artifact existence |
| RUR-73 Tool failure | Failed dose plus seed hide; failed guide plus report; failed guide plus organ read; failed dose retains old artifact | Dependent branches stop while independent branches continue, with honest partial outcomes |
| RUR-74 Speech acts | Explain stale report; recommend display tool; explain prior nonexecution; polite actual display | Action vocabulary and question marks are not reliable authorization classifiers |
| RUR-75 Evidence | Hidden guide capture restored; show then capture; guide then CTV images retained; temporary CTV occluder removal | Persistent display and reversible evidence transactions have different restoration targets |
| RUR-76 Evidence limits | Tree existence versus 3D pixels; patient centroid versus screen direction; old screenshot; dose ranking versus distance | Metadata and historical images cannot support unobserved spatial/clinical conclusions |
| RUR-77 Monitor lifecycle | Repeated stop; lost stop ACK; wrong run ID; read-only active status | Owned server state governs lifecycle; keyword matching and UI glow do not |
| RUR-78 Monitor advice | Geometry conflict without dose; existing versus new conflicts; associated reprojection; return vector meaning | Advice must identify measured changes and uncertainty, not invent optimization or independent edits |
| RUR-79 Decision dialogs | Consumed undo token; wrong-case token; keep without automatic refresh; uncommitted preview cancel | Token ownership and edit granularity constrain action; keep is not broad clinical authorization |
| RUR-80 Async boundaries | External revision changes; case switch before read; lost show ACK; queued report cancelled later | Unknown acknowledgements and late scope changes must not cause replay or stale overwrites |
| RUR-81 Degraded capabilities | Viewer unavailable but organ data saved; printer unsupported but display available; unknown tumor site; unsupported optimal drag | A limit on one capability does not erase another, and cannot justify guessed clinical execution |
| RUR-82 Report workflows | Global English body/captions; translate then export; diagnosis-only localization explanation; confirmation then rebuild/export | Global language, response language, report replacement and download delivery have separate permissions |
| RUR-83 Low-trust inputs | Diagnostic command; quoted old command; current target versus old patient ID; imported approval | Data and user history are not fresh execution authority or authenticated clinical sign-off |
| RUR-84 Efficiency/memory | One-line saved fact; cumulative versus retained tokens; compacted report-only exclusion; bounded provider failure | Useful answers honor cost and provenance rather than doing hidden work or inventing fallback success |

The first 64 families remain covered by the original coverage report and the
state-contrast expansion report. This completion does not add unrelated EHR,
printer integration or clinical-treatment tasks to inflate breadth: unsupported
capability items test honest limits and partial completion, not those external
domains' engineering correctness.

## 4. New execution and oracle mechanisms

### 4.1 Per-turn authorization

Workflow effects carry the owning user turn. The oracle checks an attempted
effect's actual audit turn against that owner. A second-turn action performed
on the first turn is unauthorized even if final state is correct. The turn
field is evaluator-private metadata, not a tool argument sent to the worker.
Invalid or Boolean turn identities fail private contract compilation.

Original multi-turn items for cancellation, retry reconciliation, manual
initialization, relative-opacity retry and four-turn corrections are migrated
to the same mechanism. This fixes a weakness in the previous component witness,
which could execute all effects before later user inputs. Original requests and
legitimate task outcomes are preserved; temporal validation is stronger.

### 4.2 Independently captured per-turn state

The environment snapshots objects, artifact status, plan/geometry revisions,
Monitor, language, viewers and report state at response delivery. A later change
cannot overwrite that earlier observation. `turn_state` requires exactly one
final response for its owner and checks that snapshot. `turn_outcome` distinguishes
pending/partial work and clarification from later completed work.

Reply truthfulness, language, usefulness and clarity remain independent semantic
review criteria. Recording a state does not make an incorrect reply correct.
Missing snapshots, duplicated finals or missing human/judge evidence cannot pass.
The authenticated collector boundary, not a SUT-authored Boolean, owns evidence.

### 4.3 Frozen artifact inputs

Jobs freeze relevant input artifact identities at submission: quality captures
dose; report captures dose and quality; report figures capture dose. Completion
stores those frozen sources on the artifact. It must not retroactively replace
the job's input with a later upstream result.

The dose-to-quality-to-report scenario exposed an actual environment omission:
quality previously had no source record. The completed mechanism records it and
tests that jobs cannot falsely inherit a later dose artifact. The oracle retains
both dependency completion and source-identity checks; no requirement is relaxed
to make a fixture pass.

### 4.4 Required fault barriers

New event-bearing scenarios explicitly require their declared event/trigger to
have fired. A recovery path is not counted as exercised just because a run
returned an acceptable status. Job failure, stop ACK loss, external edits, case
switching and provider failure are evaluator-controlled synthetic events, never
extra fabricated user requests or gold supplied to the SUT.

### 4.5 Exact setters and typed parameters

The earlier value-bound setter and Boolean-versus-number repairs remain active
across all 210 items. A correct terminal opacity cannot erase an unauthorized
intermediate value. Guide version/position fixtures retain authored identities
and the original default physical position. Counts and hashes are derived from
sources rather than hard-coded historical inventory.

## 5. Quality controls and limits

All 210 items participate in schema/fixture validation, executable machine
witnesses, no-response/no-op failure controls, unauthorized-attempt retention,
missing semantic-review controls and exact setter checks. Added workflow tests
also cover premature future-turn actions, immutable delivery snapshots,
duplicate final responses, missing fault barriers and frozen source identity.

These controls are **benchmark infrastructure self-tests**. They do not execute
every one of the 630 prose fault specifications as a product test. Each such
specification still needs independent adjudication and a corresponding concrete
injection/trace before claiming executed fault coverage. The semantic rubric
must be calibrated independently of model answers and contract-driven witnesses.

The bank is meaningfully above two hundred items, but finite. It cannot establish
that an agent understands every possible sentence, that a simulated movement is
clinically optimal, that dose physics is valid or that a Monitor teaching policy
improves human performance. Those require separate physics, clinical and user
studies. English/Chinese user stimuli remain intentional; developer text is
English. Family/fixture provenance must determine splits and uncertainty, not
item IDs or wording variants.

## 6. Use without running a model

From `/home/lht/snap/brachyplan/BrachyBot/benchmarks/brachybench`, in an isolated
environment with this extension's test dependencies:

```bash
python -m extensions.real_user_requests_v1.build --check
python -m extensions.real_user_requests_v1.prepare --check
python -m extensions.real_user_requests_v1.runner
python -m pytest -q extensions/real_user_requests_v1/
```

All commands above are offline construction/infrastructure checks. The default
runner only validates. Explicit `--execute` is a future opt-in **sandbox** worker
interface, not evidence of product/browser parity. Every formal comparison must
submit the actual request through the real user chat input and collect replies,
effects, attachments, downloads, persistence and UI lifecycle independently.
Absent real-product fixture/event drivers must be BLOCKED/missing evidence,
never a successful score.

Before main experiments: independently adjudicate all criteria and valid
alternatives, implement isolated real-product drivers, calibrate semantic/visual
review, freeze connected-family/source splits and a new manifest, and perform
the explicitly authorized pilot. No such model run is implied by this release.

## 7. Publication and validation record

Construction and testing use `/tmp/benchmark-rur-completion-20261004`; dependencies
use `/tmp/benchmark-rur-validation-20261004`. Publication checks current bytes
against the 130-item baseline, saves scoped backups, and writes only this
extension and this report. It does not reset the dirty worktree or modify LAN or
public services. Existing core benchmark inputs are checked separately.

Final regression outcomes are recorded below after the complete offline run.

### Final offline regression

- Expanded extension regression: **1,715 passed** in 22.67 seconds.
- Complete existing benchmark regression plus expanded extension:
  **25,962 passed**, zero failures/skips, in 181.18 seconds. Three warnings are
  SWIG-type deprecations in environment-lock collection.
- Candidate projection, compiled task/fixture/contract build and default
  validate-only runner must pass their drift checks after publication.
- Evidence: `/tmp/benchmark-rur-completion-20261004/regression.xml`,
  `regression.log` and `extension.log`. These files record infrastructure
  self-tests, not a model experiment or formal score.
- Published scope is only `benchmarks/brachybench/extensions/real_user_requests_v1`
  and this report. Scoped prior contents are retained in the isolated
  `pre-publication-backup` directory with a byte-hash publication record.
- All 210 items retain independent semantic review pending and live validation
  not run. No provider/SUT experiment, clinical operation or restart occurs.
