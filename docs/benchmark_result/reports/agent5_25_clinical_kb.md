# Agent 5 Benchmark Report - 25_clinical_kb

**Generated:** 2026-06-03 16:43:06
**Agent:** 5
**Category:** 25_clinical_kb

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Tests | 12 |
| Passed | 9 |
| Failed | 3 |
| Pass Rate | 75.0% |
| Avg Score | 0.919 |

### Failure Root Causes

| Root Cause | Count | % of Failures | Severity |
|------------|-------|---------------|----------|
| language_mismatch | 3 | 100.0% | P1 |

## Detailed Results

### ✅ CK001

**Input:** What are the dose constraints for prostate brachytherapy?...

**Response:**
> ## Prostate Brachytherapy Dose Constraints### LDR (I-125 / Pd-103)| Organ | Constraint | Evidence ||-------|-----------|----------|| **Urethra** | D10 < 150% (some centers < 120%) | ABS/AAPM Guidelines || **Rectum** | D2cc < 100-130 Gy | QUANTEC, ABS || **Bladder** | D2cc < 150 Gy | QUANTEC || **Prostate PTV** | V100 > 90%, V150 < 50% | Multiple series |### HDR Monotherapy| Organ | Constraint | Evidence ||-------|-----------|----------|| **Urethra** | D10 < 115-120% | GEC-ESTRO, ABS || **Rectum** | D2cc < 75 Gy (EQD2) | EMBRACE, GEC-ESTRO |...

**Scores:**
- Total: 0.88
- Keyword: 0.67
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![CK001](../screenshots/25_CK001.png)

---

### ✅ CK002

**Input:** What's the maximum tolerable dose for the rectum?...

**Response:**
> ## 直肠剂量限制（前列腺近距离放疗）### HDR前列腺近距离放疗| 约束指标 | 限值 | 证据级别 ||---------|------|---------|| **D2cc** | < 75 Gy (EQD2) | ABS/AAPM || **D1cc** | < 80 Gy | GEC-ESTRO || **V70** | < 50% | ABS || **V100** | < 10% | ABS |### LDR粒子植入| 约束指标 | 限值 | 证据级别 ||---------|------|---------|| **D2cc** | < 100-130 Gy | ABS || **V100 (直肠)** | < 50% | ABS || **D1cc** | < 200 Gy | 临床经验 |### 临床说明- **D2cc**：直肠接受最高剂量的1cc...

**Scores:**
- Total: 0.77
- Keyword: 0.33
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![CK002](../screenshots/25_CK002.png)

---

### ❌ CK003

**Input:** Tell me about the HDR cervical cancer protocol...

**Response:**
> ## HDR宫颈癌治疗方案### 适应症- **局部晚期宫颈癌**（IB3-IVA期）- **根治性放化疗**的一部分（EBRT + 近距离放疗）- **辅助治疗**用于不良预后因素的术后患者### 标准治疗流程#### 1. 外照射（EBRT）- **剂量：** 45-50.4 Gy，分25-28次- **靶区：** 子宫、宫颈、宫旁组织、阴道上1/3、盆腔淋巴结- **时机：** 先进行，随后近距离放疗#### 2. HDR近距离放疗- **分次方案：**  - 4-5次（通常4次），每次7-8 Gy  - 或...

**Scores:**
- Total: 0.72
- Keyword: 0.33
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 0.00

**Screenshot:**
![CK003](../screenshots/25_CK003.png)

**Failure Analysis:**
- Root Cause: language_mismatch
- Description: English input should get English response

---

### ✅ CK004

**Input:** 前列腺癌近距离治疗的V100目标是多少？...

**Response:**
> **前列腺癌近距离治疗V100目标：**| 指标 | 目标值 | 说明 ||------|--------|------|| **V100** | ≥95% | 处方剂量覆盖的前列腺体积比例 || V150 | 50-60% | 高剂量区体积 || V200 | <20% | 过高剂量区体积 |**临床目标值：**- **D90** (最高剂量的90%覆盖点)：处方剂量的100-120%- **D100**：>90%处方剂量（最低覆盖）- ** urethra D10**：<150%处方剂量（限制）- **rectum D2cc**：<处方剂...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![CK004](../screenshots/25_CK004.png)

