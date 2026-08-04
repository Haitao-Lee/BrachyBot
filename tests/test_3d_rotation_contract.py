from pathlib import Path


def test_orbit_controls_uses_continuous_trackball_state():
    source = (
        Path(__file__).resolve().parents[1]
        / "web/app/static/js/OrbitControls.js"
    ).read_text(encoding="utf-8")

    # Reconstructing spherical coordinates at the poles can wrap the azimuth
    # by PI and make the model jump 180 degrees. The active update path now
    # carries camera orientation incrementally as a trackball pose.
    active = source.split("// Replace the legacy spherical update above", 1)[1]
    assert "trackball-style update" in active
    assert "this.update = function ()" in active
    assert "const yawQuaternion = new THREE.Quaternion();" in active
    assert "const pitchQuaternion = new THREE.Quaternion();" in active
    assert "scope.object.quaternion.premultiply( yawQuaternion ).normalize();" in active
    assert "scope.object.quaternion.premultiply( pitchQuaternion ).normalize();" in active
    assert "scope.object.up.copy( orbitUp ).normalize();" in active
    assert "scope.object.lookAt( scope.target );" not in active
    assert "spherical.makeSafe()" not in active
    assert "const _sphericalCarry" not in active
    assert "this.up0 = this.object.up.clone();" in source
    assert "scope.object.up.copy( scope.up0 );" in source
    assert "right.set( 1, 0, 0 ).applyQuaternion( scope.object.quaternion )" in active
    assert "this.syncExternalState = function ()" in source
    assert "getBoundingClientRect" in source
