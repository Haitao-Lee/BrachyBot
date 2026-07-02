# Clinical KB and Prompt Alignment Audit

Date: 2026-07-02

## Scope

This audit reviewed the clinical knowledge-base retrieval path and every runtime prompt area that can affect clinical facts, dose standards, OAR constraints, treatment-protocol answers, or final clinical interpretation.

Reviewed areas:

- `clinical_kb/sources/**/raw/*.md`
- `tool_factory/clinical_kb/data/knowledge_base.json`
- `tool_factory/clinical_kb/__init__.py`
- `config/prompts/*.md`
- `config/prompts/multi_agent/*.md`
- `config/prompts/__init__.py`
- `agents/plan_reviewer.py`
- `agents/safety_guardian.py`
- `tool_factory/safety_validator/__init__.py`
- `tool_factory/plan_quality/clinical_standards.py`
- `tool_factory/plan_quality/plan_quality_scorer.py`
- report/training-facing interpretation code in `web/server.py`

## Problems Confirmed

| Area | Confirmed issue | Risk | Resolution |
|---|---|---:|---|
| Runtime system prompt | Stated that D90 is always a percentage of prescription dose. | High | Rewritten: D90 may be percent, model unit, Gy, or EQD2 depending on source/tool output. |
| Runtime system prompt | Embedded old citation examples and hardcoded threshold examples. | High | Rewritten to require `clinical_kb`/web/tool/config evidence for clinical facts. |
| Prompt module triggers | Conceptual brachytherapy questions could load planning workflow prompts. | High | Trigger rules now separate clinical knowledge questions from execution requests. |
| Medical safety prompts | Prompt-level tables and examples could be treated as clinical truth. | High | Replaced with KB-first policy and explicit no-invention rule. |
| PlanReviewer agent | Deterministic review used internal default OAR multipliers and target defaults as if clinically sourced. | High | Now checks only explicit `plan_config`/retrieved standards; missing standards become conditional. |
| SafetyGuardian agent | Claimed no hardcoded thresholds while using 0.80 coverage and 2x/3x prescription checks. | High | Rewritten to separate data-integrity sanity checks from clinical pass/fail constraints. |
| Report auto-fill | Embedded fixed "90%" clinical language and unsourced guideline references. | Medium | Rewritten to report actual metrics and require KB/config for clinical threshold interpretation. |
| Safety validator | Maintained a duplicate hardcoded standard table with stale source comments. | Medium | Runtime rules now come from the curated standards mirror; stale citation comments removed or downgraded to fallback-only notes. |
| KB source index | Runtime KB loaded JSON and one guideline file but ignored the raw source tree. | Medium | Runtime KB now indexes raw markdown source files and exposes `source_search`. |
| Source links | Some raw entries used `Local PDF` or generic search URLs. | Medium | Known local PDF entries were replaced with PubMed/DOI links; runtime prefers PMID/DOI/official URLs and downranks generic query links. |

## Runtime Policy After Fix

Clinical facts now follow this hierarchy:

1. `clinical_kb`
2. `web_search(search_type="clinical")` when KB coverage is missing or current-version status matters
3. Training data only as a labeled last resort

Clinical thresholds and claims must not come from prompt examples. If no source-backed threshold is available, the plan/reply is marked conditional or requires human review.

## Prompt Routing Behavior

Validated examples:

| User request type | Expected prompt modules |
|---|---|
| "介绍放射性粒子植入规划的好处" | `clinical_kb`; no planning workflow |
| "请执行放射性粒子植入规划" | planning workflow |
| "处方剂量和 OAR 剂量限制是多少" | `clinical_kb` |
| "请截图当前剂量分布" | visual/UI screenshot prompt |

This fixes the previous behavior where unrelated education questions could still carry the `ctv_segmentation -> oar_segmentation -> planning_pipeline` planning workflow prompt.

## Knowledge Sources Added or Normalized

Representative verified source links now available through the KB/runtime source index:

- Pancreatic I-125 guideline: [PubMed 39206973](https://pubmed.ncbi.nlm.nih.gov/39206973/)
- Pancreatic 3D-template I-125 paper: [PubMed 30581276](https://pubmed.ncbi.nlm.nih.gov/30581276/)
- AAPM TG-43U1: [PubMed 15070264](https://pubmed.ncbi.nlm.nih.gov/15070264/)
- AAPM TG-186: [AAPM report page](https://www.aapm.org/pubs/reports/detail.asp?docid=138)
- ICRU Report 89: [ICRU report page](https://www.icru.org/report/icru-report-89-prescribing-recording-and-reporting-brachytherapy-for-cancer-of-the-cervix/)
- Pediatric rhabdomyosarcoma brachytherapy guideline: [PubMed 38588921](https://pubmed.ncbi.nlm.nih.gov/38588921/)

## Files Changed

Key files:

- `config/prompts/system_prompt.md`
- `config/prompts/__init__.py`
- `config/prompts/clinical_kb.md`
- `config/prompts/medical_safety.md`
- `config/prompts/tool_routing.md`
- `config/prompts/multi_agent/plan_reviewer.md`
- `config/prompts/multi_agent/safety_guardian.md`
- `agents/plan_reviewer.py`
- `agents/safety_guardian.py`
- `tool_factory/clinical_kb/__init__.py`
- `tool_factory/clinical_kb/data/knowledge_base.json`
- `tool_factory/safety_validator/__init__.py`
- `tool_factory/plan_quality/clinical_standards.py`
- `web/server.py`
- `README.md`

## Validation

Commands run:

```bash
python -m py_compile config/prompts/__init__.py agents/plan_reviewer.py agents/safety_guardian.py tool_factory/clinical_kb/__init__.py tool_factory/plan_quality/clinical_standards.py tool_factory/plan_quality/plan_quality_scorer.py tool_factory/safety_validator/__init__.py web/server.py
```

Prompt-routing smoke tests verified:

- Knowledge explanation loads `clinical_kb`.
- Knowledge explanation does not load planning workflow.
- Execution planning request loads planning workflow.
- Dose-constraint question loads `clinical_kb`.

Clinical KB smoke tests verified:

- `standards` for pancreatic sources returns PubMed-backed sources.
- `source_search` for pancreatic iodine seed guideline returns pancreatic guideline/paper sources.
- `search` for pediatric rhabdomyosarcoma brachytherapy returns PubMed 38588921.

## Remaining Boundaries

- `tool_factory/plan_quality/clinical_standards.py` remains a deterministic mirror for fast scoring. It is not a citation source; user-facing clinical citations should come from `clinical_kb`.
- Some legacy fallback tables remain in `safety_validator` for compatibility, but the main runtime path generates rules from the curated standards mirror.
- Some old documentation/benchmark examples may still contain benchmark target values. They are not loaded as runtime clinical prompts and should not be used as clinical references.

## Operational Rule For Future Changes

When adding any new clinical prompt, agent, report template, validator, or UI interpretation:

1. Do not embed new clinical thresholds directly in prompt text.
2. Add or verify the source in `clinical_kb`.
3. Return clickable source links in user-facing clinical answers.
4. If a deterministic runtime mirror is needed, document it as a mirror and point citations back to `clinical_kb`.
