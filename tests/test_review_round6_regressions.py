import asyncio
import base64
import os
import threading
from pathlib import Path

import numpy as np
import pytest


def test_clinical_metric_units_and_exact_oar_matching():
    from agents.clinical_metrics import (
        match_constraint_name,
        normalized_fraction,
        parse_numeric,
    )

    assert parse_numeric("120 Gy") == (120.0, "gy")
    assert normalized_fraction("91.8%") == pytest.approx(0.918)
    constraints = {"bowel": {}, "small_bowel": {}, "kidney": {}}
    assert match_constraint_name("small_bowel", constraints) == "small_bowel"
    assert match_constraint_name("kidney_left", constraints) == "kidney"
    assert match_constraint_name("rectum_sigmoid", constraints) is None


def test_plan_reviewer_localizes_dynamic_target_and_oar_issues():
    from agents.plan_reviewer import PlanReviewer

    reviewer = PlanReviewer()
    result = reviewer._merge_results(
        {
            "score": 5.0,
            "issues": [{
                "metric": "V100",
                "value": 0.82,
                "threshold": 0.90,
                "operator": ">=",
                "status": "EXCEEDS",
                "unit": "fraction",
            }],
            "oar_issues": [{
                "organ": "small_bowel",
                "metric": "d2cc",
                "value": 94.9,
                "limit": 60.0,
                "status": "EXCEEDS",
            }],
            "advisory_issues": [],
            "unverified": [],
            "has_clinical_thresholds": True,
        },
        None,
        {"total_seeds": 14},
        "zh",
    )
    appendix = reviewer.format_as_appendix(result, "zh")
    assert "要求" in appendix
    assert "限值" in appendix
    assert "required" not in appendix
    assert "limit=" not in appendix


def test_router_patterns_are_session_local_and_use_word_boundaries():
    from agents.router_agent import RouterAgent

    first = RouterAgent()
    second = RouterAgent()
    first.add_intent_pattern("custom_case", ["planetary"])
    assert "custom_case" not in second.intent_patterns
    assert not first._contains_keyword("explanation", "plan")
    assert first._contains_keyword("run the plan", "plan")


def test_async_llm_callback_preserves_separate_system_role():
    from agents.base_agent import LLMCapableAgent
    from communication.protocol import AgentResponse, AgentRole

    class DummyAgent(LLMCapableAgent):
        async def process(self, _message):
            return AgentResponse(agent_role=self.role, success=True, result={})

    received = {}

    async def callback(prompt, system_prompt=None, temperature=None):
        received.update(prompt=prompt, system=system_prompt, temperature=temperature)
        return "ok"

    agent = DummyAgent(AgentRole.ROUTER, callback)
    assert asyncio.run(agent.call_llm("user data", system_prompt="trusted policy")) == "ok"
    assert received["prompt"] == "user data"
    assert received["system"] == "trusted policy"


def test_quality_gate_without_reviewers_requires_human_review():
    from quality.quality_gate import QualityGate

    result = asyncio.run(QualityGate({}).review("treatment_plan", {}))
    assert result.passed is True
    assert result.decision == "conditional"
    assert result.requires_human_review is True


def test_case_executor_rejects_missing_dependency_and_cycle(tmp_path):
    from brain.execution.case_executor import CaseExecutor
    from brain.execution.types import ExecutionStatus

    executor = CaseExecutor(tool_registry=object())
    missing = executor.execute(
        [{"id": 1, "dependencies": [2], "tool": 1}],
        output_dir=str(tmp_path / "missing"),
    )
    assert missing.status == ExecutionStatus.FAILED
    assert "missing dependencies" in missing.summary

    cyclic = executor.execute(
        [
            {"id": 1, "dependencies": [2], "tool": 1},
            {"id": 2, "dependencies": [1], "tool": 1},
        ],
        output_dir=str(tmp_path / "cycle"),
    )
    assert cyclic.status == ExecutionStatus.FAILED
    assert "cycle" in cyclic.summary


def test_rl_oar_penalty_is_bounded_and_monotonic():
    from plans.reward_metrics import normalized_oar_damage

    no_damage = normalized_oar_damage(0, 4)
    one_damage = normalized_oar_damage(1, 4)
    all_damage = normalized_oar_damage(4, 4)
    assert 0 <= no_damage < one_damage <= all_damage <= 1


def test_authoritative_rag_returns_clickable_sources():
    from brain.knowledge.rag import DoseRAG

    results = DoseRAG().retrieve("pancreatic iodine 125 dose standard", top_k=3)
    assert results
    assert any("https://" in result for result in results)
    constraints = DoseRAG().get_constraints("pancreas")
    assert "duodenum" in constraints
    assert constraints.get("_source", {}).get("urls")


def test_tool_writer_is_explicitly_gated(monkeypatch):
    from brain.core.tool_code_writer import ToolCodeWriter

    monkeypatch.delenv("BRACHYBOT_ENABLE_TOOL_CODE_WRITER", raising=False)
    result = ToolCodeWriter().generate_tool(
        "sample_tool", "Sample", "analysis", {}, {}, "            result = 1"
    )
    assert result["success"] is False
    assert "disabled" in result["error"].lower()


def test_environment_manager_is_explicitly_gated(monkeypatch):
    from tool_factory.env_manager import EnvManagerTool

    monkeypatch.delenv("BRACHYBOT_ENABLE_ENV_MANAGER", raising=False)
    result = EnvManagerTool().execute(action="list_envs")
    assert result.success is False
    assert "disabled" in result.error.lower()


def test_dynamic_tool_creator_is_gated_validated_and_registered(tmp_path, monkeypatch):
    import tool_factory.tool_creator as creator_module
    from agent_runtime.core import ToolRegistry
    from tool_factory.tool_creator import ToolCreatorTool

    monkeypatch.delenv("BRACHYBOT_ENABLE_TOOL_CREATOR", raising=False)
    disabled = ToolCreatorTool().execute(action="list")
    assert disabled.success is False
    assert "disabled" in disabled.error.lower()

    monkeypatch.setenv("BRACHYBOT_ENABLE_TOOL_CREATOR", "1")
    monkeypatch.setattr(creator_module, "TOOLS_DIR", str(tmp_path))
    monkeypatch.setattr(creator_module, "TOOLS_DIR_PATH", tmp_path.resolve())
    creator_module._dynamic_tools.clear()
    agent = type("Agent", (), {"registry": ToolRegistry()})()

    blocked = ToolCreatorTool().execute(
        action="create",
        tool_name="unsafe_tool",
        tool_code="import os\ndef execute():\n    return os.system('echo unsafe')",
        _agent=agent,
    )
    assert blocked.success is False
    assert "not allowlisted" in blocked.error or "not allowed" in blocked.error

    created = ToolCreatorTool().execute(
        action="create",
        tool_name="increment_value",
        description="Increment a numeric value",
        tool_code="def execute(value=0):\n    return value + 1",
        _agent=agent,
    )
    assert created.success is True
    assert created.data["registered"] is True
    assert agent.registry.execute("increment_value", value=4).data == 5

    deleted = ToolCreatorTool().execute(
        action="delete",
        tool_name="increment_value",
        _agent=agent,
    )
    assert deleted.success is True
    assert "increment_value" not in agent.registry.tool_names


def test_filesystem_browser_is_root_scoped_by_default(monkeypatch, tmp_path):
    from tool_factory.filesystem_browser import FilesystemBrowserTool

    monkeypatch.delenv("BRACHYBOT_ENABLE_FILESYSTEM_BROWSER_GLOBAL", raising=False)
    monkeypatch.delenv("BRACHYBOT_FILESYSTEM_ROOTS", raising=False)
    denied = FilesystemBrowserTool().execute(action="info", path=str(tmp_path))
    assert not denied.success
    assert "outside the configured project/data roots" in (denied.error or "")

    monkeypatch.setenv("BRACHYBOT_FILESYSTEM_ROOTS", str(tmp_path))
    allowed = FilesystemBrowserTool().execute(action="info", path=str(tmp_path))
    assert allowed.success
    assert allowed.data["path"] == str(tmp_path.resolve())


