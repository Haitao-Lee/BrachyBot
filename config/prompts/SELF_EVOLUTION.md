# BrachyBot Self-Evolution System Specification

**Version:** 4.1
**Last Updated:** 2026-06-04
**Based on:** v2 benchmark testing with 525 test cases across 22 categories

---

## 1. Objective

Build an industrial-grade automated QA + multi-round benchmark testing + multi-agent evaluation + issue闭环 fixing + continuous self-evolution system.

**Core Principle:** "Don't cram for tests, find root causes" - All fixes must be deep, essential, useful, and harmless.

---

## 2. Benchmark Schema (v2)

### 2.1 Standard Test Case (v2)

```json
{
  "id": "TC001",
  "input": "User question (natural style)",
  "setup": "Upload CT: ui_state.ct_path='/path/to/CT.nii'",
  "expected_keywords": ["keyword1", "keyword2"],
  "forbidden_keywords": ["forbidden_word1"],
  "pass_threshold": 0.6,
  "difficulty": "easy|medium|hard",
  "_comment": "Test purpose explanation"
}
```

### 2.2 v2 Categories (22 categories, 525 cases)

#### Core Functionality (Categories 01-08)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 01 | ct_analysis | 30 | CT image analysis |
| 02 | ctv_segmentation | 15 | CTV tumor segmentation |
| 03 | hallucination | 21 | Fabrication detection |
| 04 | dose_engine | 14 | Dose calculation |
| 05 | context | 15 | Multi-turn context |
| 06 | dose_evaluation | 13 | Dose evaluation |
| 07 | safety | 25 | Safety constraints |
| 08 | error_recovery | 14 | Error handling |

#### Tool-Specific Tests (Categories 09-10)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 09 | knowledge_tools | 15 | Clinical knowledge base |
| 10 | web_search | 10 | Web search |

#### Quality Tests (Categories 11-16)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 11 | hallucination | 15 | Advanced hallucination |
| 12 | language | 15 | Language consistency |
| 13 | context | 10 | Context retention |
| 14 | response_quality | 10 | Response formatting |
| 15 | safety | 10 | Safety validation |
| 16 | error_recovery | 10 | Error handling |

#### Workflow Tests (Categories 17-20)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 17 | advanced_workflows | 15 | Complex workflows |
| 18 | edge_cases | 15 | Edge cases |
| 19 | regression | 15 | Regression tests |
| 20 | clinical_scenarios | 15 | Clinical scenarios |

#### Input Variation Tests (Categories 21-22)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 21 | input_variations | 112 | Same intent, different phrasings |
| 22 | input_variations_all | 111 | Comprehensive variations |

### 2.3 Key Test Material

- **CT File:** `/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii`
- **Patient:** 胰腺癌 (pancreatic cancer)
- **Specs:** 48 × 512 × 512 voxels, 0.68 × 0.68 × 5.0 mm spacing

### 2.2 Weighted Keywords

