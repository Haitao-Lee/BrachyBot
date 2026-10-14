# English Localization Audit and Remediation

Date: 2026-10-09  
Baseline checkout: `/home/lht/snap/brachyplan/BrachyBot`  
Baseline commit: `0d840e38bea3fb36b8e9b3cf3acb33220062f3bc`

## 1. Purpose and scope

This change addresses imprecise translations, unnatural English, inconsistent control names, and fixed wording that implies unsupported clinical validity. It is a product-copy audit, not a change to the dose engine, clinical acceptance criteria, planning algorithms, coordinate transforms, authorization rules, or stored data identifiers.

The audit covers the main HTML interface, product-owned frontend modules, report captions and tables, exports, Monitor guidance, control-usage documentation, and backend presentation text. Vendor libraries, historical audit documents, user-authored names, literature titles, saved conversation text, and machine-readable identifiers are not globally rewritten.

The source inventory contains:

| Inventory | Scope | Candidate count |
|---|---|---:|
| Explicit frontend bilingual text | 29 product-owned JavaScript modules and main HTML | 1,726 |
| Direct English presentation candidates | Text, title, notification and canvas assignments/calls | 168 |
| Python bilingual candidates | 207 Python modules under `web`, `agent_runtime`, `tool_factory`, and `brain` | 973 |

All inventoried files parsed successfully. Counts are extraction candidates, not counts of mistranslations or independent defects. Some candidates are markup, identifiers, duplicates, units, or legitimate short labels. The reviewed substitution lists contain 169 exact replacements; additional targeted fixes cover control-name consistency, report captions, localized status text, and the D2 description supplied to the model. This is not a runtime search-and-replace filter.

## 2. Anatomical and geometric terminology

| Concept | Previous wording | Revised wording | Meaning |
|---|---|---|---|
| Guide channel entrance | Guide mouth | Guide channel entry | The outer opening of the generated needle-guide channel |
| Guide-entry group | Guide mouths · From needle tip | Guide channel entries · Distance to needle tip | Groups measurements by needle and guide version |
| Skin intersection | Start: skin entry | Skin entry point | The point where the needle axis intersects the derived skin surface |
| Distal endpoint | End: needle tip | Needle tip | The zero reference for the recorded seed distances |
| Insertion length | Axial skin-to-tip length | Skin-to-tip axial length | Axial distance between skin entry and needle tip |
| Seed depth | From needle tip | Distance from needle tip | Signed axial projection to the seed center |
| Neighboring seed spacing | Axial spacing | Axial center spacing | Axial center-to-center spacing, not capsule surface clearance |
| Seed displacement from axis | Axis offset | Off-axis distance | Perpendicular distance from the seed center to its owning needle axis |
| Seed coordinates | Actual XYZ position | Seed center XYZ | Saved physical patient coordinates, in mm |
| Trajectory initialization points | Close points | Target boundary points | Boundary points associated with the initialized candidate trajectories |
| Exact finite-object separation | Finite surface gap | Surface-to-surface clearance | Clearance calculated from finite needle/seed geometry |
| Conservative axis approximation | Axis-model clearance bound | Surface-clearance lower bound (axis model) | A bound, not an exact finite-surface measurement |

The guide opening and skin entry are deliberately distinct. Guide tooltips identify the center of the outer channel opening and explicitly state that it is not the skin entry point. Distance definitions, signs, units, anchors, IDs, and saved visibility/opacity/color remain unchanged.

The machine identifier `generated_primary_sleeve_outer_mouth_axis_center` is retained. Changing a user-facing label must not invalidate existing annotation records or consumers of their geometric provenance.

## 3. Dose terminology and parameter accuracy

The old fixed labels `D2 (max dose)` and `D2 (max)` were incorrect. The planning implementation obtains D2 with `dose_at_volume(2)`, so the revised label is **D2 (dose to the hottest 2%)**. Dmax remains a separate maximum-dose metric. The Chinese label and the model-facing metric description are corrected as well. No metric value or dose calculation is changed.

Planning parameter labels now read:

- **Minimum in-target dose (Gy)** instead of **In Lowest Dose (Gy)**.
- **Maximum out-of-target dose (Gy)** instead of **Out Highest Dose (Gy)**.

The latter refers to out-of-target voxels in the implemented planner; it is not relabeled as an OAR-only clinical constraint. Parameter names, defaults, input bounds, and transmission values remain unchanged.

This correction does not constitute an independent physical validation of CNN dose predictions or of every legacy metric fallback.

## 4. UI, Monitor, reports, and exports

### Surface color mode

The previous **Normal Surface** label restored structure colors; it did not display surface normals or distinguish healthy tissue. The two button states are now **Dose coloring** and **Structure colors**. The initial HTML, mode transitions, reset, workspace restore, language-switch path, backend recovery guidance, and control-usage card use these names consistently.

The handler `toggleDoseTextureMode`, capability key `viewer.surface`, and DOM ID `doseTextureToggle` are unchanged. The usage-manual version is updated to `2026-10-09.1`.

### Monitor

Representative revisions include **Dose up to date**, **Preparing images**, **Comparable dose changes (selected metrics)**, and **Location not confirmed in this view**. Grammar is corrected without converting unavailable evidence into successful verification. Preview movement, saved geometry, completed dose recalculation, and clinical approval remain distinct states.

