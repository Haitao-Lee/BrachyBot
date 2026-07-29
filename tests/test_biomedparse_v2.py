"""Regression tests for the optional, research-only BiomedParse adapter."""

from __future__ import annotations

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


def test_biomedparse_missing_runtime_fails_closed(monkeypatch):
    from tool_factory.CTV_seg.biomedparse_v2 import BiomedParseV2CTVTool

    monkeypatch.delenv("BIOMEDPARSE_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_CHECKPOINT", raising=False)
    image = sitk.GetImageFromArray(np.zeros((4, 4, 4), dtype=np.int16))
    result = BiomedParseV2CTVTool().execute(
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


def test_unavailable_non_pancreatic_site_reports_research_fallback_state(monkeypatch):
    from tool_factory.CTV_seg import CTVSegmentationTool

    monkeypatch.delenv("BIOMEDPARSE_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_ROOT", raising=False)
    monkeypatch.delenv("BIOMEDPARSE_V2_CHECKPOINT", raising=False)
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
