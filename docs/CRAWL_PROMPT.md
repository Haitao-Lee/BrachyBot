# Task: Brachytherapy Clinical Knowledge Base — Source Material Crawling

> **Purpose**: This prompt is used to drive an agent on another computer with public network access to crawl all official authoritative brachytherapy materials, save them as structured Markdown files, transfer them back to this project, and then have this project's agent organize them into the final `clinical_kb/guidelines_brachytherapy.md`.
>
> **Generated date**: 2026-06-17
> **Related files**: `clinical_kb/guidelines_brachytherapy.md` (final KB), `clinical_kb/sources/_crawled/` (directory for storing crawl results)

---

## 1. Your Identity and Goal

You are a clinical literature crawling agent. Task: **crawl all official authoritative brachytherapy materials from the public internet**, save them as structured Markdown files, output them to a folder, so that a downstream agent can build a **clinically referenceable** knowledge base based on these source texts.

You have **only two actions: crawl and save the source text**. Do not summarize, do not rewrite, do not LLM-process. Save exactly what the source text contains. Subsequent processing is done by another agent.

## 2. Working Environment and Tools

- You have the `WebFetch` tool (HTTP GET to fetch web page/PDF text)
- You have the `WebSearch` tool (Google search)
- You have the `Write` tool (save files)
- You have the `Bash` tool (create directories, package)
- You **do not have** a PubMed/ABS subscription, but open-access journals and PDFs are usually accessible
- Encountering 403/paywall/login required: skip, record in MANIFEST, **do not fabricate content**
- Do not invent URLs or paper titles just to pad the count

## 3. Output Directory Structure

**All content is output to `/tmp/brachy_kb_crawl/` (or a user-specified path), and finally packaged into `/tmp/brachy_kb_crawl.tar.gz`.**

```
/tmp/brachy_kb_crawl/
├── 00_meta/
│   ├── MANIFEST.csv                 # Manifest of all crawled items (including failures)
│   ├── FETCH_LOG.md                 # Fetch log: which domains were blocked, which mirrors were used
│   └── SOURCES_BY_CATEGORY.md       # Source list summarized by category
├── 01_gynecologic/
│   ├── INDEX.md                     # Source index for this category
│   └── raw/
│       ├── gec-estro-cervix-2018.md
│       ├── embrace-i-pivotal-2021-lancet-oncol.md
│       ├── abs-cervix-consensus-2018.md
│       └── ...（one .md per source text）
├── 02_prostate_gu/
│   ├── INDEX.md
│   └── raw/
│       ├── abs-2022-prostate-hdr-yamada.md
│       ├── aapm-tg-137-nath-2009.md
│       └── ...
├── 03_breast/
│   ├── INDEX.md
│   └── raw/
│       ├── astro-2022-apbi-consensus.md
│       └── ...
├── 04_head_neck_skin/
│   ├── INDEX.md
│   └── raw/
│       └── ...
├── 05_gi/
│   ├── INDEX.md
│   └── raw/
│       └── ...
├── 06_other_sites/
│   ├── INDEX.md
│   └── raw/
│       └── ...
├── 07_physics/
│   ├── INDEX.md
│   └── raw/
│       ├── aapm-tg-43-nath-1995.md
│       ├── aapm-tg-43u1-rivard-2004.md
│       └── ...
├── 08_frameworks/
│   ├── INDEX.md
│   └── raw/
│       └── ...
└── README.md                         # Crawl notes, source list, incomplete items
```

## 4. Format of Each Source File

For each piece of material crawled, save as `raw/<slug>.md`, **strictly following the template below**:

