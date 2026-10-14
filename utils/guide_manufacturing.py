"""Final-export constraints for reusable guide bores, without strength claims."""
from copy import deepcopy
import math

import numpy as np

from web.guide_placement import (
    GuidePlacementError, _axial_material_intervals, _basis, _digest, _unit,
    build_bore_manifest,
)


def _clip_axial(triangle, low, high):
    polygon = [point for point in triangle]
    for plane, sign in ((low, 1), (high, -1)):
        output = []
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            inside_a, inside_b = sign * (a[2] - plane) >= 0, sign * (b[2] - plane) >= 0
            if inside_a:
                output.append(a)
            if inside_a != inside_b:
                output.append(a + (b - a) * ((plane - a[2]) / (b[2] - a[2])))
        polygon = output
        if len(polygon) < 3:
            return []
    return [np.array([polygon[0], polygon[i], polygon[i + 1]]) for i in range(1, len(polygon) - 1)]


def _radial_bounds(triangles):
    xy = triangles[:, :, :2]
    lower = np.full(len(xy), np.inf)
    signs = []
    for i in range(3):
        start, end = xy[:, i], xy[:, (i + 1) % 3]
        edge = end - start
        factor = np.clip(-np.sum(start * edge, axis=1) / np.maximum(np.sum(edge * edge, axis=1), 1e-30), 0, 1)
        lower = np.minimum(lower, np.sum((start + factor[:, None] * edge) ** 2, axis=1))
        signs.append(start[:, 0] * end[:, 1] - start[:, 1] * end[:, 0])
    signs = np.stack(signs, axis=1)
    inside = ((np.all(signs >= -1e-12, axis=1) | np.all(signs <= 1e-12, axis=1))
              & (np.abs(signs.sum(axis=1)) > 1e-14))
    lower[inside] = 0
    return np.sqrt(lower), np.sqrt(np.sum(xy ** 2, axis=2).max(axis=1))


def _wall_span(projected, radius, wall, low, high):
    """Certify a material annulus by absence of any exact mesh boundary in it.

    The closed mesh supplies the inside/outside boundary; membership is checked
    once in the connected annulus. Unlike circumferential-only sampling, a slit
    or local thinning between probes still intersects this volume and fails.
    """
    tolerance = 2e-5  # Export decimal/numerical guard, not a printer tolerance.
    clipped = []
    overlap = (projected[:, :, 2].max(axis=1) > low) & (projected[:, :, 2].min(axis=1) < high)
    remaining = projected[overlap]
    full = (remaining[:, :, 2].min(axis=1) >= low) & (remaining[:, :, 2].max(axis=1) <= high)
    clipped.extend(remaining[full])
    for triangle in remaining[~full]:
        clipped.extend(_clip_axial(triangle, low, high))
    if not clipped:
        return None
    minimum, maximum = _radial_bounds(np.asarray(clipped))
    inner, outer = radius + tolerance, radius + wall + tolerance
    if np.any((minimum < outer) & (maximum > inner)):
        return None
    spans = _axial_material_intervals(projected, np.array([(inner + outer) / 2, 0.]))
    if not spans or not any(a <= low and b >= high for a, b in spans):
        return None
    # This is a conservative lower bound on complete annular material, not
    # a claim to have measured an arbitrarily distant outer surface exactly.
    return float(wall)