The absence of newly observed spacing conflicts is explicitly not proof that the entire plan is clinically safe. Patient-coordinate displacement is not described as a screen-space or dose-optimization direction. Axis-model bounds are not presented as exact surface clearances.

### Reports and exports

The seed table is titled **Needle Trajectories and Seed Positions**. Column and endpoint labels distinguish skin entry, needle tip, seed-center coordinates, axial spacing, and off-axis distance. Skin-entry provenance remains qualified as a computational derivation rather than an intraoperative measurement.

Review-order wording distinguishes cited dose criteria, case-specific priorities, comparable dose-to-limit ratios, observed-dose sorting, and unassessed data. Missing and measured-zero values remain distinct. Neither ordering nor a report table establishes clinical approval.

Report captions now identify a **Plan overview (needle reference direction)** rather than an ambiguous **Reference-direction front view**. Export dialogs use **Isodose surfaces**, **data items selected**, and **select another format**. Status text uses the existing global language manager. The report letterhead expands the institution name to **Shanghai Jiao Tong University** and replaces the programming-style `&&` with **and**.

### Unsupported marketing claims

Both language versions of the landing-page copy and its translation dictionary now say **Planning support** instead of **Clinical-grade**. Unverified universal speed, sub-millimeter inference, and automatically safe trajectory claims are replaced with descriptions of the implemented prediction and candidate-planning functions. This is a deliberate accuracy correction, not a claim that clinical validation has been completed.

## 5. Preservation and regression safeguards

The acceptance check compares the baseline and changed files using the same Python interpreter, avoiding differences in AST serialization between Python versions.

- All 430 recorded HTML action/parameter/identity attribute records are unchanged, including IDs, handlers, values, bounds, and capability attributes.
- Executable AST structure is unchanged in the four edited backend modules after string presentation content is excluded: `web/monitor_changes.py`, `agent_runtime/ui_control_manual.py`, `agent_runtime/chat_workflows.py`, and `agent_runtime/core.py`.
- Internal geometric provenance, units, authorization, tool names, clinical limits, plan state, and object IDs are not renamed.
- The new localization contract exercises the real annotation renderer, global language switching, guide-entry terminology, unchanged distance/identifier values, report labels, D2 labeling, matching usage guidance, and consistent nonapproval landing-page text.
- Existing regression tests retain their functional assertions. Only outdated literal-copy assertions were updated: retained needle position without replanning, Angle point-count progress, report tip-distance label, and the axis-model clearance wording.

Structural checks are evidence of limited mutation scope, not a substitute for behavioral testing.

## 6. Validation evidence

The final isolated `tests/` run passed **3,320 tests**, with **2 skipped**, **4 passing subtests**, and no failures or collection errors. Existing deprecation warnings remain. This is the repository product test suite, not a full benchmark evaluation or a real-patient/GPU clinical validation.

Additional checks include:

- Syntax checks for all changed product JavaScript files and Python compilation.
- Baseline/after hashes and explicit selected-file delivery checks.
- Actual Chromium annotation rendering: three synthetic labels, including the guide entry, remained within the viewport in both languages; 50.0 mm remained unchanged.
- Synthetic English and Chinese A4 reports: every requested OAR/seed row retained, repeated table headings, no table-width overflow, no rows beneath page footers, and PDF text/page-count checks. The English fixture produced 13 pages. Changed table labels and institution wording were inspected in rendered page images.

Report tests use a synthetic `about:blank` document without fetching branding assets; absent logos in that fixture are not evidence that deployed branding is unavailable. No real patient resources were loaded or altered for visual QA.

Evidence and the delivery manifest are stored privately at:

`/home/lht/.local/share/brachybot-english-localization/validation-20261009-XpV4C3`

The public-release checkout is outside this change. No commit or push is created by this delivery.

## 7. Activation and limitations

Frontend assets are read from disk and become available on a fresh page load after delivery. Avoid refreshing in the middle of an unsaved edit. Already imported backend modules require a normal controlled LAN server restart to use the new guidance and model description. A preflight found an active editing lease, so this change does not force a restart, revoke the lease, or terminate a user operation. The evidence directory records the point-in-time runtime metadata; it is not an ongoing health guarantee.

Previously downloaded PDFs and historical chat responses are not rewritten. Newly generated report sections use the revised labels; stored figure captions are updated by the normal report/capture workflow rather than bulk-renaming saved or user-edited records. Custom object names, existing guide labels such as `Puncture guide v1`, literature titles, and external third-party content retain their original identity.

LLM-generated prose can still contain translation errors. This change corrects fixed product wording and the specific model-facing D2 explanation; it cannot guarantee that every future model response is flawless English.

## 8. Terminology references

The following primary sources informed the distinction between needle guidance, channels, insertion depth, and image measurements. **Guide channel entry** is the product's descriptive label for its implemented outer-opening anchor, not a claim that a source mandates that exact UI phrase.

- [Accuracy evaluation of a 3D-printed individual template for needle guidance in head and neck brachytherapy](https://pmc.ncbi.nlm.nih.gov/articles/PMC5137284/).
- [3D-printed vaginal cylindrical template with curved needle channels for brachytherapy](https://pmc.ncbi.nlm.nih.gov/articles/PMC10789162/).
- [3D Slicer Markups documentation](https://github.com/Slicer/Slicer/blob/main/Docs/user_guide/modules/markups.md).
- [3D Slicer measurement scripting examples](https://slicer.readthedocs.io/en/latest/developer_guide/script_repository/markups.html).
