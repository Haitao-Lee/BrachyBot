---
name: dicom_export
description: Export treatment plan to DICOM RT format
category: export
triggers:
  - DICOM
  - export
  - RT Structure
  - RT Plan
tool_sequence:
  - dicom_rt_exporter
parameters:
  output_dir: ./dicom_export
  include_dose: true
  include_structures: true
success_threshold: 0.9
version: "1.0.0"
---

# DICOM Export

Export treatment plan to DICOM RT format for clinical use.

## Exported Files

- **RT Structure Set**: CTV and OAR contours
- **RT Plan**: Seed positions and needle trajectories
- **RT Dose**: Dose distribution

## Parameters

- `output_dir`: Directory to save DICOM files
- `include_dose`: Include dose distribution
- `include_structures`: Include structure sets

## Output

DICOM files ready for import into treatment planning systems.

## Notes

- Follows DICOM RT standard
- Compatible with major TPS systems
- Includes all necessary metadata
