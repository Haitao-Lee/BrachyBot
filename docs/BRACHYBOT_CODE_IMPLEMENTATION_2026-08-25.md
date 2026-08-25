# BrachyBot Current Code Implementation Guide

## Document status and evidence boundary

This document is a source-derived implementation guide for the current BrachyBot checkout. It is intentionally written from the implementation, tests, and a small amount of live-process inspection. Narrative design documents, historical specifications, backup copies, and older explanatory material are not treated as the authority for any statement below.

The inspected source snapshot was:

| Item | Value |
|---|---|
| Repository | /home/lht/snap/brachyplan/BrachyBot |
| Commit | 2234c2dda2c0 |
| Branch | codex/session-task-recovery |
| Inspection date | 2026-08-25 |
| Working tree before this file | Clean |
| Primary application entry point | web/server.py |
| Primary agent entry point | AgenticSys.py |
| Primary persistence implementation | web/workspace_store.py |

The line references in this guide are orientation anchors, not an API versioning contract. The code is the final authority when a line number changes. Runtime observations are explicitly labeled as observations; they are not automatically configuration requirements.

## Contents

1. [System identity](#1-system-identity)
2. [Runtime topology](#2-runtime-topology)
3. [Application startup and request lifecycle](#3-application-startup-and-request-lifecycle)
4. [Authentication, CSRF, and ownership boundaries](#4-authentication-csrf-and-ownership-boundaries)
5. [Workspace persistence and recovery](#5-workspace-persistence-and-recovery)
6. [HTTP route surface](#6-http-route-surface)
7. [Browser application and frontend composition](#7-browser-application-and-frontend-composition)
8. [BrachyAgent composition](#8-brachyagent-composition)
9. [Memory, context, and LLM execution](#9-memory-context-and-llm-execution)
10. [Turn policy and execution authorization](#10-turn-policy-and-execution-authorization)
11. [Clinical image and structure conventions](#11-clinical-image-and-structure-conventions)
12. [Planning-run versioning](#12-planning-run-versioning)
13. [Clinical workflow and planning pipeline](#13-clinical-workflow-and-planning-pipeline)
14. [Dose calculation, dose evaluation, and recomputation](#14-dose-calculation-dose-evaluation-and-recomputation)
15. [Viewer, manual editing, and surgical guides](#15-viewer-manual-editing-and-surgical-guides)
16. [Background chat tasks and streaming](#16-background-chat-tasks-and-streaming)
17. [Tool registry and trusted-local developer capabilities](#17-tool-registry-and-trusted-local-developer-capabilities)
18. [Configuration and environment contracts](#18-configuration-and-environment-contracts)
19. [Testing and current operational evidence](#19-testing-and-current-operational-evidence)
20. [Change guide and source index](#20-change-guide-and-source-index)

## 1. System identity

BrachyBot is a Flask-served, browser-based brachytherapy planning workbench. The server-side isolation unit is a pair:

1. an authenticated user;
2. a case session owned by that user.

Every long-lived agent, workspace snapshot, chat task, planning run, screenshot, export, lease, and audit event is scoped around that pair. A browser tab is not the isolation boundary. The browser can select a case, disconnect, reconnect, or switch sessions while the case-owned server state continues to exist.

The current clinical workflow is organized as a closed loop:

    CT and case data
        -> CTV segmentation or label import
        -> OAR segmentation or label import
        -> trajectory initialization
        -> trajectory refinement
        -> seed planning
        -> dose calculation
        -> dose evaluation and DVH metrics
        -> manual editing or intra-operative re-planning
        -> dose recomputation
        -> report, DICOM RT, STL, or surgical-guide output

The LLM is an interaction and decision layer. It selects or proposes tool calls, resolves natural-language intent, asks for missing clinical information, and summarizes results. Deterministic application code remains responsible for:

- authentication and user/case ownership;
- turn-level authorization;
- prerequisite ordering;
- CT and mask alignment;
- obstacle and needle safety filtering;
- persistence and versioning;
- active-plan identity;
- cancellation and worker lifecycle;
- report and export provenance.

This separation is visible in agent_runtime/execution_authorization.py, agent_runtime/turn_policy.py, agent_runtime/llm_runtime.py, and AgenticSys.py. A sentence that mentions an operation is not, by itself, an authorization to execute that operation.

## 2. Runtime topology

The implementation is easiest to understand as the following dependency direction:

    Browser static application
        -> Flask route modules
            -> authenticated request/session context
                -> WorkspaceStore and per-case lease checks
                    -> BrachyAgent
                        -> AgentMemory and RunLedger
                        -> turn policy and execution authorization
                        -> ToolRegistry and ToolCallGateway
                            -> segmentation, planning, dose, viewer, report, export tools
                                -> model adapters, SimpleITK/numpy data, and planning kernels

The major layers are:

| Layer | Current implementation | Responsibility |
|---|---|---|
| Browser shell | web/app/index.html and web/app/static/js/* | Viewer, chat, report, workspace, session, export, and UI state |
| HTTP application | web/server.py | Flask creation, static serving, request context, legacy-compatible endpoints, task access, upload/import glue |
| Route modules | web/routes/*.py | Data, planning, session, viewer, and surgical-guide APIs |
| Identity | web/auth.py | Cookie login, registration, password changes, CSRF, rate limiting, API-key gates |
| Workspace store | web/workspace_store.py | SQLite metadata, JSON snapshots, array sidecars, revisions, recovery, leases, trash, audits |
| Agent composition | AgenticSys.py | BrachyAgent construction, LLM/brain setup, tool registration, live-memory injection, clinical safety mediation |
| Agent runtime | agent_runtime/* | Memory, context packs, run ledger, provider-neutral tool calls, policy, streaming |
| Tools | tool_factory/* | Segmentation, planning, dose, reports, export, viewer/UI, knowledge, and controlled developer tools |
| Clinical kernels | plans/core.py and domain packages | Candidate trajectories, seed optimization, dose model execution, evaluation |
| Model adapters | tool_factory/CTV_seg/*, tool_factory/OAR_seg/*, dose packages | nnUNet, TotalSegmentator, BiomedParse, DoseUNet, and alignment/provenance |

There are two different forms of state:

- **Durable case state**: snapshots, arrays, planning-run namespaces, report fields, chat transcript, audit events, and case metadata.
- **Live process state**: agent instances, GPU/model objects, active workers, stream buffers, cancellation events, and cache entries.

The workspace store is designed to reconstruct durable state into a fresh agent. It does not revive an old running worker as if the worker were still executing.

## 3. Application startup and request lifecycle

### 3.1 Flask construction

web/server.py:create_app is the main application factory. Its current startup responsibilities are:

1. create the Flask app with the application directory as the static root;
2. configure CORS for local origins by default, private-network origins when network trust is enabled, or the explicit ALLOWED_ORIGINS setting;
3. set the maximum request body size to 500 MB;
4. create WorkspaceStore(config.get("runtime_dir"));
5. purge expired session trash;
6. configure authentication routes and request protection;
7. start workspace maintenance with a minimum interval of 300 seconds;
8. install route modules and server-level compatibility handlers;
9. expose the browser application and API.

The default runtime directory is .runtime, unless an explicit runtime directory or BRACHYBOT_RUNTIME_DIR is supplied. The store is created before most case-dependent operations, so the database and storage layout exist even when no agent has yet been hydrated.

### 3.2 Request context resolution

The request path is deliberately owner-aware:

1. authentication middleware resolves the current user;
2. a request can provide an explicit session ID or the X-BrachyBot-Session header;
3. the requested session must belong to the authenticated user;
4. otherwise the selected case from the signed cookie is used;
5. if no selected case exists, the server can create or select a new session according to the route;
6. the resulting (user_id, session_id) key controls agent lookup, task lookup, persistence, and artifact access.

_request_session_context in web/server.py is the important boundary. A raw session identifier is not enough to access another user's state.

### 3.3 Agent cache and asynchronous hydration

web/server.py:get_agent maintains an in-process cache keyed by (user_id, resolved_session_id). The current implementation has:

- a maximum cache size of 50;
- an idle timeout of 3600 seconds;
- an initializer map so concurrent requests do not construct the same agent repeatedly;
- a generation counter to invalidate stale construction and hydration work;
- lock-protected installation and eviction.

Agent creation proceeds in phases:

1. construct BrachyAgent with the workspace root, case state directory, and workspace session ID;
2. hydrate metadata only, without loading CT arrays or planning result arrays;
3. install the persistence callback and initialize hydration flags;
4. return an agent that can expose metadata while heavier data is loading;
5. load CT data in a background phase;
6. load planning arrays and result payloads in a later background phase;
7. publish readiness flags and signal the ready event;
8. refuse installation or saving if the case was deleted, replaced, cancelled, or superseded during hydration.

The metadata-first behavior is important for the browser: case metadata can be painted before all masks, plans, dose, and report data are available. The implementation exposes separate state such as hydration phase, CT readiness, planning-data readiness, and a cancellation event.

The hydration code checks the generation and cancellation state before and after each phase. If a save or mutation races the hydration pass, it can retry rather than silently overwriting newer live data. A stale agent is never allowed to re-enter the active cache merely because its background thread eventually completed.

### 3.4 Maintenance and shutdown

Workspace maintenance periodically cleans expired leases, stale workspace artifacts, and other time-based records. Shutdown behavior is intentionally conservative: the server waits for active operations to unwind unless a separate explicit force-shutdown setting is enabled. This matters for GPU inference because a Python thread cannot reliably kill a kernel that has already started executing on the GPU.

## 4. Authentication, CSRF, and ownership boundaries

### 4.1 Cookie authentication

web/auth.py configures a signed Flask session with:

- user identity in bb_user_id;
- selected case identity in bb_session_id;
- an HTTP-only cookie;
- SameSite=Lax;
- optional Secure behavior through BRACHYBOT_COOKIE_SECURE;
- a persistent secret from BRACHYBOT_SECRET_KEY, or a private runtime secret file when the variable is absent.

The generated fallback secret is stored in the runtime directory with restrictive permissions. Production deployments should provide a deliberate secret rather than relying on process-specific setup.

### 4.2 User input rules

The current username rule is:

- ASCII letters, digits, underscore, period, and hyphen;
- length from 3 through 64 characters.

The minimum password length enforced by the current authentication module is 12 characters. Passwords are hashed using Werkzeug's password hashing helpers; plaintext passwords are not part of the workspace snapshot.

### 4.3 API protection and CSRF

The authentication before-request hook protects /api/* except the authentication endpoints. Mutating requests using POST, PUT, PATCH, or DELETE require the CSRF token associated with the authenticated browser session. The public authentication surface is:

- POST /api/auth/register
- POST /api/auth/login
- POST /api/auth/logout
- POST /api/auth/password
- GET /api/auth/me

Registration and login paths use the module's rate-limiting logic. Registration additionally requires the deployment API-key gate configured by the application. The API key is never written into this document or any generated artifact.

### 4.4 Case ownership, edit leases, and delete safety

Authentication answers “who is this user?”; workspace ownership answers “which case may this user access?”; edit leases answer “who may mutate this case right now?”.

WorkspaceStore.assert_editable is used by mutation paths to enforce the lease/editability contract. A read-only viewer can still inspect an authorized case, but mutation routes must pass the workspace ownership and editability checks. Deletion uses a recoverable trash state before permanent purge, subject to the session lifecycle routes and retention policy.

## 5. Workspace persistence and recovery

### 5.1 On-disk layout

WorkspaceStore is implemented in web/workspace_store.py and uses a runtime directory with this shape:

    .runtime/
        brachybot.sqlite3
        brachybot.sqlite3-wal
        brachybot.sqlite3-shm
        workspaces/
            <case-session-id>/
                snapshot.json
                arrays/
                artifacts/
                screenshots/
        trash/
        .staging/

The exact root may be relocated with BRACHYBOT_RUNTIME_DIR. Runtime directories are created with restrictive permissions. SQLite, WAL, and shared-memory files are set to owner-only permissions where the platform permits it.

The database uses SQLite foreign keys and WAL mode. A re-entrant lock is maintained per case to serialize snapshot preparation and commit operations without globally serializing unrelated cases.

### 5.2 Database records

The current initialization code creates tables for:

- users;
- case_sessions;
- workspace_leases;
- audit_events;
- review_comments.

case_sessions tracks status, revision, and recovery status in addition to ownership and case metadata. The audit table records state-changing operations and recovery/persistence events. Review comments are stored as workspace review data rather than being mixed into the LLM transcript.

### 5.3 Snapshot contract

The empty snapshot created by WorkspaceStore has these top-level sections:

    schema_version
    session_id
    saved_at
    agent
    ui
    report
    chat
    operation

The agent section includes:

- configuration;
- planning results;
- patient data;
- conversation;
- tool results;
- context summary;
- compaction count;
- current planning phase;
- structured conversation state;
- user language.

The ui section contains browser-facing state. The report section contains report data and report-generation state. The chat section contains messages, execution trace, and attachments. The operation section contains the durable operation state and checkpoint.

The store adds public workspace/session metadata on load and removes internal visual records that are not intended to become normal transcript content. Attachment references are reconciled during load so a stale browser payload cannot make a missing file appear durable.

### 5.4 Patch and revision behavior

save_snapshot_patch merges a patch under the per-case lock and can require an expected revision. It atomically updates the durable snapshot and increments the case revision. A revision mismatch is a conflict signal, not permission to overwrite the newer snapshot.

Chat patches are append/merge oriented. This prevents a stale browser tab from replacing a newer execution trace or final response with an older full-document copy. Report patches pass through sanitization and planning identity logic. UI and operation patches remain independently addressable.

Every successful durable commit updates recovery metadata and creates an audit event. The recovery status distinguishes a workspace that has a current snapshot from one whose latest live state has not yet been persisted.

### 5.5 Array sidecars and quota handling

Heavy numpy and imaging arrays are stored as per-case .npy sidecars under the case's arrays directory. snapshot_agent and _prepare_agent_snapshot:

1. take the agent memory lock;
2. capture a coherent state view;
3. prepare arrays outside the case commit lock where possible;
4. reuse unchanged sidecars after restart;
5. encode only durable arrays;
6. skip transient objects and reloadable raw CT objects;
7. check storage quotas;
8. commit references and JSON metadata atomically;
9. prune unreferenced sidecars after a successful commit;
10. remove newly created sidecars if the commit fails or the case is deleted.

This design avoids making a multi-gigabyte CT volume part of every JSON write while still allowing a fresh process to reconstruct the agent.

### 5.6 Hydration semantics

hydrate_agent supports separate restoration phases:

- metadata-only hydration;
- CT hydration;
- planning-result hydration.

It accepts a cancellation event and phase callback. It restores data into the agent memory but deliberately does not resurrect active running tasks. A restored run is represented by the runtime contract as interrupted or otherwise non-running, so a new request must establish a new live operation.

### 5.7 Trash, leases, and audit

Case deletion is staged through trash rather than immediately destroying all state. Purge is a separate operation. Workspace leases prevent concurrent mutation and are auditable. The store also exposes workspace audit and review-comment APIs so that operational changes can be inspected independently of the chat transcript.

## 6. HTTP route surface

The current source contains 110 route declarations when aliases and repeated declarations are counted. That is not 110 unique URL strings. The route modules are:

- web/auth.py;
- web/routes/data_routes.py;
- web/routes/planning_routes.py;
- web/routes/session_routes.py;
- web/routes/surgical_guide_routes.py;
- web/routes/viewer_routes.py;
- web/server.py.

The following inventory is grouped by module. It describes the current route surface rather than promising that every route is a stable public API.

### 6.1 Authentication routes

- POST /api/auth/register
- POST /api/auth/login
- POST /api/auth/logout
- POST /api/auth/password
- GET /api/auth/me

### 6.2 Data, object, and export routes

- GET /api/data/catalog
- PATCH /api/data/structures/<path:object_id>/classification
- PATCH /api/data/structures/classification
- PATCH /api/data/generic-masks/classification
- POST /api/data/objects/batch-delete
- DELETE /api/data/objects/<path:object_id>
- POST /api/data/exports
- GET /api/data/exports/<job_id>
- POST /api/data/exports/<job_id>/cancel
- GET /api/data/exports/<job_id>/download
- GET /api/data/exports/<job_id>/files/<path:relative_path>

The data catalog is the server-side view of available structures and generic masks. Classification updates affect obstacle and clinical-role interpretation; they are not merely cosmetic labels.

### 6.3 Planning and agent routes

- POST /api/planning/clear
- GET /api/planning/results
- GET /api/planning/runs
- POST /api/planning/runs/<planning_id>/activate
- POST /api/manual_planning/restore_algorithm_plan
- POST /api/planning/show_step
- POST /api/segmentation
- GET /api/ctv/models
- POST /api/ctv/models/validation
- POST /api/planning/run_step
- GET /api/planning/config
- POST /api/planning/dose_isosurface
- GET /api/planning/dose_overlay
- POST /api/planning/dose_overlay_slice
- POST /api/planning/dose_contour_slice
- GET and POST /api/config
- GET /api/device/status
- GET and POST /api/ui/state
- GET /api/ui/capabilities
- POST /api/ui/event
- POST /api/training/start
- POST /api/training/stop
- GET and POST /api/training/advice
- GET and POST /api/readiness
- POST /api/manual_planning/update
- POST /api/manual_planning/update_geometry
- POST /api/manual_planning/delete_needle
- POST /api/manual_planning/update_seeds
- POST /api/manual_planning/restore_needle
- GET /api/status
- POST /api/plan/preoperative
- POST /api/plan/intraoperative
- POST /api/chat/abort
- POST /api/clear_all
- POST /api/export/dicom
- POST /api/export/dicom_rt
- POST /api/export/stl
- POST /api/chat
- GET /api/chat/task
- GET /api/chat/tasks/<task_id>/stream
- /api/tasks/stream
- GET /api/tasks/<task_id>
- GET /api/tasks
- POST /api/export/report
- POST /api/viewer/control
- POST /api/screenshot
- GET /api/sessions/<session_id>/screenshots/<filename>
- GET /api/screenshots/<filename>

The two DICOM export paths are compatibility aliases. The planning route module also contains UI-facing helper endpoints for dose visualization, readiness, training state, and manual editing.

### 6.4 Session and workspace routes

- GET and POST /api/sessions
- PATCH /api/sessions/<session_id>
- DELETE /api/sessions/<session_id>
- POST /api/sessions/<session_id>/select
- POST /api/sessions/<session_id>/restore
- GET /api/sessions/trash
- DELETE /api/sessions/<session_id>/purge
- GET /api/sessions/<session_id>/artifacts/<path:artifact_path>
- POST /api/workspace/artifacts
- GET /api/workspace/snapshot
- POST /api/workspace/state
- POST /api/workspace/checkpoint
- POST /api/workspace/lease
- DELETE /api/workspace/lease
- GET /api/workspace/audit
- GET and POST /api/workspace/review/comments
- PATCH /api/workspace/review/comments/<int:comment_id>
- POST /api/workspace/import-client

### 6.5 Surgical-guide routes

- GET /api/surgical-guides
- GET /api/surgical-guides/mesh
- POST /api/surgical-guides/generate
- POST /api/surgical-guides/export
- POST /api/surgical-guides/validate

The exact prefix is defined by the route module's decorators; the implementation routes the guide lifecycle through planning-run identity and active-plan validation.

### 6.6 Viewer routes

- POST /api/viewer/load
- POST /api/viewer/slice
- POST /api/viewer/overlay
- POST /api/viewer/threshold
- POST /api/viewer/hu
- POST /api/viewer/3d
- POST /api/viewer/3d_mask
- POST /api/viewer/3d_skin
- GET /api/viewer/volume
- GET /api/viewer/label_volume
- GET /api/viewer/generic_masks
- GET /api/viewer/generic_mask_volume
- GET /api/viewer/organs
- GET /api/viewer/skin_surface_volume
- GET /api/planning/seeds_3d

Viewer APIs consume the current active case and active planning aliases. A historical planning run must be activated before these active-alias-oriented routes can display it as the current plan.

## 7. Browser application and frontend composition

The browser entry point is web/app/index.html. The current frontend is a static application served by Flask rather than a separately discovered server-side template system. The page loads Plotly, Marked, Prism language support, Three.js, OrbitControls, and html2canvas, followed by BrachyBot-specific JavaScript modules.

The application modules currently loaded by the page include:

- brachybot-chat-core.js;
- brachybot-chat-todo.js;
- brachybot-ui-api.js;
- brachybot-auth.js;
- brachybot-viewer-volume.js;
- brachybot-viewer-layout.js;
- brachybot-3d-manual.js;
- brachybot-manual-annotation.js;
- brachybot-surgical-guide.js;
- brachybot-dvh-planning.js;
- brachybot-report-shell.js;
- brachybot-report-editor.js;
- brachybot-workspace.js;
- brachybot-session-cache.js;
- brachybot-report-export.js;
- brachybot-data-export.js;
- brachybot-theme.js.

The frontend responsibilities are split roughly as follows:

| Frontend area | Server contract it relies on |
|---|---|
| Authentication | /api/auth/*, CSRF-bearing cookie session |
| Chat and progress | /api/chat, task status, task SSE, abort endpoint |
| Workspace/session | /api/sessions*, /api/workspace/*, snapshot and lease APIs |
| Viewer | /api/viewer/*, volume and label-volume APIs, screenshots |
| DVH and planning | planning results, dose overlay, seed geometry, plan activation |
| Manual planning | geometry, needle, seed, restore, and dose-recompute paths |
| Reports and exports | report state, report export, DICOM RT, STL, data-export jobs |
| Surgical guide | guide listing, generation, mesh, validation, and export |
| Theme/UI | /api/ui/state, /api/ui/capabilities, UI event logging |

The session cache and workspace modules are particularly important for reconnect behavior. A browser refresh must rehydrate from the server snapshot rather than assume that in-memory JavaScript state is authoritative.

## 8. BrachyAgent composition

### 8.1 Class composition

AgenticSys.py defines BrachyAgent. The class inherits the response-tool mixin, LLM runtime mixin, and chat workflow mixin. This is a composition of responsibilities rather than a single monolithic planning algorithm.

During initialization, BrachyAgent creates or attaches:

- AgentMemory;
- ToolRegistry;
- an optional workspace-state directory;
- RunLedger;
- ContextPackBuilder with a 12,000-token context budget and a 2,000-token output reserve;
- ToolCallGateway;
- InteractionMemory;
- PreferenceStore;
- SkillRegistry and SkillLearner;
- the current skill set, approximately 28 registered skills in the inspected source;
- the LLM brain, router, and clinical decision components;
- self-evolution, enhanced-integration, and multi-agent components.

The workspace session ID and state directory are injected at construction time. They are not inferred from the user's prose, which is why a case switch must pass through the server session context before an agent is obtained.

### 8.2 Brain and provider selection

The brain initialization path creates the LLMRouter, CaseExecutor, DoseRAG, BrainToolBridge, brain registry, ToolCodeWriter, and planner/clinical/quality deciders. The router is used for planning and evaluation decisions, while the streaming runtime owns the turn-level provider interaction and tool-call loop.

The provider auto-detection logic in AgenticSys.py checks Anthropic and Anthropic-compatible configuration first. It distinguishes the native Anthropic SDK path from OpenAI-compatible endpoints based on the configured base URL and model family, including the current OpenCode Go model handling. It then checks the supported provider families, including:

- OpenAI;
- DeepSeek;
- Qwen or DashScope;
- Kimi or Moonshot;
- GLM or Zhipu;
- Gemini or Google;
- Groq;
- Grok or xAI;
- MiniMax;
- Tencent;
- OpenRouter;
- Ollama;
- a generic OpenAI-compatible endpoint using LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL.

If a brain is unavailable, the agent has explicit fallback behavior. Planning and evaluation do not silently pretend that an LLM decision was made. Depending on the call, the result is a deterministic fallback, a human-review state, or an llm-unavailable error.

### 8.3 Current tool families

AgenticSys.py registers the following current tool families when their import and availability checks succeed:

- dicom_rt_exporter;
- code_executor;
- filesystem_browser;
- env_manager;
- tool_creator;
- shell_executor;
- doc_reader;
- ui_inspector;
- ui_controller;
- ui_screenshot;
- ui_content;
- ui_annotate;
- query_metrics;
- ctv_segmentation;
- biomedparse_segmentation;
- ctv_model_catalog;
- oar_segmentation;
- dose_engine;
- dose_recompute;
- dose_evaluation;
- seed_planning;
- seed_segmentation;
- trajectory_planning;
- planning_pipeline;
- case_memory;
- surgical_guide;
- clinical_kb;
- plan_comparator;
- safety_validator;
- plan_quality_scorer;
- oar_constraint_checker;
- plan_refinement;
- report_generator;
- report_auto_fill;
- web_search;
- web_fetch;
- web_access.

The source registration list and the tool registry are not identical to the provider-visible tool list. Availability is dynamic, and turn policy filters the registry again before the provider sees schemas. The inspected running server log reported 37 registered tools; that number is an observation of one process, not a hard-coded architectural invariant.

### 8.4 Server-owned clinical state

BrachyAgent._execute_tool_with_memory is the boundary where the LLM's requested arguments are combined with live case state. The code injects or replaces sensitive inputs from the active agent memory, including:

- the canonical live CT;
- the case-owned CTV and OAR label paths;
- the active planning context;
- current obstacle classifications;
- current seed and needle geometry;
- current planning metrics;
- the current authoritative plan for safety validation.

For example, query_metrics does not trust arbitrary arrays supplied in an LLM tool argument when a current planning context exists. safety_validator receives the server-owned active plan. CTV, OAR, and BiomedParse tools receive the live CT and case-owned paths. Trajectory planning receives the current obstacle context and CT.

This injection is also why a provider schema may contain x-server-injected fields internally while the public provider schema does not expose those fields as user-controlled parameters.

## 9. Memory, context, and LLM execution

### 9.1 AgentMemory

agent_runtime/core.py defines AgentMemory. The current memory object contains:

- patient_data;
- planning_results;
- monotonically increasing planning-result versions;
- tool_results;
- conversation;
- context_summary;
- compaction count;
- current PlanningPhase;
- a deviation threshold of 2 mm;
- UI state;
- an optional persistence callback;
- user language;
- structured conversation_state;
- SmartContextManager with an 8,000-token working-context limit.

The structured conversation state records workflow facts such as:

- ctv_segmented;
- oar_segmented;
- planning_completed;
- last_tool_calls;
- data_available.

Planning result versions allow the system to distinguish a newer active result from a stale result that arrived after a case mutation. Persistence notifications are emitted when durable memory changes.

CTV and OAR label merge logic is safety-aware. CTV label priority wins over an OAR label with the same normalized identity, including the current pancreas collision example. If an OAR is stored after a CTV, overlapping labels are stripped or normalized so the CTV is not silently reclassified as an OAR.

### 9.2 RunLedger and runtime contracts

agent_runtime/contracts.py defines provider-neutral run states:

- queued;
- reasoning;
- awaiting_input;
- executing_tool;
- reviewing;
- completed;
- failed;
- cancelled.

AgentRun objects cannot be resurrected after a terminal state. The ledger keeps a case-local history capped at 40 entries. When state is restored from a snapshot, active runs are generally converted to interrupted/non-running state, except for the explicit awaiting-input semantics. A new request must therefore begin a fresh live run.

The ledger records context manifests, lifecycle events, tool calls, and terminal state. This makes the execution trace independent of a provider's native message format and allows a later audit to see which tool was requested, authorized, started, and completed.

### 9.3 ContextPackBuilder

ContextPackBuilder builds a portable provider-neutral context. Its current behavior is:

1. collect recent conversation and tool evidence;
2. compact oversized tool contents, with the current compaction threshold around 1,400 units for individual tool payloads;
3. translate unmatched tool messages into historical evidence rather than emitting malformed provider sequences;
4. add the current user message;
5. return the provider messages plus a context manifest.

The context builder has a 12,000-token maximum and reserves 2,000 tokens for the provider's output. SmartContextManager supplies a smaller working view from the agent memory when a full durable transcript would be too large.

### 9.4 ToolCallGateway

ToolCallGateway validates provider-neutral ToolCall objects against ToolRegistry. Validation covers:

- tool existence;
- required fields;
- basic types;
- enum values;
- server-injected fields;
- idempotency metadata.

A ToolCall idempotency key is derived from the tool name, normalized parameters, and workspace revision. The current cache is intentionally narrow; clinical knowledge calls are the primary idempotent cache case rather than a blanket cache for all mutating tools.

The gateway updates RunLedger state before and after execution, catches malformed tool results and exceptions, and records the result. A tool returning an unexpected object is converted into a failed, auditable result instead of being allowed to corrupt the conversation sequence.

### 9.5 Chat entry and local policy

chat_workflows.py:chat is the normal non-streaming entry. It:

1. begins a new run;
2. stores the user message unless the turn is a hidden visual child;
3. detects response language;
4. classifies the local turn policy;
5. handles local image metadata, report, session, and current-dose paths where appropriate;
6. uses the LLM function-calling path when the brain is available;
7. uses a rule-based fallback only when the brain is unavailable;
8. returns the response after the response/review gate.

Small talk is not treated as a clinical mutation. It still uses the LLM for the user-facing response when the brain is available. The local classifier is an execution policy boundary, not a replacement for natural-language response generation.

chat_with_stream isolates an internal visual-analysis child turn. It snapshots memory, suppresses normal persistence for the hidden child, runs the child stream, and restores the parent memory. The child can provide visual evidence to the parent without becoming an ordinary user-visible transcript turn.

### 9.6 Streaming LLM loop

agent_runtime/llm_runtime.py drives the streaming loop. Before provider execution, it:

- compacts memory if needed;
- adds a response-language directive;
- supplies the hidden visual-child prompt when applicable;
- includes enhanced, SOP, crystallized-skill, and user-preference context;
- classifies the query as realtime, knowledge, analysis, system, or clinical;
- uses structured current-state context;
- restricts CT/image tools for visual children;
- applies external-project scope;
- forces web search for realtime or external-project queries when required;
- injects a forced search result so the model does not search again;
- chooses a maximum iteration count of 3 for knowledge/external/clinical-knowledge turns and 8 for broader actions;
- retries one provider call when the provider path supports it.

The provider-visible tool schema is filtered by all of these constraints:

1. registry availability;
2. no-CT restrictions;
3. external-project restrictions;
4. visual-child read-only restrictions;
5. local turn-policy allow-list;
6. current authorization state.

The runtime parses native and text-form tool calls, handles incomplete markers, normalizes calls, records the action plan, grants only selected calls to the current authorization, normalizes clinical order, blocks unauthorized mutations, and executes the ordered plan.

For a completed planning turn, the final response can be assembled from stored metrics and a structured planning report rather than asking the LLM to invent metric values from a summary prompt.

### 9.7 Clarification, cancellation, and disconnects

If tumor_type is missing before CTV execution, the runtime stores pending clarification, transitions the ledger to awaiting_input, and asks for the anatomical site. It does not guess a site solely to make the pipeline continue.

A cancellation event stops downstream execution in a tool chain. It cannot necessarily interrupt a GPU inference already inside a model kernel. The worker records the cancellation and prevents later dependent steps from publishing as if the turn had completed.

An SSE disconnect is not interpreted as a clinical cancellation. The task continues in the server-side task manager until it completes, fails, or the user explicitly presses Stop.

## 10. Turn policy and execution authorization

### 10.1 Policy principle

agent_runtime/execution_authorization.py states the current security model directly:

- the LLM owns semantic intent;
- mentioning an operation is not authorization;
- deterministic code owns safety, prerequisites, ordering, and persistence;
- the module contains no natural-language matching.

This prevents a raw substring such as “do not plan”, “only analyze”, or “explain planning” from accidentally being treated as a positive mutation command.

### 10.2 Mutating and derived tool groups

The current MUTATING_TOOLS set includes:

- ctv_segmentation;
- oar_segmentation;
- biomedparse_segmentation;
- trajectory_init, trajectory_refine, and trajectory_planning;
- seed_planning, seed_rule_based, and seed_rl;
- dose_engine;
- dose_recompute;
- dose_evaluation;
- planning_pipeline;
- surgical_guide;
- plan_refinement;
- report_auto_fill;
- report_generator;
- ui_controller.

PLANNING_ANCHOR_TOOLS contains the trajectory, planning, dose, and seed-planning anchors. PLANNING_DERIVED_TOOLS contains CTV segmentation, OAR segmentation, and planning_pipeline.

A TurnExecutionAuthorization belongs to one turn. It carries a token, granted tools, granted workflows, authorization events, and the deterministic action plan. A tool is allowed only when the current turn grant permits it.

A planning workflow grant covers the planning-derived CTV/OAR/pipeline sequence. Surgical-guide generation is independent unless the turn explicitly grants it. This distinction matters because a planning request should not silently create or export a guide.

### 10.3 Local turn policy

turn_policy.py defines knowledge, UI, and clinical tool groups. It also defines the canonical planning plans:

- planning-only: CTV -> OAR -> planning_pipeline;
- planning-plus-guide: CTV -> OAR -> planning_pipeline -> surgical_guide.

The action plan stores dependencies, so the executor can establish prerequisites before a dependent call. The semantic-resolution boundary detects negation, exclusions, “only”, “then”, “before”, conditional language, corrections, analysis/explanation requests, and comparisons. Such turns go to the primary LLM rather than a local fast path.

Canonical fast paths accept only unambiguous imperative forms. Examples of policy outcomes are:

- canonical CTV/OAR segmentation commands receive direct grants for the relevant segmentation tool;
- a clear planning command receives the clinical planning workflow grant;
- a clear guide-generation command receives a direct surgical-guide grant;
- a compound plan-plus-guide command receives an explicit sequence;
- interrogative or conditional planning language goes to semantic resolution;
- generic questions go to the knowledge path;
- current-case dose questions can use the live active planning context;
- image metadata and report operations use their specific read/direct paths.

The policy does not parse the user's raw message again inside BrachyAgent._planning_requested. That method relies on the current TurnExecutionAuthorization workflow grant or planning anchor tool calls. The runtime therefore has one deterministic policy decision instead of multiple inconsistent text classifiers.

### 10.4 Order normalization and redundant execution

llm_runtime.py normalizes the selected clinical order and filters unauthorized mutating calls. It also blocks redundant CTV, OAR, or planning calls when the active case already contains those outputs, unless the turn explicitly requests re-execution. A direct re-plan command marks force_reexecution so a user can deliberately recompute.

The old behavior that silently ran a missing CTV step when the model skipped a prerequisite is disabled in AgenticSys.py. If the model asks planning_pipeline without a CTV, the system returns a clear prerequisite error and expects the model to follow the required sequence. PlanningPipelineTool itself retains a narrower internal OAR recovery path for a full pipeline; it does not make missing CTV disappear.

### 10.5 Safety boundary after authorization

Authorization is only the permission to attempt a tool call. It is not a replacement for tool validation. After authorization:

1. server-owned live inputs are injected;
2. prerequisite checks run;
3. clinical arrays are aligned;
4. obstacle and needle safety filters run;
5. result provenance is attached;
6. durable planning state is published only at the appropriate commit point.

A tool can therefore be authorized yet fail safely because an input is missing, a model is unavailable, a mask is empty, a geometry is unsafe, or an active-plan identity check fails.

## 11. Clinical image and structure conventions

### 11.1 CT grid and physical coordinates

The current segmentation and planning paths use SimpleITK physical geometry rather than shape-only assumptions. Canonical label output is oriented to an LPI reference grid. Alignment compares image size, spacing, origin, direction, and physical coordinate mapping, then resamples or transforms a label to the CT reference grid.

This is important for uploaded masks: equal numpy shapes do not prove that a label overlays the intended anatomy. The CTV and OAR tools align uploaded labels physically, preserve LPI metadata, and attach alignment/provenance details to the result.

Planning code may maintain both raw/source CT metadata and an LPI-oriented working CT. The pipeline's resampling grid is a planning representation, not a replacement for the original CT reference grid used for viewer and result delivery.

### 11.2 CTV tumor-type normalization

CTV_seg normalizes aliases before selecting a model. The current canonical mappings are:

| User/site alias family | Canonical selector |
|---|---|
| pancreatic and pancreas aliases | nnunet_pancreatic |
| liver aliases | totalsegmentator_liver_tumor |
| kidney aliases | biomedparse_kidney_lesion |
| lung aliases | biomedparse_lung_lesion |
| colon aliases | biomedparse_colon_primary |
| head/neck aliases | biomedparse_head_neck_cancer |
| prostate aliases | prostate_tumor |

resolve_ctv_tumor_type accepts tumor_type, model, tumor_site, site, organ, and organ_type aliases. A missing site does not fall back to a random model. The tool returns a clarification-required result with the current model catalog.

### 11.3 CTVSegmentationTool contract

ctv_segmentation accepts:

- a server-injected SimpleITK image;
- image_path;
- label_path;
- tumor_type and the accepted aliases;
- target_value;
- fast_mode;
- allow_empty for test/controlled cases;
- force_reexecution.

The tool first handles an uploaded label path when provided. It aligns the label to the CT's LPI physical grid. Otherwise it requires both a CT and a normalized tumor type and invokes the selected model adapter.

The result contains, as available:

- a CTV mask or array;
- voxel count;
- volume in mm3;
- source;
- LPI orientation/grid metadata;
- label-map and statistics;
- model provenance;
- optional OAR-related metadata;
- diagnostics when an adapter fails.

An empty mask fails by default. allow_empty is not the normal clinical success path. Model failures retain adapter diagnostics and fail closed instead of emitting an apparently valid empty target.

### 11.4 OARSegmentationTool contract

oar_segmentation supports pancreatic, aorta, and general organ modes. It can consume an uploaded label path or invoke the pancreatic OAR or TotalSegmentator adapter. Uploaded unknown structures are preserved as uploaded_unknown and receive names such as OAR 1 until the user renames or reclassifies them.

The result includes labels, counts, names, source, provenance, and LPI metadata. OAR labels are physically aligned to the CT, not merely resized to the same array shape.

### 11.5 Structure identity and obstacle policy

The data catalog and classification endpoints feed the live Data Tree state used by planning. A structure's clinical classification can change whether it is treated as a target, OAR, background, or hard obstacle. Planning trajectory initialization and refinement rebuild obstacle context from current classifications so a stale initial classification is not permanently baked into every later step.

CTV has priority over same-identity OAR labels during merge and normalization. This prevents a structure that was recognized as a target from being overwritten by a later generic OAR import.

### 11.6 Model availability versus model presence

A model checkpoint on disk is not the same as an enabled model runtime. The BiomedParse adapter resolves:

- BIOMEDPARSE_ROOT or BIOMEDPARSE_V2_ROOT;
- BIOMEDPARSE_V2_CHECKPOINT;
- optional text assets;
- optional Python executable;
- probe and inference timeouts.

It records adapter diagnostics and reports missing runtime configuration explicitly. The current repository contains a BiomedParse v2 checkpoint, but the live process observation in this inspection did not contain the BiomedParse runtime variables, so this guide does not claim that BiomedParse was active in the running server.

## 12. Planning-run versioning

### 12.1 Active aliases and namespaced history

web/planning_runs.py maintains two related representations:

- active planning aliases used by current Viewer, DVH, dose, and guide code;
- namespaced planning-run snapshots used for history and restoration.

ensure_planning_history migrates legacy labels into one-based names such as Planning_1 and Planning_2. The active aliases are authoritative for the currently displayed plan, while a namespaced run preserves a historical or immutable result.

### 12.2 Run lifecycle

A normal algorithmic planning lifecycle is:

1. begin_planning_run clears the old active aliases and creates a planning-UUID run with status running;
2. trajectory, seed, dose, and metric outputs are written to the active state;
3. publish_planning_run snapshots those active aliases into the namespaced run;
4. the run stores status, sequence, visibility, input revision, parent identity, metrics, dose/DVH presence, guide state, skin state, and artifact status;
5. the completed run becomes the visible run;
6. the active aliases remain available for the Viewer and interactive controls.

If the new run fails or is cancelled, the parent can be restored when possible instead of leaving an empty active state.

### 12.3 Manual editing and forked drafts

fork_planning_run creates an editable child draft before manual edits. The parent remains a restore point. This is how the implementation keeps a known algorithmic plan available while the user changes needle geometry, seed placement, or other plan inputs.

Manual geometry edits call invalidate_planning_dependents. The active dose, DVH, report, quality-check, and surgical-guide artifacts are marked stale or removed as appropriate. Guide versions are cleared because a guide generated for old geometry is not automatically valid for new geometry.

### 12.4 Activation and alias repair

activate_planning_run loads a namespaced snapshot into the legacy active aliases. This is necessary because current Viewer/DVH/guide paths operate against those aliases. restore_active_planning_aliases can repair missing aliases from the active immutable run snapshot without replacing newer live edits.

current_planning_context and active_planning_id are used by metrics, safety validation, dose recomputation, and other paths that must operate on the plan currently presented to the user.

### 12.5 Artifact identity

A report, dose, DVH, quality result, or guide is valid only relative to the planning identity and the input revision from which it was produced. Code that adds a new artifact should therefore update the planning-run metadata and its artifact-status fields rather than writing an unqualified global result.

## 13. Clinical workflow and planning pipeline

### 13.1 PlanningPipelineTool interface

tool_factory/seed_plan/planning_pipeline.py defines PlanningPipelineTool. It accepts a full run or individual steps:

- full;
- trajectory_init;
- trajectory_refine;
- seed_planning;
- dose_calc;
- dose_eval.

The main planning mode is rule_based or rl. The schema accepts CT, CTV, and OAR paths, seed information, constrained planning parameters, and a reference direction. The reference direction can be a vector or auto/auto_detect; automatic direction selection is organ-aware/geometric.

The tool requires a session-local injected agent for the normal pipeline. It can use explicit paths, but it also reads the current case-owned CT, CTV, OAR, and configuration from AgentMemory. Without an injected agent, the tool fails rather than attaching itself to an arbitrary global case.

### 13.2 Prerequisites and OAR recovery

A full pipeline requires CTV. It can auto-recover OAR through the agent's registry when OAR is missing and the current adapter can produce it. It cannot auto-recover missing CTV. This is deliberate: target creation is a clinical prerequisite that must be authorized and completed explicitly.

This internal OAR recovery is narrower than the old global agent auto-fix, which is disabled. The two behaviors must not be conflated:

- the agent-level silent “run whatever prerequisite is missing” behavior is off;
- the full pipeline's specific OAR recovery branch remains in the pipeline implementation.

### 13.3 Input normalization and configuration isolation

Before planning, the tool:

1. loads or resolves CT, CTV, and OAR;
2. normalizes the CT and preserves source metadata;
3. aligns masks to the CT/LPI grid;
4. merges embedded hard obstacles;
5. deep-copies invocation-local configuration;
6. applies only allowed planning overrides;
7. prevents per-call overrides from mutating session-wide configuration.

The planning tool keeps a shared body mask for geometry stages. It also records the obstacle labels and their source so the generated trajectory set can be explained later.

### 13.4 Trajectory initialization

trajectory_init:

1. requires CT and CTV;
2. resamples CT, CTV, and OAR to the planning grid, currently based on a 128 by 128 by rounded-slice representation;
3. resolves the current Data Tree obstacle whitelist;
4. builds target, background, and obstacle radiation volumes;
5. converts a RAS reference direction into voxel coordinates when needed;
6. calls plans.core.init_plan;
7. filters candidates with safe-trajectory and world-space safety checks;
8. applies the body mask when available;
9. stores trajectories, resampled data, radiation volume, obstacle IDs/source, and reference direction.

The result is a candidate trajectory state, not yet a published seed plan.

### 13.5 Trajectory refinement

trajectory_refine automatically initializes when necessary. It rebuilds radiation volume from the current Data Tree state, filters candidates again, applies minimum-depth constraints, and sorts by depth. Rebuilding from live classification is essential because a user can change an OAR or obstacle classification after the first geometry pass.

### 13.6 Seed planning

seed_planning requires CTV and trajectories. If an earlier geometry stage is absent, it can run the required internal initialization/refinement step. It then:

1. rebuilds the radiation volume;
2. applies safe and world-safe trajectory filters again;
3. loads the DoseUNet model;
4. converts configured dose bounds into the model's dose scale;
5. calls plans.core.optimal_plan for rule-based mode;
6. calls plans.core.optimal_plan_rf for RL mode;
7. checks coverage and can run a safety-filtered rule-based fallback when RL coverage is below target and fallback is enabled;
8. validates the actual seed-derived needle geometry;
9. rejects unsafe final needles before publishing;
10. stores the seed plan, serialized plan, verified needle geometry, algorithm plan snapshot, dose, total seed count, trajectories, and plan configuration.

The plan configuration records the effective mode, fallback status, dose units/scales, DVH settings, needle spacing, and seed parameters. A newly generated algorithm plan invalidates old surgical-guide artifacts.

### 13.7 Planning kernel behavior

plans/core.py:optimal_plan has three broad stages:

1. initialize candidate trajectories and a distance map;
2. iteratively select trajectories and place seeds until the target DVH rate or a 100-iteration limit;
3. refine/replan, then remove/add seeds sequentially for safety and fine tuning.

The algorithm stops when it reaches its target, reaches an iteration cap, or stops improving. It transforms seed positions and directions from voxel coordinates into world coordinates and uses DoseImageContext caching. optimal_plan_rf delegates to hierarchical RF planning; the pipeline still applies its safety filters before and after the model decision.

### 13.8 Dose calculation step

dose_calc requires seed_plan and dose_distribution. It resamples the planning-grid dose back to the original CT grid using linear SimpleITK resampling and stores the planning/CT-grid aliases plus dose metadata.

The current data structure includes a field named dose_distribution_gy for compatibility, but it also stores dose_units as normalized_model_output and a dose_scale_gy value. Consumers must read the explicit unit and scale metadata; the field name alone is not sufficient evidence that the array is already in absolute Gy.

### 13.9 Dose evaluation step

dose_eval works on planning-grid masks and planning-grid dose. DoseEvaluationTool computes target and OAR metrics including:

- V100;
- V150;
- V200;
- D90;
- D95;
- D99;
- absolute target/OAR statistics;
- DVH data;
- plan score.

Unknown OAR labels receive OAR_N fallback names so an evaluation can remain structurally complete. A plan score can be None and the user-facing display can be UNVERIFIED; absence of a score is not silently converted to zero quality.

### 13.10 Full pipeline transaction shape

_run_full_pipeline shares one body mask across geometry stages, runs the five substeps in order, emits progress callbacks and timing, marks dose_ready when dose calculation completes, and returns seed plan, dose, metrics, total seeds, and substep timings.

The pipeline is not one all-or-nothing GPU transaction. Intermediate state is available to the live agent, while publish and persistence boundaries decide which result is durable and visible. A failure in a later stage must not be interpreted as proof that earlier derived artifacts are still valid after an input mutation.

## 14. Dose calculation, dose evaluation, and recomputation

### 14.1 The supported dose engine

tool_factory/dose_engine provides a thin DoseEngineTool wrapper. The only supported engine is the CNN DoseUNet path. The analytical Gaussian engine has been removed from the current implementation. A request for engine=cnn is forwarded to CNNDoseEngineTool; unsupported engines fail explicitly.

Inputs include the CT dose image, seed geometry, inference size, normalization range/scale, and seed information. The tool result preserves model and dose metadata for later evaluation and display.

### 14.2 Active-plan recomputation

tool_factory/dose_recompute.py defines CurrentPlanDoseRecomputeTool with the conversational name dose_recompute. It:

1. resolves the active persisted planning identity through web.planning_runs;
2. lazily restores CT runtime objects if only a path was hydrated;
3. refuses a non-active planning_id;
4. requires current seeds and needles;
5. calls the shared manual-AI dose computation path;
6. writes all required dose aliases, DVH, and metric fields;
7. publishes only after the required aliases are coherent;
8. updates viewer/session state;
9. marks the report and guide stale until regenerated.

This tool does not rerun CTV or OAR segmentation and does not choose needles. It recomputes dose for the geometry currently authoritative in the active plan.

### 14.3 Metrics and display semantics

DoseEvaluationTool validates array shapes and maps OAR IDs to names. It uses the comprehensive evaluator to produce DVH and plan metrics. The Viewer and planning APIs can request dose overlays, contours, isosurfaces, and seed geometry, but the display layer must consume the current active planning context and explicit dose-unit metadata.

When dose or geometry changes, the following artifacts must be considered stale until their own generation path runs again:

- DVH;
- report;
- quality score;
- surgical guide;
- any export that embeds the old plan.

### 14.4 Dose-unit caution

The current implementation contains compatibility naming that can be misleading if read without its metadata. The safe interpretation is:

1. identify the dose array's grid;
2. read dose_units;
3. read dose_scale_gy;
4. check the model normalization/calibration metadata;
5. only then display absolute dose or compute a clinical threshold.

Do not infer absolute Gy from the suffix of a single field name.

## 15. Viewer, manual editing, and surgical guides

### 15.1 Viewer data flow

The Viewer endpoints support loading, slicing, overlays, HU/threshold operations, 3D data, label volumes, generic masks, organs, skin surfaces, and 3D seeds. The browser uses Plotly and Three.js for plotting and 3D rendering.

The server performs bounds and geometry checks before returning viewer data. It can serve the original CT reference grid, planning-derived arrays, and resampled presentation data as distinct representations. A label-volume route is not permission to assume that every label shares the same grid as the CT; the server-side alignment and metadata are the authority.

### 15.2 Manual planning

Manual planning endpoints update geometry, delete or restore needles, update seeds, restore an algorithm plan, and expose manual dose recomputation. Mutation paths are lease- and owner-protected. They operate on the current active plan and should fork or invalidate the planning history according to the planning-run lifecycle.

A geometry change is semantically stronger than a cosmetic UI change. It invalidates dose-dependent and guide-dependent artifacts because a previously calculated result no longer describes the current needle/seed geometry.

### 15.3 Surgical-guide lifecycle

Surgical-guide generation is a separate capability with list, mesh, generate, export, and validate routes. It is tied to an active planning identity. When an algorithm plan is regenerated or manual geometry changes, prior guide versions are invalidated.

The guide flow is:

    active valid plan
        -> generate guide geometry
        -> store guide version and planning identity
        -> validate against current plan/obstacles
        -> expose mesh
        -> export only the validated/current guide

A planning authorization grant does not automatically imply a guide authorization grant. The user must explicitly ask for the guide or use the canonical compound plan-plus-guide action.

### 15.4 Screenshots and visual evidence

Viewer screenshots are stored and served through session-scoped endpoints. Internal visual-analysis child turns can inspect a screenshot or current UI state using their read-only tool allow-list. Their evidence is returned to the parent turn without being persisted as an ordinary user-visible message unless the parent chooses to summarize it.

## 16. Background chat tasks and streaming

### 16.1 ChatTask model

web/chat_tasks.py defines a background ChatTask with:

- task ID;
- request ID;
- user/message identity;
- parent message IDs;
- internal-followup flag;
- response language;
- status;
- response and streamed response;
- execution steps;
- persistence status;
- result-committed marker.

The module's contract is explicit: a browser disconnect must not cancel a clinical workflow. Only an explicit Stop/cancel operation cancels the task.

### 16.2 Task manager ownership

ChatTaskManager keys active, live, and latest task lookup by (user_id, session_id). It rejects a second concurrent case turn when the case already has a live turn. A duplicate request ID returns the existing task instead of starting a second clinical operation.

Visual child tasks can be linked only when the parent request, user message, and assistant message IDs match exactly. An orphan visual child is rejected. A new user turn can supersede a live internal child, and the predecessor worker is awaited before a new turn touches AgentMemory.

### 16.3 Worker execution

The worker:

1. creates a Flask application context;
2. does not rely on the browser cookie session inside the worker;
3. obtains or hydrates the case agent through an optional supplier;
4. records UI and active-turn context;
5. calls agent.chat_with_stream;
6. publishes replayable task events;
7. commits the transcript and lightweight result before declaring the task done;
8. allows heavy clinical array persistence to finish independently;
9. cleans stream state and restores hidden-child memory.

The final done event is intentionally held until the transcript and lightweight result commit succeeds. This prevents the browser from seeing an apparently complete turn that was never durably recorded.

### 16.4 Replayable SSE

ChatTask.publish assigns sequence numbers and stores replayable events. iter_events can replay from a requested sequence and follow live events. The stream sends a heartbeat approximately every 10 seconds.

Typical event types include:

- step;
- text_chunk;
- final_text_chunk;
- response;
- done;
- error;
- progress metadata emitted by tools.

Internal workspace-checkpoint UI steps are suppressed from the normal user-facing stream. Tool callbacks can update progress without exposing internal persistence mechanics as clinical content.

### 16.5 Stop, cancel, and deletion

cancel marks the task terminal immediately and publishes a cancelled done event, then asks the agent to stop. Downstream work observes the cancellation event. A running GPU inference may still need to unwind naturally.

Case deletion and trash transitions wait for the worker to unwind before moving or purging the workspace. This avoids deleting the storage root while a worker is still preparing a snapshot or writing an artifact.

## 17. Tool registry and trusted-local developer capabilities

### 17.1 Tool contract

tool_factory defines ToolResult with:

- success;
- data;
- message;
- display;
- metadata;
- error;
- execution_time.

BaseTool requires a name, description, schema, and execute implementation. BaseTool.execute validates required fields, tracks execution time, catches exceptions, and turns them into a failed ToolResult. is_available is dynamic, so a registered tool can be omitted from the provider schema or return an explicit unavailable result.

ToolRegistry supports registration, unregistration, lookup, availability, execution, and OpenAI-compatible schema generation. Provider schema generation removes x-server-injected fields. The registry's schema cache is keyed by tool availability and schema state.

### 17.2 Explicit trusted-local gates

The following capabilities are disabled unless the corresponding explicit environment gate is enabled:

| Capability | Gate |
|---|---|
| Python code execution | BRACHYBOT_ENABLE_CODE_EXECUTOR=1 |
| Shell execution | BRACHYBOT_ENABLE_SHELL_EXECUTOR=1 |
| Dynamic tool creation | BRACHYBOT_ENABLE_TOOL_CREATOR=1 |
| Environment/package management | BRACHYBOT_ENABLE_ENV_MANAGER=1 |
| LLM-generated tool code writer | BRACHYBOT_ENABLE_TOOL_CODE_WRITER=1 |

The code executor and shell executor return a direct trusted-local-environment error when disabled. Shell execution also applies blocked-command checks and allowed patterns. Environment management uses a package allow-list. Tool creator and tool-code-writer paths constrain imports through explicit allow-list settings.

This is a capability boundary, not merely a UI toggle. Registering a tool class does not make the capability available when its gate is off.

### 17.3 Filesystem and document scope

filesystem_browser and doc_reader use configured roots. The safe default is case/workspace-scoped browsing. Global filesystem browsing requires its own explicit enable flag and configured roots. CT, MR, and US data roots are separate configuration concepts.

The external-project policy in the LLM runtime is also separate from local filesystem access. When the user asks about an external project, the runtime permits web_search, web_fetch, and web_access but does not silently browse local BrachyBot files unless the user explicitly asks for that.

### 17.4 Safe extension workflow

A safe new tool should:

1. implement BaseTool and a precise schema;
2. mark server-injected inputs explicitly;
3. define is_available;
4. add an execution authorization classification;
5. add a turn-policy allow-list entry;
6. validate ownership and active-plan identity;
7. preserve provenance and unit metadata;
8. add persistence and cancellation behavior;
9. add focused tests;
10. verify that the provider-visible schema does not expose internal-only fields.

## 18. Configuration and environment contracts

The following settings are visible in the current source. Names are listed without values.

### 18.1 Server, identity, and workspace

| Setting | Current role |
|---|---|
| BRACHYBOT_RUNTIME_DIR | Relocates SQLite, snapshots, sidecars, artifacts, and runtime secrets |
| BRACHYBOT_SECRET_KEY | Explicit Flask session secret |
| BRACHYBOT_COOKIE_SECURE | Enables Secure session cookies when true-like |
| ALLOWED_ORIGINS | Explicit CORS origin list |
| BRACHYBOT_TRUST_NETWORK | Enables trusted private-network behavior in server support code |
| BRACHYBOT_ALLOW_INSECURE_REMOTE | Allows non-loopback binding without the normal API-key requirement for a trusted local network |
| BRACHYBOT_API_KEY | Remote bind and deployment API-key protection |
| BRACHYBOT_REQUIRE_API_KEY | Additional API-key requirement used by UI annotation paths |
| BRACHYBOT_WORKSPACE_MAINTENANCE_SECONDS | Maintenance interval, clamped to a minimum of 300 seconds |
| BRACHYBOT_SERVER_URL | Server URL used by report auto-fill integration |
| BRACHYBOT_FORCE_SHUTDOWN_ON_SECOND_SIGNAL | Explicit force-shutdown behavior after a second signal |

A remote bind is not automatically safe just because the process starts. web/server.py checks the bind and API-key/insecure-remote settings. The runtime should be treated as a trusted deployment only when the network, API key, cookie, and CORS settings agree.

### 18.2 LLM providers

The current provider environment families include:

- ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, and ANTHROPIC_MODEL;
- OPENAI_API_KEY and OPENAI_MODEL;
- DEEPSEEK_API_KEY and DEEPSEEK_MODEL;
- QWEN_API_KEY or DASHSCOPE_API_KEY and QWEN_MODEL;
- KIMI_API_KEY or MOONSHOT_API_KEY and KIMI_MODEL;
- GLM_API_KEY or ZHIPU_API_KEY and GLM_MODEL;
- GEMINI_API_KEY or GOOGLE_API_KEY and GEMINI_MODEL;
- GROQ_API_KEY and GROQ_MODEL;
- GROK_API_KEY or XAI_API_KEY and GROK_MODEL;
- MINIMAX_API_KEY and MINIMAX_MODEL;
- TENCENT_API_KEY and TENCENT_MODEL;
- OPENROUTER_API_KEY and OPENROUTER_MODEL;
- MIMO_API_KEY and the Mimo model settings;
- OLLAMA-related local provider settings;
- LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL for a generic compatible endpoint.

Provider discovery and provider runtime classes both read environment variables. A model being named in a comment or configuration file does not prove that the active process selected it.

### 18.3 Segmentation and model runtimes

Current segmentation-related settings include:

- BIOMEDPARSE_ROOT or BIOMEDPARSE_V2_ROOT;
- BIOMEDPARSE_V2_CHECKPOINT;
- BIOMEDPARSE_V2_TEXT_ASSETS;
- BIOMEDPARSE_V2_PYTHON;
- BIOMEDPARSE_V2_PROBE_TIMEOUT;
- BIOMEDPARSE_V2_INFERENCE_TIMEOUT;
- BRACHYBOT_TOTALSEG_TIMEOUT_SEC;
- BRACHYBOT_TOTALSEG_QUEUE_TIMEOUT_SEC;
- BRACHYBOT_NNUNET_TIMEOUT_SEC.

The BiomedParse adapter may use a sibling checkout or an explicitly configured root. It reports missing root/checkpoint/text assets as runtime diagnostics rather than silently falling back to an unrelated anatomical model.

### 18.4 Developer and filesystem controls

Current explicit capability/root settings include:

- BRACHYBOT_ENABLE_CODE_EXECUTOR;
- BRACHYBOT_ENABLE_SHELL_EXECUTOR;
- BRACHYBOT_ENABLE_TOOL_CREATOR;
- BRACHYBOT_ENABLE_ENV_MANAGER;
- BRACHYBOT_ENABLE_TOOL_CODE_WRITER;
- BRACHYBOT_DYNAMIC_TOOL_IMPORT_ALLOWLIST;
- BRACHYBOT_TOOL_IMPORT_ALLOWLIST;
- BRACHYBOT_ENV_PACKAGE_ALLOWLIST;
- BRACHYBOT_FILESYSTEM_ROOTS;
- BRACHYBOT_CT_DATA_ROOTS;
- BRACHYBOT_MR_DATA_ROOTS;
- BRACHYBOT_US_DATA_ROOTS;
- BRACHYBOT_ENABLE_FILESYSTEM_BROWSER_GLOBAL;
- BRACHYBOT_MAX_DOCUMENT_BYTES;
- BRACHYBOT_AUDIT_DIR.

These settings should be configured as narrowly as possible. Do not put secrets, subscription URLs, or access tokens into this document or into persistent review artifacts.

## 19. Testing and current operational evidence

### 19.1 Test collection

Using the project environment, the current test collection command was:

    /home/lht/.conda/envs/brachytherapy/bin/python -m pytest --collect-only -q

It collected 734 tests with warnings only. Collection is not execution and should not be reported as a passing test suite.

### 19.2 Focused verification

The following current-source test group passed during this inspection:

    /home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q \
      tests/test_semantic_execution_authorization.py \
      tests/test_runtime_contracts.py \
      tests/test_workspace_store.py \
      tests/test_biomedparse_v2.py

Result: 97 passed, 3 warnings in 5.61 seconds.

The focused group covers the execution-authorization boundary, runtime contracts, workspace persistence behavior, and BiomedParse adapter contracts. It does not prove that every Viewer, frontend, export, model, or deployment path passes end to end.

### 19.3 Observed running process

The live process observed during this inspection was:

- PID 1297468;
- Python 3.12 in the brachytherapy conda environment;
- working directory /home/lht/snap/brachyplan/BrachyBot;
- server bound to 0.0.0.0:8080;
- log path .runtime/server.log;
- log-reported provider/model family: mimo-v2.5;
- log-reported registered tools: 37;
- two RTX 3090 devices visible.

The process environment contained an Anthropic API-key marker and model marker, plus remote-trust settings. Values were not printed or persisted. It did not contain the developer capability gates, BIOMEDPARSE_ROOT, or BIOMEDPARSE_V2_CHECKPOINT at observation time. The checkpoint file was present at:

    /home/lht/snap/brachyplan/BrachyBot/models/ctv/biomedparse_v2/biomedparse_v2.ckpt

The presence of that file is therefore recorded separately from runtime activation.

### 19.4 Observed workspace state

The runtime snapshot observed during inspection was approximately:

- .runtime around 5.1 GB;
- SQLite database around 9.2 MB;
- 22 users;
- 28 active cases;
- all 28 cases reporting recovery-ready status;
- 3 workspace leases;
- 22,204 audit events;
- 0 review comments.

These values are operational observations that will change as users work. They are not schema limits or acceptance criteria.

### 19.5 Recommended verification order after a code change

For a change that affects clinical or persistence behavior, use this order:

1. inspect git status and the exact diff;
2. run py_compile or the smallest import check for touched Python modules;
3. run git diff --check;
4. run focused tests for the changed contract;
5. run route or Flask smoke tests when an API boundary changed;
6. run an agent/task/workspace transition test when lifecycle behavior changed;
7. only then consider a broader test selection;
8. verify the live process configuration and restart state separately from source validation.

The sparse server environment may not have every developer CLI such as rg, node, or a globally installed pytest. Prefer the project interpreter and one-purpose checks.

## 20. Change guide and source index

### 20.1 End-to-end trace for a user turn

For debugging a user-visible clinical action, trace this path:

    HTTP request
        -> authenticated user and selected case
        -> ChatTaskManager ownership and duplicate check
        -> BrachyAgent.chat or chat_with_stream
        -> LocalTurnPolicy
        -> semantic LLM resolution when required
        -> TurnExecutionAuthorization
        -> ToolCallGateway schema validation
        -> BrachyAgent live-memory injection
        -> clinical tool
        -> AgentMemory and RunLedger result recording
        -> WorkspaceStore snapshot patch/array persistence
        -> ChatTask transcript commit
        -> replayable SSE response
        -> browser Viewer/report/workspace refresh

A failure should be classified by layer. For example:

| Symptom | First source area to inspect |
|---|---|
| User can see a case that is not theirs | web/auth.py and web/server.py request context |
| Refresh loses data | web/workspace_store.py hydration and snapshot patch logic |
| Browser disconnect cancels planning | web/chat_tasks.py cancellation/worker paths |
| Planning runs in the wrong order | agent_runtime/turn_policy.py and execution_authorization.py |
| LLM injects arbitrary CT/masks | AgenticSys.py live-memory injection |
| Uploaded mask is shifted | segmentation_alignment and CTV/OAR tool adapters |
| Old plan remains visible after edit | web/planning_runs.py invalidation/activation |
| Dose values have unclear units | planning_pipeline.py and dose_engine/dose_recompute metadata |
| Unsafe needle reaches Viewer/export | trajectory safety filters and manual-planning validation |
| Tool appears in UI but cannot run | BaseTool.is_available and developer gates |
| Guide exists for old geometry | planning-run artifact invalidation and surgical-guide routes |

### 20.2 Source index

The following files are the primary current implementation anchors:

| Concern | File and key area |
|---|---|
| App creation and agent cache | web/server.py, create_app around line 185; get_agent around line 328 |
| Server-level compatibility APIs | web/server.py, upload/import/viewer/report/reset and chat/task handlers |
| Authentication and CSRF | web/auth.py, configure_auth and before-request protection |
| Workspace database/store | web/workspace_store.py, WorkspaceStore around line 1230 |
| Workspace schema | web/workspace_store.py, database initialization around line 1302 |
| Snapshot merge | web/workspace_store.py, save_snapshot_patch around line 1539 |
| Agent snapshot | web/workspace_store.py, snapshot_agent around line 1660 |
| Agent hydration | web/workspace_store.py, hydrate_agent around line 2124 |
| Lease/editability | web/workspace_store.py, acquire_lease/assert_editable around lines 2698 and 2741 |
| Background tasks | web/chat_tasks.py, ChatTask and ChatTaskManager |
| Agent composition | AgenticSys.py, BrachyAgent around line 50 and initialization around line 84 |
| Provider detection | AgenticSys.py, provider auto-detection around lines 254 onward |
| Tool registration | AgenticSys.py, _load_tools around line 606 |
| Planning request boundary | AgenticSys.py, _planning_requested around lines 843 onward |
| Live tool execution | AgenticSys.py, _execute_tool_with_memory around line 1269 |
| Memory and registry | agent_runtime/core.py, AgentMemory and ToolRegistry |
| Run and context contracts | agent_runtime/contracts.py, AgentRun, RunLedger, ContextPackBuilder, ToolCallGateway |
| Turn authorization | agent_runtime/execution_authorization.py |
| Local policy | agent_runtime/turn_policy.py, classify_local_turn around line 736 |
| Streaming runtime | agent_runtime/llm_runtime.py, stream execution around line 1708 |
| Chat workflow | agent_runtime/chat_workflows.py, chat around line 1259 and chat_with_stream around line 1853 |
| Planning history | web/planning_runs.py |
| Clinical pipeline | tool_factory/seed_plan/planning_pipeline.py, PlanningPipelineTool around line 1434 |
| Planning kernels | plans/core.py, init_plan around line 28 and optimal_plan around line 117 |
| CNN dose wrapper | tool_factory/dose_engine/__init__.py |
| Active dose recompute | tool_factory/dose_recompute.py |
| Dose metrics | tool_factory/dose_eval/__init__.py |
| CTV models and alignment | tool_factory/CTV_seg/__init__.py and related adapters |
| OAR models and alignment | tool_factory/OAR_seg/__init__.py and related adapters |
| Tool base contract | tool_factory/__init__.py |
| Trusted developer tools | tool_factory/code_executor, shell_executor, tool_creator, env_manager; brain/core/tool_code_writer.py |
| Browser entry | web/app/index.html and web/app/static/js |
| Surgical guide routes | web/routes/surgical_guide_routes.py |
| Viewer routes | web/routes/viewer_routes.py |
| Planning routes | web/routes/planning_routes.py |
| Workspace/session routes | web/routes/session_routes.py |
| Data/export routes | web/routes/data_routes.py |

### 20.3 Practical implementation rules

When changing this project:

- Keep user/case ownership checks at the route and store boundaries; do not rely on the LLM to preserve scope.
- Keep active-plan identity explicit whenever a result is created or consumed.
- Treat CT geometry, label geometry, planning-grid geometry, and display geometry as distinct contracts.
- Store arrays in sidecars and JSON metadata in snapshots; do not put multi-gigabyte arrays into a normal chat or report patch.
- Make clinical mutation idempotency and cancellation behavior explicit.
- Add a turn-policy grant for a new mutating tool; registry registration alone is insufficient.
- Mark dose, DVH, report, quality, and guide artifacts stale after geometry or target/OAR changes.
- Preserve provenance, units, scales, source grids, and model diagnostics in tool results.
- Do not enable shell, code execution, dynamic tool creation, environment management, or tool-code writing implicitly.
- Do not claim a model is deployed from a checkpoint file alone; verify runtime variables, process state, restart state, and an inference smoke test.
- Use focused tests and source-level evidence before broad runtime claims.

### 20.4 Explicit non-claims

This document does not claim:

- that the complete 734-test suite passed;
- that every current route is a stable external API;
- that BiomedParse is active in the observed server;
- that every dose field named with a Gy suffix is already in absolute Gy;
- that a disconnected browser cancels a task;
- that an LLM-selected tool call bypasses deterministic authorization;
- that an old or backup file represents the current implementation;
- that runtime counts are fixed limits.

The purpose of this guide is to make the current implementation navigable for maintenance, debugging, and safe extension. When this document and the current source disagree, update the document after confirming the source and tests.
