# Account-Owned Persistent Case Workspaces

## Purpose

The web application now treats a clinical case as a durable, account-owned
workspace instead of a browser-local chat entry or a server-memory-only agent.
The ownership hierarchy is:

```text
User account -> owned case session -> durable workspace
```

Each case workspace contains its own inputs, clinical arrays, plan state,
artifacts, screenshots, chat history, execution timeline, and viewer state.
Selecting a case is equivalent to opening its own isolated planning workspace.

## What Is Persisted

The runtime root defaults to `.runtime/` and is Git-ignored. A workspace has:

```text
.runtime/
  brachybot.sqlite3                 # users, case metadata, leases, audit trail
  workspaces/<user-id>/<case-id>/
    inputs/                         # CT/DICOM and explicitly uploaded labels
    arrays/                         # NumPy sidecars for CT-derived data
    artifacts/                      # reports, DICOM-RT, STL, browser exports
    screenshots/                    # authenticated UI screenshots
    agent_state/                    # case-scoped auxiliary agent memory
    snapshot.json                   # JSON state and sidecar references
  trash/<user-id>/<case-id>/        # recoverable deleted workspaces
  .staging/                         # atomic upload/export staging files
```

`snapshot.json` stores JSON-only metadata. Numpy arrays use controlled `.npy`
sidecars with `allow_pickle=False`; Python objects, GPU handles, and SimpleITK
pipeline objects are never serialized. On restore, the CT is read only after
its path is confirmed to be inside the selected workspace, and visual meshes,
DVH, viewer layers, and agent memory are rebuilt from the durable arrays.

Unchanged clinical arrays are reused across checkpoints. Replaced arrays are
written to a new versioned sidecar, committed by an atomic snapshot replacement,
then the prior unreferenced sidecar is reclaimed. This prevents UI interaction
from copying CTV/OAR/dose volumes repeatedly or corrupting the previous
recoverable snapshot during a failed write.

## Authentication and Isolation

- Open registration, login, logout, current-user inspection, and password
  change are served by `/api/auth/*`.
- Passwords use Werkzeug password hashing; plaintext passwords are not stored.
- Login uses an `HttpOnly`, `SameSite=Lax` cookie. Mutating API calls require a
  per-login CSRF token.
- `BRACHYBOT_API_KEY` remains a deployment perimeter control. It is separate
  from user identity and does not authorize access to another account's case.
- The selected case is stored in the signed server cookie. Client payload
  `session_id` values are compatibility-only and cannot select an arbitrary
  workspace.
- Inputs, screenshots, viewer images, reports, and downloads are checked
  against the authenticated account and selected/owned case before file I/O.
- Auxiliary interaction memory, preferences, experience records, critic
  history, reflections, profiles, and crystallized skills are scoped to the
  workspace `agent_state/` directory rather than project-global `memory/data`.

No case sharing is implemented by design. A user cannot read, rename, restore,
download, or delete another user's case through the API.

## Case Lifecycle

1. Register or sign in. The server creates a first empty case when needed.
2. Create, rename, select, or delete cases from the server-backed sidebar.
3. On selection, the UI locks, clears only the old render resources, fetches
   the selected snapshot, restores CT/labels/plan/dose/Data Tree/viewer/DVH/
   report/chat/trace, then unlocks. It never calls planning clear implicitly.
4. Every tool completion, planning parameter change, manual needle/seed edit,
   report save, and UI bridge/training event is checkpointed. Agent memory
   changes are debounced; operation boundaries synchronously checkpoint.
5. A running task found after a server restart is marked `interrupted`. The
   last successful segmentation/plan/dose and parameters remain available;
   no GPU or LLM job is silently restarted.
6. Deleting a case moves it to the trash, revokes its lease, and removes it
   from normal access. It can be restored for seven days, then is permanently
   deleted by startup and periodic cleanup.

The browser may retain only short-lived account preferences and an optional
one-time legacy import payload. Case data itself is no longer sourced from
`localStorage`.

## Edit Leases

Each browser tab owns a random editor token in `sessionStorage`. The active
editor refreshes a short lease. A second browser can open the same case for
viewing but receives `workspace_locked` for writes until the lease is released
or expires. Targeted rename/delete/purge routes enforce the same protection
even when the locked case is not currently selected.

## Storage Quotas and File Safety

The per-account default is 20 GiB. It is set with:

```bash
export BRACHYBOT_USER_STORAGE_QUOTA_BYTES=$((20 * 1024 * 1024 * 1024))
```