```markdown
---
title: "<full paper/guideline title, verbatim>"
authors: ["Author1", "Author2", ...]   # or "Writing Committee", "ABS H&N Working Group", etc.
year: 2022
journal: "<journal name or institution>"          # e.g. "Brachytherapy" / "Radiotherapy and Oncology" / "ABS Consensus"
volume: "X(Y)"                    # optional
pages: "Z-W"                      # optional
doi: "10.xxxx/..."                # required, if no DOI write "N/A"
pmid: "12345678"                  # optional
url: "<actual URL crawled>"           # required
fetched_date: "2026-06-17"        # fetch date
fetch_method: "webfetch"          # fetch method
doc_type: "guideline|consensus|journal_paper|task_group_report|review|book_chapter"
category: "01_gynecologic"        # category
priority: "P0|P1|P2"              # see priority below
---

# <Title>

**Full Citation:**
<Authors. Title. Journal. Year. Volume(Issue): Pages. DOI:>

**URL:** <url>

**PMID:** <pmid>

---

## Abstract / Executive Summary
<If the original page has an abstract, copy it verbatim; otherwise fetch the Executive Summary / key conclusion paragraphs>

## Key Recommendations / Main Findings
<List the main findings or recommendations of the original document item by item, each on its own line, preserving the original terms. If the original is a table, keep it as a table.>

## Full Content Excerpt
<The following is the actual source text crawled by WebFetch (may be HTML converted to markdown, or text extracted from PDF); preserve the original structure, tables, and reference lists as much as possible>
<Fetch and save at least 2000 words of body text>

## References (if applicable)
<If a reference list was retrieved, copy it verbatim>

## Notes for downstream agent
<Notes for the downstream agent: which sections are dosimetry specifications, which are clinical evidence, which are historical background. 1-3 sentences.>
```

## 5. MANIFEST.csv Format

`00_meta/MANIFEST.csv`, header:

```csv
category,slug,title,year,journal,doi,pmid,url,fetch_status,fetch_date,local_path,notes
01_gynecologic,gec-estro-cervix-2018,"GEC-ESTRO/ABS recommendations on 3D image-based treatment planning",2018,Radiotherapy and Oncology,10.1016/j.radonc.2018.01.014,...,
```

`fetch_status` values: `fetched` / `partial` / `blocked` / `paywall` / `not_found` / `wrong_url`

## 6. Required Source List (approximately 86 items total, by P0/P1/P2 priority)

### Priority Description

- **P0**: Core guidelines/consensus/RCT results; body text must be retrieved (≥2000 words or full text)
- **P1**: Important supplementary literature/reviews; retrieving abstract + key sections is sufficient (≥500 words)
- **P2**: Background/historical/peripheral literature; title + abstract is sufficient

---

### 01_gynecologic (cervix/vagina/vulva/endometrium) — 12 items

| # | Priority | Title / Description | DOI / URL Hint | Target Local File |
|---|---|---|---|---|
| 1 | P0 | Haie-Meder C, et al. Recommendations from GEC-ESTRO Working Group for 3D image-based treatment planning in cervix cancer BT (2005) | Radiother Oncol 2005;74(3):235-245. DOI: 10.1016/j.radonc.2004.12.013 | gec-estro-cervix-2005-haie-meder.md |
| 2 | P0 | Dimopoulos JCA, et al. Systematic evaluation of MRI findings in advanced cervix cancer; reference for GTV/HR-CTV/IR-CTV (2012) | Radiother Oncol 2012;102(1):112-118. DOI: 10.1016/j.radonc.2011.10.016 | dimopoulos-mri-ctv-2012.md |
| 3 | P0 | Pötter R, et al. EMBRACE-I study: MRI-guided BT in locally advanced cervix cancer — 5-year results (Lancet Oncol 2021) | Lancet Oncol 2021;22(4):538-547. DOI: 10.1016/S1470-2045(20)30753-1 | embrace-i-pivotal-2021-lancet-oncol.md |
| 4 | P0 | EMBRACE-II protocol paper (Tanderup et al., 2018 or update) | DOI: 10.1016/j.radonc.2018.08.025 (or latest) | embrace-ii-protocol.md |
| 5 | P0 | ABS Cervical Cancer Brachytherapy Consensus (2018, possibly 2022 update) | Brachytherapy. DOI: 10.1016/j.brachy.2017.11.013 | abs-cervix-consensus-2018.md |
| 6 | P0 | NCCN Cervical Cancer Guideline (latest version, BT section) | https://www.nccn.org/guidelines/ (free PDF download) | nccn-cervical-2024.md |
| 7 | P0 | ICRU Report 89 (2013) on prescribing, recording, reporting gyn BT | ICRU website | icru-89-gyn.md |
| 8 | P1 | ABS Vaginal Cancer BT Consensus (2019) | Brachytherapy 2019. DOI: 10.1016/j.brachy.2019.05.001 | abs-vaginal-2019.md |
| 9 | P1 | ABS Vulvar Cancer BT Consensus (2019) | Brachytherapy 2019. DOI: 10.1016/j.brachy.2019.07.001 | abs-vulvar-2019.md |
| 10 | P1 | GEC-ESTRO/ESTRO/ABS 2024 Endometrial Cancer BT Consensus | Radiother Oncol 2024 (latest). DOI lookup via PubMed | gec-estro-endometrial-2024.md |
| 11 | P1 | PORTEC-2 (VCB vs EBRT for intermediate-risk endometrial) | Lancet 2010;375(9717):816-823. DOI: 10.1016/S0140-6736(09)62163-2 | portec-2-lancet-2010.md |
| 12 | P1 | PORTEC-3 (chemoRT for high-risk endometrial) | Lancet Oncol 2018. DOI lookup | portec-3-lancet-oncol-2018.md |

