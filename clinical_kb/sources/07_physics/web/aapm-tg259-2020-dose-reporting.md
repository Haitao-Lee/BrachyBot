# AAPM TG-259 (2020) — Dose Specification, Prescription, and Reporting for Interstitial, Intracavitary, and Endorectal Brachytherapy

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=176
- **Citation**: Nag S, Demanes DJ, Hsu IC, Mohiuddin M, Nath R, Pieters BR, Pouliot J, Ryu J, Vlachaki MT. Proposed guidelines for image-based intracavitary brachytherapy for cervical cancer: Report of the Image-Guided Brachytherapy Working Group. Int J Radiat Oncol Biol Phys. 2004;60(4):1160-1172. [Note: GEC-ESTRO 2005 consensus was seminal, TG-259 2020 is the AAPM successor updating dose reporting for various BT modalities]
- **Document type**: AAPM Task Group Report
- **Date saved**: 2026-06-17

## Key Concepts

### Prescription Intent

- **Curative**: definitive therapy, target dose high
- **Boost**: supplemental to EBRT, target dose moderate
- **Palliative**: symptom relief, target dose lower
- **Adjuvant**: post-surgical prophylaxis, target dose site-specific

### Dose Specification Hierarchy

1. **Target volume dose**: D90, D98, V100, V150
2. **OAR dose**: D2cc, D1cc, D0.1cc, Dmax
3. **Total reference air kerma (TRAK)**: integral dose proxy
4. **Source activity-time product**: total radiation output

### Reporting Standards

For each BT application, report:
- **Total dose (prescribed)**: Gy (physical or EQD2)
- **Dose per fraction**: Gy/fx
- **Number of fractions**: n
- **Dose rate**: Gy/h at reference point
- **Dose at HR-CTV / CTV**: D90, D98, V100
- **OAR doses**: D2cc, D1cc, D0.1cc, max
- **Combined dose** (EBRT + BT): EQD2 with α/β
- **Plan parameters**: TRAK, total dwell time, number of sources/dwells

## EQD2 Calculations

- General formula: EQD2 = D · (d + α/β) / (2.0 + α/β)
  - D = total physical dose
  - d = dose per fraction
  - α/β = 10 Gy (tumor), 3 Gy (OAR)

### Example: HDR Cervical BT

- EBRT: 45 Gy / 25 fx (1.8 Gy/fx)
- BT: 4 × 7 Gy (HR-CTV D90)
- EQD2 for EBRT contribution at D90: 45 · (1.8+10)/(2+10) = 44.25 Gy EQD2(α/β=10)
- EQD2 for BT contribution at D90: 4 · 7 · (7+10)/(2+10) = 39.67 Gy EQD2(α/β=10)
- Total: 83.92 Gy EQD2 — within GEC-ESTRO target (≥ 85 Gy)

### For OAR (α/β=3):

- EBRT 45 Gy / 25 fx: EQD2 = 45 · (1.8+3)/(2+3) = 43.2 Gy
- BT 4 × 7 Gy to D2cc (rectum = 4 Gy/fx): 4 · 4 · (4+3)/(2+3) = 22.4 Gy
- Total rectum: 65.6 Gy EQD2 — at limit (GEC-ESTRO recommends < 65–75 Gy)

## Reporting Format

For consistency, the AAPM report recommends a structured template:

```
Patient: _____
Plan intent: Definitive / Boost / Palliative
EBRT: ____ Gy / ____ fx (technique)
BT modality: HDR / LDR / PDR
BT prescription: ____ Gy to ____ volume in ____ fractions
Dose per fraction: ____ Gy
Dose rate: ____ Gy/h
Source type: ____ (Λ = ____ cGy·h⁻¹·U⁻¹)
Total dwell time: ____ s
TRAK: ____ µGy·m²
HR-CTV D90: ____ Gy (physical) = ____ Gy EQD2(α/β=10)
OAR doses (D2cc): rectum ____ Gy EQD2(α/β=3); bladder ____; sigmoid ____
Total (EBRT + BT): ____ Gy EQD2
```

## Site-Specific Notes

- **Cervix**: HR-CTV D90 = 85–90 Gy EQD2; OAR D2cc < 65–75 Gy EQD2
- **Endometrium (vaginal cylinder)**: 5 mm surface dose 7 Gy × 3 fx (HDR boost) or 50 Gy LDR to 5 mm depth
- **Prostate HDR boost**: 10.5 Gy × 2 fx or 15 Gy × 1 fx to whole gland
- **Breast APBI interstitial**: 3.4 Gy × 10 fx (twice daily) to PTV_Eval D90
- **Skin surface**: 5 Gy × 8 fx (Leipzig/Valencia applicator)
