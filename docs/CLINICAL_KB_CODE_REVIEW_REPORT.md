# BrachyBot Clinical KB — Code Review Report

**Report date:** 2026-06-18
**Review target:** `clinical_kb/guidelines_brachytherapy.md` (5,690 lines, 265 KB, 109 source file entries)
**Review mode:** Extra-high recall (prefer false positives over false negatives)
**Review method:** 9 independent finder angles + 1 sweep pass, 1-vote verification
**Review tooling:** 8 parallel sub-agents + direct verification in the main session

---

## 0. Summary (TL;DR)

This review covers the complete diff that restructured the KB from a **flat structure** (2,663 lines) into a **tree structure** (5,690 lines). The main goal of the restructuring: enable the LLM to index related knowledge using stable IDs, topic tags, and cross-references.

**Conclusion: The restructuring is largely successful, but 15 serious issues requiring fixes were found.**

| Severity | Count | Summary |
|------|------|------|
| 🔴 Critical | 2 | 2 broken Part I entry links (clicking jumps to the top) |
| 🟠 High | 6 | Misplaced section headings, wrong Journal field, file count 110 vs 109 inconsistency, Topic Index count bug |
| 🟡 Medium | 6 | Plural grammar error, 3 empty-shell entries, identical CSCO/CSTRO content, ICRU misclassification, Topic tag naming divergence |
| 🟢 Low | 1 | "Journal: Various" placeholder |

**Recommendation:** Fix Critical + High (8 issues) immediately; can be batch-completed in 30-60 minutes via Python scripts.

---

## 1. Restructuring Overview

### 1.1 Restructuring Goals

The user requested converting the originally "flat and straightforward" KB into a "tree structure" so the LLM can:
- Precisely locate entries by path (`kb:cat:sub:file-slug`)
- Filter and cluster by topic tag
- Explore related items via cross-references
- Reverse-lookup via Topic Index

### 1.2 Before/After Comparison

| Metric | Before | After | Change |
|------|--------|--------|------|
| Total lines | 2,663 | 5,690 | +114% |
| File size | 145 KB | 265 KB | +83% |
| Source files | 110 | 110 | 0 |
| Stable IDs | 0 | 111 | +111 |
| Topic tags | 0 | 109 | +109 |
| See also sections | 0 | 108 | +270 links |
| Topic Index | 0 | 415 topics | New |
| Cross-cutting tables | 5 | 5 | Retained |

### 1.3 Specific Changes Made by the Restructuring

1. **Structural reorganization**: 8 sections → 8 sections × 5-7 sub-topics
2. **New ID system**: an `<a id="kb:cat:sub:file"></a>` anchor for every entry
3. **New Topic tags**: `**Topics:** \`tag1\`, \`tag2\`, ...` for every entry
4. **New See also sections**: mutual references among entries of the same trial/disease/foundation
5. **New Topic Index**: reverse index from 415 topics → 109 entry IDs
6. **New Part I Foundations**: entry points to 8 cornerstone papers
7. **Removed redundancy**: 35 "File contains X only" meta-descriptions
8. **Removed 33 fake N/A links**
9. **Fixed 1 broken link** (icru-89: 07_physics → 01_gynecologic)

---

## 2. Detailed Issue List (Sorted by Severity)

### 🔴 Finding #1: Part I Foundations cornerstone link #1 broken

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 116
**Severity:** Critical
**Found by:** Angle C, D, E (cross-validated)

**Description:**
```markdown
- [GEC-ESTRO 2005 Haie-Meder (foundation paper)](#kb:gyn:cervix:gec-estro-cervix-2005-haie-meder)
```

But the actually defined anchor is at line 315:
```markdown
<a id="kb:gyn:cervix:gec-estro-cervix-2005-haie"></a>
```

**Root cause:** The `make_id()` function truncated filename slugs longer than 60 characters, but the Part I reference used the **full** filename `gec-estro-cervix-2005-haie-meder`. This is an artificial inconsistency between the anchor definition and the reference.

**Failure scenarios:**
- A user clicks "GEC-ESTRO 2005 Haie-Meder (foundation paper)" from Part I → jumps to the top of the document
- The RAG system generates a citation based on Part I → dead link
- The table-of-contents index in PDF export breaks

**Fix:**

```python
# At line 116 of the KB file, change:
# [GEC-ESTRO 2005 Haie-Meder (foundation paper)](#kb:gyn:cervix:gec-estro-cervix-2005-haie-meder)
# to:
# [GEC-ESTRO 2005 Haie-Meder (foundation paper)](#kb:gyn:cervix:gec-estro-cervix-2005-haie)

# Apply the same fix to line 118:
# [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet-oncol)
# to:
# [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet)
```

