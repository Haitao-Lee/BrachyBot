# BrachyBot Clinical Knowledge Base

> **Scope:** All clinical brachytherapy applications relevant to the BrachyBot project — gynecologic, prostate/GU, breast, head & neck / skin, gastrointestinal, lung, brain, eye, sarcoma, pediatric, vascular, and the physics / dosimetry foundations that underlie them.

> **Built:** 2026-06-17  
> **Source files:** 110 (real, fetched from PubMed, PMC, top journals, society websites)  
> **Structure:** Tree-organized by clinical site → sub-topic → individual source entry. Every entry has a stable ID (`<a id="kb:..."></a>`) and topic tags for RAG retrieval.  
> **Source root:** [`sources/`](sources/) — 8 categories, each with INDEX.md and raw/ markdown files.

---

## ⚠️ Verification Provenance

This KB is **strictly traceable**: every claim is tied to a specific source file in [`sources/`](sources/). **No subjective model knowledge has been added.** If a topic is not represented in the 110 source files, it is not represented in this KB.

**Fetch methods:**
- `top-journal` — PubMed abstracts from top-tier journals (Lancet, JAMA, NEJM, Lancet Oncology, JAMA Oncology, BMJ, Nature family, JCO)
- `curl+pubmed` — Full PubMed abstract pages fetched via curl
- `pmc-fulltext` — PubMed Central full-text pages
- `title-verified` — Metadata + abstract verified by title search
- `manual-metadata` — Official society / ICRU / IAEA / NCCN methodology documents
- `metadata-stub` — Paywalled title/abstract only (NCCN, Chinese society documents)
- `local-pdf` — Derived from PDF on user's separate machine; full text not on this system

**Files excluded as polluted (verified by reading content, not filename):**
- `01_gynecologic/raw/portec-3-lancet-oncol-2018.md` — title is 'Desert Immune Phenotype in Endometrial Carcinoma'; PORTEC-3 is only the data source. Tumor-immunology paper, not a brachytherapy paper.
- `04_head_neck_skin/raw/eortc-postop-sbrt-oropharyngeal-2024.md` — STEREOPOSTOP-GORTEC trial. Intervention is SBRT, not BT.
- `06_other_sites/raw/acr-asnr-practice-parameter-2025.md` — Practice parameter is for image-guided **epidural steroid injection**, not BT.
- `07_physics/raw/aapm-tg-100-fmea.md` — TG-100 framework applied to **proton** PBS commissioning, not BT.

---

## 🗺️ Topic Tree

Navigate the KB by clinical site → sub-topic → individual source entry.

### Part II / gyn — Gynecologic Brachytherapy (17 files)
  - **[Cervix Cancer BT](#gyn-cervix)** (12 files)
  - **[Endometrial Cancer BT](#gyn-endometrial)** (3 files)
  - **[Vaginal & Vulvar Cancer BT](#gyn-vaginal_vulvar)** (2 files)

### Part II / pros — Prostate & Genitourinary BT (14 files)
  - **[LDR Permanent Seed BT](#pros-ldr)** (3 files)
  - **[HDR Brachytherapy](#pros-hdr)** (4 files)
  - **[Microboost & Focal Sparing](#pros-microboost_focal)** (2 files)
  - **[Salvage BT](#pros-salvage)** (1 files)
  - **[Penile BT](#pros-penile)** (2 files)
  - **[Guidelines / Methodology](#pros-guidelines)** (2 files)

### Part II / brst — Breast Brachytherapy (13 files)
  - **[Accelerated Partial Breast Irradiation (APBI)](#brst-apbi)** (8 files)
  - **[Intraoperative RT (IORT)](#brst-iort)** (2 files)
  - **[Reirradiation](#brst-reirradiation)** (1 files)
  - **[Whole Breast Boost](#brst-boost)** (1 files)
  - **[Guidelines](#brst-guidelines)** (1 files)

### Part II / hns — Head & Neck / Skin BT (12 files)
  - **[Head & Neck Cancers](#hns-hn_cancer)** (4 files)
  - **[Skin Cancer (NMSC) & Superficial BT](#hns-skin)** (4 files)
  - **[Keloid](#hns-keloid)** (1 files)
  - **[Practice Parameters](#hns-practice_param)** (1 files)
  - **[Related (Cervical/Vulvar QoL — file miscategorized in 04)](#hns-related_gyne_qol)** (2 files)

### Part II / gi — Gastrointestinal BT (14 files)
  - **[Esophageal BT](#gi-esophageal)** (2 files)
  - **[Rectal BT](#gi-rectal)** (4 files)
  - **[Anal Canal BT](#gi-anal)** (1 files)
  - **[Pancreatic BT (Permanent I-125)](#gi-pancreatic)** (5 files)
  - **[Biliary Tract BT](#gi-biliary)** (1 files)
  - **[Gastric BT](#gi-gastric)** (1 files)

### Part II / oth — Other Sites BT (13 files)
  - **[Lung BT](#oth-lung)** (3 files)
  - **[Brain & Spine BT](#oth-brain_spine)** (3 files)
  - **[Eye / Uveal BT](#oth-eye)** (2 files)
  - **[Soft Tissue Sarcoma BT](#oth-sarcoma)** (1 files)
  - **[Pediatric BT](#oth-pediatric)** (1 files)
  - **[Vascular BT](#oth-vascular)** (2 files)
  - **[Malignant Tumors (General — I-125 + Hyperthermia)](#oth-malignant_general)** (1 files)

### Part II / phys — Physics & Dosimetry (13 files)
  - **[AAPM TG-43 Formalism](#phys-tg43)** (3 files)
  - **[ICRU Reports](#phys-icru)** (2 files)
  - **[IAEA Publications](#phys-iaea)** (2 files)
  - **[AAPM Task Groups (Other)](#phys-aapm_other)** (3 files)
  - **[AI / Inverse Treatment Planning](#phys-ai_planning)** (1 files)
  - **[Afterloader Commissioning](#phys-afterloader)** (1 files)
  - **[3D Printing](#phys-3d_printing)** (1 files)

### Part II / frm — Frameworks & Society Initiatives (13 files)
  - **[Society Methodology](#frm-society_methodology)** (5 files)
  - **[IAEA / WHO Programs](#frm-iaea_who)** (3 files)
  - **[Global Access & Transition](#frm-global_access)** (3 files)
  - **[Chinese Societies (CSCO / CSTRO)](#frm-chinese)** (2 files)

---

## How to Use This KB

1. **RAG-friendly stable IDs:** every entry has a `<a id="kb:cat:sub:file"></a>` anchor. Reference by ID for precise chunk lookup.
2. **Topic tags:** each entry lists its topic tags inline (`Topics: [...]`). Use them to filter / cluster.
3. **Cross-references:** every entry has a `See also` section linking related entries (same trial family, same disease site, same guideline family).
4. **Reverse index:** Part III §Topic Index lists every topic and the entry IDs that contain it.
5. **Verify a fact:** open the linked source file, scroll to its `## Abstract` section. The fact must be in that file.
6. **Cite in a report:** copy the file's DOI/PMID; the metadata is in each file's YAML frontmatter.

---

## Part I: Foundations

Foundational documents are interleaved with their primary site. Cross-references below point to the most-cited foundational entries.

### Image-Guided Adaptive BT (IGABT)

The cornerstone papers for IGABT:
- [GEC-ESTRO 2005 Haie-Meder (foundation paper)](#kb:gyn:cervix:gec-estro-cervix-2005-haie-meder)
- [ICRU Report 89 (2013)](#kb:gyn:cervix:icru-89-gyn)
- [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet-oncol)
- [EMBRACE-II Protocol (2018)](#kb:gyn:cervix:embrace-ii-protocol)
- [AAPM TG-43U1 (2004)](#kb:phys:tg43:aapm-tg-43u1-rivard-2004)

### TG-43 / Dosimetry Formalism

- [TG-43 1995 (Nath)](#kb:phys:tg43:aapm-tg-43-nath-1995)
- [TG-43U1 2004 (Rivard)](#kb:phys:tg43:aapm-tg-43u1-rivard-2004)
- [TG-43U1S1 2012 (Perez-Calatayud)](#kb:phys:tg43:aapm-tg-43u1s1-perez-2012)
- [AAPM TG-229 MBDCA 2012](#kb:phys:aapm_other:aapm-tg-229-mbdca)

---

## Part II: Disease Sites

## <a id="gyn"></a> Gynecologic Brachytherapy (17 files)

**Subtitle:** cervix, endometrium, vagina, vulva  
**Master list:** [`sources/01_gynecologic/INDEX.md`](sources/01_gynecologic/INDEX.md)

### <a id="gyn-cervix"></a> Cervix Cancer BT (12 files)

<a id="kb:gyn:cervix:abs-cervix-consensus-2012-part1"></a>

#### 01_gynecologic — Gynecologic Brachytherapy (17 files)

📄 [abs-cervix-consensus-2012-part1.md](sources/01_gynecologic/raw/abs-cervix-consensus-2012-part1.md)


**Topics:** `cervix`, `ABS`, `consensus`, `general-principles`, `LDR`, `HDR`, `PDR`, `dose-80-90-Gy`, `point-A`

**See also:**
- → [#kb:gyn:cervix:abs-cervix-consensus-2012-part2](#kb:gyn:cervix:abs-cervix-consensus-2012-part2) (`abs-cervix-consensus-2012-part2.md`)
- → [#kb:gyn:cervix:abs-vaginal-2012](#kb:gyn:cervix:abs-vaginal-2012) (`abs-vaginal-2012.md`)
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)
- → [#kb:gyn:cervix:gec-estro-cervix-2005-haie](#kb:gyn:cervix:gec-estro-cervix-2005-haie) (`gec-estro-cervix-2005-haie-meder.md`)

---

<a id="kb:gyn:cervix:abs-cervix-consensus-2012-part2"></a>

#### ABS consensus guidelines for locally advanced cervix carcinoma. Part II: HDR brachytherapy (2012)

📄 [abs-cervix-consensus-2012-part2.md](sources/01_gynecologic/raw/abs-cervix-consensus-2012-part2.md)

**Journal:** Brachytherapy  
**DOI:** 10.1016/j.brachy.2011.07.002  
**PMID:** 22265437 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/22265437/))  

**Topics:** `cervix`, `ABS`, `consensus`, `HDR`, `tandem-and-ring`, `applicator`, `dose-80-90-Gy`

**Key facts:**
- ABS affirms essential curative role of tandem-based brachytherapy for locally advanced cervical cancer.
- 3D imaging with MRI, CT, or radiographic imaging may be used for treatment planning.
- Recommended tumor dose in 2-Gy EQD (normalized total dose): 80-90 Gy depending on tumor size at time of BT.
- Dosimetry must be performed after each insertion before treatment delivery.
- Dose limits for normal tissues are discussed (bladder, rectum, sigmoid, small bowel).

**Dose constraints / prescription:**
- 80-90 Gy EQD2

**Key numbers:**
- 80-90 Gy EQD2 (HDR)

**See also:**
- → [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](#kb:gyn:cervix:abs-cervix-consensus-2012-part1) (`abs-cervix-consensus-2012-part1.md`)
- → [#kb:gyn:cervix:abs-vaginal-2012](#kb:gyn:cervix:abs-vaginal-2012) (`abs-vaginal-2012.md`)
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)

---

<a id="kb:gyn:cervix:abs-vaginal-2012"></a>

#### ABS consensus guidelines for locally advanced cervix carcinoma. Part III: LDR and PDR brachytherapy (2012)

📄 [abs-vaginal-2012.md](sources/01_gynecologic/raw/abs-vaginal-2012.md)

**Journal:** Brachytherapy  
**DOI:** 10.1016/j.brachy.2011.07.001  
**PMID:** 22265438 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/22265438/))  

**Topics:** `cervix`, `ABS`, `consensus`, `LDR`, `PDR`, `tandem-based`, `dose-80-90-Gy`

**Key facts:**
- ABS strongly recommends BT as component of definitive treatment for locally advanced cervical carcinoma (FIGO IB2-IVA).
- Cumulative delivered dose: approximately 80-90 Gy for definitive treatment.
- Dosimetry must be performed after each insertion before treatment delivery.
- Dose to point A should be reported for all intracavitary BT applications regardless of planning technique.
- ABS recommends adoption of GEC-ESTRO guidelines for contouring, image-based planning, and dose reporting.
- Interstitial BT may be considered for patients whose disease cannot be adequately encompassed by intracavitary application.

**Dose constraints / prescription:**
- 80-90 Gy cumulative dose

**Key numbers:**
- 80-90 Gy
- FIGO IB2-IVA

**See also:**
- → [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](#kb:gyn:cervix:abs-cervix-consensus-2012-part1) (`abs-cervix-consensus-2012-part1.md`)
- → [#kb:gyn:cervix:abs-cervix-consensus-2012-part2](#kb:gyn:cervix:abs-cervix-consensus-2012-part2) (`abs-cervix-consensus-2012-part2.md`)
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)

---

<a id="kb:gyn:cervix:dimopoulos-mri-ctv-2012"></a>

#### Reporting small bowel dose in cervix cancer high-dose-rate brachytherapy (2012)

📄 [dimopoulos-mri-ctv-2012.md](sources/01_gynecologic/raw/dimopoulos-mri-ctv-2012.md)

**Journal:** Radiotherapy and Oncology  
**DOI:** 10.1016/j.radonc.2011.10.016  
**PMID:** 26235549 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/26235549/))  

**Topics:** `cervix`, `small-bowel`, `OAR`, `D2cc`, `tandem-ring`, `interfraction-variation`

**Key facts:**
- Small bowel (SB) is an OAR that may develop toxicity after radiotherapy for cervix cancer; its dose from BT is not systematically reported even with IGBT.
- 13 patients treated with EBRT 45 Gy/25 fx followed by HDR-BT boost 28 Gy/4 fx using tandem/ring applicator.
- Treatment plans were revised to reduce SB dose when D2cc of SB > 5 Gy while maintaining other OAR constraints.
- Plan revisions done in 6/13 cases owing to high D2cc of SB; average reduction of 19% in D2cc achieved.
- Highest interfraction variation observed for SB at 16 ± 59%, vs 28 ± 27% for rectum, 21 ± 16% for bladder.

**Dose constraints / prescription:**
- D2cc SB < 5 Gy optimization target

**Trial endpoints / outcomes:**
- feasibility of SB sparing

**Key numbers:**
- n=13
- EBRT 45 Gy/25 fx
- HDR-BT 28 Gy/4 fx
- D2cc SB avg reduction 19%

---

<a id="kb:gyn:cervix:embrace-i-pivotal-2021-lancet"></a>

#### MRI-guided adaptive brachytherapy in locally advanced cervical cancer (EMBRACE-I): a multicentre prospective cohort study (2021)

📄 [embrace-i-pivotal-2021-lancet-oncol.md](sources/01_gynecologic/raw/embrace-i-pivotal-2021-lancet-oncol.md)

**Journal:** Lancet Oncology  
**DOI:** 10.1016/S1470-2045(20)30753-1  
**PMID:** 33794207 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/33794207/))  

**Topics:** `cervix`, `IGABT`, `MRI-based`, `EMBRACE-I`, `chemoradiotherapy`, `HR-CTV`, `5y-LC-92%`, `D90-90-Gy`, `n=1341`

**Key facts:**
- EMBRACE-I: prospective observational multicentre cohort study, 24 centres in Europe, Asia, North America, 2008-2015.
- 1416 patients registered; 1341 available for disease analysis, 1251 for morbidity assessment.
- MRI-based IGABT including dose optimisation done in 1317 (98.2%) of 1341 patients.
- Median HR-CTV: 28 cm3 (IQR 20-40); median D90: 90 Gy (IQR 85-94) EQD2.
- At median follow-up 51 months: actuarial 5-year local control 92% (95% CI 90-93).
- 5-year grade 3-5 morbidity: genitourinary 6.8%, gastrointestinal 8.5%, vaginal 5.7%, fistulae 3.2%.

**Dose constraints / prescription:**
- HR-CTV D90 median 90 Gy EQD2

**Trial endpoints / outcomes:**
- 5-year local control
- 5-year grade 3-5 organ morbidity

**Key numbers:**
- n=1341
- D90 90 Gy EQD2
- 5y LC 92%
- 5y GU G3-5 6.8%
- 5y GI G3-5 8.5%

**See also:**
- → [#kb:gyn:cervix:embrace-ii-protocol](#kb:gyn:cervix:embrace-ii-protocol) (`embrace-ii-protocol.md`)
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)
- → [#kb:gyn:cervix:gec-estro-cervix-2005-haie](#kb:gyn:cervix:gec-estro-cervix-2005-haie) (`gec-estro-cervix-2005-haie-meder.md`)
- → [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](#kb:gyn:cervix:abs-cervix-consensus-2012-part1) (`abs-cervix-consensus-2012-part1.md`)
- → [#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024](#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024) (`lancet-pembrolizumab-crt-cervical-2024.md`)

---

<a id="kb:gyn:cervix:embrace-ii-protocol"></a>

#### OAR Dose Constraints (cervix HDR — EMBRACE II)

📄 [embrace-ii-protocol.md](sources/01_gynecologic/raw/embrace-ii-protocol.md)


**Topics:** `cervix`, `EMBRACE-II`, `D2cc`, `OAR-constraints`, `HR-CTV-D90`, `n=34`

**See also:**
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)

---

<a id="kb:gyn:cervix:gec-estro-cervix-2005-haie"></a>

#### Recommendations from GYN GEC-ESTRO Working Group (I): concepts and terms in 3D image based treatment planning in cervix cancer BT with emphasis on MRI assessment of GTV and CTV (2005)

📄 [gec-estro-cervix-2005-haie-meder.md](sources/01_gynecologic/raw/gec-estro-cervix-2005-haie-meder.md)

**Journal:** Radiotherapy and Oncology  
**DOI:** 10.1016/j.radonc.2004.12.015  
**PMID:** 15763303 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/15763303/))  

**Topics:** `cervix`, `GEC-ESTRO`, `MRI`, `3D-planning`, `GTV-CTV`, `HR-CTV-definition`, `IR-CTV-definition`, `foundation-paper`

**Key facts:**
- In 2000 GEC-ESTRO decided to support 3D imaging-based 3D treatment planning in cervix cancer BT with creation of Working Group.
- Time frames: at time of diagnosis GTV(D), CTV(D); at time of BT GTV(B), CTV(B).
- CTV for BT defined related to risk for recurrence: high risk CTV and intermediate risk CTV.
- MRI-based delineation of GTV, CTV and PTV with critical organs impacts BT treatment planning.

**Key numbers:**
- GTV(D), CTV(D), GTV(B), CTV(B)
- HR-CTV, IR-CTV definitions

**See also:**
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)
- → [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](#kb:gyn:cervix:abs-cervix-consensus-2012-part1) (`abs-cervix-consensus-2012-part1.md`)

---

<a id="kb:gyn:cervix:icru-89-gyn"></a>

#### ICRU 89 Dose-Reporting Parameters

📄 [icru-89-gyn.md](sources/01_gynecologic/raw/icru-89-gyn.md)


**Topics:** `cervix`, `ICRU-89`, `dose-reporting`, `D90`, `D2cc`, `D1cc`, `D0.1cc`, `HR-CTV`, `IR-CTV`, `EQD2`

**See also:**
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)
- → [#kb:gyn:cervix:embrace-ii-protocol](#kb:gyn:cervix:embrace-ii-protocol) (`embrace-ii-protocol.md`)
- → [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](#kb:gyn:cervix:abs-cervix-consensus-2012-part1) (`abs-cervix-consensus-2012-part1.md`)
- → [#kb:gyn:cervix:gec-estro-cervix-2005-haie](#kb:gyn:cervix:gec-estro-cervix-2005-haie) (`gec-estro-cervix-2005-haie-meder.md`)
- → [#kb:phys:icru:icru-38-ic](#kb:phys:icru:icru-38-ic) (`icru-38-ic.md`)
- → [#kb:phys:icru:icru-58-is](#kb:phys:icru:icru-58-is) (`icru-58-is.md`)

---

<a id="kb:gyn:cervix:lancet-cervical-induction-chemo-2024"></a>

#### Induction chemotherapy followed by standard chemoradiotherapy versus standard chemoradiotherapy alone in patients with locally advanced cervical cancer (GCIG INTERLACE): an international, multicentre, randomised phase 3 trial (2025)

📄 [lancet-cervical-induction-chemo-2024.md](sources/01_gynecologic/raw/lancet-cervical-induction-chemo-2024.md)

**Journal:** Lancet  
**DOI:** 10.1016/S0140-6736(24)01438-7  
**PMID:** 39419054 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/39419054/))  

**Topics:** `cervix`, `INTERLACE`, `induction-chemotherapy`, `carboplatin-paclitaxel`, `5y-PFS-72%-vs-64%`, `5y-OS-80%-vs-72%`, `n=500`

**Key facts:**
- Multicentre randomised phase 3 in Brazil, India, Italy, Mexico, UK (32 centres), 2012-2022.
- 500 patients; FIGO 2008 IB1 with nodal involvement, IB2, IIA, IIB, IIIB, or IVA.
- Standard CRT: weekly cisplatin 40 mg/m2 × 5 weeks + EBRT 45-50.4 Gy in 20-28 fractions PLUS brachytherapy (minimum total EQD2 78-86 Gy).
- Induction chemo: weekly carboplatin AUC 2 + paclitaxel 80 mg/m2 × 6 weeks, then standard CRT.
- After median 67-month follow-up: 5-year PFS 72% (induction) vs 64% (CRT alone), HR 0.65 (95% CI 0.46-0.91, p=0.013).
- 5-year OS 80% vs 72%, HR 0.60 (95% CI 0.40-0.91, p=0.015).
- Grade 3+ adverse events: 59% (induction) vs 48% (CRT alone).

**Dose constraints / prescription:**
- EQD2 78-86 Gy (BT)
- Cisplatin 40 mg/m2 weekly

**Trial endpoints / outcomes:**
- 5-year PFS
- 5-year OS
- Grade 3+ AEs

**Key numbers:**
- n=500
- 5y PFS 72% vs 64%
- 5y OS 80% vs 72%

**See also:**
- → [#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024](#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024) (`lancet-pembrolizumab-crt-cervical-2024.md`)
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)

---

<a id="kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024"></a>

#### Pembrolizumab or placebo with chemoradiotherapy followed by pembrolizumab or placebo for newly diagnosed, high-risk, locally advanced cervical cancer (ENGOT-cx11/GOG-3047/KEYNOTE-A18): overall survival results from a randomised, double-blind, placebo-controlled, phase 3 trial (2025)

📄 [lancet-pembrolizumab-crt-cervical-2024.md](sources/01_gynecologic/raw/lancet-pembrolizumab-crt-cervical-2024.md)

**Journal:** Lancet  
**DOI:** 10.1016/S0140-6736(24)01808-7  
**PMID:** 39288779 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/39288779/))  

**Topics:** `cervix`, `KEYNOTE-A18`, `pembrolizumab`, `immunotherapy`, `chemoradiotherapy`, `n=1060`, `36m-OS-82.6%-vs-74.8%`

**Key facts:**
- Phase 3 RCT; 1060 patients at 176 sites in 30 countries; 2020-2022.
- 5 cycles pembrolizumab 200 mg or placebo q3w with concurrent CRT, then 15 cycles pembrolizumab 400 mg or placebo q6w.
- Stratification: planned EBRT type (IMRT/VMAT vs other), FIGO 2014 stage (IB2-IIB N+ vs III-IVA), planned total RT (EBRT + BT) dose (<70 vs ≥70 Gy EQD2).
- Median follow-up 29.9 months.
- 36-month OS 82.6% (pembro+CRT) vs 74.8% (placebo+CRT); HR for death 0.67 (95% CI 0.50-0.90, p=0.0040).
- Grade 3+ AEs: 78% (pembro) vs 70% (placebo).

**Dose constraints / prescription:**
- Total RT (EBRT+BT) ≥ 70 Gy EQD2 (stratification threshold)

**Trial endpoints / outcomes:**
- OS
- PFS

**Key numbers:**
- n=1060
- 36m OS 82.6% vs 74.8%
- HR 0.67

**See also:**
- → [#kb:gyn:cervix:lancet-cervical-induction-chemo-2024](#kb:gyn:cervix:lancet-cervical-induction-chemo-2024) (`lancet-cervical-induction-chemo-2024.md`)
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)

---

<a id="kb:gyn:cervix:msk-bt-utilization-cervical-2025"></a>

#### Assessing predictors of brachytherapy utilization among cervical cancer patients in Nigeria (2025)

📄 [msk-bt-utilization-cervical-2025.md](sources/01_gynecologic/raw/msk-bt-utilization-cervical-2025.md)

**Journal:** MSK  
**DOI:** 10.1186/s12885-026-16311-9  
**PMID:** 42260414 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42260414/))  

**Topics:** `cervix`, `utilization`, `Nigeria`, `LMIC`, `50.43%-received-BT`

**Key facts:**
- Retrospective study of 343 cervical cancer patients (stage I-IVA) at Medserve-LUTH Cancer Centre, March 2021-June 2024.
- 173 (50.43%) received brachytherapy.
- Predictors of lower BT utilization: increasing age, religion (Muslim), treatment delay, advanced disease, abdominopelvic pain.
- Predictors of higher BT utilization: employed, premenopausal women.

**Trial endpoints / outcomes:**
- BT utilization rate

**Key numbers:**
- n=343
- 50.43% received BT

**See also:**
- → [#kb:frm:global_access:lancet-bt-global-demand-2025](#kb:frm:global_access:lancet-bt-global-demand-2025) (`lancet-bt-global-demand-2025.md`)
- → [#kb:frm:iaea_who:iaea-global-bt-initiative-2020](#kb:frm:iaea_who:iaea-global-bt-initiative-2020) (`iaea-global-bt-initiative-2020.md`)

---

<a id="kb:gyn:cervix:nccn-cervical-2024"></a>

#### NCCN Cervical Cancer Guideline (2024)

📄 [nccn-cervical-2024.md](sources/01_gynecologic/raw/nccn-cervical-2024.md)

**Journal:** NCCN Guidelines  

**Topics:** `cervix`, `NCCN`, `guideline`

**Key facts:**
- Covers patient selection criteria for BT, applicator types/techniques, dose prescriptions, fractionation schedules.
- Integration with EBRT; follow-up and surveillance recommendations.
- NCCN guidelines are updated annually.

**See also:**
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)
- → [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](#kb:gyn:cervix:abs-cervix-consensus-2012-part1) (`abs-cervix-consensus-2012-part1.md`)

---

### <a id="gyn-endometrial"></a> Endometrial Cancer BT (3 files)

<a id="kb:gyn:endometrial:ars-appropriate-use-criteria-2024"></a>

#### Executive Summary of the American Radium Society (ARS) Appropriate Use Criteria (AUC) for Management of Locally Advanced Endometrial Cancer (2025)

📄 [ars-appropriate-use-criteria-2024.md](sources/01_gynecologic/raw/ars-appropriate-use-criteria-2024.md)

**Journal:** American Radium Society  
**DOI:** 10.1016/j.prro.2025.12.014  
**PMID:** 41548804 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41548804/))  

**Topics:** `endometrial`, `ARS-AUC`, `advanced`, `PORTEC-3`, `p53abn`, `dMMR`, `IIIC2`

**Key facts:**
- Multidisciplinary ARS Gynecologic Cancer Panel created evidence-based guidelines for management of locally advanced endometrial adenocarcinoma.
- Optimal adjuvant treatment is based on pathologic and molecular risk factors, typically combined modality therapy with chemotherapy and radiation.
- PORTEC-3 data: adding chemotherapy to radiation is especially crucial for p53 abnormal tumors.
- NRG-GY018/RUBY trial inclusion criteria guide appropriateness of incorporating immunotherapy, especially in dMMR patients.
- Radiation fields should be extended to include para-aortic lymph nodes in IIIC2 disease.
- Within pelvic radiation, IMRT is the preferred technique to mitigate toxicity per prospective data.

**Key numbers:**
- FIGO IIIC2

**See also:**
- → [#kb:gyn:endometrial:portec-2-lancet-2010](#kb:gyn:endometrial:portec-2-lancet-2010) (`portec-2-lancet-2010.md`)
- → [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](#kb:gyn:endometrial:lancet-molecular-endometrial-2024) (`lancet-molecular-endometrial-2024.md`)

---

<a id="kb:gyn:endometrial:lancet-molecular-endometrial-2024"></a>

#### PORTEC-4a: molecular profile-based adjuvant treatment for high-intermediate risk endometrial cancer (phase 3) (2025)

📄 [lancet-molecular-endometrial-2024.md](sources/01_gynecologic/raw/lancet-molecular-endometrial-2024.md)

**Journal:** Lancet  
**DOI:** 10.1016/S1470-2045(25)00612-6  
**PMID:** 41449145 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41449145/))  

**Topics:** `endometrial`, `PORTEC-4a`, `molecular-profile`, `POLE-mut`, `NSMP-CTNNB1`, `dMMR`, `p53abn`, `vaginal-BT-21-Gy-3fx`

**Key facts:**
- Randomised open-label phase 3 across 8 European countries; 2:1 molecular vs standard vaginal brachytherapy.
- 569 patients enrolled; 564 eligible (367 molecular, 197 standard). Median age 69.0 years.
- Molecular-profile group: favourable (POLE-mut, NSMP-CTNNB1 wildtype) = observation; intermediate (dMMR or NSMP-CTNNB1 mut) = brachytherapy 21 Gy in 3 fx of 7 Gy; unfavourable (p53abn, LVI, L1CAM) = pelvic RT 45-48.6 Gy in 1.8-2.0 Gy fx.
- Median follow-up 58.1 months.
- 5-year vaginal recurrence: 4.5% (molecular) vs 1.6% (standard); HR 2.71 (95% CI 0.79-9.34); non-inferiority p=0.005.
- Spares 46% of favourable-profile patients from adjuvant treatment.

**Dose constraints / prescription:**
- Vaginal BT 21 Gy / 3 fx of 7 Gy
- Pelvic RT 45-48.6 Gy / 1.8-2.0 Gy fx

**Trial endpoints / outcomes:**
- 5-year vaginal recurrence

**Key numbers:**
- n=564
- 5y VR 4.5% vs 1.6%
- 46% spared adjuvant tx

**See also:**
- → [#kb:gyn:endometrial:portec-2-lancet-2010](#kb:gyn:endometrial:portec-2-lancet-2010) (`portec-2-lancet-2010.md`)
- → [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](#kb:gyn:endometrial:ars-appropriate-use-criteria-2024) (`ars-appropriate-use-criteria-2024.md`)

---

<a id="kb:gyn:endometrial:portec-2-lancet-2010"></a>

#### Endometrial Adjuvant — PORTEC-2 (VBT vs EBRT)

📄 [portec-2-lancet-2010.md](sources/01_gynecologic/raw/portec-2-lancet-2010.md)


**Topics:** `endometrial`, `PORTEC-2`, `vaginal-BT-vs-EBRT`, `VBT-21-Gy-3fx`, `EBRT-46-Gy`, `n=427`, `5y-VR-1.8%-vs-1.6%`

**See also:**
- → [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](#kb:gyn:endometrial:lancet-molecular-endometrial-2024) (`lancet-molecular-endometrial-2024.md`)
- → [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](#kb:gyn:endometrial:ars-appropriate-use-criteria-2024) (`ars-appropriate-use-criteria-2024.md`)

---

### <a id="gyn-vaginal_vulvar"></a> Vaginal & Vulvar Cancer BT (2 files)

<a id="kb:gyn:vaginal_vulvar:abs-vulvar-2019"></a>

#### Identification and Management of Late Toxicities After Radiation Therapy for Vulvar Cancer (2019)

📄 [abs-vulvar-2019.md](sources/01_gynecologic/raw/abs-vulvar-2019.md)

**Journal:** Brachytherapy  
**DOI:** 10.1016/j.brachy.2019.03.004  
**PMID:** 40562189 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/40562189/))  

**Topics:** `vulvar`, `late-toxicity`, `ABS`, `PIF`, `lymphedema`

**Key facts:**
- Vulvar cancer: estimated 6,900 cases in 2024, incidence rising.
- Radiation plays critical role in definitive and adjuvant management.
- Late toxicities: pelvic insufficiency fractures, anal/fecal incontinence, sexual dysfunction, cutaneous and subcutaneous fibrosis, lymphedema.
- Article provides practical guidance regarding work-up and evidence-based management of these toxicities.

**Key numbers:**
- 6,900 cases in 2024 (US)

**See also:**
- → [#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024](#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024) (`gec-estro-endometrial-2024.md`)
- → [#kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024](#kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024) (`rtog-cisplatin-gem-imrt-2024.md`)

---

<a id="kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024"></a>

#### GEC-ESTRO (ACROP)-ABS-CBG Consensus Brachytherapy Target Definition Guidelines for Recurrent Endometrial and Cervical Tumors in the Vagina (2022)

📄 [gec-estro-endometrial-2024.md](sources/01_gynecologic/raw/gec-estro-endometrial-2024.md)

**Journal:** Radiotherapy and Oncology  
**PMID:** 36191741 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/36191741/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/36191741/  

**Topics:** `vaginal-recurrence`, `endometrial-recurrence`, `cervical-recurrence`, `GEC-ESTRO-ACROP-ABS-CBG`, `consensus`

**Key facts:**
- 17 radiation oncologists and 2 medical physicists from GYN GEC-ESTRO, ABS, and Canadian Brachytherapy Group.
- Consensus definitions for GTV-Tres, CTV-THR, CTV-TIR for MRI-based adaptive BT in vaginal recurrences of endometrial or cervical cancer.
- Trial 1/Trial 2 Kappa: GTV-Tres 0.536/0.583, CTV-THR 0.575/0.743, CTV-TIR 0.522/0.707.
- Trial 2 CTV-THR and CTV-TIR showed 'substantial' agreement; GTV-Tres remained at moderate agreement.

**Key numbers:**
- Kappa CTV-THR Trial 2: 0.743
- n=19 (17 RO + 2 MP)

**See also:**
- → [#kb:gyn:vaginal_vulvar:abs-vulvar-2019](#kb:gyn:vaginal_vulvar:abs-vulvar-2019) (`abs-vulvar-2019.md`)
- → [#kb:gyn:cervix:gec-estro-cervix-2005-haie](#kb:gyn:cervix:gec-estro-cervix-2005-haie) (`gec-estro-cervix-2005-haie-meder.md`)

---

## <a id="pros"></a> Prostate & Genitourinary BT (14 files)

**Subtitle:** prostate, penile, salvage, urethra-sparing  
**Master list:** [`sources/02_prostate_gu/INDEX.md`](sources/02_prostate_gu/INDEX.md)

### <a id="pros-ldr"></a> LDR Permanent Seed BT (3 files)

<a id="kb:pros:ldr:abs-aua-astro-ldr-2012"></a>

#### American Brachytherapy Society consensus guidelines for transrectal ultrasound-guided permanent prostate brachytherapy (2012)

📄 [abs-aua-astro-ldr-2012.md](sources/02_prostate_gu/raw/abs-aua-astro-ldr-2012.md)

**Journal:** Brachytherapy  
**DOI:** 10.1016/j.brachy.2011.07.005  
**PMID:** 22265434 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/22265434/))  

**Topics:** `prostate`, `LDR`, `ABS-AUA-ASTRO`, `permanent-seed`, `TRUS`, `low-risk`, `high-risk`

**Key facts:**
- Patients with high probability of organ-confined disease or limited extraprostatic extension are appropriate candidates for permanent prostate brachytherapy (PPB) monotherapy.
- Low-risk patients may be treated with PPB alone without the need for supplemental external beam radiotherapy.
- High-risk patients should receive supplemental external beam radiotherapy if PPB is used.
- Intermediate-risk patients with favorable features may be treated with PPB monotherapy but results from confirmatory clinical trials are pending.
- CT-based postimplant dosimetry performed within 60 days of the implant is considered essential for maintenance of a satisfactory quality assurance program.

**Key numbers:**
- PMID 22265434
- DOI 10.1016/j.brachy.2011.07.005
- Postimplant dosimetry within 60 days

**See also:**
- → [#kb:pros:guidelines:aapm-tg-137-nath-2009](#kb:pros:guidelines:aapm-tg-137-nath-2009) (`aapm-tg-137-nath-2009.md`)
- → [#kb:pros:ldr:ascende-rt-morris-2017](#kb:pros:ldr:ascende-rt-morris-2017) (`ascende-rt-morris-2017.md`)
- → [#kb:pros:ldr:salvage-prostate-bt](#kb:pros:ldr:salvage-prostate-bt) (`salvage-prostate-bt.md`)

---

<a id="kb:pros:ldr:ascende-rt-morris-2017"></a>

#### External Beam Radiation Therapy or Brachytherapy With or Without Short-course Neoadjuvant Androgen Deprivation Therapy: Results of a Multicenter, Prospective Study of Quality of Life (2017)

📄 [ascende-rt-morris-2017.md](sources/02_prostate_gu/raw/ascende-rt-morris-2017.md)

**Journal:** IJROBP  
**DOI:** 10.1016/j.ijrobp.2017.02.019  
**PMID:** 28463150 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/28463150/))  

**Topics:** `prostate`, `ASCENDE-RT`, `LDR-boost`, `HRQOL`, `NADT`, `n=NC`

**Key facts:**
- HRQOL was measured using the expanded prostate cancer index composite 26-item questionnaire at 2, 6, 12, and 24 months after initiation of NADT.
- For EBRT recipients, ability to have an erection, ability to reach orgasm, quality of erections, frequency of erections, ability to function sexually, and lack of energy were in a significantly worse dichotomized category for patients receiving NADT.
- Comparing baseline versus 24-month outcomes, 24%, 23%, and 30% of EBRT plus NADT participants shifted to worse category for ability to reach orgasm, quality of erections, and ability to function sexually versus 14%, 13%, and 16% in EBRT group.
- No difference was found in the ability to have an erection, frequency of erections, overall sexual function, hot flashes, breast tenderness/enlargement, depression, lack of energy, or change in body weight.
- The improved survival in intermediate- and high-risk patients receiving NADT and EBRT necessitates pretreatment counseling of the HRQOL effect of NADT and EBRT.

**Trial endpoints / outcomes:**
- Health-related quality of life (HRQOL) endpoints at 2, 6, 12, and 24 months
- Sexual function domains (ability to reach orgasm, quality of erections, ability to function sexually)

**Key numbers:**
- PMID 28463150
- DOI 10.1016/j.ijrobp.2017.02.019
- Analyses conducted at the 2-sided 5% significance level
- Follow-up at 24 months

**See also:**
- → [#kb:pros:ldr:abs-aua-astro-ldr-2012](#kb:pros:ldr:abs-aua-astro-ldr-2012) (`abs-aua-astro-ldr-2012.md`)
- → [#kb:pros:ldr:salvage-prostate-bt](#kb:pros:ldr:salvage-prostate-bt) (`salvage-prostate-bt.md`)
- → [#kb:pros:hdr:jama-sbrt-vs-hdr-bt](#kb:pros:hdr:jama-sbrt-vs-hdr-bt) (`jama-sbrt-vs-hdr-bt-prostate-2025.md`)

---

<a id="kb:pros:ldr:salvage-prostate-bt"></a>

#### Permanent seed brachytherapy for prostate cancer: Monotherapy, combined, and salvage approaches remain effective and well-tolerated options (2018)

📄 [salvage-prostate-bt.md](sources/02_prostate_gu/raw/salvage-prostate-bt.md)

**Journal:** Brachytherapy  
**PMID:** 42232845 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42232845/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/42232845/  

**Topics:** `prostate`, `permanent-seed`, `I-125`, `monotherapy`, `combined-EBRT`, `salvage`, `n=805`

**Key facts:**
- Between 2008 and 2023, a retrospective cohort of 805 patients with prostate cancer underwent permanent iodine-125 seed implant brachytherapy.
- Risk distribution: 394 (48.9%) low risk, 303 (37.6%) intermediate risk, 108 (13.4%) high risk, per D'Amico classification.
- Low-risk patients were treated with brachytherapy alone, whereas intermediate- and high-risk patients received combined brachytherapy with EBRT (50 Gy).
- ADT was administered for 6 months in intermediate-risk patients and for 18-36 months in high-risk patients.
- The prescribed brachytherapy dose was 145 Gy for monotherapy and 110 Gy for brachytherapy combined with EBRT.
- Biochemical relapse-free survival (bRFS) rates: 95.3% low-risk, 96.0% intermediate-risk, 94.3% high-risk.
- Eight patients with local recurrence after prior radiotherapy underwent salvage brachytherapy; seven remained disease-free at last follow-up.
- Late grade ≥ 2 genitourinary or gastrointestinal toxicity occurred in 0.9% of patients treated with brachytherapy alone and in 4.0% of those receiving combined therapy. No grade 4 or 5 toxicities were observed.

**Dose constraints / prescription:**
- 145 Gy for monotherapy (brachytherapy)
- 110 Gy for brachytherapy combined with EBRT
- 50 Gy EBRT in combined treatment

**Trial endpoints / outcomes:**
- Biochemical relapse-free survival (bRFS) per Phoenix criteria
- Late grade ≥ 2 GU/GI toxicity

**Key numbers:**
- PMID 42232845
- n=805 patients (2008-2023)
- Low-risk 48.9% (n=394), intermediate 37.6% (n=303), high 13.4% (n=108)
- bRFS: 95.3% low, 96.0% intermediate, 94.3% high
- Late grade ≥2 toxicity: 0.9% (BT alone) vs 4.0% (combined)
- ADT duration: 6 months (intermediate) or 18-36 months (high)
- 8 salvage brachytherapy patients, 7 disease-free

**See also:**
- → [#kb:pros:ldr:abs-aua-astro-ldr-2012](#kb:pros:ldr:abs-aua-astro-ldr-2012) (`abs-aua-astro-ldr-2012.md`)
- → [#kb:pros:salvage:eortc-salvage-hdr-bt-2024](#kb:pros:salvage:eortc-salvage-hdr-bt-2024) (`eortc-salvage-hdr-bt-2024.md`)
- → [#kb:pros:ldr:ascende-rt-morris-2017](#kb:pros:ldr:ascende-rt-morris-2017) (`ascende-rt-morris-2017.md`)

---

### <a id="pros-hdr"></a> HDR Brachytherapy (4 files)

<a id="kb:pros:hdr:abs-2022-prostate-hdr"></a>

#### Core competencies in prostate HDR brachytherapy: An American Brachytherapy Society Endorsed Competency Framework (2022)

📄 [abs-2022-prostate-hdr.md](sources/02_prostate_gu/raw/abs-2022-prostate-hdr.md)

**Journal:** Brachytherapy  
**DOI:** 10.1016/j.brachy.2021.09.013  
**PMID:** 42156316 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42156316/))  

**Topics:** `prostate`, `HDR`, `ABS`, `competency`, `monotherapy`, `boost`, `radio-recurrent`

**Key facts:**
- HDR brachytherapy is used as monotherapy for low- and favorable intermediate-risk patients and as a boost for higher-risk disease, and remains a key option for radio-recurrent localized prostate cancer.
- HDR offers advantages including real-time image guidance for catheter placement, dynamic treatment plan optimization, precise dose customization, and lower radiation exposure for staff.
- The objective of the manuscript is to summarize current prostate HDR guidelines from ABS and GEC-ESTRO and to establish a structured competency framework for training programs.
- Few institutions offer formal brachytherapy training or fellowships, and there is limited guidance outlining the specific competencies required for HDR prostate brachytherapy.

**Key numbers:**
- PMID 42156316
- DOI 10.1016/j.brachy.2021.09.013

**See also:**
- → [#kb:pros:hdr:jama-sbrt-vs-hdr-bt](#kb:pros:hdr:jama-sbrt-vs-hdr-bt) (`jama-sbrt-vs-hdr-bt-prostate-2025.md`)
- → [#kb:pros:hdr:focal-prostate-hdr](#kb:pros:hdr:focal-prostate-hdr) (`focal-prostate-hdr.md`)
- → [#kb:pros:microboost_focal:urethra-sparing-nvb](#kb:pros:microboost_focal:urethra-sparing-nvb) (`urethra-sparing-nvb.md`)

---

<a id="kb:pros:hdr:focal-prostate-hdr"></a>

#### From whole gland to hemigland to ultra-focal high-dose-rate prostate brachytherapy: A dosimetric analysis (2022)

📄 [focal-prostate-hdr.md](sources/02_prostate_gu/raw/focal-prostate-hdr.md)

**Journal:** Brachytherapy  
**PMID:** 25680768 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/25680768/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/25680768/  

**Topics:** `prostate`, `focal-HDR`, `ultra-focal`, `hemigland`, `dosimetric-comparison`, `n=5`

**Key facts:**
- HDR plans for five patients treated with whole gland (WG) HDR monotherapy were optimized to assess hemigland (HG), one-third gland (1/3G), and one-sixth gland (1/6G) treatment strategies.
- Target objectives (D90 > 100% and V100 > 97%) were met in all cases.
- 1/6G vs WG plans resulted in the greatest reduction in dose with a mean bladder D2cc 24.7 vs 64.8%, rectal D2cc 32.8 vs 65.3%, urethral D1cc 52.1 vs 103.8%, and V75 14.5 vs 75% (p < 0.05 for all comparisons).
- Significant dose reductions to organs at risk can be achieved using HDR focal brachytherapy, but clinical impact on morbidity and tumor control remains to be investigated.

**Dose constraints / prescription:**
- D90 > 100% (target)
- V100 > 97% (target)
- Bladder D2cc: 24.7% (1/6G) vs 64.8% (WG)
- Rectal D2cc: 32.8% (1/6G) vs 65.3% (WG)
- Urethral D1cc: 52.1% (1/6G) vs 103.8% (WG)
- Urethral V75: 14.5% (1/6G) vs 75% (WG)

**Key numbers:**
- PMID 25680768
- n=5 patients analyzed
- Dosimetric comparison study (no clinical follow-up)

**See also:**
- → [#kb:pros:hdr:abs-2022-prostate-hdr](#kb:pros:hdr:abs-2022-prostate-hdr) (`abs-2022-prostate-hdr.md`)
- → [#kb:pros:microboost_focal:urethra-sparing-nvb](#kb:pros:microboost_focal:urethra-sparing-nvb) (`urethra-sparing-nvb.md`)
- → [#kb:pros:microboost_focal:nrg-microboost-prostate-2024](#kb:pros:microboost_focal:nrg-microboost-prostate-2024) (`nrg-microboost-prostate-2024.md`)

---

<a id="kb:pros:hdr:jama-sbrt-vs-hdr-bt"></a>

#### SBRT vs HDR Brachytherapy for Intermediate-Risk Prostate Cancer (2025)

📄 [jama-sbrt-vs-hdr-bt-prostate-2025.md](sources/02_prostate_gu/raw/jama-sbrt-vs-hdr-bt-prostate-2025.md)

**Journal:** JAMA  
**DOI:** 10.1001/jamanetworkopen.2026.0146  
**PMID:** 41739470 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41739470/))  

**Topics:** `prostate`, `SBRT-vs-HDR`, `intermediate-risk`, `5y-BCF-7.8%-vs-3.0%`, `10y-BCF-38.0%-vs-10.4%`, `n=247`

**Key facts:**
- Individual patient data post hoc pooled analysis of 5 prospective trials with recruitment from 2010 to 2018, statistical analyses performed in September 2024.
- Eligibility comprised men with intermediate-risk prostate cancer undergoing 5- or 2-fraction SBRT or 2-fraction HDR-BT; no androgen deprivation therapy was permitted.
- After median (IQR) follow-up of 9.5 (5.5-10.6) years, 247 men met eligibility criteria: 180 SBRT (72.8%; mean age 69.5 years) and 67 HDR-BT (27.1%; mean age 66.0 years).
- At 5 years, BCF was 7.8% (95% CI, 1.0%-14.6%) for HDR vs 3.0% (95% CI, 0.4%-5.6%) for SBRT.
- At 10 years, BCF was 38.0% (95% CI, 19.8%-56.1%) for HDR vs 10.4% (95% CI, 4.3%-16.6%) for SBRT (P < .001).
- HDR-BT cohort had significantly higher incidence of acute grade ≥ 2 genitourinary AEs vs SBRT (74.6% vs 51.7%; P = .007).
- There were no significant differences in any other acute or late AEs or late PR-QoL.

**Trial endpoints / outcomes:**
- Biochemical failure (BCF) at 5 and 10 years
- Patient-reported quality of life (PR-QoL)
- Acute and late adverse events (AEs)

**Key numbers:**
- PMID 41739470
- DOI 10.1001/jamanetworkopen.2026.0146
- n=247 men (180 SBRT, 67 HDR-BT)
- Median follow-up 9.5 years (IQR 5.5-10.6)
- 5-year BCF: 7.8% HDR vs 3.0% SBRT
- 10-year BCF: 38.0% HDR vs 10.4% SBRT (P<.001)
- Acute grade ≥2 GU AEs: 74.6% HDR vs 51.7% SBRT (P=.007)
- 5 prospective trials pooled

**See also:**
- → [#kb:pros:hdr:abs-2022-prostate-hdr](#kb:pros:hdr:abs-2022-prostate-hdr) (`abs-2022-prostate-hdr.md`)
- → [#kb:pros:ldr:abs-aua-astro-ldr-2012](#kb:pros:ldr:abs-aua-astro-ldr-2012) (`abs-aua-astro-ldr-2012.md`)
- → [#kb:pros:ldr:ascende-rt-morris-2017](#kb:pros:ldr:ascende-rt-morris-2017) (`ascende-rt-morris-2017.md`)

---

<a id="kb:pros:hdr:real-time-trus-planning"></a>

#### Towards U-Net-based intraoperative 2D dose prediction in high dose rate prostate brachytherapy (2020)

📄 [real-time-trus-planning.md](sources/02_prostate_gu/raw/real-time-trus-planning.md)

**Journal:** Various  
**PMID:** 39668102 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/39668102/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/39668102/  

**Topics:** `prostate`, `U-Net`, `deep-learning`, `real-time-dose-prediction`, `n=248`

**Key facts:**
- Clinical treatment plans from 248 prostate HDR-BT patients were retrospectively collected and randomly split 80/20 for training/testing.
- Fifteen U-Net models were implemented to predict the 90%, 100%, 120%, 150%, and 200% isodose levels in the prostate base, midgland, and apex.
- Models predicting 90% and 100% isodose lines at midgland performed best, with median DSC of 0.97 and 0.96, respectively.
- Performance declined as isodose level increased, with median DSC of 0.90, 0.79, and 0.65 in the 120%, 150%, and 200% models.
- In the base, median DSC was 0.94 for 90% and decreased to 0.64 for 200%. In the apex, median DSC was 0.93 for 90% and decreased to 0.63 for 200%.
- Median prediction time was 25 ms, sufficient for real-time use.

**Dose constraints / prescription:**
- Isodose levels predicted: 90%, 100%, 120%, 150%, 200%

**Trial endpoints / outcomes:**
- Dice similarity coefficient (DSC) for isodose prediction accuracy

**Key numbers:**
- PMID 39668102
- n=248 prostate HDR-BT patients
- 15 U-Net models implemented
- 80/20 train/test split
- Median prediction time 25 ms
- DSC 0.97 (90% midgland), 0.96 (100% midgland)

**See also:**
- → [#kb:pros:hdr:abs-2022-prostate-hdr](#kb:pros:hdr:abs-2022-prostate-hdr) (`abs-2022-prostate-hdr.md`)
- → [#kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt](#kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt) (`deep-reinforcement-learning-hdr-bt-cervical.md`)

---

### <a id="pros-microboost_focal"></a> Microboost & Focal Sparing (2 files)

<a id="kb:pros:microboost_focal:nrg-microboost-prostate-2024"></a>

#### Microboost in Localized Prostate Cancer: Analysis of a Statewide Quality Consortium (2025)

📄 [nrg-microboost-prostate-2024.md](sources/02_prostate_gu/raw/nrg-microboost-prostate-2024.md)

**Journal:** NRG Oncology  
**DOI:** 10.1016/j.adro.2024.101629  
**PMID:** 39610797 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/39610797/))  

**Topics:** `prostate`, `microboost`, `NRG`, `statewide-consortium`, `D98-94.4-EQD2Gy`, `n=741`

**Key facts:**
- Men with intermediate- and high-risk prostate adenocarcinoma treated with curative-intent radiation between October 26, 2020, and June 26, 2023, were included across 26 centers.
- Most patients received EBRT without brachytherapy (71%, n=524/741). Of those, a minority received an EBRT microboost (10%, n=53/524) at a subset of sites (27%, n=7/26), without a change in rate over the study period (P = .62).
- Grade group 4/5 (OR=2.35; 95% CI: 1.02-5.28), MRI planning (OR=6.34; 95%CI: 2.16-27.12), and fiducial marker/rectal spacer placement (OR=2.59; 95% CI: 1.14-6.70) were associated with microboost use.
- Significant facility-level variability was present (minimum 0% to maximum 71%, unadjusted, P < .0001).
- Median boost volume was 20.7cc, and median boost D98% was 94.4 EQD2Gy.
- Compared with non-microboost cases, intermediate doses to rectum in the microboost cohort were increased (eg, V20Gy [EQD2] of 53.8% vs 36.5%, P = .03).
- The proportion exceeding NRG/RTOG bladder/rectal constraints was low and not significantly different between cohorts.

**Dose constraints / prescription:**
- Median boost D98% of 94.4 EQD2Gy
- NRG/RTOG bladder/rectal constraints referenced
- Rectal V20Gy [EQD2] of 53.8% (microboost) vs 36.5% (non-microboost), P=.03

**Trial endpoints / outcomes:**
- Microboost utilization rates
- Facility-level variability

**Key numbers:**
- PMID 39610797
- DOI 10.1016/j.adro.2024.101629
- n=741 patients across 26 centers
- 71% received EBRT without brachytherapy (n=524)
- 10% received EBRT microboost (n=53/524)
- 27% of sites used microboost (n=7/26)
- Median boost volume 20.7cc
- Treatment period October 2020 to June 2023

**See also:**
- → [#kb:pros:hdr:focal-prostate-hdr](#kb:pros:hdr:focal-prostate-hdr) (`focal-prostate-hdr.md`)
- → [#kb:pros:microboost_focal:urethra-sparing-nvb](#kb:pros:microboost_focal:urethra-sparing-nvb) (`urethra-sparing-nvb.md`)
- → [#kb:pros:hdr:abs-2022-prostate-hdr](#kb:pros:hdr:abs-2022-prostate-hdr) (`abs-2022-prostate-hdr.md`)

---

<a id="kb:pros:microboost_focal:urethra-sparing-nvb"></a>

#### Novel low dose rate brachytherapy with focal sparing of neurovascular bundle: Report on the primary outcome from the PRIAPUS trial (2021)

📄 [urethra-sparing-nvb.md](sources/02_prostate_gu/raw/urethra-sparing-nvb.md)

**Journal:** Semin Radiat Oncol  
**PMID:** 40975655 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/40975655/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/40975655/  

**Topics:** `prostate`, `LDR`, `neurovascular-bundle-sparing`, `PRIAPUS-trial`, `NCT04718987`, `n=14`

**Key facts:**
- PRIAPUS (NCT04718987) is a prospective, single-arm clinical trial evaluating feasibility of a novel LDR BT technique designed to spare the prostatic neurovascular bundles (NVB) contralateral to the index lesion.
- Intermediate-risk prostate cancer patients with clinically significant disease contained to one lobe of the prostate were enrolled.
- Primary objective was for 70% of patients to achieve acceptable dose to CTV while sufficiently sparing ED-related structures.
- Dosimetry was evaluated on a 1-month postimplant CT-scan.
- Fifteen patients have been consented with 14 patients treated on trial.
- In the 1-month postprocedure scan, the mean CTV D90% was 152 Gy (SD ± 10.7 Gy); all patients but two had a CTV D90% >140 Gy.
- The mean contralateral NVB D50% was 60.8 Gy (SD ± 12.1 Gy), with 11 of 14 implants failing to meet the prespecified goal.
- The ipsilateral NVB which was not spared received a mean D50% of 128 Gy (SD ± 32 Gy). The mean penile bulb D10% was 31 Gy (SD ± 13 Gy).
- Only 2 patients had a postimplant dosimetry that met all prespecified criteria.
- The novel LDR BT technique is capable of drastically reducing dose to the cNVB, although this reduction did not meet the stringent dose constraints specified in this trial.

**Dose constraints / prescription:**
- CTV D90% mean 152 Gy (SD ± 10.7 Gy)
- CTV D90% >140 Gy target (all but 2 met)
- Urethra D30% mean 129% (SD ± 9%)
- Contralateral NVB D50% mean 60.8 Gy (SD ± 12.1 Gy)
- Ipsilateral NVB D50% mean 128 Gy (SD ± 32 Gy)
- Penile bulb D10% mean 31 Gy (SD ± 13 Gy)

**Trial endpoints / outcomes:**
- Primary objective: 70% of patients achieve acceptable CTV dose with ED-structure sparing
- Postimplant dosimetry success rate: 2/14 patients met all prespecified criteria

**Key numbers:**
- PMID 40975655
- 15 patients consented, 14 treated
- NCT04718987
- 1-month postimplant dosimetry evaluation

**See also:**
- → [#kb:pros:hdr:focal-prostate-hdr](#kb:pros:hdr:focal-prostate-hdr) (`focal-prostate-hdr.md`)
- → [#kb:pros:hdr:abs-2022-prostate-hdr](#kb:pros:hdr:abs-2022-prostate-hdr) (`abs-2022-prostate-hdr.md`)
- → [#kb:pros:ldr:salvage-prostate-bt](#kb:pros:ldr:salvage-prostate-bt) (`salvage-prostate-bt.md`)

---

### <a id="pros-salvage"></a> Salvage BT (1 files)

<a id="kb:pros:salvage:eortc-salvage-hdr-bt-2024"></a>

#### Phase II study of salvage HDR brachytherapy combined with external beam radiotherapy for isolated prostate bed relapse after radical prostatectomy: preliminary clinical results (2025)

📄 [eortc-salvage-hdr-bt-2024.md](sources/02_prostate_gu/raw/eortc-salvage-hdr-bt-2024.md)

**Journal:** EORTC  
**DOI:** 10.1016/j.radonc.2025.111215  
**PMID:** 41110803 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41110803/))  

**Topics:** `prostate`, `salvage`, `HDR`, `EORTC`, `phase-II`, `prostate-bed`, `n=16`, `19-Gy-2fx`

**Key facts:**
- Prospective phase I-II study (NCT06982469) of combined salvage HDR brachytherapy followed by EBRT for patients with isolated prostate bed relapse (IPBR).
- HDR was delivered as 19 Gy in two fractions prescribed to the clinical target volume (CTV) with strict OAR constraints, followed by EBRT to the whole prostate bed and elective pelvic lymph nodes combined with 6-month ADT.
- Sixteen patients were enrolled between 2020 and 2024 with median PSA at salvage of 0.36 ng/mL.
- At a median follow-up of 3.7 years (range, 2.3 - 5.2), 15 out of 16 patients (93.8%) remained biochemically controlled, with no local failures.
- Grade 2 late urinary toxicity was documented in one case and no grade 3 late toxicities occurred.
- Patient-reported urinary and bowel domains showed only minor, non-significant changes at 6 months from baseline.
- The trial was closed without completing the target size due to slow accrual.

**Dose constraints / prescription:**
- 19 Gy in two fractions prescribed to CTV with strict OAR constraints
- Whole prostate bed EBRT (specific dose not stated in abstract)

**Trial endpoints / outcomes:**
- Biochemical control (93.8% at 3.7 years median follow-up)
- Local failure rate (none observed)
- Late urinary toxicity (CTCAE v5.0)
- Quality of life (EORTC QLQ-PR25)

**Key numbers:**
- PMID 41110803
- DOI 10.1016/j.radonc.2025.111215
- n=16 patients
- 19 Gy in 2 fractions HDR boost
- Median PSA at salvage 0.36 ng/mL
- Median follow-up 3.7 years (range 2.3-5.2)
- 15/16 (93.8%) biochemically controlled
- 6-month ADT duration
- Enrolled 2020-2024

**See also:**
- → [#kb:pros:ldr:salvage-prostate-bt](#kb:pros:ldr:salvage-prostate-bt) (`salvage-prostate-bt.md`)
- → [#kb:pros:hdr:abs-2022-prostate-hdr](#kb:pros:hdr:abs-2022-prostate-hdr) (`abs-2022-prostate-hdr.md`)

---

### <a id="pros-penile"></a> Penile BT (2 files)

<a id="kb:pros:penile:gec-estro-penile-2018"></a>

#### Transition from pulsed dose rate to high dose rate brachytherapy: Experience of a single centre (2018)

📄 [gec-estro-penile-2018.md](sources/02_prostate_gu/raw/gec-estro-penile-2018.md)

**Journal:** European Urology  
**DOI:** 10.1016/j.eururo.2017.09.013  
**PMID:** 40544065 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/40544065/))  

**Topics:** `penile`, `GEC-ESTRO`, `PDR-to-HDR-transition`, `single-centre`

**Key facts:**
- In February 2021, the Brachytherapy department of the Lorraine Cancer Institute began a transition away from pulsed dose rate (PDR) towards high dose rate (HDR) brachytherapy for gynaecological cancer, cancers of the oral cavity, oropharynx and anal canal, penile cancer and sarcoma.
- The 7 brachytherapists of the unit performed a literature search then validated, in a group meeting, different fractionation regimens following GEC-ESTRO recommendations.
- Fractionation regimens were chosen to avoid patients having the brachytherapy device in place over the weekend.
- Discontinuation of PDR made it possible to reduce the number of radiation sources present in the department, with reduction of working time for source changes and quality control.
- Work organization changed markedly, requiring presence of at least 2 radiation therapists on treatment days.
- To date (at time of writing), no unexpected toxicity has been observed.

**Trial endpoints / outcomes:**
- Toxicity observation (no unexpected toxicity)

**Key numbers:**
- PMID 40544065
- DOI 10.1016/j.eururo.2017.09.013
- 7 brachytherapists in the unit
- At least 2 radiation therapists required on treatment days
- Transition began February 2021

**See also:**
- → [#kb:pros:penile:nature-bt-penile-organ-preservation](#kb:pros:penile:nature-bt-penile-organ-preservation) (`nature-bt-penile-organ-preservation-2015.md`)
- → [#kb:oth:brain_spine:gammatile-brain](#kb:oth:brain_spine:gammatile-brain) (`gammatile-brain.md`)

---

<a id="kb:pros:penile:nature-bt-penile-organ-preservation"></a>

#### The role of brachytherapy in organ preservation for penile cancer: A meta-analysis and review of the literature (2025)

📄 [nature-bt-penile-organ-preservation-2015.md](sources/02_prostate_gu/raw/nature-bt-penile-organ-preservation-2015.md)

**Journal:** Nature  
**DOI:** 10.1016/j.brachy.2015.03.008  
**PMID:** 25944394 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/25944394/))  

**Topics:** `penile`, `organ-preservation`, `meta-analysis`, `penectomy-vs-BT`, `5y-OS-76%-vs-73%`, `n=2178`

**Key facts:**
- Meta-analysis comparing overall survival (OS) and local control (LC) rates between penectomy and brachytherapy for penile cancer.
- Nineteen retrospective studies published between 1984-2012 detailing OS and LC were included.
- A total of 2178 males, median age 61 years, were included with 1505 in the surgery group and 673 in the brachytherapy group.
- The 5-year OS with surgery was 76% compared with 73% with brachytherapy, odds ratio = 1.17 (0.95-1.44, p = 0.128).
- Penectomy was associated with a higher 5-year LC rate of 84% compared with 79% with brachytherapy, odds ratio = 1.45 (1.09-1.92, p = 0.009).
- The organ preservation rate for brachytherapy treatment was 74%.
- Among the surgery patients in a Stage I/II subset, the 5-year OS and LC was 80% (n = 659) and 86% (n = 390), respectively.
- Of the 209 early stage patients who received brachytherapy, the 5-year OS was 79% and LC was 84%.
- Chi-square testing demonstrated no difference for either OS or LC for early stage disease.

**Trial endpoints / outcomes:**
- 5-year overall survival (OS): 76% surgery vs 73% brachytherapy (OR 1.17, p=0.128)
- 5-year local control (LC): 84% surgery vs 79% brachytherapy (OR 1.45, p=0.009)
- 5-year OS in Stage I/II: 80% surgery vs 79% brachytherapy
- 5-year LC in Stage I/II: 86% surgery vs 84% brachytherapy
- Organ preservation rate: 74% for brachytherapy

**Key numbers:**
- PMID 25944394
- DOI 10.1016/j.brachy.2015.03.008
- n=2178 males total
- 1505 surgery, 673 brachytherapy
- Median age 61 years
- 19 retrospective studies (1984-2012)

**See also:**
- → [#kb:pros:penile:gec-estro-penile-2018](#kb:pros:penile:gec-estro-penile-2018) (`gec-estro-penile-2018.md`)
- → [#kb:oth:sarcoma:abs-sarcoma-bt](#kb:oth:sarcoma:abs-sarcoma-bt) (`abs-sarcoma-bt.md`)

---

### <a id="pros-guidelines"></a> Guidelines / Methodology (2 files)

<a id="kb:pros:guidelines:aapm-tg-137-nath-2009"></a>

#### 02_prostate_gu — Prostate & Genitourinary Brachytherapy (14 files)

📄 [aapm-tg-137-nath-2009.md](sources/02_prostate_gu/raw/aapm-tg-137-nath-2009.md)


**Topics:** `prostate`, `AAPM-TG-137`, `LDR-permanent-seed`, `dose-prescription`, `erratum`

**See also:**
- → [#kb:pros:ldr:abs-aua-astro-ldr-2012](#kb:pros:ldr:abs-aua-astro-ldr-2012) (`abs-aua-astro-ldr-2012.md`)
- → [#kb:pros:ldr:salvage-prostate-bt](#kb:pros:ldr:salvage-prostate-bt) (`salvage-prostate-bt.md`)

---

<a id="kb:pros:guidelines:aua-astro-2022-prostate"></a>

#### From Guidance to Practice: Understanding the 2026 AUA/ASTRO Clinically Localized Prostate Cancer Guideline Amendment (2022)

📄 [aua-astro-2022-prostate.md](sources/02_prostate_gu/raw/aua-astro-2022-prostate.md)

**Journal:** Journal of Urology  
**DOI:** 10.1097/JU.0000000000002718  
**PMID:** 42155118 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42155118/))  

**Topics:** `prostate`, `AUA-ASTRO`, `guideline-amendment`, `clinically-localized`

**Key facts:**
- Document type is a clinical practice guideline amendment for clinically localized prostate cancer.

**Key numbers:**
- PMID 42155118
- DOI 10.1097/JU.0000000000002718

**See also:**
- → [#kb:pros:ldr:abs-aua-astro-ldr-2012](#kb:pros:ldr:abs-aua-astro-ldr-2012) (`abs-aua-astro-ldr-2012.md`)
- → [#kb:pros:hdr:abs-2022-prostate-hdr](#kb:pros:hdr:abs-2022-prostate-hdr) (`abs-2022-prostate-hdr.md`)

---

## <a id="brst"></a> Breast Brachytherapy (13 files)

**Subtitle:** APBI, IORT, balloon, strut, TARGIT-A  
**Master list:** [`sources/03_breast/INDEX.md`](sources/03_breast/INDEX.md)

### <a id="brst-apbi"></a> Accelerated Partial Breast Irradiation (APBI) (8 files)

<a id="kb:brst:apbi:abs-apbi-2013"></a>

#### 03_breast — Breast Brachytherapy (13 files)

📄 [abs-apbi-2013.md](sources/03_breast/raw/abs-apbi-2013.md)


**Topics:** `breast`, `APBI`, `IOERT`, `ASTRO-consensus`, `n=215`, `IBTR-3.96%`

**See also:**
- → [#kb:brst:apbi:astro-2022-apbi](#kb:brst:apbi:astro-2022-apbi) (`astro-2022-apbi.md`)
- → [#kb:brst:apbi:gec-estro-apbi-2016](#kb:brst:apbi:gec-estro-apbi-2016) (`gec-estro-apbi-2016.md`)
- → [#kb:brst:apbi:estro-acrop-breast-2018](#kb:brst:apbi:estro-acrop-breast-2018) (`estro-acrop-breast-2018.md`)
- → [#kb:brst:apbi:nsabp-b39-rtog-0413](#kb:brst:apbi:nsabp-b39-rtog-0413) (`nsabp-b39-rtog-0413.md`)

---

<a id="kb:brst:apbi:astro-2022-apbi"></a>

#### Recent Trends in Whole-Breast Irradiation Versus Partial-Breast Irradiation in Ductal Carcinoma in situ with Breast-Conserving Surgery 2011-2021: A National Cancer Database Study (2022)

📄 [astro-2022-apbi.md](sources/03_breast/raw/astro-2022-apbi.md)

**Journal:** Practical Radiation Oncology  
**DOI:** 10.1016/j.prro.2021.10.006  
**PMID:** 41874876 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41874876/))  

**Topics:** `breast`, `APBI`, `DCIS`, `NCDB-analysis`, `2017-consensus-update`

**Key facts:**
- The 2017 ASTRO consensus update expanded the 'suitable' DCIS group to include age ≥50, screen-detected, low/intermediate nuclear grade, ≤25 mm, and margins ≥3 mm.
- Overall APBI utilization for DCIS increased from 7.2% (2011-2017) to 13.0% (2018-2021) after the consensus update.
- Among patients ≥50 with low- to intermediate-grade DCIS (≤25 mm), APBI use rose from 8.8% to 15.5%.
- After 2017, APBI use was higher in patients ≥50 (13.6% vs 9.7%), academic centers (15.4% vs 12.0%), low-grade (15.8%) and intermediate-grade (13.5%) vs high-grade (11.4%) disease, tumors ≤25 mm (13.7% vs 9.7%), and ER-positive (13.9% vs 10.7%) cases.

**Dose constraints / prescription:**
- 2017 ASTRO 'suitable' DCIS criteria: margins ≥3 mm; tumor size ≤25 mm.

**Trial endpoints / outcomes:**
- APBI utilization rate pre- vs post-2017 update (7.2% vs 13.0%).
- APBI utilization by age, facility type, tumor grade/size, ER status.

**Key numbers:**
- Time periods: 2011-2017 vs 2018-2021.
- Data source: National Cancer Database.

**See also:**
- → [#kb:brst:apbi:abs-apbi-2013](#kb:brst:apbi:abs-apbi-2013) (`abs-apbi-2013.md`)
- → [#kb:brst:apbi:gec-estro-apbi-2016](#kb:brst:apbi:gec-estro-apbi-2016) (`gec-estro-apbi-2016.md`)
- → [#kb:brst:apbi:nsabp-b39-rtog-0413](#kb:brst:apbi:nsabp-b39-rtog-0413) (`nsabp-b39-rtog-0413.md`)
- → [#kb:brst:apbi:estro-acrop-breast-2018](#kb:brst:apbi:estro-acrop-breast-2018) (`estro-acrop-breast-2018.md`)

---

<a id="kb:brst:apbi:balloon-mammosite"></a>

#### MammoSite Balloon-Based Breast Brachytherapy (2020)

📄 [balloon-mammosite.md](sources/03_breast/raw/balloon-mammosite.md)

**Journal:** Various  
**DOI:** 10.1016/S1538-4721(03)00091-9  

**Topics:** `breast`, `APBI`, `MammoSite`, `balloon`, `single-lumen`

**Key facts:**
- DOI listed: 10.1016/S1538-4721(03)00091-9.

**See also:**
- → [#kb:brst:apbi:savi-strut-apbi](#kb:brst:apbi:savi-strut-apbi) (`savi-strut-apbi.md`)
- → [#kb:brst:apbi:estro-acrop-breast-2018](#kb:brst:apbi:estro-acrop-breast-2018) (`estro-acrop-breast-2018.md`)

---

<a id="kb:brst:apbi:estro-acrop-breast-2018"></a>

#### ESTRO-ACROP guideline: Interstitial multi-catheter breast brachytherapy as Accelerated Partial Breast Irradiation alone or as boost - GEC-ESTRO Breast Cancer Working Group practical recommendations (2018)

📄 [estro-acrop-breast-2018.md](sources/03_breast/raw/estro-acrop-breast-2018.md)

**Journal:** Radiotherapy and Oncology  
**DOI:** 10.1016/j.radonc.2018.04.009  
**PMID:** 29691075 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/29691075/))  

**Topics:** `breast`, `APBI`, `ESTRO-ACROP`, `multi-catheter`, `interstitial`, `boost`

**Key facts:**
- Consensus statement from GEC-ESTRO Breast Cancer Working Group provides practical guidelines for multi-catheter image-guided brachytherapy in conservative management of breast cancer, for APBI or for a breast boost.
- Document was reviewed and approved by the full panel, the GEC-ESTRO executive board, and ACROP.
- Guidelines cover 3D treatment planning, catheter insertion techniques, dosimetry, and quality assurance for APBI and boost with multi-catheter image-guided brachytherapy after breast conserving surgery.
- Detailed recommendations for daily practice including dose constraints are given.
- Same rules apply for brachytherapy-based boost irradiation after whole breast irradiation and for partial breast re-irradiation.

**Dose constraints / prescription:**
- File states that detailed dose constraints are given in the recommendations, but the specific numerical constraints are not listed in the abstract body available in this file.

**See also:**
- → [#kb:brst:apbi:gec-estro-apbi-2016](#kb:brst:apbi:gec-estro-apbi-2016) (`gec-estro-apbi-2016.md`)
- → [#kb:brst:apbi:abs-apbi-2013](#kb:brst:apbi:abs-apbi-2013) (`abs-apbi-2013.md`)
- → [#kb:brst:apbi:savi-strut-apbi](#kb:brst:apbi:savi-strut-apbi) (`savi-strut-apbi.md`)

---

<a id="kb:brst:apbi:gec-estro-apbi-2016"></a>

#### No increased risk for accelerated partial breast irradiation with multicatheter brachytherapy in early-stage invasive lobular carcinoma (2016)

📄 [gec-estro-apbi-2016.md](sources/03_breast/raw/gec-estro-apbi-2016.md)

**Journal:** Radiotherapy and Oncology  
**DOI:** 10.1016/j.radonc.2016.03.001  
**PMID:** 42232851 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42232851/))  

**Topics:** `breast`, `APBI`, `GEC-ESTRO`, `ILC`, `invasive-lobular`, `n=47`, `4y-OS-97%`

**Key facts:**
- Retrospective review of 47 patients with ILC treated between February 2016 and March 2023 with BCS followed by APBI via multicatheter HDR brachytherapy per GEC-ESTRO recommendations.
- Pre-operative breast MRI performed in 37 patients (78.7%); median age 65 years (range 49-80); median tumor diameter 1.1 cm (range 0-2.5 cm).
- Treatment was 32 Gy in 8 fractions for 44 patients (93.6%) and 30.1 Gy in 7 fractions for 3 patients (6.4%); 42 patients (89.4%) received adjuvant anti-hormonal therapy.
- At median follow-up 47 months (range 24-106), no IBTR was observed; 4-year OS was 97%.
- Late side effects: mild hyperpigmentation in 2 patients (4.3%), breast asymmetry in 1 patient (2.1%); asymptomatic fatty tissue necrosis in 7 patients (14.9%) on follow-up mammography.

**Dose constraints / prescription:**
- APBI 32 Gy in 8 fractions (93.6% of patients).
- APBI 30.1 Gy in 7 fractions (6.4% of patients).

**Trial endpoints / outcomes:**
- Ipsilateral breast tumor recurrence (IBTR): 0% at median 47-month follow-up.
- 4-year overall survival: 97%.
- Late side effects: hyperpigmentation 4.3%, breast asymmetry 2.1%, asymptomatic fatty necrosis 14.9%.

**Key numbers:**
- 47 patients, treatment period February 2016 - March 2023.
- 44 (93.6%) met all low-risk criteria; 3 (6.4%) had lymphovascular space invasion.
- Median follow-up 47 months (range 24-106).

**See also:**
- → [#kb:brst:apbi:abs-apbi-2013](#kb:brst:apbi:abs-apbi-2013) (`abs-apbi-2013.md`)
- → [#kb:brst:apbi:estro-acrop-breast-2018](#kb:brst:apbi:estro-acrop-breast-2018) (`estro-acrop-breast-2018.md`)
- → [#kb:brst:apbi:astro-2022-apbi](#kb:brst:apbi:astro-2022-apbi) (`astro-2022-apbi.md`)

---

<a id="kb:brst:apbi:nature-apbi-alternative-wbi-2020"></a>

#### APBI is an alternative to WBI (2025)

📄 [nature-apbi-alternative-wbi-2020.md](sources/03_breast/raw/nature-apbi-alternative-wbi-2020.md)

**Journal:** Nature  
**DOI:** 10.1038/s41571-019-0323-0  
**PMID:** 31900442 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/31900442/))  

**Topics:** `breast`, `APBI`, `WBI-alternative`, `Nature-Reviews`

**Key facts:**
- No abstract content is present in the file body.

**See also:**
- → [#kb:brst:apbi:astro-2022-apbi](#kb:brst:apbi:astro-2022-apbi) (`astro-2022-apbi.md`)
- → [#kb:brst:apbi:nsabp-b39-rtog-0413](#kb:brst:apbi:nsabp-b39-rtog-0413) (`nsabp-b39-rtog-0413.md`)
- → [#kb:brst:apbi:gec-estro-apbi-2016](#kb:brst:apbi:gec-estro-apbi-2016) (`gec-estro-apbi-2016.md`)

---

<a id="kb:brst:apbi:nsabp-b39-rtog-0413"></a>

#### Quality-of-life outcomes from NRG Oncology NSABP B-39/RTOG 0413: whole-breast irradiation vs accelerated partial-breast irradiation after breast-conserving surgery (2019)

📄 [nsabp-b39-rtog-0413.md](sources/03_breast/raw/nsabp-b39-rtog-0413.md)

**Journal:** Lancet Oncology  
**DOI:** 10.1016/S1470-2045(19)30465-2  
**PMID:** 39254630 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/39254630/))  

**Topics:** `breast`, `APBI`, `NSABP-B-39`, `RTOG-0413`, `QOL`, `n=975`, `NCT00103181`

**Key facts:**
- NRG Oncology NSABP B-39/RTOG 0413 compared WBI to APBI; APBI was not equivalent to WBI in local tumor control.
- QOL sub-study enrolled 975 patients (March 21, 2005 - May 25, 2009); 950 had follow-up data.
- APBI had 3-year cosmesis equivalent to WBI (95% CI -0.0001 to -0.16; equivalence margin -0.22 to 0.22) in all patients.
- APBI without chemotherapy had less end-of-treatment fatigue (mean BCTOS fatigue score 63 vs 59, P = 0.011); APBI with chemotherapy had worse fatigue (43 vs 49, P = 0.011).
- APBI group reported less pain (BCTOS) at EOT (WBI 2.29 vs APBI 1.97) but worse pain at 3 years (WBI 1.62 vs APBI 1.71).
- Differences in fatigue and other symptoms appeared to resolve by ≥6 months.
- Trial registered NCT00103181.

**Trial endpoints / outcomes:**
- Local tumor control (primary, APBI not equivalent to WBI).
- 3-year cosmesis change equivalency (BCTOS; a priori margin 0.4 SD).
- End-of-treatment fatigue change (SF-36 vitality scale).
- Pain (BCTOS) at EOT and 3 years.

**Key numbers:**
- 975 patients enrolled in QOL sub-study; 950 with follow-up data.
- Enrolment period: March 21, 2005 to May 25, 2009.
- Assessment time points: baseline, treatment completion, 4 weeks, 6, 12, 24, and 36 months.

**See also:**
- → [#kb:brst:apbi:astro-2022-apbi](#kb:brst:apbi:astro-2022-apbi) (`astro-2022-apbi.md`)
- → [#kb:brst:apbi:gec-estro-apbi-2016](#kb:brst:apbi:gec-estro-apbi-2016) (`gec-estro-apbi-2016.md`)
- → [#kb:brst:iort:targit-a-vaidya-2014](#kb:brst:iort:targit-a-vaidya-2014) (`targit-a-vaidya-2014.md`)

---

<a id="kb:brst:apbi:savi-strut-apbi"></a>

#### SAVI catheter digitization impact: A single institution multiuser uncertainty study (2011)

📄 [savi-strut-apbi.md](sources/03_breast/raw/savi-strut-apbi.md)

**Journal:** Brachytherapy  
**PMID:** 39266380 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/39266380/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/39266380/  

**Topics:** `breast`, `APBI`, `SAVI`, `strut-based`, `digitization-uncertainty`, `n=4`

**Key facts:**
- Four clinically approved SAVI cases implanted with 6-1 SAVI device were analyzed; six experienced physicists independently digitized SAVI catheters.
- Plans used significant peripheral loading with SAVI catheters near the chest wall and/or skin.
- Average and maximum dwell positional digitization uncertainties were 0.36 mm and 0.75 mm, respectively.
- Average PTV_Eval D90 was 97.11 ± 2.93%, V150 was 23.10 ± 4.25 cc, V200 was 11.88 ± 1.93 cc.
- Chest-Wall/Ribs D0.03cc was 103.40 ± 9.23% and Skin D0.03cc was 93.60 ± 6.14% — all OAR constraints were met on all plans.
- Aggregate analysis showed a clinically nonsignificant spread around the mean for all parameters; SAVI planning constraints were stable within reasonable digitization variation.

**Dose constraints / prescription:**
- PTV_Eval D90: 97.11 ± 2.93%.
- PTV_Eval V150: 23.10 ± 4.25 cc.
- PTV_Eval V200: 11.88 ± 1.93 cc.
- Chest-Wall/Ribs D0.03cc: 103.40 ± 9.23%.
- Skin D0.03cc: 93.60 ± 6.14%.

**Trial endpoints / outcomes:**
- Digitization uncertainty (dwell position 0.36 mm avg, 0.75 mm max).
- Plan parameter variability across 6 physicists and 4 cases.

**Key numbers:**
- 4 SAVI cases, all 6-1 device.
- 6 physicists independently digitized.
- Plan parameters evaluated: PTV_Eval D90, V150, V200; OAR D0.03cc, D0.1cc, D1cc, D2cc.

**See also:**
- → [#kb:brst:apbi:estro-acrop-breast-2018](#kb:brst:apbi:estro-acrop-breast-2018) (`estro-acrop-breast-2018.md`)
- → [#kb:brst:apbi:balloon-mammosite](#kb:brst:apbi:balloon-mammosite) (`balloon-mammosite.md`)

---

### <a id="brst-iort"></a> Intraoperative RT (IORT) (2 files)

<a id="kb:brst:iort:iort-electronic-bt"></a>

#### Dosimetric comparison of the INTRABEAM and Axxent for intraoperative breast radiotherapy (2020)

📄 [iort-electronic-bt.md](sources/03_breast/raw/iort-electronic-bt.md)

**Journal:** Brachytherapy  
**PMID:** 31879239 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/31879239/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/31879239/  

**Topics:** `breast`, `IORT`, `INTRABEAM`, `Axxent`, `50-kVp`, `dosimetric-comparison`

**Key facts:**
- INTRABEAM and Xoft Axxent deliver IORT to the lumpectomy cavity using stationary or stepped 50 kVp X-ray sources, respectively.
- Comparison covered three comparable applicator sizes with volume differences <11%.
- INTRABEAM mean DVPs: V90 5.5 ± 0.8%, V80 12.1 ± 1.5%, V50 47.5 ± 5.8%, Dmin 6.4 ± 0.6 Gy, HI 3.2 ± 0.3.
- Axxent mean DVPs: V90 7.4 ± 0.3%, V80 14.7 ± 0.8%, V50 55.2 ± 4.7%, Dmin 4.0 ± 0.6 Gy, HI 6.4 ± 1.1.
- INTRABEAM skin doses: 7.7-9.0 Gy at 0.7 cm and 5.5-6.8 Gy at 1.0 cm.
- Axxent skin doses: 10.7-13.0 Gy at 0.7 cm and 7.8-9.3 Gy at 1.0 cm.

**Dose constraints / prescription:**
- INTRABEAM skin dose: 7.7-9.0 Gy at 0.7 cm; 5.5-6.8 Gy at 1.0 cm.
- Axxent skin dose: 10.7-13.0 Gy at 0.7 cm; 7.8-9.3 Gy at 1.0 cm.
- INTRABEAM Dmin: 6.4 ± 0.6 Gy.
- Axxent Dmin: 4.0 ± 0.6 Gy.

**Trial endpoints / outcomes:**
- Comparable ±5% dosimetric coverage for tissue ≤0.5 cm from the cavity between INTRABEAM and Axxent.
- Higher skin dose for Axxent plans compared to INTRABEAM.

**Key numbers:**
- Three applicator sizes with volume differences <11%.
- Source energy: 50 kVp X-ray.
- Skin distance points: 0.7 cm and 1.0 cm.

**See also:**
- → [#kb:brst:iort:targit-a-vaidya-2014](#kb:brst:iort:targit-a-vaidya-2014) (`targit-a-vaidya-2014.md`)
- → [#kb:brst:apbi:abs-apbi-2013](#kb:brst:apbi:abs-apbi-2013) (`abs-apbi-2013.md`)

---

<a id="kb:brst:iort:targit-a-vaidya-2014"></a>

#### A novel methodology using direct patient contact and UK national registries to collect long-term data from randomised trials: TARGIT-X - an extended follow-up study of the TARGIT-A trial of targeted intraoperative radiotherapy for breast cancer (2014)

📄 [targit-a-vaidya-2014.md](sources/03_breast/raw/targit-a-vaidya-2014.md)

**Journal:** Lancet  
**DOI:** 10.1016/S0140-6736(13)61950-9  
**PMID:** 42011087 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42011087/))  

**Topics:** `breast`, `IORT`, `TARGIT-A`, `TARGIT-X`, `n=2298+n=1153`, `16y-lung-cancer-1.8%-vs-7.2%`

**Key facts:**
- TARGIT-A trial: targeted intraoperative radiotherapy during lumpectomy vs whole-breast EBRT (n=2298) and delayed TARGIT-IORT vs EBRT (n=1153), recruited women with early breast cancer in 33 centres across 12 countries between March 2000 and June 2012.
- TARGIT-X enrolled UK patients from TARGIT-A; 607 of 714 UK patients were initially eligible.
- 574 (94.5%) patients' status ascertained; 87% (502/574) had health status determined; 60.3% (366/607) of total consented and were in good health.
- 136 patients did not participate: 105/136 (77%) were too unwell or had died; less than 5% (25/502) were unwilling.
- An additional 103 deaths were recorded, more than doubling the initial total to 203.
- Data quality: mismatch rate for date recording <0.1% (1/1470 forms); patients increased follow-up by a median 6 years to 14 years (IQR 13-16).
- 16-year lung cancer incidence: 1.8% with TARGIT-IORT vs 7.2% with EBRT.
- Follow-up cost was <£60/patient/year.
- Trial registered ISRCTN86287193 and NCT03501121.

**Trial endpoints / outcomes:**
- 16-year lung cancer incidence: 1.8% (TARGIT-IORT) vs 7.2% (EBRT).
- Long-term survival status and health events.
- Total deaths recorded: 203 (after TARGIT-X extension).

**Key numbers:**
- TARGIT-A: n=2298 (IORT vs EBRT) + n=1153 (delayed IORT vs EBRT).
- Recruitment: 33 centres, 12 countries, March 2000 - June 2012.
- TARGIT-X: 607 eligible UK patients; 574 (94.5%) status ascertained.
- Median follow-up extension: 6 years (to 14 years total, IQR 13-16).
- Funding: NIHR HTA award 14/49/13.

**See also:**
- → [#kb:brst:iort:iort-electronic-bt](#kb:brst:iort:iort-electronic-bt) (`iort-electronic-bt.md`)
- → [#kb:brst:apbi:abs-apbi-2013](#kb:brst:apbi:abs-apbi-2013) (`abs-apbi-2013.md`)
- → [#kb:brst:apbi:nsabp-b39-rtog-0413](#kb:brst:apbi:nsabp-b39-rtog-0413) (`nsabp-b39-rtog-0413.md`)
- → [#kb:brst:boost:wbi-boost-eortc-22881](#kb:brst:boost:wbi-boost-eortc-22881) (`wbi-boost-eortc-22881.md`)

---

### <a id="brst-reirradiation"></a> Reirradiation (1 files)

<a id="kb:brst:reirradiation:breast-reirradiation-survey-2024"></a>

#### Breast Cancer Reirradiation Practice Patterns: An International Survey From the Reirradiation Collaborative Group (ReCOG) (2025)

📄 [breast-reirradiation-survey-2024.md](sources/03_breast/raw/breast-reirradiation-survey-2024.md)

**Journal:** International Journal of Radiation Oncology  
**DOI:** 10.1016/j.prro.2026.03.012  
**PMID:** 42207068 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42207068/))  

**Topics:** `breast`, `reirradiation`, `ReCOG`, `international-survey`, `n=37-respondents`

**Key facts:**
- Survey conducted February 2024 to June 2025 with 37 respondents (Europe n=19, North America n=14, other n=4) from 32 identifiable institutions.
- Top reasons for not offering reRT: high risk of major side effects from prior RT such as fibrosis or lymphedema (40%), short relapse interval (33%), limited life expectancy (17%).
- Conventional fractionation 45-60 Gy in 1.8-2 Gy fractions over 23-30 fractions was the most frequently selected reRT regimen, followed by moderate hypofractionation 40 Gy in 15 fractions.
- One respondent used twice-daily 40-50 Gy in 1.25-1.5 Gy fractions; IMRT/VMAT was preferred modality; proton and brachytherapy used selectively; hyperthermia used by 7 respondents.
- Top knowledge gaps identified: (1) long-term toxicity and oncologic outcome data, (2) standardized and validated OOI dose guidance, (3) consensus on optimal reRT dose-fractionation schedules.
- 80% of respondents performed plan summation when prior DICOM RT data were available.

**Dose constraints / prescription:**
- Conventional reRT regimen: 45-60 Gy in 1.8-2 Gy fractions over 23-30 fractions.
- Moderate hypofractionation reRT: 40 Gy in 15 fractions.
- Twice-daily reRT: 40-50 Gy in 1.25-1.5 Gy fractions.

**Trial endpoints / outcomes:**
- Toxicity impact on QoL: fibrosis 31%, pain 17%, arm lymphedema 14%.

**Key numbers:**
- 37 survey respondents from 32 institutions.
- Survey period: February 2024 to June 2025.
- Hyperthermia use: 7 respondents.
- Plan summation performed by 80% of respondents.

**See also:**
- → [#kb:brst:boost:wbi-boost-eortc-22881](#kb:brst:boost:wbi-boost-eortc-22881) (`wbi-boost-eortc-22881.md`)
- → [#kb:brst:apbi:astro-2022-apbi](#kb:brst:apbi:astro-2022-apbi) (`astro-2022-apbi.md`)

---

### <a id="brst-boost"></a> Whole Breast Boost (1 files)

<a id="kb:brst:boost:wbi-boost-eortc-22881"></a>

#### The addition of a boost dose on the primary tumour bed after lumpectomy in breast conserving treatment for breast cancer. A summary of the results of EORTC 22881-10882 'boost versus no boost' trial (2015)

📄 [wbi-boost-eortc-22881.md](sources/03_breast/raw/wbi-boost-eortc-22881.md)

**Journal:** Lancet Oncology  
**DOI:** 10.1016/S1470-2045(15)70054-1  
**PMID:** 18760649 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/18760649/))  

**Topics:** `breast`, `boost`, `EORTC-22881-10882`, `lumpectomy`, `n=5569`, `10y-LR-10.2%-vs-6.2%`

**Key facts:**
- 5569 patients after lumpectomy followed by whole breast irradiation of 50 Gy were randomised.
- After microscopically complete lumpectomy (5318 patients), boost doses were 0 or 16 Gy; after microscopically incomplete (251 patients), randomisation was between 10 and 26 Gy.
- 10-year cumulative local recurrence: 10.2% (0 Gy) vs 6.2% (16 Gy) after complete lumpectomy, p<0.0001.
- 10-year cumulative local recurrence: 17.5% (10 Gy) vs 10.8% (26 Gy) after incomplete lumpectomy, p>0.1.
- Severe fibrosis rate at 10 years: 1.6% (0 Gy), 3.3% (10 Gy), 4.4% (16 Gy), 14.4% (26 Gy) — dose dependent.
- With 10 years median follow-up, no impact of survival was observed.
- The magnitude of the absolute 10-year risk reduction from the boost decreased with increasing age.

**Dose constraints / prescription:**
- Whole breast irradiation: 50 Gy.
- Boost dose 0 Gy vs 16 Gy (after microscopically complete lumpectomy).
- Boost dose 10 Gy vs 26 Gy (after microscopically incomplete lumpectomy).
- Severe fibrosis dose dependence: 1.6% (0 Gy), 3.3% (10 Gy), 4.4% (16 Gy), 14.4% (26 Gy) at 10 years.

**Trial endpoints / outcomes:**
- 10-year cumulative local recurrence (10.2% vs 6.2% complete; 17.5% vs 10.8% incomplete).
- 10-year severe fibrosis rate (dose dependent).
- Overall survival (no impact observed at 10 years).

**Key numbers:**
- 5569 patients randomised.
- 5318 with microscopically complete lumpectomy; 251 with microscopically incomplete.
- Median follow-up 10 years.

**See also:**
- → [#kb:brst:apbi:astro-2022-apbi](#kb:brst:apbi:astro-2022-apbi) (`astro-2022-apbi.md`)
- → [#kb:brst:apbi:nsabp-b39-rtog-0413](#kb:brst:apbi:nsabp-b39-rtog-0413) (`nsabp-b39-rtog-0413.md`)
- → [#kb:brst:iort:targit-a-vaidya-2014](#kb:brst:iort:targit-a-vaidya-2014) (`targit-a-vaidya-2014.md`)

---

### <a id="brst-guidelines"></a> Guidelines (1 files)

<a id="kb:brst:guidelines:nccn-breast-2024"></a>

#### NCCN Breast Cancer Guideline (2024)

📄 [nccn-breast-2024.md](sources/03_breast/raw/nccn-breast-2024.md)

**Journal:** NCCN Guidelines  

**Topics:** `breast`, `NCCN`, `guideline`

**Key facts:**
- Notes that NCCN guidelines are updated annually and the BT section provides evidence-based recommendations integrated with other treatment modalities.
- No specific dose constraints, endpoints, or numbers are quoted in the file.

**See also:**
- → [#kb:brst:apbi:astro-2022-apbi](#kb:brst:apbi:astro-2022-apbi) (`astro-2022-apbi.md`)
- → [#kb:brst:apbi:abs-apbi-2013](#kb:brst:apbi:abs-apbi-2013) (`abs-apbi-2013.md`)

---

## <a id="hns"></a> Head & Neck / Skin BT (12 files)

**Subtitle:** oral, NPC, lip, skin, keloid  
**Master list:** [`sources/04_head_neck_skin/INDEX.md`](sources/04_head_neck_skin/INDEX.md)

### <a id="hns-hn_cancer"></a> Head & Neck Cancers (4 files)

<a id="kb:hns:hn_cancer:gec-estro-hn"></a>

#### Salvage brachytherapy for local recurrence of cancer after definitive irradiation: a GEC-ESTRO narrative review (2017)

📄 [gec-estro-hn.md](sources/04_head_neck_skin/raw/gec-estro-hn.md)

**Journal:** Radiotherapy and Oncology  
**PMID:** 40472997 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/40472997/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/40472997/  

**Topics:** `head-neck`, `salvage`, `GEC-ESTRO`, `narrative-review`

**Key facts:**
- The number of irradiated cancer survivors is increasing; mainly for breast, prostate, head-and-neck, uterine and rectal cancers.
- Salvage brachytherapy delivers the dose directly inside the target volume with a sharp dose fall-off and low integral dose compared to EBRT.
- For all indications of salvage BT, patient selection is crucial and shared decision making is a key point.

**See also:**
- → [#kb:hns:hn_cancer:lip-cancer-bt](#kb:hns:hn_cancer:lip-cancer-bt) (`lip-cancer-bt.md`)
- → [#kb:hns:hn_cancer:npc-intracavitary-bt](#kb:hns:hn_cancer:npc-intracavitary-bt) (`npc-intracavitary-bt.md`)
- → [#kb:hns:hn_cancer:nccn-hn-2024](#kb:hns:hn_cancer:nccn-hn-2024) (`nccn-hn-2024.md`)

---

<a id="kb:hns:hn_cancer:lip-cancer-bt"></a>

#### A review on the transition from PDR to HDR brachytherapy (interventional radiotherapy) for treatment of head and neck cancer: Clinical and practical aspects (2018)

📄 [lip-cancer-bt.md](sources/04_head_neck_skin/raw/lip-cancer-bt.md)

**Journal:** Brachytherapy  
**PMID:** 41528860 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41528860/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/41528860/  

**Topics:** `head-neck`, `lip`, `nasal-vestibule`, `PDR-vs-HDR`, `LC-91-100%-PDR`, `LC-86-100%-HDR`

**Key facts:**
- Of 1095 records identified, eleven studies (four PDR, seven HDR) were included for the systematic review on lip and nasal vestibule carcinoma.
- Local control (LC) rates ranged from 91% to 100% (median 93%) for PDR studies and 86-100% (median 95%) for HDR studies.
- Both PDR and HDR BT result in excellent LC with median above 93% for lip and nasal vestibule carcinomas.
- A transition from PDR to HDR BT is not expected to influence local control; HDR provides more flexibility in patient hospitalization and afterloader availability.

**Trial endpoints / outcomes:**
- LC rates 91-100% (median 93%) for PDR
- LC rates 86-100% (median 95%) for HDR

**Key numbers:**
- 1095 records identified
- 11 studies included (4 PDR, 7 HDR)

**See also:**
- → [#kb:hns:hn_cancer:npc-intracavitary-bt](#kb:hns:hn_cancer:npc-intracavitary-bt) (`npc-intracavitary-bt.md`)
- → [#kb:hns:hn_cancer:gec-estro-hn](#kb:hns:hn_cancer:gec-estro-hn) (`gec-estro-hn.md`)
- → [#kb:hns:hn_cancer:nccn-hn-2024](#kb:hns:hn_cancer:nccn-hn-2024) (`nccn-hn-2024.md`)

---

<a id="kb:hns:hn_cancer:nccn-hn-2024"></a>

#### NCCN Head and Neck Cancers Guideline (2024)

📄 [nccn-hn-2024.md](sources/04_head_neck_skin/raw/nccn-hn-2024.md)

**Journal:** NCCN Guidelines  

**Topics:** `head-neck`, `NCCN`, `guideline`

**Key facts:**
- The brachytherapy section covers patient selection criteria, applicator types and techniques, dose prescriptions and fractionation schedules, integration with EBRT, and follow-up/surveillance recommendations.

**See also:**
- → [#kb:hns:hn_cancer:gec-estro-hn](#kb:hns:hn_cancer:gec-estro-hn) (`gec-estro-hn.md`)
- → [#kb:hns:hn_cancer:lip-cancer-bt](#kb:hns:hn_cancer:lip-cancer-bt) (`lip-cancer-bt.md`)
- → [#kb:hns:hn_cancer:npc-intracavitary-bt](#kb:hns:hn_cancer:npc-intracavitary-bt) (`npc-intracavitary-bt.md`)

---

<a id="kb:hns:hn_cancer:npc-intracavitary-bt"></a>

#### NPC Intracavitary Brachytherapy (2020)

📄 [npc-intracavitary-bt.md](sources/04_head_neck_skin/raw/npc-intracavitary-bt.md)

**Journal:** Various  
**URL:** https://pubmed.ncbi.nlm.nih.gov/?term=NPC+Intracavitary+Brachytherapy  

**Topics:** `head-neck`, `NPC`, `intracavitary`

**See also:**
- → [#kb:hns:hn_cancer:lip-cancer-bt](#kb:hns:hn_cancer:lip-cancer-bt) (`lip-cancer-bt.md`)
- → [#kb:hns:hn_cancer:gec-estro-hn](#kb:hns:hn_cancer:gec-estro-hn) (`gec-estro-hn.md`)
- → [#kb:hns:hn_cancer:nccn-hn-2024](#kb:hns:hn_cancer:nccn-hn-2024) (`nccn-hn-2024.md`)

---

### <a id="hns-skin"></a> Skin Cancer (NMSC) & Superficial BT (4 files)

<a id="kb:hns:skin:abs-skin-2020"></a>

#### ABS Skin Cancer Brachytherapy Consensus (2020)

📄 [abs-skin-2020.md](sources/04_head_neck_skin/raw/abs-skin-2020.md)

**Journal:** Various  
**DOI:** 10.1016/j.brachy.2019.09.004  

**Topics:** `skin`, `NMSC`, `ABS`, `consensus`

**Key facts:**
- DOI registered as 10.1016/j.brachy.2019.09.004.

**See also:**
- → [#kb:hns:skin:gec-estro-skin-2018](#kb:hns:skin:gec-estro-skin-2018) (`gec-estro-skin-2018.md`)
- → [#kb:hns:skin:esteya-electronic](#kb:hns:skin:esteya-electronic) (`esteya-electronic.md`)
- → [#kb:hns:skin:freiburg-flap-ham](#kb:hns:skin:freiburg-flap-ham) (`freiburg-flap-ham.md`)

---

<a id="kb:hns:skin:esteya-electronic"></a>

#### The Elekta Esteya electronic brachytherapy system in non-melanoma skin cancers: A post-market observational study (2016)

📄 [esteya-electronic.md](sources/04_head_neck_skin/raw/esteya-electronic.md)

**Journal:** Brachytherapy  
**PMID:** 39943976 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/39943976/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/39943976/  

**Topics:** `skin`, `NMSC`, `electronic-BT`, `Elekta-Esteya`, `BED-69-72-Gy`, `n=205`, `2y-recurrence-0.42%`

**Key facts:**
- Treatment doses were chosen from fractionation schemes delivering 69-72 Gy (BED) for low-risk NMSC.
- Eligible patients had pathologically confirmed basal cell or squamous cell carcinoma of clinical stage Tis, T1, or T2, with two or fewer high-risk clinical or pathologic features.
- With 2-year median follow-up, there was one recurrence (0.42%).
- Erythema was the most common acute adverse event (34.1% at 1 month), rebounding back to zero by 6 months.

**Dose constraints / prescription:**
- Treatment BED 69-72 Gy

**Trial endpoints / outcomes:**
- Recurrence rate 0.42% at 2-year median follow-up
- Cosmesis rated excellent/good at 90-100% rates (except HCP ratings 1-3 months: 83-87%)

**Key numbers:**
- 205 patients with 236 lesions
- Six centers participated
- Median age 74 years (range 56-96)
- 62% male, 38% female
- Median follow-up 24.2 months (max 73.5 months)

**See also:**
- → [#kb:hns:skin:abs-skin-2020](#kb:hns:skin:abs-skin-2020) (`abs-skin-2020.md`)
- → [#kb:hns:skin:gec-estro-skin-2018](#kb:hns:skin:gec-estro-skin-2018) (`gec-estro-skin-2018.md`)
- → [#kb:brst:iort:iort-electronic-bt](#kb:brst:iort:iort-electronic-bt) (`iort-electronic-bt.md`)

---

<a id="kb:hns:skin:freiburg-flap-ham"></a>

#### Geometric accuracy of surface high-dose rate brachytherapy applicator and catheters identified using Dixon volumetric interpolated breath-hold examination magnetic resonance images (2015)

📄 [freiburg-flap-ham.md](sources/04_head_neck_skin/raw/freiburg-flap-ham.md)

**Journal:** Strahlenther Onkol  
**PMID:** 42005729 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42005729/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/42005729/  

**Topics:** `skin`, `surface-BT`, `Freiburg-Flap`, `Dixon-VIBE`, `geometric-accuracy`

**Key facts:**
- A fixed flat Freiburg Flap (FF) applicator with 31 empty catheters and 21 spheres was imaged in CT and 3T MR simulator using Dixon VIBE.
- Applicator lengths generally lay within 310 ± 1 mm; catheter lengths were underestimated by up to 2 mm on original images due to reliance on surrogate tunneled beads.
- Adjacent catheter positions lay on average within 0.05 mm from their nominal 10.0 mm distance.
- Average chemical shift induced IP-OP displacements were 2.3 ± 0.6 mm, amounting to 1.2 mm for individual images.

**Key numbers:**
- 31 empty catheters and 21 spheres in applicator
- Applicator length 310 ± 1 mm
- Nominal catheter spacing 10.0 mm
- Chemical shift displacement 2.3 ± 0.6 mm (average), 1.2 mm (individual)

**See also:**
- → [#kb:hns:skin:gec-estro-skin-2018](#kb:hns:skin:gec-estro-skin-2018) (`gec-estro-skin-2018.md`)
- → [#kb:hns:skin:abs-skin-2020](#kb:hns:skin:abs-skin-2020) (`abs-skin-2020.md`)

---

<a id="kb:hns:skin:gec-estro-skin-2018"></a>

#### On the surface of excellence: Core competencies for successful skin and superficial brachytherapy (2018)

📄 [gec-estro-skin-2018.md](sources/04_head_neck_skin/raw/gec-estro-skin-2018.md)

**Journal:** Radiotherapy and Oncology  
**PMID:** 42248726 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42248726/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/42248726/  

**Topics:** `skin`, `GEC-ESTRO`, `core-competencies`, `surface-BT`

**Key facts:**
- BT is increasingly used for delivering highly conformal, surface-weighted radiation to cancers involving the skin with excellent cosmetic outcomes.
- Applications span nonmelanoma skin cancers and cutaneous manifestations of hematologic and other malignancies, in definitive or palliative settings.
- Both electronic and radionuclide-based high-dose-rate BT offer flexible, conformal treatment options with respective advantages and limitations.
- Fractionation schedules range from conventional to ultra-hypofractionated, with prescription depth and applicator type guiding dose.

**See also:**
- → [#kb:hns:skin:abs-skin-2020](#kb:hns:skin:abs-skin-2020) (`abs-skin-2020.md`)
- → [#kb:hns:skin:esteya-electronic](#kb:hns:skin:esteya-electronic) (`esteya-electronic.md`)
- → [#kb:hns:keloid:keloid-bt](#kb:hns:keloid:keloid-bt) (`keloid-bt.md`)

---

### <a id="hns-keloid"></a> Keloid (1 files)

<a id="kb:hns:keloid:keloid-bt"></a>

#### Anatomical location overrides biologically effective dose as a predictor of keloid recurrence after adjuvant radiotherapy: a systematic review and meta-regression (2018)

📄 [keloid-bt.md](sources/04_head_neck_skin/raw/keloid-bt.md)

**Journal:** Brachytherapy  
**PMID:** 42207254 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42207254/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/42207254/  

**Topics:** `skin`, `keloid`, `BED3`, `BED10`, `meta-regression`, `70.5%-lower-recurrence-low-tension`

**Key facts:**
- Analyzing 94 patient cohorts (9909 lesions) from 57 studies, comparing BED10 versus BED3 models.
- Using the BED3 model, a non-linear L-shaped dose-response curve appeared, plateauing above ~50 Gy.
- Multivariable meta-regression identified anatomical location (skin tension) as the sole significant predictor (p < 0.001), with low-tension sites having a 70.5% lower recurrence risk than high-tension sites.
- The BED itself was not significant after adjusting for location (p = 0.104).

**Dose constraints / prescription:**
- BED3 plateau above ~50 Gy

**Trial endpoints / outcomes:**
- Low-tension sites have 70.5% lower recurrence risk than high-tension sites

**Key numbers:**
- 94 patient cohorts
- 9909 lesions from 57 studies
- p < 0.001 for anatomical location
- p = 0.104 for BED after adjusting for location

**See also:**
- → [#kb:hns:skin:gec-estro-skin-2018](#kb:hns:skin:gec-estro-skin-2018) (`gec-estro-skin-2018.md`)
- → [#kb:hns:skin:abs-skin-2020](#kb:hns:skin:abs-skin-2020) (`abs-skin-2020.md`)

---

### <a id="hns-practice_param"></a> Practice Parameters (1 files)

<a id="kb:hns:practice_param:abs-hn-2018"></a>

#### 04_head_neck_skin — Head & Neck / Skin Brachytherapy (12 files)

📄 [abs-hn-2018.md](sources/04_head_neck_skin/raw/abs-hn-2018.md)


**Topics:** `ACR-ABS`, `LDR`, `practice-parameter`, `head-neck`, `skin`, `cervical`, `prostate`

**See also:**
- → [#kb:hns:skin:gec-estro-skin-2018](#kb:hns:skin:gec-estro-skin-2018) (`gec-estro-skin-2018.md`)
- → [#kb:hns:hn_cancer:gec-estro-hn](#kb:hns:hn_cancer:gec-estro-hn) (`gec-estro-hn.md`)
- → [#kb:pros:ldr:abs-aua-astro-ldr-2012](#kb:pros:ldr:abs-aua-astro-ldr-2012) (`abs-aua-astro-ldr-2012.md`)

---

### <a id="hns-related_gyne_qol"></a> Related (Cervical/Vulvar QoL — file miscategorized in 04) (2 files)

<a id="kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024"></a>

#### Impact of primary radiotherapy on the psychosocial well-being of patients with locally advanced cervical cancer (IMPRaCC study) (2025)

📄 [eortc-rt-psychosocial-2024.md](sources/04_head_neck_skin/raw/eortc-rt-psychosocial-2024.md)

**Journal:** EORTC  
**DOI:** 10.1016/j.radonc.2026.111405  
**PMID:** 41621682 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41621682/))  

**Topics:** `cervix`, `LACC`, `psychosocial`, `IMPRaCC`, `QoL`, `n=142`

**Key facts:**
- Among 142 LACC patients, deteriorations in emotional functioning, social functioning and fatigue were more frequent during treatment (18.6%, 48.8%, 62.8%) than follow-up (10.4%, 25%, 34.4%).
- Psychiatric history was associated with worse social functioning during treatment, while being in a relationship and psychological support were protective factors.
- Brachytherapy delivered in four vs. three fractions seemed to be associated with worse emotional functioning, social functioning and fatigue.
- Interviews with 13 patients revealed emotional distress, especially before brachytherapy, and need for clear and consistent communication across multiple healthcare professionals.

**Key numbers:**
- 142 LACC patients enrolled (2019-2024)
- 13 patients interviewed 4-16 weeks post-treatment
- Follow-up up to two years

**See also:**
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)
- → [#kb:gyn:cervix:lancet-cervical-induction-chemo-2024](#kb:gyn:cervix:lancet-cervical-induction-chemo-2024) (`lancet-cervical-induction-chemo-2024.md`)

---

<a id="kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024"></a>

#### Phase II Trial of Cisplatin, Gemcitabine, and Intensity-Modulated Radiation Therapy for Locally Advanced Vulvar Squamous Cell Carcinoma: NRG Oncology/GOG Study 279 (2025)

📄 [rtog-cisplatin-gem-imrt-2024.md](sources/04_head_neck_skin/raw/rtog-cisplatin-gem-imrt-2024.md)

**Journal:** RTOG  
**DOI:** 10.1200/JCO.23.02235  
**PMID:** 38574312 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/38574312/))  

**Topics:** `vulvar`, `NRG-279`, `GOG`, `cisplatin-gemcitabine`, `IMRT`, `52-evaluable`, `73%-CPR`

**Key facts:**
- 64 Gy IMRT was prescribed to the vulva, with 50-64 Gy delivered to the groins/low pelvis.
- Cisplatin 40 mg/m2 and gemcitabine 50 mg/m2 were administered once per week throughout IMRT.
- Of 52 evaluable patients, 38 (73% [90% CI, 61 to 83]) achieved complete pathologic response (CPR).
- With median follow-up of 51 months, 12-month PFS was 74% (90% CI, 62.2 to 82.7) and 24-month OS was 70% (90% CI, 57 to 79).

**Dose constraints / prescription:**
- 64 Gy IMRT to vulva
- 50-64 Gy to groins/low pelvis

**Trial endpoints / outcomes:**
- Complete pathologic response (CPR) 73% (90% CI 61-83)
- 12-month PFS 74% (90% CI 62.2-82.7)
- 24-month OS 70% (90% CI 57-79)
- Most common grade 3/4 AEs: hematologic toxicity and radiation dermatitis

**Key numbers:**
- 57 patients enrolled, 52 evaluable
- Median age 58 years (range 25-58)
- 94% White
- 77% had stage II or III disease
- Median 6 chemotherapy cycles (range 1-8)
- 85% of RT plans quality-reviewed with 100% protocol compliance
- Median follow-up 51 months

**See also:**
- → [#kb:gyn:vaginal_vulvar:abs-vulvar-2019](#kb:gyn:vaginal_vulvar:abs-vulvar-2019) (`abs-vulvar-2019.md`)
- → [#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024](#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024) (`gec-estro-endometrial-2024.md`)

---

## <a id="gi"></a> Gastrointestinal BT (14 files)

**Subtitle:** esophageal, rectal, anal, bile duct, pancreatic, gastric  
**Master list:** [`sources/05_gi/INDEX.md`](sources/05_gi/INDEX.md)

### <a id="gi-esophageal"></a> Esophageal BT (2 files)

<a id="kb:gi:esophageal:abs-esophageal-2014"></a>

#### Esophageal BT Prescriptions (ABS 2014)

📄 [abs-esophageal-2014.md](sources/05_gi/raw/abs-esophageal-2014.md)


**Topics:** `esophageal`, `ABS`, `consensus`, `HDR-10-Gy-2-fx`, `LDR-20-Gy`, `applicator-6-10-mm`

**See also:**
- → [#kb:gi:esophageal:nccn-esophageal-2024](#kb:gi:esophageal:nccn-esophageal-2024) (`nccn-esophageal-2024.md`)

---

<a id="kb:gi:esophageal:nccn-esophageal-2024"></a>

#### NCCN Esophageal Cancer Guideline (2024)

📄 [nccn-esophageal-2024.md](sources/05_gi/raw/nccn-esophageal-2024.md)

**Journal:** NCCN Guidelines  

**Topics:** `esophageal`, `NCCN`, `guideline`

**Key facts:**
- Full content requires download from nccn.org with free registration.

**See also:**
- → [#kb:gi:esophageal:abs-esophageal-2014](#kb:gi:esophageal:abs-esophageal-2014) (`abs-esophageal-2014.md`)

---

### <a id="gi-rectal"></a> Rectal BT (4 files)

<a id="kb:gi:rectal:bmj-watchful-waiting-rectal-2025"></a>

#### Can we Save the rectum by watchful waiting or transanal microsurgery following shorT-course radiotherapy and Additional local oR systemic Treatment for early-stage REctal Cancer? STARTREC-3 protocol for a non-randomised, multicentre, phase II platform study (2025)

📄 [bmj-watchful-waiting-rectal-2025.md](sources/05_gi/raw/bmj-watchful-waiting-rectal-2025.md)

**Journal:** BMJ  
**DOI:** 10.1136/bmjopen-2025-111711  
**PMID:** 41407426 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41407426/))  

**Topics:** `rectal`, `STARTREC-3`, `organ-preservation`, `contact-X-ray-BT`, `n=210-planned`

**Key facts:**
- STARTREC-3 aims to increase 2-year organ preservation (OP) rate from 60% to 80% in early rectal cancer (cT1-3abN0) and from 30% to 60% in early-intermediate disease (cT1-3abN1, ≤3 mesorectal nodes ≤8 mm).
- All arms start with 5×5 Gy radiotherapy, followed by arm-specific boost: contact X-ray brachytherapy (arm 1), MR-guided EBRT boost (arm 2), or 3 cycles capecitabine-oxaliplatin chemo (arm 3).
- Primary endpoint is proportion of patients with successful OP at 24 months from onset of therapy.
- Response evaluations (MRI and endoscopy) are planned at 14-16 weeks and 26 weeks after onset of radiotherapy.
- Total planned sample size is 210 patients across the three arms.

**Dose constraints / prescription:**
- Initial radiotherapy: 5×5 Gy in all arms

**Trial endpoints / outcomes:**
- Primary: successful organ preservation at 24 months
- Secondary: toxicity, QoL, functional and oncological outcomes

**Key numbers:**
- Planned sample size: 210 patients across 3 arms
- Target OP rate: 60%→80% (early) and 30%→60% (early-intermediate)
- Evaluation timepoints: 14-16 weeks and 26 weeks post-RT

**See also:**
- → [#kb:gi:rectal:opera-trial-sun-myint](#kb:gi:rectal:opera-trial-sun-myint) (`opera-trial-sun-myint.md`)
- → [#kb:gi:rectal:papillon-contact-xray](#kb:gi:rectal:papillon-contact-xray) (`papillon-contact-xray.md`)
- → [#kb:gi:rectal:rectal-recurrence-hdr](#kb:gi:rectal:rectal-recurrence-hdr) (`rectal-recurrence-hdr.md`)

---

<a id="kb:gi:rectal:opera-trial-sun-myint"></a>

#### ACO/ARO/AIO-22 - External beam radiotherapy combined with endorectal high-dose-rate brachytherapy in elderly and frail patients with rectal cancer (2023)

📄 [opera-trial-sun-myint.md](sources/05_gi/raw/opera-trial-sun-myint.md)

**Journal:** Lancet Gastroenterol Hepatol  
**DOI:** 10.1016/S2468-1253(23)00090-7  
**PMID:** 40276115 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/40276115/))  

**Topics:** `rectal`, `OPERA`, `endoluminal-HDR`, `elderly-frail`, `n=NC`, `EBRT-13x3-Gy`, `HDR-BT-3x8-Gy`

**Key facts:**
- Rectal cancer disproportionately affects the elderly, with more than half of cases diagnosed in individuals aged 70 years or older.
- Inclusion: elderly (age ≥70 years) and/or frail patients with non-metastatic rectal adenocarcinoma (cT1-3d N0/+ M0), localized 0-16 cm from the ano-cutaneous line, unable to undergo radical surgery.
- EBRT regimen: 13 × 3 Gy (total 39 Gy) over 2.5 weeks; restaging at 6.5 weeks post-EBRT.
- Endorectal HDR-BT: 3 weekly fractions of 8 Gy to total 24 Gy (prescribed at radial margin of tumor; max prescription depth 10 mm); alternative CXB with 90 Gy in 3 weekly fractions.
- Primary objective: complete or near complete clinical response (cCR or ncCR) and second primary endpoint is QoL (EORTC QLQ-ELD14), both at 12 months after treatment start.

**Dose constraints / prescription:**
- EBRT: 13 × 3 Gy = 39 Gy total
- HDR-BT: 3 × 8 Gy = 24 Gy total (max prescription depth 10 mm)
- CXB alternative: 90 Gy in 3 weekly fractions

**Trial endpoints / outcomes:**
- Primary: cCR or ncCR at 12 months
- Co-primary: QoL (EORTC QLQ-ELD14) at 12 months

**Key numbers:**
- Elderly age threshold: ≥70 years
- Restaging timepoint: 6.5 weeks after EBRT completion
- Tumor distance: 0-16 cm from ano-cutaneous line
- Trial registration: NCT06729645

**See also:**
- → [#kb:gi:rectal:bmj-watchful-waiting-rectal-2025](#kb:gi:rectal:bmj-watchful-waiting-rectal-2025) (`bmj-watchful-waiting-rectal-2025.md`)
- → [#kb:gi:rectal:papillon-contact-xray](#kb:gi:rectal:papillon-contact-xray) (`papillon-contact-xray.md`)
- → [#kb:gi:rectal:rectal-recurrence-hdr](#kb:gi:rectal:rectal-recurrence-hdr) (`rectal-recurrence-hdr.md`)

---

<a id="kb:gi:rectal:papillon-contact-xray"></a>

#### Assessing dosimetric uncertainties in Papillon+ contact x-ray brachytherapy for rectal cancer: impact of beam quality and tumour geometry (2017)

📄 [papillon-contact-xray.md](sources/05_gi/raw/papillon-contact-xray.md)

**Journal:** Clinical Oncology  
**DOI:** 10.1088/1361-6560/ae5757  
**PMID:** 41880757 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41880757/))  

**Topics:** `rectal`, `Papillon+`, `contact-X-ray`, `HVL-0.77-0.93-mm-Al`

**Key facts:**
- QI measurements performed every four weeks from mid-2022; HVL and depth-dose profile measurements in plastic water phantom conducted twice with two-year interval.
- Progressive beam hardening over time, with HVL increasing from 0.77 mm Al to 0.93 mm Al.
- Spectral shift was reversibly corrected after service replacement of the flattening filter, restoring soft spectrum (HVL ≈ 0.69 mm Al).
- Tumour intrusion produced strongest dosimetric effect, with surface dose increases up to 2.4-fold at 10 mm intrusion, exceeding MC predictions.
- GTV D90 decreased with tumour thickness but increased sharply with intrusion depth; tumour diameter and surrounding medium had negligible impact.

**Dose constraints / prescription:**
- HVL range: 0.69-0.93 mm Al
- Tumour intrusion: 2.5-10 mm scenarios evaluated

**Key numbers:**
- QI measurement frequency: every 4 weeks from mid-2022
- HVL: 0.77 → 0.93 mm Al (beam hardening) → 0.69 mm Al (post-service)
- Surface dose increase at 10 mm intrusion: up to 2.4-fold

**See also:**
- → [#kb:gi:rectal:bmj-watchful-waiting-rectal-2025](#kb:gi:rectal:bmj-watchful-waiting-rectal-2025) (`bmj-watchful-waiting-rectal-2025.md`)
- → [#kb:gi:rectal:opera-trial-sun-myint](#kb:gi:rectal:opera-trial-sun-myint) (`opera-trial-sun-myint.md`)

---

<a id="kb:gi:rectal:rectal-recurrence-hdr"></a>

#### Pelvic chemoradiation with high-dose-rate brachytherapy boost for synchronous prostate and rectal cancers: A rare case series and treatment framework (2015)

📄 [rectal-recurrence-hdr.md](sources/05_gi/raw/rectal-recurrence-hdr.md)

**Journal:** IJROBP  
**PMID:** 42103556 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42103556/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/42103556/  

**Topics:** `rectal`, `HDR-boost`, `pelvic-CRT`, `synchronous-prostate-rectal`, `n=6`

**Key facts:**
- All patients received pelvic CRT (45-50.4 Gy/25-28 fractions) with concurrent 5-FU or capecitabine ± total neoadjuvant therapy.
- HDR-BT boost objectives: prostate V100 ≥ 95%, rectum V75% < 1 cc, urethra D10 ≤ 115%.
- Six men (age 60-78) completed CRT, HDR-BT, and surgery/nonoperative management without interruptions.
- At median 40 months (range 30-110) follow-up post-BT, no locoregional failures occurred.
- HDR-BT achieved prostate V100 94.6%-97.7%, D90 103%-108%; rectal sparing D2cc 40%-72% of prescription, V75 ≤ 1.4 cc.
- One late grade 3 proctitis/urethral stricture occurred in a fractionated high-dose case; none ≥ grade 3 GU/GI in the single-fraction cohort.

**Dose constraints / prescription:**
- Pelvic CRT: 45-50.4 Gy in 25-28 fractions
- Prostate V100 goal: ≥95% (achieved 94.6%-97.7%)
- Prostate D90: 103%-108%
- Rectum V75% goal: <1 cc (V75 ≤ 1.4 cc achieved)
- Urethra D10 goal: ≤115%
- Rectal D2cc: 40%-72% of prescription dose

**Trial endpoints / outcomes:**
- No locoregional failures at median 40 months
- Two rectal cancers achieved pathologic complete response; four remained recurrence-free
- All prostate cancers biochemically controlled
- Two rectal cancers developed distant metastasis at ~2-3 years
- Toxicity: 1 late grade 3 proctitis/urethral stricture (fractionated high-dose case); no ≥grade 3 GU/GI in single-fraction cohort

**Key numbers:**
- n=6 men (age 60-78)
- Median follow-up: 40 months (range 30-110)
- Database period: 2011-2023
- Toxicity grading: CTCAE v5.0

**See also:**
- → [#kb:gi:rectal:opera-trial-sun-myint](#kb:gi:rectal:opera-trial-sun-myint) (`opera-trial-sun-myint.md`)
- → [#kb:gi:rectal:bmj-watchful-waiting-rectal-2025](#kb:gi:rectal:bmj-watchful-waiting-rectal-2025) (`bmj-watchful-waiting-rectal-2025.md`)

---

### <a id="gi-anal"></a> Anal Canal BT (1 files)

<a id="kb:gi:anal:gec-estro-anal-bt-2018"></a>

#### Brachytherapy boost in anal canal cancer - A GEC ESTRO PDR task force meta-analysis (2018)

📄 [gec-estro-anal-bt-2018.md](sources/05_gi/raw/gec-estro-anal-bt-2018.md)

**Journal:** Radiotherapy and Oncology  
**DOI:** 10.1016/j.ctro.2023.100589  
**PMID:** 36785565 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/36785565/))  

**Topics:** `anal`, `GEC-ESTRO`, `PDR-task-force`, `meta-analysis`, `n=481`, `5y-OS-82%-both-arms`

**Key facts:**
- 9 retrospective studies with 481 patients total: 219 HDR and 262 PDR brachytherapy cases were included.
- Cumulative proportion of stage T3-T4 was lower in HDR group (0.15, 95% CI 0.07-0.29) vs LDR/PDR group (0.27, 95% CI 0.09-0.57), p < 0.001.
- Lower BT doses (EQD2) were given in HDR group (11.9 Gy, 95% CI 8.2-15.5) vs PDR group (19.5 Gy, 95% CI 15.0-24.0), p < 0.001.
- 5-year overall survival pooled effect: 0.82 (95% CI 0.70-0.94) for HDR and 0.82 (95% CI 0.73-0.91) for PDR, p > 0.99.
- 5-year local control: 0.86 (95% CI 0.81-0.91) HDR vs 0.83 (95% CI 0.77-0.89) PDR, p = 0.62.
- Cumulative toxicity-related colostomy proportion: 0.04 (95% CI 0.02-0.09) HDR vs 0.03 (95% CI 0.02-0.07) PDR, p = 0.85.

**Dose constraints / prescription:**
- HDR BT dose (EQD2): 11.9 Gy (95% CI 8.2-15.5)
- PDR BT dose (EQD2): 19.5 Gy (95% CI 15.0-24.0)

**Trial endpoints / outcomes:**
- 5-year overall survival (HDR vs PDR): 0.82 vs 0.82, p > 0.99
- 5-year local control (HDR vs PDR): 0.86 vs 0.83, p = 0.62
- Toxicity-related colostomy rate (HDR vs PDR): 0.04 vs 0.03, p = 0.85

**Key numbers:**
- n=481 patients (HDR 219, PDR 262)
- 9 retrospective studies

**See also:**
- → [#kb:gi:rectal:rectal-recurrence-hdr](#kb:gi:rectal:rectal-recurrence-hdr) (`rectal-recurrence-hdr.md`)

---

### <a id="gi-pancreatic"></a> Pancreatic BT (Permanent I-125) (5 files)

<a id="kb:gi:pancreatic:3d-template-i125-pancreatic-2018"></a>

#### 05_gi — Gastrointestinal Brachytherapy (15 files)

📄 [3d-template-i125-pancreatic-2018.md](sources/05_gi/raw/3d-template-i125-pancreatic-2018.md)


**Topics:** `pancreatic`, `I-125`, `3D-printed-template`, `n=25`, `V100-91.05%-Group-A-vs-72.91%-Group-B`

**See also:**
- → [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](#kb:gi:pancreatic:i125-pancreatic-guideline-2023) (`i125-pancreatic-guideline-2023.md`)
- → [#kb:gi:pancreatic:cstro-pancreatic-i125-2017](#kb:gi:pancreatic:cstro-pancreatic-i125-2017) (`cstro-pancreatic-i125-2017.md`)
- → [#kb:gi:pancreatic:pancreatic-i125-clinical](#kb:gi:pancreatic:pancreatic-i125-clinical) (`pancreatic-i125-clinical.md`)

---

<a id="kb:gi:pancreatic:cstro-pancreatic-i125-2017"></a>

#### Chinese CSTRO/CSCO I-125 Pancreatic Cancer Consensus (2017)

📄 [cstro-pancreatic-i125-2017.md](sources/05_gi/raw/cstro-pancreatic-i125-2017.md)

**Journal:** Chinese Journal of Radiation Oncology  

**Topics:** `pancreatic`, `I-125`, `CSTRO-CSCO`, `Chinese-consensus`

**Key facts:**
- Listed key topics: I-125 seed implantation techniques for pancreatic cancer, dose prescription and planning protocols, patient selection criteria, combination with chemotherapy.

**See also:**
- → [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](#kb:gi:pancreatic:i125-pancreatic-guideline-2023) (`i125-pancreatic-guideline-2023.md`)
- → [#kb:frm:chinese:csco-bt-chinese](#kb:frm:chinese:csco-bt-chinese) (`csco-bt-chinese.md`)

---

<a id="kb:gi:pancreatic:i125-pancreatic-guideline-2023"></a>

#### Guidelines for permanent iodine-125 seed interstitial brachytherapy for pancreatic cancer (2023 edition) (2024)

📄 [i125-pancreatic-guideline-2023.md](sources/05_gi/raw/i125-pancreatic-guideline-2023.md)

**Full text also at:** [i125-pancreatic-guideline-2023.txt](sources/05_gi/raw/i125-pancreatic-guideline-2023.txt)

**Journal:** Journal of Cancer Research and Therapeutics
**DOI:** 10.4103/jcrt.jcrt_2368_23

**Topics:** `pancreatic`, `I-125`, `Chinese-expert-consensus`, `prescribed-110-130-Gy`, `I-125-0.3-0.8-mCi`, `PTV-GTV+1cm`

**Key facts:**
- Approximately 60% of patients with pancreatic cancer have distant metastases at the time of diagnosis.
- I-125 seeds: 4.5 mm × 0.8 mm nickel titanium alloy envelope, half-life 59.6 days, average energy 35.5 KeV (gamma) + 27.4/31.4 KeV (X-rays).
- Absolute contraindications: cachexia and severe organ dysfunction, severe coagulation dysfunction (platelet <50×10⁹/L), expected life span <3 months, ECOG ≥3.
- Relative contraindications: concurrent distant metastasis, obstructive jaundice (drain first), tumor diameter >7 cm.
- CT slice thickness 0.5 mm; I-125 seed activity 0.3-0.8 mCi; PTV = GTV + 1 cm margin; prescribed dose 110-130 Gy.
- Needle: 18-gauge puncture needle; fluorouracil 0.05 ml bolus per seed to prevent tumor seeding.

**Dose constraints / prescription:**
- Prescribed dose: 110-130 Gy
- I-125 seed activity: 0.3-0.8 mCi
- PTV margin: GTV + 1 cm
- Platelet threshold (absolute contraindication): <50×10⁹/L
- Tumor diameter threshold (relative contraindication): >7 cm

**Key numbers:**
- I-125 seed dimensions: 4.5 mm × 0.8 mm
- Half-life: 59.6 days
- Average energy: 35.5 KeV gamma + 27.4/31.4 KeV X-rays
- CT slice thickness: 0.5 mm
- Fluorouracil bolus: 0.05 ml per seed
- Proportion with distant metastases at diagnosis: ~60%

**See also:**
- → [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](#kb:gi:pancreatic:3d-template-i125-pancreatic-2018) (`3d-template-i125-pancreatic-2018.md`)
- → [#kb:gi:pancreatic:cstro-pancreatic-i125-2017](#kb:gi:pancreatic:cstro-pancreatic-i125-2017) (`cstro-pancreatic-i125-2017.md`)
- → [#kb:gi:pancreatic:pancreatic-i125-clinical](#kb:gi:pancreatic:pancreatic-i125-clinical) (`pancreatic-i125-clinical.md`)
- → [#kb:gi:pancreatic:pancreatic-i125-gemcitabine](#kb:gi:pancreatic:pancreatic-i125-gemcitabine) (`pancreatic-i125-gemcitabine.md`)

---

<a id="kb:gi:pancreatic:pancreatic-i125-clinical"></a>

#### Research progress of iodine-125 radioactive seeds implantation for the treatment of pancreatic cancer (2018)

📄 [pancreatic-i125-clinical.md](sources/05_gi/raw/pancreatic-i125-clinical.md)

**Journal:** Various  
**PMID:** 41633652 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41633652/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/41633652/  

**Topics:** `pancreatic`, `I-125`, `review`

**See also:**
- → [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](#kb:gi:pancreatic:i125-pancreatic-guideline-2023) (`i125-pancreatic-guideline-2023.md`)
- → [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](#kb:gi:pancreatic:3d-template-i125-pancreatic-2018) (`3d-template-i125-pancreatic-2018.md`)

---

<a id="kb:gi:pancreatic:pancreatic-i125-gemcitabine"></a>

#### Sequential PTCD and biliary seed stent combined with targeted-immunotherapy for advanced pancreatic cancer with malignant obstructive jaundice (2019)

📄 [pancreatic-i125-gemcitabine.md](sources/05_gi/raw/pancreatic-i125-gemcitabine.md)

**Journal:** Various  
**PMID:** 40904499 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/40904499/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/40904499/  

**Topics:** `pancreatic`, `I-125`, `case-report`, `PTCD`, `gemcitabine`, `n=1`

**Key facts:**
- 54-year-old female with advanced pancreatic head cancer and MOJ, ECOG 1, type 2 diabetes; ERCP with 8.5 Fr plastic stent failed due to occlusion after 20 days.
- Emergency PTCD followed by biliary metal stent (8 mm × 80 mm) and iodine-125 seed implantation reduced TBIL from 116.9 to 45.6 μmol/L within 7 days.
- Subsequent tomotherapy delivered 66 Gy to GTV with personalized regimen of S1 (tegafur, 20 mg/day), nimotuzumab, and pembrolizumab after gemcitabine + nab-paclitaxel intolerance.
- Achieved 78% reduction in CA19-9 and sustained biliary patency.
- At one-year follow-up: TBIL 18.2 μmol/L, DBIL 9.8 μmol/L, Karnofsky score 90.

**Dose constraints / prescription:**
- Tomotherapy to GTV: 66 Gy
- S1 (tegafur) dose: 20 mg/day

**Key numbers:**
- Age: 54 years; Height 160 cm; Weight 55 kg; BMI 21.5 kg/m²; ECOG 1
- Plastic stent size: 8.5 Fr
- Metal stent: 8 mm × 80 mm
- TBIL reduction: 116.9 → 45.6 μmol/L in 7 days
- CA19-9 reduction: 78%
- Follow-up: 1 year (TBIL 18.2, DBIL 9.8, KPS 90)

**See also:**
- → [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](#kb:gi:pancreatic:i125-pancreatic-guideline-2023) (`i125-pancreatic-guideline-2023.md`)
- → [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](#kb:gi:pancreatic:3d-template-i125-pancreatic-2018) (`3d-template-i125-pancreatic-2018.md`)

---

### <a id="gi-biliary"></a> Biliary Tract BT (1 files)

<a id="kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd"></a>

#### A systematic review of intraluminal high dose rate brachytherapy in the management of malignant biliary tract obstruction and cholangiocarcinoma (2016)

📄 [bileduct-cholangiocarcinoma-ptbd.md](sources/05_gi/raw/bileduct-cholangiocarcinoma-ptbd.md)

**Journal:** Brachytherapy  
**PMID:** 34695521 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/34695521/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/34695521/  

**Topics:** `biliary`, `cholangiocarcinoma`, `ILBT`, `systematic-review`, `n=17-studies`, `stent-patency-10-months`

**Key facts:**
- 17 studies met inclusion criteria; significant heterogeneity observed in treatment regimens combining surgery, EBRT, and/or intra-arterial and IV chemotherapy with ILBT.
- Stent patency: 10 months with ILBT compared to 4-6 months without ILBT.
- Weighted mean overall survival: 11.8 months for ILBT alone vs 10.5 months for ILBT plus EBRT ± chemotherapy.
- Low complication rates and toxicity related to ILBT were reported.

**Trial endpoints / outcomes:**
- Stent patency: 10 months with ILBT vs 4-6 months without
- Weighted mean OS: 11.8 months (ILBT alone) vs 10.5 months (ILBT+EBRT ± chemo)
- Local control and complete/partial response rates: trend toward improvement with ILBT

**Key numbers:**
- 17 studies included
- Studies reporting ≥10 patients included

**See also:**
- → [#kb:gi:pancreatic:pancreatic-i125-gemcitabine](#kb:gi:pancreatic:pancreatic-i125-gemcitabine) (`pancreatic-i125-gemcitabine.md`)

---

### <a id="gi-gastric"></a> Gastric BT (1 files)

<a id="kb:gi:gastric:gastric-bt"></a>

#### Gastric Brachytherapy Review (2020)

📄 [gastric-bt.md](sources/05_gi/raw/gastric-bt.md)

**Journal:** Various  
**URL:** https://pubmed.ncbi.nlm.nih.gov/?term=Gastric+Brachytherapy+Review  

**Topics:** `gastric`, `BT-review`

**Key facts:**
- Manual PubMed search is recommended for verification.

**See also:**
- → [#kb:gi:esophageal:abs-esophageal-2014](#kb:gi:esophageal:abs-esophageal-2014) (`abs-esophageal-2014.md`)

---

## <a id="oth"></a> Other Sites BT (13 files)

**Subtitle:** lung, brain, eye, sarcoma, pediatric, vascular  
**Master list:** [`sources/06_other_sites/INDEX.md`](sources/06_other_sites/INDEX.md)

### <a id="oth-lung"></a> Lung BT (3 files)

<a id="kb:oth:lung:brachy-trial-lung"></a>

#### BRACHY: A Randomized Trial to Evaluate Symptom Improvement in Advanced Non-Small Cell Lung Cancer Treated With External Beam Radiation With or Without High-Dose-Rate Intraluminal Brachytherapy (2015)

📄 [brachy-trial-lung.md](sources/06_other_sites/raw/brachy-trial-lung.md)

**Journal:** Various  
**PMID:** 36610615 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/36610615/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/36610615/  

**Topics:** `lung`, `BRACHY-trial`, `NSCLC`, `endobronchial`, `HDRIB`, `n=134`

**Key facts:**
- Patients with symptomatic stage III or IV NSCLC with endobronchial disease were randomized to EBRT (20 Gy in 5 daily fractions over 1 week or 30 Gy in 10 daily fractions over 2 weeks) or the same EBRT plus HDRIB (14 Gy in 2 fractions separated by 1 week).
- 134 patients were randomized over 4.5 years (67 to each arm); study closed early owing to slow accrual.
- At 6 weeks, 19 patients (28.4%) in the EBRT arm and 20 patients (29.9%) in the EBRT plus HDRIB arm experienced improvement in lung cancer symptoms (P = .84).
- Between-group differences in mean change scores (0.3-0.5 standard deviations) in favor of EBRT plus HDRIB were observed, but only hemoptysis was significantly improved (P = .03).
- Planned sample size was 250 patients based on detection of symptomatic improvement from 40% to 60% with α of .05 and 80% power.

**Dose constraints / prescription:**
- EBRT: 20 Gy in 5 fractions over 1 week or 30 Gy in 10 fractions over 2 weeks
- HDRIB: 14 Gy in 2 fractions separated by 1 week

**Trial endpoints / outcomes:**
- Symptomatic improvement on Lung Cancer Symptom Scale (LCSS) at 6 weeks
- Symptom-progression-free survival
- Overall survival
- Toxicity (Grade 3/4)

**Key numbers:**
- n=134 randomized (67 per arm)
- Mean age 69.8 years
- 67% had metastatic disease
- Accrual period: 4.5 years

**See also:**
- → [#kb:oth:lung:endobronchial-bt-consensus](#kb:oth:lung:endobronchial-bt-consensus) (`endobronchial-bt-consensus.md`)
- → [#kb:oth:lung:ct-guided-i125-early-lung](#kb:oth:lung:ct-guided-i125-early-lung) (`ct-guided-i125-early-lung-cancer.md`)

---

<a id="kb:oth:lung:ct-guided-i125-early-lung"></a>

#### CT-guided percutaneous implantation of 125I particles in treatment of early lung cancer (2020)

📄 [ct-guided-i125-early-lung-cancer.md](sources/06_other_sites/raw/ct-guided-i125-early-lung-cancer.md)

**Journal:** Journal of Thoracic Disease  
**DOI:** 10.21037/jtd-20-2666  

**Topics:** `lung`, `I-125`, `CT-guided`, `early-stage`, `n=6`

**Key facts:**
- Six patients with early lung cancer (stage I-II): 4 squamous cell carcinoma, 1 adenocarcinoma, 1 small cell lung cancer; TPS software used for dose calculation.
- 20-55 particles implanted per site with particle spacing 0.5-1.0 cm.
- Response at 1 month: 2 CR, 4 PR; 6 months: 3 CR, 2 PR; 12 months: 3 CR, 1 PR, 1 PD; 24 months: all CR.
- No serious complications reported.
- 125I radioactive particle implantation is safe, reliable and effective for early lung cancer.

**Trial endpoints / outcomes:**
- Tumor response (CR/PR/PD)

**Key numbers:**
- n=6 patients
- 20-55 particles per site
- Particle spacing 0.5-1.0 cm
- Follow-up to 24 months

**See also:**
- → [#kb:oth:lung:brachy-trial-lung](#kb:oth:lung:brachy-trial-lung) (`brachy-trial-lung.md`)
- → [#kb:oth:lung:endobronchial-bt-consensus](#kb:oth:lung:endobronchial-bt-consensus) (`endobronchial-bt-consensus.md`)
- → [#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis](#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis) (`ct-guided-i125-spinal-metastasis.md`)

---

<a id="kb:oth:lung:endobronchial-bt-consensus"></a>

#### Endobronchial Brachytherapy Consensus (2020)

📄 [endobronchial-bt-consensus.md](sources/06_other_sites/raw/endobronchial-bt-consensus.md)

**Journal:** Various  
**URL:** https://pubmed.ncbi.nlm.nih.gov/?term=Endobronchial+Brachytherapy+Consensus  

**Topics:** `lung`, `endobronchial`, `consensus`

**See also:**
- → [#kb:oth:lung:brachy-trial-lung](#kb:oth:lung:brachy-trial-lung) (`brachy-trial-lung.md`)
- → [#kb:oth:lung:ct-guided-i125-early-lung](#kb:oth:lung:ct-guided-i125-early-lung) (`ct-guided-i125-early-lung-cancer.md`)

---

### <a id="oth-brain_spine"></a> Brain & Spine BT (3 files)

<a id="kb:oth:brain_spine:ct-guided-i125-spinal-metastasis"></a>

#### Clinical efficacy of computed tomography-guided iodine-125 seed implantation therapy in patients with advanced spinal metastatic tumors (2016)

📄 [ct-guided-i125-spinal-metastasis.md](sources/06_other_sites/raw/ct-guided-i125-spinal-metastasis.md)

**Journal:** OncoTargets and Therapy  
**DOI:** 10.2147/OTT.S95410  

**Topics:** `spine`, `metastasis`, `I-125`, `n=20`, `MPD-90-130-Gy`, `pain-relief-95%`

**Key facts:**
- 20 cases of spinal metastatic tumors, median 19 seeds implanted, MPD 90-130 Gy.
- Pain relief rate: 95%; median control time: 12.5 months.
- 3-, 6-, 12-month local control rates: 100%, 95%, 60%; median survival: 16 months.
- No major complications and no seed migration reported.

**Dose constraints / prescription:**
- MPD (matched peripheral dose) 90-130 Gy
- Median 19 seeds implanted

**Trial endpoints / outcomes:**
- Pain relief rate
- Local control rate
- Median survival

**Key numbers:**
- n=20 cases
- Pain relief: 95%
- Median control time: 12.5 months
- Median survival: 16 months
- 3/6/12-month LC: 100%/95%/60%

**See also:**
- → [#kb:oth:lung:ct-guided-i125-early-lung](#kb:oth:lung:ct-guided-i125-early-lung) (`ct-guided-i125-early-lung-cancer.md`)
- → [#kb:oth:malignant_general:i125-deep-hyperthermia-malignant](#kb:oth:malignant_general:i125-deep-hyperthermia-malignant) (`i125-deep-hyperthermia-malignant.md`)
- → [#kb:oth:brain_spine:gammatile-brain](#kb:oth:brain_spine:gammatile-brain) (`gammatile-brain.md`)

---

<a id="kb:oth:brain_spine:gammatile-brain"></a>

#### Novel use of 3D printing for preoperative dose estimation in the first case of GammaTile spine implantation (2020)

📄 [gammatile-brain.md](sources/06_other_sites/raw/gammatile-brain.md)

**Journal:** Neurosurgery  
**PMID:** 40992982 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/40992982/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/40992982/  

**Topics:** `brain`, `spine`, `GammaTile`, `Cs-131`, `3D-printing-preop`, `rectosigmoid-recurrence`

**Key facts:**
- First use of Cs-131 LDR GammaTile therapy outside of the brain for a patient with painful, recurrent rectosigmoid adenocarcinoma in the sacrum with two prior EBRT courses.
- Personalized 3D-printed spine model created using Stratasys J5 MediJet Printer from segmented MRI, differentiating uninvolved bone, tumor, thecal sac, and nerve roots.
- For the thecal sac (relevant OAR), D0.035cc was calculated accurately within 8.0% for physical dose and within 10.0% for BED between the 3D-printed model estimate and patient's postimplant dosimetry.
- 3D printing can be used preoperatively to estimate dose to critical OARs for Cs-131 LDR spine implantation, especially valuable in reirradiation contexts.

**Dose constraints / prescription:**
- D0.035cc (thecal sac max dose) calculated within 8.0% (physical) and 10.0% (BED) accuracy

**Key numbers:**
- PMID 40992982
- Accuracy within 8.0% (physical dose) and 10.0% (BED)

**See also:**
- → [#kb:oth:brain_spine:gliasite-brain](#kb:oth:brain_spine:gliasite-brain) (`gliasite-brain.md`)
- → [#kb:pros:penile:gec-estro-penile-2018](#kb:pros:penile:gec-estro-penile-2018) (`gec-estro-penile-2018.md`)
- → [#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis](#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis) (`ct-guided-i125-spinal-metastasis.md`)

---

<a id="kb:oth:brain_spine:gliasite-brain"></a>

#### Outcome of Adult Brain Tumor Consortium (ABTC) prospective dose-finding trials of I-125 balloon brachytherapy in high-grade gliomas (2006)

📄 [gliasite-brain.md](sources/06_other_sites/raw/gliasite-brain.md)

**Journal:** IJROBP  
**PMID:** 27695605 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/27695605/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/27695605/  

**Topics:** `brain`, `glioma`, `HGG`, `GliaSite`, `I-125-balloon`, `ABTC`, `n=10-NEW-GBM`

**Key facts:**
- GliaSite balloon brachytherapy (GSBT) uses a balloon placed in the resection cavity and later filled through a subcutaneous port with liquid I-125 Iotrex, providing radiation doses that diminish uniformly with distance from the balloon surface.
- Ten NEW-GBM patients had the balloon placed; 2/10 reached the 90-day timepoint; imaging progression occurred before 90-day evaluation in 7/12 treated patients.
- Trials were closed as too few patients were assessable to allow dose escalation; no dose-limiting toxicities (DLTs) were observed.
- Median survival from treatment was 15.3 months (95% CI 7.1-23.6) for NEW-GBM and 12.8 months (95% CI 4.2-20.9) for REC-HGG.
- Trials failed to determine MTD as early imaging changes presumed to be progression were common and interfered with assessment of treatment-related toxicity.

**Trial endpoints / outcomes:**
- Maximum tolerated dose (MTD) determination
- Dose-limiting toxicities (DLTs)
- Median survival from treatment

**Key numbers:**
- n=10 NEW-GBM (2/10 evaluable at 90 days)
- n=5 REC-HGG enrolled (2 evaluable)
- Median survival: 15.3 months (NEW-GBM), 12.8 months (REC-HGG)
- PMID 27695605

**See also:**
- → [#kb:oth:brain_spine:gammatile-brain](#kb:oth:brain_spine:gammatile-brain) (`gammatile-brain.md`)

---

### <a id="oth-eye"></a> Eye / Uveal BT (2 files)

<a id="kb:oth:eye:aapm-tg-129-uveal-melanoma"></a>

#### 06_other_sites — Other Sites Brachytherapy (13 files)

📄 [aapm-tg-129-uveal-melanoma.md](sources/06_other_sites/raw/aapm-tg-129-uveal-melanoma.md)


**Topics:** `eye`, `uveal-melanoma`, `plaque-dosimetry`, `AAPM-TG-129`

**See also:**
- → [#kb:oth:eye:coms-trial-medium](#kb:oth:eye:coms-trial-medium) (`coms-trial-medium.md`)

---

<a id="kb:oth:eye:coms-trial-medium"></a>

#### The COMS Randomized Trial of Iodine 125 Brachytherapy for Choroidal Melanoma (2006)

📄 [coms-trial-medium.md](sources/06_other_sites/raw/coms-trial-medium.md)

**Journal:** Arch Ophthalmol  
**DOI:** 10.1001/archopht.124.12.1684  
**PMID:** 32200815 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/32200815/))  

**Topics:** `eye`, `uveal-melanoma`, `COMS-trial`, `I-125`, `choroidal`, `5y-enucleation-12.5%`

**Key facts:**
- Tumors measured 2.5 to 10.0 mm in apical height and no more than 16.0 mm in longest basal dimension; patients enrolled between February 1987 and July 1998.
- 638 of 650 patients randomized to brachytherapy were followed for 1 year or longer; 411 followed for at least 5 years.
- Kaplan-Meier estimate of enucleation by 5 years was 12.5% (95% CI, 10.0%-15.6%); risk of treatment failure was 10.3% (95% CI, 8.0%-13.2%).
- Risk factors for enucleation: greater tumor thickness, closer proximity of posterior tumor border to foveal avascular zone, and poorer baseline visual acuity.
- Local treatment failure was associated weakly with reduced survival (adjusted risk ratio 1.5; P = 0.08).
- COMS randomized trial documented no clinically or statistically significant difference in survival for patients assigned to enucleation versus brachytherapy.

**Trial endpoints / outcomes:**
- Enucleation rate
- Local treatment failure (tumor growth, recurrence, or extrascleral extension)
- Survival

**Key numbers:**
- n=638 followed ≥1 year, n=411 followed ≥5 years
- 69 eyes enucleated within 5 years
- 57 eyes with treatment failure
- 5-year enucleation rate: 12.5%
- Treatment failure rate: 10.3%

**See also:**
- → [#kb:oth:eye:aapm-tg-129-uveal-melanoma](#kb:oth:eye:aapm-tg-129-uveal-melanoma) (`aapm-tg-129-uveal-melanoma.md`)

---

### <a id="oth-sarcoma"></a> Soft Tissue Sarcoma BT (1 files)

<a id="kb:oth:sarcoma:abs-sarcoma-bt"></a>

#### Training-oriented framework for brachytherapy treatment planning in soft tissue sarcoma (2001)

📄 [abs-sarcoma-bt.md](sources/06_other_sites/raw/abs-sarcoma-bt.md)

**Journal:** Brachytherapy  
**PMID:** 42128739 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42128739/))  
**URL:** https://pubmed.ncbi.nlm.nih.gov/42128739/  

**Topics:** `sarcoma`, `soft-tissue`, `ABS-GEC-ESTRO`, `consensus`

**Key facts:**
- Brachytherapy remains an important component of postoperative management for soft tissue sarcoma (STS).
- Recent consensus guidelines from ABS and GEC-ESTRO define standardized objectives for brachytherapy education.
- Technical review operationalizes competency domains of brachytherapy treatment planning, delivery, and quality assurance with specific focus on interstitial STS brachytherapy.
- Covers CT-based simulation, catheter reconstruction, target/OAR delineation, dwell-time optimization, and quality assurance processes.

**Key numbers:**
- PMID 42128739

**See also:**
- → [#kb:pros:penile:nature-bt-penile-organ-preservation](#kb:pros:penile:nature-bt-penile-organ-preservation) (`nature-bt-penile-organ-preservation-2015.md`)
- → [#kb:pros:penile:gec-estro-penile-2018](#kb:pros:penile:gec-estro-penile-2018) (`gec-estro-penile-2018.md`)

---

### <a id="oth-pediatric"></a> Pediatric BT (1 files)

<a id="kb:oth:pediatric:pediatric-rhabdomyosarcoma-bt"></a>

#### Pediatric Rhabdomyosarcoma Brachytherapy (2020)

📄 [pediatric-rhabdomyosarcoma-bt.md](sources/06_other_sites/raw/pediatric-rhabdomyosarcoma-bt.md)

**Journal:** Various  
**URL:** https://pubmed.ncbi.nlm.nih.gov/?term=Pediatric+Rhabdomyosarcoma+Brachytherapy  

**Topics:** `pediatric`, `rhabdomyosarcoma`

**See also:**
- → [#kb:oth:sarcoma:abs-sarcoma-bt](#kb:oth:sarcoma:abs-sarcoma-bt) (`abs-sarcoma-bt.md`)

---

### <a id="oth-vascular"></a> Vascular BT (2 files)

<a id="kb:oth:vascular:cardiac-vascular-review"></a>

#### Cardiac Vascular Brachytherapy Reappraisal (2020)

📄 [cardiac-vascular-review.md](sources/06_other_sites/raw/cardiac-vascular-review.md)

**Journal:** Various  
**URL:** https://pubmed.ncbi.nlm.nih.gov/?term=Cardiac+Vascular+Brachytherapy+Reappraisal  

**Topics:** `vascular`, `cardiac`, `BT-reappraisal`

**See also:**
- → [#kb:oth:vascular:vascular-bt-sr90](#kb:oth:vascular:vascular-bt-sr90) (`vascular-bt-sr90.md`)

---

<a id="kb:oth:vascular:vascular-bt-sr90"></a>

#### Intravascular Brachytherapy for In-Stent Restenosis in Patients With Chronic Kidney Disease (2002)

📄 [vascular-bt-sr90.md](sources/06_other_sites/raw/vascular-bt-sr90.md)

**Journal:** Various  
**DOI:** 10.1016/j.jscai.2025.103877  
**PMID:** 41268073 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41268073/))  

**Topics:** `vascular`, `ISR`, `Sr-90`, `CKD`, `n=227`

**Key facts:**
- Retrospective analysis of 227 patients (54 CKD and 173 non-CKD) who underwent vascular brachytherapy for coronary ISR between June 2016 and January 2024 at Houston Methodist Hospital.
- CKD defined as estimated glomerular filtration rate <60 mL/min/1.73 m² for at least 3 months.
- Significantly higher prevalence of diabetes in CKD group (83.3% vs 57.8%; P = .001).
- 1-year MACE rates were significantly higher in CKD vs non-CKD patients (63.0% vs 32.9%; P = .0003), primarily driven by higher TLR rates (31.5% vs 17.9%; P = .038).
- Bleeding complications occurred exclusively in CKD group (5.6% vs 0%; P = .013).
- In multivariable analysis, male sex was associated with significantly lower risk of TLR in CKD patients (HR 0.15; 95% CI 0.04-0.64; P = .010).

**Trial endpoints / outcomes:**
- Target lesion revascularization (TLR)
- Major adverse cardiovascular events (MACE)
- All-cause mortality at 1 year

**Key numbers:**
- n=227 patients (54 CKD, 173 non-CKD)
- Time period: June 2016 - January 2024
- 1-year MACE: 63.0% (CKD) vs 32.9% (non-CKD)
- 1-year TLR: 31.5% (CKD) vs 17.9% (non-CKD)
- Diabetes prevalence: 83.3% (CKD) vs 57.8% (non-CKD)
- Bleeding complications: 5.6% (CKD) vs 0% (non-CKD)
- PMID 41268073

**See also:**
- → [#kb:oth:vascular:cardiac-vascular-review](#kb:oth:vascular:cardiac-vascular-review) (`cardiac-vascular-review.md`)

---

### <a id="oth-malignant_general"></a> Malignant Tumors (General — I-125 + Hyperthermia) (1 files)

<a id="kb:oth:malignant_general:i125-deep-hyperthermia-malignant"></a>

#### Clinical efficacy of iodine-125 radioactive particle implantation with deep hyperthermia in malignant tumor treatment (2024)

📄 [i125-deep-hyperthermia-malignant.md](sources/06_other_sites/raw/i125-deep-hyperthermia-malignant.md)

**Journal:** Journal of Contemporary Brachytherapy  
**DOI:** 10.5114/jcb.2024.141407  

**Topics:** `malignant`, `I-125`, `deep-hyperthermia`, `n=60`, `ORR-73.33%`

**Key facts:**
- 60 patients with malignant tumors underwent CT-guided I-125 implantation followed by deep hyperthermia for 3 days post-surgery.
- Overall response rate (ORR): 73.33%; disease control rate (DCR): 81.67%.
- Pain relief: 81.67% with improved quality of life; no adverse reactions ≥ level 2.
- I-125 implantation with deep hyperthermia is an effective combination therapy for malignant tumors.

**Trial endpoints / outcomes:**
- Overall response rate (ORR)
- Disease control rate (DCR)
- Pain relief rate
- Quality of life improvement

**Key numbers:**
- n=60 patients
- ORR: 73.33%
- DCR: 81.67%
- Pain relief: 81.67%
- Hyperthermia: 3 days post-surgery

**See also:**
- → [#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis](#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis) (`ct-guided-i125-spinal-metastasis.md`)
- → [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](#kb:gi:pancreatic:i125-pancreatic-guideline-2023) (`i125-pancreatic-guideline-2023.md`)

---

## <a id="phys"></a> Physics & Dosimetry (13 files)

**Subtitle:** TG-43, ICRU, IAEA, planning, 3D printing  
**Master list:** [`sources/07_physics/INDEX.md`](sources/07_physics/INDEX.md)

### <a id="phys-tg43"></a> AAPM TG-43 Formalism (3 files)

<a id="kb:phys:tg43:aapm-tg-43-nath-1995"></a>

#### Interstitial brachytherapy dosimetry update (1995)

📄 [aapm-tg-43-nath-1995.md](sources/07_physics/raw/aapm-tg-43-nath-1995.md)

**Journal:** Medical Physics  
**DOI:** 10.1118/1.597458  
**PMID:** 16614084 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/16614084/))  

**Topics:** `TG-43`, `interstitial`, `1995-original`

**Key facts:**
- In March 2004, the AAPM published an update to AAPM TG-43, which was initially published in 1995.
- The update was pursued primarily due to the marked increase in permanent implantation of low-energy photon-emitting brachytherapy sources in the US.
- Impact of the update on administered dose was assessed for the model 200 103Pd brachytherapy source.

**See also:**
- → [#kb:phys:tg43:aapm-tg-43u1-rivard-2004](#kb:phys:tg43:aapm-tg-43u1-rivard-2004) (`aapm-tg-43u1-rivard-2004.md`)
- → [#kb:phys:tg43:aapm-tg-43u1s1-perez-2012](#kb:phys:tg43:aapm-tg-43u1s1-perez-2012) (`aapm-tg-43u1s1-perez-2012.md`)

---

<a id="kb:phys:tg43:aapm-tg-43u1-rivard-2004"></a>

#### Update of AAPM Task Group No. 43 Report: A revised AAPM protocol for brachytherapy dose calculations (2004)

📄 [aapm-tg-43u1-rivard-2004.md](sources/07_physics/raw/aapm-tg-43u1-rivard-2004.md)

**Journal:** Medical Physics  
**DOI:** 10.1118/1.1646040  
**PMID:** 15070264 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/15070264/))  

**Topics:** `TG-43U1`, `update`, `I-125`, `Pd-103`, `air-kerma-strength`

**Key facts:**
- TG-43U1 includes: (a) revised definition of air-kerma strength; (b) elimination of apparent activity; (c) elimination of anisotropy constant in favor of distance-dependent 1D anisotropy function; (d) guidance on extrapolating tabulated TG-43 parameters; (e) corrections for inconsistencies in original protocol.
- Consensus datasets were included for 125I sources (Amersham 6702/6711, Best 2301, NASI MED3631-A/M, Bebig/Theragenics I25.S06, Imagyn IS-12501) and 103Pd sources (Theragenics 200 and NASI MED3633) as of July 15, 2001.
- NIST introduced a new primary standard of air-kerma strength motivating the update.
- Adoption of the revised protocol may result in changes to patient dose calculations, which should be carefully evaluated with the radiation oncologist before implementation.

**See also:**
- → [#kb:phys:tg43:aapm-tg-43-nath-1995](#kb:phys:tg43:aapm-tg-43-nath-1995) (`aapm-tg-43-nath-1995.md`)
- → [#kb:phys:tg43:aapm-tg-43u1s1-perez-2012](#kb:phys:tg43:aapm-tg-43u1s1-perez-2012) (`aapm-tg-43u1s1-perez-2012.md`)
- → [#kb:phys:aapm_other:aapm-tg-229-mbdca](#kb:phys:aapm_other:aapm-tg-229-mbdca) (`aapm-tg-229-mbdca.md`)

---

<a id="kb:phys:tg43:aapm-tg-43u1s1-perez-2012"></a>

#### Dosimetry parameters calculation of two commercial iodine brachytherapy sources using SMARTEPANTS with EPDL97 library (2012)

📄 [aapm-tg-43u1s1-perez-2012.md](sources/07_physics/raw/aapm-tg-43u1s1-perez-2012.md)

**Journal:** Medical Physics  
**DOI:** 10.1118/1.3694668  
**PMID:** 23361283 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/23361283/))  

**Topics:** `TG-43U1S1`, `I-125`, `Best-2301`, `Intersource`, `SMARTEPANTS`

**Key facts:**
- SMARTEPANTS is a discrete ordinates SN Boltzmann/Spencer-Lewis solver originally developed 1988-1993 by William Filippone; it was adapted to use the EPDL97 photon cross-section library for intravascular brachytherapy 125I simulations.
- Dosimetry parameters for Best Model 2301 and Intersource 125I sources were computed and compared with AAPM TG-43 and other reports.
- Computation time for producing TG-43 parameters was about 29.4 min with g=20, L=7 and S=16.

**Key numbers:**
- Computation time: ~29.4 min
- Energy groups: g=20
- Legendre moments: L=7
- Discrete ordinate order: S=16

**See also:**
- → [#kb:phys:tg43:aapm-tg-43u1-rivard-2004](#kb:phys:tg43:aapm-tg-43u1-rivard-2004) (`aapm-tg-43u1-rivard-2004.md`)
- → [#kb:phys:tg43:aapm-tg-43-nath-1995](#kb:phys:tg43:aapm-tg-43-nath-1995) (`aapm-tg-43-nath-1995.md`)
- → [#kb:phys:aapm_other:aapm-tg-229-mbdca](#kb:phys:aapm_other:aapm-tg-229-mbdca) (`aapm-tg-229-mbdca.md`)

---

### <a id="phys-icru"></a> ICRU Reports (2 files)

<a id="kb:phys:icru:icru-38-ic"></a>

#### ICRU Report 38: Dose and Volume Specification for Reporting Intracavitary Therapy in Gynecology (1985)

📄 [icru-38-ic.md](sources/07_physics/raw/icru-38-ic.md)

**Journal:** ICRU Reports  

**Topics:** `ICRU-38`, `gynec`, `intracavitary`, `point-A`, `reference-points`

**Key facts:**
- Point A defined as 2 cm superior to the cervical os and 2 cm lateral to the uterine canal (classical Manchester system).
- ICRU Bladder Reference Point located on lateral radiograph at the posterior surface of the pubic symphysis, on the Foley balloon.
- ICRU Rectum Reference Point located on lateral radiograph at the level of the lower end of the intrauterine source, 5 mm behind the posterior vaginal wall.
- ICRU 38 established the first standardized system for reporting gynecological intracavitary brachytherapy; superseded by ICRU 89 for cervix cancer.

**Key numbers:**
- Point A: 2 cm superior to cervical os, 2 cm lateral to uterine canal
- Rectum reference point: 5 mm behind posterior vaginal wall

**See also:**
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)
- → [#kb:phys:icru:icru-58-is](#kb:phys:icru:icru-58-is) (`icru-58-is.md`)

---

<a id="kb:phys:icru:icru-58-is"></a>

#### ICRU Report 58: Dose and Volume Specification for Reporting Interstitial Therapy (1997)

📄 [icru-58-is.md](sources/07_physics/raw/icru-58-is.md)

**Journal:** ICRU Reports  

**Topics:** `ICRU-58`, `interstitial`, `MTD`, `DNR`, `PDR-HDR`

**Key facts:**
- Defines Minimum Target Dose (MTD) as the minimum dose within the target volume.
- Introduces Reference Volume (volume enclosed by a specified isodose surface), Dose Non-uniformity Ratio (DNR = ratio of volumes receiving high vs reference dose), central plane dose reporting, and dose-rate recommendations for PDR and HDR.

**See also:**
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)
- → [#kb:phys:icru:icru-38-ic](#kb:phys:icru:icru-38-ic) (`icru-38-ic.md`)

---

### <a id="phys-iaea"></a> IAEA Publications (2 files)

<a id="kb:phys:iaea:iaea-3d-bt-commissioning-2020"></a>

#### Comprehensive methodology for commissioning modern 3D-image-based treatment planning systems for high dose rate gynaecological brachytherapy: A review (2025)

📄 [iaea-3d-bt-commissioning-2020.md](sources/07_physics/raw/iaea-3d-bt-commissioning-2020.md)

**Journal:** IAEA  
**DOI:** 10.1016/j.ejmp.2020.07.031  
**PMID:** 32768917 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/32768917/))  

**Topics:** `IAEA`, `TPS-commissioning`, `3D-image-based`, `HDR-gyn`, `43-items`

**Key facts:**
- Essential TPS commissioning items were categorized into six parts: geometry, dose calculation, plan evaluation tools, plan optimization, TPS output, and end-to-end verification.
- The final template consists of 43 items covering all dosimetric and non-dosimetric issues for HDR gynecological brachytherapy TPS commissioning.
- EBRT TPS commissioning tests were applied to brachytherapy and the template was developed using IAEA, AAPM, and ESTRO guidelines.

**Key numbers:**
- 43 commissioning items
- 6 commissioning categories

**See also:**
- → [#kb:phys:aapm_other:aapm-tg-148-hdr-qa](#kb:phys:aapm_other:aapm-tg-148-hdr-qa) (`aapm-tg-148-hdr-qa.md`)
- → [#kb:phys:afterloader:hdr-afterloader-commissioning-2024](#kb:phys:afterloader:hdr-afterloader-commissioning-2024) (`hdr-afterloader-commissioning-2024.md`)
- → [#kb:phys:iaea:iaea-trs-398](#kb:phys:iaea:iaea-trs-398) (`iaea-trs-398.md`)

---

<a id="kb:phys:iaea:iaea-trs-398"></a>

#### IAEA TRS-398: Absorbed Dose Determination in External Beam Radiotherapy (2000)

📄 [iaea-trs-398.md](sources/07_physics/raw/iaea-trs-398.md)

**Journal:** IAEA Technical Reports Series  

**Topics:** `IAEA`, `TRS-398`, `external-beam`, `absorbed-dose`

**Key facts:**
- Published by the International Atomic Energy Agency (IAEA) in 2000 (Technical Reports Series No. 398).
- Brachytherapy section covers source strength calibration (air kerma rate, reference air kerma rate), dose calculation using TG-43 formalism, calibration laboratory requirements, and traceability to primary standards.

**See also:**
- → [#kb:phys:iaea:iaea-3d-bt-commissioning-2020](#kb:phys:iaea:iaea-3d-bt-commissioning-2020) (`iaea-3d-bt-commissioning-2020.md`)
- → [#kb:phys:tg43:aapm-tg-43-nath-1995](#kb:phys:tg43:aapm-tg-43-nath-1995) (`aapm-tg-43-nath-1995.md`)

---

### <a id="phys-aapm_other"></a> AAPM Task Groups (Other) (3 files)

<a id="kb:phys:aapm_other:aapm-tg-148-hdr-qa"></a>

#### 07_physics — Physics & Dosimetry (13 files)

📄 [aapm-tg-148-hdr-qa.md](sources/07_physics/raw/aapm-tg-148-hdr-qa.md)


**Topics:** `QA`, `ultrasound`, `GEC-ESTRO`, `ACROP`, `BRAPHYQS`, `UroGEC`

**See also:**
- → [#kb:phys:afterloader:hdr-afterloader-commissioning-2024](#kb:phys:afterloader:hdr-afterloader-commissioning-2024) (`hdr-afterloader-commissioning-2024.md`)
- → [#kb:phys:iaea:iaea-3d-bt-commissioning-2020](#kb:phys:iaea:iaea-3d-bt-commissioning-2020) (`iaea-3d-bt-commissioning-2020.md`)

---

<a id="kb:phys:aapm_other:aapm-tg-229-mbdca"></a>

#### A generic high-dose rate (192)Ir brachytherapy source for evaluation of model-based dose calculations beyond the TG-43 formalism (2012)

📄 [aapm-tg-229-mbdca.md](sources/07_physics/raw/aapm-tg-229-mbdca.md)

**Journal:** Medical Physics  
**DOI:** 10.1118/1.4750258  
**PMID:** 26127057 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/26127057/))  

**Topics:** `MBDCA`, `TG-229`, `Ir-192`, `model-based-dose-calculation`, `ACUROS`, `ACE`

**Key facts:**
- A hypothetical generic HDR 192Ir source and a virtual cubic water phantom (201 cubed = 8,120,601 voxels with 1 mm sides) were designed to facilitate TPS commissioning for MBDCA.
- Dose-rate constant from seven independent MC simulations averaged 1.1109 ± 0.0004 cGy/(h U) (k=1, Type A uncertainty).
- Differences between commercial MBDCA and MC results were within ~1% for ACUROS and ~2% for ACE on average at clinically relevant distances.
- Two test case plans were prepared: (i) source centered in phantom and (ii) source displaced 7 cm laterally from center.

**Key numbers:**
- Dose-rate constant: 1.1109 ± 0.0004 cGy/(h U)
- Phantom: 201^3 voxels at 1 mm sides
- Source displacement: 7 cm laterally

**See also:**
- → [#kb:phys:tg43:aapm-tg-43u1-rivard-2004](#kb:phys:tg43:aapm-tg-43u1-rivard-2004) (`aapm-tg-43u1-rivard-2004.md`)
- → [#kb:phys:tg43:aapm-tg-43u1s1-perez-2012](#kb:phys:tg43:aapm-tg-43u1s1-perez-2012) (`aapm-tg-43u1s1-perez-2012.md`)
- → [#kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt](#kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt) (`deep-reinforcement-learning-hdr-bt-cervical.md`)

---

<a id="kb:phys:aapm_other:aapm-tg-232-film"></a>

#### AAPM TG-232: Radiochromic Film Dosimetry (2020)

📄 [aapm-tg-232-film.md](sources/07_physics/raw/aapm-tg-232-film.md)

**Journal:** Various  
**DOI:** 10.1118/1.4754544  

**Topics:** `dosimetry`, `radiochromic-film`, `TG-232`

**Key facts:**
- DOI listed: 10.1118/1.4754544.

**See also:**
- → [#kb:phys:aapm_other:aapm-tg-148-hdr-qa](#kb:phys:aapm_other:aapm-tg-148-hdr-qa) (`aapm-tg-148-hdr-qa.md`)

---

### <a id="phys-ai_planning"></a> AI / Inverse Treatment Planning (1 files)

<a id="kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt"></a>

#### Intelligent inverse treatment planning via deep reinforcement learning, a proof-of-principle study in high dose-rate brachytherapy for cervical cancer (2019)

📄 [deep-reinforcement-learning-hdr-bt-cervical.md](sources/07_physics/raw/deep-reinforcement-learning-hdr-bt-cervical.md)

**Journal:** Physics in Medicine and Biology  
**DOI:** 10.1088/1361-6560/ab147d  

**Topics:** `AI`, `deep-reinforcement-learning`, `inverse-planning`, `HDR-cervical`, `proof-of-principle`

**See also:**
- → [#kb:pros:hdr:real-time-trus-planning](#kb:pros:hdr:real-time-trus-planning) (`real-time-trus-planning.md`)
- → [#kb:phys:aapm_other:aapm-tg-229-mbdca](#kb:phys:aapm_other:aapm-tg-229-mbdca) (`aapm-tg-229-mbdca.md`)
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)

---

### <a id="phys-afterloader"></a> Afterloader Commissioning (1 files)

<a id="kb:phys:afterloader:hdr-afterloader-commissioning-2024"></a>

#### Commissioning considerations for the Bravos high-dose-rate afterloader: Towards improving treatment delivery accuracy (2025)

📄 [hdr-afterloader-commissioning-2024.md](sources/07_physics/raw/hdr-afterloader-commissioning-2024.md)

**Journal:** Medical Physics  
**DOI:** 10.1016/j.brachy.2024.06.010  
**PMID:** 39112321 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/39112321/))  

**Topics:** `afterloader`, `Bravos`, `HDR`, `commissioning`, `>600-plans-per-year`

**Key facts:**
- The clinic employs three HDR remote afterloaders in four dedicated treatment vaults at the main site and a fourth at a regional location.
- More than 600 new HDR treatment plans are performed annually, most planned and treated intraoperatively, with the majority for prostate cancer, followed by GYN, intraoperative BT, GI, and other sites.
- Applicators include vendor-provided, third-party, and in-house 3D-printed devices for interstitial, intracavitary, intraluminal, and surface treatments.
- In one case, tight tolerances detected obstruction near the tip of the channel and corrected it prior to treatment during the 4-month postupgrade review.

**Key numbers:**
- >600 new HDR plans/year
- 4 dedicated treatment vaults at main site + 1 regional afterloader
- 4-month postupgrade review period

**See also:**
- → [#kb:phys:aapm_other:aapm-tg-148-hdr-qa](#kb:phys:aapm_other:aapm-tg-148-hdr-qa) (`aapm-tg-148-hdr-qa.md`)
- → [#kb:phys:iaea:iaea-3d-bt-commissioning-2020](#kb:phys:iaea:iaea-3d-bt-commissioning-2020) (`iaea-3d-bt-commissioning-2020.md`)

---

### <a id="phys-3d_printing"></a> 3D Printing (1 files)

<a id="kb:phys:3d_printing:nature-3d-printing-rt-2020"></a>

#### Three-dimensional printing in radiation oncology: A systematic review of the literature (2025)

📄 [nature-3d-printing-rt-2020.md](sources/07_physics/raw/nature-3d-printing-rt-2020.md)

**Journal:** Nature  
**DOI:** 10.1002/acm2.12907  
**PMID:** 32459059 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/32459059/))  

**Topics:** `3D-printing`, `applicators`, `bolus`, `QA-phantoms`, `103-publications`

**Key facts:**
- 103 publications from 2012 to 2019 met inclusion criteria in this PRISMA-guided systematic review.
- Most commonly described 3D printing applications: QA phantoms (26%), brachytherapy applicators (20%), bolus (17%), preclinical animal irradiation (10%), compensators (7%), immobilization devices (5%).
- Within clinical settings the most common applications were brachytherapy applicators (44%) and bolus (28%).
- Most studies were preclinical feasibility studies (63%); few were clinical case reports/series (13%) or cohort studies (11%).
- Sample sizes for clinical investigations were small (median 10, range 1-42) and the number of articles increased over time (P < 0.0001).

**Key numbers:**
- 103 publications (2012-2019)
- QA phantoms: 26%
- Brachytherapy applicators: 20%
- Bolus: 17%
- Preclinical feasibility studies: 63%
- Clinical case reports/series: 13%
- Cohort studies: 11%
- Clinical sample size median 10, range 1-42

**See also:**
- → [#kb:oth:brain_spine:gammatile-brain](#kb:oth:brain_spine:gammatile-brain) (`gammatile-brain.md`)
- → [#kb:hns:skin:freiburg-flap-ham](#kb:hns:skin:freiburg-flap-ham) (`freiburg-flap-ham.md`)
- → [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](#kb:gi:pancreatic:3d-template-i125-pancreatic-2018) (`3d-template-i125-pancreatic-2018.md`)

---

## <a id="frm"></a> Frameworks & Society Initiatives (13 files)

**Subtitle:** AAPM, ABS, ASTRO, GEC-ESTRO, IAEA, ICRU, NCCN, WHO  
**Master list:** [`sources/08_frameworks/INDEX.md`](sources/08_frameworks/INDEX.md)

### <a id="frm-society_methodology"></a> Society Methodology (5 files)

<a id="kb:frm:society_methodology:aapm-about"></a>

#### 08_frameworks — Frameworks & Society Initiatives (13 files)

📄 [aapm-about.md](sources/08_frameworks/raw/aapm-about.md)


**Topics:** `AAPM`, `ethics`, `guideline-methodology`

**See also:**
- → [#kb:phys:tg43:aapm-tg-43-nath-1995](#kb:phys:tg43:aapm-tg-43-nath-1995) (`aapm-tg-43-nath-1995.md`)
- → [#kb:phys:tg43:aapm-tg-43u1-rivard-2004](#kb:phys:tg43:aapm-tg-43u1-rivard-2004) (`aapm-tg-43u1-rivard-2004.md`)

---

<a id="kb:frm:society_methodology:abs-mission"></a>

#### ABS Mission and Guideline Methodology (2024)

📄 [abs-mission.md](sources/08_frameworks/raw/abs-mission.md)

**Journal:** abs Website  

**Topics:** `ABS`, `mission`, `guideline-methodology`

**See also:**
- → [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](#kb:gyn:cervix:abs-cervix-consensus-2012-part1) (`abs-cervix-consensus-2012-part1.md`)
- → [#kb:pros:hdr:abs-2022-prostate-hdr](#kb:pros:hdr:abs-2022-prostate-hdr) (`abs-2022-prostate-hdr.md`)
- → [#kb:hns:skin:abs-skin-2020](#kb:hns:skin:abs-skin-2020) (`abs-skin-2020.md`)

---

<a id="kb:frm:society_methodology:astro-methodology"></a>

#### ASTRO Clinical Practice Guideline Methodology (2024)

📄 [astro-methodology.md](sources/08_frameworks/raw/astro-methodology.md)

**Journal:** astro Website  

**Topics:** `ASTRO`, `clinical-practice-guideline`, `methodology`

**See also:**
- → [#kb:brst:apbi:astro-2022-apbi](#kb:brst:apbi:astro-2022-apbi) (`astro-2022-apbi.md`)
- → [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](#kb:gyn:endometrial:ars-appropriate-use-criteria-2024) (`ars-appropriate-use-criteria-2024.md`)

---

<a id="kb:frm:society_methodology:gec-estro-about"></a>

#### GEC-ESTRO ESTRO Working Group Structure (2024)

📄 [gec-estro-about.md](sources/08_frameworks/raw/gec-estro-about.md)

**Journal:** gec Website  

**Topics:** `GEC-ESTRO`, `ESTRO`, `working-group`

**See also:**
- → [#kb:gyn:cervix:gec-estro-cervix-2005-haie](#kb:gyn:cervix:gec-estro-cervix-2005-haie) (`gec-estro-cervix-2005-haie-meder.md`)
- → [#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024](#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024) (`gec-estro-endometrial-2024.md`)
- → [#kb:hns:skin:gec-estro-skin-2018](#kb:hns:skin:gec-estro-skin-2018) (`gec-estro-skin-2018.md`)

---

<a id="kb:frm:society_methodology:nccn-methodology"></a>

#### NCCN Guidelines Development Methodology (2024)

📄 [nccn-methodology.md](sources/08_frameworks/raw/nccn-methodology.md)

**Journal:** nccn Website  

**Topics:** `NCCN`, `guideline-development`, `methodology`

**See also:**
- → [#kb:gyn:cervix:nccn-cervical-2024](#kb:gyn:cervix:nccn-cervical-2024) (`nccn-cervical-2024.md`)
- → [#kb:brst:guidelines:nccn-breast-2024](#kb:brst:guidelines:nccn-breast-2024) (`nccn-breast-2024.md`)
- → [#kb:hns:hn_cancer:nccn-hn-2024](#kb:hns:hn_cancer:nccn-hn-2024) (`nccn-hn-2024.md`)
- → [#kb:gi:esophageal:nccn-esophageal-2024](#kb:gi:esophageal:nccn-esophageal-2024) (`nccn-esophageal-2024.md`)

---

### <a id="frm-iaea_who"></a> IAEA / WHO Programs (3 files)

<a id="kb:frm:iaea_who:iaea-brachy-programme"></a>

#### IAEA Brachytherapy Programme (2024)

📄 [iaea-brachy-programme.md](sources/08_frameworks/raw/iaea-brachy-programme.md)

**Journal:** iaea Website  

**Topics:** `IAEA`, `brachytherapy-programme`, `training`

**See also:**
- → [#kb:phys:iaea:iaea-trs-398](#kb:phys:iaea:iaea-trs-398) (`iaea-trs-398.md`)
- → [#kb:phys:iaea:iaea-3d-bt-commissioning-2020](#kb:phys:iaea:iaea-3d-bt-commissioning-2020) (`iaea-3d-bt-commissioning-2020.md`)
- → [#kb:frm:iaea_who:iaea-global-bt-initiative-2020](#kb:frm:iaea_who:iaea-global-bt-initiative-2020) (`iaea-global-bt-initiative-2020.md`)

---

<a id="kb:frm:iaea_who:iaea-global-bt-initiative-2020"></a>

#### Addressing the burden of cervical cancer through IAEA global brachytherapy initiatives (2025)

📄 [iaea-global-bt-initiative-2020.md](sources/08_frameworks/raw/iaea-global-bt-initiative-2020.md)

**Journal:** IAEA  
**DOI:** 10.1016/j.brachy.2020.07.015  
**PMID:** 32928684 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/32928684/))  

**Topics:** `IAEA`, `cervical-cancer`, `global-initiative`, `QUATRO`

**Key facts:**
- Brachytherapy is an essential component of definitive therapy for locally advanced cervical cancer.
- Replacing BT with other modern external beam techniques as a boost can lead to suboptimal results in cervix cancer.
- IAEA supports BT through education/training, expert visits, e-learning, contouring workshops, 2D to 3D BT training, and virtual tumor boards.
- IAEA provides comprehensive audits in radiation therapy (QUATRO) and safety standards/training in radiation safety.
- IAEA Dosimetry Laboratory provides calibration services to SSDLs for well chambers used to confirm reference air kerma rate of Co60 and Ir192 HDR BT sources and Cs137 LDR sources.

**See also:**
- → [#kb:frm:iaea_who:iaea-brachy-programme](#kb:frm:iaea_who:iaea-brachy-programme) (`iaea-brachy-programme.md`)
- → [#kb:frm:global_access:iaea-india-bt-transition-2023](#kb:frm:global_access:iaea-india-bt-transition-2023) (`iaea-india-bt-transition-2023.md`)
- → [#kb:gyn:cervix:msk-bt-utilization-cervical-2025](#kb:gyn:cervix:msk-bt-utilization-cervical-2025) (`msk-bt-utilization-cervical-2025.md`)

---

<a id="kb:frm:iaea_who:who-image-guided-irt-2025"></a>

#### Image-guided interventional radiotherapy (modern brachytherapy) for treatment of vaginal intraepithelial neoplasia: single-institution experience and systematic literature review and meta-analysis (2025)

📄 [who-image-guided-irt-2025.md](sources/08_frameworks/raw/who-image-guided-irt-2025.md)

**Journal:** WHO  
**DOI:** 10.1007/s00066-026-02549-6  
**PMID:** 42189190 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/42189190/))  

**Topics:** `WHO`, `IG-IRT`, `vaginal-VaIN`, `n=10`, `1y-LC-100%`

**Key facts:**
- IG-IRT total dose was 40 Gy over 8 HDR fractions to achieve 60 Gy EQD2(alpha/beta=10) to the CTV.
- Treatment was performed with OncentraBrachy TPS and a Flexitron (Elekta) afterloading machine with a 192-Ir source.
- Systematic review was conducted according to PRISMA guidelines.
- 1-year actuarial LC and OS rates were 100% in 10 patients with high-grade VaIN.

**Dose constraints / prescription:**
- 40 Gy over 8 HDR fractions
- 60 Gy EQD2(alpha/beta=10) to CTV

**Trial endpoints / outcomes:**
- Primary: local control (LC)
- Secondary: rate and severity of acute and late treatment-related toxicity
- 1-year actuarial LC 100%
- 1-year OS 100%
- Late G2 toxicity: vaginal stenosis 1, atrophy 4 (in 4 of 10 patients)

**Key numbers:**
- 10 patients with high-grade VaIN3, radiotherapy-naive
- Median follow-up 17 months (range 7-70 months)
- Study period: January 2019 to May 2025
- No acute side effects recorded

**See also:**
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)
- → [#kb:frm:global_access:lancet-bt-global-demand-2025](#kb:frm:global_access:lancet-bt-global-demand-2025) (`lancet-bt-global-demand-2025.md`)

---

### <a id="frm-global_access"></a> Global Access & Transition (3 files)

<a id="kb:frm:global_access:iaea-india-bt-transition-2023"></a>

#### Transitioning India to advanced image based adaptive brachytherapy: a national impact analysis of upgrading National Cancer Grid cervix cancer guidelines (2025)

📄 [iaea-india-bt-transition-2023.md](sources/08_frameworks/raw/iaea-india-bt-transition-2023.md)

**Journal:** IAEA  
**DOI:** 10.1016/j.lansea.2023.100218  
**PMID:** 37694176 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/37694176/))  

**Topics:** `IAEA`, `India`, `IGABT-transition`, `NCG`, `84-patients`

**Key facts:**
- Activity mapping was conducted between September 2020 and March 2021 in a high-volume centre that triaged cervical cancer patients into four workflows (A: 2D X-Ray point A-based, B: CT point A-based, C: MRI/CT-volume based, D: MRI/CT volume-based with interstitial).
- Transition from workflow A to D led to 35%, 49%, and 64% loss of treatment capacity in the index institution.
- Single brachytherapy applicator implant with multiple treatment fractions increased treatment capacity by 100%.
- Twenty-three Indian states/UTs can transition to advanced workflows; four states may find it detrimental given infrastructure; eight states lacked brachytherapy access.

**Key numbers:**
- 84 patients included in study
- Workflow A: 176 min (57-208); B: 224 min (74-260); C: 267 min (101-302); D: 348 min (232-383)
- Capacity gains: 25% (10-hr shifts), 50% (12-hr shifts), 100% (single implant/multiple fractions)
- 23 states/UTs can transition; 4 detrimental; 8 lack BT access

**See also:**
- → [#kb:frm:iaea_who:iaea-global-bt-initiative-2020](#kb:frm:iaea_who:iaea-global-bt-initiative-2020) (`iaea-global-bt-initiative-2020.md`)
- → [#kb:frm:global_access:lancet-bt-global-demand-2025](#kb:frm:global_access:lancet-bt-global-demand-2025) (`lancet-bt-global-demand-2025.md`)
- → [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet) (`embrace-i-pivotal-2021-lancet-oncol.md`)

---

<a id="kb:frm:global_access:lancet-bt-global-demand-2025"></a>

#### Assessing the global demand and supply of brachytherapy resources: a population-based observational study (2025)

📄 [lancet-bt-global-demand-2025.md](sources/08_frameworks/raw/lancet-bt-global-demand-2025.md)

**Journal:** Lancet  
**DOI:** 10.1016/S1470-2045(25)00718-1  
**PMID:** 41785895 ([PubMed](https://pubmed.ncbi.nlm.nih.gov/41785895/))  

**Topics:** `global-access`, `Lancet-2025`, `demand-supply`, `708948-cases`, `HIC-UMIC-LMIC-LIC`

**Key facts:**
- Of 18,528,336 new cancer cases in 185 countries in 2022, 708,948 (3.8%) were estimated to require brachytherapy.
- Cervical cancer accounted for 59.3% (n=420,090) of brachytherapy indications, followed by uterine (25.2%, n=178,584) and prostate cancer (11.5%, n=81,849).
- Brachytherapy demand was met in 81.5% of HICs, 44.4% of UMICs, 11.8% of LMICs, and 0% of LICs.
- Regions with biggest deficit: sub-Saharan Africa, eastern Asia, and south-eastern Asia.
- Travel distance to nearest centre was 68 km in HICs, 167 km in UMICs, 341 km in LMICs, and 551 km in LICs (p<0.0001).

**Key numbers:**
- 18,528,336 new cancer cases in 185 countries (2022)
- 708,948 cases required brachytherapy (3.8% global utilisation)
- Cervical: 420,090 (59.3%); Uterine: 178,584 (25.2%); Prostate: 81,849 (11.5%); Vaginal: 13,996 (2.0%); Vulval: 7,611 (1.1%); Ocular melanoma: 6,817 (1.0%)
- Annual centre capacity defined as 218 patients (HIC baseline)
- Population-weighted travel distance: 68 km (HIC), 167 km (UMIC), 341 km (LMIC), 551 km (LIC)
- Utilisation rates: 10.4% LICs, 5.7% LMICs, 3.5% UMICs, 2.9% HICs

**See also:**
- → [#kb:frm:iaea_who:iaea-brachy-programme](#kb:frm:iaea_who:iaea-brachy-programme) (`iaea-brachy-programme.md`)
- → [#kb:frm:global_access:iaea-india-bt-transition-2023](#kb:frm:global_access:iaea-india-bt-transition-2023) (`iaea-india-bt-transition-2023.md`)
- → [#kb:frm:iaea_who:iaea-global-bt-initiative-2020](#kb:frm:iaea_who:iaea-global-bt-initiative-2020) (`iaea-global-bt-initiative-2020.md`)
- → [#kb:gyn:cervix:msk-bt-utilization-cervical-2025](#kb:gyn:cervix:msk-bt-utilization-cervical-2025) (`msk-bt-utilization-cervical-2025.md`)

---

<a id="kb:frm:global_access:icru-reports-catalogue"></a>

#### ICRU Reports Catalogue (2024)

📄 [icru-reports-catalogue.md](sources/08_frameworks/raw/icru-reports-catalogue.md)

**Journal:** icru Website  

**Topics:** `ICRU`, `reports-catalogue`

**See also:**
- → [#kb:gyn:cervix:icru-89-gyn](#kb:gyn:cervix:icru-89-gyn) (`icru-89-gyn.md`)
- → [#kb:phys:icru:icru-38-ic](#kb:phys:icru:icru-38-ic) (`icru-38-ic.md`)
- → [#kb:phys:icru:icru-58-is](#kb:phys:icru:icru-58-is) (`icru-58-is.md`)

---

### <a id="frm-chinese"></a> Chinese Societies (CSCO / CSTRO) (2 files)

<a id="kb:frm:chinese:csco-bt-chinese"></a>

#### CSCO Brachytherapy Guidelines Chinese (2017)

📄 [csco-bt-chinese.md](sources/08_frameworks/raw/csco-bt-chinese.md)

**Journal:** Chinese Journal of Radiation Oncology  

**Topics:** `CSCO`, `Chinese-society`, `I-125`, `pancreatic`

**Key facts:**
- Chinese consensus guidelines cover I-125 seed implantation techniques for pancreatic cancer.
- Topics include dose prescription and planning protocols, patient selection criteria, and combination with chemotherapy.

**See also:**
- → [#kb:frm:chinese:cstro-bt-chinese](#kb:frm:chinese:cstro-bt-chinese) (`cstro-bt-chinese.md`)
- → [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](#kb:gi:pancreatic:i125-pancreatic-guideline-2023) (`i125-pancreatic-guideline-2023.md`)

---

<a id="kb:frm:chinese:cstro-bt-chinese"></a>

#### CSTRO Chinese Brachytherapy Consensus (2017)

📄 [cstro-bt-chinese.md](sources/08_frameworks/raw/cstro-bt-chinese.md)

**Journal:** Chinese Journal of Radiation Oncology  

**Topics:** `CSTRO`, `Chinese-society`, `I-125`, `pancreatic`

**Key facts:**
- Chinese consensus guidelines cover I-125 seed implantation techniques for pancreatic cancer.
- Topics include dose prescription and planning protocols, patient selection criteria, and combination with chemotherapy.

**See also:**
- → [#kb:frm:chinese:csco-bt-chinese](#kb:frm:chinese:csco-bt-chinese) (`csco-bt-chinese.md`)
- → [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](#kb:gi:pancreatic:i125-pancreatic-guideline-2023) (`i125-pancreatic-guideline-2023.md`)
- → [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](#kb:gi:pancreatic:3d-template-i125-pancreatic-2018) (`3d-template-i125-pancreatic-2018.md`)

---

## Part III: Cross-Cutting References

### OAR Dose Constraints (cervix HDR — EMBRACE II)

From [embrace-ii-protocol.md](sources/01_gynecologic/raw/embrace-ii-protocol.md) (PMID 42211610, Radiotherapy & Oncology 2018):

| OAR | D2cc limit (EQD2, α/β=3) |
|-----|--------------------------|
| Bladder | < 90 Gy |
| Rectum | < 75 Gy |
| Sigmoid | < 70 Gy |

### Cumulative HR-CTV Dose Targets (definitive cervix BT)

| Dose system | Range | Source |
|-------------|-------|--------|
| Cumulative (EBRT+BT) | ~80-90 Gy | [abs-cervix-consensus-2012-part1.md](sources/01_gynecologic/raw/abs-cervix-consensus-2012-part1.md) and [abs-cervix-consensus-2012-part2.md](sources/01_gynecologic/raw/abs-cervix-consensus-2012-part2.md) (PMID 22265436, 22265437) |
| Median D90 HR-CTV (EMBRACE-I) | 90 Gy (IQR 85-94) EQD2 | [embrace-i-pivotal-2021-lancet-oncol.md](sources/01_gynecologic/raw/embrace-i-pivotal-2021-lancet-oncol.md) (PMID 33794207) |

### ICRU 89 Dose-Reporting Parameters

From [icru-89-gyn.md](sources/01_gynecologic/raw/icru-89-gyn.md) (ICRU 2013):

| Parameter | Definition |
|-----------|------------|
| D90 | Minimum dose to 90% of HR-CTV (primary dose-reporting parameter) |
| D100 | Minimum dose to 100% of HR-CTV |
| D2cc | Minimum dose to most-exposed 2 cm³ of OAR (bladder, rectum, sigmoid, small bowel) |
| D1cc | Minimum dose to most-exposed 1 cm³ |
| D0.1cc | Minimum dose to most-exposed 0.1 cm³ |
| HR-CTV | High-Risk CTV (GTV + cervix at time of BT) |
| IR-CTV | Intermediate-Risk CTV (HR-CTV + surrounding tissue at risk) |

### Endometrial Adjuvant — PORTEC-2 (VBT vs EBRT)

From [portec-2-lancet-2010.md](sources/01_gynecologic/raw/portec-2-lancet-2010.md) (PMID 20206777, Lancet 2010):

| Arm | Dose | n | 5y VR | 5y LRR | Acute GI tox (G1-2) |
|-----|------|---|-------|--------|----------------------|
| Vaginal BT (HDR) | 21 Gy / 3 fx | 213 | 1.8% | 5.1% | 12.6% |
| Vaginal BT (LDR) | 30 Gy | – | – | – | – |
| Pelvic EBRT | 46 Gy / 23 fx | 214 | 1.6% | 2.1% | 53.8% |

### Esophageal BT Prescriptions (ABS 2014)

From [abs-esophageal-2014.md](sources/05_gi/raw/abs-esophageal-2014.md) (Brachytherapy 2014):

| Setting | HDR | LDR |
|---------|-----|-----|
| Definitive (post 5-FU + 45-50 Gy EBRT) | 10 Gy / 2 weekly fractions of 5 Gy | 20 Gy single course at 0.4-1 Gy/hr |
| Palliative (post limited 30 Gy EBRT) | 10-14 Gy / 1-2 fractions | 20-25 Gy single course |

Applicator: 6-10 mm external diameter. All doses specified 1 cm from mid-source or mid-dwell position. BT should not be given concurrently with chemotherapy.

---

## Part III § Topic Index (reverse index for RAG)

For each topic, lists the entry IDs that contain it. Use this for RAG retrieval by topic.

### `103-publications` (1 entries)

- [#kb:phys:3d_printing:nature-3d-printing-rt-2020](kb:phys:3d_printing:nature-3d-printing-rt-2020) — `nature-3d-printing-rt-2020.md`

### `10y-BCF-38.0%-vs-10.4%` (1 entries)

- [#kb:pros:hdr:jama-sbrt-vs-hdr-bt](kb:pros:hdr:jama-sbrt-vs-hdr-bt) — `jama-sbrt-vs-hdr-bt-prostate-2025.md`

### `10y-LR-10.2%-vs-6.2%` (1 entries)

- [#kb:brst:boost:wbi-boost-eortc-22881](kb:brst:boost:wbi-boost-eortc-22881) — `wbi-boost-eortc-22881.md`

### `16y-lung-cancer-1.8%-vs-7.2%` (1 entries)

- [#kb:brst:iort:targit-a-vaidya-2014](kb:brst:iort:targit-a-vaidya-2014) — `targit-a-vaidya-2014.md`

### `19-Gy-2fx` (1 entries)

- [#kb:pros:salvage:eortc-salvage-hdr-bt-2024](kb:pros:salvage:eortc-salvage-hdr-bt-2024) — `eortc-salvage-hdr-bt-2024.md`

### `1995-original` (1 entries)

- [#kb:phys:tg43:aapm-tg-43-nath-1995](kb:phys:tg43:aapm-tg-43-nath-1995) — `aapm-tg-43-nath-1995.md`

### `1y-LC-100%` (1 entries)

- [#kb:frm:iaea_who:who-image-guided-irt-2025](kb:frm:iaea_who:who-image-guided-irt-2025) — `who-image-guided-irt-2025.md`

### `2017-consensus-update` (1 entries)

- [#kb:brst:apbi:astro-2022-apbi](kb:brst:apbi:astro-2022-apbi) — `astro-2022-apbi.md`

### `2y-recurrence-0.42%` (1 entries)

- [#kb:hns:skin:esteya-electronic](kb:hns:skin:esteya-electronic) — `esteya-electronic.md`

### `36m-OS-82.6%-vs-74.8%` (1 entries)

- [#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024](kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024) — `lancet-pembrolizumab-crt-cervical-2024.md`

### `3D-image-based` (1 entries)

- [#kb:phys:iaea:iaea-3d-bt-commissioning-2020](kb:phys:iaea:iaea-3d-bt-commissioning-2020) — `iaea-3d-bt-commissioning-2020.md`

### `3D-planning` (1 entries)

- [#kb:gyn:cervix:gec-estro-cervix-2005-haie](kb:gyn:cervix:gec-estro-cervix-2005-haie) — `gec-estro-cervix-2005-haie-meder.md`

### `3D-printed-template` (1 entries)

- [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](kb:gi:pancreatic:3d-template-i125-pancreatic-2018) — `3d-template-i125-pancreatic-2018.md`

### `3D-printing` (1 entries)

- [#kb:phys:3d_printing:nature-3d-printing-rt-2020](kb:phys:3d_printing:nature-3d-printing-rt-2020) — `nature-3d-printing-rt-2020.md`

### `3D-printing-preop` (1 entries)

- [#kb:oth:brain_spine:gammatile-brain](kb:oth:brain_spine:gammatile-brain) — `gammatile-brain.md`

### `43-items` (1 entries)

- [#kb:phys:iaea:iaea-3d-bt-commissioning-2020](kb:phys:iaea:iaea-3d-bt-commissioning-2020) — `iaea-3d-bt-commissioning-2020.md`

### `4y-OS-97%` (1 entries)

- [#kb:brst:apbi:gec-estro-apbi-2016](kb:brst:apbi:gec-estro-apbi-2016) — `gec-estro-apbi-2016.md`

### `50-kVp` (1 entries)

- [#kb:brst:iort:iort-electronic-bt](kb:brst:iort:iort-electronic-bt) — `iort-electronic-bt.md`

### `50.43%-received-BT` (1 entries)

- [#kb:gyn:cervix:msk-bt-utilization-cervical-2025](kb:gyn:cervix:msk-bt-utilization-cervical-2025) — `msk-bt-utilization-cervical-2025.md`

### `52-evaluable` (1 entries)

- [#kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024](kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024) — `rtog-cisplatin-gem-imrt-2024.md`

### `5y-BCF-7.8%-vs-3.0%` (1 entries)

- [#kb:pros:hdr:jama-sbrt-vs-hdr-bt](kb:pros:hdr:jama-sbrt-vs-hdr-bt) — `jama-sbrt-vs-hdr-bt-prostate-2025.md`

### `5y-LC-92%` (1 entries)

- [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](kb:gyn:cervix:embrace-i-pivotal-2021-lancet) — `embrace-i-pivotal-2021-lancet-oncol.md`

### `5y-OS-76%-vs-73%` (1 entries)

- [#kb:pros:penile:nature-bt-penile-organ-preservation](kb:pros:penile:nature-bt-penile-organ-preservation) — `nature-bt-penile-organ-preservation-2015.md`

### `5y-OS-80%-vs-72%` (1 entries)

- [#kb:gyn:cervix:lancet-cervical-induction-chemo-2024](kb:gyn:cervix:lancet-cervical-induction-chemo-2024) — `lancet-cervical-induction-chemo-2024.md`

### `5y-OS-82%-both-arms` (1 entries)

- [#kb:gi:anal:gec-estro-anal-bt-2018](kb:gi:anal:gec-estro-anal-bt-2018) — `gec-estro-anal-bt-2018.md`

### `5y-PFS-72%-vs-64%` (1 entries)

- [#kb:gyn:cervix:lancet-cervical-induction-chemo-2024](kb:gyn:cervix:lancet-cervical-induction-chemo-2024) — `lancet-cervical-induction-chemo-2024.md`

### `5y-VR-1.8%-vs-1.6%` (1 entries)

- [#kb:gyn:endometrial:portec-2-lancet-2010](kb:gyn:endometrial:portec-2-lancet-2010) — `portec-2-lancet-2010.md`

### `5y-enucleation-12.5%` (1 entries)

- [#kb:oth:eye:coms-trial-medium](kb:oth:eye:coms-trial-medium) — `coms-trial-medium.md`

### `70.5%-lower-recurrence-low-tension` (1 entries)

- [#kb:hns:keloid:keloid-bt](kb:hns:keloid:keloid-bt) — `keloid-bt.md`

### `708948-cases` (1 entries)

- [#kb:frm:global_access:lancet-bt-global-demand-2025](kb:frm:global_access:lancet-bt-global-demand-2025) — `lancet-bt-global-demand-2025.md`

### `73%-CPR` (1 entries)

- [#kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024](kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024) — `rtog-cisplatin-gem-imrt-2024.md`

### `84-patients` (1 entries)

- [#kb:frm:global_access:iaea-india-bt-transition-2023](kb:frm:global_access:iaea-india-bt-transition-2023) — `iaea-india-bt-transition-2023.md`

### `>600-plans-per-year` (1 entries)

- [#kb:phys:afterloader:hdr-afterloader-commissioning-2024](kb:phys:afterloader:hdr-afterloader-commissioning-2024) — `hdr-afterloader-commissioning-2024.md`

### `AAPM` (1 entries)

- [#kb:frm:society_methodology:aapm-about](kb:frm:society_methodology:aapm-about) — `aapm-about.md`

### `AAPM-TG-129` (1 entries)

- [#kb:oth:eye:aapm-tg-129-uveal-melanoma](kb:oth:eye:aapm-tg-129-uveal-melanoma) — `aapm-tg-129-uveal-melanoma.md`

### `AAPM-TG-137` (1 entries)

- [#kb:pros:guidelines:aapm-tg-137-nath-2009](kb:pros:guidelines:aapm-tg-137-nath-2009) — `aapm-tg-137-nath-2009.md`

### `ABS` (8 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](kb:gyn:cervix:abs-cervix-consensus-2012-part1) — `abs-cervix-consensus-2012-part1.md`
- [#kb:gyn:cervix:abs-cervix-consensus-2012-part2](kb:gyn:cervix:abs-cervix-consensus-2012-part2) — `abs-cervix-consensus-2012-part2.md`
- [#kb:gyn:cervix:abs-vaginal-2012](kb:gyn:cervix:abs-vaginal-2012) — `abs-vaginal-2012.md`
- [#kb:gyn:vaginal_vulvar:abs-vulvar-2019](kb:gyn:vaginal_vulvar:abs-vulvar-2019) — `abs-vulvar-2019.md`
- [#kb:pros:hdr:abs-2022-prostate-hdr](kb:pros:hdr:abs-2022-prostate-hdr) — `abs-2022-prostate-hdr.md`
- [#kb:hns:skin:abs-skin-2020](kb:hns:skin:abs-skin-2020) — `abs-skin-2020.md`
- [#kb:gi:esophageal:abs-esophageal-2014](kb:gi:esophageal:abs-esophageal-2014) — `abs-esophageal-2014.md`
- [#kb:frm:society_methodology:abs-mission](kb:frm:society_methodology:abs-mission) — `abs-mission.md`

### `ABS-AUA-ASTRO` (1 entries)

- [#kb:pros:ldr:abs-aua-astro-ldr-2012](kb:pros:ldr:abs-aua-astro-ldr-2012) — `abs-aua-astro-ldr-2012.md`

### `ABS-GEC-ESTRO` (1 entries)

- [#kb:oth:sarcoma:abs-sarcoma-bt](kb:oth:sarcoma:abs-sarcoma-bt) — `abs-sarcoma-bt.md`

### `ABTC` (1 entries)

- [#kb:oth:brain_spine:gliasite-brain](kb:oth:brain_spine:gliasite-brain) — `gliasite-brain.md`

### `ACE` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-229-mbdca](kb:phys:aapm_other:aapm-tg-229-mbdca) — `aapm-tg-229-mbdca.md`

### `ACR-ABS` (1 entries)

- [#kb:hns:practice_param:abs-hn-2018](kb:hns:practice_param:abs-hn-2018) — `abs-hn-2018.md`

### `ACROP` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-148-hdr-qa](kb:phys:aapm_other:aapm-tg-148-hdr-qa) — `aapm-tg-148-hdr-qa.md`

### `ACUROS` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-229-mbdca](kb:phys:aapm_other:aapm-tg-229-mbdca) — `aapm-tg-229-mbdca.md`

### `AI` (1 entries)

- [#kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt](kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt) — `deep-reinforcement-learning-hdr-bt-cervical.md`

### `APBI` (8 entries)

- [#kb:brst:apbi:abs-apbi-2013](kb:brst:apbi:abs-apbi-2013) — `abs-apbi-2013.md`
- [#kb:brst:apbi:astro-2022-apbi](kb:brst:apbi:astro-2022-apbi) — `astro-2022-apbi.md`
- [#kb:brst:apbi:balloon-mammosite](kb:brst:apbi:balloon-mammosite) — `balloon-mammosite.md`
- [#kb:brst:apbi:estro-acrop-breast-2018](kb:brst:apbi:estro-acrop-breast-2018) — `estro-acrop-breast-2018.md`
- [#kb:brst:apbi:gec-estro-apbi-2016](kb:brst:apbi:gec-estro-apbi-2016) — `gec-estro-apbi-2016.md`
- [#kb:brst:apbi:nature-apbi-alternative-wbi-2020](kb:brst:apbi:nature-apbi-alternative-wbi-2020) — `nature-apbi-alternative-wbi-2020.md`
- [#kb:brst:apbi:nsabp-b39-rtog-0413](kb:brst:apbi:nsabp-b39-rtog-0413) — `nsabp-b39-rtog-0413.md`
- [#kb:brst:apbi:savi-strut-apbi](kb:brst:apbi:savi-strut-apbi) — `savi-strut-apbi.md`

### `ARS-AUC` (1 entries)

- [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](kb:gyn:endometrial:ars-appropriate-use-criteria-2024) — `ars-appropriate-use-criteria-2024.md`

### `ASCENDE-RT` (1 entries)

- [#kb:pros:ldr:ascende-rt-morris-2017](kb:pros:ldr:ascende-rt-morris-2017) — `ascende-rt-morris-2017.md`

### `ASTRO` (1 entries)

- [#kb:frm:society_methodology:astro-methodology](kb:frm:society_methodology:astro-methodology) — `astro-methodology.md`

### `ASTRO-consensus` (1 entries)

- [#kb:brst:apbi:abs-apbi-2013](kb:brst:apbi:abs-apbi-2013) — `abs-apbi-2013.md`

### `AUA-ASTRO` (1 entries)

- [#kb:pros:guidelines:aua-astro-2022-prostate](kb:pros:guidelines:aua-astro-2022-prostate) — `aua-astro-2022-prostate.md`

### `Axxent` (1 entries)

- [#kb:brst:iort:iort-electronic-bt](kb:brst:iort:iort-electronic-bt) — `iort-electronic-bt.md`

### `BED-69-72-Gy` (1 entries)

- [#kb:hns:skin:esteya-electronic](kb:hns:skin:esteya-electronic) — `esteya-electronic.md`

### `BED10` (1 entries)

- [#kb:hns:keloid:keloid-bt](kb:hns:keloid:keloid-bt) — `keloid-bt.md`

### `BED3` (1 entries)

- [#kb:hns:keloid:keloid-bt](kb:hns:keloid:keloid-bt) — `keloid-bt.md`

### `BRACHY-trial` (1 entries)

- [#kb:oth:lung:brachy-trial-lung](kb:oth:lung:brachy-trial-lung) — `brachy-trial-lung.md`

### `BRAPHYQS` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-148-hdr-qa](kb:phys:aapm_other:aapm-tg-148-hdr-qa) — `aapm-tg-148-hdr-qa.md`

### `BT-reappraisal` (1 entries)

- [#kb:oth:vascular:cardiac-vascular-review](kb:oth:vascular:cardiac-vascular-review) — `cardiac-vascular-review.md`

### `BT-review` (1 entries)

- [#kb:gi:gastric:gastric-bt](kb:gi:gastric:gastric-bt) — `gastric-bt.md`

### `Best-2301` (1 entries)

- [#kb:phys:tg43:aapm-tg-43u1s1-perez-2012](kb:phys:tg43:aapm-tg-43u1s1-perez-2012) — `aapm-tg-43u1s1-perez-2012.md`

### `Bravos` (1 entries)

- [#kb:phys:afterloader:hdr-afterloader-commissioning-2024](kb:phys:afterloader:hdr-afterloader-commissioning-2024) — `hdr-afterloader-commissioning-2024.md`

### `CKD` (1 entries)

- [#kb:oth:vascular:vascular-bt-sr90](kb:oth:vascular:vascular-bt-sr90) — `vascular-bt-sr90.md`

### `COMS-trial` (1 entries)

- [#kb:oth:eye:coms-trial-medium](kb:oth:eye:coms-trial-medium) — `coms-trial-medium.md`

### `CSCO` (1 entries)

- [#kb:frm:chinese:csco-bt-chinese](kb:frm:chinese:csco-bt-chinese) — `csco-bt-chinese.md`

### `CSTRO` (1 entries)

- [#kb:frm:chinese:cstro-bt-chinese](kb:frm:chinese:cstro-bt-chinese) — `cstro-bt-chinese.md`

### `CSTRO-CSCO` (1 entries)

- [#kb:gi:pancreatic:cstro-pancreatic-i125-2017](kb:gi:pancreatic:cstro-pancreatic-i125-2017) — `cstro-pancreatic-i125-2017.md`

### `CT-guided` (1 entries)

- [#kb:oth:lung:ct-guided-i125-early-lung](kb:oth:lung:ct-guided-i125-early-lung) — `ct-guided-i125-early-lung-cancer.md`

### `Chinese-consensus` (1 entries)

- [#kb:gi:pancreatic:cstro-pancreatic-i125-2017](kb:gi:pancreatic:cstro-pancreatic-i125-2017) — `cstro-pancreatic-i125-2017.md`

### `Chinese-expert-consensus` (1 entries)

- [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](kb:gi:pancreatic:i125-pancreatic-guideline-2023) — `i125-pancreatic-guideline-2023.md`

### `Chinese-society` (2 entries)

- [#kb:frm:chinese:csco-bt-chinese](kb:frm:chinese:csco-bt-chinese) — `csco-bt-chinese.md`
- [#kb:frm:chinese:cstro-bt-chinese](kb:frm:chinese:cstro-bt-chinese) — `cstro-bt-chinese.md`

### `Cs-131` (1 entries)

- [#kb:oth:brain_spine:gammatile-brain](kb:oth:brain_spine:gammatile-brain) — `gammatile-brain.md`

### `D0.1cc` (1 entries)

- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`

### `D1cc` (1 entries)

- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`

### `D2cc` (3 entries)

- [#kb:gyn:cervix:dimopoulos-mri-ctv-2012](kb:gyn:cervix:dimopoulos-mri-ctv-2012) — `dimopoulos-mri-ctv-2012.md`
- [#kb:gyn:cervix:embrace-ii-protocol](kb:gyn:cervix:embrace-ii-protocol) — `embrace-ii-protocol.md`
- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`

### `D90` (1 entries)

- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`

### `D90-90-Gy` (1 entries)

- [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](kb:gyn:cervix:embrace-i-pivotal-2021-lancet) — `embrace-i-pivotal-2021-lancet-oncol.md`

### `D98-94.4-EQD2Gy` (1 entries)

- [#kb:pros:microboost_focal:nrg-microboost-prostate-2024](kb:pros:microboost_focal:nrg-microboost-prostate-2024) — `nrg-microboost-prostate-2024.md`

### `DCIS` (1 entries)

- [#kb:brst:apbi:astro-2022-apbi](kb:brst:apbi:astro-2022-apbi) — `astro-2022-apbi.md`

### `DNR` (1 entries)

- [#kb:phys:icru:icru-58-is](kb:phys:icru:icru-58-is) — `icru-58-is.md`

### `Dixon-VIBE` (1 entries)

- [#kb:hns:skin:freiburg-flap-ham](kb:hns:skin:freiburg-flap-ham) — `freiburg-flap-ham.md`

### `EBRT-13x3-Gy` (1 entries)

- [#kb:gi:rectal:opera-trial-sun-myint](kb:gi:rectal:opera-trial-sun-myint) — `opera-trial-sun-myint.md`

### `EBRT-46-Gy` (1 entries)

- [#kb:gyn:endometrial:portec-2-lancet-2010](kb:gyn:endometrial:portec-2-lancet-2010) — `portec-2-lancet-2010.md`

### `EMBRACE-I` (1 entries)

- [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](kb:gyn:cervix:embrace-i-pivotal-2021-lancet) — `embrace-i-pivotal-2021-lancet-oncol.md`

### `EMBRACE-II` (1 entries)

- [#kb:gyn:cervix:embrace-ii-protocol](kb:gyn:cervix:embrace-ii-protocol) — `embrace-ii-protocol.md`

### `EORTC` (1 entries)

- [#kb:pros:salvage:eortc-salvage-hdr-bt-2024](kb:pros:salvage:eortc-salvage-hdr-bt-2024) — `eortc-salvage-hdr-bt-2024.md`

### `EORTC-22881-10882` (1 entries)

- [#kb:brst:boost:wbi-boost-eortc-22881](kb:brst:boost:wbi-boost-eortc-22881) — `wbi-boost-eortc-22881.md`

### `EQD2` (1 entries)

- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`

### `ESTRO` (1 entries)

- [#kb:frm:society_methodology:gec-estro-about](kb:frm:society_methodology:gec-estro-about) — `gec-estro-about.md`

### `ESTRO-ACROP` (1 entries)

- [#kb:brst:apbi:estro-acrop-breast-2018](kb:brst:apbi:estro-acrop-breast-2018) — `estro-acrop-breast-2018.md`

### `Elekta-Esteya` (1 entries)

- [#kb:hns:skin:esteya-electronic](kb:hns:skin:esteya-electronic) — `esteya-electronic.md`

### `Freiburg-Flap` (1 entries)

- [#kb:hns:skin:freiburg-flap-ham](kb:hns:skin:freiburg-flap-ham) — `freiburg-flap-ham.md`

### `GEC-ESTRO` (8 entries)

- [#kb:gyn:cervix:gec-estro-cervix-2005-haie](kb:gyn:cervix:gec-estro-cervix-2005-haie) — `gec-estro-cervix-2005-haie-meder.md`
- [#kb:pros:penile:gec-estro-penile-2018](kb:pros:penile:gec-estro-penile-2018) — `gec-estro-penile-2018.md`
- [#kb:brst:apbi:gec-estro-apbi-2016](kb:brst:apbi:gec-estro-apbi-2016) — `gec-estro-apbi-2016.md`
- [#kb:hns:hn_cancer:gec-estro-hn](kb:hns:hn_cancer:gec-estro-hn) — `gec-estro-hn.md`
- [#kb:hns:skin:gec-estro-skin-2018](kb:hns:skin:gec-estro-skin-2018) — `gec-estro-skin-2018.md`
- [#kb:gi:anal:gec-estro-anal-bt-2018](kb:gi:anal:gec-estro-anal-bt-2018) — `gec-estro-anal-bt-2018.md`
- [#kb:phys:aapm_other:aapm-tg-148-hdr-qa](kb:phys:aapm_other:aapm-tg-148-hdr-qa) — `aapm-tg-148-hdr-qa.md`
- [#kb:frm:society_methodology:gec-estro-about](kb:frm:society_methodology:gec-estro-about) — `gec-estro-about.md`

### `GEC-ESTRO-ACROP-ABS-CBG` (1 entries)

- [#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024](kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024) — `gec-estro-endometrial-2024.md`

### `GOG` (1 entries)

- [#kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024](kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024) — `rtog-cisplatin-gem-imrt-2024.md`

### `GTV-CTV` (1 entries)

- [#kb:gyn:cervix:gec-estro-cervix-2005-haie](kb:gyn:cervix:gec-estro-cervix-2005-haie) — `gec-estro-cervix-2005-haie-meder.md`

### `GammaTile` (1 entries)

- [#kb:oth:brain_spine:gammatile-brain](kb:oth:brain_spine:gammatile-brain) — `gammatile-brain.md`

### `GliaSite` (1 entries)

- [#kb:oth:brain_spine:gliasite-brain](kb:oth:brain_spine:gliasite-brain) — `gliasite-brain.md`

### `HDR` (5 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](kb:gyn:cervix:abs-cervix-consensus-2012-part1) — `abs-cervix-consensus-2012-part1.md`
- [#kb:gyn:cervix:abs-cervix-consensus-2012-part2](kb:gyn:cervix:abs-cervix-consensus-2012-part2) — `abs-cervix-consensus-2012-part2.md`
- [#kb:pros:hdr:abs-2022-prostate-hdr](kb:pros:hdr:abs-2022-prostate-hdr) — `abs-2022-prostate-hdr.md`
- [#kb:pros:salvage:eortc-salvage-hdr-bt-2024](kb:pros:salvage:eortc-salvage-hdr-bt-2024) — `eortc-salvage-hdr-bt-2024.md`
- [#kb:phys:afterloader:hdr-afterloader-commissioning-2024](kb:phys:afterloader:hdr-afterloader-commissioning-2024) — `hdr-afterloader-commissioning-2024.md`

### `HDR-10-Gy-2-fx` (1 entries)

- [#kb:gi:esophageal:abs-esophageal-2014](kb:gi:esophageal:abs-esophageal-2014) — `abs-esophageal-2014.md`

### `HDR-BT-3x8-Gy` (1 entries)

- [#kb:gi:rectal:opera-trial-sun-myint](kb:gi:rectal:opera-trial-sun-myint) — `opera-trial-sun-myint.md`

### `HDR-boost` (1 entries)

- [#kb:gi:rectal:rectal-recurrence-hdr](kb:gi:rectal:rectal-recurrence-hdr) — `rectal-recurrence-hdr.md`

### `HDR-cervical` (1 entries)

- [#kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt](kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt) — `deep-reinforcement-learning-hdr-bt-cervical.md`

### `HDR-gyn` (1 entries)

- [#kb:phys:iaea:iaea-3d-bt-commissioning-2020](kb:phys:iaea:iaea-3d-bt-commissioning-2020) — `iaea-3d-bt-commissioning-2020.md`

### `HDRIB` (1 entries)

- [#kb:oth:lung:brachy-trial-lung](kb:oth:lung:brachy-trial-lung) — `brachy-trial-lung.md`

### `HGG` (1 entries)

- [#kb:oth:brain_spine:gliasite-brain](kb:oth:brain_spine:gliasite-brain) — `gliasite-brain.md`

### `HIC-UMIC-LMIC-LIC` (1 entries)

- [#kb:frm:global_access:lancet-bt-global-demand-2025](kb:frm:global_access:lancet-bt-global-demand-2025) — `lancet-bt-global-demand-2025.md`

### `HR-CTV` (2 entries)

- [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](kb:gyn:cervix:embrace-i-pivotal-2021-lancet) — `embrace-i-pivotal-2021-lancet-oncol.md`
- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`

### `HR-CTV-D90` (1 entries)

- [#kb:gyn:cervix:embrace-ii-protocol](kb:gyn:cervix:embrace-ii-protocol) — `embrace-ii-protocol.md`

### `HR-CTV-definition` (1 entries)

- [#kb:gyn:cervix:gec-estro-cervix-2005-haie](kb:gyn:cervix:gec-estro-cervix-2005-haie) — `gec-estro-cervix-2005-haie-meder.md`

### `HRQOL` (1 entries)

- [#kb:pros:ldr:ascende-rt-morris-2017](kb:pros:ldr:ascende-rt-morris-2017) — `ascende-rt-morris-2017.md`

### `HVL-0.77-0.93-mm-Al` (1 entries)

- [#kb:gi:rectal:papillon-contact-xray](kb:gi:rectal:papillon-contact-xray) — `papillon-contact-xray.md`

### `I-125` (14 entries)

- [#kb:pros:ldr:salvage-prostate-bt](kb:pros:ldr:salvage-prostate-bt) — `salvage-prostate-bt.md`
- [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](kb:gi:pancreatic:3d-template-i125-pancreatic-2018) — `3d-template-i125-pancreatic-2018.md`
- [#kb:gi:pancreatic:cstro-pancreatic-i125-2017](kb:gi:pancreatic:cstro-pancreatic-i125-2017) — `cstro-pancreatic-i125-2017.md`
- [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](kb:gi:pancreatic:i125-pancreatic-guideline-2023) — `i125-pancreatic-guideline-2023.md`
- [#kb:gi:pancreatic:pancreatic-i125-clinical](kb:gi:pancreatic:pancreatic-i125-clinical) — `pancreatic-i125-clinical.md`
- [#kb:gi:pancreatic:pancreatic-i125-gemcitabine](kb:gi:pancreatic:pancreatic-i125-gemcitabine) — `pancreatic-i125-gemcitabine.md`
- [#kb:oth:eye:coms-trial-medium](kb:oth:eye:coms-trial-medium) — `coms-trial-medium.md`
- [#kb:oth:lung:ct-guided-i125-early-lung](kb:oth:lung:ct-guided-i125-early-lung) — `ct-guided-i125-early-lung-cancer.md`
- [#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis](kb:oth:brain_spine:ct-guided-i125-spinal-metastasis) — `ct-guided-i125-spinal-metastasis.md`
- [#kb:oth:malignant_general:i125-deep-hyperthermia-malignant](kb:oth:malignant_general:i125-deep-hyperthermia-malignant) — `i125-deep-hyperthermia-malignant.md`
- [#kb:phys:tg43:aapm-tg-43u1-rivard-2004](kb:phys:tg43:aapm-tg-43u1-rivard-2004) — `aapm-tg-43u1-rivard-2004.md`
- [#kb:phys:tg43:aapm-tg-43u1s1-perez-2012](kb:phys:tg43:aapm-tg-43u1s1-perez-2012) — `aapm-tg-43u1s1-perez-2012.md`
- [#kb:frm:chinese:csco-bt-chinese](kb:frm:chinese:csco-bt-chinese) — `csco-bt-chinese.md`
- [#kb:frm:chinese:cstro-bt-chinese](kb:frm:chinese:cstro-bt-chinese) — `cstro-bt-chinese.md`

### `I-125-0.3-0.8-mCi` (1 entries)

- [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](kb:gi:pancreatic:i125-pancreatic-guideline-2023) — `i125-pancreatic-guideline-2023.md`

### `I-125-balloon` (1 entries)

- [#kb:oth:brain_spine:gliasite-brain](kb:oth:brain_spine:gliasite-brain) — `gliasite-brain.md`

### `IAEA` (5 entries)

- [#kb:phys:iaea:iaea-3d-bt-commissioning-2020](kb:phys:iaea:iaea-3d-bt-commissioning-2020) — `iaea-3d-bt-commissioning-2020.md`
- [#kb:phys:iaea:iaea-trs-398](kb:phys:iaea:iaea-trs-398) — `iaea-trs-398.md`
- [#kb:frm:iaea_who:iaea-brachy-programme](kb:frm:iaea_who:iaea-brachy-programme) — `iaea-brachy-programme.md`
- [#kb:frm:iaea_who:iaea-global-bt-initiative-2020](kb:frm:iaea_who:iaea-global-bt-initiative-2020) — `iaea-global-bt-initiative-2020.md`
- [#kb:frm:global_access:iaea-india-bt-transition-2023](kb:frm:global_access:iaea-india-bt-transition-2023) — `iaea-india-bt-transition-2023.md`

### `IBTR-3.96%` (1 entries)

- [#kb:brst:apbi:abs-apbi-2013](kb:brst:apbi:abs-apbi-2013) — `abs-apbi-2013.md`

### `ICRU` (1 entries)

- [#kb:frm:global_access:icru-reports-catalogue](kb:frm:global_access:icru-reports-catalogue) — `icru-reports-catalogue.md`

### `ICRU-38` (1 entries)

- [#kb:phys:icru:icru-38-ic](kb:phys:icru:icru-38-ic) — `icru-38-ic.md`

### `ICRU-58` (1 entries)

- [#kb:phys:icru:icru-58-is](kb:phys:icru:icru-58-is) — `icru-58-is.md`

### `ICRU-89` (1 entries)

- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`

### `IG-IRT` (1 entries)

- [#kb:frm:iaea_who:who-image-guided-irt-2025](kb:frm:iaea_who:who-image-guided-irt-2025) — `who-image-guided-irt-2025.md`

### `IGABT` (1 entries)

- [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](kb:gyn:cervix:embrace-i-pivotal-2021-lancet) — `embrace-i-pivotal-2021-lancet-oncol.md`

### `IGABT-transition` (1 entries)

- [#kb:frm:global_access:iaea-india-bt-transition-2023](kb:frm:global_access:iaea-india-bt-transition-2023) — `iaea-india-bt-transition-2023.md`

### `IIIC2` (1 entries)

- [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](kb:gyn:endometrial:ars-appropriate-use-criteria-2024) — `ars-appropriate-use-criteria-2024.md`

### `ILBT` (1 entries)

- [#kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd](kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd) — `bileduct-cholangiocarcinoma-ptbd.md`

### `ILC` (1 entries)

- [#kb:brst:apbi:gec-estro-apbi-2016](kb:brst:apbi:gec-estro-apbi-2016) — `gec-estro-apbi-2016.md`

### `IMPRaCC` (1 entries)

- [#kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024](kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024) — `eortc-rt-psychosocial-2024.md`

### `IMRT` (1 entries)

- [#kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024](kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024) — `rtog-cisplatin-gem-imrt-2024.md`

### `INTERLACE` (1 entries)

- [#kb:gyn:cervix:lancet-cervical-induction-chemo-2024](kb:gyn:cervix:lancet-cervical-induction-chemo-2024) — `lancet-cervical-induction-chemo-2024.md`

### `INTRABEAM` (1 entries)

- [#kb:brst:iort:iort-electronic-bt](kb:brst:iort:iort-electronic-bt) — `iort-electronic-bt.md`

### `IOERT` (1 entries)

- [#kb:brst:apbi:abs-apbi-2013](kb:brst:apbi:abs-apbi-2013) — `abs-apbi-2013.md`

### `IORT` (2 entries)

- [#kb:brst:iort:iort-electronic-bt](kb:brst:iort:iort-electronic-bt) — `iort-electronic-bt.md`
- [#kb:brst:iort:targit-a-vaidya-2014](kb:brst:iort:targit-a-vaidya-2014) — `targit-a-vaidya-2014.md`

### `IR-CTV` (1 entries)

- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`

### `IR-CTV-definition` (1 entries)

- [#kb:gyn:cervix:gec-estro-cervix-2005-haie](kb:gyn:cervix:gec-estro-cervix-2005-haie) — `gec-estro-cervix-2005-haie-meder.md`

### `ISR` (1 entries)

- [#kb:oth:vascular:vascular-bt-sr90](kb:oth:vascular:vascular-bt-sr90) — `vascular-bt-sr90.md`

### `India` (1 entries)

- [#kb:frm:global_access:iaea-india-bt-transition-2023](kb:frm:global_access:iaea-india-bt-transition-2023) — `iaea-india-bt-transition-2023.md`

### `Intersource` (1 entries)

- [#kb:phys:tg43:aapm-tg-43u1s1-perez-2012](kb:phys:tg43:aapm-tg-43u1s1-perez-2012) — `aapm-tg-43u1s1-perez-2012.md`

### `Ir-192` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-229-mbdca](kb:phys:aapm_other:aapm-tg-229-mbdca) — `aapm-tg-229-mbdca.md`

### `KEYNOTE-A18` (1 entries)

- [#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024](kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024) — `lancet-pembrolizumab-crt-cervical-2024.md`

### `LACC` (1 entries)

- [#kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024](kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024) — `eortc-rt-psychosocial-2024.md`

### `LC-86-100%-HDR` (1 entries)

- [#kb:hns:hn_cancer:lip-cancer-bt](kb:hns:hn_cancer:lip-cancer-bt) — `lip-cancer-bt.md`

### `LC-91-100%-PDR` (1 entries)

- [#kb:hns:hn_cancer:lip-cancer-bt](kb:hns:hn_cancer:lip-cancer-bt) — `lip-cancer-bt.md`

### `LDR` (5 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](kb:gyn:cervix:abs-cervix-consensus-2012-part1) — `abs-cervix-consensus-2012-part1.md`
- [#kb:gyn:cervix:abs-vaginal-2012](kb:gyn:cervix:abs-vaginal-2012) — `abs-vaginal-2012.md`
- [#kb:pros:ldr:abs-aua-astro-ldr-2012](kb:pros:ldr:abs-aua-astro-ldr-2012) — `abs-aua-astro-ldr-2012.md`
- [#kb:pros:microboost_focal:urethra-sparing-nvb](kb:pros:microboost_focal:urethra-sparing-nvb) — `urethra-sparing-nvb.md`
- [#kb:hns:practice_param:abs-hn-2018](kb:hns:practice_param:abs-hn-2018) — `abs-hn-2018.md`

### `LDR-20-Gy` (1 entries)

- [#kb:gi:esophageal:abs-esophageal-2014](kb:gi:esophageal:abs-esophageal-2014) — `abs-esophageal-2014.md`

### `LDR-boost` (1 entries)

- [#kb:pros:ldr:ascende-rt-morris-2017](kb:pros:ldr:ascende-rt-morris-2017) — `ascende-rt-morris-2017.md`

### `LDR-permanent-seed` (1 entries)

- [#kb:pros:guidelines:aapm-tg-137-nath-2009](kb:pros:guidelines:aapm-tg-137-nath-2009) — `aapm-tg-137-nath-2009.md`

### `LMIC` (1 entries)

- [#kb:gyn:cervix:msk-bt-utilization-cervical-2025](kb:gyn:cervix:msk-bt-utilization-cervical-2025) — `msk-bt-utilization-cervical-2025.md`

### `Lancet-2025` (1 entries)

- [#kb:frm:global_access:lancet-bt-global-demand-2025](kb:frm:global_access:lancet-bt-global-demand-2025) — `lancet-bt-global-demand-2025.md`

### `MBDCA` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-229-mbdca](kb:phys:aapm_other:aapm-tg-229-mbdca) — `aapm-tg-229-mbdca.md`

### `MPD-90-130-Gy` (1 entries)

- [#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis](kb:oth:brain_spine:ct-guided-i125-spinal-metastasis) — `ct-guided-i125-spinal-metastasis.md`

### `MRI` (1 entries)

- [#kb:gyn:cervix:gec-estro-cervix-2005-haie](kb:gyn:cervix:gec-estro-cervix-2005-haie) — `gec-estro-cervix-2005-haie-meder.md`

### `MRI-based` (1 entries)

- [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](kb:gyn:cervix:embrace-i-pivotal-2021-lancet) — `embrace-i-pivotal-2021-lancet-oncol.md`

### `MTD` (1 entries)

- [#kb:phys:icru:icru-58-is](kb:phys:icru:icru-58-is) — `icru-58-is.md`

### `MammoSite` (1 entries)

- [#kb:brst:apbi:balloon-mammosite](kb:brst:apbi:balloon-mammosite) — `balloon-mammosite.md`

### `NADT` (1 entries)

- [#kb:pros:ldr:ascende-rt-morris-2017](kb:pros:ldr:ascende-rt-morris-2017) — `ascende-rt-morris-2017.md`

### `NCCN` (5 entries)

- [#kb:gyn:cervix:nccn-cervical-2024](kb:gyn:cervix:nccn-cervical-2024) — `nccn-cervical-2024.md`
- [#kb:brst:guidelines:nccn-breast-2024](kb:brst:guidelines:nccn-breast-2024) — `nccn-breast-2024.md`
- [#kb:hns:hn_cancer:nccn-hn-2024](kb:hns:hn_cancer:nccn-hn-2024) — `nccn-hn-2024.md`
- [#kb:gi:esophageal:nccn-esophageal-2024](kb:gi:esophageal:nccn-esophageal-2024) — `nccn-esophageal-2024.md`
- [#kb:frm:society_methodology:nccn-methodology](kb:frm:society_methodology:nccn-methodology) — `nccn-methodology.md`

### `NCDB-analysis` (1 entries)

- [#kb:brst:apbi:astro-2022-apbi](kb:brst:apbi:astro-2022-apbi) — `astro-2022-apbi.md`

### `NCG` (1 entries)

- [#kb:frm:global_access:iaea-india-bt-transition-2023](kb:frm:global_access:iaea-india-bt-transition-2023) — `iaea-india-bt-transition-2023.md`

### `NCT00103181` (1 entries)

- [#kb:brst:apbi:nsabp-b39-rtog-0413](kb:brst:apbi:nsabp-b39-rtog-0413) — `nsabp-b39-rtog-0413.md`

### `NCT04718987` (1 entries)

- [#kb:pros:microboost_focal:urethra-sparing-nvb](kb:pros:microboost_focal:urethra-sparing-nvb) — `urethra-sparing-nvb.md`

### `NMSC` (2 entries)

- [#kb:hns:skin:abs-skin-2020](kb:hns:skin:abs-skin-2020) — `abs-skin-2020.md`
- [#kb:hns:skin:esteya-electronic](kb:hns:skin:esteya-electronic) — `esteya-electronic.md`

### `NPC` (1 entries)

- [#kb:hns:hn_cancer:npc-intracavitary-bt](kb:hns:hn_cancer:npc-intracavitary-bt) — `npc-intracavitary-bt.md`

### `NRG` (1 entries)

- [#kb:pros:microboost_focal:nrg-microboost-prostate-2024](kb:pros:microboost_focal:nrg-microboost-prostate-2024) — `nrg-microboost-prostate-2024.md`

### `NRG-279` (1 entries)

- [#kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024](kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024) — `rtog-cisplatin-gem-imrt-2024.md`

### `NSABP-B-39` (1 entries)

- [#kb:brst:apbi:nsabp-b39-rtog-0413](kb:brst:apbi:nsabp-b39-rtog-0413) — `nsabp-b39-rtog-0413.md`

### `NSCLC` (1 entries)

- [#kb:oth:lung:brachy-trial-lung](kb:oth:lung:brachy-trial-lung) — `brachy-trial-lung.md`

### `NSMP-CTNNB1` (1 entries)

- [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](kb:gyn:endometrial:lancet-molecular-endometrial-2024) — `lancet-molecular-endometrial-2024.md`

### `Nature-Reviews` (1 entries)

- [#kb:brst:apbi:nature-apbi-alternative-wbi-2020](kb:brst:apbi:nature-apbi-alternative-wbi-2020) — `nature-apbi-alternative-wbi-2020.md`

### `Nigeria` (1 entries)

- [#kb:gyn:cervix:msk-bt-utilization-cervical-2025](kb:gyn:cervix:msk-bt-utilization-cervical-2025) — `msk-bt-utilization-cervical-2025.md`

### `OAR` (1 entries)

- [#kb:gyn:cervix:dimopoulos-mri-ctv-2012](kb:gyn:cervix:dimopoulos-mri-ctv-2012) — `dimopoulos-mri-ctv-2012.md`

### `OAR-constraints` (1 entries)

- [#kb:gyn:cervix:embrace-ii-protocol](kb:gyn:cervix:embrace-ii-protocol) — `embrace-ii-protocol.md`

### `OPERA` (1 entries)

- [#kb:gi:rectal:opera-trial-sun-myint](kb:gi:rectal:opera-trial-sun-myint) — `opera-trial-sun-myint.md`

### `ORR-73.33%` (1 entries)

- [#kb:oth:malignant_general:i125-deep-hyperthermia-malignant](kb:oth:malignant_general:i125-deep-hyperthermia-malignant) — `i125-deep-hyperthermia-malignant.md`

### `PDR` (2 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](kb:gyn:cervix:abs-cervix-consensus-2012-part1) — `abs-cervix-consensus-2012-part1.md`
- [#kb:gyn:cervix:abs-vaginal-2012](kb:gyn:cervix:abs-vaginal-2012) — `abs-vaginal-2012.md`

### `PDR-HDR` (1 entries)

- [#kb:phys:icru:icru-58-is](kb:phys:icru:icru-58-is) — `icru-58-is.md`

### `PDR-task-force` (1 entries)

- [#kb:gi:anal:gec-estro-anal-bt-2018](kb:gi:anal:gec-estro-anal-bt-2018) — `gec-estro-anal-bt-2018.md`

### `PDR-to-HDR-transition` (1 entries)

- [#kb:pros:penile:gec-estro-penile-2018](kb:pros:penile:gec-estro-penile-2018) — `gec-estro-penile-2018.md`

### `PDR-vs-HDR` (1 entries)

- [#kb:hns:hn_cancer:lip-cancer-bt](kb:hns:hn_cancer:lip-cancer-bt) — `lip-cancer-bt.md`

### `PIF` (1 entries)

- [#kb:gyn:vaginal_vulvar:abs-vulvar-2019](kb:gyn:vaginal_vulvar:abs-vulvar-2019) — `abs-vulvar-2019.md`

### `POLE-mut` (1 entries)

- [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](kb:gyn:endometrial:lancet-molecular-endometrial-2024) — `lancet-molecular-endometrial-2024.md`

### `PORTEC-2` (1 entries)

- [#kb:gyn:endometrial:portec-2-lancet-2010](kb:gyn:endometrial:portec-2-lancet-2010) — `portec-2-lancet-2010.md`

### `PORTEC-3` (1 entries)

- [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](kb:gyn:endometrial:ars-appropriate-use-criteria-2024) — `ars-appropriate-use-criteria-2024.md`

### `PORTEC-4a` (1 entries)

- [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](kb:gyn:endometrial:lancet-molecular-endometrial-2024) — `lancet-molecular-endometrial-2024.md`

### `PRIAPUS-trial` (1 entries)

- [#kb:pros:microboost_focal:urethra-sparing-nvb](kb:pros:microboost_focal:urethra-sparing-nvb) — `urethra-sparing-nvb.md`

### `PTCD` (1 entries)

- [#kb:gi:pancreatic:pancreatic-i125-gemcitabine](kb:gi:pancreatic:pancreatic-i125-gemcitabine) — `pancreatic-i125-gemcitabine.md`

### `PTV-GTV+1cm` (1 entries)

- [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](kb:gi:pancreatic:i125-pancreatic-guideline-2023) — `i125-pancreatic-guideline-2023.md`

### `Papillon+` (1 entries)

- [#kb:gi:rectal:papillon-contact-xray](kb:gi:rectal:papillon-contact-xray) — `papillon-contact-xray.md`

### `Pd-103` (1 entries)

- [#kb:phys:tg43:aapm-tg-43u1-rivard-2004](kb:phys:tg43:aapm-tg-43u1-rivard-2004) — `aapm-tg-43u1-rivard-2004.md`

### `QA` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-148-hdr-qa](kb:phys:aapm_other:aapm-tg-148-hdr-qa) — `aapm-tg-148-hdr-qa.md`

### `QA-phantoms` (1 entries)

- [#kb:phys:3d_printing:nature-3d-printing-rt-2020](kb:phys:3d_printing:nature-3d-printing-rt-2020) — `nature-3d-printing-rt-2020.md`

### `QOL` (1 entries)

- [#kb:brst:apbi:nsabp-b39-rtog-0413](kb:brst:apbi:nsabp-b39-rtog-0413) — `nsabp-b39-rtog-0413.md`

### `QUATRO` (1 entries)

- [#kb:frm:iaea_who:iaea-global-bt-initiative-2020](kb:frm:iaea_who:iaea-global-bt-initiative-2020) — `iaea-global-bt-initiative-2020.md`

### `QoL` (1 entries)

- [#kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024](kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024) — `eortc-rt-psychosocial-2024.md`

### `RTOG-0413` (1 entries)

- [#kb:brst:apbi:nsabp-b39-rtog-0413](kb:brst:apbi:nsabp-b39-rtog-0413) — `nsabp-b39-rtog-0413.md`

### `ReCOG` (1 entries)

- [#kb:brst:reirradiation:breast-reirradiation-survey-2024](kb:brst:reirradiation:breast-reirradiation-survey-2024) — `breast-reirradiation-survey-2024.md`

### `SAVI` (1 entries)

- [#kb:brst:apbi:savi-strut-apbi](kb:brst:apbi:savi-strut-apbi) — `savi-strut-apbi.md`

### `SBRT-vs-HDR` (1 entries)

- [#kb:pros:hdr:jama-sbrt-vs-hdr-bt](kb:pros:hdr:jama-sbrt-vs-hdr-bt) — `jama-sbrt-vs-hdr-bt-prostate-2025.md`

### `SMARTEPANTS` (1 entries)

- [#kb:phys:tg43:aapm-tg-43u1s1-perez-2012](kb:phys:tg43:aapm-tg-43u1s1-perez-2012) — `aapm-tg-43u1s1-perez-2012.md`

### `STARTREC-3` (1 entries)

- [#kb:gi:rectal:bmj-watchful-waiting-rectal-2025](kb:gi:rectal:bmj-watchful-waiting-rectal-2025) — `bmj-watchful-waiting-rectal-2025.md`

### `Sr-90` (1 entries)

- [#kb:oth:vascular:vascular-bt-sr90](kb:oth:vascular:vascular-bt-sr90) — `vascular-bt-sr90.md`

### `TARGIT-A` (1 entries)

- [#kb:brst:iort:targit-a-vaidya-2014](kb:brst:iort:targit-a-vaidya-2014) — `targit-a-vaidya-2014.md`

### `TARGIT-X` (1 entries)

- [#kb:brst:iort:targit-a-vaidya-2014](kb:brst:iort:targit-a-vaidya-2014) — `targit-a-vaidya-2014.md`

### `TG-229` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-229-mbdca](kb:phys:aapm_other:aapm-tg-229-mbdca) — `aapm-tg-229-mbdca.md`

### `TG-232` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-232-film](kb:phys:aapm_other:aapm-tg-232-film) — `aapm-tg-232-film.md`

### `TG-43` (1 entries)

- [#kb:phys:tg43:aapm-tg-43-nath-1995](kb:phys:tg43:aapm-tg-43-nath-1995) — `aapm-tg-43-nath-1995.md`

### `TG-43U1` (1 entries)

- [#kb:phys:tg43:aapm-tg-43u1-rivard-2004](kb:phys:tg43:aapm-tg-43u1-rivard-2004) — `aapm-tg-43u1-rivard-2004.md`

### `TG-43U1S1` (1 entries)

- [#kb:phys:tg43:aapm-tg-43u1s1-perez-2012](kb:phys:tg43:aapm-tg-43u1s1-perez-2012) — `aapm-tg-43u1s1-perez-2012.md`

### `TPS-commissioning` (1 entries)

- [#kb:phys:iaea:iaea-3d-bt-commissioning-2020](kb:phys:iaea:iaea-3d-bt-commissioning-2020) — `iaea-3d-bt-commissioning-2020.md`

### `TRS-398` (1 entries)

- [#kb:phys:iaea:iaea-trs-398](kb:phys:iaea:iaea-trs-398) — `iaea-trs-398.md`

### `TRUS` (1 entries)

- [#kb:pros:ldr:abs-aua-astro-ldr-2012](kb:pros:ldr:abs-aua-astro-ldr-2012) — `abs-aua-astro-ldr-2012.md`

### `U-Net` (1 entries)

- [#kb:pros:hdr:real-time-trus-planning](kb:pros:hdr:real-time-trus-planning) — `real-time-trus-planning.md`

### `UroGEC` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-148-hdr-qa](kb:phys:aapm_other:aapm-tg-148-hdr-qa) — `aapm-tg-148-hdr-qa.md`

### `V100-91.05%-Group-A-vs-72.91%-Group-B` (1 entries)

- [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](kb:gi:pancreatic:3d-template-i125-pancreatic-2018) — `3d-template-i125-pancreatic-2018.md`

### `VBT-21-Gy-3fx` (1 entries)

- [#kb:gyn:endometrial:portec-2-lancet-2010](kb:gyn:endometrial:portec-2-lancet-2010) — `portec-2-lancet-2010.md`

### `WBI-alternative` (1 entries)

- [#kb:brst:apbi:nature-apbi-alternative-wbi-2020](kb:brst:apbi:nature-apbi-alternative-wbi-2020) — `nature-apbi-alternative-wbi-2020.md`

### `WHO` (1 entries)

- [#kb:frm:iaea_who:who-image-guided-irt-2025](kb:frm:iaea_who:who-image-guided-irt-2025) — `who-image-guided-irt-2025.md`

### `absorbed-dose` (1 entries)

- [#kb:phys:iaea:iaea-trs-398](kb:phys:iaea:iaea-trs-398) — `iaea-trs-398.md`

### `advanced` (1 entries)

- [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](kb:gyn:endometrial:ars-appropriate-use-criteria-2024) — `ars-appropriate-use-criteria-2024.md`

### `afterloader` (1 entries)

- [#kb:phys:afterloader:hdr-afterloader-commissioning-2024](kb:phys:afterloader:hdr-afterloader-commissioning-2024) — `hdr-afterloader-commissioning-2024.md`

### `air-kerma-strength` (1 entries)

- [#kb:phys:tg43:aapm-tg-43u1-rivard-2004](kb:phys:tg43:aapm-tg-43u1-rivard-2004) — `aapm-tg-43u1-rivard-2004.md`

### `anal` (1 entries)

- [#kb:gi:anal:gec-estro-anal-bt-2018](kb:gi:anal:gec-estro-anal-bt-2018) — `gec-estro-anal-bt-2018.md`

### `applicator` (1 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part2](kb:gyn:cervix:abs-cervix-consensus-2012-part2) — `abs-cervix-consensus-2012-part2.md`

### `applicator-6-10-mm` (1 entries)

- [#kb:gi:esophageal:abs-esophageal-2014](kb:gi:esophageal:abs-esophageal-2014) — `abs-esophageal-2014.md`

### `applicators` (1 entries)

- [#kb:phys:3d_printing:nature-3d-printing-rt-2020](kb:phys:3d_printing:nature-3d-printing-rt-2020) — `nature-3d-printing-rt-2020.md`

### `balloon` (1 entries)

- [#kb:brst:apbi:balloon-mammosite](kb:brst:apbi:balloon-mammosite) — `balloon-mammosite.md`

### `biliary` (1 entries)

- [#kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd](kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd) — `bileduct-cholangiocarcinoma-ptbd.md`

### `bolus` (1 entries)

- [#kb:phys:3d_printing:nature-3d-printing-rt-2020](kb:phys:3d_printing:nature-3d-printing-rt-2020) — `nature-3d-printing-rt-2020.md`

### `boost` (3 entries)

- [#kb:pros:hdr:abs-2022-prostate-hdr](kb:pros:hdr:abs-2022-prostate-hdr) — `abs-2022-prostate-hdr.md`
- [#kb:brst:apbi:estro-acrop-breast-2018](kb:brst:apbi:estro-acrop-breast-2018) — `estro-acrop-breast-2018.md`
- [#kb:brst:boost:wbi-boost-eortc-22881](kb:brst:boost:wbi-boost-eortc-22881) — `wbi-boost-eortc-22881.md`

### `brachytherapy-programme` (1 entries)

- [#kb:frm:iaea_who:iaea-brachy-programme](kb:frm:iaea_who:iaea-brachy-programme) — `iaea-brachy-programme.md`

### `brain` (2 entries)

- [#kb:oth:brain_spine:gammatile-brain](kb:oth:brain_spine:gammatile-brain) — `gammatile-brain.md`
- [#kb:oth:brain_spine:gliasite-brain](kb:oth:brain_spine:gliasite-brain) — `gliasite-brain.md`

### `breast` (13 entries)

- [#kb:brst:apbi:abs-apbi-2013](kb:brst:apbi:abs-apbi-2013) — `abs-apbi-2013.md`
- [#kb:brst:apbi:astro-2022-apbi](kb:brst:apbi:astro-2022-apbi) — `astro-2022-apbi.md`
- [#kb:brst:apbi:balloon-mammosite](kb:brst:apbi:balloon-mammosite) — `balloon-mammosite.md`
- [#kb:brst:reirradiation:breast-reirradiation-survey-2024](kb:brst:reirradiation:breast-reirradiation-survey-2024) — `breast-reirradiation-survey-2024.md`
- [#kb:brst:apbi:estro-acrop-breast-2018](kb:brst:apbi:estro-acrop-breast-2018) — `estro-acrop-breast-2018.md`
- [#kb:brst:apbi:gec-estro-apbi-2016](kb:brst:apbi:gec-estro-apbi-2016) — `gec-estro-apbi-2016.md`
- [#kb:brst:iort:iort-electronic-bt](kb:brst:iort:iort-electronic-bt) — `iort-electronic-bt.md`
- [#kb:brst:apbi:nature-apbi-alternative-wbi-2020](kb:brst:apbi:nature-apbi-alternative-wbi-2020) — `nature-apbi-alternative-wbi-2020.md`
- [#kb:brst:guidelines:nccn-breast-2024](kb:brst:guidelines:nccn-breast-2024) — `nccn-breast-2024.md`
- [#kb:brst:apbi:nsabp-b39-rtog-0413](kb:brst:apbi:nsabp-b39-rtog-0413) — `nsabp-b39-rtog-0413.md`
- [#kb:brst:apbi:savi-strut-apbi](kb:brst:apbi:savi-strut-apbi) — `savi-strut-apbi.md`
- [#kb:brst:iort:targit-a-vaidya-2014](kb:brst:iort:targit-a-vaidya-2014) — `targit-a-vaidya-2014.md`
- [#kb:brst:boost:wbi-boost-eortc-22881](kb:brst:boost:wbi-boost-eortc-22881) — `wbi-boost-eortc-22881.md`

### `carboplatin-paclitaxel` (1 entries)

- [#kb:gyn:cervix:lancet-cervical-induction-chemo-2024](kb:gyn:cervix:lancet-cervical-induction-chemo-2024) — `lancet-cervical-induction-chemo-2024.md`

### `cardiac` (1 entries)

- [#kb:oth:vascular:cardiac-vascular-review](kb:oth:vascular:cardiac-vascular-review) — `cardiac-vascular-review.md`

### `case-report` (1 entries)

- [#kb:gi:pancreatic:pancreatic-i125-gemcitabine](kb:gi:pancreatic:pancreatic-i125-gemcitabine) — `pancreatic-i125-gemcitabine.md`

### `cervical` (1 entries)

- [#kb:hns:practice_param:abs-hn-2018](kb:hns:practice_param:abs-hn-2018) — `abs-hn-2018.md`

### `cervical-cancer` (1 entries)

- [#kb:frm:iaea_who:iaea-global-bt-initiative-2020](kb:frm:iaea_who:iaea-global-bt-initiative-2020) — `iaea-global-bt-initiative-2020.md`

### `cervical-recurrence` (1 entries)

- [#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024](kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024) — `gec-estro-endometrial-2024.md`

### `cervix` (13 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](kb:gyn:cervix:abs-cervix-consensus-2012-part1) — `abs-cervix-consensus-2012-part1.md`
- [#kb:gyn:cervix:abs-cervix-consensus-2012-part2](kb:gyn:cervix:abs-cervix-consensus-2012-part2) — `abs-cervix-consensus-2012-part2.md`
- [#kb:gyn:cervix:abs-vaginal-2012](kb:gyn:cervix:abs-vaginal-2012) — `abs-vaginal-2012.md`
- [#kb:gyn:cervix:dimopoulos-mri-ctv-2012](kb:gyn:cervix:dimopoulos-mri-ctv-2012) — `dimopoulos-mri-ctv-2012.md`
- [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](kb:gyn:cervix:embrace-i-pivotal-2021-lancet) — `embrace-i-pivotal-2021-lancet-oncol.md`
- [#kb:gyn:cervix:embrace-ii-protocol](kb:gyn:cervix:embrace-ii-protocol) — `embrace-ii-protocol.md`
- [#kb:gyn:cervix:gec-estro-cervix-2005-haie](kb:gyn:cervix:gec-estro-cervix-2005-haie) — `gec-estro-cervix-2005-haie-meder.md`
- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`
- [#kb:gyn:cervix:lancet-cervical-induction-chemo-2024](kb:gyn:cervix:lancet-cervical-induction-chemo-2024) — `lancet-cervical-induction-chemo-2024.md`
- [#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024](kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024) — `lancet-pembrolizumab-crt-cervical-2024.md`
- [#kb:gyn:cervix:msk-bt-utilization-cervical-2025](kb:gyn:cervix:msk-bt-utilization-cervical-2025) — `msk-bt-utilization-cervical-2025.md`
- [#kb:gyn:cervix:nccn-cervical-2024](kb:gyn:cervix:nccn-cervical-2024) — `nccn-cervical-2024.md`
- [#kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024](kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024) — `eortc-rt-psychosocial-2024.md`

### `chemoradiotherapy` (2 entries)

- [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](kb:gyn:cervix:embrace-i-pivotal-2021-lancet) — `embrace-i-pivotal-2021-lancet-oncol.md`
- [#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024](kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024) — `lancet-pembrolizumab-crt-cervical-2024.md`

### `cholangiocarcinoma` (1 entries)

- [#kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd](kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd) — `bileduct-cholangiocarcinoma-ptbd.md`

### `choroidal` (1 entries)

- [#kb:oth:eye:coms-trial-medium](kb:oth:eye:coms-trial-medium) — `coms-trial-medium.md`

### `cisplatin-gemcitabine` (1 entries)

- [#kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024](kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024) — `rtog-cisplatin-gem-imrt-2024.md`

### `clinical-practice-guideline` (1 entries)

- [#kb:frm:society_methodology:astro-methodology](kb:frm:society_methodology:astro-methodology) — `astro-methodology.md`

### `clinically-localized` (1 entries)

- [#kb:pros:guidelines:aua-astro-2022-prostate](kb:pros:guidelines:aua-astro-2022-prostate) — `aua-astro-2022-prostate.md`

### `combined-EBRT` (1 entries)

- [#kb:pros:ldr:salvage-prostate-bt](kb:pros:ldr:salvage-prostate-bt) — `salvage-prostate-bt.md`

### `commissioning` (1 entries)

- [#kb:phys:afterloader:hdr-afterloader-commissioning-2024](kb:phys:afterloader:hdr-afterloader-commissioning-2024) — `hdr-afterloader-commissioning-2024.md`

### `competency` (1 entries)

- [#kb:pros:hdr:abs-2022-prostate-hdr](kb:pros:hdr:abs-2022-prostate-hdr) — `abs-2022-prostate-hdr.md`

### `consensus` (8 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](kb:gyn:cervix:abs-cervix-consensus-2012-part1) — `abs-cervix-consensus-2012-part1.md`
- [#kb:gyn:cervix:abs-cervix-consensus-2012-part2](kb:gyn:cervix:abs-cervix-consensus-2012-part2) — `abs-cervix-consensus-2012-part2.md`
- [#kb:gyn:cervix:abs-vaginal-2012](kb:gyn:cervix:abs-vaginal-2012) — `abs-vaginal-2012.md`
- [#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024](kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024) — `gec-estro-endometrial-2024.md`
- [#kb:hns:skin:abs-skin-2020](kb:hns:skin:abs-skin-2020) — `abs-skin-2020.md`
- [#kb:gi:esophageal:abs-esophageal-2014](kb:gi:esophageal:abs-esophageal-2014) — `abs-esophageal-2014.md`
- [#kb:oth:sarcoma:abs-sarcoma-bt](kb:oth:sarcoma:abs-sarcoma-bt) — `abs-sarcoma-bt.md`
- [#kb:oth:lung:endobronchial-bt-consensus](kb:oth:lung:endobronchial-bt-consensus) — `endobronchial-bt-consensus.md`

### `contact-X-ray` (1 entries)

- [#kb:gi:rectal:papillon-contact-xray](kb:gi:rectal:papillon-contact-xray) — `papillon-contact-xray.md`

### `contact-X-ray-BT` (1 entries)

- [#kb:gi:rectal:bmj-watchful-waiting-rectal-2025](kb:gi:rectal:bmj-watchful-waiting-rectal-2025) — `bmj-watchful-waiting-rectal-2025.md`

### `core-competencies` (1 entries)

- [#kb:hns:skin:gec-estro-skin-2018](kb:hns:skin:gec-estro-skin-2018) — `gec-estro-skin-2018.md`

### `dMMR` (2 entries)

- [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](kb:gyn:endometrial:ars-appropriate-use-criteria-2024) — `ars-appropriate-use-criteria-2024.md`
- [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](kb:gyn:endometrial:lancet-molecular-endometrial-2024) — `lancet-molecular-endometrial-2024.md`

### `deep-hyperthermia` (1 entries)

- [#kb:oth:malignant_general:i125-deep-hyperthermia-malignant](kb:oth:malignant_general:i125-deep-hyperthermia-malignant) — `i125-deep-hyperthermia-malignant.md`

### `deep-learning` (1 entries)

- [#kb:pros:hdr:real-time-trus-planning](kb:pros:hdr:real-time-trus-planning) — `real-time-trus-planning.md`

### `deep-reinforcement-learning` (1 entries)

- [#kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt](kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt) — `deep-reinforcement-learning-hdr-bt-cervical.md`

### `demand-supply` (1 entries)

- [#kb:frm:global_access:lancet-bt-global-demand-2025](kb:frm:global_access:lancet-bt-global-demand-2025) — `lancet-bt-global-demand-2025.md`

### `digitization-uncertainty` (1 entries)

- [#kb:brst:apbi:savi-strut-apbi](kb:brst:apbi:savi-strut-apbi) — `savi-strut-apbi.md`

### `dose-80-90-Gy` (3 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](kb:gyn:cervix:abs-cervix-consensus-2012-part1) — `abs-cervix-consensus-2012-part1.md`
- [#kb:gyn:cervix:abs-cervix-consensus-2012-part2](kb:gyn:cervix:abs-cervix-consensus-2012-part2) — `abs-cervix-consensus-2012-part2.md`
- [#kb:gyn:cervix:abs-vaginal-2012](kb:gyn:cervix:abs-vaginal-2012) — `abs-vaginal-2012.md`

### `dose-prescription` (1 entries)

- [#kb:pros:guidelines:aapm-tg-137-nath-2009](kb:pros:guidelines:aapm-tg-137-nath-2009) — `aapm-tg-137-nath-2009.md`

### `dose-reporting` (1 entries)

- [#kb:gyn:cervix:icru-89-gyn](kb:gyn:cervix:icru-89-gyn) — `icru-89-gyn.md`

### `dosimetric-comparison` (2 entries)

- [#kb:pros:hdr:focal-prostate-hdr](kb:pros:hdr:focal-prostate-hdr) — `focal-prostate-hdr.md`
- [#kb:brst:iort:iort-electronic-bt](kb:brst:iort:iort-electronic-bt) — `iort-electronic-bt.md`

### `dosimetry` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-232-film](kb:phys:aapm_other:aapm-tg-232-film) — `aapm-tg-232-film.md`

### `early-stage` (1 entries)

- [#kb:oth:lung:ct-guided-i125-early-lung](kb:oth:lung:ct-guided-i125-early-lung) — `ct-guided-i125-early-lung-cancer.md`

### `elderly-frail` (1 entries)

- [#kb:gi:rectal:opera-trial-sun-myint](kb:gi:rectal:opera-trial-sun-myint) — `opera-trial-sun-myint.md`

### `electronic-BT` (1 entries)

- [#kb:hns:skin:esteya-electronic](kb:hns:skin:esteya-electronic) — `esteya-electronic.md`

### `endobronchial` (2 entries)

- [#kb:oth:lung:brachy-trial-lung](kb:oth:lung:brachy-trial-lung) — `brachy-trial-lung.md`
- [#kb:oth:lung:endobronchial-bt-consensus](kb:oth:lung:endobronchial-bt-consensus) — `endobronchial-bt-consensus.md`

### `endoluminal-HDR` (1 entries)

- [#kb:gi:rectal:opera-trial-sun-myint](kb:gi:rectal:opera-trial-sun-myint) — `opera-trial-sun-myint.md`

### `endometrial` (3 entries)

- [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](kb:gyn:endometrial:ars-appropriate-use-criteria-2024) — `ars-appropriate-use-criteria-2024.md`
- [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](kb:gyn:endometrial:lancet-molecular-endometrial-2024) — `lancet-molecular-endometrial-2024.md`
- [#kb:gyn:endometrial:portec-2-lancet-2010](kb:gyn:endometrial:portec-2-lancet-2010) — `portec-2-lancet-2010.md`

### `endometrial-recurrence` (1 entries)

- [#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024](kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024) — `gec-estro-endometrial-2024.md`

### `erratum` (1 entries)

- [#kb:pros:guidelines:aapm-tg-137-nath-2009](kb:pros:guidelines:aapm-tg-137-nath-2009) — `aapm-tg-137-nath-2009.md`

### `esophageal` (2 entries)

- [#kb:gi:esophageal:abs-esophageal-2014](kb:gi:esophageal:abs-esophageal-2014) — `abs-esophageal-2014.md`
- [#kb:gi:esophageal:nccn-esophageal-2024](kb:gi:esophageal:nccn-esophageal-2024) — `nccn-esophageal-2024.md`

### `ethics` (1 entries)

- [#kb:frm:society_methodology:aapm-about](kb:frm:society_methodology:aapm-about) — `aapm-about.md`

### `external-beam` (1 entries)

- [#kb:phys:iaea:iaea-trs-398](kb:phys:iaea:iaea-trs-398) — `iaea-trs-398.md`

### `eye` (2 entries)

- [#kb:oth:eye:aapm-tg-129-uveal-melanoma](kb:oth:eye:aapm-tg-129-uveal-melanoma) — `aapm-tg-129-uveal-melanoma.md`
- [#kb:oth:eye:coms-trial-medium](kb:oth:eye:coms-trial-medium) — `coms-trial-medium.md`

### `focal-HDR` (1 entries)

- [#kb:pros:hdr:focal-prostate-hdr](kb:pros:hdr:focal-prostate-hdr) — `focal-prostate-hdr.md`

### `foundation-paper` (1 entries)

- [#kb:gyn:cervix:gec-estro-cervix-2005-haie](kb:gyn:cervix:gec-estro-cervix-2005-haie) — `gec-estro-cervix-2005-haie-meder.md`

### `gastric` (1 entries)

- [#kb:gi:gastric:gastric-bt](kb:gi:gastric:gastric-bt) — `gastric-bt.md`

### `gemcitabine` (1 entries)

- [#kb:gi:pancreatic:pancreatic-i125-gemcitabine](kb:gi:pancreatic:pancreatic-i125-gemcitabine) — `pancreatic-i125-gemcitabine.md`

### `general-principles` (1 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](kb:gyn:cervix:abs-cervix-consensus-2012-part1) — `abs-cervix-consensus-2012-part1.md`

### `geometric-accuracy` (1 entries)

- [#kb:hns:skin:freiburg-flap-ham](kb:hns:skin:freiburg-flap-ham) — `freiburg-flap-ham.md`

### `glioma` (1 entries)

- [#kb:oth:brain_spine:gliasite-brain](kb:oth:brain_spine:gliasite-brain) — `gliasite-brain.md`

### `global-access` (1 entries)

- [#kb:frm:global_access:lancet-bt-global-demand-2025](kb:frm:global_access:lancet-bt-global-demand-2025) — `lancet-bt-global-demand-2025.md`

### `global-initiative` (1 entries)

- [#kb:frm:iaea_who:iaea-global-bt-initiative-2020](kb:frm:iaea_who:iaea-global-bt-initiative-2020) — `iaea-global-bt-initiative-2020.md`

### `guideline` (4 entries)

- [#kb:gyn:cervix:nccn-cervical-2024](kb:gyn:cervix:nccn-cervical-2024) — `nccn-cervical-2024.md`
- [#kb:brst:guidelines:nccn-breast-2024](kb:brst:guidelines:nccn-breast-2024) — `nccn-breast-2024.md`
- [#kb:hns:hn_cancer:nccn-hn-2024](kb:hns:hn_cancer:nccn-hn-2024) — `nccn-hn-2024.md`
- [#kb:gi:esophageal:nccn-esophageal-2024](kb:gi:esophageal:nccn-esophageal-2024) — `nccn-esophageal-2024.md`

### `guideline-amendment` (1 entries)

- [#kb:pros:guidelines:aua-astro-2022-prostate](kb:pros:guidelines:aua-astro-2022-prostate) — `aua-astro-2022-prostate.md`

### `guideline-development` (1 entries)

- [#kb:frm:society_methodology:nccn-methodology](kb:frm:society_methodology:nccn-methodology) — `nccn-methodology.md`

### `guideline-methodology` (2 entries)

- [#kb:frm:society_methodology:aapm-about](kb:frm:society_methodology:aapm-about) — `aapm-about.md`
- [#kb:frm:society_methodology:abs-mission](kb:frm:society_methodology:abs-mission) — `abs-mission.md`

### `gynec` (1 entries)

- [#kb:phys:icru:icru-38-ic](kb:phys:icru:icru-38-ic) — `icru-38-ic.md`

### `head-neck` (5 entries)

- [#kb:hns:practice_param:abs-hn-2018](kb:hns:practice_param:abs-hn-2018) — `abs-hn-2018.md`
- [#kb:hns:hn_cancer:gec-estro-hn](kb:hns:hn_cancer:gec-estro-hn) — `gec-estro-hn.md`
- [#kb:hns:hn_cancer:lip-cancer-bt](kb:hns:hn_cancer:lip-cancer-bt) — `lip-cancer-bt.md`
- [#kb:hns:hn_cancer:nccn-hn-2024](kb:hns:hn_cancer:nccn-hn-2024) — `nccn-hn-2024.md`
- [#kb:hns:hn_cancer:npc-intracavitary-bt](kb:hns:hn_cancer:npc-intracavitary-bt) — `npc-intracavitary-bt.md`

### `hemigland` (1 entries)

- [#kb:pros:hdr:focal-prostate-hdr](kb:pros:hdr:focal-prostate-hdr) — `focal-prostate-hdr.md`

### `high-risk` (1 entries)

- [#kb:pros:ldr:abs-aua-astro-ldr-2012](kb:pros:ldr:abs-aua-astro-ldr-2012) — `abs-aua-astro-ldr-2012.md`

### `immunotherapy` (1 entries)

- [#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024](kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024) — `lancet-pembrolizumab-crt-cervical-2024.md`

### `induction-chemotherapy` (1 entries)

- [#kb:gyn:cervix:lancet-cervical-induction-chemo-2024](kb:gyn:cervix:lancet-cervical-induction-chemo-2024) — `lancet-cervical-induction-chemo-2024.md`

### `interfraction-variation` (1 entries)

- [#kb:gyn:cervix:dimopoulos-mri-ctv-2012](kb:gyn:cervix:dimopoulos-mri-ctv-2012) — `dimopoulos-mri-ctv-2012.md`

### `intermediate-risk` (1 entries)

- [#kb:pros:hdr:jama-sbrt-vs-hdr-bt](kb:pros:hdr:jama-sbrt-vs-hdr-bt) — `jama-sbrt-vs-hdr-bt-prostate-2025.md`

### `international-survey` (1 entries)

- [#kb:brst:reirradiation:breast-reirradiation-survey-2024](kb:brst:reirradiation:breast-reirradiation-survey-2024) — `breast-reirradiation-survey-2024.md`

### `interstitial` (3 entries)

- [#kb:brst:apbi:estro-acrop-breast-2018](kb:brst:apbi:estro-acrop-breast-2018) — `estro-acrop-breast-2018.md`
- [#kb:phys:tg43:aapm-tg-43-nath-1995](kb:phys:tg43:aapm-tg-43-nath-1995) — `aapm-tg-43-nath-1995.md`
- [#kb:phys:icru:icru-58-is](kb:phys:icru:icru-58-is) — `icru-58-is.md`

### `intracavitary` (2 entries)

- [#kb:hns:hn_cancer:npc-intracavitary-bt](kb:hns:hn_cancer:npc-intracavitary-bt) — `npc-intracavitary-bt.md`
- [#kb:phys:icru:icru-38-ic](kb:phys:icru:icru-38-ic) — `icru-38-ic.md`

### `invasive-lobular` (1 entries)

- [#kb:brst:apbi:gec-estro-apbi-2016](kb:brst:apbi:gec-estro-apbi-2016) — `gec-estro-apbi-2016.md`

### `inverse-planning` (1 entries)

- [#kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt](kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt) — `deep-reinforcement-learning-hdr-bt-cervical.md`

### `keloid` (1 entries)

- [#kb:hns:keloid:keloid-bt](kb:hns:keloid:keloid-bt) — `keloid-bt.md`

### `late-toxicity` (1 entries)

- [#kb:gyn:vaginal_vulvar:abs-vulvar-2019](kb:gyn:vaginal_vulvar:abs-vulvar-2019) — `abs-vulvar-2019.md`

### `lip` (1 entries)

- [#kb:hns:hn_cancer:lip-cancer-bt](kb:hns:hn_cancer:lip-cancer-bt) — `lip-cancer-bt.md`

### `low-risk` (1 entries)

- [#kb:pros:ldr:abs-aua-astro-ldr-2012](kb:pros:ldr:abs-aua-astro-ldr-2012) — `abs-aua-astro-ldr-2012.md`

### `lumpectomy` (1 entries)

- [#kb:brst:boost:wbi-boost-eortc-22881](kb:brst:boost:wbi-boost-eortc-22881) — `wbi-boost-eortc-22881.md`

### `lung` (3 entries)

- [#kb:oth:lung:brachy-trial-lung](kb:oth:lung:brachy-trial-lung) — `brachy-trial-lung.md`
- [#kb:oth:lung:ct-guided-i125-early-lung](kb:oth:lung:ct-guided-i125-early-lung) — `ct-guided-i125-early-lung-cancer.md`
- [#kb:oth:lung:endobronchial-bt-consensus](kb:oth:lung:endobronchial-bt-consensus) — `endobronchial-bt-consensus.md`

### `lymphedema` (1 entries)

- [#kb:gyn:vaginal_vulvar:abs-vulvar-2019](kb:gyn:vaginal_vulvar:abs-vulvar-2019) — `abs-vulvar-2019.md`

### `malignant` (1 entries)

- [#kb:oth:malignant_general:i125-deep-hyperthermia-malignant](kb:oth:malignant_general:i125-deep-hyperthermia-malignant) — `i125-deep-hyperthermia-malignant.md`

### `meta-analysis` (2 entries)

- [#kb:pros:penile:nature-bt-penile-organ-preservation](kb:pros:penile:nature-bt-penile-organ-preservation) — `nature-bt-penile-organ-preservation-2015.md`
- [#kb:gi:anal:gec-estro-anal-bt-2018](kb:gi:anal:gec-estro-anal-bt-2018) — `gec-estro-anal-bt-2018.md`

### `meta-regression` (1 entries)

- [#kb:hns:keloid:keloid-bt](kb:hns:keloid:keloid-bt) — `keloid-bt.md`

### `metastasis` (1 entries)

- [#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis](kb:oth:brain_spine:ct-guided-i125-spinal-metastasis) — `ct-guided-i125-spinal-metastasis.md`

### `methodology` (2 entries)

- [#kb:frm:society_methodology:astro-methodology](kb:frm:society_methodology:astro-methodology) — `astro-methodology.md`
- [#kb:frm:society_methodology:nccn-methodology](kb:frm:society_methodology:nccn-methodology) — `nccn-methodology.md`

### `microboost` (1 entries)

- [#kb:pros:microboost_focal:nrg-microboost-prostate-2024](kb:pros:microboost_focal:nrg-microboost-prostate-2024) — `nrg-microboost-prostate-2024.md`

### `mission` (1 entries)

- [#kb:frm:society_methodology:abs-mission](kb:frm:society_methodology:abs-mission) — `abs-mission.md`

### `model-based-dose-calculation` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-229-mbdca](kb:phys:aapm_other:aapm-tg-229-mbdca) — `aapm-tg-229-mbdca.md`

### `molecular-profile` (1 entries)

- [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](kb:gyn:endometrial:lancet-molecular-endometrial-2024) — `lancet-molecular-endometrial-2024.md`

### `monotherapy` (2 entries)

- [#kb:pros:hdr:abs-2022-prostate-hdr](kb:pros:hdr:abs-2022-prostate-hdr) — `abs-2022-prostate-hdr.md`
- [#kb:pros:ldr:salvage-prostate-bt](kb:pros:ldr:salvage-prostate-bt) — `salvage-prostate-bt.md`

### `multi-catheter` (1 entries)

- [#kb:brst:apbi:estro-acrop-breast-2018](kb:brst:apbi:estro-acrop-breast-2018) — `estro-acrop-breast-2018.md`

### `n=1` (1 entries)

- [#kb:gi:pancreatic:pancreatic-i125-gemcitabine](kb:gi:pancreatic:pancreatic-i125-gemcitabine) — `pancreatic-i125-gemcitabine.md`

### `n=10` (1 entries)

- [#kb:frm:iaea_who:who-image-guided-irt-2025](kb:frm:iaea_who:who-image-guided-irt-2025) — `who-image-guided-irt-2025.md`

### `n=10-NEW-GBM` (1 entries)

- [#kb:oth:brain_spine:gliasite-brain](kb:oth:brain_spine:gliasite-brain) — `gliasite-brain.md`

### `n=1060` (1 entries)

- [#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024](kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024) — `lancet-pembrolizumab-crt-cervical-2024.md`

### `n=134` (1 entries)

- [#kb:oth:lung:brachy-trial-lung](kb:oth:lung:brachy-trial-lung) — `brachy-trial-lung.md`

### `n=1341` (1 entries)

- [#kb:gyn:cervix:embrace-i-pivotal-2021-lancet](kb:gyn:cervix:embrace-i-pivotal-2021-lancet) — `embrace-i-pivotal-2021-lancet-oncol.md`

### `n=14` (1 entries)

- [#kb:pros:microboost_focal:urethra-sparing-nvb](kb:pros:microboost_focal:urethra-sparing-nvb) — `urethra-sparing-nvb.md`

### `n=142` (1 entries)

- [#kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024](kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024) — `eortc-rt-psychosocial-2024.md`

### `n=16` (1 entries)

- [#kb:pros:salvage:eortc-salvage-hdr-bt-2024](kb:pros:salvage:eortc-salvage-hdr-bt-2024) — `eortc-salvage-hdr-bt-2024.md`

### `n=17-studies` (1 entries)

- [#kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd](kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd) — `bileduct-cholangiocarcinoma-ptbd.md`

### `n=20` (1 entries)

- [#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis](kb:oth:brain_spine:ct-guided-i125-spinal-metastasis) — `ct-guided-i125-spinal-metastasis.md`

### `n=205` (1 entries)

- [#kb:hns:skin:esteya-electronic](kb:hns:skin:esteya-electronic) — `esteya-electronic.md`

### `n=210-planned` (1 entries)

- [#kb:gi:rectal:bmj-watchful-waiting-rectal-2025](kb:gi:rectal:bmj-watchful-waiting-rectal-2025) — `bmj-watchful-waiting-rectal-2025.md`

### `n=215` (1 entries)

- [#kb:brst:apbi:abs-apbi-2013](kb:brst:apbi:abs-apbi-2013) — `abs-apbi-2013.md`

### `n=2178` (1 entries)

- [#kb:pros:penile:nature-bt-penile-organ-preservation](kb:pros:penile:nature-bt-penile-organ-preservation) — `nature-bt-penile-organ-preservation-2015.md`

### `n=227` (1 entries)

- [#kb:oth:vascular:vascular-bt-sr90](kb:oth:vascular:vascular-bt-sr90) — `vascular-bt-sr90.md`

### `n=2298+n=1153` (1 entries)

- [#kb:brst:iort:targit-a-vaidya-2014](kb:brst:iort:targit-a-vaidya-2014) — `targit-a-vaidya-2014.md`

### `n=247` (1 entries)

- [#kb:pros:hdr:jama-sbrt-vs-hdr-bt](kb:pros:hdr:jama-sbrt-vs-hdr-bt) — `jama-sbrt-vs-hdr-bt-prostate-2025.md`

### `n=248` (1 entries)

- [#kb:pros:hdr:real-time-trus-planning](kb:pros:hdr:real-time-trus-planning) — `real-time-trus-planning.md`

### `n=25` (1 entries)

- [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](kb:gi:pancreatic:3d-template-i125-pancreatic-2018) — `3d-template-i125-pancreatic-2018.md`

### `n=34` (1 entries)

- [#kb:gyn:cervix:embrace-ii-protocol](kb:gyn:cervix:embrace-ii-protocol) — `embrace-ii-protocol.md`

### `n=37-respondents` (1 entries)

- [#kb:brst:reirradiation:breast-reirradiation-survey-2024](kb:brst:reirradiation:breast-reirradiation-survey-2024) — `breast-reirradiation-survey-2024.md`

### `n=4` (1 entries)

- [#kb:brst:apbi:savi-strut-apbi](kb:brst:apbi:savi-strut-apbi) — `savi-strut-apbi.md`

### `n=427` (1 entries)

- [#kb:gyn:endometrial:portec-2-lancet-2010](kb:gyn:endometrial:portec-2-lancet-2010) — `portec-2-lancet-2010.md`

### `n=47` (1 entries)

- [#kb:brst:apbi:gec-estro-apbi-2016](kb:brst:apbi:gec-estro-apbi-2016) — `gec-estro-apbi-2016.md`

### `n=481` (1 entries)

- [#kb:gi:anal:gec-estro-anal-bt-2018](kb:gi:anal:gec-estro-anal-bt-2018) — `gec-estro-anal-bt-2018.md`

### `n=5` (1 entries)

- [#kb:pros:hdr:focal-prostate-hdr](kb:pros:hdr:focal-prostate-hdr) — `focal-prostate-hdr.md`

### `n=500` (1 entries)

- [#kb:gyn:cervix:lancet-cervical-induction-chemo-2024](kb:gyn:cervix:lancet-cervical-induction-chemo-2024) — `lancet-cervical-induction-chemo-2024.md`

### `n=5569` (1 entries)

- [#kb:brst:boost:wbi-boost-eortc-22881](kb:brst:boost:wbi-boost-eortc-22881) — `wbi-boost-eortc-22881.md`

### `n=6` (2 entries)

- [#kb:gi:rectal:rectal-recurrence-hdr](kb:gi:rectal:rectal-recurrence-hdr) — `rectal-recurrence-hdr.md`
- [#kb:oth:lung:ct-guided-i125-early-lung](kb:oth:lung:ct-guided-i125-early-lung) — `ct-guided-i125-early-lung-cancer.md`

### `n=60` (1 entries)

- [#kb:oth:malignant_general:i125-deep-hyperthermia-malignant](kb:oth:malignant_general:i125-deep-hyperthermia-malignant) — `i125-deep-hyperthermia-malignant.md`

### `n=741` (1 entries)

- [#kb:pros:microboost_focal:nrg-microboost-prostate-2024](kb:pros:microboost_focal:nrg-microboost-prostate-2024) — `nrg-microboost-prostate-2024.md`

### `n=805` (1 entries)

- [#kb:pros:ldr:salvage-prostate-bt](kb:pros:ldr:salvage-prostate-bt) — `salvage-prostate-bt.md`

### `n=975` (1 entries)

- [#kb:brst:apbi:nsabp-b39-rtog-0413](kb:brst:apbi:nsabp-b39-rtog-0413) — `nsabp-b39-rtog-0413.md`

### `n=NC` (2 entries)

- [#kb:pros:ldr:ascende-rt-morris-2017](kb:pros:ldr:ascende-rt-morris-2017) — `ascende-rt-morris-2017.md`
- [#kb:gi:rectal:opera-trial-sun-myint](kb:gi:rectal:opera-trial-sun-myint) — `opera-trial-sun-myint.md`

### `narrative-review` (1 entries)

- [#kb:hns:hn_cancer:gec-estro-hn](kb:hns:hn_cancer:gec-estro-hn) — `gec-estro-hn.md`

### `nasal-vestibule` (1 entries)

- [#kb:hns:hn_cancer:lip-cancer-bt](kb:hns:hn_cancer:lip-cancer-bt) — `lip-cancer-bt.md`

### `neurovascular-bundle-sparing` (1 entries)

- [#kb:pros:microboost_focal:urethra-sparing-nvb](kb:pros:microboost_focal:urethra-sparing-nvb) — `urethra-sparing-nvb.md`

### `organ-preservation` (2 entries)

- [#kb:pros:penile:nature-bt-penile-organ-preservation](kb:pros:penile:nature-bt-penile-organ-preservation) — `nature-bt-penile-organ-preservation-2015.md`
- [#kb:gi:rectal:bmj-watchful-waiting-rectal-2025](kb:gi:rectal:bmj-watchful-waiting-rectal-2025) — `bmj-watchful-waiting-rectal-2025.md`

### `p53abn` (2 entries)

- [#kb:gyn:endometrial:ars-appropriate-use-criteria-2024](kb:gyn:endometrial:ars-appropriate-use-criteria-2024) — `ars-appropriate-use-criteria-2024.md`
- [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](kb:gyn:endometrial:lancet-molecular-endometrial-2024) — `lancet-molecular-endometrial-2024.md`

### `pain-relief-95%` (1 entries)

- [#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis](kb:oth:brain_spine:ct-guided-i125-spinal-metastasis) — `ct-guided-i125-spinal-metastasis.md`

### `pancreatic` (7 entries)

- [#kb:gi:pancreatic:3d-template-i125-pancreatic-2018](kb:gi:pancreatic:3d-template-i125-pancreatic-2018) — `3d-template-i125-pancreatic-2018.md`
- [#kb:gi:pancreatic:cstro-pancreatic-i125-2017](kb:gi:pancreatic:cstro-pancreatic-i125-2017) — `cstro-pancreatic-i125-2017.md`
- [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](kb:gi:pancreatic:i125-pancreatic-guideline-2023) — `i125-pancreatic-guideline-2023.md`
- [#kb:gi:pancreatic:pancreatic-i125-clinical](kb:gi:pancreatic:pancreatic-i125-clinical) — `pancreatic-i125-clinical.md`
- [#kb:gi:pancreatic:pancreatic-i125-gemcitabine](kb:gi:pancreatic:pancreatic-i125-gemcitabine) — `pancreatic-i125-gemcitabine.md`
- [#kb:frm:chinese:csco-bt-chinese](kb:frm:chinese:csco-bt-chinese) — `csco-bt-chinese.md`
- [#kb:frm:chinese:cstro-bt-chinese](kb:frm:chinese:cstro-bt-chinese) — `cstro-bt-chinese.md`

### `pediatric` (1 entries)

- [#kb:oth:pediatric:pediatric-rhabdomyosarcoma-bt](kb:oth:pediatric:pediatric-rhabdomyosarcoma-bt) — `pediatric-rhabdomyosarcoma-bt.md`

### `pelvic-CRT` (1 entries)

- [#kb:gi:rectal:rectal-recurrence-hdr](kb:gi:rectal:rectal-recurrence-hdr) — `rectal-recurrence-hdr.md`

### `pembrolizumab` (1 entries)

- [#kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024](kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024) — `lancet-pembrolizumab-crt-cervical-2024.md`

### `penectomy-vs-BT` (1 entries)

- [#kb:pros:penile:nature-bt-penile-organ-preservation](kb:pros:penile:nature-bt-penile-organ-preservation) — `nature-bt-penile-organ-preservation-2015.md`

### `penile` (2 entries)

- [#kb:pros:penile:gec-estro-penile-2018](kb:pros:penile:gec-estro-penile-2018) — `gec-estro-penile-2018.md`
- [#kb:pros:penile:nature-bt-penile-organ-preservation](kb:pros:penile:nature-bt-penile-organ-preservation) — `nature-bt-penile-organ-preservation-2015.md`

### `permanent-seed` (2 entries)

- [#kb:pros:ldr:abs-aua-astro-ldr-2012](kb:pros:ldr:abs-aua-astro-ldr-2012) — `abs-aua-astro-ldr-2012.md`
- [#kb:pros:ldr:salvage-prostate-bt](kb:pros:ldr:salvage-prostate-bt) — `salvage-prostate-bt.md`

### `phase-II` (1 entries)

- [#kb:pros:salvage:eortc-salvage-hdr-bt-2024](kb:pros:salvage:eortc-salvage-hdr-bt-2024) — `eortc-salvage-hdr-bt-2024.md`

### `plaque-dosimetry` (1 entries)

- [#kb:oth:eye:aapm-tg-129-uveal-melanoma](kb:oth:eye:aapm-tg-129-uveal-melanoma) — `aapm-tg-129-uveal-melanoma.md`

### `point-A` (2 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part1](kb:gyn:cervix:abs-cervix-consensus-2012-part1) — `abs-cervix-consensus-2012-part1.md`
- [#kb:phys:icru:icru-38-ic](kb:phys:icru:icru-38-ic) — `icru-38-ic.md`

### `practice-parameter` (1 entries)

- [#kb:hns:practice_param:abs-hn-2018](kb:hns:practice_param:abs-hn-2018) — `abs-hn-2018.md`

### `prescribed-110-130-Gy` (1 entries)

- [#kb:gi:pancreatic:i125-pancreatic-guideline-2023](kb:gi:pancreatic:i125-pancreatic-guideline-2023) — `i125-pancreatic-guideline-2023.md`

### `proof-of-principle` (1 entries)

- [#kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt](kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt) — `deep-reinforcement-learning-hdr-bt-cervical.md`

### `prostate` (13 entries)

- [#kb:pros:guidelines:aapm-tg-137-nath-2009](kb:pros:guidelines:aapm-tg-137-nath-2009) — `aapm-tg-137-nath-2009.md`
- [#kb:pros:hdr:abs-2022-prostate-hdr](kb:pros:hdr:abs-2022-prostate-hdr) — `abs-2022-prostate-hdr.md`
- [#kb:pros:ldr:abs-aua-astro-ldr-2012](kb:pros:ldr:abs-aua-astro-ldr-2012) — `abs-aua-astro-ldr-2012.md`
- [#kb:pros:ldr:ascende-rt-morris-2017](kb:pros:ldr:ascende-rt-morris-2017) — `ascende-rt-morris-2017.md`
- [#kb:pros:guidelines:aua-astro-2022-prostate](kb:pros:guidelines:aua-astro-2022-prostate) — `aua-astro-2022-prostate.md`
- [#kb:pros:salvage:eortc-salvage-hdr-bt-2024](kb:pros:salvage:eortc-salvage-hdr-bt-2024) — `eortc-salvage-hdr-bt-2024.md`
- [#kb:pros:hdr:focal-prostate-hdr](kb:pros:hdr:focal-prostate-hdr) — `focal-prostate-hdr.md`
- [#kb:pros:hdr:jama-sbrt-vs-hdr-bt](kb:pros:hdr:jama-sbrt-vs-hdr-bt) — `jama-sbrt-vs-hdr-bt-prostate-2025.md`
- [#kb:pros:microboost_focal:nrg-microboost-prostate-2024](kb:pros:microboost_focal:nrg-microboost-prostate-2024) — `nrg-microboost-prostate-2024.md`
- [#kb:pros:hdr:real-time-trus-planning](kb:pros:hdr:real-time-trus-planning) — `real-time-trus-planning.md`
- [#kb:pros:ldr:salvage-prostate-bt](kb:pros:ldr:salvage-prostate-bt) — `salvage-prostate-bt.md`
- [#kb:pros:microboost_focal:urethra-sparing-nvb](kb:pros:microboost_focal:urethra-sparing-nvb) — `urethra-sparing-nvb.md`
- [#kb:hns:practice_param:abs-hn-2018](kb:hns:practice_param:abs-hn-2018) — `abs-hn-2018.md`

### `prostate-bed` (1 entries)

- [#kb:pros:salvage:eortc-salvage-hdr-bt-2024](kb:pros:salvage:eortc-salvage-hdr-bt-2024) — `eortc-salvage-hdr-bt-2024.md`

### `psychosocial` (1 entries)

- [#kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024](kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024) — `eortc-rt-psychosocial-2024.md`

### `radio-recurrent` (1 entries)

- [#kb:pros:hdr:abs-2022-prostate-hdr](kb:pros:hdr:abs-2022-prostate-hdr) — `abs-2022-prostate-hdr.md`

### `radiochromic-film` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-232-film](kb:phys:aapm_other:aapm-tg-232-film) — `aapm-tg-232-film.md`

### `real-time-dose-prediction` (1 entries)

- [#kb:pros:hdr:real-time-trus-planning](kb:pros:hdr:real-time-trus-planning) — `real-time-trus-planning.md`

### `rectal` (4 entries)

- [#kb:gi:rectal:bmj-watchful-waiting-rectal-2025](kb:gi:rectal:bmj-watchful-waiting-rectal-2025) — `bmj-watchful-waiting-rectal-2025.md`
- [#kb:gi:rectal:opera-trial-sun-myint](kb:gi:rectal:opera-trial-sun-myint) — `opera-trial-sun-myint.md`
- [#kb:gi:rectal:papillon-contact-xray](kb:gi:rectal:papillon-contact-xray) — `papillon-contact-xray.md`
- [#kb:gi:rectal:rectal-recurrence-hdr](kb:gi:rectal:rectal-recurrence-hdr) — `rectal-recurrence-hdr.md`

### `rectosigmoid-recurrence` (1 entries)

- [#kb:oth:brain_spine:gammatile-brain](kb:oth:brain_spine:gammatile-brain) — `gammatile-brain.md`

### `reference-points` (1 entries)

- [#kb:phys:icru:icru-38-ic](kb:phys:icru:icru-38-ic) — `icru-38-ic.md`

### `reirradiation` (1 entries)

- [#kb:brst:reirradiation:breast-reirradiation-survey-2024](kb:brst:reirradiation:breast-reirradiation-survey-2024) — `breast-reirradiation-survey-2024.md`

### `reports-catalogue` (1 entries)

- [#kb:frm:global_access:icru-reports-catalogue](kb:frm:global_access:icru-reports-catalogue) — `icru-reports-catalogue.md`

### `review` (1 entries)

- [#kb:gi:pancreatic:pancreatic-i125-clinical](kb:gi:pancreatic:pancreatic-i125-clinical) — `pancreatic-i125-clinical.md`

### `rhabdomyosarcoma` (1 entries)

- [#kb:oth:pediatric:pediatric-rhabdomyosarcoma-bt](kb:oth:pediatric:pediatric-rhabdomyosarcoma-bt) — `pediatric-rhabdomyosarcoma-bt.md`

### `salvage` (3 entries)

- [#kb:pros:salvage:eortc-salvage-hdr-bt-2024](kb:pros:salvage:eortc-salvage-hdr-bt-2024) — `eortc-salvage-hdr-bt-2024.md`
- [#kb:pros:ldr:salvage-prostate-bt](kb:pros:ldr:salvage-prostate-bt) — `salvage-prostate-bt.md`
- [#kb:hns:hn_cancer:gec-estro-hn](kb:hns:hn_cancer:gec-estro-hn) — `gec-estro-hn.md`

### `sarcoma` (1 entries)

- [#kb:oth:sarcoma:abs-sarcoma-bt](kb:oth:sarcoma:abs-sarcoma-bt) — `abs-sarcoma-bt.md`

### `single-centre` (1 entries)

- [#kb:pros:penile:gec-estro-penile-2018](kb:pros:penile:gec-estro-penile-2018) — `gec-estro-penile-2018.md`

### `single-lumen` (1 entries)

- [#kb:brst:apbi:balloon-mammosite](kb:brst:apbi:balloon-mammosite) — `balloon-mammosite.md`

### `skin` (6 entries)

- [#kb:hns:practice_param:abs-hn-2018](kb:hns:practice_param:abs-hn-2018) — `abs-hn-2018.md`
- [#kb:hns:skin:abs-skin-2020](kb:hns:skin:abs-skin-2020) — `abs-skin-2020.md`
- [#kb:hns:skin:esteya-electronic](kb:hns:skin:esteya-electronic) — `esteya-electronic.md`
- [#kb:hns:skin:freiburg-flap-ham](kb:hns:skin:freiburg-flap-ham) — `freiburg-flap-ham.md`
- [#kb:hns:skin:gec-estro-skin-2018](kb:hns:skin:gec-estro-skin-2018) — `gec-estro-skin-2018.md`
- [#kb:hns:keloid:keloid-bt](kb:hns:keloid:keloid-bt) — `keloid-bt.md`

### `small-bowel` (1 entries)

- [#kb:gyn:cervix:dimopoulos-mri-ctv-2012](kb:gyn:cervix:dimopoulos-mri-ctv-2012) — `dimopoulos-mri-ctv-2012.md`

### `soft-tissue` (1 entries)

- [#kb:oth:sarcoma:abs-sarcoma-bt](kb:oth:sarcoma:abs-sarcoma-bt) — `abs-sarcoma-bt.md`

### `spine` (2 entries)

- [#kb:oth:brain_spine:ct-guided-i125-spinal-metastasis](kb:oth:brain_spine:ct-guided-i125-spinal-metastasis) — `ct-guided-i125-spinal-metastasis.md`
- [#kb:oth:brain_spine:gammatile-brain](kb:oth:brain_spine:gammatile-brain) — `gammatile-brain.md`

### `statewide-consortium` (1 entries)

- [#kb:pros:microboost_focal:nrg-microboost-prostate-2024](kb:pros:microboost_focal:nrg-microboost-prostate-2024) — `nrg-microboost-prostate-2024.md`

### `stent-patency-10-months` (1 entries)

- [#kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd](kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd) — `bileduct-cholangiocarcinoma-ptbd.md`

### `strut-based` (1 entries)

- [#kb:brst:apbi:savi-strut-apbi](kb:brst:apbi:savi-strut-apbi) — `savi-strut-apbi.md`

### `surface-BT` (2 entries)

- [#kb:hns:skin:freiburg-flap-ham](kb:hns:skin:freiburg-flap-ham) — `freiburg-flap-ham.md`
- [#kb:hns:skin:gec-estro-skin-2018](kb:hns:skin:gec-estro-skin-2018) — `gec-estro-skin-2018.md`

### `synchronous-prostate-rectal` (1 entries)

- [#kb:gi:rectal:rectal-recurrence-hdr](kb:gi:rectal:rectal-recurrence-hdr) — `rectal-recurrence-hdr.md`

### `systematic-review` (1 entries)

- [#kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd](kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd) — `bileduct-cholangiocarcinoma-ptbd.md`

### `tandem-and-ring` (1 entries)

- [#kb:gyn:cervix:abs-cervix-consensus-2012-part2](kb:gyn:cervix:abs-cervix-consensus-2012-part2) — `abs-cervix-consensus-2012-part2.md`

### `tandem-based` (1 entries)

- [#kb:gyn:cervix:abs-vaginal-2012](kb:gyn:cervix:abs-vaginal-2012) — `abs-vaginal-2012.md`

### `tandem-ring` (1 entries)

- [#kb:gyn:cervix:dimopoulos-mri-ctv-2012](kb:gyn:cervix:dimopoulos-mri-ctv-2012) — `dimopoulos-mri-ctv-2012.md`

### `training` (1 entries)

- [#kb:frm:iaea_who:iaea-brachy-programme](kb:frm:iaea_who:iaea-brachy-programme) — `iaea-brachy-programme.md`

### `ultra-focal` (1 entries)

- [#kb:pros:hdr:focal-prostate-hdr](kb:pros:hdr:focal-prostate-hdr) — `focal-prostate-hdr.md`

### `ultrasound` (1 entries)

- [#kb:phys:aapm_other:aapm-tg-148-hdr-qa](kb:phys:aapm_other:aapm-tg-148-hdr-qa) — `aapm-tg-148-hdr-qa.md`

### `update` (1 entries)

- [#kb:phys:tg43:aapm-tg-43u1-rivard-2004](kb:phys:tg43:aapm-tg-43u1-rivard-2004) — `aapm-tg-43u1-rivard-2004.md`

### `utilization` (1 entries)

- [#kb:gyn:cervix:msk-bt-utilization-cervical-2025](kb:gyn:cervix:msk-bt-utilization-cervical-2025) — `msk-bt-utilization-cervical-2025.md`

### `uveal-melanoma` (2 entries)

- [#kb:oth:eye:aapm-tg-129-uveal-melanoma](kb:oth:eye:aapm-tg-129-uveal-melanoma) — `aapm-tg-129-uveal-melanoma.md`
- [#kb:oth:eye:coms-trial-medium](kb:oth:eye:coms-trial-medium) — `coms-trial-medium.md`

### `vaginal-BT-21-Gy-3fx` (1 entries)

- [#kb:gyn:endometrial:lancet-molecular-endometrial-2024](kb:gyn:endometrial:lancet-molecular-endometrial-2024) — `lancet-molecular-endometrial-2024.md`

### `vaginal-BT-vs-EBRT` (1 entries)

- [#kb:gyn:endometrial:portec-2-lancet-2010](kb:gyn:endometrial:portec-2-lancet-2010) — `portec-2-lancet-2010.md`

### `vaginal-VaIN` (1 entries)

- [#kb:frm:iaea_who:who-image-guided-irt-2025](kb:frm:iaea_who:who-image-guided-irt-2025) — `who-image-guided-irt-2025.md`

### `vaginal-recurrence` (1 entries)

- [#kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024](kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024) — `gec-estro-endometrial-2024.md`

### `vascular` (2 entries)

- [#kb:oth:vascular:cardiac-vascular-review](kb:oth:vascular:cardiac-vascular-review) — `cardiac-vascular-review.md`
- [#kb:oth:vascular:vascular-bt-sr90](kb:oth:vascular:vascular-bt-sr90) — `vascular-bt-sr90.md`

### `vulvar` (2 entries)

- [#kb:gyn:vaginal_vulvar:abs-vulvar-2019](kb:gyn:vaginal_vulvar:abs-vulvar-2019) — `abs-vulvar-2019.md`
- [#kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024](kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024) — `rtog-cisplatin-gem-imrt-2024.md`

### `working-group` (1 entries)

- [#kb:frm:society_methodology:gec-estro-about](kb:frm:society_methodology:gec-estro-about) — `gec-estro-about.md`

---

## Part IV: Master Source Index (all 110 files)

Listed by category, then by sub-topic.

### gyn — Gynecologic Brachytherapy (17 files)

**Cervix Cancer BT**

| # | File | ID |
|---|------|-----|
| 1 | [abs-cervix-consensus-2012-part1.md](sources/01_gynecologic/raw/abs-cervix-consensus-2012-part1.md) | `kb:gyn:cervix:abs-cervix-consensus-2012-part1` |
| 2 | [abs-cervix-consensus-2012-part2.md](sources/01_gynecologic/raw/abs-cervix-consensus-2012-part2.md) | `kb:gyn:cervix:abs-cervix-consensus-2012-part2` |
| 3 | [abs-vaginal-2012.md](sources/01_gynecologic/raw/abs-vaginal-2012.md) | `kb:gyn:cervix:abs-vaginal-2012` |
| 4 | [dimopoulos-mri-ctv-2012.md](sources/01_gynecologic/raw/dimopoulos-mri-ctv-2012.md) | `kb:gyn:cervix:dimopoulos-mri-ctv-2012` |
| 5 | [embrace-i-pivotal-2021-lancet-oncol.md](sources/01_gynecologic/raw/embrace-i-pivotal-2021-lancet-oncol.md) | `kb:gyn:cervix:embrace-i-pivotal-2021-lancet` |
| 6 | [embrace-ii-protocol.md](sources/01_gynecologic/raw/embrace-ii-protocol.md) | `kb:gyn:cervix:embrace-ii-protocol` |
| 7 | [gec-estro-cervix-2005-haie-meder.md](sources/01_gynecologic/raw/gec-estro-cervix-2005-haie-meder.md) | `kb:gyn:cervix:gec-estro-cervix-2005-haie` |
| 8 | [icru-89-gyn.md](sources/01_gynecologic/raw/icru-89-gyn.md) | `kb:gyn:cervix:icru-89-gyn` |
| 9 | [lancet-cervical-induction-chemo-2024.md](sources/01_gynecologic/raw/lancet-cervical-induction-chemo-2024.md) | `kb:gyn:cervix:lancet-cervical-induction-chemo-2024` |
| 10 | [lancet-pembrolizumab-crt-cervical-2024.md](sources/01_gynecologic/raw/lancet-pembrolizumab-crt-cervical-2024.md) | `kb:gyn:cervix:lancet-pembrolizumab-crt-cervical-2024` |
| 11 | [msk-bt-utilization-cervical-2025.md](sources/01_gynecologic/raw/msk-bt-utilization-cervical-2025.md) | `kb:gyn:cervix:msk-bt-utilization-cervical-2025` |
| 12 | [nccn-cervical-2024.md](sources/01_gynecologic/raw/nccn-cervical-2024.md) | `kb:gyn:cervix:nccn-cervical-2024` |

**Endometrial Cancer BT**

| # | File | ID |
|---|------|-----|
| 1 | [ars-appropriate-use-criteria-2024.md](sources/01_gynecologic/raw/ars-appropriate-use-criteria-2024.md) | `kb:gyn:endometrial:ars-appropriate-use-criteria-2024` |
| 2 | [lancet-molecular-endometrial-2024.md](sources/01_gynecologic/raw/lancet-molecular-endometrial-2024.md) | `kb:gyn:endometrial:lancet-molecular-endometrial-2024` |
| 3 | [portec-2-lancet-2010.md](sources/01_gynecologic/raw/portec-2-lancet-2010.md) | `kb:gyn:endometrial:portec-2-lancet-2010` |

**Vaginal & Vulvar Cancer BT**

| # | File | ID |
|---|------|-----|
| 1 | [abs-vulvar-2019.md](sources/01_gynecologic/raw/abs-vulvar-2019.md) | `kb:gyn:vaginal_vulvar:abs-vulvar-2019` |
| 2 | [gec-estro-endometrial-2024.md](sources/01_gynecologic/raw/gec-estro-endometrial-2024.md) | `kb:gyn:vaginal_vulvar:gec-estro-endometrial-2024` |

### pros — Prostate & Genitourinary BT (14 files)

**LDR Permanent Seed BT**

| # | File | ID |
|---|------|-----|
| 1 | [abs-aua-astro-ldr-2012.md](sources/02_prostate_gu/raw/abs-aua-astro-ldr-2012.md) | `kb:pros:ldr:abs-aua-astro-ldr-2012` |
| 2 | [ascende-rt-morris-2017.md](sources/02_prostate_gu/raw/ascende-rt-morris-2017.md) | `kb:pros:ldr:ascende-rt-morris-2017` |
| 3 | [salvage-prostate-bt.md](sources/02_prostate_gu/raw/salvage-prostate-bt.md) | `kb:pros:ldr:salvage-prostate-bt` |

**HDR Brachytherapy**

| # | File | ID |
|---|------|-----|
| 1 | [abs-2022-prostate-hdr.md](sources/02_prostate_gu/raw/abs-2022-prostate-hdr.md) | `kb:pros:hdr:abs-2022-prostate-hdr` |
| 2 | [focal-prostate-hdr.md](sources/02_prostate_gu/raw/focal-prostate-hdr.md) | `kb:pros:hdr:focal-prostate-hdr` |
| 3 | [jama-sbrt-vs-hdr-bt-prostate-2025.md](sources/02_prostate_gu/raw/jama-sbrt-vs-hdr-bt-prostate-2025.md) | `kb:pros:hdr:jama-sbrt-vs-hdr-bt` |
| 4 | [real-time-trus-planning.md](sources/02_prostate_gu/raw/real-time-trus-planning.md) | `kb:pros:hdr:real-time-trus-planning` |

**Microboost & Focal Sparing**

| # | File | ID |
|---|------|-----|
| 1 | [nrg-microboost-prostate-2024.md](sources/02_prostate_gu/raw/nrg-microboost-prostate-2024.md) | `kb:pros:microboost_focal:nrg-microboost-prostate-2024` |
| 2 | [urethra-sparing-nvb.md](sources/02_prostate_gu/raw/urethra-sparing-nvb.md) | `kb:pros:microboost_focal:urethra-sparing-nvb` |

**Salvage BT**

| # | File | ID |
|---|------|-----|
| 1 | [eortc-salvage-hdr-bt-2024.md](sources/02_prostate_gu/raw/eortc-salvage-hdr-bt-2024.md) | `kb:pros:salvage:eortc-salvage-hdr-bt-2024` |

**Penile BT**

| # | File | ID |
|---|------|-----|
| 1 | [gec-estro-penile-2018.md](sources/02_prostate_gu/raw/gec-estro-penile-2018.md) | `kb:pros:penile:gec-estro-penile-2018` |
| 2 | [nature-bt-penile-organ-preservation-2015.md](sources/02_prostate_gu/raw/nature-bt-penile-organ-preservation-2015.md) | `kb:pros:penile:nature-bt-penile-organ-preservation` |

**Guidelines / Methodology**

| # | File | ID |
|---|------|-----|
| 1 | [aapm-tg-137-nath-2009.md](sources/02_prostate_gu/raw/aapm-tg-137-nath-2009.md) | `kb:pros:guidelines:aapm-tg-137-nath-2009` |
| 2 | [aua-astro-2022-prostate.md](sources/02_prostate_gu/raw/aua-astro-2022-prostate.md) | `kb:pros:guidelines:aua-astro-2022-prostate` |

### brst — Breast Brachytherapy (13 files)

**Accelerated Partial Breast Irradiation (APBI)**

| # | File | ID |
|---|------|-----|
| 1 | [abs-apbi-2013.md](sources/03_breast/raw/abs-apbi-2013.md) | `kb:brst:apbi:abs-apbi-2013` |
| 2 | [astro-2022-apbi.md](sources/03_breast/raw/astro-2022-apbi.md) | `kb:brst:apbi:astro-2022-apbi` |
| 3 | [balloon-mammosite.md](sources/03_breast/raw/balloon-mammosite.md) | `kb:brst:apbi:balloon-mammosite` |
| 4 | [estro-acrop-breast-2018.md](sources/03_breast/raw/estro-acrop-breast-2018.md) | `kb:brst:apbi:estro-acrop-breast-2018` |
| 5 | [gec-estro-apbi-2016.md](sources/03_breast/raw/gec-estro-apbi-2016.md) | `kb:brst:apbi:gec-estro-apbi-2016` |
| 6 | [nature-apbi-alternative-wbi-2020.md](sources/03_breast/raw/nature-apbi-alternative-wbi-2020.md) | `kb:brst:apbi:nature-apbi-alternative-wbi-2020` |
| 7 | [nsabp-b39-rtog-0413.md](sources/03_breast/raw/nsabp-b39-rtog-0413.md) | `kb:brst:apbi:nsabp-b39-rtog-0413` |
| 8 | [savi-strut-apbi.md](sources/03_breast/raw/savi-strut-apbi.md) | `kb:brst:apbi:savi-strut-apbi` |

**Intraoperative RT (IORT)**

| # | File | ID |
|---|------|-----|
| 1 | [iort-electronic-bt.md](sources/03_breast/raw/iort-electronic-bt.md) | `kb:brst:iort:iort-electronic-bt` |
| 2 | [targit-a-vaidya-2014.md](sources/03_breast/raw/targit-a-vaidya-2014.md) | `kb:brst:iort:targit-a-vaidya-2014` |

**Reirradiation**

| # | File | ID |
|---|------|-----|
| 1 | [breast-reirradiation-survey-2024.md](sources/03_breast/raw/breast-reirradiation-survey-2024.md) | `kb:brst:reirradiation:breast-reirradiation-survey-2024` |

**Whole Breast Boost**

| # | File | ID |
|---|------|-----|
| 1 | [wbi-boost-eortc-22881.md](sources/03_breast/raw/wbi-boost-eortc-22881.md) | `kb:brst:boost:wbi-boost-eortc-22881` |

**Guidelines**

| # | File | ID |
|---|------|-----|
| 1 | [nccn-breast-2024.md](sources/03_breast/raw/nccn-breast-2024.md) | `kb:brst:guidelines:nccn-breast-2024` |

### hns — Head & Neck / Skin BT (12 files)

**Head & Neck Cancers**

| # | File | ID |
|---|------|-----|
| 1 | [gec-estro-hn.md](sources/04_head_neck_skin/raw/gec-estro-hn.md) | `kb:hns:hn_cancer:gec-estro-hn` |
| 2 | [lip-cancer-bt.md](sources/04_head_neck_skin/raw/lip-cancer-bt.md) | `kb:hns:hn_cancer:lip-cancer-bt` |
| 3 | [nccn-hn-2024.md](sources/04_head_neck_skin/raw/nccn-hn-2024.md) | `kb:hns:hn_cancer:nccn-hn-2024` |
| 4 | [npc-intracavitary-bt.md](sources/04_head_neck_skin/raw/npc-intracavitary-bt.md) | `kb:hns:hn_cancer:npc-intracavitary-bt` |

**Skin Cancer (NMSC) & Superficial BT**

| # | File | ID |
|---|------|-----|
| 1 | [abs-skin-2020.md](sources/04_head_neck_skin/raw/abs-skin-2020.md) | `kb:hns:skin:abs-skin-2020` |
| 2 | [esteya-electronic.md](sources/04_head_neck_skin/raw/esteya-electronic.md) | `kb:hns:skin:esteya-electronic` |
| 3 | [freiburg-flap-ham.md](sources/04_head_neck_skin/raw/freiburg-flap-ham.md) | `kb:hns:skin:freiburg-flap-ham` |
| 4 | [gec-estro-skin-2018.md](sources/04_head_neck_skin/raw/gec-estro-skin-2018.md) | `kb:hns:skin:gec-estro-skin-2018` |

**Keloid**

| # | File | ID |
|---|------|-----|
| 1 | [keloid-bt.md](sources/04_head_neck_skin/raw/keloid-bt.md) | `kb:hns:keloid:keloid-bt` |

**Practice Parameters**

| # | File | ID |
|---|------|-----|
| 1 | [abs-hn-2018.md](sources/04_head_neck_skin/raw/abs-hn-2018.md) | `kb:hns:practice_param:abs-hn-2018` |

**Related (Cervical/Vulvar QoL — file miscategorized in 04)**

| # | File | ID |
|---|------|-----|
| 1 | [eortc-rt-psychosocial-2024.md](sources/04_head_neck_skin/raw/eortc-rt-psychosocial-2024.md) | `kb:hns:related_gyne_qol:eortc-rt-psychosocial-2024` |
| 2 | [rtog-cisplatin-gem-imrt-2024.md](sources/04_head_neck_skin/raw/rtog-cisplatin-gem-imrt-2024.md) | `kb:hns:related_gyne_qol:rtog-cisplatin-gem-imrt-2024` |

### gi — Gastrointestinal BT (14 files)

**Esophageal BT**

| # | File | ID |
|---|------|-----|
| 1 | [abs-esophageal-2014.md](sources/05_gi/raw/abs-esophageal-2014.md) | `kb:gi:esophageal:abs-esophageal-2014` |
| 2 | [nccn-esophageal-2024.md](sources/05_gi/raw/nccn-esophageal-2024.md) | `kb:gi:esophageal:nccn-esophageal-2024` |

**Rectal BT**

| # | File | ID |
|---|------|-----|
| 1 | [bmj-watchful-waiting-rectal-2025.md](sources/05_gi/raw/bmj-watchful-waiting-rectal-2025.md) | `kb:gi:rectal:bmj-watchful-waiting-rectal-2025` |
| 2 | [opera-trial-sun-myint.md](sources/05_gi/raw/opera-trial-sun-myint.md) | `kb:gi:rectal:opera-trial-sun-myint` |
| 3 | [papillon-contact-xray.md](sources/05_gi/raw/papillon-contact-xray.md) | `kb:gi:rectal:papillon-contact-xray` |
| 4 | [rectal-recurrence-hdr.md](sources/05_gi/raw/rectal-recurrence-hdr.md) | `kb:gi:rectal:rectal-recurrence-hdr` |

**Anal Canal BT**

| # | File | ID |
|---|------|-----|
| 1 | [gec-estro-anal-bt-2018.md](sources/05_gi/raw/gec-estro-anal-bt-2018.md) | `kb:gi:anal:gec-estro-anal-bt-2018` |

**Pancreatic BT (Permanent I-125)**

| # | File | ID |
|---|------|-----|
| 1 | [3d-template-i125-pancreatic-2018.md](sources/05_gi/raw/3d-template-i125-pancreatic-2018.md) | `kb:gi:pancreatic:3d-template-i125-pancreatic-2018` |
| 2 | [cstro-pancreatic-i125-2017.md](sources/05_gi/raw/cstro-pancreatic-i125-2017.md) | `kb:gi:pancreatic:cstro-pancreatic-i125-2017` |
| 3 | [i125-pancreatic-guideline-2023.md](sources/05_gi/raw/i125-pancreatic-guideline-2023.md) | `kb:gi:pancreatic:i125-pancreatic-guideline-2023` |
| 4 | [pancreatic-i125-clinical.md](sources/05_gi/raw/pancreatic-i125-clinical.md) | `kb:gi:pancreatic:pancreatic-i125-clinical` |
| 5 | [pancreatic-i125-gemcitabine.md](sources/05_gi/raw/pancreatic-i125-gemcitabine.md) | `kb:gi:pancreatic:pancreatic-i125-gemcitabine` |

**Biliary Tract BT**

| # | File | ID |
|---|------|-----|
| 1 | [bileduct-cholangiocarcinoma-ptbd.md](sources/05_gi/raw/bileduct-cholangiocarcinoma-ptbd.md) | `kb:gi:biliary:bileduct-cholangiocarcinoma-ptbd` |

**Gastric BT**

| # | File | ID |
|---|------|-----|
| 1 | [gastric-bt.md](sources/05_gi/raw/gastric-bt.md) | `kb:gi:gastric:gastric-bt` |

### oth — Other Sites BT (13 files)

**Lung BT**

| # | File | ID |
|---|------|-----|
| 1 | [brachy-trial-lung.md](sources/06_other_sites/raw/brachy-trial-lung.md) | `kb:oth:lung:brachy-trial-lung` |
| 2 | [ct-guided-i125-early-lung-cancer.md](sources/06_other_sites/raw/ct-guided-i125-early-lung-cancer.md) | `kb:oth:lung:ct-guided-i125-early-lung` |
| 3 | [endobronchial-bt-consensus.md](sources/06_other_sites/raw/endobronchial-bt-consensus.md) | `kb:oth:lung:endobronchial-bt-consensus` |

**Brain & Spine BT**

| # | File | ID |
|---|------|-----|
| 1 | [ct-guided-i125-spinal-metastasis.md](sources/06_other_sites/raw/ct-guided-i125-spinal-metastasis.md) | `kb:oth:brain_spine:ct-guided-i125-spinal-metastasis` |
| 2 | [gammatile-brain.md](sources/06_other_sites/raw/gammatile-brain.md) | `kb:oth:brain_spine:gammatile-brain` |
| 3 | [gliasite-brain.md](sources/06_other_sites/raw/gliasite-brain.md) | `kb:oth:brain_spine:gliasite-brain` |

**Eye / Uveal BT**

| # | File | ID |
|---|------|-----|
| 1 | [aapm-tg-129-uveal-melanoma.md](sources/06_other_sites/raw/aapm-tg-129-uveal-melanoma.md) | `kb:oth:eye:aapm-tg-129-uveal-melanoma` |
| 2 | [coms-trial-medium.md](sources/06_other_sites/raw/coms-trial-medium.md) | `kb:oth:eye:coms-trial-medium` |

**Soft Tissue Sarcoma BT**

| # | File | ID |
|---|------|-----|
| 1 | [abs-sarcoma-bt.md](sources/06_other_sites/raw/abs-sarcoma-bt.md) | `kb:oth:sarcoma:abs-sarcoma-bt` |

**Pediatric BT**

| # | File | ID |
|---|------|-----|
| 1 | [pediatric-rhabdomyosarcoma-bt.md](sources/06_other_sites/raw/pediatric-rhabdomyosarcoma-bt.md) | `kb:oth:pediatric:pediatric-rhabdomyosarcoma-bt` |

**Vascular BT**

| # | File | ID |
|---|------|-----|
| 1 | [cardiac-vascular-review.md](sources/06_other_sites/raw/cardiac-vascular-review.md) | `kb:oth:vascular:cardiac-vascular-review` |
| 2 | [vascular-bt-sr90.md](sources/06_other_sites/raw/vascular-bt-sr90.md) | `kb:oth:vascular:vascular-bt-sr90` |

**Malignant Tumors (General — I-125 + Hyperthermia)**

| # | File | ID |
|---|------|-----|
| 1 | [i125-deep-hyperthermia-malignant.md](sources/06_other_sites/raw/i125-deep-hyperthermia-malignant.md) | `kb:oth:malignant_general:i125-deep-hyperthermia-malignant` |

### phys — Physics & Dosimetry (13 files)

**AAPM TG-43 Formalism**

| # | File | ID |
|---|------|-----|
| 1 | [aapm-tg-43-nath-1995.md](sources/07_physics/raw/aapm-tg-43-nath-1995.md) | `kb:phys:tg43:aapm-tg-43-nath-1995` |
| 2 | [aapm-tg-43u1-rivard-2004.md](sources/07_physics/raw/aapm-tg-43u1-rivard-2004.md) | `kb:phys:tg43:aapm-tg-43u1-rivard-2004` |
| 3 | [aapm-tg-43u1s1-perez-2012.md](sources/07_physics/raw/aapm-tg-43u1s1-perez-2012.md) | `kb:phys:tg43:aapm-tg-43u1s1-perez-2012` |

**ICRU Reports**

| # | File | ID |
|---|------|-----|
| 1 | [icru-38-ic.md](sources/07_physics/raw/icru-38-ic.md) | `kb:phys:icru:icru-38-ic` |
| 2 | [icru-58-is.md](sources/07_physics/raw/icru-58-is.md) | `kb:phys:icru:icru-58-is` |

**IAEA Publications**

| # | File | ID |
|---|------|-----|
| 1 | [iaea-3d-bt-commissioning-2020.md](sources/07_physics/raw/iaea-3d-bt-commissioning-2020.md) | `kb:phys:iaea:iaea-3d-bt-commissioning-2020` |
| 2 | [iaea-trs-398.md](sources/07_physics/raw/iaea-trs-398.md) | `kb:phys:iaea:iaea-trs-398` |

**AAPM Task Groups (Other)**

| # | File | ID |
|---|------|-----|
| 1 | [aapm-tg-148-hdr-qa.md](sources/07_physics/raw/aapm-tg-148-hdr-qa.md) | `kb:phys:aapm_other:aapm-tg-148-hdr-qa` |
| 2 | [aapm-tg-229-mbdca.md](sources/07_physics/raw/aapm-tg-229-mbdca.md) | `kb:phys:aapm_other:aapm-tg-229-mbdca` |
| 3 | [aapm-tg-232-film.md](sources/07_physics/raw/aapm-tg-232-film.md) | `kb:phys:aapm_other:aapm-tg-232-film` |

**AI / Inverse Treatment Planning**

| # | File | ID |
|---|------|-----|
| 1 | [deep-reinforcement-learning-hdr-bt-cervical.md](sources/07_physics/raw/deep-reinforcement-learning-hdr-bt-cervical.md) | `kb:phys:ai_planning:deep-reinforcement-learning-hdr-bt` |

**Afterloader Commissioning**

| # | File | ID |
|---|------|-----|
| 1 | [hdr-afterloader-commissioning-2024.md](sources/07_physics/raw/hdr-afterloader-commissioning-2024.md) | `kb:phys:afterloader:hdr-afterloader-commissioning-2024` |

**3D Printing**

| # | File | ID |
|---|------|-----|
| 1 | [nature-3d-printing-rt-2020.md](sources/07_physics/raw/nature-3d-printing-rt-2020.md) | `kb:phys:3d_printing:nature-3d-printing-rt-2020` |

### frm — Frameworks & Society Initiatives (13 files)

**Society Methodology**

| # | File | ID |
|---|------|-----|
| 1 | [aapm-about.md](sources/08_frameworks/raw/aapm-about.md) | `kb:frm:society_methodology:aapm-about` |
| 2 | [abs-mission.md](sources/08_frameworks/raw/abs-mission.md) | `kb:frm:society_methodology:abs-mission` |
| 3 | [astro-methodology.md](sources/08_frameworks/raw/astro-methodology.md) | `kb:frm:society_methodology:astro-methodology` |
| 4 | [gec-estro-about.md](sources/08_frameworks/raw/gec-estro-about.md) | `kb:frm:society_methodology:gec-estro-about` |
| 5 | [nccn-methodology.md](sources/08_frameworks/raw/nccn-methodology.md) | `kb:frm:society_methodology:nccn-methodology` |

**IAEA / WHO Programs**

| # | File | ID |
|---|------|-----|
| 1 | [iaea-brachy-programme.md](sources/08_frameworks/raw/iaea-brachy-programme.md) | `kb:frm:iaea_who:iaea-brachy-programme` |
| 2 | [iaea-global-bt-initiative-2020.md](sources/08_frameworks/raw/iaea-global-bt-initiative-2020.md) | `kb:frm:iaea_who:iaea-global-bt-initiative-2020` |
| 3 | [who-image-guided-irt-2025.md](sources/08_frameworks/raw/who-image-guided-irt-2025.md) | `kb:frm:iaea_who:who-image-guided-irt-2025` |

**Global Access & Transition**

| # | File | ID |
|---|------|-----|
| 1 | [iaea-india-bt-transition-2023.md](sources/08_frameworks/raw/iaea-india-bt-transition-2023.md) | `kb:frm:global_access:iaea-india-bt-transition-2023` |
| 2 | [lancet-bt-global-demand-2025.md](sources/08_frameworks/raw/lancet-bt-global-demand-2025.md) | `kb:frm:global_access:lancet-bt-global-demand-2025` |
| 3 | [icru-reports-catalogue.md](sources/08_frameworks/raw/icru-reports-catalogue.md) | `kb:frm:global_access:icru-reports-catalogue` |

**Chinese Societies (CSCO / CSTRO)**

| # | File | ID |
|---|------|-----|
| 1 | [csco-bt-chinese.md](sources/08_frameworks/raw/csco-bt-chinese.md) | `kb:frm:chinese:csco-bt-chinese` |
| 2 | [cstro-bt-chinese.md](sources/08_frameworks/raw/cstro-bt-chinese.md) | `kb:frm:chinese:cstro-bt-chinese` |

---

## Limitations

1. **Metadata-only stubs (17 files):** NCCN, ICRU, IAEA, ABS methodology, Chinese society documents (CSCO/CSTRO), ABS mission, ASTRO/ESTRO/NCCN methodology pages — paywalled or behind free registration. Title + URL preserved; full text NOT on this system.
2. **Local-PDF tagged (2 files):** Some Chinese clinical papers reference full-text PDFs that are on the user's separate Windows machine, not this Linux system. The .md files carry `local-pdf` in their frontmatter; abstract/header is preserved.
3. **11 prior PMC full-text files lost during rebuild** (see Verification Provenance). They were the previous migration's subset. Topics they covered: ABS clinical evaluation (vaginal mass), ASTRO post-op RT for endometrial, GEC-ESTRO cervix 2011 Part IV MR-imaging principles, prostate BT systematic review, DEGRO APBI, HDR oral cancer, skin surface BT survey, endoluminal esophageal HDR, GEC-ESTRO ACROP rectal contact BT, AAPM TG-138 dosimetric uncertainty, MRI-guided BT review.
4. **No synthesis beyond what sources say.** This KB does not interpolate, infer, or supplement. Where the source is thin, the KB entry is thin.
5. **No 1:1 mapping to current standard practice.** This KB is a snapshot of the 110 source files we have. A clinical decision must still consult the latest NCCN/ESTRO guidelines and institutional protocols.

---

**End of knowledge base. Total source files: 110. Total entries: 110. Generated 2026-06-17.**