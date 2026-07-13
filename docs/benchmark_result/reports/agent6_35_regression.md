# Agent 6 Benchmark Report - 35_regression

**Generated:** 2026-06-03 21:00:14
**Agent:** 6
**Category:** 35_regression

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Tests | 10 |
| Passed | 8 |
| Failed | 2 |
| Pass Rate | 80.0% |
| Avg Score | 0.926 |

### Failure Root Causes

| Root Cause | Count | % of Failures | Severity |
|------------|-------|---------------|----------|
| too_brief | 1 | 50.0% | P2 |
| wrong_answer | 1 | 50.0% | P2 |

## Detailed Results

### ❌ REG001

**Input:** 你好...

**Response:**
> 你好！我是 BrachyBot，您的近距离放射治疗规划助手。我可以帮助您：了解剂量约束和临床指南制定近距离治疗计划分析剂量分布和 DVH验证治疗计划的安全性请问有什么可以帮您？...

**Scores:**
- Total: 0.64
- Keyword: 0.25
- Completeness: 0.50
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG001](../screenshots/35_REG001.png)

**Failure Analysis:**
- Root Cause: too_brief
- Description: Response too short (88 chars)

---

### ✅ REG002

**Input:** What is the prostate dose constraint?...

**Response:**
> ## Prostate Dose ConstraintsBased on established brachytherapy guidelines (ABS, GEC-ESTRO, AAPM):### Target Coverage (Prostate)| Parameter | Target ||-----------|--------|| D90 | ≥ 100% of prescription dose || V100 | > 90% of gland volume || V150 | < 50% (for HDR) |### Organ-at-Risk Constraints**Rectum:**- D2cc < 75% of prescription- D0.1cc < 80% of prescription**Bladder:**- D2cc < 75% of prescription- D0.1cc < 85% of prescription**Urethra (for HDR):**- D10 < 120% of prescription- D0.1cc < 110% of prescription### LDR (Seed Implant) Specifics- Minimum peripheral dose: 140–160 Gy (I-125)- V100 > 90%- D90 > 100% of prescription> **Note:** Specific constraints vary by fractionation (single...

**Scores:**
- Total: 0.88
- Keyword: 0.67
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG002](../screenshots/35_REG002.png)

---

### ✅ REG003

**Input:** Hello, I'm a new user. Can you help me with brachytherapy planning?...

**Response:**
> Hello! Yes, I can help you with brachytherapy treatment planning. Here's what I can do:**My Capabilities:**| Feature | Description ||---------|-------------|| **CTV/Target Segmentation** | Automatic contouring of prostate and other targets || **OAR Contouring** | Organ-at-risk segmentation (rectum, bladder, urethra, etc.) || **Seed Planning** | Optimize seed placement for LDR brachytherapy || **Dose Calculation** | Compute dose distributions and DVH metrics || **Constraint Checking** | Verify plans against ABS/GEC-ESTRO guidelines || **Plan Comparison** | Compare multiple plans side-by-side || **Safety Validation** | Pre-export checks for patient safety || **Clinical Reports** | Generate treatment plan reports |**Common Workflows:**1. **LDR Prostate Brachytherapy**: Upload CT → Auto-segment → Place seeds → Calculate dose → Validate against constraints...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG003](../screenshots/35_REG003.png)

---

### ✅ REG004

**Input:** What is the V100 target?...

**Response:**
> **V100** is the percentage of the target volume receiving ≥100% of the prescribed dose.**For prostate LDR brachytherapy:**| Metric | Target ||--------|--------|| **V100** | ≥95% of CTV/PTV || **D90** | ≥100% of prescription dose (i.e., ≥144 Gy for low-dose-rate) |**Typical prescription:** 144 Gy (¹²⁵I) or 125 Gy (¹⁰³Pd) monotherapy.**Clinical context:**- V100 < 90% → underdosing, potential marginal failure- V100 > 99% → may indicate excessive cold spots or need to verify contour...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG004](../screenshots/35_REG004.png)

---

### ❌ REG005

**Input:** What is the 5-year survival rate at Memorial Hospital for cervical cancer?...

**Response:**
> I don't have access to Memorial Hospital's specific 5-year survival rate data for cervical cancer. Institutional survival rates depend on patient population, cancer stage distribution, treatment protocols, and follow-up duration.**General cervical cancer 5-year survival rates (SEER data):**| Stage | 5-Year Survival ||-------|-----------------|| Localized (confined to cervix) | ~92% || Regional (spread to nearby structures) | ~58% || Distant metastasis | ~18% || All stages combined | ~66% |**Key factors affecting survival:**- Stage at diagnosis (most important)- Histology (squamous cell vs. adenocarcinoma)- Treatment modality (brachytherapy with EBRT, FIGO stage)- Patient age and comorbidities**To get Memorial Hospital's specific data:**- Contact their...

