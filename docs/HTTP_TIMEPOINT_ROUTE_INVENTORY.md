# Registered HTTP timepoint scope inventory

Snapshot: 2026-10-13, local candidate `timepoints-implementation-20261010`.
Factory: real `web.server.create_app`, maintenance disabled, temporary runtime.
No production process, database, model, or clinical case is used.

## Result and limits

**157 registered rules, 156 distinct endpoints, 167 explicit method/rule pairs.**
`api_export_dicom_rt` has two URLs. HEAD and OPTIONS are Flask transport additions
and excluded from the explicit-method count; they remain on the real URL map.
Every registered rule, including static assets, is listed below. No route prefix
is used as an automatic approval of future endpoints.

This inventory checks classification, request ownership capture, selected
negative controls, and retained callback ownership. It does **not** establish
numerical dose/segmentation/planning correctness, clinical safety, image geometry,
GPU functionality, or completion of the timepoint product. The originally
discovered G1–G3 gaps are now repaired; their negative assertions must pass.

## Classification and exception allowlist

| Classification | Rules | Meaning / path |
| --- | ---: | --- |
| account_control | 16 | Auth, Session lifecycle, or owned bundle import; central hook bypass, route owns account/Session. |
| clinical_http | 93 | Central captured triple; scoped Agent/store/UI bucket or progress owner as needed. |
| explicit_timepoint | 25 | Exact middleware exception sets; route checks owner + URL Session/timepoint itself. |
| scoped_export_job | 4 | Captured triple is checked against original job owner/Session/timepoint before status/cancel/download. |
| scoped_file | 3 | File URL Session and target membership are enforced; legacy unprefixed files belong only to the migrated default. |
| public_asset | 2 | Non-clinical HTML/static; central clinical hook skips non-API URLs. |
| shared_http | 11 | Shared conversation/control or new-Session client import; central binding exists but shared storage remains deliberate. |
| system_http | 3 | Process/device/model metadata; central hook may bind a selected Session, handler needs no clinical snapshot. |

The executable test freezes the exact endpoint names in each exception group
and the exact endpoint/URL/method/source-module rows. Changing a handler's
module, adding an alias/method/endpoint, or expanding the middleware exception
sets requires reviewing this inventory. Source line numbers below are navigation
anchors at this snapshot and are intentionally not asserted, so unrelated edits
do not invalidate the inventory.

`shared_http` is an explicit semantic exception, not a clinical exemption:
chat transcript, context accounting, abort/replay and one active conversation
are Session shared. Submission `api_chat` still captures a clinical target;
the worker executes against that target. Workspace audit and review comments
are Session records, leases lock the Session, and import-client creates a new
Session. The test does not imply that these shared endpoints offer per-timepoint
filtering. Bundle import is account owned and creates a new Session; it must
not project into the mounted target.

## Central request/runtime codepath

Actual before-request order: `web.auth._require_authenticated_api_user`,
`web.server.reject_unscoped_timepoint_execution`,
`_record_request_started_at`, `_restore_display_tokens_in_request`,
`_protect_live_workspace_lease`. Auth establishes the owner and CSRF boundary.
The inventory invokes the actual preprocess chain for every explicit method,
without invoking numerical route handlers.

`web/server.py:566`: the central hook calls `explicit_case_id` and
`explicit_timepoint_id`, validates the authenticated owner's Session/catalog,
and installs frozen `HttpTimepointBinding(owner_id, session_id, timepoint_id)`
on Flask `g`. Headers/query/JSON must agree. The selected Session cookie is
only a Session fallback; absent timepoint selects the owned migrated default.
For Session artifact/screenshot URLs, the URL Session is also passed into
`explicit_case_id`; conflicting header/query/body identities fail before file
serving. A captured target must be an active owned catalog entry.

