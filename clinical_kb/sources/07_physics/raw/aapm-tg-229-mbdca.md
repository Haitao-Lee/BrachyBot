---
title: "A generic high-dose rate (192)Ir brachytherapy source for evaluation of model-based dose calculations beyond the TG-43 formalism"
year: 2012
journal: "Medical Physics"
doi: "10.1118/1.4750258"
pmid: "26127057"
url: "https://pubmed.ncbi.nlm.nih.gov/26127057/"
fetched_date: "2026-06-17"
fetch_method: "title-verified"
doc_type: "task_group_report"
category: "07_physics"
priority: "P0"
---

# A generic high-dose rate (192)Ir brachytherapy source for evaluation of model-based dose calculations beyond the TG-43 formalism

**PMID:** 26127057 | **DOI:** 10.1118/1.4750258

## Abstract

id="eng-abstract">
Purpose:
In order to facilitate a smooth transition for brachytherapy dose calculations from the American Association of Physicists in Medicine (AAPM) Task Group No. 43 (TG-43) formalism to model-based dose calculation algorithms (MBDCAs), treatment planning systems (TPSs) using a MBDCA require a set of well-defined test case plans characterized by Monte Carlo (MC) methods. This also permits direct dose comparison to TG-43 reference data. Such test case plans should be made available for use in the software commissioning process performed by clinical end users. To this end, a hypothetical, generic high-dose rate (HDR) (192)Ir source and a virtual water phantom were designed, which can be imported into a TPS.
Methods:
A hypothetical, generic HDR (192)Ir source was designed based on commercially available sources as well as a virtual, cubic water phantom that can be imported into any TPS in DICOM format. The dose distribution of the generic (192)Ir source when placed at the center of the cubic phantom, and away from the center under altered scatter conditions, was evaluated using two commercial MBDCAs [Oncentra(®) Brachy with advanced collapsed-cone engine (ACE) and BrachyVision ACUROS™ ]. Dose comparisons were performed using state-of-the-art MC codes for radiation transport, including ALGEBRA, BrachyDose, GEANT4, MCNP5, MCNP6, and PENELOPE2008. The methodologies adhered to recommendations in the AAPM TG-229 report on high-energy brachytherapy source dosimetry. TG-43 dosimetry parameters, an along-away dose-rate table, and primary and scatter separated (PSS) data were obtained. The virtual water phantom of (201)(3) voxels (1 mm sides) was used to evaluate the calculated dose distributions. Two test case plans involving a single position of the generic HDR (192)Ir source in this phantom were prepared: (i) source centered in the phantom and (ii) source displaced 7 cm laterally from the center. Datasets were independently produced by different investigators. MC results were then compared against dose calculated using TG-43 and MBDCA methods.
Results:
TG-43 and PSS datasets were generated for the generic source, the PSS data for use with the ace algorithm. The dose-rate constant values obtained from seven MC simulations, performed independently using different codes, were in excellent agreement, yielding an average of 1.1109 ± 0.0004 cGy/(h U) (k = 1, Type A uncertainty). MC calculated dose-rate distributions for the two plans were also found to be in excellent agreement, with differences within type A uncertainties. Differences between commercial MBDCA and MC results were test, position, and calculation parameter dependent. On average, however, these differences were within 1% for ACUROS and 2% for ace at clinically relevant distances.
Conclusions:
A hypothetical, generic HDR (192)Ir source was designed and implemented in two commercially available TPSs employing different MBDCAs. Reference dose distributions for this source were benchmarked and used for the evaluation of MBDCA calculations employing a virtual, cubic water phantom in the form of a CT DICOM image series. The implementation of a generic source of identical design in all TPSs using MBDCAs is an important step toward supporting univocal commissioning procedures and direct comparisons between TPSs.
