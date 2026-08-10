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
    _SUPPORTED_AUTOMATIC_CTV_TYPES = frozenset({
        "nnunet_pancreatic",
        "biomedparse_liver_tumor",
        "biomedparse_kidney_lesion",
        "biomedparse_lung_lesion",
        "biomedparse_colon_primary",
        "biomedparse_head_neck_cancer",
    })

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


def test_open_anatomy_request_routes_to_generic_biomedparse_mask():
    harness = _DirectHarness(_Memory({"ct_path": "/case/ct.nii"}))
    calls = harness._detect_tool_request("\u8bf7\u5206\u5272\u809d\u810f")

    assert [call["tool"] for call in calls] == ["biomedparse_segmentation"]
    assert calls[0]["params"]["target"] == "liver"
    assert calls[0]["params"]["prompt"] == "liver"


def test_open_anatomy_request_does_not_override_ctv_workflow():
    harness = _DirectHarness(
        _Memory({"ct_path": "/case/ct.nii", "tumor_type_used": "nnunet_pancreatic"})
    )
    calls = harness._detect_tool_request("\u5206\u5272\u80f0\u817a\u80bf\u7624\u7684 CTV")

    assert calls is None or all(call["tool"] != "biomedparse_segmentation" for call in calls)


def test_patient_tumor_measurement_question_routes_to_ctv_segmentation():
    harness = _DirectHarness(_Memory({"ct_path": "/case/ct.nii"}))
    calls = harness._detect_tool_request(
        "\u4f60\u597d\uff0c\u6211\u4e0a\u4f20\u4e86\u4e00\u540d\u809d\u810f\u80bf\u7624\u60a3\u8005CT\uff0c\u8bf7\u5e2e\u6211\u5206\u6790\u80bf\u7624\u5728\u54ea\uff0c\u6709\u591a\u5927"
    )

    assert [call["tool"] for call in calls] == ["ctv_segmentation"]
    assert calls[0]["params"]["tumor_type"] == "biomedparse_liver_tumor"


def test_tumor_site_clarification_restores_the_original_full_planning_workflow():
    """A missing site must pause planning, not downgrade it to CTV only."""
    harness = _DirectHarness(_Memory({"ct_path": "/case/ct.nii"}))

    first = harness._detect_tool_request("\u8bf7\u6267\u884c\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212")

    assert first is None
    pending = harness.memory.retrieve("pending_clarification")
    assert pending["requested_actions"] == ["plan_full"]
    assert pending["requested_workflow"] == "clinical_planning"

    resumed = harness._detect_tool_request("\u80f0\u817a")

    assert [call["tool"] for call in resumed] == [
        "ctv_segmentation",
        "oar_segmentation",
        "planning_pipeline",
        "surgical_guide",
    ]
    assert resumed[0]["params"]["tumor_type"] == "nnunet_pancreatic"


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


def test_failed_planning_never_runs_the_dependent_surgical_guide():
    class Harness(_DirectHarness):
        def __init__(self):
            super().__init__(_Memory())
            self.calls = []

        def _execute_tool_with_memory(self, tool, _params):
            self.calls.append(tool)
            if tool == "planning_pipeline":
                return ToolResult(success=False, error="planning failed")
            return ToolResult(success=True, message="unexpected guide execution")

    harness = Harness()
    steps = []
    harness._execute_direct_tools([
        {"tool": "planning_pipeline", "params": {"step": "full"}},
        {"tool": "surgical_guide", "params": {"action": "generate"}},
    ], steps, [0])

    assert harness.calls == ["planning_pipeline"]
    assert steps[0]["status"] == "error"
    assert all(step.get("tool") != "surgical_guide" for step in steps)


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


def test_ctv_normalization_recovers_catalog_model_and_organ_aliases():
    harness = _DirectHarness(_Memory({"ct_path": "/tmp/case.nii.gz"}))
    normalized = harness._normalize_ctv_tool_params({
        "ct_image_path": "/tmp/case.nii.gz",
        "model": "biomedparse_liver_tumor",
        "organ": "liver",
    })

    assert normalized["image_path"] == "/tmp/case.nii.gz"
    assert normalized["tumor_type"] == "biomedparse_liver_tumor"
    assert all(key not in normalized for key in ("model", "organ", "ct_image_path"))

    calls = harness._normalize_tool_params([{
        "tool": "ctv_segmentation",
        "params": {"model": "biomedparse_liver_tumor", "organ": "liver"},
    }])
    assert calls[0]["params"]["tumor_type"] == "biomedparse_liver_tumor"
    assert "model" not in calls[0]["params"]


