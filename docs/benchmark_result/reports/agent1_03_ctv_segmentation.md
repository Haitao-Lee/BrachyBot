# Agent 1 Benchmark Report - 03_ctv_segmentation

**Generated:** 2026-06-03 12:53:47
**Agent:** 1
**Category:** 03_ctv_segmentation

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Tests | 25 |
| Passed | 25 |
| Failed | 0 |
| Pass Rate | 100.0% |
| Avg Score | 0.972 |

## Detailed Results

### ✅ Q0101

**Input:** Please segment the clinical target volume (CTV) for a prostate cancer brachytherapy case. The CT scan shows the prostate with the following characteristics: the prostate volume is approximately 35cc, there is no extraprostatic extension visible, and the patient has intermediate-risk disease with Gleason 3+4. Include the entire prostate gland with a minimal margin for microscopic disease....

**Response:**
> No CT scan is currently loaded in the system. To perform CTV segmentation, please upload the patient's CT scan first.Once the CT is loaded, I can perform accurate prostate segmentation based on the actual imaging data. The segmentation will include:CTV = Prostate gland (for brachytherapy, no additional margin is added to the prostate as the technique inherently accounts for microscopic extension)For intermediate-risk disease (Gleason 3+4), the entire prostate is treatedSeminal vesicles may be partially included based on clinical indicationPlease upload the CT scan to proceed with segmentation....

**Scores:**
- Total: 0.94
- Keyword: 0.83
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0101](../screenshots/03_Q0101.png)

---

### ✅ Q0102

**Input:** I need you to segment the HR-CTV for a cervical cancer patient receiving HDR brachytherapy with tandem and ovoids. The MRI shows a 4cm cervical tumor with 1cm parametrial extension on the right side. The applicator is in good position. Please delineate the high-risk clinical target volume including the entire cervix and any visible residual tumor....

**Response:**
> No CT scan is currently loaded in the system. I cannot perform segmentation without imaging data.However, I can describe the **HR-CTV delineation** based on GEC-ESTRO guidelines for your clinical scenario:## HR-CTV Delineation for Cervical Cancer Brachytherapy**Based on GEC-ESTRO recommendations:**### HR-CTV should include:1. **Entire cervix** - the entire cervical stroma2. **Gross tumor volume (GTV)** - visible residual disease3. **Parametrial tissue** - extending to involve the 1cm right parametrial extension4. **Applicator-adjacent tissue** - tissue immediately surrounding the tandem and ovoids### For your case (4cm tumor + 1cm right parametrial extension):| Structure | Description ||-----------|-------------|| Cervix | Entire cervical stroma (approximately 3-...

**Scores:**
- Total: 0.95
- Keyword: 0.86
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0102](../screenshots/03_Q0102.png)

---

### ✅ Q0103

**Input:** Please segment the clinical target volume for an endometrial cancer patient receiving vaginal cuff brachytherapy. The patient had a total hysterectomy for Stage IB endometrial cancer. The vaginal cuff is visible on CT with no residual disease. Define the treatment volume for the vaginal cuff boost....

**Response:**
> No CT scan is currently loaded in the system. I will answer from clinical knowledge regarding vaginal cuff brachytherapy CTV definition.## Vaginal Cuff Brachytherapy CTV Definition (Endometrial Cancer)### Standard CTV Delineation for VBT BoostFor **Stage IB endometrial cancer** with no residual disease after TAH-BSO, the vaginal cuff CTV typically includes:| Structure | Description ||-----------|-------------|| **Vaginal Cuff** | Proximal 3-5 cm of vaginal apex (or entire vaginal length if high-risk features) || **Peri-vaginal tissue** | 0.5-1.0 cm radial margin around vaginal wall |### Clinical Considerations by Risk Level**Low-intermediate risk (GOG 99 criteria...

**Scores:**
- Total: 0.94
- Keyword: 0.83
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0103](../screenshots/03_Q0103.png)

---

### ✅ Q0104

**Input:** I have a CT scan for a patient with anal cancer receiving chemoradiation followed by brachytherapy boost. The tumor is a 3cm lesion at the anal canal. Please segment the gross tumor volume (GTV) and clinical target volume (CTV) for the brachytherapy boost portion of treatment....

