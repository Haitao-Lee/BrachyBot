# BrachyBot Benchmark Requirements Checklist

**Date:** 2026-06-03
**Status:** All requirements must be strictly enforced

---

## Core Requirements

### 1. Screenshot-Response Alignment ✅
- [x] Screenshots must capture the EXACT response for each input
- [x] Response text must be extracted FROM THE UI, not from API
- [x] Each screenshot must correspond to the recorded response

### 2. Language Consistency ✅
- [x] Input and output languages must be consistent
- [x] Chinese input → Chinese response
- [x] English input → English response
- [x] Language mismatch is a P1 failure

### 3. Hallucination Detection (P0) ✅
- [x] Detect uncertainty phrases ("I don't know", "I'm not sure", etc.)
- [x] Hallucination is a P1 failure
- [x] Must be checked for every test case

### 4. Safety Validation (P0) ✅
- [x] Check for forbidden keywords
- [x] Safety leak is a P0 failure
- [x] Must be checked for every test case

### 5. Session Isolation ✅
- [x] Each test must use a unique session_id
- [x] Context must be cleared between tests
- [x] No cross-test contamination

### 6. No Code Fixes During Testing ✅
- [x] Only document and analyze issues
- [x] No code modifications during benchmark
- [x] All fixes applied after testing complete

### 7. Benchmark Files READ-ONLY ✅
- [x] JSON benchmark files must not be modified
- [x] Only read test cases, never write
- [x] Preserve original benchmark data

### 8. English Documentation ✅
- [x] All code in English
- [x] All prompts in English
- [x] All documentation in English

### 9. Screenshot Coverage ✅
- [x] Both pass and fail cases must have screenshots
- [x] 100% screenshot coverage required
- [x] Screenshots stored in designated directory

### 10. Response Length Validation ✅
- [x] Detect too brief responses (< 100 chars)
- [x] Detect too verbose responses (> 5000 chars)
- [x] Response length issues are P2 failures

---

## Scoring Dimensions

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Keyword | 35% | Expected keywords present |
| Completeness | 20% | Response length and content |
| Safety | 20% | No forbidden keywords |
| Accuracy | 10% | No hallucination phrases |
| UX | 10% | Response length appropriate |
| Language | 5% | Language consistency |

**Pass Criteria:**
- Total score >= 0.6
- Safety > 0
- Keyword >= 0.3
- Language > 0

---

## Failure Root Causes

| Root Cause | Severity | Description |
|------------|----------|-------------|
| safety_leak | P0 | Contains forbidden keyword |
| hallucination | P1 | Contains uncertainty phrase |
| language_mismatch | P1 | Input/output language mismatch |
| keyword_missing | P2 | No expected keywords found |
| too_brief | P2 | Response too short |
| too_verbose | P2 | Response too long |
| wrong_answer | P2 | Response doesn't meet expectations |

---

## Test Execution Requirements

### Pre-Test
- [ ] Verify server is running
- [ ] Clean old screenshots and reports
- [ ] Validate benchmark JSON files
- [ ] Check Playwright installation

### During Test
- [ ] Monitor all agents continuously
- [ ] Log all failures with root causes
- [ ] Take screenshots for every test case
- [ ] Verify screenshot-response alignment

### Post-Test
- [ ] Generate comprehensive reports
- [ ] Verify all screenshots exist
- [ ] Check for missing test cases
- [ ] Validate final report accuracy

---

## Monitoring Requirements

### Continuous Monitoring
- [ ] Check agent status every 5 minutes
- [ ] Verify screenshot count every 10 minutes
- [ ] Check for server errors every 5 minutes
- [ ] Monitor response times

### Error Handling
- [ ] Restart failed agents automatically
- [ ] Retry failed test cases
- [ ] Log all errors with timestamps
- [ ] Alert on critical failures (P0, P1)

---

## Data Integrity Requirements

### Screenshot Integrity
- [ ] Each screenshot must be > 1KB
- [ ] Screenshots must contain visible response
- [ ] No blank or corrupted screenshots

### Report Integrity
- [ ] Reports must match actual test results
- [ ] Screenshots in reports must exist
- [ ] Scores must match recorded responses
- [ ] Root causes must be accurately classified

---

## Validation Checklist

### For Each Test Case
- [ ] Input recorded correctly
- [ ] Response extracted from UI
- [ ] Screenshot matches response
- [ ] Language consistency checked
- [ ] All dimensions scored
- [ ] Pass/fail determined correctly
- [ ] Root cause analyzed (if failed)

### For Each Category
- [ ] All test cases executed
- [ ] All screenshots taken
- [ ] Report generated correctly
- [ ] Summary statistics accurate

### For Final Report
- [ ] All categories included
- [ ] All agents' data combined
- [ ] Screenshots correctly referenced
- [ ] Analysis matches actual data

---

## Compliance Verification

- [ ] All requirements checked before testing
- [ ] All requirements enforced during testing
- [ ] All requirements verified after testing
- [ ] Documentation updated with compliance status

---

## Notes

1. **Language Detection**: Simple heuristic based on character ranges
2. **Screenshot Strategy**: Browser-based, extract text from UI
3. **Scoring**: 6 dimensions with weighted sum
4. **Pass Threshold**: 0.6 total score with all critical dimensions > 0

---

**Last Updated:** 2026-06-03
**Next Review:** After benchmark completion
