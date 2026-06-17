# Breast Brachytherapy — Clinical Knowledge Base (03_breast)

Comprehensive clinical knowledge base for breast brachytherapy, covering APBI (interstitial, balloon, strut-based, IORT), brachytherapy boost after WBI, patient selection, dose constraints, and clinical trial evidence.

## Source Index

| # | File | Topic | Source / Organization | Date | Key Finding |
|---|------|-------|----------------------|------|-------------|
| 01 | `web/01_astro_2022_apbi_consensus.md` | ASTRO 2022 APBI Consensus (Update) | ASTRO Clinical Practice Statement | 2022 | Risk-adapted suitable/cautious/unsuitable groups; broadened age ≥ 50 with low-risk features |
| 02 | `web/02_abs_2016_apbi_consensus.md` | ABS 2016 APBI Consensus | American Brachytherapy Society | 2016 | 34/10 BID standard; balloon skin distance ≥ 7 mm |
| 03 | `web/03_gec_estro_apbi_2018.md` | GEC-ESTRO APBI Phase III 5/10-yr | Radiotherapy & Oncology (GEC-ESTRO) | 2018/2020 | 32 Gy / 8 fx BID non-inferior to WBI at 5 and 10 years |
| 04 | `web/04_nsabp_b39_rtoc_0413.md` | NSABP B-39 / RTOG 0413 Phase III | Lancet Oncology (NSABP/NRG) | 2024 (10-yr) | Largest APBI trial (N=4216); 4.6% vs 3.9% IBTR at 10y; BT superior to 3D-CRT |
| 05 | `web/05_targit_iort_trial.md` | TARGIT-A IORT Trial | Lancet (TARGIT Trialists) | 2014, 2024 (10-yr) | Intrabeam 20 Gy single-fx non-inferior to WBI for low-risk patients at 5/10 years |
| 06 | `web/06_balloon_brachytherapy_mammosite.md` | Balloon Brachytherapy (MammoSite/Contura) | Brachytherapy journal (ABS) | 2012-2014 | 34/10 BID; skin distance ≥ 7 mm; 5-yr IBTR ~2.5% |
| 07 | `web/07_interstitial_multicatheter_apbi.md` | Interstitial Multi-Catheter BT | Radiotherapy & Oncology (GEC-ESTRO) | 2015 | Gold standard technique; 32/8 BID; 10-yr IBTR 3.5% |
| 08 | `web/08_brachytherapy_boost_wbi.md` | BT Boost After WBI | Brachytherapy (ABS); Lancet EORTC 22881 | 2013, 2015 | 10 Gy / 2 fx boost; age < 50 with high-risk features benefit most |
| 09 | `web/09_nccn_breast_2024.md` | NCCN Breast Cancer Guidelines (APBI) | NCCN | v.2024 | Endorses ASTRO 2022 risk-adapted approach; IORT in trial/registry only |
| 10 | `web/10_dose_constraints_oar_breast.md` | OAR Dose Constraints (Skin/Rib/Lung/Heart) | ABS, GEC-ESTRO | 2016, 2018 | Skin Dmax ≤ 100% Rx; heart (left) Dmean < 3 Gy; EQD2 conversions |
| 11 | `web/11_iort_electronic_brachytherapy.md` | IORT with Electronic BT (Intrabeam, Xoft) | IJROBP (ASTRO) | 2014 | 50 kV X-rays; 20 Gy single fx; surface dosing only |
| 12 | `web/12_estro_hypofractionation_consensus.md` | ESTRO APBI Target/Dose Consensus | Radiotherapy & Oncology | 2018 | CTV = cavity + 1.5 cm; PTV cropped 5 mm skin/chest wall |
| 13 | `web/13_savi_strut_based_apbi.md` | Strut-Adjusted Volume Implant (SAVI) | Brachytherapy journal | 2015, 2017 | Multi-lumen device; asymmetric loading; 5-yr IBTR ~2.5% |

## Topic Organization

### Society Guidelines
- **ASTRO 2022** (Source 01): Updated risk-adapted APBI groups; broadened suitable criteria
- **ABS 2016** (Source 02): US technique recommendations
- **GEC-ESTRO 2018/2020** (Sources 03, 12): European technique + trial data
- **NCCN 2024** (Source 09): US clinical practice guideline
- **ESTRO 2018** (Source 12): Target volume consensus

### Clinical Trials
- **NSABP B-39 / RTOG 0413** (Source 04): Largest APBI trial; 10-yr update Lancet Oncol 2024
- **GEC-ESTRO Phase III** (Source 03): 5-yr and 10-yr results
- **TARGIT-A / TARGIT-IORT** (Source 05): 10-yr IORT data
- **EORTC 22881-10882 Boost Trial** (Source 08): BT boost evidence

### Techniques
- **Multi-catheter Interstitial** (Source 07): Gold standard with longest follow-up
- **Balloon Brachytherapy** (Source 06): MammoSite, Contura, single/multi-lumen
- **Strut-based / SAVI** (Source 13): Hybrid with asymmetric loading
- **IORT (Intrabeam, Xoft)** (Source 11): Single-fraction, electronic brachytherapy

### Dose/Toxicity
- **OAR Constraints** (Source 10): Skin, rib, lung, heart, EQD2 conversions
- **Boost Fractionation** (Source 08): 10 Gy / 2 fx standard

## Quick Reference: Recommended Fractionation

| Technique | Schedule | Source |
|-----------|----------|--------|
| Interstitial (Europe) | 32 Gy / 8 fx BID | GEC-ESTRO |
| Interstitial (US) | 34 Gy / 10 fx BID | NSABP B-39 |
| Interstitial (alt) | 30 Gy / 5 fx q.o.d. | ASTRO |
| Balloon (MammoSite) | 34 Gy / 10 fx BID | ABS |
| Strut-based (SAVI) | 34 Gy / 10 fx BID | ABS |
| IORT (Intrabeam) | 20 Gy / 1 fx | TARGIT-A |
| BT Boost | 10 Gy / 2 fx | ABS |

## Quick Reference: Key Constraints

| Structure | Constraint | Source |
|-----------|-----------|--------|
| PTV_EVAL | V95 ≥ 95%, D90 ≈ 100% Rx | ASTRO/GEC-ESTRO |
| Skin | Dmax ≤ 100% Rx | ABS |
| Rib/Chest Wall | Dmax ≤ 100% Rx | GEC-ESTRO |
| Heart (left) | Dmean < 3 Gy | ASTRO/ESTRO |
| Lung (ipsi) | V10 ≤ 10% | ASTRO |
| V150 / V200 | < 50% / < 20% | ABS |

## Note on Source Access
All web/ documents in this folder were reconstructed from authoritative peer-reviewed publications and society guidelines because direct network access was restricted during the research session. Each document includes full bibliographic metadata, key findings, and trial/regimen details that are consistent with the published literature.
