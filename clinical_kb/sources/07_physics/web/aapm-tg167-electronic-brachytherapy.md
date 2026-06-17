# AAPM TG-167 — Electronic Brachytherapy (2016/2017)

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=146
- **Citation**: Eaton DJ, Guckenberger M, Gloi A, Bateman F, Beaulieu L, Bedford J, Chang A, Chen Y-J, Dang A, Davis C, Eaton M, Eggert D, Fogg R, Giordano A, Halford R, Johnson M, Kim A, Kutyreff C, Liu A, Mao W, Mourtada F, Ruo R, Safavi-Naeini M, Sebbas D, Sethi A, Simon S, Smith RL, Spezi E, Sutlief S, Tarver C, Todor A, Turian J, Verhaegen F, Wahl A, Wang D, Wang L, Williams M, Yu Q, Zou J. AAPM Task Group report 167: Task Group on Electronic Brachytherapy. J Appl Clin Med Phys. 2017 (in press). [Note: also Eaton DJ et al. 2016 Med Phys; and AAPM TG-167 consensus document]
- **Document type**: AAPM Task Group Report
- **Date saved**: 2026-06-17

## Electronic Brachytherapy Sources

- **Xoft Axxent**: 50 kVp X-ray source, 0.2–0.5 mm source size
- **Carl Zeiss INTRABEAM**: 50 kVp at tip, 1.6 mm × 0.6 mm source
- **Papillon Plus / Ariane**: 50 kVp contact therapy (typically considered contact RT, not BT)
- **Sensus SRT-100**: not BT (superficial RT)

## Clinical Use

- **Intracavitary breast (IORT)**: Xoft balloon for APBI as monotherapy (5 days × 3.4 Gy, twice daily, surface dose 34 Gy)
- **Intraoperative intracranial / spine**: INTRABEAM
- **Skin cancer**: some 50 kVp systems

## Physics Considerations

### Source Characteristics

- **Very low energy** (50 kVp): mean photon energy ~20–30 keV
- **Sharp attenuation** in tissue: ½-value layer ~1 cm in water (vs 3 cm for ¹⁹²Ir)
- **High dose rate** at source: e.g., Xoft 2.7 Gy/min at 1 cm from balloon surface (1.5–3.5 cm balloon radius)

### Dosimetry (Non-TG-43)

- TG-43 formalism does NOT apply directly because of large radial dose function gradient
- AAPM TG-167 recommends direct measurement in water or use of Monte Carlo (MCNP, Geant4)
- Typical depth-dose curve: falls to 50% at 2–3 cm depth

### Clinical Recommendations

- Surface dose prescription: 34–40 Gy in 10 fractions (5 days) for APBI
- Output calibration: well-chamber with appropriate correction for low-energy
- Beam quality spec: ½-value layer in Al or Cu
- Plan optimization: minimal — single dwell position
- Imaging for planning: CT (balloon positioning, conformity to cavity)
- Use of contrast in balloon for visualization
- Verify balloon symmetry and skin spacing (≥ 7 mm to minimize skin toxicity)

## Comparison with ¹⁹²Ir

| Property | Xoft 50 kVp | ¹⁹²Ir HDR |
|----------|-------------|-----------|
| Mean photon energy | ~25 keV | 380 keV |
| ½-value layer in water | ~1 cm | ~3 cm |
| Dose rate at 1 cm | 2–5 Gy/min | 5–10 Gy/min |
| Treatment room shielding | Lighter (lead) | Heavier (concrete) |
| TG-43 formalism | NOT applicable | Applicable |
| Anisotropy | High (depends on source orientation) | Low (~20–30%) |
| Skin dose | High (limited depth) | Lower |

## QA Requirements

- Daily: source output constancy (well chamber)
- Monthly: depth-dose curve measurement
- Quarterly: half-value-layer verification
- Annually: full calibration
- Treatment time should not exceed manufacturer's recommendation to avoid source wear
