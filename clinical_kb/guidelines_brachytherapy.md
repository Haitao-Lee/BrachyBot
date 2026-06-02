# Brachytherapy Guidelines Knowledge Base

> Last updated: 2026-06-02
> 
> This knowledge base is structured for indexed retrieval by clinical_kb tool.
> Each section is independently searchable by topic/keyword.
> All data includes source attribution (organization, document, PMID/DOI).

---

## Index: Topic → Section Mapping

| Topic | Keywords | Section |
|-------|----------|---------|
| Prostate LDR dosimetry | prostate, LDR, I-125, Pd-103, seed, D90, V100 | §1 |
| Prostate HDR dosimetry | prostate, HDR, fractionation | §2 |
| Cervical cancer BT | cervix, cervical, tandem, ovoid, GEC-ESTRO | §3 |
| I-125 seed implant (Chinese) | 粒子植入, I-125, Chinese guidelines | §4 |
| TG-43 formalism | TG-43, dose rate, dosimetry formalism | §5 |
| OAR constraints | rectum, bladder, urethra, sigmoid, D2cc | §6 |
| Post-implant evaluation | post-implant, CT, edema, verification | §7 |

---

## §1. Prostate LDR Brachytherapy

**Sources:**
- AAPM TG-137 (2009): Nath R et al., Med Phys 36(11):5151-5161. PMID: 19994539. DOI: 10.1118/1.3233333
- ABS Consensus (2012): Davis BJ et al., Brachytherapy 11(1):6-19. PMID: 22221608. DOI: 10.1016/j.brachy.2011.07.005
- ABS Original (1999): Nag S et al., Int J Radiat Oncol Biol Phys 43(4). PMID: 10098428

### Prescription Doses (Monotherapy)

| Isotope | Dose | Source |
|---------|------|--------|
| I-125 | 144-145 Gy | TG-137, ABS 2012 |
| Pd-103 | 115-125 Gy | TG-137, ABS 2012 |

### Prescription Doses (Boost with EBRT)

| Isotope | Dose | Source |
|---------|------|--------|
| I-125 | 108-110 Gy | ABS 2012 |
| Pd-103 | 90-100 Gy | ABS 2012 |

### Dosimetric Goals

| Metric | Target | Clinical Significance | Source |
|--------|--------|----------------------|--------|
| D90 | >= 144 Gy (I-125 mono) | Strong predictor of biochemical control | TG-137, ABS 2012 |
| V100 | >= 95% | Prostate volume covered by Rx dose | TG-137 |
| V150 | < 50% | Limits excessive hot spots | TG-137 |
| V200 | < 20% | Limits extreme hot spots | TG-137 |

### Patient Selection (ABS 2012)

**Monotherapy indications:**
- Gleason <= 6, PSA < 10, stage T1-T2a
- Prostate volume < 60 cc
- IPSS < 20 (ideally < 15)

**Contraindications:**
- Large median lobe, severe obstruction (IPSS > 20), prior TURP (relative), life expectancy < 5 years

---

## §2. Prostate HDR Brachytherapy

**Source:** ABS HDR Prostate Update (2020), Brachytherapy.

### Dose Fractionation

| Regimen | Dose | Fractions | Source |
|---------|------|-----------|--------|
| Monotherapy | 27 Gy | 2 x 13.5 Gy | ABS 2020 |
| Monotherapy | 34-36 Gy | 4 x 8.5-9.0 Gy | ABS 2020 |
| Monotherapy | 36-38 Gy | 6 fractions | ABS 2020 |
| Boost | 13-15 Gy | 1 fx (after 45-50 Gy EBRT) | ABS 2020 |
| Boost | 21 Gy | 3 fx (after 40-45 Gy EBRT) | ABS 2020 |

---

## §3. Cervical Cancer Brachytherapy (GEC-ESTRO / ICRU 89)

**Sources:**
- GEC-ESTRO Part I (2005): Haie-Meder C et al., Radiother Oncol 74(3):235-245. PMID: 15763303. DOI: 10.1016/j.radonc.2004.12.015
- GEC-ESTRO Part II (2006): Potter R et al., Radiother Oncol 78(1):67-77. PMID: 16403584. DOI: 10.1016/j.radonc.2005.12.003
- ICRU Report 89 (2016): Prescribing, Recording, and Reporting Brachytherapy for Cancer of the Cervix

### Target Volumes

| Volume | Definition | Source |
|--------|-----------|--------|
| GTV | Visible/palpable tumor at BT | GEC-ESTRO I |
| HR-CTV | Entire cervix + presumed residual disease | GEC-ESTRO I, ICRU 89 |
| IR-CTV | HR-CTV + margin for microscopic disease | GEC-ESTRO II |

### Dose Goals (EQD2, combined EBRT + BT)

| Metric | Goal | Source |
|--------|------|--------|
| HR-CTV D90 | >= 85-90 Gy | GEC-ESTRO, ICRU 89 |
| IR-CTV D90 | >= 60-65 Gy | GEC-ESTRO, ICRU 89 |

### OAR Constraints (D2cc, alpha/beta=3)