Or, a more thorough fix: make the `make_id()` function **not truncate**, and instead keep the full slug:

```python
def make_id(cat_key, sub_key, fname):
    """Generate stable ID from category, subtopic, filename. No truncation."""
    cat_short = CAT_DISPLAY[cat_key][2]
    base = fname.replace('.md', '').replace('.txt', '')
    return f"kb:{cat_short}:{sub_key}:{base}"
```

**Verification method:**
```bash
# 1. List all anchor definitions
grep -oE '<a id="(kb:gyn:cervix:gec-estro-cervix-2005-haie[^"]*)"' guidelines_brachytherapy.md | sort -u
# 2. List all related references
grep -oE '\[GEC-ESTRO 2005[^]]*\]\(#kb:gyn:cervix:gec-estro-cervix-2005-haie[^)]*\)' guidelines_brachytherapy.md
# 3. The two must match 1:1
```

---

### 🔴 Finding #2: Part I Foundations cornerstone link #2 broken

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 118
**Severity:** Critical
**Found by:** Angle C, D, E (cross-validated)

**Description:**
```markdown
- [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet-oncol)
```

The actual anchor is at line 257:
```markdown
<a id="kb:gyn:cervix:embrace-i-pivotal-2021-lancet"></a>
```

**Root cause:** Same as #1; the slug was truncated.

**Failure scenarios:** Same as #1.

**Fix:**

```python
# Edit directly at line 118 of the KB file
# [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet-oncol)
# →
# [EMBRACE-I (Lancet Oncology 2021)](#kb:gyn:cervix:embrace-i-pivotal-2021-lancet)
```

Or adopt the no-truncation approach from #1.

**Verification method:**
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

### 🟠 Finding #3: 8 entry titles overwritten by section titles

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 142, 1143, 1190, 1891, 2224, 2623, 3001, 3161
**Severity:** High
**Found by:** Angle A, sweep pass

**Description:**
The `#### Title` lines of 8 entries are not paper titles but the titles of their parent section.

```markdown
# Line 142: first entry (abs-cervix-consensus-2012-part1)
#### 01_gynecologic — Gynecologic Brachytherapy (17 files)   ← BUG: should be the paper title

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

**Root cause:** In the rebuild script, the section title was probably mistakenly applied to the "first entry" of each section. These 8 entries each correspond to the first file of a category, and the section title was erroneously copied over.

**Failure scenarios:**
- When a user navigates by `#### Title`, they see the category title instead of the paper title
- It hurts table-of-contents readability
- But the stable IDs and content are correct, so automatic RAG retrieval is unaffected

**Fix:**

The real frontmatter title of these 8 entries already exists in the source files and can be extracted directly from the source frontmatter:

```python
# Fix script
import yaml
import re
from pathlib import Path

ROOT = Path("<workspace>/BrachyBot/clinical_kb")
KB = ROOT / "guidelines_brachytherapy.md"
SRC = ROOT / "sources"

KB_TEXT = KB.read_text(encoding='utf-8')

# For each corrupted entry, find its stable ID, read the correct title from the source file, and replace
ENTRIES_TO_FIX = [
    # (stable_id, expected_line_pattern, source_file)
    ("kb:gyn:cervix:abs-cervix-consensus-2012-part1", "01_gynecologic — Gynecologic Brachytherapy", "abs-cervix-consensus-2012-part1.md"),
    ("kb:pros:guidelines:aapm-tg-137-nath-2009", "02_prostate_gu — Prostate & Genitourinary Brachytherapy", "aapm-tg-137-nath-2009.md"),
    # ... the other 6
]

for entry_id, wrong_title, source_file in ENTRIES_TO_FIX:
    # Read the real title from the source file frontmatter
    src_path = SRC / entry_id.split(":")[1] / "raw" / source_file
    # Infer the category from entry_id
    cat_map = {"gyn": "01_gynecologic", "pros": "02_prostate_gu", "brst": "03_breast",
               "hns": "04_head_neck_skin", "gi": "05_gi", "oth": "06_other_sites",
               "phys": "07_physics", "frm": "08_frameworks"}
    cat = cat_map[entry_id.split(":")[1]]
    src_path = SRC / cat / "raw" / source_file
    
    src_text = src_path.read_text(encoding='utf-8', errors='replace')
    m = re.search(r'^title:\s*"([^"]+)"', src_text, re.MULTILINE)
    real_title = m.group(1) if m else "Unknown"
    
    # Find the entry in the KB and replace the #### line
    # ... complex string handling ...
```

Simpler: manually fix these 8 lines directly (using the Edit tool):