def test_filesystem_browser_global_access_requires_explicit_opt_in(monkeypatch, tmp_path):
    from tool_factory.filesystem_browser import FilesystemBrowserTool

    monkeypatch.delenv("BRACHYBOT_FILESYSTEM_ROOTS", raising=False)
    monkeypatch.setenv("BRACHYBOT_ENABLE_FILESYSTEM_BROWSER_GLOBAL", "1")
    result = FilesystemBrowserTool().execute(action="info", path=str(tmp_path))
    assert result.success


def test_multimodal_screenshot_uses_repository_upload_path(tmp_path, monkeypatch):
    import agent_runtime.llm_runtime as runtime

    fake_module = tmp_path / "agent_runtime" / "llm_runtime.py"
    screenshots = tmp_path / "uploads" / "screenshots"
    screenshots.mkdir(parents=True)
    fake_module.parent.mkdir(exist_ok=True)
    image = screenshots / "dose.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"test")
    monkeypatch.setattr(runtime, "__file__", str(fake_module))

    content = runtime.LLMRuntimeMixin._build_multimodal_content(
        "Analyze [Screenshot captured: /api/screenshots/dose.png]"
    )
    assert isinstance(content, list)
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_multimodal_screenshot_uses_current_workspace_only(tmp_path):
    import agent_runtime.llm_runtime as runtime

    session_id = "a" * 32
    workspace = tmp_path / "runtime" / "users" / "case"
    screenshots = workspace / "screenshots"
    screenshots.mkdir(parents=True)
    (screenshots / "dose.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"case")

    content = runtime.LLMRuntimeMixin._build_multimodal_content(
        f"Analyze [Screenshot captured: /api/sessions/{session_id}/screenshots/dose.png]",
        screenshot_root=str(workspace),
        workspace_session_id=session_id,
    )
    assert isinstance(content, list)
    assert content[1]["type"] == "image_url"

    rejected = runtime.LLMRuntimeMixin._build_multimodal_content(
        f"Analyze [Screenshot captured: /api/sessions/{'b' * 32}/screenshots/dose.png]",
        screenshot_root=str(workspace),
        workspace_session_id=session_id,
    )
    assert isinstance(rejected, str)
    assert "unavailable" in rejected


def test_native_provider_multimodal_adapters_preserve_text_and_image():
    from brain.providers.anthropic_llm import AnthropicLLM
    from brain.providers.gemini_llm import GeminiLLM
    from brain.providers.local_llm import OllamaLLM

    data_url = "data:image/png;base64,aGVsbG8="
    blocks = [
        {"type": "text", "text": "Inspect dose coverage"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]

    ollama_text, ollama_images = OllamaLLM._convert_content_to_ollama(blocks)
    assert ollama_text == "Inspect dose coverage"
    assert ollama_images == ["aGVsbG8="]

    system_text, contents = GeminiLLM._convert_messages([
        {"role": "system", "content": "Use clinical image context."},
        {"role": "user", "content": blocks},
    ])
    assert system_text == "Use clinical image context."
    assert contents[0]["parts"][0] == {"text": "Inspect dose coverage"}
    assert contents[0]["parts"][1]["inline_data"] == {
        "mime_type": "image/png",
        "data": "aGVsbG8=",
    }

    anthropic_blocks = AnthropicLLM._convert_content_to_anthropic(blocks)
    assert anthropic_blocks == [
        {"type": "text", "text": "Inspect dose coverage"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "aGVsbG8=",
            },
        },
    ]


def test_dose_model_path_can_be_configured(tmp_path, monkeypatch):
    from plans.dose_pre.model_loader import resolve_dose_model_path

    checkpoint = tmp_path / "dose_unet_spacing1mm_test.pth"
    checkpoint.write_bytes(b"placeholder")
    monkeypatch.setenv("BRACHYBOT_DOSE_MODEL_PATH", str(checkpoint))
    assert resolve_dose_model_path() == checkpoint.resolve()


def test_web_config_route_reads_project_root_defaults(tmp_path):
    from web.server import create_app

    app = create_app({
        "runtime_dir": str(tmp_path / "runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })
    client = app.test_client()
    registered = client.post(
        "/api/auth/register",
        json={"username": "config_route_user", "password": "correct horse battery staple"},
    )
    assert registered.status_code == 201
    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert "seed_info" in payload["defaults"]


def test_dicom_export_routes_share_one_implementation():
    from web.server import create_app

    app = create_app({"session_id": "dicom-route-test"})
    endpoints = {
        rule.rule: rule.endpoint
        for rule in app.url_map.iter_rules()
        if rule.rule in {"/api/export/dicom", "/api/export/dicom_rt"}
    }

    assert endpoints["/api/export/dicom"] == endpoints["/api/export/dicom_rt"]


def test_dose_evaluation_uses_actual_prescription_and_descending_dx():
    import SimpleITK as sitk
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool

    class Memory:
        def __init__(self, values):
            self.values = values

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def store(self, key, value):
            self.values[key] = value

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

    dose = np.array([[[1.05, 0.9], [0.8, 0.7]], [[0.6, 0.5], [0.4, 0.3]]], dtype=np.float32)
    ctv = np.ones_like(dose, dtype=np.uint8)
    oar = np.ones_like(dose, dtype=np.uint8)
    grid = sitk.GetImageFromArray(np.zeros_like(dose, dtype=np.float32))
    grid.SetSpacing((2.0, 2.0, 2.0))
    memory = Memory({
        "dose_distribution": dose,
        "resampled_ctv": ctv,
        "resampled_oar": oar,
        "resampled_ct": grid,
        "plan_config": {"in_lowest_energy": 1.1},
        "organ_names": {1: "test_oar"},
    })
    agent = type("Agent", (), {"memory": memory, "config": {}})()

    result = PlanningPipelineTool()._step_dose_eval(ctv, oar, agent)

    assert result.success is True
    assert result.metadata["prescribed_dose"] == pytest.approx(1.1)
    assert result.metadata["prescription_gy"] == pytest.approx(132.0)
    assert result.metadata["v100"] == 0.0
    assert result.metadata["oar_metrics"]["test_oar"]["d90"] == pytest.approx(36.0)


def test_dose_evaluation_prescription_does_not_depend_on_oar_presence():
    import SimpleITK as sitk
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool

    class Memory:
        def __init__(self, values):
            self.values = values

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def store(self, key, value):
            self.values[key] = value

    dose = np.ones((2, 2, 2), dtype=np.float32)
    ctv = np.ones_like(dose, dtype=np.uint8)
    grid = sitk.GetImageFromArray(dose)
    memory = Memory({
        "dose_distribution": dose,
        "resampled_ctv": ctv,
        "resampled_oar": None,
        "resampled_ct": grid,
        "plan_config": {"in_lowest_energy": 0.8},
    })
    agent = type("Agent", (), {"memory": memory, "config": {}})()

    result = PlanningPipelineTool()._step_dose_eval(ctv, None, agent)

    assert result.success is True
    assert result.metadata["prescribed_dose"] == pytest.approx(0.8)
    assert result.metadata["prescription_gy"] == pytest.approx(96.0)
    assert result.metadata["v100"] == pytest.approx(1.0)


def test_dose_evaluation_rejects_grid_mismatch_before_mask_indexing():
    from tool_factory.seed_plan.planning_pipeline import PlanningPipelineTool

    class Memory:
        def retrieve(self, key, default=None):
            if key == "dose_distribution":
                return np.ones((2, 2, 2), dtype=np.float32)
            return default

    agent = type("Agent", (), {"memory": Memory(), "config": {}})()
    result = PlanningPipelineTool()._step_dose_eval(
        np.ones((3, 2, 2), dtype=np.uint8),
        None,
        agent,
    )

    assert result.success is False
    assert "Dose and CTV grids do not match" in result.error


def test_dicom_rt_export_writes_linked_objects_on_one_grid(tmp_path):
    pydicom = pytest.importorskip("pydicom")
    import SimpleITK as sitk
    from pydicom.uid import RTDoseStorage, RTPlanStorage, RTStructureSetStorage
    from tool_factory.output.dicom_rt_exporter import DicomRTExporterTool

    image = sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.int16))
    image.SetSpacing((0.8, 1.2, 2.5))
    image.SetOrigin((-10.0, 20.0, 30.0))
    image.SetDirection((1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0))
    ctv = np.zeros((3, 4, 5), dtype=np.uint8)
    ctv[1, 1:3, 1:4] = 1
    dose = np.linspace(0.0, 2.0, ctv.size, dtype=np.float32).reshape(ctv.shape)
    seed_plan = [{
        "trajectory": None,
        "seeds": [
            ([12.0, -4.0, 8.0], [0.0, 0.0, 1.0]),
            ([12.0, -4.0, 12.0], [0.0, 0.0, 1.0]),
        ],
    }]

    result = DicomRTExporterTool().execute(
        ct_image=image,
        structures={"CTV": ctv},
        dose_array=dose,
        seed_plan=seed_plan,
        output_dir=str(tmp_path / "dicom"),
        dicom_tags={"patient_id": "CASE-01"},
        dose_scale_gy=120.0,
        prescription_gy=120.0,
    )

    assert result.success is True, result.error
    by_class = {}
    for path in result.data:
        if path.endswith(".dcm"):
            dataset = pydicom.dcmread(path)
            by_class[str(dataset.SOPClassUID)] = dataset
    assert set(by_class) == {str(RTStructureSetStorage), str(RTPlanStorage), str(RTDoseStorage)}

    rtstruct = by_class[str(RTStructureSetStorage)]
    rtplan = by_class[str(RTPlanStorage)]
    rtdose = by_class[str(RTDoseStorage)]
    assert rtplan.ApprovalStatus == "UNAPPROVED"
    assert len(rtplan.SourceSequence) == 2
    assert len(rtplan.ApplicationSetupSequence[0].ChannelSequence) == 2
    first_position = rtplan.ApplicationSetupSequence[0].ChannelSequence[0].BrachyControlPointSequence[0].ControlPoint3DPosition
    assert [float(value) for value in first_position] == pytest.approx([12.0, -4.0, 8.0])
    assert rtplan.ReferencedStructureSetSequence[0].ReferencedSOPInstanceUID == rtstruct.SOPInstanceUID
    assert rtdose.ReferencedRTPlanSequence[0].ReferencedSOPInstanceUID == rtplan.SOPInstanceUID
    assert tuple(rtdose.pixel_array.shape) == dose.shape
    recovered_dose = rtdose.pixel_array.astype(np.float64) * float(rtdose.DoseGridScaling)
    assert recovered_dose.max() == pytest.approx(float(dose.max() * 120.0), rel=1e-6)
    assert len(rtstruct.ROIContourSequence[0].ContourSequence) > 0


def test_dicom_rt_export_rejects_mixed_geometry(tmp_path):
    pytest.importorskip("pydicom")
    import SimpleITK as sitk
    from tool_factory.output.dicom_rt_exporter import DicomRTExporterTool

    image = sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.int16))
    result = DicomRTExporterTool().execute(
        ct_image=image,
        structures={"CTV": np.ones((3, 4, 5), dtype=np.uint8)},
        dose_array=np.ones((2, 4, 5), dtype=np.float32),
        seeds=[{"position": [0, 0, 0], "direction": [0, 0, 1]}],
        output_dir=str(tmp_path / "dicom"),
    )

    assert result.success is False
    assert "does not match planning grid" in result.error


