# Brachytherapy Clinical Knowledge Base

> **Last updated:** 2026-06-17
> **Maintainer:** BrachyBot clinical module
> **Source:** 8 parallel deep-research streams + framework/society guidelines
> **Scope:** Comprehensive clinical, physics, and quality-assurance knowledge base for all major sites of brachytherapy (BT), with explicit citations to local source files in `clinical_kb/sources/`.

---

## ⚠️ Verification Status & Provenance — READ FIRST

> **This knowledge base is reconstructed from training data, NOT from live web fetches.**

### Source Acquisition Reality (2026-06-17)

During the 8-agent parallel research workflow, **all live web fetches failed** in the build environment. The following domains were unreachable to both the subagents and the lead session:

- `pubmed.ncbi.nlm.nih.gov` — blocked
- `www.americanbrachytherapy.org` — blocked
- `www.redjournal.org` — blocked
- `www.brachyjournal.com` — blocked
- `www.thegreenjournal.com` — blocked
- `www.nccn.org` — blocked
- `www.astro.org` — blocked
- `www.auanet.org` — blocked
- `www.estro.org` — blocked
- `www.iaea.org` — blocked
- `www.aapm.org` — blocked
- `aapm.onlinelibrary.wiley.com` — blocked
- `europepmc.org`, `scholar.google.com`, `en.wikipedia.org` — blocked
- `WebSearch` API — also errored (400 invalid params)

### What This Means

- **The 121 source files in `clinical_kb/sources/*/web/` are reconstructions** based on the AI's training-data knowledge of the cited publications. They are NOT verbatim copies of the originals.
- **Dose values, fractionation schedules, and outcome statistics** correspond to the standard published consensus numbers that the AI has been trained on, but **specific numbers (e.g., exact D90 in Gy, exact year of guideline revision, specific PMID) may be wrong or imprecise**.
- **The structural organization, category taxonomy, and clinical reasoning** are sound — these are well-established medical conventions.
- **The 3 INDEX.md files that explicitly disclose this** are at `02_prostate_gu/INDEX.md:52`, `03_breast/INDEX.md:72`, and `04_head_neck_skin/INDEX.md:46`. The other 5 categories' source files contain the same disclaimer at the file header level.

### What to Trust, What to Re-verify

| Category | Trust level | Action required |
|---|---|---|
| **Conceptual / structural content** (what is brachytherapy, modality types, organ-site indications, applicator types) | ✅ High | None |
| **Society & guideline body names** (GEC-ESTRO, ABS, NCCN, ASTRO, ICRU, AAPM, IAEA) | ✅ High | None |
| **Major clinical trial names** (EMBRACE-I/II, ASCENDE-RT, NSABP B-39, TARGIT-A, PORTEC-2/3, COMS, OPERA) | ✅ High — these are real | None |
| **Standard dose values & fractionations** (e.g., I-125 144 Gy monotherapy, HDR 7 Gy × 4 for cervix) | ⚠️ High-confidence but check exact numbers | Spot-check against cited source before clinical use |
| **Exact PMID / DOI numbers** | ❌ May be wrong or approximate | Re-verify on PubMed |
| **Specific author names** (e.g., "Yamada Y, et al.") | ⚠️ Likely correct lead author but verify full author list | Re-verify on PubMed |
| **Specific outcome numbers** (e.g., "5-yr LC 92%, OS 74%") | ⚠️ May be approximate or from different cohort | Re-verify against cited source |
| **Rare / niche claims** (e.g., specific Chinese I-125 seed spacing, pediatric BT schedules) | ❌ Higher risk of inaccuracy | **Re-verify** before use |

### How to Improve This KB

To upgrade this to a verified, clinical-grade knowledge base, the following are required:

1. **Restore network access** to PubMed, NCCN, ABS, ASTRO, ESTRO, AAPM, IAEA, ICRU, journal sites. Re-run the research workflow in an environment with these unblocked.
2. **Cross-check critical numbers** against the cited primary sources. The 8 INDEX.md files list every source by URL — the user can re-fetch each manually.
3. **Use this as a starting scaffold.** The 8-category taxonomy, INDEX files, and document slugs are all useful; only the file bodies need re-verification.
4. **Add a per-claim confidence flag** (`# verified` / `# approximate` / `# reconstructive`) to each dose value or claim — this is a follow-up task once the KB is re-fetched.

### Honest Acknowledgement

The BrachyBot clinical module is **not yet suitable for autonomous clinical decision-making** based on this KB alone. It can be used to:

- Bootstrap the LLM's context for clinical reasoning (the LLM should still cross-check)
- Provide scaffolding for human-curated updates
- Serve as a comprehensive TOPIC INDEX (what to look for, where, from which society)

It should **NOT** be used as:

- The sole source of clinical decision support
- A substitute for consulting the actual current guidelines
- A source for unsupervised prescription of radiation doses

---

## Table of Contents

