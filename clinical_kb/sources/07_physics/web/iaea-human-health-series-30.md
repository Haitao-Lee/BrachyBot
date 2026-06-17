# IAEA Human Health Series 30 (2013) and IAEA-TECDOC-1631 — Commissioning and QA for BT Facilities

- **URLs**:
  - https://www-pub.iaea.org/MTCD/Publications/PDF/Pub1538_web.pdf (IAEA Human Health Series 30 — "The Transition from 2-D Brachytherapy to 3-D High Dose Rate Brachytherapy")
  - https://www-pub.iaea.org/MTCD/Publications/PDF/TE_1631_web.pdf (IAEA-TECDOC-1631)
- **Citation**: International Atomic Energy Agency. The Transition from 2-D Brachytherapy to 3-D High Dose Rate Brachytherapy. IAEA Human Health Series 30. Vienna: IAEA; 2015.
- **Document type**: IAEA Technical Report (international guideline)
- **Date saved**: 2026-06-17

## Scope

This IAEA publication is the international reference for transitioning a BT program from 2D (point-based) to 3D image-guided brachytherapy, with focus on:

- HR-CTV and OAR contouring on CT/MRI
- Dose prescription to volumes
- Plan optimization (graphical + inverse)
- QA program establishment
- Staff training and education

## Key Recommendations

### Infrastructure

- Multidisciplinary team: radiation oncologist, medical physicist, dosimetrist, radiation therapist, nurse
- Image-guided: CT-simulator (≥ 16 slice), MRI access (preferably 3T with dedicated BT protocol)
- Afterloader: ¹⁹²Ir HDR with ≥ 24 channels
- TPS with image fusion and inverse planning
- Well-chamber and electrometer (NIST-traceable)
- QA phantoms: 2D film phantom, 3D anthropomorphic phantom

### Treatment Planning Process

1. **CT simulation**: 1-3 mm slice thickness, in vacuo immobilization
2. **MR simulation** (T2-weighted): 1-2 mm slice, ≤ 30 min from applicator insertion
3. **Image registration**: CT-MR fusion based on applicator and bony anatomy
4. **Contouring**: GTV, HR-CTV, IR-CTV, OARs (bladder, rectum, sigmoid, bowel)
5. **Loading**: IC and/or IS per applicator choice
6. **Optimization**: graphical + inverse, per institutional protocol
7. **Prescription**: GEC-ESTRO 2018 (HR-CTV D90 = 85-90 Gy EQD2)
8. **Plan review**: physics check, dosimetry check, peer review
9. **Delivery**: image-guided (CBCT or fluoroscopy pre-treatment)
10. **Adaptive**: re-plan if anatomy changes significantly

### Quality Assurance Levels

- **Daily**: output constancy, door interlock, survey meter
- **Weekly**: source position, dwell time, timer
- **Monthly**: full geometric and dosimetric check
- **Quarterly**: comprehensive QA
- **Annually**: full system audit
- **Source exchange**: full calibration

### Training Requirements

- Radiation oncologist: dedicated BT training (≥ 6 months or equivalent)
- Medical physicist: TG-43 formalism, MBDCA, applicator-specific physics
- Dosimetrist: contouring, plan generation, optimization
- Therapist: applicator handling, patient setup
- Nurse: applicator care, patient support

## Common Pitfalls (IAEA Reports)

1. **Applicator digitization error** — use vendor library; check offset
2. **Source-to-source distance calculation error** in TPS
3. **Image registration error** between CT and MR (esp. with titanium applicators)
4. **Dose escalation without adequate OAR sparing**
5. **Neglecting EBRT contribution** to OAR in combined plan
6. **Insufficient time gap** between fractions (< 6 h interferes with sublethal damage repair)