def test_agent_memory_tracks_available_data_and_resets_state():
    from agent_runtime.core import AgentMemory

    memory = AgentMemory(session_id="availability-test")
    memory.store("ct_image", object())
    memory.store("ctv_array", np.ones((1, 1, 1), dtype=np.uint8))
    assert memory.conversation_state["data_available"] == ["ct_image", "ctv_array"]

    memory.store("ct_image", None)
    assert memory.conversation_state["data_available"] == ["ctv_array"]
    memory.conversation_state["ctv_segmented"] = True
    memory.clear_all_data()
    assert memory.conversation_state == {
        "ctv_segmented": False,
        "oar_segmented": False,
        "planning_completed": False,
        "last_tool_calls": [],
        "data_available": [],
    }


def test_report_context_exposes_source_backed_target_and_oar_criteria():
    from tool_factory.report_context import build_prescription_rationale

    memory = {
        "tumor_type_used": "pancreatic",
        "plan_config": {"in_lowest_energy": 1.0},
    }
    rationale = build_prescription_rationale(memory)

    assert rationale["prescription_gy"] == pytest.approx(120.0)
    assert rationale["target_criteria"]["v100_min"] == pytest.approx(0.9)
    assert rationale["oar_criteria"]["duodenum"]["d2cc_gy"] == pytest.approx(55.0)
    assert rationale["sources"]
    assert all(url.startswith("https://") for url in rationale["sources"])
    assert rationale["rationale_zh"]


def test_report_context_keeps_chinese_prescription_boundary_in_chinese():
    from tool_factory.report_context import format_prescription_rationale_markdown

    context = {
        "prescription_rationale": {
            "prescription_gy": 120.0,
            "prescription_source": "plan_config.in_lowest_energy",
            "rationale": "English fallback",
            "rationale_zh": "当前处方剂量为 120.0 Gy。",
            "clinical_boundary": "English boundary",
            "target_criteria": {},
            "sources": [],
        }
    }
    rendered = format_prescription_rationale_markdown(context, "zh")
    assert "当前处方剂量为 120.0 Gy。" in rendered
    assert "English fallback" not in rendered
    assert "English boundary" not in rendered


def test_planning_report_uses_persisted_effective_mode():
    from agent_runtime.core import AgentMemory
    from agent_runtime.response_tools import ResponseToolMixin

    agent = object.__new__(ResponseToolMixin)
    agent.memory = AgentMemory("report-mode-test")
    agent.memory.store("plan_config", {"mode": "rl", "effective_mode": "rl"})
    report = agent._build_planning_report("en", [])
    assert "reinforcement learning" in report
    assert "Planning mode**: rule_based" not in report


def test_report_context_does_not_apply_cross_site_defaults():
    from tool_factory.report_context import build_prescription_rationale

    rationale = build_prescription_rationale({"plan_config": {"in_lowest_energy": 1.0}})
    assert rationale["site"] == "unknown"
    assert rationale["target_criteria"] == {}
    assert rationale["oar_criteria"] == {}
    assert rationale["sources"] == []
    assert "no cross-site clinical threshold" in rationale["rationale"]


def test_report_generator_never_invents_unsourced_clinical_thresholds():
    from tool_factory.report_generator import ReportGeneratorTool

    plan = {
        "metrics": {"v100": 0.91, "v150": 0.40, "v200": 0.20, "d90": 123.0, "plan_score": 73},
        "prescription_dose_gy": 120.0,
    }
    report = ReportGeneratorTool()._generate_full_report(plan)
    assert "See cited case criteria" in report
    assert "Not assessed" in report
    assert "≥90%" not in report

    plan["prescription_rationale"] = {
        "prescription_gy": 120.0,
        "target_criteria": {"v100_min": 0.9, "d90_min_pct": 1.0, "v200_max": 0.3},
        "sources": ["https://example.org/source"],
    }
    sourced_report = ReportGeneratorTool()._generate_full_report(plan)
    assert "| V100 | 91.0% | >=90% | Pass |" in sourced_report
    assert "| D90 | 123.0 Gy | >=100% Rx (120.0 Gy) | Pass |" in sourced_report


