"""Synthetic receipt and lifecycle regressions; no patient/provider/GPU work."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from flask import Flask

from agent_runtime.visual_evidence import grounded_location_answer
from web.visual_location_delivery import location_delivery_context
from web.chat_tasks import ChatTaskManager


SID = "a" * 32


@pytest.fixture
def receipt(tmp_path):
    def digest(value):
        return hashlib.sha256(value).hexdigest()
    evidence = []
    attachments = []
    for index, view in enumerate(("data-tree", "viewer-3d")):
        raw, marked = f"source-{index}".encode(), f"marked-{index}".encode()
        (tmp_path / f"source-{index}.png").write_bytes(raw)
        (tmp_path / f"marked-{index}.png").write_bytes(marked)
        target = {"target_ref": "structure:ctv:2", "label": "Label 2", "kind": "scene-object",
                  "visible": True, "in_view": True, "annotatable": True, "loaded": True,
                  "scene_visible": True, "data_tree_visible": True, "status": "ready",
                  "normalized_bounds": [0.2, 0.2, 0.4, 0.4]}
        url = f"/api/sessions/{SID}/screenshots/source-{index}.png?v=abc"
        item = {"id": f"shot-{index}", "session_id": SID, "request_id": "parent",
                "planning_id": "planning-a", "data_version": "7", "target": view,
                "url": url, "annotated_url": f"/api/sessions/{SID}/screenshots/marked-{index}.png",
                "sha256": digest(raw), "annotation_sha256": digest(marked),
                "visual_purpose": "locate", "annotation_policy": "required",
                "semantic_target": "ctv", "semantic_targets": ["ctv"],
                "view_metadata": {"grounding_manifest": {"version": 1, "targets": [target]},
                                  "temporary_occluders": ["surgical_guide:active"]},
                "annotation": {"source_sha256": digest(raw), "marks": [{"target_ref": "structure:ctv:2"}]}}
        attachments.append(item)
        evidence.append({"attachment_id": item["id"], "url": url})
    question = "肿瘤在哪里啊"
    steps = [{"id": 3, "type": "tool", "tool": "ui_screenshot", "status": "done",
              "metadata": {"screenshot_plan": {"visual_purpose": "locate", "semantic_targets": ["ctv"],
                                                "views": ["data-tree", "viewer-3d"]}}}]
    snapshot = {"chat": {"attachments": attachments, "messages": [
        {"type": "user", "request_id": "parent", "content": question},
        {"type": "thinking", "request_id": "parent", "steps": steps}]}}
    context = {"version": 2, "parent_request": question, "evidence": evidence, "omitted_count": 0}
    def check(s=snapshot, c=context, state=("planning-a", "7")):
        return location_delivery_context(s, c, "parent", SID, state, lambda name: tmp_path / name)
    return snapshot, context, check, tmp_path


def test_complete_location_uses_persisted_targets_and_restore_notice(receipt):
    snapshot, context, check, _ = receipt
    context["evidence"][0].update({"grounding_manifest": {"targets": [{"label": "forged"}]},
                                   "annotation_present": True, "temporary_reveal": True})
    context["preliminary_response"] = "untrusted patient name and unrelated claim"
    verified = check()
    assert verified is not None
    text = grounded_location_answer(verified, "zh")
    assert "Label 2" in text and "截图后已恢复" in text
    assert "forged" not in text and "patient name" not in text and "临时显示了" not in text
    assert grounded_location_answer(verified, "en") and "restored" in grounded_location_answer(verified, "en")


@pytest.mark.parametrize("change", [
    "other_request", "other_session", "missing_annotation", "source_hash", "marked_hash",
    "partial", "duplicate", "omitted", "changed_plan", "changed_version", "missing_trace",
    "other_tool", "tool_failed", "explain", "hidden", "not_loaded", "missing_mark",
    "semantic_mismatch", "missing_file", "changed_source", "changed_marked", "forged_url",
    "changed_question", "mixed_question",
])
def test_location_shortcut_fails_closed(receipt, change):
    snapshot, context, check, tmp_path = receipt
    attachment = snapshot["chat"]["attachments"][0]
    target = attachment["view_metadata"]["grounding_manifest"]["targets"][0]
    step = snapshot["chat"]["messages"][1]["steps"][0]
    state = ("planning-a", "7")
    if change == "other_request": attachment["request_id"] = "old"
    elif change == "other_session": attachment["session_id"] = "b" * 32
    elif change == "missing_annotation": attachment.pop("annotated_url")
    elif change == "source_hash": attachment["annotation"]["source_sha256"] = "bad"
    elif change == "marked_hash": attachment["annotation_sha256"] = "bad"
    elif change == "partial": context["evidence"].pop()
    elif change == "duplicate": context["evidence"][1] = copy.deepcopy(context["evidence"][0])
    elif change == "omitted": context["omitted_count"] = 1
    elif change == "changed_plan": state = ("other-plan", "7")
    elif change == "changed_version": state = ("planning-a", "8")
    elif change == "missing_trace": snapshot["chat"]["messages"].pop()
    elif change == "other_tool": step["tool"] = "query_metrics"
    elif change == "tool_failed": step["status"] = "error"
    elif change == "explain": attachment["visual_purpose"] = "explain"
    elif change == "hidden": target["visible"] = False
    elif change == "not_loaded": snapshot["chat"]["attachments"][1]["view_metadata"]["grounding_manifest"]["targets"][0]["loaded"] = False
    elif change == "missing_mark": attachment["annotation"]["marks"] = [{"target_ref": "another"}]
    elif change == "semantic_mismatch": target["target_ref"] = "surgical_guide:active"; attachment["annotation"]["marks"][0]["target_ref"] = "surgical_guide:active"
    elif change == "missing_file": (tmp_path / "source-0.png").unlink()
    elif change == "changed_source": (tmp_path / "source-0.png").write_bytes(b"changed")
    elif change == "changed_marked": (tmp_path / "marked-0.png").write_bytes(b"changed")
    elif change == "forged_url": context["evidence"][0]["url"] = f"/api/sessions/{SID}/screenshots/unrelated.png"
    elif change == "changed_question": context["parent_request"] = "报告是否包含剂量信息"
    elif change == "mixed_question":
        question = "肿瘤在哪里，剂量分布怎么样，报告里都写了吗？"
        snapshot["chat"]["messages"][0]["content"] = question
        context["parent_request"] = question
    assert check(snapshot, context, state) is None


class Memory:
    user_lang = "en"
    def set_ui_state(self, value): pass


class Agent:
    def __init__(self): self.memory = Memory(); self.calls = 0
    def chat_with_stream(self, message):
        self.calls += 1
        yield 'event: response\ndata: {"response":"model answer"}\n\n'
        yield 'event: done\ndata: {}\n\n'


@pytest.mark.parametrize("eligible", [True, False])
def test_receipt_delivery_uses_real_worker_finalizer_without_model(eligible):
    app, agent, manager = Flask(__name__), Agent(), ChatTaskManager()
    committed = []
    task = manager.start(app, "user", SID, agent, "Visual evidence analysis follow-up.", {},
                         internal_followup=True, parent_request_id="parent",
                         response_factory=lambda task, agent: {"response": "receipt answer",
                             "llm_meta": {"route": "grounded_location_receipt", "llm_calls": 0}} if eligible else None,
                         on_finish=lambda task: committed.append(task.response) or True)
    assert task.wait_for_worker(timeout=5)
    assert task.status == "completed" and task.result_committed
    assert agent.calls == (0 if eligible else 1)
    assert committed == ["receipt answer" if eligible else "model answer"]


def test_visual_delivery_clock_and_terminal_cleanup_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node runtime is required for DOM lifecycle checks")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, str(root / "tests/chat_visual_delivery_clock.cjs")],
                            cwd=root, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["receipt", "changed_version", "mixed"])
def test_real_chat_route_receipt_gate_and_durable_reply(receipt, monkeypatch, tmp_path, mode):
    from test_case_archive_active_use import _build_app
    from agent_runtime.core import AgentMemory
    monkeypatch.delenv("BRACHYBOT_API_KEY", raising=False)
    monkeypatch.delenv("BRACHYBOT_REQUIRE_API_KEY", raising=False)
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()
    auth = client.post("/api/auth/register", json={"username": "synthetic_receipt",
        "password": "synthetic-pass-123"}).get_json()
    case, owner = auth["active_session_id"], auth["user"]["id"]
    snapshot, context, _, artifact_dir = receipt
    snapshot = json.loads(json.dumps(snapshot).replace(SID, case))
    context = json.loads(json.dumps(context).replace(SID, case))
    if mode == "mixed":
        question = "肿瘤在哪里，剂量分布如何，这些写在报告里了吗？"
        snapshot["chat"]["messages"][0]["content"] = question
        context["parent_request"] = question
    snapshot["agent"] = {"planning_results": {"active_planning_id": "planning-a",
        "manual_plan_version": 8 if mode == "changed_version" else 7}}
    store = app.extensions["brachybot_workspace_store"]
    for filename in ("source-0.png", "source-1.png", "marked-0.png", "marked-1.png"):
        store.write_screenshot(owner, case, filename, (artifact_dir / filename).read_bytes())
    store.save_snapshot_patch(owner, case, snapshot, expected_revision=None)
    store.save_agent_results_patch(owner, case, snapshot["agent"]["planning_results"])
    if mode == "receipt":
        saved = store.load_snapshot(owner, case)
        from web.routes.planning_routes import _snapshot_annotation_planning_state
        verified = location_delivery_context(saved, context, "parent", case,
            _snapshot_annotation_planning_state(saved),
            lambda name: store.session_artifact_path(owner, case, "screenshots", name))
        assert verified is not None, json.dumps(saved, ensure_ascii=False)
    calls = []
    agent = SimpleNamespace(memory=AgentMemory(case), brain_available=False, config={}, _workspace_data_ready=True)
    def chat(message):
        calls.append(message)
        yield 'event: response\ndata: {"response":"model analysis"}\n\n'
        yield 'event: done\ndata: {}\n\n'
    agent.chat_with_stream = chat
    sessions, timestamps, lock = app.extensions["brachybot_agent_cache"]
    with lock:
        sessions[(owner, case)] = agent; timestamps[(owner, case)] = 1e12
    response = client.post("/api/chat", json={
        "message": "Visual evidence analysis follow-up.", "stream": True,
        "internal_followup": True, "request_id": "child", "parent_request_id": "parent",
        "parent_user_message_id": "user-parent", "parent_assistant_message_id": "assistant-parent",
        "visual_context": context, "response_language": "zh",
    }, headers={"X-CSRF-Token": auth["csrf_token"], "X-BrachyBot-Session": case})
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert bool(calls) == (mode != "receipt"), body
    assert ("grounded_location_receipt" in body) == (mode == "receipt")
    persisted = store.load_snapshot(owner, case)["chat"]["messages"]
    assert len([row for row in persisted if row.get("type") == "user"]) == 1
    answers = [row for row in persisted if row.get("type") == "bot-response"
               and row.get("request_id") == "parent"]
    assert len(answers) == 1 and answers[0]["content"].strip()
