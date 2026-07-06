# Remaining Issues After adfc27a — Should Fix (5)

**Context:** After commit `adfc27a` fixed 24 issues from the 95-issue review,
these 5 items remain unfixed and should be addressed before the next deployment.

---

## H1. `_record_experience` crashes when `_init_self_evolution` fails

| Field | Value |
|-------|-------|
| **File** | `AgenticSys.py` (init), `agent_runtime/chat_workflows.py:1469` (crash site) |
| **Fix** | `agent_runtime/chat_workflows.py` or `AgenticSys.py` |
| **Effort** | 1 line |

**Problem:** `_init_self_evolution()` at `AgenticSys.py:420-432` catches import
failure and logs a warning, but does NOT set `self.exp_memory = None`. When
`_record_experience` at `chat_workflows.py:1469` accesses `if not self.exp_memory:`,
Python raises `AttributeError` because the attribute was never created.

```python
# AgenticSys.py:431 (except block, current — missing line):
    except Exception as e:
        logger.warning(f"Self-evolution system not available: {e}")
        # self.exp_memory = None   ← missing
```

**Trigger:** Any `memory` module import failure — missing dependency, corrupted
`.pyc`, broken install. This can happen transiently during deployment or
dependency upgrades.

**Impact:** Every user message raises `AttributeError`. Chat completely
unusable. Server must be restarted to recover.

**Fix:** Add `self.exp_memory = None` in the except block:

```python
    except Exception as e:
        logger.warning(f"Self-evolution system not available: {e}")
        self.exp_memory = None
```

---

## H3. Missing `_cancelled()` check at streaming loop top

| Field | Value |
|-------|-------|
| **File** | `agent_runtime/llm_runtime.py:1286` |
| **Fix** | Same file |
| **Effort** | 4 lines |

**Problem:** The non-streaming LLM loop checks `self._cancelled()` at every
iteration top (line 338). The streaming loop (`_run_llm_function_calling_stream`)
starts its `while True` at line 1286 WITHOUT this check. Cancel is only checked
inside the tool execution sub-loop (line 1541), NOT between LLM rounds.

```python
# llm_runtime.py:1286 (streaming — missing cancel check):
        while True:
            # ← no _cancelled() check here
```

**Trigger:** User clicks "Cancel" while streaming is waiting for LLM response
or processing tool results between rounds.

**Impact:** The system ignores user cancel and continues calling the LLM. UI
shows streaming responses after the user thought they cancelled. Confusing UX.

**Fix:** Add cancel check at loop top:

```python
        while True:
            if self._cancelled():
                logger.info("Stream cancelled by user")
                yield_event("done", {"final": str("Cancelled")})
                return
```

---

## H6. Inline path validation bypasses centralized `_validate_path`

| Field | Value |
|-------|-------|
| **File** | `web/server.py:261-275` (`api_viewer_image`) |
| **Fix** | Same file |
| **Effort** | 2 lines |

**Problem:** `api_viewer_image` validates the user-supplied file path with a
hardcoded `startswith(upload_dir)` check instead of calling the shared
`_validate_path()` function. This bypasses `BRACHYBOT_CT_DATA_ROOTS` and other
env-var-based directory expansions that all other routes respect.

```python
# server.py:272-275 (current — bypasses _validate_path):
upload_dir = os.path.realpath(os.path.join(...))
if not image_path.startswith(upload_dir + os.sep):
    return jsonify({"error": "Access denied"}), 403
```

**Trigger:** User configures `BRACHYBOT_CT_DATA_ROOTS` to include a custom data
directory, then tries to view an image from that directory via the viewer.

**Impact:** Other routes (segmentation, planning, planning run-step) respect the
env-var allowlist. This one route doesn't, creating an inconsistent user
experience where planning succeeds but the resulting image cannot be viewed.

**Fix:** Replace inline check with `_validate_path`:

```python
if not _validate_path(image_path, purpose="read"):
    return jsonify({"error": "Access denied"}), 403
```

---

