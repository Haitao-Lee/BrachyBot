"""Regression tests for provider-neutral agent runtime contracts."""

from __future__ import annotations

from pathlib import Path

from agent_runtime.contracts import ContextPackBuilder, RunLedger, RunStatus, ToolCallGateway
from tool_factory import ToolResult


class _Tool:
    def __init__(self, schema):
        self.input_schema = schema


class _Registry:
    def __init__(self):
        self._tools = {
            "clinical_kb": _Tool({
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }),
            "ui_inspector": _Tool({
                "type": "object",
                "properties": {"scope": {"type": "string"}},
            }),
            "ctv_segmentation": _Tool({
                "type": "object",
                "properties": {
                    "image": {
                        "type": "object",
                        "x-server-injected": True,
                    },
                },
            }),
        }

    @property
    def tool_names(self):
        return list(self._tools)

    def get(self, name):
        return self._tools[name]


def test_context_pack_keeps_multimodal_current_turn_and_safe_tool_evidence():
    image_turn = [
        {"type": "text", "text": "Please assess this dose distribution."},
        {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}},
    ]
    builder = ContextPackBuilder(max_tokens=2_000, reserve_output_tokens=256)
    packed, manifest = builder.build([
        {"role": "system", "content": "Clinical safety instructions."},
        {"role": "tool", "tool_call_id": "old-call", "content": "x" * 2_000},
        {"role": "user", "content": image_turn},
    ], image_turn)

    assert packed[-1]["content"] == image_turn
    assert sum(1 for item in packed if item.get("content") == image_turn) == 1
    assert all(item.get("role") != "tool" for item in packed)
    assert manifest["strategy"] == "portable_structured_budget_v1"


def test_gateway_requires_schema_fields_and_reuses_only_idempotent_read_tool():
    ledger = RunLedger()
    ledger.begin("find evidence")
    gateway = ToolCallGateway(ledger)
    registry = _Registry()
    calls = []

    missing = gateway.execute(registry, "clinical_kb", {}, lambda: ToolResult(True))
    assert not missing.success
    assert ledger.active_status() == RunStatus.AWAITING_INPUT

    # A new user turn supersedes the clarification run before executing.
    ledger.begin("find pancreatic evidence")
    first = gateway.execute(
        registry,
        "clinical_kb",
        {"query": "pancreatic dose constraint"},
        lambda: calls.append("called") or ToolResult(True, data={"sources": 1}),
        workspace_revision=4,
    )
    second = gateway.execute(
        registry,
        "clinical_kb",
        {"query": "pancreatic dose constraint"},
        lambda: calls.append("called") or ToolResult(True, data={"sources": 2}),
        workspace_revision=4,
    )

    assert first.success and second.success
    assert calls == ["called"]
    assert second.metadata["reused_idempotent_result"] is True


def test_gateway_never_caches_live_ui_inspection_without_a_fresh_snapshot():
    """The current viewer state is case-local and must be observed each time."""
    ledger = RunLedger()
    ledger.begin("inspect active viewer")
    gateway = ToolCallGateway(ledger)
    registry = _Registry()
    calls = []

    first = gateway.execute(
        registry,
        "ui_inspector",
        {"scope": "viewer"},
        lambda: calls.append("first") or ToolResult(True, data={"slice": 12}),
    )
    second = gateway.execute(
        registry,
        "ui_inspector",
        {"scope": "viewer"},
        lambda: calls.append("second") or ToolResult(True, data={"slice": 13}),
    )

    assert first.success and second.success
    assert calls == ["first", "second"]
    assert not second.metadata.get("reused_idempotent_result")


def test_gateway_accepts_server_injected_opaque_image_but_keeps_object_validation_strict():
    """SimpleITK images are trusted server values, not JSON object payloads."""
    ledger = RunLedger()
    ledger.begin("segment ctv")
    gateway = ToolCallGateway(ledger)
    registry = _Registry()

    result = gateway.execute(
        registry,
        "ctv_segmentation",
        {"image": object()},
        lambda: ToolResult(True, data={"ok": True}),
    )
    assert result.success

    invalid = gateway.execute(
        registry,
        "ui_inspector",
        {"scope": object()},
        lambda: ToolResult(True),
    )
    assert not invalid.success
    assert invalid.error == "Invalid parameter type for scope"


