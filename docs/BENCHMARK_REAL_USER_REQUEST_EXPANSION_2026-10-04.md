# Real User Requests: state-contrast expansion and quality-controlled scaling

## 1. Outcome and scope

The development extension grows from 40 families / 82 scenarios to **64
families / 130 scenarios**. The addition is 24 manually specified contrast
families / 48 scenarios, with 144 new negative-control specifications (390
across the extension). Existing scenario IDs and source user protocols are
retained. Chinese stimuli remain Chinese; new developer documentation and
metadata are English.

This is benchmark construction, not agent evaluation. There are **zero new
SUT runs**, no provider experiment, no production browser submission, no clinical
computation, and no service restart. The extension remains development-only,
with independent semantic review pending and no formal ranking eligibility.
The original core task bank, results, splits and MANIFEST are not modified.

## 2. Why 82 was not an exhaustive coverage argument

The original set samples valuable failure mechanisms, but most families have
only two contexts. A family name such as "multiple targets" does not show that
every combination of absent targets, stale artifacts, failed independent
branches and delivered attachments has been tested. The distinction between
case state, authorization, execution, evidence delivery and user experience
must survive combinations, not just isolated happy paths.

The expansion selects cases in which state or request scope changes a valid
decision. It does not claim that 130 covers every possible request. The number
of written prompts is neither the number of independent patients nor evidence
of semantic understanding. `compiled/coverage.json` distinguishes design
presence, built component contracts, pending independent review and unperformed
live browser validation.

## 3. Added families and the specific decision each tests

Each row has two separately authored scenarios, each with explicit initial
state, user input, private machine contract, response rubric, three different
fault specifications and observation requirements.

| Family | Decision contrast | Why it matters in BrachyBot |
|---|---|---|
| RUR-41 | Already visible versus absent guide | Avoid toggle-off, regeneration or fictitious display success |
| RUR-42 | Stable v2 identity versus display of an explicitly stale guide | Do not confuse labels, versions, visibility and validity |
| RUR-43 | Hide seeds but retain needles versus empty version filter | Exclusions and empty target sets must not expand scope |
| RUR-44 | Strict measured-dose threshold versus missing measurement | Distinguish equality, actual zero and unknown OAR dose |
| RUR-45 | Verified true V100 condition versus unknown condition | Conditional commands require verified branch selection |
| RUR-46 | All outputs current versus report alone stale | Incremental updates must not redo current expensive work |
| RUR-47 | Three independent actions versus Viewer-unavailable partial success | A display failure must not suppress saved organ information |
| RUR-48 | Hypothetical hide versus actual hide request | Operation vocabulary alone is not authorization |
| RUR-49 | Harmless display typo versus 100-fold prescription-unit conflict | Recover harmless wording; do not guess clinical parameters |
| RUR-50 | Relative halving from zero versus deliberately unspecified magnitude | Zero is not missing; arbitrary numeric changes are not authorized |
| RUR-51 | Explicit percent versus normalized fractional opacity | Bind exact parameter values and preserve hidden state |
| RUR-52 | Current stable selection versus no selection | Pronouns need real grounding, not first-match targets |
| RUR-53 | Existing current PDF export versus stale report requiring clarification | Export is not rebuild and stale is not latest |
| RUR-54 | Temporary occluder removal for evidence versus persistent hide | Screenshot restoration must not undo an intentional UI command |
| RUR-55 | Independent guide/CTV attachment groups versus unavailable Viewer | Prevent overwrite, missing-delivery contradiction and invented location |
| RUR-56 | Stored score versus user-supplied simulation threshold | Engineering metrics and arithmetic do not grant clinical approval |
| RUR-57 | Already inactive Monitor versus an active owned run | Stop must not start, and local decoration is not a server ACK |
| RUR-58 | Chinese response with English logs versus English answer with Chinese UI | Output language and global interface language are separate scopes |
| RUR-59 | No-auto-capture preference versus one explicit override | Respect preferences without blocking a narrow current instruction |
| RUR-60 | Report-only versus guide-only regeneration | Independent artifact types must not cross-authorize each other |
| RUR-61 | Saved facts during image hydration versus no active plan | Resource loading must not block unrelated data or import old-case facts |
| RUR-62 | Imported low-trust instruction versus unrelated old-case measurement | Data is not authority; active provenance outranks historical prose |
| RUR-63 | One absent independent target versus two present hidden targets | Preserve partial success without creating missing clinical objects |
| RUR-64 | Exact saved-dose ratio versus unavailable clinical criteria | Answer measurable arithmetic; acknowledge unsupported compliance claims |

The complete question, effects, evidence and fault controls for each item are
in `compiled/review_cards/RUR-xx-yyy.json`. Those cards are evaluator-private,
not inputs to the tested agent. Answer truthfulness remains independently
reviewed; machine-checking state alone cannot establish a correct reply.

## 4. Infrastructure corrections made with the expansion

1. The compiled family count is derived from the catalog, not hard-coded to 40.
   Candidate hashing covers both original catalog and new expansion source;
   the runtime manifest hashes all Python sources and generated products.
2. Fixture materialization preserves authored guide version and geometry.
   Previously every guide was forced to v1 and a fixed position. Original guide
   defaults remain at `[0, 0, 20]` mm; an explicitly authored position is retained.
3. Setter authorization includes its exact value, not only operation and path.
   Original unbound setters are compiled from their unique authored equality
   goal; the protocol-fault display scenario has an explicit true value.
   Ambiguous setter definitions fail compilation rather than widening scope.
4. Boolean and numeric effect parameters are compared with strict typed
   semantics. `1` does not authorize Boolean `true`.
5. Added controls reject a wrong temporary parameter even if a later operation
   returns the final state to the correct value. Terminal equality must not
   erase a known unauthorized intermediate operation.