| Line | Replacement |
|------|------|
| 142 | `#### 01_gynecologic — Gynecologic Brachytherapy (17 files)` → `#### American Brachytherapy Society consensus guidelines for locally advanced carcinoma of the cervix. Part I: general principles (2012)` |
| 1141 | `#### 02_prostate_gu — Prostate & Genitourinary Brachytherapy (14 files)` → `#### Erratum: AAPM recommendations on dose prescription and reporting methods for permanent interstitial brachytherapy for prostate cancer: Report of Task Group 137 (2009)` |
| 1190 | `#### 03_breast — Breast Brachytherapy (13 files)` → `#### Recurrence rates for patients with early-stage breast cancer treated with IOERT at a community hospital per the ASTRO consensus statement for APBI (2013)` |
| 1891 | `#### 04_head_neck_skin — Head & Neck / Skin Brachytherapy (12 files)` → `#### The American College of Radiology and the American Brachytherapy Society practice parameter for the performance of low-dose-rate brachytherapy (2018)` |
| 2224 | `#### 05_gi — Gastrointestinal Brachytherapy (15 files)` → `#### Preliminary application of 3D-printed coplanar template for iodine-125 seed implantation therapy in patients with advanced pancreatic cancer (2018)` |
| 2623 | `#### 06_other_sites — Other Sites Brachytherapy (13 files)` → `#### AAPM TG-129: Uveal Melanoma Plaque Dosimetry (2020)` |
| 3001 | `#### 07_physics — Physics & Dosimetry (13 files)` → `#### GEC-ESTRO/ACROP recommendations for quality assurance of ultrasound imaging in brachytherapy (2012)` |
| 3161 | `#### 08_frameworks — Frameworks & Society Initiatives (13 files)` → `#### AAPM Guidelines and Code of Ethics (2024)` |

**Verification method:**
```bash
# Confirm that the 8 entry titles have been fixed
for line in 142 1143 1190 1891 2224 2623 3001 3161; do
    sed -n "${line}p" guidelines_brachytherapy.md
done
# Each line should show a paper title rather than a section title
```

---

### 🟠 Finding #4: Wrong Journal field in Penile-BT source file

**File:** `clinical_kb/sources/02_prostate_gu/raw/nature-bt-penile-organ-preservation-2015.md`
**Line:** 5 (YAML frontmatter)
**Severity:** High
**Found by:** Angle A

**Description:**
```yaml
title: "The role of brachytherapy in organ preservation for penile cancer: A meta-analysis and review of the literature"
year: 2025
journal: "Nature"             # ← wrong
doi: "10.1016/j.brachy.2015.03.008"  # ← this is the DOI of the Brachytherapy (Elsevier) journal
pmid: "25944394"             # ← 25944394 corresponds to Brachytherapy 2015
```

**Root cause:** The filename starts with `nature-bt-`; "nature" is a misleading label (possibly mislabeled by an earlier crawl round). The source frontmatter directly filled "nature" into the journal field.

**Verification:**
- The DOI `10.1016/j.brachy.*` belongs to Elsevier's Brachytherapy journal
- PMID 25944394 → PubMed shows "Brachytherapy. 2015"
- The actual paper was indeed published in Brachytherapy in 2015

**Failure scenarios:**
- When auto-generating references, journal="Nature" is inconsistent with the DOI
- DOI resolvers will error out or show a contradiction
- Citation validation tools (such as Crossref) will flag this entry as a mismatch

**Fix:**

```bash
# At line 5 of nature-bt-penile-organ-preservation-2015.md:
# journal: "Nature"
# change to:
# journal: "Brachytherapy"
```

**Additional fix:** The filename should also be changed:

```bash
# Rename the file
cd <workspace>/BrachyBot/clinical_kb/sources/02_prostate_gu/raw
mv nature-bt-penile-organ-preservation-2015.md brachytherapy-penile-organ-preservation-2015.md
# Then all references in the KB must be updated as well
# stable_id: kb:pros:penile:brachytherapy-penile-organ-preservation-2015
```

**Verification method:**
```bash
# 1. PubMed verification
curl -s "https://pubmed.ncbi.nlm.nih.gov/25944394/" | grep -E "Brachytherapy|journal"
# 2. DOI resolution
curl -s "https://api.crossref.org/works/10.1016/j.brachy.2015.03.008" | python3 -c "import json,sys; print(json.load(sys.stdin)['message']['container-title'])"
# Expected: ['Brachytherapy']
```

---

### 🟠 Finding #5: File count "110" inconsistency (actually 109 + 1 orphaned .txt)

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 6, 14, 5335, 5683
**Severity:** High
**Found by:** Angle C, E, sweep pass

**Description:**
- Header (line 6) says "Source files: 110"
- Verification Provenance (line 14) says "110 source files"
- Master Source Index (line 5335) says "all 110 files"
- Limitations (line 5683) says "snapshot of the 110 source files"