**Response:**
> No CT scan is currently loaded in the system. However, I can provide guidance on GTV and CTV delineation for anal cancer brachytherapy boost based on standard clinical practice:## Anal Cancer Brachytherapy Boost - Target Volume Delineation### GTV (Gross Tumor Volume)For a 3 cm lesion at the anal canal:- **Primary GTV**: Visible tumor extent on examination and imaging- Include the entire visible lesion at the anal canal- Should encompass the 3 cm lesion with adequate proximal-distal margins on the anal canal wall### CTV (Clinical Target Volume)For brachytherapy boost after EBRT (typically 30.6-36 Gy in 1.8 Gy fractions):**CTV_T:**- Primary tumor bed plus microscopic disease- Proximal margin: 1-2 cm above GTV superior extent- Distal margin: 1-...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0104](../screenshots/03_Q0104.png)

---

### ✅ Q0105

**Input:** Please segment the CTV for a patient with a recurrent head and neck cancer in the oral tongue. The CT shows a 2.5cm recurrent squamous cell carcinoma in the left lateral tongue. Define the clinical target volume for interstitial brachytherapy, including the visible tumor and appropriate margins for microscopic spread....

**Response:**
> No CT scan is currently loaded. I'll answer from clinical knowledge regarding CTV delineation for oral tongue interstitial brachytherapy.## CTV Delineation for Oral Tongue Brachytherapy### GTV (Gross Tumor Volume)- Visible tumor on imaging and clinical examination- Include the 2.5 cm recurrent lesion in the left lateral tongue- May require MRI/T PET for accurate soft tissue delineation### CTV_T (Treatment CTV)For interstitial brachytherapy of oral tongue recurrence:| Component | Margin | Rationale ||-----------|--------|-----------|| GTV → CTV_0 | 5-10 mm | Microscopic disease extension || Optional | 3-5 mm anisotropic | May reduce posterior margin near mandible |### CTV_Clinical...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0105](../screenshots/03_Q0105.png)

---

### ✅ Q0106

**Input:** For a breast cancer patient undergoing APBI with MammoSite, please segment the lumpectomy cavity and the planning target volume (PTV). The CT shows the lumpectomy cavity in the upper outer quadrant of the left breast with no surgical clips visible. Define appropriate margins for the PTV....

**Response:**
> No CT scan is currently loaded in the system. To perform accurate lumpectomy cavity and PTV segmentation, please upload the patient's CT scan first.However, I can provide guidance on **MammoSite APBI planning principles** based on clinical knowledge:---## MammoSite APBI: Target Volume Definition### Lumpectomy Cavity (LC) Delineation**Without surgical clips**, the cavity is defined by:- **CT evidence** of seroma (fluid collection, surgical changes)- **Symmetry** comparison with contralateral breast- **Clips placed at surgery** (if available) define cavity margins- If cavity poorly visualized, consider **ultrasound-guided** cavity delineation** Cavity Visualization Score (CVS):**| Score...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0106](../screenshots/03_Q0106.png)

---

### ✅ Q0107

**Input:** I need to segment the CTV for a patient with vaginal cancer. The tumor involves the upper third of the vagina, extending from the vaginal cuff to approximately 4cm distally. Please delineate the GTV and CTV for HDR brachytherapy, including the visible tumor and adjacent vaginal mucosa....

**Response:**
> No CT scan is currently loaded in the system. I cannot perform actual image segmentation, but I can provide the clinical guidelines for vaginal cancer brachytherapy CTV delineation:## Vaginal Cancer Brachytherapy CTV Delineation**GTV (Gross Tumor Volume):**- Visible tumor extent on clinical exam and imaging- Include any vaginal wall thickening or enhancement**CTV for Upper 1/3 Vaginal Tumor (per GEC-ESTRO):| Segment | Coverage ||---------|----------|| **CTV-T** | 3-4 cm vaginal length from tumor margin || **Lateral** | Entire vaginal circumference (2-3 cm width) || **Longitudinal** | From vaginal cuff to 2-3 cm beyond visible tumor |**Standard CTV Margins:**- Longitudinal: 2-3 cm superior and inferior to visible tumor- Radial: Full vaginal wall thickness (1.5-2 cm diameter typical)- Vag...

