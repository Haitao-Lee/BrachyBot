# Request execution scope: LAN activation record

Date: 2026-10-08

The 13 selected remediation files in `REQUEST_EXECUTION_SCOPE_AUDIT_2026-10-08.md` were delivered to `/home/lht/snap/brachyplan/BrachyBot` with per-file before/after SHA-256 checks. No commit or push was performed.

## Evidence

- Private recoverable backup: `/tmp/brachybot-replan-scope-backup-20261008-hfozyl4e` (mode 0700).
- Persistent validation evidence: `/home/lht/.local/share/brachybot-replan-scope/validation-20261008` (mode 0700).
- Full isolated product suite: 3,140 passed, 2 deployment-dependent skips, 31 warnings, 4 subtests passed. No failures or collection errors.
- Deployed-source targeted checks: 148 passed; changed Python files compiled successfully; `git diff --check` passed.
- Delivered Python sources matched tested sources modulo mechanically preserved newline style. All 13 delivered hashes matched the final manifest before and after activation.

## Controlled activation

- LAN listener before: PID 2795115.
- LAN listener after: PID 2849076, `192.168.1.113:8080`.
- Verified new process working directory: `/home/lht/snap/brachyplan/BrachyBot`.
- Public service remained PID 2794575 at `127.0.0.1:18082`; it was not restarted or updated.
- Before stopping LAN, read-only aggregate metadata showed zero running case records and zero unexpired workspace editing leases.
- Only one normal SIGTERM was sent to the verified LAN process. Its existing active-workflow shutdown guard remained intact. No forced shutdown signal or broad process-name kill was used.
- Existing startup/configuration/credential bootstrap was reused without dumping credential values. The deployment's existing trusted-LAN plain-HTTP policy was not changed.
- Post-activation `/api/healthz` returned `{"ok":true,"status":"ok"}`.
- Normal server shutdown/startup may checkpoint existing workspace state. No clinical edit, case planning, guide generation or report regeneration was requested for this activation check.

This record proves selected delivery and LAN process activation, not live-model semantic accuracy or clinical acceptance. Synthetic provider-loop evidence and remaining limits are documented in the audit. A normal page refresh is sufficient; no patient re-upload or recomputation is needed merely to load this server-side change.