Actually `find sources -name '*.md' -path '*/raw/*' | wc -l` = 109.
The 110th file, `i125-pancreatic-guideline-2023.txt`, has **no corresponding row** in the KB's Master Index.

**Root cause:** This is a leftover issue from the last rebuild. `.txt` and `.md` are two formats of the same paper (`.md` is the abstract + frontmatter, `.txt` is the full-text PDF OCR). But during the rebuild, only `.md` was treated as a "real" entry and `.txt` as an auxiliary reference, causing the count mismatch.

**Failure scenarios:**
- An automated audit script comparing the disk file count (110) against the KB claim (110) will pass, but only 109 actually have complete entries
- Explorers cannot find the existence of the `.txt` from the Master Index
- When the `.txt` file is updated independently, no index row tracks it

**Fix (Option B recommended):**

**Option A: Delete the `.txt`, standardize on 109**
```bash
# Delete the redundant .txt
rm <workspace>/BrachyBot/clinical_kb/sources/05_gi/raw/i125-pancreatic-guideline-2023.txt
# Then delete the "Full text also at:" line at KB line 2263
# Change all "110" to "109"
```

**Option B: Keep the `.txt`, correct to 110 + add a row to the Master Index**

```markdown
# Modify line 6, 14, 5335, 5683: "110" stays unchanged

# Add to the 05_gi table in the Master Source Index:
| (txt) | [i125-pancreatic-guideline-2023.txt](sources/05_gi/raw/i125-pancreatic-guideline-2023.txt) | `kb:gi:pancreatic:i125-pancreatic-guideline-2023` (same id, .txt is full-text companion) |
```

**Option A recommended** (more concise). The `.txt` content is the full text extracted by PDF OCR and is already reflected in the KB by the `.md` abstract; if the full text is needed, the `.md` can be read directly from the source library.

**Verification method:**
```bash
# 1. Actual disk file count
find clinical_kb/sources -name "*.md" -path "*/raw/*" | wc -l
# 2. The 110/109 claimed by the KB
grep -c "110 source files\|all 110\|110 files" clinical_kb/guidelines_brachytherapy.md
# 3. The two should be consistent
```

---

### 🟠 Finding #6: GI section header "15 files" vs Master Index "14 files"

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 2224 vs 5498
**Severity:** High
**Found by:** Sweep pass

**Description:**
- Line 2224 GI section header: `Gastrointestinal Brachytherapy (15 files)`
- Line 5498 Master Source Index: `05_gi — Gastrointestinal Brachytherapy (14 files)`
- Topic Tree (line 64-70) sum: 2+4+1+5+1+1 = 14
- The Master Index is correct (14); the section header overcounts by 1

**Root cause:** Caused by the same orphaned `.txt` as #5. The section header mistakenly counted the `.txt`.

**Fix:**

If adopting Option A from Finding #5 (delete the `.txt`):
```bash
# Line 2224: (15 files) → (14 files)
sed -i 's/Gastrointestinal Brachytherapy (15 files)/Gastrointestinal Brachytherapy (14 files)/' guidelines_brachytherapy.md
```

If adopting Option B (keep the `.txt`):
```bash
# The Master Index must also add the .txt row (see #5)
```

**Verification method:**
```bash
# GI file count
find clinical_kb/sources/05_gi/raw -name "*.md" | wc -l
# Should be 14 (if going with Option A)
```

---

### 🟠 Finding #7: 4 topic count errors in Topic Index

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 3987, 4496, 4536, 5134
**Severity:** High
**Found by:** Sweep pass

**Description:**
```markdown
### `I-125` (14 entries)        # actually only 11 bullets
### `breast` (13 entries)      # actually only 8 bullets
### `cervix` (13 entries)       # actually only 8 bullets
### `prostate` (13 entries)     # actually only 8 bullets
```

**Root cause:** The rebuild script used `len(entries_for_topic)` when generating the Topic Index but did not exclude duplicate or empty entries.

**Failure scenarios:**
- When a RAG user filters by topic, they see "(14 entries)" but can only get 11, so budgets will be miscalculated
- Saying "filter by cervix topic" in a prompt returns 8 results instead of the expected 13

**Fix (regenerate the Topic Index):**

```python
# Recompute the topic → entries mapping
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

# Write to the KB; each line = actual entry count
for topic in sorted(topic_to_entries.keys()):
    entries = topic_to_entries[topic]
    out.append(f"### `{topic}` ({len(entries)} entries)")
    out.append("")
    for eid, fname in entries:
        out.append(f"- [#{eid}]({eid}) — `{fname}`")
    out.append("")
```

