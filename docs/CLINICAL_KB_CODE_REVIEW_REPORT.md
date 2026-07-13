# BrachyBot Clinical KB — Code Review 报告

**报告日期：** 2026-06-18
**审查对象：** `clinical_kb/guidelines_brachytherapy.md` (5,690 行, 265 KB, 109 个源文件条目)
**审查模式：** Extra-high recall（宁可误报不漏报）
**审查方法：** 9 个独立 finder angles + 1 个 sweep pass，1-vote 验证
**审查工具：** 8 个并行 sub-agent + 主会话直接验证

---

## 0. 摘要 (TL;DR)

本次审查覆盖了将 KB 从**平铺结构**（2,663 行）改造为**树形结构**（5,690 行）的完整 diff。改造主要目的：让 LLM 能用稳定 ID、topic tags、cross-references 索引相关知识。

**结论：改造基本成功，但发现 15 个需要修复的严重问题。**

| 等级 | 数量 | 摘要 |
|------|------|------|
| 🔴 Critical | 2 | Part I 入口链接 2 个 broken（点击跳到顶部） |
| 🟠 High | 6 | 章节标题错位、Journal 字段错误、文件计数 110 vs 109 不一致、Topic Index 计数 bug |
| 🟡 Medium | 6 | 复数语法错误、3 个空壳条目、CSCO/CSTRO 内容完全相同、ICRU 错误归类、Topic tag 命名分歧 |
| 🟢 Low | 1 | "Journal: Various" 占位符 |

**推荐：** 立即修复 Critical + High（8 个），可在 30-60 分钟内通过 Python 脚本批量完成。

---

## 1. 改造概述

### 1.1 改造目标

用户要求将原本"平铺直叙"的 KB 改造为"树形结构"，让 LLM 能：
- 按路径精确定位条目（`kb:cat:sub:file-slug`）
- 按 topic tag 过滤聚类
- 按 cross-references 探索关联
- 按 Topic Index 反向查询

### 1.2 改造前后对比

| 指标 | 改造前 | 改造后 | 变化 |
|------|--------|--------|------|
| 总行数 | 2,663 | 5,690 | +114% |
| 文件大小 | 145 KB | 265 KB | +83% |
| 源文件 | 110 | 110 | 0 |
| 稳定 ID | 0 | 111 | +111 |
| Topic tags | 0 | 109 | +109 |
| See also 段 | 0 | 108 | +270 链接 |
| Topic Index | 0 | 415 topics | 新增 |
| Cross-cutting tables | 5 | 5 | 保留 |

### 1.3 改造涉及的具体修改

1. **结构重组**：8 章节 → 8 章节 × 5-7 sub-topics
2. **新增 ID 系统**：每个条目 `<a id="kb:cat:sub:file"></a>` 锚点
3. **新增 Topic tags**：每条目 `**Topics:** \`tag1\`, \`tag2\`, ...`
4. **新增 See also 段**：同试验/同疾病/同基础条目间互相引用
5. **新增 Topic Index**：415 个 topic → 109 个条目 ID 的反向索引
6. **新增 Part I Foundations**：8 篇 cornerstone paper 入口
7. **删除冗余**：35 条 "File contains X only" 元描述
8. **删除 33 个虚假 N/A 链接**
9. **修正 1 个 broken link**（icru-89: 07_physics → 01_gynecologic）

---

## 2. 详细问题清单（按严重度排序）

### 🔴 Finding #1: Part I Foundations cornerstone 链接 #1 broken

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 116
**等级：** Critical
**发现者：** Angle C, D, E (交叉验证)

**问题描述：**
```markdown
- [GEC-ESTRO 2005 Haie-Meder (foundation paper)](#kb:gyn:cervix:gec-estro-cervix-2005-haie-meder)
```

但实际定义的 anchor 在 line 315：
```markdown
<a id="kb:gyn:cervix:gec-estro-cervix-2005-haie"></a>
```

**根本原因：** `make_id()` 函数把超过 60 字符的 filename slug 截断了，但 Part I 引用处用了**完整的** filename `gec-estro-cervix-2005-haie-meder`。这是 anchor 定义和引用之间的人为不一致。

**失败场景：**
- 用户从 Part I 点击"GEC-ESTRO 2005 Haie-Meder (foundation paper)"→ 跳到文档顶部
- RAG 系统基于 Part I 生成引用 → 死链
- PDF 导出的目录索引失效

**修复方案：**

```python
# 在 KB 文件第 116 行，将：
# [GEC-ESTRO 2005 Haie-Meder (foundation paper)](#kb:gyn:cervix:gec-estro-cervix-2005-haie-meder)
# 改为：
# [GEC-ESTRO 2005 Haie-Meder (foundation paper)](#kb:gyn:cervix:gec-estro-cervix-2005-haie)

# 同样的修复应用到 line 118：
# [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet-oncol)
# 改为：
# [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet)
```

或者，更彻底的修复：让 `make_id()` 函数**不截断**，而是保留完整 slug：

```python
def make_id(cat_key, sub_key, fname):
    """Generate stable ID from category, subtopic, filename. No truncation."""
    cat_short = CAT_DISPLAY[cat_key][2]
    base = fname.replace('.md', '').replace('.txt', '')
    return f"kb:{cat_short}:{sub_key}:{base}"
```

