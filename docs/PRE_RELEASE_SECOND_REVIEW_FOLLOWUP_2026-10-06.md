# Second pre-release review: independent verification and remediation

Date: 2026-10-06. Authoritative LAN checkout: `/home/lht/snap/brachyplan/BrachyBot`.
Baseline HEAD: `95a3c6ea8bf6fa51680c0941739aecb7f76ccb83`.

## 1. Outcome and evidence boundaries

The review at the top of `CODE_REVIEW.md` identifies several real defects, including normalized dose exported as Gy, case-independent seed-map caching, an over-broad guide-status authorization grant, shared knowledge-base writes and unaccounted export/cache writes. These are not cosmetic defects. This follow-up changes their underlying unit, identity, authorization and commit contracts and adds negative controls.

**This is not a release approval, an assertion that every finding is closed, a penetration test or a clinical physics validation.** Outstanding items are explicitly retained below. The public-release checkout and its service are independent and were not patched or restarted. No provider-account credential revocation, Git-history rewrite, commit, push, real-patient planning or GPU/model migration was performed.

The original review contains **89 labeled references: 4 P0, 13 P1, 26 P2, 26 P3 and 20 FE**. Several references describe the same issue. Its stated 65 deduplicated findings cannot be independently reconstructed without a deduplication map, and its P3 headline of 22 disagrees with the 26 P3 table rows. The matrix below covers every label; it does not claim there are 89 distinct vulnerabilities.

Statuses:

- **Fixed:** a reproducible defect has a scoped implementation and regression evidence.
- **Partial:** a verified portion is fixed, with a remaining contract, deployment or validation gap.
- **Open:** a genuine concern remains; it must not be presented as fixed.
- **Qualified:** the cited behavior exists, but its exploitability, intended scope or proposed remedy needs correction.
- **Refuted:** the specific allegation is incorrect for the inspected implementation/specification.

## 2. Important scientific corrections

### 2.1 Model calibration is not prescription and not an independent dose engine

`dose_distribution_gy` is a historical **normalized model-output alias**, despite its name. `dose_distribution_physical_gy` is the physical Gy volume. A recorded calibration of 190.8 means one model unit maps to 190.8 Gy; it does not mean the patient's prescription is 190.8 Gy. A 120 Gy prescription remains separate.

New `utils/dose_units.py` centralizes explicit physical/normalized conversion. Physical arrays win over the misleading legacy alias. Physical volumes are not rescaled again; unknown normalized calibration, non-finite arrays and invalid units are rejected. NIfTI and isodose exports use this same physical volume. DICOM-RT requires explicit units or a saved positive scale and no longer silently substitutes a scale of 1. A legitimate 4 Gy physical array remains 4 Gy even when a model calibration is present.

These fixes **do not replace the CNN with TG-43/Monte Carlo**. They correct the representation of CNN output. Synthetic value/geometry round-trips are internal software checks, not independent dose-accuracy evidence. A separate independently calculated dose field is still needed before making independent physical-accuracy claims.

The old global legacy-unit inference helpers remain a migration concern. This patch does not arbitrarily reinterpret all historic low-valued prescriptions or overwrite old case data. See P2-4, P2-5 and FE-16.

### 2.2 Dxcc needs voxel volume and a declared sampling rule

The discrete hottest-volume rule now uses `ceil(volume_cc / voxel_volume_cc)`, with an integer floating-point tolerance, a lower bound of one and an upper bound of the organ voxel count. Blind `int()` truncation and blind `round()` are not scientifically equivalent. When the requested cc exceeds organ volume, the current clamped result is the organ minimum, not proof that the organ contains the requested cc.

Acquisition masks use acquisition spacing; resampled masks require the resampled image's spacing. A different grid cannot borrow acquisition spacing merely because an array shape matches. Direct unified/comprehensive/absolute-volume dose tools also reject missing, zero, negative or non-finite spacing. One-millimetre fallback is no longer used in those paths. Cross-tool percentile/interpolation conventions beyond this Dxcc rule still require explicit documentation.

### 2.3 Geometric safety is not just a collinear sign patch

`ray_min_distance` is solved as a constrained closest-point problem with normalized directions, feasible interior and boundary candidates. This corrects both opposing-ray overlap/separation and the inspected nonparallel sign error. It does not imply finite needle length or guide wall thickness has been independently validated.

