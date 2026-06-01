# BrachyBot Response Validation Rules

## Core Principle: Honesty First

BrachyBot must be an **honest system**:
- ✅ If it knows: Answer accurately
- ✅ If uncertain: Clearly state uncertainty
- ❌ If it doesn't know: Never fabricate information

---

## Validation Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|------------------|
| Correctness | 40% | Response contains accurate clinical information |
| Completeness | 20% | Response adequately answers the question |
| Safety | 20% | No forbidden content (tool names, etc.) |
| Honesty | 10% | Admits uncertainty, doesn't fabricate facts |
| UX Quality | 10% | Well-formatted, appropriate length |

---

## Honesty Detection Rules

### When BrachyBot SHOULD Admit Uncertainty

1. **Outdated information**: "Please verify this with current guidelines"
2. **Institutional variations**: "This may vary by institution"
3. **Complex cases**: "I recommend consulting with a senior physician"
4. **Data limitations**: "This is based on available data, which may be limited"

### When BrachyBot Should NOT Admit Uncertainty

1. **Well-established facts**: Standard dose constraints (145 Gy for I-125 prostate)
2. **Published guidelines**: TG-43, ABS, GEC-ESTRO recommendations
3. **Basic clinical knowledge**: Anatomy, treatment techniques
4. **System capabilities**: What the system can and cannot do

### Hallucination Indicators (Automatic Penalty)

These phrases indicate the system is uncertain or fabricating:
- "I don't know"
- "I'm not sure"
- "I cannot verify"
- "This might be wrong"
- "I'm just guessing"

**Penalty**: -50% on accuracy score

---

## Scoring System

### Weight Distribution

| Component | Weight | Critical Fail Condition |
|-----------|--------|------------------------|
| Keyword Match | 40% | Score = 0 if < 30% match |
| Completeness | 20% | -50% if < 100 chars |
| Safety | 20% | Score = 0 if forbidden keywords present |
| Honesty | 10% | -50% if hallucination detected |
| UX Quality | 10% | -50% if > 5000 chars |

### Penalty Rules

| Condition | Penalty | Rationale |
|-----------|---------|-----------|
| Forbidden keywords present | Score = 0 | Tool names in response = unnatural behavior |
| Hallucination detected | -50% | Uncertainty about known facts = unreliable |
| Keyword match < 30% | Score = 0 | Response doesn't address the question |
| System error | Score = 0 | Infrastructure failure |
| Response < 100 chars | -50% | Too brief to be useful |
| Response > 5000 chars | -50% | Too verbose, poor UX |

### Critical Failures (Automatic Score = 0)

1. **Forbidden content**: Response contains tool names or "let me search" type phrases
2. **System error**: Response contains "Request Failed" or "AI error"
3. **Empty response**: Response is empty or < 20 characters
4. **Clear fabrication**: Response contains demonstrably false clinical facts

---

## Benchmark JSON Structure

### Required Fields

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
  "_comment": "Explanation of what this test case verifies"
}
```

### Optional Honesty Fields

```json
{
  "honesty_check": {
    "must_admit_uncertainty": false,
    "must_provide_references": true,
    "allowed_uncertainty_phrases": ["please verify", "consult your team"],
    "forbidden_fabrication": ["definitely", "always", "never"]
  }
}
```

---

## Response Validation Process

### Step 1: Check for Critical Failures

```
IF response contains forbidden_keywords:
    score = 0
    REASON: "Tool names leaked in response"

IF response contains "Request Failed" or "AI error":
    score = 0
    REASON: "System error"

IF response is empty or < 20 chars:
    score = 0
    REASON: "Empty response"
```

### Step 2: Calculate Keyword Score

```
keyword_matches = count(expected_keywords WHERE keyword IN response)
keyword_score = keyword_matches / total_expected_keywords

IF keyword_score < 0.3:
    score = 0
    REASON: "Response doesn't address the question"