**Verification method:**
```bash
# Find the 4 wrong topic headers and count bullets manually
python3 -c "
import re
text = open('guidelines_brachytherapy.md').read()
# Find the '### \`I-125\` (14 entries)' section
m = re.search(r'### \`I-125\` \(14 entries\)\n+(.*?)(?=\n### |\Z)', text, re.DOTALL)
if m:
    body = m.group(1)
    bullets = len(re.findall(r'^- ', body, re.MULTILINE))
    print(f'I-125: header says 14, actual bullets: {bullets}')
"
```

---

### 🟠 Finding #8: Limitations 17 vs 24 actual metadata stubs

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 5683
**Severity:** High
**Found by:** Sweep pass

**Description:**
The Limitations section says "Metadata-only stubs (17 files)", but there are actually 24 entries with no body content at all (only Topics + See also). 7 framework files + multiple metadata stubs were all missed.

**Fix:**
```python
# Scan all entries and count those without Key facts
n_stubs = 0
for entry in entries:
    if not entry.get('key_facts'):
        n_stubs += 1
print(f"Actual metadata stubs: {n_stubs}")
# Then write the actual number in the Limitations section
```

Or simpler: manually change the number in the Limitations section from 17 → 24.

**Verification method:**
```bash
grep -B 1 -A 3 "Key facts" guidelines_brachytherapy.md | grep "📄" | wc -l
# Should equal the number of entries that have a body
```

---

### 🟡 Finding #9: "(1 files)" plural grammar error

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 46, 53, 54, 78, 90 and about 7-10 places
**Severity:** Medium
**Found by:** Angle C, G

**Description:**
Sub-section headers use `(1 files)` instead of `(1 file)`.

**Fix:**
```bash
# Global replacement
sed -i 's/(1 files)/(1 file)/g' guidelines_brachytherapy.md
```

**Verification method:**
```bash
grep -E "\(1 files\)" guidelines_brachytherapy.md
# Should be empty
```

---

### 🟡 Finding #10: 3 entry bodies are empty shells (PORTEC-2, EMBRACE-II, ICRU-89)

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 300, 346, 560
**Severity:** Medium
**Found by:** Angle A, F, sweep pass

**Description:**
3 entries have only Topics and See also, with no Key facts / Dose constraints / Trial endpoints / Key numbers sections. Their content is entirely in the 5 cross-cutting tables.

Specific locations:
- Line 300: `kb:gyn:cervix:embrace-ii-protocol` — the title is "OAR Dose Constraints (cervix HDR — EMBRACE II)" (not the paper title)
- Line 346: `kb:gyn:cervix:icru-89-gyn` — the title is "ICRU 89 Dose-Reporting Parameters" (not the paper title)
- Line 560: `kb:gyn:endometrial:portec-2-lancet-2010` — the title is "Endometrial Adjuvant — PORTEC-2 (VBT vs EBRT)" (a cross-cutting table title, not the paper title)

**Root cause:** The rebuild script pulled data from the cross-cutting tables, but the actual content of the cross-section source files was not copied into the entry body. The title was also replaced with the cross-cutting table title.

**Failure scenarios:**
- When the RAG system retrieves only entries (without consulting the cross-cutting tables), the specific data for PORTEC-2 / EMBRACE-II / ICRU-89 will be missing
- A user opening the entry sees an empty body and assumes these papers have no content

**Fix:**

Extract the real content from the source file frontmatter + body:

```python
# Fix the EMBRACE-II entry
real_title = "Cervical Cancer Brachytherapy Dose Escalation Protocol: Analysis of Early Data Treatments According to EMBRACE II Protocol"
real_key_facts = [
    "34 patients with locally advanced cervical cancer analyzed",
    "EBRT followed by 3 HDR BT sessions (7 Gy, later 8 Gy per fraction)",
    "Mean D90 for HR-CTV increased significantly with transition from 7 Gy to 8 Gy per fraction",
    "7/34 treatment plans achieved total dose ≥ 85 Gy EQD2 for HR-CTV",
    "13/34 achieved 80-85 Gy",
    "All 34 plans complied with EMBRACE II OAR constraints: D2cc < 90 Gy bladder, < 75 Gy rectum, < 70 Gy sigmoid",
]
# ... replace entry content
```

Or simpler: add an explanatory line at the start of each empty-shell entry, pointing users to the Part III cross-cutting tables for the specific data:

```markdown
> **Note:** For detailed dose constraints / endpoints / numbers, see [Part III § OAR Dose Constraints (cervix HDR — EMBRACE II)](#part-iii).

#### Cervical Cancer Brachytherapy Dose Escalation Protocol (2018)
...
```

