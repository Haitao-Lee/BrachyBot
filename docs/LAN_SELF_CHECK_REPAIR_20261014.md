# LAN full-suite self-check repair — 2026-10-14

Target: `/home/lht/snap/brachyplan/BrachyBot` (LAN). Public release and clinical
runtime directories are not part of this patch. No subagents were used.

## Baseline and scope

The frozen LAN source reproduced exactly the reported 37 failures:
`37 failed, 234 passed` in the eight affected test modules (44.71 s).
The seven installed files were checked against their captured pre-change
SHA-256 hashes before installation, rejecting concurrent edits. Other dirty
and untracked files were not committed, reset, or replaced.

## Corrections

| Group | Correction and verification |
| --- | --- |
| A: asset revisions | Assert the compatible viewer-layout revision floor (49), not an obsolete exact revision. Registry and scheduler checks remain intact. |
| B: timeout and switching | Keep the bounded 60 s production timeout. The short-deadline runtime test overrides exactly one numeric declaration and asserts that the override matched. Transition assertions require detached, case-owned saves before shell clearing, immediate clean target shells, and nonblocking cleanup. |
| C: owned configuration | GET returns only saved, allowlisted timepoint config, with defaults kept separately. This avoids extra configuration groups and phantom clinical changes on an unchanged GET/POST round trip. Cold reads must not repopulate the clinical Agent cache. Tests retain cross-timepoint independence, persistence/import, invalid-input rejection, downstream preservation, and execution-config checks. |
| D: annotation visibility | Automatic annotations remain hidden by default. Visible-interaction tests explicitly show them using the production group controls. Added regressions cover default-hidden records, preservation of manual annotations, actual eye show/hide, and retention after a repeated result packet. Existing eye, 3D source gating, localization, opacity/color, restore-index, and late-result tests remain enabled. |

Final targeted verification: **276 passed, 0 failed**, 32.64 s.

The initial full run used a source-only `/tmp` copy and produced
`3 failed, 4522 passed, 11 skipped, 34 warnings, 4 subtests passed` (677.07 s).
Those three failures were missing deployment assets in the isolated fixture:
liver/kidney cascade paths and the canonical dose CNN. The model checks were
not weakened. The final fixture uses `BRACHYBOT_DEPLOY_ROOT` for real cascade
assets and a separate copy of the installed dose CNN. Its SHA-256 matches the
deployed model (`d73d19f22c846ee989786eabd9336fba80b8c9658881a6e878aca846861b5681`).

Final full-suite result: **4526 passed, 0 failed, 11 skipped, 34 warnings,
4 subtests passed**, 667.36 s (11:07). Command: `python -m pytest -q tests/
--junitxml=../full-final.xml`, in the isolated LAN copy with API keys removed,
the real deployment root configured, and the independently copied dose CNN.
The 11 skipped items are not represented as executed checks; the existing
34 warnings were retained rather than suppressed.

## Deployment

Seven files were installed with a receipt at
`/tmp/brachybot-lan-selfcheck-20261014/install-receipt.json`.
Backup: `/home/lht/snap/brachyplan/backups/brachybot-lan-selfcheck-20261014-7xcrrscv`.
The LAN process accepted graceful shutdown (no forced termination), was
relaunched using its existing environment, and `/api/healthz` returned 200.
New LAN PID: 2296439. Public PID remained 2070185.

Post-installation anonymous HTTP probes: LAN `/api/healthz` = 200;
LAN `/api/config` = 401 (authentication remains enforced).
Source consistency checks covered 614 core/app/test files and 33,664
additional code/fixture-metadata files. The only difference beyond this patch
was the expected runtime-generated `skills/data/skills/skills_registry.json`,
which was deliberately preserved online. These inventory counts are not a
claim that this patch changes that many files.

Execution logs and JUnit records are under
`/tmp/brachybot-lan-selfcheck-20261014/`.
API credentials were removed from the test environment; no clinical account
was created in production, and no production clinical data was edited.
