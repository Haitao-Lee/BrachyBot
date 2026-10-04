# Pre-release code review: verification and remediation

Date: 2026-10-04 (Asia/Shanghai)

**Acceptance correction:** This document records the original 61-file delivery. Its bounded verification missed an authorization-contract regression and a surgical-guide test collection error. The latest corrections, full-suite results, isolated Torch compatibility work, credential cleanup and runtime observations are in [PRE_RELEASE_ACCEPTANCE_FOLLOWUP_2026-10-04.md](PRE_RELEASE_ACCEPTANCE_FOLLOWUP_2026-10-04.md). Historical claims below are not a current release approval.

## 1. Outcome and scope

This is an independent verification of the newest findings in `docs/CODE_REVIEW.md`, followed by risk-focused review of the application, agent runtime, tools, scientific calculations, browser code, persistence and deployment entry points. The baseline checkout was `/home/lht/snap/brachyplan/BrachyBot`, HEAD `0d1dbffe4de291b39737b87ea44961429b12748c`. Its tracked source/script inventory contained 622 Python, JavaScript, HTML and shell paths. Inventory and cross-module searches are not a claim that every line, dependency or attack surface has been proved safe.

Existing edits to `CODE_REVIEW.md`, the CT-cohort documents, inventory and `experiments/` were preserved. The history of `CODE_REVIEW.md` was retained, apart from mechanical redaction of provider-credential literals. The initial review-document SHA-256 was `9188fdb7f68cac21b484d54475e5772a6fe85724678a2e9a24d7717126eb9dae`.

Patches were first tested in `/tmp/brachybot-review-stage-20261004`, without patient data, production runtime directories, GPU planning or service restart. Only checked task-related deltas are intended for the actual checkout. The separate `/home/lht/snap/brachyplan/BrachyBot-release` deployment is outside the mutation scope.

**This review does not approve a public launch or clinical use.** Several findings are corrected; others are narrowed, partially mitigated or explicitly blocked pending deployment/model validation. Source changes are not proof that an already-running Python process has loaded them.

Status vocabulary:

- **Corrected:** the identified behavior was changed and relevant tests passed.
- **Partial:** a concrete mitigation exists, but the broader claim is not closed.
- **Design/narrowed:** the original claim overstates a legitimate design or an existing defense; the narrower risk is recorded.
- **Release gate:** cannot be honestly resolved by a small code patch or by changing a requirement without validating the real environment.

## 2. Verification matrix for the newest review

Paths are relative to the repository. Findings with a shared root cause are deliberately repaired through common boundaries rather than per-request keyword exceptions.