def test_web_api_isolates_agent_and_ui_state_by_session(monkeypatch, tmp_path):
    import AgenticSys
    from web.server import create_app

    class Memory:
        def __init__(self, session_id):
            self.session_id = session_id
            self.planning_results = {}
            self.ui_state = {}
            self._lock = threading.RLock()
            self.patient_data = {}
            self.conversation = []
            self.tool_results = []
            self.context_summary = ""
            self.compaction_count = 0
            self.conversation_state = {}
            self.user_lang = "en"
            self._ui_state = {}
            self.current_phase = "idle"

        def retrieve(self, key, default=None):
            return self.planning_results.get(key, default)

        def set_ui_state(self, state):
            self.ui_state = dict(state)
            self._ui_state = dict(state)

        def set_persistence_callback(self, callback):
            self._persistence_callback = callback

        def get_ui_state(self):
            return dict(self._ui_state)

        def clear_all_data(self):
            self.planning_results.clear()

        def clear_conversation(self):
            pass

    class FakeAgent:
        def __init__(self, session_id, config=None):
            self.memory = Memory(session_id)
            self.brain_available = False
            self.config = dict(config or {})

        def get_status(self):
            return {
                "session_id": self.memory.session_id,
                "phase": "idle",
                "stored_keys": list(self.memory.planning_results),
                "ct_loaded": False,
                "ct_path": "",
            }

    monkeypatch.setattr(AgenticSys, "BrachyAgent", FakeAgent)
    app = create_app({
        "runtime_dir": str(tmp_path / "runtime"),
        "secret_key": "test-secret",
        "workspace_maintenance": False,
    })
    app.testing = True
    first = app.test_client()
    second = app.test_client()
    first_auth = first.post(
        "/api/auth/register",
        json={"username": "session_owner_a", "password": "correct horse battery staple"},
    ).get_json()
    second_auth = second.post(
        "/api/auth/register",
        json={"username": "session_owner_b", "password": "correct horse battery staple"},
    ).get_json()
    a = {"X-CSRF-Token": first_auth["csrf_token"]}
    b = {"X-CSRF-Token": second_auth["csrf_token"]}
    assert first.get("/api/status").get_json()["session_id"] == first_auth["active_session_id"]
    assert second.get("/api/status").get_json()["session_id"] == second_auth["active_session_id"]

    response = first.post("/api/ui/state", headers=a, json={"state": {"zoom": 1.5}})
    assert response.status_code == 200
    assert first.get("/api/ui/state").get_json()["state"] == {"zoom": 1.5}
    assert second.get("/api/ui/state").get_json()["state"] == {}

    assert first.post("/api/reset", headers=a).status_code == 200
    # /api/reset releases only the in-memory agent. Durable workspace/UI state
    # must survive so reopening the case restores the previous work.
    assert first.get("/api/ui/state").get_json()["state"] == {"zoom": 1.5}


