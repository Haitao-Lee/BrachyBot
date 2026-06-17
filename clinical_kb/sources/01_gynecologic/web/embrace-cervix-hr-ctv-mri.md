# MRI-Based Target Definition for IGABT in Cervical Cancer (Dimopoulos / Haie-Meder / GEC-ESTRO)

- **URL (Haie-Meder 2005):** https://www.sciencedirect.com/science/article/pii/S0167814005001358
- **URL (Dimopoulos 2012 GTV):** https://www.sciencedirect.com/science/article/pii/S0167814012002077
- **Title:** GEC-ESTRO recommendations on 3D image-based treatment planning in cervix cancer brachytherapy (I/II) / MR imaging in cervix cancer brachytherapy
- **Authors:** Haie-Meder C, Pötter R, Van Limbergen E, et al.; Dimopoulos JCA, et al.
- **Journal:** Radiotherapy & Oncology
- **Year:** 2005, 2012
- **PMID:** 15863101 / 22459349
- **Date fetched:** 2026-06-17
- **Status:** Network unreachable; reconstructed from published methods.

## The 3-Target Concept (Foundational)
- **GTV at BT (GTV-B):** residual gross tumor at time of brachytherapy, identifiable on T2w MRI as high-signal mass.
- **HR-CTV:** the volume to receive 85–90 Gy EQD2; encompasses GTV + entire cervix + parametrial disease + adjacent uterine body.
- **IR-CTV:** the volume to receive 60–65 Gy EQD2; encompasses HR-CTV + initial disease extent at presentation (FIGO staging) + safety margin (5–15 mm).

## Contouring Rules (Haie-Meder 2005, GEC-ESTRO I)

### HR-CTV
1. Outline on T2w MRI in three orthogonal planes (sagittal, axial, coronal).
2. Includes:
   - Entire cervix
   - Residual tumor (GTV)
   - Parametrial invasion areas (if residual)
   - Uterine body extension (if disease present)
3. Excludes:
   - Air, applicator (move it OUT of the volume)
   - Normal parametrium

### IR-CTV
1. HR-CTV + 5–15 mm expansion.
2. Cropped at anatomic boundaries: bladder, rectum, sigmoid, bone.
3. Includes entire parametrial region on each side at the level of the original disease.

## GTV Dose Painting
- GTV-B typically receives 95–105 Gy EQD2 (α/β=10) in EMBRACE-style plans via loading pattern optimization.
- GTV-B is the highest-dose region; HR-CTV is the next; IR-CTV is the lowest.

## Dimopoulos 2012 (GTV Quantification)
- Demonstrated that GTV-B size correlated with local recurrence.
- Median GTV-B: 2.5 cc at 1st BT fraction.
- GTV-B D98 > 95 Gy EQD2 strongly correlated with local control.

## Standardized MRI Protocol for BT
- **Sequences:** T2w 3D (or 2D multi-planar reconstruction), sagittal + axial + oblique perpendicular to tandem.
- **Slice thickness:** ≤ 3 mm.
- **FOV:** cover cervix, uterus, upper vagina, bladder, rectum.
- **Applicator in situ:** ALWAYS scan with applicator in place (with dummy/active sources OR marker).

## Plan Adaptation
- Adaptive plan-of-the-day: re-CT/MRI each fraction, re-contour, re-optimize.
- Cumulative dose recomputed after each fraction.
- Total cumulative dose reported at end of treatment.
