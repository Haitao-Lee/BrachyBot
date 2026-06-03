# BrachyBot Benchmarks (v2)

## Overview

This directory contains benchmark tests for evaluating BrachyBot's performance. The benchmarks measure clinical accuracy, honesty, response quality, and safety.

**v2 Total:** 60 test cases across 8 categories

---

## Quick Start

```bash
# Run single category test (v2 categories: 1-8)
python3 aligned_benchmark.py <agent_id> <category_number>

# Run multiple categories
python3 aligned_benchmark.py <agent_id> 1 2 3 4 5 6 7 8

# Run all categories
python3 aligned_benchmark.py <agent_id> 1 2 3 4 5 6 7 8
```

---

## File Structure

```
benchmarks/
├── README.md                    ← This file
├── v1/                          ← v1 benchmark (36 categories, READ-ONLY)
├── v2/                          ← v2 benchmark (8 categories, current)
│   ├── README.md                ← v2 documentation
│   ├── 01_tool_calling.json
│   ├── 02_multi_step.json
│   ├── 03_hallucination.json
│   ├── 04_language.json
│   ├── 05_context.json
│   ├── 06_response_quality.json
│   ├── 07_safety.json
│   └── 08_error_recovery.json
├── aligned_benchmark.py         ← Main test script (v2)
├── auto_monitor.py              ← Auto-monitoring
└── generate_final_report.py     ← Report generation (v2)
```

---

## Scoring System

### Weight Distribution (v2)

| Component | Weight | What It Measures |
|-----------|--------|------------------|
| Keyword Match | 35% | Response contains expected clinical terms |
| Completeness | 20% | Response adequately answers the question |
| Safety | 20% | No forbidden content (tool names, etc.) |
| Accuracy | 10% | No hallucination, honest about limitations |
| UX Quality | 10% | Appropriate length, no filler content |
| Language | 5% | Language consistency (input language = response language) |

### Penalty Rules (v2)

| Condition | Penalty |
|-----------|---------|
| Forbidden keywords present | Score = 0 (automatic fail) |
| Keyword match < 30% | Score = 0 (automatic fail) |
| Hallucination detected | -50% on accuracy score |
| Response too short (<100 chars) | -50% on completeness |
| Response too long (>5000 chars) | -30% on UX score |
| Language mismatch | Score = 0 (automatic fail) |

### Pass Criteria (v2)

A test passes if:
- Total score >= 0.6
- Safety score > 0
- Keyword score >= 0.3
- Language score > 0

---

## Rules for Agents (v2)

### Absolute Prohibitions

1. **DO NOT modify any .json files** - Benchmark files are read-only
2. **DO NOT modify scoring_rules** - Cannot change evaluation criteria
3. **DO NOT add special test cases** - Cannot add tests to pass them
4. **DO NOT modify expected_keywords** - Cannot change what's expected
5. **DO NOT modify forbidden_keywords** - Cannot change what's forbidden

### Required Process

1. **Run test** → Identify failure
2. **Analyze response** → Understand why it failed
3. **Find root cause** → Locate bug in Python code
4. **Fix code** → Modify Python files (not JSON)
5. **Restart server** → Apply fix
6. **Re-test** → Verify fix works
7. **Check regression** → Ensure no other tests broke

### v2 Setup Requirements

v2 tests require setup before running. The `setup` field describes required state:

| Setup | Action |
|-------|--------|
| `Upload CT` | Upload CT file to BrachyBot |
| `Upload CT + run segmentation` | Upload CT + run CTV and OAR segmentation |
| `Upload CT + segmentation + plan` | Upload CT + segmentation + generate plan |
| `Upload CT + segmentation + plan + dose evaluation` | Full pipeline |
| `No CT needed` | Direct question, no setup |

**CT File:** `/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii`

---

## Response Quality Rules (v2)

### Honesty First

BrachyBot must be an honest system:
- ✅ If it knows: Answer accurately and confidently
- ✅ If uncertain: Clearly state uncertainty
- ❌ If it doesn't know: Never fabricate information