**Scores:**
- Total: 0.87
- Keyword: 0.62
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0107](../screenshots/03_Q0107.png)

---

### ✅ Q0108

**Input:** Please segment the prostate CTV for a patient with high-risk prostate cancer (Gleason 8, PSA 22, Stage T3a). The CT shows possible extraprostatic extension on the left side. Include the entire prostate and the region of suspected EPE with appropriate margins....

**Response:**
> No CT scan is currently loaded. To perform prostate CTV segmentation, please upload the patient's CT scan first.For high-risk prostate cancer (Gleason 8, PSA 22, T3a with suspected EPE), the CTV typically includes:CTV = Prostate + Region of EPEEntire prostate glandSuspected EPE region with 3-5 mm margin in the direction of EPESeminal vesicles (bases included for T3a)No additional whole-pelvis margin needed for brachytherapy boostFor a combined EBRT + brachytherapy approach, the EBRT CTV would be different (includes pelvic lymph nodes), but for brachytherapy monotherapy or boost, the CTV is typically the prostate + suspected extraprostatic disease.Please upload the CT scan so I can perform the actual segmentation based on the imaging data....

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0108](../screenshots/03_Q0108.png)

---

### ✅ Q0109

**Input:** I have a CT scan for a patient with gallbladder cancer. The tumor is unresectable and interstitial brachytherapy is planned. Please segment the GTV encompassing the visible gallbladder tumor and define the CTV with appropriate margins considering the adjacent liver parenchyma and duodenum....

**Response:**
> No CT scan is currently loaded in the system. I cannot perform the actual segmentation.However, I can provide guidance on GTV/CTV definition for gallbladder cancer interstitial brachytherapy:## Gallbladder Cancer Brachytherapy GTV/CTV**GTV (Gross Tumor Volume)**- Visible tumor in gallbladder wall- Any soft tissue mass extending into adjacent structures- Involved lymph nodes (portocaval, celiac)- Use contrast-enhanced CT/MRI for delineation**CTV (Clinical Target Volume)**- GTV + 5-10 mm margin for microscopic extension- Consider adjacent liver segment IVb/V (frequent invasion route)- Duodenal margin if tumor abuts duodenum- No formal consensus guidelines for gallbladder brachytherapy margins**Critical OARs**- Liver parenchyma- Duodenum (especially D1...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0109](../screenshots/03_Q0109.png)

---

### ✅ Q0110

**Input:** For a patient with rectal cancer at 3cm from the anal verge, please segment the CTV for brachytherapy boost after external beam chemoradiation. Include the tumor bed, mesorectal region, and perirectal lymph node stations in the CTV definition....

**Response:**
> No CT scan is currently loaded for this patient. I cannot perform actual segmentation without the imaging data.## Rectal Cancer Brachytherapy Boost — CTV DefinitionBased on clinical guidelines for rectal cancer brachytherapy boost:### GTV (Gross Tumor Volume)- Visible residual tumor or tumor bed on post-nCRT imaging- For 3cm from anal verge: GTV includes the rectal wall abnormality### CTV (Clinical Target Volume)**Superior-Inferior Extent:**- From 2 cm above the GTV/tumor bed superiorly- To 1 cm below the anal verge inferiorly**Radial Extent:**- Entire rectal wall (all quadrants) in the region of interest- Mesorectal fat (5-10 mm radial margin around rectal wall)- Perirectal soft tissue**Lymph Node CTV (if involved):**- Include perirectal, mesorectal, and presacral lymph node stations if involved- Typically 5-10 mm margin around suspicious...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0110](../screenshots/03_Q0110.png)

---

### ✅ Q0111

**Input:** Please segment the HR-CTV and IR-CTV for a cervical cancer case with a larger tumor. The MRI shows a 6cm cervical tumor with bilateral parametrial invasion extending to the pelvic sidewall on the right. The tandem and ovoids are in place. Define both high-risk and intermediate-risk target volumes....

