# Remaining Issues After adfc27a — Re-verified & Fixed (2026-07-07)

## Verification Results

| ID | Severity | Claim | Re-verdict | Fixed? |
|----|----------|-------|------------|--------|
| H1 | HIGH | `_record_experience` crashes if `_init_self_evolution` fails | **CONFIRMED REAL.** Line 1472 uses bare `if not self.exp_memory:` → `AttributeError` if import fails. `get_status()` at line 1944 already uses safe `getattr(self, "exp_memory", None)` pattern. | ✅ Yes |
| H3 | HIGH | Missing `_cancelled()` at streaming loop top | **CONFIRMED REAL.** Non-stream has it (line 338); stream does not. User cancel between LLM rounds is silently ignored. | ✅ Yes |
| H6 | HIGH | `api_viewer_image` bypasses centralized `_validate_path` | **CONFIRMED REAL — low impact.** The inline `startswith(upload_dir)` is secure against traversal, but ignores `BRACHYBOT_{CT,MR,US}_DATA_ROOTS` env-var expansion. Users with custom data roots cannot view images here. | ✅ Yes |
| I20 | IMPORTANT | Hardcoded label IDs `[1,2,3,4,5,6]` miss labels >6 | **CONFIRMED REAL.** `window._ctvLabelMap` IS populated from server (viewer-volume.js:251) but unused in `reconstructOrgan3D`. Labels >6 (e.g. stomach, duodenum) never reconstruct in 3D. | ✅ Yes |
| I21 | IMPORTANT | Sequential HTTP per vertex — "10 minutes" | **PARTIALLY CORRECTED.** `_fetchDoseRawAxialSlice` caches by Z-slice (`state.doseTexture.rawAxialSlices`), so unique requests = number of Z-slices (50-200), not vertex count (12,500). Actual latency is ~2-10 seconds for typical volumes, not 10 minutes. Still worth batching for near-instant response. | ✅ Yes |

## Fix Details

### H1 — `chat_workflows.py:1472` (1 line)

```diff
-       if not self.exp_memory:
+       if not getattr(self, "exp_memory", None):
```

Changed bare attribute access to `getattr` with safe default, matching the existing pattern in `get_status()` at line 1944.

### H3 — `llm_runtime.py:1288-1297` (6 lines)

Added cancel check at top of streaming while-loop:

```python
while iteration < max_iterations:
    iteration += 1
    if _cancelled():
        logger.info("Streaming cancelled by user between LLM rounds")
        yield_event("done", {"final": "", "cancelled": True})
        return
```

### H6 — `server.py:285-290` (3 lines)

Replaced inline `startswith(upload_dir)` with centralized `_validate_path`:

```python
if not _validate_path(image_path, purpose="read"):
    return jsonify({"error": "Access denied"}), 403
real_image_path = os.path.realpath(image_path)
```

### I20 — `viewer-layout.js:679` (3 lines)

Read actual label IDs from `window._ctvLabelMap` instead of hardcoding [1..6]:

```javascript
const _lm = window._ctvLabelMap || {};
const ids = Object.keys(_lm).map(Number).filter(k => Number.isFinite(k) && k > 0);
const labelIds = ids.length > 0 ? ids : [1, 2, 3, 4, 5, 6];
```

### I21 — `viewer-layout.js:1002-1015` (+15 lines for pre-warm)

Added a pre-warm phase that collects all unique Z-slice indices referenced by mesh vertices and fetches them in parallel via `Promise.all(...zSet.map(z => _fetchDoseRawAxialSlice(z)))`. After the warm-up, the per-vertex loop in lines 1012+ gets a cache hit for every vertex, so `await _sampleDoseNormalizedAtIndex(idx)` returns instantly. No sequential HTTP.

## Issues Re-classified After Re-verification

| Original ID | Original severity | New assessment |
|-------------|-------------------|----------------|
| H6 | HIGH | HIGH — functional gap for users with custom data roots |
| I21 | IMPORTANT (10 min) | IMPORTANT (~2-10 sec without fix, instant with fix) |
