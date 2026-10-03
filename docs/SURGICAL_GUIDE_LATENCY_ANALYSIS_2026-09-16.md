# Surgical Guide Generation Latency Analysis Report

- Date: 2026-09-16
- Scope: `web/surgical_guide.py` (4286 lines), `web/routes/surgical_guide_routes.py`, `tool_factory/surgical_guide/__init__.py`, and the trigger paths of the frontend `brachybot-surgical-guide.js`
- Method: **read-only code review + measurement from existing server logs + 1/8-scale microbenchmark extrapolation** (no code was modified, no cases were altered)
- Goal: to provide acceleration options and expected benefits on the premise that **results and quality remain unchanged**
- Original prediction: field observations showed about **250–400s** for a single run; the original proposal estimated **60–110s (about 3–5x)** after optimization. This is a prediction based on logs and extrapolation, not a verified gain. The implementation review and paired measurements below are new; the original analysis is retained as the source of the proposals.

## Implementation Review (2026-09-16, takes precedence over the original proposal's equivalence and benefit statements)

This review uses the actual working tree of the remote `codex/session-task-recovery` as the baseline (HEAD `d09a104ea`, including the then-uncommitted guide fix), rather than overwriting the working tree with a clean HEAD. The complete old module is saved at `tests/data/surgical_guide_latency_reference.py` with SHA-256 `dad562e79d2036fb836c2656f487658bf3344675bd09f8bf08186b839f1f06ff`. Hashes of external geometry dependencies are pinned by `tests/guide_latency_reference.json` / `scripts/guide_latency_reference_guard.py`; any modification to a dependency must be re-reviewed to avoid drift on both sides at once.

### Corrections to the Original Report

1. **P0 must cover the public generation entry point.** Changing only the HTTP route cannot merge direct tool invocations. We now use in-process in-flight merging inside `generate_surgical_guide`, with a key that includes the same memory instance; CT content/shape/type/spatial metadata; planning identity and geometry; manual version; manufacturing parameters; and the selected needle tracks. Only overlapping requests are merged; an explicit subsequent regeneration still re-executes, avoiding stale result caching. Different processes or different memory instances do not share in-flight results. Keys are cleaned up on failure, and waiters can cancel independently.
2. **P1's narrow-band sentinel approach cannot be implemented as originally argued.** `_remove_truncated_cap_backed_voxels` reads the actual values of `signed_distance` and then compares them against the distance to the truncation plane; not all downstream consumers read only a fixed threshold. The original report also did not prove that the interpolated label SDF satisfies the Lipschitz bound used. The full SDF and the original resampling path remain unchanged.
3. **P2/P4's mathematical equivalence is not the same as bit-for-bit floating-point equivalence.** The cylindrical formula that changes the order of world/index coordinate operations was not adopted. The original float64 physical transform, expression order, and boundary checks are preserved; only broadcast grids and sparse solid indexing are used to reduce work. Patches are processed only within the local box around the entry sphere, preserving the original float32 entry quantization; near the critical band it falls back to the original cKDTree decision.
4. **The default grid's blur is actually an identity operation.** The current `blur_sigma=min(0.4, 0.35*min(spacing))` is in voxel units; the default 0.2 mm yields 0.07, and the discrete kernel radius for SciPy's default truncate=4 is zero. The original report's estimate of filter cost assuming sigma=0.35 voxels does not match the code. Directly generating the float32 binary array that the original MC ultimately receives is strictly equivalent; a non-zero-radius float64 filter was not changed to float32.
5. **MC cropping must preserve the original coordinate rounding.** After cropping the default binary field, integer/half-integer vertices are first extracted on the unit grid, the original grid offset is restored, and only then are the original spacing multiplication and float32 rounding performed, followed by smoothing and transform; this is not simply adding an offset to already-smoothed world coordinates. Cases such as non-binary fields and non-zero-radius blur use the original path.
6. **The CPU work of duplicated computation cannot be directly multiplied into a latency benefit.** Two overlapping calls share CPU/memory bandwidth, so the wall-clock benefit of cancelling one must be measured in the field; this paired-generation test did not count the theoretical benefit of running twice.
7. Microbenchmark volume scaling does not guarantee linear wall-clock extrapolation: MC output size, memory bandwidth, concurrent load, and topology repair all affect the actual result. The measured environment is NumPy 2.4.6, SciPy 1.15.3, scikit-image 0.26.0, SimpleITK 2.5.0; the SciPy 0.3.31 in the original appendix is not the version of this environment.

### Implemented Optimizations