**Response:**
> ## HR-CTV and IR-CTV Contouring for Locally Advanced Cervical Cancer### Clinical ContextThis is a **T3b cervical cancer** with bilateral parametrial invasion reaching the right pelvic sidewall. Per GEC-ESTRO/ESTRO guidelines, this requires careful multi-level target definition.---### High-Risk CTV (HR-CTV)**Definition:** Encompasses all residual macroscopic disease visible on imaging.**Contouring Approach:**| Region | Boundaries ||--------|------------|| **Cervix/Primary tumor** | Entire residual cervical mass visible on T2-weighted MRI || **Right parametrium** | Include entire parametrial extension to pelvic sidewall; follow the right ureter laterally || **Left parametrium** | Include parametrial involvement up to the left pelvic sidewall || **Vagina** | Include upper 2-3 cm of vagina (or entire vagina if involved) || ** uterus** | Include if tumor involves corpus |...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0111](../screenshots/03_Q0111.png)

---

### ✅ Q0112

**Input:** I need to segment the treatment volume for a patient with penile cancer. The tumor is on the glans penis, approximately 2cm in diameter, with suspected invasion into the corpus spongiosum. Please define the GTV and CTV for interstitial brachytherapy....

**Response:**
> No CT scan is currently loaded. I can provide the clinical guidance for penile cancer brachytherapy target volume definition based on your description.## Penile Cancer Brachytherapy Target Volumes**Clinical Scenario:** 2cm glans lesion with suspected corpus spongiosum invasion### GTV (Gross Tumor Volume)- Visible tumor on glans including any palpable/visible病变- Entire glans penis if involved- Corpus spongiosum up to 5mm beyond visible tumor (based on suspected invasion)### CTV (Clinical Target Volume)**CTV_T-primary:**- GTV + 5mm radial margin for microscopic extension- Include corpus spongiosum proximal to suspected invasion (minimum 1cm proximal margin)- Entire glans if tumor involves...

**Scores:**
- Total: 0.96
- Keyword: 0.88
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0112](../screenshots/03_Q0112.png)

---

### ✅ Q0113

**Input:** Please segment the target volume for a patient with nasopharyngeal carcinoma receiving intracavitary brachytherapy boost. The post-EBRT CT shows residual mucosal disease in the nasopharynx. Define the CTV for the brachytherapy boost....

**Response:**
> No CT scan is currently loaded in the system. To perform actual segmentation, please upload the patient's CT scan first.**Based on clinical knowledge, nasopharyngeal brachytherapy CTV definition:****GTV (post-EBRT residual disease):**- Visible mucosal abnormality on examination/imaging- Post-EBRT residual typically smaller than initial tumor- Usually confined to nasopharyngeal mucosa**CTV for brachytherapy boost:**- **CTV_high** = GTV + 5-10 mm margin to adjacent mucosa- **CTV_intermediate** = GTV + 5 mm + entire nasopharynx (optional based on institutional protocol)- For intracavitary brachytherapy, CTV typically limited to 1-2 cm in any dimension from applicator**Critical OARs in nasopharynx:**- Brainstem, spinal cord, optic chiasm, optic nerves- Temporally,...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0113](../screenshots/03_Q0113.png)

---

### ✅ Q0114

**Input:** For a patient with a skin cancer on the scalp, please segment the GTV and treatment volume for surface brachytherapy. The lesion is a 3cm basal cell carcinoma with irregular borders. The CT shows no deep invasion. Define the appropriate treatment volume....

**Response:**
> No CT scan is currently loaded. I'll provide the clinical guidance for scalp BCC surface brachytherapy target volume definition based on standard practice.## Surface Brachytherapy Target Volume: Scalp BCC**GTV (Gross Tumor Volume)**- Visible tumor including irregular borders- Entire clinical lesion as seen clinically and on imaging**CTV (Clinical Target Volume)**- GTV + **5-10 mm margin** for microscopic spread- For scalp BCC with irregular borders: use **10 mm margin** (higher risk of subclinical extension)- Include full thickness of skin involved**PTV (Planning Target Volume)**- CTV + **2...

**Scores:**
- Total: 0.91
- Keyword: 0.75
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0114](../screenshots/03_Q0114.png)

---

### ✅ Q0115

**Input:** I have a CT scan for a patient with urethral cancer involving the bulbar urethra. Please segment the GTV and CTV for HDR brachytherapy. The tumor extends approximately 3cm along the urethra. Define the treatment volumes for interstitial brachytherapy....