Named bowel, stomach, duodenum, esophagus, bladder and heart labels are now included in the named default obstacle policy; browser and planner agree. The exact existing 117-label ontology was moved into a dependency-free shared module. Default policy no longer imports the inference adapter or falls back to incomplete guessed numeric ranges if optional inference imports fail. A different segmentation ontology still requires its own explicit source-version mapping; the TotalSegmentator map is not universal anatomy truth.

### 2.4 DICOM output is unapproved research output, not certified TPS interoperability

RTDOSE validates a finite positive-spacing orthonormal grid, writes `FrameIncrementPointer` and signed frame offsets along the row/column cross product. Synthetic read-back reconstructs 190.8 Gy and explicit 4 Gy, including a reversed slice direction.

An additional defect was found: RTSTRUCT previously exported rectangular bounding contours instead of the segmentation boundary. It now extracts half-voxel contours of the actual mask, preserving disconnected components and holes using `CLOSEDPLANAR_XOR`. A rotated/anisotropic synthetic mask with a hole and disconnected edge component is rasterized back and matches exactly.

Original CT SOP-instance linking, complete source/RTPLAN semantics and real TPS interoperability remain unvalidated. The exports retain `UNAPPROVED`; these round-trips must not be described as clinical acceptance. Primary references: [DICOM grid frame offsets](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.8.3.2.html), [DICOM ROI contour module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.8.6.html).

## 3. Item-by-item disposition

### P0

| ID | Status | Independent finding and disposition |
|---|---|---|
| P0-1 | Partial; release blocked | Three ignored worktree literals and four historical commits were independently confirmed. The three exact current literals were sanitized with file-hash guards and no plaintext backup. Fingerprint registry extended. Provider revocation and history cleanup are not completed. Existing release scanning already covers source roots and selected process environments; the claim that it scans only two files is stale. |
| P0-2 | Fixed | NIfTI dose previously wrote normalized values with Gy metadata. Export now resolves validated physical Gy first, with recorded normalized calibration only as an explicit fallback. Synthetic export checks protect against approximately 190-fold errors and double scaling. |
| P0-3 | Fixed at dose boundary; interoperability open | RTDOSE's implicit scale=1 was unsafe. Units/calibration are exposed and enforced; missing normalized calibration fails. Real TPS/source/FrameOfReference linkage is not certified. |
| P0-4 | Fixed | Per-seed key now includes case identity, actual normalized CT-content SHA256, image grid, model instance/device and inference/seed settings. Locked bounded LRU stores read-only arrays. Same-geometry different-content cases cannot share entries. Model hot-replacement must continue replacing the loaded model instance rather than changing its weights invisibly. |

### P1

