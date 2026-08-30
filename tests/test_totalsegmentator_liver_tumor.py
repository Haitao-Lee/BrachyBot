"""Regression tests for the dedicated TotalSegmentator liver CTV route."""

from __future__ import annotations

import numpy as np
import pytest
import SimpleITK as sitk


def _ct_image() -> sitk.Image:
    image = sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.int16))
    image.SetSpacing((0.7, 0.8, 5.0))
    image.SetOrigin((-10.0, 20.0, -30.0))
    image.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, -1.0))
    return image


def test_runtime_resolver_finds_conda_cli_when_path_is_not_activated(
    monkeypatch, tmp_path
):
    from tool_factory.CTV_seg import totalsegmentator_runtime as runtime

    env_bin = tmp_path / "env" / "bin"
    env_bin.mkdir(parents=True)
    python_path = env_bin / "python3.12"
    cli_path = env_bin / "TotalSegmentator"
    python_path.write_text("", encoding="utf-8")
    cli_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    monkeypatch.setattr(runtime.shutil, "which", lambda _name: None)
    monkeypatch.setattr(runtime.sys, "executable", str(python_path))
    monkeypatch.setattr(runtime.os, "access", lambda _path, _mode: True)

    assert runtime.find_totalsegmentator_executable() == str(cli_path)


def test_totalsegmentator_liver_route_returns_only_binary_liver_tumor(monkeypatch):
    from tool_factory.CTV_seg.totalsegmentator_liver_tumor import (
        TotalSegmentatorLiverTumorTool,
    )

    image = _ct_image()
    raw_labels = np.zeros((3, 4, 5), dtype=np.int32)
    raw_labels[1, 2, 3] = 7
    raw_labels[0, 0, 0] = 2
    tool = TotalSegmentatorLiverTumorTool()
    monkeypatch.setattr(
        tool,
        "_run_totalsegmentator",
        lambda _image, *, fast_mode: raw_labels,
    )

    result = tool._execute(image=image)

    assert result.success is True
    assert np.array_equal(result.data, (raw_labels > 0).astype(np.uint8))
    assert set(np.unique(result.metadata["ctv_array"])) <= {0, 1}
    assert result.metadata["ctv_source"] == "totalsegmentator"
    assert result.metadata["total_segmentator_task"] == "liver_vessels"
    assert result.metadata["total_segmentator_label"] == "liver_tumor"
    assert result.metadata["source_labels_exposed"] == ["liver_tumor"]
    assert result.metadata["target_semantics"] == "liver_tumor_ctv_only"
    assert result.metadata["ctv_mask"].GetSize() == image.GetSize()
    assert result.metadata["ctv_mask"].GetSpacing() == image.GetSpacing()
    assert result.metadata["ctv_mask"].GetOrigin() == image.GetOrigin()
    assert result.metadata["ctv_mask"].GetDirection() == image.GetDirection()


def test_totalsegmentator_liver_route_fails_closed_without_executable(monkeypatch):
    from tool_factory.CTV_seg.totalsegmentator_liver_tumor import (
        TotalSegmentatorLiverTumorTool,
    )

    monkeypatch.setattr(
        "tool_factory.CTV_seg.totalsegmentator_liver_tumor.find_totalsegmentator_executable",
        lambda: None,
    )
    result = TotalSegmentatorLiverTumorTool()._execute(image=_ct_image())

    assert result.success is False
    assert "TotalSegmentator" in (result.error or "")
    assert "BiomedParse" not in (result.error or "")


def test_liver_output_discovery_ignores_other_task_outputs(tmp_path):
    from tool_factory.CTV_seg.totalsegmentator_liver_tumor import (
        TotalSegmentatorLiverTumorTool,
    )

    (tmp_path / "liver.nii.gz").write_bytes(b"organ")
    (tmp_path / "vessels.nii.gz").write_bytes(b"vessels")
    assert TotalSegmentatorLiverTumorTool._find_tumor_output(tmp_path) is None

    tumor = tmp_path / "nested"
    tumor.mkdir()
    (tumor / "liver_tumor.nii.gz").write_bytes(b"tumor")
    assert TotalSegmentatorLiverTumorTool._find_tumor_output(tmp_path) == tumor / "liver_tumor.nii.gz"


def test_liver_vessels_command_does_not_pass_unsupported_fast_flag(monkeypatch):
    from tool_factory.CTV_seg import totalsegmentator_liver_tumor as module
    from tool_factory.CTV_seg.totalsegmentator_liver_tumor import (
        TotalSegmentatorLiverTumorTool,
    )

    class _CompletedProcess:
        returncode = 0

        def communicate(self, timeout=None):
            return "", None

        def poll(self):
            return self.returncode

    command = []
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda args, **_kwargs: (command.extend(args) or _CompletedProcess()),
    )

    with pytest.raises(RuntimeError, match="did not produce liver_tumor"):
        TotalSegmentatorLiverTumorTool()._run_locked(
            _ct_image(),
            "cpu",
            fast_mode=True,
            executable="/usr/bin/TotalSegmentator",
            align_segmentation_to_reference=lambda _path, _image: np.zeros((3, 4, 5), dtype=np.int32),
        )

    assert "--task" in command
    assert command[command.index("--task") + 1] == "liver_vessels"
    assert "--fast" not in command


def test_historical_liver_ctv_ids_resolve_to_sat3d():
    from tool_factory.CTV_seg import get_tool, normalize_tumor_type
    from tool_factory.CTV_seg.sat3d import SAT3DCTVTool

    for alias in ("liver", "liver_tumor", "biomedparse_liver_tumor", "voco_liver"):
        assert normalize_tumor_type(alias) == "sat3d_liver_tumor"
        assert isinstance(get_tool(alias), SAT3DCTVTool)
