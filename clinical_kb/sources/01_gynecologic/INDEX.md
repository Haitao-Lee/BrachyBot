# Gynecologic Brachytherapy — Clinical Knowledge Base

**Category:** 01_gynecologic
**Last updated:** 2026-06-17
**Scope:** Cervical (definitive + postoperative), vaginal, vulvar, endometrial (VCB), IGABT planning, dose constraints, applicators, image guidance.

> ## ⚠️ Verification Status
> The web/` source files in this folder were **reconstructed from training-data knowledge** of the cited publications, not live-fetched. All pubmed/ABS/NCCN/ESTRO/GEC-ESTRO/ICRU domains were blocked in the build environment on 2026-06-17. Conceptual content, society names, trial names (EMBRACE-I/II, PORTEC-2/3, etc.), and standard dose values are reliable; specific PMIDs, exact author lists, and granular numerical claims should be re-verified against the cited primary source. See the main `guidelines_brachytherapy.md` → "Verification Status" section for full disclosure.

## Source Index (16 sources, organized by topic)

### Cervical Cancer — Definitive IGABT (core)

| # | File | Topic | Year | Source type |
|---|---|---|---|---|
| 1 | [gec-estro-cervix-2018.md](web/gec-estro-cervix-2018.md) | GEC-ESTRO/ABS IGRT/ART consensus, HR-CTV/IR-CTV/GTV | 2018 | Multidisciplinary consensus |
| 2 | [embrace-cervix-hr-ctv-mri.md](web/embrace-cervix-hr-ctv-mri.md) | Haie-Meder / Dimopoulos MRI target definition | 2005, 2012 | Foundational GEC-ESTRO papers |
| 3 | [embrace-i-pivotal-2021.md](web/embrace-i-pivotal-2021.md) | EMBRACE-I pivotal 5-yr LC 92%, OS 74% | 2021 | Multicenter prospective cohort |
| 4 | [embrace-ii-protocol.md](web/embrace-ii-protocol.md) | EMBRACE-II protocol — tighter planning aims, 90 Gy HR-CTV D90 | 2018/2024 | RCT protocol + 2024 outcomes |
| 5 | [embrace-i-secondary-2022.md](web/embrace-i-secondary-2022.md) | Dose-response for OARs: rectum, bladder, vagina, uterus | 2020-2022 | EMBRACE-I secondary analyses |
| 6 | [embrace-cervix-prognostic-factors.md](web/embrace-cervix-prognostic-factors.md) | Stage / size / nodal / D90 / time prognostic factors | 2015-2024 | EMBRACE prognostic analyses |
| 7 | [abs-cervix-2018.md](web/abs-cervix-2018.md) | ABS 2018 cervical cancer BT guideline | 2018/2022 | ABS consensus |
| 8 | [nccn-cervical-v4-2024.md](web/nccn-cervical-v4-2024.md) | NCCN cervical cancer v4.2024 BT recommendations | 2024 | NCCN guideline |
| 9 | [icru-report-89-gyn.md](web/icru-report-89-gyn.md) | ICRU 89 — dose reporting standard for gyn BT | 2016 | ICRU report |

### Applicators (IC, IS, IC+IS)

| # | File | Topic | Year | Source type |
|---|---|---|---|---|
| 10 | [ic-is-hybrid-applicators-2020.md](web/ic-is-hybrid-applicators-2020.md) | Vienna, T&O + needles, ring, 3D-printed applicators | 2006-2020 | Multi-paper review |

### Postoperative & Adjuvant

| # | File | Topic | Year | Source type |
|---|---|---|---|---|
| 11 | [cervix-postop-bt-evidence.md](web/cervix-postop-bt-evidence.md) | GOG 92/99, Sedlis criteria, post-op VCB | 1999, 2003 | RCT (GOG) |
| 12 | [portec-3-endometrial-bt.md](web/portec-3-endometrial-bt.md) | PORTEC-2 (VCB vs EBRT) and PORTEC-3 (chemoRT) | 2010, 2018 | RCT (PORTEC) |
| 13 | [gec-estro-icru-vcb-2024.md](web/gec-estro-icru-vcb-2024.md) | GEC-ESTRO/ESTRO/ABS 2024 endometrial BT consensus | 2024 | Multidisciplinary consensus |

### Other Gynecologic Sites

| # | File | Topic | Year | Source type |
|---|---|---|---|---|
| 14 | [abs-vaginal-cancer-2019.md](web/abs-vaginal-cancer-2019.md) | ABS primary vaginal cancer BT guideline | 2019 | ABS consensus |
| 15 | [abs-vulvar-cancer-2019.md](web/abs-vulvar-cancer-2019.md) | ABS vulvar BT guideline (interstitial, surface) | 2019 | ABS consensus |

### Pulsed-Dose-Rate

| # | File | Topic | Year | Source type |
|---|---|---|---|---|
| 16 | [pdr-gyn-2005.md](web/pdr-gyn-2005.md) | GEC-ESTRO PDR recommendations | 2004-2005 | GEC-ESTRO physics |

## Key Numbers (consolidated)

### HR-CTV D90 (cumulative EQD2, alpha/beta=10)
- Small tumors (<4 cm): **85 Gy** is acceptable, aim 90 Gy
- Large tumors (>4 cm): **90-95 Gy** is the planning aim

### OAR Constraints (cumulative EQD2, alpha/beta=3) — GEC-ESTRO / ABS / EMBRACE
| OAR | Aim | Upper limit |
|---|---|---|
| Bladder D2cc | <= 80 Gy | 90 Gy |
| Rectum D2cc | <= 60-65 Gy | 75 Gy |
| Sigmoid D2cc | <= 60-65 Gy | 75 Gy |
| Bowel D2cc | <= 60-65 Gy | 75 Gy |
| Vagina PIBS+2 cm | <= 120 Gy | 140 Gy |

## Common HDR Schedules (after 45 Gy EBRT)
- 4 x 7 Gy HR-CTV D90 (most common, 28 Gy total, EQD2 ~ 36 Gy)
- 3 x 8.5 Gy HR-CTV D90
- 5 x 6 Gy HR-CTV D90
- 6 x 5 Gy (for VCB)

## Applicator Selection Quick Guide
| Scenario | Applicator |
|---|---|
| Small tumor, good response | T&O or T&R |
| Large HR-CTV, distal parametrium | IC+IS (Vienna, T&O+needles) |
| Bulky or barrel cervix | T&R or T&O with needles |
| Narrow vagina | Ring + needles (no ovoids) |
| Extensive parametrial disease | Interstitial (MUPIT, Syed) |
| Post-hysterectomy (cuff) | Cylinder (single or multichannel) |
| Vulvar, recurrent | Interstitial (perineal template) |
| Vaginal, primary | Multichannel cylinder + IS |
