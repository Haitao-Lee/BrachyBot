"""Regression checks for the shared Data Tree and viewer structure palette."""

import colorsys
from pathlib import Path

from web.server_support import (
    _SLICER_STRUCTURE_COLORS,
    _ctv_label_color,
    _label_color,
)


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_structure_palette_is_distinct_and_has_useful_chroma():
    assert len(_SLICER_STRUCTURE_COLORS) == 32
    assert len(set(_SLICER_STRUCTURE_COLORS)) == 32
    saturations = [
        colorsys.rgb_to_hsv(*(channel / 255.0 for channel in color))[1]
        for color in _SLICER_STRUCTURE_COLORS
    ]
    assert min(saturations) >= 0.39
    assert sum(saturations) / len(saturations) >= 0.55
    assert len({_label_color(label) for label in range(1, 58)}) == 57


def test_primary_ctv_is_vivid_red_and_does_not_collide_with_oar_label_one():
    assert _ctv_label_color(1) == (255, 48, 76)
    assert _label_color(1) == (77, 157, 224)
    assert _ctv_label_color(1) != _label_color(1)
    assert _ctv_label_color(2) != _ctv_label_color(1)


def test_frontend_uses_typed_luts_and_migrates_only_legacy_defaults():
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    layout = read("web/app/static/js/brachybot-viewer-layout.js")
    workspace = read("web/app/static/js/brachybot-workspace.js")
    routes = read("web/routes/viewer_routes.py")

    assert "let ctvLabelColorLUT = {};" in viewer
    assert "let oarLabelColorLUT = {};" in viewer
    assert "X-CTV-Color-LUT" in routes
    assert "X-OAR-Color-LUT" in routes
    assert "const c = ctvLabelColorLUT[label_id];" in layout
    assert "LEGACY_STRUCTURE_COLORS.has" in viewer
    assert "window.migrateLegacyStructurePalette?.(savedTree);" in workspace
    assert "window.syncStructureColorLUTsFromTree?.(dataTreeState);" in workspace
    assert "if (Number(tree.structurePaletteVersion || 0) >= STRUCTURE_PALETTE_VERSION)" in viewer


def test_palette_defaults_are_shared_by_config_and_data_tree():
    viewer = read("web/app/static/js/brachybot-viewer-volume.js")
    config = read("config/default_params.json")
    report = read("web/app/static/js/brachybot-report-editor.js")

    assert "const DEFAULT_CTV_STRUCTURE_COLOR = '#ff304c';" in viewer
    assert '"ctv_color": "#ff304c"' in config
    assert "dataTreeState.ctv?.color || '#ff304c'" in report
    assert '"oar_non_traversable_color": "#e58a48"' in config
    assert '"oar_traversable_color": "#3ccb8f"' in config