**Response:**
> No CT scan is currently loaded. To perform actual segmentation, please upload the patient's CT scan.## Urethral Cancer Brachytherapy Volume Definitions**GTV (Gross Tumor Volume):**- Visible tumor extent on cystoscopy/urethroscopy- Documented tumor length on urethrography (approximately 3 cm in this case)- Any palpable/visible extraurethral extension**CTV (Clinical Target Volume):**- GTV + 5-10 mm margin for microscopic spread along urethral mucosa- Proximal margin: 1-2 cm beyond GTV- Distal margin: 1-2 cm beyond GTV- Lateral margin: 3-5 mm into surrounding tissue (accounting for corpus spongiosum involvement)- For bulbar urethral tumors, CTV typically includes the affected urethral segment plus adjacent corpus spongiosum**CTV for 3 cm bulbar urethral tumor:**- Longitudinal: approximately 5-...

**Scores:**
- Total: 0.95
- Keyword: 0.86
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0115](../screenshots/03_Q0115.png)

---

### ✅ Q0116

**Input:** Please segment the CTV for a patient with an anal margin cancer. The tumor is a 4cm lesion at the anal margin extending into the perianal skin. For the brachytherapy boost, define the target volume including the visible tumor and a 1cm margin....

**Response:**
> No CT scan is currently loaded. I can provide the CTV definition methodology for anal margin cancer brachytherapy based on clinical guidelines:## CTV Definition for Anal Margin Cancer Brachytherapy Boost**GTV (Gross Tumor Volume)**- Visible tumor + perianal extension (4 cm lesion)- Include any areas of ulceration or induration**CTV (Clinical Target Volume)**- GTV + **1 cm margin** in all directions- Include the entire perianal skin region within 1 cm of visible tumor- For superficial lesions: extend to dermis- For lesions approaching the anal canal: include 1 cm distal to the dentate line**PTV (Planning Target Volume)** - if used- CTV + 3-5 mm margin for geometric uncertainty## Key Considerations...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0116](../screenshots/03_Q0116.png)

---

### ✅ Q0117

**Input:** For a pancreatic cancer patient receiving intraoperative brachytherapy, please segment the tumor bed CTV. The patient had a partial resection with positive margins at the portal vein confluence. Define the CTV for the intraoperative HDR boost....

**Response:**
> ## Pancreatic Cancer Intraoperative Brachytherapy (IORT) - CTV Definition### Clinical Context- Partial resection with positive margins at portal vein confluence- IORT boost performed at time of surgery- Typically used for locally advanced pancreatic cancer with margin concerns### CTV Definition for Pancreatic IORT**GTV = Residual tumor bed + positive margin region**- Surgical bed at pancreatic bed/duodenal sweep- Region of positive surgical margins (portal vein confluence)- Any suspicious soft tissue adjacent to major vessels**CTV = GTV + 1.0-1.5 cm margin** (in non-fixed anatomy, intraoperative setting)- Accounts for microscopic extension- Modified by anatomic boundaries (vertebral body, major vessels)- For positive...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0117](../screenshots/03_Q0117.png)

---

### ✅ Q0118

**Input:** I need to segment the treatment volume for a patient with vulvar cancer. The primary tumor is on the left labium majus with a 3cm lesion. There is also a separate satellite lesion on the right labium minus. Define the GTV and CTV for interstitial brachytherapy covering both lesions....

**Response:**
> No CT scan is currently loaded in the system. I cannot perform actual image segmentation without the scan, but I can provide the clinical guidelines for vulvar cancer brachytherapy target volume delineation.## Vulvar Cancer Brachytherapy Target Volume Definition**GTV (Gross Tumor Volume):**- Primary lesion: 3 cm on left labium majus- Satellite lesion: right labium minus- Include all visible disease identified on clinical examination and imaging**CTV (Clinical Target Volume):**- **CTV_Tumor**: GTV + 1.5-2.0 cm radial margin for microscopic spread- **CTV_Surgical_Bed**: If post-operative, include operative bed with margin- **CTV_Elective**: May include regional tissues at risk based on clinical stage**For T2-T3 vulvar cancer with positive lymph nodes:**- CTV should include bilateral inguinal-femoral lymph node regions- Consider superficial inguinal nodes for lateral...

