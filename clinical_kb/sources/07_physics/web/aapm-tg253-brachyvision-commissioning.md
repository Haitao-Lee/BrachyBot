# AAPM TG-253 — Brachytherapy Treatment Planning System Commissioning (2017/2018)

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=158
- **Citation**: Fraass B, Doppke K, Hunt M, Kutcher G, Starkschall G, Stern R, Van Dyke J. American Association of Physicists in Medicine Task Group 53: Quality assurance for clinical radiotherapy treatment planning. Med Phys. 1998;25(10):1773-1829. (TG-53 foundational; TG-253 BT-specific supplement)
- **Document type**: AAPM Task Group Report
- **Date saved**: 2026-06-17

## Commissioning Tests for BT TPS

### Geometric Accuracy

- Source position reconstruction accuracy
  - Tolerance: ± 1 mm
  - Test: known geometry phantom with markers, compute plan, compare reconstructed positions
- Applicator library accuracy
  - Digitization accuracy ≤ 0.5 mm
  - Compare with vendor specification
- Coordinate system alignment
  - DICOM origin must be consistent across scans and applicator library

### Dosimetric Accuracy

- **Single-source accuracy** vs published TG-43 parameters (Λ, g(r), F(r,θ))
  - Comparison: ≤ 2% in dose at r = 1–5 cm, θ = 90°
  - At oblique angles (θ = 0–30°): ≤ 5% (F(r,θ) most variable)
- **Multi-source / implant accuracy** vs published reference data
  - Use AAPM-developed test cases (e.g., Daskalov 1998 tests for ¹²⁵I)
- **Optimization algorithm accuracy**
  - Inverse planning: verify that optimizer can find global minimum
  - Dwell time gradient: verify continuous vs discrete step

### Plan Comparison

- Identical dose calculation between TPS and independent calculation
  - Hand calculation using TG-43 equation
  - Second TPS (different vendor)
  - Monte Carlo (for selected cases)
- Tolerance: ≤ 2% for individual dwell positions; ≤ 3% for plan total dose

### Applicator-Specific Tests

- HDR ring/tandem: comparison to clinical reference plans from GEC-ESTRO
- Interstitial templates: verify needle positions vs physical
- Surface applicators (Leipzig, Valencia, flap): verify surface dose at multiple points
- Ocular plaques: verify plaque dimensions and edge effects
- Intravascular BT: verify source centering, dose at vessel lumen

### Dose Distribution Display

- Isodose lines: 1-mm accuracy
- DVH: bin width 0.1–0.5 Gy
- Color wash: visual reference, not for measurement

### Hardware/Software QA

- Version control: track TPS version, dose calculation algorithm version
- License: ensure timely update of license
- Backup: daily backup of treatment plans and data
- User training documentation

## Acceptance Criteria Summary

| Test | Tolerance |
|------|-----------|
| Source position | ± 1 mm |
| Dose at reference point | ± 2% |
| Anisotropy at θ=0°, 30°, 60° | ± 5% |
| DVH integral | ± 2% |
| Total dose per fraction | ± 3% |
| Plan independence from system | ≤ 3% deviation |
