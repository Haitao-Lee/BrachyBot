# Brachytherapy Clinical Guidelines Knowledge Base

This file is the stable entry point for BrachyBot clinical guideline retrieval.
The full source-backed guideline digest is split into smaller topic files under
`clinical_kb/guidelines/` so each file stays reviewable while the clinical KB tool
continues to search the complete corpus.

## Split Guideline Corpus

| File | Topic |
|---|---|
| [`guidelines/01_foundations.md`](guidelines/01_foundations.md) | Foundations and topic tree |
| [`guidelines/02_gynecologic.md`](guidelines/02_gynecologic.md) | Gynecologic brachytherapy |
| [`guidelines/03_prostate_gu.md`](guidelines/03_prostate_gu.md) | Prostate and genitourinary brachytherapy |
| [`guidelines/04_breast.md`](guidelines/04_breast.md) | Breast brachytherapy |
| [`guidelines/05_head_neck_skin.md`](guidelines/05_head_neck_skin.md) | Head and neck / skin brachytherapy |
| [`guidelines/06_gastrointestinal.md`](guidelines/06_gastrointestinal.md) | Gastrointestinal brachytherapy |
| [`guidelines/07_other_sites.md`](guidelines/07_other_sites.md) | Other disease sites |
| [`guidelines/08_physics_dosimetry.md`](guidelines/08_physics_dosimetry.md) | Physics and dosimetry |
| [`guidelines/09_frameworks.md`](guidelines/09_frameworks.md) | Frameworks and society initiatives |
| [`guidelines/10_cross_reference_index.md`](guidelines/10_cross_reference_index.md) | Cross-cutting and master source index |

## Retrieval Notes

- Raw verified sources remain under `clinical_kb/sources/**/raw/*.md`.
- The `clinical_kb` tool searches both this entry file and every markdown file in
  `clinical_kb/guidelines/`.
- Clinical pass/fail thresholds must still come from retrieved KB evidence or an
  explicit case `plan_config`; this index is not a standalone treatment protocol.
