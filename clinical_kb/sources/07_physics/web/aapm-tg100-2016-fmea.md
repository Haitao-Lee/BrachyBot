# AAPM TG-100 — Risk-Based Failure Mode and Effects Analysis (FMEA) for Brachytherapy (2016)

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=128
- **Citation**: Huq MS, Fraass BA, Dunscombe PB, Gibbons JP Jr, Ibbott GS, Medin PM, Mundt AJ, Mutic S, Palta JR, Rath F, Thomadsen BR, Williamson JF, Yorke ED. The report of Task Group 100 of the AAPM: Application of risk analysis methods to radiation therapy quality management. Med Phys. 2016;43(7):4209-4262.
- **Document type**: AAPM Task Group Report (consensus guideline)
- **Date saved**: 2026-06-17

## Methodology

1. **Process map**: identify all subprocesses (e.g., patient consult, simulation, contouring, planning, plan check, treatment delivery, etc.)
2. **Failure modes (FMs)**: potential ways each step can fail
3. **Severity (S)**: 1 (no impact) to 10 (catastrophic)
4. **Occurrence (O)**: 1 (very rare) to 10 (very frequent)
5. **Detectability (D)**: 1 (always detected) to 10 (never detected before reaching patient)
6. **Risk Priority Number (RPN)**: S × O × D

## BT-Specific Failure Modes (Illustrative)

| Process | Failure Mode | S | O | D | RPN |
|---------|--------------|---|---|---|-----|
| Applicator insertion | Wrong applicator type (e.g., ring vs ovoid) | 9 | 2 | 3 | 54 |
| Source calibration | Wrong Λ used in TPS | 10 | 1 | 4 | 40 |
| Image transfer | Applicator shifts between CT and planning | 8 | 5 | 5 | 200 |
| Plan check | Wrong total dose entered | 10 | 2 | 2 | 40 |
| Treatment delivery | Wrong transfer tube connection | 10 | 1 | 2 | 20 |
| Patient identification | Wrong patient treated | 10 | 1 | 1 | 10 |
| Dwell position | Indexer length error (mm shift) | 8 | 3 | 5 | 120 |
| Post-treatment | Source not retracted | 10 | 1 | 1 | 10 |

## BT-Specific Process Tree (High-Level)

1. **Referral & consult**
2. **Imaging (CT, MRI, US)**
3. **Applicator insertion** (intraoperative for interstitial)
4. **Imaging for planning**
5. **Target/OAR contouring**
6. **Treatment planning (loading, optimization)**
7. **Plan review (chart check, physics check)**
8. **Patient setup verification (pre-treatment imaging)**
9. **Treatment delivery (HDR/PDR/LDR)**
10. **Post-treatment verification & follow-up**
11. **Source exchange/retrieval**
12. **Equipment QA (daily, monthly, annual)**

## Recommendations

- Implement QM program with TG-100 risk analysis
- Identify high-RPN failure modes and add mitigations (e.g., second-person checks, automated barriers)
- For BT, focus on:
  - Source strength verification (well-chamber, NIST-traceable)
  - Indexer length verification (mechanical QA daily)
  - Independent dose calculation (second MU/dwell-time check)
  - Plan sum review (EBRT + BT)
  - In-vivo dosimetry (when feasible)