**Scores:**
- Total: 0.95
- Keyword: 0.86
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0118](../screenshots/03_Q0118.png)

---

### ✅ Q0119

**Input:** Please segment the CTV for a patient with a urethral recurrence after radical prostatectomy. The CT shows soft tissue at the vesicourethral anastomosis. Define the target volume for salvage HDR brachytherapy including the anastomotic recurrence with appropriate margins....

**Response:**
> No CT scan is currently loaded in the system. I cannot perform segmentation without imaging data.However, I can provide the clinical guidance for defining the CTV for salvage HDR brachytherapy of urethral anastomotic recurrence:## CTV Definition: Post-Prostatectomy Urethral Recurrence### Patient Context- Recurrence at vesicourethral anastomosis after radical prostatectomy- Typically ≥2 years post-prostatectomy- Salvage setting (prior EBRT may or may not have been given)### GTV (Gross Tumor Volume)- Visible soft tissue abnormality at the anastomosis on imaging- Defined on MRI (preferred) or CT with contrast- May be defined by PET-positive disease (Choline, PSMA)### CTV Delineation**CTV_T (...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0119](../screenshots/03_Q0119.png)

---

### ✅ Q0120

**Input:** For a patient with bile duct cancer, I need to segment the GTV and CTV for interstitial brachytherapy. The CT shows a tumor at the hilum of the liver involving the left and right hepatic ducts. Define the target volume considering the tumor extension along the bile ducts....

**Response:**
> No CT scan is currently loaded. I will provide target volume definitions based on clinical guidelines for hilar cholangiocarcinoma (Klatskin tumor) brachytherapy.## Target Volume Definition for Hilar Cholangiocarcinoma Brachytherapy### GTV (Gross Tumor Volume)- Visible tumor at the hepatic hilum involving left and right hepatic ducts- Tumor extension along bile duct margins (typically 1-2 cm beyond visible disease)- Any soft tissue mass at the bifurcation### CTV (Clinical Target Volume)**CTV = GTV + 0.5-1.0 cm margin** for microscopic spread along:- Left hepatic duct (segmental ducts)- Right hepatic duct (segmental ducts)- Common hepatic duct distal margin- Perid...

**Scores:**
- Total: 0.96
- Keyword: 0.89
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0120](../screenshots/03_Q0120.png)

---

### ✅ Q0121

**Input:** Please segment the HR-CTV for a cervical cancer patient treated with MRI-guided brachytherapy. The MRI shows a 3cm residual tumor after 45Gy external beam. The tandem and ring applicator is in place. Define the high-risk CTV based on MRI findings....

**Response:**
> No CT or MRI files are currently loaded in the system. I cannot perform image segmentation without the imaging data.However, I can provide the **clinical guidelines for HR-CTV delineation** for this case:---## HR-CTV Delineation for MRI-Guided Cervical Cancer Brachytherapy### Patient Information- **Tumor:** 3cm residual after 45 Gy EBRT- **Modality:** MRI-guided adaptive brachytherapy (IGABT)- **Applicator:** Tandem and ring in place### HR-CTV Definition (per GEC-ESTRO recommendations)The HR-CTV encompasses all macroscopic disease and high-risk microscopic spread:| Component | Description ||-----------|-------------|| **Primary GTV** | Visible residual tumor on T2-weighted MRI (3cm in this case) || **Cervix** | Entire cervix including any residual thickening...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0121](../screenshots/03_Q0121.png)

---

### ✅ Q0122

**Input:** I have a CT scan for a patient with a parotid gland malignancy. The patient had a superficial parotidectomy and has a positive superficial margin. Please segment the surgical bed CTV for HDR brachytherapy boost with a 1cm margin....

**Response:**
> No CT scan is currently loaded in the system. I cannot perform segmentation without the imaging data.However, I can provide the **clinical CTV definition** for parotid brachytherapy based on standard guidelines:## Parotid Bed CTV for HDR Boost (Positive Margin)**GTV**: Residual disease at the superficial margin identified on pathology/imaging**CTV Delineation Guidelines:**| Structure | Margin | Notes ||-----------|--------|-------|| Surgical bed | 1-1.5 cm | Includes parotid fossa, adjacent soft tissue || Facial nerve pathway | Include | From stylomastoid foramen to pes anserinus || Skin | 5 mm deep | If superficial margin involved || Mastoid tip...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0122](../screenshots/03_Q0122.png)

