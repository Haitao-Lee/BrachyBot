# AAPM TG-43U1 — Update of AAPM Task Group No. 43 Report (Rivard et al., 2004)

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=87
- **Citation**: Rivard MJ, Coursey BM, DeWerd LA, Hanson WF, Huq MS, Ibbott GS, Mitch MG, Nath R, Williamson JF. Update of AAPM Task Group No. 43 Report: A revised AAPM protocol for brachytherapy dose calculations. Med Phys. 2004;31(3):633-674.
- **Document type**: AAPM Task Group Report (consensus guideline, revision of TG-43)
- **Date saved**: 2026-06-17

## 2D Formalism (line-source approximation)

Ḋ(r,θ) = Λ · S_k · (G_L(r,θ)/G_L(1,θ₀)) · g_L(r) · F(r,θ)

Where:
- G_L(r,θ) = line-source geometry function = β/(L·r·sin θ) when r·sin θ ≥ L/2
- g_L(r) = radial dose function along the transverse bisector
- F(r,θ) = 2D anisotropy function (renamed; was 1D anisotropy function in TG-43)
- L = active length of source
- β = angle subtended by the active source at point (r,θ)

## Key Improvements over TG-43 (1995)

1. **2D anisotropy**: accounts for off-axis dose variation as a function of both r and θ
2. **Line-source geometry function**: more accurate for finite-length sources
3. **Consensus consensus dataset**: published consensus Λ and g_L for many HDR and LDR sources
4. **Tabulated recommended values** for 1-2 dozen low- and high-dose-rate sources
5. Recommended use of the 2D formalism for clinical dose calculations

## Consensus Dose-Rate Constants (Λ) for Common Sources

| Source | Model | Λ (cGy·h⁻¹·U⁻¹) |
|--------|-------|------------------|
| ¹⁹²Ir HDR | microSelectron v1/v2 | 1.108 ± 1.8% |
| ¹⁹²Ir HDR | VariSource | 1.101 |
| ¹⁹²Ir HDR | GammaMed | 1.118 |
| ¹²⁵I LDR | Amersham 6702/6711 | 0.965 ± 1.5% |
| ¹²⁵I LDR | OncoSeed 6711/6733 | 0.972 |
| ¹²⁵I LDR | Best 2301/2335 | 0.964 |
| ¹⁰³Pd LDR | TheraSeed 200 | 0.665 ± 3% |
| ¹⁰³Pd LDR | IsoRay | 0.677 |
| ¹⁶⁹Yb HDR | | 0.45 (approx) |
| ⁶⁰Co HDR | Ralstron / GZP-3 | 1.089 |
| ¹⁹⁸Au seeds | | 0.105 |
| ¹³¹Cs seeds | IsoRay CS-1 | 0.913 |

(Values are nominal; see TG-43U1 consensus tables for full uncertainties)

## Reference Conditions

- Water medium
- Reference point: r₀ = 1 cm, θ₀ = 90°
- Source-to-detector distance typically > 1 cm to avoid 1/r² divergence issues at very small r
