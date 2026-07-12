# 任务：Brachytherapy 临床知识库 — 原始资料抓取

> **用途**：本 prompt 用于在另一台有公开网络访问权限的电脑上驱动一个 agent，把 brachytherapy（近距离放射治疗）的全部官方权威资料抓取下来，保存为结构化的 Markdown 文件，传回本项目，再由本项目的 agent 整理成最终的 `clinical_kb/guidelines_brachytherapy.md`。
>
> **生成日期**：2026-06-17
> **关联文件**：`clinical_kb/guidelines_brachytherapy.md`（最终 KB），`clinical_kb/sources/_crawled/`（放置抓取结果的目录）

---

## 1. 你的身份与目标

你是一个临床文献抓取 agent。任务：**从公开网络抓取 brachytherapy（近距离放射治疗）的全部官方权威资料**，保存为结构化的 Markdown 文件，输出到一个文件夹，让后续 agent 可以基于这些原文构建一个**临床可参考**的知识库。

你**只有抓取和保存原文**两个动作。不要总结、不要改写、不要 LLM 加工。原文抓什么就存什么。后续处理由别的 agent 做。

## 2. 工作环境与工具

- 你有 `WebFetch` 工具（HTTP GET 抓取网页/PDF 文本）
- 你有 `WebSearch` 工具（Google 搜索）
- 你有 `Write` 工具（保存文件）
- 你有 `Bash` 工具（建目录、打包）
- 你**没有** PubMed/ABS 订阅，但 open-access 期刊和 PDF 通常可访问
- 遇到 403/付费墙/必须登录：跳过，记到 MANIFEST，**不要伪造内容**
- 不要为了凑数编造 URL 或论文标题

## 3. 输出目录结构

**所有内容输出到 `/tmp/brachy_kb_crawl/`（或用户指定路径），最终打包成 `/tmp/brachy_kb_crawl.tar.gz`。**

```
/tmp/brachy_kb_crawl/
├── 00_meta/
│   ├── MANIFEST.csv                 # 所有抓取项的清单（含失败项）
│   ├── FETCH_LOG.md                 # 抓取日志：哪些域被屏蔽、用了哪些镜像
│   └── SOURCES_BY_CATEGORY.md       # 按分类汇总的来源列表
├── 01_gynecologic/
│   ├── INDEX.md                     # 本分类的来源索引
│   └── raw/
│       ├── gec-estro-cervix-2018.md
│       ├── embrace-i-pivotal-2021-lancet-oncol.md
│       ├── abs-cervix-consensus-2018.md
│       └── ...（每份原文一个 .md）
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
└── README.md                         # 抓取说明、源列表、未完成项
```

## 4. 每个原文文件的格式

每抓到一份资料，存为 `raw/<slug>.md`，**严格按以下模板**：

```markdown
---
title: "<完整论文/指南标题，verbatim>"
authors: ["作者1", "作者2", ...]   # 或 "Writing Committee", "ABS H&N Working Group" 等
year: 2022
journal: "<期刊名或机构>"          # 例 "Brachytherapy" / "Radiotherapy and Oncology" / "ABS Consensus"
volume: "X(Y)"                    # 可选
pages: "Z-W"                      # 可选
doi: "10.xxxx/..."                # 必填，如无 DOI 写 "N/A"
pmid: "12345678"                  # 可选
url: "<抓取的实际 URL>"           # 必填
fetched_date: "2026-06-17"        # 抓取日期
fetch_method: "webfetch"          # 抓取方式
doc_type: "guideline|consensus|journal_paper|task_group_report|review|book_chapter"
category: "01_gynecologic"        # 分类
priority: "P0|P1|P2"              # 见下方优先级
---

# <Title>

**完整引用（Citation）:**
<作者. 标题. 期刊. 年. 卷(期): 页. DOI:>

**URL:** <url>

**PMID:** <pmid>

---

## Abstract / Executive Summary
<如果原网页有 abstract，verbatim 复制；没有就抓取 Executive Summary / 关键结论段>

## Key Recommendations / Main Findings
<逐条列出原文件的主要发现或推荐，每条独立成行，保留原文术语。原文是表就保留为表。>

## Full Content Excerpt
<以下内容是 WebFetch 抓取的实际原文（可能是 HTML 转 markdown、或 PDF 提取的文本），尽量保留原始结构、表格、参考文献列表>
<至少抓取并保存 2000 词以上的正文>

## References (if applicable)
<如果抓到了参考文献列表，verbatim 复制>

## Notes for downstream agent
<留给后续 agent 看的备注：哪些章节是剂量学规范、哪些是临床证据、哪些是历史背景。1-3 句话。>
```

## 5. MANIFEST.csv 格式

`00_meta/MANIFEST.csv`，表头：

```csv
category,slug,title,year,journal,doi,pmid,url,fetch_status,fetch_date,local_path,notes
01_gynecologic,gec-estro-cervix-2018,"GEC-ESTRO/ABS recommendations on 3D image-based treatment planning",2018,Radiotherapy and Oncology,10.1016/j.radonc.2018.01.014,...,
```

`fetch_status` 取值：`fetched` / `partial` / `blocked` / `paywall` / `not_found` / `wrong_url`