| ID | Status | Independent finding and disposition |
|---|---|---|
| P1-1 | Fixed for reachable guide-status path | Direct status execution already selected `action=status`, but its tool-name grant also allowed a model-selected default generate. Pure/compound status no longer grants writes; guide mutations always pass the second semantic authorization gate, including under direct grants. Explicit generation remains functional. A generic action-capability refactor for every mixed tool is not claimed. |
| P1-2 | Fixed for web agents | Removed `clinical_kb add` from the model-facing schema. KB mutations are classified and shared add/propose/refresh writes are denied in web scope. Non-web administrator writes require an explicit administrator environment switch. No user instruction can authorize a cross-tenant repository mutation. |
| P1-3 | Fixed at inspected tool/history boundaries | All three external evidence tools are JSON-quoted as untrusted data in both model-selected execution paths. Durable user-role memory and tool history retain receipts/hashes, not attacker body text. This is provenance separation, not a mathematical guarantee that an LLM cannot be influenced by retrieved text. |
| P1-4 | Partial | `vtk`, `scikit-learn` and `pillow` are declared. Existing validated environment imports are tested; a fresh installation and a complete regenerated hash-locked deployment environment were not run. |
| P1-5 | Fixed in candidate application and deployment example | Flask denies hidden/source/backup suffixes through an asset allowlist. Nginx example now denies `.orig`, `.rej`, `.tmp`, `.log`, `.bak*` and related source suffixes. No backup was broadly deleted; gateway configuration of a live public deployment was not modified. |
| P1-6 | Fixed | Dose evaluation chooses physical Gy ahead of the normalized alias, resolves calibration only if needed, validates spacing and refuses silently dropping a loaded mismatched OAR grid. |
| P1-7 | Fixed for the declared source | Named obstacle policy and frontend parity corrected; old tests expecting bowel traversal were scientifically invalid and updated. Both OAR adapter and planner share the exact existing dependency-free ontology; optional inference-import failure no longer weakens the policy. Configuration remains a research safety policy, not a site-approved clinical path. |
| P1-8 | Fixed | Constrained ray distance replaces the erroneous parallel/nonparallel formulas. Overlap, separation and degeneracy counterexamples are tested. |
| P1-9 | Fixed for product viewer routes | All product cache routes provide server-derived owner context. Case guard, active-local check, quota lock and replacement-capacity accounting prevent deleted-case resurrection and quota bypass; pending writes are bounded. Standalone unowned CLI cache behavior is separate. |
| P1-10 | Fixed in scene-export contract; OS limit open | Per-account/global job limits and selection cap enforce admission. Account-namespaced staging counts toward usage, reserves space, commits actual bytes under quota/case fences and rolls back failed/lifecycle-invalid output. Completed status is published after quota commit. The estimate is not a hard filesystem sandbox; process/filesystem limits remain required. |
| P1-11 | Fixed | Interrupted-state repair and snapshot reads serialize with all case-guarded writers. No unlocked read-modify-write interruption repair remains in the inspected function. |
| P1-12 | Fixed for current callers; broader stale-action design open | Replacement supports `expected_revision`. Current server-owned destructive read-modify-replace callers are serialized around the complete operation, not just the final write. No route directly accepts an arbitrary browser whole-section replacement. A newer intentional delete of a specific object is not automatically an invalid stale checkpoint; action-level fencing is still needed if such a future route is added. |
| P1-13 | Fixed in inspected router/loop | `finish_reason=error` is a failed provider attempt, not a valid clinical answer. Fallback advances; the runtime refuses an error finish before processing tool calls. Exhaustion gives a generic unavailable response, not the raw provider exception. |

### P2

