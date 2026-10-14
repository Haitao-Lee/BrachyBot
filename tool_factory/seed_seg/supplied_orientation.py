"""Reuse the updated, pinned SeedFinder direction function without rewriting it.

Its XY-plane restriction and singleton/global fallbacks remain explicit
estimated evidence. This provider cannot approve its own axes or substitute
Fiducial orientation. It does not load the AE model or run CT inference.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import numpy as np

from utils.implant_reconstruction import (
    AxisDiagnostics, DepositionLine, ImageGeometry, OrientationProfile,
    SeedAxisReconstruction, SeedObservation, canonical_axis, check_execution,
    seed_presentation,
)


class SuppliedXYOrientationProvider:
    provider_id = "supplied-seedfinder-xy-deposition"

    def __init__(self, model_contract):
        if model_contract.artifact_schema != "native_model_v2":
            raise ValueError("The updated direction provider requires the v2 bundle contract")
        self.contract = model_contract
        self.provider_version = dict(model_contract.code_sha256)["seed_pipeline_deepdec_roi.py"]

    def _load_function(self):
        bundle = Path(self.contract.bundle_dir).resolve(strict=True)
        for name, digest in self.contract.code_sha256:
            path = bundle / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
                raise ValueError("The supplied direction source is not a bounded regular file")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("The supplied direction source changed since review")
        # The module contains the user's deterministic direction routine; no
        # replacement algorithm or model deserialization is introduced here.
        spec = importlib.util.spec_from_file_location(
            "_brachybot_pinned_seedfinder_" + self.provider_version[:16],
            bundle / "seed_pipeline_deepdec_roi.py",
        )
        if spec is None or spec.loader is None:
            raise ValueError("The supplied direction module cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.cluster_needles_xy_plane

    def estimate_seed_axes(self, image_ref, original_ct, detections, native_component_labels=None, *,
                           profile=OrientationProfile(), dimensions=None, coverage_status="unknown",
                           cancelled=None, deadline=None):
        check_execution(cancelled, deadline)
        if not image_ref.geometry.agrees_with(original_ct):
            raise ValueError("The original CT geometry does not match the captured image")
        detections = tuple(detections)
        if len(detections) > profile.max_detections:
            raise ValueError("The supplied direction input exceeds its configured bound")
        points = np.asarray([d.center_lps_mm for d in detections], dtype=float).reshape(-1, 3)
        function = self._load_function()
        check_execution(cancelled, deadline)
        # These are the exact parameters used by the updated run_pipeline.
        axes, groups = function(points, z_eps=2.0, xy_eps=5.0)
        check_execution(cancelled, deadline)
        axes = np.asarray(axes, dtype=float)
        groups = np.asarray(groups)
        if (axes.shape != points.shape or groups.shape != (len(points),)
                or not np.isfinite(axes).all() or not np.isfinite(groups).all()
                or not np.all(groups == groups.astype(int))):
            raise ValueError("The supplied direction routine returned invalid identities or axes")
        lines, line_for_group = [], {}
        for group in sorted(set(groups.tolist())):
            indices = np.flatnonzero(groups == group)
            if len(indices) < 2:
                continue
            check_execution(cancelled, deadline)
            group_points = points[indices]
            try:
                axis = np.asarray(canonical_axis(axes[indices[0]]))
            except ValueError:
                continue
            anchor = group_points.mean(axis=0)
            projection = (group_points - anchor) @ axis
            extent = float(np.ptp(projection))
            if extent <= 1e-8:
                continue
            residual = group_points - anchor - projection[:, None] * axis
            ids = tuple(detections[int(i)].detection_id for i in indices)
            line_id = uuid5(NAMESPACE_URL, self.provider_version + ":" + ":".join(ids)).hex
            lines.append(DepositionLine(
                line_id, tuple(anchor), tuple(axis), ids, extent,
                float(np.sqrt(np.mean(np.sum(residual ** 2, axis=1)))), 0,
                flags=("supplied_XY_heuristic", "not_an_observed_needle"),
            ))
            line_for_group[group] = line_id
        observations = []
        for index, detection in enumerate(detections):
            check_execution(cancelled, deadline)
            group = groups[index].item()
            flags = ["supplied_XY_plane_constraint_requires_review",
                     "not_independently_measured_capsule_axis"]
            if np.count_nonzero(groups == group) == 1:
                flags.append("supplied_global_direction_fallback_for_singleton")
            try:
                axis, source = canonical_axis(axes[index]), "provider_estimate"
            except ValueError:
                axis, source = None, "unknown"
                flags.append("supplied_axis_unavailable")
            if axis is not None and abs(axis[2]) > 1e-8:
                raise ValueError("The pinned XY provider changed its declared plane semantics")
            observations.append(SeedObservation(
                observation_id=uuid5(NAMESPACE_URL, str(image_ref) + ":" + self.provider_version + ":" + detection.detection_id).hex,
                detection_id=detection.detection_id, center_lps_mm=detection.center_lps_mm,
                axis_lps=axis, axis_source=source,
                local_diagnostics=AxisDiagnostics(flags=tuple(flags)),
                component_ids=detection.component_ids,
                candidate_line_ids=(line_for_group[group],) if group in line_for_group else (),
                diagnostics=tuple(flags), presentation=seed_presentation("review_needed", axis is not None, dimensions is not None),
                dimensions=dimensions, center_uncertainty_mm=detection.center_uncertainty_mm,
                component_association_status=detection.association_status,
            ))
        return SeedAxisReconstruction(
            uuid4().hex, uuid4().hex, 1, image_ref, tuple(observations), tuple(lines),
            profile, self.provider_id, self.provider_version, coverage_status=coverage_status,
            diagnostics=("native_algorithm_reused_without_modification",
                         "XY_plane_assumption_and_fallbacks_require_review",
                         "native_STL_is_visual_evidence_not_source_dimension_certification"),
        )
