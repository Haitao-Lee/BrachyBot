# Native guide original-source acceptance follow-up — 2026-10-13

The sole reported full-regression failure was an incomplete synthetic native
browser fixture. The actual native upload/load path succeeds with its saved
Planning image provenance. No original-source service change or relaxation of
the missing/multi-image rules was needed.

## Scope and changed paths

This bounded sidecar changes only:

- `tests/test_guide_original_source_image.py`
- `tests/test_timepoint_product_browser.py`
- this new `docs/GUIDE_NATIVE_SOURCE_FOLLOWUP_20261013.md`

`web/guide_service.py` was inspected and remains byte-identical. Its SHA-256
before and after, locally and in the isolated mutable Linux checkout, is
`eb2bae0d8398580ce2d22e8aca93be9e1043914f21ec6e87be9b7629b4524c6b`.
The prior `GUIDE_SOURCE_IMAGE_AUDIT.md` and integration/provenance code were read.
No prior freeze, archive/session restoration code, deployment, production
runtime, or production service restart was changed by this sidecar. Main owns
those independent tasks and any new full-regression freeze.

## Actual reproduction and cause

The unchanged native browser test was reproduced in
`/tmp/brachybot-timepoints-stage-20261010-E1Rvjz/product-browser-checkout` using
the existing Linux Python, Node and Playwright installations. It failed:
**1 failed, 3 SWIG deprecation warnings, 29.72 s**. The real full page submitted
`POST .../guide-registration/jobs`, received HTTP **400** with
`guide_source_image_unverified`, and failed the expected HTTP 202 assertion.
The pre-repair browser-test file SHA-256 was
`5bedbbaca10013bd1aaee0e905b336bd551355b93fa4a54251710e5e8fc826b2`.

A separate local reproduction used the real `create_app`, authentication,
`/api/upload` and `/api/viewer/load` endpoints and owned `WorkspaceStore`, with
the same phantom and guide fixture. Both upload and load returned HTTP 200.
The saved source contained exactly **one** acquisition and this archive:

```text
image_resources keys: ["unassigned"]
unassigned.reference_image_id: null
unassigned.source_receipt: null
unassigned.agent.planning_results keys: []
guide.planning_id: null
saved planning_run:* keys: []
```

This archive is produced by `TimepointImageService._set_reference` on the first
selection: it saves the prior unassigned state before setting the first image
reference. Nonempty `image_resources` alone therefore does not demonstrate a
second acquisition. However, the service's explicitly documented no-parent
legacy policy excludes acquisition resource archives. The fixture wrote only
the `surgical_guide` alias and supplied neither a linked immutable Planning
parent nor its frozen image fingerprint. Its rejection was consistent with that
policy; removing the archive or allowing a current-image fallback would not
repair the missing proof.

## Fixture repair and retained guards

The native fixture preserves its actual uploaded collection and unassigned
archive. It obtains the real owned image through
`TimepointImageService.planning_reference_bridge`, calls the existing
`capture_resources` function, and stores the image dependency in
`planning_run:synthetic-guide-parent.timepoint_resource_state.fingerprints.image`.
The declared synthetic guide is linked to that parent by `planning_id`.
This supplies the same image-fingerprint contract preserved by normal Planning
snapshots (`web/planning_runs.py`, `PLANNING_VALUE_KEYS`), without copying the
source resolver's hash formula into the browser fixture.

Before the browser starts, assertions require the exact uploaded image ID,
`saved_parent_image_fingerprint` policy, `original_acquisition_verified=true`,
and the captured parent leaf. After browser confirmation, reload and rejection,
assertions require the persisted candidate's identical source provenance and
unchanged source reference selection. The existing native JavaScript workflow
and real CPU registration worker are unchanged.

Four added original-source cases cover:

1. Real native first upload/load with the unassigned archive and missing parent:
   still rejects with `guide_source_image_unverified`.
2. The same path with a matching captured parent: resolves the exact owned image
   with verified provenance and identical pixels.
3. The same path with a parent captured from different pixels on an equal grid:
   still rejects with `guide_source_image_unverified`.
4. A/C history with C deleted and only A active: even when archive hints and
   parent are absent, the historical second acquisition blocks the legacy
   fallback. Filtering to active images cannot bypass this guard.

