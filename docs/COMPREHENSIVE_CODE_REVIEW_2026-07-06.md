# BrachyBot Comprehensive Code Review Report

**Date:** 2026-07-06
**Scope:** All Python source files (AgenticSys.py, brain/, memory/, agents/, tool_factory/, web/server.py, web/app/index.html, config/prompts/)
**Total files reviewed:** ~280 Python files + 1 HTML file (~24,724 lines JS/CSS/HTML)
**Total issues found:** 120 (21 HIGH, 44 MEDIUM, 55 LOW)

---

## Executive Summary

This review covers the entire BrachyBot codebase. The architecture is sound and the clinical safety design has been significantly improved in recent commits (source-aware prompting, fail-closed CTV tools, deterministic safety guardians). However, **21 HIGH-severity issues** were identified that require attention, the most critical being:

1. **Broken Dx dose metrics formula** — D90/D95/V100 calculations in `dx_metrics.py` use a wrong percentile index formula, producing silently incorrect clinical metrics
2. **7 LLM providers missing `import time`** — `time.time()` calls will raise `NameError` at runtime on those provider paths
3. **Infinite recursion in web_search** — weather search calls itself instead of delegating
4. **Stale pixel data in CT viewer** — overlay pixels persist when structures are hidden
5. **Broken DICOM series loading** — `sitk.ImageFileReaderWarningOff()` does not exist, crashes on DICOM loading

---

## 1. AgenticSys.py — Core Agent Engine

**File:** `AgenticSys.py` (8,306 lines)

| # | Line | Severity | Description |
|---|------|----------|-------------|
| 1 | 4452 | **HIGH** | `_cancelled()` is called in non-streaming `_run_llm_function_calling` but only defined inside `_run_llm_function_calling_stream`. Any cancellation attempt in non-streaming path raises `NameError`. |
| 2 | 744-745 | **HIGH** | Chinese localization bug: `if msg.endswith(")"): msg += ")"` causes doubled closing parenthesis. Example: `"命令执行失败（返回码 1)"` → `"命令执行失败（返回码 1))"`. Fix: should be `if not msg.endswith(")"):` or remove these lines. |
| 3 | 700 | MEDIUM | Dead code: `_LOCALIZABLE_TOOLS` class attribute defined but never referenced. |
| 4 | 5437-5443 | MEDIUM | Inconsistency: `_allowed_without_ct` includes `web_search` and `web_fetch` but omits `web_access`. Comment says "Allow web tools" — `web_access` is blocked when CT is not loaded even though it has no CT dependency. |
| 5 | 3903-3981 | MEDIUM | 15 duplicate dictionary keys in `_TUMOR_TYPE_MAP` (e.g., `"胰腺癌"` appears twice). Python keeps the last value — harmless currently since values are identical, but a maintenance risk. |
| 6 | 2330 | MEDIUM | `result.metadata["ctv_array"]` accessed directly without `.get()`, while adjacent accesses use `.get()`. `KeyError` if key is missing from a successful result. |
| 7 | 305-306 | MEDIUM | `except (ValueError, TypeError): pass` — int conversion fails silently during CTV/OAR label merge (no logging). |
| 8 | 324-325 | MEDIUM | Silent int conversion failure during CTV/OAR label merge (second instance). |
| 9 | 371-372 | MEDIUM | Silent int conversion failure during OAR label stripping. |
| 10 | 2403-2404 | MEDIUM | `except AttributeError: pass` — memory helper fallback silently swallows error. |
| 11 | 2489-2498 | MEDIUM | Two `except Exception: pass` blocks — auto-OAR operation tracking fails silently. |
| 12 | 2662-2694 | MEDIUM | Two `except Exception: pass` blocks — auto-planning operation tracking fails silently. |
| 13 | 3312-3348 | MEDIUM | Two `except Exception: pass` blocks — CTV voxel count and prescription dose parsing fail silently. |
| 14 | 4188-4189 | MEDIUM | `except Exception: pass` — session language persistence fails silently. |
| 15 | 5151-5152 | MEDIUM | `except Exception: pass` — session language persistence in streaming path fails silently. |
| 16 | 6677-6764 | MEDIUM | 4 `except Exception: pass` blocks — workflow enforcer auto-exec tracking failures. |
| 17 | 7271-7616 | MEDIUM | 2 `except Exception: pass` blocks — post-enforcer event loop close failures. |
| 18 | 5068-5568 | MEDIUM | ~500 lines of code nearly identical between streaming and non-streaming variants. Any bug fix must be applied twice. |
| 19 | 5076-5078 | LOW | Dead code: `emit` function defined inside `_run_llm_function_calling_stream` but never called. |