| ID | Status | Independent finding and disposition |
|---|---|---|
| P2-1 | Fixed | Isodose STL thresholds are applied to resolved physical Gy; normalized aliases are not compared directly to Gy. |
| P2-2 | Fixed for inspected Dxcc paths | Shared discrete hottest-volume helper replaces inconsistent truncation; report's suggested blind rounding was not adopted. Broader percentile conventions are separate. |
| P2-3 | Fixed | `dmax_pct`/`max_dose_pct` evaluate Dmax/Rx using the supplied positive prescription. Missing prescription cannot silently pass a relative constraint. The KB represents ratios (e.g. 1.2), not 120-style percentages. |
| P2-4 | Partial | New export/evaluation boundaries reject missing calibration. Global historical `resolve_dose_scale_gy` fallback persists for legacy compatibility; require a versioned migration/classification and an explicit legacy marker before retiring it. Do not claim global closure. |
| P2-5 | Open migration issue | Unknown-unit low values still pass through historic heuristics in other consumers. Explicit physical values are protected in the new boundaries, but changing every old case's interpretation without a unit migration would corrupt valid legacy results. |
| P2-6 | Fixed in evaluation paths | Acquisition/resampled spacing is grid-specific and validated; direct volume-dose tools also refuse unknown voxel volume. |
| P2-7 | Partial | Different-sized NumPy segmentation requires finite orthonormal source geometry; cropping is not stretched over CT. Equal-sized predictor output inherits geometry only under the existing documented raw-input-grid contract. Same shape alone is not proof for arbitrary external masks; adapter/TPS round-trips remain necessary. |
| P2-8 | Fixed for listed clients | Eight legacy OpenAI-compatible constructors now set finite timeouts and zero hidden SDK retries. Overall multi-tool/turn deadlines and real provider availability remain separate. |
| P2-9 | Fixed for inspected streams | After emitted content, transport failure raises instead of replaying a whole answer. Pre-content retry/fallback remains allowed. |
| P2-10 | Fixed | Malformed Anthropic JSON is not replaced with executable empty arguments; pre-content fallback retains tool calls and partial-content fallback does not duplicate output. |
| P2-11 | Fixed at deterministic safety ledger | Safety/geometry/reviewer results persist compact evidence with plan/manual-version ownership. Compression exposes current/stale status and does not infer approval from absent failures. Large/raw details require rereading the tool output. |
| P2-12 | Partial | Listed prompt/context/search/URL/provider-preview log sites were reduced to metadata; trace payloads are bounded. Other application exceptions, history and operator-assigned labels can still be sensitive. Deployment log ACL, retention, redaction and a complete PHI/DLP audit remain open. |
| P2-13 | Partial | Removed the underscore-recursion bypass and strip forged internal agent/workspace arguments. Recognized nested file fields remain contained and medical headers inspected. A schema-owned exhaustive per-tool path contract is still needed for arbitrary unconventional aliases; all strings cannot safely be interpreted as paths. |
| P2-14 | Partial | Web annotation reads/writes the authenticated case screenshots directory, not a shared repository folder. It is a visual evidence operation, not automatically an authorized medical-plan mutation; adding the whole tool to `MUTATING_TOOLS` would break read-only screenshot requests. Annotation-specific quota/cancellation/lifecycle transactions remain open. |
| P2-15 | Fixed with authenticated compatibility | Anonymous healthz returns constant liveness. Authenticated clients retain restart identity/uptime needed for existing restart detection. No case-resource hydration is performed. |
| P2-16 | Fixed | `/api/auth/password` uses the authentication limit bucket. |
| P2-17 | Fixed for inspected snapshot writers | Snapshot cache updates now share the case serialization boundary with writes. This does not claim cross-process locking or arbitrary OS crash consistency. |
| P2-18 | Qualified; recovery UX open | Source-change detection correctly fails closed. Blindly discarding the transfer journal, as suggested in the report, can destroy the only reconciliation evidence. A recoverable quarantine/restart protocol with operator-visible disposition is needed; no transfer or patient data was discarded. |
| P2-19 | Fixed for archived purge availability | Archived case permanent deletion refuses when archive storage is unavailable, rather than deleting the DB reference and leaving inaccessible NAS data. |
| P2-20 | Fixed at case serialization | Trash/restore/purge serialize with case writers and owned cache/export commit checks; synthetic tests reject output commit after trash. Physical power-loss recovery is not inferred from thread tests. |
| P2-21 | Partial | Case-lock holder/waiter reference counts reclaim idle guards without splitting waiting writers onto different locks. Snapshot cache invalidation and lifecycle fences improved. Best-effort purge orphan recovery and checkpoint/output-lock bookkeeping are still open; a durable purge journal is needed. |
| P2-22 | Open governance/operations | Audit records do grow. Retention, legal hold, PHI handling and archival must be specified before deleting them. No audit trail was silently erased to satisfy a bounded-size assertion. |
| P2-23 | Fixed | UI bridge has a 2 MiB encoded limit and atomic replacement-capacity/quota accounting. |
| P2-24 | Open | Planning history retention and copy-on-write/array reference lifetime need an explicit run/undo retention contract. No completed run or undo history was silently truncated. |
| P2-25 | Open LAN operations | LAN development listener/log behavior remains; the independent public implementation already uses a bounded WSGI server. No service replacement/restart was made as an audit side effect. |
| P2-26 | Open clinical configuration | Software defaults and source calibration are not site-approved prescriptions/OAR constraints. Require explicit site/source/profile provenance and research-only labels; this review does not invent clinical thresholds. |

### P3