## I20. Hardcoded organ label IDs 1-6 — labels >6 never rendered in 3D

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-layout.js:680` |
| **Fix** | Same file |
| **Effort** | 2 lines |

**Problem:** `reconstructOrgan3D` loops over exactly 6 hardcoded label IDs.
TotalSegmentator produces 104+ organ classes with label IDs up to 119. Any
organ with label ID >6 (stomach=7, duodenum=8, colon=9, etc.) is silently
skipped and never appears in 3D.

```javascript
// viewer-layout.js:680 (current — hardcoded subset):
const labelIds = [1, 2, 3, 4, 5, 6]; // All non-background labels
```

**Trigger:** User segments a CT scan and tries to view any organ other than the
first 6 (liver, kidney, spleen, pancreas, gallbladder, esophagus — roughly).
The 3D reconstruction shows only those 6 structures.

**Impact:** The 3D view shows only 6 of 100+ possible organs. Other OARs are
invisible, potentially causing the clinician to miss critical anatomical
structures during review.

**Fix:** Read actual labels from the loaded label map:

```javascript
const ctvLabels = window._ctvLabelMap || {};
const actualLabels = Object.keys(ctvLabels).map(Number).filter(k => k > 0);
const labelIds = actualLabels.length > 0 ? actualLabels : [1, 2, 3, 4, 5, 6];
```

---

## I21. Dose texture: sequential HTTP per vertex — unusable for large meshes

| Field | Value |
|-------|-------|
| **File** | `web/app/static/js/brachybot-viewer-layout.js:1008` |
| **Fix** | Same file |
| **Effort** | ~20 lines |

**Problem:** `_applyDoseTextureToMesh` loops over vertices with
`await _sampleDoseNormalizedAtIndex(idx)` — 1 HTTP fetch per vertex. For a
25K-vertex mesh with `sampleEvery=2`, this is 12,500 sequential requests.
At 50ms each, that's ~10 minutes.

```javascript
// viewer-layout.js:1008 (current — 1 fetch per vertex):
for (let i = 0; i < positions.length; i += sampleEvery) {
    const idx = ...;
    const doseNorm = await _sampleDoseNormalizedAtIndex(idx);
    // ...
}
```

**Trigger:** User enables "dose texture" mode on the 3D view.

**Impact:** The feature is effectively unusable. The browser hangs for minutes
with no visible progress, appearing to the user as if the application has
crashed.

**Fix:** Batch requests by Z-slice:

```javascript
// Group vertices by Z-slice, fetch each slice once:
const sliceRequests = {};
for (let i = 0; i < positions.length; i += sampleEvery) {
    const zSlice = Math.round(positions[i + 2]);
    if (!sliceRequests[zSlice]) sliceRequests[zSlice] = [];
    sliceRequests[zSlice].push(i);
}
// Fetch all unique slices in parallel:
const sliceDataMap = {};
const zValues = Object.keys(sliceRequests).map(Number);
const results = await Promise.all(
    zValues.map(z =>
        fetch(`/api/planning/dose_overlay_slice?z=${z}`)
            .then(r => r.json())
            .then(data => { sliceDataMap[z] = data; })
    )
);
// Apply fetched data:
for (const [z, indices] of Object.entries(sliceRequests)) {
    const sliceData = sliceDataMap[z];
    if (!sliceData) continue;
    for (const idx of indices) { /* apply sliceData to vertex idx */ }
}
```

---

## Summary

| ID | Severity | File | Fix effort | Auto-triggered? |
|----|----------|------|-----------|----------------|
| H1 | HIGH | `AgenticSys.py:431` | 1 line | Every message if memory module broken |
| H3 | HIGH | `llm_runtime.py:1286` | 4 lines | Every streaming cancel |
| H6 | HIGH | `server.py:272` | 2 lines | Config with custom data roots |
| I20 | IMPORTANT | `viewer-layout.js:680` | 2 lines | Every 3D reconstruction |
| I21 | IMPORTANT | `viewer-layout.js:1008` | ~20 lines | Every dose texture enable |

**Estimated total fix time:** 30 minutes (with verification).

All five are independent and can be fixed in any order.
