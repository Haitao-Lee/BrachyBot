# Pre-release acceptance follow-up

Date: 2026-10-04 (Asia/Shanghai)

## 1. Outcome, scope and release decision

The four independent acceptance findings are substantially correct. The first two are real regressions introduced by the earlier remediation, not false positives: a read-only authorization contract was inconsistent, and an unchanged guide helper was contained in a changed hash-frozen module without renewed evidence. Both have been repaired. The original verification and listener wording has been corrected rather than defended as comprehensive evidence.

The source checkout is `/home/lht/snap/brachyplan/BrachyBot`, HEAD `0d1dbffe4de291b39737b87ea44961429b12748c`. Existing unrelated edits and the CT-cohort experiment/inventory files remain in place. The public deployment uses `/home/lht/snap/brachyplan/BrachyBot-release` and is not an overlay target. Its only follow-up mutation is removal of the same known leaked literal from `start-public.sh`; no public application code or runtime directory was copied.

**Decision: do not submit this as a release-ready deployment.** Passing source tests closes the identified contract and collection regressions, not provider revocation, runtime reload, TLS/Access/browser validation, real-model physical geometry or clinical use. The running LAN environment is still Torch 2.6.0, and the compromised credential remains in its process environment. No service restart, patient upload/planning, database/account change, commit or push was performed by this follow-up.

## 2. Acceptance finding disposition

| Finding | Verification | Repair and limit |
|---|---|---|
| 1. Case-memory read/save contradiction | Confirmed: the old name-only contract and the new negative test disagreed; runtime exceptions masked the discrepancy. | One action-aware classifier is shared by tool selection, grants, second-line authorization and execution. Actual calls pass parameters. Explicit read actions remain read-only; save, unknown or missing actions in actual calls fail closed. |
| 2. Guide dependency hash invalidation | Confirmed: the earlier `planning_pipeline.py` edits invalidated the frozen dependency and prevented test collection. | Audit the direct imported helper and run old/new paired guide generation before renewing the manifest. Preserve the guard, frozen historical reference and exact geometry/QA comparisons; bind the renewal evidence by SHA-256. |
| 3. Verification scope understated | Confirmed: 467 core outcomes + 297 UI outcomes = 764 selected tests, not the full top-level suite. | Correct both review documents; run all top-level `tests/`, including guide collection. Update the retired benchmark report import to exercise the supported CLI; do not weaken benchmark judgments. |
| 4. Active leaked credential invisible to gate | Confirmed, and broader than the two reported variables: the same fingerprint occurs in three LAN environment variables. | Add bounded redacted source/process scans, explicit roots/PIDs, exclusions and completeness reporting. Sanitize identified literal copies. Provider revocation and coordinated replacement/reload remain blocked pending operator action. |
| Obsolete listener statement | Confirmed: PIDs 596570/596669 were replaced before this follow-up. | Record observed PIDs, start times and loopback listeners; distinguish observation from who caused the restart and from whether later patches are loaded. |

## 3. Authorization contract: one definition, not competing exceptions

`agent_runtime/execution_authorization.py` owns `tool_call_is_mutating(tool, params)`. The request parser, LLM filtering and response execution use it consistently.

- `case_memory` read actions: `retrieve`, `search`, `list`, `statistics`, `recommend`.
- `surgical_guide` read actions: `status`, `analyze`.
- `case_memory.save` remains a mutation and does not acquire authority from the provider merely naming that tool.
- Unknown actions and missing actions in actual parameter dictionaries are mutations, not an accidental read-only bypass.
- The legacy **name-only capability query**, with `params=None`, remains compatible with the existing case-memory read-only contract. It is not a runtime execution call. Runtime call sites explicitly supply `params or {}` so an action-less actual call cannot use this compatibility exception.
- Read calls do not issue a reusable mutation grant for a later save call. Local explicitly authorized fast paths retain their existing scoped grants.

The contradictory new test now explicitly tests `params={"action":"save"}`. Additional controls cover normalization, read actions, unknown actions, read-to-save escalation and the actual response-execution filter. This is a shared action/authorization repair, not an intent keyword whitelist.

## 4. Guide dependency renewal: evidence before hashes

The earlier `planning_pipeline.py` changes were independently inspected: standard planning-target label handling, finite/nonnegative dose validation, prescription threshold consistency, grid validation and Dxcc edge handling. The direct helper imported by guide code, `_canonical_needle_points_from_seeds`, has identical before/after AST hashes.