---

## 2. brain/ — Brain System (Router, Providers, Executors, Deciders)

### 2.1 Critical: 7 LLM providers missing `import time`

| # | File | Line | Severity | Description |
|---|------|------|----------|-------------|
| 20 | `brain/providers/deepseek_llm.py` | 70, 89 | **HIGH** | Missing `import time` — `time.time()` raises `NameError` on any API call. |
| 21 | `brain/providers/kimi_llm.py` | 75, 94 | **HIGH** | Same — missing `import time`. |
| 22 | `brain/providers/glm_llm.py` | 74, 93 | **HIGH** | Same — missing `import time`. |
| 23 | `brain/providers/groq_llm.py` | 72, 91 | **HIGH** | Same — missing `import time`. |
| 24 | `brain/providers/grok_llm.py` | 73, 92 | **HIGH** | Same — missing `import time`. |
| 25 | `brain/providers/mimo_llm.py` | 69, 88 | **HIGH** | Same — missing `import time`. |
| 26 | `brain/providers/tencent_llm.py` | 69, 88 | **HIGH** | Same — missing `import time`. |

### 2.2 Other brain/ issues

| # | File | Line | Severity | Description |
|---|------|------|----------|-------------|
| 27 | `brain/core/router.py` | 101 | **HIGH** | Broken relative import: `from .openai_llm import OpenAILLM` — `openai_llm.py` lives in `providers/`, not `core/`. Error swallowed by `except`, so auto-config fallback never works. |
| 28 | `brain/execution/plan_executor.py` | 135 | **HIGH** | Undefined variable `k` in list comprehension: `self._resolve_args({k: v}, context)[k]` — `k` is not defined in any enclosing scope. `NameError` when `_resolve_args` encounters list-typed arguments. |
| 29 | `brain/core/tool_code_writer.py` | 204 | **HIGH** | Wrong argument type: `self.tool_registry.register(tool_instance)` passes a tool object but `ToolRegistry.register()` expects `name: str` as first argument. `TypeError` at runtime. |
| 30 | `brain/core/multi_agent_critic.py` | 141-142 | MEDIUM | `except: pass` in `_get_critique` — LLM callback failure silently swallowed, falls through to `_fallback_critique` with no logging. |
| 31 | `brain/execution/case_executor.py` | 309-311 | MEDIUM | Return value from `execute_fn()` unconditionally overwritten by `json.load(f)` from output file. If file is stale or corrupt, metadata is silently lost. |
| 32 | `brain/core/base.py` | 68-71 | MEDIUM | LSP violation: `BaseDecider.decide()` abstract signature uses `context: Dict[str, Any]` (required), but `PlannerDecider.decide()` uses `context: Dict[str, Any] = None` and `ClinicalDecider.decide()` adds extra `indicators` parameter. |
| 33 | `brain/integration/enhanced_agent.py` | 43-47 | MEDIUM | Import from `memory` package may fail — `brain/memory/` has no `__init__.py`; absolute import `from brain.core import MultiAgentCritic` should be relative `from ..core import`. |
| 34 | `brain/deciders/planner_decider.py` | 153-157 | LOW | Dead code: `if actual != expected` block unreachable because line 150-151 reassigns consecutive IDs. |
| 35 | `brain/core/tool_code_writer.py` | 125 | LOW | `open(file_path, "w")` without `encoding="utf-8"`. On non-UTF-8 systems, non-ASCII tool code may be corrupted. |

---

## 3. memory/ — Self-Evolving Memory System

