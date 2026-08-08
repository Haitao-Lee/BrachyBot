"""Regression tests for the optional, research-only BiomedParse adapter."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import SimpleITK as sitk
import torch


def test_biomedparse_catalog_is_explicit_and_excludes_pancreatic_production():
    from tool_factory.CTV_seg import CTVSegmentationTool, TOOL_REGISTRY
    from tool_factory.CTV_seg.biomedparse_v2 import SITE_SPECS

    assert set(SITE_SPECS) <= set(TOOL_REGISTRY)
    assert "nnunet_pancreatic" in TOOL_REGISTRY
    assert "biomedparse_pancreas_tumor" not in SITE_SPECS
    assert set(SITE_SPECS) <= set(CTVSegmentationTool().input_schema["properties"]["tumor_type"]["enum"])


def test_deprecated_voco_aliases_are_hidden_from_the_agent():
    """The LLM-facing enum and catalog must advertise the biomedparse_*
    candidates, not the deprecated VoCo SwinUNETR aliases. The aliases remain
    accepted for backward compatibility (they route to BiomedParse) but must
    never be presented to the agent as a model choice."""
    from tool_factory.CTV_seg import CTVSegmentationTool, get_tool
    from tool_factory.CTV_seg.biomedparse_v2 import BiomedParseV2CTVTool
    from tool_factory.CTV_seg.model_catalog import filter_catalog

    enum = CTVSegmentationTool().input_schema["properties"]["tumor_type"]["enum"]
    assert "biomedparse_liver_tumor" in enum
    assert "liver_tumor" in enum
    # No deprecated VoCo alias may appear in the agent-facing enum or catalog.
    assert not any(str(t).startswith("voco_") for t in enum), "voco_* aliases must be hidden from the agent"
    assert not any(str(m.get("tumor_type", "")).startswith("voco_") for m in filter_catalog())
    # The aliases must still resolve so existing callers keep working.
    assert isinstance(get_tool("voco_liver"), BiomedParseV2CTVTool)


def test_legacy_voco_aliases_route_to_biomedparse():
    """All non-pancreatic CTV aliases (liver/kidney/lung/colon and their VoCo
    forms) must resolve to BiomedParse, never the deprecated VoCo SwinUNETR.
    The pancreatic production alias stays on nnU-Net."""
    from tool_factory.CTV_seg import BIOMEDPARSE_FALLBACKS, TOOL_REGISTRY, get_tool
    from tool_factory.CTV_seg.biomedparse_v2 import BiomedParseV2CTVTool
    from tool_factory.CTV_seg.pancreatic_tumor_nnunet import NNUNetPancreaticTumorTool

    for alias in ("liver_tumor", "kidney_tumor", "lung_tumor", "colon_tumor",
                  "voco_liver", "voco_kidney", "voco_lung", "voco_colon"):
        assert isinstance(get_tool(alias), BiomedParseV2CTVTool), alias
        assert alias in BIOMEDPARSE_FALLBACKS, alias
        assert BIOMEDPARSE_FALLBACKS[alias].startswith("biomedparse_"), alias
    # Pancreatic stays on nnU-Net for all aliases.
    assert isinstance(get_tool("nnunet_pancreatic"), NNUNetPancreaticTumorTool)
    assert isinstance(get_tool("voco_pancreatic"), NNUNetPancreaticTumorTool)
    assert isinstance(get_tool("pancreatic_tumor"), NNUNetPancreaticTumorTool)


def test_runtime_python_venv_symlink_is_not_resolved():
    """A POSIX venv exposes .venv/bin/python as a symlink; resolving it would
    bypass pyvenv.cfg and lose every installed package (numpy/torch). The
    external inference must use the venv path verbatim."""
    import tool_factory.CTV_seg.biomedparse_v2 as adapter

    src = Path(adapter.__file__).read_text(encoding="utf-8")
    # The _execute path must build runtime_python from availability WITHOUT
    # .resolve(): a POSIX venv python is a symlink and resolving it bypasses
    # pyvenv.cfg, losing numpy/torch. The line that uses the venv path must not
    # resolve it, while the fallback to sys.executable does.
    idx = src.index("runtime_python = (")
    venv_line_end = src.index("\n", src.index("Path(runtime_python_text)"))
    venv_branch = src[idx:venv_line_end]
    assert "resolve" not in venv_branch, "venv runtime_python must not be resolved"
    assert "Path(sys.executable).resolve()" in src, "fallback python is resolved"
    assert "_run_external_inference(" in src
    assert adapter._runtime_python.__name__ == "_runtime_python"


def test_empty_nnunet_mask_reports_honest_diagnostic(monkeypatch, tmp_path):
    """When the pancreatic nnU-Net runs but finds no tumor label, the CTV
    wrapper must say the model RAN and which structures it found — not fall back
    to the generic 'model not installed' guess."""
    import tool_factory.CTV_seg as ctv
    from tool_factory import ToolResult
    from tool_factory.CTV_seg.pancreatic_tumor_nnunet import NNUNetPancreaticTumorTool

    image = sitk.GetImageFromArray(
        np.zeros((4, 4, 4), dtype=np.int16).astype(np.int16)
    )

    class _FakeNNUNet(NNUNetPancreaticTumorTool):
        def _execute(self, **kwargs):
            result_array = np.zeros((4, 4, 4), dtype=np.uint8)
            result_array[0:2, 0:2, 0:2] = 4  # pancreas only, no tumor label 1
            result_array[2:4, 2:4, 2:4] = 3  # vein
            return ToolResult(
                success=True,
                data=(result_array == 1).astype(np.uint8),
                metadata={
                    "label_counts": {
                        "pancreatic tumor": 0,
                        "artery": 0,
                        "vein": int(np.sum(result_array == 3)),
                        "pancreas": int(np.sum(result_array == 4)),
                    },
                },
            )

    monkeypatch.setattr(ctv, "TOOL_REGISTRY", {**ctv.TOOL_REGISTRY, "nnunet_pancreatic": _FakeNNUNet})
    result = ctv.CTVSegmentationTool()._execute(
        image=image, tumor_type="nnunet_pancreatic"
    )

    assert result.success is False
    assert "did NOT detect any tumor region" in result.error
    assert "vein" in result.error
    assert "pancreas" in result.error
    assert "model is not installed" not in result.error


def test_empty_manual_label_reports_check_message(tmp_path):
    """An empty (background-only) manual CTV label should tell the user to
    check the label file, not blame the model."""
    from tool_factory.CTV_seg import CTVSegmentationTool

    label = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.uint8))
    label_path = tmp_path / "empty_manual_ctv.nii.gz"
    sitk.WriteImage(label, str(label_path))

    result = CTVSegmentationTool()._execute(label_path=str(label_path))

    assert result.success is False
    assert "label is empty" in result.error
    assert "label file" in result.error


def test_biomedparse_missing_runtime_fails_closed(monkeypatch, tmp_path):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter

    monkeypatch.delenv("BIOMEDPARSE_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_CHECKPOINT", raising=False)
    monkeypatch.setattr(adapter, "_repo_root", lambda: None)
    monkeypatch.setattr(
        adapter,
        "_checkpoint_path",
        lambda _root: tmp_path / "missing-biomedparse-v2.ckpt",
    )
    image = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.int16))
    result = adapter.BiomedParseV2CTVTool().execute(
        image=image,
        tumor_type="biomedparse_liver_tumor",
    )
    assert result.success is False
    assert result.metadata["research_only"] is True
    assert any("BIOMEDPARSE_ROOT" in item for item in result.metadata["missing"])


def test_biomedparse_default_checkpoint_uses_repository_deployment_path(monkeypatch):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter

    monkeypatch.delenv("BIOMEDPARSE_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_CHECKPOINT", raising=False)
    expected = adapter._default_checkpoint_path()
    assert expected.name == "biomedparse_v2.ckpt"
    assert expected.parts[-3:] == ("ctv", "biomedparse_v2", "biomedparse_v2.ckpt")
    assert adapter._checkpoint_path(None) == expected


def test_biomedparse_availability_requires_checkout_python_and_imports(
    monkeypatch,
    tmp_path,
):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter

    root = tmp_path / "BiomedParse"
    (root / "configs" / "model").mkdir(parents=True)
    (root / "inference.py").write_text("", encoding="utf-8")
    (root / "utils.py").write_text("", encoding="utf-8")
    checkpoint = tmp_path / "biomedparse_v2.ckpt"
    checkpoint.write_bytes(b"weights")
    runtime_python = tmp_path / "python"
    runtime_python.write_bytes(b"runtime")
    text_assets = tmp_path / "clip-vit-base-patch32"
    text_assets.mkdir()
    for filename in adapter._TEXT_ASSET_FILES:
        (text_assets / filename).write_text("{}", encoding="utf-8")

    monkeypatch.setattr(adapter, "_repo_root", lambda: root)
    monkeypatch.setattr(adapter, "_checkpoint_path", lambda _root: checkpoint)
    monkeypatch.setattr(adapter, "_text_assets_path", lambda _root: text_assets)
    monkeypatch.setattr(adapter, "_runtime_python", lambda _root: runtime_python)
    monkeypatch.setattr(
        adapter,
        "_probe_runtime",
        lambda *_args: {
            "ready": False,
            "missing_modules": ["hydra", "detectron2"],
            "python": str(runtime_python),
            "probe_error": "",
        },
    )

    availability = adapter._availability()

    assert availability["available"] is False
    assert availability["checkpoint"] == str(checkpoint)
    assert availability["runtime_python"] == str(runtime_python)
    assert any("hydra, detectron2" in item for item in availability["missing"])


def test_biomedparse_availability_requires_local_text_assets(monkeypatch, tmp_path):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter

    root = tmp_path / "BiomedParse"
    (root / "configs" / "model").mkdir(parents=True)
    (root / "inference.py").write_text("", encoding="utf-8")
    (root / "utils.py").write_text("", encoding="utf-8")
    checkpoint = tmp_path / "biomedparse_v2.ckpt"
    checkpoint.write_bytes(b"weights")
    runtime_python = tmp_path / "python"
    runtime_python.write_bytes(b"runtime")
    text_assets = tmp_path / "missing-clip-tokenizer"

    monkeypatch.setattr(adapter, "_repo_root", lambda: root)
    monkeypatch.setattr(adapter, "_checkpoint_path", lambda _root: checkpoint)
    monkeypatch.setattr(adapter, "_text_assets_path", lambda _root: text_assets)
    monkeypatch.setattr(adapter, "_runtime_python", lambda _root: runtime_python)
    monkeypatch.setattr(
        adapter,
        "_probe_runtime",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("runtime probe must not run without local text assets")
        ),
    )

    availability = adapter._availability()

    assert availability["available"] is False
    assert availability["text_assets"] == str(text_assets)
    assert any("CLIP tokenizer assets" in item for item in availability["missing"])


def test_external_biomedparse_worker_result_is_loaded(monkeypatch, tmp_path):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter

    root = tmp_path / "BiomedParse"
    root.mkdir()
    checkpoint = tmp_path / "biomedparse_v2.ckpt"
    checkpoint.write_bytes(b"weights")
    runtime_python = tmp_path / "python"
    runtime_python.write_bytes(b"runtime")
    text_assets = tmp_path / "clip-vit-base-patch32"
    text_assets.mkdir()

    def fake_run(command, **_kwargs):
        output_path = adapter.Path(command[command.index("--output") + 1])
        metadata_path = adapter.Path(command[command.index("--metadata") + 1])
        np.save(output_path, np.ones((2, 3, 4), dtype=np.uint8), allow_pickle=False)
        metadata_path.write_text(
            '{"object_existence_confidence": 0.91}',
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    mask, confidence = adapter._run_external_inference(
        normalised=np.zeros((2, 3, 4), dtype=np.float32),
        root=root,
        checkpoint=checkpoint,
        text_assets=text_assets,
        runtime_python=runtime_python,
        prompt="liver tumors",
        slice_batch_size=2,
    )

    assert mask.shape == (2, 3, 4)
    assert np.all(mask == 1)
    assert confidence == 0.91


def test_biomedparse_ct_window_maps_to_official_byte_range():
    from tool_factory.CTV_seg.biomedparse_v2 import _normalise_ct

    values = np.asarray([-910.0, -160.0, 590.0], dtype=np.float32)
    result = _normalise_ct(values, (1500.0, -160.0))
    assert np.allclose(result, [0.0, 127.5, 255.0])


def test_unavailable_non_pancreatic_site_reports_research_fallback_state(
    monkeypatch,
    tmp_path,
):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter
    from tool_factory.CTV_seg import CTVSegmentationTool

    monkeypatch.delenv("BIOMEDPARSE_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_CHECKPOINT", raising=False)
    monkeypatch.setattr(adapter, "_repo_root", lambda: None)
    monkeypatch.setattr(
        adapter,
        "_checkpoint_path",
        lambda _root: tmp_path / "missing-biomedparse-v2.ckpt",
    )
    image = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.int16))
    result = CTVSegmentationTool().execute(image=image, tumor_type="liver")
    assert result.success is False
    assert result.metadata["research_only"] is True
    assert any("BIOMEDPARSE_ROOT" in item for item in result.metadata["missing"])


def test_mocked_biomedparse_runtime_preserves_lpi_geometry_and_records_chain(
    monkeypatch,
    tmp_path,
):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter

    root = tmp_path / "BiomedParse"
    root.mkdir()
    checkpoint = root / "biomedparse_v2.ckpt"
    checkpoint.write_bytes(b"test")
    monkeypatch.setenv("BIOMEDPARSE_ROOT", str(root))
    monkeypatch.setenv("BIOMEDPARSE_V2_CHECKPOINT", str(checkpoint))
    monkeypatch.setenv("BRACHYBOT_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(
        adapter,
        "_availability",
        lambda: {
            "available": True,
            "missing": [],
            "research_only": True,
            "clinical_validation_status": "not_established",
        },
    )

    class FakeModel:
        def __call__(self, payload, mode, slice_batch_size):
            depth = int(payload["image"].shape[1])
            return {
                "predictions": {
                    "pred_gmasks": torch.ones((depth, 1, 8, 8), dtype=torch.float32),
                    "object_existence": torch.full((depth, 1), 8.0),
                }
            }

    source_shape = (3, 5, 7)
    fake_runtime = (
        FakeModel(),
        torch.device("cpu"),
        lambda array, size: (
            torch.as_tensor(array, dtype=torch.int32),
            None,
            array.shape,
            0,
        ),
        lambda volume, pad_width, padded_size, valid_axis: np.ones(source_shape, dtype=np.uint8),
        lambda logits, existence: logits > 0,
        lambda masks, ids: masks,
        torch,
    )
    monkeypatch.setattr(adapter, "_load_runtime", lambda *args: fake_runtime)

    image = sitk.GetImageFromArray(np.zeros(source_shape, dtype=np.int16))
    image.SetSpacing((0.8, 0.9, 2.5))
    image.SetOrigin((12.0, -7.0, 30.0))
    result = adapter.BiomedParseV2CTVTool().execute(
        image=image,
        tumor_type="biomedparse_liver_tumor",
    )

    assert result.success is True
    expected = sitk.DICOMOrient(image, "LPI")
    mask = result.metadata["ctv_mask"]
    assert mask.GetSize() == expected.GetSize()
    assert mask.GetSpacing() == expected.GetSpacing()
    assert mask.GetOrigin() == expected.GetOrigin()
    assert mask.GetDirection() == expected.GetDirection()
    record = adapter._validation_records()["biomedparse_liver_tumor"]
    assert record["technical_call_chain_passed"] is True
    assert record["space_alignment_passed"] is True
    assert record["clinical_case_validation"] is False


def test_model_catalog_exposes_four_state_capability(monkeypatch, tmp_path):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter
    from tool_factory.CTV_seg.model_catalog import catalog_with_local_status

    monkeypatch.setattr(adapter, "_availability", lambda: {"available": True, "missing": []})
    monkeypatch.setattr(
        adapter,
        "_validation_records",
        lambda: {
            "biomedparse_liver_tumor": {
                "technical_call_chain_passed": True,
                "space_alignment_passed": True,
                "result_save_path_passed": True,
                "data_tree_viewer_passed": True,
            }
        },
    )
    items = {
        item["tumor_type"]: item
        for item in catalog_with_local_status(str(tmp_path))
        if item.get("tumor_type")
    }
    liver = items["biomedparse_liver_tumor"]
    assert liver["capability_state"] == "experimental"
    assert liver["capability_color"] == "orange"
    assert liver["callable"] is True
    assert liver["technical_call_chain_passed"] is True
    assert liver["space_alignment_passed"] is True
    assert liver["clinical_case_validation"] is False
    assert items["nnunet_pancreatic"]["capability_state"] == "unavailable"


def test_generic_biomedparse_mask_is_an_independent_displayable_result(monkeypatch):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter

    image = sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.int16))
    image.SetSpacing((0.7, 0.8, 2.0))
    mask = np.zeros((3, 4, 5), dtype=np.uint8)
    mask[1, 1:3, 2:4] = 1
    lpi_image = sitk.DICOMOrient(image, "LPI")
    monkeypatch.setattr(
        adapter,
        "_run_prompt_inference",
        lambda *_args, **_kwargs: (
            {"available": True, "research_only": True},
            lpi_image,
            mask,
            0.87,
        ),
    )

    result = adapter.BiomedParseV2GenericSegmentationTool().execute(
        image=image,
        image_path="/case/ct.nii.gz",
        target="shoulder joint",
    )

    assert result.success is True
    assert result.metadata["generic_mask"]["kind"] == "generic_segmentation"
    assert result.metadata["generic_mask"]["target"] == "shoulder joint"
    assert result.metadata["generic_mask"]["research_only"] is True
    assert "ctv_array" not in result.metadata
    assert np.array_equal(result.data, mask)
    assert "not classified as CTV or OAR" in result.message


def test_generic_biomedparse_empty_mask_is_reported_honestly(monkeypatch):
    import tool_factory.CTV_seg.biomedparse_v2 as adapter

    image = sitk.GetImageFromArray(np.zeros((2, 3, 4), dtype=np.int16))
    monkeypatch.setattr(
        adapter,
        "_run_prompt_inference",
        lambda *_args, **_kwargs: (
            {"available": True, "research_only": True},
            image,
            np.zeros((2, 3, 4), dtype=np.uint8),
            0.12,
        ),
    )

    result = adapter.BiomedParseV2GenericSegmentationTool().execute(
        image=image,
        target="liver",
    )

    assert result.success is False
    assert "found no 'liver'" in result.error
    assert "model is not installed" not in result.error


def test_generic_biomedparse_result_persists_with_stable_session_metadata():
    from AgenticSys import BrachyAgent

    class Memory:
        session_id = "generic-persist"

        def __init__(self):
            self.values = {"ct_spacing": (0.7, 0.8, 2.0)}

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def store(self, key, value):
            self.values[key] = value

    memory = Memory()
    agent = type("AgentHarness", (), {"memory": memory})()
    mask = np.zeros((2, 3, 4), dtype=np.uint8)
    mask[1, 1, 2] = 1
    metadata = {
        "mask_id": "mask_bp_stable",
        "generic_mask": {
            "mask_id": "mask_bp_stable",
            "target": "liver",
            "kind": "generic_segmentation",
            "spacing": [0.7, 0.8, 2.0],
        },
        "voxel_count": 1,
    }

    assert BrachyAgent._persist_generic_segmentation(agent, metadata, mask) is True
    entry = memory.retrieve("generic_segmentation_masks")[0]
    assert entry["session_id"] == "generic-persist"
    assert entry["data_tree_node_id"] == "mask_bp_stable"
    assert entry["status"] == "ready"
    assert np.array_equal(entry["mask_array"], mask)