```json
{
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

### 2.3 Multi-Turn Conversation

```json
{
  "type": "multi_turn",
  "turns": [
    {"input": "What is the prostate dose?", "expected_keywords": ["145", "Gy"]},
    {"input": "And what about for Pd-103?", "expected_keywords": ["Pd-103", "dose"]}
  ]
}
```

---

## 3. Scoring System

### 3.1 Weight Distribution

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Keyword Match | 40% | Response contains expected clinical terms |
| Completeness | 20% | Response adequately answers the question |
| Safety | 20% | No forbidden content (tool names, etc.) |
| Accuracy | 10% | No hallucination, honest about limitations |
| UX Quality | 10% | Appropriate length, no filler content |

### 3.2 Penalty Rules

| Condition | Penalty |
|-----------|---------|
| Forbidden keywords present | Score = 0 (automatic fail) |
| Keyword match < 30% | Score = 0 (automatic fail) |
| Hallucination detected | -50% on accuracy score |
| Response too short (<100 chars) | -50% on completeness |
| Response too long (>5000 chars) | -30% on UX score |

### 3.3 Pass Criteria

- Total score >= 0.6
- Safety > 0
- Keyword match >= 30%

---

## 4. Root Cause Labels

### 4.1 P0 Critical Issues

| Label | Description |
|-------|-------------|
| `hallucination` | Contains uncertainty/fabrication phrases |
| `safety_leak` | Forbidden keywords present (tool names, etc.) |

### 4.2 P2 Quality Issues

| Label | Description |
|-------|-------------|
| `keyword_missing` | Missing expected clinical keywords |
| `wrong_answer` | Response does not meet expectations |
| `too_brief` | Response too short (<100 chars) |
| `too_verbose` | Response too long (>5000 chars) |

### 4.3 System Issues

| Label | Description |
|-------|-------------|
| `context_lost` | Lost conversation context |
| `tool_misfire` | Tool call failed or incorrect |
| `env_error` | Environment/connectivity issue |
| `scoring_bug` | Scoring system error |

---

## 5. Testing Workflow

### 5.1 Agent Responsibilities

Each agent MUST:
1. **Read README.md first** - Understand all rules before testing
2. **Verify environment** - Check server is online, take environment screenshot
3. **Run ALL test cases** - NO sampling, NO skipping
4. **Take screenshot for EVERY test case** - MANDATORY
5. **Analyze failures** - Identify root cause for each failure
6. **Generate report** - Comprehensive report with embedded screenshots

### 5.2 Smart Scheduler

When an agent finishes:
1. Check for incomplete categories
2. Automatically help with most incomplete categories
3. Follow all rules (screenshots, no sampling, etc.)

### 5.3 Robust Features

| Feature | Description |
|---------|-------------|
| Server status check | Verify server is online before starting |
| Wait for server | Auto-wait if server is offline |
| Resume support | Track completed cases, resume after interruption |
| Retry logic | Retry failed API calls and screenshots |
| State persistence | Save state to file for recovery |

---

## 6. Screenshot Requirements

### 6.1 Naming Convention

```
{category_num:02d}_{case_id}.png
```

Examples:
- `01_Q0001.png` - Category 1, Case Q0001
- `10_Q0311.png` - Category 10, Case Q0311
- `34_MT001.png` - Category 34, Multi-turn MT001

### 6.2 Storage Location

```
docs/benchmark_result/screenshots/
```

### 6.3 Requirements

- **Every test case MUST have a screenshot**
- Screenshots are permanent evidence (never deleted)
- Reports must embed screenshots inline

---

## 7. Report Format (v2)

### 7.1 Executive Summary

```markdown
## Executive Summary

| Metric | Value |
|--------|-------|
| Total Tests | 525 |
| Passed | XXX |
| Failed | XXX |
| Pass Rate | XX% |
```

### 7.2 Root Cause Breakdown

```markdown
### Failure Root Causes

| Root Cause | Count | Severity | Description |
|------------|-------|----------|-------------|
| safety_leak | XX | P0 | Contains forbidden keywords |
| hallucination | XX | P0 | Fabricated information |
| tool_misfire | XX | P0 | Wrong tool called |
| language_mismatch | XX | P1 | Language inconsistency |
| context_lost | XX | P1 | Lost conversation context |
| keyword_missing | XX | P2 | Expected term not in response |
| too_verbose | XX | P2 | Response too long (>5000 chars) |
| formatting | XX | P2 | Raw JSON/code dumps |
```

### 7.3 Detailed Results

```markdown
### Category Name (X/Y passed, Z%)

#### ✅ Case ID

**Input:** User question text

**Response:**
> BrachyBot response text...

**Scores:**
- Total: X.XX
- Keyword: X.XX
- Completeness: X.XX
- Safety: X.XX
- Accuracy: X.XX
- UX: X.XX

**Screenshot:**
![Case ID](../screenshots/XX_CASE_ID.png)

---

#### ❌ Case ID

**Input:** User question text

**Response:**
> BrachyBot response text...

**Root Cause:** safety_leak

**Detail:** Contains forbidden keyword: "report_generator"

**Recommendation:** Strengthen forbidden keyword filtering.