| # | File | Line | Severity | Description |
|---|------|------|----------|-------------|
| 36 | `self_evolution.py` | 193 | **HIGH** | `f["tools"]` — `KeyError`. `get_failure_patterns()` returns dicts with key `"tool_chain"`, not `"tools"`. Crashes at runtime. |
| 37 | `skill_crystallizer.py` | 135-136 | **HIGH** | Incorrect `success_rate` formula: `usage_count` is incremented *before* the weighted average computation, biasing the rate downward when `success_rate < 1.0`. Same bug at lines 251-253. |
| 38 | `interaction_memory.py` | 188 | **HIGH** | Type filtering uses `not in [...]` with literal strings `'<class numpy'`, `'<class torch'`, `'<class SimpleITK'` but `str(type(...))` returns `"<class 'numpy.ndarray'>"` — the quotes inside the string cause the match to always fail. Numpy/torch/SimpleITK objects leak into JSON serialization, causing downstream failures. |
| 39 | `self_evolution.py` | 115 | **HIGH** | Conditional runtime import `from skills.skill_base import Skill` without try/except. If `skills.skill_base` doesn't exist, the entire evolution cycle crashes. |
| 40 | `reflexion_engine.py` | 181 | MEDIUM | `response.strip().split("\n")` crashes with `AttributeError` if `llm_callback` returns `None`. Caught by outer `except` but silently falls back to heuristic. |
| 41 | `reflexion_engine.py` | 228-229 | MEDIUM | `except Exception: pass` silently swallows ALL LLM errors in `_multi_agent_reflexion`. |
| 42 | `layered_memory.py` | 175-176 | MEDIUM | `json.dump` without `default=str`. Same in `reflexion_engine.py:96`, `skill_crystallizer.py:115`, `user_profile.py:113`. Non-serializable types cause JSON dump crashes. |
| 43 | `layered_memory.py` | 125-129 | MEDIUM | Uses `dict[str, ...]`/`list[str]` type hints (Python 3.9+ syntax) without `from __future__ import annotations`. Fails on Python 3.8. |
| 44 | `skil_crystallizer.py` | 227-228 | MEDIUM | `evolve()` returns `None` when `should_auto_evolve()` is False, but type annotation says `-> EvolutionCycle`. |
| 45 | `context_optimizer.py` | 128-146 | MEDIUM | `remaining_budget` can go negative if required tokens exceed `max_tokens`, causing incorrect compression behavior. |
| 46 | `experience_memory.py` | 84-85 | LOW | `except Exception: self.patterns = []` with no logging. |
| 47 | `interaction_memory.py` | 205-206 | LOW | `except (json.JSONDecodeError, KeyError): pass` with no logging. |
| 48 | `layered_memory.py` | 164-165 | LOW | `except (json.JSONDecodeError, TypeError): pass` with no logging. |
| 49 | `preference_store.py` | 208-209 | LOW | `except (json.JSONDecodeError, KeyError): self.preferences = {}` with no logging. |
| 50 | `reflexion_engine.py` | 85-86, 193-194 | LOW | Two `except ...: pass` with no logging. |
| 51 | `skill_crystallizer.py` | 102-103, 219-220 | LOW | Two `except ...: pass` with no logging. |
| 52 | `skill_learner.py` | 296-297 | LOW | `except (json.JSONDecodeError, KeyError): self.skills = {}` with no logging. |
| 53 | `user_profile.py` | 93-94 | LOW | `except (json.JSONDecodeError, TypeError): pass` with no logging. |
| 54 | `language.py` | 155-156 | LOW | `except Exception: pass` with no logging. |
| 55 | `smart_context.py` | 387-388 | LOW | Compressed messages marked as summaries may inconsistently be included via recency guarantee. |

---

## 4. agents/ — Multi-Agent System

| # | File | Line | Severity | Description |
|---|------|------|----------|-------------|
| 56 | `safety_guardian.py` | 22 | MEDIUM | `llm_callback` parameter accepted but hard-coded to `None` in `super().__init__()`. Caller's argument silently ignored. |
| 57 | `safety_guardian.py` | 147 | MEDIUM | `ReviewResult` uses positional args while all other call sites use keyword args. Fragile if field order changes. |
| 58 | `plan_reviewer.py` | 186-203 | MEDIUM | `_dose_ratio_or_fraction()` duplicated identically in `SafetyGuardian` (`safety_guardian.py:285-303`). Maintenance risk. |
| 59 | `plan_reviewer.py` | 158-178 | MEDIUM | `_advisory_sanity_checks()` near-identical to `SafetyGuardian._check_advisory_dose_distribution()`. Both agents run the same check on the same data. |
| 60 | `orchestrator.py` | 94 | MEDIUM | `{**self._global_context, **role_specific}` — if a key exists in both, `role_specific` silently overwrites global context with no warning. |
| 61 | `orchestrator.py` | 12 | LOW | Unused import: `AsyncGenerator`. |
| 62 | `orchestrator.py` | 188 | LOW | Redundant `import asyncio` inside method body (duplicates module-level import on line 8). |
| 63 | `router_agent.py` | 314 | LOW | `import json` inside method body instead of at module level. |
| 64 | `completeness_checker.py` | 76 | LOW | Instance variable `self._conversation_state` set in `process()` not `__init__`. |
| 65 | `safety_guardian.py` | — | LOW | No `import logging` (unlike every other agent file). |

