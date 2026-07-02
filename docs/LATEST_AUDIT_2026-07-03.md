# BrachyBot Audit and Fixes - 2026-07-03

## Scope

This pass re-audited the latest GitHub version from a clean third-party perspective, then fixed only issues that were verified in code.

## Verified Issues Fixed

### 1. Screenshot-to-LLM analysis loop was incomplete

- Problem:
  - `ui_screenshot` captured and displayed the image in chat, but the frontend did not send the captured screenshot back to the LLM for multimodal analysis.
  - The user therefore received a generic placeholder reply instead of an answer grounded in the screenshot.
- Fix:
  - Added a hidden follow-up chat queue in `web/app/index.html`.
  - After the frontend uploads a screenshot successfully, it now sends:
    - the persisted screenshot marker
    - the original analysis question
  - The follow-up is sent only after the active stream finishes, so screenshot analysis does not race the current turn.

### 2. Screenshot placeholder replies polluted the UX

- Problem:
  - Screenshot-only turns produced generic text such as `Requested screenshot: ...`.
  - This created visible duplicate bot output and distracted from the actual image.
- Fix:
  - The frontend now detects screenshot-only acknowledgement responses and suppresses them from the visible chat.
  - The actual screenshot remains visible, and the hidden multimodal follow-up produces the real answer.

### 3. Signed screenshot URLs broke local multimodal file resolution

- Problem:
  - `_build_multimodal_content()` derived the filename with `split("/")[-1]`.
  - Signed links such as `/api/screenshots/foo.png?expires=...&sig=...` therefore produced an invalid local filename.
- Fix:
  - Switched to `urlparse()` + `unquote()` + basename extraction in `AgenticSys.py`.
  - The backend now resolves the local screenshot file correctly and base64-encodes it for provider-safe multimodal delivery.

### 4. Anthropic multimodal adaptation was broken

- Problem:
  - The Anthropic adapter converted list-based user content to `str(content)`.
  - Screenshot multimodal messages were therefore flattened into plain text instead of image blocks.
- Fix:
  - Added explicit OpenAI-style block -> Anthropic block conversion in `brain/providers/anthropic_llm.py`.
  - `text` blocks remain text.
  - `image_url` data URLs are converted into Anthropic `image` blocks with base64 payloads.

### 5. Gemini image MIME type was wrong

- Problem:
  - The Gemini adapter hard-coded screenshot data URLs as `image/jpeg`.
  - The captured screenshots are PNGs.
- Fix:
  - Gemini now extracts the MIME type from the data URL and forwards the correct media type.

### 6. DVH redraw cache was stale and structurally under-keyed

- Problem:
  - `drawDVH()` skipped redraws based only on organ names.
  - If the DVH values changed while the same organs remained present, the chart could stay stale.
  - The prescription marker could also go stale when only Rx changed.
- Fix:
  - Added a deterministic DVH signature built from:
    - all `dose_bins`
    - all `volume_pcts`
    - current prescription Gy
  - DVH redraw now tracks actual chart content, not only organ keys.

### 7. Screenshot prompt modules were internally inconsistent

- Problem:
  - Some prompts still instructed the model to answer immediately after `ui_screenshot`, before any screenshot returned.
  - That contradicted the intended multimodal loop.
- Fix:
  - Updated `config/prompts/visual_proactive.md` and `config/prompts/planning_agent.md`.
  - Prompts now distinguish:
    - backend/tool state inspection
    - visual confirmation by screenshot
    - screenshot-first, answer-after-image behavior

## Product-Level Improvement Added

### Cross-provider screenshot analysis flow

The web UI now supports a complete screenshot analysis round-trip:

1. LLM calls `ui_screenshot`
2. Frontend captures the requested UI target
3. Frontend persists the screenshot
4. Frontend shows the image to the user
5. Frontend sends a hidden multimodal follow-up turn
6. Backend normalizes the screenshot into provider-safe multimodal input
7. The selected LLM answers from the actual screenshot

This was the most impactful missing product capability because it directly affected visual QA, dose explanation, viewer troubleshooting, and training interactions.

## Validation Performed

- Python syntax validation:
  - `AgenticSys.py`
  - `brain/providers/anthropic_llm.py`
  - `brain/providers/gemini_llm.py`
- Inline HTML script parse validation with Node.js:
  - `web/app/index.html`
- Focused behavior checks:
  - signed screenshot URL -> local base64 image resolution
  - Anthropic multimodal block conversion
  - Gemini MIME extraction from screenshot data URLs

## Remaining Notes

- The screenshot analysis round-trip depends on the web frontend because the browser owns the actual DOM capture.
- Non-frontend clients that only call `ui_screenshot` without returning the captured image will still only get the screenshot request acknowledgement.
