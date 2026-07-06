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