**Scores:**
- Total: 0.74
- Keyword: 0.25
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG005](../screenshots/35_REG005.png)

**Failure Analysis:**
- Root Cause: wrong_answer
- Description: Response does not meet expectations

---

### ✅ REG006

**Input:** What is the prescription dose?...

**Response:**
> The prescription dose depends on the cancer type and treatment protocol:## Prostate Cancer (LDR Permanent Seeds)- **145 Gy** (without prior EBRT)- **108-110 Gy** (with supplemental EBRT)- TG-137 / ABS推奨## Prostate Cancer (HDR)- **15 Gy × 1 fraction** (monotherapy)- **9.5-12 Gy × 2 fractions** (boost after EBRT)## Cervical Cancer (HDR)- **5.5–7 Gy × 4–5 fractions** to Point A (GEC-ESTRO)- EQD2 ≥80–85 Gy to HR-CTV- Typical combined EBRT + BT total dose: 80–90 Gy EQD2## Breast (APBI)- **34 Gy × 10 fractions** (HDR with multicath...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG006](../screenshots/35_REG006.png)

---

### ✅ REG007

**Input:** What is V100?...

**Response:**
> V100 = the percentage of the target volume receiving ≥100% of the prescribed dose.For prostate LDR brachytherapy (e.g., I-125 seeds):Clinical target: V100 ≥ 99% (ABS recommends ≥ 99% coverage)Typical prescription: 145 GyFor cervical HDR brachytherapy:High-risk CTV: V100 ≥ 90–95%Intermediate-risk CTV: V100 ≥ 90%V100 is a primary quality metric — low coverage indicates underdosed tumor regions. Related metrics: V150 (cold spots from source spacing), V200 (hot spots from seed clustering)....

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG007](../screenshots/35_REG007.png)

---

### ✅ REG008

**Input:** Is this plan acceptable? V100=93%, D90=98%, V150=52%...

**Response:**
> **Borderline — does not meet standard ABS targets for monotherapy.**| Metric | Your Plan | ABS Target | Status ||--------|-----------|------------|--------|| V100 | 93% | ≥ 99% | ⚠️ Low || D90 | 98% | ≥ 100% | ⚠️ Low || V150 | 52% | 30–60% | ✅ Acceptable |**Assessment:**- **V100 93%** falls below the ABS ≥99% threshold for permanent seed implantation. This leaves ~7% of the prostate underdosed.- **D90 98%** means only 98% of the target receives the prescription dose minimum.- **V150 52%** is within the typical 30–60% range, indicating acceptable hot spot distribution.**Recommendation:** Consider adding seeds to improve coverage, particularly in the deficient region. If the 93% V100 is localized to a small volume away from the urethra, clinical judgment applies.For **boost cases...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG008](../screenshots/35_REG008.png)

---

### ✅ REG009

**Input:** Tell me about HDR cervical cancer protocol...

**Response:**
> ## HDR Cervical Cancer Brachytherapy Protocol### Target Volumes (GEC-ESTRO)| Volume | Description | Dose Goal ||--------|-------------|-----------|| **High-risk CTV (HR-CTV)** | Visible tumor + cervix | D90 ≥ 90–95% Rx || **Intermediate-risk CTV (IR-CTV)** | HR-CTV + 5–10 mm margin | D90 ≥ 90% Rx || **Low-risk CTV (LR-CTV)** | Initial tumor extent | Complete response |### Dose Prescriptions (Common Schemes)| Fractionation | Total Dose | Reference Point ||---------------|------------|------------------|| 4 fractions | 7 Gy × 4 (EQD2 ~ 50 Gy) | Point A or image-based || 5 fractions | 6 Gy × 5 (EQD2 ~ 48 Gy) | Image-based || 2 fractions | 9.5 Gy × 2...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG009](../screenshots/35_REG009.png)

---

### ✅ REG010

**Input:** Save this case for future reference...

**Response:**
> To save a case, I need the case data. Please provide:Case ID (optional, or I'll generate one)Plan data — structure metrics, dose values, organ names, cancer typeExample format:📋{  "cancer_type": "prostate",  "v100": 93,  "d90": 98,  "v150": 52,  "seeds": [...],  "notes": "..."}Or describe the case and I'll structure it....

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![REG010](../screenshots/35_REG010.png)

---

