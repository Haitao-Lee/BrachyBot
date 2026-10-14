"""Actual factory route census and transport scope checks; no numerical inference.

The Markdown manifest is frozen review data, not a prefix-derived route list.
Consumer negatives are mandatory passing regressions after boundary repair.
"""
import inspect
import os
from io import BytesIO
from pathlib import Path
import re
import tempfile
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "HTTP_TIMEPOINT_ROUTE_INVENTORY.md"
EXCEPTIONS = {
    "public_asset": frozenset("index static".split()),
    "account_control": frozenset("auth_login auth_logout auth_me auth_change_password auth_register create_case_session list_case_sessions rename_case_session trash_case_session activate_archived_session archive_case_session purge_case_session restore_case_session select_case_session list_trashed_sessions import_timepoint_bundle".split()),
    "shared_http": frozenset("api_chat api_chat_abort api_chat_context api_chat_context_compress api_chat_task api_chat_task_stream workspace_audit_events workspace_lease workspace_review_comments update_workspace_review_comment import_legacy_client_workspace".split()),
    "system_http": frozenset("api_ctv_models api_device_status api_healthz".split()),
    "explicit_timepoint": frozenset("list_timepoints create_timepoint update_timepoint timepoint_delete_impact delete_timepoint restore_timepoint load_timepoint_workspace save_timepoint_workspace implant_view implant_detect implant_job implant_correct implant_presentation implant_source_profile implant_review timepoint_images timepoint_image_update timepoint_image_source guide_registration_inventory guide_registration_start guide_registration_job guide_registration_cancel guide_registration_overlay guide_registration_review intraoperative_settings".split()),
    "scoped_file": frozenset("download_case_artifact api_serve_screenshot api_serve_legacy_screenshot".split()),
    "scoped_export_job": frozenset("api_export_status api_cancel_export api_download_export api_download_export_file".split()),
}


def inventory_rows():
    rows = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 5 and cells[1].startswith("/"):
            endpoint, rule, methods, category, source = cells
            rows.append((endpoint, rule, methods, category, source.rsplit(":", 1)[0]))
    assert len(rows) == 157, "Review the frozen inventory/count on route changes"
    return rows


ROWS = inventory_rows()
METHOD_ROWS = [(row, method) for row in ROWS for method in row[2].split(",")]
UNBOUND = EXCEPTIONS["public_asset"] | EXCEPTIONS["account_control"] | EXCEPTIONS["explicit_timepoint"]


@pytest.fixture(scope="module")
def owned_app():
    # Keep nested state filenames below the native Windows path-length limit.
    temporary = tempfile.TemporaryDirectory(prefix="hri-")
    directory = Path(temporary.name)
    patch = pytest.MonkeyPatch()
    patch.setenv("BRACHYBOT_ARCHIVE_ROOT", str(directory / "archive"))
    patch.setenv("BRACHYBOT_RUNTIME_DIR", str(directory / "support-runtime"))
    patch.setenv("BRACHYBOT_API_KEY", "synthetic-inventory-api-key")
    from web import server_support
    from web.workspace_store import WorkspaceStore
    # Transport inventory on Windows does not test Linux directory durability.
    if os.name == "nt":
        patch.setattr(WorkspaceStore, "_fsync_directory", staticmethod(lambda path: None))
    patch.setattr(server_support, "API_KEY", "synthetic-inventory-api-key")
    patch.setattr(server_support, "_API_KEY_REQUIRED", True)
    from web.server import create_app
    app = create_app({"runtime_dir": str(directory / "runtime"),
                      "secret_key": "synthetic-inventory-secret",
                      "workspace_maintenance": False})
    assert app is not None
    app.config["TESTING"] = True
    raw = app.extensions["brachybot_workspace_store"].raw
    user = raw.create_user("inventory_owner", "synthetic-unused-password-hash")
    sid = raw.create_session(user["id"], "Synthetic inventory patient").id
    catalog = raw.migrate_default_timepoint(user["id"], sid)
    first = catalog["default_timepoint_id"]
    second = raw.create_timepoint(user["id"], sid, "Second scan",
                                 expected_revision=catalog["catalog_revision"])["created_timepoint_id"]
    other_sid = raw.create_session(user["id"], "Other synthetic patient").id
    other_tid = raw.migrate_default_timepoint(user["id"], other_sid)["default_timepoint_id"]
    value = SimpleNamespace(app=app, raw=raw, user=user, sid=sid, first=first,
                            second=second, other_sid=other_sid, other_tid=other_tid,
                            directory=directory)
    try:
        yield value
    finally:
        patch.undo()
        temporary.cleanup()


