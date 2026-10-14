"""Owned guide discovery and revision-fenced, review-pending rigid candidates.

The service captures trusted owner/Session identity, never swaps agent memory,
and writes candidates only through the existing timepoint CAS API. It does not
approve physical manufacture or placement, initialize a clinical plan, or alter
the source guide. HTTP and accepted-placement workflows remain separate.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Mapping
from dataclasses import asdict

import numpy as np

from web.guide_placement import (
    GuidePlacementError, RigidTransform, _digest, _placement_signature,
    create_guide_placement, estimate_landmark_placement, image_geometry_identity,
    verify_manufactured_geometry,
    review_guide_placement,
)


def guide_manifest_summary(guide):
    """Expose recorded final-STL evidence without claiming current mesh QA."""
    guide = guide if isinstance(guide, Mapping) else {}
    manifest = guide.get("bore_manifest")
    summary = {
        "guide_version": guide.get("version"), "planning_id": guide.get("planning_id"),
        "density_profile": (guide.get("parameters") or {}).get("auxiliary_density_profile", "not_recorded"),
        "manifest_available": False, "manufacturing_confirmation": "not_recorded",
        "mechanical_validation": "not_established", "physical_placement": "not_established",
        "memory_path": "surgical_guide.bore_manifest", "legacy_center_only_eligible": False,
        "declared_manufactured_guide_id": guide.get("manufactured_guide_id"),
    }
    if not isinstance(manifest, Mapping):
        return {**summary, "reason": "no_audited_bore_manifest"}
    expected = _digest({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    if manifest.get("schema_version") != 1 or manifest.get("manifest_sha256") != expected:
        return {**summary, "reason": "invalid_manifest_identity"}
    bores = manifest.get("bores")
    if not isinstance(bores, list):
        return {**summary, "reason": "invalid_bore_inventory"}
    if any(not isinstance(bore, Mapping) for bore in bores):
        return {**summary, "reason": "invalid_bore_inventory"}
    outcomes = {name: sum(bore.get("manufacturing_outcome") == name for bore in bores)
                for name in ("realized", "skipped", "unverified")}
    eligible = [bore for bore in bores if bore.get("eligible") is True
                and bore.get("manufacturing_outcome") == "realized"]
    return {**summary, "manifest_available": True, "manifest_identity_checked": True,
            "mesh_identity_checked": False, "evidence": "recorded_final_stl_audit_not_recomputed",
            "schema_version": manifest["schema_version"], "geometry_id": manifest["geometry_id"],
            "mesh_sha256": manifest["mesh_sha256"], "stl_sha256": manifest["stl_sha256"],
            "manifest_sha256": manifest["manifest_sha256"], "candidate_count": len(bores),
            "eligible_bore_count": len(eligible), "outcomes": outcomes,
            "eligible_by_kind": {kind: sum(bore.get("kind") == kind for bore in eligible)
                                 for kind in ("primary", "auxiliary")},
            "minimum_wall_policy_mm": manifest.get("minimum_wall_policy_mm"),
            "source_provenance": deepcopy(manifest.get("source_provenance") or {}),
            "placement_requires_review": True}


def guide_manifest_page(guide, *, offset=0, limit=20):
    """Bounded exact recorded inventory; no mesh hydration or regeneration."""
    if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 32):
        raise GuidePlacementError("Manifest pagination requires a nonnegative offset and 1 to 32 rows")
    summary = guide_manifest_summary(guide)
    if not summary["manifest_available"]:
        return {"summary": summary, "bores": [], "next_offset": None, "total": 0}
    rows = guide["bore_manifest"]["bores"]
    stop = min(offset + limit, len(rows))
    return {"summary": summary, "bores": deepcopy(rows[offset:stop]), "offset": offset,
            "next_offset": stop if stop < len(rows) else None, "total": len(rows)}


class GuideSourceImageError(GuidePlacementError):
    """Public recovery is localized; technical provenance details stay in logs."""

    error_code = 'guide_source_image_unverified'


class GuidePlacementService:
    """Session-owned storage service, with no caller-selected owner or Session."""

    def __init__(self, agent):
        config = getattr(agent, "config", {}) or {}
        self.store = getattr(agent, "_workspace_store", None)
        self.owner_id = config.get("_workspace_owner_id")
        self.session_id = config.get("_workspace_session_id")
        if self.store is None or not self.owner_id or not self.session_id:
            raise GuidePlacementError("An authenticated Session workspace is required")

    def _snapshot(self, identifier):
        return self.store.load_timepoint_snapshot(self.owner_id, self.session_id, identifier, decode_arrays=False)

    def _decode(self, value):
        from web.workspace_store import _decode_artifacts

        return _decode_artifacts(value, self.store.workspace_root(self.owner_id, self.session_id))

    @staticmethod
    def _results(snapshot):
        from web.workspace_store import _restore_json
        # Restores only JSON tuple/key markers. Numerical arrays remain lazy;
        # this also reads legacy signed read-sets without hashing wire tags.
        return _restore_json((snapshot.get("agent") or {}).get("planning_results") or {})

    @staticmethod
    def _result_sets(snapshot):
        """Current and acquisition-archived results, without hydrating arrays."""
        yield GuidePlacementService._results(snapshot)
        for resource in (snapshot.get('image_resources') or {}).values():
            if isinstance(resource, Mapping):
                yield GuidePlacementService._results(resource)

    @staticmethod
    def guide_records(snapshot):
        """Include immutable older Planning guides after a planning-only replan."""
        records = []
        for results in GuidePlacementService._result_sets(snapshot):
            records.extend([results.get('surgical_guide'), *(results.get('surgical_guide_versions') or [])])
            for key,value in results.items():
                if str(key).startswith('planning_run:') and isinstance(value,Mapping):
                    records.extend([value.get('surgical_guide'),*(value.get('surgical_guide_versions') or [])])
        return [record for record in records if isinstance(record,Mapping)]

    @staticmethod
    def _guide(snapshot, version):
        if type(version) is not int or version <= 0:
            raise GuidePlacementError("An explicit positive source guide version is required")
        records = GuidePlacementService.guide_records(snapshot)
        candidates = [record for record in records if isinstance(record, Mapping) and record.get("version") == version]
        if not candidates:
            raise GuidePlacementError("The exact source guide version is unavailable")
        for record in candidates:
            manifest = record.get("bore_manifest") or {}
            for key in ("geometry_id", "mesh_sha256", "stl_sha256"):
                if record.get(key) is not None and manifest.get(key) is not None and record[key] != manifest[key]:
                    raise GuidePlacementError("Source guide metadata conflicts with its immutable bore manifest")
        identities = {tuple(record.get(key) or (record.get("bore_manifest") or {}).get(key)
                            for key in ("geometry_id", "mesh_sha256", "stl_sha256", "manifest_sha256"))
                      for record in candidates}
        if len(identities) != 1:
            raise GuidePlacementError("Source guide version has conflicting geometry identities")
        if len({(record.get('planning_id'), record.get('source_plan_signature')) for record in candidates}) != 1:
            raise GuidePlacementError('Source guide version has conflicting Planning provenance; explicit guide selection is required')
        # A decoded alias is preferable to an otherwise identical metadata shell.
        return next((record for record in candidates if record.get("vertices") is not None and record.get("faces") is not None), candidates[0])

    def manifest(self, *, source_timepoint_id, guide_version, offset=0, limit=20):
        snapshot = self._snapshot(source_timepoint_id)
        page = guide_manifest_page(self._guide(snapshot, guide_version), offset=offset, limit=limit)
        page["scope"] = {"session_id": self.session_id, "source_timepoint_id": source_timepoint_id,
                         "source_state_revision": snapshot["timepoint_state_revision"]}
        return page

    def _source_target(self, source_id, target_id, version):
        if source_id == target_id:
            raise GuidePlacementError("Guide transfer requires distinct source and target timepoints")
        source, target = self._snapshot(source_id), self._snapshot(target_id)
        if source["timepoint"]["stage"] != "preoperative":
            raise GuidePlacementError("Source guide must belong to a preoperative timepoint")
        target_record = target["timepoint"]
        if (target_record["stage"] != "intraoperative"
                or target_record.get("preoperative_timepoint_id") != source_id):
            raise GuidePlacementError("Target must explicitly reference this preoperative source")
        # Decode only the selected frozen guide, not every historical guide,
        # dose array, segmentation or source CT in the timepoint snapshot.
        guide = self._decode(self._guide(source, version))
        verify_manufactured_geometry(guide)
        return source, target, guide

    def _target_ct_image(self, snapshot):
        """Use saved current CT data and physical metadata, never source CT."""
        import SimpleITK as sitk

        results = GuidePlacementService._results(snapshot)
        if snapshot.get('image_collection') is not None:
            from web.timepoint_images import TimepointImageService
            collection = snapshot['image_collection']
            identifier = collection.get('planning_reference_image_id')
            if not identifier:
                raise GuidePlacementError('Select an explicit owned planning reference image')
            bridge = TimepointImageService(self.store).planning_reference_bridge(
                self.owner_id, self.session_id, snapshot['timepoint_id'], load_pixels=True, require_ct=True)
            if bridge['planning_reference_image_id'] != identifier:
                raise GuidePlacementError('Planning reference changed after registration input capture')
            image = bridge['ct_image']
            if np.prod(image.GetSize(), dtype=np.int64) > 64_000_000:
                raise GuidePlacementError('Selected image exceeds the bounded registration input size')
            return image
        if results.get("images") and not results.get("planning_reference_image_id"):
            raise GuidePlacementError("An explicit current planning reference image is required")
        if results.get("images"):
            records = results["images"]
            records = list(records.values()) if isinstance(records, Mapping) else records
            selected = [record for record in records if isinstance(record, Mapping)
                        and record.get("image_id", record.get("id")) == results["planning_reference_image_id"]]
            if len(selected) != 1:
                raise GuidePlacementError("The explicit planning reference image is unavailable or ambiguous")
            record = selected[0]
            array = self._decode(record.get("ct_data", record.get("data")))
            if array is not None:
                metadata = record.get("geometry") or record
                image = sitk.GetImageFromArray(np.asarray(array))
                try:
                    image.SetSpacing(tuple(metadata.get("ct_spacing", metadata.get("spacing"))))
                    image.SetOrigin(tuple(metadata.get("ct_origin", metadata.get("origin"))))
                    image.SetDirection(tuple(metadata.get("ct_direction", metadata.get("direction"))))
                except (TypeError, RuntimeError) as exc:
                    raise GuidePlacementError("Selected image requires explicit physical geometry") from exc
            else:
                from pathlib import Path
                path_value = record.get("path", record.get("file_path", record.get("owned_path")))
                if not isinstance(path_value, str):
                    raise GuidePlacementError("The selected reference image needs owned data or an owned file path")
                root = self.store.workspace_root(self.owner_id, self.session_id).resolve()
                path = Path(path_value)
                path = (path if path.is_absolute() else root / path).resolve()
                if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 512 * 1024**2:
                    raise GuidePlacementError("Selected image file is unavailable or outside this owned Session")
                reader = sitk.ImageFileReader(); reader.SetFileName(str(path)); reader.ReadImageInformation()
                if reader.GetDimension() != 3 or np.prod(reader.GetSize(), dtype=np.int64) > 64_000_000:
                    raise GuidePlacementError("Selected reference image exceeds the bounded registration input size")
                image = reader.Execute()
            if image.GetDimension() != 3 or np.prod(image.GetSize(), dtype=np.int64) > 64_000_000:
                raise GuidePlacementError("Selected reference must be a bounded three-dimensional image")
            return image
        image = results.get("ct_image")
        if not isinstance(image, sitk.Image):
            # Current CT is the only target clinical array needed here. Dose,
            # CTV/OAR and implant arrays remain encoded for this pose operation.
            array = self._decode(results.get("ct_data"))
            if (array is None or np.asarray(array).ndim != 3 or not all(
                    results.get(key) is not None for key in ("ct_spacing", "ct_origin", "ct_direction"))):
                raise GuidePlacementError("Current target CT data and explicit physical geometry are required")
            if np.asarray(array).size > 64_000_000:
                raise GuidePlacementError('Current CT exceeds the bounded registration input size')
            image = sitk.GetImageFromArray(np.asarray(array))
            image.SetSpacing(tuple(self._decode(results["ct_spacing"])))
            image.SetOrigin(tuple(self._decode(results["ct_origin"])))
            image.SetDirection(tuple(self._decode(results["ct_direction"])))
        if image.GetDimension() != 3:
            raise GuidePlacementError("Target reference must be a three-dimensional CT")
        return image

    def _target_image(self, snapshot):
        image = self._target_ct_image(snapshot)
        results = GuidePlacementService._results(snapshot)
        identifier = (snapshot.get('image_collection') or {}).get('planning_reference_image_id') or results.get("planning_reference_image_id") or results.get("ct_image_id") or "ct_data:" + snapshot["timepoint_id"]
        return self._image_identity(image, identifier)

    @staticmethod
    def _image_identity(image, identifier):
        import SimpleITK as sitk
        grid = image_geometry_identity(image, image_id="grid", image_revision="grid")
        digest = hashlib.sha256(grid["geometry_id"].encode())
        array = sitk.GetArrayViewFromImage(image)
        digest.update(array.dtype.str.encode())
        digest.update(np.ascontiguousarray(array))
        # Legacy single-CT workspaces have a real, scoped ct_data key but no
        # image UUID. Its content signature is an explicit compatibility
        # revision, not a claim about acquisition time or anatomical stability.
        identity = image_geometry_identity(image, image_id=identifier, image_revision=digest.hexdigest())
        return identity

    def _guide_source_image(self, snapshot, guide):
        """Resolve original acquisition from frozen parent, never current selection.

        Parent Planning stores the image dependency fingerprint, which includes
        the acquisition ID and receipt as well as canonical physical pixels.
        Archive/reference IDs are search hints only; a full match is required.
        Legacy compatibility is limited to one acquisition with no saved leaf.
        """
        import SimpleITK as sitk
        from web.timepoint_images import TimepointImageService, reference_receipt, geometry_metadata
        from web.timepoint_resources import fingerprint
        from tool_factory.seed_plan.continuation_support import image_signature
        from utils.image_limits import image_header
        from web.timepoints import TimepointError

        planning_id = guide.get('planning_id')
        manifest_source = guide['bore_manifest'].get('source_provenance') or {}
        for key in ('planning_id', 'source_plan_signature'):
            if manifest_source.get(key) is not None and manifest_source[key] != guide.get(key):
                raise GuideSourceImageError('Guide and immutable manifest disagree on source Planning provenance')
        leaves, hints = set(), []
        # Acquisition archives are better hints than current aliases, which
        # may contain an older parent while pointing at a newer reference.
        for results in reversed(list(self._result_sets(snapshot))):
            parent = results.get('planning_run:' + str(planning_id)) if planning_id else None
            if not isinstance(parent, Mapping):
                continue
            leaf = (parent.get('timepoint_resource_state') or {}).get('fingerprints', {}).get('image')
            if leaf:
                leaves.add(leaf)
                identifier = results.get('planning_reference_image_id')
                if identifier and identifier not in hints:
                    hints.append(identifier)
        if len(leaves) > 1:
            raise GuideSourceImageError('Original guide parent has conflicting source image fingerprints; review provenance')
        expected = next(iter(leaves), None)
        collection = snapshot.get('image_collection')
        if collection is None:
            results = self._results(snapshot)
            if len(results.get('images') or ()) > 1 or snapshot.get('image_resources'):
                raise GuideSourceImageError('Original guide source image is unavailable; review provenance or use direct visible-guide fit')
            image = self._target_ct_image(snapshot)
            if int(np.prod(image.GetSize(), dtype=np.int64)) > 64_000_000:
                raise GuideSourceImageError('Original CT exceeds the bounded registration input size')
            identifier = results.get('planning_reference_image_id') or results.get('ct_image_id') or 'ct_data:' + snapshot['timepoint_id']
            identity = self._image_identity(image, identifier)
            if expected:
                receipt = results.get('planning_reference_receipt') or {}
                leaf = fingerprint({'content': image_signature(image),
                    'reference_image_id': results.get('planning_reference_image_id'),
                    'reference': {k: receipt.get(k) for k in ('image_id', 'source_sha256', 'volume_sha256',
                        'voxel_sha256', 'geometry_signature', 'frame_index', 'modality')}})
                if leaf != expected:
                    raise GuideSourceImageError('Original single-CT image differs from the saved parent fingerprint; review provenance or use direct visible-guide fit')
            return image, {'policy': 'saved_parent_single_ct_fingerprint' if expected else 'legacy_single_ct_content_fenced',
                           'planning_id': planning_id, 'parent_image_fingerprint': expected,
                           'image': identity, 'original_acquisition_verified': bool(expected)}
        records = collection['images']
        if not expected and (len(records) != 1 or snapshot.get('image_resources')):
            raise GuideSourceImageError('Original guide source image provenance is unavailable in a multi-image history; review provenance or use direct visible-guide fit')
        # Prefer captured acquisition IDs. Fingerprint-only checkpoints without
        # such hints use a small exhaustive search, never first-match selection.
        identifiers = list(hints)
        if len(records) <= 8:
            identifiers.extend(sorted(set(records) - set(hints)))
        elif not hints:
            raise GuideSourceImageError('Original guide image lookup exceeds the bounded provenance search; explicit provenance review is required')
        if len(identifiers) > 8:
            raise GuideSourceImageError('Original guide image lookup exceeds the bounded provenance search; explicit provenance review is required')
        matches, voxels = [], 0
        images = TimepointImageService(self.store)
        try:
            for identifier in identifiers:
                record = records.get(identifier)
                if not record or record.get('status') != 'active':
                    continue
                if record.get('modality') not in {'CT', 'CBCT'}:
                    continue
                path, record = images.source_file(self.owner_id, self.session_id, snapshot['timepoint_id'], identifier)
                images.source_file(self.owner_id, self.session_id, snapshot['timepoint_id'], identifier, original=True)
                reader = image_header(path)
                voxels += int(np.prod(reader.GetSize(), dtype=np.int64))
                if reader.GetDimension() != 3 or reader.GetNumberOfComponents() != 1 or voxels > 64_000_000:
                    raise GuideSourceImageError('Original guide image lookup exceeds the bounded registration input size')
                image = reader.Execute()
                if (geometry_metadata(image)['geometry_signature'] != record['geometry']['geometry_signature']
                        or hashlib.sha256(sitk.GetArrayFromImage(image).tobytes()).hexdigest() != record['voxel_sha256']):
                    raise GuideSourceImageError('Original guide image pixels or geometry disagree with the owned receipt')
                receipt = reference_receipt(collection, record)
                receipt.pop('reference_revision')  # selection history is not acquisition identity
                leaf = fingerprint({'content': image_signature(image), 'reference_image_id': identifier,
                    'reference': {k: receipt[k] for k in ('image_id', 'source_sha256', 'volume_sha256',
                        'voxel_sha256', 'geometry_signature', 'frame_index', 'modality')}})
                if expected is None or leaf == expected:
                    match = (image, {'policy': 'saved_parent_image_fingerprint' if expected else 'legacy_single_owned_acquisition',
                        'planning_id': planning_id, 'parent_image_fingerprint': expected, 'receipt': receipt,
                        'image': self._image_identity(image, identifier), 'original_acquisition_verified': bool(expected)})
                    if expected:
                        # The leaf hashes the unique acquisition ID too. This
                        # is exact provenance resolution, not a first-image policy.
                        return match
                    matches.append(match)
        except (TimepointError, OSError, RuntimeError, ValueError) as exc:
            raise GuideSourceImageError('Original guide source image is unavailable or changed; review provenance or use direct visible-guide fit') from exc
        if len(matches) != 1:
            raise GuideSourceImageError('Original guide source image is unavailable or ambiguous; review provenance or use direct visible-guide fit')
        return matches[0]

    def _check_source_image(self, source, guide, binding):
        if binding.get('source_image'):
            if not binding.get('source_provenance'):
                raise GuideSourceImageError('Image-derived placement lacks verified original source provenance; estimate it again')
            image, provenance = self._guide_source_image(source, guide)
            if (binding.get('source_provenance') != provenance or binding['source_image'] != provenance['image']):
                raise GuideSourceImageError('Original guide source image provenance changed after registration; estimate it again')
            return image, provenance

    def estimate(self, *, source_timepoint_id, target_timepoint_id, guide_version,
                 manufactured_guide_id, expected_state_revision, method, matrix=None,
                 source_landmarks=None, target_landmarks=None, max_residual_mm=None,
                 evidence_source=None):
        if type(expected_state_revision) is not int or expected_state_revision < 0:
            raise GuidePlacementError("An explicit target state revision is required")
        if not isinstance(manufactured_guide_id, str) or not manufactured_guide_id.strip() or len(manufactured_guide_id) > 160:
            raise GuidePlacementError("A bounded declared manufactured guide identity is required")
        if method not in {"manual_rigid", "landmarks"}:
            raise GuidePlacementError("Supported candidate methods are manual_rigid and landmarks")
        with self.store._case_guard(self.owner_id, self.session_id):
            execution_context = self.store.capture_timepoint_context(self.owner_id, self.session_id, target_timepoint_id)
            source, target, guide = self._source_target(source_timepoint_id, target_timepoint_id, guide_version)
            if target["timepoint"].get("legacy_default"):
                raise GuidePlacementError("Legacy default target candidate CAS publication is not wired yet")
            if target["timepoint_state_revision"] != expected_state_revision:
                raise GuidePlacementError("Target timepoint state changed before pose estimation")
            declared = guide.get("manufactured_guide_id")
            if declared and declared != manufactured_guide_id:
                raise GuidePlacementError("Declared manufactured guide differs from the source record")
            target_image = self._target_image(target)
            scope = {"session_id": self.session_id, "source_timepoint_id": source_timepoint_id,
                     "target_timepoint_id": target_timepoint_id, "guide_version": guide_version,
                     "source_state_revision": source["timepoint_state_revision"],
                     "target_input_state_revision": expected_state_revision,
                     "manufactured_identity_status": "declared_unconfirmed"}
            identity = {"manufactured_guide_id": manufactured_guide_id, "target_image": target_image}
            if method == "manual_rigid":
                if not isinstance(evidence_source, str) or not evidence_source.strip() or len(evidence_source) > 500:
                    raise GuidePlacementError("Manual placement requires direct evidence provenance")
                placement = create_guide_placement(guide, matrix, evidence={"source": evidence_source},
                                                    qc={"service_scope": scope, "proper_rigid": True}, **identity)
            else:
                if matrix is not None:
                    raise GuidePlacementError("Landmark candidates cannot also provide a manual matrix")
                for points in (source_landmarks, target_landmarks):
                    array = np.asarray(points)
                    if array.ndim != 2 or array.shape[1:] != (3,) or not 3 <= len(array) <= 64:
                        raise GuidePlacementError("Provide 3 to 64 corresponding 3D landmarks")
                placement = estimate_landmark_placement(guide, source_landmarks, target_landmarks,
                                                        max_residual_mm=max_residual_mm, **identity)
                placement["qc"]["service_scope"] = scope
                placement["candidate_sha256"] = _placement_signature(placement)
            placement['evidence']['input_readset'] = {
                'context': asdict(execution_context), 'target_image': target_image,
                'source_timepoint_id': source_timepoint_id, 'target_timepoint_id': target_timepoint_id,
                'guide_version': guide_version, 'manifest_sha256': guide['bore_manifest']['manifest_sha256']}
            from web.workspace_store import _safe_json
            placement = _safe_json(placement)
            placement['candidate_sha256'] = _placement_signature(placement)
            candidates = deepcopy(self._results(target).get("guide_placement_candidates") or {})
            if not isinstance(candidates, dict) or len(candidates) >= 32:
                raise GuidePlacementError("Candidate inventory requires explicit review/retention before adding more poses")
            candidates[placement["placement_id"]] = placement
            saved = self.store.save_timepoint_results(self.owner_id, self.session_id, target_timepoint_id,
                                                      {"guide_placement_candidates": candidates},
                                                      expected_state_revision=expected_state_revision,
                                                      execution_context=execution_context)
            return {"placement": placement, "scope": scope,
                    "saved_state_revision": saved["timepoint_state_revision"],
                    "review_state": "pending", "clinical_use_approved": False,
                    "mesh_changed": False, "published_to": "guide_placement_candidates"}

    def validate(self, *, source_timepoint_id, target_timepoint_id, guide_version, placement_id):
        """Read-only mathematical validation of a saved candidate and inputs."""
        with self.store._case_guard(self.owner_id, self.session_id):
            source, target, guide = self._source_target(source_timepoint_id, target_timepoint_id, guide_version)
            record = (self._results(target).get("guide_placement_candidates") or {}).get(placement_id)
            if not isinstance(record, Mapping):
                raise GuidePlacementError("The candidate is unavailable in this target timepoint")
            scope = record.get("qc", {}).get("service_scope", {})
            if (scope.get("session_id") != self.session_id or scope.get("source_timepoint_id") != source_timepoint_id
                    or scope.get("target_timepoint_id") != target_timepoint_id or scope.get("guide_version") != guide_version):
                raise GuidePlacementError("Candidate scope differs from the requested source or target")
            if record.get("candidate_sha256") != _placement_signature(record):
                raise GuidePlacementError("Stored candidate changed after estimation")
            manifest = guide["bore_manifest"]
            if guide.get("manufactured_guide_id") and guide["manufactured_guide_id"] != record["manufactured_guide_id"]:
                raise GuidePlacementError("Source manufactured guide identity changed after estimation")
            if any(record.get(key) != manifest[key] for key in ("geometry_id", "mesh_sha256", "stl_sha256", "manifest_sha256")):
                raise GuidePlacementError("Candidate refers to a different manufactured geometry")
            if record.get("target_image") != self._target_image(target):
                raise GuidePlacementError("Current target CT changed after candidate estimation")
            self._check_readset(record, target_timepoint_id)
            if record.get('source_to_target_matrix') and not record['evidence']['input_readset'].get('source_image'):
                raise GuideSourceImageError('Image-derived placement lacks original source provenance; estimate it again')
            self._check_source_image(source, guide, record['evidence']['input_readset'])
            RigidTransform.from_matrix(record["matrix"])
            return {"placement_id": placement_id, "scope": deepcopy(scope), "proper_rigid": True,
                    "geometry_identity_checked": True, "target_image_checked": True,
                    "review_state": record.get("review_state"), "clinical_use_approved": False,
                    "physical_placement": "not_established", "read_only": True}

    def _check_readset(self, record, target_timepoint_id):
        binding = record.get('evidence', {}).get('input_readset')
        if not binding:
            raise GuidePlacementError('The placement lacks a persisted source read-set; estimate it again')
        captured = binding['context']
        current = asdict(self.store.capture_timepoint_context(self.owner_id, self.session_id, target_timepoint_id))
        if (captured.get('owner_id') != self.owner_id or captured.get('session_id') != self.session_id
                or list(current['dependencies']) != list(captured['dependencies'])):
            raise GuidePlacementError('Source dependency changed after guide registration')
        frozen_target, current_target = captured['target'], current['target']
        for key in ('timepoint_id', 'stage', 'preoperative_timepoint_id', 'previous_intraoperative_timepoint_id', 'lifecycle_revision', 'legacy_default'):
            if current_target[key] != frozen_target[key]:
                raise GuidePlacementError('Registration target lifecycle or source association changed')

    def capture_registration(self, *, source_timepoint_id, target_timepoint_id, guide_version,
                             expected_state_revision, manufactured_guide_id, expected_clinical_revision=None):
        """Capture exact owned inputs before a bounded child process starts."""
        if type(expected_state_revision) is not int or expected_state_revision < 0:
            raise GuidePlacementError("An explicit nonnegative target state revision is required")
        if not isinstance(manufactured_guide_id, str) or not 1 <= len(manufactured_guide_id.strip()) <= 160:
            raise GuidePlacementError("Declare the physical printed guide identity")
        with self.store._case_guard(self.owner_id, self.session_id):
            context = self.store.capture_timepoint_context(self.owner_id, self.session_id, target_timepoint_id)
            source, target, guide = self._source_target(source_timepoint_id, target_timepoint_id, guide_version)
            if expected_state_revision > target['timepoint_state_revision']:
                raise GuidePlacementError('Target changed before registration capture')
            if expected_clinical_revision is None:
                if target['timepoint_state_revision'] != expected_state_revision:
                    raise GuidePlacementError('Target changed before registration capture')
            elif (type(expected_clinical_revision) is not int or expected_clinical_revision < 0
                    or expected_clinical_revision != target['timepoint_clinical_revision']):
                raise GuidePlacementError('Clinical inputs changed before registration capture')
            if guide.get('manufactured_guide_id') and guide['manufactured_guide_id'] != manufactured_guide_id:
                raise GuidePlacementError('Printed guide identity differs from the saved source guide')
            target_image = self._target_ct_image(target)
            profile = self._results(target).get('continuation_review_profile')
            binding = {'context': asdict(context), 'source_timepoint_id': source_timepoint_id,
                       'target_timepoint_id': target_timepoint_id, 'guide_version': guide_version,
                       'target_image': self._target_image(target), 'manifest_sha256': guide['bore_manifest']['manifest_sha256'],
                       'manufactured_guide_id': manufactured_guide_id, 'expected_state_revision': expected_state_revision}
            binding['expected_clinical_revision']=context.target.clinical_revision
            if profile:
                binding['review_profile_sha256'] = _digest(profile)
            return context, source, target, guide, target_image, binding

    def publish_registration(self, result, binding, context, *, job_id):
        """CAS includes persisted source dependency revisions within SQLite."""
        with self.store._case_guard(self.owner_id, self.session_id):
            source, target, guide = self._source_target(binding['source_timepoint_id'], binding['target_timepoint_id'], binding['guide_version'])
            if (self._target_image(target) != binding['target_image']
                    or guide['bore_manifest']['manifest_sha256'] != binding['manifest_sha256']):
                raise GuidePlacementError('Registration image or guide inputs changed before publication')
            if result.get('source_to_target_matrix') and not binding.get('source_image'):
                raise GuideSourceImageError('Image-derived registration requires original source provenance')
            self._check_source_image(source, guide, binding)
            if binding.get('review_profile_sha256') and binding['review_profile_sha256'] != _digest(self._results(target).get('continuation_review_profile')):
                raise GuidePlacementError('Confirmed guide/needle review profile changed during registration')
            scope = {'session_id': self.session_id, 'source_timepoint_id': binding['source_timepoint_id'],
                     'target_timepoint_id': binding['target_timepoint_id'], 'guide_version': binding['guide_version']}
            qc = {**result['qc'], 'service_scope': scope}
            candidate = create_guide_placement(guide, result['matrix'], manufactured_guide_id=binding['manufactured_guide_id'],
                       target_image=binding['target_image'], method=result['method'], qc=qc,
                       evidence={**result['evidence'], 'input_readset': deepcopy(binding), 'registration_job_id': job_id})
            if result.get('source_to_target_matrix'):
                candidate['source_to_target_matrix'] = result['source_to_target_matrix']
            if result.get('observed_surface'):
                candidate['observed_surface'] = result['observed_surface']
            from web.workspace_store import _safe_json
            candidate = _safe_json(candidate)
            candidate['candidate_sha256'] = _placement_signature(candidate)
            candidates = deepcopy(self._results(target).get('guide_placement_candidates') or {})
            recovered = next((row for row in candidates.values() if row.get('evidence', {}).get('registration_job_id') == job_id), None)
            if recovered:
                return recovered, target['timepoint_state_revision']
            if len(candidates) >= 32:
                raise GuidePlacementError('Review or retain the existing placement inventory before creating more')
            candidates[candidate['placement_id']] = candidate
            saved = self.store.save_timepoint_results(self.owner_id, self.session_id, binding['target_timepoint_id'],
                    {'guide_placement_candidates': candidates}, expected_clinical_revision=binding['expected_clinical_revision'], execution_context=context)
            return candidate, saved['timepoint_state_revision']

    def current_candidate(self, *, source_timepoint_id, target_timepoint_id, guide_version, placement_id):
        self.validate(source_timepoint_id=source_timepoint_id, target_timepoint_id=target_timepoint_id,
                      guide_version=guide_version, placement_id=placement_id)
        source, target, guide = self._source_target(source_timepoint_id, target_timepoint_id, guide_version)
        record = deepcopy(self._results(target)['guide_placement_candidates'][placement_id])
        binding = record.get('evidence', {}).get('input_readset')
        if binding:
            captured = binding['context']
            current = asdict(self.store.capture_timepoint_context(self.owner_id, self.session_id, target_timepoint_id))
            if current['dependencies'] != tuple(captured['dependencies']) and list(current['dependencies']) != list(captured['dependencies']):
                raise GuidePlacementError('Source dependency changed after guide registration')
            frozen_target = captured['target']; current_target = current['target']
            if any(current_target[k] != frozen_target[k] for k in ('stage', 'preoperative_timepoint_id', 'previous_intraoperative_timepoint_id', 'lifecycle_revision', 'legacy_default')):
                raise GuidePlacementError('Registration target lifecycle or source association changed')
            self._check_source_image(source, guide, binding)
        return source, target, guide, record

    def review(self, *, source_timepoint_id, target_timepoint_id, guide_version, placement_id,
               expected_state_revision, candidate_sha256, decision, profile_id, note,
               overlay_receipt=None, manufacturing_confirmed=False, expected_clinical_revision=None):
        with self.store._case_guard(self.owner_id, self.session_id):
            context = self.store.capture_timepoint_context(self.owner_id, self.session_id, target_timepoint_id)
            _, target, guide, record = self.current_candidate(source_timepoint_id=source_timepoint_id,
                  target_timepoint_id=target_timepoint_id, guide_version=guide_version, placement_id=placement_id)
            if (type(expected_state_revision) is not int or expected_state_revision < 0
                    or expected_state_revision > target['timepoint_state_revision']):
                raise GuidePlacementError('Target changed; reload the overlay before review')
            if expected_clinical_revision is None:
                if target['timepoint_state_revision'] != expected_state_revision:
                    raise GuidePlacementError('Target changed; reload the overlay before review')
            elif (type(expected_clinical_revision) is not int or expected_clinical_revision != target['timepoint_clinical_revision']):
                raise GuidePlacementError('Clinical inputs changed; reload the owned overlay before review')
            if candidate_sha256 != record['candidate_sha256']:
                raise GuidePlacementError('Review does not refer to the displayed placement hash')
            if not isinstance(note, str) or not 1 <= len(note.strip()) <= 1000:
                raise GuidePlacementError('Record an explicit guide-fit review note')
            if decision == 'accepted':
                profile = self._results(target).get('continuation_review_profile')
                if profile and (profile_id != profile.get('profile_id') or not profile.get('confirmed_by')):
                    raise GuidePlacementError('Use the confirmed current needle geometry review profile')
                if record.get('qc', {}).get('fit_failed'):
                    raise GuidePlacementError('Failed geometric fit requires a new placement estimate')
                if (not isinstance(overlay_receipt, Mapping) or overlay_receipt.get('candidate_sha256') != candidate_sha256
                        or overlay_receipt.get('target_image') != record['target_image']
                        or overlay_receipt.get('state_revision') != expected_state_revision
                        or expected_clinical_revision is not None and overlay_receipt.get('clinical_revision') != expected_clinical_revision
                        or set(overlay_receipt.get('dimensions', [])) != {'2d', '3d'}):
                    raise GuidePlacementError('Acceptance requires current 2D and 3D guide overlay review')
            reviewed = review_guide_placement(record, reviewer=self.owner_id, decision=decision, profile_id=profile_id,
                         evidence_reviewed=decision == 'accepted', manufacturing_confirmed=manufacturing_confirmed is True)
            reviewed['review'].update(note=note.strip(), overlay_receipt=deepcopy(overlay_receipt),
                 approval_scope='user_confirmed_rigid_guide_fit_not_mechanical_or_clinical_commissioning')
            candidates = deepcopy(self._results(target)['guide_placement_candidates']); candidates[placement_id] = reviewed
            updates = {'guide_placement_candidates': candidates}
            updates.update(continuation_baseline_record=None, continuation_search_record=None,
                           guide_current_feasibility=None)
            active = self._results(target).get('guide_placement') or {}
            if decision == 'accepted':
                updates['guide_placement'] = reviewed
                updates['guide_current_feasibility'] = self.feasibility(guide, reviewed, target)
            elif active.get('placement_id') == placement_id:
                updates['guide_placement'] = None
            saved = self.store.save_timepoint_results(self.owner_id, self.session_id, target_timepoint_id, updates,
                **({'expected_state_revision':expected_state_revision} if expected_clinical_revision is None
                    else {'expected_clinical_revision':expected_clinical_revision}), execution_context=context)
            return {'placement': reviewed, 'state_revision': saved['timepoint_state_revision'], 'clinical_use_approved': False}

    def feasibility(self, guide, placement, target):
        """Record actual current-anatomy results separately from immutable STL.

        No missing observation becomes an explicit empty obstacle inventory.
        This geometric report neither optimizes nor recomputes dose.
        """
        from web.guide_placement import BoreValidationProfile, CurrentCTGeometry, initialize_bore_trajectories
        from utils.ctv_targets import resolve_ctv_target
        from utils.implant_reconstruction import SeedAxisReconstruction

        values = self._results(target)
        profile_values = values.get('continuation_review_profile')
        current = (values.get('implanted_seed_reconstruction') or {}).get('by_timepoint', {}).get(target['timepoint_id'], {}).get('current')
        missing = []
        if not profile_values or not profile_values.get('confirmed_by'):
            missing.append('confirmed_needle_geometry_profile')
        if not current:
            missing.append('reviewed_current_fixed_seed_observations')
        if values.get('in_situ_needles') is None:
            missing.append('explicit_current_in_situ_needle_observations')
        ctv = resolve_ctv_target(lambda key, default=None: self._decode(values.get(key, default)))
        oar = self._decode(values.get('oar_array'))
        if ctv is None or oar is None:
            missing.append('current_ctv_and_oar')
        report = {'placement_id': placement['placement_id'], 'candidate_sha256': placement['candidate_sha256'],
                  'target_image': placement['target_image'], 'source_manifest_sha256': guide['bore_manifest']['manifest_sha256'],
                  'current_state_revision': target['timepoint_state_revision'], 'clinical_use_approved': False,
                  'mechanical_strength': 'not_established'}
        if missing:
            return {**report, 'status': 'pending_inputs', 'missing': missing}
        try:
            reconstruction = SeedAxisReconstruction.from_dict(current['reconstruction'])
            if not reconstruction.dose_input_ready or reconstruction.image_ref.timepoint_id != target['timepoint_id']:
                return {**report, 'status': 'pending_inputs', 'missing': ['accepted_current_fixed_seed_observations']}
            profile = BoreValidationProfile(**{key: profile_values[key] for key in ('profile_id', 'needle_radius_mm',
                'minimum_guiding_length_mm', 'obstacle_clearance_mm', 'maximum_depth_mm')})
            fixed = [dict(id=row.physical_seed_id or 'observed:' + row.observation_id, center_lps_mm=row.center_lps_mm,
                axis_lps=row.axis_lps, length_mm=row.dimensions.capsule_length_mm,
                radius_mm=row.dimensions.capsule_diameter_mm / 2)
                for row in reconstruction.observations if row.review_status == 'accepted']
            image = self._target_ct_image(target)
            from tool_factory.seed_plan.planning_pipeline import _body_mask_from_ct
            # Without a reviewed traversability classification, every recorded
            # OAR label is conservatively non-traversable in this guide report.
            anatomy = CurrentCTGeometry(image, identity=placement['target_image'], body_mask=_body_mask_from_ct(image),
                ctv_mask=np.asarray(ctv) > 0, oar_mask=np.asarray(oar) > 0)
            result = initialize_bore_trajectories(guide, placement, anatomy, profile=profile, fixed_seeds=fixed,
                in_situ_needles=self._decode(values['in_situ_needles']), channel_states=values.get('guide_channel_states'))
            result['per_bore'] = {row['bore_id']: {'feasible': True, 'candidate_id': row['candidate_id'],
                'skin_entry_lps_mm': row['skin_entry_lps_mm'], 'depth_from_skin_mm': row['depth_from_skin_mm']}
                for row in result['candidates']}
            result['per_bore'].update({row['bore_id']: {'feasible': False, 'reasons': row['reasons']} for row in result['rejected']})
            return {**report, 'status': 'evaluated', 'profile_sha256': profile.signature(),
                    'observation_revision_id': reconstruction.revision_id, 'anatomy_sha256': anatomy.anatomy_sha256,
                    'result': result, 'oar_policy': 'all_current_oar_labels_conservatively_nontraversable'}
        except (ValueError, TypeError, KeyError) as exc:
            return {**report, 'status': 'invalid_inputs', 'reason': str(exc)}