### 02_prostate_gu (prostate/bladder/urethra/penis) — 12 items

| # | Priority | Title | DOI / URL | Target Local File |
|---|---|---|---|---|
| 1 | P0 | Yamada Y, et al. ABS 2022 Consensus Guidelines for HDR Prostate Brachytherapy | Brachytherapy 2022. DOI: 10.1016/j.brachy.2021.09.013 | abs-2022-prostate-hdr.md |
| 2 | P0 | Davis BJ, et al. ABS/AUA/ASTRO LDR Permanent Seed Implant Guidelines (2012, 2017 update) | Brachytherapy 2012. DOI: 10.1016/j.brachy.2011.07.005 | abs-aua-astro-ldr-2012.md |
| 3 | P0 | Nath R, et al. AAPM TG-137: Dose prescription and reporting for LDR prostate BT | Med Phys 2009. DOI: 10.1118/1.3233333 | aapm-tg-137-nath-2009.md |
| 4 | P0 | Morris WJ, et al. ASCENDE-RT Trial: 6-year results of LDR boost vs EBRT | IJROBP 2017. DOI: 10.1016/j.ijrobp.2017.05.062 | ascende-rt-morris-2017.md |
| 5 | P0 | AUA/ASTRO 2022 Clinically Localized Prostate Cancer Guideline | DOI lookup | aua-astro-2022-prostate.md |
| 6 | P0 | GEC-ESTRO ACROP Consensus on HDR Prostate BT (2020) | Radiother Oncol 2020. DOI: 10.1016/j.radonc.2020.01.014 | gec-estro-acrop-prostate-2020.md |
| 7 | P1 | GEC-ESTRO/EAU-ESPU Penile Cancer Brachytherapy Guidelines (2018) | Eur Urol 2018. DOI: 10.1016/j.eururo.2017.09.013 | gec-estro-penile-2018.md |
| 8 | P1 | Bladder-Preserving Brachytherapy for Muscle-Invasive Bladder Cancer (multicatheter, intraop) | IJROBP or similar; DOI lookup | bladder-bt-multicatheter.md |
| 9 | P1 | Focal / Ultra-Focal HDR Prostate BT trials (2020-2024) | Various; DOI lookup | focal-prostate-hdr.md |
| 10 | P1 | Salvage / Re-Implant Prostate Brachytherapy (Nguyen, Crook 2018-2019) | DOI lookup | salvage-prostate-bt.md |
| 11 | P2 | Real-Time TRUS Intraoperative Planning (various) | DOI lookup | real-time-trus-planning.md |
| 12 | P2 | Urethral Sparing & Neurovascular Bundle Dosimetry (Mohammed et al.) | DOI lookup | urethra-sparing-nvb.md |

### 03_breast (breast APBI / IORT / boost) — 11 items

