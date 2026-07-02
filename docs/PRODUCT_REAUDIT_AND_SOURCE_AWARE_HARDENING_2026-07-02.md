# Product Re-Audit and Source-Aware Hardening

Date: 2026-07-02

Scope: latest `main` branch after the UI-aware manual planning, training monitor, clinical KB, and product-readiness work.

## Executive Summary

This pass focused on issues that were verifiable from code and could be fixed without changing the already-correct imaging coordinate chain. The main problems were not GPU planning math or 2D/3D orientation; they were product-governance and safety boundaries:

- Some report and agent summary paths still converted observed metrics into clinical pass/fail statements from local hardcoded ratios.
- The deterministic readiness API existed conceptually but was not exposed as a first-class UI/LLM action.
- Dynamic tool creation accepted unsafe tool names that could escape the intended dynamic tool directory.
- Plan-quality tools were present but not registered in the main agent tool registry.

All fixes below use English code comments and avoid changing CT/mask/dose/seed coordinate transforms.

## Findings and Fixes

| ID | Finding | Verification | Fix |
|---|---|---|---|
| R1 | Report auto-fill and clinical evaluation could imply clinical acceptability from local defaults or corrupted template text. | Reviewed `web/server.py` report auto-fill, `web/app/index.html` report templates, `_autoFillInterpretation`, and `updateClinicalEvaluation`. | Replaced pass/fail wording with observed metrics plus a requirement to use `clinical_kb` or explicit `plan_config` for clinical thresholds. Removed corrupted report-template text from active auto-fill paths. |
| R2 | Agent planning summaries still instructed LLM synthesis to classify OAR rows as OK/WARN/EXCEEDS from generic ratios. | Reviewed the planning synthesis prompt in `AgenticSys.py`. | Changed OAR status guidance to `Needs clinical_kb/plan_config review` unless retrieved evidence or explicit constraints are available. |
| R3 | `OARConstraintCheckerTool` had generic built-in OAR constraints that could produce false PASS/FAIL labels for the wrong disease site. | Reviewed `tool_factory/plan_quality/oar_constraint_checker.py`. | Rebuilt the tool as source-aware: it only checks caller-supplied constraints or curated standards for an explicit tumor site; otherwise it returns `NOT_CHECKED`. |
| R4 | The LLM could not call a deterministic "is this case ready?" product checklist through the UI action registry. | Reviewed `/api/readiness`, manual UI actions, and `tool_factory/ui_controller`. | Added a `Readiness` button, `checkSystemReadiness()` frontend action, `/api/readiness` response aliases, and `system.readiness` UI-controller registration. |
| R5 | Dynamic tool creation allowed unsafe names such as path traversal tokens. | Reviewed `tool_factory/tool_creator/__init__.py`. | Added strict tool-name normalization, a regex allowlist, resolved-path checks, and centralized `_tool_file()` path construction. This preserves code-tool creation while preventing directory escape. |
| R6 | Plan-quality tools existed but were not available through the main agent registry. | Reviewed `AgenticSys._load_tools`. | Registered `PlanQualityScorerTool`, `OARConstraintCheckerTool`, and `PlanRefinementTool`. |
| R7 | Plan advice and optimization suggestions used local score/hotspot thresholds as if they were clinical conclusions. | Reviewed `web/server.py::_build_plan_advice` and `AgenticSys._handle_optimization_request`. | Converted them to observational advice and source-backed review language. |
| R8 | Legacy analytical/Gaussian dose functions were still present as callable implementations in `plans/utilizations.py`. | Searched for Gaussian/manual preview paths and traced the active myDoseNet path separately. | Replaced legacy analytical functions with short fail-closed compatibility stubs. Active planning remains on the v2/myDoseNet dose functions. |

## New Product Feature: System Readiness

The added readiness checklist is designed for both manual users and LLM-driven control.

Frontend entry:

- Input panel -> Manual Fine Planning -> `Readiness`
- Chat/LLM action target: `system.readiness`

Backend endpoint:

- `GET/POST /api/readiness`

Checklist coverage:

- CT loaded
- CTV segmentation available
- OAR segmentation available and named
- trajectories/needles and seeds available
- dose and DVH metrics current
- report data ready
- clinical KB source index present
- execution-tool policy state

The endpoint returns deterministic `checks`, `blockers`, `snapshot`, `execution_tools`, and `clinical_governance` fields. It does not ask the LLM to infer product state from chat history.

## Product Design Additions Implemented

From a product-manager perspective, the missing feature was not another planning algorithm; it was a pre-review operational gate. Users need a single answer to "Can I safely review/export this case now, and what is missing?" before generating reports or relying on agent advice.

Implemented design:

- Single-click readiness check for manual users.
- LLM-callable readiness action for conversational control.
- Deterministic backend state collection, independent of LLM response quality.
- Clinical-governance text that makes source-backed constraints explicit.

This improves usability without disturbing existing viewer coordinate logic, manual dose recomputation, 3D reconstruction, or planning-pipeline execution.

## Boundaries Preserved

- No CT, mask, dose-map, seed, needle, or 2D/3D coordinate transforms were changed.
- Manual dose recomputation remains routed through the trained model path; no Gaussian preview model was introduced.
- Legacy analytical/Gaussian function names are retained only as import-compatible stubs and raise `NotImplementedError`.
- Code/tool creation remains possible under the existing policy controls; the change only constrains tool names to the dynamic-tools directory.
- Shell/code execution policy was not broadened in this pass.

## Verification Plan

Completed static/target checks should include:

- Python compile check for changed Python modules.
- JavaScript parse check for the modified inline script.
- Unit smoke for unsafe dynamic tool names.
- Unit smoke for `OARConstraintCheckerTool` returning `NOT_CHECKED` when no source-backed constraint exists.
- Grep audit for active hardcoded clinical pass/fail wording in changed clinical-output paths.

End-to-end GPU planning with CT data is still required on the target RTX workstation before clinical demo use.
