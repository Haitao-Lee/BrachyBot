"""Bounded CPU pose estimation. All returned transforms push source to target."""
from dataclasses import dataclass
import time

import numpy as np
import SimpleITK as sitk

from web.guide_placement import GuidePlacementError, RigidTransform, fit_rigid_landmarks, _digest


@dataclass(frozen=True)
class RegistrationLimits:
    max_seconds: float = 45.
    max_edge: int = 96
    iterations: int = 100
    max_surface_points: int = 3000
    threads: int = 2

    def __post_init__(self):
        if (not 1 <= self.max_seconds <= 120 or not 24 <= self.max_edge <= 128
                or not 10 <= self.iterations <= 200 or not 256 <= self.max_surface_points <= 5000
                or not 1 <= self.threads <= 4):
            raise GuidePlacementError('Registration resource limits are invalid')


def image_payload(image):
    return {'array': sitk.GetArrayFromImage(image), 'spacing': image.GetSpacing(),
            'origin': image.GetOrigin(), 'direction': image.GetDirection()}


def from_payload(payload):
    image = sitk.GetImageFromArray(np.asarray(payload['array']))
    image.SetSpacing(tuple(payload['spacing']))
    image.SetOrigin(tuple(payload['origin']))
    image.SetDirection(tuple(payload['direction']))
    return image


def reduced_image(image, limits):
    size = np.asarray(image.GetSize())
    factor = max(1., float(size.max()) / limits.max_edge)
    output_size = np.maximum(4, np.ceil(size / factor).astype(int))
    spacing = np.asarray(image.GetSpacing()) * (size - 1) / np.maximum(1, output_size - 1)
    return sitk.Resample(image, output_size.tolist(), sitk.Transform(3, sitk.sitkIdentity),
                         sitk.sitkLinear, image.GetOrigin(), spacing.tolist(), image.GetDirection(),
                         -1000., sitk.sitkFloat32)


def matrix_of(transform):
    origin = np.asarray(transform.TransformPoint((0., 0., 0.)))
    matrix = np.eye(4)
    matrix[:3, 3] = origin
    matrix[:3, :3] = np.column_stack([np.asarray(transform.TransformPoint(tuple(row))) - origin for row in np.eye(3)])
    return RigidTransform.from_matrix(matrix).matrix()


def bounded_points(points, limit):
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.all(np.isfinite(points)) or len(points) < 8:
        raise GuidePlacementError('An observed guide needs at least eight finite surface points')
    return points[np.linspace(0, len(points) - 1, min(len(points), limit), dtype=int)]


def visible_guide_surface(image, roi, threshold, limits):
    """Reconstruct the selected material component from actual target CT voxels."""
    from scipy import ndimage
    from skimage.measure import marching_cubes

    if (not isinstance(roi, list) or len(roi) != 6 or any(type(v) is not int for v in roi)
            or not np.isfinite(threshold) or not -1000 <= threshold <= 5000):
        raise GuidePlacementError('Provide a bounded guide ROI in XYZ voxel indices and a finite material threshold')
    low, high = np.asarray(roi[:3]), np.asarray(roi[3:])
    if np.any(low < 0) or np.any(high > image.GetSize()) or np.any(high - low < 4):
        raise GuidePlacementError('Guide observation ROI is outside the selected target image')
    crop = sitk.RegionOfInterest(image, (high - low).tolist(), low.tolist())
    crop = reduced_image(crop, limits)
    mask = sitk.GetArrayFromImage(crop) >= threshold
    labels, count = ndimage.label(mask)
    counts = np.bincount(labels.ravel()); counts[0] = 0
    if not count or counts.max() < 16:
        raise GuidePlacementError('No reconstructable guide material is visible in the selected ROI')
    component = labels == int(counts.argmax())
    if any(np.any(face) for face in (component[0], component[-1], component[:, 0], component[:, -1], component[:, :, 0], component[:, :, -1])):
        raise GuidePlacementError('The selected guide component touches the ROI boundary; expand the ROI')
    vertices, faces, _, _ = marching_cubes(component.astype(np.uint8), level=.5)
    xyz = vertices[:, ::-1] * np.asarray(crop.GetSpacing())
    points = xyz @ np.asarray(crop.GetDirection()).reshape(3, 3).T + np.asarray(crop.GetOrigin())
    return bounded_points(points, limits.max_surface_points), {
        'source': 'current_ct_selected_roi_material_component', 'roi_index_xyz': roi,
        'threshold_hu': float(threshold), 'component_count': int(count), 'selected_component_voxels': int(component.sum()),
        'surface_sha256': _digest(points.tolist()), 'reconstruction_is_estimate': True,
        'vertices_lps_mm': points.tolist(), 'faces': faces.tolist()}