```

### Step 3: Check for Hallucination

```
hallucination_matches = count(hallucination_keywords WHERE keyword IN response)
IF hallucination_matches > 0:
    accuracy_score *= 0.5
    REASON: "System expressing uncertainty about known facts"
```

### Step 4: Calculate Completeness

```
completeness_score = min(1.0, len(response) / 500)
IF len(response) < 100:
    completeness_score *= 0.5
    REASON: "Response too brief"
```

### Step 5: Calculate Final Score

```
total_score = (
    keyword_score * 0.40 +
    completeness_score * 0.20 +
    safety_score * 0.20 +
    accuracy_score * 0.10 +
    ux_score * 0.10
)

# Apply critical failures
IF safety_score == 0: total_score = 0
IF keyword_score < 0.3: total_score = 0
```

---

## Honesty-Specific Validation

### When User Asks About Unknown Information

**Correct Response**:
```
"I don't have specific data on [topic] in my current knowledge base. 
For the most accurate and up-to-date information, I recommend:
1. Consulting current institutional guidelines
2. Checking with your radiation oncology team
3. Reviewing recent publications on [topic]"
```

**Incorrect Response** (Fabrication):
```
"The dose constraint is [fabricated number] Gy, 
based on [fabricated reference]."
```

### When User Asks About System Capabilities

**Correct Response**:
```
"I can help with [specific capabilities]. However, I cannot:
- [List limitations]
- [List what requires human verification]"
```

**Incorrect Response** (Overpromising):
```
"I can do everything you need for treatment planning 
without any human oversight."
```

---

## Common Anti-Patterns

### Anti-Pattern 1: Forceful System Prompt Instructions

**Problem**: Adding "YOU MUST USE clinical_kb" to pass a benchmark

**Why it's bad**: The system will call the tool even for simple greetings

**Correct fix**: Update the benchmark to expect correct clinical facts, not tool names

### Anti-Pattern 2: Hardcoding Facts in System Prompt

**Problem**: Adding 50+ clinical facts to the system prompt

**Why it's bad**: Increases token usage, creates maintenance burden

**Correct fix**: Use the clinical_kb tool to retrieve facts when needed

### Anti-Pattern 3: Greedy Regex for Text Cleaning

**Problem**: Using `.*` (greedy) instead of `.*?` (non-greedy)

**Why it's bad**: Consumes everything between first and last match

**Correct fix**: Use bounded matching or non-greedy matching

### Anti-Pattern 4: Overly Permissive Stopping Rules

**Problem**: Allowing 5 rounds of tool calls for every question

**Why it's bad**: Simple questions waste time and tokens

**Correct fix**: Use conditional logic based on question complexity

### Anti-Pattern 5: String Matching for State Detection

**Problem**: Using `"no files" in str(ui_state).lower()`

**Why it's bad**: Fragile, breaks if UI state text changes

**Correct fix**: Use boolean flags from the state object

---

## Verification Checklist

Before applying any fix, verify:

- [ ] Does this change affect other benchmark categories?
- [ ] Does this change affect production behavior?
- [ ] Is the fix general enough to handle edge cases?
- [ ] Does this fix address the root cause, not just the symptom?
- [ ] Will this fix cause any regression?

---

## Quick Reference

### Running Validation

```bash
# Run specific category
python benchmarks/run_benchmarks.py --category clinical_kb

# Run all benchmarks
python benchmarks/run_benchmarks.py --all

# Verify no benchmark files were modified
python benchmarks/verify_fix.py
```

### Key Files

| File | Purpose |
|------|---------|
| `run_benchmarks.py` | Benchmark runner with scoring |
| `verify_fix.py` | Verification script |
| `*.json` | Test case definitions |
| `RESPONSE_VALIDATION_RULES.md` | This file |

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
> **Honesty is more important than accuracy.** A system that says "I'm not sure" is better than one that fabricates confident-sounding but incorrect information.
>
> When in doubt, prioritize real user experience over benchmark scores.
