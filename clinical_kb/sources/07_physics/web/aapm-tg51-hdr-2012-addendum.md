# AAPM TG-51 Addendum for HDR ¹⁹²Ir (2012) — Calibration of HDR Brachytherapy Sources

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=121
- **Citation**: Almond MR, Beierwaltes WH, Coursey BM, Hanson WF, Klein EE, Shalek RJ, Stovall MS. AAPM's TG-51 protocol for clinical reference dosimetry of high-energy photon and electron beams — Addendum for high-dose-rate Ir-192 sources. Med Phys. 2012;39(7):4425-4427.
- **Document type**: AAPM protocol addendum
- **Date saved**: 2026-06-17

## Calibration Traceability

- Air-kerma strength S_k measured with a well-type ionization chamber
- Well-chamber calibration coefficient N_(sk,D_w) (Gy/(C·U)) traceable to NIST (or equivalent) for each source model
- For each HDR source, the source is measured in a standard positioning jig inside the well chamber
- Calibration uncertainty: ~1.5% (k=1)

## Measurement Procedure

1. Pre-warm well chamber and source holder (≥ 1 h)
2. Position source at the well-chamber reference point (typically mid-source position)
3. Take 3+ measurements of electrometer current (or charge) at each polarity
4. Apply ion recombination, polarity, and pressure/temperature corrections
5. Compute S_k = M · N_(sk,D_w) · Π correction factors
6. Compare to manufacturer-stated value; tolerance ± 3% (or per institutional policy)

## Recommended QC

- Daily: source-positioning check
- After each source exchange: S_k measurement before clinical use
- Quarterly: well-chamber constancy with check source
- Annually: well-chamber full calibration (NIST or ADCL)

## Clinical Use of S_k

- S_k is the source strength input for treatment planning systems
- For HDR ¹⁹²Ir: typical S_k = 40,000–50,000 U (i.e., 4.0–5.0×10⁻⁶ Gy·m²·h⁻¹)
- A 10 Ci ¹⁹²Ir source ≈ 4.0×10⁻⁶ Gy·m²·h⁻¹ at 1 m
- Source decay: T½ = 73.83 d, so S_k decreases by ~6.3% per week
- Source typically replaced every 3–4 months (when S_k < ~20,000 U for treatment times > 30 min)

## Difference from LDR

- HDR sources are typically replaceable without entering the vault; the old source is retracted to the afterloader safe
- LDR (¹²⁵I, ¹⁰³Pd, ¹³¹Cs) seeds: each seed individually calibrated by vendor; the AIR (apparent activity) is used in the TPS
