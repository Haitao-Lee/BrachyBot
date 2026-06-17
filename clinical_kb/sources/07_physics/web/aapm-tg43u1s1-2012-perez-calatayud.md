# AAPM TG-43U1S1 — Supplement to TG-43U1 (Perez-Calatayud et al., 2012)

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=105
- **Citation**: Perez-Calatayud J, Ballester F, Das RK, DeWerd LA, Ibbott GS, Meigooni AS, Ouhib Z, Rivard MJ, Sloboda RS, Williamson JF. Dose calculation for photon-emitting brachytherapy sources with average energy higher than 50 keV: Report of the AAPM and ESTRO. Med Phys. 2012;39(5):2904-2929.
- **Document type**: AAPM/ESTRO joint consensus guideline
- **Date saved**: 2026-06-17

## Scope

- HDR ¹⁹²Ir (>380 keV avg), ⁶⁰Co, ¹⁶⁹Yb, ⁷⁵Se
- LDR ¹³⁷Cs, ⁶⁰Co, ¹⁹⁸Au
- Sources with average emitted photon energy > 50 keV (i.e., high-energy emitters where photoelectric effect in tissue is small)

## Key Contributions

1. **Consensus datasets** for 11 high-energy emitter models (4 HDR ¹⁹²Ir, 1 HDR ⁶⁰Co, 1 HDR ¹⁶⁹Yb, 1 LDR ⁶⁰Co, 1 LDR ¹³⁷Cs, 1 LDR ¹⁹⁸Au)
2. Updated uncertainty analysis methodology
3. **Consensus Λ values** for high-energy emitters, with NIST-traceable calibrations
4. 2D anisotropy function tabulations F(r,θ) on a fine grid

## Consensus Dose-Rate Constants (TG-43U1S1)

| Source | Model | Λ (cGy·h⁻¹·U⁻¹) | Uncertainty (k=1) |
|--------|-------|------------------|-------------------|
| ¹⁹²Ir HDR | mHDR-v1 (Nucletron) | 1.115 | 1.5% |
| ¹⁹²Ir HDR | mHDR-v2 (Nucletron) | 1.116 | 1.5% |
| ¹⁹²Ir HDR | Flexisource (Nucletron/Elekta) | 1.109 | 1.5% |
| ¹⁹²Ir HDR | VS2000 (Varian) | 1.094 | 1.5% |
| ⁶⁰Co HDR | Co0.A86 (Eckert & Ziegler BEBIG) | 1.089 | 1.5% |
| ⁶⁰Co HDR | Flexisource Co-60 (Elekta) | 1.066 | 1.5% |
| ¹⁶⁹Yb HDR | M42 (Eckert & Ziegler BEBIG) | 0.467 | 1.5% |
| ¹⁹²Ir LDR | Ir-192 generic | 1.092 | 1.5% |
| ¹³⁷Cs LDR | CDCS-J (Isotron) | 0.0913 | 1.5% |
| ⁶⁰Co LDR | Co-AE-1 (Eckert & Ziegler BEBIG) | 1.089 | 1.5% |
| ¹⁹⁸Au seeds | Best 81-01 | 0.105 | 2.5% |

## Methodology Update

- All published data should be derived from full Monte Carlo (MC) transport in water, with primary collisional kerma scoring
- Dosimetry parameters should be tabulated on a 1-mm radial and 1° angular grid
- Anisotropy in modern ¹⁹²Ir HDR sources typically < 30% near the tip; old wire sources had F(1cm,0°) ≈ 0.6
