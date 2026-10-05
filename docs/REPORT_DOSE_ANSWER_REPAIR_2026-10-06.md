# Report-dose answer and visual-evidence repair

## Reproduced source-level failure

A question about dose distribution and report completeness invoked `ui_content(report)` and `query_metrics(dose_metrics)`. The browser then ran a parent-bound visual child. On a child failure, a location-only fallback treated saved report figures as object-location evidence, discarded same-turn read results, and claimed marked captures despite absent object manifests. A failed final trace could consequently coexist with success-shaped location prose.

## Contract repair

- Explanatory report/chart evidence is not routed to an object-location fallback. A failed interpretation retains same-turn results and explicitly identifies the uncompleted interpretation. The error trace remains an error; a partial answer is not relabelled as successful image interpretation.
- SSE and JSON visual-child contexts carry both the parent read response and the browser's content summary. HTTP, SSE error, and exception fallbacks all retain this context, independently of a multi-intent classification.
- Report summary reads actual Session-owned populated report fields, enumerates missing fields, counts populated organ dose rows (zero is valid), and compares D90/D95 with available current physical-dose metrics. It does not guess percentage units, claim completeness, certify clinical acceptability, or infer freshness from image availability.
- The visual prompt explicitly separates explanatory figures, spatial observations, numerical metrics, and report completeness/freshness. An empty object manifest is not proof that an explanatory report object is missing.
- Asset revisions advance together. No patient geometry, prescription, dose, report contents or clinical thresholds are changed.

## Scope and limits

This is a code and synthetic regression repair, not a replay of the screenshot's authenticated case. It does not prove which provider failure caused that historic child's failure, whether that report was up to date, or where its cold/hot dose regions actually were. No clinical judgement follows from Dmax alone. The internal prompt remains bounded to the existing selected-image limit; omitted figures are not treated as fully analysed. Runtime restart is intentionally not performed because LAN and public release are independent deployments.

The pre-existing modification of `web/routes/planning_routes.py` is unrelated and preserved.

## Validation

The final targeted Python contracts passed (58 tests; three third-party import warnings). Native-JS report-answer, screenshot delivery, visual-location/visibility and turn-lifecycle checks passed. The existing native-JS screenshot fixture exposed a pre-existing missing `uiActionTasks` stub, confirmed in the pre-change product source; the fixture is updated rather than changing working production scheduling. A new report-answer regression covers explanatory failure in Chinese/English, retained dose/report values, true zero versus missing fields, organ-row counting, dose mismatch, and all transport error context paths. Both changed JS bundles pass syntax checks; `git diff --check` passes. Validation is synthetic and does not certify an authenticated patient-case replay. No full repository, GPU or clinical-physics suite was run.