def test_ctv_normalization_prefers_a_valid_site_over_an_unknown_model_alias():
    harness = _DirectHarness(_Memory())

    normalized = harness._normalize_ctv_tool_params({
        "ct_image_path": "/case/ct.nii",
        "model": "stale_catalog_model_v0",
        "organ": "liver",
    })

    assert normalized["image_path"] == "/case/ct.nii"
    assert normalized["tumor_type"] == "biomedparse_liver_tumor"


def test_ctv_normalization_does_not_let_an_unknown_model_hide_user_context():
    harness = _DirectHarness(_Memory())
    normalized = harness._normalize_ctv_tool_params(
        {"model": "stale_catalog_model_v0"},
        message=(
            "I uploaded a liver tumor CT; please analyze where the tumor is "
            "and how large it is"
        ),
    )

    assert normalized["tumor_type"] == "biomedparse_liver_tumor"


def test_ctv_tool_boundary_prefers_a_valid_organ_over_a_stale_model_id():
    from tool_factory.CTV_seg import resolve_ctv_tumor_type

    assert resolve_ctv_tumor_type({
        "model": "stale_catalog_model_v0",
        "organ": "liver",
    }) == "biomedparse_liver_tumor"


def test_ctv_tool_boundary_reports_missing_ct_after_resolving_site_aliases():
    from tool_factory.CTV_seg import CTVSegmentationTool

    result = CTVSegmentationTool()._execute(
        model="biomedparse_liver_tumor",
        organ="liver",
    )

    assert not result.success
    assert "image" in (result.error or "").lower()
    assert "tumor site is required" not in (result.error or "").lower()


def test_ctv_normalization_recovers_site_from_current_user_message():
    memory = _Memory({"ct_path": "/tmp/case.nii.gz"})
    memory.conversation = [{
        "role": "user",
        "content": "你好，我上传了一名肝脏肿瘤患者CT，请帮我分析肿瘤在哪，有多大",
    }]
    harness = _DirectHarness(memory)

    normalized = harness._normalize_ctv_tool_params({"image_path": "/tmp/case.nii.gz"})

    assert normalized["tumor_type"] == "biomedparse_liver_tumor"


def test_liver_aliases_use_the_biomedparse_route_before_ctv_validation():
    """A liver planning request must not emit the retired ``voco_liver``.

    The CTV tool accepts legacy aliases for old Sessions, but automatic
    planning and LLM tool calls must already be canonical before schema/tool
    validation starts.
    """
    harness = _DirectHarness(_Memory({"ct_path": "/tmp/case.nii.gz"}))
    harness._SUPPORTED_AUTOMATIC_CTV_TYPES = frozenset({
        "nnunet_pancreatic",
        "biomedparse_liver_tumor",
    })

    assert harness._map_tumor_type("liver") == "biomedparse_liver_tumor"
    assert harness._map_tumor_type("voco_liver") == "biomedparse_liver_tumor"
    assert harness._normalize_ctv_tool_params({
        "tumor_type": "biomedparse_v2_liver_tumor",
    })["tumor_type"] == "biomedparse_liver_tumor"



def test_explicit_seed_implant_plan_runs_complete_local_delivery_chain():
    """A clear plan request must not wait for router rediscovery.

    The sequence intentionally leaves each segmentation result observable by
    the browser before planning starts, then generates a guide from the
    resulting needle geometry.
    """
    harness = _DirectHarness(_Memory({
        "ct_path": "/tmp/case.nii.gz",
        "tumor_type_used": "nnunet_pancreatic",
    }))

    calls = harness._detect_tool_request(
        "\u8bf7\u6267\u884c\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212"
    )

    assert [call["tool"] for call in calls] == [
        "ctv_segmentation",
        "oar_segmentation",
        "planning_pipeline",
        "surgical_guide",
    ]
    assert calls[0]["params"]["tumor_type"] == "nnunet_pancreatic"
    assert calls[2]["params"]["step"] == "full"
    assert calls[3]["params"] == {"action": "generate"}
