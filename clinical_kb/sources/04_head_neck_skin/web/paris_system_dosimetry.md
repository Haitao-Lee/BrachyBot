# Paris System for Interstitial Brachytherapy Dosimetry (Head & Neck applications)

- **URL**: https://www.thegreenjournal.com/article/S0167-8140(18)30114-6/fulltext
- **Also**: ICRU Report 58 (1997), ICRU Report 89 (2016 update)
- **Document type**: International dosimetry system (ICRU report + GEC-ESTRO)
- **Date accessed**: 2026-06-17 (webfetch blocked; content from training knowledge of the Paris dosimetry system)

## Overview
The Paris system is the original LDR interstitial dosimetry system, designed for iridium-192 wire implants. It provides uniform dose to the implant volume when catheters are placed in a regular geometric pattern with:
- Equal catheter spacing (typically 10–15 mm)
- Equal active (treatment) length
- Linear source arrangement (parallel catheters, equidistant)

## Key Dose-Volume Definitions
- **Basal dose (D_B)**: dose at the cross-section center of the implant (manually calculated, or minimum inter-catheter distance isocenter)
- **Reference dose (D_ref)**: typically 85% of the basal dose (D_B) in Paris system
- **Minimum target dose (MTD) / D_min**: lowest dose on the envelope of CTV — corresponds to the isodose surface that just encompasses the CTV
- **High-dose regions**: areas > 150% of D_B (avoid within target)

## Rules
- Implant volume = volume of "central" plane region of all sources
- Active length ≥ 1.0–1.5 × the target diameter
- For implants with N catheters, the reference isodose should encompass the target while sparing outside normal tissue
- Uniform spacing: 1.0–1.5 cm typical for head & neck
- For tongue, floor of mouth: 0.5–1.0 cm spacing (small volumes, geometry more variable)

## Head and Neck Application Examples
- **Tongue (T1–T2)**: 3–5 plastic tubes, 1.0–1.5 cm spacing, dose 60–65 Gy LDR (or HDR equivalent)
- **Floor of mouth**: 3–6 tubes in 2 planes (loop technique) for adequate coverage of mucosa
- **Lip**: 2–4 tubes or surface mold; 1 plane generally sufficient
- **Buccal mucosa**: 3–5 tubes on outer surface, 1.0–1.5 cm spacing

## Dose Uniformity
- Homogeneity index (HI = V100/V150): ≥ 0.6 acceptable
- Dose gradient: 5–10% per mm near catheters
- Critical structures (mandible, mucosa opposite): dose should be < 80% of D_ref
- V100 of PTV ≥ 90% typically required for adequate coverage

## Modern Implementation
- HDR and PDR can use Paris-equivalent stepping source positions
- CT-based 3D planning with inverse optimization (IPSA/HO) is now standard
- D90 (dose covering 90% of CTV) used as the prescription metric in modern planning
- GEC-ESTRO recommends GTV + 0.5–1.0 cm margin = HR-CTV for boost
- ICRU 89 (2016) provides modern recommendations for interstitial implants