| ID | Independent assessment | Remediation and remaining boundary | Status |
|---|---|---|---|
| P0-1 | A provider credential was present in an operational script and repeated in the review. Insecure startup defaults were real. The claim that `TRUST_NETWORK` disables account authentication was overstated. | Remove literal credentials; use an explicitly supplied environment credential or the existing user-owned auth file. Default startup to loopback, network trust off and insecure-remote override off. Existing account/CSRF enforcement remains. Revoke/rotate the exposed credential and check historical copies. | Partial / release gate |
| P0-2 | Tool parameters and several default output locations could escape an authenticated case despite route-level ownership checks. | Add `utils/tool_security.py`: server-owned case scope, real-path containment including symlinks, nested/list path validation and checks before memory mutation and after path recovery. Scope case-memory, report and DICOM output defaults. Keep trusted standalone CLI behavior separate. Filesystem namespace containment is not an OS sandbox or a quota transaction. | Corrected for examined Web tool paths; partial broader isolation |
| P0-3 | Provider-selected grants were not the sole existing authorization gate, but blanket direct-execution exemption and missing mutating-tool entries were real gaps. | Keep exact local fast-path grants; apply the second-line semantic gate to other provider mutations. Add missing mutation entries; unknown declared mutations fail closed. Disable developer execution tools in Web availability, selection and execution, including direct fallback code-writing/self-evolution handlers. | Corrected for active examined paths |
| P0-4 | DICOM metadata reached HTML without escaping. Security headers were absent. | Escape metadata keys, values and modality; escape report age and inline run identifiers. Markdown falls back to escaped text if its sanitizer is missing. Add compatible response headers/CSP. This CSP does not restrict all script execution; a strict nonce/event-handler migration remains. | Corrected sinks; partial CSP |
| P1-1 | `web_access` had a separate unsafe fetch implementation; external search material was presented as mandatory instructions. | Delegate all Web-access fetch variants to WebFetch. Pin the checked public DNS address to the socket; retain original Host, TLS SNI and certificate hostname; reject private answers, URL credentials and implicit redirects. Bound and close fetch responses. Mark search material as untrusted evidence, never authorization. | Corrected for WebFetch/WebAccess; fixed-host search transports still need inventory |
| P1-2 | Multi-label CTV evaluation included pancreatic vascular labels through `> 0`. | Evaluate the standardized planning target label `1`; do not relabel source-specific GTVp/GTVn uploads as vessels. Reject non-finite/negative dose before publishing metrics. | Corrected |
| P1-3 | Failed task-owner resolution led to unscoped reads. The same defect existed in SSE. | Task list, status and stream all require a server-derived authenticated case owner; a failure returns 403 before reading the task store. SSE captures the owner before leaving the request context. | Corrected |
| P1-4 | Legacy screenshot serving used a shared directory. | Serve only artifacts owned by the authenticated case; never fall back to repository-wide screenshots. | Corrected |
| P1-5 | Self-enrollment and debug identity were enabled by default; network-trust mode exempted auth requests from rate limiting. | Default enrollment/debug-account features off; explicit debug configuration remains possible outside public mode. Auth requests retain a bounded rate budget even on a trusted LAN. Tests explicitly opt into enrollment and clear test-only budgets. Public TLS/Access/cookie configuration still requires deployment validation. | Corrected defaults; partial deployment |
| P1-6 | `get_device()` incremented reservation counters without a matching lease lifecycle. | Separate selection from reservation; explicit `acquire()` leases retain their original counter/release contract. | Corrected |
| P1-7 | Snapshot retention was unbounded. Startup scans all active cases to repair stale running state. | Bound the snapshot LRU by both count (8) and serialized bytes (64 MiB). Keep restart-recovery semantics; do not blindly skip the scan, which repairs real planning/chat contradictions. Startup scan latency and decoded-object memory amplification still require measurement. | Partial |
| P1-8 | A negative retention setting could cause immediate deletion. | Clamp to at least one day; malformed settings use the seven-day default. No patient trash was purged by this review. | Corrected |
| P1-9 | Segmentation/planning arbitrary paths share P0-2's root cause. | Use the same server-owned tool path boundary, including recovered paths and path lists. | Corrected examined paths |
| P2-1 | The zero centerline deviation is a nominal construction result, not independently measured mesh accuracy. Replacing it with a nominal direction comparison would still not validate the final mesh. | Preserve compatibility fields and add `nominal_axis_by_construction_not_mesh_measurement` plus an explicitly absent mesh measurement. Printing/clinical mesh QA remains required. | Design/narrowed; partial QA |
| P2-2 | A loaded OAR with a mismatched dose grid could disappear silently. | Return an input-resolution error instead of pretending no OAR was supplied. Absence of OAR is not a safety approval. | Corrected |
| P2-3 | Coverage evaluation swallowed grid errors as 0%; its threshold differed from DVH. | Raise a distinct evaluation failure on empty/mismatched/non-finite inputs and use `>=` at the prescription threshold. | Corrected |
| P2-4 | The lease guard and route modules resolved different cases from the same request. | Add `web/request_identity.py` and use it in server, session, data, planning, guide and viewer resolvers. Reject conflicting explicit argument/header/body/query identities; the navigation cookie is a fallback only. Ownership is always checked. | Corrected |
| P2-5 | Logout left cached patient data and remembered credentials. | Stop new SessionCache gets/puts during logout; clear IndexedDB and product-prefixed storage, then reload. A hostile already-running same-origin script is not defeated by cache deletion. | Corrected normal logout; partial hostile-browser isolation |
| P2-6 | A localStorage editor token was shared across tabs. | Keep the identity in sessionStorage, stable across reloads but not shared by ordinary independent tabs. Duplicating a tab can clone sessionStorage; no untested BroadcastChannel claim is made. | Partial; duplicate-tab concurrency gate |
| P2-7 | Three VoCo paths used predictable PID-based temporary files; two also did not clean them up. | Use exclusive random temporary files and `finally` cleanup in shared VoCo, legacy prostate and legacy aorta implementations. | Corrected |
| P2-8 | Main CT/restore decodes had no declared-dimension budget. Detached image headers can additionally reference arbitrary raw files. | Validate dimensions/components/series counts before allocation; use bounded header inspection. Cover main CT loading, workspace restore, uploaded-mask CT fallback, shared label alignment and examined route rereads. Web tool path validation inspects existing medical-image headers before legacy tools decode them. Reject escaping detached sidecars and unvalidated detached multifile headers. A per-image budget is not a total-process memory limit. | Corrected examined entry points; partial global resource isolation |
| P2-9 | RTDOSE pixel decoding and RTSTRUCT contour payloads were unbounded. | Reject excessive declared voxel/contour counts and non-finite contours before materializing pixels or processing contours. | Corrected |
| P2-10 | Unsafe pickle loads were present, but switching only `weights_only` does not secure the installed Torch stack. | Harden DoseUNet and SAT3D loading; do not fall back to unsafe unpickling. Raise the declared Torch floor to 2.10.0 and add a read-only release gate. Existing trusted VoCo checkpoint formats still need validated conversion/provenance. The running environment remains Torch 2.6.0+cu124. | Partial / release gate |
| P2-11 | Requirements are not a validated hash-locked release environment. | Do not fabricate a lock from the currently vulnerable environment or install into the active GPU environment. Build and validate an isolated lock, including inference plugins/model formats, before release. | Release gate |
| P2-12 | Credentialed CORS patterns accepted prefixes. | Anchor built-in LAN/loopback patterns; explicit deployment origins remain configuration-owned. | Corrected |
| P2-13 | Shutdown did not flush cached agents or wait for children. | Flush cached complete agents outside the cache lock, skip hydrating shells, and wait for terminated children. In-flight writes, hung workers and SIGKILL/power-loss races remain separate crash-consistency risks. | Partial |
| P2-14 | Atomic replacement did not persist the directory entry. | Fsync parent directories after snapshot/array/upload/artifact replacement, using the existing helper. This is not a guarantee against all filesystem/device failure. | Corrected examined writes |
| P3-1 | An unauthenticated health route exposed process identifiers. | Return constant health information; process inspection remains an operator-only check. | Corrected |
| P3-2 | Display tokens could resolve outside their declared root. | Real-path/common-path containment; malformed display paths return a controlled error. | Corrected |
| P3-3 | `.`/`..` passed filename sanitization. | Reject both special names. | Corrected |
| P3-4 | Raw model/provider failure content could enter logs. | Log content length rather than raw output at the examined LLM sinks. Remaining patient-path/exception logs and retention/access controls require a full logging policy; no repository-wide PHI scrubbing is claimed. | Partial |
| P3-5 | Experience success depended on English substrings, so fluent Chinese failures could train a successful execution experience. | Use completed tool-step status and structured failure fields; text-only outcomes remain unverified. This records execution evidence, not clinical validity or proof that every user requirement was met. | Corrected heuristic |
| P3-6 | JSON inside HTML event attributes could break quoting. | HTML-escape the serialized identifier before embedding it; migrate inline events under the future strict CSP. | Corrected sink; partial architectural CSP |
| P3-7 | Patient age was inserted unescaped in report HTML. | Escape it. | Corrected |
| P3-8 | API credentials could arrive through URLs and persist in localStorage. | Strip/ignore URL credentials; remove persistent localStorage fallback and retain only explicit session credentials. Compatibility still exposes a key to same-origin JavaScript; a closure is not protection against a fully compromised origin. | Partial |
| P3-9 | Precheck and request performed separate DNS lookups. | Pin the validated numeric address in the shared transport, with original-host TLS validation. The first lookup remains an input check; no unchecked DNS re-resolution is used for the actual connection. | Corrected for pinned transports |
| P3-10 | Weather city text was not query-encoded. | Encode the city parameter. | Corrected |
| P3-11 | UI-bridge identity failure fell back to a shared `web` bucket. | Require an owned case or return a controlled error. Correct the outdated comment that said all explicit payload identities were ignored. | Corrected |
| P3-12 | Full-volume Dxcc clamped to `n-1` rather than `n`. | Correct the clamp. | Corrected |
| P3-13 | Equal/reversed distance bounds could divide by zero. | Reject invalid/non-finite windows in geometry and planning configuration. | Corrected |
| P3-14 | Legacy missing-calibration fallback is real; treating every model as interchangeable is not valid. | Preserve legacy calibration compatibility; validate finite positive scales/prescriptions. Never substitute the other model's 190.8 Gy scale for a 120 Gy legacy model without provenance. Clinical-release inputs must have an approved model-specific calibration. | Design/narrowed / release gate |

