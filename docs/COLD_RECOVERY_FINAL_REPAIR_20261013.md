# Cold resource recovery: final owned-hydration follow-up

This is a bounded software recovery repair, not a declaration that all a-i
compositions or clinical commissioning have passed. Production LAN source is
`/home/lht/snap/brachyplan/BrachyBot`; public release is outside this deployment.

## Observed failure and first verified repair

The deployment freeze completed with 4524 passed, 2 failed, 2 skipped and 4
passing subtests in 1569.75 s. Both failures were actual page recovery scenarios.
Legacy planning normalization can change a clinical receipt during resource
loading. Generic recovery then reentered the same item's pending hydrate promise,
causing self-await. The fix coalesces same-generation recovery, waits for pending
mount hydration and explicitly remounts clinical drift instead of replaying the
same promise. No test assertion or timeout was weakened to turn this green.

Exact first-repair browser evidence:

- `lan-hydration-serialized-current-20261013.xml`: 12 passed, 188.55 s;
  actual two-timepoint upload/switch/cold recovery/native import plus frontend
  contracts, real product APIs and resources.
- `lan-implant-current-frozen-replay-20261013.xml`: 1 passed, 214.74 s;
  actual supplied detector and dose engine, 2D/3D/tree controls, manual add/drag/
  exclusion, review, dose and cold reload. Demo acquisition, not a reference
  clinical-accuracy validation.

The earlier mutable diagnostic group had source changes while running and is
not exact-source acceptance. A separate initial-page navigation timeout also
remains in the historical logs; it is not rewritten as a cold-recovery pass.

## Additional guarded boundaries

The independent saved-source scheduling diagnostic is preserved in
`COLD_RECOVERY_DIAGNOSIS_20261013.md`. Subsequent source changes address:

- Final receipt comparison captures immutable clinical/lifecycle version values
  before resource producers start. A concurrent observer cannot update
  a mutable cache and hide a clinically stale resource input.
- Pending recovery may follow only explicitly linked hydration successors;
  A1 -> B2 -> A3 navigation cannot adopt the unrelated later A generation.
- A rejected old recovery can show failed status only on its exact generation.
- Observation reload keeps existing boolean return behavior for interactive
  callers. Resource hydration requests `throwOnError` so genuine failed reads
  leave the workspace unready, while superseded observation requests are not
  misclassified as transport errors.

`tests/timepoint-hydration-reentry.test.cjs` executes the actual extracted
production functions with labelled synthetic receipts and controlled scheduling.
It tests promise termination, coalescing/retry, consumed-receipt drift, owned
successors, navigation/rejection negatives, and observation failure/supersession.
These are deterministic scheduling contracts, not substitutes for product tests.

## Final verification status

The first additional-guard freeze was
`/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/lan-recovery-final-guard-20261013-yBAc8A`.
It remained immutable during its frontend/archive/two-timepoint/supplied-model
batch: **26 passed, 2 failed**, **148.95 s**. Deep JSON copying the runtime
workspace before loading destroyed iterable runtime geometry already attached
by the synchronous shell. Both real browser tests caught that regression;
those guards were not installed. The repair captures immutable revision values
without serializing live geometry objects, preserving the existing loader input
contract. The revised exact freeze/result and installed hashes are recorded
after verification. No full-suite green result is claimed by targeted reruns.

The revised exact freeze is
`/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/lan-recovery-revision-fence-20261013-YSkeLO`.
Its complete batch is recorded in `lan-recovery-revision-fence-20261013.xml`
and `.log`: **28 passed**, **361.62 s**, three SimpleITK deprecation warnings,
no failures or skips. This includes 11 frontend contract cases, 15 archive
configuration cases, actual two-timepoint upload/switch/cold/native import and
actual supplied-model full-page edit/dose/cold restoration. The production
bridge SHA256 is `b64db58bd6a737d331559ec5fb2efbb68b8793954281473c3ca0dcdea75d5704`;
the compatible observation-loader SHA256 is
`cac9b812282e7b37c70dd931f1ad14f71f568305b2b945196e41e0caefae1634`.
The companion observation-loader browser/asset contracts passed
**2 tests**, **6.50 s** (`lan-implant-loader-contract-followup-20261013.xml`).
These companion browser contracts use labelled synthetic inputs; the actual
supplied-model full-page scenario is the separate complete-batch gate.

Deployment uses a source-only, hash-preflighted follow-up with rollback files
under the existing LAN backup. It does not restart the service, edit case data
or touch the public release. `lan-recovery-followup-installed-20261013.json`
records installation and cumulative source verification;
`lan-final-live-verification-20261013.json` records the observed listener/cwd,
live HTTP asset hashes and NAS availability. Installation success is established
by those reports, not by the existence of this document. The earlier failed
full regression remains historical failed evidence; no final full-suite green
claim or completed a-i/clinical claim is made.
