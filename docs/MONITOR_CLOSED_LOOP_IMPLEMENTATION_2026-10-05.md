# Monitor Closed-Loop Interaction Implementation

Date: 2026-10-05 (Asia/Shanghai). Scope: the LAN/debug checkout at
`/home/lht/snap/brachyplan/BrachyBot`, baseline HEAD
`4c46cb2f3dfda9de9a9f6437acca1500a6c46627`. The independent public-release
checkout and its writable runtime are outside this change.

## Contract and design

Monitor presents one evolving server-committed edit record. Geometry checks,
dose comparisons, image delivery, and clinical acceptance remain separate.
The UI immediately acknowledges committed evidence without awaiting image
upload. Normal saves do not require routine keep confirmation; restore remains
available under secondary actions. Detailed records remain stored and readable.

The backend now supplies a compact measured assessment: the most important
new/worsened related geometry conflict, or bounded dose/OAR highlights with
explicit single-edit versus edit-sequence attribution. These are measurements,
not a clinical pass/fail verdict, noise estimate, or optimized movement claim.

## Correctness repairs

- Keep and restore both require the current planning identity/version/geometry.
  A stale keep cannot consume a newer or invalid inverse offer.
- Preview and apply requests bind case, monitor run, checkpoint, plan, version,
  and geometry. Read-only preview requires a cached case, never cold hydration.
- Automatic dose comparison defers during dragging, camera interaction,
  background tabs, report capture and occupied jobs, and resumes when idle.
- Captures wait for interactions to finish; they do not hold up edit feedback.
- Automatic annotations preserve camera, visibility, color and real geometry.
  Once the user moves the camera, an old focus/capture cannot restore its old pose.
- Open-ended Monitor questions use the semantic agent and compact case facts,
  not the legacy keyword-triggered reply handler. Existing explicit token
  commands remain compatible. Live buttons expose stable operation references.
- Preview controls require the new server interaction schema. During a mixed
  frontend/backend rollout they are hidden, rather than submitting to missing
  endpoints or suggesting that a backend restart already happened.

## Spatial assistance and geometric candidates

`POST /api/training/edit_preview` supports:

1. `mode=previous`: a server-owned, read-only pre-edit geometry preview. Purple
   dashed lines/point markers/arrows are reference annotations, not changed
   patient geometry and not a declaration that the prior position was safe.
2. `mode=spacing`: explicit bounded axial search for an independently edited
   seed with a related new/worsened spacing issue. At most ten offsets (0.5,
   1, 2, 3, 4 mm in either needle direction), two proposals, 512 seeds, 256
   needles, and a cooperative 1.5-second search budget. It uses the actual seed
   normalizer and finite-cylinder interference checker. All affected pairs
   must be clear; other seed records must remain unchanged after normalization.
   A sampled seed cylinder must lie in the current CTV grid. Missing CT/CTV,
   invalid geometry, incomplete evidence or exhausted search fail closed.

`POST /api/training/apply_candidate` accepts only an unexpired server-issued
candidate ID plus explicit confirmation, never caller-supplied coordinates or
safety overrides. It rechecks current target membership and affected spacing,
then calls the ordinary seed commit endpoint. Versioning, persistence, stale
artifacts and the next Monitor checkpoint are therefore shared with manual edits.
Offers expire after two minutes and are invalidated by another committed edit.

Important limits: this is a **local geometric candidate generator**, not a
dose optimizer. Target membership is sampled, not an exhaustive continuous
containment proof. There is no independent OAR dose calculation, clinical
acceptance, global feasibility proof or claim that any candidate improves
coverage. The ordinary clinical workflow still requires updated dose/DVH,
QA and review. No candidate is applied automatically. Needle relocation
candidates and dose-verified multi-object optimization are not implemented.

## Timing and UX observability