## 3. Additional findings and common-boundary fixes

1. **Task SSE fail-open:** corrected alongside task list/status, with negative controls that fail if any task-store read occurs without an owner.
2. **Detached medical-image sidecars:** `.mhd`/`.nhdr` headers can name a cross-case raw file even when the header itself is owned. Header inspection now checks the referenced path before decoding; detached multifile variants require an explicit validated importer. Embedded/local data and an ordinary same-directory sidecar remain supported.
3. **Path-list bypass:** scalar checks alone miss `dicom_files`, `file_paths` and similar list fields. The common guard now checks string entries recursively rather than trusting a list container.
4. **Fallback developer execution:** disabling registered tools was insufficient while direct Web chat handlers could call code generation/evolution. Those handlers now reject Web-scoped execution before accessing developer machinery. Trusted standalone development remains separate and is not a sandbox.
5. **Stale context polling:** capture the case and request sequence, check HTTP success, and discard obsolete context-usage responses. An older request cannot overwrite the newly selected case's context display.
6. **Custom quota migration:** startup previously raised valid lower account quotas to the global default. Only missing/nonpositive quota values are initialized now; user-specific positive quotas are preserved.
7. **RAG retention:** cap retained retrievals by entry count and per-entry bytes, protect cache operations with a lock, clamp top-k and return copies. This does not solve knowledge-base invalidation or clinical source quality.
8. **Legacy VoCo physical geometry:** the deprecated standalone prostate/aorta files have questionable inverse-transform assumptions (invented zero origin or copied original metadata onto transformed arrays). The CTV dispatcher already documents removal of the old prostate adapter and uses other active implementations. Their temp-file vulnerability was repaired, but their inference geometry is **not** declared validated and they must not be re-enabled for clinical use without physical-grid round-trip tests using the real checkpoint. No unsupported model rewrite was made.

