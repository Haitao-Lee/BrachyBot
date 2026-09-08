from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLS = (ROOT / "web/app/static/js/OrbitControls.js").read_text(encoding="utf-8")


def test_rotation_axis_follows_current_screen_up_instead_of_world_up():
    active = CONTROLS.split("// Replace the legacy spherical update above", 1)[1]
    assert "const yawAxis = new THREE.Vector3();" in active
    assert "yawAxis.copy( orbitUp ).normalize();" in active
    assert "yawQuaternion.setFromAxisAngle( yawAxis, yaw );" in active
    assert "const worldUp = new THREE.Vector3( 0, 1, 0 );" not in active


def test_rotation_scale_is_square_and_pointer_lifecycle_is_closed():
    assert CONTROLS.count("const referenceSize = Math.max( 1, Math.min( size.width, size.height ) );") == 2
    assert "setPointerCapture( activePointerId )" in CONTROLS
    assert "releasePointerCapture( activePointerId )" in CONTROLS
    assert "function onPointerCancel( event )" in CONTROLS
    assert "function onWindowBlur()" in CONTROLS
    assert "addEventListener( 'pointercancel', onPointerCancel )" in CONTROLS
    assert "window.addEventListener( 'blur', onWindowBlur )" in CONTROLS