**验证方法：**
```bash
# 1. 列出所有 anchor 定义
grep -oE '<a id="(kb:gyn:cervix:gec-estro-cervix-2005-haie[^"]*)"' guidelines_brachytherapy.md | sort -u
# 2. 列出所有相关引用
grep -oE '\[GEC-ESTRO 2005[^]]*\]\(#kb:gyn:cervix:gec-estro-cervix-2005-haie[^)]*\)' guidelines_brachytherapy.md
# 3. 对比两者必须 1:1 匹配
```

---

### 🔴 Finding #2: Part I Foundations cornerstone 链接 #2 broken

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 118
**等级：** Critical
**发现者：** Angle C, D, E (交叉验证)

**问题描述：**
```markdown
- [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet-oncol)
```

实际 anchor 在 line 257：
```markdown
<a id="kb:gyn:cervix:embrace-i-pivotal-2021-lancet"></a>
```

**根本原因：** 同 #1，slug 被截断。

**失败场景：** 同 #1。

**修复方案：**

```python
# 在 KB 文件第 118 行直接修改
# [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet-oncol)
# →
# [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet)
```

或采用 #1 的不截断方案。

**验证方法：**
```bash
python3 -c "
import re
text = open('guidelines_brachytherapy.md').read()
defined = set(re.findall(r'<a id=\"(kb:gyn:cervix:embrace-i-pivotal-2021-lancet[^\"]*)\"', text))
referenced = set(re.findall(r'#(kb:gyn:cervix:embrace-i-pivotal-2021-lancet[^)\"]*)', text))
print(f'Defined: {defined}')
print(f'Referenced: {referenced}')
print(f'Match: {defined == referenced}')
"
```

---

### 🟠 Finding #3: 8 个 entry 标题被章节标题覆盖

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 142, 1143, 1190, 1891, 2224, 2623, 3001, 3161
**等级：** High
**发现者：** Angle A, sweep pass

**问题描述：**
8 个 entry 的 `#### Title` 行不是论文标题，而是父章节的标题。

```markdown
# Line 142: 第一条 entry (abs-cervix-consensus-2012-part1)
#### 01_gynecologic — Gynecologic Brachytherapy (17 files)   ← BUG：应该是论文标题

# Line 1141: aapm-tg-137-nath-2009
#### 02_prostate_gu — Prostate & Genitourinary Brachytherapy (14 files)

# Line 1190: abs-apbi-2013
#### 03_breast — Breast Brachytherapy (13 files)

# Line 1891: abs-hn-2018
#### 04_head_neck_skin — Head & Neck / Skin Brachytherapy (12 files)

# Line 2222: 3d-template-i125-pancreatic-2018
#### 05_gi — Gastrointestinal Brachytherapy (15 files)

# Line 2623: aapm-tg-129-uveal-melanoma
#### 06_other_sites — Other Sites Brachytherapy (13 files)

# Line 3001: aapm-tg-148-hdr-qa
#### 07_physics — Physics & Dosimetry (13 files)

# Line 3161: aapm-about
#### 08_frameworks — Frameworks & Society Initiatives (13 files)
```

**根本原因：** 在 rebuild 脚本中，可能对每个章节的"第一个 entry"误用了章节标题。这 8 个 entry 各自对应一个分类的第一个文件，恰好章节标题被错误复制。

**失败场景：**
- 用户按 `#### Title` 导航时看到的是分类标题而非论文标题
- 影响目录可读性
- 但 stable ID 和内容都是正确的，所以 RAG 自动检索不受影响

**修复方案：**

这 8 个 entry 的真实 frontmatter title 已经在 source 文件中，可以直接从源文件 frontmatter 提取：

```python
# 修复脚本
import yaml
import re
from pathlib import Path

ROOT = Path("/home/lht/snap/brachyplan/BrachyBot/clinical_kb")
KB = ROOT / "guidelines_brachytherapy.md"
SRC = ROOT / "sources"

KB_TEXT = KB.read_text(encoding='utf-8')

# 对每个损坏的 entry，找到其 stable ID，从源文件读取正确 title，替换
ENTRIES_TO_FIX = [
    # (stable_id, expected_line_pattern, source_file)
    ("kb:gyn:cervix:abs-cervix-consensus-2012-part1", "01_gynecologic — Gynecologic Brachytherapy", "abs-cervix-consensus-2012-part1.md"),
    ("kb:pros:guidelines:aapm-tg-137-nath-2009", "02_prostate_gu — Prostate & Genitourinary Brachytherapy", "aapm-tg-137-nath-2009.md"),
    # ... 其他 6 个
]

for entry_id, wrong_title, source_file in ENTRIES_TO_FIX:
    # 从源文件 frontmatter 读真实 title
    src_path = SRC / entry_id.split(":")[1] / "raw" / source_file
    # 根据 entry_id 推断 category
    cat_map = {"gyn": "01_gynecologic", "pros": "02_prostate_gu", "brst": "03_breast",
               "hns": "04_head_neck_skin", "gi": "05_gi", "oth": "06_other_sites",
               "phys": "07_physics", "frm": "08_frameworks"}
    cat = cat_map[entry_id.split(":")[1]]
    src_path = SRC / cat / "raw" / source_file
    
    src_text = src_path.read_text(encoding='utf-8', errors='replace')
    m = re.search(r'^title:\s*"([^"]+)"', src_text, re.MULTILINE)
    real_title = m.group(1) if m else "Unknown"
    
    # 在 KB 中找到 entry 并替换 #### 行
    # ... 复杂的字符串处理 ...
```

