from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web/app/static/js"


def _read(name):
    return (JS / name).read_text(encoding="utf-8")


def test_planning_special_nodes_use_the_same_2d_visibility_contract():
    volume = _read("brachybot-viewer-volume.js")
    assert "id === 'dose_overlay' || id === 'dvh'" in volume
    assert "planning.dvh === node" in volume
    assert "function isPlanningDoseOverlayVisible2D()" in volume
    assert "function isPlanningDvhVisible2D()" in volume
    assert "function _applyDvhViewVisibility()" in volume
    assert "node.visible2D = next" in volume
    assert "_scheduleDataTreeSave(`viewer.visibility:${id}`, id)" in volume


def test_dose_renderers_do_not_bypass_data_tree_visibility():
    manual = _read("brachybot-manual-annotation.js")
    manual3d = _read("brachybot-3d-manual.js")
    assert "function _isDoseOverlayVisibleIn2D()" in manual
    assert "_isDoseOverlayVisibleIn2D()" in manual
    assert "function _doseOverlayVisibleFor2D()" in manual3d
    assert manual3d.count("_doseOverlayVisibleFor2D()") >= 6


def test_dvh_visibility_and_opacity_are_consumed_by_plotly_view():
    dvh = _read("brachybot-dvh-planning.js")
    volume = _read("brachybot-viewer-volume.js")
    assert "window.isPlanningDvhVisible2D()" in dvh
    assert "dvhEl.style.visibility" in dvh
    assert "dvhEl.style.opacity" in dvh
    assert "if (id === 'dvh')" in volume
    assert "_applyDvhViewVisibility();" in volume


def test_ui_bridge_routes_dose_visibility_through_data_tree():
    api = _read("brachybot-ui-api.js")
    assert "setDataItemVisibility('dose_overlay', requested)" in api
    assert "window.isPlanningDoseOverlayVisible2D" in api
    assert "setGroupVisibility('planning_trajectories', value === 'on')" in api


def test_planning_trajectory_and_mesh_colors_are_real_controls():
    volume = _read("brachybot-viewer-volume.js")
    assert "function _planningTrajectoryForId(id)" in volume
    assert "function _planningMeshForId(id)" in volume
    assert "_applyPlanningTrajectoryColor(id, pendingColor)" in volume
    assert "else if (_planningMeshForId(id)) itemState = _planningMeshForId(id);" in volume
    assert "category === 'planning_trajectories'" in volume


def test_analysis_nodes_do_not_publish_noop_color_actions():
    volume = _read("brachybot-viewer-volume.js")
    api = _read("brachybot-ui-api.js")
    assert "function _isColorlessPlanningNode(id)" in volume
    assert "const isColorablePlanningItem = isPlanningItem && !_isColorlessPlanningNode(firstId);" in volume
    assert "const isColorlessAnalysis = ['dose', 'dose_overlay', 'dvh'].includes(id);" in api


def test_batch_planning_controls_cover_analysis_and_independent_mesh_nodes():
    volume = _read("brachybot-viewer-volume.js")
    assert "else if (id === 'dose_overlay' || id === 'dvh')" in volume
    assert "else if (_planningTrajectoryForId(id))" in volume
    assert "else if (_planningMeshForId(id))" in volume
    assert "function batchSolo()" in volume
    assert "const hasPlanningSelection = planningIds.length > 0;" in volume