- The shared generation entry point merges overlapping identical requests for the same case; stage logs now include a `call_id`.
- Cylinders use sparse broadcasting while preserving the original formula; bore cutting is only computed for solid voxels, while auxiliary holes retain the original order and support review.
- A local sphere at the entry replaces the batch nearest-neighbor query over the entire skin shell; near the threshold the original decision is still used.
- Connected components are labeled only within non-empty bounding boxes, preserving scan order and equal-size component tie-breaking; the full shell point table is built only when bridging is needed.
- The default binary field directly generates the float32 MC input and crops blank regions, preserving the original vertex coordinate rounding, face order, and smoothing pipeline.
- Bore-wall projection preserves the original full axial matrix multiplication, computing radial distance only for vertices selected by the axial and bounding-box filters; cross-bore protection is unchanged.
- Additional profiling found that an 8-needle case still had 125 bore-wall projections and about 15,500 cross-bore checks: per-coordinate filtering was adopted to avoid N×3 temporary boolean arrays, and bounding boxes with conservative numeric margins exclude bore pairs that are definitely disjoint. The original decision for the remaining bore pairs is fully preserved.
- Taubin smoothing reuses sparse product buffers; the execution order of division, subtraction, multiplication, and addition and the float64 precision remain unchanged, and the original 20 bidirectional iterations are still performed.
- The watertightness check losslessly encodes undirected edges as uint64 before counting; all edge multiplicity, open-edge, and non-manifold-edge decisions are unchanged.
- Topological repair morphological operations are restricted to the solid bounding box plus a two-layer full halo, preserving the real array boundaries and the original repair order.
- The body-surface cache uses CT content and spatial information, threshold, and smoothing parameters as its key, isolated per memory, retaining at most two entries with weak-reference ownership; the original boundary body surface and the smoothed body surface are reused together.

The default manufacturing grid of 0.2 mm, 5 mm truncation, wall thickness, all needle-track/bore constraints, and quality rejection conditions are unchanged. `BRACHYBOT_GUIDE_FAST_PATH=0` reverts this numeric fast path and the entry merging/body-surface cache, facilitating A/B comparison within the same deployment.

### Verification Method and Applicable Boundaries

`scripts/benchmark_surgical_guide_latency.py` restores CT/needle tracks read-only from a saved Session into isolated memory and calls the full guide generation function, without calling `save_guide_version`, HTTP, UI, or the actual Session checkpoint. Running the frozen baseline and the current code separately, after checking that snapshot/CT/parameters/planning signatures match, it performs SHA-256 comparisons on vertices, triangles, auxiliary holes, and the entire validation with timing removed. Generation time excludes loading, browser download/rendering, and persistence; process peak RSS includes input restoration and digest computation.

This proves that the generated results for the tested cases are element-wise identical, but it is not the same as having measured all cases or the browser-side end-to-end latency. During testing the server had other workloads, so single-run timings fluctuate; historical congestion logs were not used as a same-condition baseline.

### Final Paired Measurements

The following are `stage_timings_seconds.total` inside the generation function; all tests used independent process cold starts, and body-surface cache hits or concurrent deduplication benefits were not counted:

| Input/Config | Frozen baseline | Optimized | Speedup | Process peak RSS (before → after) | Output comparison |
|---|---:|---:|---:|---:|---|
| Truncated FOV, 4 effective needle tracks at the end, 0.2 mm, frozen snapshot re-run | 19.081 s | 6.646 s | 2.87× | 6.87 → 3.92 GiB | All five hashes identical |
| 8 needles, 0.2 mm | 27.539 s | 10.328 s | 2.67× | 8.13 → 4.19 GiB | All four hashes identical |
| 50 needles, including topology repair, 0.2 mm | 119.178 s | 43.227 s | 2.76× | 9.76 → 5.21 GiB | All four hashes identical |
| Same 8-needle input, independent test at 0.35 mm | 7.625 s | 4.205 s | 1.81× | 2.73 → 1.98 GiB | All four hashes identical |

The four hashes are vertices, faces, auxiliary_holes, and the complete validation after removing timing fields; they include bore diameter error, support QA, truncation-plane decisions, all topology repair attempts and results. The fifth is needle_paths. Another re-run of the 8-needle case was 26.178→10.527 s, with all five hashes also identical. 0.35 mm is only an isolation verification parameter and does not change the case or the product defaults. Another old case could not be recovered because its saved CT path could not be restored, so it was not included in the paired sample; that case's data was not modified.

The 4-needle case had an initial baseline of 27.745 s, but the online service subsequently updated its Session snapshot. Even though the CT/planning signatures and geometry results all matched, cross-snapshot time pairing was still not used; after re-freezing the snapshot manifest, the 19.081→6.646 s in the table above was obtained. This also shows that historical timings under different loads cannot be treated as a definite gain.

In the 50-needle case, plate_patch went 13.300→5.586 s, mesh_extraction_and_validation 24.528→7.658 s, and mesh_topology_repair 67.899→22.390 s. The total before the additional bore-wall optimization was 64.222 s, and after it was 43.227 s; the corresponding 8-needle case was 13.930→10.328 s.

Final geometry/runtime/existing guide regression: **96 passed, 3 pre-existing SWIG DeprecationWarnings**. Differential coverage includes rotated/anisotropic cylinders, sparse bore cutting, entry-sphere thresholds, random topology and coordinate offsets, different grid resolutions, connected-component ties and empty inputs, bridging, bore-wall projection and cross protection, morphological halo/real boundaries, edge counting, smoothing rounding, cache invalidation isolation, and in-flight failure cleanup/waiter cancellation. The complete reference module and dependency hashes are retained with the code.

Re-runnable scripts:

```bash
python scripts/benchmark_surgical_guide_latency.py --workspace <saved-session> --variant baseline --output /tmp/guide-before.json
python scripts/benchmark_surgical_guide_latency.py --workspace <same-saved-session> --variant current --output /tmp/guide-after.json
python scripts/summarize_guide_latency.py --pair case /tmp/guide-before.json /tmp/guide-after.json --output /tmp/guide-paired-summary.json
```