`web/server.py:1061`: `get_agent` obtains the control Agent under
`bound_request(None)`, then constructs/reuses a request `ScopedHttpRuntime`.
`get_cached_agent` delegates to this scoped path when a binding exists;
`get_agent_for_owner` constructs a worker runtime under the captured binding.
`api_chat` instead obtains conversational control and builds its own submitted
scope. `web/timepoint_http.py:289` installs detached `ScopedChatRuntime` clinical
memory, an explicitly bound `ScopedWorkspaceStore`, a captured persistence
callback, and revision/operation context. Its checkpoint re-enters its own
binding; close commits only that runtime. The scoped facade's generic
`__getattr__` delegates methods it does not override: a central binding alone
does not prove a downstream file/job consumer is scoped.

`web/routes/planning_routes.py:1904`: `request_case_context` returns
`store.for_binding()`. Viewer/Manual/Monitor handlers use the supplied scoped
Agent, per-triple `bucket_key`, and/or that bound store. Progress endpoints
`api_tasks_list`, `api_task_status`, `api_tasks_stream` use
`task_workspace_owner` (`owner:session:timepoint`) and filter the manager;
the SSE generator retains that value. Actual progress endpoint tests exercise
these filters with a completed synthetic task.

`web/server.py:1338`: after-request checkpoint marks the scoped runtime dirty.
Streaming is wrapped by `scoped_iterator(original, binding)`; done/result/
complete checkpoints occur before acknowledgements, and exhaustion closes
the retained runtime. Non-stream completion closes that runtime directly.
Headers echo Session/timepoint; they are scope metadata, **not evidence that
a handler validated an artifact/job's target**.

Explicit route exceptions are the exact five sets in `timepoint_routes.py`,
`implant_routes.py`, `timepoint_image_routes.py`,
`guide_registration_routes.py`, and `intraoperative_routes.py` (25 endpoints).
Their decorators/handler resolve URL identities against header/query/body and
load/check the owner's target. Catalog list/create have Session scope only;
other operations carry a target URL. The tests exercise every exception's
actual wrapper with conflicting URL/header Session to reject before work.

## Retained asynchronous work

| Producer/callback | Retained ownership | Audit finding |
| --- | --- | --- |
| Chat worker / on_finish / response_factory / hydration progress | `web/chat_tasks.py:661` typed task scope; `scoped_callable(..., binding)`; worker at 1114 | Captured task owner/Session/timepoint; conversation stays shared. |
| Chat start / final checkpoint threads | `planning_routes.py:8590,2726` `scoped_callable`; task fields and scoped Agent | Captured binding, no cookie lookup in the detached callback. |
| Monitor/UI debounce and closed bridge | `planning_routes.py:3192,1046,1077` retains `store.for_binding()`, owner, Session in pending tuple; triple key | Timer need not inherit ContextVar because facade itself holds the binding. Test flushes retained tuple after entering another binding and checks only original target changes. |
| HTTP/SSE iteration and generator close | `server.py:1378`; `timepoint_http.scoped_iterator` binds each next/close | Test checks real factory after-request wrapper after switching binding, plus generator close and worker propagation. |
| Export worker | `export_service.py` captures job target/context, owner, and `scoped_callable(self._run)` | Producer retains original owner; repaired status/cancel/download consumers check the same triple. Numerical export is not exercised by this inventory. |
| Implant detector | `implant_routes.py:69-93` captures workspace instance and `(owner,session,identifier,request_id)` job key | No Flask binding needed: `ImplantWorkspace` carries the triple. Not a detected unbound callback. |
| Guide registration thread/process | `guide_registration.py:146-170` passes owner, Session, target, service, captured context/readset, payload | Publication/review uses captured target/readset. Child computation gets payload; owned publication stays in parent. |
| Timepoint hydration pool | `timepoint_hydration.py:47-99` closure retains raw store, snapshot, immutable execution context; cache includes owner/Session/timepoint/revisions | No mutable selected pointer; context currency is checked before acceptance. |
| Shared control Agent hydration/retry | `server.py:837-1026` captured owner/Session, generation guards | Session control/cache restoration; numerical target view is separately hydrated above. |
| Maintenance/archive/cache checkpoint | Factory maintenance disabled for this inventory; shared Session lifecycle callbacks use explicit owner/Session | Not timepoint computation; no production worker touched. |

No additional unbound clinical callback was established in this bounded pass.
The concrete gaps below are consumers of already captured requests, not a
claim that every possible transitive tool callback has been formally proved.

