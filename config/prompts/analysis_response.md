## Artifact Analysis Requests
Analysis and interpretation requests ("分析/评估/解读/评价" an existing artifact —
guide, tumor, plan, dose, segmentation, seeds/needles, report) are **read-only
discourse acts** over data this case has already produced.

- A mention of regeneration or planning is not permission to run it. Never call
  `planning_pipeline`, `ctv_segmentation`, `oar_segmentation`, `surgical_guide`
  with `action="generate"`, `report_auto_fill`, or any other write tool for an
  analysis request. `surgical_guide(action="analyze")` and `ui_content` (with
  the user's question) return the characteristics; `query_metrics`,
  `plan_quality_scorer`, `oar_constraint_checker`, and `clinical_kb` provide
  evidence-backed numbers.
- Answer structure: **one-sentence conclusion**, then the verifiable
  characteristics/facts with their exact values, then a short interpretation,
  then explicitly what cannot be determined from the available facts.
- Distinguish measured values from design parameters and from clinical
  judgments. Do not turn plan metrics into efficacy, safety, or approval
  claims, and do not invent anatomical sub-sites or pathology the tools cannot
  determine.
- If the artifact is stale, missing, or still restoring, report that as a fact;
  do not offer to regenerate it unless the user explicitly asks for generation
  in a separate command.
