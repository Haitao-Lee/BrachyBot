# Export Save Data delivery and activation evidence

Date: 2026-10-08 (Asia/Shanghai). This is point-in-time evidence, not a claim
that subsequent unrelated deployments retain the same process identifiers.

## Source and delivery

- Baseline HEAD: `bbc2b7cf0c5201e6024be9d8cdf41865012d2858`.
- Twenty selected files were delivered after verifying their baseline hashes,
  final hashes, and byte identity with the tested isolated staging checkout.
- Original mixed line endings and existing file permissions were preserved.
- Recovery copy: `/tmp/brachybot-export-backup-20261008-jken3cyd`, mode `0700`.
- Evidence: `/home/lht/.local/share/brachybot-export-workflow/validation-20261008-fgcn5N`.
  It contains `manifest-final.json`, `full-suite.xml`, `delivery.json`,
  `activation.json`, and `route-verification.json`.
- This activation document is an additional documentation-only file.
- No commit or push was made. The public-release checkout was not changed.

## Verification

- Final isolated full product suite: **3,209 passed, 2 skipped, 31 warnings,
  4 subtests passed**, 221.01 seconds.
- Deployed-source export/report/capture subset: **108 passed**, 10.90 seconds.
- New export regression cases: **69**, including parametrized cases. This is
  not a count of independent benchmark scenarios or a measured live-model
  semantic accuracy percentage.
- `git diff --check` and all six changed JavaScript syntax checks passed.
- Read-only top-router checks for report, guide, needles/seeds STL, Session,
  DVH CSV, and Session-excluding-chat all remained on the primary semantic
  route with **no planning, guide-generation or report-regeneration grants**.
- The two skips are public-origin and nginx/TLS deployment checks:
  `test_real_public_origin` and
  `test_nginx_template_tls_headers_and_unbuffered_sse`.
- Warnings are existing SimpleITK wrapper and `datetime.utcnow` deprecations.

The browser tests use actual headless Chromium for rendering, keyboard/focus,
selection, timers, download handling and completion text. Native OS file and
directory pickers are tested through simulated File System Access handles;
this does not replace interactive acceptance in every operator's browser/OS.
Serializer tests read the generated STL/NIfTI/DICOM-RT files and compare them
against synthetic source geometry and physical dose. No real patient inference,
planning, report recapture, guide generation or paid provider call was run.

## LAN activation

- Old LAN listener PID: `2849825`.
- New LAN listener PID: `2938933`.
- Address: `192.168.1.113:8080`.
- Listener process working directory verified as
  `/home/lht/snap/brachyplan/BrachyBot`.
- `/api/healthz` returned `ok=true` after activation.
- All twenty delivered hashes were rechecked after activation.
- No running case or valid workspace editing lease existed before restart.
- One normal SIGTERM was used; no forced termination was used.
- Independent public listener remained PID `2878061` on `127.0.0.1:18082`.

The LAN process retains the existing trusted-LAN plain-HTTP configuration and
its existing insecure-development warning. HTTPS/public-access configuration
was not weakened or changed by this feature. On insecure LAN origins, native
directory/file access may be unavailable: the dialog explicitly falls back to
browser download/structured ZIP and does not claim an arbitrary local path was
written. Refresh an already-open page to load the new frontend assets.

For behavior, supported formats and limitations, see
[Unified conversational export audit](EXPORT_SAVE_WORKFLOW_AUDIT_2026-10-08.md).