def test_frontend_session_wrapper_and_dvh_do_not_drop_case_data():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    ui_api = (root / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    dvh = (root / "web/app/static/js/brachybot-dvh-planning.js").read_text(encoding="utf-8")

    assert "headers.set('X-BrachyBot-Session', _activeApiSessionId())" in ui_api
    assert "fetch(API + '/planning/clear'" not in ui_api
    assert ".slice(0, 30)" not in dvh


def test_report_links_and_uploaded_images_are_protocol_restricted():
    root = Path(__file__).resolve().parents[1]
    editor = (root / "web/app/static/js/brachybot-report-editor.js").read_text(encoding="utf-8")
    export = (root / "web/app/static/js/brachybot-report-export.js").read_text(encoding="utf-8")

    assert "url.protocol === 'http:' || url.protocol === 'https:'" in editor
    assert "image/png,image/jpeg,image/webp" in editor
    assert "_safeReportUrl(r.url)" in editor
    assert "const safeUrl = _safeReportUrl(r.url);" in export


def test_ui_controller_uses_the_same_working_controls_as_manual_ui():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    ui = (root / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    expected_calls = [
        "document.getElementById('slider' + capitalize(axis))",
        "setViewerLayout(value)",
        "setDoseOverlayOpacity(value)",
        "setGroupOpacity(axis, value)",
        "setDisplayMode()",
        "setDataItemVisibility(id, vis)",
        "setDataOpacity(id, op)",
        "setViewerTool(value)",
        "clearCurrentChatHistory({ skipConfirm: true })",
    ]
    for call in expected_calls:
        assert call in ui
    assert "document.getElementById('layoutMode')" not in ui
    assert "document.getElementById('slice' + capitalize(axis))" not in ui


def test_planning_completion_requires_current_turn_and_complete_products():
    from AgenticSys import BrachyAgent

    class Memory:
        def __init__(self, values):
            self.values = values

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

    agent = object.__new__(BrachyAgent)
    agent.memory = Memory({
        "dose_metrics": {"v100": 0.9},
        "seed_plan_serialized": [{"seeds": [1]}],
        "dose_distribution": np.ones((1, 1, 1), dtype=np.float32),
    })

    knowledge_steps = [{"type": "assistant", "status": "done"}]
    seed_only_steps = [{"type": "tool", "tool": "seed_planning", "status": "done"}]
    evaluated_steps = [{"type": "tool", "tool": "dose_evaluation", "status": "done"}]

    assert agent._has_completed_planning(knowledge_steps) is False
    assert agent._has_completed_planning(seed_only_steps) is False
    assert agent._has_completed_planning(evaluated_steps) is True

    agent.memory.values.pop("dose_distribution")
    assert agent._has_completed_planning(evaluated_steps) is False


def test_clinical_deciders_do_not_invent_default_thresholds():
    from brain.deciders.clinical_decider import ClinicalDecider
    from brain.deciders.quality_decider import QualityDecider

    clinical = ClinicalDecider(None)
    result = clinical.decide_from_metrics({"v100": 0.91})
    assert result["diagnosis"] == "UNVERIFIED"
    assert result["score"] is None

    quality = QualityDecider(None)
    unverified = quality._assess_quality(
        {"v100": 0.91}, {}, {}, 120.0, {}
    )
    assert unverified["acceptability"] == "UNVERIFIED"
    assert unverified["quality_score"] is None

    sourced = quality._assess_quality(
        {"v100": 0.91, "d90": 123.0},
        {"duodenum": {"d2cc": 40.0}},
        {"duodenum": {"d2cc_gy": 55.0}},
        120.0,
        {"v100_min": 0.90, "d90_min_pct": 1.0},
    )
    assert sourced["acceptability"] == "MEETS_CONFIGURED_CRITERIA"
    assert sourced["quality_score"] == pytest.approx(100.0)


def test_comprehensive_dose_score_requires_explicit_site_criteria():
    from tool_factory.dose_eval.comprehensive_dose_evaluation import (
        ComprehensiveDoseEvaluationTool,
    )

    tool = ComprehensiveDoseEvaluationTool()
    target = {"V100": 0.91, "V150": 0.45, "V200": 0.25, "D90": 123.0}
    assert tool._compute_plan_score(target, 120.0, [], "") is None
    assert tool._compute_plan_score(target, 120.0, [], "unknown_site") is None
    score = tool._compute_plan_score(target, 120.0, [], "nnunet_pancreatic")
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_quality_scorer_and_safety_validator_do_not_use_generic_site_defaults():
    from tool_factory.plan_quality.plan_quality_scorer import PlanQualityScorerTool
    from tool_factory.safety_validator import SafetyValidatorTool

    score = PlanQualityScorerTool().execute(
        v100=0.91,
        v150=0.40,
        v200=0.20,
        d90=123.0,
        prescribed_dose=120.0,
    )
    assert score.success
    assert score.data["acceptability"] == "UNVERIFIED"
    assert score.data["overall_score"] is None

    validation = SafetyValidatorTool().execute(
        action="validate",
        plan={"metrics": {"v100": 0.91, "d90": 1.02}},
    )
    assert validation.success
    assert validation.data["standards_available"] is False
    assert validation.data["safe"] is False


def test_quality_scorer_uses_only_available_source_backed_metrics():
    from tool_factory.plan_quality.plan_quality_scorer import PlanQualityScorerTool

    result = PlanQualityScorerTool().execute(
        v100=0.91,
        v150=0.95,
        v200=0.25,
        d90=123.0,
        prescribed_dose=120.0,
        organ="pancreas",
    )
    assert result.success
    assert result.data["standards_available"] is True
    assert result.data["overall_score"] is not None
    # Pancreatic criteria do not define V150; changing it must not alter the score.
    second = PlanQualityScorerTool().execute(
        v100=0.91,
        v150=0.01,
        v200=0.25,
        d90=123.0,
        prescribed_dose=120.0,
        organ="pancreas",
    )
    assert second.data["overall_score"] == result.data["overall_score"]


def test_run_server_fails_loudly_for_unauthenticated_remote_bind(monkeypatch):
    """An insecure remote bind must produce a non-zero CLI outcome."""
    from web import server

    monkeypatch.delenv("BRACHYBOT_API_KEY", raising=False)
    monkeypatch.delenv("BRACHYBOT_ALLOW_INSECURE_REMOTE", raising=False)
    monkeypatch.setattr(server, "_is_loopback_host", lambda _host: False)

    with pytest.raises(RuntimeError, match="Refusing to bind"):
        server.run_server(host="0.0.0.0")


def test_run_server_fails_loudly_when_flask_app_is_unavailable(monkeypatch):
    """A missing Flask runtime must not be reported as a successful start."""
    from web import server

    monkeypatch.setattr(server, "_is_loopback_host", lambda _host: True)
    monkeypatch.setattr(server, "create_app", lambda _config=None: None)

    with pytest.raises(RuntimeError, match="Flask is not available"):
        server.run_server(host="127.0.0.1")


def test_trusted_network_does_not_disable_a_configured_api_key():
    from web import server_support

    if server_support.API_KEY:
        assert server_support._API_KEY_REQUIRED is True
    source = Path(server_support.__file__).read_text(encoding="utf-8")
    assignment = next(
        line for line in source.splitlines() if line.startswith("_API_KEY_REQUIRED =")
    )
    assert "_TRUST_NETWORK" not in assignment


def test_spacing_normalized_dose_model_exports_are_defined():
    """The deployed DoseUNet module exposes only its real public symbols."""
    import ast
    from pathlib import Path

    source_path = Path(__file__).resolve().parents[1] / "plans/dose_pre/dose_unet.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    definitions = {
        node.name
        for node in module.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    export_assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    exports = set(ast.literal_eval(export_assignment.value))

    assert "DoseUNet" in exports
    assert exports <= definitions


def test_plan_refinement_requires_explicit_source_backed_target():
    from tool_factory.plan_quality.plan_refinement import PlanRefinementTool

    tool = PlanRefinementTool()
    common = {
        "current_plan": [],
        "dose_distribution": np.ones((2, 2, 2), dtype=np.float32),
        "ctv_mask": np.ones((2, 2, 2), dtype=np.uint8),
    }
    missing = tool.execute(**common)
    assert missing.success is False
    assert "prescribed_dose" in missing.error

    unsourced = tool.execute(**common, prescribed_dose=120.0)
    assert unsourced.success is False
    assert "target_v100" in unsourced.error

    explicit = tool.execute(**common, prescribed_dose=1.0, target_v100=0.90)
    assert explicit.success is True
    assert explicit.metadata["metrics_before"]["target_v100"] == pytest.approx(0.90)


def test_new_chat_turn_cannot_revive_cancelled_previous_turn():
    import threading
    from AgenticSys import BrachyAgent

    agent = object.__new__(BrachyAgent)
    agent._cancel_requested = False
    agent._turn_generation = 0
    agent._active_turn_token = 0
    agent._turn_state_lock = threading.RLock()
    agent._turn_local = threading.local()

    first = agent._begin_turn()
    assert agent._is_turn_cancelled(first) is False
    agent._cancel_active_turn()
    assert agent._is_turn_cancelled(first) is True

    second = agent._begin_turn()
    assert agent._is_turn_cancelled(second) is False
    assert agent._is_turn_cancelled(first) is True


def test_benchmark_report_generator_resolves_repository_root():
    from benchmarks import generate_final_report

    expected_root = Path(__file__).resolve().parents[1]
    assert Path(generate_final_report._ROOT).resolve() == expected_root


def test_unconnected_brain_tool_fails_instead_of_reporting_placeholder_success():
    from brain.core.tool_registry import ToolRegistry

    registry = ToolRegistry(use_agentic_sys=False)
    tool = registry.get("prostate_ctv")
    assert tool is not None
    with pytest.raises(RuntimeError, match="no connected implementation"):
        tool.execute_fn()


def test_ctv_ambiguity_has_no_automatic_model_recovery():
    from AgenticSys import BrachyAgent

    assert "ctv_segmentation" not in BrachyAgent._RECOVERY_ACTIONS


def test_workflow_normalizer_routes_explicit_tumor_site_and_keeps_ambiguity_closed():
    from AgenticSys import BrachyAgent

    class Memory:
        def retrieve(self, _key, default=None):
            return default

    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    agent._has_completed_planning = lambda *_args, **_kwargs: False
    agent._current_ct_path = lambda *_args, **_kwargs: "/tmp/case.nii.gz"

    planning_call = [{
        "id": "plan",
        "tool": "planning_pipeline",
        "params": {"step": "full"},
    }]
    routed = agent._normalize_clinical_tool_calls(planning_call, "请执行胰腺癌粒子植入规划")
    assert [call["tool"] for call in routed[:3]] == [
        "ctv_segmentation", "oar_segmentation", "planning_pipeline"
    ]
    assert routed[0]["params"]["tumor_type"] == "nnunet_pancreatic"

    ambiguous = agent._normalize_clinical_tool_calls(planning_call, "请执行粒子植入规划")
    assert "tumor_type" not in ambiguous[0]["params"]


def test_direct_ctv_request_uses_explicit_site_without_inventing_an_ambiguous_one():
    from AgenticSys import BrachyAgent

    class Memory:
        def retrieve(self, key, default=None):
            return "/tmp/case.nii.gz" if key == "ct_path" else default

        def get_ui_state(self):
            return {}

    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()

    routed = agent._detect_tool_request("segment CTV for pancreatic cancer")
    assert routed[0]["tool"] == "ctv_segmentation"
    assert routed[0]["params"]["tumor_type"] == "nnunet_pancreatic"

    assert agent._detect_tool_request("segment CTV") is None
    assert agent._detect_tool_request("segment a head and neck tumor CTV") is None


def test_direct_ctv_request_does_not_treat_manual_provenance_as_a_model():
    from AgenticSys import BrachyAgent

    class Memory:
        def retrieve(self, key, default=None):
            values = {
                "ct_path": "/tmp/case.nii.gz",
                "tumor_type_used": "manual_label",
            }
            return values.get(key, default)

        def get_ui_state(self):
            return {}

    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()

    assert agent._detect_tool_request("segment CTV") is None


def test_ctv_registry_excludes_non_target_and_mri_only_research_models():
    from tool_factory.CTV_seg import TOOL_REGISTRY
    from tool_factory.CTV_seg.pancreatic_tumor_voco import VoCoPancreaticTumorTool

    assert VoCoPancreaticTumorTool.LABEL_MAP[1] == ("pancreatic_tumor", True)
    assert VoCoPancreaticTumorTool.LABEL_MAP[2] == ("vein", False)
    assert VoCoPancreaticTumorTool.LABEL_MAP[3] == ("artery", False)
    assert VoCoPancreaticTumorTool.LABEL_MAP[4] == ("pancreas", False)
    assert {"voco_liver", "voco_kidney", "voco_lung", "voco_colon"} <= set(TOOL_REGISTRY)
    assert {
        "voco_btcv", "voco_segthor", "voco_fumpe", "voco_covid",
        "voco_aorta", "voco_brats21", "head_neck_tumor",
    }.isdisjoint(TOOL_REGISTRY)


def test_manual_ctv_label_preserves_source_when_site_is_also_declared(tmp_path):
    import SimpleITK as sitk
    from tool_factory.CTV_seg import CTVSegmentationTool

    label = sitk.GetImageFromArray(np.ones((2, 2, 2), dtype=np.uint8))
    label_path = tmp_path / "manual_ctv.nii.gz"
    sitk.WriteImage(label, str(label_path))

    result = CTVSegmentationTool()._execute(
        label_path=str(label_path), tumor_type="nnunet_pancreatic"
    )

    assert result.success is True
    assert result.metadata["tumor_type_used"] == "nnunet_pancreatic"
    assert result.metadata["ctv_source"] == "manual_label"


def test_manual_ctv_and_oar_labels_use_the_viewer_lpi_orientation(tmp_path):
    """Manual labels must use the same orientation policy as loaded CT slices."""
    import SimpleITK as sitk
    from tool_factory.CTV_seg import CTVSegmentationTool
    from tool_factory.OAR_seg import OARSegmentationTool

    # The asymmetric values make an unnoticed z-axis reversal observable.
    source = sitk.GetImageFromArray(np.arange(24, dtype=np.uint16).reshape(2, 3, 4))
    source.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, -1.0))
    label_path = tmp_path / "manual_label_with_reversed_z.nii.gz"
    sitk.WriteImage(source, str(label_path))
    expected = sitk.GetArrayFromImage(sitk.DICOMOrient(source, "LPI"))

    ctv = CTVSegmentationTool()._execute(
        label_path=str(label_path), tumor_type="nnunet_pancreatic", allow_empty=True
    )
    oar = OARSegmentationTool()._execute(label_path=str(label_path))

    assert ctv.success is True
    assert oar.success is True
    assert ctv.metadata["manual_label_orientation"] == "LPI"
    assert oar.metadata["manual_label_orientation"] == "LPI"
    assert np.array_equal(ctv.data, expected)
    assert np.array_equal(oar.data, expected)