---

### ❌ CK005

**Input:** What's the difference between TG-43 and TG-137?...

**Response:**
> **TG-43 vs TG-137 主要区别**| 方面 | TG-43 (1995) | TG-137 (2006) ||------|--------------|----------------|| **主题** | 插植近距离治疗源剂量学 | 插植近距离治疗源剂量学更新 || **计算介质** | 均匀水模体 | 考虑组织不均匀性 || **计算方法** | 解析公式（基于测量数据） | 模型基础剂量计算算法 (MBDCA) || **不均匀性校正** | 不考虑 | 明确推荐 || **蒙特卡罗应用** | 未涉及 | 详细讨论 || **临床应用** | 当时主流方法 | 现代治疗计划系统基础 |**TG-43 局限性：**- 假设无限均匀水介质- 不考虑骨骼、空气、组织密度差异- 对高密度材料（如施源器）假设错误**TG-137 改进：**- 推荐使用蒙特卡罗、盒氏求和等不均匀性校正方法- 为现代治疗计划系统的...

**Scores:**
- Total: 0.83
- Keyword: 0.67
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 0.00

**Screenshot:**
![CK005](../screenshots/25_CK005.png)

**Failure Analysis:**
- Root Cause: language_mismatch
- Description: English input should get English response

---

### ✅ CK006

**Input:** Is this plan acceptable? V100=93%, D90=98%, V150=52%...

