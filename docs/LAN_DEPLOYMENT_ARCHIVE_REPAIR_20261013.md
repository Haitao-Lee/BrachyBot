# LAN cumulative merge and archive-activation repair — 2026-10-13

The user explicitly requested merging into
`/home/lht/snap/brachyplan/BrachyBot` and correcting archived Session activation.
The independent `BrachyBot-release` checkout/runtime/process is excluded.

## Confirmed archive failure cause

The running LAN process had no `BRACHYBOT_ARCHIVE_ROOT`, so it looked under
repository `runtime/archive`. Read-only metadata checks found 38 nondeleted
archived Sessions and zero corresponding snapshots under that default.
All 38 owned directories and all 38 snapshots existed under the mounted
`/home/lht/nas/LHT_workspace/Brachytherapy/users/<owner>/sessions/<session>`.
No password hashes, clinical image content or case titles were printed.
There was no pending transfer journal. This is configuration loss, not evidence
of deleted cases.

Archive identity is now supported through per-runtime
`storage-config.json`: schema 1, explicit absolute archive root and optional
required mountpoint. Explicit environment overrides remain higher priority.
Malformed configuration fails closed rather than selecting an empty fallback.
A missing NAS mount cannot create an archive underneath the unmounted stub or
reactivate a stale local leftover. Activation returns a fixed zh/en
`archive_storage_unavailable` message instead of implying case loss.
LAN configuration records the confirmed NAS root and `/home/lht/nas` mountpoint;
public runtime configuration is not copied or changed.

## Executed bounded verification

- Real synthetic archive/cold restore after environment removal, current
  multi-timepoint arrays/UI restoration, bad-config/mount guards and actual
  activation-route localization were tested.
- Combined archive/config/authentication, workspace store, registered route
  inventory, legacy archive active-use, bundle and frontend batch:
  **465 passed**, 3 SimpleITK warnings, **21.52 s** on Linux.
- The earlier archive/storage subset: **66 passed**, **11.67 s**.
- The previously failing native guide browser fixture now captures its actual
  uploaded image through normal `capture_resources` and saves a linked parent.
  Original-source/CPU/workflow/exact native browser batch: **38 passed**,
  **63.00 s**; no source guard was relaxed. See
  `GUIDE_NATIVE_SOURCE_FOLLOWUP_20261013.md`.

These batches are not additive totals and are not independent clinical validation.
The historical 4506-passed/1-failed full freeze remains unchanged as historical
evidence. The newer deployment freeze completed with **4524 passed, 2 failed,
2 skipped and 4 passing subtests**, **1569.75 s**. Its two failures were actual
two-timepoint cold/import recovery and supplied-model page cold recovery, not
the now-corrected guide provenance fixture. This full run is **not green**.

## Merge safeguards

Every accumulated source modification is checked against the saved dirty baseline
before replacement; unrelated live edits are not discarded. The live generated
`skills/data/skills/skills_registry.json` is preserved, not overwritten by a
local test's regenerated timestamps/counters.
Source/config backup and consistent SQLite backup precede the merge.
Existing case files and NAS archives are not replaced by the deployment.
Normal shutdown uses only the confirmed LAN PID and respects the existing
active-workflow deferral; no forced KILL or public-service restart is used.
The LAN startup retains provider configuration and reads private
`.runtime/seedfinder.env` for the already installed pinned supplied inference
bundle/interpreter/device. No substitute detector or model is installed.

Deployment plan/backup/apply/verify artifacts and health/asset checks are recorded
under the isolated stage. Actual merge/restart status must be verified from those
artifacts and process/listener state, not inferred from this description.
Follow-up execution confirmed the merge: **257 cumulative source/test/document
paths**, launcher and private configuration installed and hash verified. The live
generated skill registry was excluded. Backup:
`/home/lht/snap/brachyplan/backups/brachybot-timepoints-archive-20261013`.
LAN PID **1853900**, working directory the requested checkout, listener
`192.168.1.113:8080`. Health/index returned 200; timepoint, workspace,
implant-observation and guide-review scripts matched deployed disk hashes.
Public PID **1836580** remained on loopback 18082.

Further verification restored a bounded real old NAS archive on a private
isolated clone: **30 files, 133587846 bytes, 5 array files**, same Session
identity and exact restored hashes; legacy-default timepoint loading passed.
No original archive or production database was changed by this check.
Evidence: `legacy-archive-clone-verification-20261013.json`.
An authenticated synthetic UI proof using the deployed code and a separate
empty runtime rendered **two timepoint tabs** and enabled the plus control.
Its screenshot `lan-interface-proof-20261013.png` contains no patient data.
No test account was created in the production runtime.

The new freeze archive SHA256 is
`0e6cf7b03cb24cf221b4b517cef65d681eee891d3f1d14ad0412363c79471d35`.
Complete regression log/XML are
`lan-deployment-frozen-full-20261013.log` and `.xml` in the isolated stage.
Both failing workflows were subsequently rerun against the hydration-reentry
repair: the frontend/two-timepoint batch passed **12 tests**, **188.55 s**;
the supplied-model full-page edit/dose/cold replay passed **1 test**, **214.74 s**.
The first repair was installed as a static-asset-only follow-up, without another
LAN restart. Follow-up audit and stricter generation/receipt/failure guards are
tracked in `COLD_RECOVERY_FINAL_REPAIR_20261013.md`. Targeted passes do not
retroactively change the failed frozen full-suite result.
The final immutable revision/generation/failure guard freeze passed **28 tests**,
**361.62 s**, including both actual product workflows and archive configuration.
The companion observation browser/asset batch passed **2 tests**, **6.50 s**.
The guarded source-only installation and final cumulative hash/HTTP/NAS proof
are recorded in `lan-recovery-followup-installed-20261013.json` and
`lan-final-live-verification-20261013.json`; no further LAN restart is required.
The wider a–i checklist's unfinished nonzero guide-to-exterior/full-CNN composition
and separate clinical commissioning claims remain distinct from this release.
