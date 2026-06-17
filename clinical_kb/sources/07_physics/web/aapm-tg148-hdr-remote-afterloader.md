# AAPM TG-148 — Quality Assurance for High-Dose-Rate Brachytherapy (Remote Afterloader) (2004, updated)

- **URL**: https://aapm.org/pubs/reports/detail.asp?docid=98
- **Citation**: Kubo HD, Glasgow GP, Pethel TD, Thomadsen BR, Williamson JF. High dose-rate brachytherapy treatment delivery. Report of the AAPM Radiation Therapy Committee Task Group No. 59. Med Phys. 1998;25(4):375-403. (TG-59 foundational)
- **Subsequent updates**: Nath R et al. AAPM recommendations on dose specification, prescription, and reporting for interstitial, intracavitary, and endorectal brachytherapy. Med Phys. 2020 (TG-259 update)
- **Document type**: AAPM Task Group Report
- **Date saved**: 2026-06-17

## QA Tests for HDR Remote Afterloader

### Daily QA

1. **Door interlock**: open door → source retracts
2. **Audiovisual indicators**: warning lights and alarms
3. **Emergency stop**: accessible
4. **Source position (test dwell)**: ± 1 mm precision
5. **Console operation**: simple test plan delivered
6. **Hand pendant / manual override**: functional
7. **Survey meter**: battery + response
8. **Treatment room radiation survey**: background

### Weekly QA

1. **Source position accuracy**: dwell positions at 1, 5, 10 cm
   - Tolerance: ± 1 mm
2. **Source dwell time accuracy**:
   - Test: 1 sec, 10 sec, 100 sec
   - Tolerance: ± 1% or 50 ms, whichever is greater
3. **Transfer tube length check**:
   - Visual + autoradiograph
4. **Timer accuracy**:
   - Compare to stopwatch for known dwell time
5. **Source strength check**:
   - Well chamber or in-air measurement

### Monthly QA

1. **Source position vs planned**:
   - Phantom test
2. **Dose calculation check**:
   - Independent calculation vs TPS plan
3. **In-vivo dosimetry check** (if MOSFET/TLD used)
4. **Mechanical integrity of applicators**
5. **Facility radiation survey**

### Quarterly QA

1. **Full QA** including all daily and weekly
2. **Dose-rate calibration** of well chamber
3. **Source decay correction check** vs vendor value
4. **Apparent activity / S_k comparison** vs vendor

### Annual QA

1. **Full system audit** by medical physicist
2. **AAPM TG-253 TPS commissioning review**
3. **Well chamber ADCL calibration** (or equivalent)
4. **Source exchange and recalibration**
5. **Radiation survey of facility** with new source

## Key Performance Specifications

- **Source position accuracy**: ± 1 mm (clinical impact: 5% dose at 1 cm per 1 mm longitudinal)
- **Dwell time accuracy**: ± 1% (clinical impact: linear in dose)
- **Source strength accuracy**: ± 3% (clinical impact: linear in dose)
- **Total uncertainty budget for clinical BT dose**:
  - Source calibration: 1.5%
  - Source positioning: 1.5%
  - TPS dose calculation: 2%
  - Dose summation (EBRT+BT): 2%
  - Plan delivery: 2%
  - **Total (RSS)**: ~4%

## Applicator-Specific QA

- **Ring/tandem (cervical)**: ring film autoradiograph + dummy wire test
- **Interstitial needles**: source transit through each needle + connector check
- **Surface applicators**: cone alignment check, skin spacing
- **Endorectal/endocavitary**: balloon integrity, source centering
- **Breast brachytherapy (balloon, strut-adjusted)**: balloon symmetry, source path

## Emergency Procedures

1. **Source fails to retract**:
   - Manual source retraction (afterloader has hand crank)
   - If source remains exposed: evacuate staff, close door, contact radiation safety
2. **Wrong patient or wrong plan**:
   - Stop treatment, do not retract if treatment in progress; if retracted, do not reuse
3. **Patient emergency**:
   - Disconnect transfer tube from patient, move patient away from afterloader
4. **Source loss** (theft/displacement):
   - Notify radiation safety officer immediately