Aggregate evidence: `docs/benchmarks/surgical_guide_latency_2026-09-16.json`. The comparison script requires matching input fingerprints and all output hashes on both sides before producing a summary; subsequent re-runs also record the needle-track source `needle_paths`, avoiding comparing only the mesh while missing needle-track metadata. When an online case is updated, use `--snapshot-file <frozen-manifest.json>` to freeze the snapshot manifest on both sides; resources are still resolved from the original read-only workspace.

### Follow-up Items Worth Exploring but Not Enabled by Default This Time

- A more complete spatial index could further reduce bore-wall scanning, but if the BLAS matrix multiplication shape is changed before/after point selection, the rounding path may differ, so a new strict differential must be done first.
- A coarse-fine hierarchical SDF would need to maintain both the truncation-plane distance semantics and a provable error bound; the original P1 out-of-band sentinel cannot be used directly.
- Cross-process task merging and reuse of completed results require stable case identity, version, failure/cancellation, and persistence transaction contracts; this time only in-process, same-memory merging of overlapping computations was implemented.
- The extra time of browser download, STL serialization, and checkpoint needs separate end-to-end observation; this table does not include those times. Shared server load still affects wall-clock time, so it cannot be promised that all several-hundred-second cases will drop to a fixed number of seconds.

---

## 1. Current State and Measured Data

### 1.1 Pipeline and Code Locations

`generate_surgical_guide()` (`web/surgical_guide.py:3396`) executes sequentially within one thread:

| # | Stage (log name) | Code | Scale/Notes |
|---|---|---|---|
| 1 | `skin_envelope` | `_body_mask` 1438 / `_largest_component` 1427 / `_smooth_body_mask` 1716; 3441–3461 | Full CT (201×313×403 ≈ 25.3M voxels): threshold + connected components ×3 + closing + hole filling + anisotropic Gaussian |
| 2 | `skin_surface_persisted` | `store_guide_skin_surface` 1454 | Persist the body-surface mask to the session |
| 3 | `local_grid_resampled` | `_resample_mask_to_local_grid` 2849; 3523–3547 | Source crop (CT resolution) dual EDT → trilinear sampling on the 0.2mm grid of **931×436×1496 = 607,250,336 voxels** (SDF + mask) |
| 4 | `skin_distance_field_reused` | 3548–3555 | Reuse the SDF from the previous step (0.0–0.03s) |
| 5 | `plate_patch` | 3572–3612; `_connect_plate_patch_components` 2744 | Full-grid boolean band (`~body & od∈[c,c+t] & safety`), `np.argwhere` 8.79M points, KD-tree query, `ndimage.label` 607M |
| 6 | `auxiliary_holes` | 3618–3661; `_auxiliary_hole_specs` 415, `_auxiliary_hole_support` 2257 | 36 needles × 2 rings × 12 holes = **864 candidates**, per-candidate SDF box + sampling validation (measured realized 503) |
| 7 | `primary_sleeves_and_bores` | 3669–3723; `_primary_bore_cutter_specs` 339 | Union of 36 sleeves + 36 primary bore cuts (the cut length is extended when crossing sleeves) |
| 8 | `solid_cleanup` | 3729–3804; `_retain_largest_printable_component` 2335, `_primary_sleeve_support_quality` 2407, `_face_component_count` 2632 | Truncated-cap removal, `ndimage.label`, per-bore ring sampling QA |
| 9 | `mesh_extraction_and_validation` | 3822–3840; `_mesh_from_mask` 3013, `_smooth_mesh_vertices` 3070, `_project_bore_walls` 3131, `mesh_validation` 3344 | Full-grid `float64` conversion + Gaussian + `np.pad` + Marching Cubes + Taubin + per-bore-wall projection |
| 10 | (Optional) `mesh_topology_repair` | 3841–4010 | Heavyweight repair path when the mesh is not watertight (can amplify into multiple rebuilds) |
| 11 | Persistence and return | 4015–4184 | QA summary, STL serialization, `save_guide_version` |

### 1.2 Server Log Measurements (2026-09-16 17:54–17:57, same case)

```
17:54:50.657 skin_envelope              5.735s
17:54:50.743 skin_surface_persisted     0.086s
17:55:28.620 local_grid_resampled      37.877s   grid_shape=(931,436,1496) 607,250,336 voxels
17:55:28.640 skin_distance_field_reused 0.021s
17:55:49.528 skin_envelope              9.025s   ← second run (see 1.3)
17:55:49.596 skin_surface_persisted     0.069s
17:56:07.058 plate_patch               38.418s   plate_voxels=8,793,204 initial_components=1 bridges=0
17:56:24.303 auxiliary_holes           17.244s   requested=864 realized=503
17:56:37.957 local_grid_resampled      48.360s   ← second run (see 1.3)
17:56:59.902 primary_sleeves_and_bores 35.599s   needle_count=36
```

The 16:40 round of the same log: `skin_envelope` 10.36s + 10.13s, `local_grid_resampled` 75.82s (that round was interrupted and did not finish).

**Total of measured stages (part of a single invocation) ≈ 190–200s**; stages such as `solid_cleanup`, `mesh_extraction_and_validation`, and persistence were not captured in the logs, and extrapolating per the microbenchmark in Section 1.4 gives about **30–90s**, consistent with the user's perceived "several hundred seconds".

### 1.3 Key Finding: Two Generations Ran Concurrently for the Same Case (Duplicate Execution)

