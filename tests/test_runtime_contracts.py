"""Regression tests for provider-neutral agent runtime contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
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


def test_query_metrics_workspace_inputs_are_server_injected():
    """A model must not be able to break a live metric read with fake arrays."""
    from tool_factory.viewer_command.query_metrics import QueryMetricsTool

    properties = QueryMetricsTool().input_schema["properties"]
    for field in (
        "metrics",
        "ctv_array",
        "oar_array",
        "organ_names",
        "ct_spacing",
        "ct_data",
        "seed_positions",
        "total_seeds",
    ):
        assert properties[field]["x-server-injected"] is True

    # Only the user-selectable metric type should reach the provider schema.
    from agent_runtime.core import ToolRegistry

    class _NamedMetricsTool(_Tool):
        name = "query_metrics"

    registry = ToolRegistry()
    registry.register(_NamedMetricsTool(QueryMetricsTool().input_schema))
    provider_schema = registry.to_openai_tools()[0]["function"]["parameters"]
    assert list(provider_schema["properties"]) == ["metric_type"]


def test_safety_validator_plan_is_server_injected():
    """The provider selects a check; it never serializes clinical plan data."""
    from agent_runtime.core import ToolRegistry
    from tool_factory.safety_validator import SafetyValidatorTool

    assert SafetyValidatorTool().input_schema["properties"]["plan"]["x-server-injected"] is True

    class _NamedSafetyTool(_Tool):
        name = "safety_validator"

    registry = ToolRegistry()
    registry.register(_NamedSafetyTool(SafetyValidatorTool().input_schema))
    provider_schema = registry.to_openai_tools()[0]["function"]["parameters"]
    assert "plan" not in provider_schema["properties"]
    assert "action" in provider_schema["properties"]


def test_agent_query_metrics_uses_live_workspace_values_without_numpy_truth_checks():
    """A follow-up metric read must not validate or truth-test model arrays."""
    import numpy as np

    from AgenticSys import BrachyAgent
    from agent_runtime.core import ToolRegistry
    from tool_factory.viewer_command.query_metrics import QueryMetricsTool

    class _Memory:
        def __init__(self):
            self.values = {
                "dose_metrics": {"v100": 0.914, "d90": 122.5},
                "ct_spacing": np.asarray([0.7, 0.7, 5.0]),
                "seed_positions": np.asarray([[1.0, 2.0, 3.0]]),
                "total_seeds": np.int64(1),
            }
            self.conversation_state = {"last_tool_calls": []}
            self.logged = []

        def retrieve(self, key):
            return self.values.get(key)

        def get_ui_state(self):
            return {}

        def store(self, key, value):
            self.values[key] = value

        def log_tool_call(self, *args):
            self.logged.append(args)

    memory = _Memory()
    registry = ToolRegistry()
    registry.register(QueryMetricsTool())
    agent = object.__new__(BrachyAgent)
    agent.memory = memory
    agent.registry = registry
    agent.run_ledger = RunLedger()
    agent.tool_gateway = ToolCallGateway(agent.run_ledger)

    # These are the kinds of values that previously leaked from an LLM call.
    params = {
        "metric_type": "dose_metrics",
        "metrics": "stale model text",
        "ctv_array": "array([...])",
        "oar_array": "array([...])",
        "organ_names": "stale names",
        "ct_spacing": "stale spacing",
        "total_seeds": "stale count",
    }

    result = agent._execute_tool_with_memory("query_metrics", params)

    assert result.success is True
    assert result.data["V100"] == 0.914
    assert params["metrics"] == memory.values["dose_metrics"]
    assert "ctv_array" not in params
    assert "oar_array" not in params
    assert isinstance(params["ct_spacing"], np.ndarray)
    assert isinstance(params["total_seeds"], np.integer)
    assert memory.logged


def test_agent_safety_validator_reads_hydrated_active_planning_snapshot():
    """A restored Session must validate the same Planning that metrics reads use."""
    from AgenticSys import BrachyAgent
    from agent_runtime.core import ToolRegistry
    from tool_factory.safety_validator import SafetyValidatorTool

    class _Memory:
        def __init__(self):
            planning_id = "planning-restored"
            self.values = {
                "active_planning_id": planning_id,
                "planning_run_id": planning_id,
                "tumor_type_used": "nnunet_pancreatic",
                f"planning_run:{planning_id}": {
                    "dose_metrics": {
                        "v100": 0.903,
                        "v150": 0.6543,
                        "v200": 0.4407,
                        "d90": 120.59,
                    },
                    "plan_config": {"prescription_gy": 120.0},
                    "total_seeds": 35,
                    "num_trajectories": 5,
                },
            }
            self.conversation_state = {"last_tool_calls": []}
            self.logged = []

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def get_ui_state(self):
            return {}

        def store(self, key, value):
            self.values[key] = value

        def log_tool_call(self, *args):
            self.logged.append(args)

    memory = _Memory()
    registry = ToolRegistry()
    registry.register(SafetyValidatorTool())
    agent = object.__new__(BrachyAgent)
    agent.memory = memory
    agent.registry = registry
    agent.run_ledger = RunLedger()
    agent.tool_gateway = ToolCallGateway(agent.run_ledger)
    params = {"action": "validate"}

    result = agent._execute_tool_with_memory("safety_validator", params)

    assert result.success is True
    assert params["plan"]["planning_id"] == "planning-restored"
    assert params["plan"]["metrics"]["v100"] == 0.903
    assert params["plan"]["total_seeds"] == 35
    assert result.data["status"] == "conditional"
    assert result.data["clinical_efficacy_assessed"] is False
    assert result.data["surgical_feasibility_assessed"] is False
    assert memory.logged


def test_local_turn_policy_shortcuts_only_low_risk_requests():
    from agent_runtime.turn_policy import classify_local_turn, filter_tool_schemas

    greeting = classify_local_turn("\u4f60\u597d")
    assert greeting.intent == "small_talk"
    assert not greeting.use_router
    assert not greeting.use_completeness
    assert filter_tool_schemas([{"function": {"name": "web_search"}}], greeting) == []

    planning = classify_local_turn("\u8bf7\u6267\u884c\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212")
    assert planning.intent == "clinical_planning"
    assert not planning.use_router and planning.use_completeness
    assert planning.requires_review

    external = classify_local_turn("\u8bf7\u67e5\u8be2 DeepRare \u7684\u5f00\u6e90\u4ee3\u7801")
    assert external.intent == "external_project_query"
    assert filter_tool_schemas([
        {"function": {"name": "web_search"}},
        {"function": {"name": "filesystem_browser"}},
    ], external) == [{"function": {"name": "web_search"}}]


def test_viewer_result_display_is_a_provider_independent_ui_action():
    from agent_runtime.core import ToolResultPipeline
    from agent_runtime.response_tools import ResponseToolMixin
    from agent_runtime.turn_policy import classify_local_turn
    from tool_factory.ui_controller import UIControllerTool

    message = "将结果在viewer中显示出来啊"
    policy = classify_local_turn(message)
    assert policy.intent == "viewer_display"
    assert policy.direct_execution is True
    assert policy.use_router is False
    assert policy.use_completeness is False
    assert policy.allow_tools == frozenset({"ui_controller"})
    assert policy.execution_grants == frozenset({"ui_controller"})

    # The detector must be able to materialize the complete action without a
    # Memory/LLM object: this is the contract used by the direct stream path.
    calls = ResponseToolMixin()._detect_tool_request(message)
    assert calls == [{
        "id": "tool_ui_refresh_planning_viewer",
        "tool": "ui_controller",
        "params": {"actions": [{
            "target": "viewer.refresh_planning",
            "command": "run",
        }]},
    }]

    # Server-side validation is the hard boundary before the browser receives
    # the action, so a provider outage cannot turn this into an unvalidated UI
    # command.
    result = UIControllerTool().execute(**calls[0]["params"])
    assert result.success is True
    assert result.metadata["actions"] == calls[0]["params"]["actions"]
    zh = ToolResultPipeline.format("ui_controller", result, "zh")
    en = ToolResultPipeline.format("ui_controller", result, "en")
    assert "Viewer" in zh
    assert "规划结果" in zh
    assert "planning result" in en

    frontend = Path(__file__).resolve().parents[1] / "web/app/static/js/brachybot-ui-api.js"
    frontend_source = frontend.read_text(encoding="utf-8")
    assert "target === 'viewer.refresh_planning'" in frontend_source
    assert "backgroundRestore: true" in frontend_source
    assert "preserveViewerState: false" in frontend_source


def test_viewer_result_display_stream_bypasses_llm_and_emits_refresh_action():
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    from agent_runtime.response_tools import ResponseToolMixin

    class Memory:
        def __init__(self):
            self.user_lang = "zh"
            self.conversation = []

        def add_message(self, role, content):
            self.conversation.append({"role": role, "content": content})

    class Registry:
        @staticmethod
        def get(name):
            assert name == "ui_controller"
            return object()

    class Workflow(ResponseToolMixin, ChatWorkflowMixin):
        def __init__(self):
            self.memory = Memory()
            self.registry = Registry()
            self.multi_agent_wrapper = None
            self.brain_available = True
            self._turn_token = "turn-viewer-display"
            self.llm_called = False

        def _begin_turn(self, _message):
            return None

        def _current_turn_token(self):
            return self._turn_token

        def _is_turn_cancelled(self, _token):
            return False

        def _pending_tumor_site_clarification(self):
            return False

        def _detect_tool_request(self, message):
            assert message == "将结果在viewer中显示出来啊"
            return [{
                "id": "tool_ui_refresh_planning_viewer",
                "tool": "ui_controller",
                "params": {"actions": [{
                    "target": "viewer.refresh_planning",
                    "command": "run",
                }]},
            }]

        def _execute_tool_with_memory(self, name, params):
            assert name == "ui_controller"
            return ToolResult(
                success=True,
                message="viewer.refresh_planning: run",
                metadata={"actions": params["actions"]},
            )

        def _current_execution_authorization(self):
            return None

        def _record_experience(self, *_args, **_kwargs):
            return None

        def _finish_turn(self, _response):
            return None

        def _run_llm_function_calling_stream(self, *_args, **_kwargs):
            self.llm_called = True
            raise AssertionError("viewer display must not call the LLM")

    workflow = Workflow()
    events = list(workflow.chat_with_stream("将结果在viewer中显示出来啊"))
    parsed = []
    for event in events:
        lines = event.splitlines()
        if len(lines) >= 2 and lines[0].startswith("event: "):
            parsed.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))

    assert workflow.llm_called is False
    controller_steps = [
        data for event, data in parsed
        if event == "step" and data.get("tool") == "ui_controller"
    ]
    assert controller_steps[-1]["status"] == "done"
    assert controller_steps[-1]["metadata"]["actions"] == [{
        "target": "viewer.refresh_planning",
        "command": "run",
    }]
    response = next(data for event, data in parsed if event == "response")
    assert response["llm_meta"]["route"] == "direct_tool"
    assert "Viewer" in response["response"]
    assert "不会重新运行规划" in response["response"]


def test_viewer_script_dependency_contract_is_cache_busted_and_syntax_safe():
    root = Path(__file__).resolve().parents[1]
    index = (root / "web/app/index.html").read_text(encoding="utf-8")
    ui_api = (root / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    manual_3d_path = root / "web/app/static/js/brachybot-3d-manual.js"
    manual_3d = manual_3d_path.read_text(encoding="utf-8")

    # A browser can retain independent classic-script URLs. Bump the query
    # versions whenever this cross-bundle contract changes, otherwise an old
    # 3D bundle can coexist with a new UI action bundle and hide its parse
    # failure as a missing global helper.
    assert 'brachybot-ui-api.js?v=49' in index
    assert 'brachybot-3d-manual.js?v=69' in index
    assert "window._normalizeTrajectoryId = function _normalizeTrajectoryId" in ui_api

    # This exact malformed expression previously prevented the entire 3D
    # bundle from executing, which made _normalizeTrajectoryId unavailable to
    # DVH hydration and left the 3D scene empty.
    assert ".sort((a, b) => a - b))]" in manual_3d
    assert ".sort((a, b) => a - b)]" not in manual_3d

    # Use the host's JavaScript parser when available; the remote production
    # image does not require Node, so the source-contract assertions above are
    # intentionally the non-Node fallback.
    node = shutil.which("node") or shutil.which("nodejs")
    if node:
        for path in (
            root / "web/app/static/js/brachybot-ui-api.js",
            root / "web/app/static/js/brachybot-3d-manual.js",
            root / "web/app/static/js/brachybot-viewer-layout.js",
            root / "web/app/static/js/brachybot-dvh-planning.js",
            root / "web/app/static/js/brachybot-viewer-volume.js",
        ):
            subprocess.run([node, "--check", str(path)], check=True)


def test_segmentation_intent_and_site_followup_are_not_knowledge_queries():
    from agent_runtime.turn_policy import classify_local_turn

    direct = classify_local_turn("\u8bf7\u6267\u884cCTV\u5206\u5272")
    assert direct.intent == "segmentation"
    assert "ctv_segmentation" in direct.allow_tools
    followup = classify_local_turn("\u80f0\u817a", pending_tumor_site=True)
    assert followup.intent == "segmentation"
    assert followup.use_completeness


def test_surgical_guide_generation_is_a_deterministic_clinical_action():
    from agent_runtime.turn_policy import classify_local_turn

    policy = classify_local_turn("\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f")

    assert policy.intent == "surgical_guide_generation"
    assert not policy.use_router
    assert policy.use_completeness
    assert "surgical_guide" in policy.allow_tools
    assert "code_executor" not in policy.allow_tools


def test_viewing_a_surgical_guide_remains_read_only():
    from agent_runtime.turn_policy import classify_local_turn

    policy = classify_local_turn("\u67e5\u770b\u5f53\u524d\u624b\u672f\u5bfc\u677f")

    assert policy.intent == "session_content_query"


def test_patient_tumor_location_question_uses_image_segmentation_route():
    from agent_runtime.turn_policy import classify_local_turn

    policy = classify_local_turn(
        "\u4f60\u597d\uff0c\u6211\u4e0a\u4f20\u4e86\u4e00\u540d\u809d\u810f\u80bf\u7624\u60a3\u8005CT\uff0c\u8bf7\u5e2e\u6211\u5206\u6790\u80bf\u7624\u5728\u54ea\uff0c\u6709\u591a\u5927"
    )

    assert policy.intent == "semantic_action"
    assert policy.use_completeness



def test_monitor_stop_request_is_ui_control_not_knowledge_query():
    from agent_runtime.turn_policy import classify_local_turn

    for message in (
        "\u8bf7\u505c\u6b62monitor",
        "\u8bf7\u505c\u6b62\u76d1\u6d4b",
        "stop monitoring please",
        "\u7ed3\u675f\u76d1\u6d4b",
    ):
        policy = classify_local_turn(message)
        assert policy.intent == "ui_control", f"{message!r} -> {policy.intent}"
        assert "ui_controller" in policy.allow_tools
        assert not policy.use_router


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


def test_ui_controller_registers_manual_mask_commands():
    from tool_factory.ui_controller import CONTROL_REGISTRY

    for key in (
        "mask.create", "mask.finalize", "mask.threshold",
        "mask.rename", "mask.move", "mask.delete",
        "viewer.tool", "viewer.threshold",
    ):
        assert key in CONTROL_REGISTRY, f"{key} missing from ui_controller registry"
        assert CONTROL_REGISTRY[key].get("description"), f"{key} lacks a description"

    assert "annotate" in CONTROL_REGISTRY["viewer.tool"]["values"]
    assert "eraser" in CONTROL_REGISTRY["viewer.tool"]["values"]
    assert CONTROL_REGISTRY["mask.move"]["values"] == ["ctv", "oar"]


def test_ui_controller_registers_parameter_targets():
    from tool_factory.ui_controller import CONTROL_REGISTRY, UIControllerTool

    for key in (
        "parameter.catalog", "parameter.set", "planning.hyperparams.set",
        "surgical_guide.parameters.set", "tree.color",
        "report.field.set", "report.template.set",
    ):
        assert key in CONTROL_REGISTRY, f"{key} missing from ui_controller registry"
        assert CONTROL_REGISTRY[key].get("description"), f"{key} lacks a description"

    tool = UIControllerTool()
    # Valid target/command passes server-side validation.
    ok = tool.execute(actions=[{"target": "parameter.catalog", "command": "inspect"}])
    assert ok.success is True
    ok = tool.execute(actions=[{
        "target": "parameter.set", "command": "set",
        "value": '{"id":"seedRadius","value":0.5}',
    }])
    assert ok.success is True
    ok = tool.execute(actions=[{
        "target": "surgical_guide.parameters.set", "command": "set",
        "value": '{"plate_thickness_mm":4}',
    }])
    assert ok.success is True
    ok = tool.execute(actions=[{
        "target": "tree.color", "command": "set",
        "value": '{"id":"organ_1","color":"#ff0000"}',
    }])
    assert ok.success is True
    ok = tool.execute(actions=[{
        "target": "report.field.set", "command": "set",
        "value": '{"key":"planning.prescriptionGy","value":120}',
    }])
    assert ok.success is True
    # Group visibility accepts the extended mask/planning groups.
    ok = tool.execute(actions=[{"target": "tree.group.visibility", "command": "set", "value": "masks,show"}])
    assert ok.success is True
    # Unknown target still rejected.
    bad = tool.execute(actions=[{"target": "parameter.nope", "command": "run"}])
    assert bad.success is False


def test_ui_controller_separates_panel_maximize_camera_fit_and_zoom_delta():
    from agent_runtime.core import ToolResultPipeline
    from tool_factory.ui_controller import UIControllerTool

    tool = UIControllerTool()

    # A delta is not an absolute zoom percentage.  This was the regression
    # behind the user-visible "20 out of range [50, 300]" error.
    delta = tool.execute(actions=[{
        "target": "viewer.zoom", "command": "increase", "value": 20,
    }])
    assert delta.success is True

    absolute_too_small = tool.execute(actions=[{
        "target": "viewer.zoom", "command": "set", "value": 20,
    }])
    assert absolute_too_small.success is False
    hint = absolute_too_small.metadata["repair_hints"][0]
    assert hint["value_semantics"] == "absolute"
    assert hint["accepted_range"] == [50, 300]
    localized = ToolResultPipeline.format("ui_controller", absolute_too_small, "zh")
    assert "界面操作未执行" in localized
    assert "Error:" not in localized

    # Maximizing the 3D card and fitting its camera are separate capabilities.
    maximize = tool.execute(actions=[{
        "target": "viewer.fullscreen", "command": "toggle", "value": "3d",
    }])
    fit = tool.execute(actions=[{"target": "3d.fit", "command": "run"}])
    assert maximize.success is True
    assert fit.success is True


def test_ui_inspector_reports_real_viewer_capabilities_from_dom_contracts():
    from tool_factory.ui_inspector import UIInspectorTool

    capabilities = UIInspectorTool()._scan_ui_elements()["action_capabilities"]
    actions = [item["action"] for item in capabilities]
    assert {"target": "viewer.fullscreen", "command": "toggle", "value": "3d"} in actions
    assert {"target": "viewer.zoom", "command": "set", "value_source": "control"} in actions
    assert {"target": "viewer.fit_all", "command": "run"} in actions


def test_surgical_guide_schema_enumerates_manufacturing_parameters():
    from tool_factory.surgical_guide import SurgicalGuideTool

    props = SurgicalGuideTool().input_schema["properties"]["parameters"]["properties"]
    for name in (
        "skin_threshold_hu", "skin_clearance_mm", "plate_thickness_mm",
        "patch_margin_mm", "channel_radius_mm", "sleeve_outer_radius_mm",
        "sleeve_outward_mm", "sleeve_inward_mm", "geometry_resolution_mm",
    ):
        assert name in props, f"{name} missing from surgical_guide parameter schema"
        assert "minimum" in props[name] and "maximum" in props[name]


def test_honest_failure_summary_detects_failed_tools():
    from agent_runtime.llm_runtime import _failed_steps_summary, _HONEST_FAILURE_PROMPT

    assert _failed_steps_summary([]) is None
    assert _failed_steps_summary([
        {"type": "tool", "tool": "web_search", "status": "done", "result": "ok"},
    ]) is None
    summary = _failed_steps_summary([
        {"type": "tool", "tool": "ctv_segmentation", "status": "error",
         "result": {"error": "No CT image loaded"}},
        {"type": "tool", "tool": "planning_pipeline", "status": "done", "result": "ok"},
    ])
    assert summary is not None
    assert "ctv_segmentation" in summary and "No CT image loaded" in summary
    # The honest-failure prompt must never tell the LLM to claim success.
    rendered = _HONEST_FAILURE_PROMPT.format(failures=summary)
    assert "Do NOT claim success" in rendered
    assert "clinical efficacy, procedural safety, or approval" in rendered
    assert "tool executed" not in rendered.lower() or "Do NOT say 'tool executed'" in rendered


def test_system_prompts_separate_plan_quality_from_patient_outcome():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    system_prompt = (root / "config/prompts/system_prompt.md").read_text(encoding="utf-8")
    medical_prompt = (root / "config/prompts/medical_safety.md").read_text(encoding="utf-8")

    assert "dosimetric plan quality, surgical/geometric feasibility, and patient treatment efficacy" in system_prompt
    assert "they do not by themselves establish" in system_prompt
    assert "not direct evidence of patient-level" in medical_prompt


class _WebResult:
    success = True
    message = "Found 3 results"
    display = None
    error = None
    data = {
        "results": [
            {"title": "DeepRare", "snippet": "clinical phenotype", "url": "https://x.com/1"},
            {"title": "DeepRare KB", "snippet": "genetic variant", "url": "https://x.com/2"},
        ],
        "sources": ["https://x.com/1", "https://x.com/2"],
        "quality": "good",
    }
    metadata = {"quality": "good"}


def test_web_tool_results_format_clean_language_matched_digest():
    from agent_runtime.core import ToolResultPipeline

    zh = ToolResultPipeline.format("web_search", _WebResult(), "zh")
    en = ToolResultPipeline.format("web_search", _WebResult(), "en")
    # No raw LLM-facing debug text ("Found 3 results") leaks into the digest.
    assert "Found 3 results" not in zh and "Found 3 results" not in en
    assert "## 搜索结果" in zh and "来源: https://x.com/1" in zh
    assert "## Search results" in en and "Source: https://x.com/1" in en
    # Chinese digest must not mix in English labels and vice versa.
    assert "Source:" not in zh
    assert "来源:" not in en


def test_tool_fallback_prefers_clean_step_results_over_llm_digest():
    from agent_runtime.llm_runtime import _collect_tool_fallback_text

    steps = [
        {"type": "tool", "tool": "web_search", "status": "done",
         "result": "## 搜索结果\n- **DeepRare**\n  来源: https://x.com/1"},
    ]
    messages = [
        {"role": "tool", "content": "Search results:\n- DeepRare: clinical phenotype\n  Source: https://x.com/1\nFound 3 results"},
    ]
    successes, failures = _collect_tool_fallback_text(steps, messages)
    assert failures == []
    assert len(successes) >= 1
    # The clean display-formatted step result is preferred; the raw LLM-facing
    # digest must NOT be mixed into the user-facing list.
    joined = "\n".join(successes)
    assert "Search results:\n- DeepRare: clinical phenotype" not in joined


def test_local_model_checkpoints_load_with_weights_only_false():
    """VoCo CTV/OAR model checkpoints are trusted local deployment artifacts.

    PyTorch 2.6 changed torch.load's default weights_only to True, which rejects
    the numpy scalars stored in these older checkpoints and broke every
    non-pancreatic CTV model (liver, kidney, colon, lung, ...) plus the OAR
    VoCo models. Every load site must pass weights_only=False; the dose model
    loader already handles this via an explicit flag."""
    ROOT = Path(__file__).resolve().parents[1]
    files = [
        ROOT / "tool_factory/CTV_seg/voco_base.py",
        ROOT / "tool_factory/CTV_seg/prostate_tumor_voco.py",
        ROOT / "tool_factory/OAR_seg/voco_total_segmentation.py",
        ROOT / "tool_factory/OAR_seg/aorta_vessel_voco.py",
    ]
    for path in files:
        src = path.read_text(encoding="utf-8")
        assert "torch.load(" in src, f"{path.name} has no checkpoint load"
        assert "weights_only=False" in src, (
            f"{path.name} must load its trusted local checkpoint with "
            "weights_only=False (PyTorch 2.6 default True rejects numpy scalars)"
        )