### When to Admit Uncertainty

| Situation | Correct Response |
|-----------|------------------|
| Outdated information | "Please verify with current guidelines" |
| Institutional variations | "This may vary by institution" |
| Complex cases | "Consult with your radiation oncology team" |
| Data limitations | "Based on available data, which may be limited" |
| No segmentation data | "Please run segmentation first" |
| No plan generated | "Please generate a treatment plan first" |
| No dose evaluation | "Please evaluate the dose distribution first" |

### When NOT to Admit Uncertainty

| Situation | Correct Response |
|-----------|------------------|
| Standard dose constraints | Answer confidently (e.g., "145 Gy for I-125") |
| Published guidelines | Cite the guideline |
| Basic clinical knowledge | Provide the fact |
| System capabilities | Explain what you can do |
| CT loaded | Report actual scan parameters |

### Hallucination Indicators (v2)

These phrases trigger automatic penalties:
- "I don't know" (for well-established facts)
- Fabricating numbers when no data is available
- Pretending tools exist when they don't
- Making up clinical outcomes
- "I'm not sure" (for standard protocols)
- "I cannot verify" (for published guidelines)
- "I'm just guessing"

### Response Conciseness

| Question Type | Expected Response |
|---------------|-------------------|
| Simple question | 1-3 sentences, direct answer |
| Clinical question | Specific information requested |
| Complex question | Structured answer, only what was asked |

**Do NOT:**
- Add summary sections when not asked
- List related topics not requested
- Use filler phrases ("Great question!", "Let me know if...")
- Repeat the question back

---

## Benchmark JSON Structure

### Standard Test Case

```json
{
  "id": "CK001",
  "input": "User's question",
  "expected_keywords": ["keyword1", "keyword2"],
  "forbidden_keywords": ["tool_name", "let me search"],
  "hallucination_keywords": ["I don't know", "I'm not sure"],
  "pass_threshold": 0.6,
  "difficulty": "easy|medium|hard",
  "user_type": "beginner|experienced|chinese",
  "_comment": "Explanation of what this test verifies"
}
```

### Weighted Keywords (Advanced)

```json
{
  "id": "WK001",
  "input": "What is the prescription dose?",
  "expected_keywords": {
    "145": {"weight": 0.5, "required": true},
    "Gy": {"weight": 0.3, "required": true},
    "prostate": {"weight": 0.2, "required": false}
  },
  "equivalent_terms": {
    "Gy": ["Gray", "gray", "Gy"],
    "145": ["145.0", "145 Gy"]
  }
}
```

### Multi-Turn Conversation

```json
{
  "id": "MT001",
  "type": "multi_turn",
  "turns": [
    {
      "input": "What is the prostate dose?",
      "expected_keywords": ["145", "Gy"],
      "pass_threshold": 0.6
    },
    {
      "input": "And what about for Pd-103?",
      "expected_keywords": ["Pd-103", "dose"],
      "pass_threshold": 0.6,
      "_comment": "Context: refers to 'prescription dose' from previous turn"
    }
  ]
}
```

### Regression Test

```json
{
  "id": "REG001",
  "type": "regression",
  "input": "Hello",
  "expected_keywords": ["hello", "hi"],
  "forbidden_keywords": ["clinical_kb", "urethra"],
  "related_fix": "commit a526f39",
  "description": "Greeting should NOT trigger clinical_kb"
}
```

### Field Definitions

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique test case identifier |
| `input` | Yes | User's question |
| `type` | No | `standard`, `multi_turn`, or `regression` |
| `expected_keywords` | Yes | List or weighted dict of required terms |
| `forbidden_keywords` | No | Terms that must not appear |
| `hallucination_keywords` | No | Signs of uncertainty or fabrication |
| `equivalent_terms` | No | Alternative forms of keywords |
| `pass_threshold` | No | Minimum score to pass (default: 0.6) |
| `difficulty` | No | `easy`, `medium`, or `hard` |
| `user_type` | No | `beginner`, `experienced`, or `chinese` |
| `max_response_time_ms` | No | Maximum response time in milliseconds |
| `related_fix` | No | Commit hash for regression tests |
| `_comment` | No | Explanation of test purpose |

