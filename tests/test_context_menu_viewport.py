from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_context_menu_positioning_clamps_and_scrolls_inside_viewport():
    viewer = _read("web/app/static/js/brachybot-viewer-volume.js")
    css = _read("web/app/static/css/brachybot-report-controls.css")

    assert "function positionBrachyContextMenu(menu, anchorX, anchorY)" in viewer
    assert "menu.style.maxHeight = `${maxMenuHeight}px`" in viewer
    assert "left = Math.min(Math.max(margin, left), maxLeft)" in viewer
    assert "top = Math.min(Math.max(margin, top), maxTop)" in viewer
    assert "window.positionBrachyContextMenu = positionBrachyContextMenu" in viewer
    assert "event.target === menu || menu.contains?.(event.target)" in viewer
    assert "max-height: calc(100dvh - 16px)" in css
    assert "overflow-y: auto" in css


def test_all_context_menu_entry_points_use_shared_positioning():
    viewer = _read("web/app/static/js/brachybot-viewer-volume.js")
    manual_3d = _read("web/app/static/js/brachybot-3d-manual.js")
    annotation = _read("web/app/static/js/brachybot-manual-annotation.js")
    export = _read("web/app/static/js/brachybot-data-export.js")

    # The two Data Tree paths include the normal and non-visual-artifact early
    # return.  The latter used to bypass all viewport correction.
    assert viewer.count("positionBrachyContextMenu(menu, x, y)") >= 3
    assert "window.positionBrachyContextMenu(menu, x, y)" in manual_3d
    assert "window.positionBrachyContextMenu(menu, event.clientX, event.clientY)" in annotation
    assert "window.positionBrachyContextMenu(menu, event.clientX, event.clientY)" in export


def test_data_tree_group_context_menu_is_unified_and_not_closed_by_a_stale_listener():
    viewer = _read("web/app/static/js/brachybot-viewer-volume.js")
    manual_3d = _read("web/app/static/js/brachybot-3d-manual.js")
    annotation = _read("web/app/static/js/brachybot-manual-annotation.js")

    # Every rendered parent branch, including OAR's two classification
    # subgroups, must go through the same handler.  That handler prevents and
    # stops the native event before opening the group menu, so a nested header
    # cannot fall through to another tree branch.
    group_ids = (
        "image", "segmentation", "ctv", "oar", "non_traversable",
        "traversable", "planning", "planning_meshes", "artifacts",
    )
    for group_id in group_ids:
        assert f"oncontextmenu=\"handleTreeItemRightClick('{group_id}', event)\"" in viewer

    assert "'image', 'segmentation', 'ctv', 'oar', 'non_traversable', 'traversable'," in viewer
    assert "'masks', 'generic_masks', 'upload_masks', 'artifacts'," in viewer
    assert "document.addEventListener('contextmenu', event =>" in viewer

    # Per-menu delayed document listeners caused the next right-click to close
    # the newly-created menu.  Context-menu dismissal is now centralized in the
    # capture-phase boundary and must not be re-installed by any viewer module.
    for source in (viewer, manual_3d, annotation):
        assert "document.addEventListener('contextmenu', hideContextMenu" not in source
    assert "document.addEventListener('click', hideContextMenu, { once: true })" not in viewer
    assert "document.addEventListener('click', hideContextMenu, { once: true })" not in manual_3d
    assert "document.addEventListener('click', hideContextMenu, { once: true })" not in annotation