| Bound asset | SHA-256 |
|---|---|
| Pre-remediation pipeline, from the restricted original backup | `6066ac1982e85f157ebc556a23afd7975df03949729454fb9db9bc643dcb349a` |
| Current pipeline | `3ee5ff0d97a63cc6f8c06c19177fc08eaa931152ee6c9c41a31f4bc37d4d9947` |
| Direct helper AST, both versions | `66973a3ede02a03fbfea7d560a1f96b88ca94071b84a666f579cc1f1c2602466` |
| Paired renewal evidence | `c63632aab2c727b4684ccc13dafb6eccb260bcfea6d55ad74b6c8a167e1bb974` |

`scripts/audit_guide_dependency_change.py` executes fresh-process old/new guide generation with the actual historical/current pipeline dependency, identical synthetic inputs, two scenarios and two alternating-order repeats. Scenarios include a one-needle 0.2-mm grid and a four-needle 0.5-mm grid with physical spacing/origin. All **four pairs** have identical selected paths, mesh vertices/faces, auxiliary hole geometry and QA hashes after removing timing-only fields. Individual runs were approximately 0.59–0.93 seconds.

These are bounded deterministic geometry/QA and latency-regression probes, **not** a real-patient performance study, proof of clinical guide manufacture or statistically powered speed comparison. No guide was published into a patient case.

Evidence: `docs/benchmarks/surgical_guide_dependency_renewal_2026-10-04.json`. `tests/guide_latency_reference.json` now binds the evidence and current dependency hashes. The guard checks the evidence hash, four paired matches, identical helper AST, baseline/current dependency binding, input/output equality and finite positive timings. A tampered evidence file fails the guard. A future direct-helper change cannot reuse this unchanged-helper renewal protocol.

## 5. Verification evidence and denominators

The scope below is the application's **top-level `tests/`**, not the separate benchmark project's approximately 24,000-test suite, the full CT cohort, an authenticated browser study or a penetration test. Tests and subtests are not added into one invented denominator.

| Run | Environment and result | Evidence |
|---|---|---|
| Original review, historical | 466 passed / 1 baseline failure + 297 passed; 764 selected outcomes only | Logs named in the original review; insufficient to assert absence of all regressions |
| First actual-checkout follow-up | Product Python 3.12 / Torch 2.6: 2,166 passed, 8 skipped, 17 warnings, 4 subtests passed, 50.28 s | `/tmp/brachybot-acceptance-full-actual-20261004.log` |
| Offline rebuilt candidate | Hash-locked Python 3.12 / Torch 2.10: 2,167 passed, 8 skipped, 17 warnings, 4 subtests passed, 45.38 s | `/home/lht/.local/share/brachybot-pre-release-20261004/full-locked-tests.log` |

The additional candidate-suite test checks credential streaming across a read boundary; this explains the 2,166/2,167 difference, not a lost test or a changed success criterion. Final post-delivery verification is recorded in section 10. Skips and warnings remain visible; a passing suite does not close every untested deployment or clinical condition.

The former baseline failure imported removed `benchmarks.generate_final_report`. The repaired test invokes the supported `benchmarks/brachybench/tools/score_report.py` from an unrelated working directory and checks a real temporary fixture's summary. It is neither skipped nor replaced with a fake module. Benchmark tasks/oracles and their scoring rules were not modified.

## 6. Credential containment and scan boundaries

`scripts/compromised_credentials.json` stores only the incident SHA-256 fingerprint and `revocation_status="unverified"`. Raw key values, token prefixes and matching source text are never emitted by `credential_audit.py` or `pre_release_security_check.py`.

### 6.1 Known literal copies sanitized

The identified literal was removed from:

1. `/tmp/brachybot-review-backup-20261004-GQZavM/start_server.sh`.
2. `/tmp/brachybot-review-backup-20261004-GQZavM/docs/CODE_REVIEW.md`.
3. `/home/lht/snap/brachyplan/BrachyBot-release/start-public.sh`.

The public startup retains its existing user-owned configuration fallback rather than receiving a fabricated new credential. No service restart was triggered. The redaction receipt is `/tmp/brachybot-review-backup-20261004-GQZavM/credential-redaction-2026-10-04.json` (0600); the enclosing original backup remains 0700. Raw copies were deliberately not preserved in a second backup, so these credential literals cannot be recovered from the sanitized files. The original 61-file backup manifest consequently has two intentionally changed entries; the receipt preserves before/after hashes, not the secret.

