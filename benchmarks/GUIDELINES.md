# Benchmark Execution Guidelines

## Purpose

This document provides guidelines for using benchmarks to iteratively improve BrachyBot. It serves as a reference for the AI model when making changes to ensure that improvements do not inadvertently degrade system behavior.

---

## Core Principles

### 1. First, Do No Harm

Before making any change to improve benchmark scores, verify that the change does not break existing functionality. A 5% improvement on one benchmark that causes a 10% regression on another is a net loss.

**Checklist before applying any fix:**
- [ ] Does this change affect other benchmark categories?
- [ ] Does this change affect production behavior (real user interactions)?
- [ ] Is the fix general enough to handle edge cases, or is it "teaching to the test"?

### 2. Test Real Behavior, Not Tool Invocation

Benchmarks should verify that the system provides **correct, helpful responses** — not that specific tools are called. A system that answers clinical questions correctly from its training knowledge is better than one that mechanically calls tools for every question.

**Wrong approach:**
```json
{
  "input": "What is the prostate dose constraint?",
  "expected_keywords": ["clinical_kb", "constraints", "prostate"]
}
```

**Right approach:**
```json
{
  "input": "What is the prostate dose constraint?",
  "expected_keywords": ["145", "Gy", "prostate"],
  "forbidden_keywords": ["clinical_kb", "let me search"]
}
```

### 3. Avoid "Teaching to the Test"

If a benchmark fails, the fix should address the **root cause**, not add a special case to pass the test. Adding "YOU MUST USE clinical_kb" to the system prompt because a benchmark expects it is a band-aid that will cause problems in production.

**Root cause analysis questions:**
- Why did the system fail this test?
- Is the system prompt unclear or contradictory?
- Is the tool not being called when it should be?
- Is the tool being called when it shouldn't be?

---

## Benchmark Structure

### File Naming Convention

```
{number}_{category}.json
```

- `01-23`: Core medical AI benchmarks (extracted from benchmark_2000.json)
- `24-32`: New tool and workflow benchmarks

### JSON Structure

```json
{
  "category": "category_name",
  "description": "Human-readable description",
  "requires_ct": false,
  "_comment": "Explanation of what this benchmark tests and the testing philosophy",
  "scoring_rules": {
    "keyword_weight": 0.40,
    "completeness_weight": 0.20,
    "safety_weight": 0.20,
    "accuracy_weight": 0.10,
    "ux_weight": 0.10,
    "pass_threshold": 0.6,
    "critical_fail_if": ["forbidden_keywords_present", "keyword_match_below_0.3"]
  },
  "cases": [
    {
      "id": "CK001",
      "input": "User's question",
      "expected_keywords": ["keyword1", "keyword2"],
      "forbidden_keywords": ["tool_name", "let me search"],
      "hallucination_keywords": ["I don't know", "I'm not sure"],
      "pass_threshold": 0.6,
      "difficulty": "easy|medium|hard",
      "user_type": "beginner|experienced|chinese",
      "_comment": "Explanation of what this test case verifies"
    }
  ]
}
```

### Key Fields

| Field | Purpose | Example |
|-------|---------|---------|
| `expected_keywords` | Terms that MUST appear in a correct response | `["145", "Gy", "prostate"]` |
| `forbidden_keywords` | Terms that MUST NOT appear (tool names, etc.) | `["clinical_kb", "let me search"]` |
| `hallucination_keywords` | Signs of uncertainty or fabrication | `["I don't know", "I'm not sure"]` |
| `pass_threshold` | Minimum score to pass (0.0-1.0) | `0.6` |
| `_comment` | Human-readable explanation of test purpose | `"User asks about dose..."` |

---

## Scoring System

### Weight Distribution

| Component | Weight | What It Measures |
|-----------|--------|------------------|
| Keyword Match | 40% | Response contains expected clinical terms |
| Completeness | 20% | Response is substantial (≥300 chars) |
| Safety | 20% | No forbidden keywords present |
| Accuracy | 10% | No hallucination indicators |
| UX Quality | 10% | Well-formatted, appropriate length |

### Penalty Rules

| Condition | Penalty | Rationale |
|-----------|---------|-----------|
| Forbidden keywords present | Score = 0 | Tool names in response = unnatural behavior |
| Hallucination detected | -50% | Uncertainty about known facts = unreliable |
| Keyword match <30% | Automatic fail | Response doesn't address the question |
| System error | Score = 0 | Infrastructure failure |
| Response <100 chars | -50% | Too brief to be useful |

### Critical Failures

These conditions result in an automatic score of 0, regardless of other factors:

1. **Forbidden content**: Response contains tool names or "let me search" type phrases
2. **System error**: Response contains "Request Failed" or "AI error"
3. **Empty response**: Response is empty or <20 characters

---

## Common Anti-Patterns to Avoid

### Anti-Pattern 1: Forceful System Prompt Instructions

**Problem:** Adding "YOU MUST USE clinical_kb" to pass a benchmark that expects tool calls.

**Why it's bad:** The system will call the tool even for simple greetings, wasting tokens and providing unnatural responses.

**Correct fix:** Update the benchmark to expect correct clinical facts, not tool names.

### Anti-Pattern 2: Hardcoding Facts in System Prompt

**Problem:** Adding 50+ clinical facts to the system prompt to ensure they appear in responses.

**Why it's bad:** 
- Increases token usage by ~2000 tokens per request
- Creates maintenance burden (two places to update)
- May conflict with clinical_kb if values differ