def surface_pose(source_points, observed_points, *, limits, max_residual_mm, ambiguity_margin_mm,
                 initial_matrix=None):
    from scipy.spatial import cKDTree
    from scipy.spatial.transform import Rotation

    source, target = bounded_points(source_points, limits.max_surface_points), bounded_points(observed_points, limits.max_surface_points)
    tree = cKDTree(target)
    starts = []
    if initial_matrix is not None:
        starts.append(RigidTransform.from_matrix(initial_matrix).matrix())
    for angles in ((0, 0, 0), (180, 0, 0), (0, 180, 0), (0, 0, 180), (90, 0, 0), (0, 90, 0), (0, 0, 90)):
        rotation = Rotation.from_euler('xyz', angles, degrees=True).as_matrix()
        matrix = np.eye(4); matrix[:3, :3] = rotation
        matrix[:3, 3] = target.mean(axis=0) - rotation @ source.mean(axis=0)
        starts.append(matrix)
    solutions = []
    deadline = time.monotonic() + limits.max_seconds
    for matrix in starts:
        transform = RigidTransform.from_matrix(matrix)
        for _ in range(limits.iterations):
            if time.monotonic() > deadline:
                raise GuidePlacementError('Registration time limit reached')
            _, indices = tree.query(transform.points(source))
            try:
                fit = fit_rigid_landmarks(source, target[indices], max_residual_mm=max(1000., max_residual_mm * 20))
            except GuidePlacementError:
                break
            updated = RigidTransform.from_matrix(fit['matrix'])
            change = np.linalg.norm(updated.matrix() - transform.matrix())
            transform = updated
            if change < 1e-6:
                break
        moved = transform.points(source)
        forward, reverse = tree.query(moved)[0], cKDTree(moved).query(target)[0]
        score = float(max(np.sqrt(np.mean(forward**2)), np.sqrt(np.mean(reverse**2))))
        maximum = float(max(forward.max(), reverse.max()))
        # Collapse equivalent converged starts; distinct symmetric poses stay.
        if not any(np.max(np.linalg.norm(RigidTransform.from_matrix(item['matrix']).points(source) - moved, axis=1)) < .1 for item in solutions):
            solutions.append({'matrix': transform.matrix().tolist(), 'rms_mm': score, 'max_residual_mm': maximum})
    solutions.sort(key=lambda row: row['rms_mm'])
    best = solutions[0]
    eigen = np.linalg.svd(source - source.mean(axis=0), compute_uv=False)
    ambiguous = (eigen[-1] < eigen[0] * 1e-3 or
                 (len(solutions) > 1 and solutions[1]['rms_mm'] - best['rms_mm'] <= ambiguity_margin_mm))
    failed = best['max_residual_mm'] > max_residual_mm
    return {'matrix': best['matrix'], 'method': 'visible_guide_multistart_rigid_icp_v1',
            'qc': {'ambiguous': bool(ambiguous), 'fit_failed': bool(failed), 'proper_rigid': True,
                   'bidirectional_rms_mm': best['rms_mm'], 'max_residual_mm': best['max_residual_mm'],
                   'residual_limit_mm': max_residual_mm, 'ambiguity_margin_mm': ambiguity_margin_mm,
                   'distinct_pose_count': len(solutions), 'alternatives': solutions,
                   'review_required': True, 'direct_guide_observation': True}}


