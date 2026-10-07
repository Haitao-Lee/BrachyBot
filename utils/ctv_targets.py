"""Source-aware CTV projection shared by planning, safety and dose evaluation.

Display/source labels are not a universal anatomy namespace. An effective
Structure Set owns a binary union; model outputs retain their original labels
separately. Never infer vascular obstacles from the number 2 alone.
"""
from __future__ import annotations

import numpy as np


def label_array(value, *, shape=None):
    if value is None:
        return None
    if hasattr(value, "GetSize") and hasattr(value, "GetSpacing"):
        import SimpleITK as sitk
        value = sitk.GetArrayFromImage(value)
    array = np.asarray(value)
    if shape is not None and array.shape != tuple(shape):
        if array.ndim == 1 and array.size == int(np.prod(shape)):
            array = array.reshape(shape)
        else:
            raise ValueError("CTV mask does not match the reference image grid")
    if array.ndim != 3 or not np.issubdtype(array.dtype, np.number) and array.dtype != bool:
        raise ValueError("CTV mask must be a numeric 3D label volume")
    if not np.isfinite(array).all() or np.any(array < 0) or np.any(array != np.floor(array)):
        raise ValueError("CTV labels must be finite non-negative integers")
    return array


def canonical_semantics(source=None, semantics=None):
    """Registered source identity wins over historical engine metadata."""
    from tool_factory.CTV_seg.model_registry import route, canonical_ctv_source, target_semantics
    token = str(source or "").strip().lower()
    registered = route(canonical_ctv_source(token)) if token else None
    if registered is not None:
        return registered.target_semantics
    if token == "classified":
        return "classified_union"
    aliases = {"primary_and_nodal_gtv_union": "multi_target_gtv", "lung_tumor_only": "single_target"}
    explicit = aliases.get(str(semantics or ""), str(semantics or ""))
    if explicit in {"single_target", "target_plus_anatomy", "multi_target_gtv", "classified_union", "candidate_mask"}:
        return explicit
    return target_semantics(token) if token else "single_target"


def project_target(value, *, source=None, semantics=None, target_value=1, shape=None):
    array = label_array(value, shape=shape)
    if array is None:
        return None
    policy = canonical_semantics(source, semantics)
    if policy == "target_plus_anatomy":
        mask = array == 1
    elif policy == "multi_target_gtv":
        mask = np.isin(array, (1, 2))
    elif policy == "classified_union" or source in {"manual_label", "uploaded", "manual_upload"}:
        mask = array > 0
    else:
        mask = array == target_value
    # Preserve the zero-copy binary contract for already-normalized arrays.
    if target_value == 1 and array.dtype == np.uint8 and np.array_equal(array, mask):
        return array
    return mask.astype(np.uint8)


def resolve_ctv_target(retrieve, *, shape=None):
    """Prefer the durable effective union; legacy fallback remains source-aware.

    A malformed binary companion is an error, not permission to silently use
    another mask. Replacements must clear/replace this companion atomically.
    """
    if shape is None:
        reference = retrieve("ct_image")
        if reference is not None and hasattr(reference, "GetSize"):
            shape = tuple(reversed(reference.GetSize()))
    binary = retrieve("ctv_binary_array")
    if binary is not None:
        array = label_array(binary, shape=shape)
        if not np.isin(array, (0, 1)).all():
            raise ValueError("ctv_binary_array must contain only background 0 and target 1")
        return array
    source = str(retrieve("ctv_source") or "").strip().lower()
    semantics = canonical_semantics(source, retrieve("target_semantics"))
    keys = ("ctv_full_labels", "ctv_array", "ctv_mask", "ctv_label_data") if semantics in {
        "multi_target_gtv", "target_plus_anatomy"
    } else ("ctv_array", "ctv_mask", "ctv_label_data")
    for key in keys:
        value = retrieve(key)
        if value is not None:
            return project_target(value, source=source, semantics=semantics, shape=shape)
    return None


def embedded_obstacle_mask(value, *, semantics):
    array = label_array(value)
    if array is None:
        return None
    return np.isin(array, (2, 3)) if canonical_semantics(semantics=semantics) == "target_plus_anatomy" else np.zeros(array.shape, bool)
