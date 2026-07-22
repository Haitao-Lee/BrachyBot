# Viewer Rendering and Report Fixes (2026-07-22)

## Scope

This change set addresses five independently reported usability and rendering
defects without changing planning coordinates, dose-engine semantics, or
clinical decision logic.

## Implemented fixes

### Tumor type input

- The Input panel now presents tumor types rather than implementation brands.
  The API value remains the stable internal catalog key, but the visible labels
  no longer expose model names.
- The catalog availability probe marks available types green and unavailable
  types red. An unavailable type remains selectable so the user can import a
  matching CTV mask for a manual workflow.
- The help text is localized and explains the user action instead of model
  installation details.

### 2D dose overlays

- PET Rainbow remains the default 2D palette with the existing 0–600 Gy
  range.
- Dose rendering now uses an explicit render epoch in addition to slice index.
  Changing the color scale, replacing dose metadata, clearing a session, or
  resizing the overlay canvas invalidates the epoch and repaints every current
  2D view immediately.
- Async dose-slice callbacks check both their requested slice and render epoch,
  preventing an older case or previous scale from painting over the current
  viewer.

### Data Tree and Dose Surface consistency

- The Data Tree is the canonical source for mesh visibility, opacity, and
  normal-surface color. Dose Surface can replace materials with dose vertex
  colors, but it no longer restores fixed CTV/OAR opacity values or forces
  hidden objects visible.
- Switching back to Normal Surface reapplies current Data Tree state instead
  of a stale material snapshot.
- Color changes for masks and isodose surfaces update the 3D mesh, 2D label
  projection, and 2D dose contour in the same refresh cycle.
- Needle interaction handles are excluded from treatment geometry and remain
  hidden during report capture and dose-surface transitions unless explicitly
  revealed by their normal hover interaction.

### Report Figure 1

- The overview camera is now framed around CTV, seeds, and only nearby OARs;
  remote structures and full external needle length cannot shrink the plan to
  an unreadable size.
- The seed-distribution panel uses a tighter tumor-focused framing and a wider
  exported composite. It intentionally prioritizes seed placement over showing
  every external needle endpoint.
- Internal needle endpoint handles are explicitly hidden for the full capture
  transaction, including meshes rebuilt while the image is being prepared.

## Verification

- JavaScript syntax checks cover all changed browser modules.
- `tests/test_workspace_frontend.py` includes static regression checks for the
  render epoch, Data Tree precedence, report-capture endpoint suppression, and
  tumor-type presentation.
- Verified on the deployment host with the `brachytherapy` environment:
  `python -m pytest tests/test_workspace_frontend.py
  tests/test_viewer_safety_geometry.py -q` completed with **43 passed**.
- The clinical coordinate chain and planning model are not changed by this
  update.

## Design invariant

Any future viewer mode must treat `dataTreeState` as display authority. A mode
may create or replace materials, but must preserve the selected object color
when normal rendering is active and must never override user-set visibility or
opacity.