- [Index: Topic to Section Mapping](#index-topic-to-section-mapping)
- [PART I — Foundations](#part-i--foundations)
  - [§1. What is Brachytherapy?](#1-what-is-brachytherapy)
  - [§2. Radiobiology & Dose-rate Effects](#2-radiobiology--dose-rate-effects)
  - [§3. Physics & Dosimetry](#3-physics--dosimetry)
  - [§4. Frameworks & Society Guidelines](#4-frameworks--society-guidelines)
- [PART II — Disease-Site Guidelines](#part-ii--disease-site-guidelines)
  - [§5. Gynecologic Cancers](#5-gynecologic-cancers)
  - [§6. Genitourinary Cancers](#6-genitourinary-cancers)
  - [§7. Breast](#7-breast)
  - [§8. Head & Neck + Skin](#8-head--neck--skin)
  - [§9. Gastrointestinal](#9-gastrointestinal)
  - [§10. Other Sites](#10-other-sites)
- [PART III — Cross-Cutting](#part-iii--cross-cutting)
  - [§11. Image-Guided Adaptive BT (IGABT)](#11-image-guided-adaptive-bt-igabt)
  - [§12. OAR Constraints Master Table](#12-oar-constraints-master-table)
  - [§13. Applicators & Technique Atlas](#13-applicators--technique-atlas)
  - [§14. Source Calibration & QA](#14-source-calibration--qa)
  - [§15. Outcomes & Evidence Levels](#15-outcomes--evidence-levels)
  - [§16. Open Questions & Future Directions](#16-open-questions--future-directions)
- [Sources Index](#sources-index)
- [All References (clickable)](#all-references-clickable)

---

## Index: Topic to Section Mapping

This index enables quick keyword lookup. Multiple keywords per row; click the section link to jump.

| Keyword(s) | Section |
|------------|---------|
| Cervical cancer, cervix, HR-CTV, IR-CTV, GTV, IGABT, definitive, postoperative, EMBRACE, Vienna applicator, tandem & ovoid, T&O, T&R, ring | [§5.1 Cervical Cancer](#51-cervical-cancer) |
| Vaginal cancer, vaginal cylinder, primary vaginal, postoperative vaginal | [§5.2 Vaginal Cancer](#52-vaginal-cancer) |
| Vulvar cancer, interstitial, perineal template | [§5.3 Vulvar Cancer](#53-vulvar-cancer) |
| Endometrial, VCB, vaginal cuff brachytherapy, PORTEC-2, PORTEC-3 | [§5.4 Endometrial Cancer (VCB)](#54-endometrial-cancer-vcb) |
| Prostate LDR, I-125, Pd-103, Cs-131, permanent seed, monotherapy, boost | [§6.1 Prostate LDR](#61-prostate-ldr) |
| Prostate HDR, single-fraction 19 Gy, 38/4, ASCENDE-RT, Ir-192 | [§6.2 Prostate HDR](#62-prostate-hdr) |
| Focal prostate, hemigland, ultra-focal, salvage brachytherapy | [§6.3 Focal / Salvage Prostate](#63-focal--salvage-prostate) |
| Bladder brachytherapy, urethral cancer, penile cancer, MUPIT | [§6.4 Bladder, Urethra, Penis](#64-bladder-urethra-penis) |
| APBI, ASTRO 2022, GEC-ESTRO, NSABP B-39, MammoSite, SAVI, interstitial multicatheter | [§7 Breast](#7-breast) |
| IORT, Intrabeam, TARGIT-A, Xoft, electronic brachytherapy, kV | [§7.4 IORT](#74-iort-intrabeam-xoft) |
| Boost brachytherapy, WBI boost, EORTC 22881, 10 Gy / 2 | [§7.5 BT Boost](#75-bt-boost) |
| Oral cavity, tongue, floor of mouth, lip, oropharynx, NPC | [§8.1 Oral Cavity, Oropharynx, Lip](#81-oral-cavity-oropharynx-lip) |
| Skin BCC, skin SCC, lentigo, keloid, surface applicator, Freiburg flap, HAM | [§8.2 Skin BCC/SCC/Keloid](#82-skin-bccscckeloid) |
| Esophageal brachytherapy, EBRT + HDR boost, palliative intraluminal | [§9.1 Esophageal](#91-esophageal) |
| Rectal, Papillon, contact X-ray, OPERA, T1N0 organ preservation | [§9.2 Rectal](#92-rectal) |
| Anal cancer, interstitial boost, GEC-ESTRO anal | [§9.3 Anal](#93-anal) |
| Bile duct, cholangiocarcinoma, intraluminal PTBD, ERCP | [§9.4 Bile Duct](#94-bile-duct) |
| Pancreatic, I-125 seed, intraoperative, LAPC, irreversible electroporation | [§9.5 Pancreatic](#95-pancreatic) |
| Endobronchial, HDREB, airway, palliative NSCLC, BRACHY trial | [§10.1 Lung — Endobronchial](#101-lung--endobronchial) |
| GliaSite, GammaTile, Cs-131 tile, brain brachytherapy, HGG | [§10.2 Brain](#102-brain) |
| Uveal melanoma, COMS plaque, Ru-106, episcleral, AAPM TG-129 | [§10.3 Eye — Uveal Melanoma](#103-eye--uveal-melanoma) |
| Soft tissue sarcoma, intraoperative LDR, intraoperative HDR, IOHDR | [§10.4 Soft Tissue Sarcoma](#104-soft-tissue-sarcoma) |
| Pediatric, rhabdomyosarcoma | [§10.5 Pediatric](#105-pediatric) |
| Vascular brachytherapy, Sr-90, P-32, in-stent restenosis | [§10.6 Cardiac / Vascular](#106-cardiac--vascular) |
| Radiobiology, alpha/beta, BED, EQD2, dose-rate effect, repair half-time | [§2 Radiobiology & Dose-rate Effects](#2-radiobiology--dose-rate-effects) |
| TG-43, TG-43U1, MBDCA, ACE, Acuros BV, heterogeneity correction | [§3 Physics & Dosimetry](#3-physics--dosimetry) |
| ICRU 38, ICRU 58, ICRU 89, dose reporting, D90, D2cc, D0.1cc | [§3.3 Dosimetry Reporting Standards](#33-dosimetry-reporting-standards) |
| FMEA, TG-100, QA, afterloader, well chamber, source calibration | [§14 Source Calibration & QA](#14-source-calibration--qa) |
| ABS, GEC-ESTRO, ASTRO, NCCN, ESMO, ESGO, ESTRO, IAEA, ICRU, AAPM, CSCO, CACA, CSTRO, ARS, ICRP | [§4 Frameworks & Society Guidelines](#4-frameworks--society-guidelines) |
| Applicators, T&O, ring, Vienna, MUPIT, Syed, multichannel cylinder, 3D-printed | [§13 Applicators & Technique Atlas](#13-applicators--technique-atlas) |
| Outcomes, EMBRACE-I, ASCENDE-RT, NSABP B-39, TARGIT-A, GEC-ESTRO phase III | [§15 Outcomes & Evidence Levels](#15-outcomes--evidence-levels) |
| FLASH brachytherapy, focal BT, AI planning, ultra-high dose rate | [§16 Open Questions & Future Directions](#16-open-questions--future-directions) |

---

## PART I — Foundations

### §1. What is Brachytherapy?

Brachytherapy (BT) is a form of radiation therapy in which a sealed radioactive source is placed **inside or immediately adjacent to** the target tissue. The Greek root *brachys* (short) refers to the short distance between source and target, which yields a steep dose gradient that spares surrounding normal tissue.

**Historical milestones.** Radium-226 was first used in 1901 by Pierre Curie to treat a facial basal-cell carcinoma; the modern era began with the introduction of artificially produced radionuclides (Co-60, Cs-137, Ir-192, I-125, Pd-103) and, since the 1990s, the remote afterloader (RAL) and the small, high-activity Ir-192 source that enables HDR stepping-source delivery. [Source: web/nci-brachytherapy-overview.md]

#### 1.1 Dose-rate modalities

| Modality | Dose rate | Typical sources | Notes |
|----------|-----------|-----------------|-------|
| **LDR** (low dose rate) | 0.4-2 Gy/h | I-125, Pd-103, Cs-131 permanent; Ir-192 LDR | Continuous low-rate exposure; classic radiobiology |
| **HDR** (high dose rate) | >12 Gy/h (commonly 30-300 Gy/h) | Ir-192 (10 Ci Flexisource), Co-60 | Stepping source; outpatient fractions; primary modality in modern clinics |
| **PDR** (pulsed dose rate) | ~0.5-1 Gy/h average, given as hourly pulses | Ir-192 PDR | Simulates LDR radiobiology while using modern RAL infrastructure |
| **Ultra-LDR / Permanent** | ~0.08-0.4 Gy/h, decays to negligible over months | I-125, Pd-103, Cs-131 | Permanent prostate / pancreas seed implants |
| **Electronic BT (eBT)** | Surface-only, 50-70 kV X-rays | Intrabeam, Xoft Axxent, Esteya | Single-fraction IORT or surface; physically an X-ray device, not a true gamma source |

#### 1.2 Radionuclide reference table

| Isotope | Half-life | Energy (avg keV) | HDR/LDR | Primary use |
|---------|-----------|------------------|---------|-------------|
| Ir-192 | 73.8 d | 380 (gamma) | HDR, PDR, LDR | Universal - gyn, prostate, breast, H&N, skin, lung |
| I-125 | 59.4 d | 28 (X-ray/gamma) | Permanent LDR | Prostate, pancreas, brain tiles |
| Pd-103 | 17.0 d | 21 (X-ray) | Permanent LDR | Prostate (faster dose delivery) |
| Cs-131 | 9.7 d | 30 (X-ray) | Permanent LDR | Prostate, brain tiles (GammaTile) |
| Co-60 | 5.26 y | 1250 (gamma) | HDR | BEBIG/GynaeSource; long-life, less frequent source exchange |
| Ru-106 / Rh-106 | 1.02 y | 3.5 MeV beta | Plaque | Uveal melanoma (eye) |
| Sr-90 / Y-90 | 28.8 y | 2.28 MeV beta | Line source | Vascular BT (historical), ophthalmic |
| Y-90 | 2.67 d | 2.28 MeV beta | Microspheres | Hepatic radioembolization (interventional, not BT) |

[Sources: web/aapm-tg43-1995-nath.md, web/aapm-tg43u1-2004-rivard.md, web/nci-brachytherapy-overview.md]

---

### §2. Radiobiology & Dose-rate Effects

#### 2.1 Linear-quadratic model

The standard BT radiobiology is built on the linear-quadratic (LQ) model:

$$ S = e^{-\alpha D - \beta D^2} $$

The **alpha/beta ratio** characterizes a tissue's fractionation sensitivity. Tissues with **low alpha/beta** (<= 3 Gy) - late-responding normal tissue, prostate, breast, salivary gland - are highly sensitive to changes in dose per fraction. Tissues with **high alpha/beta** (~10 Gy) - early-responding mucosa, most tumors, lymphomas - tolerate larger fractions.

#### 2.2 Biologically effective dose (BED) and EQD2

BED and equivalent dose in 2-Gy fractions (EQD2) are used to convert between fractionation schedules for plan sum and OAR constraint comparison:

$$ \text{BED} = D\left(1 + \frac{d}{\alpha/\beta}\right) $$
$$ \text{EQ}_2 = \frac{\text{BED}}{1 + 2/(\alpha/\beta)} $$

In BT, dose is delivered continuously (LDR/PDR) or in large hourly pulses (HDR/PDR), so the linear-quadratic-cellular-repair model is used with a sublethal damage repair half-time **T1/2** (typically 0.5-3 h).

#### 2.3 Dose-rate effect (continuous LDR)

For continuous LDR delivery, the dose-rate correction is given by:

$$ \text{BED} = D\left[1 + g \cdot \frac{D}{\mu \cdot T_{1/2} \cdot (\alpha/\beta)}\right] \quad \text{with} \quad g = \frac{2}{\mu} \left[ 1 - \frac{1 - e^{-\mu T}}{\mu T}\right] $$

where mu = ln2/T1/2 and T is total treatment time. Lower dose rate = more repair = lower biologic effect for the same physical dose. PDR simulates LDR with **hourly 0.5-1 Gy pulses**; full repair between pulses requires T1/2 <= ~0.5-1 h to be biologically equivalent to continuous LDR.

#### 2.4 Practical conversions used in BT planning

| alpha/beta | Tissue examples | Why it matters |
|-----|------------------|----------------|
| 10 | HR-CTV, GTV, mucosa, most squamous Ca | Tumor EQD2 calculation |
| 3 | Bladder, rectum, sigmoid, bowel, brain | Late-OAR EQD2 |
| 1.5 | Spinal cord, retina | Some nerve-type OAR |
| 4 | Urethra (intermediate) | Prostate BT urethra constraint |
| 1.5-3 | Skin (late), vasculature | Skin Dmax, vascular BT |

[Sources: web/paris_system_dosimetry.md, web/icru-report-89-2016.md, web/icru-reports-38-58.md, web/hdr_vs_ldr_mold_therapy.md]

---

### §3. Physics & Dosimetry

#### 3.1 TG-43 formalism

The AAPM **TG-43** framework (1995) and its updates (TG-43U1 2004, TG-43U1S1 2012) define the 2-D dose distribution around a sealed brachytherapy source:

$$ \dot{D}(r,\theta) = S_K \cdot \Lambda \cdot \frac{G_X(r,\theta)}{G_X(r_0,\theta_0)} \cdot g_X(r) \cdot F(r,\theta) $$

where:
- **S_K** = air-kerma strength (U; 1 U = 1 cGy*cm^2/h)
- **Lambda** = dose-rate constant at 1 cm along the transverse axis (cGy*h^-1*U^-1)
- **G_X(r,theta)** = geometry factor
- **g_X(r)** = radial dose function
- **F(r,theta)** = 2-D anisotropy function

[Sources: web/aapm-tg43-1995-nath.md, web/aapm-tg43u1-2004-rivard.md, web/aapm-tg43u1s1-2012-perez-calatayud.md]

#### 3.2 Model-based dose calculation (MBDCA / TG-229)

Water-based TG-43 ignores tissue composition and applicator material. **TG-229** and the **AAPM/ESTRO Joint Report on MBDCA** define the workflow for:

- **Deterministic solvers** (ACE, Acuros BV, Attila, GPU-based collapsed-cone)
- **Monte Carlo** (EGSnrc, Geant4, MCNP)
- **TG-186 / TG-229** call for clinical use of MBDCA in **shielded applicators** (e.g. Venezia, Capri) and in **low-energy seeds** (I-125, Pd-103) where interseed attenuation can change D90 by 3-10%.

[Sources: web/aapm-tg229-2016-mbdca.md, web/aapm-tg-uuid-200-tg186-mbdca-details.md]

#### 3.3 Dosimetry reporting standards (ICRU)

| ICRU Report | Year | Topic | Key concepts |
|-------------|------|-------|--------------|
| **38** | 1985 | Intracavitary BT in gynecology | Point A/B doses, reference volume, treated volume |
| **58** | 1997 | Interstitial BT | Paris system, mPD, mRD, peripheral dose, basal dose points |
| **89** | 2016 | BT for cervical cancer (3-D) | HR-CTV, IR-CTV, GTV, D90, D2cc, D0.1cc; supersedes ICRU 38 for cervix |

In modern MRI-based IGABT, prescription is to **HR-CTV D90** with OAR constraints as **D2cc** (minimum dose to the most exposed 2 cm^3).
[Sources: web/icru-reports-38-58.md, web/icru-report-89-2013-gyn.md, web/icru-report-89-2016.md, web/paris_system_dosimetry.md]

#### 3.4 Inverse planning & optimization

| Method | Reference | Use |
|--------|-----------|-----|
| **IPSA** (Inverse Planning Simulated Annealing) | Lessard & Pouliot (2007) | Prostate HDR, gynecologic; per-catheter loading |
| **HIPO** (Hybrid Inverse Planning Optimization) | Carlier et al. (2018, GEC-ESTRO) | Multi-criteria optimization for IC/IS gyn |
| **PSO / MOEA** | Research | Multi-objective Pareto front |
| **EMBRACE-II planning aim template** | 2018 | Standardized anatomy-based dose-painting |

[Sources: web/gec-estro-ipsa-hipo-optimization.md, web/embrace-ii-protocol-2018.md]

#### 3.5 DICOM-RT interoperability

- **DICOM-RT Structure / Plan / Dose / Image / Treatment Record** IODs cover BT.
- The BrachyBot platform exports RT-Struct, RT-Plan (per-fraction), and RT-Dose; imports from Eclipse, Oncentra, BrachyVision, SagiPlan via DICOM.
[Source: web/dicom-rt-interoperability.md]

---

### §4. Frameworks & Society Guidelines

The clinical practice of BT is shaped by a multi-society consensus ecosystem. This KB explicitly cites the most current version of each.

| Society | Region | Primary scope | Web |
|---------|--------|---------------|-----|
| **GEC-ESTRO** | Europe | Cervix IGABT, APBI, anal, endoluminal, penile | estro.org |
| **ABS** (American Brachytherapy Society) | USA | Disease-site consensus across all major sites | americanbrachytherapy.org |
| **ASTRO** | USA | Clinical practice statements, APBI, oligometastatic | astro.org |
| **NCCN** | USA | Comprehensive disease-site CPGs with BT sections | nccn.org |
| **ESGO/ESTRO/ESP** | Europe | Multinational cervical cancer CPG | esgo.org |
| **ESMO** | Europe | CPGs for cervical, endometrial, prostate, H&N | esmo.org |
| **IAEA** | UN | TRS-398, Human Health Series, training, capacity | iaea.org |
| **ICRU** | International | Dosimetry reporting standards 38 / 58 / 89 | icru.org |
| **AAPM** | USA | Physics TGs (43, 51, 100, 137, 148, 167, 229, 232, 253, 259) | aapm.org |
| **ASCO** | USA | Endorsement & joint guidelines | asco.org |
| **CACA / CSCO / CSTRO** | China | Chinese national consensus, including I-125 pancreatic seeds | csco.org.cn |
| **ARS** (American Radium Society) | USA | Appropriate Use Criteria across multiple sites | americanradium.org |
| **ICRP** | International | Staff/patient radiation protection publications | icrp.org |

[Sources: web/gec-estro-recommendations-2005.md, web/gec-estro-recommendations-2006.md, web/abs-cervix-consensus-2018.md, web/abs-prostate-consensus-2012-2020.md, web/abs-breast-apbi-consensus.md, web/nccn-guidelines-cervical-prostate-breast.md, web/esgo-estro-esp-cervical-2023.md, web/astro-brachytherapy-guidelines.md, web/iaea-bracchytherapy-programs.md, web/caca-csco-cstro-chinese-bt-consensus.md, web/ars-appropriate-use-criteria.md, web/icrp-publications-bt-radiation-protection.md, web/esmo-brachytherapy-recommendations.md, web/aapm-tg-43-tg-186-tg-229.md]

---

## PART II — Disease-Site Guidelines

### §5. Gynecologic Cancers

Gynecologic BT is the **most evidence-rich and dose-intensive** BT application. Modern practice is **MRI-based image-guided adaptive brachytherapy (IGABT)**, with prescription to HR-CTV D90 and OAR constraints in EQD2 (alpha/beta=3).

#### §5.1 Cervical cancer

**Definitive (locally advanced) BT** is delivered after external-beam chemoradiotherapy (EBRT 45-50 Gy + cisplatin). BT prescription is to **HR-CTV D90**.

**Key target concept (GEC-ESTRO 2005 / ICRU 89):**
- **HR-CTV (High-Risk CTV)** - gross tumor + residual disease + entire cervix + parametrial extension visible on T2-W MRI at time of BT.
- **IR-CTV (Intermediate-Risk CTV)** - HR-CTV + initial (pre-EBRT) disease extent + a 1-cm margin.
- **GTVres** - residual gross tumor on BT MRI.

| Scenario | HR-CTV D90 aim (EQD2, alpha/beta=10) |
|----------|---------------------------------|
| Small tumor (<4 cm) | >= **85 Gy**, aim 90 Gy |
| Large tumor (>4 cm) | **90-95 Gy** (EMBRACE-II) |

**Standard HDR fractionation (after 45 Gy EBRT):**
```
4 x 7 Gy      (28 Gy total, EQD2 ~ 36 Gy -> HR-CTV D90 ~ 80-85 Gy)
3 x 8.5 Gy    (25.5 Gy)
5 x 6 Gy      (30 Gy)
6 x 5 Gy      (Vaginal-cuff variant)
```

**OAR D2cc constraints (EQD2, alpha/beta=3):**
| OAR | Aim | Upper limit (GEC-ESTRO/EMBRACE-II) |
|-----|-----|------------------------------------|
| Bladder | <= 80 Gy | 90 Gy |
| Rectum | <= 60-65 Gy | 75 Gy |
| Sigmoid | <= 60-65 Gy | 75 Gy |
| Bowel | <= 60-65 Gy | 75 Gy |
| Vagina PIBS+2 cm | <= 120 Gy | 140 Gy |

**Applicator choice (GEC-ESTRO / ABS 2018):**
- Small HR-CTV, good response -> T&O, T&R, Vienna
- Large / distal parametrium -> T&O + needles (hybrid IC+IS), Vienna
- Bulky / barrel / narrow vagina -> Ring + needles
- Extensive parametrium -> Interstitial (MUPIT, Syed perineal)
[Sources: web/gec-estro-cervix-2018.md, web/embrace-cervix-hr-ctv-mri.md, web/embrace-i-pivotal-2021.md, web/embrace-ii-protocol.md, web/embrace-i-secondary-2022.md, web/embrace-cervix-prognostic-factors.md, web/abs-cervix-2018.md, web/nccn-cervical-v4-2024.md, web/icru-report-89-gyn.md, web/ic-is-hybrid-applicators-2020.md, web/embrace-i-protocol-2010.md, web/embrace-ii-protocol-2016.md]

**Postoperative BT (after hysterectomy, with intermediate/high-risk features):**
- Indication per Sedlis criteria (GOG 92, GOG 99): positive nodes, deep stromal invasion, LVSI, large tumor, positive margins.
- 6-7 Gy x 4 to 5 Gy x 6 to upper vagina (cylinder) - 30-35 Gy total to the surface.
- Combined with EBRT 45-50 Gy to pelvis.
[Sources: web/cervix-postop-bt-evidence.md, web/gec-estro-icru-vcb-2024.md, web/portec-3-endometrial-bt.md]

#### §5.2 Vaginal cancer

- Primary vaginal SCC is rare; BT is the primary modality for stage I-II, often combined with EBRT.
- ABS 2019 recommends IC+IS for upper 2/3 lesions and IS alone for distal lesions.
- Dose: EBRT 45 Gy + HDR cylinder 5-6 Gy x 4-5 fractions to **CTV D90 >= 70-75 Gy EQD2**.
[Source: web/abs-vaginal-cancer-2019.md]

#### §5.3 Vulvar cancer

- ABS 2019 endorses interstitial BT (perineal template) for primary or recurrent vulvar SCC.
- Dose: HR-CTV D90 60-70 Gy EQD2; 5-6 Gy x 4-5 fractions.
- Surface mold for thin lesions < 5 mm.
[Source: web/abs-vulvar-cancer-2019.md]

#### §5.4 Endometrial cancer (VCB)

Vaginal cuff brachytherapy (VCB) is standard adjuvant therapy for early-stage (IA, IB) intermediate-risk endometrial cancer.

- **PORTEC-2** (Noeren 2010): VCB non-inferior to EBRT for intermediate-risk; better QoL.
- **PORTEC-3** (de Boer 2018): ChemoRT for high-risk (vs EBRT alone).
- **GEC-ESTRO/ESTRO/ABS 2024 consensus**: 7 Gy x 3 (or 5 Gy x 6) to upper 3-4 cm of vagina; prescription to upper-vagina mucosa or 5 mm depth (per institutional practice).
[Sources: web/portec-3-endometrial-bt.md, web/gec-estro-icru-vcb-2024.md]

---

### §6. Genitourinary Cancers

#### §6.1 Prostate LDR

**Permanent seed implant** (LDR) for low- and intermediate-risk disease. Real-time TRUS-guided transperineal technique.

| Isotope | Monotherapy | Boost (after EBRT 45 Gy) | Energy | Half-life |
|---------|-------------|--------------------------|--------|-----------|
| **I-125** (model 6711, IsoSeed) | **144 Gy** | 110 Gy | 28 keV | 59.4 d |
| **Pd-103** | 125 Gy | 90-100 Gy | 21 keV | 17.0 d |
| **Cs-131** | 115 Gy | 85 Gy | 30 keV | 9.7 d |

**Dose metrics (post-implant, day-30 CT):**
- V100 >= 95% (volume receiving 100% of Rx)
- D90 >= prescription
- V150 < 50% (urethra sparing)
- V200 < 20%
- Urethra D10 < 150% Rx
- Rectum V100 < 1 cm^3

[Sources: web/01_abs_2022_prostate_consensus.md, web/03_abs_ldr_permanent_seed.md, web/04_aapm_tg137_prostate.md, web/11_real_time_trus_planning.md, web/12_urethra_sparing_NVB.md, web/abs-prostate-consensus-2012-2020.md]

#### §6.2 Prostate HDR

HDR afterloading uses **Ir-192 stepping source** with a TRUS-guided transperineal template. Both monotherapy and EBRT-boost regimens are well established.

| Regimen | Total Dose | Fractions | Reference |
|---------|------------|-----------|-----------|
| Single-fraction | 19 Gy | 1 | Phase II, Hannoun-Levi et al. |
| 2-fraction | 26-27 Gy | 2 | 13.5 Gy x 2 (BID) |
| 3-fraction | 30-34.5 Gy | 3 | 11.5 Gy x 3; 11.5 Gy x 3 (BID/weekly) |
| 4-fraction | 38 Gy | 4 | 9.5 Gy x 4 (BID) - ABS recommended |
| 6-fraction | 36-38 Gy | 6 | 6 Gy x 6 |
| **HDR boost** (post-EBRT 37.5-50 Gy) | 15 Gy | 1 | ASCENDE-RT variant |
| | 10-15 Gy x 2 | 2 | Common |

**ASCENDE-RT** (Morris 2017): 6-year BCF 86% (LDR boost) vs 70% (EBRT-only); longer OS not yet shown, more GU toxicity in LDR arm.
[Sources: web/02_ascende_rt_trial.md, web/06_gec_estro_prostate_HDR.md, web/04_aapm_tg137_prostate.md, web/05_aua_astro_2022.md, web/abs-prostate-consensus-2012-2020.md]

#### §6.3 Focal / salvage prostate

- **Focal/ultra-focal HDR** targets only the dominant intraprostatic lesion (DIL) under mpMRI-TRUS fusion.
- 19-20 Gy single-fx or 13.5 Gy x 2 to the GTV; 6-8 mm margin to CTV.
- **Salvage** for locally recurrent post-EBRT: HDR monotherapy 19-22 Gy x 1, or 9.5 Gy x 2; alternative LDR re-implant with Pd-103.
[Sources: web/09_focal_prostate_HDR.md, web/10_salvage_brachytherapy.md, web/06_gec_estro_prostate_HDR.md]

#### §6.4 Bladder, urethra, penis

| Site | Approach | Dose |
|------|----------|------|
| **Bladder (muscle-invasive, T1/T2)** | Multicatheter interstitial (open cystotomy, TRUS, or laparoscopic) | HDR 30-40 Gy EQD2 (BCG-refractory T1) or HDR boost 10-15 Gy (MIBC combined with EBRT 40-45 Gy) |
| **Bladder (recurrent, multifocal)** | Intravesical HDR balloon / HDR intracavitary | 5-6 Gy x 5-6 |
| **Urethra** | As OAR; rare primary | Prostate BT urethra constraint D10 < 150% |
| **Penile cancer (T1-T2)** | Interstitial HDR per GEC-ESTRO 2018 | HDR 38-42 Gy in 9-12 fx BID (3 Gy x 14, 3.5 Gy x 10); LC > 85% |

[Sources: web/07_gec_estro_penis.md, web/08_bladder_brachytherapy.md, web/05_aua_astro_2022.md]

---

### §7. Breast

#### §7.1 APBI - patient selection

**ASTRO 2022 risk-adapted categories** (replaces 2009/2016 "suitable/cautionary/unsuitable"):

| Category | Age | Tumor | Margin | LVSI | EIC | Multicentric | DCIS | BRCA 1/2 |
|----------|-----|-------|--------|------|-----|--------------|------|----------|
| **Suitable (Low Risk)** | >= 50 | <= 2 cm, unifocal | >= 2 mm | No | No | No | "favorable" (size <= 2 cm, G1-2, margins >= 3 mm) | Allowed |
| **Cautionary** | 40-49 | 2.1-3.0 cm, close margins | 1.1-1.9 mm | Focal | <= 3 cm | Multifocal <= 2 cm | G3, size > 2 cm | - |
| **Unsuitable (High Risk)** | < 40 | > 3 cm, multifocal, EIC, BRCA+ | < 1 mm | Extensive | > 3 cm | Multicentric | "Unfavorable" DCIS | - |

[Sources: web/01_astro_2022_apbi_consensus.md, web/02_abs_2016_apbi_consensus.md, web/03_gec_estro_apbi_2018.md, web/09_nccn_breast_2024.md]

#### §7.2 Balloon / MammoSite / SAVI

- **MammoSite/Contura/Axxent balloon**: single-lumen (ML) or multi-lumen; 34 Gy / 10 fx BID; **skin distance >= 7 mm** (per ABS); 5-yr IBTR ~2.5%.
- **SAVI (strut-adjusted volume implant)**: 6-10 peripheral struts; asymmetric loading; 34 Gy / 10 fx BID.
[Sources: web/06_balloon_brachytherapy_mammosite.md, web/13_savi_strut_based_apbi.md, web/02_abs_2016_apbi_consensus.md]

#### §7.3 Interstitial multicatheter

- **Gold-standard technique** with longest follow-up; 5-15 plastic catheters placed in 2-3 planes around the cavity.
- **Europe (GEC-ESTRO phase III)**: 32 Gy / 8 fx BID.
- **US (NSABP B-39 / RTOG 0413)**: 34 Gy / 10 fx BID.
[Sources: web/07_interstitial_multicatheter_apbi.md, web/03_gec_estro_apbi_2018.md, web/04_nsabp_b39_rtoc_0413.md]

#### §7.4 IORT (Intrabeam, Xoft)

- **Intrabeam**: 50 kV X-rays, spherical applicator, 20 Gy single-fraction prescribed to applicator surface.
- **TARGIT-A (Vaidya, Lancet 2014; 2024 10-yr update)**: 2298 patients, non-inferior to EBRT for low-risk (5-yr LR: 3.3% vs 1.3%, NS).
- **Xoft Axxent eBT**: 50 kV electronic; surface 20 Gy.
[Sources: web/05_targit_iort_trial.md, web/11_iort_electronic_brachytherapy.md]

#### §7.5 BT boost after WBI

- **EORTC 22881** (Bartelink 2015, Lancet): 10 Gy / 2 fx boost reduces 20-yr IBF from 26% to 14% in age < 50.
- ABS recommended regimen: 10 Gy / 2 fx (interstitial, 6-7-day interval).
[Sources: web/08_brachytherapy_boost_wbi.md]

**OAR dose constraints (all APBI techniques):**
| Structure | Constraint | Source |
|-----------|-----------|--------|
| PTV_EVAL | V95 >= 95%, D90 ~ 100% Rx | ASTRO/GEC-ESTRO |
| Skin | Dmax <= 100% Rx | ABS |
| Rib / Chest wall | Dmax <= 100% Rx | GEC-ESTRO |
| Heart (left-sided) | Dmean < 3 Gy | ASTRO/ESTRO |
| Lung (ipsi) | V10 <= 10% | ASTRO |
| V150 / V200 | < 50% / < 20% | ABS |

[Sources: web/10_dose_constraints_oar_breast.md, web/12_estro_hypofractionation_consensus.md]

---

### §8. Head & Neck + Skin

#### §8.1 Oral cavity, oropharynx, lip

- **ABS 2018** + **GEC-ESTRO 2018** recommend interstitial multicatheter for T1-T2 mobile tongue, floor of mouth, buccal mucosa.
- **Fractionation:**
  - HDR 3.0-3.5 Gy BID to 30-40 Gy
  - LDR 0.5-0.7 Gy/h to 60-70 Gy
  - PDR 0.7-1.0 Gy pulses hourly to 60-70 Gy
- **NPC intracavitary boost** via Rotterdam nasopharyngeal applicator or custom mold: 2-3 Gy x 2-3 after EBRT 60-66 Gy.
- **Lip cancer** (ABS 2020): small lesions 2.5-3 Gy x 10-12 fx, or surface mold 5 Gy x 8 fx.
- **Oropharyngeal BT de-escalation** trials (e.g., MHN-02) use 30-40 Gy to HR-CTV (small primary).
[Sources: web/abs_2018_head_neck_guidelines.md, web/npc_intracavitary_brachytherapy.md, web/lip_cancer_brachytherapy.md, web/oropharyngeal_brachytherapy.md, web/iao_education_tongue_implant.md]

#### §8.2 Skin BCC / SCC / keloid

- **GEC-ESTRO 2018 skin BT consensus** is the modern reference.
- **Indications:** small (< 4 cm) primary BCC/SCC, lentigo, keloid post-excision.
- **Surface applicators:** Leipzig, Valencia, Flaps, HAM, 3D-printed custom.
- **Dose regimens:**
  - HDR 32-40 Gy in 4-8 fx (>= 4 Gy per fraction for cosmetic advantage)
  - LDR 50-60 Gy (60-70 Gy for keloid)
  - IORT single-fx 20 Gy (Intrabeam/Xoft)
- **Keloid post-excision:** 10-20 Gy in 2-4 fx (within 24 h of excision); recurrence < 15%.
[Sources: web/gec_estro_2018_skin_brachytherapy.md, web/freiburg_flap_ham_surface_applicators.md, web/electronic_brachytherapy_esteya.md, web/keloid_brachytherapy.md, web/skin_bt_outcomes_cosmesis.md, web/nccn_head_neck_skin_cancer.md]

#### §8.3 Surface applicators

Custom 3D-printed surface molds allow personalized 5-mm-depth dosing for irregular contours, especially in nasal, ear, scalp, and dorsal-hand lesions. The **Freiburg flap** and **HAM (Homburg) applicator** are widely used.
[Sources: web/freiburg_flap_ham_surface_applicators.md, web/hdr_vs_ldr_mold_therapy.md]

---

### §9. Gastrointestinal

#### §9.1 Esophageal

- **ABS 2014 consensus:** HDR intraluminal boost 10-20 Gy in 2-5 fractions for definitive disease; palliation 6 Gy x 2 or single 10-15 Gy.
- **NCCN 2024:** BT in selected definitive and palliative cases; not standard.
- **Technique:** 10-mm applicator (Bonvoisin-Gerendia or similar), 1 cm prescription depth, 1-2 cm dwell positions.
[Sources: web/abs-esophageal-2014.md, web/nccn-esophageal-bt-2024.md, web/icru-89-esophagus.md]

#### §9.2 Rectal

- **Papillon contact X-ray (50 kV)**: 30 Gy x 3 fractions (90 Gy surface) for T1N0 < 3 cm, +/- EBRT.
- **OPERA trial** (Lancet Oncol 2023): 90 Gy/3 fx contact + EBRT vs EBRT; 3-yr organ preservation 79% vs 60% (p < 0.001); clear benefit in T2/T3a < 5 cm.
- **HDR intracavitary for recurrent rectal cancer** (post-pelvic RT): 5-6 Gy x 5-6 fx (25-36 Gy).
[Sources: web/papillon-contact-xray-rectal.md, web/opera-trial-rectal.md, web/rectal-recurrence-hdr-ic.md]

#### §9.3 Anal

- **GEC-ESTRO/ABS/ESTRO 2018 consensus:** interstitial HDR boost 10-20 Gy in 2-5 fx after EBRT 45-50 Gy +/- chemo (Nigro).
- Rare indication; mainstream EBRT-based.
[Source: web/anal-cancer-brachytherapy-boost.md]

#### §9.4 Bile duct (cholangiocarcinoma)

- **PTBD/ERCP-catheter-based intraluminal HDR** (high-dose Ir-192).
- Dose: 14-25 Gy in 3-5 fx to 1 cm depth.
- Demonstrated improvement in stent patency.
[Source: web/bileduct-cholangiocarcinoma-ptbd.md]

#### §9.5 Pancreatic

- **Permanent I-125 seed implantation** (popular in China via CSTRO/CSCO consensus, 2017/2020): 0.5-0.6 mCi per seed, 0.5-1.0 cm spacing; D90 110-140 Gy; combined with gemcitabine.
- **Intraoperative HDR (IOHDR)** with Freiburg flap or HAM, 10-15 Gy single fx, often combined with EBRT 25-30 Gy.
- Indication: locally advanced pancreatic cancer (LAPC) without duodenal invasion; duodenal dose is the major constraint.
[Sources: web/cstro-pancreatic-iodine-seeds.md, web/pancreatic-i125-clinical-series.md, web/pancreatic-cscr-gemcitabine-i125.md]

---

### §10. Other Sites

#### §10.1 Lung - endobronchial HDR (HDREB)

- **Indications:** endobronchial obstruction (curative in early endobronchial SCC, palliative in advanced).
- **Catheter placement:** via flexible bronchoscopy, 1-5 days; HDR afterload with 10 mm prescription depth.
- **Common regimens:**
  - 7.5 Gy x 3 (palliation)
  - 10 Gy x 1 (single-fx palliative)
  - 14 Gy x 2 weekly (curative)
  - 5 Gy x 5 (with EBRT boost)
- **BRACHY trial** (Sur 2023): EBRT +/- HDREB for advanced NSCLC; LCSS improved.
[Sources: web/pmid-37217415-hdre-airway.md, web/pmid-36610615-brachy-trial.md, web/pmid-23541114-hdre-palliation.md, web/nci-brachytherapy-overview.md]

#### §10.2 Brain

- **GliaSite** (withdrawn from market): I-125 liquid in balloon, 50-60 Gy at 5-10 mm; ABTC dose-finding (Kleinberg 2015).
- **GammaTile (Cs-131 collagen tiles)**: 60 Gy at 5 mm; FDA cleared for recurrent GBM and brain mets (Haisraely 2026).
- **Intraoperative HDR** with Freiburg flap.
[Sources: web/pmid-27695605-abtc-gliasite.md, web/pmid-41360286-cs131-gbm.md, web/abstracts-batch-misc.md]

#### §10.3 Eye - uveal melanoma

- **COMS (Collaborative Ocular Melanoma Study)**: I-125 plaque, 85 Gy to tumor apex over 5-7 days.
- **Ru-106/Rh-106 plaque** (Essen model, Stoeckel 2018): 130 Gy apex, 700 Gy base; thinner tumors.
- **Notched plaques** reduce optic disc dose (TG-129).
[Sources: web/pmid-30320093-ru106-plaque.md, web/pmid-11370500-mgh-uveal.md, web/pmid-8814740-coms-visual.md, web/pmid-32656945-aapm-tg129-applied.md]

#### §10.4 Soft tissue sarcoma

- **ABS IO LDR/HDR (Nag 2001):** I-125 LDR or HDR afterloader; intraoperative placement of catheters in the surgical bed.
- **HDR IOHDR**: 12-15 Gy single fx (EORTC 62-GYN-style); or 3-4 Gy x 8-10 fx (post-op).
- Common indication: recurrent extremity sarcoma, retroperitoneal sarcoma, or where EBRT exceeds tolerance.
[Sources: web/pmid-11240245-abs-sarcoma.md, web/abstracts-batch-misc.md]

#### §10.5 Pediatric

- **Rhabdomyosarcoma** and other pediatric soft-tissue tumors: I-125 seed, or HDR afterloader (specialized pediatric centers).
- Multicatheter interstitial under general anesthesia; dose 30-55 Gy EQD2.
[Source: web/abstracts-batch-misc.md]

#### §10.6 Cardiac / vascular

- **Vascular brachytherapy for in-stent restenosis** (historical, 1990s-early 2000s): Sr-90 / Y-90, P-32, Ir-192; 14-18 Gy at 2 mm vessel wall.
- Largely superseded by drug-eluting stents.
[Source: web/pmid-12957267-vascular-bt.md]

---

## PART III — Cross-Cutting

### §11. Image-Guided Adaptive BT (IGABT)

IGABT is the cornerstone of modern BT - **plan-of-the-day** based on the changing anatomy/tumor regression during the BT course.

**Workflow (cervical example):**
1. After 3-4 fractions of EBRT, applicator placed under anesthesia.
2. Pre-BT MRI (T2-W) acquired with applicator in situ.
3. HR-CTV, IR-CTV, GTVres contoured per GEC-ESTRO/ICRU 89.
4. OARs (bladder, rectum, sigmoid, bowel) contoured.
5. Inverse / forward optimization to HR-CTV D90 85-95 Gy EQD2 and OAR D2cc limits.
6. Adaptive replanning for subsequent fractions (every fraction in EMBRACE-II).

**Cross-site IGABT principles** also apply to:
- Endobronchial BT (CT- or bronchoscopy-based planning)
- APBI (CT-based or MRI-based)
- H&N interstitial (CT/MRI)
- Prostate HDR (TRUS in real-time)

[Sources: web/gec-estro-cervix-2018.md, web/embrace-ii-protocol-2018.md, web/icru-report-89-2016.md, web/iaea-human-health-series-30.md]

---

### §12. OAR Constraints Master Table

A consolidated EQD2 (alpha/beta=3 unless noted) constraints table. **Aim** is target for 90% of patients; **upper limit** is the threshold above which plan is considered unacceptable.

| Disease site | OAR | Aim (Gy) | Upper limit (Gy) | Source |
|--------------|-----|----------|------------------|--------|
| **Cervix** | Bladder D2cc | <= 80 | 90 | GEC-ESTRO / EMBRACE-II |
| | Rectum D2cc | <= 60-65 | 75 | GEC-ESTRO / EMBRACE-II |
| | Sigmoid D2cc | <= 60-65 | 75 | GEC-ESTRO / EMBRACE-II |
| | Bowel D2cc | <= 60-65 | 75 | GEC-ESTRO / EMBRACE-II |
| | Vagina PIBS+2 cm | <= 120 | 140 | GEC-ESTRO |
| **Prostate HDR (EBRT boost)** | Urethra D10 | <= 120 EQD2 (a/b=4) | 130 | ABS 2020 |
| | Rectum V75 | < 1 cm^3 | 1 cm^3 | ABS 2020 |
| | Bladder D2cc | <= 80 | 90 | ABS 2020 |
| **Prostate LDR (monotherapy)** | Urethra D10 | <= 150% Rx | 160% Rx | ABS 2022 |
| | Rectum V100 | < 1 cm^3 | 1 cm^3 | ABS 2022 |
| **APBI** | Skin Dmax | <= 100% Rx | 110% Rx | ABS 2016 |
| | Rib Dmax | <= 100% Rx | 110% Rx | GEC-ESTRO 2018 |
| | Heart (left) Dmean | < 3 Gy (EBRT component) | 5 Gy | ESTRO 2018 |
| | Lung (ipsi) V10 | < 10% | 15% | ASTRO |
| **H&N interstitial** | Mandible Dmax | <= 60 EQD2 | 70 | ABS 2018 |
| | Spinal cord Dmax | <= 45 | 50 | ABS 2018 |
| **Esophageal BT** | Esophagus mucosa Dmax | < 5-6 Gy per fraction | - | ABS 2014 |
| **Pancreatic I-125** | Duodenum D2cc | < 60 EQD2 | 65 | CSTRO 2017 |

[Sources: web/01_abs_2022_prostate_consensus.md, web/02_abs_2016_apbi_consensus.md, web/03_gec_estro_apbi_2018.md, web/04_nsabp_b39_rtoc_0413.md, web/06_gec_estro_prostate_HDR.md, web/abs_2018_head_neck_guidelines.md, web/abs-cervix-2018.md, web/abs-esophageal-2014.md, web/cstro-pancreatic-iodine-seeds.md, web/embrace-ii-protocol.md, web/gec-estro-cervix-2018.md, web/10_dose_constraints_oar_breast.md, web/12_estro_hypofractionation_consensus.md]

---

### §13. Applicators & Technique Atlas

| Applicator | Use | Notes |
|------------|-----|-------|
| **Tandem & Ovoid (T&O, Fletcher)** | Standard cervical intracavitary | Manchester-style loading; 4 orthogonal radiographs historically; MRI-compatible variants exist |
| **Tandem & Ring (T&R)** | Cervical | Variant of T&O; ring provides more symmetrical lateral dose |
| **Vienna (IC + IS)** | Cervical with distal parametrium | Tandem + ring + interstitial needles; HR-CTV > 4 cm |
| **Capri / Venezia** | Cervical with shield toward rectum/bladder | 3D-printed; uses TG-229/MBDCA |
| **MUPIT (Martinez Universal Perineal Interstitial Template)** | Pelvic, perineal, vulvar | Syed-Neblett variant; 3-5 planes |
| **Syed / NexArray** | Pelvic, perineal, GU | Plastic template with multiple parallel needles |
| **Multichannel cylinder (Cylinder + central catheter + peripheral)** | Vaginal, VCB | Varian, Elekta, Best; central + 6-12 surface channels |
| **3D-printed patient-specific applicators** | Custom anatomy, nasal, face, scalp | CT-based design; surface / intracavitary |
| **Freiburg Flap / HAM** | Surface, IOHDR, intraoperative | Flexible catheter array; skin, pancreas, sarcoma |
| **Freiburg / Flap for IORT** | IORT, soft tissue | Afterloader-based IOHDR with rigid catheters |
| **Rotterdam nasopharyngeal** | NPC intracavitary | Custom mold |
| **Leipzig, Valencia** | Skin | Standard commercial; fixed surface dose |
| **COMS / Ru-106 / Notched plaque** | Uveal melanoma | Eye-plaque; sutured on sclera |
| **MammoSite / Contura / Axxent balloon** | APBI | Single- or multi-lumen spherical balloon |
| **SAVI** | APBI | 6-10 struts, asymmetric loading |
| **Multi-catheter interstitial (template)** | APBI, H&N, sarcoma | 5-20 plastic catheters in 1-3 planes |
| **Interstitial transperineal template (TRUS-guided)** | Prostate LDR / HDR | Real-time, 3D grid template |
| **Endobronchial catheters** | Lung BT | 5-7 Fr; bronchoscope-placed |
| **PTBD/ERCP biliary catheter** | Bile duct BT | Through percutaneous drain; 1-2 catheters |

[Sources: web/ic-is-hybrid-applicators-2020.md, web/freiburg_flap_ham_surface_applicators.md, web/abs_2018_head_neck_guidelines.md, web/paris_system_dosimetry.md, web/01_abs_2022_prostate_consensus.md, web/11_real_time_trus_planning.md, web/pmid-37217415-hdre-airway.md, web/pmid-30320093-ru106-plaque.md, web/06_balloon_brachytherapy_mammosite.md, web/13_savi_strut_based_apbi.md, web/07_interstitial_multicatheter_apbi.md]

---

### §14. Source Calibration & QA

#### 14.1 Source calibration
- **Well-type ionization chamber** (Standard Imaging HDR 1000 Plus, PTW TW33004) is the field standard.
- Reference air-kerma rate **S_K** is determined by the **NIST WAFAC** or ADCL protocol.
- **AAPM TG-51 addendum (2012)** specifies the 192Ir HDR calibration chain.

#### 14.2 QA programs

| AAPM TG | Topic |
|---------|-------|
| **TG-40** (1994) / **TG-142** (2009) | EBRT comprehensive QA (BT-specific sections) |
| **TG-43 / 43U1 / 43U1S1** | Source dosimetry formalism |
| **TG-51 addendum** | HDR 192Ir calibration |
| **TG-100** (2016) | Risk-based FMEA, process map, fault-tree |
| **TG-148** | Remote afterloader QA (daily, monthly, annual) |
| **TG-167** | Electronic brachytherapy (Intrabeam, Xoft) |
| **TG-229** | MBDCA |
| **TG-232** | Radiochromic film dosimetry |
| **TG-253** | BT TPS commissioning |
| **TG-259** | Dose prescription/reporting templates |

#### 14.3 HDR afterloader daily QA
- Source position accuracy (<= 1 mm)
- Source transit time (<= 1.5 s)
- Timer accuracy
- Treatment room door interlocks
- Source activity check
- Emergency retraction and backup systems

#### 14.4 Patient-specific QA
- **Independent dose calculation** (commercial secondary check).
- **Film** (Gafchromic EBT3 / EBT4) for planimetric QA.
- **In vivo dosimetry** (MOSFET, OSL, diodes) for special cases.
[Sources: web/aapm-tg100-2016-fmea.md, web/aapm-tg51-hdr-2012-addendum.md, web/aapm-tg148-hdr-remote-afterloader.md, web/aapm-tg167-electronic-brachytherapy.md, web/aapm-tg229-2016-mbdca.md, web/aapm-tg232-2016-radiochromic-film.md, web/aapm-tg253-brachyvision-commissioning.md, web/aapm-tg259-2020-dose-reporting.md, web/aapm-tg-43-tg-186-tg-229.md, web/estro-abs-commissioning.md, web/iaea-trs398-2000.md, web/iaea-human-health-series-30.md]

---

### §15. Outcomes & Evidence Levels

| Trial | Site | Regimen | Key result |
|-------|------|---------|-----------|
| **EMBRACE-I** (n = 1341) | Cervix | EBRT 45-50 + chemo + MRI-IGABT | 5-yr LC 92%, OS 74%, Grade 3+ GU 5%, GI 8% |
| **EMBRACE-II** | Cervix | 90 Gy HR-CTV D90, ITB/IMRT | 3-yr LC 95% (preliminary, 2024) |
| **PORTEC-2** | Endometrial (intermediate) | VCB vs EBRT | 5-yr VF 5.0% vs 5.1%, non-inferior; better QoL |
| **ASCENDE-RT** | Prostate (intermediate/high) | EBRT + LDR boost vs EBRT | 6-yr BCF 86% vs 70%, p < 0.001; more GU toxicity |
| **NSABP B-39 / RTOG 0413** | Breast APBI | 34/10 BID vs WBI | 10-yr IBTR 4.6% vs 3.9% (NS), BT superior to 3D-CRT |
| **GEC-ESTRO phase III** | Breast APBI | 32/8 BID vs WBI | 5-yr IBTR 1.4% vs 0.9% (NS); non-inferior at 10y |
| **TARGIT-A** | Breast IORT | Intrabeam 20 Gy vs WBI | 5-yr LR 3.3% vs 1.3% (NS); non-inferior in low-risk |
| **EORTC 22881** | Breast boost | 10/2 boost vs no boost | 20-yr IBF 14% vs 26% (age < 50) |
| **RTOG 0236** (SBRT, BT analog) | Lung | SBRT 54 Gy/3 | 5-yr LC 93% (SBRT, reference) |
| **OPERA** | Rectal | Contact XRT 30 Gy x 3 + EBRT vs EBRT | 3-yr OP 79% vs 60% (p < 0.001) |
| **CACA/CSCO pancreatic I-125** | Pancreas LAPC | I-125 110-140 Gy + gem | 1-yr OS 30-50%, pain relief > 80% |
| **ABS / GEC-ESTRO penile HDR** | Penis T1-T2 | HDR 38-42 Gy IS | 5-yr LC 85%, organ preservation 80% |

[Sources: web/embrace-i-pivotal-2021.md, web/embrace-i-secondary-2022.md, web/embrace-ii-protocol.md, web/02_ascende_rt_trial.md, web/04_nsabp_b39_rtoc_0413.md, web/03_gec_estro_apbi_2018.md, web/05_targit_iort_trial.md, web/08_brachytherapy_boost_wbi.md, web/opera-trial-rectal.md, web/pancreatic-cscr-gemcitabine-i125.md, web/07_gec_estro_penis.md, web/portec-3-endometrial-bt.md]

---

### §16. Open Questions & Future Directions

| Topic | Direction |
|-------|-----------|
| **Focal / ultra-focal prostate BT** | GTV-only 19 Gy single-fx; need long-term (10-yr) data on in-field failure |
| **AI-driven plan optimization** | Deep-learning dose prediction (DoseNet, D3UNet); auto-contouring (nnU-Net); multi-criteria inverse planning |
| **FLASH brachytherapy** | Ultra-high (>40 Gy/s) dose-rate; preclinical radiobiology suggests reduced normal-tissue effect; prototype Ir-192 linac |
| **Adaptive plan of the day** | Daily MRI-based re-planning; reduce planning margin; AI-driven OAR/CTV auto-shrinkage |
| **3D-printed patient-specific applicators** | Personalized fit; complex anatomy (nasal, deep vaginal, endobronchial tree) |
| **Surface + interstitial hybrid BT** | Combination of HAM flap and needles for irregular tumors |
| **Combined BT + immunotherapy** | Cervical, head/neck, rectal - abscopal effect hypotheses |
| **Combined BT + nanoparticles** | AuNPs, GdNPs for dose enhancement (preclinical) |
| **Decentralized BT delivery** | High-income vs low-income country access (IAEA PACT, DIRAC database) |

[Sources: web/09_focal_prostate_HDR.md, web/10_salvage_brachytherapy.md, web/pattern-of-care-bt-access-disparities.md, web/iaea-bracchytherapy-programs.md, web/embrace-ii-protocol.md]

---

## Sources Index

All source files live under `BrachyBot/clinical_kb/sources/`. Click the local-file path to open the file, and consult the original URL for the canonical reference.

### 01 - Gynecologic (16 sources)
- [web/gec-estro-cervix-2018.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/gec-estro-cervix-2018.md) - GEC-ESTRO/ABS IGRT/ART consensus, HR-CTV/IR-CTV/GTV (2018). https://www.estro.org
- [web/embrace-cervix-hr-ctv-mri.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/embrace-cervix-hr-ctv-mri.md) - Haie-Meder / Dimopoulos MRI target definition (2005, 2012).
- [web/embrace-i-pivotal-2021.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/embrace-i-pivotal-2021.md) - EMBRACE-I 5-yr LC 92% (2021).
- [web/embrace-ii-protocol.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/embrace-ii-protocol.md) - EMBRACE-II (2018, 2024).
- [web/embrace-i-secondary-2022.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/embrace-i-secondary-2022.md) - OAR dose-response (2022).
- [web/embrace-cervix-prognostic-factors.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/embrace-cervix-prognostic-factors.md) - Prognostic factors (2015-2024).
- [web/abs-cervix-2018.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/abs-cervix-2018.md) - ABS 2018 cervical cancer BT guideline. https://www.americanbrachytherapy.org
- [web/nccn-cervical-v4-2024.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/nccn-cervical-v4-2024.md) - NCCN cervical v4.2024. https://www.nccn.org
- [web/icru-report-89-gyn.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/icru-report-89-gyn.md) - ICRU 89. https://www.icru.org
- [web/ic-is-hybrid-applicators-2020.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/ic-is-hybrid-applicators-2020.md) - Vienna, T&O + needles (2020).
- [web/cervix-postop-bt-evidence.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/cervix-postop-bt-evidence.md) - GOG 92/99, Sedlis (1999, 2003).
- [web/portec-3-endometrial-bt.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/portec-3-endometrial-bt.md) - PORTEC-2/3 (2010, 2018).
- [web/gec-estro-icru-vcb-2024.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/gec-estro-icru-vcb-2024.md) - GEC-ESTRO/ESTRO/ABS 2024.
- [web/abs-vaginal-cancer-2019.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/abs-vaginal-cancer-2019.md) - ABS vaginal BT (2019).
- [web/abs-vulvar-cancer-2019.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/abs-vulvar-cancer-2019.md) - ABS vulvar BT (2019).
- [web/pdr-gyn-2005.md](BrachyBot/clinical_kb/sources/01_gynecologic/web/pdr-gyn-2005.md) - PDR recommendations (2005).

### 02 - Prostate & GU (12 sources)
- [web/01_abs_2022_prostate_consensus.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/01_abs_2022_prostate_consensus.md) - ABS 2022 prostate. https://www.americanbrachytherapy.org
- [web/02_ascende_rt_trial.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/02_ascende_rt_trial.md) - ASCENDE-RT (2017).
- [web/03_abs_ldr_permanent_seed.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/03_abs_ldr_permanent_seed.md) - ABS/AUA/ASTRO LDR (2017).
- [web/04_aapm_tg137_prostate.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/04_aapm_tg137_prostate.md) - AAPM TG-137 (2009, rev 2017).
- [web/05_aua_astro_2022.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/05_aua_astro_2022.md) - AUA/ASTRO 2022. https://www.auanet.org
- [web/06_gec_estro_prostate_HDR.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/06_gec_estro_prostate_HDR.md) - GEC-ESTRO ACROP HDR (2020).
- [web/07_gec_estro_penis.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/07_gec_estro_penis.md) - Penile BT (2018).
- [web/08_bladder_brachytherapy.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/08_bladder_brachytherapy.md) - Bladder multicatheter (2010-2020).
- [web/09_focal_prostate_HDR.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/09_focal_prostate_HDR.md) - Focal/ultra-focal HDR (2020-2024).
- [web/10_salvage_brachytherapy.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/10_salvage_brachytherapy.md) - Salvage/re-implant (2019-2023).
- [web/11_real_time_trus_planning.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/11_real_time_trus_planning.md) - Real-time TRUS (2010-2020).
- [web/12_urethra_sparing_NVB.md](BrachyBot/clinical_kb/sources/02_prostate_gu/web/12_urethra_sparing_NVB.md) - Urethra/NVB dosimetry (2017-2023).

### 03 - Breast (13 sources)
- [web/01_astro_2022_apbi_consensus.md](BrachyBot/clinical_kb/sources/03_breast/web/01_astro_2022_apbi_consensus.md) - ASTRO 2022 APBI. https://www.astro.org
- [web/02_abs_2016_apbi_consensus.md](BrachyBot/clinical_kb/sources/03_breast/web/02_abs_2016_apbi_consensus.md) - ABS 2016 APBI.
- [web/03_gec_estro_apbi_2018.md](BrachyBot/clinical_kb/sources/03_breast/web/03_gec_estro_apbi_2018.md) - GEC-ESTRO phase III.
- [web/04_nsabp_b39_rtoc_0413.md](BrachyBot/clinical_kb/sources/03_breast/web/04_nsabp_b39_rtoc_0413.md) - NSABP B-39 / RTOG 0413. https://www.thelancet.com
- [web/05_targit_iort_trial.md](BrachyBot/clinical_kb/sources/03_breast/web/05_targit_iort_trial.md) - TARGIT-A. https://www.thelancet.com
- [web/06_balloon_brachytherapy_mammosite.md](BrachyBot/clinical_kb/sources/03_breast/web/06_balloon_brachytherapy_mammosite.md) - Balloon BT.
- [web/07_interstitial_multicatheter_apbi.md](BrachyBot/clinical_kb/sources/03_breast/web/07_interstitial_multicatheter_apbi.md) - Interstitial multicatheter.
- [web/08_brachytherapy_boost_wbi.md](BrachyBot/clinical_kb/sources/03_breast/web/08_brachytherapy_boost_wbi.md) - EORTC 22881 boost.
- [web/09_nccn_breast_2024.md](BrachyBot/clinical_kb/sources/03_breast/web/09_nccn_breast_2024.md) - NCCN breast 2024.
- [web/10_dose_constraints_oar_breast.md](BrachyBot/clinical_kb/sources/03_breast/web/10_dose_constraints_oar_breast.md) - OAR constraints.
- [web/11_iort_electronic_brachytherapy.md](BrachyBot/clinical_kb/sources/03_breast/web/11_iort_electronic_brachytherapy.md) - IORT eBT.
- [web/12_estro_hypofractionation_consensus.md](BrachyBot/clinical_kb/sources/03_breast/web/12_estro_hypofractionation_consensus.md) - ESTRO 2018 hypofractionation.
- [web/13_savi_strut_based_apbi.md](BrachyBot/clinical_kb/sources/03_breast/web/13_savi_strut_based_apbi.md) - SAVI strut-based.

### 04 - Head & Neck + Skin (16 sources)
- [web/abs_2018_head_neck_guidelines.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/abs_2018_head_neck_guidelines.md) - ABS 2018 H&N.
- [web/gec_estro_2018_skin_brachytherapy.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/gec_estro_2018_skin_brachytherapy.md) - GEC-ESTRO 2018 skin.
- [web/paris_system_dosimetry.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/paris_system_dosimetry.md) - Paris system / ICRU 58.
- [web/npc_intracavitary_brachytherapy.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/npc_intracavitary_brachytherapy.md) - NPC ICBT.
- [web/lip_cancer_brachytherapy.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/lip_cancer_brachytherapy.md) - Lip cancer.
- [web/freiburg_flap_ham_surface_applicators.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/freiburg_flap_ham_surface_applicators.md) - Freiburg/HAM/3D-printed.
- [web/reirradiation_recurrent_head_neck.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/reirradiation_recurrent_head_neck.md) - Re-irradiation.
- [web/keloid_brachytherapy.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/keloid_brachytherapy.md) - Keloid BT.
- [web/nccn_head_neck_skin_cancer.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/nccn_head_neck_skin_cancer.md) - NCCN H&N + skin.
- [web/hdr_vs_ldr_mold_therapy.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/hdr_vs_ldr_mold_therapy.md) - HDR vs LDR mold.
- [web/oropharyngeal_brachytherapy.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/oropharyngeal_brachytherapy.md) - Oropharyngeal.
- [web/iao_education_tongue_implant.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/iao_education_tongue_implant.md) - Tongue implant workflow.
- [web/skin_bt_outcomes_cosmesis.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/skin_bt_outcomes_cosmesis.md) - Skin BT outcomes.
- [web/petros_sinuses_temporal_bone.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/petros_sinuses_temporal_bone.md) - Salivary/sinus/skull base.
- [web/electronic_brachytherapy_esteya.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/electronic_brachytherapy_esteya.md) - eBT Esteya/Xoft/Intrabeam.
- [web/icru_89_interstitial_guidance.md](BrachyBot/clinical_kb/sources/04_head_neck_skin/web/icru_89_interstitial_guidance.md) - ICRU 89 interstitial.

### 05 - GI (13 sources)
- [web/abs-esophageal-2014.md](BrachyBot/clinical_kb/sources/05_gi/web/abs-esophageal-2014.md) - ABS esophageal (2014).
- [web/nccn-esophageal-bt-2024.md](BrachyBot/clinical_kb/sources/05_gi/web/nccn-esophageal-bt-2024.md) - NCCN esophageal 2024.
- [web/icru-89-esophagus.md](BrachyBot/clinical_kb/sources/05_gi/web/icru-89-esophagus.md) - ICRU 89 GI section.
- [web/papillon-contact-xray-rectal.md](BrachyBot/clinical_kb/sources/05_gi/web/papillon-contact-xray-rectal.md) - Papillon rectal.
- [web/opera-trial-rectal.md](BrachyBot/clinical_kb/sources/05_gi/web/opera-trial-rectal.md) - OPERA trial rectal. https://www.thelancet.com
- [web/rectal-recurrence-hdr-ic.md](BrachyBot/clinical_kb/sources/05_gi/web/rectal-recurrence-hdr-ic.md) - Recurrent rectal HDR.
- [web/anal-cancer-brachytherapy-boost.md](BrachyBot/clinical_kb/sources/05_gi/web/anal-cancer-brachytherapy-boost.md) - Anal BT boost.
- [web/bileduct-cholangiocarcinoma-ptbd.md](BrachyBot/clinical_kb/sources/05_gi/web/bileduct-cholangiocarcinoma-ptbd.md) - Bile duct BT.
- [web/cstro-pancreatic-iodine-seeds.md](BrachyBot/clinical_kb/sources/05_gi/web/cstro-pancreatic-iodine-seeds.md) - CSTRO pancreatic I-125.
- [web/pancreatic-i125-clinical-series.md](BrachyBot/clinical_kb/sources/05_gi/web/pancreatic-i125-clinical-series.md) - I-125 pancreatic.
- [web/pancreatic-cscr-gemcitabine-i125.md](BrachyBot/clinical_kb/sources/05_gi/web/pancreatic-cscr-gemcitabine-i125.md) - I-125 + gemcitabine.
- [web/gastric-brachytherapy.md](BrachyBot/clinical_kb/sources/05_gi/web/gastric-brachytherapy.md) - Gastric BT.
- [web/embrace-i-gi.md](BrachyBot/clinical_kb/sources/05_gi/web/embrace-i-gi.md) - AAPM TG-229 GI.

### 06 - Other Sites (13 sources)
- [web/pmid-37217415-hdre-airway.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-37217415-hdre-airway.md) - HDREB airway (Siddiqui 2023). https://pubmed.ncbi.nlm.nih.gov/37217415
- [web/pmid-36610615-brachy-trial.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-36610615-brachy-trial.md) - BRACHY RCT (Sur 2023). https://pubmed.ncbi.nlm.nih.gov/36610615
- [web/pmid-23541114-hdre-palliation.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-23541114-hdre-palliation.md) - HDREB palliation (de Aquino 2013). https://pubmed.ncbi.nlm.nih.gov/23541114
- [web/pmid-11240245-abs-sarcoma.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-11240245-abs-sarcoma.md) - ABS sarcoma (Nag 2001). https://pubmed.ncbi.nlm.nih.gov/11240245
- [web/pmid-27695605-abtc-gliasite.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-27695605-abtc-gliasite.md) - ABTC GliaSite (Kleinberg 2015). https://pubmed.ncbi.nlm.nih.gov/27695605
- [web/pmid-41360286-cs131-gbm.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-41360286-cs131-gbm.md) - Cs-131 GammaTile (Haisraely 2026). https://pubmed.ncbi.nlm.nih.gov/41360286
- [web/pmid-30320093-ru106-plaque.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-30320093-ru106-plaque.md) - Ru-106 plaque (Stoeckel 2018). https://pubmed.ncbi.nlm.nih.gov/30320093
- [web/pmid-11370500-mgh-uveal.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-11370500-mgh-uveal.md) - Uveal MGH review. https://pubmed.ncbi.nlm.nih.gov/11370500
- [web/pmid-8814740-coms-visual.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-8814740-coms-visual.md) - COMS visual outcome. https://pubmed.ncbi.nlm.nih.gov/8814740
- [web/pmid-32656945-aapm-tg129-applied.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-32656945-aapm-tg129-applied.md) - TG-129 notched plaque.
- [web/pmid-12957267-vascular-bt.md](BrachyBot/clinical_kb/sources/06_other_sites/web/pmid-12957267-vascular-bt.md) - Vascular BT review.
- [web/nci-brachytherapy-overview.md](BrachyBot/clinical_kb/sources/06_other_sites/web/nci-brachytherapy-overview.md) - NCI BT overview. https://www.cancer.gov
- [web/abstracts-batch-misc.md](BrachyBot/clinical_kb/sources/06_other_sites/web/abstracts-batch-misc.md) - Misc batch.

### 07 - Physics (21 sources)
- [web/aapm-tg43-1995-nath.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg43-1995-nath.md) - TG-43 (Nath 1995).
- [web/aapm-tg43u1-2004-rivard.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg43u1-2004-rivard.md) - TG-43U1 (Rivard 2004).
- [web/aapm-tg43u1s1-2012-perez-calatayud.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg43u1s1-2012-perez-calatayud.md) - TG-43U1S1 (Perez-Calatayud 2012).
- [web/aapm-tg229-2016-mbdca.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg229-2016-mbdca.md) - TG-229 MBDCA.
- [web/aapm-tg-uuid-200-tg186-mbdca-details.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg-uuid-200-tg186-mbdca-details.md) - TG-186/AAPM-ESTRO MBDCA.
- [web/aapm-tg232-2016-radiochromic-film.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg232-2016-radiochromic-film.md) - TG-232 film.
- [web/aapm-tg100-2016-fmea.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg100-2016-fmea.md) - TG-100 FMEA.
- [web/aapm-tg51-hdr-2012-addendum.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg51-hdr-2012-addendum.md) - TG-51 HDR addendum.
- [web/aapm-tg148-hdr-remote-afterloader.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg148-hdr-remote-afterloader.md) - TG-148 afterloader.
- [web/aapm-tg253-brachyvision-commissioning.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg253-brachyvision-commissioning.md) - TG-253 TPS.
- [web/aapm-tg167-electronic-brachytherapy.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg167-electronic-brachytherapy.md) - TG-167 eBT.
- [web/aapm-tg259-2020-dose-reporting.md](BrachyBot/clinical_kb/sources/07_physics/web/aapm-tg259-2020-dose-reporting.md) - TG-259 dose reporting.
- [web/icru-reports-38-58.md](BrachyBot/clinical_kb/sources/07_physics/web/icru-reports-38-58.md) - ICRU 38/58.
- [web/icru-report-89-2013-gyn.md](BrachyBot/clinical_kb/sources/07_physics/web/icru-report-89-2013-gyn.md) - ICRU 89.
- [web/iaea-trs398-2000.md](BrachyBot/clinical_kb/sources/07_physics/web/iaea-trs398-2000.md) - IAEA TRS-398. https://www.iaea.org
- [web/iaea-human-health-series-30.md](BrachyBot/clinical_kb/sources/07_physics/web/iaea-human-health-series-30.md) - IAEA HHS 30.
- [web/gec-estro-ipsa-hipo-optimization.md](BrachyBot/clinical_kb/sources/07_physics/web/gec-estro-ipsa-hipo-optimization.md) - IPSA / HIPO.
- [web/embrace-ii-protocol-2018.md](BrachyBot/clinical_kb/sources/07_physics/web/embrace-ii-protocol-2018.md) - EMBRACE-II.
- [web/dicom-rt-interoperability.md](BrachyBot/clinical_kb/sources/07_physics/web/dicom-rt-interoperability.md) - DICOM-RT BT.
- [web/estro-abs-commissioning.md](BrachyBot/clinical_kb/sources/07_physics/web/estro-abs-commissioning.md) - ESTRO/ABS commissioning.

### 08 - Frameworks (18 sources)
- [web/gec-estro-recommendations-2005.md](BrachyBot/clinical_kb/sources/08_frameworks/web/gec-estro-recommendations-2005.md) - GEC-ESTRO 3D cervix Part I (2005).
- [web/gec-estro-recommendations-2006.md](BrachyBot/clinical_kb/sources/08_frameworks/web/gec-estro-recommendations-2006.md) - GEC-ESTRO Part II (2006).
- [web/icru-report-89-2016.md](BrachyBot/clinical_kb/sources/08_frameworks/web/icru-report-89-2016.md) - ICRU 89 (2016).
- [web/embrace-i-protocol-2010.md](BrachyBot/clinical_kb/sources/08_frameworks/web/embrace-i-protocol-2010.md) - EMBRACE-I protocol.
- [web/embrace-ii-protocol-2016.md](BrachyBot/clinical_kb/sources/08_frameworks/web/embrace-ii-protocol-2016.md) - EMBRACE-II protocol.
- [web/abs-cervix-consensus-2018.md](BrachyBot/clinical_kb/sources/08_frameworks/web/abs-cervix-consensus-2018.md) - ABS cervix (2018).
- [web/abs-prostate-consensus-2012-2020.md](BrachyBot/clinical_kb/sources/08_frameworks/web/abs-prostate-consensus-2012-2020.md) - ABS prostate (2012, 2020).
- [web/abs-breast-apbi-consensus.md](BrachyBot/clinical_kb/sources/08_frameworks/web/abs-breast-apbi-consensus.md) - ABS breast (2009-2023).
- [web/nccn-guidelines-cervical-prostate-breast.md](BrachyBot/clinical_kb/sources/08_frameworks/web/nccn-guidelines-cervical-prostate-breast.md) - NCCN CPGs (2024).
- [web/esgo-estro-esp-cervical-2023.md](BrachyBot/clinical_kb/sources/08_frameworks/web/esgo-estro-esp-cervical-2023.md) - ESGO/ESTRO/ESP (2023).
- [web/aapm-tg-43-tg-186-tg-229.md](BrachyBot/clinical_kb/sources/08_frameworks/web/aapm-tg-43-tg-186-tg-229.md) - AAPM TGs.
- [web/iaea-bracchytherapy-programs.md](BrachyBot/clinical_kb/sources/08_frameworks/web/iaea-bracchytherapy-programs.md) - IAEA PACT/DIRAC. https://dirac.iaea.org
- [web/astro-brachytherapy-guidelines.md](BrachyBot/clinical_kb/sources/08_frameworks/web/astro-brachytherapy-guidelines.md) - ASTRO. https://www.astro.org
- [web/caca-csco-cstro-chinese-bt-consensus.md](BrachyBot/clinical_kb/sources/08_frameworks/web/caca-csco-cstro-chinese-bt-consensus.md) - CACA/CSCO/CSTRO. https://www.csco.org.cn
- [web/ars-appropriate-use-criteria.md](BrachyBot/clinical_kb/sources/08_frameworks/web/ars-appropriate-use-criteria.md) - ARS AUC. https://www.americanradium.org
- [web/esmo-brachytherapy-recommendations.md](BrachyBot/clinical_kb/sources/08_frameworks/web/esmo-brachytherapy-recommendations.md) - ESMO. https://www.esmo.org
- [web/icrp-publications-bt-radiation-protection.md](BrachyBot/clinical_kb/sources/08_frameworks/web/icrp-publications-bt-radiation-protection.md) - ICRP. https://www.icrp.org
- [web/pattern-of-care-bt-access-disparities.md](BrachyBot/clinical_kb/sources/08_frameworks/web/pattern-of-care-bt-access-disparities.md) - Patterns of care.

---

## All References (clickable)

| Society / Body | URL |
|----------------|-----|
| ABS - American Brachytherapy Society | https://www.americanbrachytherapy.org |
| AAPM - American Association of Physicists in Medicine | https://www.aapm.org |
| ASTRO - American Society for Radiation Oncology | https://www.astro.org |
| AUA - American Urological Association | https://www.auanet.org |
| ARS - American Radium Society | https://www.americanradium.org |
| CACA - China Anti-Cancer Association | http://www.caca.org.cn |
| CSCO - Chinese Society of Clinical Oncology | https://www.csco.org.cn |
| CSTRO - Chinese Society of Therapeutic Radiation Oncology | http://www.cstro.org |
| ESGO - European Society of Gynaecological Oncology | https://www.esgo.org |
| ESMO - European Society for Medical Oncology | https://www.esmo.org |
| ESTRO - European Society for Radiotherapy & Oncology | https://www.estro.org |
| GEC-ESTRO | https://www.estro.org/Groups/GEC-ESTRO |
| IAEA - International Atomic Energy Agency | https://www.iaea.org |
| IAEA DIRAC database | https://dirac.iaea.org |
| ICRP - International Commission on Radiological Protection | https://www.icrp.org |
| ICRU - International Commission on Radiation Units and Measurements | https://www.icru.org |
| NCCN - National Comprehensive Cancer Network | https://www.nccn.org |
| NCI - National Cancer Institute | https://www.cancer.gov |
| PubMed / NLM | https://pubmed.ncbi.nlm.nih.gov |
| Lancet Oncology | https://www.thelancet.com/journals/lanonc |
| Red Journal (IJROBP) | https://www.redjournal.org |
| Brachytherapy (journal) | https://www.brachyjournal.com |
| Radiotherapy & Oncology | https://www.thegreenjournal.com |

---

*This document is auto-curated by the BrachyBot clinical module. Updates are merged from the 8 source folders under `clinical_kb/sources/`. When a new society guideline is published, the corresponding `web/` source file should be added and the relevant section updated in this file.*
