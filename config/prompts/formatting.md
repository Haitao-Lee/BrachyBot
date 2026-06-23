## Report Generation Rules
When generating clinical treatment reports:
1. **Terminology**: Use "Radioactive Seed Implantation", NOT "Permanent Seed Implantation" (outdated).
2. **Screenshots**: The report MUST include visual evidence (CTV/OAR overlay, dose heatmap, DVH curves, 3D view). Use `captureReportFigure2D()` and `captureReportFigure3D()`.
3. **Language consistency**: Report language must match the user's input language. Do NOT mix languages.
4. **Input-output alignment**: If user inputs in Chinese, report output must be in Chinese.
5. **Structure**: Include all sections — patient info, CTV/OAR segmentation, dose metrics, DVH analysis, clinical recommendations, references.
6. **References**: Include source links (PMID, DOI) for all clinical claims.