| # | Priority | Title | DOI / URL | Target Local File |
|---|---|---|---|---|
| 1 | P0 | ASTRO 2022 APBI Consensus Statement | https://www.astro.org/Patient-Care-and-Research/Clinical-Practice-Statements (free PDF) | astro-2022-apbi.md |
| 2 | P0 | ABS 2016 Consensus Guideline on APBI (and 2018 update) | Brachytherapy 2016. DOI: 10.1016/j.brachy.2016.05.001 | abs-apbi-2016.md |
| 3 | P0 | GEC-ESTRO APBI Recommendations (Strnad et al., 2018) | Radiother Oncol 2018. DOI: 10.1016/j.radonc.2018.01.009 | gec-estro-apbi-2018.md |
| 4 | P0 | Vicini F, et al. NSABP B-39 / RTOG 0413 APBI Trial | Lancet Oncol 2010 or later update | nsabp-b39-vicini-2010.md |
| 5 | P0 | Vaidya JS, et al. TARGIT-A IORT trial (initial 2014 + 20-year update) | Lancet 2014;383(9917):603-613. DOI: 10.1016/S0140-6736(13)61950-9 + 2024 update | targit-a-vaidya.md |
| 6 | P0 | ESTRO 2018 Consensus on APBI (Strnad et al.) | Radiother Oncol 2018 | estro-apbi-2018.md |
| 7 | P1 | NCCN Breast Cancer Guideline (current, BT section) | https://www.nccn.org/guidelines/ | nccn-breast-2024.md |
| 8 | P1 | MammoSite / Balloon-Based Brachytherapy (clinical trials / consensus) | DOI lookup | balloon-mammosite.md |
| 9 | P1 | SAVI Strut-Based APBI (Yashar et al.) | DOI lookup | savi-strut-apbi.md |
| 10 | P1 | WBI + Brachytherapy Boost (EORTC 22881, START) | DOI lookup | wbi-boost-eortc.md |
| 11 | P1 | Intraoperative Electronic BT (Intrabeam, Xoft) | DOI lookup | iort-electronic-bt.md |

### 04_head_neck_skin (head & neck + skin) — 10 items

| # | Priority | Title | DOI / URL | Target Local File |
|---|---|---|---|---|
| 1 | P0 | ABS Head & Neck Interstitial Brachytherapy Consensus (Shah et al., 2018) | Brachytherapy 2018. DOI: 10.1016/j.brachy.2018.01.009 | abs-hn-2018.md |
| 2 | P0 | GEC-ESTRO Head & Neck BT Recommendations | DOI lookup (likely 2017-2018) | gec-estro-hn.md |
| 3 | P0 | GEC-ESTRO/ESTRO Skin Cancer BT Recommendations (2018) | Radiother Oncol 2018. DOI lookup | gec-estro-skin-2018.md |
| 4 | P0 | ABS Skin Cancer Brachytherapy Consensus (2020) | Brachytherapy 2020. DOI: 10.1016/j.brachy.2020.01.001 | abs-skin-2020.md |
| 5 | P1 | NCCN Head and Neck Cancer Guideline (BT section) | nccn.org | nccn-hn-2024.md |
| 6 | P1 | Lip Cancer BT (GEC-ESTRO or ABS) | DOI lookup | lip-cancer-bt.md |
| 7 | P1 | Freiburg Flap / HAM Applicators (paper) | Strahlenther Onkol or similar | freiburg-flap-ham.md |
| 8 | P1 | Esteya Electronic Surface Therapy | DOI lookup | esteya-electronic.md |
| 9 | P1 | Keloid Brachytherapy (post-op, superficial) | DOI lookup | keloid-bt.md |
| 10 | P2 | Nasopharyngeal BT (intracavitary) | DOI lookup | npc-intracavitary-bt.md |

### 05_gi (esophagus/rectum/anus/bile duct/pancreas/stomach) — 11 items

