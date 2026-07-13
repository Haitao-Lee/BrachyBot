# Agent 5 Benchmark Report - 27_safety_validator

**Generated:** 2026-06-03 16:49:17
**Agent:** 5
**Category:** 27_safety_validator

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Tests | 5 |
| Passed | 3 |
| Failed | 2 |
| Pass Rate | 60.0% |
| Avg Score | 0.840 |

### Failure Root Causes

| Root Cause | Count | % of Failures | Severity |
|------------|-------|---------------|----------|
| language_mismatch | 2 | 100.0% | P1 |

## Detailed Results

### ✅ SV001

**Input:** Run a safety check on this treatment plan before I export it...

**Response:**
> No treatment plan is currently loaded for safety validation.To run pre-export safety checks, please provide:ParameterValueCancer type(prostate / cervical / breast, etc.)Technique(LDR / HDR)V100?D90?V150?V200?Rectum D2cc?Urethra D10?Bladder D2cc?Safety checks performed:✓ Target coverage (V100 ≥93%)✓ OAR dose constraints✓ Hot spot limits (V200 <25%)✓ Plan quality flagsUpload your plan file and I will run automatic safety validation before export....

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![SV001](../screenshots/27_SV001.png)

---

### ❌ SV002

**Input:** Check if the rectum dose is within safe limits...

**Response:**
> 没有可检查的直肠剂量数据。请提供直肠剂量值：参数值直肠 D2cc?处方剂量?癌症类型?直肠安全剂量限制（临床标准）：癌症类型约束证据宫颈癌 HDRD2cc < 75-80Gy EQD2EMBRACE II前列腺粒子植入D2cc < 处方剂量 130-150%ABS前列腺 HDRD2cc < 75Gy EQD2Phoenix请提供直肠 D2cc 值，我会判断是否在安全范围内。...

**Scores:**
- Total: 0.60
- Keyword: 0.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 0.00

**Screenshot:**
![SV002](../screenshots/27_SV002.png)

**Failure Analysis:**
- Root Cause: language_mismatch
- Description: English input should get English response

---

### ✅ SV006

**Input:** Is this plan safe to export? Run all safety checks...

**Response:**
> No treatment plan is currently loaded for safety validation.To run safety checks, please provide:ParameterValueCancer type(prostate / cervical / breast)Technique(LDR seeds / HDR)V100?D90?V150?V200?Rectum D2cc?Urethra D10?Bladder D2cc?Safety checks that will run:✓ Target coverage (V100 ≥93%)✓ OAR dose constraints compliance✓ Hot spot limits (V200 <25%)✓ Dose homogeneity index✓ Pre-export clearanceOr: Upload your plan file and I will extract all metrics automatically.Please provide the plan data to proceed with safety validation....

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![SV006](../screenshots/27_SV006.png)

---

### ✅ SV007

**Input:** 这个方案的V200超标了吗？...

**Response:**
> 没有 V200 数据可供检查。V200 超标标准（前列腺近距离治疗）：V200判定<20-25%✓ 合格25-30%⚠️ 临界>30%✗ 超标超标风险：尿道热点过高 → 尿路毒性增加直肠剂量溅射 → 直肠炎风险剂量不均匀性差请提供 V200 值，我会判断是否超标。...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![SV007](../screenshots/27_SV007.png)

---

### ❌ SV010

**Input:** Run a pre-export validation with strict mode...

**Response:**
> 预导出验证失败： 没有加载治疗计划数据。原因： 当前系统没有可验证的计划数据。要执行严格模式预导出验证，请提供：参数值癌症类型?技术(LDR/HDR)V100?D90?V150?V200?直肠 D2cc?尿道 D10?膀胱 D2cc?严格模式检查标准：V100 ≥ 95%（严格）vs ≥93%（标准）V200 < 20%（严格）vs <25%（标准）OAR 约束更严格（直肠 D2cc < 70Gy）请上传 CT 图像和治疗计划，我会执行完整的严格模式安全验证。...

**Scores:**
- Total: 0.60
- Keyword: 0.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 0.00

**Screenshot:**
![SV010](../screenshots/27_SV010.png)

**Failure Analysis:**
- Root Cause: language_mismatch
- Description: English input should get English response

---

