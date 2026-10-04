"""Regression controls for the independently reported acceptance findings."""
import hashlib
import json
import os
from pathlib import Path

import pytest


@pytest.mark.parametrize("action", ["retrieve", "search", "list", "statistics", "recommend"])
def test_case_memory_reads_share_one_authorization_contract(action):
    from agent_runtime.execution_authorization import TurnExecutionAuthorization, tool_call_is_mutating
    from agent_runtime.request_parse import mutating_execution_authorized
    params = {"action": action}
    assert not tool_call_is_mutating("case_memory", params)
    assert TurnExecutionAuthorization(1).tool_allowed("case_memory", params)
    assert mutating_execution_authorized("Has the report finished?", "case_memory", params=params)


@pytest.mark.parametrize("params", [{"action": "save"}, {}, {"action": "invented"}, {"action": None}, {"action": ["list"]}])
def test_case_memory_write_and_invalid_actions_do_not_inherit_read_exemption(params):
    from agent_runtime.execution_authorization import TurnExecutionAuthorization, tool_call_is_mutating
    from agent_runtime.request_parse import mutating_execution_authorized
    assert tool_call_is_mutating("case_memory", params)
    assert not TurnExecutionAuthorization(1).tool_allowed("case_memory", params)
    assert not mutating_execution_authorized("What is in this case?", "case_memory", params=params)


def test_case_memory_name_only_compatibility_is_not_an_invocation_grant():
    from agent_runtime.execution_authorization import TurnExecutionAuthorization
    from agent_runtime.request_parse import mutating_execution_authorized
    auth = TurnExecutionAuthorization(1)
    assert mutating_execution_authorized("Has the report finished?", "case_memory")
    assert auth.tool_allowed("case_memory")
    auth.grant_tool_calls([{"tool": "case_memory", "params": {"action": "list"}}], source="llm")
    assert "case_memory" not in auth.granted_tools
    assert not auth.tool_allowed("case_memory", {"action": "save"})
    auth.grant_tool_calls([{"tool": "case_memory", "params": None}], source="llm")
    # Malformed invocation parameters cannot be classified as a read.
    assert not mutating_execution_authorized("List cases", "case_memory", params={})


@pytest.mark.parametrize("action", ["status", "analyze"])
def test_guide_read_actions_do_not_authorize_generation(action):
    from agent_runtime.execution_authorization import TurnExecutionAuthorization
    from agent_runtime.request_parse import mutating_execution_authorized
    auth = TurnExecutionAuthorization(2)
    params = {"action": action}
    assert auth.tool_allowed("surgical_guide", params)
    assert mutating_execution_authorized("Where is the guide?", "surgical_guide", params=params)
    auth.grant_tool_calls([{"tool": "surgical_guide", "params": params}], source="llm")
    assert not auth.tool_allowed("surgical_guide", {"action": "generate"})


def incident(secret):
    return {"sha256": hashlib.sha256(secret).hexdigest(), "revocation_status": "unverified"}


def test_credential_scan_covers_other_files_and_redacts_match(tmp_path):
    from scripts.credential_audit import scan_sources
    secret = b"sk-" + b"AcceptanceTestValue" * 2
    directory = tmp_path / "other-checkout"
    directory.mkdir()
    (directory / "config.env").write_bytes(b"API_KEY=" + secret + b"\n")
    findings, scope = scan_sources([tmp_path], [incident(secret)])
    assert any(item["id"] == "compromised_credential_copy" for item in findings)
    assert secret.decode() not in json.dumps(findings)
    assert scope["files"] == 1 and scope["complete_within_scope"]


def test_process_environment_scan_detects_compromised_values_not_new_key(tmp_path):
    from scripts.credential_audit import scan_processes
    old = b"sk-" + b"OldTestCredential" * 2
    new = b"sk-" + b"NewTestCredential" * 2
    process = tmp_path / "123"
    process.mkdir()
    (process / "environ").write_bytes(b"ANTHROPIC_API_KEY=" + old + b"\0OTHER_KEY=" + new + b"\0")
    findings, scope = scan_processes([123], [incident(old)], proc_root=tmp_path)
    assert len(findings) == 1
    assert findings[0]["variable"] == "ANTHROPIC_API_KEY"
    assert scope["inspected_pids"] == [123]
    assert old.decode() not in json.dumps(findings)
    assert new.decode() not in json.dumps(findings)


