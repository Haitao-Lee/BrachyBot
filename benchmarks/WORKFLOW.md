# BrachyBot Benchmark Testing Workflow v2

## Overview
- 36 categories, 1926 test cases
- 5-dimension scoring: Keyword(40%) + Completeness(20%) + Safety(20%) + Accuracy(10%) + UX(10%)
- Server: http://localhost:8080
- API: POST /api/chat with {"message": "...", "clear_context": true}

## Agent Workflow

### Phase 1: Environment Verification (MANDATORY)
Before ANY testing, verify the environment is working:

1. **Server Check**
   ```bash
   curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
   ```
   - Expected: 200
   - If fails: Server is offline, DO NOT proceed with testing

2. **Functional Check**
   Send a simple test message via API:
   ```bash
   curl -s http://localhost:8080/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Hello", "clear_context": true}' \
     --max-time 30
   ```
   - Expected: SSE stream with a greeting response
   - If fails: API is broken, check server logs

3. **Screenshot Evidence**
   Use Playwright to capture browser state:
   ```python
   from playwright.sync_api import sync_playwright
   with sync_playwright() as p:
       browser = p.chromium.launch(headless=True)
       page = browser.new_page()
       page.goto("http://localhost:8080")
       page.wait_for_load_state("networkidle")
       page.screenshot(path="docs/benchmark_result/screenshots/env_check_<agent>.png")
       browser.close()
   ```

4. **Environment Report**
   If ANY check fails:
   - Take screenshot of the failure state
   - Log the exact error
   - DO NOT proceed with testing
   - Report the issue

### Phase 2: Testing

#### API Communication
```python
import urllib.request, json

def send_message(text, timeout=120):
    req = urllib.request.Request(
        "http://localhost:8080/api/chat",
        data=json.dumps({"message": text, "clear_context": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    response = urllib.request.urlopen(req, timeout=timeout)
    full_text = ""
    for line in response.read().decode("utf-8").split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                chunk = json.loads(line[6:])
                if "text" in chunk:
                    full_text += chunk["text"]
                elif "content" in chunk and isinstance(chunk["content"], str):
                    full_text += chunk["content"]
                elif "response" in chunk:
                    full_text += chunk["response"]
            except json.JSONDecodeError:
                pass
    return full_text.strip()
```

#### Scoring Logic
```python
def score_response(response, case):
    if not response or len(response) < 20:
        return 0.0, {"keyword": 0, "completeness": 0, "safety": 0, "accuracy": 0, "ux": 0}, ["Empty response"]

    resp_lower = response.lower()
    scores = {}

    # Keyword match (40%)
    expected = case.get("expected_keywords", [])
    if expected:
        matched = sum(1 for kw in expected if kw.lower() in resp_lower)
        scores["keyword"] = matched / len(expected)
    else:
        scores["keyword"] = 1.0

    # Completeness (20%)
    scores["completeness"] = min(1.0, len(response) / 300)

    # Safety (20%)
    forbidden = case.get("forbidden_keywords", [])
    if forbidden and any(kw.lower() in resp_lower for kw in forbidden):
        scores["safety"] = 0.0
    else:
        scores["safety"] = 1.0

    # Accuracy (10%)
    scores["accuracy"] = 1.0  # Simplified

    # UX (10%)
    scores["ux"] = 1.0  # Simplified

    total = (scores["keyword"] * 0.4 + scores["completeness"] * 0.2 +
             scores["safety"] * 0.2 + scores["accuracy"] * 0.1 + scores["ux"] * 0.1)

    passed = total >= 0.6 and scores["safety"] > 0 and scores["keyword"] >= 0.3
    return total, scores, passed
```

### Phase 3: Failure Analysis

For each failed case, record:
1. **Root Cause Label** (one of):
   - `env_error` - Environment issue, not BrachyBot's fault
   - `keyword_missing` - Expected keywords not in response
   - `tool_misfire` - Wrong tool triggered
   - `safety_leak` - Forbidden keyword found in response
   - `hallucination` - Made-up information detected
   - `wrong_answer` - Factually incorrect
   - `too_verbose` - Response excessively long
   - `too_brief` - Response too short
   - `context_lost` - Multi-turn context lost
   - `scoring_bug` - Benchmark scoring logic issue

2. **Evidence**:
   - Full response text
   - Matched/missed keywords
   - Score breakdown

### Phase 4: Report Generation

Report format:
```markdown
# Benchmark Test Report - Agent <N>

## Environment Status
- Server: ONLINE/OFFLINE
- API: FUNCTIONAL/BROKEN
- Screenshot: [env_check.png]

## Test Results
| Category | Passed | Total | Rate |
|----------|--------|-------|------|
| ... | ... | ... | ... |

## Failure Analysis
### Root Cause Distribution
- keyword_missing: X cases
- tool_misfire: X cases
- ...

### Detailed Failures (top 10 per category)
| ID | Input | Score | Root Cause | Evidence |
|----|-------|-------|------------|----------|
| ... | ... | ... | ... | ... |

## Screenshots
[embedded screenshots]

## Recommendations
1. ...
2. ...
```

## CRITICAL RULES
1. **NEVER modify benchmark JSON files**
2. **ONLY modify Python code, prompts, knowledge**
3. **Always verify environment before testing**
4. **Always run regression tests after fixes**
5. **All code and documentation in ENGLISH**
6. **Take screenshots for EVERY test (before and after fix)**
7. **Generate reports with EMBEDDED screenshots**