**Verification method:**
```bash
# Find entries without a Key facts section
python3 -c "
import re
text = open('guidelines_brachytherapy.md').read()
# Find each entry (from <a id to the next --- or <a id)
entries = re.split(r'<a id=\"', text)
no_facts = []
for e in entries[1:]:
    m = re.match(r'([^>]+)\">', e)
    if not m: continue
    eid = m.group(1)
    # Find the #### title
    title_m = re.search(r'####\s+(.+)', e)
    title = title_m.group(1) if title_m else 'unknown'
    # Find the Key facts section
    if '**Key facts:**' not in e:
        no_facts.append((eid, title))
print(f'Entries without Key facts: {len(no_facts)}')
for eid, title in no_facts:
    print(f'  {eid}: {title[:60]}')
"
```

---

### 🟡 Finding #11: CSCO and CSTRO entries have identical content (duplicate)

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 3419, 3439
**Severity:** Medium
**Found by:** Sweep pass

**Description:**
Both Chinese society entries have exactly the same Key facts text:
```markdown
"Chinese consensus guidelines cover I-125 seed implantation techniques for pancreatic cancer.
Topics include dose prescription and planning protocols, patient selection criteria, and combination with chemotherapy."
```

**Root cause:** The crawl stage did not distinguish the specific content of CSCO and CSTRO.

**Fix:**
1. Read the source files, see which file has more specific content, and update
2. Or add a note to one of the entries explaining the difference in focus between CSCO/CSTRO

```python
# Read the source file frontmatter
for f in ['csco-bt-chinese.md', 'cstro-bt-chinese.md']:
    text = SRC / '08_frameworks' / 'raw' / f
    # ... extract the real information
```

**Verification method:**
```bash
diff <(grep -A 3 "csco-bt-chinese" guidelines_brachytherapy.md | head -20) \
     <(grep -A 3 "cstro-bt-chinese" guidelines_brachytherapy.md | head -20)
# If the output is empty, the two have identical content (confirms duplicate)
```

---

### 🟡 Finding #12: ICRU Reports Catalogue misclassification

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 3396 (anchor), 5664-5670 (Master Index)
**Severity:** Medium
**Found by:** Sweep pass

**Description:**
`icru-reports-catalogue.md` is an ICRU document catalogue, but it is classified under `frm:global_access` (Global Access & Transition) rather than `frm:society_methodology` (Society Methodology).

**Fix:**

Modify the `STRUCTURE` of the rebuild script:

```python
"08_frameworks": {
    "society_methodology": {
        "title": "Society Methodology",
        "files": [
            "aapm-about.md",
            "abs-mission.md",
            "astro-methodology.md",
            "gec-estro-about.md",
            "icru-reports-catalogue.md",  # ← move here
            "nccn-methodology.md",
        ],
    },
    "iaea_who": {...},
    "global_access": {
        "title": "Global Access & Transition",
        "files": [
            "iaea-india-bt-transition-2023.md",
            "lancet-bt-global-demand-2025.md",
            # Remove icru-reports-catalogue.md
        ],
    },
    "chinese": {...},
}
```

Then regenerate the entire KB.

**Verification method:**
```bash
grep -B 1 "icru-reports-catalogue" guidelines_brachytherapy.md
# Should be under the frm:society_methodology section, not frm:global_access
```

---

### 🟡 Finding #13: Topic tag naming divergence (`VBT-21-Gy-3fx` vs `vaginal-BT-21-Gy-3fx`)

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 536, 571
**Severity:** Medium
**Found by:** Angle F, sweep

**Description:**
- PORTEC-2 entry (line 571) topic tag: `VBT-21-Gy-3fx`
- PORTEC-4a entry (line 536) topic tag: `vaginal-BT-21-Gy-3fx`

Both describe "vaginal brachytherapy 21 Gy in 3 fractions of 7 Gy" but use different tag names.

**Fix:**
Standardize on `vaginal-BT-21-Gy-3fx`:

```python
# In the TOPIC_TAGS dict of the rebuild script:
"portec-2-lancet-2010.md": [
    "endometrial", "PORTEC-2", "vaginal-BT-vs-EBRT",
    "vaginal-BT-21-Gy-3fx",  # ← was originally VBT-21-Gy-3fx
    "EBRT-46-Gy", "n=427", "5y-VR-1.8%-vs-1.6%"
],
```

**Verification method:**
```bash
grep -E "VBT-21-Gy|vaginal-BT-21-Gy" guidelines_brachytherapy.md
# Should contain only vaginal-BT-21-Gy-3fx (after standardization)
```

---

### 🟢 Finding #14: "Journal: Various" placeholder

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 875, 1097, 2306, 2424, 2709, 2727, 3176, 3197, 3213, 3230, 3250, 3402
**Severity:** Low
**Found by:** Angle A

**Description:**
Multiple entries use "Various" or a website name as the Journal field. For entries that have a DOI, the DOI already implies the real journal name.

**Fix:**