## Consumer gaps discovered and repaired

The paragraphs below retain the pre-fix reproduction, not current passing
behavior. `ScopedWorkspaceStore.session_artifact_path` now checks captured
owner/Session/timepoint membership, preserves traversal checks, and confines
unprefixed legacy files to the migrated default. The central hook reconciles
file URL Session with header/query/body. `ExportJobManager.get` checks the
captured triple before all consumers, including cancellation and downloads.
Generated artifact/download/signed screenshot URLs carry explicit scope for
anchors and image tags. The export browser captures an immutable scope for
catalog, polling, cancellation and file saving, and checks report ownership
at timepoint level before on-screen report serialization.

**G1, pre-fix reproduction: three file-serving endpoints lacked a target-membership guard.**
`download_case_artifact` -> `store.session_artifact_path`;
`api_serve_screenshot` and `api_serve_legacy_screenshot` -> same delegated raw
method. `WorkspaceStore.session_artifact_path` validates Session ownership and
path traversal, not timepoint membership. An A-owned `reports_tp_A/a.txt` or
`A_a.png` requested with Session S/timepoint B returns **200 and A bytes** while
the response header says B. The test writes only synthetic artifacts in its
temporary store. Cross-account protection still exists; this is a same-owner
cross-timepoint isolation failure, not evidence of cross-account disclosure.

**G2, pre-fix reproduction: four export job consumers ignored the submitted Session/timepoint.**
`api_export_status`, `api_cancel_export`, `api_download_export`,
`api_download_export_file` call `ExportJobManager.get(user_id, job_id)`;
`cancel` delegates to that lookup. The job already has Session/timepoint fields
but these are not compared with the captured request. A request bound to B can
read A job metadata, set A's `cancel_requested=True`, or download A's files.
The same issue holds after navigating to another owned Session. The reproducible
fixture inserts a synthetic completed job with tiny files; it does not run an
export or numerical producer. These are **not** accepted account-wide job
exceptions under the requested clinical route contract.

**G3, pre-fix reproduction: URL Session was not reconciled in two file routes.**
The central hook resolves headers/query/body/cookie only; the file handlers use
their URL Session without `explicit_case_id(session_id)`. With cookie/header
Session B and an A file URL, the request can return A bytes labeled as B.
Target-prefixed screenshot names alone do not constitute authorization. The
two Session-mismatch controls are now mandatory passing assertions, not xfails.

Executed repairs: reconcile URL Session before central binding; enforce target
provenance/membership for all three file readers, with unprefixed legacy files
limited to the actual migrated default; validate export job
owner/Session/timepoint at every consumer. The frontend retains the original
scope across polling/cancel/download and refuses report serialization from a
different mounted timepoint. Tests include authorized nondefault artifact and
signed screenshot links, so the negative guards do not merely deny all files.

The combined route/file/export/provider regression
`cumulative-route-file-export-provider-current-20261013.xml` reported
**443 passed**, 23.75 s. This targeted batch precedes the last provider
authorization/formatting refinements; the newer frozen full regression is a
separate result and must not be inferred from this batch.

## Validation

Run locally:

```powershell
& C:\Users\hunte\anaconda3\python.exe -E -m pytest -q tests/test_registered_route_timepoint_inventory.py -rx
```

Run only in the authorized isolated remote checkout:

```sh
cd /tmp/brachybot-timepoints-stage-20261010-E1Rvjz/product-browser-checkout
/home/lht/.conda/envs/brachytherapy/bin/python -m pytest -q tests/test_registered_route_timepoint_inventory.py -rx
```

Tests use fresh temporary account/Session/target stores, maintenance disabled,
synthetic signed-cookie identity, no Agent constructor/model/GPU inference.
Windows only: directory fsync is replaced in the fixture because native Windows
cannot open these directories with the Linux durability primitive. This gives
no Windows durability evidence. Linux uses the real directory fsync.
The original 13 strict expected failures are now ordinary mandatory tests.
Positive controls cover nondefault artifact links, actual durable screenshot
signatures and migrated-default legacy files. Local first inventory: 215
passed. Subsequent positives are included in the Linux combined route/file/
export/provider batch: 443 passed (23.75 s). These counts do not validate
clinical dose, printed-guide strength, or a deployed production website.

