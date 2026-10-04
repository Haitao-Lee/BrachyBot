"""Actual bytes/values, tri-state quality, and explicit external-review contracts."""
from __future__ import annotations
import json
import math
import shutil
import zipfile
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from .core import Blocked, child, digest, finite, load_json, sha256
from .preflight import equal_grid


def check(status, reason=None, **evidence):
    return {"status": status, "reason": reason, **evidence}


def geometry(rows, keys):
    if not rows:
        return check("FAIL", "EMPTY_GEOMETRY")
    ids = [r.get("id") for r in rows]
    if any(not v for v in ids) or len(ids) != len(set(ids)):
        return check("FAIL", "MISSING_OR_DUPLICATE_IDS")
    for row in rows:
        for key in keys:
            value = row.get(key)
            if not isinstance(value, (tuple, list)) or len(value) != 3 or not all(finite(x) for x in value):
                return check("FAIL", "INVALID_COORDINATES", object_id=row.get("id"), field=key)
    return check("PASS", count=len(rows), coordinate_system="LPS_mm")


def dose_field(path, ct_path):
    dose = sitk.ReadImage(str(path))
    ct = sitk.ReadImage(str(ct_path))
    a = sitk.GetArrayFromImage(dose)
    if not equal_grid(dose, ct):
        return check("UNKNOWN", "DOSE_GRID_TRANSFORM_REQUIRED")
    if a.size == 0 or not np.isfinite(a).all() or np.min(a) < 0 or np.max(a) <= 0:
        return check("FAIL", "INVALID_DOSE_FIELD")
    return check("PASS", minimum=float(a.min()), maximum=float(a.max()), evidence_level="external_artifact_verification")


def metrics_from_field(path, target_path, prescription_gy):
    """Independent arithmetic on a saved CNN field, not independent physics."""
    d, target = sitk.ReadImage(str(path)), sitk.ReadImage(str(target_path))
    if not equal_grid(d, target):
        return check("UNKNOWN", "DOSE_TARGET_GRID_TRANSFORM_REQUIRED")
    values = sitk.GetArrayFromImage(d)[sitk.GetArrayFromImage(target) > 0]
    if not len(values) or not np.isfinite(values).all() or np.min(values) < 0:
        return check("FAIL", "INVALID_TARGET_DOSE")
    m = {f"V{n}_percent": float(np.mean(values >= prescription_gy * n / 100) * 100) for n in (100, 150, 200)}
    m.update({f"D{n}_gy": float(np.percentile(values, 100 - n)) for n in (90, 95, 98, 2)})
    m.update(Dmean_gy=float(np.mean(values)), Dmax_gy=float(np.max(values)))
    return check("PASS", metrics=m, evidence_level="external_artifact_verification",
                 physical_validity="NOT_ESTABLISHED", quantile_method="numpy_linear")


def pdf(path, minimum_pages=1):
    try:
        from pypdf import PdfReader
    except ImportError:
        return check("UNKNOWN", "PYPDF_MISSING")
    try:
        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted or len(reader.pages) < minimum_pages:
            return check("FAIL", "PDF_ENCRYPTED_OR_TOO_SHORT")
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        if not text.strip():
            return check("FAIL", "PDF_TEXT_MISSING")
        images = sum(len(p.images) for p in reader.pages)
        return check("PASS", pages=len(reader.pages), image_count=images,
                     text_sha256=digest(text), visual_readability="REVIEW_REQUIRED")
    except Exception as exc:
        return check("FAIL", "PDF_PARSE_ERROR", detail=str(exc))