## 6. 必须抓取的来源清单（共约 86 项，按 P0/P1/P2 优先级）

### 优先级说明

- **P0**：核心指南/共识/RCT 结果，必须抓到正文（≥2000 词或全文）
- **P1**：重要补充文献/综述，抓到 abstract + 关键章节即可（≥500 词）
- **P2**：背景/历史/边缘文献，标题+abstract 即可

---

### 01_gynecologic（宫颈/阴道/外阴/子宫内膜）— 12 项

| # | 优先级 | 标题 / 描述 | DOI / URL 提示 | 目标本地文件 |
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

### 02_prostate_gu（前列腺/膀胱/尿道/阴茎）— 12 项

| # | 优先级 | 标题 | DOI / URL | 目标本地文件 |
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

### 03_breast（乳腺 APBI / IORT / boost）— 11 项

| # | 优先级 | 标题 | DOI / URL | 目标本地文件 |
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

### 04_head_neck_skin（头颈 + 皮肤）— 10 项

| # | 优先级 | 标题 | DOI / URL | 目标本地文件 |
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

### 05_gi（食管/直肠/肛门/胆管/胰腺/胃）— 11 项

| # | 优先级 | 标题 | DOI / URL | 目标本地文件 |
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

### 06_other_sites（肺/脑/眼/肉瘤/儿科/血管）— 10 项

| # | 优先级 | 标题 | DOI / URL | 目标本地文件 |
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

### 07_physics（物理与剂量学）— 11 项

| # | 优先级 | 标题 | DOI / URL | 目标本地文件 |
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

### 08_frameworks（学会与框架）— 9 项

| # | 优先级 | 标题 | DOI / URL | 目标本地文件 |
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

**总计 86 项。** 目标抓取成功率 ≥70%。

## 7. 执行流程（严格按顺序）

1. **建立目录骨架**（`mkdir -p`）
2. **先抓 P0**（共 ~45 项）
3. **再抓 P1**（共 ~25 项）
4. **最后抓 P2**（共 ~16 项）
5. **每个分类生成 INDEX.md**（基于 MANIFEST 自动生成）
6. **写 FETCH_LOG.md**：记录哪些域被屏蔽、用了哪些镜像、为何某些来源失败
7. **写 README.md**：抓取总览、成功/失败统计、注意事项
8. **打包**：`cd /tmp && tar czf brachy_kb_crawl.tar.gz brachy_kb_crawl/`

## 8. 抓取策略（关键！）

### 优先级 1：开放访问 PDF / 全文

- PMC（PubMed Central）：所有 PMC 文章都是免费的
- 期刊开放内容：多数 red journal / blue journal / green journal 文章发表 12 个月后开放
- 学会官网的指南 PDF：ABS, GEC-ESTRO, NCCN, ASTRO 大多有免费 PDF 下载链接
- 预印本：medRxiv, arXiv, ResearchGate

### 优先级 2：摘要 + 关键章节

- 如果全文付费，至少抓 abstract + intro + 关键结果章节
- 至少 500 词的实质内容

### 优先级 3：只记录 metadata

- 如果完全 blocked，只在 MANIFEST 记一行，URL 标 `fetch_status=blocked`

### 严禁

- ❌ 抓不到就编造内容
- ❌ 用训练数据补全
- ❌ 改写或"翻译"原文
- ❌ 把不同来源混在一起

## 9. 质量自检（完成前必做）

完成后检查：

- [ ] MANIFEST.csv 存在且每行格式正确
- [ ] FETCH_LOG.md 存在且诚实记录所有屏蔽/失败
- [ ] 每份 P0 文件 ≥2000 词（用 `wc -w` 检查）
- [ ] 每份文件有正确的 frontmatter（DOI, URL, fetch_date）
- [ ] README.md 含总览 + 成功/失败统计
- [ ] 文件夹按 8 分类组织
- [ ] tar.gz 成功生成

输出最后一行应该是：

```
✅ Done. /tmp/brachy_kb_crawl.tar.gz ready (size: X MB, X/86 sources fetched).
```

## 10. 预期产出

一个 `.tar.gz` 文件（~30-100 MB），传给主会话的 agent，它会基于这些原文构建最终的 `clinical_kb/guidelines_brachytherapy.md`。

---

## 附录 A：抓取后下一步（给用户的交接说明）

1. 把 `brachy_kb_crawl.tar.gz` 下载到本机
2. 解压到 `clinical_kb/sources/_crawled/`
3. 通知主项目的 agent（运行 `brachy_kb_crawl` 工作流的）
4. 主 agent 会：
   - 把每份原文按 8 分类归位
   - 提取关键 dose/fractionation/OAR 数据，结构化进 `guidelines_brachytherapy.md`
   - 删除旧有的 121 个 reconstructed 文件
   - 更新 `INDEX.md` 加 "verification status" 标签
   - 重新生成主 KB

## 附录 B：网络访问参考清单

抓取 agent 应该**能访问**的常用域（不需要登录）：

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

如果某个域在你的环境被屏蔽，**记录到 FETCH_LOG.md**，不要伪造。