def image_pose(source_image, target_image, *, limits, initial_matrix=None, source_roi=None, target_roi=None):
    """SimpleITK fixed=source, moving=target yields source-to-target point push.

    Resampling a source overlay in the target grid uses its inverse. Neither
    equal grid metadata nor optimizer termination establishes physical fit.
    """
    def crop(image, roi):
        if roi is None:
            return image
        if not isinstance(roi, list) or len(roi) != 6 or any(type(v) is not int for v in roi):
            raise GuidePlacementError('Image registration ROI requires six XYZ voxel indices')
        low, high = np.asarray(roi[:3]), np.asarray(roi[3:])
        if np.any(low < 0) or np.any(high > image.GetSize()) or np.any(high - low < 8):
            raise GuidePlacementError('Image registration ROI is outside its image')
        return sitk.RegionOfInterest(image, (high - low).tolist(), low.tolist())

    source, target = reduced_image(crop(source_image, source_roi), limits), reduced_image(crop(target_image, target_roi), limits)
    for image in (source, target):
        array = sitk.GetArrayViewFromImage(image)
        if not np.all(np.isfinite(array)) or float(np.std(array)) < 5:
            raise GuidePlacementError('Selected images lack sufficient finite intensity variation for registration')
    transform = sitk.CenteredTransformInitializer(source, target, sitk.Euler3DTransform(), sitk.CenteredTransformInitializerFilter.GEOMETRY)
    if initial_matrix is not None:
        matrix = RigidTransform.from_matrix(initial_matrix).matrix()
        transform.SetCenter((0., 0., 0.)); transform.SetMatrix(matrix[:3, :3].ravel().tolist())
        transform.SetTranslation(matrix[:3, 3].tolist())
    registration = sitk.ImageRegistrationMethod()
    registration.SetNumberOfThreads(limits.threads)
    registration.SetMetricAsMattesMutualInformation(32)
    registration.SetMetricSamplingStrategy(registration.REGULAR)
    registration.SetMetricSamplingPercentage(.3, 1771)
    registration.SetInterpolator(sitk.sitkLinear)
    registration.SetOptimizerAsRegularStepGradientDescent(1., .002, limits.iterations, .5)
    registration.SetOptimizerScalesFromPhysicalShift()
    registration.SetShrinkFactorsPerLevel([2, 1])
    registration.SetSmoothingSigmasPerLevel([1., 0.])
    registration.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    registration.SetInitialTransform(transform, inPlace=False)
    deadline = time.monotonic() + limits.max_seconds
    registration.AddCommand(sitk.sitkIterationEvent, lambda: registration.StopRegistration() if time.monotonic() > deadline else None)
    fitted = registration.Execute(source, target)
    if time.monotonic() > deadline:
        raise GuidePlacementError('Registration time limit reached')
    matrix = matrix_of(fitted)
    warped = sitk.Resample(target, source, fitted, sitk.sitkLinear, -1000., sitk.sitkFloat32)
    validity = sitk.Image(target.GetSize(), sitk.sitkUInt8)
    validity.CopyInformation(target)
    valid = sitk.Resample(validity + 1, source, fitted, sitk.sitkNearestNeighbor, 0)
    mask = sitk.GetArrayViewFromImage(valid) > 0
    overlap = float(mask.mean())
    if overlap < .15:
        raise GuidePlacementError('Image registration has insufficient physical overlap')
    a, b = sitk.GetArrayViewFromImage(source)[mask], sitk.GetArrayViewFromImage(warped)[mask]
    correlation = float(np.corrcoef(a, b)[0, 1]) if min(np.std(a), np.std(b)) > 1e-6 else 0.
    # Image registration cannot observe a printed guide uniquely. Direct fit
    # review and optional corresponding guide landmarks supply that evidence.
    return {'matrix': matrix.tolist(), 'method': 'simpleitk_anatomy_rigid_estimated_guide_pose_v1',
            'qc': {'proper_rigid': True, 'ambiguous': False, 'fit_failed': not np.isfinite(correlation) or correlation < .1,
                   'overlap_fraction': overlap, 'intensity_correlation': correlation,
                   'metric': float(registration.GetMetricValue()), 'optimizer_stop': registration.GetOptimizerStopConditionDescription(),
                   'direct_guide_observation': False, 'anatomy_to_guide_pose_is_estimate': True,
                   'guide_pose_observability': 'requires_direct_overlay_review', 'review_required': True,
                   'soft_tissue_nonrigid': 'separate_not_performed'}}


def run_registration(payload):
    limits = RegistrationLimits(**payload.get('limits', {}))
    guide = payload['guide']
    request = payload['request']
    target = from_payload(payload['target'])
    mode = request['method']
    if mode in {'auto', 'visible_guide'} and request.get('guide_roi_index_xyz') is not None:
        observed, evidence = visible_guide_surface(target, request['guide_roi_index_xyz'], request['guide_threshold_hu'], limits)
        result = surface_pose(guide['vertices'], observed, limits=limits, max_residual_mm=request['max_residual_mm'],
                              ambiguity_margin_mm=request['ambiguity_margin_mm'], initial_matrix=request.get('initial_matrix'))
        result['evidence'] = evidence
        result['observed_surface'] = {'vertices_lps_mm': evidence.pop('vertices_lps_mm'), 'faces': evidence.pop('faces')}
        return result
    if mode == 'visible_guide':
        raise GuidePlacementError('Visible-guide registration requires a selected current guide ROI')
    source = from_payload(payload['source'])
    result = image_pose(source, target, limits=limits, initial_matrix=request.get('initial_matrix'),
                        source_roi=request.get('source_roi_index_xyz'), target_roi=request.get('target_roi_index_xyz'))
    local_to_source = RigidTransform.from_matrix(guide['bore_manifest']['guide_local_to_source_lps']).matrix()
    result['source_to_target_matrix'] = result['matrix']
    result['matrix'] = (np.asarray(result['matrix']) @ local_to_source).tolist()
    result['evidence'] = {'source': 'explicit_preoperative_and_current_image_registration',
                          'source_roi_index_xyz': request.get('source_roi_index_xyz'),
                          'target_roi_index_xyz': request.get('target_roi_index_xyz')}
    return result


def registration_process(connection, payload):
    """Spawn entry point; the parent enforces cancellation and a hard deadline."""
    try:
        connection.send({'success': True, 'result': run_registration(payload)})
    except Exception as exc:
        connection.send({'success': False, 'error': str(exc)[:1000]})
    finally:
        connection.close()