### 6.2 Source/process scan coverage

The pre-final-delivery bounded scan examined the LAN checkout, independent public checkout and restricted original backup: **38,812 UTF-8 text files, 1,046,765,543 bytes**, with the configured in-scope scan complete; evidence is `/tmp/brachybot-acceptance-credential-gates-final-complete-20261004.json`. No registered compromised literal was found in those scanned files after sanitation. It still found **16 other credential-shaped literals**, largely in old worktrees and vendor examples/tests. Those are not automatically declared valid credentials or silently whitelisted; synthetic placeholders versus live credentials require review. Section 10 records the later delivered-code scan separately; counts are timestamped observations, not permanent repository totals.

The same compromised fingerprint remains in PID 916502 under `ANTHROPIC_API_KEY`, `BRACHYBOT_OPENCODE_GO_TOKEN` and `ANTHROPIC_AUTH_TOKEN`. Environment inspection does not prove what credentials a process loaded into Python objects or whether the provider still accepts them; it is sufficient to prevent a false clean-environment claim. The public PID's selected environment contained no registered fingerprint, which is not a whole-process-memory clearance.

The scanner provides:

- Explicit additional checkout/backup/log roots and selected same-user PIDs; otherwise same-user processes with the checkout as cwd are discovered.
- Streaming reads with boundary overlap, no raw-match output, and rejection of unreadable roots/files, oversized in-scope files, changed files or exceeded budgets.
- Per-file 512 MiB, total 2 GiB and 120,000-file limits, all stated in code; incomplete scans block rather than pass silently.
- Reported exclusions for Git objects/history, compressed archives, symlinks, models, patient/binary artifacts, runtime directories and caches.
- Separate installed-interpreter Torch checks and process-environment checks. A new interpreter's version does not certify an old service process.

A bounded scan is **not** confirmation that all historical logs, archive copies, external stores or process heap objects are clean. Additional selected review/acceptance text logs were checked without finding the registered literal; this is not a machine-wide DLP audit. Provider revocation must be confirmed by the authorized account owner. A local JSON status change is not independent provider evidence.

Example operator check (reconfirm PIDs first; never paste a key):

```bash
cd /home/lht/snap/brachyplan/BrachyBot
umask 077
/home/lht/.conda/envs/brachytherapy/bin/python scripts/pre_release_security_check.py \
  --scan-root /home/lht/snap/brachyplan/BrachyBot-release \
  --scan-root /tmp/brachybot-review-backup-20261004-GQZavM \
  --pid 916502 --pid 917541 > /tmp/brachybot-release-gates.json
```

Exit 1 currently means the gate correctly blocks. Output reports paths/variable names and reasons, never values. Even exit 0 remains `manual_review_required`, not authorization to publish. Restrict the saved report's permissions because operational paths are sensitive metadata.

## 7. Isolated PyTorch compatibility candidate, not a production migration

PyTorch's [official CVE-2026-24747 advisory](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p) identifies affected versions through 2.9.1 and a patched 2.10.0, including `weights_only=True` attacks. Therefore, retaining hardened loads under Torch 2.6 alone does not close that release gate.

An isolated candidate and a second offline rebuilt environment were created under `/home/lht/.local/share/brachybot-pre-release-20261004`. The active conda/public environments were not upgraded. The candidate includes:

| Component | Candidate version |
|---|---|
| Torch / torchvision | 2.10.0+cu126 / 0.25.0+cu126 |
| MONAI | 1.6.1 |
| nnU-Net v2 / TotalSegmentator | 2.7.0 / 2.13.0 |
| SimpleITK / SciPy | 2.5.0 / 1.15.3 |
| pydicom / dicom2nifti | 2.4.5 / 2.6.0 |
| transformers | 4.46.3, retaining the existing VISTA compatibility requirement |

The existing MONAI 1.5 constraint rejects Torch 2.10. The newer dicom2nifti release conflicts with the repository's pydicom<3 contract, so the candidate uses a compatible 2.6.0 version. Both environments pass `pip check`; the second was installed **offline with `--require-hashes`**, not merely recorded after installing an unresolved stack.

Assets in `docs/releases/`:

- `requirements.compatibility-candidate-20261004.lock`: all 141 installed distributions pinned to observed wheel hashes, for this Linux x86_64 / Python 3.12 candidate.
- `wheels.compatibility-candidate-20261004.json`: wheel inventory and hashes.
- `models.observed-20261004.json`: hashes of 38 local model artifacts. These freeze observed bytes, **not** trusted clinical provenance or all external model roots.
- `compatibility-probe-20261004.json` and `torch-cpu-parity-20261004.json`: bounded probe and old/new CPU comparison.