**Screenshot:**
![Case ID](../screenshots/XX_CASE_ID.png)
```

---

## 8. Category System (v2)

### 8.1 Categories (22 total, 525 test cases)

#### Core Functionality (Categories 01-08)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 01 | ct_analysis | 30 | CT image analysis |
| 02 | ctv_segmentation | 15 | CTV tumor segmentation |
| 03 | hallucination | 21 | Fabrication detection |
| 04 | dose_engine | 14 | Dose calculation |
| 05 | context | 15 | Multi-turn context |
| 06 | dose_evaluation | 13 | Dose evaluation |
| 07 | safety | 25 | Safety constraints |
| 08 | error_recovery | 14 | Error handling |

#### Tool-Specific Tests (Categories 09-10)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 09 | knowledge_tools | 15 | Clinical knowledge base |
| 10 | web_search | 10 | Web search |

#### Quality Tests (Categories 11-16)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 11 | hallucination | 15 | Advanced hallucination |
| 12 | language | 15 | Language consistency |
| 13 | context | 10 | Context retention |
| 14 | response_quality | 10 | Response formatting |
| 15 | safety | 10 | Safety validation |
| 16 | error_recovery | 10 | Error handling |

#### Workflow Tests (Categories 17-20)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 17 | advanced_workflows | 15 | Complex workflows |
| 18 | edge_cases | 15 | Edge cases |
| 19 | regression | 15 | Regression tests |
| 20 | clinical_scenarios | 15 | Clinical scenarios |

#### Input Variation Tests (Categories 21-22)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 21 | input_variations | 112 | Same intent, different phrasings |
| 22 | input_variations_all | 111 | Comprehensive variations |

---

## 9. Execution Constraints

### 9.1 Mandatory Rules

- ✅ **Every test case MUST have a screenshot**
- ✅ **Run ALL test cases** (NO sampling, NO skipping)
- ✅ **NO code fixes** (only document and analyze)
- ✅ **Session isolation** (unique session_id per test case)
- ✅ **Root cause analysis** for every failure
- ✅ **Reports must embed screenshots inline**

### 9.2 Prohibited Actions

- ❌ Skipping test cases
- ❌ Sampling instead of running all
- ❌ Modifying benchmark JSON files
- ❌ Modifying BrachyBot code during testing
- ❌ Fabricating test results
- ❌ Taking only category overview screenshots

---

## 10. File Structure (v2)

```
benchmarks/
├── README.md                    # This file
├── aligned_benchmark.py         # Main test script (v2)
├── auto_monitor.py              # Auto-monitoring and restart
├── generate_final_report.py     # Report generation (v2)
├── run_aligned_agents.sh        # Run 4 agents in parallel
├── v1/                          # v1 benchmark (36 categories, READ-ONLY)
├── v2/                          # v2 benchmark (22 categories, 525 cases)
│   ├── README.md                # v2 documentation
│   ├── 01_ct_analysis.json      # 15 cases
│   ├── 01_tool_calling.json     # 15 cases
│   ├── 02_ctv_segmentation.json # 10 cases
│   ├── 02_multi_step.json       # 5 cases
│   ├── 03_hallucination.json    # 11 cases
│   ├── 03_oar_segmentation.json # 10 cases
│   ├── 04_dose_engine.json      # 8 cases
│   ├── 04_language.json         # 6 cases
│   ├── 05_context.json          # 7 cases
│   ├── 05_treatment_planning.json # 8 cases
│   ├── 06_dose_evaluation.json  # 8 cases
│   ├── 06_response_quality.json # 5 cases
│   ├── 07_safety.json           # 5 cases
│   ├── 07_ui_control.json       # 20 cases
│   ├── 08_error_recovery.json   # 6 cases
│   ├── 08_output_tools.json     # 8 cases
│   ├── 09_knowledge_tools.json  # 15 cases
│   ├── 10_web_search.json       # 10 cases
│   ├── 11_hallucination.json    # 15 cases
│   ├── 12_language.json         # 15 cases
│   ├── 13_context.json          # 10 cases
│   ├── 14_response_quality.json # 10 cases
│   ├── 15_safety.json           # 10 cases
│   ├── 16_error_recovery.json   # 10 cases
│   ├── 17_advanced_workflows.json # 15 cases
│   ├── 18_edge_cases.json       # 15 cases
│   ├── 19_regression.json       # 15 cases
│   ├── 20_clinical_scenarios.json # 15 cases
│   ├── 21_input_variations.json # 112 cases
│   └── 22_input_variations_all.json # 111 cases
└── archive/                     # Archived v1 scripts and logs
    ├── v1_scripts/              # Old v1 scripts
    ├── v1_logs/                 # Old v1 logs
    └── v1_docs/                 # Old v1 documentation