def mesh(path):
    try:
        import trimesh
    except ImportError:
        return check("UNKNOWN", "TRIMESH_MISSING")
    try:
        m = trimesh.load_mesh(str(path), process=False)
        if not isinstance(m, trimesh.Trimesh) or len(m.vertices) == 0 or len(m.faces) == 0:
            return check("FAIL", "EMPTY_OR_AMBIGUOUS_MESH")
        if not np.isfinite(m.vertices).all() or not np.isfinite(m.face_normals).all():
            return check("FAIL", "NONFINITE_MESH")
        # STL repeats vertices per triangle. Deduplicate identical vertices only;
        # do not repair holes or invent faces to make a failed guide pass.
        m.merge_vertices()
        if not m.is_watertight or not m.is_winding_consistent or not finite(float(abs(m.volume)), True):
            return check("FAIL", "INVALID_MESH_TOPOLOGY")
        return check("PASS", vertices=len(m.vertices), faces=len(m.faces), volume_mm3=float(abs(m.volume)),
                     bounds_lps_mm=m.bounds.tolist(), units="mm_requires_provenance",
                     channel_wall_skin_acceptance="REVIEW_REQUIRED")
    except Exception as exc:
        return check("FAIL", "MESH_READ_ERROR", detail=str(exc))


def unzip_verified(path, root, maximum_bytes=100 * 1024**3):
    """Reject traversal, symlinks, duplicate paths and decompression bombs."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        names = [x.filename for x in entries]
        if len(names) != len(set(names)) or sum(i.file_size for i in entries) > maximum_bytes:
            raise Blocked("UNSAFE_EXPORT_ARCHIVE")
        for item in entries:
            if item.filename.endswith("/"):
                child(root, item.filename).mkdir(parents=True, exist_ok=True)
                continue
            if item.external_attr >> 16 & 0o170000 == 0o120000:
                raise Blocked("ARCHIVE_SYMLINK")
            target = child(root, item.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(item) as source, target.open("xb") as out:
                shutil.copyfileobj(source, out, length=4 * 1024 * 1024)
            if target.stat().st_size != item.file_size:
                raise Blocked("ARCHIVE_SIZE_MISMATCH")
    manifests = list(root.rglob("session_manifest.json"))
    if len(manifests) != 1:
        raise Blocked("EXPORT_MANIFEST_NOT_UNIQUE")
    return manifests[0], load_json(manifests[0])


def review(review_path, recipe_hash, artifacts, required, rules_hash=None, attempt_id=None):
    """An adjudicated receipt must bind this attempt's actual artifact hashes."""
    if not review_path or not Path(review_path).is_file():
        return check("UNKNOWN", "EXTERNAL_REVIEW_MISSING")
    r = load_json(review_path)
    if r.get("status") != "APPROVED_RESEARCH_REVIEW":
        return check("UNKNOWN", "REVIEW_NOT_APPROVED")
    if r.get("recipe_hash") != recipe_hash or not r.get("reviewer") or not r.get("reviewed_at"):
        return check("FAIL", "REVIEW_PROVENANCE_INVALID")
    if (rules_hash and r.get("rules_hash") != rules_hash) or (attempt_id and r.get("attempt_id") != attempt_id):
        return check("FAIL", "REVIEW_RULES_OR_ATTEMPT_MISMATCH")
    observed_hashes = {a["path"]: a["sha256"] for a in artifacts}
    if not r.get("artifact_hashes") or any(observed_hashes.get(k) != v for k, v in r["artifact_hashes"].items()):
        return check("FAIL", "REVIEW_ARTIFACT_MISMATCH")
    reviewed = set(r["artifact_hashes"])
    essential = [a["path"] for a in artifacts if a["path"] == "report.pdf" or a.get("data_type") == "surgical_guide"
                 or "/report" in a["path"].lower() and a["path"].lower().endswith((".png", ".jpg", ".jpeg"))]
    if "report.pdf" not in essential or not any(a.get("data_type") == "surgical_guide" for a in artifacts) or not set(essential) <= reviewed:
        return check("UNKNOWN", "REVIEW_REQUIRED_ARTIFACT_HASHES_MISSING")
    if any(r.get("checks", {}).get(k) not in {"PASS", "FAIL", "UNKNOWN"} for k in required):
        return check("UNKNOWN", "REVIEW_CHECKS_INCOMPLETE")
    statuses = [r["checks"][k] for k in required]
    return check("FAIL" if "FAIL" in statuses else "UNKNOWN" if "UNKNOWN" in statuses else "PASS", receipt=r)