更简单：直接手动修复这 8 行（用 Edit 工具）：

| Line | 替换 |
|------|------|
| 142 | `#### 01_gynecologic — Gynecologic Brachytherapy (17 files)` → `#### American Brachytherapy Society consensus guidelines for locally advanced carcinoma of the cervix. Part I: general principles (2012)` |
| 1141 | `#### 02_prostate_gu — Prostate & Genitourinary Brachytherapy (14 files)` → `#### Erratum: AAPM recommendations on dose prescription and reporting methods for permanent interstitial brachytherapy for prostate cancer: Report of Task Group 137 (2009)` |
| 1190 | `#### 03_breast — Breast Brachytherapy (13 files)` → `#### Recurrence rates for patients with early-stage breast cancer treated with IOERT at a community hospital per the ASTRO consensus statement for APBI (2013)` |
| 1891 | `#### 04_head_neck_skin — Head & Neck / Skin Brachytherapy (12 files)` → `#### The American College of Radiology and the American Brachytherapy Society practice parameter for the performance of low-dose-rate brachytherapy (2018)` |
| 2224 | `#### 05_gi — Gastrointestinal Brachytherapy (15 files)` → `#### Preliminary application of 3D-printed coplanar template for iodine-125 seed implantation therapy in patients with advanced pancreatic cancer (2018)` |
| 2623 | `#### 06_other_sites — Other Sites Brachytherapy (13 files)` → `#### AAPM TG-129: Uveal Melanoma Plaque Dosimetry (2020)` |
| 3001 | `#### 07_physics — Physics & Dosimetry (13 files)` → `#### GEC-ESTRO/ACROP recommendations for quality assurance of ultrasound imaging in brachytherapy (2012)` |
| 3161 | `#### 08_frameworks — Frameworks & Society Initiatives (13 files)` → `#### AAPM Guidelines and Code of Ethics (2024)` |

**验证方法：**
```bash
# 确认 8 个 entry 标题已修正
for line in 142 1143 1190 1891 2224 2623 3001 3161; do
    sed -n "${line}p" guidelines_brachytherapy.md
done
# 每行应显示论文标题而非章节标题
```

---

### 🟠 Finding #4: Penile-BT 源文件 Journal 字段错误

**文件：** `clinical_kb/sources/02_prostate_gu/raw/nature-bt-penile-organ-preservation-2015.md`
**行号：** 5 (YAML frontmatter)
**等级：** High
**发现者：** Angle A

**问题描述：**
```yaml
title: "The role of brachytherapy in organ preservation for penile cancer: A meta-analysis and review of the literature"
year: 2025
journal: "Nature"             # ← 错误
doi: "10.1016/j.brachy.2015.03.008"  # ← 这是 Brachytherapy (Elsevier) 期刊的 DOI
pmid: "25944394"             # ← 25944394 对应 Brachytherapy 2015
```

**根本原因：** 文件名以 `nature-bt-` 开头，"nature" 是个误导性的标签（可能由前一轮 crawl 误标）。源文件的 frontmatter 直接把"nature"作为 journal 字段填入。

**验证：**
- DOI `10.1016/j.brachy.*` 是 Elsevier 的 Brachytherapy 期刊
- PMID 25944394 → PubMed 显示是 "Brachytherapy. 2015"
- 实际论文确实是 Brachytherapy 期刊 2015 年发表

**失败场景：**
- 自动生成参考文献时，journal="Nature" 与 DOI 不一致
- DOI 解析器会报错或显示矛盾
- 引用验证工具（如 Crossref）会标记此条为不匹配

**修复方案：**

```bash
# 在 nature-bt-penile-organ-preservation-2015.md 第 5 行：
# journal: "Nature"
# 改为：
# journal: "Brachytherapy"
```

**附加修复：** 文件名也应该改：

```bash
# 重命名文件
cd /home/lht/snap/brachyplan/BrachyBot/clinical_kb/sources/02_prostate_gu/raw
mv nature-bt-penile-organ-preservation-2015.md brachytherapy-penile-organ-preservation-2015.md
# 然后 KB 中所有引用也要更新
# stable_id: kb:pros:penile:brachytherapy-penile-organ-preservation-2015
```

**验证方法：**
```bash
# 1. PubMed 验证
curl -s "https://pubmed.ncbi.nlm.nih.gov/25944394/" | grep -E "Brachytherapy|journal"
# 2. DOI 解析
curl -s "https://api.crossref.org/works/10.1016/j.brachy.2015.03.008" | python3 -c "import json,sys; print(json.load(sys.stdin)['message']['container-title'])"
# 期望: ['Brachytherapy']
```