| Organ | Constraint | Source |
|-------|-----------|--------|
| Bladder | <= 80-85 Gy | ICRU 89 |
| Rectum | <= 70-75 Gy | ICRU 89 |
| Sigmoid | <= 70-75 Gy | ICRU 89 |
| Small Bowel | <= 70-75 Gy | ICRU 89 |

---

## §4. Chinese I-125 Seed Implant Guidelines

**Sources:**
- National Health Commission PRC: "放射性粒子植入治疗技术管理规范" (2009 revised)
- Chinese Expert Consensus (2017): Chinese Journal of Radiation Oncology (中华放射肿瘤学杂志)
- CMA Urology Branch (2018): I-125 Prostate Consensus
- CSCO Thoracic Oncology (2019): I-125 Lung Consensus

### Indications (Chinese Expert Consensus 2017)

- Unresectable locally advanced solid tumors
- Post-op/post-RT local recurrence
- Residual disease after surgery
- Site-specific: prostate, lung, liver, head/neck, pancreas

### Prescription Doses by Site

| Site | Dose | Source |
|------|------|--------|
| Prostate | 110-145 Gy | Chinese Consensus 2017 |
| Lung | 80-120 Gy | Chinese Consensus 2017 |
| Liver | 80-120 Gy | Chinese Consensus 2017 |
| Head/Neck | 80-120 Gy | Chinese Consensus 2017 |
| Pancreas | 80-120 Gy | Chinese Consensus 2017 |

### Quality Metrics

| Metric | Target | Source |
|--------|--------|--------|
| D90 | >= 90% PD | Chinese Consensus 2017 |
| V100 | >= 90% target | Chinese Consensus 2017 |

### Imaging Guidance

- CT-guided percutaneous: standard for non-prostate sites
- Ultrasound guidance: prostate and superficial lesions
- 3D TPS planning: mandatory
- Template-guided: recommended for reproducibility

---

## §5. AAPM TG-43 Dosimetry Formalism

**Sources:**
- TG-43 Original (1995): Nath R et al., Med Phys 22(2):209-234. PMID: 7565352
- TG-43U1 Update (2004): Rivard MJ et al., Med Phys 31(3):633-674. PMID: 15070256. DOI: 10.1118/1.1646040
- TG-186 (2012): Rivard MJ et al., Med Phys 39(11):6381-6404. PMID: 23127081. DOI: 10.1118/1.4752416

### Dose Rate Equation

```
D_dot(r,theta) = S_K * Lambda * [G_L(r,theta)/G_L(r0,theta0)] * g_L(r) * F(r,theta)
```
- r0 = 1 cm, theta0 = pi/2 (reference point)
- Source: TG-43 (1995), TG-43U1 (2004)

### Core Parameters

| Parameter | Description | Source |
|-----------|-------------|--------|
| S_K (Air-Kerma Strength) | Source strength, unit: U | TG-43 |
| Lambda (Dose Rate Constant) | Dose rate at r0 per unit S_K | TG-43 |
| G(r,theta) (Geometry Function) | Inverse-square + geometry | TG-43 |
| g(r) (Radial Dose Function) | Scatter/attenuation correction | TG-43 |
| F(r,theta) (Anisotropy Function) | Angular dose variation | TG-43 |

### Key Recommendation

All clinical BT dose calculations SHALL use 2D formalism. TG-43 assumes homogeneous water medium — for heterogeneity corrections, use TG-186 MBDCA.

---

## §6. OAR Constraints Summary

### Prostate LDR (TG-137, ABS 2012)

| Structure | Constraint | Source |
|-----------|-----------|--------|
| Rectum V100 | < 1 cc | TG-137 |
| Rectum D2cc | < 145 Gy | TG-137 |
| Urethra D30 | < 150% Rx | TG-137 |
| Urethra Dmax | < 200% Rx | TG-137 |

### Cervical Cancer (ICRU 89)

| Structure | D2cc (EQD2) | Source |
|-----------|------------|--------|
| Bladder | <= 80-85 Gy | ICRU 89 |
| Rectum | <= 70-75 Gy | ICRU 89 |
| Sigmoid | <= 70-75 Gy | ICRU 89 |
| Small Bowel | <= 70-75 Gy | ICRU 89 |

---

## §7. Post-Implant Evaluation

**Sources:** TG-137 (2009), ABS 2012, Chinese Consensus 2017

### Timing

| Timing | Purpose | Source |
|--------|---------|--------|
| Day 0-1 | Acute edema assessment | TG-137, ABS 2012 |
| Day 30 | Delayed edema resolution | TG-137, ABS 2012 |

### Requirements

- CT slice thickness <= 3 mm (ABS 2012)
- Contour: prostate, rectum, urethra (ABS 2012)
- Report: D90, V100, OAR doses (TG-137)
- Compare with pre-implant plan (ABS 2012)
- DVH analysis mandatory (Chinese Consensus 2017)

---

> **Disclaimer:** For reference only. Always verify against original source documents.
> Clinical decisions must consider institutional protocols and individual patient factors.
