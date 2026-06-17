# AAPM TG-229 / Joint AAPM-ESTRO Report on MBDCA for Brachytherapy (2016/2020)

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=141
- **Citation 1 (TG-229)**: Beaulieu L, Tedgren Åsa Carlsson, Carrier J-F, Davis SD, Mourtada F, Rivard MJ, Thomson RM, Verhaegen F, Wareing TA, Williamson JF. Report of the Task Group 186 on model-based dose calculation methods in brachytherapy beyond the TG-43 formalism: Current status and recommendations for clinical implementation. Med Phys. 2012;39(10):6208-6236.
- **Citation 2 (Joint Report)**: Ma Y, Vijande J, Ballester F, Tedgren ÅC, Granero D, Haworth A, Mourtada F, Fonseca GP, Zourari K, LaTessa C, Sowards K, von Stevern J, Beierholm AR, Christensen MS, Sarfehnia A, Delage ME, Townsend LW, Tagne T, Etxebeste A, Luketina IA, Papagiannis P, Roy R, Rivard MJ, Ballester F, Renaud J, Fröhlich T, Chiavassa S, Martin-Vaquero P, Kobayashi K, Eakins J, Lopes de Almeida JP, Smith RL, Siebert F-A, Sander T, Verhaegen F, Beaulieu L, Williamson JF, Thomson RM. Joint AAPM/ESTRO report on MBDCA in brachytherapy. Med Phys. 2020 (in press). [Note: Beaulieu L et al. cited 2012 for the seminal TG-229; subsequent 2020 joint report is the update]
- **Document type**: AAPM Task Group Report / Joint AAPM-ESTRO consensus guideline
- **Date saved**: 2026-06-17

## Motivation: Why MBDCA?

TG-43 assumes:
1. Water medium everywhere
2. Full scatter conditions (infinite water phantom)
3. Does not account for tissue/applicator heterogeneities or patient geometry
4. Does not account for interseed attenuation (ISA) or high-Z shielding

In reality:
- Air gaps, bone, soft tissue, applicator materials (titanium, stainless steel, plastic) affect dose
- Interseed attenuation for LDR prostate implants can reduce D90 by 5–10%
- Shielded applicators (intracavitary, surface) have major impact on OAR dose
- Patient-specific MBDCA accounts for all these effects

## MBDCA Methods

| Category | Algorithms | Accuracy vs MC |
|----------|-----------|----------------|
| Type I (correction-based) | 1D path-length correction, effective attenuation coefficient μ_eff | Limited |
| Type II (collapsed-cone / superposition) | CCCS, Acuros BV (Varian), ACE (Oncentra) | 2-3% in heterogeneous regions |
| Type III (deterministic Boltzmann solvers) | Attila, Adjoint Acuros | 1-2% |
| Type IV (Monte Carlo) | MCNP, Geant4, Penelope, TOPAS, GATE, DOSXYZnrc, egs_brachy | Gold standard |

## MBDCA Software Implementations

- **Acuros BV (Varian)**: deterministic Boltzmann solver, license from Transpire Inc; uses pre-computed radiation transport database for ¹⁹²Ir, ¹²⁵I, ¹⁰³Pd, ¹⁶⁹Yb
- **ACE (Elekta Oncentra)**: collapsed-cone engine
- **RapidBrachyMCTPS / SagiPlan**: research TPS
- **Gammex, MIM, RayStation**: each added MBDCA modules
- **Topas, GATE, MCNP**: research-grade MC

## Clinical Implementation Recommendations

1. Commission MBDCA using published reference data (Carlsson-Tedgren, 2014; Ballester et al., 2015) — comparison to TG-43 for simple geometries
2. Verify MBDCA against well-benchmarked MC codes for at least 10 patient cases
3. Calculate mean dose to OAR over full course (EBRT + BT) for true biologically meaningful reporting
4. For shielded applicators: MBDCA strongly recommended; TG-43 may be off by 20–50%
5. For LDR prostate: ISA correction typically reduces prostate D90 by 4–8%
6. For superficial (skin) BT with tungsten shields: MBDCA mandatory

## Dose to Medium vs Dose to Water

- MBDCA reports D_(m,m) (dose to medium in medium) by default
- For historical comparison: convert to D_(w,m) (dose to water in medium) using Bragg-like scaling, e.g.:
  D_w,m ≈ D_m,m · (μ_en/ρ)_w,m
- For ¹⁹²Ir, the correction is typically 1–2% in soft tissue, larger in bone (D_m,m can be 5-10% higher)