def final_wall_constraint(vertices, faces, bore, *, minimum_wall_mm, minimum_guiding_length_mm):
    axis = _unit(bore['axis_local'])
    first, second = _basis(axis)
    triangles = np.asarray(vertices)[np.asarray(faces)] - np.asarray(bore['center_local_mm'])
    projected = np.stack((triangles @ first, triangles @ second, triangles @ axis), axis=2)
    radius = float(bore['requested_radius_mm'])
    extent = radius + minimum_wall_mm + 4e-5
    nearby = np.all((projected[:, :, :2].max(axis=1) >= -extent)
                    & (projected[:, :, :2].min(axis=1) <= extent), axis=1)
    projected = projected[nearby]
    low, high = map(float, bore['connected_extent_axis_mm'])
    center = (low + high) / 2
    # A shorter continuous central span can remain useful on a curved plate.
    # Never certify the unsupported ends as guidance.
    half = (high - low) / 2 - 5e-5
    wanted = float(minimum_guiding_length_mm) / 2
    base = {'method': 'final_stl_closed_material_annulus_v1', 'minimum_wall_policy_mm': minimum_wall_mm,
            'minimum_guiding_length_policy_mm': minimum_guiding_length_mm,
            'mechanical_strength': 'not_established', 'printer_tolerance': 'not_established'}
    if half < wanted:
        return {**base, 'passed': False, 'reason': 'insufficient_final_guiding_length'}
    measured = _wall_span(projected, radius, minimum_wall_mm, center - wanted, center + wanted)
    if measured is None:
        return {**base, 'passed': False, 'reason': 'insufficient_final_minimum_wall'}
    left, right = wanted, half
    for _ in range(10):
        test = (left + right) / 2
        bound = _wall_span(projected, radius, minimum_wall_mm, center - test, center + test)
        if bound is None:
            right = test
        else:
            left, measured = test, bound
    start, end = center - left, center + left
    origin = np.asarray(bore['center_local_mm'])
    return {**base, 'passed': True, 'reason': None, 'minimum_wall_lower_bound_mm': measured,
            'guiding_length_mm': end - start, 'connected_extent_axis_mm': [start, end],
            'outer_intersection_local_mm': (origin + start * axis).tolist(),
            'inner_intersection_local_mm': (origin + end * axis).tolist()}


def build_production_bore_manifest(vertices, faces, candidates, *, minimum_wall_mm,
                                   minimum_guiding_length_mm, parameters=None, source_provenance=None):
    from web.surgical_guide import mesh_to_ascii_stl, parse_stl, mesh_validation, _segment_distance_mm

    if not math.isfinite(float(minimum_guiding_length_mm)) or minimum_guiding_length_mm <= 0:
        raise GuidePlacementError('An explicit positive manufacturing guidance length is required')
    manifest = build_bore_manifest(vertices, faces, candidates, minimum_wall_mm=minimum_wall_mm,
                                  parameters=parameters, source_provenance=source_provenance)
    exported_vertices, exported_faces = parse_stl(mesh_to_ascii_stl(vertices, faces), vertex_dtype=np.float64)
    closed = bool(mesh_validation(exported_vertices, exported_faces).get('watertight'))
    for bore in manifest['bores']:
        bore['current_anatomy_feasibility'] = {'status': 'requires_current_image_pose_and_anatomy_review'}
        if not bore['eligible']:
            continue
        check = (final_wall_constraint(exported_vertices, exported_faces, bore, minimum_wall_mm=minimum_wall_mm,
                                      minimum_guiding_length_mm=minimum_guiding_length_mm) if closed else
                 {'passed': False, 'reason': 'final_mesh_not_closed', 'mechanical_strength': 'not_established'})
        bore['production_constraint'] = check
        if not check['passed']:
            bore.update(eligible=False, manufacturing_outcome='unverified', reason=check['reason'])
            continue
        for key in ('guiding_length_mm', 'connected_extent_axis_mm', 'outer_intersection_local_mm',
                    'inner_intersection_local_mm', 'minimum_wall_lower_bound_mm'):
            bore[key] = check[key]
        bore['centerline_local_mm'] = [bore['outer_intersection_local_mm'], bore['inner_intersection_local_mm']]
    # Record clearance on the actual measured finite guide spans, including
    # crossing primary/auxiliary axes. A construction-layout promise is not QA.
    realized = [b for b in manifest['bores'] if b['eligible']]
    for bore in realized:
        distances = []
        for other in realized:
            if other is bore:
                continue
            distance = _segment_distance_mm(*(np.asarray(p) for p in (*bore['centerline_local_mm'], *other['centerline_local_mm'])))
            distances.append((distance - bore['requested_radius_mm'] - other['requested_radius_mm'], other['bore_id']))
        nearest = min(distances, default=(None, None))
        bore['minimum_interbore_wall_mm'], bore['nearest_bore_id'] = nearest
        bore['spacing_method'] = 'final_measured_finite_centerline_cylinder_clearance'
        if nearest[0] is not None and nearest[0] < minimum_wall_mm - 2e-5:
            bore.update(eligible=False, manufacturing_outcome='unverified', reason='insufficient_final_bore_spacing')
    manifest.update(production_constraint_version=1, minimum_guiding_length_policy_mm=minimum_guiding_length_mm,
                    mechanical_validation='not_established', realized_count=sum(b['eligible'] for b in manifest['bores']))
    manifest['manifest_sha256'] = _digest({k: v for k, v in manifest.items() if k != 'manifest_sha256'})
    return manifest
