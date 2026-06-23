---
title: "Towards U-Net-based intraoperative 2D dose prediction in high dose rate prostate brachytherapy"
year: 2020
journal: "Various"
doi: ""
pmid: "39668102"
url: "https://pubmed.ncbi.nlm.nih.gov/39668102/"
fetched_date: "2026-06-17"
fetch_method: "title-verified"
doc_type: "review"
category: "02_prostate_gu"
priority: "P2"
---

# Towards U-Net-based intraoperative 2D dose prediction in high dose rate prostate brachytherapy

**PMID:** 39668102 | **DOI:** 

## Abstract

id="eng-abstract">
Background:
Poor needle placement in prostate high-dose-rate brachytherapy (HDR-BT) results in sub-optimal dosimetry and mentally predicting these effects during HDR-BT is difficult, creating a barrier to widespread availability of high-quality prostate HDR-BT.
Purpose:
To provide earlier feedback on needle implantation quality, we trained machine learning models to predict 2D dosimetry for prostate HDR-BT on axial TRUS images.
Methods and materials:
Clinical treatment plans from 248 prostate HDR-BT patients were retrospectively collected and randomly split 80/20 for training/testing. Fifteen U-Net models were implemented to predict the 90%, 100%, 120%, 150%, and 200% isodose levels in the prostate base, midgland, and apex. Predicted isodose lines were compared to delivered dose using Dice similarity coefficient (DSC), precision, recall, average symmetric surface distance, area percent difference, and 95th percentile Hausdorff distance. To benchmark performance, 10 cases were retrospectively replanned and compared against the clinical plans using the same metrics.
Results:
Models predicting 90% and 100% isodose lines at midgland performed best, with median DSC of 0.97 and 0.96, respectively. Performance declined as isodose level increased, with median DSC of 0.90, 0.79, and 0.65 in the 120%, 150%, and 200% models. In the base, median DSC was 0.94 for 90% and decreased to 0.64 for 200%. In the apex, median DSC was 0.93 for 90% and decreased to 0.63 for 200%. Median prediction time was 25 ms.
Conclusion:
U-Net models accurately predicted HDR-BT isodose lines on 2D TRUS images sufficiently quickly for real-time use. Incorporating auto-segmentation algorithms will allow intra-operative feedback on needle implantation quality.