## 4. Preserved semantics and compatibility

- No new intent keyword whitelist was introduced. Authorization and file/network containment are separate from model interpretation.
- Existing local fast paths keep their exact locally issued tool grants; the blanket exemption for unrelated provider tools is removed.
- Read-only surgical-guide status/analyze and case-memory list/search remain read-only exceptions, not mutation grants.
- Ad-hoc `case_memory.save` and raw DICOM exporter mutations do not gain authorization simply from a provider tool call. An explicit supported goal/authorization contract is required before enabling them through chat; existing authenticated workspace/export UI routes remain available.
- UI-only visibility changes, Monitor restoration tokens, guide truncation policy, staged-upload-to-CTV classification, source-specific labels and explicit GPU lease semantics are preserved.
- Cookie fallback deliberately supports an asynchronous callback bound to the previous owned case after navigation; conflicting explicit identities never silently choose one case.
- Developer tools being unavailable in a Web case is an intentional security change. This does not mean CLI developer tools are safely sandboxed.
- Frontend asset versions are incremented for changed JavaScript. Existing servers need a controlled restart to load Python changes, and browsers need a refresh to load versioned assets.

## 5. Verification evidence

The original delivery did not run the full top-level suite, GPU planning, patient uploads, real clinical calculations or public deployment. Its evidence was bounded targeted regression and negative controls. The acceptance follow-up subsequently ran the full top-level suite and bounded synthetic GPU compatibility checks, without patient planning or public deployment.

Baseline evidence:

- Core pre-change regression: 263 passed (`/tmp/brachybot-review-baseline-20261004.log`).
- Expanded pre-change regression: 131 passed, 1 failed (`/tmp/brachybot-review-expanded-baseline-20261004.log`).
- The pre-existing failure was `test_review_round6_regressions.py::test_benchmark_report_generator_resolves_repository_root`: it imported the absent `benchmarks.generate_final_report`. The follow-up now tests the supported `benchmarks/brachybench/tools/score_report.py` CLI from an unrelated working directory. No benchmark scoring criteria were changed.