Within the 17:54–17:57 window there was only one `Executing tool: surgical_guide` (17:54:44.897), but the following appeared:

- Two `skin_envelope` segments (17:54:50 and 17:55:49);
- Two `local_grid_resampled` segments (37.9s and 48.4s).

Back-calculating the start point of each segment from its duration reconstructs two concurrent pipelines:

- **Invocation A (chat tool)**: starts 17:54:44.9 → skin(5.7) → local_grid(37.9) → plate(38.4) → aux(17.2) → sleeves(35.6);
- **Invocation B (starts around 17:55:40, no `Executing tool` in the log)**: skin(9.0) → local_grid(48.4) → …

The entry points of the two paths are respectively:

- Chat tool: `tool_factory/surgical_guide/__init__.py:217` → `generate_surgical_guide(...)`;
- Frontend "auto-generate": `web/app/static/js/brachybot-surgical-guide.js:800-833` calls `POST /api/surgical-guides/generate` (`web/routes/surgical_guide_routes.py:240-292`) when the state is `not_generated/stale` and `autoGenerate === true`.

The frontend has `autoGeneratedSignatures` (deduplication by signature, `brachybot-surgical-guide.js:817`), but **the server side has no in-flight/result deduplication at all**: the chat tool and the API each run one copy, concurrently writing to the same case. B at least duplicated A's skin+resample (≈57s), and would continue duplicating plate/aux/sleeves. The 16:40 round likewise had a double `skin_envelope` (11.2s apart).

**This is the highest-benefit, lowest-risk item (see P0).**

### 1.4 Resource Profile and Microbenchmark

- 0.2mm local grid = **607M voxels**; resident array estimates:
  - `skin_signed_distance` float32 = **2.43 GB**
  - `body_crop` / `plate_mask` / `patch_mask` / `solid` / `boundary_safe_mask` each bool ≈ **0.61 GB × 5**
  - Stage 5 additionally has `plate_voxel_indices` (8.79M×3 int64 ≈ 211 MB) and a KD-tree structure
  - **resident at the plate_patch point ≈ 6–7 GB**
- `_mesh_from_mask` (3013): `mask.astype(np.float64)` (4.86 GB) + `gaussian_filter` output float64 (4.86 GB) + `np.pad` (≈4.9 GB) + `marching_cubes` internals → **peak >15 GB**, occupying process memory for a long time.
- 1/8-scale microbenchmark (75.8M voxels, script `/tmp/opencode/guide_bench.py`, for extrapolation reference only):

| Operation | 1/8 measured | ×8 extrapolated |
|---|---|---|
| `float64` conversion | 0.30s | ≈2.4s |
| Gaussian (σ=0.35 vox) | 0.74s | ≈5.9s |
| `np.pad` | 0.33s | ≈2.6s |
| Marching Cubes (lewiner) | 1.09s | ≈8.7s |
| `ndimage.label` (6-connected) | 0.46s | ≈3.7s |
| `np.argwhere` | 0.47s | ≈3.7s |
| Single full-grid bool operation | 0.168s | ≈1.3s |

> Note: the microbenchmark mask is denser than the real guide solid body (argwhere/label are pessimistic upper bounds); the Marching Cubes cost is approximately linear in voxel count, so the extrapolation is trustworthy.

---

## 2. Hotspot Analysis and Optimization Proposals

Each item is labeled: cost source → proposal → **equivalence argument** → expected benefit → risk. Equivalence falls into three categories:
- **[Bit-for-bit equivalent]** operation cropping/index reordering/batch merging; boolean results and the vertex numeric path are unchanged;
- **[Threshold equivalent]** only values not involved in the decision are changed (downstream only compares), so the decision result is identical;
- **[Within QA tolerance]** micrometer-level differences caused by a changed floating-point path, requiring geometric-tolerance acceptance (not preferred).

### P0 Server-Side Generation Deduplication and Merging (risk ≈0, highest benefit)

- **Problem**: Section 1.3 measured two concurrent generations for the same case; frontend deduplication covers only its own path.
- **Proposal**: add a **per-case generation registry** in `web/routes/surgical_guide_routes.py` (`(user, session, planning_signature, parameters_hash, needle_set) → Future/result`):
  - Already running: the second caller waits directly on the same Future (or returns an "in progress" status) and does not start a second copy;
  - Already completed with a matching key: directly reuse the current guide version (`_resolve_guide_version` already has signature/version logic, 4015–4040);
  - Clean up the registry when the generation thread completes/fails; implement with `threading.Lock` + a `threading.Event` per key, with no need to change geometry code.
- **Equivalence [bit-for-bit]**: only affects "who executes"; the result is still the same `generate_surgical_guide` output and goes through the same `save_guide_version`/`publish_active_planning_guide`.
- **Expected benefit**: eliminates the observed duplicate execution; one full generation can be directly saved from a single run's duration (measured at least 57s of duplicated skin+resample; a full copy is roughly equal to the overall duration). If double-running is currently the norm, end-to-end is **close to 2x**.
- **Risk**: need to handle "different parameters during generation" (different `needle_ids`/parameters should not be merged) — distinguishing by the full key suffices; the key must be released after failure.

### P1 `local_grid_resampled`: from "full-grid 0.2mm sampling" to **narrow band + bounding box** (37.9–75.8s → estimated 8–20s)

