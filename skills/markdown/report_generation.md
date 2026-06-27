---
name: report_generation
description: Generate treatment plan report
category: export
triggers:
  - report
  - generate report
tool_sequence:
  - report_generator
parameters:
  format: pdf
  include_images: true
  include_dvh: true
success_threshold: 0.9
version: "1.0.0"
---

# Report Generation

Generate comprehensive treatment plan report.

## Report Contents

- Patient information
- CT image details
- CTV and OAR volumes
- Dose metrics (V100, D90, etc.)
- DVH curves
- Seed positions
- Trajectory information
- Quality assessment

## Parameters

- `format`: Output format (pdf, html, json)
- `include_images`: Include CT slices with contours
- `include_dvh`: Include DVH curves

## Output

Formatted report ready for clinical review.
