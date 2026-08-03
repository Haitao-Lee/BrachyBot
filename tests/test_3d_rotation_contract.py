from pathlib import Path


def test_orbit_controls_uses_continuous_pole_reflection():
    source = (
        Path(__file__).resolve().parents[1]
        / "web/app/static/js/OrbitControls.js"
    ).read_text(encoding="utf-8")

    # A negative polar angle must reflect to a small positive angle. Mapping
    # it to PI + epsilon and then clamping to PI produces a visible flip.
    assert "const rawPhi = spherical.phi;" in source
    assert "const wrappedPhi = ( ( rawPhi % twoPI ) + twoPI ) % twoPI;" in source
    assert "const poleParity = Math.abs( Math.floor( rawPhi / Math.PI ) ) % 2;" in source
    assert "_sphericalCarry.phi = rawPhi;" in source
    assert "const lastTarget = new THREE.Vector3();" in source
    assert "scope.target.distanceToSquared( lastTarget ) > 1e-10" in source
    assert "spherical.phi = twoPI - wrappedPhi;" in source
    assert "spherical.phi = Math.PI - spherical.phi" not in source
