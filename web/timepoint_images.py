"""Owned image collections and independently selected display/planning sources.

This service publishes through the existing immutable target-state/CAS boundary.
Only uploaded bytes create images. A filename or a model-supplied path is never
authority to read a server file. The original acquisition and the selected LPI
3-D volume are both retained, including when an image is recoverably deleted.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import time
import uuid
import zipfile

import numpy as np
import SimpleITK as sitk

from web.timepoints import (TimepointConflict, TimepointError,
    TimepointIntegrityError, TimepointNotFound, revision, timepoint_id, title)
from web.workspace_store import _safe_workspace_child


IMAGE_COLLECTION_VERSION = 1
MAX_IMAGES = 1024
MAX_UPLOAD_BYTES = 2 * 1024 ** 3
MODALITIES = frozenset({"CT", "CBCT", "MR", "PT", "US", "OT"})
ROLES = frozenset({"preop", "intraop", "unclassified"})
SOURCE_EXTENSIONS = (".nii.gz", ".nii", ".mha", ".nrrd", ".dcm", ".dicom")
INVALIDATED_RESOURCES = (
    "ctv", "oar", "skin", "implant_observations", "implanted_dose", "planned_dose",
    "total_dose", "metrics", "supplemental_plan", "manufactured_guide", "guide_pose",
    "registration", "report", "monitor", "planning", "needles", "seeds",
)
_HASH = re.compile(r"^[0-9a-f]{64}$")


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def geometry_metadata(image):
    dimension = image.GetDimension()
    size = list(image.GetSize())
    spacing = list(image.GetSpacing())
    origin = list(image.GetOrigin())
    direction = list(image.GetDirection())
    if (any(v <= 0 for v in size) or any(not math.isfinite(v) or v <= 0 for v in spacing)
            or not all(math.isfinite(v) for v in origin + direction)):
        raise TimepointError("Image geometry must be finite, with positive size and spacing")
    matrix = np.asarray(direction).reshape(dimension, dimension)
    if not np.allclose(matrix.T @ matrix, np.eye(dimension), atol=1e-5):
        raise TimepointError("Image direction must describe orthonormal physical axes")
    value = {"size": size, "shape": size[::-1], "spacing": spacing,
             "origin": origin, "direction": direction, "coordinate_system": "LPS",
             "spatial_unit": "mm", "dimension": dimension}
    value["geometry_signature"] = hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return value


def empty_collection(session_id, target_id):
    return {"schema_version": IMAGE_COLLECTION_VERSION, "session_id": session_id,
            "timepoint_id": target_id, "collection_revision": 0, "reference_revision": 0,
            "order": [], "images": {}, "display_image_id": None,
            "planning_reference_image_id": None, "journal": []}


def validate_collection(collection, session_id, target_id):
    if (not isinstance(collection, dict) or collection.get("schema_version") != IMAGE_COLLECTION_VERSION
            or collection.get("session_id") != session_id or collection.get("timepoint_id") != target_id):
        raise TimepointIntegrityError("The image collection belongs to another workspace")
    revision(collection.get("collection_revision"))
    revision(collection.get("reference_revision"))
    images, order = collection.get("images"), collection.get("order")
    if (not isinstance(images, dict) or len(images) > MAX_IMAGES or not isinstance(order, list)
            or len(order) != len(set(order)) or set(order) != set(images)):
        raise TimepointIntegrityError("Invalid image identities or order")
    for identifier, image in images.items():
        timepoint_id(identifier)
        if (not isinstance(image, dict) or image.get("id") != identifier
                or image.get("session_id") != session_id or image.get("timepoint_id") != target_id):
            raise TimepointIntegrityError("An image does not belong to this Session and target")
        title(image.get("name"))
        if (image.get("status") not in {"active", "trashed"} or image.get("modality") not in MODALITIES
                or image.get("role") not in ROLES):
            raise TimepointIntegrityError("Invalid image classification or lifecycle")
        prefix = f"inputs/timepoints/{target_id}/images/{identifier}/"
        for key in ("source_path", "volume_path"):
            value = image.get(key)
            if (not isinstance(value, str) or not value.startswith(prefix) or "\\" in value
                    or ":" in value or any(p in {".", ".."} for p in value.split("/"))):
                raise TimepointIntegrityError("An image file is not owned by its target and image")
        for key in ("source_sha256", "volume_sha256", "voxel_sha256"):
            if not isinstance(image.get(key), str) or not _HASH.fullmatch(image[key]):
                raise TimepointIntegrityError("An image is missing its content receipt")
        metadata = image.get("geometry")
        if (not isinstance(metadata, dict) or metadata.get("dimension") != 3
                or not _HASH.fullmatch(str(metadata.get("geometry_signature", "")))):
            raise TimepointIntegrityError("An image is missing its physical geometry")
        if type(image.get("show")) is not bool or image["show"] != (collection.get("display_image_id") == identifier):
            raise TimepointIntegrityError("Image backgrounds must be mutually exclusive")
    for field in ("display_image_id", "planning_reference_image_id"):
        identifier = collection.get(field)
        if identifier is not None and (identifier not in images or images[identifier]["status"] != "active"):
            raise TimepointIntegrityError("Selected image is unavailable")
    if not isinstance(collection.get("journal"), list):
        raise TimepointIntegrityError("Image change journal is unavailable")
    return collection


def reference_receipt(collection, image):
    return {"session_id": collection["session_id"], "timepoint_id": collection["timepoint_id"],
            "image_id": image["id"], "source_sha256": image["source_sha256"],
            "volume_sha256": image["volume_sha256"], "voxel_sha256": image["voxel_sha256"],
            "geometry_signature": image["geometry"]["geometry_signature"],
            "frame_index": image["frame_index"], "modality": image["modality"],
            "reference_revision": collection["reference_revision"]}


def bind_reference_results(state, updates, *, reference_image_id):
    """Server publication hook: attach every result to the captured source ID.

    Main must call this before its ArtifactEncoder/save_timepoint_results while
    holding its target guard, and still check captured clinical revision at CAS.
    Presentation and image visibility never participate in the scientific hash.
    """
    collection = state.get("image_collection")
    if not collection:
        raise TimepointConflict("Select an owned planning reference before publishing clinical results")
    validate_collection(collection, state["session_id"], state["timepoint_id"])
    if (reference_image_id is None or reference_image_id != collection["planning_reference_image_id"]):
        raise TimepointConflict("Clinical results belong to a different planning reference")
    image = collection["images"][reference_image_id]
    receipt = reference_receipt(collection, image)
    results = copy.deepcopy(dict(updates))
    prior = (state.get("agent") or {}).get("planning_results") or {}
    associations = copy.deepcopy(prior.get("clinical_resource_sources") or {})
    for key in results:
        if key not in {"clinical_resource_sources", "planning_reference_receipt"}:
            associations[key] = receipt
    results.update(planning_reference_image_id=reference_image_id,
                   planning_reference_receipt=receipt, clinical_resource_sources=associations)
    return results


class _LimitedStream:
    def __init__(self, stream, maximum):
        self.stream, self.maximum, self.read_bytes = stream, maximum, 0

    def read(self, count):
        data = self.stream.read(min(count, self.maximum - self.read_bytes + 1))
        self.read_bytes += len(data)
        if self.read_bytes > self.maximum:
            raise TimepointError("Image upload exceeds the supported byte limit")
        return data


class TimepointImageService:
    def __init__(self, store):
        self.store = getattr(store, "raw", store)

    def _read(self, user_id, session_id, target_id, *, metadata_only=False):
        timepoint_id(session_id)
        timepoint_id(target_id)
        catalog = self.store._timepoint_catalog(user_id, session_id)
        item = self.store._timepoint_record(catalog, target_id)
        # The store returns detached, checksum-verified state. Copying its full
        # DVH/history again for an image metadata read made every restore route
        # compete for the GIL and serialize large cases for tens of seconds.
        state = self.store._read_timepoint_state(user_id, session_id, item, image_metadata=metadata_only)
        state["session_id"], state["timepoint_id"] = session_id, target_id
        collection = state.setdefault("image_collection", empty_collection(session_id, target_id))
        validate_collection(collection, session_id, target_id)
        return catalog, item, state, collection

    def _editable(self, user_id, session_id, item, editor_token):
        if editor_token is None:
            raise TimepointError("An explicit human editor request is required for image changes")
        self.store.assert_editable(user_id, session_id, editor_token)
        if item["legacy_default"]:
            raise TimepointConflict("Detach the default target before changing its image sources")

    def _public(self, item, collection):
        images = []
        trashed = []
        for identifier in collection["order"]:
            image = copy.deepcopy(collection["images"][identifier])
            image.setdefault('color', '#888888')
            base = f"/api/sessions/{collection['session_id']}/timepoints/{collection['timepoint_id']}/images/{identifier}"
            image.update(title=image["name"], path=image["volume_path"], url=base + "/source",
                         original_url=base + "/original", geometry_signature=image["geometry"]["geometry_signature"],
                         planning_reference=identifier == collection["planning_reference_image_id"])
            (images if image["status"] == "active" else trashed).append(image)
        clinical_visible = (collection["display_image_id"] is not None
                            and collection["display_image_id"] == collection["planning_reference_image_id"])
        return {"session_id": collection["session_id"], "timepoint_id": collection["timepoint_id"],
                "collection_revision": collection["collection_revision"],
                "reference_revision": collection["reference_revision"], "images": images, "trashed_images": trashed,
                "display_image_id": collection["display_image_id"],
                "planning_reference_image_id": collection["planning_reference_image_id"],
                "timepoint_state_revision": item["state_revision"],
                "timepoint_clinical_revision": item.get("clinical_revision", 0),
                "clinical_visible": clinical_visible, "clear_clinical_view": not clinical_visible,
                "allowed_roles": sorted(ROLES), "allowed_modalities": sorted(MODALITIES)}

    def list_images(self, user_id, session_id, target_id):
        with self.store._case_guard(user_id, session_id):
            _, item, _, collection = self._read(user_id, session_id, target_id, metadata_only=True)
            return self._public(item, collection)

    def adopt_saved_reference(self, user_id, session_id, target_id):
        """Materialize the already-saved single-image workspace without replanning.

        Only persisted server numerical state is admitted here. A browser
        cannot nominate a legacy source. The original immutable state/version
        remains retained; clinical masks, plan, report and appearance are not
        cleared merely because their image acquires its stable collection ID.
        """
        with self.store._case_guard(user_id, session_id):
            catalog, item, state, collection = self._read(user_id, session_id, target_id)
            if collection["images"]:
                return self._public(item, collection)
            encoded = (state.get("agent") or {}).get("planning_results") or {}
            from web.workspace_store import _decode_artifacts
            root = self.store.workspace_root(user_id, session_id)
            fields = {key: encoded.get(key) for key in ("ct_data", "ct_spacing", "ct_origin", "ct_direction", "ct_path")}
            values = _decode_artifacts(fields, root)
            if values.get("ct_data") is None:
                # Old durable snapshots intentionally omitted transient CT pixels.
                # Recover the owned saved source, not a mask, blank placeholder,
                # browser-nominated file, or another timepoint's CT.
                old_path = values.get("ct_path")
                if not old_path:
                    return self._public(item, collection)
                source = Path(old_path)
                if not source.is_absolute():
                    source = root / source
                for part in (source, *source.parents):
                    if part == root:
                        break
                    if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                        raise TimepointIntegrityError("Saved CT sources cannot traverse filesystem links")
                source = source.resolve()
                if root.resolve() not in source.parents or not source.exists():
                    raise TimepointIntegrityError("The saved CT source is missing or outside its owning workspace")
                image = self._saved_source_image(source, encoded, values)
                array = sitk.GetArrayFromImage(image)
            else:
                array = np.asarray(values["ct_data"])
                image = sitk.GetImageFromArray(array)
                image.SetSpacing(tuple(values["ct_spacing"]))
                image.SetOrigin(tuple(values["ct_origin"]))
                image.SetDirection(tuple(values["ct_direction"]))
            if array.ndim != 3 or not np.isfinite(array).all():
                raise TimepointIntegrityError("The saved image pixels cannot be migrated safely")
            source_geometry = geometry_metadata(image)
            old_path = str(values.get("ct_path") or "")
            leaf = Path(old_path).name or "Restored image.nii.gz"
            image_id = uuid.uuid5(uuid.NAMESPACE_URL,
                f"brachybot:saved-image:{session_id}:{target_id}:{hashlib.sha256(array.tobytes()).hexdigest()}").hex
            with tempfile.TemporaryDirectory(prefix="saved-image-", dir=self.store.staging_dir) as temporary:
                generated = Path(temporary) / "source.nii.gz"
                sitk.WriteImage(image, str(generated), True)
                with generated.open("rb") as stream:
                    source = self.store.write_upload(user_id, session_id,
                        f"timepoints/{target_id}/images/{image_id}/source.nii.gz", stream,
                        expected_bytes=generated.stat().st_size)
            saved_ui = copy.deepcopy(state.get("ui") or {})
            result = self._register_decoded(user_id, session_id, target_id, catalog, item, state, source,
                image, source_geometry, image_id, leaf, title(leaf),
                str(encoded.get("image_modality") or "CT").upper(),
                "intraop" if item["stage"] == "intraoperative" else "preop", None, None,
                select_first_reference=True, preserve_saved_reference=True, preserved_ui=saved_ui)
            return result

    @staticmethod
    def _saved_source_image(source, encoded, values):
        """Decode an owned legacy acquisition on its saved clinical grid."""
        from utils.image_limits import image_header, check_voxel_count
        if source.is_dir():
            series = list(sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(source)) or [])
            selected = encoded.get("dicom_series_uid") or encoded.get("series_instance_uid")
            if selected is None and len(series) == 1:
                selected = series[0]
            if selected not in series:
                raise TimepointIntegrityError("The saved DICOM acquisition does not identify one unique series")
            files = [Path(p) for p in sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(source), selected)]
            if not files or len(files) > 4096 or sum(p.stat().st_size for p in files) > MAX_UPLOAD_BYTES:
                raise TimepointIntegrityError("The saved DICOM acquisition exceeds its size limit")
            for path in files:
                if path.is_symlink() or source not in path.resolve().parents:
                    raise TimepointIntegrityError("Saved DICOM slices must be regular owned files")
            first = image_header(files[0])
            check_voxel_count(first.GetSize(), components=first.GetNumberOfComponents(), series_length=len(files))
            reader = sitk.ImageSeriesReader()
            reader.SetFileNames([str(p) for p in files])
        else:
            reader = image_header(source)
        image = reader.Execute()
        if image.GetDimension() == 4:
            frame = int(encoded.get("image_volume_index") or 0)
            matrix = np.asarray(image.GetDirection()).reshape(4, 4)
            if not 0 <= frame < image.GetSize()[3] or not (
                    np.allclose(matrix[:3, 3], 0) and np.allclose(matrix[3, :3], 0)):
                raise TimepointIntegrityError("The saved temporal frame cannot be recovered safely")
            image = sitk.Extract(image, list(image.GetSize()[:3]) + [0], [0, 0, 0, frame])
        if image.GetDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1:
            raise TimepointIntegrityError("The saved CT source is not a scalar three-dimensional acquisition")
        # Legacy loaders used both native and LPI grids. Match the persisted
        # mask/plan grid; never silently reorient a CT away from those artifacts.
        candidates = (image, sitk.DICOMOrient(image, "LPI"))
        for candidate in candidates:
            if all(values.get(key) is None or np.allclose(values[key], actual, atol=1e-5, rtol=0)
                   for key, actual in (("ct_spacing", candidate.GetSpacing()),
                                       ("ct_origin", candidate.GetOrigin()),
                                       ("ct_direction", candidate.GetDirection()))):
                return candidate
        raise TimepointIntegrityError("The saved CT source geometry does not match its clinical snapshot")

    def _publish(self, user_id, session_id, catalog, item, state, *, action, image_id, clinical_change):
        from web.timepoint_context import capture_context
        context = capture_context(user_id, session_id, catalog, item["id"],
                                  self.store.get_session(user_id, session_id).revision)
        collection = state["image_collection"]
        collection["collection_revision"] += 1
        for image in collection["images"].values():
            image["show"] = image["id"] == collection["display_image_id"]
        collection["journal"].append({"id": uuid.uuid4().hex, "action": action, "image_id": image_id,
            "session_id": session_id, "timepoint_id": item["id"], "actor_id": user_id,
            "collection_revision": collection["collection_revision"], "created_at": time.time(),
            "display_image_id": collection["display_image_id"],
            "planning_reference_image_id": collection["planning_reference_image_id"]})
        validate_collection(collection, session_id, item["id"])
        self.store._publish_timepoint_state(user_id, session_id, catalog, item, state,
            clinical_change=clinical_change, execution_context=context)
        return self.list_images(user_id, session_id, item["id"])

    def _owned_file(self, user_id, session_id, image, *, original=False, verify=True):
        root = self.store.workspace_root(user_id, session_id)
        relative = image["source_path" if original else "volume_path"]
        candidate = root / relative
        for part in (candidate, *candidate.parents):
            if part == root:
                break
            if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                raise TimepointIntegrityError("Owned images cannot traverse filesystem links")
        path = _safe_workspace_child(root, relative)
        if not path.is_file():
            raise TimepointIntegrityError("An owned image source is missing")
        if verify and file_sha256(path) != image["source_sha256" if original else "volume_sha256"]:
            raise TimepointIntegrityError("The owned image content no longer matches its receipt")
        return path

    def source_file(self, user_id, session_id, target_id, image_id, *, original=False):
        with self.store._case_guard(user_id, session_id):
            _, _, _, collection = self._read(user_id, session_id, target_id, metadata_only=True)
            image = collection["images"].get(timepoint_id(image_id))
            if not image or image["status"] != "active":
                raise TimepointNotFound("The requested image is unavailable")
            return self._owned_file(user_id, session_id, image, original=original), copy.deepcopy(image)

    @staticmethod
    def _uploaded_image(path, *, modality, frame_index):
        # Embedded MetaImage/NRRD only: a header cannot ask the decoder to read
        # a different owned file or any absolute server path.
        if path.suffix.lower() in {".mha", ".nrrd"}:
            with path.open("rb") as stream:
                header = stream.read(65536).decode("utf-8", errors="replace")
            if path.suffix.lower() == ".mha":
                match = re.search(r"(?im)^\s*ElementDataFile\s*=\s*(.+)$", header)
                if not match or match.group(1).strip().upper() != "LOCAL":
                    raise TimepointError("Upload a self-contained image, not a detached data header")
            elif re.search(r"(?im)^\s*data\s+file\s*:", header):
                raise TimepointError("Upload a self-contained image, not a detached data header")
        from utils.image_limits import image_header
        try:
            reader = image_header(path)
            if reader.GetNumberOfComponents() != 1 or reader.GetDimension() not in {3, 4}:
                raise TimepointError("Upload a scalar 3-D volume or explicitly select a 4-D frame")
            if reader.HasMetaDataKey("0008|0060"):
                actual = reader.GetMetaData("0008|0060").strip().upper()
                if actual != modality and not (actual == "CT" and modality == "CBCT"):
                    raise TimepointError("Declared modality differs from the source acquisition")
            dimension = reader.GetDimension()
            if dimension == 4:
                if type(frame_index) is not int or not 0 <= frame_index < reader.GetSize()[3]:
                    raise TimepointError("A 4-D upload requires an explicit valid frame_index")
                matrix = np.asarray(reader.GetDirection()).reshape(4, 4)
                if not (np.allclose(matrix[:3, 3], 0) and np.allclose(matrix[3, :3], 0)):
                    raise TimepointError("A coupled space/time geometry cannot be reduced to one planning frame")
            elif frame_index is not None:
                raise TimepointError("A 3-D upload does not have a selectable fourth dimension")
            source_geometry = geometry_metadata(reader)
            image = reader.Execute()
            if dimension == 4:
                image = sitk.Extract(image, list(image.GetSize()[:3]) + [0], [0, 0, 0, frame_index])
            image = sitk.DICOMOrient(image, "LPI")
            geometry = geometry_metadata(image)
            array = sitk.GetArrayViewFromImage(image)
            if not np.isfinite(array).all():
                raise TimepointError("Image pixels contain nonfinite values")
            return image, geometry, source_geometry, hashlib.sha256(array.tobytes()).hexdigest()
        except RuntimeError as exc:
            raise TimepointError("The uploaded source is not a readable medical volume") from exc

    def register_upload(self, user_id, session_id, target_id, stream, filename, *, modality,
                        expected_collection_revision, frame_index=None, name=None, role="unclassified",
                        editor_token=None, expected_bytes=0, select_first_reference=False):
        if not isinstance(filename, str) or len(filename) > 255 or any(ord(c) < 32 for c in filename):
            raise TimepointError("A printable source filename is required")
        leaf = filename.replace("\\", "/").rsplit("/", 1)[-1]
        suffix = next((ext for ext in SOURCE_EXTENSIONS if leaf.lower().endswith(ext)), None)
        if suffix is None:
            raise TimepointError("Upload a self-contained NIfTI, MetaImage, NRRD or DICOM volume")
        name = title(leaf if name is None else name)
        if modality not in MODALITIES or role not in ROLES:
            raise TimepointError("Select an explicit supported modality and image role")
        revision(expected_collection_revision)
        with self.store._case_guard(user_id, session_id):
            catalog, item, state, collection = self._read(user_id, session_id, target_id)
            self._editable(user_id, session_id, item, editor_token)
            if collection["collection_revision"] != expected_collection_revision:
                raise TimepointConflict("The image collection changed; reload before uploading")
            if len(collection["images"]) >= MAX_IMAGES:
                raise TimepointError("The image collection has reached its retained image limit")
            image_id = uuid.uuid4().hex
            relative = f"timepoints/{target_id}/images/{image_id}/source{suffix}"
            source = self.store.write_upload(user_id, session_id, relative,
                _LimitedStream(stream, MAX_UPLOAD_BYTES), expected_bytes=expected_bytes)
            # A failed decode/CAS may leave unreferenced owned files. They are
            # charged to quota and never registered or accepted as current.
            image, geometry, source_geometry, voxel_hash = self._uploaded_image(
                source, modality=modality, frame_index=frame_index)
            return self._register_decoded(user_id, session_id, target_id, catalog, item, state, source,
                image, source_geometry, image_id, leaf, name, modality, role, frame_index, editor_token,
                select_first_reference=select_first_reference)

    def _register_decoded(self, user_id, session_id, target_id, catalog, item, state, source,
                          image, source_geometry, image_id, leaf, name, modality, role, frame_index,
                          editor_token, *, select_first_reference=False, acquisition_files=None,
                          ingest_source_path=None, preserve_saved_reference=False, preserved_ui=None):
            collection = state["image_collection"]
            first_image = not collection["images"]
            with tempfile.TemporaryDirectory(prefix="image-frame-", dir=self.store.staging_dir) as temporary:
                generated = Path(temporary) / "volume.nii.gz"
                sitk.WriteImage(image, str(generated), True)
                with generated.open("rb") as handle:
                    volume = self.store.write_upload(user_id, session_id,
                        f"timepoints/{target_id}/images/{image_id}/volume.nii.gz", handle,
                        expected_bytes=generated.stat().st_size)
            # NIfTI stores its physical header at finite precision. Receipts
            # describe the actual saved volume, including that serialization.
            from utils.image_limits import read_image
            saved_volume = read_image(volume)
            geometry = geometry_metadata(saved_volume)
            voxel_hash = hashlib.sha256(sitk.GetArrayViewFromImage(saved_volume).tobytes()).hexdigest()
            root = self.store.workspace_root(user_id, session_id)
            collection["images"][image_id] = {"id": image_id, "session_id": session_id,
                "timepoint_id": target_id, "name": name, "original_filename": leaf,
                "modality": modality, "role": role, "status": "active", "show": True,
                "source_path": source.relative_to(root).as_posix(), "source_sha256": file_sha256(source),
                "volume_path": volume.relative_to(root).as_posix(), "volume_sha256": file_sha256(volume),
                "source_bytes": source.stat().st_size, "volume_bytes": volume.stat().st_size,
                "voxel_sha256": voxel_hash, "geometry": geometry, "source_geometry": source_geometry,
                "source_dimension": source_geometry["dimension"], "frame_index": frame_index,
                "frame_count": source_geometry["size"][3] if source_geometry["dimension"] == 4 else 1,
                "wwl": {"width": 400.0, "level": 40.0} if modality in {"CT", "CBCT"} else None,
                "opacity": 1.0, "color": "#888888", "move": {"translation_mm": [0.0, 0.0, 0.0]},
                "created_at": time.time(), "updated_at": time.time(), "deleted_at": None,
                "acquisition_files": acquisition_files or [], "ingest_source_path": ingest_source_path}
            collection["order"].append(image_id)
            self._set_display(state, image_id)
            if preserve_saved_reference:
                if not first_image:
                    raise TimepointConflict("Saved-reference migration can only initialize an empty collection")
                collection["planning_reference_image_id"] = image_id
                collection["reference_revision"] += 1
                state["ui"] = preserved_ui or {}
                original_results = state.setdefault("agent", {}).setdefault("planning_results", {})
                original_results.update(ct_path=str(volume), ct_image_path=str(volume),
                    planning_reference_image_id=image_id,
                    planning_reference_receipt=reference_receipt(collection, collection["images"][image_id]))
                receipt = original_results["planning_reference_receipt"]
                original_results["clinical_resource_sources"] = {
                    key: copy.deepcopy(receipt) for key in original_results if key != "clinical_resource_sources"}
                state.setdefault("migration", {})["saved_reference_image_id"] = image_id
                clinical = False
            else:
                clinical = self._set_reference(user_id, session_id, state, image_id) if select_first_reference and first_image else False
                self._editable(user_id, session_id, item, editor_token)
            result = self._publish(user_id, session_id, catalog, item, state,
                action="image.uploaded", image_id=image_id, clinical_change=clinical)
            result["created_image_id"] = image_id
            return result

    def register_owned_source(self, user_id, session_id, target_id, owned_path, *, modality,
                              expected_collection_revision, frame_index=None, name=None, role="unclassified",
                              editor_token=None, select_first_reference=False, series_id=None):
        """SERVER-ONLY legacy upload adapter; public routes never accept paths.

        The caller has already uploaded into inputs/timepoints/<target>. Reusing
        a registered path displays its existing UUID. A DICOM directory requires
        an explicit series ID when it contains multiple acquisitions; every
        selected source file is retained in an owned ZIP acquisition artifact.
        """
        with self.store._case_guard(user_id, session_id):
            catalog, item, state, collection = self._read(user_id, session_id, target_id)
            self._editable(user_id, session_id, item, editor_token)
            if revision(expected_collection_revision) != collection["collection_revision"]:
                raise TimepointConflict("The image collection changed; reload before loading an upload")
            root = self.store.workspace_root(user_id, session_id)
            owned_root = root / "inputs" / "timepoints" / target_id
            candidate = Path(owned_path)
            if not candidate.is_absolute():
                candidate = root / candidate
            for part in (candidate, *candidate.parents):
                if part == root:
                    break
                if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                    raise TimepointError("Uploaded image sources cannot traverse filesystem links")
            candidate = candidate.resolve()
            if owned_root.resolve() not in candidate.parents or not candidate.exists():
                raise TimepointError("Source must be a real upload owned by this Session and target")
            relative = candidate.relative_to(root).as_posix()
            for image in collection["images"].values():
                if relative in {image["source_path"], image["volume_path"], image.get("ingest_source_path")}:
                    if image["status"] != "active":
                        raise TimepointNotFound("Restore the removed image before displaying it")
                    self._owned_file(user_id, session_id, image)
                    self._owned_file(user_id, session_id, image, original=True)
                    if collection['display_image_id'] == image['id']:
                        # Loading the currently selected image is a projection,
                        # not a new selection. Repeated Viewer restores must
                        # not make a pending user control's collection CAS stale.
                        result = self.list_images(user_id,session_id,target_id)
                    else:
                        self._set_display(state, image["id"])
                        result = self._publish(user_id, session_id, catalog, item, state,
                            action="image.displayed", image_id=image["id"], clinical_change=False)
                    result["registered_image_id"] = image["id"]
                    return result
            if modality not in MODALITIES or role not in ROLES or len(collection["images"]) >= MAX_IMAGES:
                raise TimepointError("Select a supported modality/role within the retained image limit")
            if candidate.is_file():
                with candidate.open("rb") as stream:
                    image_id = uuid.uuid4().hex
                    suffix = next((ext for ext in SOURCE_EXTENSIONS if candidate.name.lower().endswith(ext)), None)
                    if suffix is None:
                        raise TimepointError("The uploaded image format is unsupported")
                    source = self.store.write_upload(user_id, session_id,
                        f"timepoints/{target_id}/images/{image_id}/source{suffix}",
                        _LimitedStream(stream, MAX_UPLOAD_BYTES), expected_bytes=candidate.stat().st_size)
                    image, geometry, source_geometry, voxel_hash = self._uploaded_image(
                        source, modality=modality, frame_index=frame_index)
                return self._register_decoded(user_id, session_id, target_id, catalog, item, state, source,
                    image, source_geometry, image_id, candidate.name, title(name or candidate.name), modality, role,
                    frame_index, editor_token, select_first_reference=select_first_reference, ingest_source_path=relative)
            if frame_index is not None:
                raise TimepointError("DICOM series uploads do not accept an implicit temporal frame")
            series = list(sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(candidate)) or [])
            if not series or (series_id is None and len(series) != 1) or (series_id is not None and series_id not in series):
                raise TimepointError("Select one explicit DICOM series from the owned upload directory")
            selected = series_id or series[0]
            files = [Path(p) for p in sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(candidate), selected)]
            if not files or len(files) > 4096 or sum(p.stat().st_size for p in files) > MAX_UPLOAD_BYTES:
                raise TimepointError("The DICOM acquisition exceeds its file/byte limit")
            for source in files:
                if (source.is_symlink() or source.stat().st_nlink != 1
                        or candidate not in source.resolve().parents):
                    raise TimepointError("DICOM slices must be regular owned uploaded files")
            from utils.image_limits import image_header, check_voxel_count
            first = image_header(files[0])
            actual = first.GetMetaData("0008|0060").strip().upper() if first.HasMetaDataKey("0008|0060") else ""
            if actual != modality and not (actual == "CT" and modality == "CBCT"):
                raise TimepointError("Declared modality differs from the DICOM acquisition")
            check_voxel_count(first.GetSize(), components=first.GetNumberOfComponents(), series_length=len(files))
            reader = sitk.ImageSeriesReader()
            reader.SetFileNames([str(p) for p in files])
            image = reader.Execute()
            if image.GetDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1:
                raise TimepointError("Select a scalar three-dimensional DICOM acquisition")
            source_geometry = geometry_metadata(image)
            image = sitk.DICOMOrient(image, "LPI")
            if not np.isfinite(sitk.GetArrayViewFromImage(image)).all():
                raise TimepointError("Image pixels contain nonfinite values")
            image_id = uuid.uuid4().hex
            acquisition_files = []
            with tempfile.TemporaryDirectory(prefix="dicom-acquisition-", dir=self.store.staging_dir) as temporary:
                archive_path = Path(temporary) / "source_series.zip"
                with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
                    for index, source in enumerate(files):
                        leaf = f"slice_{index:05d}.dcm"
                        archive.write(source, leaf)
                        acquisition_files.append({"path": leaf, "bytes": source.stat().st_size,
                                                  "sha256": file_sha256(source)})
                with archive_path.open("rb") as stream:
                    source = self.store.write_upload(user_id, session_id,
                        f"timepoints/{target_id}/images/{image_id}/source_series.zip", stream,
                        expected_bytes=archive_path.stat().st_size)
            return self._register_decoded(user_id, session_id, target_id, catalog, item, state, source,
                image, source_geometry, image_id, candidate.name, title(name or candidate.name), modality, role,
                None, editor_token, select_first_reference=select_first_reference,
                acquisition_files=acquisition_files, ingest_source_path=relative)

    def display_image_bridge(self, user_id, session_id, target_id, *, load_pixels=True):
        with self.store._case_guard(user_id, session_id):
            _, item, _, collection = self._read(user_id, session_id, target_id, metadata_only=True)
            image_id = collection["display_image_id"]
            result = self._public(item, collection)
            result["available"] = image_id is not None
            if image_id is None:
                return result
            image = collection["images"][image_id]
            path = self._owned_file(user_id, session_id, image)
            result.update(ct_path=str(path), ct_image_path=str(path), ct_metadata=copy.deepcopy(image["geometry"]),
                          display_image_receipt=reference_receipt(collection, image), image=copy.deepcopy(image))
            if load_pixels:
                from utils.image_limits import read_image
                volume = read_image(path)
                result.update(ct_image=volume, ct_image_raw=volume, ct_data=sitk.GetArrayFromImage(volume),
                    ct_spacing=list(volume.GetSpacing()), ct_origin=list(volume.GetOrigin()),
                    ct_direction=list(volume.GetDirection()), ct_shape=list(volume.GetSize()[::-1]),
                    ct_window_center=(image.get("wwl") or {}).get("level", 40),
                    ct_window_width=(image.get("wwl") or {}).get("width", 400))
            return result

    @staticmethod
    def _set_display(state, image_id):
        collection = state["image_collection"]
        if collection["display_image_id"] != image_id:
            # Viewer scene state is source-associated. Do not allow a later
            # restore/save to mount anatomy or implants from the prior image.
            from web.timepoints import compact_restore_presentation
            bridge = (state.get('ui') or {}).get('bridge')
            appearance = compact_restore_presentation(state.get('ui'))
            appearance.pop('bridge',None)
            state.setdefault("image_presentations", {})[str(collection["display_image_id"])] = appearance
            state["ui"] = copy.deepcopy((state.get("image_presentations") or {}).get(str(image_id)) or {})
            if bridge is not None:
                state['ui']['bridge'] = bridge
        collection["display_image_id"] = image_id

    def _set_reference(self, user_id, session_id, state, image_id):
        collection = state["image_collection"]
        previous = collection["planning_reference_image_id"]
        if previous == image_id:
            return False
        resource_sets = state.setdefault("image_resources", {})
        resource_sets[previous or "unassigned"] = {
            "reference_image_id": previous, "agent": copy.deepcopy(state.get("agent") or {}),
            "report": copy.deepcopy(state.get("report") or {}), "operation": copy.deepcopy(state.get("operation") or {}),
            "source_receipt": reference_receipt(collection, collection["images"][previous]) if previous else None}
        # Saved resource sets remain archived; switching never republishes old
        # scientific results as current merely because the user returns to A.
        previous_agent = state.get("agent") or {}
        state["agent"] = {key: copy.deepcopy(previous_agent[key]) for key in
            ("config", "patient_data", "conversation", "context_summary", "compaction_count", "context_accounting", "user_lang")
            if key in previous_agent}
        state["agent"].update(planning_results={}, current_phase="idle", tool_results=[], planning_versions={})
        state["report"] = {"status": "stale", "reason": "planning_reference_changed"}
        state["operation"] = {"state": "idle", "checkpoint": None}
        collection["planning_reference_image_id"] = image_id
        collection["reference_revision"] += 1
        receipt = None
        if image_id:
            image = collection["images"][image_id]
            path = self._owned_file(user_id, session_id, image)
            self._owned_file(user_id, session_id, image, original=True)
            receipt = reference_receipt(collection, image)
            state["agent"]["planning_results"] = {
                "ct_image_path": str(path), "ct_path": str(path),
                "ct_metadata": copy.deepcopy(image["geometry"]),
                "planning_reference_image_id": image_id, "planning_reference_receipt": receipt,
                "clinical_resource_sources": {}}
            reusable = resource_sets.get(image_id)
            old_receipt = (reusable or {}).get("source_receipt") or {}
            if reusable and all(old_receipt.get(key) == receipt.get(key) for key in
                    ("image_id", "source_sha256", "volume_sha256", "voxel_sha256", "geometry_signature", "frame_index", "modality")):
                # An unchanged owned acquisition can recover its own structures
                # and saved plan. This does not copy any B-image results to A,
                # nor certify previously stale artifacts as current.
                recovered = copy.deepcopy(reusable["agent"])
                recovered.setdefault("planning_results", {}).update(ct_path=str(path), ct_image_path=str(path),
                    planning_reference_image_id=image_id, planning_reference_receipt=receipt)
                state["agent"] = recovered
                state["report"] = copy.deepcopy(reusable.get("report") or {})
                state["operation"] = {"state": "idle", "checkpoint": None}
                recovered["planning_results"]["clinical_resource_sources"] = {
                    key: copy.deepcopy(receipt) for key in recovered["planning_results"] if key != "clinical_resource_sources"}
                state["scientific_dependencies"] = {"reference_image_id": image_id, "receipt": receipt,
                    "invalidated": [], "reused": list(recovered["planning_results"]),
                    "reason": "unchanged_owned_reference_recovered"}
        # All clinical Viewer data must be reloaded against the new receipt.
        state["ui"] = {}
        if (state.get("scientific_dependencies") or {}).get("reason") != "unchanged_owned_reference_recovered" or (
                state.get("scientific_dependencies") or {}).get("reference_image_id") != image_id:
            state["scientific_dependencies"] = {"reference_image_id": image_id, "receipt": receipt,
                "invalidated": list(INVALIDATED_RESOURCES), "ready": [], "reason": "planning_reference_changed"}
        state.setdefault("image_invalidation_journal", []).append({"id": uuid.uuid4().hex,
            "session_id": session_id, "timepoint_id": collection["timepoint_id"], "previous_image_id": previous,
            "reference_image_id": image_id, "reference_revision": collection["reference_revision"],
            "invalidated": list(INVALIDATED_RESOURCES), "created_at": time.time()})
        return True

    def update_image(self, user_id, session_id, target_id, image_id, patch, *,
                     expected_collection_revision, editor_token=None):
        allowed = {"name", "title", "role", "display", "planning_reference", "show", "wwl",
                   "window_width", "window_level", "opacity", "color", "move", "restore"}
        if not isinstance(patch, dict) or not patch or set(patch) - allowed:
            raise TimepointError("Image patches can update only presentation, role or explicit reference selection")
        with self.store._case_guard(user_id, session_id):
            catalog, item, state, collection = self._read(user_id, session_id, target_id)
            self._editable(user_id, session_id, item, editor_token)
            if revision(expected_collection_revision) != collection["collection_revision"]:
                raise TimepointConflict("The image collection changed; reload before editing")
            image = collection["images"].get(timepoint_id(image_id))
            if image is None or (image["status"] != "active" and patch.get("restore") is not True):
                raise TimepointNotFound("The requested image is unavailable")
            for key in ("display", "planning_reference", "show", "restore"):
                if key in patch and type(patch[key]) is not bool:
                    raise TimepointError("Image selection flags must be explicit booleans")
            if "show" in patch and "display" in patch and patch["show"] != patch["display"]:
                raise TimepointError("show and display cannot request different backgrounds")
            if "name" in patch and "title" in patch and patch["name"] != patch["title"]:
                raise TimepointError("Image name and title must agree")
            if "name" in patch or "title" in patch:
                image["name"] = title(patch.get("name", patch.get("title")))
            if "role" in patch:
                if patch["role"] not in ROLES:
                    raise TimepointError("Invalid image role")
                image["role"] = patch["role"]
            if "restore" in patch:
                if not patch["restore"]:
                    raise TimepointError("Use DELETE to remove an image")
                self._owned_file(user_id, session_id, image)
                self._owned_file(user_id, session_id, image, original=True)
                image.update(status="active", deleted_at=None)
            if "opacity" in patch:
                if type(patch["opacity"]) not in {int, float} or not 0 <= patch["opacity"] <= 1:
                    raise TimepointError("Image opacity must be a finite number from 0 to 1")
                image["opacity"] = float(patch["opacity"])
            if 'color' in patch:
                if not isinstance(patch['color'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',patch['color']):
                    raise TimepointError('Image marker color must be a six-digit hexadecimal color')
                image['color'] = patch['color'].lower()
            if any(k in patch for k in ("wwl", "window_width", "window_level")):
                wwl = copy.deepcopy(image.get("wwl") or {"width": 400.0, "level": 40.0})
                incoming = patch.get("wwl", {})
                if not isinstance(incoming, dict) or set(incoming) - {"width", "level"}:
                    raise TimepointError("Window/level must contain width and/or level")
                wwl.update(incoming)
                for key, alias in (("width", "window_width"), ("level", "window_level")):
                    if alias in patch:
                        wwl[key] = patch[alias]
                if (any(type(v) not in {float, int} or not math.isfinite(v) for v in wwl.values()) or wwl["width"] <= 0):
                    raise TimepointError("Window width must be positive; level must be finite")
                image["wwl"] = wwl
            if "move" in patch:
                move = patch["move"]
                if (not isinstance(move, dict) or set(move) != {"translation_mm"}
                        or not isinstance(move["translation_mm"], list) or len(move["translation_mm"]) != 3
                        or any(type(v) not in {float, int} or not math.isfinite(v) for v in move["translation_mm"])):
                    raise TimepointError("Image move must contain three finite presentation translation_mm values")
                image["move"] = copy.deepcopy(move)
            display = patch.get("display", patch.get("show"))
            if display is True:
                self._set_display(state, image_id)
            elif display is False and collection["display_image_id"] == image_id:
                self._set_display(state, None)
            clinical = False
            if patch.get("planning_reference") is True:
                clinical = self._set_reference(user_id, session_id, state, image_id)
            elif patch.get("planning_reference") is False and collection["planning_reference_image_id"] == image_id:
                clinical = self._set_reference(user_id, session_id, state, None)
            image["updated_at"] = time.time()
            self._editable(user_id, session_id, item, editor_token)
            return self._publish(user_id, session_id, catalog, item, state,
                action="image.updated", image_id=image_id, clinical_change=clinical)

    def delete_image(self, user_id, session_id, target_id, image_id, *, expected_collection_revision, editor_token=None):
        with self.store._case_guard(user_id, session_id):
            catalog, item, state, collection = self._read(user_id, session_id, target_id)
            self._editable(user_id, session_id, item, editor_token)
            if revision(expected_collection_revision) != collection["collection_revision"]:
                raise TimepointConflict("The image collection changed; reload before removing an image")
            image = collection["images"].get(timepoint_id(image_id))
            if image is None or image["status"] != "active":
                raise TimepointNotFound("The requested image is unavailable")
            clinical = self._set_reference(user_id, session_id, state, None) if collection["planning_reference_image_id"] == image_id else False
            if collection["display_image_id"] == image_id:
                self._set_display(state, None)
            image.update(status="trashed", show=False, deleted_at=time.time(), updated_at=time.time())
            return self._publish(user_id, session_id, catalog, item, state,
                action="image.deleted", image_id=image_id, clinical_change=clinical)

    def planning_reference_bridge(self, user_id, session_id, target_id, *, load_pixels=True, require_ct=False):
        """Main's hydration contract: selected owned volume plus receipt/aliases.

        A non-CT reference may be displayed/annotated, but CT inference must ask
        require_ct=True. The result uses the planning source, not display source.
        Call under the captured target guard and check its clinical revision at
        publication; never inject this into the shared Session/root Agent.
        """
        with self.store._case_guard(user_id, session_id):
            _, item, _, collection = self._read(user_id, session_id, target_id, metadata_only=True)
            image_id = collection["planning_reference_image_id"]
            if image_id is None:
                raise TimepointConflict("Select an owned planning reference image")
            image = collection["images"][image_id]
            if require_ct and image["modality"] not in {"CT", "CBCT"}:
                raise TimepointError("CT inference requires an explicitly selected CT or CBCT reference")
            path = self._owned_file(user_id, session_id, image)
            self._owned_file(user_id, session_id, image, original=True)
            result = {"ct_image_path": str(path), "ct_path": str(path),
                "ct_metadata": copy.deepcopy(image["geometry"]), "planning_reference_image_id": image_id,
                "planning_reference_receipt": reference_receipt(collection, image),
                "timepoint_clinical_revision": item.get("clinical_revision", 0),
                "display_image_id": collection["display_image_id"]}
            if load_pixels:
                from utils.image_limits import read_image
                volume = read_image(path)
                actual = sitk.GetArrayFromImage(volume)
                if (geometry_metadata(volume)["geometry_signature"] != image["geometry"]["geometry_signature"]
                        or hashlib.sha256(actual.tobytes()).hexdigest() != image["voxel_sha256"]):
                    raise TimepointIntegrityError("The selected volume no longer matches its physical/content receipt")
                result.update(ct_image=volume, ct_data=actual)
            return result
