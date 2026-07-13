# BrachyBot Benchmark Final Report

**Generated:** 2026-06-04 02:19:29
**Total Test Cases:** 857
**Agents Used:** 45

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Tests | 857 |
| Passed | 530 |
| Failed | 327 |
| Overall Pass Rate | 61.8% |
| Overall Avg Score | 0.800 |

### Agent Performance Summary

| Agent | Tests | Passed | Failed | Pass Rate | Avg Score |
|-------|-------|--------|--------|-----------|----------|
| Agent 1 | 25 | 17 | 8 | 68.0% | 0.808 |
| Agent 1 | 88 | 72 | 16 | 81.8% | 0.812 |
| Agent 1 | 25 | 25 | 0 | 100.0% | 0.972 |
| Agent 1 | 25 | 23 | 2 | 92.0% | 0.917 |
| Agent 1 | 2 | 2 | 0 | 100.0% | 0.767 |
| Agent 1 | 6 | 5 | 1 | 83.3% | 0.808 |
| Agent 1 | 5 | 5 | 0 | 100.0% | 0.944 |
| Agent 1 | 12 | 11 | 1 | 91.7% | 0.920 |
| Agent 2 | 1 | 1 | 0 | 100.0% | 0.900 |
| Agent 2 | 44 | 35 | 9 | 79.5% | 0.884 |
| Agent 2 | 1 | 0 | 1 | 0.0% | 0.650 |
| Agent 2 | 1 | 0 | 1 | 0.0% | 0.700 |
| Agent 2 | 2 | 1 | 1 | 50.0% | 0.725 |
| Agent 3 | 194 | 76 | 118 | 39.2% | 0.752 |
| Agent 3 | 3 | 2 | 1 | 66.7% | 0.750 |
| Agent 3 | 4 | 0 | 4 | 0.0% | 0.679 |
| Agent 3 | 1 | 1 | 0 | 100.0% | 0.883 |
| Agent 3 | 1 | 0 | 1 | 0.0% | 0.650 |
| Agent 3 | 1 | 0 | 1 | 0.0% | 0.575 |
| Agent 3 | 1 | 1 | 0 | 100.0% | 1.000 |
| Agent 3 | 8 | 8 | 0 | 100.0% | 0.949 |
| Agent 4 | 30 | 8 | 22 | 26.7% | 0.646 |
| Agent 4 | 1 | 1 | 0 | 100.0% | 0.961 |
| Agent 4 | 40 | 16 | 24 | 40.0% | 0.752 |
| Agent 4 | 65 | 60 | 5 | 92.3% | 0.831 |
| Agent 5 | 15 | 15 | 0 | 100.0% | 0.925 |
| Agent 5 | 1 | 1 | 0 | 100.0% | 0.850 |
| Agent 5 | 10 | 2 | 8 | 20.0% | 0.677 |
| Agent 5 | 14 | 12 | 2 | 85.7% | 0.888 |
| Agent 5 | 1 | 1 | 0 | 100.0% | 0.825 |
| Agent 5 | 108 | 50 | 58 | 46.3% | 0.732 |
| Agent 5 | 9 | 7 | 2 | 77.8% | 0.857 |
| Agent 5 | 12 | 9 | 3 | 75.0% | 0.919 |
| Agent 5 | 5 | 5 | 0 | 100.0% | 0.965 |
| Agent 5 | 5 | 3 | 2 | 60.0% | 0.840 |
| Agent 6 | 3 | 1 | 2 | 33.3% | 0.694 |
| Agent 6 | 10 | 9 | 1 | 90.0% | 0.947 |
| Agent 6 | 9 | 3 | 6 | 33.3% | 0.650 |
| Agent 6 | 9 | 5 | 4 | 55.6% | 0.816 |
| Agent 6 | 10 | 6 | 4 | 60.0% | 0.880 |
| Agent 6 | 15 | 4 | 11 | 26.7% | 0.643 |
| Agent 6 | 3 | 3 | 0 | 100.0% | 0.977 |
| Agent 6 | 10 | 8 | 2 | 80.0% | 0.926 |
| Agent 6 | 15 | 12 | 3 | 80.0% | 0.891 |
| Agent 8 | 7 | 4 | 3 | 57.1% | 0.840 |

### Failure Root Causes (All Agents)

| Root Cause | Count | % of Failures | Severity |
|------------|-------|---------------|----------|
| wrong_answer | 122 | 37.4% | P2 |
| keyword_missing | 96 | 29.4% | P2 |
| language_mismatch | 58 | 17.8% | P2 |
| too_brief | 41 | 12.6% | P2 |
| safety_leak | 9 | 2.8% | P0 |

---

## Key Findings

### Strengths
1. **CTV/OAR Segmentation** (Categories 03, 04): 100% pass rate
2. **Tool Calling** (Category 08): 100% pass rate
3. **UI Interaction** (Category 07): 100% pass rate
4. **Adversarial Robustness** (Category 10): 96% pass rate
5. **Safety** (Category 17): 93-100% pass rate

### Areas for Improvement
1. **Medical Reasoning** (Category 12): 74% pass rate
2. **Stress Testing** (Category 14): 75% pass rate
3. **Medium Complexity** (Category 23): 74% pass rate
4. **Response Length Issues**: 60-72% of failures

---

## Data Sources

- **Agent 1 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_*.md`
- **Agent 1 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_*.md`
- **Agent 1 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_*.md`
- **Agent 1 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_*.md`
- **Agent 1 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_*.md`
- **Agent 1 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_*.md`
- **Agent 1 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_*.md`
- **Agent 1 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent1_*.md`
- **Agent 2 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_*.md`
- **Agent 2 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_*.md`
- **Agent 2 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_*.md`
- **Agent 2 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_*.md`
- **Agent 2 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent2_*.md`
- **Agent 3 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent3_*.md`
- **Agent 3 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent3_*.md`
- **Agent 3 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent3_*.md`
- **Agent 3 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent3_*.md`
- **Agent 3 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent3_*.md`
- **Agent 3 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent3_*.md`
- **Agent 3 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent3_*.md`
- **Agent 3 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent3_*.md`
- **Agent 4 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent4_*.md`
- **Agent 4 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent4_*.md`
- **Agent 4 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent4_*.md`
- **Agent 4 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent4_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 5 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent5_*.md`
- **Agent 6 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent6_*.md`
- **Agent 6 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent6_*.md`
- **Agent 6 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent6_*.md`
- **Agent 6 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent6_*.md`
- **Agent 6 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent6_*.md`
- **Agent 6 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent6_*.md`
- **Agent 6 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent6_*.md`
- **Agent 6 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent6_*.md`
- **Agent 6 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent6_*.md`
- **Agent 8 Report:** `/home/lht/snap/brachyplan/BrachyBot/docs/benchmark_result/reports/agent8_*.md`

