# Report Context Enhancement - 2026-07-05

## Request

After a planning run completes, the final BrachyBot reply and generated report
must include a richer clinical-planning context:

- tumor size and geometric extent;
- tumor location expressed in centimeters;
- edge or shape regularity;
- malignancy or grade when the user provides pathology/staging context;
- prescription dose rationale, using explicit case configuration first and
  source-backed clinical knowledge when no case-specific rationale is provided.

## Implementation

### Shared report context helper

Added `tool_factory/report_context.py` as a read-only report helper. It derives
deterministic context from current agent memory without mutating planning state.

The helper computes:

- CTV volume in cm3;
- voxel count;
- bounding-box dimensions in X/Y/Z centimeters;
- maximum bounding diameter and equivalent spherical diameter;
- CTV centroid in world coordinates, expressed in centimeters;
- CTV centroid offset from the CT volume center, expressed in centimeters;
- bounding-box fill ratio and boundary voxel ratio;
- a conservative shape regularity descriptor.

The helper deliberately does not infer tumor biology from CT geometry alone.
If `plan_config` contains pathology, histology, malignancy, malignancy grade, or
tumor stage, that text is reported. Otherwise the report states that malignancy
cannot be inferred from planning CT/CTV geometry and requires pathology,
staging, enhancement pattern, and clinician diagnosis.

### Prescription dose rationale

Prescription rationale now follows this priority order:

1. Explicit user or case configuration:
   `plan_config.prescription_dose_gy`, `rx_gy`, `prescribed_dose_gy`,
   `in_lowest_energy`, `prescription_dose`, or `prescribed_dose`.
2. Existing dose metrics, when available.
3. The existing BrachyBot planning convention of normalized prescription
   `1.0 = 120 Gy` for the myDoseNet dose scale.

Case-specific rationale text can be supplied through:

- `plan_config.prescription_rationale`
- `plan_config.dose_rationale`
- `plan_config.rx_reason`

Source URLs can be supplied through:

- `plan_config.prescription_source_urls`
- `plan_config.source_urls`

When explicit text is absent, the helper retrieves matching source URLs and
target criteria from `tool_factory/clinical_kb/data/knowledge_base.json`.

### Final BrachyBot reply

`AgenticSys.BrachyAgent._build_planning_report()` now embeds:

- Tumor Imaging Summary under CTV Segmentation.
- Prescription Dose Rationale under Dose Distribution.

The agent passes runtime `self.config` as a fallback for `plan_config`, so
report text still reflects dose settings that live in the active agent config
rather than memory only.

### Web report auto-fill and export

`web/server.py` now adds structured report context into:

- `/api/report/auto-fill`:
  - `case.tumorImagingAssessment`
  - `planning.prescriptionRationale`
- `/api/export/report`:
  - `tumor_imaging_assessment`
  - `prescription_rationale`
  - `narrative_markdown`

The export route now defaults to `output/report.json`, uses `output/report.html`
for HTML when no path is supplied, and serializes non-standard values with a
safe fallback.

### Report generator tool

`tool_factory/report_generator/__init__.py` now includes:

- Tumor Imaging Assessment section when structured tumor context is supplied.
- Prescription Dose Rationale section when structured dose-rationale context is
  supplied.
- Safer numeric formatting so missing CTV volume or report fields do not crash
  report generation.

## Clinical Boundaries

The new fields are planning-support descriptors, not a signed diagnosis.

- Shape regularity is derived from the CTV mask and should be reviewed against
  original imaging by a clinician.
- Malignancy degree is reported only when pathology/staging context exists.
  Otherwise the report explicitly says that the information is not inferable
  from planning CT geometry alone.
- Dose rationale must be confirmed by the treating radiation oncologist and
  physicist before clinical use.

## Source Model

The implementation is designed to work with the existing clinical knowledge
base. Relevant external authority examples include:

- AAPM TG-43/TG-43U1 source-dosimetry guidance.
- ABS prostate brachytherapy consensus material.
- Chinese expert consensus and guideline material for permanent I-125
  pancreatic seed implantation.

## Verification

Validation performed:

- targeted Python compile check for modified Python files;
- report-context smoke test using an in-memory CTV mask and plan config;
- `git diff --check` whitespace validation.

