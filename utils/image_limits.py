"""Reject oversized decoded medical images before allocating their pixels."""
import math
import os
from pathlib import Path
import re
import SimpleITK as sitk


def check_voxel_count(size, *, components=1, series_length=1):
    values = tuple(int(value) for value in size)
    if not values or any(value <= 0 for value in values) or int(components) <= 0 or int(series_length) <= 0:
        raise ValueError("Invalid image dimensions")
    try:
        configured = int(os.environ.get("BRACHYBOT_MAX_IMAGE_VOXELS", 256 * 1024 * 1024))
    except ValueError:
        configured = 256 * 1024 * 1024
    maximum = max(1, min(configured, 512 * 1024 * 1024))
    if math.prod(values) * int(components) * int(series_length) > maximum:
        raise ValueError("Decoded medical image exceeds the configured voxel limit")


def _check_detached_image(path):
    path = Path(path).resolve()
    if path.suffix.lower() not in {".mhd", ".mha", ".nhdr", ".nrrd"}:
        return
    # Read only the bounded textual header, never an embedded pixel payload.
    with path.open("rb") as handle:
        header = handle.read(64 * 1024).decode("utf-8", errors="replace")
    for line in header.splitlines():
        match = re.match(r"\s*(?:ElementDataFile\s*=|data\s+file\s*:)\s*(.+)", line, re.I)
        if not match:
            continue
        value = match.group(1).strip()
        if value.upper() == "LOCAL":
            return
        if value.upper().startswith("LIST") or "%" in value:
            raise ValueError("Detached multi-file image headers require an explicit validated import")
        from utils.tool_security import workspace_root, checked_path
        checked_path(path.parent / value, root=workspace_root() or path.parent)
        return


def image_header(path):
    _check_detached_image(path)
    reader = sitk.ImageFileReader()
    reader.SetFileName(str(path))
    reader.ReadImageInformation()
    check_voxel_count(reader.GetSize(), components=reader.GetNumberOfComponents())
    return reader


def read_image(path):
    return image_header(path).Execute()