---

### 🟠 Finding #5: 文件计数 "110" 不一致（实际 109 + 1 孤立 .txt）

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 6, 14, 5335, 5683
**等级：** High
**发现者：** Angle C, E, sweep pass

**问题描述：**
- Header（line 6）说 "Source files: 110"
- Verification Provenance（line 14）说 "110 source files"
- Master Source Index（line 5335）说 "all 110 files"
- Limitations（line 5683）说 "snapshot of the 110 source files"

实际 `find sources -name '*.md' -path '*/raw/*' | wc -l` = 109。
第 110 个文件 `i125-pancreatic-guideline-2023.txt` 在 KB 的 Master Index 中**没有对应行**。

**根本原因：** 这是上次 rebuild 时的遗留问题。`.txt` 和 `.md` 是同一篇论文的两种格式（`.md` 是摘要 + frontmatter，`.txt` 是 PDF 全文 OCR）。但 rebuild 时只把 `.md` 视为"真实"条目，把 `.txt` 作为辅助引用，导致计数不匹配。

**失败场景：**
- 自动审计脚本对比 disk 文件数（110）和 KB 声称（110）会通过，但实际只有 109 个有完整条目
- 探索者从 Master Index 找不到 `.txt` 的存在
- 当 `.txt` 文件独立更新时，没有索引行追踪

**修复方案（推荐 Option B）：**

**Option A：删除 `.txt`，统一用 109**
```bash
# 删除冗余的 .txt
rm /home/lht/snap/brachyplan/BrachyBot/clinical_kb/sources/05_gi/raw/i125-pancreatic-guideline-2023.txt
# 然后把 KB line 2263 的 "Full text also at:" 行删除
# 把所有 "110" 改为 "109"
```

**Option B：保留 `.txt`，修正为 110 + Master Index 添加行**

```markdown
# 修改 line 6, 14, 5335, 5683: "110" 不变

# 在 Master Source Index 的 05_gi 表格中添加：
| (txt) | [i125-pancreatic-guideline-2023.txt](sources/05_gi/raw/i125-pancreatic-guideline-2023.txt) | `kb:gi:pancreatic:i125-pancreatic-guideline-2023` (same id, .txt is full-text companion) |
```

**推荐 Option A**（更简洁）。`.txt` 内容是 PDF OCR 提取的全文，已经被 `.md` 摘要在 KB 中反映了；如需全文可以直接从 source 库读 `.md`。

**验证方法：**
```bash
# 1. 实际 disk 文件数
find clinical_kb/sources -name "*.md" -path "*/raw/*" | wc -l
# 2. KB 声称的 110/109
grep -c "110 source files\|all 110\|110 files" clinical_kb/guidelines_brachytherapy.md
# 3. 两者应一致
```

---

### 🟠 Finding #6: GI 章节 header "15 files" vs Master Index "14 files"

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 2224 vs 5498
**等级：** High
**发现者：** Sweep pass

**问题描述：**
- Line 2224 GI 章节 header: `Gastrointestinal Brachytherapy (15 files)`
- Line 5498 Master Source Index: `05_gi — Gastrointestinal Brachytherapy (14 files)`
- Topic Tree（line 64-70）sum: 2+4+1+5+1+1 = 14
- Master Index 是正确的（14），章节 header 多算了 1

**根本原因：** 跟 #5 同样的孤立 `.txt` 造成。章节 header 误算了 `.txt`。

**修复方案：**

如果采用 Finding #5 的 Option A（删 `.txt`）：
```bash
# Line 2224: (15 files) → (14 files)
sed -i 's/Gastrointestinal Brachytherapy (15 files)/Gastrointestinal Brachytherapy (14 files)/' guidelines_brachytherapy.md
```

如果采用 Option B（保留 `.txt`）：
```bash
# Master Index 也要加 .txt 行（见 #5）
```

**验证方法：**
```bash
# GI 文件数
find clinical_kb/sources/05_gi/raw -name "*.md" | wc -l
# 应为 14（如果走 Option A）
```

---

### 🟠 Finding #7: Topic Index 4 个 topic 计数错误

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 3987, 4496, 4536, 5134
**等级：** High
**发现者：** Sweep pass

**问题描述：**
```markdown
### `I-125` (14 entries)        # 实际只有 11 个 bullet
### `breast` (13 entries)      # 实际只有 8 个 bullet
### `cervix` (13 entries)       # 实际只有 8 个 bullet
### `prostate` (13 entries)     # 实际只有 8 个 bullet
```

**根本原因：** Rebuild 脚本生成 Topic Index 时用 `len(entries_for_topic)` 但没排除重复或空条目。

**失败场景：**
- RAG 用户按 topic 过滤时，看到 "(14 entries)" 但实际只能得到 11 个，预算会算错
- 在 prompt 中说"按 cervix topic 过滤"会得到 8 个结果而非预期的 13 个

**修复方案（重新生成 Topic Index）：**

