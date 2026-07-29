"""Regression tests for explicit segmentation reruns and truthful tool status."""

from agent_runtime.response_tools import ResponseToolMixin
from tool_factory import ToolResult


class _Memory:
    user_lang = "en"

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.conversation = []

    def retrieve(self, key, default=None):
        return self.values.get(key, default)

    def store(self, key, value):
        self.values[key] = value

    def add_message(self, role, content):
        self.conversation.append({"role": role, "content": content})


class _DirectHarness(ResponseToolMixin):
    _SUPPORTED_AUTOMATIC_CTV_TYPES = frozenset({"nnunet_pancreatic"})

    def __init__(self, memory):
        self.memory = memory

    def _execute_tool_with_memory(self, _tool, _params):
        return ToolResult(success=False, error="empty CTV mask")

    def _format_tool_result(self, _tool, result, lang="en"):
        return result.error or result.message

    def _build_direct_response(self, steps, _lang):
        return "".join(step.get("result", "") for step in steps)

    def _synthesize_with_llm(self, raw, _steps, _lang, _message, _query_type):
        return raw


def test_force_reexecution_requires_an_explicit_override_signal():
    assert ResponseToolMixin._force_reexecution_requested("请忽略现有结果再分割")
    assert ResponseToolMixin._force_reexecution_requested("run it again", {"overwrite": True})
    assert not ResponseToolMixin._force_reexecution_requested("查看已有分割结果")


def test_generic_repeat_preserves_the_last_segmentation_scope():
    harness = _DirectHarness(_Memory({"last_segmentation_target": "oar"}))
    assert harness._segmentation_scope("再启动一次分割") == "oar"
    harness.memory.store("last_segmentation_target", "ctv")
    assert harness._segmentation_scope("run it again") == "ctv"


def test_generic_forced_repeat_routes_only_to_the_inherited_oar_scope():
    harness = _DirectHarness(
        _Memory({"ct_path": "/case/ct.nii", "last_segmentation_target": "oar"})
    )
    calls = harness._detect_tool_request("忽略现有结果，再启动一次分割")
    assert [call["tool"] for call in calls] == ["oar_segmentation"]
    assert calls[0]["params"]["force_reexecution"] is True


def test_failed_direct_tool_is_not_marked_done():
    harness = _DirectHarness(_Memory())
    steps = []
    harness._execute_direct_tools(
        [{"tool": "ctv_segmentation", "params": {"force_reexecution": True}}],
        steps,
        [0],
    )
    assert steps[0]["status"] == "error"
    assert "empty CTV" in steps[0]["result"]


def test_ctv_followup_inherits_site_from_recent_user_message():
    memory = _Memory({"ct_path": "/tmp/case.nii.gz"})
    memory.conversation = [
        {"role": "user", "content": "我上传的是胰腺肿瘤患者的CT"},
        {"role": "assistant", "content": "已收到"},
    ]
    harness = _DirectHarness(memory)

    routed = harness._detect_tool_request("请再执行一次CTV分割")

    assert routed[0]["tool"] == "ctv_segmentation"
    assert routed[0]["params"]["tumor_type"] == "nnunet_pancreatic"


def test_ctv_normalization_uses_persisted_site_for_llm_tool_call():
    memory = _Memory({
        "ct_path": "/tmp/case.nii.gz",
        "tumor_type_used": "nnunet_pancreatic",
    })
    harness = _DirectHarness(memory)

    assert harness._normalize_ctv_tool_params({})["tumor_type"] == "nnunet_pancreatic"
