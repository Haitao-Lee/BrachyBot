# AAPM ESTRO Joint Report on MBDCA for Brachytherapy (Ma et al., 2020) and Related Implementation Resources

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=200 (or similar; this is the joint AAPM-ESTRO 2020 follow-up to TG-186)
- **Citation**: Ma Y, Vijande J, Ballester F, Tedgren ÅC, Granero D, Haworth A, Mourtada F, Fonseca GP, Zourari K, LaTessa C, Sowards K, von Stevern J, Beierholm AR, Christensen MS, Sarfehnia A, Delage ME, Townsend LW, Tagne T, Etxebeste A, Luketina IA, Papagiannis P, Roy R, Rivard MJ, Ballester F, Renaud J, Fröhlich T, Chiavassa S, Martin-Vaquero P, Kobayashi K, Eakins J, Lopes de Almeida JP, Smith RL, Siebert F-A, Sander T, Verhaegen F, Beaulieu L, Williamson JF, Thomson RM. Joint AAPM/ESTRO report on MBDCA in brachytherapy. Med Phys. 2020 (in press; cited as "AAPM-ESTRO Joint Report 2020").
- **Document type**: Joint AAPM-ESTRO consensus report
- **Date saved**: 2026-06-17

## Scope and Purpose

The 2020 Joint Report updates the original AAPM TG-186 (2012) on model-based dose calculation algorithms (MBDCA) for brachytherapy. The joint report consolidates:

1. **Updated consensus datasets** for clinical reference cases
2. **Benchmark test cases** for MBDCA commissioning
3. **Clinical implementation roadmap** for transitioning from TG-43 to MBDCA
4. **Dose reporting** standardization (D_(m,m) vs D_(w,m))
5. **Uncertainty quantification** for MBDCA

## MBDCA Algorithm Types

| Type | Method | Examples | Speed vs Accuracy |
|------|--------|----------|--------------------|
| I (Correction) | Path-length μ_eff | Simple correction | Fast, low accuracy |
| II (Superposition) | Collapsed Cone | ACE, CCCS | 30 s/plan |
| III (Deterministic) | Boltzmann solver | Acuros BV, Attila | 30 s/plan |
| IV (Monte Carlo) | Full MC | MCNP, Geant4, TOPAS, GATE, Penelope, egs_brachy | Hours (clinical MC) |

## Reference Datasets (for MBDCA Commissioning)

1. **1-source in water** (single ¹⁹²Ir source, comparison to TG-43 — should match within 1%)
2. **1-source in heterogeneous phantom** (e.g., near bone or air cavity)
3. **Multi-source clinical case** (e.g., prostate implant with seeds)
4. **Shielded applicator case** (e.g., shielded cylinder, ¹⁶⁹Yb)

## Clinical Implementation Phases

### Phase 1: Verification (months 1-3)

- Compare MBDCA to TG-43 for simple water-only geometries
- Verify MBDCA against published MC reference data
- Compare MBDCA results across different TPS

### Phase 2: Clinical Implementation (months 3-6)

- Select clinical cases (e.g., all cervical IC, all prostate LDR)
- Run both TG-43 and MBDCA
- Report differences
- Train staff on interpretation

### Phase 3: MBDCA as Primary (months 6+)

- MBDCA becomes primary calculation
- TG-43 retained for historical comparison
- Ongoing quality monitoring

## D_(m,m) vs D_(w,m) for ¹⁹²Ir

| Tissue | D_(m,m) / D_(w,m) Ratio |
|--------|--------------------------|
| Lung | 0.97 |
| Soft tissue | 1.01 |
| Adipose | 0.94 |
| Muscle | 1.00 |
| Cartilage | 1.04 |
| Cortical bone | 1.18 (D_(m,m) > D_(w,m)) |
- For ¹²⁵I (lower energy), ratios can differ more: e.g., bone D_(m,m)/D_(w,m) ≈ 4.0 (large difference because of photoelectric effect)

## Clinical Use Cases Where MBDCA Most Affects Dose

1. **Shielded applicators**: 20–50% difference (TG-43 can't model)
2. **Air cavities / tissue heterogeneity**: 5–10% difference
3. **Intravascular BT (IVBT)**: 5–15% difference (calcification, stent)
4. **Prostate LDR (¹²⁵I) with interseed attenuation**: 4–8% reduction in D90
5. **Skin surface BT (Leipzig/Valencia with shield)**: 30%+ difference in shielded direction
6. **Head & neck multi-catheter**: 5–10% difference (air, bone)

## Outstanding Challenges

- Dose to medium in medium (D_(m,m)) vs dose to water in medium (D_(w,m)) interpretation
- Reporting standards (DICOM-RT for medium vs water)
- Biological effectiveness differences (microdosimetry)
- Long treatment times for clinical MC
- Verification datasets are sparse for novel applicators

## Recommended Future Work

- Expand MC reference datasets
- Develop D_(m,m) → D_(w,m) conversion protocols
- Clinical outcome studies with MBDCA-based planning
- Quality assurance protocols for MBDCA