| ID | Status | Independent finding and disposition |
|---|---|---|
| P3-1 | Fixed at missing/inactive-account branch | Missing/inactive accounts perform a dummy default-KDF hash verification; bounded input prevents excessive work. This does not prove uniform timing across historic password algorithms. |
| P3-2 | Open | IP-only rate limits do not stop distributed account attacks. A shared per-account abuse/challenge policy is still required; naive permanent username lockout would enable denial of service. |
| P3-3 | Fixed | XFF is considered only from an explicitly configured trusted peer; right-to-left chain processing ignores attacker-controlled prefixes. `TRUST_PROXY=1` alone is insufficient. |
| P3-4 | Partial | Provider/raw export failures are generic at repaired boundaries. Several other endpoint exceptions still need typed public error conversion; actionable validation messages should not be blindly replaced. |
| P3-5 | Open release gate | Compatibility CSP does not provide script isolation. Full inline-handler migration and nonce/strict-CSP browser testing remain necessary. |
| P3-6 | Fixed in generic basename resolver | With an authenticated workspace, generic basename lookup no longer scans the shared runtime/app trees; symlink entries are not resolved. Existing ownership checks still apply. |
| P3-7 | Qualified intended LAN behavior | Long-lived named debug-account exception is opt-in, default-disabled and public-blocked. It was a specific LAN/debug user requirement, not a public default vulnerability. Do not enable it in release. |
| P3-8 | Open; duplicate P2-25 | LAN Werkzeug remains a development service. |
| P3-9 | Qualified deployment gate | Public entry refuses insecure remote overrides and requires HTTPS origin; LAN insecure behavior is explicit development configuration. Real TLS/cookie/origin tests are still needed. |
| P3-10 | Qualified intended durable artifact | A permanent saved screenshot is owner/session authenticated as well as signed. Lack of expiry is not by itself a public read bypass. Time-limit temporary capture URLs separately; do not break historic report attachments by expiring all signatures. |
| P3-11 | Overstated / partially refuted | Extension filtering is not the entire upload chain: image header, decoded geometry and resource validation exist. Additional format-specific malformed/header mismatch tests remain useful; no blanket extension-only claim is warranted. |
| P3-12 | Qualified non-web risk | Python sanitizer is not a sandbox. Web developer-execution tools are disabled at multiple boundaries; trusted opt-in CLI execution requires an OS/process sandbox if untrusted input is allowed. No production enablement was added. |
| P3-13 | Qualified non-web risk | Shell blacklist is not a security sandbox; same web exclusion and CLI boundary as P3-12. |
| P3-14 | Open for opt-in CLI | A daemon-thread timeout cannot terminate arbitrary Python code; process isolation is needed. The disabled web tool was not enabled or advertised as safe. |
| P3-15 | Qualified non-web risk | Dynamic tools are process/repository-global; web creation is disabled. Tenant-specific hot registration is not implemented or claimed. |
| P3-16 | Qualified inactive/standalone path | Alternate executors exist but no active web caller was established. If reactivated, they must use the authoritative gateway rather than becoming a second security boundary. |
| P3-17 | Open design concern | Text-derived confirmation hints are not durable structured authorization receipts. Rework confirmation as case/turn/tool/action-bound proposals; do not treat arbitrary assistant wording or external evidence as authorization. |
| P3-18 | Partial | Presentation traces omit executable parameters, paths, arrays, payloads and patient containers. The allowlist is not a PHI detector; arbitrary operator object labels may still be sensitive. |
| P3-19 | Fixed for standard embedded ranges | NAT64 well-known/local-use, 6to4, Teredo and mapped private destinations are rejected in the public transport policy. Custom network translation routes still require deployment egress policy. |
| P3-20 | Fixed | DOI is encoded as an EUtils query value rather than concatenated into query syntax. |
| P3-21 | Fixed for scoped files | `checked_path` rejects hard-linked files in web case scope as well as escapes. File/FS sandbox and TOCTOU guarantees are separate. |
| P3-22 | Qualified intended CLI | Unscoped CLI output is not tenant-isolated web execution. Scoped web output is constrained. No claim that arbitrary user CLI code is sandboxed. |
| P3-23 | Qualified | A path denial cannot cross the boundary by retrying: every attempt is checked. A typed terminal/security-result taxonomy would improve behavior and audit clarity; raising all PermissionErrors indiscriminately could break legitimate bounded recovery. |
| P3-24 | Fixed | Model-provided `_agent` and forged workspace internal fields are stripped before server-controlled injection. |
| P3-25 | Open hardening | Some fixed-host search/access clients retain redirects/env proxy semantics unlike `public_get`. A unified bounded transport and deployment egress policy remain necessary; this is not proof of a reachable arbitrary-host SSRF. |
| P3-26 | Fixed; duplicate P2-8 | Listed constructors now set timeout/retry policy. |

### Frontend references