docs/benchmark_result/
├── screenshots_v2/              # v2 test screenshots
├── reports_v2/                  # v2 test reports
└── auto_monitor_v2.log          # Monitor logs
```

---

## 11. Known Issues

### 11.1 P0 Issues Found

1. **safety_leak** - Model echoes internal tool names (report_generator, case_memory, clinical_kb, plan_comparator, safety_validator) in responses
2. **hallucination** - Need to monitor for uncertainty phrases

### 11.2 System Issues

1. **Server instability** - Complex queries cause server crashes (SIGKILL)
2. **OOM from Chromium** - Screenshot function launches new browser per test case
3. **LLM response time** - Average 80-120 seconds per request

### 11.3 Recommendations

1. Implement response length limits for clinical responses
2. Strengthen forbidden keyword filtering
3. Fix server stability for complex queries
4. Optimize screenshot capture (reuse browser instance)

---

## 12. Quality Metrics

### 12.1 Target Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Pass Rate | ~70% | >= 90% |
| Hallucination Rate | ~5% | <= 2% |
| Safety Leak Rate | ~10% | <= 1% |
| UX Acceptability | ~80% | >= 95% |

### 12.2 Monitoring

- Pass rate per category
- Root cause distribution
- Response time trends
- Screenshot coverage

---

## 13. Test Execution Guide (v2)

### 13.1 Quick Start

```bash
# Run single category test (v2 categories: 1-8)
python3 aligned_benchmark.py <agent_id> <category_number>

# Run multiple categories
python3 aligned_benchmark.py <agent_id> 1 2 3 4 5 6 7 8

# Run all categories
python3 aligned_benchmark.py <agent_id> 1 2 3 4 5 6 7 8
```

### 13.2 v2 Categories (22 categories, 525 cases)

#### Core Functionality (Categories 01-08)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 01 | ct_analysis | 30 | CT image analysis |
| 02 | ctv_segmentation | 15 | CTV tumor segmentation |
| 03 | hallucination | 21 | Fabrication detection |
| 04 | dose_engine | 14 | Dose calculation |
| 05 | context | 15 | Multi-turn context |
| 06 | dose_evaluation | 13 | Dose evaluation |
| 07 | safety | 25 | Safety constraints |
| 08 | error_recovery | 14 | Error handling |

#### Tool-Specific Tests (Categories 09-10)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 09 | knowledge_tools | 15 | Clinical knowledge base |
| 10 | web_search | 10 | Web search |

#### Quality Tests (Categories 11-16)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 11 | hallucination | 15 | Advanced hallucination |
| 12 | language | 15 | Language consistency |
| 13 | context | 10 | Context retention |
| 14 | response_quality | 10 | Response formatting |
| 15 | safety | 10 | Safety validation |
| 16 | error_recovery | 10 | Error handling |

#### Workflow Tests (Categories 17-20)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 17 | advanced_workflows | 15 | Complex workflows |
| 18 | edge_cases | 15 | Edge cases |
| 19 | regression | 15 | Regression tests |
| 20 | clinical_scenarios | 15 | Clinical scenarios |

#### Input Variation Tests (Categories 21-22)

| # | Category | Cases | Description |
|---|----------|-------|-------------|
| 21 | input_variations | 112 | Same intent, different phrasings |
| 22 | input_variations_all | 111 | Comprehensive variations |

### 13.3 Setup Field (v2)

v2 tests require setup before running. The `setup` field describes required state:

| Setup | Action |
|-------|--------|
| `Upload CT` | Upload CT file to BrachyBot |
| `Upload CT + run segmentation` | Upload CT + run CTV and OAR segmentation |
| `Upload CT + segmentation + plan` | Upload CT + segmentation + generate plan |
| `Upload CT + segmentation + plan + dose evaluation` | Full pipeline |
| `No CT needed` | Direct question, no setup |

**CT File:** `/home/lht/snap/brachyplan/data/RuijinCases/10/CTyuanaju.nii`

### 13.4 Screenshot-Response Alignment

**CRITICAL: Screenshots MUST match recorded responses**

1. Open browser and navigate to BrachyBot
2. Setup required state (upload CT, run segmentation, etc.)
3. Type the input
4. Wait for response to complete
5. Take screenshot (captures EXACT response)
6. Extract response text FROM THE UI
7. Score the extracted response

**Never:**
- Take screenshot before response is complete
- Use API response instead of UI response
- Skip screenshots for any test case

### 13.5 Language Consistency

**Requirements:**
- Chinese input → Chinese response
- English input → English response
- Language mismatch = P1 failure

**Detection:**
```python
def detect_language(text):
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    if chinese_chars > english_chars * 0.3:
        return 'zh'
    else:
        return 'en'