def identity(value, selected=None):
    return {"bb_user_id": value.user["id"], "bb_auth_epoch": value.user["auth_epoch"],
            "bb_session_id": selected or value.sid, "bb_csrf_token": "inventory-csrf"}


def headers(value, tid=None, sid=None):
    return {"X-CSRF-Token": "inventory-csrf",
            "X-API-Key": "synthetic-inventory-api-key",
            "X-BrachyBot-Session": sid or value.sid,
            "X-BrachyBot-Timepoint": tid or value.first}


def client(value):
    result = value.app.test_client()
    with result.session_transaction() as cookie:
        cookie.update(identity(value))
    return result


def url_for_row(row, value):
    values = {"session_id": value.sid, "identifier": value.first,
              "filename": "inventory.png", "artifact_path": "inventory.txt",
              "relative_path": "inventory.txt", "comment_id": "1",
              "kind": "source"}
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>",
                  lambda match: values.get(match[1], "a" * 32), row[1])


def test_complete_actual_registered_map_and_exception_allowlist(owned_app):
    app = owned_app.app
    actual = set()
    for rule in app.url_map.iter_rules():
        handler = inspect.unwrap(app.view_functions[rule.endpoint])
        source = Path(inspect.getsourcefile(handler)).resolve()
        source = source.relative_to(ROOT).as_posix() if source.is_relative_to(ROOT) else "flask.app"
        actual.add((rule.endpoint, rule.rule, ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"})), source))
    expected = {(row[0], row[1], row[2], row[4]) for row in ROWS}
    assert actual == expected, {"unclassified_or_changed": actual - expected, "missing": expected - actual}
    assert len(app.url_map._rules) == 157 and len(app.view_functions) == 156
    assert len(METHOD_ROWS) == 167
    seen = set()
    for category, endpoints in EXCEPTIONS.items():
        assert not seen & endpoints
        seen.update(endpoints)
        assert {row[0] for row in ROWS if row[3] == category} == endpoints
    for endpoint, _, _, category, _ in ROWS:
        assert category == next((name for name, endpoints in EXCEPTIONS.items()
                                 if endpoint in endpoints), "clinical_http")
    from web.routes.timepoint_routes import TIMEPOINT_CONTROL_ENDPOINTS
    from web.routes.implant_routes import SCOPED_IMPLANT_ENDPOINTS
    from web.routes.timepoint_image_routes import SCOPED_IMAGE_ENDPOINTS
    from web.routes.guide_registration_routes import SCOPED_GUIDE_REGISTRATION_ENDPOINTS
    from web.routes.intraoperative_routes import SCOPED_INTRAOPERATIVE_ENDPOINTS
    actual_exceptions = (TIMEPOINT_CONTROL_ENDPOINTS | SCOPED_IMPLANT_ENDPOINTS |
                         SCOPED_IMAGE_ENDPOINTS | SCOPED_GUIDE_REGISTRATION_ENDPOINTS |
                         SCOPED_INTRAOPERATIVE_ENDPOINTS)
    assert actual_exceptions == EXCEPTIONS["explicit_timepoint"]
    assert [fn.__name__ for fn in app.before_request_funcs[None]] == [
        "_require_authenticated_api_user", "reject_unscoped_timepoint_execution",
        "_record_request_started_at", "_restore_display_tokens_in_request",
        "_protect_live_workspace_lease"]


@pytest.mark.parametrize("row,method", METHOD_ROWS,
                         ids=[f"{r[0]}:{m}:{r[1]}" for r, m in METHOD_ROWS])
def test_every_registered_method_preprocesses_with_reviewed_scope(owned_app, row, method):
    from flask import g, session
    from web.timepoint_http import HttpTimepointBinding, current_binding
    # Do not invoke handlers: real auth, scope and lease hooks only.
    with owned_app.app.test_request_context(url_for_row(row, owned_app), method=method,
                                           headers=headers(owned_app), json={}):
        session.update(identity(owned_app, owned_app.other_sid))
        assert owned_app.app.preprocess_request() is None
        binding = getattr(g, "brachybot_timepoint_binding", None)
        if row[0] in UNBOUND:
            assert binding is None
        else:
            assert binding == HttpTimepointBinding(owned_app.user["id"], owned_app.sid, owned_app.first)
            assert current_binding() == binding


@pytest.mark.parametrize("row,method",
                         [(r, m) for r, m in METHOD_ROWS if r[3] == "explicit_timepoint"],
                         ids=[f"{r[0]}:{m}" for r, m in METHOD_ROWS if r[3] == "explicit_timepoint"])
def test_explicit_route_wrappers_reject_conflicting_url_session(owned_app, row, method):
    response = client(owned_app).open(url_for_row(row, owned_app), method=method,
        headers=headers(owned_app, owned_app.other_tid, owned_app.other_sid), json={})
    assert response.status_code == 400, response.get_data(as_text=True)
    # All route exceptions must reject before executing a clinical producer.


def test_central_mismatch_and_unowned_target_fail_before_handler(owned_app):
    browser = client(owned_app)
    response = browser.post("/api/viewer/load", headers=headers(owned_app),
                            json={"timepoint_id": owned_app.second})
    assert response.status_code == 400 and response.get_json()["code"] == "invalid_timepoint_scope"
    response = browser.get("/api/planning/results", headers=headers(owned_app, "f" * 32))
    assert response.status_code == 404
    response = browser.get("/api/planning/results", headers=headers(owned_app, sid="f" * 32))
    assert response.status_code == 400


def test_actual_progress_consumers_filter_and_stream_original_triple(owned_app):
    from web.server_support import task_manager
    owner = f"{owned_app.user['id']}:{owned_app.sid}:{owned_app.first}"
    task_id = task_manager.create_task("inventory", "Synthetic finished task", workspace_owner=owner)
    task_manager.complete_task(task_id)
    try:
        browser = client(owned_app)
        assert browser.get(f"/api/tasks/{task_id}", headers=headers(owned_app)).status_code == 200
        assert browser.get(f"/api/tasks/{task_id}", headers=headers(owned_app, owned_app.second)).status_code == 404
        assert task_id not in browser.get("/api/tasks", headers=headers(owned_app, owned_app.second)).get_json()
        response = browser.get(f"/api/tasks/stream?task_id={task_id}", headers=headers(owned_app), buffered=False)
        from web.timepoint_http import HttpTimepointBinding, bound_request
        with bound_request(HttpTimepointBinding(owned_app.user["id"], owned_app.other_sid, owned_app.other_tid)):
            payload = b"".join(response.response)
        assert task_id.encode() in payload
        response.close()
    finally:
        with task_manager._lock:
            task_manager._tasks.pop(task_id, None)


def test_worker_and_actual_after_request_stream_keep_original_binding(owned_app, monkeypatch):
    from flask import Response
    from web.timepoint_http import HttpTimepointBinding, bound_request, current_binding, scoped_callable
    original = HttpTimepointBinding(owned_app.user["id"], owned_app.sid, owned_app.first)
    later = HttpTimepointBinding(owned_app.user["id"], owned_app.other_sid, owned_app.other_tid)
    captured, closed = [], []
    with bound_request(original):
        worker = scoped_callable(lambda: captured.append(current_binding()))
    with bound_request(later):
        thread = threading.Thread(target=worker)
        thread.start(); thread.join(timeout=5)
        assert not thread.is_alive()
        assert current_binding() == later
    assert captured == [original]
    def handler():
        def generate():
            try:
                yield repr(current_binding()).encode()
                yield repr(current_binding()).encode()
            finally:
                closed.append(current_binding())
        return Response(generate(), mimetype="text/event-stream")
    # Existing registered endpoint; only producer is a tiny transport fixture.
    monkeypatch.setitem(owned_app.app.view_functions, "api_tasks_stream", handler)
    response = client(owned_app).get("/api/tasks/stream", headers=headers(owned_app), buffered=False)
    with bound_request(later):
        assert all(repr(original).encode() == chunk for chunk in response.response)
        assert current_binding() == later
    response.close()
    assert closed == [original]


def test_retained_ui_checkpoint_store_writes_original_target(owned_app):
    from web.routes import planning_routes as routes
    from web.timepoint_http import HttpTimepointBinding, ScopedWorkspaceStore, bound_request
    original = HttpTimepointBinding(owned_app.user["id"], owned_app.sid, owned_app.first)
    later = HttpTimepointBinding(owned_app.user["id"], owned_app.sid, owned_app.second)
    retained = ScopedWorkspaceStore(owned_app.raw, original)
    key = (original.owner_id, original.session_id, original.timepoint_id)
    before_other = owned_app.raw.load_ui_bridge(original.owner_id, original.session_id)
    before_second = ScopedWorkspaceStore(owned_app.raw, later).load_ui_bridge(later.owner_id, later.session_id)
    with routes._UI_BRIDGE_CHECKPOINT_LOCK:
        assert key not in routes._UI_BRIDGE_CHECKPOINT_PENDING
        routes._UI_BRIDGE_CHECKPOINT_PENDING[key] = (
            retained, original.owner_id, original.session_id,
            {"inventory_marker": "original-owner"}, "inventory.synthetic")
    with bound_request(later):
        routes._flush_ui_bridge_checkpoint(key)
    assert retained.load_ui_bridge(original.owner_id, original.session_id)["inventory_marker"] == "original-owner"
    assert ScopedWorkspaceStore(owned_app.raw, later).load_ui_bridge(later.owner_id, later.session_id) == before_second
    # Root Session control state must not have received the retained target patch.
    assert owned_app.raw.load_ui_bridge(original.owner_id, original.session_id) == before_other


def test_scoped_http_runtime_close_publishes_only_captured_target(owned_app):
    from agent_runtime.core import AgentMemory
    from web.timepoint_http import HttpTimepointBinding, ScopedHttpRuntime, bound_request
    control = SimpleNamespace(memory=AgentMemory(owned_app.sid), _workspace_store=owned_app.raw,
        config={"_workspace_owner_id": owned_app.user["id"], "_workspace_session_id": owned_app.sid,
                "_workspace_root": str(owned_app.raw.workspace_root(owned_app.user["id"], owned_app.sid))})
    original = HttpTimepointBinding(owned_app.user["id"], owned_app.sid, owned_app.first)
    later = HttpTimepointBinding(owned_app.user["id"], owned_app.sid, owned_app.second)
    before = owned_app.raw.load_timepoint_snapshot(later.owner_id, later.session_id, later.timepoint_id)
    runtime = ScopedHttpRuntime(control, original)
    assert runtime.view.memory is not control.memory
    assert runtime.store.binding == original
    runtime.view.memory.set_ui_state({"inventory": {"target": "original"}})
    runtime.mark_dirty()
    with bound_request(later):
        runtime.close(commit=True)
    saved = owned_app.raw.load_timepoint_snapshot(original.owner_id, original.session_id, original.timepoint_id)
    assert saved["ui"]["state"]["inventory"]["target"] == "original"
    after = owned_app.raw.load_timepoint_snapshot(later.owner_id, later.session_id, later.timepoint_id)
    # load_timepoint_snapshot stamps saved_at on every read, even without writes.
    assert {key: value for key, value in after.items() if key != "saved_at"} == {
        key: value for key, value in before.items() if key != "saved_at"}
    assert "inventory" not in control.memory.get_ui_state()


@pytest.mark.parametrize("kind", ["artifact", "screenshot", "legacy_screenshot"])
def test_file_consumer_must_reject_another_timepoint(owned_app, kind):
    raw, uid, sid, first = owned_app.raw, owned_app.user["id"], owned_app.sid, owned_app.first
    if kind == "artifact":
        raw.write_artifact(uid, sid, "reports_tp_" + first, "inventory.txt", BytesIO(b"original-target"))
        url = f"/api/sessions/{sid}/artifacts/reports_tp_{first}/inventory.txt"
    else:
        name = first + "_inventory.png"
        raw.write_screenshot(uid, sid, name, b"synthetic-file-bytes")
        url = f"/api/sessions/{sid}/screenshots/{name}" if kind == "screenshot" else f"/api/screenshots/{name}"
    response = client(owned_app).get(url, headers=headers(owned_app, owned_app.second))
    status, body = response.status_code, response.get_data()
    response.close()
    assert status in {403, 404, 409}, (status, body)


@pytest.mark.parametrize("action", ["status", "cancel", "download", "file"])
@pytest.mark.parametrize("navigation", ["timepoint", "session"])
def test_export_job_consumer_must_reject_changed_target(owned_app, action, navigation):
    from web.export_service import ExportJob
    job_id = uuid4().hex
    staging = owned_app.directory / "synthetic-export" / job_id
    staging.mkdir(parents=True)
    archive = staging / "inventory.zip"; archive.write_bytes(b"synthetic-archive")
    individual = staging / "inventory.txt"; individual.write_text("original-target", encoding="utf-8")
    job = ExportJob(job_id, owned_app.user["id"], owned_app.sid, status="completed",
                    timepoint_id=owned_app.first, zip_path=str(archive), export_root=str(staging))
    manager = owned_app.app.extensions["brachybot_export_jobs"]
    with manager._lock:
        manager._jobs[job_id] = job
    try:
        target = headers(owned_app, owned_app.second) if navigation == "timepoint" else headers(
            owned_app, owned_app.other_tid, owned_app.other_sid)
        suffix = {"status": "", "cancel": "/cancel", "download": "/download", "file": "/files/inventory.txt"}[action]
        response = client(owned_app).open("/api/data/exports/" + job_id + suffix,
                                         method="POST" if action == "cancel" else "GET", headers=target)
        status = response.status_code
        response.close()
        assert status in {403, 404, 409}, (status, job.cancel_requested)
    finally:
        with manager._lock:
            manager._jobs.pop(job_id, None)


@pytest.mark.parametrize("kind", ["artifact", "screenshot"])
def test_url_file_session_must_match_captured_session(owned_app, kind):
    raw, uid, sid = owned_app.raw, owned_app.user["id"], owned_app.sid
    if kind == "artifact":
        raw.write_artifact(uid, sid, "reports_tp_" + owned_app.first, "url-inventory.txt", BytesIO(b"original-case"))
        url = f"/api/sessions/{sid}/artifacts/reports_tp_{owned_app.first}/url-inventory.txt"
    else:
        name = owned_app.first + "_url-inventory.png"
        raw.write_screenshot(uid, sid, name, b"synthetic-file-bytes")
        url = f"/api/sessions/{sid}/screenshots/{name}"
    response = client(owned_app).get(url, headers=headers(owned_app, owned_app.other_tid, owned_app.other_sid))
    status, claimed_session = response.status_code, response.headers.get("X-BrachyBot-Session")
    response.close()
    assert status in {400, 403, 404, 409}, (status, claimed_session)


def test_nondefault_artifact_and_signed_screenshot_links_keep_original_target(owned_app):
    from web.server_support import _make_session_screenshot_url
    browser = client(owned_app)
    uploaded = browser.post('/api/workspace/artifacts', headers=headers(owned_app,owned_app.second),
        data={'category':'reports','file':(BytesIO(b'nondefault-report'),'qa.txt')},content_type='multipart/form-data')
    assert uploaded.status_code == 201,uploaded.get_data(as_text=True)
    url = uploaded.get_json()['download_url']
    assert 'timepoint_id='+owned_app.second in url
    # An ordinary anchor cannot send the pane headers; the generated URL can.
    read = browser.get(url,headers={'X-API-Key':'synthetic-inventory-api-key'})
    assert read.status_code == 200 and read.get_data()==b'nondefault-report'
    assert read.headers['X-BrachyBot-Timepoint'] == owned_app.second
    read.close()
    name=owned_app.second+'_scope.png'
    owned_app.raw.write_screenshot(owned_app.user['id'],owned_app.sid,name,b'nondefault-capture')
    screenshot = _make_session_screenshot_url(owned_app.sid,name)
    assert 'timepoint_id='+owned_app.second in screenshot
    read=browser.get(screenshot)  # Real durable signature, no API-key header.
    assert read.status_code==200 and read.get_data()==b'nondefault-capture'
    assert read.headers['X-BrachyBot-Timepoint']==owned_app.second
    read.close()


def test_legacy_unprefixed_artifact_is_readable_only_on_migrated_default(owned_app):
    owned_app.raw.write_artifact(owned_app.user['id'],owned_app.sid,'reports','legacy.txt',BytesIO(b'legacy-default'))
    url=f'/api/sessions/{owned_app.sid}/artifacts/reports/legacy.txt'
    browser=client(owned_app)
    read=browser.get(url,headers=headers(owned_app))
    assert read.status_code==200 and read.get_data()==b'legacy-default'
    read.close()
    rejected=browser.get(url,headers=headers(owned_app,owned_app.second))
    assert rejected.status_code==404


def test_completed_nondefault_export_supplies_owned_plain_file_links(owned_app):
    from urllib.parse import parse_qs, urlsplit
    from web.export_service import ExportJob
    job_id=uuid4().hex
    staging=owned_app.directory/'owned-link-export'/job_id
    staging.mkdir(parents=True)
    individual=staging/'source with space.txt'
    individual.write_text('original nondefault export',encoding='utf-8')
    archive=staging/'whole.zip'; archive.write_bytes(b'synthetic-archive')
    job=ExportJob(job_id,owned_app.user['id'],owned_app.sid,status='completed',
        timepoint_id=owned_app.second,zip_path=str(archive),export_root=str(staging),
        files=[{'relative_path':individual.name,'object_id':'synthetic:source'}])
    manager=owned_app.app.extensions['brachybot_export_jobs']
    with manager._lock:
        manager._jobs[job_id]=job
    try:
        browser=client(owned_app)
        packet=browser.get('/api/data/exports/'+job_id,
            headers=headers(owned_app,owned_app.second)).get_json()['job']
        url=packet['files'][0]['download_url']
        assert parse_qs(urlsplit(url).query)['timepoint_id']==[owned_app.second]
        assert '%20' in url
        # No mounted-pane headers: an actual generated link selects its own
        # captured target, not the selected cookie's default timepoint.
        response=browser.get(url,headers={'X-API-Key':'synthetic-inventory-api-key'})
        assert response.status_code==200
        assert response.get_data()==b'original nondefault export'
        response.close()
        denied=browser.get(url,headers=headers(owned_app,owned_app.first))
        assert denied.status_code==400
        assert 'download_url' not in job.files[0], 'Response decoration must not mutate the durable job'
    finally:
        with manager._lock:
            manager._jobs.pop(job_id,None)