```python
# 重新计算 topic → entries 映射
from collections import defaultdict
topic_to_entries = defaultdict(list)
for fname, tags in TOPIC_TAGS.items():
    for ck, sd in STRUCTURE.items():
        for sk, sub in sd.items():
            if fname in sub['files']:
                eid = make_id(ck, sk, fname)
                for tag in tags:
                    topic_to_entries[tag].append(eid)
                break

# 写入 KB，每行 = 实际 entry 数
for topic in sorted(topic_to_entries.keys()):
    entries = topic_to_entries[topic]
    out.append(f"### `{topic}` ({len(entries)} entries)")
    out.append("")
    for eid, fname in entries:
        out.append(f"- [#{eid}]({eid}) — `{fname}`")
    out.append("")
```

**验证方法：**
```bash
# 找到 4 个错误的 topic header，手动数 bullet
python3 -c "
import re
text = open('guidelines_brachytherapy.md').read()
# 找到 '### \`I-125\` (14 entries)' 段
m = re.search(r'### \`I-125\` \(14 entries\)\n+(.*?)(?=\n### |\Z)', text, re.DOTALL)
if m:
    body = m.group(1)
    bullets = len(re.findall(r'^- ', body, re.MULTILINE))
    print(f'I-125: header says 14, actual bullets: {bullets}')
"
```

---

### 🟠 Finding #8: Limitations 17 vs 24 实际 metadata stubs

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 5683
**等级：** High
**发现者：** Sweep pass

**问题描述：**
Limitations 段说"Metadata-only stubs (17 files)"，但实际有 24 个 entry 完全没有 body content（只有 Topics + See also）。7 个 framework 文件 + 多个 metadata-stub 都被漏算了。

**修复方案：**
```python
# 扫描所有 entry，统计没有 Key facts 的
n_stubs = 0
for entry in entries:
    if not entry.get('key_facts'):
        n_stubs += 1
print(f"Actual metadata stubs: {n_stubs}")
# 然后在 Limitations 段写实际数字
```

或者更简单：手动修改 Limitations 段的数字 17 → 24。

**验证方法：**
```bash
grep -B 1 -A 3 "Key facts" guidelines_brachytherapy.md | grep "📄" | wc -l
# 应等于有 body 的 entry 数
```

---

### 🟡 Finding #9: "(1 files)" 复数语法错误

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 46, 53, 54, 78, 90 等约 7-10 处
**等级：** Medium
**发现者：** Angle C, G

**问题描述：**
Sub-section headers 使用 `(1 files)` 而不是 `(1 file)`。

**修复方案：**
```bash
# 全局替换
sed -i 's/(1 files)/(1 file)/g' guidelines_brachytherapy.md
```

**验证方法：**
```bash
grep -E "\(1 files\)" guidelines_brachytherapy.md
# 应为空
```

---

### 🟡 Finding #10: 3 个 entry body 是空壳（PORTEC-2, EMBRACE-II, ICRU-89）

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 300, 346, 560
**等级：** Medium
**发现者：** Angle A, F, sweep pass

**问题描述：**
3 个 entry 只有 Topics 和 See also，没有 Key facts / Dose constraints / Trial endpoints / Key numbers 段。内容完全在 5 个 cross-cutting tables 里。

具体位置：
- Line 300: `kb:gyn:cervix:embrace-ii-protocol` — 标题是 "OAR Dose Constraints (cervix HDR — EMBRACE II)"（不是论文标题）
- Line 346: `kb:gyn:cervix:icru-89-gyn` — 标题是 "ICRU 89 Dose-Reporting Parameters"（不是论文标题）
- Line 560: `kb:gyn:endometrial:portec-2-lancet-2010` — 标题是 "Endometrial Adjuvant — PORTEC-2 (VBT vs EBRT)"（cross-cutting table 标题，不是论文标题）

**根本原因：** Rebuild 脚本从 cross-cutting tables 中抓数据，但跨章节的源文件实际内容没被复制到 entry body。同时标题也被替换成了 cross-cutting table 的标题。

**失败场景：**
- RAG 系统只检索 entry（不查 cross-cutting tables）时，PORTEC-2 / EMBRACE-II / ICRU-89 的具体数据会缺失
- 用户点开 entry 看到空 body，会以为这些论文没有内容

**修复方案：**

从源文件 frontmatter + body 提取真实内容：

```python
# 修复 EMBRACE-II entry
real_title = "Cervical Cancer Brachytherapy Dose Escalation Protocol: Analysis of Early Data Treatments According to EMBRACE II Protocol"
real_key_facts = [
    "34 patients with locally advanced cervical cancer analyzed",
    "EBRT followed by 3 HDR BT sessions (7 Gy, later 8 Gy per fraction)",
    "Mean D90 for HR-CTV increased significantly with transition from 7 Gy to 8 Gy per fraction",
    "7/34 treatment plans achieved total dose ≥ 85 Gy EQD2 for HR-CTV",
    "13/34 achieved 80-85 Gy",
    "All 34 plans complied with EMBRACE II OAR constraints: D2cc < 90 Gy bladder, < 75 Gy rectum, < 70 Gy sigmoid",
]
# ... 替换 entry 内容
```

或者更简单：在每个空壳 entry 的开头加一行说明，提示用户去 Part III cross-cutting tables 看具体数据：