```

### 13.6 Auto-Monitoring

**Features:**
- Monitors agent progress every 5 minutes
- Restarts stuck or non-compliant agents
- No restart limit (retries until correct)
- Logs all actions for audit

**Start monitoring:**
```bash
nohup python3 auto_monitor.py > auto_monitor.log 2>&1 &
```

### 13.7 Report Generation

**Final report generation:**
```bash
python3 generate_final_report.py
```

**Report contents:**
- Executive summary
- Agent performance
- Root cause analysis
- Category breakdown
- Data sources

### 13.8 Troubleshooting

| Issue | Solution |
|-------|----------|
| Timeout errors | Check server status, increase timeout |
| Screenshot blank | Wait longer for response |
| Language mismatch | Check input language |
| Server offline | Run `wait_for_server()` |
| Agent stuck | Check auto_monitor logs |
| Setup incomplete | Wait longer for CT/segmentation |

### 13.9 File Locations

```
benchmarks/
├── README.md                      # This file
├── aligned_benchmark.py           # Main test script (v2)
├── auto_monitor.py                # Auto-monitoring
├── generate_final_report.py       # Report generation (v2)
├── run_aligned_agents.sh          # Run 4 agents in parallel
├── v1/                            # v1 benchmark (36 categories, READ-ONLY)
├── v2/                            # v2 benchmark (22 categories, 525 cases)
│   ├── README.md                  # v2 documentation
│   ├── 01_ct_analysis.json        # 15 cases
│   ├── 01_tool_calling.json       # 15 cases
│   ├── 02_ctv_segmentation.json   # 10 cases
│   ├── 02_multi_step.json         # 5 cases
│   ├── 03_hallucination.json      # 11 cases
│   ├── 03_oar_segmentation.json   # 10 cases
│   ├── 04_dose_engine.json        # 8 cases
│   ├── 04_language.json           # 6 cases
│   ├── 05_context.json            # 7 cases
│   ├── 05_treatment_planning.json # 8 cases
│   ├── 06_dose_evaluation.json    # 8 cases
│   ├── 06_response_quality.json   # 5 cases
│   ├── 07_safety.json             # 5 cases
│   ├── 07_ui_control.json         # 20 cases
│   ├── 08_error_recovery.json     # 6 cases
│   ├── 08_output_tools.json       # 8 cases
│   ├── 09_knowledge_tools.json    # 15 cases
│   ├── 10_web_search.json         # 10 cases
│   ├── 11_hallucination.json      # 15 cases
│   ├── 12_language.json           # 15 cases
│   ├── 13_context.json            # 10 cases
│   ├── 14_response_quality.json   # 10 cases
│   ├── 15_safety.json             # 10 cases
│   ├── 16_error_recovery.json     # 10 cases
│   ├── 17_advanced_workflows.json # 15 cases
│   ├── 18_edge_cases.json         # 15 cases
│   ├── 19_regression.json         # 15 cases
│   ├── 20_clinical_scenarios.json # 15 cases
│   ├── 21_input_variations.json   # 112 cases
│   └── 22_input_variations_all.json # 111 cases
└── archive/                       # Archived v1 scripts and logs
    ├── v1_scripts/                # Old v1 scripts
    ├── v1_logs/                   # Old v1 logs
    └── v1_docs/                   # Old v1 documentation

docs/benchmark_result/
├── screenshots_v2/                # v2 screenshots
├── reports_v2/                    # v2 reports
└── auto_monitor_v2.log            # Monitor logs
```

---

**Document Version:** 4.0
**Last Updated:** 2026-06-04
**Maintainer:** BrachyBot QA System
