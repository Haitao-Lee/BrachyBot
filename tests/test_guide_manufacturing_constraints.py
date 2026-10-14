"""Final STL wall/guidance constraints, independently of requested cutters."""
import numpy as np
import pytest

from test_guide_bore_manifest import annular_mesh, bore_candidate, synthetic_agent
from utils.guide_manufacturing import build_production_bore_manifest
from web.guide_placement import verify_manufactured_geometry
from web.surgical_guide import generate_surgical_guide


def manifest(vertices, faces, candidates=None, length=1.):
    return build_production_bore_manifest(vertices, faces, candidates or [bore_candidate()],
        minimum_wall_mm=.35, minimum_guiding_length_mm=length)


def test_final_full_annulus_has_measured_wall_length_and_anatomy_gate():
    vertices, faces = annular_mesh(outer=2.)
    result = manifest(vertices, faces)
    bore = result['bores'][0]
    assert bore['eligible']
    assert bore['minimum_wall_lower_bound_mm'] >= .35
    assert 2.99 < bore['guiding_length_mm'] < 3.
    assert bore['production_constraint']['mechanical_strength'] == 'not_established'
    assert bore['current_anatomy_feasibility']['status'].startswith('requires_current_image')
    verify_manufactured_geometry({'vertices': vertices, 'faces': faces, 'bore_manifest': result})


def test_half_wall_probe_does_not_certify_required_full_wall():
    vertices, faces = annular_mesh(outer=1.55)
    result = manifest(vertices, faces)
    bore = result['bores'][0]
    assert bore['geometry_audit']['passed']
    assert not bore['eligible']
    assert bore['reason'] == 'insufficient_final_minimum_wall'


def test_short_or_absent_final_hole_never_becomes_available():
    vertices, faces = annular_mesh(end=.7)
    assert manifest(vertices, faces)['bores'][0]['reason'] == 'insufficient_final_guiding_length'
    vertices, faces = annular_mesh()
    candidate = bore_candidate(); candidate['center_local_mm'] = [0., 8., 0.]
    assert not manifest(vertices, faces, [candidate])['bores'][0]['eligible']


def test_boundary_thinning_between_old_wall_probes_is_rejected():
    vertices, faces = annular_mesh(outer=2., count=128)
    # Thin one outer-wall vertex between most old circumferential probes.
    vertices[128 + 1, 1:] *= 1.5 / 2.
    vertices[3 * 128 + 1, 1:] *= 1.5 / 2.
    bore = manifest(vertices, faces)['bores'][0]
    assert not bore['eligible']


def test_generation_records_final_constraints_without_changing_5mm_policy():
    guide = generate_surgical_guide(synthetic_agent(), {'geometry_resolution_mm': 1., 'auxiliary_density_profile': 'continuation_dense_v1'})
    result = guide['bore_manifest']
    assert result['production_constraint_version'] == 1
    assert guide['parameters']['truncation_margin_mm'] == 5.
    assert all('current_anatomy_feasibility' in bore for bore in result['bores'])
    for bore in result['bores']:
        if bore['eligible']:
            assert bore['minimum_wall_lower_bound_mm'] >= .35 - 2e-5
            assert bore['guiding_length_mm'] >= 1.
            assert bore['minimum_interbore_wall_mm'] is None or bore['minimum_interbore_wall_mm'] >= .35 - 2e-5
