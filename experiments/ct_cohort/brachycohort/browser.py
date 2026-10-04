"""Real user controls only for mutations; readonly observation is explicit."""
from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from .core import Blocked, atomic_json, sanitize, mounts, load_json, utc
from .observer import Observer, terminal_task, verify_effective_target


def timed(stage):
    from functools import wraps
    def decorate(method):
        @wraps(method)
        async def measured(self, *args, **kwargs):
            deadline = self.cfg.get("execution_deadline_utc")
            if deadline:
                from datetime import datetime, timezone
                if datetime.fromisoformat(deadline.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    raise Blocked("RESOURCE_DEADLINE_EXPIRED")
            start = time.monotonic()
            self.journal.event(stage, "STARTED")
            try:
                value = await method(self, *args, **kwargs)
            except BaseException as exc:
                self.journal.event(stage, "FAILED", duration_s=time.monotonic() - start, error=str(exc))
                raise
            self.journal.event(stage, "FINISHED", duration_s=time.monotonic() - start)
            return value
        return measured
    return decorate


def selector_attribute(name, value):
    # JSON-quoted strings are valid CSS attribute values and escape quotes/backslashes.
    return f"[{name}={json.dumps(str(value))}]"


class Browser:
    def __init__(self, cfg, storage, journal, attempt_root):
        self.cfg, self.storage, self.journal = cfg, storage, journal
        self.root = Path(attempt_root)
        self.session_id = None
        self.task_id = None
        self.requests = []
        self.response_tasks = set()

    async def __aenter__(self):
        try:
            return await self._open()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def _open(self):
        from playwright.async_api import async_playwright
        u = urlsplit(self.cfg["deployment_url"])
        if u.scheme not in {"http", "https"} or u.username or u.password or u.port in {8080, 18082}:
            raise Blocked("UNSAFE_DEPLOYMENT_URL", "Production ports and embedded credentials are prohibited")
        self.pw = await async_playwright().start()
        # Chromium profile, downloads and scratch must not default to /tmp.
        # CIFS here cannot create Chromium's singleton symlinks. Use volatile tmpfs,
        # not a disk cache or a fallback into the production checkout.
        ram_root = Path(self.cfg.get("browser_tmpfs", "/dev/shm")).resolve()
        if not any(Path(m["target"]).resolve() == ram_root and m["fstype"] == "tmpfs" for m in mounts()):
            raise Blocked("BROWSER_TMPFS_NOT_AVAILABLE")
        import tempfile
        import shutil
        self.browser_temp = Path(tempfile.mkdtemp(prefix="brachy-cohort-", dir=ram_root))
        temp = self.browser_temp
        self.old_temp_env = {k: os.environ.get(k) for k in ("TMPDIR", "TEMP", "TMP")}
        os.environ.update(TMPDIR=str(temp), TEMP=str(temp), TMP=str(temp))
        self.chromium = await self.pw.chromium.launch(headless=self.cfg.get("headless", True),
                                                      downloads_path=str(self.root / "downloads"),
                                                      env={**os.environ, "TMPDIR": str(temp)},
                                                      args=["--disk-cache-size=1", "--media-cache-size=1"])
        self.context = await self.chromium.new_context(base_url=self.cfg["deployment_url"],
                         accept_downloads=True, viewport={"width": 1920, "height": 1080})
        self.context.set_default_timeout(30000)
        self.page = await self.context.new_page()

        def request_seen(request):
            path = urlsplit(request.url).path
            if path.startswith("/api/") and request.method not in {"GET", "HEAD"}:
                self.requests.append({"path": path, "method": request.method, "at": time.monotonic(),
                                      "session_id": self.session_id})
        self.page.on("request", request_seen)
        await self.page.goto("/", wait_until="domcontentloaded")
        if await self.page.locator("#authOverlay").is_visible():
            username = os.environ.get(self.cfg.get("username_env", "COHORT_USERNAME"))
            password = os.environ.get(self.cfg.get("password_env", "COHORT_PASSWORD"))
            if not username or not password:
                raise Blocked("EXPERIMENT_CREDENTIALS_MISSING")
            await self.page.locator("#authUsername").fill(username)
            await self.page.locator("#authPassword").fill(password)
            await self.page.locator("#authLogin").click()
            await self.page.locator("#authOverlay").wait_for(state="hidden")
        return self

    async def __aexit__(self, *exc):
        atomic_json(self.root / "mutation_transport_log.json", self.requests)
        if getattr(self, "chromium", None):
            await self.chromium.close()
        if getattr(self, "pw", None):
            await self.pw.stop()
        if getattr(self, "browser_temp", None):
            import shutil
            shutil.rmtree(self.browser_temp)
        for k, v in getattr(self, "old_temp_env", {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    async def screenshot(self, name):
        self.storage.check()
        (self.root / "screenshots").mkdir(exist_ok=True)
        await self.page.screenshot(path=str(self.root / "screenshots" / (name + ".png")), full_page=True)

    @timed("create_case")
    async def create_case(self):
        self.storage.check()
        async with self.page.expect_response(lambda r: urlsplit(r.url).path == "/api/sessions" and r.request.method == "POST") as response:
            await self.page.locator("button.new-chat-btn").click()
        r = await response.value
        payload = await r.json()
        if r.status not in {200, 201} or payload.get("success") is not True:
            raise Blocked("CASE_CREATION_FAILED")
        self.session_id = str(payload.get("active_session_id") or payload.get("session", {}).get("id") or "")
        if not self.session_id:
            raise Blocked("CASE_ID_MISSING")
        # Commit identity BEFORE another await or any upload/planning action.
        rec = load_json(self.root / "attempt.json") if (self.root / "attempt.json").is_file() else {}
        atomic_json(self.root / "session.json", {"session_id": self.session_id,
                    "recipe_hash": rec.get("recipe_hash"), "created_at": utc()})
        self.observer = Observer(self.context, self.session_id, self.journal, self.storage.check)
        self.journal.event("case", "CREATED", session_id=self.session_id)
        # A fresh case must not inherit a former planning target/artifact.
        catalog = await self.observer.get("/api/data/catalog")
        if any(r.get("data_type") in {"ctv", "dose", "surgical_guide"} for r in catalog.get("objects", [])):
            raise Blocked("NEW_CASE_NOT_EMPTY")
        return self.session_id

    async def attach_case(self, session_id):
        """Recovery selects an existing case via UI; never creates a replacement."""
        node = self.page.locator("#session-title-" + session_id)
        if await node.count() != 1:
            raise Blocked("RECOVERY_SESSION_NOT_IN_OWNED_UI")
        await node.click()
        self.session_id = session_id
        self.observer = Observer(self.context, session_id, self.journal, self.storage.check)
        await self.observer.get("/api/workspace/snapshot")

    async def input_panel(self):
        await self.page.locator('[data-panel="input"]').click()

    @timed("upload_and_ctv_promotion")
    async def upload_and_promote(self, row):
        await self.input_panel()
        async with self.page.expect_response(lambda r: urlsplit(r.url).path == "/api/upload" and r.request.method == "POST", timeout=self.cfg["budgets"]["upload_s"] * 1000) as response:
            await self.page.locator("#fileCT").set_input_files(row["derived_ct_path"])
        receipt = await (await response.value).json()
        self.journal.event("ct_upload", "TRANSPORT_RECEIPT", receipt=sanitize(receipt))
        await self.observer.wait("/api/data/catalog", lambda x: any(r.get("object_id") == "image:ct" for r in x.get("objects", [])),
                                 self.cfg["budgets"]["upload_s"], "ct_loaded")
        # Actual UI readiness, not just an owned upload path.
        await self.page.wait_for_function("typeof state !== 'undefined' && state.ctLoaded === true", timeout=self.cfg["budgets"]["upload_s"] * 1000)
        async with self.page.expect_response(lambda r: urlsplit(r.url).path == "/api/segmentation" and r.request.method == "POST", timeout=self.cfg["budgets"]["upload_s"] * 1000) as response:
            await self.page.locator("#fileCTV").set_input_files(row["derived_label_path"])
        receipt = await (await response.value).json()
        self.journal.event("mask_staging", "TRANSPORT_RECEIPT", receipt=sanitize(receipt))
        staged = await self.observer.wait("/api/data/catalog", lambda x: bool([r for r in x.get("objects", []) if r.get("data_type") == "generic_mask"]),
                                         self.cfg["budgets"]["upload_s"], "mask_staged")
        masks = [r for r in staged.get("objects", []) if r.get("data_type") == "generic_mask"]
        # The primary transport is a verified binary derivative: exactly ONE child.
        if len(masks) != 1 or masks[0].get("metadata", {}).get("voxel_count") != row["target_voxels"]:
            raise Blocked("STAGED_TARGET_AMBIGUOUS")
        selected = [masks[0]["object_id"]]
        node = masks[0]["metadata"].get("data_tree_node_id")
        if not node:
            raise Blocked("STAGED_NODE_REFERENCE_MISSING")
        await self.page.locator('[data-panel="viewers"]').click()
        item = self.page.locator(".tree-item" + selector_attribute("data-node-id", node))
        if await item.count() != 1:
            raise Blocked("STAGED_DOM_REFERENCE_AMBIGUOUS")
        await item.click()
        await item.click(button="right")
        menu = self.page.locator('.ctx-menu-item[onclick*="moveSelectedMasks"][onclick*="ctv"]')
        async with self.page.expect_response(lambda r: urlsplit(r.url).path == "/api/data/generic-masks/classification" and r.request.method == "PATCH") as response:
            await menu.click()
        receipt = await (await response.value).json()
        if receipt.get("success") is not True or set(receipt.get("object_ids", [])) != set(selected):
            raise Blocked("CTV_PROMOTION_RECEIPT_MISMATCH")
        self.journal.event("ctv_promotion", "TRANSPORT_RECEIPT", receipt=sanitize(receipt), selected_ids=selected)
        evidence = verify_effective_target(self.cfg["metadata_runtime"], self.session_id, row, selected)
        self.journal.event("ctv_verification", "PASS", evidence=evidence)
        # Restoration must preserve the server-owned target, not only a transient tree row.
        await self.page.reload(wait_until="domcontentloaded")
        await self.page.locator("#chatInput").wait_for(state="visible")
        evidence = verify_effective_target(self.cfg["metadata_runtime"], self.session_id, row, selected)
        await self.screenshot("target-promoted")
        return selected, evidence

    @timed("apply_profile")
    async def apply_profile(self, profile):
        await self.input_panel()
        if not await self.page.locator("#hyperparamsSection").is_visible():
            await self.page.locator('[aria-controls="hyperparamsSection"]').click()
        s = profile["settings"]
        controls = {"inLowestEnergy": s["prescription_gy"], "outHighestEnergy": s["upper_dose_gy"],
                    "dvhRate": s["coverage_fraction"], "maxIter": s["max_iterations"],
                    **profile.get("ui_controls", {})}
        for name, value in controls.items():
            if not name.isalnum() or not isinstance(value, (int, float)):
                raise Blocked("INVALID_PROFILE_UI_CONTROL")
            loc = self.page.locator("#" + name)
            await loc.fill(str(value))
            await loc.press("Tab")
            if float(await loc.input_value()) != value:
                raise Blocked("UI_SETTING_READBACK_MISMATCH", name)
        # The checkbox is visually hidden inside a genuine label; click the label.
        toggle = self.page.locator("#useRLToggle")
        if await toggle.is_checked() != (s["mode"] == "rl"):
            await toggle.locator("..").click()
        async with self.page.expect_response(lambda r: "/api/config" in r.url and r.request.method == "POST") as response:
            await self.page.locator('button[onclick="applyHyperparams()"]').click()
        r = await response.value
        if r.status != 200:
            raise Blocked("PROFILE_APPLICATION_FAILED")
        self.journal.event("parameters", "APPLIED", controls=controls, mode=s["mode"], receipt=sanitize(await r.json()))

    @timed("chat_submission")
    async def chat(self, message):
        self.storage.check()
        await self.page.locator("#chatInput").fill(message)
        async with self.page.expect_response(lambda r: urlsplit(r.url).path == "/api/chat" and r.request.method == "POST", timeout=90000) as response:
            await self.page.locator("#chatSendBtn").click()
        r = await response.value
        # Streaming POST responses are not parsed as JSON; recover task by readonly status.
        if r.status not in {200, 202}:
            raise Blocked("CHAT_SUBMISSION_FAILED", str(r.status))
        payload = await self.observer.wait("/api/chat/task", lambda x: bool(x.get("task")), 90, "chat_task_seen")
        task = payload["task"]
        if task.get("session_id") != self.session_id:
            raise Blocked("CHAT_TASK_CASE_MISMATCH")
        self.task_id = task["task_id"]
        atomic_json(self.root / "chat_task.json", {"task_id": self.task_id, "session_id": self.session_id})
        self.journal.event("chat", "SUBMITTED", session_id=self.session_id, task_id=self.task_id, prompt=message)
        return self.task_id

    @timed("chat_workflow")
    async def wait_chat(self):
        p = await self.observer.wait("/api/chat/task", lambda x: terminal_task(x, self.task_id),
                                    self.cfg["budgets"]["workflow_s"], "chat_terminal", poll=3)
        await self.page.wait_for_function("(() => { const b=document.getElementById('chatSendBtn'); return b && !b.classList.contains('streaming') && !b.disabled && !document.body.classList.contains('chat-session-awaiting'); })()", timeout=90000)
        await self.screenshot("chat-terminal")
        messages = self.page.locator("#chatMessages")
        if await messages.count():
            atomic_json(self.root / "user_visible_chat.json", {"session_id": self.session_id,
                        "task_id": self.task_id, "text": await messages.inner_text(),
                        "note": "Rendered UI text is not an outcome oracle"})
        return p

    @timed("manual_ui_workflow")
    async def manual_ui(self):
        """The locked manual comparator, never a private tool/API shortcut."""
        await self.input_panel()
        async with self.page.expect_response(lambda r: urlsplit(r.url).path == "/api/planning/run_step" and r.request.method == "POST",
                                              timeout=self.cfg["budgets"]["workflow_s"] * 1000) as response:
            await self.page.locator('button[onclick="runPlanning()"]').click()
        r = await response.value
        payload = await r.json()
        self.journal.event("manual_pipeline", "RECEIPT", payload=sanitize(payload))
        if r.status != 200 or payload.get("success") is not True:
            raise Blocked("MANUAL_PIPELINE_FAILED")
        # Full pipeline already includes dose evaluation. Guide/report are distinct.
        async with self.page.expect_response(lambda r: urlsplit(r.url).path == "/api/surgical-guides/generate" and r.request.method == "POST",
                                              timeout=self.cfg["budgets"]["guide_s"] * 1000) as response:
            await self.page.locator("#generateSurgicalGuideButton").click()
        r = await response.value
        payload = await r.json()
        self.journal.event("manual_guide", "RECEIPT", payload=sanitize(payload))
        if r.status != 200 or payload.get("success") is not True:
            raise Blocked("MANUAL_GUIDE_FAILED")
        await self.page.locator('[data-panel="report"]').click()
        async with self.page.expect_response(lambda r: urlsplit(r.url).path == "/api/report/auto-fill" and r.request.method == "POST",
                                              timeout=self.cfg["budgets"]["report_s"] * 1000) as response:
            await self.page.locator('button[onclick="Report.autoFill.fromAll()"]').click()
        r = await response.value
        payload = await r.json()
        self.journal.event("manual_report", "RECEIPT", payload=sanitize(payload))
        if r.status != 200 or payload.get("success") is False:
            raise Blocked("MANUAL_REPORT_FAILED")
        # The POST prepares fields; browser-side figure capture and durable save
        # happen later. Wait on the actual user's completion indicator.
        status = self.page.locator("#reportStatusText.ok, #reportStatusText.error")
        await status.wait_for(state="visible", timeout=self.cfg["budgets"]["report_s"] * 1000)
        if "error" in (await status.get_attribute("class") or "").split():
            raise Blocked("MANUAL_REPORT_CAPTURE_OR_SAVE_FAILED", await status.inner_text())

    @timed("export_pdf")
    async def export_pdf(self):
        await self.page.locator('[data-panel="report"]').click()
        await self.screenshot("report-before-pdf")
        async with self.page.expect_download(timeout=self.cfg["budgets"]["report_s"] * 1000) as download:
            await self.page.locator('button[onclick="Report.export.pdf()"]',).click()
        result = await download.value
        if await result.failure():
            raise Blocked("PDF_EXPORT_FAILED")
        dest = self.root / "report.pdf"
        await result.save_as(str(dest))
        return dest

    @timed("export_session")
    async def export_session(self):
        # Actual session context menu -> Export Session -> Select All -> Export.
        node = self.page.locator("#session-title-" + self.session_id).locator("..")
        await node.click(button="right")
        await self.page.locator("[data-session-export]").click()
        await self.page.locator("[data-export-all]").click()
        async with self.page.expect_download(timeout=self.cfg["budgets"]["export_s"] * 1000) as download:
            await self.page.locator("[data-export-start]").click()
        result = await download.value
        if await result.failure():
            raise Blocked("SESSION_EXPORT_FAILED")
        dest = self.root / "session-export.zip"
        await result.save_as(str(dest))
        return dest

    async def cancel_and_reconcile(self):
        if not self.session_id:
            return "NO_CASE"
        try:
            payload = await self.observer.get("/api/chat/task")
            if (payload.get("task") or {}).get("status") == "running":
                if "streaming" not in (await self.page.locator("#chatSendBtn").get_attribute("class") or "").split():
                    return "CANCEL_PENDING"
                await self.page.locator("#chatSendBtn").click()
                await self.observer.wait("/api/chat/task", lambda x: terminal_task(x, self.task_id), 90, "cancel_reconciled")
            snapshot = await self.observer.get("/api/workspace/snapshot")
            state = snapshot.get("workspace", {}).get("operation", {}).get("state")
            if state not in {"ready", "completed", "idle", "failed", "cancelled"}:
                return "CANCEL_PENDING"
            return "TASK_TERMINAL"
        except Exception:
            return "CANCEL_PENDING"