Post-change evidence: **466 passed, 1 pre-existing failed** in `/tmp/brachybot-review-regression-final-20261004.log`; **297 passed** in `/tmp/brachybot-review-ui-regression-20261004.log`. The new controls separately report **42 passed** in `/tmp/brachybot-review-negative-controls-20261004.log`, already included in the 466 count. Three Node VM harnesses passed in `/tmp/brachybot-review-node-regression-20261004.log`; these scripts require source-path arguments and are not standalone `node --test` files. New controls are in `tests/test_pre_release_review_20261004.py` and include real small-volume header inspection, invalid dose grids, same-case/symlink/list boundaries, default-closed account behavior, request-case conflicts, task SSE denial, pinned-IP/original-host TLS behavior, release CVE gating, decoder budgets and structured execution experience.

Existing enrollment tests explicitly opt into enrollment rather than depending on an insecure product default. Web-fetch mocks target the actual transport seam. Editor-identity tests target tab-scoped storage. These are contract updates, not relaxed security or clinical assertions.

**Scope correction:** The 467 core outcomes plus 297 UI outcomes are 764 selected tests, not the full suite. The independent acceptance run found the case-memory contract failure and a guide-latency collection error, in addition to the retired report-import failure. Therefore, the original evidence did not establish absence of newly introduced regressions. See the follow-up for repaired contracts and exact full-suite logs; do not add the 42 controls a second time.

Python compilation, five changed JavaScript files' `node --check`, shell syntax and whitespace/diff checks accompany regression results. The deployed DoseUNet checkpoint was inspected with the hardened CPU loading mode successfully; this is checkpoint-format compatibility evidence, not a full GPU inference or dose-physics validation.

## 6. Mandatory release gates

### 6.1 Credentials

The exposed provider credential must be revoked/rotated at its provider. Removing a literal does not revoke it or establish that nobody obtained it. The follow-up sanitized the two identified restricted-backup copies and the public startup-script copy, and expanded redacted source/process scans. The live LAN process still contains the registered compromised fingerprint in three environment variables; provider revocation is unverified. Git history, compressed archives and arbitrary historical stores were not exhaustively scanned. Never print credential values in audit evidence.

### 6.2 PyTorch and model provenance

The installed environment was verified as Torch `2.6.0+cu124`. PyTorch's [official CVE-2026-24747 advisory](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p) states that affected versions extend through 2.9.1 and that 2.10.0 is patched, including attacks against `weights_only=True`. Consequently, the old statement that upgrading to 2.6 or merely using `weights_only=True` closes checkpoint RCE is no longer sufficient.

Use an isolated release environment; validate CUDA/MONAI/nnU-Net/TotalSegmentator/VoCo and DoseUNet compatibility, freeze a hash-locked package set, and freeze trusted model hashes. Convert unsupported trusted checkpoint formats with an audited offline process; never add unsafe fallback loading for user files. No active GPU-environment upgrade was performed. The original review installed no packages; the acceptance follow-up built and offline-rebuilt a separate Torch 2.10.0+cu126 compatibility candidate, with bounded checks and explicitly incomplete real-model/clinical qualification.

Read-only gate:

```bash
cd /home/lht/snap/brachyplan/BrachyBot
/home/lht/.conda/envs/brachytherapy/bin/python scripts/pre_release_security_check.py
```

Exit status 1 means a blocking condition was found. Exit status 0 still says `manual_review_required`; it is not a launch approval or penetration-test result. Environment overrides must be checked in the actual launch environment, not inferred from a separate SSH shell.

### 6.3 Deployment, browser and process isolation

Validate real TLS/Access origin, cookie security, enrollment policy, auth throttling, model/runtime isolation and cross-origin negative controls in the independent public checkout. Migrate inline handlers to a strict script CSP if that protection is claimed. Test duplicate-tab lease identity, late logout writes, archived-case callbacks and report/Monitor interactions in a real browser. Subject remaining subprocess/read-decode work to OS resource and filesystem limits.

### 6.4 Remaining architectural checks