def test_scan_budget_and_missing_process_are_explicit_failures(tmp_path):
    from scripts.credential_audit import scan_sources, scan_processes
    (tmp_path / "large.env").write_bytes(b"a" * 40)
    findings, scope = scan_sources([tmp_path], [], max_file_bytes=20)
    assert findings[0]["severity"] == "block"
    assert scope["complete_within_scope"] is False
    findings, scope = scan_processes([987654], [], proc_root=tmp_path)
    assert findings[0]["id"] == "credential_process_uninspectable"


def test_credential_scan_does_not_follow_symlinks_or_hide_exclusions(tmp_path):
    from scripts.credential_audit import scan_sources
    outside = tmp_path / "outside.env"
    outside.write_bytes(b"ordinary")
    root = tmp_path / "root"
    root.mkdir()
    (root / "linked.env").symlink_to(outside)
    (root / "backup.tar.gz").write_bytes(b"not an archive")
    findings, scope = scan_sources([root], [])
    assert not findings
    assert {item["reason"] for item in scope["excluded"]} == {
        "non-regular file or symlink", "compressed archive; inspect separately"}


def test_streamed_credential_scan_preserves_boundary_matches_and_line_numbers(tmp_path):
    from scripts.credential_audit import scan_sources
    secret = b"sk-" + b"BoundaryCredentialTest" * 2
    prefix = b"\n" + b"a" * (1024**2 - 8) + b"\n"
    (tmp_path / "large.jsonl").write_bytes(prefix + secret + b"\nordinary\n" + secret)
    findings, scope = scan_sources([tmp_path], [incident(secret)])
    assert [f["line"] for f in findings] == [3, 5]
    assert len(findings) == 2 and scope["complete_within_scope"]
    assert secret.decode() not in json.dumps(findings)


def test_release_gate_checks_processes_and_preserves_revocation_block(tmp_path, monkeypatch):
    from scripts.pre_release_security_check import checks
    secret = b"sk-" + b"IncidentValueTest" * 2
    registry = tmp_path / "incidents.json"
    registry.write_text(json.dumps({"schema_version": 1, "credentials": [incident(secret)]}))
    monkeypatch.setattr("importlib.metadata.version", lambda _name: "2.10.0+cu126")
    monkeypatch.setenv("BRACHYBOT_ALLOW_SELF_REGISTRATION", "0")
    monkeypatch.setattr("scripts.pre_release_security_check.scan_processes", lambda pids, entries: (
        [{"id": "compromised_process_credential", "severity": "block", "pid": 123}], {"inspected_pids": [123]}))
    scope = {}
    findings = checks(tmp_path, pids=[123], incident_file=registry, coverage=scope)
    assert {"credential_revocation_unverified", "compromised_process_credential"} <= {item["id"] for item in findings}
    assert scope["processes"]["inspected_pids"] == [123]
    assert secret.decode() not in json.dumps(findings)


@pytest.mark.parametrize("action", ["list", "search", "statistics", "save", "invented", None])
def test_normalization_uses_action_aware_gate_for_provider_case_memory(action):
    from AgenticSys import BrachyAgent
    from types import SimpleNamespace
    from agent_runtime.turn_policy import classify_local_turn
    agent = BrachyAgent.__new__(BrachyAgent)
    message = "What is in this case?"
    agent.memory = SimpleNamespace(conversation=[{"role": "user", "content": message}], get_ui_state=lambda: {})
    agent.config = {"_workspace_root": "/owned/case"}
    agent._active_turn_policy = classify_local_turn(message)
    params = {"action": action} if action is not None else {}
    calls = agent._normalize_tool_params([{"tool": "case_memory", "params": params}])
    assert bool(calls) is (action in {"list", "search", "statistics"})


def test_guide_renewal_guard_rejects_tampered_paired_evidence(tmp_path):
    import shutil
    from scripts.guide_latency_reference_guard import verify_reference
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "tests/guide_latency_reference.json").read_text())
    files = ["tests/guide_latency_reference.json", "tests/data/surgical_guide_latency_reference.py",
             manifest["renewal"]["evidence_path"], *manifest["dependencies"]]
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    assert verify_reference(tmp_path)["schema_version"] == 2
    evidence_path = tmp_path / manifest["renewal"]["evidence_path"]
    evidence_path.write_bytes(evidence_path.read_bytes() + b"\n")
    with pytest.raises(AssertionError, match="paired evidence hash"):
        verify_reference(tmp_path)