```python
# For each entry, derive the real journal from frontmatter or DOI
import requests
def get_journal_from_doi(doi):
    r = requests.get(f"https://api.crossref.org/works/{doi}")
    return r.json()['message']['container-title'][0] if r.status_code == 200 else "Unknown"

# Fix examples
# abs-skin-2020.md: DOI 10.1016/j.brachy.2019.09.004 → Brachytherapy
# papillon-contact-xray.md: DOI 10.1088/1361-6560/ae5757 → Physics in Medicine & Biology
```

For framework files (no DOI), keep "Various" or the website name ("abs Website"), but normalize the casing to "ABS Website".

**Verification method:**
```bash
grep -c "Journal: Various\|Website" guidelines_brachytherapy.md
# Should decrease after fixing
```

---

### 🟢 Finding #15: Orphaned `.txt` file referenced in isolation

**File:** `clinical_kb/guidelines_brachytherapy.md`
**Line:** 2263
**Severity:** Low
**Found by:** Angle C, E, sweep

**Description:**
`i125-pancreatic-guideline-2023.txt` is referenced at line 2263 as "Full text also at:" but is **not in the Master Source Index** and **not in the gi:pancreatic sub-topic of the Topic Tree**.

**Fix:**
See Finding #5 (recommendation: delete the `.txt` or add a row in the Master Index).

---

## 3. Fix Priority Matrix

| Severity | Count | Fix effort | Fix method |
|--------|------|----------|----------|
| 🔴 Critical | 2 | 5 minutes | one-line sed replacement |
| 🟠 High | 6 | 30 minutes | sed + manual + regenerate Topic Index |
| 🟡 Medium | 6 | 1-2 hours | manual fixes or Python batch script |
| 🟢 Low | 1 | 30 minutes | recompute or complete |

**Total fix effort: 2-3 hours**

---

## 4. Complete Fix Execution Plan

### 4.1 Immediate fixes (within 10 minutes)

```bash
# Fix #1, #2: 2 broken anchors
cd <workspace>/BrachyBot/clinical_kb
sed -i 's|gec-estro-cervix-2005-haie-meder)|gec-estro-cervix-2005-haie)|g' guidelines_brachytherapy.md
sed -i 's|embrace-i-pivotal-2021-lancet-oncol)|embrace-i-pivotal-2021-lancet)|g' guidelines_brachytherapy.md

# Fix #9: "(1 files)" → "(1 file)"
sed -i 's|(1 files)|(1 file)|g' guidelines_brachytherapy.md
```

### 4.2 Short-term fixes (within 30 minutes)

```bash
# Fix #5: 110 → 109 (delete the .txt)
rm sources/05_gi/raw/i125-pancreatic-guideline-2023.txt
sed -i 's|110 source files|109 source files|g; s|all 110 files|all 109 files|g; s|the 110 source files|the 109 source files|g' guidelines_brachytherapy.md
# Also delete the "Full text also at: ..." line at line 2263
# Also fix line 2224: (15 files) → (14 files)
sed -i 's|Gastrointestinal Brachytherapy (15 files)|Gastrointestinal Brachytherapy (14 files)|' guidelines_brachytherapy.md
```

### 4.3 Medium-term fixes (1-2 hours)

```bash
# Fix #4: Penile-BT Journal field
cd <workspace>/BrachyBot/clinical_kb
sed -i 's|^journal: "Nature"$|journal: "Brachytherapy"|' sources/02_prostate_gu/raw/nature-bt-penile-organ-preservation-2015.md

# Fix #3: 8 entry titles (modify one by one with the manual Edit tool)

# Fix #7: regenerate the Topic Index (run the rebuild script)

# Fix #8: 24 vs 17 metadata stubs (actually recompute)
```

### 4.4 Long-term improvements (optional)

- #10, #11, #12, #13, #14, #15: depends on user priorities

---

## 5. Verification Methods (Must Run After Fixing)

### 5.1 Automated verification script

Create a `verify_kb.py` script to run after every modification:

```python
#!/usr/bin/env python3
"""Verify KB integrity after any modification."""
import re
import subprocess
from pathlib import Path

ROOT = Path("<workspace>/BrachyBot/clinical_kb")
KB = ROOT / "guidelines_brachytherapy.md"

text = KB.read_text(encoding='utf-8')

# Check 1: all <a id> are unique
ids = re.findall(r'<a id="([^"]+)">', text)
assert len(ids) == len(set(ids)), f"Duplicate IDs: {[i for i in ids if ids.count(i) > 1]}"

# Check 2: all [text](#id) references exist
defined = set(ids)
refs = set(re.findall(r'\(#(kb:[^)]+)\)', text))
missing = refs - defined
assert not missing, f"Broken refs: {missing}"

# Check 3: all source files are referenced
src_files = set(f.name for cat in (ROOT / "sources").iterdir() 
                if cat.is_dir() and cat.name != "_meta"
                for f in (cat / "raw").iterdir() 
                if f.suffix in (".md", ".txt"))
kb_refs = set(re.findall(r'\[([^\]]+\.(?:md|txt))\]\(sources/[^)]+\)', text))
assert src_files == kb_refs, f"Missing: {src_files - kb_refs}, Extra: {kb_refs - src_files}"

# Check 4: no "(1 files)" grammar error
assert "(1 files)" not in text, "Grammar error: (1 files) found"

# Check 5: no #N/A links
assert "pubmed.ncbi.nlm.nih.gov/N/A" not in text, "Hallucinated N/A link found"

# Check 6: Topic Index counts are accurate
topic_header_re = re.compile(r"### `([^`]+)` \((\d+) entries\)\n+(.*?)(?=\n### |\Z)", re.DOTALL)
for topic, count_str, body in topic_header_re.findall(text):
    count = int(count_str)
    actual = len(re.findall(r"^- ", body, re.MULTILINE))
    assert count == actual, f"Topic '{topic}': header says {count}, actual {actual}"

print("✅ All KB integrity checks passed")
```

### 5.2 Manual verification checklist

- [ ] Open the KB, Ctrl+F "gec-estro-cervix-2005-haie-meder" — should be 0 matches
- [ ] Open the KB, Ctrl+F "embrace-i-pivotal-2021-lancet-oncol" — should be 0 matches
- [ ] Open the KB, Ctrl+F "(1 files)" — should be 0 matches
- [ ] Open the KB, Ctrl+F "Nature" — should appear in places such as cross-ref links, but not as a Journal field
- [ ] Open the KB, Ctrl+F "110" — should appear only in disk count contexts (after fixing it should be 109)
- [ ] Open the KB, click each cornerstone link in the Part I IGABT list — should jump to the corresponding entry
- [ ] Open the KB, browse the first entry of each category — the title should be a paper title, not a section title
- [ ] Open the KB, go to the Master Source Index — 109 rows corresponding to 109 .md files

---

## 6. Design-Level Reflections

### 6.1 Is the restructuring effective?

**Yes.** The tree structure + stable ID + topic tags + cross-references significantly improve the LLM's indexing capability:
- Locate by topic path: `kb:cat:sub:file-slug`
- Reverse-query by topic: Part III § Topic Index
- Explore by theme: the See also network

### 6.2 New problems introduced by the restructuring

1. **Anchor inconsistency**: Manually constructing 111 IDs easily produces subtle differences (`meder` vs `haie`); generation should be automated in the future
2. **Content duplication**: The distribution of content between cross-cutting tables and entry bodies needs rules (either the entry is complete or the table is complete)
3. **Empty-shell entries**: 3 entries depend entirely on a cross-cutting table, breaking RAG retrieval completeness
4. **Count drift**: The `.md`/`.txt` twins introduce a +1 drift; a single format should be standardized

### 6.3 Long-term recommendations

1. **Establish CI verification**: automatically run `verify_kb.py` after every KB modification
2. **Create a source file template**: make `title` / `journal` / `year` / `doi` / `pmid` mandatory, with a warning if any is missing
3. **Build a stable ID auto-generation function**: forbid manual ID editing
4. **Consider migrating to a structured format**: in the future, migrate the KB from markdown to JSON / YAML and render it on the frontend with a RAG-friendly schema

---

## 7. Appendix

### 7.1 Review tooling

- 8 sub-agents scanning in parallel (Angle A, B, C, D, E, F, G, H)
- 1 sweep pass
- Direct verification of key findings in the main session

### 7.2 Review effort

- Launching 8 sub-agents: ~5 minutes
- Sub-agent run time: ~30-60 seconds each (~5 minutes total in parallel)
- Main-session verification: ~5 minutes
- Writing this report: ~30 minutes
- **Total effort: ~45 minutes**

### 7.3 Fix effort estimate

| Phase | Effort |
|------|------|
| Immediate fixes (#1, #2, #9) | 5-10 minutes |
| Short-term fixes (#3-#8) | 1-2 hours |
| Medium-term improvements (#10-#15) | 2-3 hours |
| Establish CI verification | 1-2 hours |
| **Total** | **4-8 hours** |

### 7.4 Related file paths

- `clinical_kb/guidelines_brachytherapy.md` — main KB
- `clinical_kb/sources/<category>/raw/` — 110 source files
- `clinical_kb/_meta/MANIFEST.csv` — source file manifest
- `clinical_kb/_meta/FETCH_LOG.md` — fetch log

---

**Report author:** BrachyBot Clinical KB Code Review
**Report version:** 1.0
**Recommendation for next review:** After fixes are complete, re-run the 8-angle review to verify improvements
