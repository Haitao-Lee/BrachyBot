# Sub-Agent Workflow Improvement Report
**Date**: 2026-06-27  
**Author**: Main Agent (with sub-agent verification)

## Executive Summary

Implemented intelligent claim extraction for FactChecker to improve source reliability verification. The main agent now prepares targeted input for sub-agents instead of blindly passing raw data.

---

## 1. Problem Statement

### Original Issue
FactChecker was receiving the first 2-3 sentences of search results as claims to verify, regardless of their importance. This led to:
- Missing critical factual errors buried in the text
- Wasting verification effort on trivial statements
- Not prioritizing suspicious assertions that match hallucination patterns

### User's Insight
> "主 agent 知道下一步要调用哪个子 agent，因此可以从'让子 agent 决策更准确'的角度，主动整理最相关的输入。"

The main agent should intelligently prepare input for each sub-agent based on what that sub-agent needs to make accurate decisions.

---

## 2. Implementation

### New Method: `_prepare_fact_check_brief()`
**Location**: `AgenticSys.py:3265-3359`

**Priority Order** (highest to lowest):
1. **Suspicious assertions** - Matches FactChecker's hallucination patterns
   - "According to a study we conducted..."
   - "We found that..."
   - Placeholder journals/institutions
   
2. **Clinical guideline references** - High-stakes factual claims
   - NCCN, AAPM, ASTRO, ICRU, WHO, ESTRO guidelines
   - Must be verified for accuracy
   
3. **Literature citations** - Verifiable references
   - PMID numbers
   - Study IDs/trial names
   
4. **Numerical claims** - Dose metrics and percentages
   - V100 > 95%, D90 = 145 Gy
   - Prescription doses
   
5. **Fallback** - Key factual statements with clinical data
   - Only if < 3 claims extracted so far

**Constraints**:
- Maximum 7 claims to avoid overwhelming FactChecker
- Deduplication to prevent redundant verification
- Edge case handling (empty text, generic text, very long text)

### Integration
**Location**: `AgenticSys.py:3361-3404`

Modified `_check_search_reliability()` to:
1. Call `_prepare_fact_check_brief()` instead of blindly taking first sentences
2. Return original text if no claims extracted
3. Maintain existing error handling and fallback behavior

---

## 3. Testing Results

### Test 1: Priority Verification
```
Input: Medical text with suspicious assertion, guidelines, PMID, numerical claims
Output: 5 claims in correct priority order
✅ Suspicious assertion extracted first
✅ NCCN guideline extracted
✅ PMID extracted
✅ Numerical claim extracted
```

### Test 2: Edge Cases
```
✅ Empty text → returns empty list
✅ Generic text (no extractable claims) → returns empty list
✅ Very long text → capped at 7 claims
```

### Test 3: Integration
```
✅ Syntax check passed
✅ Full workflow test passed
✅ Error handling verified
```

---

## 4. Workflow Analysis

### Current Sub-Agent Calls