The existing original-A/current-C tests remain intact and passed, including
real child input/registration, original-A overlay pixels, publication,
review/restart, missing/altered/deleted files, conflicting parents, conflicting
same-version guide provenance, and source-free direct visible-guide fits.

The mesh and manually supplied Planning remain synthetic software fixtures.
These tests do not establish optimized clinical Planning, patient fit accuracy,
printing approval, mechanical strength, or clinical commissioning.

## Bounded verification

| Run | Result |
| --- | --- |
| Unchanged native full-page browser baseline, Linux | 1 failed, 3 warnings, 29.72 s; HTTP 400 `guide_source_image_unverified` |
| Final original-source suite, local Windows | 21 passed, 3 warnings, 53.80 s |
| Final original-source + registration workflow + CPU + exact native browser test, Linux | 38 passed, 3 warnings, 63.00 s |
| Existing localized missing-source recovery route tests, Linux | 2 passed, 3 warnings, 5.38 s |

The Linux 38-test run includes the actual child-crash/explicit-retry test without
deselection and the previously failing native product acceptance without a
skip. The full page performs CPU registration, three CT-slice canvases and one
3D guide/CT overlay, explicit human fit confirmation, reload restoration of the
accepted placement, and rejection. Persisted original-source provenance is
checked after that sequence. The two additional route tests retain HTTP 400 and
localized recovery for missing multi-image provenance without publishing a
candidate.

Windows used `C:/Users/hunte/anaconda3/python.exe -E -X utf8`, short unique test
roots (`C:/gsrc1013b1` for the direct reproduction and `C:/gsrc1013u1` for pytest),
and the already documented test-only directory-fsync and own-worker-PID
accommodations. The native test now includes the same accommodations if it is
run on Windows. Local Node had no resolvable Playwright module; the actual
browser acceptance was executed on Linux using the existing installation.
The Windows result is not validation of native Windows durability/liveness.

Local original-source command:

```powershell
& C:/Users/hunte/anaconda3/python.exe -E -X utf8 -m pytest -q -p no:cacheprovider tests/test_guide_original_source_image.py --basetemp=C:/gsrc1013u1 --tb=short
```

Linux environment for the native baseline and final combined run:

```bash
cd /tmp/brachybot-timepoints-stage-20261010-E1Rvjz/product-browser-checkout
export BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan
export BRACHYBOT_NODE=/home/lht/.vscode-server/cli/servers/Stable-04c0d99f4fb0d8afe6ce4f0c58e31e183ac3e4b1/server/node
export PLAYWRIGHT_MODULE=/home/lht/.conda/envs/brachytherapy/lib/python3.12/site-packages/playwright/driver/package
export PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1
```

Baseline command, before synchronizing the repaired tests:

```bash
/home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q -p no:cacheprovider tests/test_timepoint_product_browser.py::test_actual_product_guide_registration_and_review_on_synthetic_phantom --basetemp=/tmp/gsrc1013b1 --tb=short
```

Final combined command:

```bash
/home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q -p no:cacheprovider tests/test_guide_original_source_image.py tests/test_guide_registration_workflow.py tests/test_guide_registration_cpu.py tests/test_timepoint_product_browser.py::test_actual_product_guide_registration_and_review_on_synthetic_phantom --basetemp=/tmp/gsrc1013f1 --tb=short
```

Additional route command, with `PYTHONPATH=.` and `PYTHONDONTWRITEBYTECODE=1`:

```bash
/home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q -p no:cacheprovider tests/test_guide_source_recovery_routes.py --basetemp=/tmp/gsrc1013r1 --tb=short
```

Only the two changed test files were synchronized to the authorized mutable
remote checkout for these runs. This follow-up document is delivered locally.
No full suite was run. The prior **4506 passed / 1 failed** frozen full-regression
record remains historical evidence; the passing bounded rerun does not turn
that old freeze into a passing full-regression result.

## Final test-file identities

- `tests/test_guide_original_source_image.py` SHA-256:
  `8e56f5c367d7c3a53697ec4dc3fc16f1ad789297a305e1b7218ad78b0e6baf68`
- `tests/test_timepoint_product_browser.py` SHA-256:
  `a321506efbf396e7c893a9d68de04f0d011f815d153069a10ba9fa9568302955`

The remote copies matched these exact local test sources during final acceptance.