**Correct fix:** Use the clinical_kb tool to retrieve facts when needed.

### Anti-Pattern 3: Greedy Regex for Text Cleaning

**Problem:** Using `.*` (greedy) instead of `.*?` (non-greedy) in regex patterns to remove tool call blocks.

**Why it's bad:** Greedy matching consumes everything between the first and last match, including legitimate response text.

**Correct fix:** Use bounded matching (e.g., `.{0,2000}`) or non-greedy matching (`.*?`).

### Anti-Pattern 4: Overly Permissive Stopping Rules

**Problem:** Allowing 5 rounds of tool calls for every question.

**Why it's bad:** Simple questions that should be answered in 1 round end up calling tools 5 times, wasting time and tokens.

**Correct fix:** Use conditional logic — 1 round for knowledge questions, up to 5 rounds for workflows.

### Anti-Pattern 5: String Matching for State Detection

**Problem:** Using `"no files" in str(ui_state).lower()` to detect if CT is loaded.

**Why it's bad:** Fragile — breaks if the UI state text changes.

**Correct fix:** Use boolean flags from the state object (e.g., `ui_state.get("ct_loaded", False)`).

---

## Iteration Process

### Step 1: Run Baseline

```bash
python benchmarks/run_benchmarks.py --all
```

Record the baseline scores for all categories.

### Step 2: Identify Failures

Focus on categories with the lowest pass rates. For each failure:
1. Read the test case `_comment` to understand what it's testing
2. Read the actual response to understand what went wrong
3. Identify the root cause

### Step 3: Apply Fix

Make a targeted fix that addresses the root cause. Avoid:
- Adding forceful instructions to the system prompt
- Hardcoding expected values
- Adding special cases for specific test cases

### Step 4: Verify No Regression

After applying the fix:
1. Re-run the failing category to verify the fix works
2. Re-run ALL categories to verify no regression
3. Compare scores with baseline

### Step 5: Document Change

Update the `_comment` field in any modified test cases to explain the change.

---

## Adding New Test Cases

When adding new test cases:

1. **Focus on user intent**: What does the user actually want?
2. **Use natural language**: Write inputs as a real user would
3. **Expect correct facts**: Use `expected_keywords` for clinical values
4. **Forbid tool names**: Use `forbidden_keywords` to prevent tool name leakage
5. **Add comments**: Explain what the test verifies and why
6. **Set appropriate threshold**: Use `pass_threshold` based on difficulty

### Example: Adding a New Clinical Question

```json
{
  "id": "CK016",
  "input": "What is the standard prescription dose for I-125 prostate brachytherapy?",
  "expected_keywords": ["145", "Gy", "I-125", "prostate"],
  "forbidden_keywords": ["clinical_kb", "let me search", "I'll look up"],
  "hallucination_keywords": ["I don't know", "I'm not sure", "I cannot verify"],
  "pass_threshold": 0.6,
  "difficulty": "easy",
  "user_type": "beginner",
  "_comment": "Standard clinical knowledge question. System should answer directly with the correct dose (145 Gy) without calling tools."
}
```

---

## Interpreting Results

### Pass Rate Interpretation

| Pass Rate | Interpretation | Action |
|-----------|----------------|--------|
| 90-100% | Excellent | Focus on edge cases |
| 70-89% | Good | Address specific failures |
| 50-69% | Needs work | Identify systematic issues |
| <50% | Poor | Major rework needed |

### Score Breakdown Analysis

If a category has low scores, check which component is failing:

- **Low keyword score**: System is not providing correct clinical information
- **Low safety score**: System is leaking tool names or forbidden content
- **Low accuracy score**: System is expressing uncertainty about known facts
- **Low completeness score**: System is providing too-brief responses

---

## Maintenance

### Regular Tasks

1. **Weekly**: Run full benchmark suite and compare with previous week
2. **After any system prompt change**: Run benchmarks to verify no regression
3. **After adding new tools**: Run tool-specific benchmarks
4. **After updating clinical_kb**: Run clinical knowledge benchmarks

### Benchmark Updates

When updating benchmarks:
1. Always add `_comment` fields explaining the change
2. Update `expected_keywords` if clinical facts change
3. Add `forbidden_keywords` for new tool names
4. Test the updated benchmark against the current system before committing

---

## Quick Reference

### Running Benchmarks

```bash
# Show statistics
python benchmarks/run_benchmarks.py --stats

# Run specific category
python benchmarks/run_benchmarks.py --category clinical_kb

# Run all benchmarks
python benchmarks/run_benchmarks.py --all

# Verbose output
python benchmarks/run_benchmarks.py --all -v
```

### Key Files

| File | Purpose |
|------|---------|
| `run_benchmarks.py` | Benchmark runner with scoring |
| `*.json` | Test case definitions |
| `GUIDELINES.md` | This file |

### Scoring Formula

```
total_score = (
    keyword_score * 0.40 +
    completeness_score * 0.20 +
    safety_score * 0.20 +
    accuracy_score * 0.10 +
    ux_score * 0.10
)

# Apply penalties
if safety_score == 0: total_score = 0
if keyword_score < 0.3: total_score = 0
if accuracy_score < 0.5: total_score *= 0.5
```

---

## Remember

> **The goal is not to pass benchmarks — the goal is to build a system that helps clinicians.**
>
> Benchmarks are a tool to measure progress, not an end in themselves. A system that passes all benchmarks but gives unnatural responses in production is a failure.
>
> When in doubt, prioritize real user experience over benchmark scores.