Uploads, screenshots, browser-generated artifacts, server reports, and STL
exports use replacement-aware quota checks before their final atomic write.
Scientific exporters that require an output directory are constrained to the
selected workspace and checked again before an artifact is returned. Workspace
paths reject traversal and resolve symlinks before ownership checks. Runtime
directories use restrictive permissions where the host OS supports them.

## API Summary

| Area | Endpoints |
|---|---|
| Account | `POST /api/auth/register`, `login`, `logout`; `GET /api/auth/me`; `POST /api/auth/password` |
| Cases | `GET/POST /api/sessions`, `PATCH/DELETE /api/sessions/<id>`, `POST /select` |
| Recovery | `GET /api/sessions/trash`, `POST /restore`, `DELETE /purge` |
| Workspace | `GET /api/workspace/snapshot`, `POST /state`, `POST /checkpoint`, `POST/DELETE /lease` |
| Files | `POST /api/upload`, `POST /api/workspace/artifacts`, authenticated artifact/screenshot download routes |

All existing clinical endpoints keep their business payloads but now resolve
the current authenticated workspace on the server.

## Deployment Configuration

For production, set a stable random secret and use HTTPS:

```bash
export BRACHYBOT_SECRET_KEY="a-long-random-secret"
export BRACHYBOT_COOKIE_SECURE=1
export BRACHYBOT_API_KEY="deployment-perimeter-key"
export BRACHYBOT_RUNTIME_DIR="/srv/brachybot-runtime"
export BRACHYBOT_TRASH_RETENTION_DAYS=7
export BRACHYBOT_WORKSPACE_MAINTENANCE_SECONDS=3600
```

The application is designed for one active Python web process per runtime
directory because live `BrachyAgent`/GPU work is process-local. SQLite and
case leases protect durable metadata, but multi-worker clinical execution
requires an external shared task/agent coordinator before being enabled.

## Legacy Migration

After login, the UI offers a one-time import for old browser-local chat,
report, manual-planning, and viewer JSON. It does not import arbitrary browser
files. A pre-workspace in-memory plan can be captured only while its original
server process is still alive; otherwise its browser metadata is imported into
a new durable case and clinical inputs must be uploaded again.

## Verification

The focused regression suite covers password hashing and CSRF, unauthenticated
access denial, cross-account case denial, owned downloads, upload placement,
leases, trash/restore, restart interruption, artifact quota enforcement,
workspace snapshot round trips, array sidecar reuse/pruning, and workspace-
scoped auxiliary agent storage.

```bash
python -m pytest \
  tests/test_workspace_store.py \
  tests/test_workspace_auth.py \
  tests/test_agent_workspace_state.py -q
```

## Planning Liveness Audit

The planner must distinguish an unreachable clinical objective from a stalled
control-flow loop. The following guards are intentionally part of the durable
workspace release because an interrupted case must remain safely recoverable:

- CTV/OAR/planning workflow waits observe cancellation once per second. A
  stopped request never schedules downstream work, even though an already
  dispatched GPU call cannot be safely force-killed by Python.
- Geometric ray and trajectory scans reject zero/non-finite vectors, normalize
  their dominant voxel step, and have strict finite traversal bounds.
- Distance-based island shrinking is a deterministic one-pass operation. The
  previous float-distance retry loop could make no voxel change and therefore
  never reach its volume condition.
- Rule-based selection, re-planning, and fine-tuning have explicit iteration
  limits. RL has independent caps for candidate trajectories, dense seeds,
  hierarchy depth, actions per episode, episode count, and a wall-clock
  deadline.
- All planning stages now receive the same validated, invocation-local
  configuration snapshot. UI parameter changes can no longer cause trajectory
  generation to read defaults while seed optimization reads overrides.
- RL records aggregate seed-dose cache hits and model evaluations. This makes
  an expensive but bounded model-evaluation workload diagnosable from logs
  without logging patient geometry.
- The RL wall-clock budget is enforced inside DoseUNet preparation and at each
  sliding-window boundary, not only between episodes. A slow CPU fallback,
  GPU contention, or a large batch therefore cannot silently overrun the
  interactive budget by many minutes. The planner returns the best valid plan
  completed before the budget boundary; it never substitutes a simplified
  dose engine or changes the trained model's coordinate/normalization contract.
- Audit of every production `while` loop found no remaining planning loop
  whose only exit requires a dose or DVH value to improve. The few remaining
  external waits are either cancellable tool-thread joins, finite LLM/tool
  iteration budgets, bounded request/task deadlines, or stream reads that end
  at the HTTP request EOF.

Focused liveness and obstacle regression coverage:

```bash
python -m pytest \
  tests/test_planning_loop_guards.py \
  tests/test_rl_termination_and_batched_dose.py \
  tests/test_needle_obstacle_safety.py -q
```