## Complete actual registered map

The following table is also the test's reviewable frozen manifest.
Columns are endpoint, exact rule, explicit methods, classification, unwrapped
handler codepath. Source locations are from the local snapshot.

| Endpoint | Rule | Methods | Classification | Codepath |
| --- | --- | --- | --- | --- |
| index | / | GET | public_asset | web/server.py:1578 |
| static | /<path:filename> | GET | public_asset | flask.app:713 |
| auth_login | /api/auth/login | POST | account_control | web/auth.py:282 |
| auth_logout | /api/auth/logout | POST | account_control | web/auth.py:308 |
| auth_me | /api/auth/me | GET | account_control | web/auth.py:320 |
| auth_change_password | /api/auth/password | POST | account_control | web/auth.py:336 |
| auth_register | /api/auth/register | POST | account_control | web/auth.py:250 |
| api_chat | /api/chat | POST | shared_http | web/routes/planning_routes.py:8053 |
| api_chat_abort | /api/chat/abort | POST | shared_http | web/routes/planning_routes.py:7580 |
| api_chat_context | /api/chat/context | GET | shared_http | web/routes/planning_routes.py:7978 |
| api_chat_context_compress | /api/chat/context/compress | POST | shared_http | web/routes/planning_routes.py:7993 |
| api_chat_task | /api/chat/task | GET | shared_http | web/routes/planning_routes.py:8654 |
| api_chat_task_stream | /api/chat/tasks/<task_id>/stream | GET | shared_http | web/routes/planning_routes.py:8697 |
| api_clear_all | /api/clear_all | POST | clinical_http | web/routes/planning_routes.py:7666 |
| api_config | /api/config | POST | clinical_http | web/routes/planning_routes.py:5203 |
| api_config_get | /api/config | GET | clinical_http | web/routes/planning_routes.py:5160 |
| api_ctv_models | /api/ctv/models | GET | system_http | web/routes/planning_routes.py:4227 |
| api_ctv_model_validation | /api/ctv/models/validation | POST | clinical_http | web/routes/planning_routes.py:4253 |
| api_data_catalog | /api/data/catalog | GET | clinical_http | web/routes/data_routes.py:205 |
| api_create_export | /api/data/exports | POST | clinical_http | web/routes/data_routes.py:573 |
| api_export_status | /api/data/exports/<job_id> | GET | scoped_export_job | web/routes/data_routes.py:603 |
| api_cancel_export | /api/data/exports/<job_id>/cancel | POST | scoped_export_job | web/routes/data_routes.py:618 |
| api_download_export | /api/data/exports/<job_id>/download | GET | scoped_export_job | web/routes/data_routes.py:628 |
| api_download_export_file | /api/data/exports/<job_id>/files/<path:relative_path> | GET | scoped_export_job | web/routes/data_routes.py:642 |
| api_generic_masks_classification | /api/data/generic-masks/classification | PATCH | clinical_http | web/routes/data_routes.py:399 |
| api_delete_data_object | /api/data/objects/<path:object_id> | DELETE | clinical_http | web/routes/data_routes.py:553 |
| api_batch_delete_data_objects | /api/data/objects/batch-delete | POST | clinical_http | web/routes/data_routes.py:449 |
| api_structure_classification | /api/data/structures/<path:object_id>/classification | PATCH | clinical_http | web/routes/data_routes.py:222 |
| api_structures_classification | /api/data/structures/classification | PATCH | clinical_http | web/routes/data_routes.py:265 |
| api_structures_traversability | /api/data/structures/traversability | PATCH | clinical_http | web/routes/data_routes.py:310 |
| api_device_status | /api/device/status | GET | system_http | web/routes/planning_routes.py:5185 |
| dose_component_recompute | /api/dose/recompute | POST | clinical_http | web/routes/dose_component_routes.py:101 |
| dose_component_view | /api/dose/view | GET | clinical_http | web/routes/dose_component_routes.py:143 |
| dose_component_volume | /api/dose/view-volume | GET | clinical_http | web/routes/dose_component_routes.py:159 |
| api_export_dicom_rt | /api/export/dicom | POST | clinical_http | web/routes/planning_routes.py:7687 |
| api_export_dicom_rt | /api/export/dicom_rt | POST | clinical_http | web/routes/planning_routes.py:7687 |
| api_export_report | /api/export/report | POST | clinical_http | web/routes/planning_routes.py:8809 |
| api_export_stl | /api/export/stl | POST | clinical_http | web/routes/planning_routes.py:7824 |
| api_header_info | /api/header/info | POST | clinical_http | web/server.py:2039 |
| api_healthz | /api/healthz | GET | system_http | web/routes/planning_routes.py:7252 |
| api_import_dicom_rt | /api/import/dicom_rt | GET,POST | clinical_http | web/server.py:1731 |
| api_manual_planning_delete_needle | /api/manual_planning/delete_needle | POST | clinical_http | web/routes/planning_routes.py:6619 |
| api_manual_planning_restore_algorithm_plan | /api/manual_planning/restore_algorithm_plan | POST | clinical_http | web/routes/planning_routes.py:3664 |
| api_manual_planning_restore_needle | /api/manual_planning/restore_needle | POST | clinical_http | web/routes/planning_routes.py:7018 |
| api_manual_planning_update | /api/manual_planning/update | POST | clinical_http | web/routes/planning_routes.py:6051 |
| api_manual_planning_update_geometry | /api/manual_planning/update_geometry | POST | clinical_http | web/routes/planning_routes.py:6348 |
| api_manual_planning_update_seeds | /api/manual_planning/update_seeds | POST | clinical_http | web/routes/planning_routes.py:6775 |
| api_intraoperative_plan | /api/plan/intraoperative | POST | clinical_http | web/routes/planning_routes.py:7495 |
| api_preoperative_plan | /api/plan/preoperative | POST | clinical_http | web/routes/planning_routes.py:7388 |
| api_planning_clear | /api/planning/clear | POST | clinical_http | web/routes/planning_routes.py:3276 |
| api_planning_config | /api/planning/config | GET | clinical_http | web/routes/planning_routes.py:4462 |
| api_planning_distance_annotations | /api/planning/distance-annotations | GET | clinical_http | web/routes/viewer_routes.py:2842 |
| api_planning_dose_contour_slice | /api/planning/dose_contour_slice | POST | clinical_http | web/routes/planning_routes.py:4988 |
| api_planning_dose_isosurface | /api/planning/dose_isosurface | POST | clinical_http | web/routes/planning_routes.py:4534 |
| api_planning_dose_overlay | /api/planning/dose_overlay | GET | clinical_http | web/routes/planning_routes.py:4803 |
| api_planning_dose_overlay_slice | /api/planning/dose_overlay_slice | POST | clinical_http | web/routes/planning_routes.py:4928 |
| api_planning_dose_overlay_volume | /api/planning/dose_overlay_volume | GET | clinical_http | web/routes/planning_routes.py:4863 |
| api_planning_results | /api/planning/results | GET | clinical_http | web/routes/planning_routes.py:3293 |
| api_planning_run_step | /api/planning/run_step | POST | clinical_http | web/routes/planning_routes.py:4289 |
| api_planning_runs | /api/planning/runs | GET | clinical_http | web/routes/planning_routes.py:3565 |
| api_activate_planning_run | /api/planning/runs/<planning_id>/activate | POST | clinical_http | web/routes/planning_routes.py:3630 |
| api_planning_seeds_3d | /api/planning/seeds_3d | GET | clinical_http | web/routes/viewer_routes.py:2864 |
| api_planning_show_step | /api/planning/show_step | POST | clinical_http | web/routes/planning_routes.py:3769 |
| api_structure_analysis | /api/planning/structure-analysis | GET | clinical_http | web/routes/planning_routes.py:3533 |
| api_readiness | /api/readiness | GET,POST | clinical_http | web/routes/planning_routes.py:6041 |
| api_report_auto_fill | /api/report/auto-fill | POST | clinical_http | web/server.py:2225 |
| api_reset | /api/reset | POST | clinical_http | web/server.py:2533 |
| api_screenshot | /api/screenshot | POST | clinical_http | web/routes/planning_routes.py:8986 |
| api_screenshot_annotation | /api/screenshot/annotation | POST | clinical_http | web/routes/planning_routes.py:9290 |
| api_serve_legacy_screenshot | /api/screenshots/<filename> | GET | scoped_file | web/routes/planning_routes.py:9516 |
| api_segmentation | /api/segmentation | POST | clinical_http | web/routes/planning_routes.py:3825 |
| create_case_session | /api/sessions | POST | account_control | web/routes/session_routes.py:130 |
| list_case_sessions | /api/sessions | GET | account_control | web/routes/session_routes.py:98 |
| rename_case_session | /api/sessions/<session_id> | PATCH | account_control | web/routes/session_routes.py:175 |
| trash_case_session | /api/sessions/<session_id> | DELETE | account_control | web/routes/session_routes.py:277 |
| activate_archived_session | /api/sessions/<session_id>/activate | POST | account_control | web/routes/session_routes.py:218 |
| archive_case_session | /api/sessions/<session_id>/archive | POST | account_control | web/routes/session_routes.py:244 |
| download_case_artifact | /api/sessions/<session_id>/artifacts/<path:artifact_path> | GET | scoped_file | web/routes/session_routes.py:353 |
| purge_case_session | /api/sessions/<session_id>/purge | DELETE | account_control | web/routes/session_routes.py:329 |
| restore_case_session | /api/sessions/<session_id>/restore | POST | account_control | web/routes/session_routes.py:317 |
| api_serve_screenshot | /api/sessions/<session_id>/screenshots/<filename> | GET | scoped_file | web/routes/planning_routes.py:9492 |
| select_case_session | /api/sessions/<session_id>/select | POST | account_control | web/routes/session_routes.py:191 |
| create_timepoint | /api/sessions/<session_id>/timepoints | POST | explicit_timepoint | web/routes/timepoint_routes.py:87 |
| list_timepoints | /api/sessions/<session_id>/timepoints | GET | explicit_timepoint | web/routes/timepoint_routes.py:79 |
| delete_timepoint | /api/sessions/<session_id>/timepoints/<identifier> | DELETE | explicit_timepoint | web/routes/timepoint_routes.py:116 |
| update_timepoint | /api/sessions/<session_id>/timepoints/<identifier> | PATCH | explicit_timepoint | web/routes/timepoint_routes.py:99 |
| timepoint_delete_impact | /api/sessions/<session_id>/timepoints/<identifier>/delete-impact | GET | explicit_timepoint | web/routes/timepoint_routes.py:111 |
| guide_registration_inventory | /api/sessions/<session_id>/timepoints/<identifier>/guide-registration | GET | explicit_timepoint | web/routes/guide_registration_routes.py:71 |
| guide_registration_start | /api/sessions/<session_id>/timepoints/<identifier>/guide-registration/jobs | POST | explicit_timepoint | web/routes/guide_registration_routes.py:96 |
| guide_registration_job | /api/sessions/<session_id>/timepoints/<identifier>/guide-registration/jobs/<job_id> | GET | explicit_timepoint | web/routes/guide_registration_routes.py:101 |
| guide_registration_cancel | /api/sessions/<session_id>/timepoints/<identifier>/guide-registration/jobs/<job_id>/cancel | POST | explicit_timepoint | web/routes/guide_registration_routes.py:106 |
| guide_registration_overlay | /api/sessions/<session_id>/timepoints/<identifier>/guide-registration/placements/<placement_id>/overlay | GET | explicit_timepoint | web/routes/guide_registration_routes.py:111 |
| guide_registration_review | /api/sessions/<session_id>/timepoints/<identifier>/guide-registration/placements/<placement_id>/review | POST | explicit_timepoint | web/routes/guide_registration_routes.py:122 |
| timepoint_images | /api/sessions/<session_id>/timepoints/<identifier>/images | GET,POST | explicit_timepoint | web/routes/timepoint_image_routes.py:42 |
| timepoint_image_update | /api/sessions/<session_id>/timepoints/<identifier>/images/<image_id> | DELETE,PATCH | explicit_timepoint | web/routes/timepoint_image_routes.py:80 |
| timepoint_image_source | /api/sessions/<session_id>/timepoints/<identifier>/images/<image_id>/<kind> | GET | explicit_timepoint | web/routes/timepoint_image_routes.py:98 |
| implant_view | /api/sessions/<session_id>/timepoints/<identifier>/implants | GET | explicit_timepoint | web/routes/implant_routes.py:54 |
| implant_correct | /api/sessions/<session_id>/timepoints/<identifier>/implants/corrections | POST | explicit_timepoint | web/routes/implant_routes.py:109 |
| implant_detect | /api/sessions/<session_id>/timepoints/<identifier>/implants/detect | POST | explicit_timepoint | web/routes/implant_routes.py:59 |
| implant_source_profile | /api/sessions/<session_id>/timepoints/<identifier>/implants/dose-source | GET,POST | explicit_timepoint | web/routes/implant_routes.py:131 |
| implant_job | /api/sessions/<session_id>/timepoints/<identifier>/implants/jobs/<job_id> | GET | explicit_timepoint | web/routes/implant_routes.py:96 |
| implant_presentation | /api/sessions/<session_id>/timepoints/<identifier>/implants/presentation | PATCH | explicit_timepoint | web/routes/implant_routes.py:118 |
| implant_review | /api/sessions/<session_id>/timepoints/<identifier>/implants/review | POST | explicit_timepoint | web/routes/implant_routes.py:123 |
| intraoperative_settings | /api/sessions/<session_id>/timepoints/<identifier>/intraoperative-settings | GET,POST | explicit_timepoint | web/routes/intraoperative_routes.py:19 |
| restore_timepoint | /api/sessions/<session_id>/timepoints/<identifier>/restore | POST | explicit_timepoint | web/routes/timepoint_routes.py:124 |
| load_timepoint_workspace | /api/sessions/<session_id>/timepoints/<identifier>/workspace | GET | explicit_timepoint | web/routes/timepoint_routes.py:132 |
| save_timepoint_workspace | /api/sessions/<session_id>/timepoints/<identifier>/workspace | PATCH | explicit_timepoint | web/routes/timepoint_routes.py:137 |
| list_trashed_sessions | /api/sessions/trash | GET | account_control | web/routes/session_routes.py:308 |
| api_status | /api/status | GET | clinical_http | web/routes/planning_routes.py:7284 |
| api_surgical_guide_status | /api/surgical-guides | GET | clinical_http | web/routes/surgical_guide_routes.py:201 |
| api_surgical_guide_export | /api/surgical-guides/export | POST | clinical_http | web/routes/surgical_guide_routes.py:297 |
| api_surgical_guide_generate | /api/surgical-guides/generate | POST | clinical_http | web/routes/surgical_guide_routes.py:237 |
| api_surgical_guide_mesh | /api/surgical-guides/mesh | GET | clinical_http | web/routes/surgical_guide_routes.py:216 |
| api_surgical_guide_validate | /api/surgical-guides/validate | POST | clinical_http | web/routes/surgical_guide_routes.py:352 |
| api_tasks_list | /api/tasks | GET | clinical_http | web/routes/planning_routes.py:8799 |
| api_task_status | /api/tasks/<task_id> | GET | clinical_http | web/routes/planning_routes.py:8786 |
| api_tasks_stream | /api/tasks/stream | GET | clinical_http | web/routes/planning_routes.py:8738 |
| api_training_advice | /api/training/advice | GET,POST | clinical_http | web/routes/planning_routes.py:5964 |
| api_training_apply_candidate | /api/training/apply_candidate | POST | clinical_http | web/routes/planning_routes.py:3146 |
| api_training_edit | /api/training/edit | GET | clinical_http | web/routes/planning_routes.py:2919 |
| api_training_edit_preview | /api/training/edit_preview | POST | clinical_http | web/routes/planning_routes.py:3103 |
| api_training_restore_edit | /api/training/restore_edit | POST | clinical_http | web/routes/planning_routes.py:2955 |
| api_training_start | /api/training/start | POST | clinical_http | web/routes/planning_routes.py:5696 |
| api_training_status | /api/training/status | GET | clinical_http | web/routes/planning_routes.py:5788 |
| api_training_stop | /api/training/stop | POST | clinical_http | web/routes/planning_routes.py:5820 |
| api_training_timeline | /api/training/timeline | GET | clinical_http | web/routes/planning_routes.py:6001 |
| api_ui_capabilities | /api/ui/capabilities | GET | clinical_http | web/routes/planning_routes.py:5474 |
| api_ui_event | /api/ui/event | POST | clinical_http | web/routes/planning_routes.py:5545 |
| api_ui_manual | /api/ui/manual | GET | clinical_http | web/routes/planning_routes.py:5243 |
| api_ui_state | /api/ui/state | GET,POST | clinical_http | web/routes/planning_routes.py:5252 |
| api_upload | /api/upload | POST | clinical_http | web/server.py:1586 |
| api_viewer_3d | /api/viewer/3d | POST | clinical_http | web/routes/viewer_routes.py:2100 |
| api_viewer_3d_mask | /api/viewer/3d_mask | POST | clinical_http | web/routes/viewer_routes.py:2226 |
| api_viewer_3d_skin | /api/viewer/3d_skin | POST | clinical_http | web/routes/viewer_routes.py:2633 |
| api_viewer_control | /api/viewer/control | POST | clinical_http | web/routes/planning_routes.py:8896 |
| api_viewer_generic_mask_volume | /api/viewer/generic_mask_volume | GET | clinical_http | web/routes/viewer_routes.py:1538 |
| api_viewer_generic_masks | /api/viewer/generic_masks | GET | clinical_http | web/routes/viewer_routes.py:1513 |
| api_viewer_hu | /api/viewer/hu | POST | clinical_http | web/routes/viewer_routes.py:2016 |
| api_viewer_image | /api/viewer/image | GET | clinical_http | web/server.py:1788 |
| api_viewer_label_volume | /api/viewer/label_volume | GET | clinical_http | web/routes/viewer_routes.py:1339 |
| api_viewer_load | /api/viewer/load | POST | clinical_http | web/routes/viewer_routes.py:851 |
| api_viewer_organs | /api/viewer/organs | GET | clinical_http | web/routes/viewer_routes.py:1763 |
| api_viewer_overlay | /api/viewer/overlay | POST | clinical_http | web/routes/viewer_routes.py:1621 |
| api_viewer_skin_surface_volume | /api/viewer/skin_surface_volume | GET | clinical_http | web/routes/viewer_routes.py:2583 |
| api_viewer_slice | /api/viewer/slice | POST | clinical_http | web/routes/viewer_routes.py:1154 |
| api_viewer_threshold | /api/viewer/threshold | POST | clinical_http | web/routes/viewer_routes.py:1959 |
| api_viewer_volume | /api/viewer/volume | GET | clinical_http | web/routes/viewer_routes.py:1291 |
| upload_generated_case_artifact | /api/workspace/artifacts | POST | clinical_http | web/routes/session_routes.py:370 |
| workspace_audit_events | /api/workspace/audit | GET | shared_http | web/routes/session_routes.py:581 |
| checkpoint_workspace | /api/workspace/checkpoint | POST | clinical_http | web/routes/session_routes.py:526 |
| import_timepoint_bundle | /api/workspace/import-bundle | POST | account_control | web/routes/timepoint_bundle_routes.py:15 |
| import_legacy_client_workspace | /api/workspace/import-client | POST | shared_http | web/routes/session_routes.py:635 |
| workspace_lease | /api/workspace/lease | DELETE,POST | shared_http | web/routes/session_routes.py:554 |
| workspace_review_comments | /api/workspace/review/comments | GET,POST | shared_http | web/routes/session_routes.py:595 |
| update_workspace_review_comment | /api/workspace/review/comments/<int:comment_id> | PATCH | shared_http | web/routes/session_routes.py:615 |
| workspace_snapshot | /api/workspace/snapshot | GET | clinical_http | web/routes/session_routes.py:400 |
| save_workspace_state | /api/workspace/state | POST | clinical_http | web/routes/session_routes.py:423 |