- Direct report/DICOM tool outputs are case-scoped but not yet routed through WorkspaceStore quota-accounted artifact transactions.
- Per-case lock/generation maps retain lifecycle history; unsafe eviction could resurrect superseded checkpoint work, so cleanup needs a lifecycle/concurrency design rather than an arbitrary cache cap.
- Startup recovery still reads active snapshots. Replace this only with a tested indexed/streamed recovery design that preserves stale-task repairs.
- Some fixed-host search transports use the existing requests-based implementation; inventory/redirection/body-size policy is not globally unified.
- Global PHI logging/retention and audit-log access have not been proved compliant.
- Advisory reviewers, latent brain/tree-search executors, knowledge-cache invalidation and the bounded but long cold-agent wait require further explicit contract/performance work before enabling new execution paths.
- Shutdown flushing improves normal termination but is not a transactional shutdown barrier against every active callback or forcible crash.
- A coverage/score/report generated by the product is not independent physical validation or clinical authorization; final guide mesh QA and approved model-specific dose calibration remain required.

## 7. Safe handoff

No commit, push, public-checkout copy, database migration, account change, patient deletion, planning job or service restart was part of the original patch delivery. The subsequent acceptance follow-up's only public mutation was redaction of the identified leaked literal in `start-public.sh`; no application overlay was copied there and no public restart occurred. Verify selected-file baseline hashes before applying any overlay; abort on concurrent edits. Keep restricted recovery backups and inspect actual Git changes and current listener/process/cwd after application.

The next operational step is a coordinated reload/restart and bounded browser/real-case validation, only after active case tasks and deployment configuration are reviewed. A passing source regression alone must not be reported as a running hardened service or a fully secure clinical release.

## 8. Actual-checkout delivery verification

The original overlay was applied to **61 selected files**, after two checks of original-file hashes and HEAD, archive membership/type checks, and overlay-content hashes. Every post-copy hash matched at delivery. Existing file permissions were preserved. The restricted recovery directory is `/tmp/brachybot-review-backup-20261004-GQZavM` (mode 0700). The acceptance follow-up deliberately redacted credential literals from its `start_server.sh` and `docs/CODE_REVIEW.md`; the original before-hashes for these two files no longer match. `credential-redaction-2026-10-04.json` records the intentional before/after hashes without a raw credential. The other backup contents were preserved. This temporary directory is a recovery aid, not a durable backup service or proof of credential revocation.

The actual checkout then reproduced **466 passed / 1 existing failure** in `/tmp/brachybot-review-actual-core-20261004.log` and **297 passed** in `/tmp/brachybot-review-actual-ui-20261004.log`. The three frontend harnesses passed in `/tmp/brachybot-review-actual-node-20261004.log`. Compilation, JavaScript/shell syntax and `git diff --check` passed. The read-only gate returned `blocked` for installed Torch 2.6.0 in `/tmp/brachybot-review-release-gates-20261004.json`; that nonzero status is an expected unresolved release blocker, not a passed launch check.

A real pinned-IP HTTPS request to `https://example.com` returned HTTP 200 with original-host certificate validation; no credentials or case data were sent. The current SSH environment did not have HTTP(S) proxy variables. This is a transport smoke test, not proof that every external clinical source is reachable.

The original delivery recorded PID 596570 on LAN `192.168.1.113:8080` and PID 596669 on public `127.0.0.1:18082`; that snapshot became obsolete before independent acceptance. The follow-up observed PID 916502 serving LAN `127.0.0.1:8080` from BrachyBot, started 2026-10-04 19:07:56, and PID 917541 serving public `127.0.0.1:18082` from BrachyBot-release, started 19:09:45 (Asia/Shanghai). This establishes intervening process replacement but does not identify its operator. Earlier HTTP/unauthenticated health results remain historical, not current authenticated health or browser/Access validation.

Future `start_server.sh` invocations default to loopback instead of implicitly enabling insecure LAN exposure. A LAN operator must explicitly supply the intended host and reviewed security configuration. No service was restarted by this acceptance follow-up. An intervening restart before acceptance may have loaded the earlier Python changes; the new follow-up Python changes have not been reloaded by this work. Browser assets require refresh, and coordinated runtime verification remains separate from source delivery.
