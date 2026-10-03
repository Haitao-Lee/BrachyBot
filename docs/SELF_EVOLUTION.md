# BrachyBot Self-Evolution System

**Last updated:** 2026-06-04

## 1. System Overview

BrachyBot's self-evolution system is one of the core components of the AI-BrachyAgent architecture. Through a closed-loop feedback mechanism, the system continuously learns from test results, clinical interactions, and error cases, automatically optimizing the toolchain, prompts, and response strategies.

### Design Goals

- **Automated capability improvement**: Benchmark-driven, automatically discovers weaknesses and generates improvement plans
- **Clinical safety assurance**: All evolution paths must pass safety validation to ensure clinical safety is not reduced
- **Knowledge accumulation**: Extract reusable experience from each interaction to form a structured knowledge base

---

## 2. Evolution Architecture

```
┌─────────────────────────────────────────────────────┐
│                Self-Evolution Closed Loop            │
│                                                     │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│   │Benchmark │───▶│Weakness  │───▶│Improve-  │     │
│   │          │    │Analysis  │    │ment Gen. │     │
│   └──────────┘    └──────────┘    └──────────┘     │
│        ▲                               │            │
│        │           ┌──────────┐        │            │
│        └───────────│Validation│◀───────┘            │
│                    │Test      │                     │
│                    └──────────┘                     │
└─────────────────────────────────────────────────────┘
```

### Core Components

| Component | Responsibility | Key File |
|------|------|----------|
| **ToolRegistry** | Tool registration and discovery | `AgenticSys.py` |
| **SkillManager** | Skill loading and execution | `skills/` |
| **PromptEngine** | Dynamic prompt assembly | `config/prompts/` |
| **BenchmarkRunner** | Benchmark execution | `benchmarks/aligned_benchmark.py` |
| **CaseMemory** | Case memory and retrieval | `memory/` |
| **ClinicalKB** | Clinical knowledge base | `clinical_kb/` |

---

## 3. Benchmark System

### v2 Benchmark (current version)

- **Total test cases**: 525
- **Number of categories**: 22
- **Test focus**: System capabilities (not LLM knowledge)

#### Category Overview

| Category | Test Cases | Description |
|------|--------|------|
| ct_analysis | 30 | CT image analysis |
| ctv_segmentation | 15 | CTV tumor segmentation |
| hallucination | 21+15 | Hallucination detection (basic + advanced) |
| dose_engine | 14 | Dose calculation |
| context | 15+10 | Multi-turn context retention |
| dose_evaluation | 13 | Dose evaluation |
| safety | 25+10 | Safety constraint validation |
| error_recovery | 14 | Error recovery |
| knowledge_tools | 15 | Clinical knowledge base tools |
| web_search | 10 | Web search tools |
| language | 15 | Language consistency |
| response_quality | 10 | Response formatting |
| ui_control | 10 | UI control capabilities |
| output_tools | 10 | Output tool invocation |
| advanced_workflows | 10 | Advanced workflows |
| edge_cases | 10 | Edge cases |
| regression | 10 | Regression tests |
| clinical_scenarios | 10 | Clinical scenarios |
| input_variations | 30+26 | Input variation tests |

#### Test Process

```bash
# Run a single category
python3 aligned_benchmark.py <agent_id> <category_number>

# Run multiple categories
python3 aligned_benchmark.py <agent_id> 1 2 3 4 5 6 7 8

# Run 4 agents in parallel
./run_aligned_agents.sh
```

### v1 Benchmark (archived)

- **Total test cases**: 2000
- **Number of categories**: 38
- **Status**: Archived to `benchmarks/v1/`
- **Pass rate**: 1.6% (mainly due to no_response issues, not capability deficiencies)

---

## 4. Known Issues and Improvement Directions

### 4.1 Main Failure Modes of v1 Tests

| Failure Type | Count | Cause |
|----------|------|------|
| no_response | 1961 | System did not respond (need to check Web API communication) |
| keyword_mismatch | 2 | Keyword matching logic needs optimization |
| low_relevance | 2 | Response relevance to the question is insufficient |

### 4.2 v2 Improvement Focus

1. **Tool invocation reliability**: Ensure toolchains such as CT analysis, segmentation, and dose calculation are triggered correctly
2. **Multi-turn dialogue context**: Verify the ability to retain information across turns
3. **Hallucination prevention**: Detect and block fabricated clinical data
4. **Safety boundaries**: Validate safety mechanisms such as OAR dose constraints and contraindication refusal
5. **Language consistency**: Ensure the response language matches the input language

### 4.3 Evolution Strategy

```
Weakness Discovery → Root Cause Analysis → Improvement Plan → A/B Testing → Deployment
    │                                         │
    └─────────────── Effect Validation ◀───────┘
```

| Strategy | Implementation | Applicable Scenario |
|------|----------|----------|
| **Prompt optimization** | Adjust `config/prompts/system_prompt.md` | Response format, language style |
| **Toolchain enhancement** | Extend `tool_factory/` | Add new tool capabilities |
| **Knowledge base update** | Update `clinical_kb/` | Supplement clinical knowledge |
| **Skill extension** | Add new `skills/` modules | Composite workflows |
| **Memory optimization** | Optimize `memory/` retrieval | Case experience reuse |

---

## 5. Safety Mechanisms

### Evolution Safety Constraints

1. **Clinical safety first**: No evolution may reduce safety metrics such as OAR protection and dose constraints
2. **Zero tolerance for hallucination**: After evolution, the hallucination category tests must pass
3. **Regression validation**: Each evolution must pass all safety category tests
4. **Human review**: Changes involving clinical decision logic require human confirmation

### Safety Test Coverage

- OAR dose constraint validation (QUANTEC/TG-43 standards)
- Contraindication identification and refusal
- Dose exceedance warnings
- Hallucination detection (fabricated dose values, indications, etc.)
- Error recovery (safe degradation when tools fail)

---

## 6. Operating Metrics

### Current Status (as of 2026-06-04)

| Metric | Value |
|------|-----|
| v2 benchmark test cases | 525 |
| v2 number of categories | 22 |
| Number of toolchain tools | 15+ |
| Number of skill modules | 6 |
| Clinical knowledge entries | Continuously growing |

### Evolution Cycle

```
Daily: automatically run benchmarks → generate reports
Weekly: analyze weakness trends → formulate improvement plans
Monthly: evaluate overall progress → adjust evolution strategy
```

---

## 7. File Structure

```
docs/
├── SELF_EVOLUTION.md              ← This document
├── BrachyBot_SELF_EVOLUTION_REPORT_20260530.md  ← v1 test report
├── BENCHMARK_ISSUES_AND_FIXES.md  ← Benchmark issues and fixes
├── BENCHMARK_OVERCORRECTION_REVIEW.md  ← Overcorrection review
├── BENCHMARK_QUALITY_ASSESSMENT.md  ← Quality assessment
├── BENCHMARK_REQUIREMENTS_CHECKLIST.md  ← Requirements checklist
├── CODE_REVIEW_REPORT.md          ← Code review report
├── OPTIMIZATION_SUMMARY.md        ← Optimization summary
└── QA_REPORT_2026-05-30.md        ← QA report
```

---

## 8. Related Documents

- [Benchmark README](../benchmarks/README.md) — Test execution guide
- [v2 Test Guide](../benchmarks/v2/README.md) — Detailed v2 test process
- [System Prompt](../config/prompts/system_prompt.md) — Current prompt configuration
- [Tool Factory](../tool_factory/) — Tool registration and implementation
- [Skill System](../skills/) — Skill module definitions
