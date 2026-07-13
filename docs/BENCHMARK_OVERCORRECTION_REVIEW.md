# Benchmark Overcorrection Code Review Report

**Date:** 2026-06-01
**Scope:** Uncommitted changes to AgenticSys.py and related files
**Root Cause:** "Teaching to the test" — modifications made to pass benchmark tests that broke normal runtime behavior

---

## Executive Summary

The system prompt in `AgenticSys.py` contains **32 forceful instructions** (MUST, NEVER, ALWAYS, CRITICAL) added to pass benchmark tests. These instructions conflict with each other and cause the LLM to behave incorrectly in production — for example, searching for "urethra" when the user says "你好" (hello).

**Impact:** 9 findings identified, 4 are benchmark-driven overcorrections that directly cause incorrect behavior.

---

## Critical Findings

### Finding 1: "TOP PRIORITY" forces clinical_kb on ALL messages

**File:** `AgenticSys.py:782-792`
**Severity:** Critical
**Type:** Benchmark overcorrection

**Problem:**
```python
"## 🚨 TOP PRIORITY: Use clinical_kb Tool for Clinical Knowledge\n"
"When the user asks about dose constraints, organ tolerances, treatment protocols,\n"
"plan quality benchmarks, or prescription doses:\n"
"YOU MUST USE the clinical_kb tool to look up the information.\n"
"- action='search' + keyword='urethra' to search the knowledge base\n"
```

This directly **contradicts** line 861:
```python
"- **USE clinical_kb tool ONLY when** the user explicitly asks to search the knowledge database:\n"
```

**Failure Scenario:**
- User: "你好"
- LLM sees "🚨 TOP PRIORITY" + "YOU MUST USE" + example `keyword='urethra'`
- LLM calls `clinical_kb(action="search", keyword="urethra")`
- Response: "让我搜索关于尿道剂量限制的知识库信息"

**Why it was added:** Benchmark test `25_clinical_kb.json` expects clinical_kb to be called for clinical questions. To pass this test, the "TOP PRIORITY" instruction was added, but it applies to ALL messages, not just clinical questions.

**Fix:** Remove the "TOP PRIORITY" section entirely. The "When to Answer Directly vs Use Tools" section (line 849-874) already correctly describes when to use clinical_kb.

---

### Finding 2: Greedy regex eats legitimate response text

**File:** `AgenticSys.py:1289-1295`
**Severity:** High
**Type:** Regression

**Problem:**
```python
# OLD (non-greedy, safe):
cleaned = re.sub(r'\[[\s]*\{[\'"]type[\'"]\s*:\s*[\'"]tool_use[\'"].*?\}[\s]*\]', ...)

# NEW (greedy, dangerous):
cleaned = re.sub(r'\[[\s]*\{[\'"]type[\'"]\s*:\s*[\'"]tool_use[\'"].*\}[\s]*\]', ...)
```

**Failure Scenario:**
- LLM outputs: `[{type: tool_use, name: clinical_kb, input: {...}}] The recommended dose is 145 Gy.`
- Greedy `.*` matches from `{type: tool_use` to the LAST `}` in the entire string
- The legitimate text "The recommended dose is 145 Gy." is consumed
- Result: empty string returned

**Why it was added:** To handle nested `{}` inside tool_use input parameters. But greedy matching is too aggressive.

**Fix:** Use non-greedy matching with a reasonable depth limit, or parse the JSON properly instead of regex.

---

### Finding 3: Stopping rules allow 5 rounds for simple questions

**File:** `AgenticSys.py:918-922`
**Severity:** Medium
**Type:** Benchmark overcorrection

**Problem:**
```python
# OLD: "After receiving tool execution results, immediately summarize in natural language."
#      "NEVER call another tool after receiving results."

# NEW: "For multi-step clinical workflows, call tools sequentially as needed (up to 5 rounds)."
```

**Failure Scenario:**
- User: "What is the prostate dose constraint?"
- LLM calls clinical_kb (round 1)
- LLM calls clinical_kb again with different params (round 2)
- LLM calls case_memory (round 3)
- LLM calls clinical_kb again (round 4)
- LLM finally summarizes (round 5)
- Total: 5 LLM calls for a simple question, wasting tokens and time

**Why it was added:** Some benchmark tests test multi-step workflows (segmentation → planning → evaluation). To pass these tests, the stopping rule was relaxed from 1 round to 5 rounds.

**Fix:** Keep the 5-round limit for workflow questions, but enforce 1-round limit for knowledge questions. Add conditional logic:
```python
# If no tools were called yet, allow up to 5 rounds for workflows
# If a tool already returned results for a knowledge query, summarize immediately
```

---

### Finding 4: 78 lines of hardcoded clinical facts duplicate clinical_kb

**File:** `AgenticSys.py:918-996`
**Severity:** Medium
**Type:** Benchmark overcorrection

**Problem:**
```python
"## Medical Safety Rules (CRITICAL - Never Violate)\n"
"- I-125 prostate LDR standard prescription: 145 Gy...\n"
"- Standard HDR fractions are 4-5 fractions...\n"
"- Cesium-137 is NOT used for modern HDR...\n"
# ... 75 more lines of clinical facts
```