| Sub-Agent | Trigger | Input Preparation | Status |
|-----------|---------|-------------------|--------|
| **FactChecker** | After web_search/web_fetch | `_prepare_fact_check_brief()` | ✅ **IMPROVED** |
| **PlanReviewer** | After planning pipeline | Direct metrics/config pass | ✅ OK |
| **CompletenessChecker** | After response generation | Full message/response/steps | ✅ OK |
| **Router** | Before tool execution | Raw message | ✅ OK (routing doesn't need prep) |

### Identified Issues

#### Issue 1: Duplicate AAPM in Guideline List
**Location**: `AgenticSys.py:3299`  
**Fix**: Removed duplicate 'AAPM' entry  
**Status**: ✅ **FIXED**

#### Issue 2: skip_distill=True in Sync Context
**Location**: `AgenticSys.py:3395`  
**Description**: FactChecker call uses `skip_distill=True` to avoid nested event loops  
**Impact**: FactChecker receives raw claims without LLM-distilled context  
**Status**: ⚠️ **ACCEPTED** (intentional design tradeoff for sync compatibility)

#### Issue 3: Global Context Noise
**Description**: Orchestrator passes entire `_global_context` to all sub-agents  
**Impact**: Minimal - sub-agents only use relevant fields  
**Status**: ℹ️ **NO ACTION** (not a practical issue)

---

## 5. Remaining Workflow Concerns

### 5.1 No Feedback Loop
**Issue**: If FactChecker flags something as suspicious, there's no mechanism to:
- Log for future improvement
- Adjust source confidence
- Trigger re-search with different keywords

**Current Mitigation**: FactChecker's note is appended to result, LLM can decide what to do  
**Recommendation**: Monitor usage patterns; add feedback mechanism if needed

### 5.2 Limited to FactChecker
**Issue**: Only FactChecker has intelligent preparation  
**Analysis**: 
- PlanReviewer already gets structured metrics (appropriate)
- CompletenessChecker needs full response (appropriate)
- Router analyzes raw message (appropriate)

**Conclusion**: No other sub-agents need similar preparation at this time

### 5.3 Async Context Distillation Unused
**Issue**: `_distill_context()` exists but is only used in async contexts  
**Current Usage**: All practical calls use `skip_distill=True`  
**Impact**: Missing opportunity for LLM-powered context refinement  
**Recommendation**: Consider enabling distillation in async workflows if performance allows

---

## 6. Architecture Validation

### Workflow Diagram
```
User Message
    ↓
BrachyAgent (Main Agent)
    ↓
Tool Execution (e.g., web_search)
    ↓
_check_search_reliability()
    ↓
_prepare_fact_check_brief() [NEW]
    ↓
Extract intelligent claims (max 7, prioritized)
    ↓
multi_agent_wrapper.review_facts_append()
    ↓
Orchestrator → FactChecker
    ↓
FactChecker reviews claims
    ↓
Append reliability note to result
    ↓
Continue to next step / return to user
```

### Design Principles Applied
1. ✅ **Main agent as decision maker**: BrachyAgent decides what to send to sub-agents
2. ✅ **Sub-agents as advisors**: FactChecker provides verification, doesn't block
3. ✅ **Intelligent preparation**: Claims are prioritized and filtered
4. ✅ **Robust error handling**: Failures don't break the workflow
5. ✅ **Bounded complexity**: Max 7 claims, deduplication, edge case handling

---

## 7. Recommendations

### Immediate (Done)
- ✅ Implement `_prepare_fact_check_brief()`
- ✅ Fix duplicate AAPM
- ✅ Test and verify

### Short-term (Monitor)
- Track FactChecker effectiveness with new claim extraction
- Monitor if 7-claim limit is appropriate
- Collect feedback on false positive/negative rates

### Long-term (If Needed)
- Add feedback loop for suspicious claims
- Enable context distillation in async workflows
- Consider similar preparation for other sub-agents if use cases emerge

---

## 8. Conclusion

The sub-agent workflow has been improved with intelligent claim extraction for FactChecker. The main agent now prepares targeted input based on what the sub-agent needs, following the principle that "主 agent 知道下一步要调用哪个子 agent，因此可以从'让子 agent 决策更准确'的角度，主动整理最相关的输入。"

**Key Achievements**:
1. FactChecker receives prioritized, relevant claims
2. Suspicious assertions are flagged first
3. Clinical guidelines and citations are extracted
4. Robust error handling maintained
5. Edge cases handled correctly

**No Critical Issues Remaining**: The workflow is solid, with only minor optimization opportunities for the future.

---

## Appendix: Code Changes Summary

### Modified Files
- `AgenticSys.py`: Added `_prepare_fact_check_brief()` method (95 lines)
- `AgenticSys.py`: Modified `_check_search_reliability()` to use new method (5 lines changed)
- `AgenticSys.py`: Fixed duplicate AAPM in guideline list (1 line)

### Test Coverage
- Priority order verification
- Edge case handling (empty, generic, long text)
- Integration with existing workflow
- Error handling validation

### Backward Compatibility
- ✅ No breaking changes
- ✅ Existing behavior preserved when no claims extracted
- ✅ Error handling unchanged
