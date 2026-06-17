# DICOM-RT and Brachytherapy Treatment Planning Interoperability

- **URLs**:
  - https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.34.html (DICOM-RT Brachytherapy IOD)
  - https://dicom.nema.org/medical/dicom/2017e/output/chtml/part02/ (DICOM Standard)
- **Citation**: DICOM Standards Committee. Digital Imaging and Communications in Medicine (DICOM), Part 3: Information Object Definitions, Section A.34 — RT Brachytherapy IOD. National Electrical Manufacturers Association. Latest version 2023.
- **Document type**: International standard (DICOM PS3.3)
- **Date saved**: 2026-06-17

## DICOM-RT Brachytherapy IOD

### Modules

- **Patient Module**: patient demographics
- **Study / Series / Frame of Reference**: identifies imaging series
- **RT Series Module**: specifies modality (RTIMAGE, RTPLAN, RTSTRUCT, RTDOSE, RTRECORD)
- **RT Brachytherapy Treatment Record IOD (RT BRACHY RECORD)**:
  - **Application Setup Sequence**: applicator type, transfer tube parameters
  - **Channel Sequence**: dwell positions, dwell times, source strength
  - **Brachy Control Point Sequence**: for each source position
  - **Cumulative Dose Reference**: total dose delivered
  - **Treatment Summary**: total reference air kerma (TRAK), total dwell time, number of fractions

### Key Tags

- (300A,02A0) — Source Serial Number
- (300A,02A2)) — Source Isotope Name
- (300A,022C) — Source Isotope Half Life
- (300A,02A4) — Source Manufacturer
- (300A,02A6) — Source Strength Reference Date/Time
- (300A,02B0) — Source Strength
- (300A,02C0) — Source Type (POINT, LINE, CYLINDER, SPHERE)
- (300A,0280) — Channel Total Time
- (300A,0282) — Channel Number
- (300A,0284) — Channel Length
- (300A,0286) — Final Cumulative Time Weight
- (300A,02D0) — Brachy Accessory Device Sequence
- (300A,02D2) — Brachy Accessory Device ID
- (300A,02D4) — Brachy Accessory Device Type
- (300A,0502) — Applicator Sequence
- (300A,0504) — Applicator ID
- (300A,0506) — Applicator Type
- (300A,0508) — Applicator Description
- (300A,0510) — Cumulative Dose Reference Coefficient
- (300A,0512) — Final Cumulative Dose Reference Dose Value
- (300A,0200) — Current Fraction Number
- (300A,0202) — Number of Fractions Planned
- (3006,0002) — Structure Set Label

## Clinical Workflow

1. **Image acquisition**: CT, MRI, US (per ICRU 89)
2. **Applicator digitization**: physical or virtual, library-based
3. **Structure set (RTSTRUCT)**: target and OAR contours
4. **Plan (RTPLAN)**: dose prescription, fractionation, plan intent
5. **Dose (RTDOSE)**: 3D dose distribution
6. **Treatment record (RTRECORD)**: actually delivered treatment

## Applicator Library

- Vendor-supplied or institutional applicator library contains:
  - Digitized applicator geometry
  - Treatment channel endpoints
  - Pre-defined dwell positions
  - Reconstruction offsets
- AAPM TG-253 recommends applicator-specific commissioning
- For multi-modality (CT + MR) imaging, applicator reconstruction offset in MR is critical (3T titanium = signal void)

## DICOM-RT Interoperability Issues

- **Coordinate system**: some TPS use patient origin, some use applicator origin; transfer must respect DICOM (0,0,0) at patient origin
- **Source model identification**: vendor-specific source names vs DICOM standard (e.g., "Ir-192" vs "Flexisource")
- **Cumulative dose**: critical for combined EBRT + BT; DICOM-RT can store sum
- **DICOM-RTSTRUCT export/import**: contour name normalization (target, GTV, HR-CTV) essential

## IHE-Radiation Oncology (IHE-RO) Profiles

- **BRTO (Brachytherapy Treatment Workflow)**: end-to-end workflow including imaging, planning, delivery
- **RXRO (Prescription)**: structured prescription
- **TPPC (Treatment Planning - Plan Compare)**: plan comparison
- **AROY / DROI / CDE**: data exchange profiles
