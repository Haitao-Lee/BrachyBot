"""Unified node, group, and Session scene export service."""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional
from xml.sax.saxutils import escape as xml_escape

import numpy as np
import SimpleITK as sitk
from skimage import measure

from plans.dose_pre.model_loader import (
    dose_gy_to_model,
    resolve_dose_scale_gy,
    resolve_prescription_gy,
)
from web.structure_service import EffectiveStructures, build_effective_structures


EXPORT_SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)


class ExportError(ValueError):
    """Raised when an export request cannot be fulfilled."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_name(value: Any, fallback: str = "data") -> str:
    text = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(value or "")).strip(" ._")
    # Export roots are already deeply nested in an owned case workspace.
    # Keeping each generated component bounded avoids Win32 MAX_PATH failures
    # while the manifest retains every full human-readable object name.
    return text[:64] or fallback


def _reference_image(memory: Any, shape: Optional[tuple[int, int, int]] = None) -> sitk.Image:
    reference = memory.retrieve("ct_image")
    if reference is None:
        reference = memory.retrieve("ct_sitk")
    if isinstance(reference, sitk.Image):
        return reference
    array = memory.retrieve("ct_data")
    if array is None:
        if shape is None:
            raise ExportError("No CT geometry is available")
        array = np.zeros(shape, dtype=np.int16)
    image = sitk.GetImageFromArray(np.asarray(array))
    spacing = memory.retrieve("ct_spacing")
    origin = memory.retrieve("ct_origin")
    direction = memory.retrieve("ct_direction")
    if isinstance(spacing, (list, tuple)) and len(spacing) >= 3:
        image.SetSpacing(tuple(float(value) for value in spacing[:3]))
    if isinstance(origin, (list, tuple)) and len(origin) >= 3:
        image.SetOrigin(tuple(float(value) for value in origin[:3]))
    if isinstance(direction, (list, tuple)) and len(direction) >= 9:
        image.SetDirection(tuple(float(value) for value in direction[:9]))
    return image


def _ct_array(memory: Any) -> Optional[np.ndarray]:
    """Return the durable CT voxel array regardless of its in-memory form."""
    array = memory.retrieve("ct_data")
    if array is not None:
        data = np.asarray(array)
        return data if data.ndim == 3 and data.size else None
    for key in ("ct_image", "ct_sitk"):
        image = memory.retrieve(key)
        if isinstance(image, sitk.Image):
            data = sitk.GetArrayFromImage(image)
            return data if data.ndim == 3 and data.size else None
    return None


def _write_nifti(array: Any, path: Path, memory: Any, *, unit: str = "") -> None:
    data = np.asarray(array)
    if data.ndim != 3 or data.size == 0:
        raise ExportError("The requested volume is empty")
    image = sitk.GetImageFromArray(data)
    reference = _reference_image(memory, tuple(int(value) for value in data.shape))
    image.SetSpacing(reference.GetSpacing())
    image.SetOrigin(reference.GetOrigin())
    image.SetDirection(reference.GetDirection())
    if unit:
        image.SetMetaData("BrachyBot.Unit", unit)
        image.SetMetaData("intent_name", unit)
    path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(path), True)
    if not path.is_file() or path.stat().st_size <= 0:
        raise ExportError(f"NIfTI export is empty: {path.name}")


def _physical_vertices(vertices_zyx: np.ndarray, reference: sitk.Image) -> np.ndarray:
    output = np.empty((len(vertices_zyx), 3), dtype=np.float64)
    for index, vertex in enumerate(vertices_zyx):
        output[index] = reference.TransformContinuousIndexToPhysicalPoint(
            (float(vertex[2]), float(vertex[1]), float(vertex[0]))
        )
    return output


def _ascii_stl(vertices: np.ndarray, faces: np.ndarray, name: str) -> bytes:
    lines = [f"solid {_safe_name(name)}"]
    for face in np.asarray(faces, dtype=np.int64):
        triangle = vertices[face]
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        norm = float(np.linalg.norm(normal))
        if norm > 0:
            normal = normal / norm
        else:
            normal = np.zeros(3, dtype=np.float64)
        lines.append(f"  facet normal {normal[0]:.9g} {normal[1]:.9g} {normal[2]:.9g}")
        lines.append("    outer loop")
        for vertex in triangle:
            lines.append(f"      vertex {vertex[0]:.9g} {vertex[1]:.9g} {vertex[2]:.9g}")
        lines.extend(("    endloop", "  endfacet"))
    lines.append(f"endsolid {_safe_name(name)}")
    return ("\n".join(lines) + "\n").encode("ascii")


def _write_mask_stl(mask: Any, path: Path, memory: Any, name: str) -> None:
    binary = np.asarray(mask, dtype=np.uint8)
    if binary.ndim != 3 or np.count_nonzero(binary) < 4:
        raise ExportError("The selected structure has no exportable surface")
    padded = np.pad(binary, 1, mode="constant")
    vertices, faces, _normals, _values = measure.marching_cubes(padded, level=0.5)
    vertices -= 1.0
    vertices = _physical_vertices(vertices, _reference_image(memory, binary.shape))
    payload = _ascii_stl(vertices, faces, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _planning_snapshot(memory: Any) -> Dict[str, list]:
    manual_seeds = memory.retrieve("manual_seeds")
    manual_needles = memory.retrieve("manual_needles")
    manual_seeds = [] if manual_seeds is None else list(manual_seeds)
    manual_needles = [] if manual_needles is None else list(manual_needles)
    if memory.retrieve("manual_plan_active") or manual_seeds or manual_needles:
        return {"seeds": list(manual_seeds), "needles": list(manual_needles)}
    baseline = memory.retrieve("algorithm_plan_snapshot")
    if isinstance(baseline, Mapping):
        baseline_seeds = baseline.get("seeds")
        baseline_needles = baseline.get("needles")
        return {
            "seeds": list([] if baseline_seeds is None else baseline_seeds),
            "needles": list([] if baseline_needles is None else baseline_needles),
        }
    serialized = memory.retrieve("seed_plan_serialized")
    serialized = [] if serialized is None else serialized
    if isinstance(serialized, Mapping):
        nested = serialized.get("trajectories")
        if nested is None:
            nested = serialized.get("plan")
        serialized = [serialized] if nested is None else nested
    geometry = memory.retrieve("verified_needle_geometry") or {}
    seeds: list[Dict[str, Any]] = []
    needles: list[Dict[str, Any]] = []
    for trajectory_index, entry in enumerate(serialized):
        trajectory_id = f"traj_{trajectory_index + 1}"
        points = geometry.get(str(trajectory_index))
        if points is None:
            points = geometry.get(trajectory_index)
        if isinstance(points, list) and len(points) >= 2:
            needles.append({
                "id": f"needle_{trajectory_index}",
                "points": points[:2],
                "trajectory_id": trajectory_id,
            })
        if isinstance(entry, Mapping):
            serialized_seeds = entry.get("seeds")
            if serialized_seeds is None:
                serialized_seeds = []
        elif isinstance(entry, (list, tuple)):
            serialized_seeds = entry
        else:
            continue
        for seed_index, seed in enumerate(serialized_seeds):
            if isinstance(seed, Mapping):
                position = seed.get("position")
                if position is None:
                    position = seed.get("pos")
                direction = seed.get("direction")
                if direction is None:
                    direction = seed.get("dir")
            elif isinstance(seed, (list, tuple)) and len(seed) >= 2:
                position, direction = seed[0], seed[1]
            else:
                continue
            seeds.append({
                "id": f"seed_{trajectory_index}_{seed_index}",
                "position": position,
                "direction": direction,
                "trajectory_id": trajectory_id,
            })
    return {"seeds": seeds, "needles": needles}


def _normalized_needles(memory: Any) -> list[Dict[str, Any]]:
    planning_id = str(memory.retrieve("manual_planning_id") or memory.retrieve("planning_id") or "")
    records = []
    for index, needle in enumerate(_planning_snapshot(memory)["needles"]):
        if not isinstance(needle, Mapping):
            continue
        points = needle.get("points")
        if points is None:
            points = []
        if not isinstance(points, (list, tuple, np.ndarray)) or len(points) < 2:
            continue
        start = np.asarray(points[0], dtype=float).reshape(-1)[:3]
        end = np.asarray(points[-1], dtype=float).reshape(-1)[:3]
        direction = end - start
        length = float(np.linalg.norm(direction))
        if length > 0:
            direction = direction / length
        records.append({
            "needle_id": str(needle.get("id") or f"needle_{index}"),
            "name": str(needle.get("name") or f"Needle {index + 1}"),
            "index": index,
            "start_point": start.tolist(),
            "end_point": end.tolist(),
            "direction": direction.tolist(),
            "length_mm": length,
            "planning_id": planning_id,
            "coordinate_system": "LPS",
        })
    return records


def _normalized_seeds(memory: Any) -> list[Dict[str, Any]]:
    config = memory.retrieve("plan_config") or {}
    seed_info = config.get("seed_info") if isinstance(config, Mapping) else {}
    length = float((seed_info or {}).get("length", 4.5) or 4.5)
    radius = float((seed_info or {}).get("radius", 0.4) or 0.4)
    planning_id = str(memory.retrieve("manual_planning_id") or memory.retrieve("planning_id") or "")
    records = []
    for index, seed in enumerate(_planning_snapshot(memory)["seeds"]):
        if not isinstance(seed, Mapping):
            continue
        position = seed.get("position")
        if position is None:
            position = seed.get("pos")
        direction = seed.get("direction")
        if direction is None:
            direction = seed.get("dir")
        if direction is None:
            direction = [0, 0, 1]
        if position is None:
            continue
        records.append({
            "seed_id": str(seed.get("id") or f"seed_{index}"),
            "needle_id": str(seed.get("needle_id") or seed.get("trajectory_id") or ""),
            "position": np.asarray(position, dtype=float).reshape(-1)[:3].tolist(),
            "direction": np.asarray(direction, dtype=float).reshape(-1)[:3].tolist(),
            "length_mm": length,
            "diameter_mm": radius * 2.0,
            "model": str((seed_info or {}).get("model") or "I-125"),
            "planning_id": planning_id,
            "coordinate_system": "LPS",
        })
    return records


@dataclass(frozen=True)
class ExportFormat:
    key: str
    label: str
    extension: str


@dataclass
class ExportObject:
    object_id: str
    parent_id: Optional[str]
    name: str
    data_type: str
    relative_dir: str
    formats: tuple[ExportFormat, ...]
    default_format: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> Dict[str, Any]:
        return {
            "object_id": self.object_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "data_type": self.data_type,
            "formats": [
                {"key": item.key, "label": item.label, "extension": item.extension}
                for item in self.formats
            ],
            "default_format": self.default_format,
            "metadata": self.metadata,
        }


NIFTI = ExportFormat("nifti", "NIfTI (.nii.gz)", ".nii.gz")
STL = ExportFormat("stl", "STL (.stl)", ".stl")
JSON_FORMAT = ExportFormat("json", "JSON (.json)", ".json")
CSV_FORMAT = ExportFormat("csv", "CSV (.csv)", ".csv")
XLSX_FORMAT = ExportFormat("xlsx", "Excel Workbook (.xlsx)", ".xlsx")
PNG = ExportFormat("png", "PNG (.png)", ".png")
PDF = ExportFormat("pdf", "PDF (.pdf)", ".pdf")


class ExportService:
    """Maps durable objects to serializers used at every export level."""

    def __init__(self, store: Any):
        self.store = store

    def catalog(
        self, user_id: str, session_id: str, agent: Any,
    ) -> list[ExportObject]:
        memory = agent.memory
        objects: list[ExportObject] = []
        if _ct_array(memory) is not None:
            objects.append(ExportObject(
                "image:ct", "group:images", "CT", "image", "Images",
                (NIFTI,), "nifti",
            ))

        structures = build_effective_structures(memory)
        for item in structures.structures:
            classification = item["classification"].upper()
            objects.append(ExportObject(
                item["object_id"],
                f"group:structures:{classification.lower()}",
                str(item["name"]),
                "ctv" if classification == "CTV" else "oar",
                f"Structures/{classification}",
                (NIFTI, STL), "nifti",
                {
                    "classification": classification.lower(),
                    "transport_label": int(item["target_label"]),
                    "voxel_count": int(item["voxel_count"]),
                },
            ))

        skin_surface = memory.retrieve("skin_surface")
        skin_mask = memory.retrieve("skin_surface_mask")
        if isinstance(skin_surface, Mapping) and skin_mask is not None:
            skin_array = np.asarray(skin_mask)
            if skin_array.ndim == 3 and np.count_nonzero(skin_array):
                objects.append(ExportObject(
                    str(skin_surface.get("object_id") or "skin_surface:guide"),
                    "group:structures:skin",
                    str(skin_surface.get("label") or "Guide skin surface"),
                    "skin_surface",
                    "Structures/Skin",
                    (NIFTI, STL),
                    "nifti",
                    {
                        "data_tree_node_id": str(
                            skin_surface.get("data_tree_node_id") or "skin_surface"
                        ),
                        "voxel_count": int(np.count_nonzero(skin_array)),
                        "source": str(skin_surface.get("source") or "surgical_guide"),
                        "threshold_hu": skin_surface.get("threshold_hu"),
                    },
                ))

        # Generic BiomedParse/open-segmentation masks are first-class scene
        # objects.  They remain independent masks until the user explicitly
        # moves one to CTV or OAR, but they must still be exportable with the
        # same spatial metadata as any other segmentation.
        generic_masks = memory.retrieve("generic_segmentation_masks") or []
        if isinstance(generic_masks, list):
            for index, raw_entry in enumerate(generic_masks):
                if not isinstance(raw_entry, Mapping):
                    continue
                mask_array = raw_entry.get("mask_array")
                if mask_array is None:
                    continue
                try:
                    array = np.asarray(mask_array)
                except Exception:
                    continue
                if array.ndim != 3 or not np.count_nonzero(array):
                    continue
                mask_id = str(raw_entry.get("mask_id") or f"mask_{index}")
                object_id = str(
                    raw_entry.get("object_id") or f"mask:{mask_id}"
                )
                objects.append(ExportObject(
                    object_id,
                    "group:structures:masks",
                    str(raw_entry.get("label") or raw_entry.get("name") or mask_id),
                    "generic_mask",
                    "Structures/AdditionalMasks",
                    (NIFTI, STL),
                    "nifti",
                    {
                        "mask_id": mask_id,
                        "classification": str(raw_entry.get("classification") or "unclassified"),
                        "data_tree_node_id": str(
                            raw_entry.get("data_tree_node_id") or mask_id
                        ),
                        "voxel_count": int(np.count_nonzero(array)),
                    },
                ))

        needles = _normalized_needles(memory)
        seeds = _normalized_seeds(memory)
        for index, trajectory in enumerate(memory.retrieve("trajectories") or []):
            if not isinstance(trajectory, Mapping):
                continue
            trajectory_id = str(trajectory.get("id") or f"trajectory_{index + 1}")
            objects.append(ExportObject(
                f"trajectory:{trajectory_id}",
                "group:planning:trajectories",
                str(trajectory.get("name") or f"Trajectory {index + 1}"),
                "trajectory",
                "Planning/Trajectories",
                (JSON_FORMAT,),
                "json",
                {"trajectory_id": trajectory_id, "trajectory_index": index},
            ))
        for needle in needles:
            objects.append(ExportObject(
                f"needle:{needle['needle_id']}", "group:planning:needles",
                needle["name"], "needle", "Planning/Needles",
                (JSON_FORMAT,), "json", {"needle_id": needle["needle_id"]},
            ))
        for seed in seeds:
            objects.append(ExportObject(
                f"seed:{seed['seed_id']}", "group:planning:seeds",
                seed["seed_id"], "seed", "Planning/Seeds",
                (JSON_FORMAT,), "json", {"seed_id": seed["seed_id"]},
            ))
        if needles or seeds or memory.retrieve("plan_config"):
            objects.append(ExportObject(
                "planning:parameters", "group:planning", "Planning parameters",
                "planning_parameters", "Planning", (JSON_FORMAT,), "json",
            ))

        dose = memory.retrieve("dose_distribution_gy")
        if dose is None:
            dose = memory.retrieve("dose_distribution")
        if dose is not None:
            objects.append(ExportObject(
                "dose:volume", "group:dose", "Dose volume", "dose",
                "Dose", (NIFTI,), "nifti",
            ))
            prescription_gy = self._prescription_gy(memory)
            deleted_iso_levels = {
                str(value)
                for value in (memory.retrieve("deleted_dose_iso_levels") or [])
            }
            for multiplier in self._iso_multipliers(memory):
                threshold_gy = prescription_gy * multiplier
                if (
                    "all" in deleted_iso_levels
                    or f"{threshold_gy:g}" in deleted_iso_levels
                    or f"dose_iso_{threshold_gy:g}" in deleted_iso_levels
                ):
                    continue
                objects.append(ExportObject(
                    f"dose_iso:{threshold_gy:g}",
                    "group:dose:isosurfaces",
                    f"{threshold_gy:g} Gy iso-surface",
                    "dose_isosurface",
                    "Dose/IsoSurfaces",
                    (STL,),
                    "stl",
                    {"threshold_gy": threshold_gy, "multiplier": multiplier},
                ))

        dvh = self._dvh_payload(memory)
        if dvh:
            objects.extend((
                ExportObject(
                    "dvh:data", "group:dvh", "DVH data", "dvh_data",
                    "DVH", (CSV_FORMAT, XLSX_FORMAT, JSON_FORMAT), "csv",
                ),
                ExportObject(
                    "dvh:curve", "group:dvh", "DVH curve", "dvh_curve",
                    "DVH", (PNG,), "png",
                ),
            ))

        guide = memory.retrieve("surgical_guide")
        if isinstance(guide, Mapping) and guide.get("status") == "ready":
            objects.append(ExportObject(
                "surgical_guide:active", "group:surgical_guide",
                "Surgical guide", "surgical_guide", "SurgicalGuide",
                (STL,), "stl", {"version": int(guide.get("version") or 1)},
            ))

        snapshot = self.store.load_snapshot(user_id, session_id)
        report = snapshot.get("report") if isinstance(snapshot.get("report"), Mapping) else {}
        if report:
            objects.append(ExportObject(
                "report:data", "group:report", "Report data", "report_data",
                "Report", (JSON_FORMAT,), "json",
                {"status": str(report.get("status") or "ready")},
            ))
        report_pdf = self._latest_artifact(user_id, session_id, "artifacts/reports", "*.pdf")
        report_is_stale = str(report.get("status") or "").lower() == "stale"
        if report_pdf and not report_is_stale:
            objects.append(ExportObject(
                "report:pdf", "group:report", "Report", "report",
                "Report", (PDF,), "pdf", {"source_path": str(report_pdf)},
            ))

        screenshot_root = self.store.workspace_root(user_id, session_id) / "screenshots"
        report_figure_files: set[str] = set()
        report_form = report.get("form") if isinstance(report.get("form"), Mapping) else report
        for index, figure in enumerate(report_form.get("figures") or []):
            if not isinstance(figure, Mapping):
                continue
            source_url = str(figure.get("_serverUrl") or figure.get("dataUrl") or "")
            filename = Path(source_url.split("?", 1)[0]).name
            source_path = screenshot_root / filename
            if not filename.lower().endswith(".png") or not source_path.is_file():
                continue
            report_figure_files.add(filename)
            objects.append(ExportObject(
                f"figure:{filename}", "group:figures",
                str(figure.get("title") or f"Report Figure {index + 1}"),
                "report_figure", "Figures", (PNG,), "png",
                {
                    "source_path": str(source_path),
                    "axis": figure.get("axis"),
                    "captured_at": figure.get("capturedAt"),
                    "view_metadata": {
                        "axis": figure.get("axis"),
                        "figure_group": figure.get("figureGroup"),
                        "figure_number": figure.get("figureNumber"),
                        "subfigure": figure.get("subfigure"),
                        "sort_order": figure.get("sortOrder"),
                        "capture_role": figure.get("captureRole"),
                        "capture_contract": figure.get("captureContract"),
                    },
                },
            ))

        chat = snapshot.get("chat") if isinstance(snapshot.get("chat"), Mapping) else {}
        if chat:
            objects.extend((
                ExportObject(
                    "chat:history", "group:chat", "chat_history",
                    "chat_messages", "Chat", (JSON_FORMAT,), "json",
                ),
                ExportObject(
                    "chat:execution_trace", "group:chat", "execution_trace",
                    "execution_trace", "Chat", (JSON_FORMAT,), "json",
                ),
                ExportObject(
                    "chat:tool_history", "group:chat", "tool_invocation_history",
                    "tool_history", "Chat", (JSON_FORMAT,), "json",
                ),
            ))

        if screenshot_root.is_dir():
            for path in sorted(screenshot_root.glob("*.png")):
                if path.name in report_figure_files:
                    continue
                objects.append(ExportObject(
                    f"screenshot:{path.name}", "group:chat:screenshots",
                    path.stem, "screenshot", "Chat/Screenshots", (PNG,), "png",
                    {"source_path": str(path)},
                ))
        ui = snapshot.get("ui") if isinstance(snapshot.get("ui"), Mapping) else {}
        ui_state = ui.get("state") if isinstance(ui.get("state"), Mapping) else ui
        viewer = ui_state.get("viewer") if isinstance(ui_state.get("viewer"), Mapping) else {}
        for index, annotation in enumerate(viewer.get("annotations") or []):
            if not isinstance(annotation, Mapping):
                continue
            annotation_id = str(annotation.get("id") or f"annotation_{index + 1}")
            objects.append(ExportObject(
                f"annotation:{annotation_id}",
                "group:annotations",
                str(annotation.get("label") or annotation.get("name") or f"Annotation {index + 1}"),
                "annotation",
                "Annotations",
                (JSON_FORMAT,),
                "json",
                {"annotation_id": annotation_id},
            ))
        return objects

    def groups(self, objects: Iterable[ExportObject]) -> list[Dict[str, Any]]:
        definitions = {
            "group:chat": (None, "Chat & Agent History"),
            "group:chat:screenshots": ("group:chat", "Screenshots"),
            "group:images": (None, "Medical Images"),
            "group:structures": (None, "Structures"),
            "group:structures:ctv": ("group:structures", "CTV"),
            "group:structures:oar": ("group:structures", "OAR"),
            "group:structures:skin": ("group:structures", "Skin surface"),
            "group:structures:masks": ("group:structures", "Additional masks"),
            "group:planning": (None, "Planning"),
            "group:planning:trajectories": ("group:planning", "Trajectories"),
            "group:planning:needles": ("group:planning", "Needles"),
            "group:planning:seeds": ("group:planning", "Seeds"),
            "group:dose": (None, "Dose"),
            "group:dose:isosurfaces": ("group:dose", "Dose iso-surfaces"),
            "group:dvh": (None, "DVH"),
            "group:surgical_guide": (None, "Surgical Guide"),
            "group:report": (None, "Report"),
            "group:figures": (None, "Figures"),
            "group:annotations": (None, "Annotations"),
        }
        required = {item.parent_id for item in objects if item.parent_id}
        changed = True
        while changed:
            changed = False
            for group_id in list(required):
                parent = definitions.get(group_id, (None, ""))[0]
                if parent and parent not in required:
                    required.add(parent)
                    changed = True
        return [
            {"object_id": group_id, "parent_id": definitions[group_id][0],
             "name": definitions[group_id][1], "data_type": "group"}
            for group_id in definitions
            if group_id in required
        ]

    def public_catalog(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
    ) -> Dict[str, Any]:
        """Return the one public object contract used by the UI and tests."""
        objects = self.catalog(user_id, session_id, agent)
        planning_id = str(
            agent.memory.retrieve("manual_planning_id")
            or agent.memory.retrieve("planning_id")
            or ""
        )
        data_version = max(
            int(agent.memory.retrieve("planning_version") or 0),
            int(agent.memory.retrieve("manual_plan_version") or 0),
        )
        public_objects = []
        for item in objects:
            row = item.public_dict()
            row.update({
                "session_id": str(session_id),
                "case_id": str(session_id),
                "planning_id": planning_id or None,
                "data_version": data_version,
                "status": str(item.metadata.get("status") or "ready"),
                "error": item.metadata.get("error"),
            })
            public_objects.append(row)
        return {
            "session_id": str(session_id),
            "groups": self.groups(objects),
            "objects": public_objects,
        }

    def export_object(
        self,
        user_id: str,
        session_id: str,
        agent: Any,
        item: ExportObject,
        format_key: str,
        destination_root: Path,
    ) -> Path:
        format_spec = next((fmt for fmt in item.formats if fmt.key == format_key), None)
        if format_spec is None:
            raise ExportError(f"{item.name} does not support {format_key}")
        filename = _safe_name(item.name) + format_spec.extension
        path = destination_root / item.relative_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        memory = agent.memory

        if item.data_type == "image":
            _write_nifti(_ct_array(memory), path, memory)
        elif item.data_type in {"ctv", "oar"}:
            effective = build_effective_structures(memory)
            structure = next(
                (row for row in effective.structures if row["object_id"] == item.object_id),
                None,
            )
            if structure is None:
                raise ExportError(f"Structure is no longer available: {item.name}")
            if format_key == "nifti":
                _write_nifti(structure["mask"].astype(np.uint8), path, memory)
            else:
                _write_mask_stl(structure["mask"], path, memory, item.name)
        elif item.data_type == "skin_surface":
            skin_mask = memory.retrieve("skin_surface_mask")
            if skin_mask is None:
                raise ExportError("The guide skin surface is no longer available")
            if format_key == "nifti":
                _write_nifti(np.asarray(skin_mask, dtype=np.uint8), path, memory)
            else:
                _write_mask_stl(skin_mask, path, memory, item.name)
        elif item.data_type == "generic_mask":
            mask_id = str(item.metadata.get("mask_id") or "")
            entries = memory.retrieve("generic_segmentation_masks") or []
            entry = next(
                (
                    row for row in entries
                    if isinstance(row, Mapping)
                    and str(row.get("mask_id") or "") == mask_id
                ),
                None,
            )
            if not isinstance(entry, Mapping) or entry.get("mask_array") is None:
                raise ExportError(f"Generic segmentation mask is no longer available: {item.name}")
            mask_array = np.asarray(entry["mask_array"], dtype=np.uint8)
            if not np.count_nonzero(mask_array):
                raise ExportError(f"Generic segmentation mask is empty: {item.name}")
            if format_key == "nifti":
                _write_nifti(mask_array, path, memory)
            else:
                _write_mask_stl(mask_array, path, memory, item.name)
        elif item.data_type == "needle":
            needle_id = item.metadata["needle_id"]
            records = [row for row in _normalized_needles(memory) if row["needle_id"] == needle_id]
            self._write_json(path, records[0] if records else None)
        elif item.data_type == "trajectory":
            records = [
                row
                for row in (memory.retrieve("trajectories") or [])
                if isinstance(row, Mapping)
            ]
            index = int(item.metadata.get("trajectory_index") or 0)
            self._write_json(path, records[index] if index < len(records) else None)
        elif item.data_type == "seed":
            seed_id = item.metadata["seed_id"]
            records = [row for row in _normalized_seeds(memory) if row["seed_id"] == seed_id]
            self._write_json(path, records[0] if records else None)
        elif item.data_type == "planning_parameters":
            self._write_json(path, {
                "planning_id": str(memory.retrieve("manual_planning_id") or memory.retrieve("planning_id") or ""),
                "planning_version": int(memory.retrieve("manual_plan_version") or memory.retrieve("planning_version") or 0),
                "plan_config": memory.retrieve("plan_config") or {},
                "needles": _normalized_needles(memory),
                "seeds": _normalized_seeds(memory),
            })
        elif item.data_type == "dose":
            dose_gy = memory.retrieve("dose_distribution_gy")
            if dose_gy is None:
                raw_dose = memory.retrieve("dose_distribution")
                dose_gy = self._dose_gy(memory, raw_dose)
            _write_nifti(dose_gy, path, memory, unit="Gy")
        elif item.data_type == "dose_isosurface":
            self._write_dose_isosurface(
                path,
                memory,
                float(item.metadata.get("threshold_gy") or 0.0),
                item.name,
            )
        elif item.data_type == "dvh_data":
            if format_key == "json":
                self._write_json(path, self._dvh_payload(memory))
            elif format_key == "xlsx":
                self._write_dvh_xlsx(path, self._dvh_payload(memory))
            else:
                self._write_dvh_csv(path, self._dvh_payload(memory))
        elif item.data_type == "dvh_curve":
            self._write_dvh_png(path, self._dvh_payload(memory))
        elif item.data_type == "surgical_guide":
            guide = memory.retrieve("surgical_guide") or {}
            raw_vertices = guide.get("vertices")
            raw_faces = guide.get("faces")
            vertices = np.asarray([] if raw_vertices is None else raw_vertices, dtype=float)
            faces = np.asarray([] if raw_faces is None else raw_faces, dtype=int)
            if vertices.size == 0 or faces.size == 0:
                raise ExportError("The surgical guide mesh is empty")
            path.write_bytes(_ascii_stl(vertices, faces, "surgical_guide"))
        elif item.data_type == "report_data":
            snapshot = self.store.load_snapshot(user_id, session_id)
            self._write_json(path, snapshot.get("report") or {})
        elif item.data_type in {"report", "report_figure", "screenshot"}:
            source = Path(item.metadata.get("source_path") or "")
            if not source.is_file():
                raise ExportError(f"Source artifact is missing: {item.name}")
            shutil.copy2(source, path)
        elif item.data_type == "chat_messages":
            snapshot = self.store.load_snapshot(user_id, session_id)
            self._write_json(path, {
                "session": snapshot.get("session") or {},
                "messages": (snapshot.get("chat") or {}).get("messages") or [],
            })
        elif item.data_type == "execution_trace":
            snapshot = self.store.load_snapshot(user_id, session_id)
            chat = snapshot.get("chat") or {}
            traces = list(chat.get("execution_trace") or chat.get("traces") or [])
            for index, message in enumerate(chat.get("messages") or []):
                if not isinstance(message, Mapping):
                    continue
                steps = message.get("steps") or message.get("execution_trace")
                if not isinstance(steps, list) or not steps:
                    continue
                traces.append({
                    "message_id": message.get("id") or message.get("message_id") or f"message_{index + 1}",
                    "request_id": message.get("request_id"),
                    "timestamp": message.get("timestamp"),
                    "status": message.get("status"),
                    "steps": steps,
                })
            self._write_json(path, {
                "session_id": session_id,
                "execution_trace": traces,
            })
        elif item.data_type == "tool_history":
            snapshot = self.store.load_snapshot(user_id, session_id)
            agent_state = snapshot.get("agent") or {}
            chat = snapshot.get("chat") or {}
            trace_tool_steps = []
            for message_index, message in enumerate(chat.get("messages") or []):
                if not isinstance(message, Mapping):
                    continue
                for step in message.get("steps") or []:
                    if not isinstance(step, Mapping):
                        continue
                    step_type = str(step.get("type") or step.get("kind") or "").lower()
                    if "tool" not in step_type and not step.get("tool"):
                        continue
                    trace_tool_steps.append({
                        "message_id": message.get("id") or message.get("message_id") or f"message_{message_index + 1}",
                        "request_id": message.get("request_id"),
                        "tool": step.get("tool") or step.get("name"),
                        "status": step.get("status"),
                        "started_at": step.get("started_at") or step.get("timestamp"),
                        "completed_at": step.get("completed_at"),
                        "input_summary": step.get("input_summary") or step.get("args_summary"),
                        "output_summary": step.get("output_summary") or step.get("result_summary"),
                    })
            self._write_json(path, {
                "session_id": session_id,
                "agent_conversation": agent_state.get("conversation") or [],
                "tool_results": (snapshot.get("agent") or {}).get("tool_results") or [],
                "trace_tool_steps": trace_tool_steps,
                "audit_events": self.store.list_audit_events(user_id, session_id, 1000),
            })
        elif item.data_type == "annotation":
            snapshot = self.store.load_snapshot(user_id, session_id)
            ui = snapshot.get("ui") if isinstance(snapshot.get("ui"), Mapping) else {}
            ui_state = ui.get("state") if isinstance(ui.get("state"), Mapping) else ui
            viewer = ui_state.get("viewer") if isinstance(ui_state.get("viewer"), Mapping) else {}
            annotation_id = str(item.metadata.get("annotation_id") or "")
            annotation = next(
                (
                    row for index, row in enumerate(viewer.get("annotations") or [])
                    if isinstance(row, Mapping)
                    and str(row.get("id") or f"annotation_{index + 1}") == annotation_id
                ),
                None,
            )
            self._write_json(path, annotation)
        else:
            raise ExportError(f"No serializer is registered for {item.data_type}")
        if not path.is_file() or path.stat().st_size <= 0:
            raise ExportError(f"Export produced an empty file: {path.name}")
        return path

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        if value is None:
            raise ExportError("The requested object no longer exists")
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _dvh_payload(memory: Any) -> Dict[str, Any]:
        direct = memory.retrieve("dvh_data")
        if isinstance(direct, Mapping) and direct:
            return dict(direct)
        metrics = memory.retrieve("dose_metrics") or {}
        nested = metrics.get("dvh_data") if isinstance(metrics, Mapping) else {}
        return dict(nested) if isinstance(nested, Mapping) else {}

    @staticmethod
    def _dose_scale_gy(memory: Any) -> float:
        return resolve_dose_scale_gy(
            memory.retrieve("plan_config") or {},
            memory.retrieve("dose_metrics") or {},
            dose_scale_gy=memory.retrieve("dose_scale_gy"),
        )

    @classmethod
    def _dose_gy(cls, memory: Any, dose: Any) -> np.ndarray:
        array = np.asarray(dose, dtype=np.float32)
        units = str(memory.retrieve("dose_units") or "").strip().lower()
        if units in {"gy", "physical_gy"}:
            return array
        return array * cls._dose_scale_gy(memory)

    @classmethod
    def _prescription_gy(cls, memory: Any) -> float:
        return resolve_prescription_gy(
            memory.retrieve("plan_config") or {},
            memory.retrieve("dose_metrics") or {},
            dose_scale_gy=cls._dose_scale_gy(memory),
        )

    @staticmethod
    def _iso_multipliers(memory: Any) -> list[float]:
        plan_config = memory.retrieve("plan_config") or {}
        iso_params = plan_config.get("iso_dose_params") if isinstance(plan_config, Mapping) else {}
        raw = iso_params.get("iso_dose_values") if isinstance(iso_params, Mapping) else None
        values = raw if isinstance(raw, (list, tuple)) else [1.0, 1.5, 2.0, 4.0]
        output = []
        for value in values:
            try:
                multiplier = float(value)
            except (TypeError, ValueError):
                continue
            if multiplier > 0 and math.isfinite(multiplier) and multiplier not in output:
                output.append(multiplier)
        return output or [1.0, 1.5, 2.0, 4.0]

    def _write_dose_isosurface(
        self,
        path: Path,
        memory: Any,
        threshold_gy: float,
        name: str,
    ) -> None:
        if not threshold_gy > 0:
            raise ExportError("The dose iso-surface threshold is invalid")
        physical_dose = memory.retrieve("dose_distribution_gy")
        raw = physical_dose
        if raw is None:
            raw = memory.retrieve("dose_distribution")
        if raw is None:
            raise ExportError("No dose distribution is available")
        dose = np.asarray(raw, dtype=np.float32)
        units = str(memory.retrieve("dose_units") or "").strip().lower()
        level = (
            threshold_gy
            if physical_dose is not None or units in {"gy", "physical_gy"}
            else dose_gy_to_model(threshold_gy, self._dose_scale_gy(memory))
        )
        if dose.ndim != 3 or dose.size == 0:
            raise ExportError("The dose volume is empty")
        data_min = float(np.nanmin(dose))
        data_max = float(np.nanmax(dose))
        if not data_min < level <= data_max:
            raise ExportError(
                f"{threshold_gy:g} Gy is outside the available dose range"
            )
        vertices, faces, _normals, _values = measure.marching_cubes(
            dose,
            level=level,
            allow_degenerate=False,
        )
        vertices = _physical_vertices(vertices, _reference_image(memory, dose.shape))
        path.write_bytes(_ascii_stl(vertices, faces, name))

    @staticmethod
    def _curve_points(value: Any) -> tuple[list[float], list[float]]:
        if isinstance(value, Mapping):
            dose = next(
                (value.get(key) for key in ("dose", "doses", "dose_bins")
                 if value.get(key) is not None),
                [],
            )
            volume = next(
                (value.get(key) for key in ("volume_percent", "volumes_percent", "volume", "volumes")
                 if value.get(key) is not None),
                [],
            )
            return list(dose), list(volume)
        if isinstance(value, list) and value and isinstance(value[0], Mapping):
            return (
                [float(row.get("dose", 0)) for row in value],
                [float(row.get("volume_percent", row.get("volume", 0))) for row in value],
            )
        return [], []

    @staticmethod
    def _curve_columns(
        value: Any,
    ) -> tuple[list[float], list[Optional[float]], list[Optional[float]]]:
        """Return dose, absolute volume, and volume-percent without conflating units."""
        if isinstance(value, Mapping):
            dose_source = next(
                (value.get(key) for key in ("dose", "doses", "dose_bins")
                 if value.get(key) is not None),
                [],
            )
            percent_source = next(
                (value.get(key) for key in ("volume_percent", "volumes_percent")
                 if value.get(key) is not None),
                None,
            )
            absolute_source = next(
                (value.get(key) for key in ("volume_cc", "volumes_cc", "absolute_volume")
                 if value.get(key) is not None),
                None,
            )
            generic_source = next(
                (value.get(key) for key in ("volume", "volumes")
                 if value.get(key) is not None),
                None,
            )
            total_volume = value.get("total_volume_cc")
            if total_volume is None:
                total_volume = value.get("structure_volume_cc")
            if percent_source is None and generic_source is not None:
                # The viewer's existing generic "volume" field is cumulative
                # percentage. Treat it as such unless an explicit absolute
                # volume field is present.
                percent_source = generic_source
            dose = [float(item) for item in list(dose_source)]
            percent = (
                [float(item) for item in list(percent_source)]
                if percent_source is not None else []
            )
            absolute = (
                [float(item) for item in list(absolute_source)]
                if absolute_source is not None else []
            )
            if not absolute and percent and total_volume is not None:
                total = float(total_volume)
                absolute = [total * item / 100.0 for item in percent]
            size = len(dose)
            return (
                dose,
                [absolute[index] if index < len(absolute) else None for index in range(size)],
                [percent[index] if index < len(percent) else None for index in range(size)],
            )
        if isinstance(value, list) and value and isinstance(value[0], Mapping):
            return (
                [float(row.get("dose", 0)) for row in value],
                [
                    float(row["volume_cc"]) if row.get("volume_cc") is not None else None
                    for row in value
                ],
                [
                    float(row.get("volume_percent", row.get("volume", 0)))
                    if row.get("volume_percent", row.get("volume")) is not None else None
                    for row in value
                ],
            )
        return [], [], []

    def _write_dvh_csv(self, path: Path, payload: Mapping[str, Any]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(("Structure", "Dose_Gy", "Volume_cc", "Volume_Percent"))
            rows = 0
            for name, value in payload.items():
                dose, absolute, percent = self._curve_columns(value)
                for index, dose_value in enumerate(dose):
                    writer.writerow((
                        name,
                        dose_value,
                        "" if absolute[index] is None else absolute[index],
                        "" if percent[index] is None else percent[index],
                    ))
                    rows += 1
            if rows == 0:
                raise ExportError("DVH data contains no curve samples")

    def _write_dvh_xlsx(self, path: Path, payload: Mapping[str, Any]) -> None:
        rows: list[list[Any]] = [
            ["Structure", "Dose_Gy", "Volume_cc", "Volume_Percent"],
        ]
        for name, value in payload.items():
            dose, absolute, percent = self._curve_columns(value)
            for index, dose_value in enumerate(dose):
                rows.append([
                    name,
                    dose_value,
                    "" if absolute[index] is None else absolute[index],
                    "" if percent[index] is None else percent[index],
                ])
        if len(rows) == 1:
            raise ExportError("DVH data contains no curve samples")

        def cell(reference: str, value: Any) -> str:
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return f'<c r="{reference}"><v>{float(value):.12g}</v></c>'
            text = xml_escape(str(value))
            return f'<c r="{reference}" t="inlineStr"><is><t>{text}</t></is></c>'

        letters = ("A", "B", "C", "D")
        sheet_rows = []
        for row_index, values in enumerate(rows, 1):
            cells = "".join(
                cell(f"{letters[column]}{row_index}", value)
                for column, value in enumerate(values)
            )
            sheet_rows.append(f'<row r="{row_index}">{cells}</row>')
        sheet = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>' + "".join(sheet_rows) + '</sheetData></worksheet>'
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        )
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        workbook = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="DVH" sheetId="1" r:id="rId1"/></sheets></workbook>'
        )
        workbook_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)

    def _write_dvh_png(self, path: Path, payload: Mapping[str, Any]) -> None:
        try:
            from PIL import Image, ImageDraw
        except ImportError as exc:  # pragma: no cover - viewer already depends on Pillow
            raise ExportError("PNG export requires Pillow") from exc
        width, height = 1200, 760
        margin = (90, 50, 40, 80)
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        curves = []
        maximum_dose = 0.0
        for name, value in payload.items():
            dose, volume = self._curve_points(value)
            points = [
                (float(dose[index]), float(volume[index]))
                for index in range(min(len(dose), len(volume)))
                if math.isfinite(float(dose[index])) and math.isfinite(float(volume[index]))
            ]
            if points:
                curves.append((str(name), points))
                maximum_dose = max(maximum_dose, max(point[0] for point in points))
        if not curves or maximum_dose <= 0:
            raise ExportError("DVH data contains no plottable curves")
        left, top, right_margin, bottom_margin = margin
        right = width - right_margin
        bottom = height - bottom_margin
        draw.line((left, top, left, bottom), fill="#334155", width=2)
        draw.line((left, bottom, right, bottom), fill="#334155", width=2)
        palette = ("#ef4444", "#2563eb", "#16a34a", "#a855f7", "#f59e0b", "#0891b2")
        for curve_index, (name, points) in enumerate(curves):
            color = palette[curve_index % len(palette)]
            pixels = [
                (
                    left + point[0] / maximum_dose * (right - left),
                    bottom - max(0.0, min(100.0, point[1])) / 100.0 * (bottom - top),
                )
                for point in points
            ]
            if len(pixels) >= 2:
                draw.line(pixels, fill=color, width=3)
            legend_y = top + curve_index * 24
            draw.line((right - 190, legend_y + 6, right - 160, legend_y + 6), fill=color, width=3)
            draw.text((right - 150, legend_y), name, fill="#0f172a")
        draw.text((width // 2 - 40, height - 45), "Dose (Gy)", fill="#0f172a")
        draw.text((18, 18), "Volume (%)", fill="#0f172a")
        image.save(path, "PNG")

    def _latest_artifact(
        self, user_id: str, session_id: str, relative: str, pattern: str,
    ) -> Optional[Path]:
        root = self.store.workspace_root(user_id, session_id) / relative
        if not root.is_dir():
            return None
        files = [path for path in root.glob(pattern) if path.is_file()]
        return max(files, key=lambda path: path.stat().st_mtime) if files else None


@dataclass
class ExportJob:
    job_id: str
    user_id: str
    session_id: str
    status: str = "queued"
    completed: int = 0
    total: int = 0
    current: str = ""
    files: list[Dict[str, Any]] = field(default_factory=list)
    failures: list[Dict[str, str]] = field(default_factory=list)
    skipped: list[Dict[str, str]] = field(default_factory=list)
    zip_path: str = ""
    export_root: str = ""
    created_at: float = field(default_factory=time.time)
    cancel_requested: bool = False

    def public_dict(self) -> Dict[str, Any]:
        folder_name = Path(self.export_root).name if self.export_root else ""
        return {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "status": self.status,
            "completed": self.completed,
            "total": self.total,
            "current": self.current,
            "files": self.files,
            "failures": self.failures,
            "skipped": self.skipped,
            "created_at": self.created_at,
            "cancel_requested": self.cancel_requested,
            "folder_name": folder_name,
        }


class ExportJobManager:
    """Runs case-bound exports without blocking the selected Session UI."""

    def __init__(self, store: Any, get_agent_for_owner: Callable[..., Any]):
        self.store = store
        self.get_agent_for_owner = get_agent_for_owner
        self._jobs: Dict[str, ExportJob] = {}
        self._lock = threading.RLock()

    def create(
        self,
        user: Mapping[str, Any],
        session_id: str,
        selections: list[Mapping[str, Any]],
        session_name: str,
    ) -> ExportJob:
        job = ExportJob(
            job_id=uuid.uuid4().hex,
            user_id=str(user["id"]),
            session_id=str(session_id),
            total=len(selections),
        )
        with self._lock:
            self._jobs[job.job_id] = job
        owner = dict(user)
        worker = threading.Thread(
            target=self._run,
            args=(job, owner, list(selections), session_name),
            daemon=True,
            name=f"export-{job.job_id[:8]}",
        )
        worker.start()
        return job

    def get(self, user_id: str, job_id: str) -> ExportJob:
        with self._lock:
            job = self._jobs.get(str(job_id))
        if job is None or job.user_id != str(user_id):
            raise ExportError("Export job was not found")
        return job

    def cancel(self, user_id: str, job_id: str) -> ExportJob:
        job = self.get(user_id, job_id)
        job.cancel_requested = True
        return job

    @staticmethod
    def _version_vector(memory: Any) -> Dict[str, Any]:
        """Identity of the medical/planning data captured by one export."""
        ct = _ct_array(memory)
        ctv = memory.retrieve("ctv_array")
        oar = memory.retrieve("oar_array")
        return {
            "planning_version": int(memory.retrieve("planning_version") or 0),
            "manual_plan_version": int(memory.retrieve("manual_plan_version") or 0),
            "ct_path": str(
                memory.retrieve("ct_image_path")
                or memory.retrieve("ct_path")
                or ""
            ),
            "ct_shape": list(ct.shape) if ct is not None else [],
            "ctv_shape": list(np.asarray(ctv).shape) if ctv is not None else [],
            "oar_shape": list(np.asarray(oar).shape) if oar is not None else [],
        }

    def _run(
        self,
        job: ExportJob,
        user: Mapping[str, Any],
        selections: list[Mapping[str, Any]],
        session_name: str,
    ) -> None:
        try:
            job.status = "preparing"
            agent = self.get_agent_for_owner(dict(user), job.session_id)
            if agent is None:
                raise ExportError("The case workspace could not be loaded")
            service = ExportService(self.store)
            catalog = {
                item.object_id: item
                for item in service.catalog(job.user_id, job.session_id, agent)
            }
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder = f"BrachyBot_{_safe_name(session_name, job.session_id)[:32]}_{stamp}"
            # Scene exports are transient downloadable bundles. Building them
            # below the already-deep user/session workspace can exceed Win32
            # path limits once the stable directory tree is appended. The
            # store's private staging root remains server-owned, while job
            # authorization still binds every download to user + Session.
            export_root = (
                self.store.staging_dir
                / "scene_exports"
                / job.job_id
                / folder
            )
            export_root.mkdir(parents=True, exist_ok=True)
            job.export_root = str(export_root)
            manifest_files = []
            source_version = self._version_vector(agent.memory)
            source_changed = False
            job.status = "running"
            for selection in selections:
                if job.cancel_requested:
                    job.status = "cancelled"
                    break
                object_id = str(selection.get("object_id") or "")
                if source_changed or self._version_vector(agent.memory) != source_version:
                    source_changed = True
                    job.skipped.append({
                        "object_id": object_id,
                        "reason": "Session data changed while the export was running",
                    })
                    job.completed += 1
                    continue
                item = catalog.get(object_id)
                if item is None:
                    job.skipped.append({"object_id": object_id, "reason": "Object is unavailable"})
                    job.completed += 1
                    continue
                format_key = str(selection.get("format") or item.default_format)
                job.current = item.name
                try:
                    path = service.export_object(
                        job.user_id, job.session_id, agent, item, format_key, export_root,
                    )
                    if self._version_vector(agent.memory) != source_version:
                        path.unlink(missing_ok=True)
                        source_changed = True
                        raise ExportError(
                            "Session data changed while this object was being exported"
                        )
                    relative = path.relative_to(export_root).as_posix()
                    record = {
                        "object_id": item.object_id,
                        "data_type": item.data_type,
                        "format": format_key,
                        "relative_path": relative,
                        "bytes": path.stat().st_size,
                        "planning_id": str(
                            agent.memory.retrieve("manual_planning_id")
                            or agent.memory.retrieve("planning_id")
                            or ""
                        ),
                        "data_version": max(
                            source_version["planning_version"],
                            source_version["manual_plan_version"],
                        ),
                        "version_vector": source_version,
                        "coordinate_system": "LPS",
                    }
                    job.files.append(record)
                    manifest_files.append(record)
                except Exception as exc:
                    job.failures.append({"object_id": object_id, "error": str(exc)})
                finally:
                    job.completed += 1

            session = self.store.get_session(job.user_id, job.session_id)
            manifest = {
                "schema_version": EXPORT_SCHEMA_VERSION,
                "session_id": job.session_id,
                "session_name": session.title,
                "case_id": job.session_id,
                "planning_id": str(agent.memory.retrieve("manual_planning_id") or agent.memory.retrieve("planning_id") or ""),
                "export_time": _utc_now(),
                "brachybot_version": os.getenv("BRACHYBOT_VERSION", "unknown"),
                "data_version": max(
                    source_version["planning_version"],
                    source_version["manual_plan_version"],
                ),
                "version_vector": source_version,
                "coordinate_system": "LPS",
                "files": manifest_files,
                "failures": job.failures,
                "skipped": job.skipped,
            }
            manifest_path = export_root / "session_manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            job.files.append({
                "object_id": "session:manifest",
                "data_type": "manifest",
                "format": "json",
                "relative_path": "session_manifest.json",
                "bytes": manifest_path.stat().st_size,
            })

            if job.status == "cancelled":
                # Completed files remain intact in server staging for
                # diagnostics, but a cancelled job is never presented as a
                # downloadable Scene and does not spend time compressing work
                # the user explicitly stopped.
                job.zip_path = ""
                job.current = ""
                return

            zip_path = export_root.parent / f"{folder}.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(export_root.rglob("*")):
                    if path.is_file():
                        archive.write(path, f"{folder}/{path.relative_to(export_root).as_posix()}")
            job.zip_path = str(zip_path)
            job.status = (
                "completed_with_errors"
                if job.failures or job.skipped else "completed"
            )
            job.current = ""
        except Exception as exc:
            logger.exception(
                "Session export job failed (session=%s, job=%s)",
                job.session_id,
                job.job_id,
            )
            job.status = "failed"
            job.failures.append({"object_id": "session", "error": str(exc)})
            job.current = ""