| # | Priority | Title | DOI / URL | Target Local File |
|---|---|---|---|---|
| 1 | P0 | ABS Esophageal Brachytherapy Consensus (2014) | Brachytherapy 2014. DOI: 10.1016/j.brachy.2014.07.001 | abs-esophageal-2014.md |
| 2 | P0 | NCCN Esophageal Cancer Guideline (current, BT section) | nccn.org | nccn-esophageal-2024.md |
| 3 | P0 | Sun Myint A, et al. OPERA Phase III Trial: Contact X-Ray BT Boost in Rectal Cancer | Lancet Oncol 2023 (or JAMA). DOI: 10.1016/S1470-2045(23)00149-X (or lookup) | opera-trial-sun-myint.md |
| 4 | P0 | Papillon Contact X-Ray Brachytherapy for Early Rectal Cancer (technique + outcomes) | DOI lookup (multiple Sun Myint papers) | papillon-contact-xray.md |
| 5 | P1 | GEC-ESTRO Anal Cancer BT Boost Consensus (2018) | DOI lookup | gec-estro-anal-bt-2018.md |
| 6 | P1 | HDR Intracavitary BT for Recurrent Rectal Cancer | IJROBP. DOI lookup | rectal-recurrence-hdr.md |
| 7 | P1 | Bile Duct / Cholangiocarcinoma Intraluminal HDR BT (PTBD/ERCP technique) | DOI lookup | bileduct-cholangiocarcinoma-ptbd.md |
| 8 | P0 | Chinese CSTRO/CSCO I-125 Seed Implantation Expert Consensus for Pancreatic Cancer (2017/2020) | CSTRO/CSCO website (Chinese) | cstro-pancreatic-i125-2017.md |
| 9 | P0 | Wang J, et al. I-125 seed implantation for pancreatic cancer: clinical evidence / multicenter trials | PMID lookup (likely 2015-2020) | pancreatic-i125-clinical.md |
| 10 | P1 | I-125 + Gemcitabine for LAPC (Chinese trials) | PMID lookup | pancreatic-i125-gemcitabine.md |
| 11 | P2 | Gastric Brachytherapy review | DOI lookup | gastric-bt.md |

### 06_other_sites (lung/brain/eye/sarcoma/pediatric/vascular) — 10 items

| # | Priority | Title | DOI / URL | Target Local File |
|---|---|---|---|---|
| 1 | P0 | Goldman JM, et al. (or ABS) Endobronchial Brachytherapy Consensus | DOI lookup | endobronchial-bt-consensus.md |
| 2 | P0 | BRACHY Trial (Surveillance or similar) for endobronchial BT | DOI lookup | brachy-trial-lung.md |
| 3 | P1 | GliaSite Brain Brachytherapy (I-125 balloon) | IJROBP. DOI lookup | gliasite-brain.md |
| 4 | P1 | GammaTile (Cs-131 collagen tile) for brain | DOI lookup | gammatile-brain.md |
| 5 | P0 | ABS / AAPM TG-129 Uveal Melanoma Episcleral Plaque Dosimetry | Med Phys 2012. DOI: 10.1118/1.3694668 | aapm-tg-129-uveal-melanoma.md |
| 6 | P0 | COMS (Collaborative Ocular Melanoma Study) — Medium-size Trial Report | Arch Ophthalmol 2001/2006 (medium trial) | coms-trial-medium.md |
| 7 | P0 | ABS Soft Tissue Sarcoma Brachytherapy Consensus (most recent) | Brachytherapy. DOI lookup | abs-sarcoma-bt.md |
| 8 | P1 | Pediatric Rhabdomyosarcoma BT (IRS-V / COG protocols) | DOI lookup | pediatric-rhabdomyosarcoma-bt.md |
| 9 | P2 | Vascular Brachytherapy (Sr-90, P-32) for in-stent restenosis (historical) | DOI lookup (pre-2005) | vascular-bt-sr90.md |
| 10 | P2 | Cardiac / Vascular BT review (recent reappraisal) | DOI lookup | cardiac-vascular-review.md |

### 07_physics (physics and dosimetry) — 11 items

