# Benchmark Quality Audit Report

## Executive Summary

This document identifies potential issues with current benchmark tests and provides recommendations for improvement. It serves as a reference for agents iterating on BrachyBot to avoid "teaching to the test" pitfalls.

**Date:** 2026-06-01  
**Auditor:** Claude Code  
**Version:** 1.0

---

## 1. Scoring System Limitations

### 1.1 Keyword Matching ≠ Understanding

**Issue:** Current keyword matching detects word presence but not semantic correctness.

**Example Problem:**
```json
// Test expects: "dose", "Gy", "bladder"
// BrachyBot outputs: "The dose should be given to the bladder in Gy units"
// Score: 100% keyword match
// Reality: Meaningless sentence with correct keywords
```

**Recommendation:**
- Add semantic similarity checks using sentence embeddings
- Verify keyword context (e.g., "dose" should be near a number + "Gy")
- Consider adding `expected_phrases` field for multi-word concepts

### 1.2 Completeness Scoring Too Simple

**Issue:** Current scoring uses character count (<300 chars = full score).

**Problems:**
- A 200-char response with incorrect info gets higher score than 100-char correct response
- Doesn't assess information quality or relevance
- Structured content (lists, headers) not rewarded

**v3 Improvements:**
- Quality-based scoring with bonuses for:
  - Structured content (lists, headers)
  - Specific numbers/units (Gy, cc, mm)
  - Appropriate length for difficulty level
- Penalty for excessive repetition

### 1.3 Limited Hallucination Detection

**Issue:** Only matches fixed phrases like "typically around", "generally about".

**Problems:**
- Many fabrication patterns not detected
- False positives on legitimate hedging language
- No context-aware detection

**v3 Improvements:**
- Expanded fabrication indicators
- Bonus for appropriate hedging ("may", "might", "typically")
- Difficulty-aware honesty bonuses

---

## 2. Test Reliability Issues

### 2.1 LLM Output Variability

**Issue:** Same input can produce different outputs, causing score fluctuations.

**Impact:**
- A test might pass/fail randomly
- Difficult to distinguish real improvements from noise
- Regression detection unreliable

**v3 Solution: Multi-Run Stability Testing**
```bash
# Run each test 3 times, take majority vote
python benchmarks/run_benchmarks_v3.py --all --runs 3
```

**Metrics Added:**
- `stability`: 0-1 score indicating consistency across runs
- `pass_votes` / `fail_votes`: Raw vote counts
- Low stability tests flagged for investigation

### 2.2 API Timeout Issues

**Issue:** Complex questions may exceed 120s timeout.

**v3 Solution: Dynamic Timeout**
```python
TIMEOUT_BY_DIFFICULTY = {
    "easy": 60,     # Simple questions
    "medium": 120,  # Standard questions
    "hard": 180     # Complex questions
}
# Multi-turn tests get additional time
# CT-dependent tests get +30s
```

---

## 3. Chain Reaction Risks

### 3.1 Cross-Category Impact

**Issue:** Fixing one category may break another.

**Example:**
- Strengthening honesty mechanism → originally correct answers become too conservative
- Adding safety rules → legitimate medical info refused

**Mitigation:**
- Always run full regression suite after changes
- Compare results before/after using `--compare` flag
- Regression tests (35_regression.json) are red lines

### 3.2 Prompt Modification Impact

**Issue:** System prompt changes have widest impact.

**Risk Assessment:**
| Change Type | Impact Scope | Risk Level |
|-------------|--------------|------------|
| System prompt | All tests | HIGH |
| Tool definitions | Tool-using tests | MEDIUM |
| Response format | All tests | MEDIUM |
| Single tool logic | Related tests | LOW |

**Recommendation:**
- Test prompt changes with `--runs 3` for stability
- Compare before/after with `--compare`
- Document expected impact before changes

---

## 4. Root Analysis Pitfalls

### 4.1 Symptom vs Root Cause

**Issue:** Multiple test failures may look similar but have different root causes.