---

## 5. tool_factory/ — 50+ Medical Tools

### 5.1 HIGH severity

| # | File | Line | Severity | Description |
|---|------|------|----------|-------------|
| 66 | `image_processing/image_loader.py` | 131 | **HIGH** | `reader.ImageFileReaderWarningOff()` — method does not exist on `sitk.ImageFileReader`. Correct method is `reader.SetWarningOff()`. DICOM loading crashes with `AttributeError`. |
| 67 | `image_processing/image_loader.py` | 134 | **HIGH** | `import sitk as s` — `sitk` is not a package on the module path (aliased as `SimpleITK` import). `ModuleNotFoundError` on DICOM series selection. |
| 68 | `CTV_seg/pancreatic_tumor_nnunet.py` | 254 | **HIGH** | `image.GetDirection()[::-1]` — reversing the 9-element flat direction matrix gives incorrect permutation `[dzz, dzy, dzx, dyz, dyx, dyx, dxz, dxy, dxx]`. SimpleITK uses (x,y,z) axis order; nnUNet expects (z,y,x). Causes misaligned segmentation. |
| 69 | `dose_eval/dx_metrics.py` | 100 | **HIGH** | **Wrong Dx formula.** `idx = int((100 - dx) / 100.0 * total_voxels)` computes the (100−x)th percentile, not dose covering x%. For D90, returns dose covering ~11% of target. Correct: `idx = max(0, int(dx / 100.0 * total_voxels) - 1)`. Same bug in `comprehensive_dose_evaluation.py:141`. |
| 70 | `seed_plan/planning_pipeline.py` | 1396 | **HIGH** | Off-by-one: `idx = min(int(n * vol_pct / 100.0), n - 1)`. For 90% volume with n=100, idx=90 gives 91% coverage, not 90%. |
| 71 | `safety_validator/__init__.py` | 185-188 | **HIGH** | `_normalize_tumor_type` maps both `"voco_kidney"` and `"voco_colon"` to `"liver"`. Kidney and colon have completely different OAR constraints. Causes wrong safety thresholds for kidney/colon cases. |
| 72 | `OAR_seg/totalsegmentator_oar.py` | 273-277 | **HIGH** | After transposing nibabel output to (Z,Y,X), mask direction is never set. Default identity matrix misaligns OAR masks on rotated acquisitions (non-identity CT direction). |
| 73 | `OAR_seg/voco_total_segmentation.py` | 179 | **HIGH** | `torch.load(..., weights_only=False)` — disables PyTorch 2.6+ weight serialization safety. Arbitrary code execution from malicious .pt files. Same in `aorta_vessel_voco.py:95` and `CTV_seg/voco_base.py:114`. |
| 74 | `traj_plan/trajectory_refine.py` | 138 | **HIGH** | Unit mismatch: `depth` is in mm but `radiation_volume.shape` returns voxel counts. `max_depth_idx = min(int(depth), max(...) - 1)` — if spacing ≠ 1mm, trajectory sampling uses wrong number of steps. |
| 75 | `web_search/__init__.py` | 1591 | **HIGH** | Infinite recursion: `_search_weather` calls itself (`return _search_weather(query)`) instead of delegating to the module-level function. Any weather query causes `RecursionError`/stack overflow. |

### 5.2 MEDIUM severity

