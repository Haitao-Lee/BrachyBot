# GEC-ESTRO Recommendations on Inverse Planning / IPSA / HIPO for Brachytherapy (2007, 2012, 2018)

- **URLs**:
  - https://www.estro.org/Science/Activities/GEC-ESTRO (GEC-ESTRO)
  - https://www.greenjournal.org/article/S0167-8140(18)30295-8/fulltext (EMBRACE-II 2018)
- **Citations**:
  - Lessard E, Pouliot J. Inverse planning anatomy-based dose optimization for HDR brachytherapy of the prostate using fast simulated annealing algorithm and dedicated objective function. Med Phys. 2001;28(5):773-779.
  - D'Amours M, Pouliot J. Inverse planning anatomy-based dose optimization for HDR brachytherapy of the prostate using IPSA. Med Phys. 2007 (IPSA update).
  - Carlier T, Hensel B, Cormier A, Monini-Mounier C, Karaiskos P, Mavroidis P, Baltas D, Chauvie S, HIPO. Inverse planning optimization in interstitial HDR BT for breast, prostate, GYN. Radiother Oncol. 2012.
  - Tanderup K, Ménard C, Polgar C, Lindegaard JC, Kirisits C, Pötter R. ICRU 89 / GEC-ESTRO 2018: Recommendations on target and OAR definitions. Radiother Oncol. 2018;127(1):89-94.
- **Document type**: GEC-ESTRO consensus guidelines + EMBRACE-II protocol
- **Date saved**: 2026-06-17

## Inverse Planning Concepts

### IPSA (Inverse Planning Simulated Annealing)

- Anatomy-based: each dwell position has a unique weight set by its anatomical relationship to target and OAR
- Objective function:
  - Maximize PTV coverage (D90)
  - Minimize OAR doses (D2cc, D1cc, D0.1cc)
  - Penalize overdosed regions (>150% V)
- Free parameters: minimum dwell time, dwell step, iteration count
- Allows non-uniform loading (e.g., more loading near HR-CTV)

### HIPO (Hybrid Inverse Planning Optimization)

- Combines manual graphical optimization with inverse planning
- Two phases: (1) define target/OAR constraints, (2) hybrid optimization with "tuning" parameters
- Useful for complex implant geometries (interstitial, multi-catheter)

### Comparison with Manual Loading

| Method | Pros | Cons |
|--------|------|------|
| Standard loading (Manchester/Fletcher) | Reproducible, established | Suboptimal for unusual anatomy |
| Graphical optimization | Intuitive, expert-controlled | Time-consuming, expert-dependent |
| Inverse (IPSA/HIPO) | Fast, target coverage, OAR avoidance | Less predictable dose distribution shape, can have "hot spots" |
| Multi-objective (Pareto front) | Explicit trade-off visualization | Requires more computation |

## GEC-ESTRO/EMBRACE-II 2018 Recommendations

### Target

- HR-CTV D90 ≥ 85–90 Gy EQD2(α/β=10); in EMBRACE-II, target 90 Gy
- IR-CTV D90 ≥ 60 Gy EQD2
- TraC V100 ≥ 90% of HR-CTV
- D2cc OAR: see constraints below

### Dose Gradients

- V150 for HR-CTV typically 30–50%
- V200 for HR-CTV typically 15–30% (interstitial); <20% for IC+IS

### Plan Evaluation

- Cumulative DVH across EBRT+BT fractions
- Time pattern: 4×7 Gy or 5×6 Gy HR-CTV D90, twice-daily, ≥ 6 h interval
- Adaptive BT: re-plan after each fraction based on applicator position and tumor response

### Constraints (GEC-ESTRO 2018, ABS 2018, EMBRACE-II)

| OAR | Constraint (EQD2, α/β=3) |
|-----|---------------------------|
| D2cc rectum | < 65 Gy (aim < 75 Gy) |
| D2cc bladder | < 80 Gy (aim < 90 Gy) |
| D2cc sigmoid | < 65 Gy (aim < 75 Gy) |
| D2cc bowel | < 65 Gy (aim < 75 Gy) |
| D0.1cc urethra | < 150 Gy EQD2 (prostate HDR) |
| D10 (prostate) rectum | < 75 Gy EQD2 (HDR monotherapy) |

## Dwell Time Modulation

- Dwell time proportional to local dose desired
- Minimize inter-catheter dose variation
- Avoid very short or very long dwell times (delivery precision)
