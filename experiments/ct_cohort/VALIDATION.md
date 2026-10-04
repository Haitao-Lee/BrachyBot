# Code-validation record — 2026-10-04

This document concerns implementation tests, not cohort measurements.

## Case-level resumption: targeted fault injection (package 0.2.1)

The same `run` command now reconciles interrupted cases before scheduling any new
work. Tests cover skipped terminal prefixes; repeated interruptions and linked
retries; live/dead/foreign/legacy owner proofs, reboot/PID reuse; recipe drift;
hashed recovery-link tampering; both task/operation fences; Ctrl+C without assumed
server cancellation; and first-attempt versus eventual outcome separation.
An actual Chromium synthetic-UI test disconnects after submission, reattaches the
original case, exports artifacts and asserts no upload/planning/chat mutation was
repeated. This is not a real-model or clinical recovery result.

The targeted suite has **88 passed** (17.97 seconds; three existing SWIG warnings).
It includes same-command queue advancement and legacy missing identity safeguards,
plus SIGKILL of an owned synthetic child process and recovery of its real stale
lease. No product/server/model process was killed by this test.

```bash
PYTHONPATH=. /home/lht/.local/share/brachybot-ct-cohort/code-validation/venv/bin/python \
  -m pytest -q tests/test_case_resumption.py tests/test_core.py \
  tests/test_census_scheduling.py tests/test_browser_contract.py \
  tests/test_analysis_reference_recovery.py tests/test_protocol_and_collection.py
```
The full product/benchmark suite and a real patient cohort were not run. No
experimental server was provisioned and neither 8080 nor 18082 was restarted.

## Census extension: targeted validation only

The 0.2.0 extension uses no fixed 800-case runtime cap. Added synthetic
metadata-only tests exercise a 2,400-row census, deterministic selection,
one-per-cluster versus all-targets, frame/hash and resolved-row drift,
incomplete/busy attempt fencing, partial-pair recovery, batching past a terminal
prefix, actual pending-arm budget accounting, allocation-aware denominators,
and distinct software/review/physics outcomes. Full browser/GPU/cohort tests
were deliberately not rerun for this extension.

Targeted command (isolated staging source, 2026-10-04):

```bash
PYTHONPATH=. /home/lht/.local/share/brachybot-ct-cohort/code-validation/venv/bin/python \
  -m pytest -q tests/test_census_scheduling.py tests/test_protocol_and_collection.py \
  tests/test_profiles.py tests/test_analysis_reference_recovery.py
```

Result: **63 passed**, with three existing SimpleITK/SWIG deprecation warnings;
approximately 1.2 seconds of pytest execution. This proves the stated synthetic
contracts, not the throughput/physics/clinical validity of 2,400 real cases.
Package syntax/JSON/TOML, selected diff and source integrity are checked
separately before delivery. No real source volumes were planned or modified,
no experimental server was provisioned, and neither service was restarted.

## Scope

- Pinned product source HEAD: `0d1dbffe4de291b39737b87ea44961429b12748c`.
- New standalone code: `experiments/ct_cohort`; product modules unchanged.
- Runner validation environment:
  `/home/lht/.local/share/brachybot-ct-cohort/code-validation/venv`.
- Synthetic medical volumes, DICOM and output artifacts are on the owned NAS
  validation directory. Tiny symlink/account-DB fixtures and browser profiles
  use `/dev/shm` tmpfs. No source patient images are rewritten.

## Tests

The final result and command are also recorded in
`docs/CT_COHORT_EXPERIMENT_IMPLEMENTATION_2026-10-04.md`.

Tests cover registry/preflight contracts, exact label and physical geometry,
uploaded-versus-effective CTV, real Chromium control sequences for both arms,
whole-attempt export/collection/tri-state outcomes, consumed parameter/fallback
provenance, finite geometry/dose, honest PDF/guide acceptance, DICOM negative
controls, source/recipe/rules hashes, adjudication identity, missing attempts and
paired analysis, service PID/cwd/runtime/listener identity and account quota.

The synthetic whole-attempt fixtures deliberately generate valid software
artifacts but no qualified medical review. They must remain UNKNOWN/partial,
not VERIFIED_SUCCESS. This is a meaningful negative control against self-proof.

## Not established

- No approved real-case pilot, cohort planning or comparison result.
- No model/source calibration validation or independent TG-43/MC reference.
- No accepted clinical indication, patient-level linkage or efficacy.
- No manufactured-guide channel/wall/fit or report figure-quality approval.
- No measured main-study runtime/storage feasibility or validated sample size.
- No isolated experimental SUT service provision/start in this implementation
  turn; the doctor reports deployment NOT_READY in the draft configuration.

## Read-only smoke checks

`inventory`: 40,299 registry rows. Manifest SHA256:
`9b2cefc9a60d9ddb864779c3988230b4ce5f923f3b6e956fd6010c9cd2916b06`.

`dry-run`: gates CLOSED, `GOVERNANCE_UNRESOLVED`, zero product mutations.

`doctor`: runner dependencies present, expected CIFS mount verified; missing
isolated deployment marker remains NOT_READY rather than a fake ready state.

Observed existing listeners during validation: LAN 8080 and independent release
18082; no experimental listener on 18086. These services were not restarted.

## Primary references for implementation decisions

- [SQLite WAL and network-filesystem limitation](https://www.sqlite.org/wal.html).
- [Playwright Python input controls](https://playwright.dev/python/docs/input).
- [SimpleITK ImageSeriesReader](https://simpleitk.org/doxygen/latest/html/classitk_1_1simple_1_1ImageSeriesReader.html).
- [AAPM TG-43U1 report](https://www.aapm.org/pubs/reports/detail.asp?docid=85):
  a source-dose framework, not invented site-specific limits or approval.
