# Agent 3 Benchmark Report - 23_medium_complexity

**Generated:** 2026-06-03 16:38:35
**Agent:** 3
**Category:** 23_medium_complexity

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Tests | 1 |
| Passed | 0 |
| Failed | 1 |
| Pass Rate | 0.0% |
| Avg Score | 0.650 |

### Failure Root Causes

| Root Cause | Count | % of Failures | Severity |
|------------|-------|---------------|----------|
| keyword_missing | 1 | 100.0% | P2 |

## Detailed Results

### ❌ Q1257

**Input:** Dosimetric comparison of applicator systems (tandem/ovoid, tandem/ring): CT-based, DVH parameters, statistical comparison, visualization, and clinical interpretation....

**Response:**
> ## Dosimetric Comparison: Tandem/Ovoid vs Tandem/Ring Applicators### 1. CT-Based Applicator Reconstruction| Aspect | Tandem/Ovoid (T/O) | Tandem/Ring (T/R) ||--------|-------------------|-------------------|| **Geometry** | Two ovoids lateral to tandem | Single ring perpendicular to tandem || **Source paths** | 3 channels (tandem + 2 ovoids) | 2 channels (tandem + ring) || **Dwell positions** | More complex distribution | More uniform coverage || **Reconstruction** | More challenging (3D orientation) | Simpler (orthogonal ring) |### 2. Key DVH Parameters for Comparison**Target Coverage (HR-CTV)**- D90 (dose covering 90% of volume)- D100- V100, V150, V200**O...

**Scores:**
- Total: 0.65
- Keyword: 0.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q1257](../screenshots/23_Q1257.png)

**Failure Analysis:**
- Root Cause: keyword_missing
- Description: No expected keywords found

---