`scripts/freeze_release_assets.py` and `scripts/probe_release_stack.py` make the observations repeatable. The real deployed DoseUNet checkpoint loads strictly, with no unsafe unpickle fallback; SHA-256 is `d73d19f22c846ee989786eabd9336fba80b8c9658881a6e878aca846861b5681`.

Probe results:

- MONAI, nnU-Net predictor, TotalSegmentator API and VoCo-base imports succeed.
- A MONAI/SwinUNETR API/shape probe succeeds; it is not actual VoCo checkpoint inference.
- Fixed NumPy-generated synthetic input through the real DoseUNet checkpoint gives finite CPU output; old Torch 2.6 CPU versus new Torch 2.10 CPU matches exactly for this input.
- Bounded CUDA inference acquires the product device lease and cross-process GPU lock, then releases both. FP32 CPU/CUDA parity passes; maximum absolute error is approximately `5.44e-7`.
- An anisotropic, oblique SimpleITK index/physical-coordinate round trip has zero measured index error for the synthetic probe.

**Important precision disclosure:** the first strict CPU/CUDA comparison under default accelerated precision did not meet the probe tolerance. The validated comparison explicitly disables TF32 in the detached probe only. Production precision policy was not changed or qualified. A real release must separately qualify its intended TF32/mixed-precision behavior; this evidence cannot be presented as all-precision equivalence.

No real-case nnU-Net/TotalSegmentator/VoCo inference or full CNN-dose clinical qualification was run. The deprecated prostate/aorta VoCo real-checkpoint physical back-mapping remains **NOT_VALIDATED**. An API import or synthetic SimpleITK test cannot substitute for that measurement. Local/external checkpoint trust, approved dose calibration and independent dose-physics validation remain separate gates.

The candidate's existing offline-rebuilt interpreter is `/home/lht/.local/share/brachybot-pre-release-20261004/locked-venv/bin/python`. To reproduce installation in a **new** operator-chosen Python 3.12 virtual environment, use the retained wheel directory and the committed candidate lock:

```bash
# Do not point this command at either active service environment.
/path/to/new/python3.12-venv/bin/python -m pip install \
  --no-index \
  --find-links /home/lht/.local/share/brachybot-pre-release-20261004/wheels \
  --require-hashes \
  -r /home/lht/snap/brachyplan/BrachyBot/docs/releases/requirements.compatibility-candidate-20261004.lock
/path/to/new/python3.12-venv/bin/python -m pip check
```

This candidate directory currently occupies approximately **20 GiB** for two environments, wheel retention and evidence. It is not a patient-result store; no CT-cohort results were placed on this disk. This lock is platform/interpreter-specific, and local wheel retention is not a durable release archive. Do not treat this installation command as authority to switch the running deployment.

## 8. Runtime observations and operation boundaries

Observed on this follow-up, both processes retain their current independent cwd/runtime:

| Deployment | PID | Start time (Asia/Shanghai) | Listener |
|---|---|---|---|
| LAN/debug | 916502 | 2026-10-04 19:07:56 | 127.0.0.1:8080 |
| Independent public checkout | 917541 | 2026-10-04 19:09:45 | 127.0.0.1:18082 |

The old PIDs are gone. This demonstrates a prior replacement; it does not attribute the restart to this agent or another operator. This follow-up restarted neither service. Source delivery after those start times is not proof that the new Python authorization/scanner code is active in the already-running process.

Credential revocation can immediately disrupt provider calls, and a controlled replacement/reload requires a new credential from a restricted file and coordination with active tasks. No blank-key restart or unrequested teardown was used to manufacture a clean-environment screenshot. Do not paste the replacement key into chat, shell logs or this report.

## 9. Remaining checklist: explicit, not hidden by green tests

