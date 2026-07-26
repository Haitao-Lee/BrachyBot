"""Regression tests for the optional, research-only BiomedParse adapter."""

from __future__ import annotations

import numpy as np
import SimpleITK as sitk


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
    assert "BIOMEDPARSE_ROOT" in result.metadata["missing"]


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
    assert "BIOMEDPARSE_ROOT" in result.metadata["missing"]