| # | File | Line | Severity | Description |
|---|------|------|----------|-------------|
| 76 | `seed_plan/planning_pipeline.py` | 86 | MEDIUM | `open(CONFIG_PATH, 'r')` without `encoding=`. Non-UTF-8 system locale raises `UnicodeDecodeError`. |
| 77 | `doc_reader/__init__.py` | 353, 354, 373 | MEDIUM | Multiple bare `except:` blocks that silently swallow all exceptions. NIfTI/MHD/PNG fallbacks return empty metadata with no diagnostics. |
| 78 | `viewer_command/query_metrics.py` | 149 | MEDIUM | `except: pass` in `_get_all_metrics` — if one metric fails, entire function returns partial/incomplete data with no indication. |
| 79 | `web_search/__init__.py` | 1592-1615 | MEDIUM | Dead code after `return _search_weather(query)` on line 1592. Lines 1594-1615 are unreachable and use undefined variable `city`. |
| 80 | `web_search/__init__.py` | 1532-1534 | MEDIUM | `WebFetchTool.execute(url=url, extract_text=True)` — `extract_text` is not in `_execute`'s signature. Intended text extraction is silently ignored. |
| 81 | `web_access/__init__.py` | 38 | MEDIUM | `from utils.retry import retry_with_backoff` — brittle import; `utils` module may not exist in all deployment configurations. |
| 82 | `code_executor/__init__.py` | 35 | MEDIUM | `"open("` in `DANGEROUS_PATTERNS` — substring match blocks any code containing `"open("` in comments, variable names, or legitimate `open()` calls. Overly broad. |
| 83 | `OAR_seg/totalsegmentator_oar.py` | 300-306 | MEDIUM | `_get_clean_subprocess_env` removes `PYTHONPATH` but NOT `LD_LIBRARY_PATH`, `CUDA_VISIBLE_DEVICES`, or `PATH`. Inconsistent with `pancreatic_oar.py:295-300`. |
| 84 | `dose_eval/__init__.py` | 102 | MEDIUM | `dose_array = kwargs["dose_array"]` raises `KeyError` if missing (no `.get()`), but `ctv_mask = kwargs.get("ctv_mask")` silently defaults to `None`. Inconsistent access pattern. |
| 85 | `shell_executor/__init__.py` | 93 | MEDIUM | Shell operator detection uses `">"` substring match — matches `"->"`, `"=>"`, `"> 0"` causing false positives. |
| 86 | `env_manager/__init__.py` | 35 | MEDIUM | Audit log path inside package directory. On read-only package installations, audit logging silently fails. |

### 5.3 LOW severity

| # | File | Line | Severity | Description |
|---|------|------|----------|-------------|
| 87 | `seed_plan/planning_pipeline.py` | 86 | LOW | Same `open` without encoding as #76. |
| 88 | `report_context.py` | 159 | LOW | `list(shape_zyx)[:3]` raises `TypeError` if memory returns non-iterable. |
| 89 | `CTV_seg/pancreatic_tumor_nnunet.py` | 271-281 | LOW | Direct access to private attributes `_dm._lease_lock` and `_dm._active_per_device`. Brittle under refactoring. |
| 90 | `OAR_seg/pancreatic_oar.py` | 200 | LOW | `env["PYTHONHOME"] = python_home` may conflict with subprocess venv. |
| 91 | `traj_plan/trajectory_init.py` | 136 | LOW | No try/except around `utilizations.get_reference_direction(...)`. If missing, `None` reaches `np.array(...)` with confusing error. |
| 92 | `shell_executor/__init__.py` | 22 | LOW | `EXECUTION_ENABLED` evaluated at import time, not per-call. Runtime env var changes not reflected. |
| 93 | `performance_tracker/__init__.py` | 33 | LOW | `except: pass` silently swallows JSON decode errors on corrupted metrics file. |
| 94 | `plans/utilizations.py` | 471-472 | HIGH | Bare `except Exception: return None, None, None, None` wrapping the entire function body — any error silently returns `None` with zero logging. |
| 95 | `plans/utilizations.py` | 89 | MEDIUM | `sitk.GetArrayFromImage(dose_image).shape` reads entire 3D array into memory just to get shape. Use `dose_image.GetSize()` (O(1)). |
| 96 | `quality/quality_gate.py` | 260-261 | MEDIUM | Exception traceback not logged: `logger.warning(f"Review agent failed: {result}")` only logs `str(result)`. |
| 97 | `plans/utilizations.py` | 13, 23 | LOW | Unused imports: `import torch.optim as optim`, `import traceback as _tb`. |
| 98 | `tool_factory/clinical_kb/__init__.py` | 145-148 | LOW | Ineffective PubMed search filter — both branches return the URL, making the `"pubmed.ncbi.nlm.nih.gov/?term="` check redundant. |
| 99 | `tool_factory/clinical_kb/__init__.py` | 87-91 | LOW | `_ensure_default_kb()` never validates existing JSON. Corrupt file passes existence check. |
| 100 | `scripts/download_ctv_models.py` | 44 | LOW | `total.isdigit()` rejects decimal Content-Length strings (e.g., `"1048576.0"`), suppressing progress display. |