def archive_manifest(root):
    root = Path(root)
    roles = {}
    for path in root.rglob("session_manifest.json"):
        manifest = load_json(path)
        for entry in manifest.get("files", []):
            resolved = child(path.parent, entry["relative_path"])
            if root.resolve() not in resolved.parents:
                raise Blocked("ARCHIVE_OBJECT_PATH_ESCAPES_ROOT")
            roles[resolved] = entry.get("data_type")
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if any(p.is_symlink() for p in files):
        raise Blocked("ARCHIVE_UNEXPECTED_SYMLINK")
    return [{"path": p.relative_to(root).as_posix(), "sha256": sha256(p), "bytes": p.stat().st_size,
             **({"data_type": roles[p.resolve()]} if p.resolve() in roles else {})}
            for p in files if p.name not in {"artifact_manifest.json", "terminal_result.json"}]


def verify_archive(root, entries):
    for e in entries:
        path = child(root, e["path"])
        if not path.is_file() or path.stat().st_size != e["bytes"] or sha256(path) != e["sha256"]:
            return check("FAIL", "ARCHIVE_HASH_MISMATCH", path=e["path"])
    if not entries:
        return check("FAIL", "EMPTY_ARCHIVE")
    return check("PASS", files=len(entries), bytes=sum(e["bytes"] for e in entries))


def physics_reference(dose_path, reference_path, target_path, p, reference):
    """Validate a separately supplied physics result; never invent a reference engine."""
    required = ("engine", "version", "source_model", "isotope", "strength", "strength_unit",
                "time_assumptions", "reviewer", "approval_reference", "reference_sha256",
                "sut_dose_sha256", "target_sha256", "geometry_path", "geometry_sha256", "dose_unit")
    if any(not reference.get(k) for k in required) or reference["engine"] == p["engine"]["name"]:
        return check("UNKNOWN", "INDEPENDENT_REFERENCE_UNRESOLVED")
    if reference["dose_unit"] != "Gy" or sha256(dose_path) != reference["sut_dose_sha256"] or sha256(target_path) != reference["target_sha256"]:
        return check("FAIL", "REFERENCE_TARGET_DOSE_OR_UNIT_MISMATCH")
    if sha256(reference["geometry_path"]) != reference["geometry_sha256"]:
        return check("FAIL", "REFERENCE_GEOMETRY_CHANGED")
    for k in ("isotope", "strength", "strength_unit", "time_assumptions"):
        if reference[k] != p["source"][k]:
            return check("FAIL", "REFERENCE_SOURCE_RECIPE_MISMATCH", field=k)
    if reference["source_model"] != p["source"]["model"] or sha256(reference_path) != reference["reference_sha256"]:
        return check("FAIL", "REFERENCE_PROVENANCE_MISMATCH")
    a, b, t = (sitk.ReadImage(str(x)) for x in (dose_path, reference_path, target_path))
    if not equal_grid(a, b) or not equal_grid(a, t):
        return check("UNKNOWN", "REFERENCE_GRID_TRANSFORM_REQUIRED")
    x, y, mask = (sitk.GetArrayFromImage(i) for i in (a, b, t))
    if not np.isfinite(x).all() or not np.isfinite(y).all() or min(x.min(), y.min()) < 0 or y.max() <= 0 or not np.isin(mask, [0, 1]).all() or not np.any(mask):
        return check("FAIL", "REFERENCE_VALUES_INVALID")
    errors = np.abs(x - y)[mask > 0]
    return check("PASS", evidence_level="independent_physics_validation",
                 mean_absolute_error_gy=float(errors.mean()), p95_absolute_error_gy=float(np.percentile(errors, 95)),
                 max_absolute_error_gy=float(errors.max()), physical_acceptance="REVIEW_REQUIRED",
                 reference=reference)