- **Cost source** (`_resample_mask_to_local_grid` 2849–2947): `map_coordinates(order=1)` trilinear sampling at 607M target grid points; `sampled_signed_distance` itself is 2.43GB of write bandwidth. The two EDTs operate only on the source crop (CT resolution, ≈6M voxels) and are not the bottleneck.
- **Proposal** (recommended combination):
  1. **Coarse-fine two level**: first compute the same SDF on a 0.4–0.8mm coarse grid (607M/8 or /64) (same EDT + trilinear), then for each 0.2mm grid point use the coarse value + a conservative Lipschitz bound (the change of linear interpolation within a 0.2mm step ≤ √3·0.2mm, plus the coarse grid spacing) to determine whether it may fall into the subsequent threshold interval;
  2. Perform exact 0.2mm sampling only for grid points that "may fall into the interval"; write clamped sentinel values (e.g. `+1e6` / `0`) for the rest according to the upper/lower bound;
  3. Keep the existing sharding + thread pool in the sampling loop (`_resample_worker_count` 2833, `GUIDE_RESAMPLE_MAX_WORKERS=8`), but shards cover only the matched sub-intervals.
- **Threshold intervals** (determining the narrow-band width; all can be statically derived within `generate_surgical_guide`):
  - `plate_mask`: `outside_distance ∈ [protected_clearance, protected_clearance+plate_thickness]` (3572–3577);
  - `sleeve_mask`: `outside_distance >= protected_clearance` (3682–3686) — a **monotonic threshold**, amenable to conservative decision using coarse values;
  - `_remove_truncated_cap_backed_voxels` (2950) uses a 2D EDT + nearest index, not dependent on full-precision SDF;
  - the remaining `solid` composite parts (patch/aux/bores) do not read SDF values.
- **Equivalence [threshold]**: all downstream uses of `outside_distance` are `>=`/`<=` comparisons; writing strictly out-of-range sentinel values for out-of-band grid points leaves the decision result unchanged (in-band grid points still use the original exact sampling). Must preserve "band boundary ± conservative margin" during implementation and add differential tests.
- **Expected benefit**: in-band grid points are typically 10–30% (skin shell + crop range), reducing sampling and write bandwidth by **3–6x**; this stage goes 38–76s → **8–20s**, and `sampled_signed_distance` can be changed to sparse/blocked storage, lowering resident memory from 2.43GB to <0.8GB.
- **Risk**: the conservative bound of the two-level decision must be correct (recommended to verify point-by-point with a "frozen old-implementation differential", see Section 4); does not change the 0.2mm default resolution (does not sacrifice manufacturing precision).
- **Lower-risk variant (do first)**: compute only the **bounding box of the plate band** (obtained via coarse grid or a sharded threshold scan), restricting all subsequent full-grid operators (P2–P5) to the bbox; even without in-band refinement, a 1.5–3x gain can be obtained from the bbox/crop volume ratio.

### P2 `plate_patch`: full-grid scan + KD-tree → bounding box + direct indexing (38.4s → estimated 3–6s)