**Example - "Low keyword match":**
- Cause A: Keyword not in vocabulary → fix: add to knowledge base
- Cause B: Question misunderstood → fix: improve intent detection
- Cause C: Response too brief → fix: adjust length constraints
- Cause D: Wrong tool called → fix: improve tool selection

**Recommendation:**
- Analyze failures by category, not just symptom
- Group similar failures and look for patterns
- Test fixes in isolation before applying broadly

### 4.2 Batch Fix Dangers

**Issue:** Applying same fix to all failures is risky.

**Wrong Approach:**
```
"All keyword failures → add more keywords to system prompt"
```

**Right Approach:**
```
1. Group failures by root cause
2. Fix highest-impact cause first
3. Test fix on affected tests only
4. Run full regression
5. Repeat for next cause
```

---

## 5. Practical Recommendations

### 5.1 Priority Order

Fix in this order:
1. **Safety violations** (automatic 0 score)
2. **Regression failures** (previously working features broken)
3. **Low keyword matches** (largest category, 35% weight)
4. **Accuracy issues** (hallucination, fabrication)
5. **UX issues** (verbosity, filler content)

### 5.2 Iteration Protocol

```
1. Run baseline: python benchmarks/run_benchmarks_v3.py --all --runs 3
2. Save results: cp results/latest.json results/baseline_YYYYMMDD.json
3. Make ONE change
4. Run tests: python benchmarks/run_benchmarks_v3.py --all --runs 3
5. Compare: python benchmarks/run_benchmarks_v3.py --compare results/current.json results/baseline.json
6. If improved → commit
7. If regressed → revert and investigate
8. Repeat
```

### 5.3 Result Preservation

- Save ALL result JSON files (version history evidence)
- Name format: `benchmark_v3_YYYYMMDD_HHMMSS.json`
- Keep baseline results for major milestones
- Never delete historical results

### 5.4 Context Management

- Always use `clear_context=true` between tests
- Server restart clears all context
- Multi-turn tests handle context internally

---

## 6. Known Benchmark Issues

### 6.1 Unreasonable Expectations

**Status:** To be documented during test runs

**What to look for:**
- Tests expecting hospital-specific data BrachyBot shouldn't know
- Tests with ambiguous "correct" answers
- Tests where refusing is actually the right response
- Tests with outdated medical guidelines

**Action:** Document in this file but don't modify benchmarks

### 6.2 Test Coverage Gaps

**Current gaps:**
- No negative testing (what BrachyBot should refuse)
- Limited edge case coverage
- No stress testing (very long inputs, rapid requests)
- No adversarial testing (prompt injection attempts)

---

## 7. v3 Feature Summary

| Feature | Description | Command |
|---------|-------------|---------|
| Multi-run stability | Run tests N times, majority vote | `--runs N` |
| Dynamic timeout | Adjusts by difficulty | Automatic |
| Concept coverage | Checks medical term coverage | Automatic |
| Quality-based completeness | Structure, numbers, relevance | Automatic |
| Enhanced hallucination | Expanded detection patterns | Automatic |
| Run comparison | Diff two result files | `--compare A B` |

---

## 8. Recommendations for Agents

### DO:
- ✅ Run `--runs 3` for critical changes
- ✅ Always compare before/after
- ✅ Save result files with descriptive names
- ✅ Analyze failures by root cause
- ✅ Test one change at a time
- ✅ Keep regression tests as red lines

### DON'T:
- ❌ Modify .json benchmark files
- ❌ Apply same fix to all failures
- ❌ Skip regression tests
- ❌ Delete historical results
- ❌ Make multiple changes between test runs
- ❌ Trust single-run pass/fail for flaky tests

---

## Appendix: Quick Reference

```bash
# Basic usage
python benchmarks/run_benchmarks_v3.py --all
python benchmarks/run_benchmarks_v3.py --category greeting

# Stability testing
python benchmarks/run_benchmarks_v3.py --all --runs 3
python benchmarks/run_benchmarks_v3.py --category safety --runs 5

# Compare results
python benchmarks/run_benchmarks_v3.py --compare results/current.json results/baseline.json

# View statistics
python benchmarks/run_benchmarks_v3.py --stats
```

---

*This document should be updated as new issues are discovered during benchmark runs.*
