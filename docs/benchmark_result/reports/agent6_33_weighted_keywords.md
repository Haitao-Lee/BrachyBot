# Agent 6 Benchmark Report - 33_weighted_keywords

**Generated:** 2026-06-03 20:49:56
**Agent:** 6
**Category:** 33_weighted_keywords

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Tests | 3 |
| Passed | 3 |
| Failed | 0 |
| Pass Rate | 100.0% |
| Avg Score | 0.977 |

## Detailed Results

### ✅ WK001

**Input:** What is the prescription dose for I-125 prostate brachytherapy?...

**Response:**
> **I-125 Prostate Brachytherapy Prescription Dose:**| Protocol | Prescription Dose | Notes ||----------|-------------------|-------|| **ABS / AUA** | **144 Gy** | Monotherapy (without EBRT) || **ABS** | **110–120 Gy** | With 40–45 Gy EBRT boost || **GEC-ESTRO** | 145 Gy | Alternative monotherapy dose || **Common Practice** | 145–160 Gy | Institutional variations |---**Key Parameters:**- **Seed activity**: Typically 0.4–0.5 mCi (2.0–2.6 U) for optimized plans- **Minimum peripheral dose (MPD)**: 140–160 Gy- **D90 target**: 100–120% of prescription (>144 Gy for monotherapy)---**Dose Constraints...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![WK001](../screenshots/33_WK001.png)

---

### ✅ WK002

**Input:** What V100 target should I aim for in prostate brachytherapy?...

**Response:**
> ## V100 Target for Prostate Brachytherapy| Guideline | V100 Target ||-----------|-------------|| **ABS (American Brachytherapy Society)** | ≥95% || **GEC-ESTRO** | ≥95% (ideal: 95-99%) || **Common clinical practice** | 93-99% |### Key Points- **V100 = percentage of prostate volume receiving 100% of prescription dose**- Target: **≥95%** of the CTV (prostate + margin) should receive the full dose- Going above 99% increases urethral/rectal dose without clinical benefit- **V100 <90%** is generally considered underdosed and may compromise tumor control### Related Metrics| Metric | Target | Notes ||--------...

**Scores:**
- Total: 0.93
- Keyword: 0.80
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![WK002](../screenshots/33_WK002.png)

---

### ✅ WK003

**Input:** What are the OAR constraints for rectum in prostate brachytherapy?...

**Response:**
> **Rectum Constraints in Prostate Brachytherapy (LDR):**| Constraint | Limit | Priority ||------------|-------|----------|| D2cc | < 65 Gy (for 145 Gy prescription) | Critical || D0.1cc | < 200 Gy | Critical || V100 | < 1% of rectal volume | Important || V200 | Minimal/no overlap | Important |**For HDR prostate brachytherapy:**| Constraint | Limit ||------------|-------|| D2cc | < 75 Gy (EQD2, α/β=3) || D0.1cc | < 90 Gy (EQD2) |**Guidelines:** ABS, GEC-ESTRO, AAPM TG-64**Key points:**- D2cc is the most critical metric — correlates with late rectal toxicity- Keep seed/catheter distance from rectal...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![WK003](../screenshots/33_WK003.png)

---