| # | Priority | Title | DOI / URL | Target Local File |
|---|---|---|---|---|
| 1 | P0 | Nath R, et al. AAPM TG-43: Dosimetry of Interstitial Brachytherapy Sources (1995) | Med Phys 1995;22(2):209-234. DOI: 10.1118/1.597458 | aapm-tg-43-nath-1995.md |
| 2 | P0 | Rivard MJ, et al. Update of AAPM TG-43: Revised Protocol for Brachytherapy Dose Calculations (2004) | Med Phys 2004;31(3):633-674. DOI: 10.1118/1.1646040 | aapm-tg-43u1-rivard-2004.md |
| 3 | P0 | Perez-Calatayud J, et al. AAPM TG-43 U1S1: Update with High-Energy Sources (2012) | Med Phys 2012. DOI: 10.1118/1.3694668 (or related) | aapm-tg-43u1s1-perez-2012.md |
| 4 | P0 | Beaulieu L, et al. AAPM TG-229: Report on Model-Based Dose Calculation (MBDCA) for Brachytherapy (2012) | Med Phys 2012. DOI: 10.1118/1.4738004 | aapm-tg-229-mbdca.md |
| 5 | P1 | AAPM TG-232: Radiochromic Film Dosimetry (2012) | Med Phys 2012. DOI: 10.1118/1.4754544 | aapm-tg-232-film.md |
| 6 | P1 | Thomadsen BR, et al. AAPM TG-100: FMEA for Brachytherapy (2016) | Med Phys 2016. DOI: 10.1002/mp.12139 | aapm-tg-100-fmea.md |
| 7 | P1 | AAPM TG-167: Electronic Brachytherapy (2017) | Med Phys 2017. DOI: 10.1002/mp.12056 | aapm-tg-167-electronic.md |
| 8 | P1 | AAPM TG-148: HDR Remote Afterloader QA | Med Phys 2012. DOI: 10.1118/1.3694668 (or similar) | aapm-tg-148-hdr-qa.md |
| 9 | P0 | ICRU Report 38 (1985): Dose and Volume Specification for Intracavitary BT | ICRU website | icru-38-ic.md |
| 10 | P0 | ICRU Report 58 (1997): Dose and Volume Specification for Interstitial BT | ICRU website | icru-58-is.md |
| 11 | P0 | IAEA TRS-398: Absorbed Dose Determination in Photon and Electron Beams (BT section) | IAEA website | iaea-trs-398.md |

### 08_frameworks (societies and frameworks) — 9 items

| # | Priority | Title | DOI / URL | Target Local File |
|---|---|---|---|---|
| 1 | P1 | ABS Mission and Guideline Methodology | https://www.americanbrachytherapy.org/about | abs-mission.md |
| 2 | P1 | GEC-ESTRO / ESTRO Working Group Structure | https://www.estro.org/Groups/GEC-ESTRO | gec-estro-about.md |
| 3 | P1 | NCCN Methodology | https://www.nccn.org/guidelines/development | nccn-methodology.md |
| 4 | P1 | ASTRO Clinical Practice Guideline Methodology | https://www.astro.org/Patient-Care-and-Research/Clinical-Practice-Statements | astro-methodology.md |
| 5 | P1 | AAPM Guidelines and Code of Ethics | https://www.aapm.org/ | aapm-about.md |
| 6 | P1 | IAEA Brachytherapy Programme / Human Health Series | https://www.iaea.org/health/radiation-oncology/brachytherapy | iaea-brachy-programme.md |
| 7 | P1 | ICRU Reports Catalogue | https://www.icru.org/home/reports | icru-reports-catalogue.md |
| 8 | P1 | CSCO Brachytherapy Guidelines (Chinese) | https://www.csco.org.cn/ | csco-bt-chinese.md |
| 9 | P1 | CSTRO Chinese Brachytherapy Consensus | http://www.cstro.org/ | cstro-bt-chinese.md |

---

**86 items in total.** Target crawl success rate ≥70%.

## 7. Execution Flow (strict order)

