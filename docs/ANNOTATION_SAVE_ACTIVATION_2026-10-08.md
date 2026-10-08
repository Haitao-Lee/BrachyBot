# Annotation Save Repair: LAN Runtime Activation

## Completed activation

The remaining runtime activation step was completed on **2026-10-08 at
20:35:23 Asia/Shanghai**. The earlier repair delivery deliberately did not
restart the running server; this follow-up records the subsequent controlled
restart rather than rewriting the earlier point-in-time evidence.

- LAN checkout: `/home/lht/snap/brachyplan/BrachyBot`.
- LAN endpoint: `http://192.168.1.113:8080/`.
- Previous LAN process: `2598003`; new LAN process: `2764625`.
- The independent public process on `127.0.0.1:18082` remained `2604106`.
- `/api/healthz` returned `{"ok":true,"status":"ok"}` after restart.
- The LAN root references annotation JS `v34`, viewer-volume JS `v93`, and
  workspace JS `v74`; their served bytes match the delivered source hashes.

The scoped annotation-save route is now loaded in the new process. The legacy
compatibility fallback remains available but is no longer required merely because
the old server process had not loaded the new Python modules. Refresh the browser
after any current save finishes to load the versioned frontend assets.

## Restart safety

Before sending any signal, read-only metadata checks found **zero running-case
records and zero unexpired editing leases**. These are not treated as perfect
proof that no transient worker exists. The server's active-operation shutdown
guard remained authoritative: only `SIGTERM` was sent, and the follow-up would
have stopped if the server deferred exit. No forced termination was used.

The exact LAN listener PID, process command, working directory, and source hashes
were checked. The existing startup configuration/security/credential bootstrap
was reused, but its broad `pgrep`/forced-kill stop block was omitted. No signal was
sent to the public-release service. No credentials, patient contents, or account
identifiers were emitted in the inspection output.

This follow-up did not execute real-case annotation clearing, planning, model
inference, or provider calls. Normal server shutdown checkpointing and startup
recovery are product-managed persistence operations, not manual clinical edits.

## Verification retained

The repair's final unfiltered product regression remains **3,044 passed,
2 skipped, 4 subtests passed**, with no failures or collection errors. No product
code changed during this activation follow-up; the complete suite was therefore
not rerun. All 13 original delivery hashes were checked again against both the
LAN source and the tested isolated stage.

Private evidence:
`/home/lht/.local/share/brachybot-annotation-save/validation-20261008/`

- `activation.json`: process identities, health, pre-restart aggregate checks,
  no-force flag, and completion timestamp.
- `manifest-final.json`: original selected-file hashes.
- `full-suite.xml`: complete regression result.

Related repair analysis:
[Annotation Save Queue and Data Tree Feedback Audit](ANNOTATION_SAVE_UX_AUDIT_2026-10-08.md).

## Claim boundary

Implementation, regression validation, selected-file delivery, and LAN runtime
activation are complete for this repair. This does not promise instantaneous
storage I/O or certify the entire application's clinical readiness. Real-case
usability remains a separate acceptance step; no patient mutation was used as
an activation smoke test.