`getMonitorUXMetrics()` returns bounded per-run aggregate counts/p50/p95 for
checkpoint-to-feedback, checkpoint-to-image delivery and preview responses.
It does not contain patient names, case IDs, object IDs, coordinates or tokens.
It measures browser-local intervals, not server edit latency, GPU throughput or
an external clinical performance result. No production latency target is
claimed from unit or synthetic browser tests.

## Validation and deployment

Validation uses synthetic geometry and isolated storage; no patient was edited
and no clinical planning/model job was launched for this implementation.

### Recorded validation

- Targeted Monitor Python tests: **145 passed, 31 warnings**, 3.60 seconds.
- Full isolated application suite after adding the read-only checkpoint gate:
  **2,204 passed, 2 skipped, 31 warnings, 4 subtests passed**, 50.06 seconds.
  The two skips are existing public HTTP dependency and real NGINX-binary
  integration prerequisites, not skipped Monitor checks.
- Full application suite on the actual delivered LAN/debug working tree,
  including the final primary-action UI refinements: **2,204 passed, 2 skipped,
  31 warnings, 4 subtests passed**, 52.78 seconds. Recorded in
  `actual-delivered-tests.log`; the skip reasons remain unchanged.
- Four unchanged-source stale-keep counterexamples: **4 failed**, each returning
  HTTP 200 where HTTP 409 was required. The same cases pass after the repair.
- All **14 Monitor Node/browser scripts** pass locally with bundled Playwright
  and real Chrome/WebGL. Three browser scripts use synthetic objects and stubbed
  transport; these are not patient end-to-end or production-network results.
  All fourteen were rerun successfully against the final delivered payload.
- Actual normalizer/spacing checks are exercised by candidate tests. The real
  Flask seed commit endpoint is exercised after explicit candidate confirmation.
- Browser evidence includes camera-preserving automatic marks and read-only
  ghosts, mesh/color preservation, user camera ownership, concise records,
  secondary normal-edit decisions, and stale-preview rejection.

Evidence directory: `/tmp/brachybot-monitor-closed-loop-delivery-20261005`.
Selected-file SHA checks, private original backups and an atomic index-last
publish are used for delivery. No commit or push is performed. Static refresh
can activate frontend changes; new backend routes require a LAN 8080 restart.
The restart is awaiting the user's scheduling choice. New preview controls are
gated on interaction schema 3 so an older running backend does not expose broken
new actions. The public-release listener is not restarted or modified.

Delivery checks confirmed all fifteen selected files against the delivery
manifest and retained original bytes in the private backup
`/tmp/brachybot-monitor-closed-loop-backup-20261005-tb2caele` (mode 0700).
`git diff --check` and syntax checks for all four changed JavaScript files passed.
The LAN server's returned HTML already references the updated static asset
versions. This does not prove backend activation: the new routes, schema and
server-side correctness repairs require a restart of the existing LAN process.
At the final listener check, LAN PID 1047880 and public-release PID 1047604
remained unchanged. These process IDs are point-in-time observations, not a
promise about subsequent concurrent maintenance.

### Reproduction

```bash
cd /home/lht/snap/brachyplan/BrachyBot
PYTHONDONTWRITEBYTECODE=1 /home/lht/.conda/envs/brachytherapy/bin/python \
  -m pytest -q -rs -p no:cacheprovider tests/
```

Include an existing Node runtime in PATH to execute Node-dependent contract
tests. Browser scripts additionally require the existing Playwright package and
Chrome executable; no new dependency was installed into the production service.
The isolated tree used `BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan` only to
retain the actual external model-directory lookup. It did not link live runtime
or patient storage into the validation tree.

## Remaining clinical and product validation

This delivery does not claim every aspect of the long-term Monitor vision is
complete. Needle relocation search, dose-verified candidate optimization,
real-patient user studies, production latency percentiles, and full external
deployment/security acceptance remain separate work. In particular a geometric
candidate is not a CNN-verified dose improvement, clinical approval, or a proof
that all targets/OARs are safe. The product CNN dose engine is unchanged.