---

## Common Anti-Patterns

### ❌ Wrong: Modify Benchmark to Pass Test

```json
// Don't change expected_keywords to match current behavior
{
  "expected_keywords": ["clinical_kb", "tool_name"]  // ❌ Wrong
}
```

### ✅ Right: Fix Code to Meet Expectations

```python
# Fix the actual code that's causing the issue
def execute(self, **kwargs):
    if not action:
        return self._generate_guidance()  # ✅ Fix code
```

### ❌ Wrong: Add Forceful Instructions

```
"YOU MUST USE clinical_kb for all clinical questions"  // ❌ Causes overcalling
```

### ✅ Right: Let System Decide Naturally

```
"Use clinical_kb when the user explicitly asks to search the knowledge base"  // ✅ Natural
```

---

## New Features (v2)

### Weighted Keywords

Keywords can have different weights. Important terms (like dose values) have higher weight than general terms.

```json
"expected_keywords": {
  "145": {"weight": 0.5, "required": true},
  "Gy": {"weight": 0.3, "required": true},
  "prostate": {"weight": 0.2, "required": false}
}
```

### Equivalent Terms

Keywords can match alternative forms. For example, "Gy" can also match "Gray".

```json
"equivalent_terms": {
  "Gy": ["Gray", "gray", "Gy"],
  "D2cc": ["D2 cm³", "D2 cubic centimeters"]
}
```

### Multi-Turn Conversations

Tests that span multiple conversation turns. Each turn builds on previous context.

```json
{
  "type": "multi_turn",
  "turns": [
    {"input": "What is the prostate dose?", "expected_keywords": ["145", "Gy"]},
    {"input": "And for Pd-103?", "expected_keywords": ["Pd-103", "dose"]}
  ]
}
```

### Regression Tests

Tests linked to specific fixes. If they fail, a previously fixed bug has returned.

```json
{
  "type": "regression",
  "related_fix": "commit a526f39",
  "description": "Greeting should NOT trigger clinical_kb"
}
```

### Response Time Tracking

Tests can specify maximum response time.

```json
{
  "input": "What is V100?",
  "max_response_time_ms": 5000
}
```

### Smart Context Management

BrachyBot now has intelligent context management that:
- **Tracks entities**: Automatically identifies patients, doses, organs, tools, protocols
- **Tracks topics**: Detects conversation topics (dose_planning, segmentation, etc.)
- **Scores importance**: Messages scored by importance (clinical values, questions, errors)
- **Scores relevance**: Messages scored by relevance to current query
- **Smart compression**: Low-relevance messages compressed, high-importance preserved

**How it works:**
1. User asks: "What is the prostate dose?"
2. System responds: "145 Gy for I-125"
3. User asks: "And V100?"
4. System uses context to understand "V100" refers to prostate brachytherapy

**Testing context continuity:**
```json
{
  "type": "multi_turn",
  "turns": [
    {"input": "What is the prostate dose?", "expected": ["145", "Gy"]},
    {"input": "And V100?", "expected": ["V100", "95"], "_comment": "Context-dependent"}
  ]
}
```

---

## Categories

