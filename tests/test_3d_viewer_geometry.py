from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_3d_renderer_uses_one_css_to_drawing_buffer_geometry_path():
    source = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")

    assert "function syncViewer3DSize()" in source
    assert "renderer.setPixelRatio(dpr)" in source
    assert "renderer.setSize(cssWidth, cssHeight, false)" in source
    assert "renderer.domElement.style.width = '100%'" in source
    assert "const { pixelWidth, pixelHeight, dpr, cssWidth, cssHeight } = geometry" in source
    assert "setViewport(0, 0, pixelWidth, pixelHeight)" in source
    assert "setScissor(0, 0, pixelWidth, pixelHeight)" in source
    assert "const axisSize = Math.max(1, Math.round(axisSizeCss * dpr))" in source
    # A CSS-sized viewport must not be used after a high-DPI renderer is
    # configured; it would crop the scene when the viewer card is resized.
    assert "setViewport(0, 0, w, h)" not in source
    assert source.index("const geometry = syncViewer3DSize()") < source.index("const controlsChanged = scene3D.controls.update()")
    assert "axesGroup.quaternion.copy(scene3D.camera.quaternion)" in source
    assert "function sync3DCameraPose" in source


def test_force_render_reuses_the_same_resize_guard_without_replacing_camera_pose():
    source = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    force = source.split("function forceRender3DViewer()", 1)[1].split(
        "function update3DMeshOpacity", 1
    )[0]
    assert "scene3D.resize?.()" in force
    assert "renderer.setSize(w, h)" not in force


def test_2d_zoom_applies_each_overlay_transform_once():
    annotation = (ROOT / "web/app/static/js/brachybot-manual-annotation.js").read_text(encoding="utf-8")
    assert "const transformHost = sliceCanvas._doseWrapper" in annotation
    assert "transformHost && transformHost.contains?.(layerCanvas)" in annotation
    assert "const applyOverlayTransform = element =>" in annotation
    assert "wrapper.contains?.(element)" in annotation
    assert "applyOverlayTransform(doseCanvas)" in annotation
    assert "applyOverlayTransform(contourCanvas)" in annotation
    assert "applyOverlayTransform(seedsCanvas)" in annotation


def test_external_report_camera_capture_does_not_resize_live_renderer():
    report = (ROOT / "web/app/static/js/brachybot-report-editor.js").read_text(encoding="utf-8")
    workspace = (ROOT / "web/app/static/js/brachybot-workspace.js").read_text(encoding="utf-8")
    assert "window.sync3DCameraPose?." in report
    assert "renderer.setSize(width, height, false)" not in report
    assert "scene3D.resize?.()" in report
    assert "camera_up" in workspace
    assert "sync3DCameraPose" in workspace
