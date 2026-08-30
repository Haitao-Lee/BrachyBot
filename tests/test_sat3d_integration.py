from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path

import numpy as np
import SimpleITK as sitk


def test_closed_set_routes_use_sat3d_and_pancreas_stays_nnunet():
    from tool_factory.CTV_seg import get_tool, normalize_tumor_type
    from tool_factory.CTV_seg.pancreatic_tumor_nnunet import NNUNetPancreaticTumorTool
    from tool_factory.CTV_seg.sat3d import SAT3DCTVTool

    expected = {
        "liver": "sat3d_liver_tumor",
        "biomedparse_liver_tumor": "sat3d_liver_tumor",
        "kidney": "sat3d_kidney_tumor",
        "biomedparse_kidney_lesion": "sat3d_kidney_tumor",
        "lung": "sat3d_lung_tumor",
        "colon": "sat3d_colon_tumor",
        "head and neck": "sat3d_head_neck_tumor",
        "prostate": "sat3d_prostate_tumor",
    }
    for alias, canonical in expected.items():
        assert normalize_tumor_type(alias) == canonical
        assert isinstance(get_tool(alias), SAT3DCTVTool)
    assert normalize_tumor_type("pancreas") == "nnunet_pancreatic"
    assert isinstance(get_tool("pancreas"), NNUNetPancreaticTumorTool)


def test_prostate_route_rejects_ct_but_accepts_t2_modality_before_runtime_probe(monkeypatch):
    import tool_factory.CTV_seg.sat3d as sat3d

    image = sitk.GetImageFromArray(np.ones((4, 5, 6), dtype=np.float32))
    result = sat3d.SAT3DCTVTool()._execute(
        image=image,
        tumor_type="sat3d_prostate_tumor",
        image_modality="CT",
    )
    assert not result.success
    assert result.metadata["code"] == "sat3d_modality_mismatch"
    assert "t2" in " ".join(result.metadata["supported_modalities"])

    monkeypatch.setattr(
        sat3d,
        "_availability",
        lambda: {"available": False, "missing": ["test runtime"]},
    )
    result = sat3d.SAT3DCTVTool()._execute(
        image=image,
        tumor_type="sat3d_prostate_tumor",
        image_modality="T2w",
    )
    assert not result.success
    assert result.metadata["code"] == "sat3d_unavailable"


def test_sat3d_rejects_nonzero_volume_index_for_3d_input():
    import tool_factory.CTV_seg.sat3d as sat3d

    image = sitk.GetImageFromArray(np.ones((4, 5, 6), dtype=np.float32))
    result = sat3d.SAT3DCTVTool()._execute(
        image=image,
        tumor_type="sat3d_liver_tumor",
        image_modality="CT",
        volume_index=1,
    )
    assert not result.success
    assert result.metadata["code"] == "invalid_sat3d_volume_index"


def test_sat3d_adapter_passes_prompts_and_preserves_lpi_geometry(monkeypatch, tmp_path):
    import tool_factory.CTV_seg.sat3d as sat3d

    runtime = tmp_path / "python"
    runtime.write_text("", encoding="utf-8")
    model = tmp_path / "model.pth"
    critic = tmp_path / "critic.pth"
    model.write_bytes(b"model")
    critic.write_bytes(b"critic")
    monkeypatch.setattr(
        sat3d,
        "_availability",
        lambda: {
            "available": True,
            "missing": [],
            "runtime_python": str(runtime),
            "root": str(tmp_path),
            "checkpoint": str(model),
            "critic_checkpoint": str(critic),
        },
    )

    def fake_run(command, **_kwargs):
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        points = Path(command[command.index("--points") + 1])
        input_image = sitk.ReadImage(command[command.index("--input") + 1])
        array = np.zeros(tuple(reversed(input_image.GetSize())), dtype=np.uint8)
        array[1:3, 2:4, 3:5] = 1
        mask = sitk.GetImageFromArray(array)
        mask.CopyInformation(input_image)
        sitk.WriteImage(mask, str(output))
        metadata.write_text(
            json.dumps({"prompt_payload": json.loads(points.read_text(encoding="utf-8"))}),
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr(sat3d.subprocess, "run", fake_run)
    image = sitk.GetImageFromArray(np.ones((5, 6, 7), dtype=np.float32))
    image.SetSpacing((0.8, 0.9, 2.0))
    image.SetOrigin((4.0, 5.0, 6.0))
    result = sat3d.SAT3DCTVTool()._execute(
        image=image,
        tumor_type="sat3d_liver_tumor",
        image_modality="CT",
        positive_points=[[2, 3, 4]],
        negative_points=[[1, 1, 1]],
        point_coordinate_system="voxel_zyx",
    )
    assert result.success
    expected = sitk.DICOMOrient(image, "LPI")
    mask = result.metadata["ctv_mask"]
    assert mask.GetSize() == expected.GetSize()
    assert mask.GetSpacing() == expected.GetSpacing()
    assert result.metadata["sat3d_prompt_mode"] == "point_guided"
    assert result.metadata["sat3d_positive_points_zyx"] == [[2, 3, 4]]
    assert result.metadata["volume_index"] == 0
    assert result.metadata["sat3d_requires_clinician_review"] is True
    assert result.metadata["worker_metadata"]["prompt_payload"]["negative"] == [[1, 1, 1]]


def test_sat3d_worker_does_not_depend_on_ground_truth_click_generation():
    source = (Path(__file__).parents[1] / "scripts" / "sat3d_worker.py").read_text(encoding="utf-8")
    assert "gt3D" not in source
    assert "get_next_click" not in source
    assert "positive_points" in source


def test_sat3d_runtime_keeps_virtual_environment_launcher(monkeypatch, tmp_path):
    import tool_factory.CTV_seg.sat3d as sat3d

    launcher = tmp_path / ".venv" / "bin" / "python"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("", encoding="utf-8")
    monkeypatch.setenv("SAT3D_RUNTIME_PYTHON", str(launcher))
    assert sat3d._runtime_python(tmp_path) == Path(os.path.abspath(str(launcher)))


def test_sat3d_thin_volume_padding_shifts_prompt_to_the_image_grid():
    worker_path = Path(__file__).parents[1] / "scripts" / "sat3d_worker.py"
    spec = importlib.util.spec_from_file_location("sat3d_worker_test", worker_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    before, after, shifted = module._explicit_roi_padding(
        (11, 128, 96),
        [[5, 64, 20]],
    )
    assert before == [58, 0, 16]
    assert after == [59, 0, 16]
    assert shifted == [[63, 64, 36]]


def test_frontend_exposes_sat3d_models_modality_and_point_tools():
    root = Path(__file__).parents[1]
    html = (root / "web" / "app" / "index.html").read_text(encoding="utf-8")
    manual = (root / "web" / "app" / "static" / "js" / "brachybot-manual-annotation.js").read_text(encoding="utf-8")
    for tumor_type in (
        "sat3d_liver_tumor",
        "sat3d_kidney_tumor",
        "sat3d_lung_tumor",
        "sat3d_colon_tumor",
        "sat3d_prostate_tumor",
        "sat3d_head_neck_tumor",
    ):
        assert f'value="{tumor_type}"' in html
    assert 'id="ctvImageModality"' in html
    assert 'id="ctvVolumeIndex"' in html
    assert "sat3d_positive" in html and "sat3d_negative" in html
    assert "point_coordinate_system: 'voxel_zyx'" in manual
    assert "positive_points" in manual and "negative_points" in manual
