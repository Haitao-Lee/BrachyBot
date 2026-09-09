"""Regression tests for the dedicated liver/kidney nnUNet cascades."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import SimpleITK as sitk


def test_dedicated_cascade_resources_and_aliases_are_available():
    from tool_factory.CTV_seg import get_tool, normalize_tumor_type
    from tool_factory.CTV_seg.nnunet_cascade_tumor import (
        NNUNetKidneyTumorTool,
        NNUNetLiverTumorTool,
        cascade_availability,
    )

    available = cascade_availability()
    assert available["liver"]["available"] is True
    assert available["kidney"]["available"] is True
    assert available["liver"]["folds"] == 5
    assert available["kidney"]["folds"] == 5

    for alias in ("liver", "biomedparse_liver_tumor", "voco_liver"):
        assert normalize_tumor_type(alias) == "nnunet_liver_tumor"
        assert isinstance(get_tool(alias), NNUNetLiverTumorTool)
    for alias in ("kidney", "biomedparse_kidney_lesion", "voco_kidney"):
        assert normalize_tumor_type(alias) == "nnunet_kidney_tumor"
        assert isinstance(get_tool(alias), NNUNetKidneyTumorTool)


def test_five_fold_is_default_and_fast_mode_is_explicit(monkeypatch):
    from tool_factory.CTV_seg.nnunet_cascade_tumor import (
        cascade_folds,
        cascade_tile_step_size,
    )

    monkeypatch.delenv("BRACHYBOT_CASCADE_FOLDS", raising=False)
    monkeypatch.delenv("BRACHYBOT_CASCADE_FAST_FOLDS", raising=False)
    monkeypatch.delenv("BRACHYBOT_CASCADE_TILE_STEP_SIZE", raising=False)
    monkeypatch.delenv("BRACHYBOT_CASCADE_FAST_TILE_STEP_SIZE", raising=False)

    assert cascade_folds() == "0,1,2,3,4"
    assert cascade_tile_step_size() == 0.5
    assert cascade_folds(fast=True) == "0"
    assert cascade_tile_step_size(fast=True) == 0.75


def test_cascade_runner_preserves_geometry_and_passes_speed_controls(monkeypatch):
    import tool_factory.CTV_seg.nnunet_cascade_tumor as module

    image = sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.int16))
    image.SetSpacing((0.7, 0.8, 2.0))
    image.SetOrigin((11.0, -4.0, 7.0))
    image.SetDirection((1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0))
    commands = []

    class FakeProcess:
        pid = 12345
        returncode = 0

        def __init__(self, args, **_kwargs):
            commands.append(list(args))

        def communicate(self, timeout=None):
            command = commands[-1]
            output_dir = Path(command[command.index("--output") + 1])
            input_dir = Path(command[command.index("--input") + 1])
            ct_path = next(input_dir.glob("*.nii.gz"))
            ct = sitk.ReadImage(str(ct_path))
            mask = sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.uint8))
            mask.SetSpacing(ct.GetSpacing())
            mask.SetOrigin(ct.GetOrigin())
            mask.SetDirection(ct.GetDirection())
            mask_array = sitk.GetArrayFromImage(mask)
            mask_array[1, 2, 3] = 1
            mask = sitk.GetImageFromArray(mask_array)
            mask.CopyInformation(ct)
            output_dir.mkdir(parents=True, exist_ok=True)
            sitk.WriteImage(mask, str(output_dir / "mock.nii.gz"), True)
            return "mock cascade complete", None

        def poll(self):
            return self.returncode

    monkeypatch.setattr(module.subprocess, "Popen", FakeProcess)
    tool = module.NNUNetLiverTumorTool()
    availability = module.cascade_availability("liver")
    result = tool._run_cascade(image, gpu_index="0", availability=availability)

    assert result.success is True
    assert result.metadata["cascade_folds_used"] == "0,1,2,3,4"
    assert result.metadata["cascade_tile_step_size"] == 0.5
    assert result.metadata["cascade_preprocess_workers"] == 2
    output_mask = result.metadata["ctv_mask"]
    expected = sitk.DICOMOrient(image, "LPI")
    assert output_mask.GetSize() == expected.GetSize()
    assert output_mask.GetSpacing() == expected.GetSpacing()
    assert output_mask.GetOrigin() == expected.GetOrigin()
    assert output_mask.GetDirection() == expected.GetDirection()
    assert result.metadata["output_orientation"] == "LPI"
    command = commands[0]
    assert command[command.index("--folds") + 1] == "0,1,2,3,4"
    assert command[command.index("--tile_step_size") + 1] == "0.5"