def test_ctv_model_catalog_describes_every_optional_automatic_tumor_model():
    from tool_factory.CTV_seg import TOOL_REGISTRY
    from tool_factory.CTV_seg.model_catalog import CTV_MODEL_CATALOG

    catalog_types = {
        entry.get("tumor_type") for entry in CTV_MODEL_CATALOG if entry.get("tool")
    }
    routed_types = {name for name in TOOL_REGISTRY if name.startswith("voco_")}
    assert routed_types <= catalog_types


def test_unified_seed_planning_dispatches_exactly_one_mode(monkeypatch):
    from plans import core
    from tool_factory.seed_plan.seed_planning import SeedPlanningTool

    calls = []

    def rule_based(**kwargs):
        calls.append(("rule_based", kwargs))
        return []

    def reinforcement(**kwargs):
        calls.append(("rl", kwargs))
        return []

    monkeypatch.setattr(core, "optimal_plan", rule_based)
    monkeypatch.setattr(core, "optimal_plan_rf", reinforcement)
    model = object()
    common = {
        "trajectories": [],
        "radiation_volume": np.zeros((2, 2, 2), dtype=np.uint8),
        "dose_image": object(),
        "dose_cal_model": model,
    }

    rule_result = SeedPlanningTool()._execute(**common, mode="rule_based")
    assert rule_result.success is True
    assert [name for name, _ in calls] == ["rule_based"]
    assert calls[0][1]["dose_cal_model"] is model

    calls.clear()
    rl_result = SeedPlanningTool()._execute(**common, mode="rl")
    assert rl_result.success is True
    assert [name for name, _ in calls] == ["rl"]
    assert calls[0][1]["dose_cal_model"] is model


def test_trajectory_planning_forwards_geometry_limits(monkeypatch):
    from tool_factory import ToolResult
    from tool_factory.traj_plan import (
        TrajectoryInitTool,
        TrajectoryPlanningTool,
        TrajectoryRefineTool,
    )

    captured = {}

    def initialize(_self, **kwargs):
        captured.update(kwargs)
        return ToolResult(success=True, data=[])

    monkeypatch.setattr(TrajectoryInitTool, "_execute", initialize)
    monkeypatch.setattr(
        TrajectoryRefineTool,
        "_execute",
        lambda _self, **_kwargs: ToolResult(success=True, data=[]),
    )

    result = TrajectoryPlanningTool()._execute(
        dose_image=object(),
        radiation_volume=np.zeros((2, 2, 2), dtype=np.uint8),
        ref_direc=[0, 1, 0],
        direc_resolution=[30, 3, 2],
        extract_angle=0.75,
        maximum_candidate_trajectories=123,
        min_depth=4.5,
    )

    assert result.success is True
    assert captured["direc_resolution"] == [30, 3, 2]
    assert captured["extract_angle"] == pytest.approx(0.75)
    assert captured["maximum_candidate_trajectories"] == 123
    assert captured["min_depth"] == pytest.approx(4.5)