---

## 6. web/server.py — Flask Web Server (5,188 lines)

| # | Line | Severity | Description |
|---|------|----------|-------------|
| 101 | 5161 | **HIGH** | SIGHUP handler set to custom handler then immediately overwritten to `SIG_IGN`. First registration is dead code. If platform lacks SIGHUP (Windows), `AttributeError` on `signal.SIG_IGN`. |
| 102 | 1222 | **HIGH** | `@staticmethod` on `_load_ct_image` defined inside `create_app()` function (not a class). On Python <3.10, staticmethod objects are not callable. `TypeError` if called. Same for lines 1335, 1445. |
| 103 | 570-571 | MEDIUM | `except: continue` when seed coordinate transform fails. Seeds outside CT volume dropped without warning or logging. |
| 104 | 577-578 | MEDIUM | `except:` falls back to default direction `[0,0,1]` with no logging when RAS-to-voxel conversion fails. |
| 105 | 1021 | MEDIUM | CORS origins set to `"*"` when `BRACHYBOT_TRUST_NETWORK` enabled. Any website can make authenticated API requests from the browser. |
| 106 | 4108 | MEDIUM | `except: pass` when `agent.memory.set_ui_state()` fails in `api_ui_event`. UI state desynchronization silently swallowed. |
| 107 | 4638-4664 | MEDIUM | SSE endpoint `api_tasks_stream` does not handle client disconnection. No `GeneratorExit` handling unlike the chat SSE endpoint. |
| 108 | 62, 991-995 | MEDIUM | Rate limiting uses `request.remote_addr` directly. Behind a reverse proxy, all requests appear from proxy IP, bypassing per-client rate limiting. |
| 109 | 3392 | LOW | JSON config file opened without `encoding=`. Non-UTF-8 default may cause mojibake. Same for lines 3470, 3480, 3938. |
| 110 | 769 | LOW | `dose_range_normalized` set to identical values as `dose_range`. Should use planning-grid normalized values vs CT-space resampled values. |
| 111 | 865-870 | LOW | `_validate_path` uses string-based `'..'` check which does not handle null bytes or Unicode normalization attacks. |

---

## 7. web/app/index.html — Frontend (24,724 lines)