```markdown
> **Note:** For detailed dose constraints / endpoints / numbers, see [Part III § OAR Dose Constraints (cervix HDR — EMBRACE II)](#part-iii).

#### Cervical Cancer Brachytherapy Dose Escalation Protocol (2018)
...
```

**验证方法：**
```bash
# 找没有 Key facts 段落的 entry
python3 -c "
import re
text = open('guidelines_brachytherapy.md').read()
# 找每个 entry (从 <a id 到下一个 --- 或 <a id)
entries = re.split(r'<a id=\"', text)
no_facts = []
for e in entries[1:]:
    m = re.match(r'([^>]+)\">', e)
    if not m: continue
    eid = m.group(1)
    # 找 #### 标题
    title_m = re.search(r'####\s+(.+)', e)
    title = title_m.group(1) if title_m else 'unknown'
    # 找 Key facts 段
    if '**Key facts:**' not in e:
        no_facts.append((eid, title))
print(f'Entries without Key facts: {len(no_facts)}')
for eid, title in no_facts:
    print(f'  {eid}: {title[:60]}')
"
```

---

### 🟡 Finding #11: CSCO 和 CSTRO entry 内容完全相同（duplicate）

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 3419, 3439
**等级：** Medium
**发现者：** Sweep pass

**问题描述：**
两个 Chinese society 学会的 entry 都有完全相同的 Key facts 文本：
```markdown
"Chinese consensus guidelines cover I-125 seed implantation techniques for pancreatic cancer.
Topics include dose prescription and planning protocols, patient selection criteria, and combination with chemotherapy."
```

**根本原因：** Crawl 阶段没有区分 CSCO 和 CSTRO 的具体内容。

**修复方案：**
1. 读取源文件，看哪个文件有更具体的内容，更新
2. 或在其中一个 entry 加 note 说明 CSCO/CSTRO 关注点差异

```python
# 读取源文件 frontmatter
for f in ['csco-bt-chinese.md', 'cstro-bt-chinese.md']:
    text = SRC / '08_frameworks' / 'raw' / f
    # ... 提取真实信息
```

**验证方法：**
```bash
diff <(grep -A 3 "csco-bt-chinese" guidelines_brachytherapy.md | head -20) \
     <(grep -A 3 "cstro-bt-chinese" guidelines_brachytherapy.md | head -20)
# 如果输出空，则两个内容相同（验证 duplicate）
```

---

### 🟡 Finding #12: ICRU Reports Catalogue 归类错误

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 3396 (anchor), 5664-5670 (Master Index)
**等级：** Medium
**发现者：** Sweep pass

**问题描述：**
`icru-reports-catalogue.md` 是个 ICRU 文件目录，但它被归在 `frm:global_access` (Global Access & Transition) 而不是 `frm:society_methodology` (Society Methodology)。

**修复方案：**

修改 rebuild 脚本的 `STRUCTURE`：

```python
"08_frameworks": {
    "society_methodology": {
        "title": "Society Methodology",
        "files": [
            "aapm-about.md",
            "abs-mission.md",
            "astro-methodology.md",
            "gec-estro-about.md",
            "icru-reports-catalogue.md",  # ← 移到这里
            "nccn-methodology.md",
        ],
    },
    "iaea_who": {...},
    "global_access": {
        "title": "Global Access & Transition",
        "files": [
            "iaea-india-bt-transition-2023.md",
            "lancet-bt-global-demand-2025.md",
            # 移除 icru-reports-catalogue.md
        ],
    },
    "chinese": {...},
}
```

然后重新生成整个 KB。

**验证方法：**
```bash
grep -B 1 "icru-reports-catalogue" guidelines_brachytherapy.md
# 应在 frm:society_methodology 段下，而非 frm:global_access
```

---

### 🟡 Finding #13: Topic tag 命名分歧（`VBT-21-Gy-3fx` vs `vaginal-BT-21-Gy-3fx`）

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 536, 571
**等级：** Medium
**发现者：** Angle F, sweep

**问题描述：**
- PORTEC-2 entry（line 571）topic tag: `VBT-21-Gy-3fx`
- PORTEC-4a entry（line 536）topic tag: `vaginal-BT-21-Gy-3fx`

两者都是描述"vaginal brachytherapy 21 Gy in 3 fractions of 7 Gy"，但用了不同的 tag 名字。

**修复方案：**
统一为 `vaginal-BT-21-Gy-3fx`：

```python
# 在 rebuild 脚本的 TOPIC_TAGS 字典中：
"portec-2-lancet-2010.md": [
    "endometrial", "PORTEC-2", "vaginal-BT-vs-EBRT",
    "vaginal-BT-21-Gy-3fx",  # ← 原来是 VBT-21-Gy-3fx
    "EBRT-46-Gy", "n=427", "5y-VR-1.8%-vs-1.6%"
],
```

**验证方法：**
```bash
grep -E "VBT-21-Gy|vaginal-BT-21-Gy" guidelines_brachytherapy.md
# 应只有 vaginal-BT-21-Gy-3fx（统一后）
```

---

### 🟢 Finding #14: "Journal: Various" 占位符

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 875, 1097, 2306, 2424, 2709, 2727, 3176, 3197, 3213, 3230, 3250, 3402
**等级：** Low
**发现者：** Angle A