| Priority / acceptance item | Current status and required closure |
|---|---|
| Must 1: action-aware case-memory contract | Corrected; full-suite and negative-control evidence. |
| Must 2: guide paired dependency renewal | Corrected for the audited change; four paired probes and evidence-bound guard. |
| Must 3: provider revocation and copies | Known source copies sanitized, scans expanded; provider revocation, live-process replacement and excluded historical stores **remain blocked**. |
| Must 4: patched Torch stack | Isolated hash-locked candidate rebuilt and bounded checks passed; active environment migration and real-model/precision/provenance qualification **remain blocked**. |
| Must 5: full top-level tests | Run including guide collection; no claim about unrun browser, physics or nested benchmark suites. |
| 6: strict CSP | Existing compatible CSP is not a strict nonce/external-handler policy; migration and real-browser validation remain open. |
| 7: actual public deployment | Real TLS/Access origin, cookie Secure, closed enrollment/debug defaults, throttling and cross-origin negative tests remain deployment work. Public checkout was not silently overwritten. |
| 8: browser concurrency/lifecycle | Duplicate-tab edit identity, late logout writes, archived callbacks, report/Monitor interaction need authenticated real-browser tests; unit coverage is insufficient. |
| 9: crash/resource/quota transactions | SIGKILL/power-loss consistency and process/filesystem budgets remain open. Direct report/DICOM tool outputs remain case-scoped, not WorkspaceStore quota transactions. |
| 10: deprecated VoCo geometry | Do not clinically enable; actual checkpoint/grid inverse mapping not validated. |
| 11: architectural/retention work | Indexed/streamed snapshot recovery, safe per-case lock lifecycle, all fixed-host search policies and PHI/audit retention remain open; arbitrary eviction would risk state races. |
| 12: report evidence/runtime corrections | Corrected at the top of `CODE_REVIEW.md` and in the original detailed report; bounded historical evidence remains labeled historical. |

Items 6–11 are not declared repaired by this follow-up. They require separate bounded implementation/validation designs; silently replacing them with an optimistic status would recreate the acceptance problem.

## 10. Delivery and final validation record

Changes are delivered only to selected LAN source/evidence/test files after baseline/HEAD/archive/payload checks. A selected target with an unrelated concurrent hash aborts the overlay. Replaced files have private 0700 recovery backups; the first follow-up backup is `/tmp/brachybot-acceptance-backup-20261004-20exlxrk`. Hash manifests describe the exact selected files, not the entire dirty repository.

The final selected overlay contains **24 files**. Its second delivery verified every post-copy hash; 14 files needed writing at that stage and the rest already matched the earlier follow-up. Recovery backup: `/tmp/brachybot-acceptance-backup-20261004-oj_rc3y6` (0700). Final documentation-only sealing is also hash-checked and does not change the tested Python, JSON evidence or lock assets.

**Observed final actual-checkout results, after the 24-file delivery:**

| Interpreter | Final top-level suite | Log |
|---|---|---|
| Active product's Python 3.12, Torch 2.6 | **2,167 passed, 8 skipped, 17 warnings, 4 subtests passed; 0 failed, 0 collection errors; 55.53 s** | `/tmp/brachybot-acceptance-full-actual-final-20261004.log` |
| Offline rebuilt Python 3.12, Torch 2.10 candidate | **2,167 passed, 8 skipped, 17 warnings, 4 subtests passed; 0 failed, 0 collection errors; 55.23 s** | `/home/lht/.local/share/brachybot-pre-release-20261004/full-locked-tests-final.log` |

The eight skips are explicit: one loopback public-entry test requires the missing `waitress` package; one real-proxy test requires `NGINX_TEST_BINARY`; six browser-bridge VM tests require `node`, which is absent from the remote test PATH. These are **unvalidated paths**, not successful tests. Existing warnings concern SimpleITK wrapper types and deprecated naive `datetime.utcnow()` calls; no warning was hidden by a blanket filter. Guide-test collection is included and succeeds.

Selected Python compilation, the evidence-bound guide guard, `git diff --check`, public startup shell syntax and candidate `pip check` pass. No JavaScript file was changed in this follow-up; the earlier original-delivery JavaScript checks remain historical evidence, not a fresh browser run.

The delivered scanner's latest bounded scan checked **38,820 text files / 1,046,853,986 bytes**, with in-scope completeness true and 1,351 explicitly recorded exclusions. It found **0 registered compromised source literals, 16 other credential-shaped source literals and 3 compromised LAN environment variables**. The gate correctly returned `blocked`, also recording active-interpreter Torch and unverified provider revocation. Evidence is `/tmp/brachybot-acceptance-credential-gates-delivered-20261004.json` (0600). This scan preceded final documentation-only sealing; it does not claim global historical-store clearance.

The same listener PIDs/start times were reconfirmed. No commit/push/restart was made. Green source regression closes the examined regressions; the unresolved release gates in section 9 remain unresolved.