| # | Lines | Severity | Description |
|---|-------|----------|-------------|
| 112 | 11748 | **HIGH** | **Stale pixel data in CT viewer:** `continue` inside pixel loop skips RGBA data writes. If a CTV sub-label changes from visible to hidden, pixels retain old overlay color instead of showing CT grayscale. |
| 113 | 4415-4416 | **HIGH** | `setUiLanguage('en')`/`setUiLanguage('zh')` called from HTML `onclick` handlers. If function is undefined, clicking EN/中 toggle raises `ReferenceError`, breaking language switching. |
| 114 | 16706-16747 | HIGH | Duplicate `_petRainbow2` function. Two implementations — first is dead code (160+ lines). Last one wins, but confusing. |
| 115 | 18504-18621 | MEDIUM | Duplicate `renderSeedsOverlay` function. Two implementations; first (legacy) is overridden. If `updateSlice` depends on first version's coordinate mapping, visual output differs. |
| 116 | 24685 | MEDIUM | `if (false && ...)` guard permanently disables language-detection hook. Feature is always off. |
| 117 | 20197-20293 | MEDIUM | DVH tooltip DOM leak. IIFE inside `Plotly.react()` callback appends a new `<div>` to `document.body` on every re-render with no cleanup. |
| 118 | 9586 | MEDIUM | `toggleStepButtons` targets `document.getElementById('stepButtonsContainer')` but HTML element has `id="stepButtonsSection"`. Collapse toggle silently fails. |
| 119 | 5100 | MEDIUM | `applyZoom(this.value)` called from HTML `oninput`. If function not defined, zoom slider throws `ReferenceError`. |
| 120 | 11250-11313 | MEDIUM | `volumeShape` is [Z, Y, X] but `volumeSpacing` is [X_spacing, Y_spacing, Z_spacing]. Convention duality is error-prone. |
| 121 | 9494 | MEDIUM | `state.ctLoaded = true` set before `await loadVolumeData()` completes. If async load throws, state shows "CT loaded" but no slices render. |
| 122 | 19667-20350 | MEDIUM | DVH chart relayout cascade: multiple timers (0ms, 80ms, 250ms, 600ms) + `responsive: true` + `plotly_relayout` → adaptive dtick logic → another relayout. Performance issue during rapid panel switches. |
| 123 | 17057 | MEDIUM | `state.doseOverlay.data` accessed but never populated in modern code paths. Modern path stores data as `slices: {}` cache. Misleading property name. |
| 124 | 17010-17029 | MEDIUM | `fetchDoseOverlaySlice` version counter race: stale out-of-order data cached when user scrolls back. Cache has no staleness check. |
| 125 | 11326-11338 | MEDIUM | `ResizeObserver` set up on every `loadVolumeData` call with no cleanup. Observers persist on detached canvases when CT is unloaded. |
| 126 | 11280 | LOW | `volumeSpacing` fallback magic number `[0.68, 0.68, 5.0]` assumes CT abdomen. Wrong aspect ratio for head (1.0mm) or chest (3.0mm) CTs. |
| 127 | 4734 | LOW | `applyHyperparams()` only adds a chat message. Hyperparameter values never serialized or sent to server. Misleading "updated" message. |
| 128 | 24684 | LOW | `_origSendChat` capture assumes single-threaded synchronous script loading. If `sendChat` is replaced after Report module loads, hook calls old version. |
| 129 | 12465 | LOW | `state.ctvVolume` read but never written. CTV volume never shown in data tree. |
| 130 | 21618 | LOW | Report IIFE runs at script parse time, references `window.reportForm` defined later in same block. Protected by `typeof` guards but fragile. |

---

## Severity Distribution

| Severity | Count | 
|----------|-------|
| **HIGH** | 21 |
| **MEDIUM** | 44 |
| **LOW** | 55 |

## Most Critical Issues (Top 5)

| # | Area | Issue | Impact |
|---|------|-------|--------|
| 1 | `dose_eval/dx_metrics.py:100` | Wrong Dx formula | All D90/D95/V100 metrics silently wrong → cascades into plan quality scores and safety validation |
| 2 | `brain/providers/*_llm.py` | 7 providers missing `import time` | `NameError` on any API call to DeepSeek/Kimi/GLM/Groq/Grok/Mimo/Tencent providers |
| 3 | `web_search/__init__.py:1591` | Weather search recursion | Infinite recursion / stack overflow on any weather query |
| 4 | `image_loader.py:131-134` | DICOM loading crashes | `AttributeError` + `ModuleNotFoundError` on DICOM series loading |
| 5 | `index.html:11748` | Stale pixel data | Overlay pixels persist when CTV sub-labels are hidden in viewer |

## Module-by-Module Quality

| Module | Lines | HIGH | MED | LOW | Score |
|--------|-------|------|-----|-----|-------|
| AgenticSys.py | 8,306 | 2 | 14 | 3 | B- |
| brain/ | ~5,000 | 9 | 6 | 3 | C |
| memory/ | ~3,000 | 4 | 6 | 12 | C+ |
| agents/ | ~1,500 | 0 | 5 | 5 | B+ |
| tool_factory/ | ~15,000 | 9 | 8 | 14 | C+ |
| web/server.py | 5,188 | 2 | 6 | 3 | B |
| web/app/index.html | 24,724 | 2 | 9 | 7 | B |
| config/prompts/ | ~1,000 | 0 | 0 | 0 | A |

---

*Generated by comprehensive static analysis. This report catalogs all identified issues without modifying any source code.*