**问题描述：**
多个 entry 使用 "Various" 或 website 名称作为 Journal 字段。对于有 DOI 的 entry，DOI 已经隐含了真实期刊名。

**修复方案：**

```python
# 对每个 entry，从 frontmatter 或 DOI 推算真实 journal
import requests
def get_journal_from_doi(doi):
    r = requests.get(f"https://api.crossref.org/works/{doi}")
    return r.json()['message']['container-title'][0] if r.status_code == 200 else "Unknown"

# 修复示例
# abs-skin-2020.md: DOI 10.1016/j.brachy.2019.09.004 → Brachytherapy
# papillon-contact-xray.md: DOI 10.1088/1361-6560/ae5757 → Physics in Medicine & Biology
```

对于 framework 文件（无 DOI），保留 "Various" 或 website 名（"abs Website"），但用大小写规范化为 "ABS Website"。

**验证方法：**
```bash
grep -c "Journal: Various\|Website" guidelines_brachytherapy.md
# 修复后应减少
```

---

### 🟢 Finding #15: Orphan `.txt` 文件孤立引用

**文件：** `clinical_kb/guidelines_brachytherapy.md`
**行号：** 2263
**等级：** Low
**发现者：** Angle C, E, sweep

**问题描述：**
`i125-pancreatic-guideline-2023.txt` 在 line 2263 被引用为 "Full text also at:"，但**没在 Master Source Index 中**，**没在 Topic Tree 的 gi:pancreatic sub-topic 中**。

**修复方案：**
见 Finding #5（建议删除 `.txt` 或在 Master Index 中添加行）。

---

## 3. 修复优先级矩阵

| 严重度 | 数量 | 修复工时 | 修复方式 |
|--------|------|----------|----------|
| 🔴 Critical | 2 | 5 分钟 | sed 一行替换 |
| 🟠 High | 6 | 30 分钟 | sed + 手动 + 重新生成 Topic Index |
| 🟡 Medium | 6 | 1-2 小时 | 手动修复或 Python 脚本批量 |
| 🟢 Low | 1 | 30 分钟 | 重新计算或补全 |

**总计修复工时：2-3 小时**

---

## 4. 完整修复执行计划

### 4.1 立即修复（10 分钟内）

```bash
# 修复 #1, #2: 2 个 broken anchor
cd /home/lht/snap/brachyplan/BrachyBot/clinical_kb
sed -i 's|gec-estro-cervix-2005-haie-meder)|gec-estro-cervix-2005-haie)|g' guidelines_brachytherapy.md
sed -i 's|embrace-i-pivotal-2021-lancet-oncol)|embrace-i-pivotal-2021-lancet)|g' guidelines_brachytherapy.md

# 修复 #9: "(1 files)" → "(1 file)"
sed -i 's|(1 files)|(1 file)|g' guidelines_brachytherapy.md
```

### 4.2 短期修复（30 分钟内）

```bash
# 修复 #5: 110 → 109（删除 .txt）
rm sources/05_gi/raw/i125-pancreatic-guideline-2023.txt
sed -i 's|110 source files|109 source files|g; s|all 110 files|all 109 files|g; s|the 110 source files|the 109 source files|g' guidelines_brachytherapy.md
# 同时删除 line 2263 的 "Full text also at: ..." 行
# 同时修复 line 2224: (15 files) → (14 files)
sed -i 's|Gastrointestinal Brachytherapy (15 files)|Gastrointestinal Brachytherapy (14 files)|' guidelines_brachytherapy.md
```

### 4.3 中期修复（1-2 小时）

```bash
# 修复 #4: Penile-BT Journal 字段
cd /home/lht/snap/brachyplan/BrachyBot/clinical_kb
sed -i 's|^journal: "Nature"$|journal: "Brachytherapy"|' sources/02_prostate_gu/raw/nature-bt-penile-organ-preservation-2015.md

# 修复 #3: 8 个 entry 标题（手动 Edit 工具逐个修改）

# 修复 #7: 重新生成 Topic Index（运行 rebuild 脚本）

# 修复 #8: 24 vs 17 metadata stubs（实际重新计算）
```

### 4.4 长期改进（可选）

- #10, #11, #12, #13, #14, #15: 取决于用户优先级

---

## 5. 验证方法（修复后必跑）

### 5.1 自动化验证脚本

创建一个 `verify_kb.py` 脚本，每次修改后跑：

