# Isolated remote synchronization handoff — 2026-10-13

User requested synchronization and wrapping up this round. This is a candidate
handoff, not a statement that prompts a–i are entirely completed or clinically
validated. No new production deployment/restart is performed.

## Exact destinations

- SSH connection: `rtx3090_external`.
- Authorized stage: `/tmp/brachybot-timepoints-stage-20261010-E1Rvjz`.
- Mutable synchronized source: stage `/product-browser-checkout`.
- Frozen regression source: stage
  `/cumulative-safety-guide-source-frozen-20261013-checkout`.
- Current frozen archive: stage
  `/cumulative-safety-guide-source-candidate-20261013.tar.gz`,
  SHA256 `f7b6868b5605234079827f8c54f7139eb1b745813459b0152c96dbd9fd862829`.
- Delivery after documentation updates: stage
  `/cumulative-wrapup-delivery-20261013.tar.gz` and matching manifest.
  This delivery has the same source code as the running freeze, with updated
  audit/handoff documents. Its checksum and per-file verification are recorded
  in `/cumulative-wrapup-sync-verification-20261013.json`.

Do not modify the running freeze or mix its writable test data with either
production runtime. This stage is under /tmp; retain or explicitly move it to
an approved durable candidate location before temporary-storage cleanup.

## Evidence retained

- Previous full freeze: **4295 passed, 2 skipped, 4 passing subtests**,
  1289.60 s. It predates this round's safety and guide-source repair.
- Current safety/OAR merged batch: **243 passed**, 15.35 s.
- Current guide/source/recovery/image/safety merged batch: **298 passed**,
  38.73 s, on Linux. Real child registration/crash/retry tests are included.
- Guide review browser contract: all five scenario markers passed. Verified,
  legacy and direct evidence labels and cross-timepoint clearing were exercised.
  Synthetic transport is explicitly not real-patient registration evidence.
- New full regression PID **1733881**, observed running at
  **2026-10-13 09:25:44 UTC**; no passing final result yet at handoff creation.

Full log/XML: stage
`/cumulative-safety-guide-source-frozen-full-20261013.log` and
`/cumulative-safety-guide-source-frozen-full-20261013.xml`.
Targeted XML: stage `/cumulative-safety-guide-source-targeted-20261013.xml`.
Inspect the final XML and log, not only process exit or progress dots.
The process was intentionally left uninterrupted. Follow-up: it has now finished
with **4506 passed, 1 failed, 2 skipped, 4 passing subtests**, 1333.75 s.
The native full-page guide test received `guide_source_image_unverified`
(HTTP 400 rather than expected 202). Further diagnosis is required;
the current full suite is not green.

## Remaining software acceptance gates

1. Inspect the failed native guide-browser provenance scenario; repair any genuine
   failures, then freeze and verify again if source changes.
2. Compose an actual reviewed-guide, nonzero supplemental continuation through
   guide-first planning and necessary exterior-path fallback with the actual CNN,
   then exercise native viewer/report/export/cold recovery on that result.
   Existing numerical guards, real component inference and zero-addition workflow
   tests are not a substitute for this combined acceptance.
3. Compose live natural-language detection with actual full-page reconstruction.
   Actual detector/browser and live post-edit dose executions passed separately;
   do not report the unexecuted composition as passed.
4. Same numeric guide-version collisions across different acquisition archives
   currently fail closed. A specific Planning/manifest identity selector remains
   necessary to make those ambiguous historical prints selectable. Never choose
   the first conflicting version as a workaround.

The cumulative checklist maps a–i and all 32 checks to actual code and evidence.
Do not turn pending items green solely because the full unit suite passes.

## Separate external validation

Paired patient preoperative/intraoperative images, actual printed-guide fit,
manufacturing strength/tolerance/sterilization, confirmed physical source inputs,
source commissioning and independent dosimetry are not established here.
Synthetic fixtures and supplied-model smoke evidence are clearly distinguished.
Production directories and processes remain outside this synchronization target.