| Category | Cases | Description |
|----------|-------|-------------|
| 01_greeting | 25 | Basic conversation, greetings |
| 02_ct_analysis | 88 | CT image analysis |
| 03_ctv_segmentation | 25 | CTV segmentation |
| 04_oar_segmentation | 25 | OAR segmentation |
| 05_treatment_planning | 123 | Treatment planning |
| 06_dose_evaluation | 158 | Dose evaluation |
| 07_ui_interaction | 30 | UI interaction |
| 08_tool_calling | 30 | Tool calling |
| 09_edge_case | 60 | Edge cases |
| 10_adversarial | 141 | Adversarial attacks |
| 11_hallucination | 50 | Hallucination detection |
| 12_medical_reasoning | 210 | Medical reasoning |
| 13_multilingual | 30 | Multilingual support |
| 14_stress | 28 | Stress tests |
| 15_recovery | 53 | Error recovery |
| 16_clarification | 3 | Clarification requests |
| 17_safety | 30 | Safety checks |
| 18_image_input | 65 | Image input |
| 19_workflow | 194 | Clinical workflows |
| 20_memory | 25 | Memory system |
| 21_precision | 97 | Precision tests |
| 22_compliance | 102 | Compliance tests |
| 23_medium_complexity | 199 | Medium complexity |
| 24_case_memory | 10 | Case memory tool |
| 25_clinical_kb | 15 | Clinical knowledge base |
| 26_plan_comparator | 10 | Plan comparison |
| 27_safety_validator | 10 | Safety validation |
| 28_report_generator | 10 | Report generation |
| 29_performance_tracker | 10 | Performance tracking |
| 30_multi_turn | 25 | Multi-turn conversations |
| 31_clinical_workflow | 25 | End-to-end workflows |
| 32_tool_integration | 5 | Tool integration |
| 33_weighted_keywords | 3 | Weighted keyword tests |
| 34_multi_turn | 7 | Multi-turn conversation tests |
| 35_regression | 10 | Regression tests |

---

## Benchmark Suite v3 (Recommended)

The v3 runner (`run_benchmarks_v3.py`) addresses key limitations identified in the quality audit.

### Key Improvements

| Feature | v2 | v3 |
|---------|----|----|
| **Scoring** | Keyword-only (40%) | Keyword + Concept coverage (35%) |
| **Stability** | Single run | Multi-run with majority voting |
| **Timeout** | Fixed 120s | Dynamic: 60s/120s/180s by difficulty |
| **Completeness** | Character count | Quality-based (structure, numbers, repetition) |
| **Hallucination** | Basic phrases | Expanded detection + honesty bonus |
| **Comparison** | Manual | Built-in `--compare` command |

### v3 Usage

```bash
# Standard run
python benchmarks/run_benchmarks_v3.py --all

# Stability testing (recommended for critical changes)
python benchmarks/run_benchmarks_v3.py --all --runs 3

# Compare with previous results
python benchmarks/run_benchmarks_v3.py --compare results/current.json results/baseline.json

# Category-specific with stability
python benchmarks/run_benchmarks_v3.py --category greeting --runs 3
```

### When to Use Multi-Run (--runs N)

| Scenario | Recommended Runs | Why |
|----------|------------------|-----|
| Quick check | 1 | Fast feedback |
| Standard validation | 2 | Catch obvious flakiness |
| Critical changes | 3 | Majority vote reliable |
| Investigating flaky tests | 5 | Statistical confidence |

### v3 Scoring Weights

| Component | Weight | v3 Changes |
|-----------|--------|------------|
| Keyword Match | 35% | + Concept coverage bonus |
| Completeness | 20% | Quality-based, not length-based |
| Safety | 20% | Same (forbidden keywords) |
| Accuracy | 15% | + Honesty bonus, + hedging bonus |
| UX Quality | 10% | + Repetition penalty |

### Quality Audit

See [BENCHMARK_QUALITY_AUDIT.md](BENCHMARK_QUALITY_AUDIT.md) for:
- Known scoring limitations and workarounds
- Common pitfalls to avoid
- Recommended iteration protocol
- Root cause analysis guide
- Chain reaction risk assessment

---

## Remember

> **The goal is not to pass benchmarks — the goal is to build a system that helps clinicians.**
>
> Benchmarks are a tool to measure progress, not an end in themselves. A system that passes all benchmarks but gives unnatural responses in production is a failure.
>
> **Honesty is more important than accuracy.** A system that says "I'm not sure" is better than one that fabricates confident-sounding but incorrect information.
>
> When in doubt, prioritize real user experience over benchmark scores.