```python
#!/usr/bin/env python3
"""Verify KB integrity after any modification."""
import re
import subprocess
from pathlib import Path

ROOT = Path("/home/lht/snap/brachyplan/BrachyBot/clinical_kb")
KB = ROOT / "guidelines_brachytherapy.md"

text = KB.read_text(encoding='utf-8')

# Check 1: 所有 <a id> 唯一
ids = re.findall(r'<a id="([^"]+)">', text)
assert len(ids) == len(set(ids)), f"Duplicate IDs: {[i for i in ids if ids.count(i) > 1]}"

# Check 2: 所有 [text](#id) 引用都存在
defined = set(ids)
refs = set(re.findall(r'\(#(kb:[^)]+)\)', text))
missing = refs - defined
assert not missing, f"Broken refs: {missing}"

# Check 3: 所有源文件都被引用
src_files = set(f.name for cat in (ROOT / "sources").iterdir() 
                if cat.is_dir() and cat.name != "_meta"
                for f in (cat / "raw").iterdir() 
                if f.suffix in (".md", ".txt"))
kb_refs = set(re.findall(r'\[([^\]]+\.(?:md|txt))\]\(sources/[^)]+\)', text))
assert src_files == kb_refs, f"Missing: {src_files - kb_refs}, Extra: {kb_refs - src_files}"

# Check 4: 没有 "(1 files)" 语法错误
assert "(1 files)" not in text, "Grammar error: (1 files) found"

# Check 5: 没有 #N/A 链接
assert "pubmed.ncbi.nlm.nih.gov/N/A" not in text, "Hallucinated N/A link found"

# Check 6: Topic Index 计数准确
topic_header_re = re.compile(r"### `([^`]+)` \((\d+) entries\)\n+(.*?)(?=\n### |\Z)", re.DOTALL)
for topic, count_str, body in topic_header_re.findall(text):
    count = int(count_str)
    actual = len(re.findall(r"^- ", body, re.MULTILINE))
    assert count == actual, f"Topic '{topic}': header says {count}, actual {actual}"

print("✅ All KB integrity checks passed")
```

### 5.2 手动验证检查清单

- [ ] 打开 KB，Ctrl+F "gec-estro-cervix-2005-haie-meder" — 应为 0 个匹配
- [ ] 打开 KB，Ctrl+F "embrace-i-pivotal-2021-lancet-oncol" — 应为 0 个匹配
- [ ] 打开 KB，Ctrl+F "(1 files)" — 应为 0 个匹配
- [ ] 打开 KB，Ctrl+F "Nature" — 应在 cross-ref 链接等位置出现，但不应作为 Journal 字段
- [ ] 打开 KB，Ctrl+F "110" — 应只在 disk count context 出现（已修复后应为 109）
- [ ] 打开 KB，从 Part I IGABT 列表点击每个 cornerstone 链接 — 应跳到对应 entry
- [ ] 打开 KB，浏览每个 category 第一个 entry — 标题应是论文标题而非章节标题
- [ ] 打开 KB，翻到 Master Source Index — 109 行对应 109 个 .md 文件

---

## 6. 设计层面的反思

### 6.1 改造有效吗？

**是。** 树形结构 + stable ID + topic tags + cross-references 显著提升了 LLM 索引能力：
- 按 topic 路径定位：`kb:cat:sub:file-slug`
- 按 topic 反向查询：Part III § Topic Index
- 按主题探索：See also 网络

### 6.2 改造引入的新问题

1. **锚点不一致**：手工构建 111 个 ID 时容易产生细微差异（`meder` vs `haie`），未来应自动化生成
2. **内容重复**：cross-cutting tables 和 entry body 之间的内容分布需要规则化（要么 entry 完整，要么 table 完整）
3. **空壳 entry**：3 个 entry 完全依赖 cross-cutting table，破坏 RAG 检索完整性
4. **计数漂移**：`.md` 和 `.txt` 双胞胎引入 +1 漂移，应统一一种格式

### 6.3 长期建议

1. **建立 CI 验证**：每次 KB 修改后自动跑 `verify_kb.py`
2. **建立 source file 模板**：明确 `title` / `journal` / `year` / `doi` / `pmid` 必填，缺一则警告
3. **建立稳定 ID 自动生成函数**：禁止手工编辑 ID
4. **考虑迁移到结构化格式**：未来可将 KB 从 markdown 迁移到 JSON / YAML，前端用 RAG-friendly schema 渲染

---

## 7. 附录

### 7.1 审查用工具

- 8 个 sub-agents 并行扫描（Angle A, B, C, D, E, F, G, H）
- 1 个 sweep pass
- 主会话直接验证关键发现

### 7.2 审查工时

- 启动 8 个 sub-agents：~5 分钟
- Sub-agent 运行：~30-60 秒每个（总并行 ~5 分钟）
- 主会话验证：~5 分钟
- 撰写本报告：~30 分钟
- **总工时：~45 分钟**

### 7.3 修复工时估算

| 阶段 | 工时 |
|------|------|
| 立即修复（#1, #2, #9） | 5-10 分钟 |
| 短期修复（#3-#8） | 1-2 小时 |
| 中期改进（#10-#15） | 2-3 小时 |
| 建立 CI 验证 | 1-2 小时 |
| **总计** | **4-8 小时** |

### 7.4 相关文件路径

- `clinical_kb/guidelines_brachytherapy.md` — 主 KB
- `clinical_kb/sources/<category>/raw/` — 110 个源文件
- `clinical_kb/_meta/MANIFEST.csv` — 源文件清单
- `clinical_kb/_meta/FETCH_LOG.md` — 抓取日志

---

**报告作者：** BrachyBot Clinical KB Code Review
**报告版本：** 1.0
**下次审查建议：** 修复完成后，重新跑 8-angle review 验证改进
