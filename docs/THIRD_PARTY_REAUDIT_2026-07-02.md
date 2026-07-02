# Third-Party Re-Audit Report - 2026-07-02

## Scope

This pass reviewed the latest `main` branch from a fresh third-party perspective, with emphasis on product reliability, UI-agent interaction, screenshot feedback, API-key protected deployments, manual/agent workflows, and previously hardened clinical-governance boundaries.

The audit intentionally avoided touching the established CT/mask/dose/seed coordinate chain because the current viewer alignment is known to be correct.

## Confirmed Issues and Fixes

| Area | Confirmed Problem | Fix | Verification |
| --- | --- | --- | --- |
| Screenshot display in API-key mode | `/api/screenshot` returned `/api/screenshots/<file>.png`, but chat images are rendered through `<img>` and cannot attach `X-API-Key`. When API-key protection is enabled, generated screenshots could save successfully but fail to render in chat. | Added short-lived HMAC-signed screenshot URLs. `/api/screenshots/<file>` now accepts either normal API-key headers or a valid signed URL, still enforces PNG filenames and the screenshot directory boundary, and returns `Cache-Control: private`. | `web/server.py` compiles; diff review confirms signed URL creation and path validation are used by screenshot save/serve routes. |
| Screenshot annotation with signed URLs | `ui_annotate` extracted the filename by splitting on `/`, so a signed URL such as `file.png?expires=...&sig=...` would be treated as a literal filename and fail lookup. | Added URL parsing, filename validation, traversal-safe path resolution, and signed output URLs for annotated screenshots when API-key protection is configured. | `tool_factory/ui_annotate/__init__.py` compiles; helper tests cover signed filename extraction and traversal rejection. |
| Readiness blind spot | `/api/readiness` reported planning prerequisites but did not expose whether screenshot capture/feedback storage was writable, even though screenshots are required for UI-aware training and visual feedback. | Added a non-blocking `screenshots` readiness item. It does not gate clinical plan readiness, but surfaces screenshot-feedback deployment problems early. | `web/server.py` compiles; readiness item added after clinical KB so the existing clinical readiness gate remains unchanged. |
| Stale dose-model wording | A docstring in `plans/utilizations.py` still described `calculate_tmp_DVH_rate_v2` as using a Gaussian model even though the implementation calls the supplied dose model. | Updated the wording to match the active model-based implementation. No calculation code was changed. | `plans/utilizations.py` compiles; Gaussian search now only reports fail-closed legacy stubs, smoothing utilities, and documentation boundary notes. |

## Rechecked Non-Issues

- Environment variable reads such as `BRACHYBOT_API_KEY` are not secret leaks by themselves. The audit did not find newly hardcoded API keys in the reviewed diff.
- The manual-dose path remains tied to myDoseNet/planning pipeline boundaries. Legacy analytical/Gaussian utility entry points continue to fail closed rather than silently generating clinical-looking dose estimates.
- The global frontend `fetch` wrapper can attach `X-API-Key` to normal API calls; the screenshot issue was specific to browser image loading, not all API access.

## Product-Level Addition

The implemented signed screenshot link path improves BrachyBot's UI-aware assistant workflow:

1. The frontend captures a viewer or UI panel.
2. The backend stores a bounded PNG under `uploads/screenshots`.
3. The backend returns a browser-renderable signed URL when API-key protection is active.
4. The chat image and `ui_annotate` can consume the same URL without weakening the rest of the API.
5. Readiness can flag missing screenshot write permissions before a training or visual-feedback session fails.

This is intentionally narrow: it strengthens a core user-facing loop without changing dose calculation, segmentation, planning, or coordinate transforms.

## Residual Risks

- Runtime server smoke testing was limited by the local Windows environment and project dependency footprint. Static compilation and targeted helper checks were used for this pass.
- Signed screenshot URLs currently use a one-hour default lifetime for generated links and private browser caching for five minutes. Deployments with stricter PHI retention policies may lower that TTL.

## Files Changed

- `web/server.py`
- `tool_factory/ui_annotate/__init__.py`
- `plans/utilizations.py`
- `README.md`
- `docs/THIRD_PARTY_REAUDIT_2026-07-02.md`