| ID | Status | Independent finding and disposition |
|---|---|---|
| FE-1 | Fixed at inspected sinks | Invalid colors fall back to a safe color. Data-tree IDs use a helper that encodes both JS-string and HTML-attribute contexts; primary data attributes are HTML escaped. Synthetic malicious ID remains literal. |
| FE-2 | Partial | Seed detail markup/owner/position and inspected needle/category handler sinks are encoded. This is not a claim that every inline handler in the application has been audited or migrated; strict CSP remains open. |
| FE-3 | Refuted as a requested restoration | Removing `?api_key=` credentials is intentional security hardening. Stale documentation is corrected; putting a credential back into URL history/referrers is not an acceptable functionality fix. |
| FE-4 | Fixed | Legacy `showToast` delegates to the existing non-blocking text-only notice surface; native browser verifies no HTML execution. |
| FE-5 | Refuted | `openCursor(arrayKey)` is an exact key, not a lower-bound range. Native IndexedDB test preserves both neighbors. `dbDeleteOne` now makes intent clearer and clear/all transactions wait for commit, but this is not a repaired mass-deletion bug. [IndexedDB specification](https://w3c.github.io/IndexedDB/#dom-idbobjectstore-opencursor). |
| FE-6 | Qualified / unproven | Fetch wrappers compose in current load order; no actual key/CSRF loss was reproduced. A single explicit request adapter would simplify ownership but deleting a wrapper without integration tests is unsafe. |
| FE-7 | Qualified / UX follow-up | Global colorbar preference is a display preference, not patient dose evidence. Per-case restoration precedence and cross-tab stale-display tests remain useful; no patient-array leak was established from this preference alone. |
| FE-8 | Open browser interaction validation | Sequence/lease fences exist, but complete real-browser multi-tab stale-replacement validation was not performed. Do not infer universal protection from server replacement tests. |
| FE-9 | Qualified | A same-origin print helper is intentional; patient values are rendered through report escaping. Full print-window lifecycle, opener isolation and output DOM audit remain open. Blind `noopener` would prevent writing the required print document on some browsers. |
| FE-10 | Fixed at pre-ready path | Clinical chat before cache/workspace readiness stays in bounded-in-scope memory rather than fallback localStorage; later owner-bound persistence remains. |
| FE-11 | Fixed at listed key families | Logout clears dot/underscore BrachyBot keys and layout preferences as well as the deployment-key cache. It does not indiscriminately erase unrelated origin storage. |
| FE-12 | Fixed at listed sink | Context-component labels are HTML-escaped before rendering. |
| FE-13 | Partial | Escapers in chat/report-editor include apostrophes; duplicated global helper consolidation still needs cross-bundle testing. |
| FE-14 | Qualified refactor opportunity | Duplicate/legacy helpers alone are not demonstrated bugs. Preserve working compatibility paths until caller and load-order behavior tests justify consolidation. |
| FE-15 | Fixed | Undo/redo actions are mapped to annotation history, not transform history. |
| FE-16 | Open migration issue; duplicate P2-5 | Viewer low-value unit heuristic is part of the old prescription contract and needs explicit unit/profile migration, not another numeric threshold. |
| FE-17 | Partial/unproven | App-wide timers are not automatically leaks; unbounded undo/history remains a retention/resource concern. Instance disposal and undo memory budgets need explicit UX contracts. |
| FE-18 | Fixed | Clear is coalesced, generation-fenced, waits for commit and reopens cache usage. Old pending reads/writes/invalidation cannot adjust a new generation. Native browser verifies new-session put/get after clear. |
| FE-19 | Qualified/open lifecycle cleanup | Patient-identifying filenames are a privacy/export policy issue, not automatically server traversal. Default de-identified filenames and print cleanup should be reviewed with existing artifact naming/audit requirements. |
| FE-20 | Open; duplicate P3-5 | Strict CSP/handler migration not completed; bundle cache versions were advanced for changed scripts. |

## 4. Tests and evidence

### 4.1 Full-suite discipline

Do not report targeted passes as a full-suite pass. The staged work was repeatedly tested against the complete top-level `tests/` suite, including surgical-guide collection. Intermediate runs were red and were used to repair the patch:

- An introduced missing `re` import in export-staging validation was reproduced and fixed.
- Old fixtures lacking planning-grid spacing or labeling a physical array as normalized were corrected to model the declared contract.
- Old expectations granting guide writes for status and permitting bowel traversal were corrected, not used to weaken production safety.
- Source-assertion tests that froze an old browser cache-buster number were changed to assert the referenced versioned bundle, retaining their actual geometry/opacity checks.
- Temporary stages need explicit read-only liver/kidney model paths and Node on PATH. These were provided rather than skipping availability/frontend tests. The two real-checkout availability tests also passed independently.

Latest completed staging run before the final report/extra boundary controls: **2,287 passed, 2 skipped, 31 warnings, 4 subtests passed; zero failures and zero collection errors** (55.67 s). Exact final post-delivery results supersede this intermediate count and are to be recorded below.

No nested benchmark experiment, real GPU inference, real-patient/TPS run, provider billing run or authenticated product browser session was performed. Tests use synthetic cases and the existing validated interpreter; declarations in `requirements.txt` are not a fresh-install validation.

### 4.2 Synthetic browser components

`tests/browser_review_second_20261006.cjs` serves only an isolated developer fixture on an ephemeral local port and starts a fresh headless Chrome context. Six tests passed:

1. Native array-key cursor exactness (refutes FE-5).
2. One-key invalidation preserves neighbors.
3. Clearing fences old operations and permits the next session.
4. Eviction obeys the 800 MiB accounting cap even when fewer than four entries remain; over-cap entries are refused.
5. Malicious inline object IDs remain literal across HTML and JS-string contexts.
6. Legacy toast text does not execute image/event markup.

Evidence: `docs/benchmarks/browser_review_second_2026-10-06.json`, with browser version and exact source SHA256s. Synthetic byteLength objects test accounting without allocating multi-gigabyte/patient storage. This is component evidence, not a claim that the entire application's UI has passed real-user acceptance.

### 4.3 Guide guard renewal is paired evidence, not a hash waiver

The pipeline changed named obstacles and Dxcc selection, which legitimately invalidated its frozen guide dependency. The imported canonical needle helper AST did not change. Four isolated pre/post synthetic pairs preserved input, vertices, faces, needle paths, auxiliary holes and QA hashes, with measured timings. `tests/guide_latency_reference.json` now links the paired evidence and its hash. The historical guide module itself was preserved.

Final evidence: `docs/benchmarks/surgical_guide_dependency_renewal_2026-10-06-review.json`, SHA256 `7c4729665a03e553ede260984d5c6d89dd8f8e04a5072c45fc09e72537638f4a`. The earlier October 5 replay is also retained, but is superseded after the shared label-ontology extraction. These are fixture-level results, not a real-case clinical latency claim. No guard was simply disabled or renewed with an unsupported hash.

## 5. Credential incident and release gate

The three reviewed ignored worktree files were checked against exact pre-change file hashes and the registered credential fingerprint. Only that quoted credential was replaced with an empty configuration value. Python compilation and post-change hashes were checked; mode was preserved. The receipt retains fingerprints and file hashes, not key text. No plaintext backup of the compromised credential was created.

Receipt: `docs/benchmarks/credential_redaction_receipt_2026-10-06.json`. The three files are the `AgenticSys.py` copies under `ui-design-fixes`, `datamind-report` and `benchmark-optimization`. No unrelated worktree content was changed. The four identified historical commits remain unchanged: history rewrite requires coordinated remediation of all clones/references, not an unannounced force-push.

Read-only source/process inspection covered both checkout source trees and the selected LAN/public service environments, using the updated fingerprint registry. It inspected 38,782 files / 1,041,379,430 bytes within its bounded scope. **LAN PID 1226477 still had a registered compromised key in three variables: `ANTHROPIC_API_KEY`, `BRACHYBOT_OPENCODE_GO_TOKEN`, `ANTHROPIC_AUTH_TOKEN`.** This observation is a dated snapshot, not a promise that PIDs remain fixed. Public PID 1226191 did not match a registered compromised fingerprint in this scan; that is not proof all its credentials are valid/revoked.

Thirteen additional key-shaped literals were flagged in vendored benchmark examples/tests. They are not automatically thirteen active leaked credentials; they require human classification and were not silently allowlisted or removed. The tool does not print values. Git objects, compressed archives, medical/model data, excluded symlink targets and provider portals are outside its scan scope. Registered-process checks match fingerprints, not every possible unknown runtime secret.

The gate remains **blocked** by credential revocation uncertainty, registered compromised runtime credentials and the inspected old PyTorch interpreter. The installed >=2.10.0 requirement for this advisory is supported by [the PyTorch maintainers' CVE-2026-24747 advisory](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p); `weights_only=True` alone does not eliminate that old-version risk. A version floor does not establish compatibility, model provenance or absence of later advisories.

**Do not restart a service with the same key and call that rotation.** Obtain/revoke through the provider, install a clean environment configuration, coordinate a scoped LAN reload, then scan the new PID. Public deployment must be handled independently. No service environment was dumped and no raw key was placed in this report.

## 6. Remaining ordered work

1. Provider revocation/rotation, explicit clean runtime configuration and fresh PID verification; coordinated Git-history/clone remediation. This requires account/operational authority not available in a source patch.
2. Versioned legacy dose/prescription unit migration, with ambiguous historical cases blocked/marked for review rather than guessed; explicit source/site/profile provenance.
3. Shared typed authorization proposals/receipts and exhaustive per-tool path/action schemas; annotation-output quota/lifecycle transactions; uniform bounded search/access transport.
4. Durable purge/transfer recovery journal, bounded checkpoint/output bookkeeping and planning/undo/audit retention approved by the data-governance owner. Do not delete clinical evidence as a shortcut.
5. Strict CSP/inline-handler migration, account abuse policy, typed public errors, log redaction/ACL/retention, and bounded production WSGI/filesystem/process deployment limits.
6. Hash-locked compatible isolated release environment, model/checkpoint provenance and geometry/precision tests for all actually enabled adapters. No unverified legacy VoCo adapter should be clinically enabled.
7. Real authenticated browser tests for multi-tab/login/logout, archived callbacks, Monitor/report capture/language/print/export and active edit leases; bounded crash/kill tests in an isolated runtime.
8. Independent clinical/physics/TPS acceptance and source-backed site eligibility. Software completion and synthetic contour/dose tests do not authorize patient treatment.

## 7. Delivery and final verification

Delivery uses a changed-file manifest with expected HEAD, each baseline SHA256 and each target SHA256. It aborts if selected user files changed concurrently. Existing files are backed up to a private 0700 directory; changed files are published atomically, with browser bundle versions last. The original `CODE_REVIEW.md` entry/history is retained as an exact suffix, superseded by a new summary rather than silently rewritten.

Final pre-publication candidate verification:

- Complete top-level suite: **2,290 passed, 2 skipped, 31 warnings, 4 subtests passed** in 58.66 s, with no failure or collection error.
- Skip reasons: optional public-transport dependency set (`tests/test_public_http.py:16`); real Nginx proxy binary not supplied (`tests/test_public_proxy.py:23`). Neither is a clinical/GPU pass.
- All changed **63 Python files** compile and **9 JavaScript/CommonJS files** pass Node syntax checks.
- Frozen surgical-guide reference guard passes; the four renewed paired replays all match.
- All 117 ontology entries are exactly equal to the original mapping, not just the protected-label subset.
- All 89 review labels have one matrix row. The old `CODE_REVIEW.md` bytes remain an exact suffix of the updated file.
- Six isolated native-browser component tests pass, as specified above.

The final candidate has **84 selected files** (source, regression tests, report and evidence). Guarded publication and actual-checkout retest are separate from these staging results. Their receipt/logs are retained in `/tmp/brachybot-review-second-delivery-20261005`; dated runtime observations do not automatically update themselves. No commit, push or automatic service restart is part of delivery.

### 7.1 Actual-checkout acceptance

Guarded publication completed for all 84 selected files. The original-file backup is `/tmp/brachybot-monitor-closed-loop-backup-20261005-hbxexlha` (mode 0700). Every original `before_sha256` and every delivered `after_sha256` was verified; the final report-only acceptance append is reflected in `manifest-final.json` in the delivery directory. Initial/intermediate receipts are retained rather than overwritten as if they had always described the final document.

The actual authoritative checkout then ran the complete top-level suite, without temporary-stage model path substitutions: **2,290 passed, 2 skipped, 31 warnings, 4 subtests passed in 57.74 s**. No failures or collection errors. Node was explicitly placed on PATH; the existing `/home/lht/.conda/envs/brachytherapy/bin/python` interpreter was used. The same two optional public-deployment checks were skipped for the reasons above. Log: `/tmp/brachybot-review-second-delivery-20261005/full-pytest-actual-checkout.txt`.

`git diff --check` passed. HEAD remains `95a3c6ea8bf6fa51680c0941739aecb7f76ccb83`; nothing was committed or pushed. All 84 corresponding public-checkout fingerprints were unchanged. Listeners remained LAN `127.0.0.1:8080` / PID 1226477 and public `127.0.0.1:18082` / PID 1226191. Both executables resolved to the existing brachytherapy interpreter. There was no service restart.

**Loaded backend processes still need a coordinated reload before these source fixes become runtime behavior.** Static bundle refresh is not equivalent to backend activation. Credential revocation/rotation, clean launch configuration and remaining release gates must be handled before claiming a safe deployment. This document does not claim the still-running process is using newly edited Python modules.