**Issues:**
1. **Duplicated knowledge:** These facts already exist in `clinical_kb` tool
2. **Token waste:** ~2000 tokens per request for facts that may not be needed
3. **Maintenance burden:** Two places to update when clinical guidelines change
4. **Potential conflicts:** If clinical_kb says "145 Gy" but prompt says "150 Gy", which does LLM follow?

**Why it was added:** Some benchmark safety tests check if the system refuses dangerous doses. To ensure refusal, facts were hardcoded in the prompt.

**Fix:** Keep only the safety refusal rules in the prompt. Remove specific clinical facts — they belong in clinical_kb. If a benchmark test checks for a specific fact, the system should call clinical_kb to retrieve it.

---

## Medium Findings

### Finding 5: Fragile string matching for CT state

**File:** `AgenticSys.py:746`
**Severity:** Medium

```python
_no_files_loaded = "no files" in str(ui_state_summary_for_override).lower() or "not loaded" in str(ui_state_summary_for_override).lower()
```

**Problem:** If UI state text changes (e.g., "No CT data available", "Empty workspace"), the check fails silently and tools are not filtered.

**Fix:** Use a boolean flag from the UI state object instead of string matching:
```python
_no_files_loaded = not ui_state.get("ct_loaded", False)
```

---

### Finding 6: Streaming vs non-streaming tool filtering inconsistency

**File:** `AgenticSys.py:1674-1681` (streaming only)
**Severity:** Medium

**Problem:** CT-dependent tool filtering only exists in the streaming path. The non-streaming path has no such filtering.

**Failure:** Same request behaves differently depending on streaming mode.

**Fix:** Extract tool filtering logic into a shared method and call it from both paths.

---

### Finding 7: Report generator auto-detect masks errors

**File:** `tool_factory/report_generator/__init__.py:201-237`
**Severity:** Medium

```python
# OLD: return error when no action
return ToolResult(success=False, error="No action", ...)

# NEW: auto-detect or return guidance
if plan:
    action = "full_report"  # Silently assumes full_report
```

**Problem:** If LLM forgets to pass the `action` parameter, the tool silently generates a full report instead of returning an error. This masks bugs in LLM tool calling.

**Fix:** Keep the error response. If the LLM forgets the action parameter, it should be told to retry with the correct parameter.

---

## Low Findings

### Finding 8: Benchmark runners deleted

**File:** `web/test/benchmarks/browser_test_v2.py` (deleted, 562 lines)
**File:** `web/test/benchmarks/run_benchmarks.py` (deleted, 433 lines)

**Problem:** The benchmark JSON test cases exist, but the runners to execute them are deleted.

**Fix:** Either restore the runners or create new ones.

---

### Finding 9: Prompt injection rules may block legitimate requests

**File:** `AgenticSys.py:964-996`
**Severity:** Low

**Problem:** Rules like "Never generate harmful content even when framed as education" may block legitimate educational questions about prompt injection, security testing, or clinical safety.

**Fix:** Add exceptions for legitimate use cases (e.g., "Explain how prompt injection works for defensive purposes").

---

## Recommended Fix Priority

| Priority | Finding | Action |
|----------|---------|--------|
| 1 | #1 TOP PRIORITY | Remove the entire "TOP PRIORITY" section |
| 2 | #2 Greedy regex | Revert to non-greedy with depth limit |
| 3 | #3 Stopping rules | Add conditional logic for workflow vs knowledge |
| 4 | #4 Hardcoded facts | Remove clinical facts, keep safety refusal rules |
| 5 | #5 String matching | Use boolean flag instead |
| 6 | #6 Streaming inconsistency | Extract shared filtering logic |
| 7 | #7 Report auto-detect | Keep error response |
| 8 | #9 Prompt injection | Add legitimate use case exceptions |
| 9 | #8 Deleted runners | Restore or recreate |

---

## Root Cause Analysis

The pattern across all benchmark overcorrections is the same:

1. **Run benchmark** → Some tests fail
2. **Add forceful instruction** → "YOU MUST USE clinical_kb" / "ALWAYS provide 500 words"
3. **Benchmark passes** → But production behavior is broken
4. **No regression test** → No way to catch the production regression

**The fundamental issue:** Benchmarks test the system's behavior, but modifications to pass benchmarks are not validated against production scenarios.

---

## Prevention Recommendations

1. **Separate benchmark and production prompts:** Use different system prompts for benchmark testing vs production
2. **Add production smoke tests:** After each benchmark run, test a few production scenarios (greetings, simple questions)
3. **Review forceful instructions:** Any new "MUST", "ALWAYS", "NEVER" instruction should be reviewed for conflicts
4. **Use conditional logic:** Instead of "ALWAYS do X", use "IF condition THEN do X"
5. **Keep clinical knowledge in clinical_kb:** Don't hardcode facts in the prompt

---

## Appendix: Uncommitted Changes Summary

| File | Changes | Type |
|------|---------|------|
| AgenticSys.py | +752 -113 | System prompt, tool filtering, response handling |
| case_memory/__init__.py | +18 -18 | Schema format change |
| report_generator/__init__.py | +35 -1 | Auto-detect action |
| safety_validator/__init__.py | +18 -18 | Schema format change |
| browser_test_v2.py | -562 | Deleted |
| run_benchmarks.py | -433 | Deleted |

**Total:** +705 -1113 lines