1. **Create the directory skeleton** (`mkdir -p`)
2. **Crawl P0 first** (~45 items total)
3. **Then crawl P1** (~25 items total)
4. **Finally crawl P2** (~16 items total)
5. **Generate INDEX.md for each category** (auto-generated from MANIFEST)
6. **Write FETCH_LOG.md**: record which domains were blocked, which mirrors were used, and why some sources failed
7. **Write README.md**: crawl overview, success/failure statistics, notes
8. **Package**: `cd /tmp && tar czf brachy_kb_crawl.tar.gz brachy_kb_crawl/`

## 8. Crawling Strategy (Critical!)

### Priority 1: Open-Access PDF / Full Text

- PMC (PubMed Central): all PMC articles are free
- Journal open content: most red journal / blue journal / green journal articles become open 12 months after publication
- Guideline PDFs on society websites: ABS, GEC-ESTRO, NCCN, ASTRO mostly have free PDF download links
- Preprints: medRxiv, arXiv, ResearchGate

### Priority 2: Abstract + Key Sections

- If the full text is paywalled, at least fetch abstract + intro + key results sections
- At least 500 words of substantive content

### Priority 3: Record metadata only

- If completely blocked, record only one row in MANIFEST, mark URL as `fetch_status=blocked`

### Strictly Prohibited

- ❌ Fabricating content when a fetch fails
- ❌ Filling in with training data
- ❌ Rewriting or "translating" the source text
- ❌ Mixing different sources together

## 9. Quality Self-Check (mandatory before completion)

After completion, check:

- [ ] MANIFEST.csv exists and every row is correctly formatted
- [ ] FETCH_LOG.md exists and honestly records all blocks/failures
- [ ] Each P0 file is ≥2000 words (check with `wc -w`)
- [ ] Each file has correct frontmatter (DOI, URL, fetch_date)
- [ ] README.md contains overview + success/failure statistics
- [ ] Folder is organized into 8 categories
- [ ] tar.gz successfully generated

The last line of output should be:

```
✅ Done. /tmp/brachy_kb_crawl.tar.gz ready (size: X MB, X/86 sources fetched).
```

## 10. Expected Deliverables

A `.tar.gz` file (~30-100 MB), passed to the main session's agent, which will build the final `clinical_kb/guidelines_brachytherapy.md` based on these source texts.

---

## Appendix A: Next Steps After Crawling (handoff instructions for the user)

1. Download `brachy_kb_crawl.tar.gz` to the local machine
2. Extract to `clinical_kb/sources/_crawled/`
3. Notify the main project's agent (the one running the `brachy_kb_crawl` workflow)
4. The main agent will:
   - File each source text into its proper place under the 8 categories
   - Extract key dose/fractionation/OAR data and structure it into `guidelines_brachytherapy.md`
   - Delete the existing 121 reconstructed files
   - Update `INDEX.md` to add "verification status" tags
   - Regenerate the main KB

## Appendix B: Network Access Reference List

Common domains the crawling agent should **be able to access** (no login required):

- `https://pubmed.ncbi.nlm.nih.gov/`
- `https://www.ncbi.nlm.nih.gov/pmc/` (PMC free)
- `https://europepmc.org/`
- `https://www.americanbrachytherapy.org/` (ABS guidelines)
- `https://www.estro.org/` (GEC-ESTRO, ESTRO)
- `https://www.nccn.org/guidelines/` (free PDF)
- `https://www.astro.org/`
- `https://www.aapm.org/pubs/reports/` (TG reports)
- `https://www.icru.org/home/reports/`
- `https://www.iaea.org/publications/`
- `https://www.sciencedirect.com/` (Elsevier, partial OA)
- `https://www.redjournal.org/` (IJROBP — 12-month delay OA)
- `https://www.brachyjournal.com/`
- `https://www.thegreenjournal.com/` (Radiother Oncol)
- `https://www.thelancet.com/journals/lanonc/` (Lancet Oncology)
- `https://www.nejm.org/`
- `https://doi.org/` (DOI resolver, redirects to actual)
- `https://scholar.google.com/`
- `https://www.researchgate.net/` (publicly visible papers)
- `https://www.cstro.org/`, `https://www.csco.org.cn/` (Chinese societies)

If a domain is blocked in your environment, **record it in FETCH_LOG.md**; do not fabricate.