def test_provider_tool_schema_hides_server_injected_fields():
    """Providers must never be asked to serialize workspace-owned images."""
    from agent_runtime.core import ToolRegistry

    class _NamedTool(_Tool):
        name = "ctv_segmentation"

    registry = ToolRegistry()
    registry.register(_NamedTool({
        "type": "object",
        "properties": {
            "image": {"type": "object", "x-server-injected": True},
            "image_path": {"type": "string"},
        },
    }))
    tool = registry.to_openai_tools()[0]["function"]["parameters"]
    assert "image" not in tool["properties"]
    assert "image_path" in tool["properties"]


def test_local_turn_policy_shortcuts_only_low_risk_requests():
    from agent_runtime.turn_policy import classify_local_turn, filter_tool_schemas

    greeting = classify_local_turn("\u4f60\u597d")
    assert greeting.intent == "small_talk"
    assert not greeting.use_router
    assert not greeting.use_completeness
    assert filter_tool_schemas([{"function": {"name": "web_search"}}], greeting) == []

    planning = classify_local_turn("\u8bf7\u6267\u884c\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212")
    assert planning.intent == "clinical_planning"
    assert planning.use_router and planning.use_completeness
    assert planning.requires_review

    external = classify_local_turn("\u8bf7\u67e5\u8be2 DeepRare \u7684\u5f00\u6e90\u4ee3\u7801")
    assert external.intent == "external_project_query"
    assert filter_tool_schemas([
        {"function": {"name": "web_search"}},
        {"function": {"name": "filesystem_browser"}},
    ], external) == [{"function": {"name": "web_search"}}]


def test_segmentation_intent_and_site_followup_are_not_knowledge_queries():
    from agent_runtime.turn_policy import classify_local_turn

    direct = classify_local_turn("\u8bf7\u6267\u884cCTV\u5206\u5272")
    assert direct.intent == "segmentation"
    assert "ctv_segmentation" in direct.allow_tools
    followup = classify_local_turn("\u80f0\u817a", pending_tumor_site=True)
    assert followup.intent == "segmentation"
    assert followup.use_completeness


def test_tool_schema_cache_invalidates_when_registry_changes():
    from agent_runtime.core import ToolRegistry

    class _NamedTool(_Tool):
        def __init__(self, name):
            super().__init__({"type": "object", "properties": {}})
            self.name = name
            self.description = name

    registry = ToolRegistry()
    registry.register(_NamedTool("first"))
    first = registry.to_openai_tools()
    assert registry.to_openai_tools() is first
    registry.register(_NamedTool("second"))
    assert {item["function"]["name"] for item in registry.to_openai_tools()} == {"first", "second"}


def test_restored_running_run_is_archived_as_interrupted_not_resumed():
    ledger = RunLedger()
    ledger.begin("start planning")
    restored = RunLedger()
    restored.restore_state(ledger.export_state())

    assert restored.active_id() is None
    assert restored.history[-1]["status"] == "interrupted"


def test_restored_clarification_is_not_mislabeled_as_interrupted():
    ledger = RunLedger()
    ledger.begin("plan a case")
    ledger.transition(RunStatus.AWAITING_INPUT, "clinical.tumor_site_required")
    restored = RunLedger()
    restored.restore_state(ledger.export_state())

    assert restored.active_id() is None
    assert restored.history[-1]["status"] == RunStatus.AWAITING_INPUT.value


def test_streaming_tool_callbacks_are_turn_local_after_cancellation():
    """A cancelled worker must not inject progress into the next turn's trace."""
    source = (Path(__file__).resolve().parents[1] / "agent_runtime" / "llm_runtime.py").read_text(encoding="utf-8")

    assert "self._pending_callback_events" not in source
    assert "callback_events_lock" in source
    assert "if _cancelled():\n                        return" in source
