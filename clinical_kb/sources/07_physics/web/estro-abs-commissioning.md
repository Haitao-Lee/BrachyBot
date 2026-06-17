# ESTRO/ABS/GEC-ESTRO Joint Guidelines for Commissioning, QA, and Source Calibration (Various)

- **URLs**:
  - https://www.astro.org/Patient-Care-and-Research/Clinical-Practice-Statements (ASTRO clinical statements)
  - https://www.estro.org/About/ESTRO-organisation (ESTRO)
  - https://www.americanbrachytherapy.org/ (ABS)
- **Citations**:
  - ABS (American Brachytherapy Society). Various consensus guidelines for cervix, prostate, breast, head/neck, skin, etc. 2012-2022.
  - ESTRO (European Society for Radiotherapy & Oncology). Various consensus guidelines via GEC-ESTRO working group.
- **Document type**: Society consensus guidelines
- **Date saved**: 2026-06-17

## ESTRO/ABS Joint Statements

### Source Calibration and Traceability

- All BT sources should be calibrated at a primary or secondary standards laboratory (NIST, NRC, NPL, PTB, ARPANSA, LNHB, ENEA, etc.)
- Well-type ionization chamber is the recommended clinical instrument
- Calibration should be performed after each source exchange (HDR ¹⁹²Ir) or as required (LDR seeds)
- Independent verification by a second physicist strongly recommended

### Applicator-Specific Recommendations

| Modality | Applicator | Special Physics |
|----------|------------|-----------------|
| Cervical IC | Ring + tandem, ovoid + tandem, mold | MRI-compatible preferred |
| Cervical IC+IS | Venezia, Utrecht | MBDCA for full benefit |
| Endometrial | Cylinder (multichannel) | Surface dose uniformity |
| Prostate LDR | Stranded seeds, loose seeds | Interseed attenuation (MBDCA) |
| Prostate HDR | Real-time US-guided | Position tracking per dwell |
| Breast APBI | SAVI, Contura, MammoSite, interstitial | Skin spacing ≥ 7 mm |
| Skin | Leipzig, Valencia, flap | Surface dose calibration |
| H&N | Interstitial catheters, molds | Heterogeneous anatomy |
| Ocular | ¹⁰⁶Ru / ¹²⁵I plaque | Plaque-specific dose calc |

### QA Frequency Summary

| Test | Frequency | Tolerance |
|------|-----------|-----------|
| Source output | Daily | ± 3% |
| Source position | Weekly | ± 1 mm |
| Dwell time | Weekly | ± 1% |
| Timer | Weekly | ± 0.5 s |
| Survey | Monthly | Background |
| Full QA | Quarterly | Per TG-148 |
| TPS check | After each update | Per TG-253 |
| Calibration | Annually (well chamber) | ± 1% |

## Common Challenges in Clinical Implementation

1. **Adaptive re-planning requires real-time imaging** (CBCT, MR)
2. **Multi-modality image registration** (CT + MR + US) requires QA
3. **In-vivo dosimetry** is difficult for BT (miniature detectors in sensitive locations)
4. **Tissue heterogeneity** requires MBDCA
5. **Shielded applicators** require vendor-specific dose calculation
6. **Source exchange logistics** (HDR ¹⁹²Ir every 3 months)

## Recommendations for New Programs

1. Start with simple cases (e.g., tandem/ring for cervix, cylinder for endometrium)
2. Progress to interstitial templates (prostate, breast, GYN)
3. Establish QA program from day 1
4. Document all source calibrations and TPS commissioning
5. Peer review for first 50 cases
6. Attend IAEA / AAPM / ESTRO training courses
7. Use published test cases (AAPM, GEC-ESTRO) for commissioning