6. Added per-family tests require a difference in executable decision, facts or
   acceptable outcome, not merely wording. Tests also retain original IDs,
   verify exact setter binding, preserve versioned fixture geometry, and run
   positive checker witnesses, no-op failures and unauthorized attempts across
   the complete inventory.

These are component controls. They do not establish independent semantic gold
or implement every declared fault specification as a live product test.

## 5. Is a few hundred scenarios appropriate?

Yes, **a few hundred well-adjudicated scenarios are a sensible development and
experimental target**, but no count establishes completeness. Do not generate
hundreds of paraphrases and report them as independent mechanisms. Do not turn
an arbitrary Cartesian product into a clinically meaningful task bank.

A further expansion should use the following mechanism-by-state matrix:

| Dimension | Meaningful states to sample |
|---|---|
| User goal | Read, explain, show, modify, compare, undo, refresh, export, monitor, locate |
| Grounding | Explicit stable ID, current selection, prior referent, duplicate label, absent target |
| Speech act | Imperative, polite request, capability question, hypothetical, quote, conditional, correction |
| Scope | One target, subset/exclusion, multiple independent targets, dependent artifact DAG |
| Provenance | Current case, old case, current revision, stale artifact, unavailable or conflicting evidence |
| Lifecycle | Accepted, running, partial, failed, cancelled, uncertain ACK, late delivery, restored history |
| Interaction | Drag commit, preview only, several edits, keep/undo choice, case switch during capture |
| Evidence | Visible, occluded, hidden, absent, captured, decoded, delivered, restored, attachment collision |
| Constraints | Precise units, missing units, budget limits, preference override, unsupported capability |
| Communication | Chinese/English, mixed logs, concise format, complete tables, honest partial outcomes |

Use risk-weighted selection and constrained pairwise interaction coverage,
with hand-authored higher-order cases for known dangerous chains. For example,
"cancel generation, switch case, receive old completion, then ask to export"
tests a different mechanism from a single cancellation. A held drag, delayed
dose result and consumed undo token likewise require a versioned event protocol,
not three independent single-turn prompts.

Before an additional item is counted, require:

- A plausible real BrachyBot user goal and a concrete current-case fixture.
- A stated new failure mode or interaction absent from the existing inventory.
- A decision-sensitive contrast: a different permissible action, branch,
  dependency, result or evidence requirement, not just a different sentence.
- Stable identity, units, revisions and job states sufficient to avoid guessing.
- At least one successful response requirement; "no mutation" alone is not success.
- Explicit allowed effects and forbidden scope, with valid alternative paths.
- Three meaningful counterexamples and an actual observation strategy.
- Independent adjudication; ambiguous natural language allows valid clarification
  instead of forcing the author's preferred guess.
- A frozen isolated driver and honest readiness status. Missing drivers do not pass.
- Acceptable runtime cost; no hidden GPU work, repeated per-organ model planning,
  uncontrolled retry or arbitrary sleep disguised as a realistic interaction.

Monitor needs further higher-order driver-backed cases: multiple committed
edits before recomputation, stale dose arrival after a new drag, run ownership
after reconnect, undo races and idempotency, rapid stop/start, restored evidence
across case switching, and specific geometric evidence versus unsupported
dose-optimal movement claims. These remain a scaling backlog rather than
invented completed coverage in this release.

## 6. Scientific reporting and split discipline

Report **scenario families, independently adjudicated items, language variants,
fixture lineages and executions separately**. The 390 fault specifications are
not 390 passed trials. Development items are public; there is no sealed-set claim.
Family and shared-source connected components must not cross development and
held-out splits. Synthetic reuse requires clustered uncertainty estimates.

Separate safety breaches, goal completion, response accuracy, evidence delivery,
latency and resource cost. A missing judge/collector means insufficient evidence,
not pass. No-op component witnesses and unauthenticated SUT-authored observations
must never become formal agent results. Latency limits require preregistration
after an independent pilot, not limits selected from candidate outcomes.

All future formal tests must submit the request like a real user in the chat
input and observe the delivered result. Sandbox tools are useful for checker
development, not a substitute for the product path or clinical physics tests.

## 7. Validation record

Validation commands and final offline outcomes are recorded after construction.
The isolated validation directory is `/tmp/benchmark-rur-expansion-20261004`;
dependencies are installed only in `/tmp/benchmark-rur-validation-20261004`.
No production Python environment or running service is modified.

See the validation addendum below for final test counts and limitations.

### Final offline validation addendum

- Full benchmark infrastructure plus expanded extension:
  `python -m pytest tests extensions/real_user_requests_v1 -q --tb=short`
  **25,276 passed**, zero failures/skips, 170.13 seconds. Three warnings are
  SWIG-type deprecation warnings from environment-lock collection.
- The preceding incomplete staging run had 25,275 passed / 1 failed because
  source files referenced by the existing provenance test were not copied into
  the isolated repository. Supplying those source directories resolved that
  failure without modifying the test or its requirements.
- Read-only foundation comparison: **12,427 existing tracked benchmark files**
  outside this extension match the current checkout byte-for-byte.
- Candidate build check, runtime build check, default non-executing runner and
  standalone `build.py --check` all pass; counts are 64 families / 130 scenarios,
  `sut_runs=0`, `formal_ready=false`.
- Regression evidence: `/tmp/benchmark-rur-expansion-20261004/final-regression.xml`
  and `final-regression.log`. Component traces generated by pytest are not agent
  experiment results. No formal result was added to the repository.
- Publication uses baseline byte checks to reject concurrent edits, creates
  scoped backups, and writes only this extension and this new report. Existing
  unrelated dirty files and the public-release deployment remain untouched.