def test_preoperative_pipeline_forwards_declared_parameters(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from agent_runtime.chat_workflows import ChatWorkflowMixin
    import agent_runtime.chat_workflows as workflows

    class Memory:
        def __init__(self):
            self.current_phase = None
            self.values = {}

        def add_message(self, *_args):
            return None

        def store(self, key, value):
            self.values[key] = value

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def log_tool_call(self, *_args):
            return None

        def export_state(self, _path):
            return None

    class Registry:
        def __init__(self):
            self.calls = []

        def execute(self, name, **kwargs):
            self.calls.append((name, kwargs))
            if name == "ctv_segmentation":
                ctv = np.ones((2, 2, 2), dtype=np.uint8)
                return SimpleNamespace(
                    success=True,
                    metadata={"ctv_array": ctv, "ctv_voxel_count": 8},
                    error=None,
                )
            if name == "oar_segmentation":
                return SimpleNamespace(
                    success=True,
                    metadata={"oar_array": np.zeros((2, 2, 2), dtype=np.uint8)},
                    error=None,
                )
            if name == "trajectory_planning":
                return SimpleNamespace(
                    success=True,
                    metadata={"trajectories": []},
                    error=None,
                )
            if name == "seed_planning":
                return SimpleNamespace(
                    success=True,
                    metadata={
                        "optimal_plan": [],
                        "dose_distribution": np.zeros((2, 2, 2), dtype=np.float32),
                        "total_seeds": 0,
                    },
                    error=None,
                )
            if name == "dose_evaluation":
                return SimpleNamespace(success=True, metadata={}, error=None)
            raise AssertionError(name)

    agent = SimpleNamespace(
        memory=Memory(),
        registry=Registry(),
        config={
            "dl_params": {},
            "direc_resolution": [20, 4, 3],
            "distance_filter": {"lower_bound": 1.2, "interval_rate": 3},
        },
    )
    monkeypatch.setattr(workflows.sitk, "ReadImage", lambda _path: object())

    result = ChatWorkflowMixin.run_preoperative_plan(
        agent,
        ct_path="case.nii.gz",
        radiation_array_params={
            "target_value": 1,
            "obstacle_value": 2,
            "background_value": 0,
            "backlit_angle": 0.8,
            "maximum_candidate_trajectories": 88,
            "min_depth": 3,
        },
        reference_direc=[0, -1, 0],
        in_lowest_energy=1.25,
        out_highest_energy=0.9,
        DVH_rate=0.92,
        max_iter=5,
        output_dir=str(tmp_path),
        tumor_type="nnunet_pancreatic",
    )

    assert result["success"] is True
    trajectory_kwargs = next(kwargs for name, kwargs in agent.registry.calls if name == "trajectory_planning")
    seed_kwargs = next(kwargs for name, kwargs in agent.registry.calls if name == "seed_planning")
    evaluation_kwargs = next(kwargs for name, kwargs in agent.registry.calls if name == "dose_evaluation")
    ctv_kwargs = next(kwargs for name, kwargs in agent.registry.calls if name == "ctv_segmentation")
    assert ctv_kwargs["tumor_type"] == "nnunet_pancreatic"
    assert trajectory_kwargs["ref_direc"] == [0, -1, 0]
    assert trajectory_kwargs["extract_angle"] == pytest.approx(0.8)
    assert trajectory_kwargs["maximum_candidate_trajectories"] == 88
    assert seed_kwargs["in_lowest_dose"] == pytest.approx(1.25)
    assert seed_kwargs["DVH_rate"] == pytest.approx(0.92)
    assert seed_kwargs["iter_rate"] == 5
    assert seed_kwargs["lower_bound"] == pytest.approx(1.2)
    assert evaluation_kwargs["prescribed_dose"] == pytest.approx(1.25)
    assert evaluation_kwargs["tumor_type"] == "nnunet_pancreatic"


def test_preoperative_api_requires_tumor_type_when_no_ctv_label_is_supplied():
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    from types import SimpleNamespace

    agent = SimpleNamespace(
        memory=SimpleNamespace(current_phase=None, add_message=lambda *_args: None),
        registry=None,
        config={},
    )
    result = ChatWorkflowMixin.run_preoperative_plan(agent, ct_path="case.nii.gz")

    assert result["success"] is False
    assert result["clarification_required"] is True
    assert "tumor_type" in result["error"]


def test_dose_evaluation_uses_target_label_names_and_explicit_constraints():
    from tool_factory.dose_eval import DoseEvaluationTool

    dose = np.array([[[5.0, 0.0], [0.0, 0.0]]], dtype=np.float32)
    ctv = np.array([[[2, 1], [0, 0]]], dtype=np.uint8)
    oar = np.array([[[7, 0], [0, 0]]], dtype=np.uint8)

    result = DoseEvaluationTool()._execute(
        dose_array=dose,
        ctv_mask=ctv,
        target_value=1,
        oar_mask=oar,
        organ_names={7: "stomach"},
        prescribed_dose=1.0,
        oar_constraints={"stomach": {"max_dose": 1.0}},
        spacing=[1.0, 1.0, 1.0],
    )

    assert result.success is True
    assert result.metadata["v100"] == pytest.approx(0.0)
    assert "stomach" in result.metadata["oar_metrics"]
    assert result.metadata["oar_violations"][0]["structure"] == "stomach"
    assert result.metadata["oar_violations"][0]["source"] == "plan_config"


def test_trajectory_refinement_rejects_obstacle_intersection():
    from tool_factory.traj_plan.trajectory_refine import TrajectoryRefineTool

    radiation = np.ones((5, 5, 5), dtype=np.uint8)
    radiation[2, 0, 0] = 3
    blocked = (np.array([0, 0, 0]), np.array([1, 0, 0]), [4], [], 4)
    clear = (np.array([0, 1, 0]), np.array([1, 0, 0]), [4], [], 4)

    result = TrajectoryRefineTool()._execute(
        trajectories=[blocked, clear],
        radiation_volume=radiation,
        ref_direc=[1, 0, 0],
        target_value=1,
        obstacle_value=3,
        min_target_coverage=0.5,
    )

    assert result.success is True
    assert len(result.data) == 1
    assert np.array_equal(result.data[0][0], clear[0])


def test_layered_memory_prefers_query_relevant_facts(tmp_path):
    from memory.layered_memory import LayeredMemory

    memory = LayeredMemory(base_dir=str(tmp_path))
    memory.add_fact("Needle placement uses a validated coordinate transform", confidence=0.7)
    memory.add_fact("Unrelated export preference", confidence=0.99)

    summary = memory.get_context_summary("needle coordinate placement", max_facts=1)
    assert summary["l2_facts"][0][0].startswith("Needle placement")


def test_plan_refinement_validates_optional_oar_grid():
    from tool_factory.plan_quality.plan_refinement import PlanRefinementTool

    result = PlanRefinementTool()._execute(
        current_plan=[],
        dose_distribution=np.zeros((2, 2, 2), dtype=np.float32),
        ctv_mask=np.ones((2, 2, 2), dtype=np.uint8),
        oar_mask=np.ones((3, 2, 2), dtype=np.uint8),
        prescribed_dose=1.0,
        target_v100=0.9,
    )
    assert result.success is False
    assert "oar_mask shape mismatch" in result.error


def test_unvalidated_voco_oar_wrappers_are_not_public_tools():
    from tool_factory.OAR_seg import list_tools

    names = set(list_tools())
    assert "voco_total_segmentation" not in names
    assert "voco_aorta_vessel" not in names


def test_client_volume_renderer_applies_hu_threshold_and_monotonic_dvh():
    root = Path(__file__).resolve().parents[1]
    viewer_source = (root / "web/app/static/js/brachybot-viewer-volume.js").read_text(encoding="utf-8")
    dvh_source = (root / "web/app/static/js/brachybot-dvh-planning.js").read_text(encoding="utf-8")

    assert "volumeData[flatIdx] > thresholdValue" in viewer_source
    assert "function clearSliceCache()" in viewer_source
    assert "Math.min(outY[outY.length - 1], bounded)" in dvh_source


def test_web_fetch_rejects_all_non_public_address_classes(monkeypatch):
    import importlib

    web_fetch = importlib.import_module("tool_factory.web_fetch")
    tool = web_fetch.WebFetchTool()

    for url in (
        "http://127.0.0.1/",
        "http://172.20.1.10/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fc00::1]/",
    ):
        allowed, _ = tool._validate_public_url(url)
        assert allowed is False

    monkeypatch.setattr(
        web_fetch.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (web_fetch.socket.AF_INET, web_fetch.socket.SOCK_STREAM, 6, "", ("10.10.0.5", 80))
        ],
    )
    allowed, _ = tool._validate_public_url("http://internal.example/")
    assert allowed is False


def test_web_fetch_validates_every_redirect_hop(monkeypatch):
    import importlib

    web_fetch = importlib.import_module("tool_factory.web_fetch")
    tool = web_fetch.WebFetchTool()

    monkeypatch.setattr(
        web_fetch.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (web_fetch.socket.AF_INET, web_fetch.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ],
    )

    class RedirectResponse:
        status_code = 302
        headers = {"location": "http://127.0.0.1/admin"}
        encoding = "utf-8"

        def close(self):
            return None

    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        return RedirectResponse()

    monkeypatch.setattr(web_fetch.requests, "get", fake_get)
    result = tool._fetch_direct("http://public.example/start", 5000)

    assert result.success is False
    assert "private" in result.message.lower()
    assert calls == ["http://public.example/start"]


def test_seed_segmentation_converts_numpy_zyx_to_physical_xyz():
    import SimpleITK as sitk

    from tool_factory.seed_seg import SeedSegmentationTool

    image = sitk.Image([12, 13, 14], sitk.sitkInt16)
    image.SetSpacing((2.0, 3.0, 5.0))
    image.SetOrigin((10.0, 20.0, 30.0))

    physical = SeedSegmentationTool()._voxel_to_physical(
        image,
        np.array([4.0, 3.0, 2.0]),  # NumPy (z, y, x)
    )

    assert physical == pytest.approx([14.0, 29.0, 50.0])


def test_intraoperative_seed_matching_preserves_physical_directions():
    import SimpleITK as sitk

    from agent_runtime.chat_workflows import ChatWorkflowMixin

    workflow = ChatWorkflowMixin()
    planned = workflow._extract_planned_seeds({
        "seed_plan": [{
            "seeds": [
                {"position": [10.0, 0.0, 0.0], "direction": [1.0, 0.0, 0.0]},
                {"position": [0.0, 0.0, 0.0], "direction": [0.0, 1.0, 0.0]},
            ]
        }]
    })
    detected = [
        {"id": 1, "physical_position": [0.1, 0.0, 0.0]},
        {"id": 2, "physical_position": [9.9, 0.0, 0.0]},
    ]

    matched, deviations = workflow._match_detected_seeds(planned, detected)

    by_id = {seed["id"]: seed for seed in matched}
    assert by_id[1]["direction"] == [0.0, 1.0, 0.0]
    assert by_id[2]["direction"] == [1.0, 0.0, 0.0]
    assert sorted(deviations.tolist()) == pytest.approx([0.1, 0.1])

    reference = sitk.Image([8, 8, 8], sitk.sitkInt16)
    moving = sitk.Image([8, 8, 8], sitk.sitkInt16)
    assert workflow._images_share_physical_frame(reference, moving)[0] is True
    moving.SetOrigin((1.0, 0.0, 0.0))
    assert workflow._images_share_physical_frame(reference, moving)[0] is False