---

### ✅ Q0123

**Input:** For a patient with a recurrent tumor at the bronchial anastomosis after sleeve resection, please segment the GTV and CTV for endoluminal brachytherapy. The CT shows a 1.5cm nodule at the anastomosis site. Define the target volume for the endoluminal treatment....

**Response:**
> # Endoluminal Brachytherapy Target Volume: Bronchial Anastomosis Recurrence## Case Summary- **Tumor:** 1.5 cm nodule at bronchial anastomosis post-sleeve resection- **Treatment:** Endoluminal HDR brachytherapy---## Target Volume Definition### GTV (Gross Tumor Volume)Based on the 1.5 cm visible nodule on CT:- Contour the enhancing soft tissue lesion at the anastomosis- Include the full thickness of the bronchial wall if involved- Extend proximally and distally to encompass any mucosal abnormality### CTV (Clinical Target Volume)**Longitudinal margins along bronchus:**| Direction | Margin | Rationale ||-----------|--------|-----------|| Proximal | 1.0-1.5 cm | Microscopic extension along bronchial mucosa || Distal | 1.0-1.5 cm | Submucosal lymphatic spread |**Rad...

**Scores:**
- Total: 0.95
- Keyword: 0.86
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0123](../screenshots/03_Q0123.png)

---

### ✅ Q0124

**Input:** Please segment the CTV for a patient with a pediatric pelvic rhabdomyosarcoma. The patient is 6 years old with a bladder neck tumor. After chemotherapy, there is a residual 2cm mass. Define the brachytherapy boost target volume considering the small pelvic anatomy....

**Response:**
> No CT scan is currently loaded. To perform the actual CTV segmentation, please upload the patient's CT scan first.Based on clinical knowledge, here is how the CTV should be defined for pediatric pelvic rhabdomyosarcoma brachytherapy boost:---## Pediatric Pelvic Rhabdomyosarcoma Brachytherapy CTV Definition### Patient Characteristics- 6-year-old (small pelvic anatomy)- Bladder neck location- 2 cm residual after chemotherapy### CTV Definition**GTV (Gross Tumor Volume)**- Visible residual tumor (2 cm mass at bladder neck)- Delineated on post-chemotherapy MRI/CT**CTV (Clinical Target Volume)**For pediatric rhabdomyosarcoma, margins must balance cure with long-term toxicity:| Component | Margin ||-----------|--------|| GTV → CTV | 1.0-1.5 cm (3D radial) || Microscopic spread | 0...

**Scores:**
- Total: 1.00
- Keyword: 1.00
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0124](../screenshots/03_Q0124.png)

---

### ✅ Q0125

**Input:** I need to segment the target volumes for a patient with advanced cervical cancer undergoing MRI-guided adaptive brachytherapy. The pre-treatment MRI shows a 7cm tumor with bladder wall invasion and bilateral parametrial extension. Please segment the pre-treatment GTV, HR-CTV, and IR-CTV....

**Response:**
> No CT scan is currently loaded. I cannot perform image segmentation without patient imaging data.However, I can explain the **target volume delineation** for this case based on the clinical description:## Target Volume Definitions for Advanced Cervical Cancer (7cm with bladder invasion)### 1. GTV (Gross Tumor Volume)Based on MRI findings:- Entire cervical mass (7cm)- Bladder wall invasion region- Both parametria (tumor extension to pelvic sidewalls)### 2. HR-CTV (High-Risk CTV)Per GEC-ESTRO guidelines:- Entire cervix (if present)- Entire GTV- Entire bladder wall region with invasion- Both parametria (to pelvic sidewall)- Upper vagina (if involved)### 3. IR-CTV (Intermediate-Risk CTV)-...

**Scores:**
- Total: 0.92
- Keyword: 0.78
- Completeness: 1.00
- Safety: 1.00
- Accuracy: 1.00
- Ux: 1.00
- Language: 1.00

**Screenshot:**
![Q0125](../screenshots/03_Q0125.png)

---