**Response:**
> **Plan Assessment: Marginally Acceptable ⚠️**| Metric | Your Plan | Target | Status ||--------|-----------|--------|--------|| V100 | 93% | ≥93-95% | ⚠️ At lower limit || D90 | 98% | ≥90-100% | ✓ Acceptable || V150 | 52% | <50-60% | ✓ Acceptable |**Clinical Interpretation:**- **V100 = 93%**: This is the minimum acceptable threshold per ABS guidelines. Ideally, ≥95% is preferred for better tumor coverage.- **D90 = 98%**: Good — indicates 98% of the prescription dose covering 90% of the target volume.- **V150 = 52%**: Acceptable but slightly high. Higher V150 increases urethral dose and may elevate urinary toxicity risk.**Recommendation:**The plan meets minimum criteria but is not optimal. Consider re-optimization to improve V100 to ≥95% while controlling V150 below 50%.**For HDR prostate (alternative...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![CK006](../screenshots/25_CK006.png)

---

### ✅ CK007

**Input:** 宫颈癌HDR的OAR约束标准是什么？...

**Response:**
> # 宫颈癌HDR近距离治疗的OAR剂量约束## 标准剂量约束（EQD2）| 器官 | 约束指标 | 目标值 | 证据来源 ||------|----------|--------|----------|| **膀胱** | D2cc | < 70 Gy | GEC-ESTRO, EMBRACE || **直肠** | D2cc | < 65-70 Gy | GEC-ESTRO, ABS || **乙状结肠** | D2cc | < 65-70 Gy | GEC-ESTRO || **小肠** | D2cc | < 70 Gy | GEC-ESTRO || **尿道** | D0.1cc | < 80-85 Gy | ABS || **阴道** | D2cc | < 70 Gy | ABS |## EMBRACE研究约束（更严格）| 器官 | 约束指标 | EMBRACE II目标 ||------|----------|----------------|| 膀胱 | D2cc | < 90 Gy EQD2 || 直肠 | D...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![CK007](../screenshots/25_CK007.png)

---

### ✅ CK008

**Input:** What are the organ tolerance limits for spinal cord?...

**Response:**
> ## Spinal Cord Dose Tolerance Limits**Standard Dose Constraints (Conventional Fractionation):**| Constraint | Limit | Evidence ||------------|-------|----------|| **Max point dose** | **< 50 Gy** | QUANTEX, NCRP || **Partial cord (10cm segment)** | < 50 Gy | TG-101 || **Mean dose** | < 45 Gy | Various guidelines |**Single Fraction / SBRT Context (NCRP TG-101):**| Volume | Constraint ||--------|------------|| 0.35 cc | 30 Gy (parallel) || 1.2 cc | 30 Gy || Max point | 30 Gy |**Combined EBRT + Brachytherapy:**- Cumulative dose to spinal cord should remain **< 50 Gy EQD2**- Account for brachytherapy contribution when...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![CK008](../screenshots/25_CK008.png)

---

### ✅ CK009

**Input:** What treatment protocol do you recommend for intermediate risk prostate cancer?...

**Response:**
> ## Intermediate-Risk Prostate Cancer Treatment Options**Definition (NCCN/AUA):**- One or more: PSA 10-20 ng/mL, Gleason 7, or T2b-T2c- No high-risk features### Brachytherapy Options| Modality | Protocol | Details ||----------|----------|---------|| **LDR Seeds** | Monotherapy | 145-160 Gy (I-125), 125 Gy (Pd-103) || **HDR Monotherapy** | 19-21 Gy × 1 fraction | Emerging evidence for single-fraction || **HDR Boost** | 9.5-15 Gy × 1 + EBRT 45-50.4 Gy | Standard of care per NCCN |...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![CK009](../screenshots/25_CK009.png)

---

### ✅ CK011

**Input:** 肝脏近距离治疗的正常肝平均剂量限制是多少？...

**Response:**
> 让我搜索肝脏近距离治疗的剂量限制信息：**肝脏近距离治疗的正常肝剂量限制：**基于临床知识库查询结果，肝脏正常组织剂量约束取决于治疗方案和临床情境：**主要剂量限制参考值：**| 参数 | 限制值 | 依据 ||------|--------|------|| 全肝平均剂量 | <15-21 Gy | QUANTEC/肝脏组织耐受性研究 || 全肝V15 | <50% | 功能性肝组织保护 || 全肝V30 | <30% | 放射性肝病(RILD)预防 |**针对肝脏近距离治疗（SBRT/消融）的补充考虑：**1. **正常肝（受保护体积）**：指除肿瘤靶区外的...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![CK011](../screenshots/25_CK011.png)

---

### ✅ CK014

**Input:** What are the quality benchmarks for an excellent plan?...

**Response:**
> ## Quality Benchmarks for Brachytherapy Plans### Prostate Cancer (LDR/HDR Monotherapy)| Metric | Acceptable | Excellent ||--------|------------|-----------|| V100 | ≥93% | ≥95% || D90 | 100-110% Rx | 100-105% Rx || V150 | 50-60% | 50-55% || V200 | <20% | <15% || Rectum D2cc | <75% Rx | <70% Rx || Urethra D10 | <150% Rx | <130% Rx |### Cervical Cancer (HDR/PDR)| Metric | Acceptable | Excellent ||--------|------------|-----------|| CTV D90 | ≥100% Rx | ≥105% Rx || Bladder D2cc | <70 Gy (EQD2) | <65 Gy || Rectum D2cc | <70 Gy (EQD2) | <65 Gy || Sigmoid D2cc | <70 Gy (EQD2) | <65 Gy || Bowel D2cc | <70 Gy (EQD2) | <65 Gy |### Breast APBI| Metric | Acceptable | Excellent ||--------|------------|-----------|| P...

**Scores:**
- Total: 0.88
- Keyword: 0.67
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![CK014](../screenshots/25_CK014.png)

---

### ❌ CK015

**Input:** Add a new dose constraint for bladder: D2cc should be less than 90Gy EQD2...

**Response:**
> 添加失败： clinical_kb 需要 category 和 key 参数。膀胱剂量约束已在临床知识库中：癌症类型约束证据来源宫颈癌D2cc < 75-80Gy EQD2EMBRACE II前列腺癌D2cc < 处方剂量 150%ABS/AAPM您请求的膀胱 D2cc < 90Gy EQD2：此值高于宫颈癌标准约束可能适用于叠加了 EBRT 剂量后的总剂量约束如需添加自定义约束，请提供：category: "constraints" 或 "tolerance"key: 唯一标识符（如 "bladder_d2cc_custom"）...

**Scores:**
- Total: 0.95
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 0.00

**Screenshot:**
![CK015](../screenshots/25_CK015.png)

**Failure Analysis:**
- Root Cause: language_mismatch
- Description: English input should get English response

---