- **Cost source** (3572–3612): 3 full-grid booleans for `plate_mask` (≈1.3s each) + `np.argwhere(plate_mask)` (measured `solid` 8.79M points, `plate_mask` point count ≥ that value; int64 index ≥211MB) + `cKDTree(entry_indices).query(plate_voxel_indices)` (8.79M×36 distances) + another `ndimage.label(607M)` and `np.argwhere` inside `_connect_plate_patch_components`.
- **Proposal**:
  1. First use P1's bbox (or a sharded bounding-box scan of `plate_mask`) to restrict boolean and indexing operations to the bounding box;
  2. `np.argwhere` → `np.nonzero` (avoid the (N,3) copy) and immediately convert to int32;
  3. Change the patch decision to **chunked broadcasting** (approximate distances of 8.79M×36, processed in chunks) or directly "stamp a sphere per entry" (radius 24mm/0.2mm=120 voxels, setting `distance<=r` within each entry's local box) — both are exactly consistent with the boolean result of the existing KD-tree query (both are "Euclidean distance to the nearest entry ≤ patch_radius_index");
  4. `_connect_plate_patch_components` calls `label` only once and reuses the same label result (currently it already returns early when `initial_count<=1` and does not go through bridging, so the 38.4s mainly comes from items 1–3 above).
- **Equivalence [bit-for-bit]**: the boolean set is voxel-wise identical; the patch decision is a different evaluation order of the same inequality.
- **Expected benefit**: 38.4s → **3–6s** (bbox 2–4x + indexing/query 5–10x).
- **Risk**: low; must ensure chunk boundaries/sphere-stamping radius use the same discrete radius constant.

### P3 `auxiliary_holes`: 864 candidates each building a box → batch per needle, evaluate only on plate voxels (17.2s → estimated 3–6s)

- **Cost source** (3618–3661, `_auxiliary_hole_support` 2257, `_cylinder_sdf_in_region` 2137): each of the 864 candidates constructs a local-box world-coordinate grid and computes a flat-bottomed cylinder SDF; the validation stage additionally does two sparse samples.
- **Proposal**:
  1. **Share a bounding box per needle**: the 24 hole centers of the same needle all fall near the entry (offset ≤ `first_offset+ring_spacing`≈6mm, radius≈1.75mm, axial length `clearance+plate+8mm`×2 ≈ 22mm); merge the 24 holes into a single ~50×50×120-voxel box and build the grid once, reducing total box volume from ~93M to ~11M (≈8x);
  2. **Compute the SDF only for plate voxels**: `removable = solid & plate_mask & hole_mask`; within the box, first take the nonzero indices of `plate_mask` and compute the flat-bottomed cylinder inside/outside decision only for those points (analytic form, no whole-box world grid needed);
  3. The O(N²) primary-sleeve conflict check in `_auxiliary_hole_specs` (415–470: 36×864 segment distances) and the acceptance-stage O(A²) (320–410k pairs) are already minor, and could be vectorized/pruned, but it is not required.
- **Equivalence [bit-for-bit]**: the hole mask is the `<=0` decision of an analytic SDF; box merging and sparse point selection do not change the decision set.
- **Expected benefit**: 17.2s → **3–6s**.
- **Risk**: low; just keep `AUXILIARY_HOLE_OVERRUN_MM=8`, the radius, and the decision constants unchanged.

### P4 `primary_sleeves_and_bores`: 108 cylinders each building a box → index-space analytic form + current solid clipping (35.6s → estimated 8–15s)

- **Cost source** (3669–3723, `_cylinder_sdf_in_region` 2137, `_subtract_cylinder_specs_from_mask` 2191): 36 sleeves + 36 primary cuts (the cut length is expanded per `_primary_bore_cutter_specs` when crossing sleeves, making boxes larger) each construct a world grid (float64, multiple arrays) and compute an SDF; then large boxes are operated on with `solid[box] |= ...` / `&= ~...`.
- **Proposal**:
  1. **Analytic form in index space**: the local grid is isotropic and axis-aligned (`spacing_zyx` uniform), so the cylindrical SDF can be computed directly in index coordinates (transform start/end/axis into index space once, scaling radial distance by spacing); equivalent to the world-coordinate formula via an affine transform;
  2. **Box shrinkage**: `lo/hi` takes "cylinder bounding box ∩ solid bounding box (P1/P2 output)";
  3. **Sparse evaluation**: before `solid[box] |= sleeve_mask` for sleeves, first take the nonzero indices of `outside_distance[box] >= protected_clearance & boundary_safe` and compute the SDF only at candidate points; similarly for primary cuts, evaluate `sdf<=0` only on voxels where `solid[box]` is true.
- **Equivalence [bit-for-bit/threshold]**: the sign-decision set of the SDF is unchanged; the index-space formula is an equivalent expression of the same geometry, with a floating-point error ≤1e-6mm, and may flip only on a single voxel that lies exactly on the surface (covered by differential verification).
- **Expected benefit**: 35.6s → **8–15s**.
- **Risk**: low-medium; must preserve the extended-cut semantics for crossing sleeves (339–413) and must not change the `nominal/cutter` lengths or the crossing-sleeve decision.

### P5 Meshing and Wrap-up: bounding-box cropping + float32 + per-bore box pre-filtering (≈30–90s → estimated 10–25s)

- **Cost sources**:
  - `_mesh_from_mask` (3013): full 607M grid `float64` conversion/Gaussian/`np.pad`/Marching Cubes, peak >15GB;
  - `_project_bore_walls` (3131): for all ~500k vertices, performs an N×3 vector operation and an `_inside_flat_cylinder` cross check for each of 36 primary bores + 503 auxiliary holes (≈540 × 500k × 3 operations);
  - `mesh_validation` (3344): edge sorting/uniquification over ~1.5M faces (~1–2s, acceptable).
- **Proposal**:
  1. **First take the tight bounding box of `solid`** (`np.nonzero` once to get min/max, 7.9–8.8M points), crop `mask` to bbox+ (kernel radius 4 voxels), then do the float64 conversion/Gaussian/pad/MC — the Gaussian is a local kernel and everything outside the crop boundary is 0, so **values in the retained region are bit-for-bit unchanged**;
  2. **float32 fields**: keep the blur output and pad in float32 (MC accepts float32), halving memory; vertex positions differ from the float64 path by on the order of 1e-6mm, which is [within QA tolerance], provided as an optional switch (retain float64 by default if bit-for-bit consistency is required);
  3. **`_project_bore_walls` pre-filtering**: for each hole, first compute the sparse indices of vertices that "fall within (axial segment bounding box + radius + tolerance)" (a single O(N) comparison or a one-time KD-tree/grid bucket), and perform the existing projection and cross-protection computation only for candidate vertices. The `selected` condition (radial error ≤ tolerance and axial position within range) necessarily falls within that bounding box, so **the decision set is unchanged**;
  4. `_smooth_mesh_vertices` is already a sparse-matrix implementation (3070–3130) and needs no change.
- **Equivalence [bit-for-bit] for 1/3; [within QA tolerance] for 2**.
- **Expected benefit**: mesh+projection+QA drops from ≈30–90s to **10–25s**; peak memory drops from >15GB to 5–8GB (halved again with the float32 option), significantly reducing memory contention with other services (snapshots/screenshots/model inference).
- **Risk**: medium (the float32 option requires geometric-tolerance acceptance); recommend doing 1/3 first (bit-for-bit), with 2 as optional.

### P6 `skin_envelope` Reuse (5.7–10.4s × number of regenerations)

- **Problem**: `_body_mask` + `_smooth_body_mask` depend only on CT, threshold, and σ=2.0mm, and are independent of needle tracks; but they are recomputed on every generation (`store_guide_skin_surface` only persists the result and does not reuse it, 1454–1513).
- **Proposal**: reuse `skin_surface_mask` keyed by `(CT content hash/version, skin_threshold_hu, sigma=2.0mm)` (including the pre-crop full CT grid); recompute on a miss. After generation, still persist and increment `data_version` per the existing logic.
- **Equivalence [bit-for-bit]**: reuses the same mask produced by the same input (the current implementation is a deterministic operator).
- **Expected benefit**: saves 6–10s per regeneration; combined with P0, the waste from duplicate calls is further reduced.
- **Risk**: low; need to define the CT-change invalidation condition (the existing `data_version`/CT hash basis can be reused).

### P7 Observability and Environment (does not change results)

- Add `call_id` to the `finish_stage` log (generate a random/request id for each `generate_surgical_guide`), which can directly confirm/rule out the concurrent duplication in Section 1.3;
- The generation entry point records `request_id`/`planning_signature`/`parameters_hash`/`needle_count`, facilitating statistics and deduplication auditing;
- Within the measurement window there were also concurrent workloads such as screenshot saving and workspace checkpoints (`Screenshot saved` and `checkpoint` logs interleaved); it is recommended to avoid doing report screenshots/replanning at the same time during generation; P5's memory optimization will also significantly alleviate this.

---

## 3. Summary of Expected Benefits (conservative ranges)

| Proposal | Target stage | Current (measured/extrapolated) | Expected | Equivalence |
|---|---|---|---|---|
| P0 server-side deduplication | Overall | 2 concurrent observed | save 1 copy (≈2x, depending on trigger pattern) | bit-for-bit |
| P1 narrow band+bbox | local_grid_resampled | 37.9–75.8s | 8–20s (3–6x) | threshold |
| P2 indexing | plate_patch | 38.4s | 3–6s (6–10x) | bit-for-bit |
| P3 per-needle batching | auxiliary_holes | 17.2s | 3–6s (3–5x) | bit-for-bit |
| P4 index+sparse | primary_sleeves_and_bores | 35.6s | 8–15s (2.5–4x) | bit-for-bit/threshold |
| P5 bbox+pre-filter(+f32) | mesh/QA/projection | ≈30–90s (extrapolated) | 10–25s (2–4x) | bit-for-bit / QA tolerance |
| P6 body-surface reuse | skin_envelope | 5.7–10.4s each | 0 (on hit) | bit-for-bit |

**Single generation (single run)**: ≈250–400s → **≈60–110s (about 3–5x)**;
**Adding P0 (eliminating concurrent duplication)**: in the observed double-run scenario, can approach another 2x.
**First-step recommendation**: doing only P0+P6 (zero geometry risk) saves 40–70s per run and eliminates double-running; then do P2→P3→P4→P5→P1 (from easy to hard).

---

## 4. Quality-Invariance Verification Plan (acceptance criteria)

1. **Gold-standard differential**: select 3–5 representative cases (sparse/dense needle tracks, with truncated FOV, different `geometry_resolution_mm`), run once before and once after the change, and compare item by item:
   - stage timings (`validation.stage_timings_seconds`);
   - `validation.watertight/open_edges/nonmanifold_edges/vertex_count/face_count/bounds_world_mm`;
   - `bore_quality.max_radius_error_after_mm`, `projected_vertex_count`, `cross_bore_protected_vertex_count`;
   - `primary_sleeve_support` (per-bore sampling and valid), `plate_connectivity`, `component_cleanup`;
   - `auxiliary_holes.realized/skipped` (including the skip_reason list);
   - `plate_voxels` (should be bit-for-bit identical after P2).
2. **Mesh geometry**: the bit-for-bit scheme requires the STL vertex set to be element-wise identical (or Hausdorff distance = 0); the optional float32 scheme requires ≤ manufacturing tolerance (recommend ≤ 1e-3 mm and record the maximum).
3. **Frozen old-implementation differential test**: following the approach of `tests/test_planning_latency_equivalence.py`/`tests/latency_reference.json`, freeze the old hot functions (`_resample_mask_to_local_grid`, `_cylinder_sdf_in_region`, `_mesh_from_mask`, etc.) as reference implementations and perform numeric differentials on random/real inputs (boolean arrays must be exactly equal).
4. **Fallback switch**: the new `BRACHYBOT_GUIDE_FAST_PATH=0` (or an equivalent parameter) can revert to the old path, for field comparison and emergency rollback.
5. **End-to-end**: generate twice in a row for the same case; the second time should hit the P0/P6 reuse (the log shows "reused" and a drop in total duration), and the guide version/QA is identical to the first time.

---

## 5. Recommended Implementation Order

1. **P0** (server-side in-flight/result deduplication) + **P7** (`call_id` observability) — minimal change, directly eliminates duplication and unobservability;
2. **P2** (plate_patch indexing) + **P6** (body-surface reuse) — low risk, immediate benefit;
3. **P3** (aux batching) + **P4** (index-space cylinders) — the same class of local-box optimization, can be merged into a single "cylinder SDF engine" refactor;
4. **P5** (mesh bbox + projection pre-filtering, optional float32) — large benefit, requires geometric-tolerance acceptance;
5. **P1** (narrow-band two-level sampling) — largest benefit but most complex to implement; leave it after the verification experience from the first four items.

---

## 6. Discouraged Acceleration Approaches

- **Lowering the `geometry_resolution_mm` default (0.2→0.3/0.4mm)**: both the discrete solid and the mesh change, which is a "result change"; it can only be a parameter option when the user explicitly accepts a change in manufacturing precision, not a default acceleration method;
- **Using SDF min/max direct isosurfacing instead of a boolean solid**: risks degenerate folds/non-watertightness, which the current implementation deliberately avoids (comment at 3013–3029);
- **Switching the Marching Cubes implementation/method (e.g. lorensen, GPU version)**: topology and vertices change, breaking "bit-for-bit";
- **Parallelizing CSG across stages (multiple processes/threads writing the same large array)**: high memory and race risk, and the current bottleneck is operator efficiency within a single stage, so the benefit/risk ratio is not worthwhile.

---

## Appendix A: Log Evidence Excerpt

```
2026-09-16 17:54:44,897 INFO tool_factory Executing tool: surgical_guide
2026-09-16 17:54:50,657 INFO web.surgical_guide ... stage=skin_envelope duration_s=5.735
2026-09-16 17:55:28,620 INFO web.surgical_guide ... stage=local_grid_resampled duration_s=37.877 grid_shape=(931, 436, 1496) grid_voxels=607250336
2026-09-16 17:55:49,528 INFO web.surgical_guide ... stage=skin_envelope duration_s=9.025        # second generation
2026-09-16 17:56:07,058 INFO web.surgical_guide ... stage=plate_patch duration_s=38.418 plate_voxels=8793204 initial_components=1 bridges=0
2026-09-16 17:56:24,303 INFO web.surgical_guide ... stage=auxiliary_holes duration_s=17.244 requested=864 realized=503
2026-09-16 17:56:37,957 INFO web.surgical_guide ... stage=local_grid_resampled duration_s=48.360  # second generation
2026-09-16 17:56:59,902 INFO web.surgical_guide ... stage=primary_sleeves_and_bores duration_s=35.599 needle_count=36
```

(The same window also had concurrent `Screenshot saved` and `workspace checkpoint` logs; the 16:40 round was a similar double-run: two `skin_envelope` runs of 10.36s/10.13s + a 75.82s `local_grid_resampled`.)

## Appendix B: Code Index

| Topic | Location |
|---|---|
| Main generation flow | `web/surgical_guide.py:3396-4184` |
| Body-surface extraction/smoothing | `1427`, `1438`, `1716`, `3441-3461` |
| Local grid resampling | `2833-2947` (thread pool/sharding), `3523-3547` |
| Plate and patch, component bridging | `3572-3612`, `_connect_plate_patch_components` 2744 |
| Auxiliary holes | `415-557`, `2257-2334`, `3618-3661` |
| Cylinder SDF/boolean | `2101-2255`, `339-413`, `3669-3723` |
| Truncated cap/single-part cleanup/support QA | `2950-3012`, `2335-2392`, `2407-2568`, `2632-2642` |
| Mesh extraction/smoothing/bore-wall projection/QA | `3013-3069`, `3070-3130`, `3131-3343`, `3344-3372` |
| Entry points (API/tool/frontend auto) | `web/routes/surgical_guide_routes.py:240-292`, `tool_factory/surgical_guide/__init__.py:217`, `web/app/static/js/brachybot-surgical-guide.js:800-833` |

## Appendix C: Microbenchmark

- Script: `/tmp/opencode/guide_bench.py` (temporary directory, not a repository file)
- Scale: `(465, 218, 748)` = 75,824,760 voxels (1/8 of the real grid)
- Environment: AMD Ryzen 9 5900X (24 threads), scipy 0.3.31/OpenBLAS, `~/.conda/envs/brachytherapy`
- Note: results are from a single measurement, used for order-of-magnitude extrapolation; during implementation, data should be re-collected on the target cases per Section 4.

## Appendix D: 2026-09-19 Dependency-Hash Renewal

`tool_factory/seed_plan/planning_pipeline.py` was subsequently modified by another workflow (`rule_based_max_wall_seconds` deadline handling, `551d6608…` → `9e56f0c1…`), which triggered a fail-closed collection failure of the reference guard.

- **Audit conclusion**: this change does not involve guide geometry. Re-running baseline/current with the existing frozen input (`9c916d51…`, 4 needles, 0.2 mm) and the currently saved Session snapshot (`42171a32…`, 0.2/0.35 mm), vertices, triangles, needle-track source, auxiliary holes, and timing-removed validation are all bit-for-bit identical; the guide implementation is still a bit-exact optimization.
- **Normalization note**: the current implementation added the report-only fields `grid_budget` and `requested_geometry_resolution_mm`; after excluding these two extra fields, the current validation re-hashes back to the original value `0b3612f4…`. The benchmark script `scripts/benchmark_surgical_guide_latency.py` now excludes these two extra fields via an explicit allowlist, keeping the equivalence hash comparable with the 2026-09-16 evidence.
- **Evidence**: newly added `docs/benchmarks/surgical_guide_latency_renewal_2026-09-19.json` (3 pairs, all `inputs_match`/`output_hashes_match`). The original 8-needle and 50-needle synthetic snapshot manifests have been lost and cannot be reproduced; the historical data is retained in `docs/benchmarks/surgical_guide_latency_2026-09-16.json`.
- **Renewal result**: `tests/guide_latency_reference.json` updates the dependency hashes and records the renewal information; `tests/test_surgical_guide_latency.py` has 41 passing items.