def test_world_seed_dose_helper_uses_model_grid_coordinates(monkeypatch):
    import SimpleITK as sitk

    from plans import utilizations
    from tool_factory.seed_plan.model_support import compute_world_seed_dose_grid

    image = sitk.Image([6, 7, 8], sitk.sitkFloat32)
    image.SetSpacing((2.0, 3.0, 4.0))
    image.SetOrigin((10.0, 20.0, 30.0))
    captured = {}

    monkeypatch.setattr(
        utilizations,
        "ras_direction_to_voxel",
        lambda direction, _image: np.asarray(direction, dtype=np.float32),
    )

    def fake_batch(seeds, dose_image, *_args):
        captured["position_zyx"] = seeds[0][0].copy()
        return [np.ones(sitk.GetArrayFromImage(dose_image).shape, dtype=np.float32)]

    monkeypatch.setattr(utilizations, "batch_seed_dose_calculation_dl", fake_batch)
    dose, accepted = compute_world_seed_dose_grid(
        [{"position": [14.0, 29.0, 46.0], "direction": [0.0, 0.0, 1.0]}],
        image,
        object(),
        {"infer_img_size": [4, 4, 4], "image_normalize": [-1000, 3000, 255]},
        {"radius": 0.4, "length": 4.5, "seed_avr_dose": 50},
    )

    assert captured["position_zyx"] == pytest.approx([4.0, 3.0, 2.0])
    assert dose.shape == (8, 7, 6)
    assert float(dose.max()) == pytest.approx(1.0)
    assert len(accepted) == 1


def test_document_reader_enforces_roots_and_actions(tmp_path, monkeypatch):
    from tool_factory.doc_reader import DocumentReaderTool

    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    document = allowed_root / "case.md"
    document.write_text("First finding.\n\nSecond finding.\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")
    monkeypatch.setenv("BRACHYBOT_FILESYSTEM_ROOTS", str(allowed_root))
    monkeypatch.delenv("BRACHYBOT_ENABLE_FILESYSTEM_BROWSER_GLOBAL", raising=False)

    tool = DocumentReaderTool()
    blocked = tool._execute(file_path=str(outside), action="read")
    summary = tool._execute(file_path=str(document), action="summary")
    metadata = tool._execute(file_path=str(document), action="metadata")

    assert blocked.success is False
    assert "outside" in blocked.error.lower()
    assert summary.success is True
    assert "First finding" in summary.data["content"]
    assert summary.data["metadata"]["summary_type"] == "extractive_preview"
    assert metadata.success is True
    assert metadata.data["content"] == ""


def test_bing_api_returns_all_requested_results(monkeypatch):
    import importlib

    web_search = importlib.import_module("tool_factory.web_search")

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "webPages": {
                    "value": [
                        {"name": "First", "snippet": "A", "url": "https://example.com/1"},
                        {"name": "Second", "snippet": "B", "url": "https://example.com/2"},
                    ]
                }
            }

    monkeypatch.setattr(web_search.requests, "get", lambda *_args, **_kwargs: Response())
    results = web_search.BingSearch()._search_api("test", 5, "test-key")

    assert [item["title"] for item in results] == ["First", "Second"]


def test_geometry_surface_points_exclude_target_interior():
    from plans.geometry import get_surface_points

    volume = np.zeros((5, 5, 5), dtype=np.uint8)
    volume[1:4, 1:4, 1:4] = 1

    points = get_surface_points(volume, target_val=1, obs_val=3, back_val=0)
    point_set = {tuple(int(v) for v in point) for point in points}

    assert (2, 2, 2) not in point_set
    assert (1, 2, 2) in point_set
    assert len(point_set) == 26


def test_intraoperative_replanning_combines_delivered_and_supplemental_ai_dose(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import SimpleITK as sitk

    from agent_runtime.chat_workflows import ChatWorkflowMixin
    from tool_factory.seed_plan import model_support
    from tool_factory.seed_plan import planning_pipeline

    image = sitk.Image([4, 4, 4], sitk.sitkFloat32)
    ctv_image = sitk.GetImageFromArray(np.ones((4, 4, 4), dtype=np.uint8))
    ctv_image.CopyInformation(image)
    oar_image = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.uint8))
    oar_image.CopyInformation(image)

    class Memory:
        def __init__(self):
            self.values = {
                "ct_image": image,
                "ctv_array": np.ones((4, 4, 4), dtype=np.uint8),
                "oar_array": np.zeros((4, 4, 4), dtype=np.uint8),
                "resampled_ct": image,
                "resampled_ctv": ctv_image,
                "resampled_oar": oar_image,
                "organ_names": {},
                "tumor_type_used": "pancreas",
            }

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def store(self, key, value):
            self.values[key] = value

        def export_state(self, _path):
            return None

    supplemental_plan = [
        [
            [np.array([0, 0, 0]), np.array([1, 0, 0]), [2], [], 2],
            [(np.array([1.0, 1.0, 1.0]), np.array([0.0, 0.0, 1.0]))],
            [],
        ]
    ]

    class Registry:
        def execute(self, name, **_kwargs):
            if name == "trajectory_planning":
                return SimpleNamespace(success=True, data=[supplemental_plan[0][0]], error=None)
            if name == "seed_planning":
                return SimpleNamespace(
                    success=True,
                    data=supplemental_plan,
                    metadata={"dose_distribution": np.full((4, 4, 4), 0.5, dtype=np.float32)},
                    error=None,
                )
            if name == "dose_evaluation":
                return SimpleNamespace(success=True, metadata={"v100": 0.75}, error=None)
            raise AssertionError(name)

    workflow = ChatWorkflowMixin()
    workflow.memory = Memory()
    workflow.registry = Registry()
    workflow.config = {
        "radiation_array_params": {"target_value": 1, "background_value": 0, "obstacle_value": 3},
        "reference_direc": [0.0, 1.0, 0.0],
        "in_lowest_energy": 1.0,
        "out_highest_energy": 1.0,
        "DVH_rate": 0.9,
        "iter_rate": 1,
    }

    monkeypatch.setattr(model_support, "resolve_dose_model", lambda *_args, **_kwargs: (object(), None))
    monkeypatch.setattr(
        model_support,
        "compute_world_seed_dose_grid",
        lambda seeds, *_args, **_kwargs: (
            np.full((4, 4, 4), 0.25, dtype=np.float32),
            [{"id": seeds[0]["id"], "position": seeds[0]["position"], "direction": seeds[0]["direction"]}],
        ),
    )
    monkeypatch.setattr(
        planning_pipeline,
        "_resolve_ref_direc",
        lambda *_args, **_kwargs: np.array([0.0, 1.0, 0.0]),
    )

    result = workflow._trigger_replanning(
        image,
        original_plan=[],
        detected_seeds=[{"id": 1, "position": [1.0, 1.0, 1.0], "direction": [0.0, 0.0, 1.0]}],
        output_dir=str(tmp_path),
    )

    assert result["success"] is True
    assert result["implanted_seed_count"] == 1
    assert result["supplemental_seed_count"] == 1
    assert result["dose_engine"] == "dose_unet_spacing1mm"
    assert np.allclose(workflow.memory.values["dose_distribution"], 0.75)
    assert len(workflow.memory.values["seed_plan"]) == 2
