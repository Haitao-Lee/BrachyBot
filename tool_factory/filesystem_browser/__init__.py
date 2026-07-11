"""
Filesystem Browser Tool
=======================
Allows the agent to list directories and inspect file metadata.
"""

import logging
import os
import stat
from pathlib import Path

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".nii", ".nii.gz", ".dcm", ".dicom", ".mha", ".nrrd",
    ".json", ".txt", ".csv", ".xml", ".yaml", ".yml",
    ".py", ".md", ".log",
}

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _configured_roots() -> tuple[Path, ...]:
    """Return the directories the read-only browser may inspect by default."""
    project_root = Path(__file__).resolve().parents[2]
    roots = [project_root, project_root / "uploads", project_root / "outputs"]
    for variable in (
        "BRACHYBOT_FILESYSTEM_ROOTS",
        "BRACHYBOT_CT_DATA_ROOTS",
        "BRACHYBOT_MR_DATA_ROOTS",
        "BRACHYBOT_US_DATA_ROOTS",
    ):
        for raw in os.environ.get(variable, "").split(os.pathsep):
            if raw.strip():
                roots.append(Path(raw.strip()).expanduser())

    resolved: list[Path] = []
    for root in roots:
        try:
            candidate = root.resolve(strict=False)
        except OSError:
            continue
        if candidate not in resolved:
            resolved.append(candidate)
    return tuple(resolved)


def _path_is_allowed(path: str) -> tuple[bool, Path]:
    """Resolve a path and enforce the browser's explicit root allowlist."""
    resolved = Path(path).expanduser().resolve(strict=False)
    global_access = os.environ.get(
        "BRACHYBOT_ENABLE_FILESYSTEM_BROWSER_GLOBAL", ""
    ).strip().lower() in _TRUE_VALUES
    if global_access:
        return True, resolved
    for root in _configured_roots():
        try:
            resolved.relative_to(root)
            return True, resolved
        except ValueError:
            continue
    return False, resolved


class FilesystemBrowserTool(BaseTool):
    """Browse filesystem: list directories, get file info."""

    name = "filesystem_browser"
    description = "List directory contents or get file metadata. Parameters: 'path' (required: directory or file path to browse), 'action' (optional: 'list' to list directory contents, 'info' to get file details). Example: {\"path\": \"/some/directory\", \"action\": \"list\"}"
    input_schema = {
        "action": {"type": "string", "enum": ["list", "info"], "description": "Action: 'list' directory or get 'info' about a file"},
        "path": {"type": "string", "description": "Directory or file path to browse"},
    }
    output_schema = {
        "success": {"type": "boolean"},
        "entries": {"type": "array"},
        "file_info": {"type": "object"},
    }

    def _execute(self, **kwargs) -> "ToolResult":
        action = kwargs.get("action", "list")
        path = kwargs.get("path", "")

        if not path:
            return ToolResult(
                success=False,
                error="No path provided",
                message="Filesystem browse requires 'path' parameter",
            )

        try:
            allowed, resolved_path = _path_is_allowed(path)
            normalized = str(resolved_path)
            if not allowed:
                return ToolResult(
                    success=False,
                    error=(
                        "Access denied: path is outside the configured project/data roots. "
                        "Add it to BRACHYBOT_FILESYSTEM_ROOTS or explicitly enable trusted "
                        "global browsing with BRACHYBOT_ENABLE_FILESYSTEM_BROWSER_GLOBAL=1."
                    ),
                    message="Path access restricted for security",
                )

            if action == "list":
                if not resolved_path.is_dir():
                    return ToolResult(
                        success=False,
                        error=f"Not a directory: {path}",
                        message="Path is not a directory",
                    )

                entries = []
                try:
                    items = sorted(os.listdir(resolved_path))
                except PermissionError:
                    return ToolResult(
                        success=False,
                        error=f"Permission denied: {path}",
                        message="Cannot list directory",
                    )

                for item in items:
                    item_path = resolved_path / item
                    try:
                        st = item_path.stat()
                        is_dir = item_path.is_dir()
                        lower_name = item.lower()
                        ext = ".nii.gz" if lower_name.endswith(".nii.gz") else item_path.suffix.lower()
                        entries.append({
                            "name": item,
                            "type": "directory" if is_dir else "file",
                            "size": st.st_size if not is_dir else None,
                            "size_human": self._human_size(st.st_size) if not is_dir else None,
                            "extension": ext,
                            "is_medical_image": ext in {".nii", ".nii.gz", ".dcm", ".mha", ".nrrd"},
                        })
                    except (OSError, PermissionError):
                        entries.append({"name": item, "type": "unknown", "size": None})

                # Filter to show max 100 entries
                if len(entries) > 100:
                    entries = entries[:100]

                return ToolResult(
                    success=True,
                    data={"entries": entries, "total": len(entries), "path": normalized},
                    message=f"Listed {len(entries)} items in {path}",
                    metadata={"tool": "filesystem_browser", "action": "list"},
                )

            elif action == "info":
                if not resolved_path.exists():
                    return ToolResult(
                        success=False,
                        error=f"File not found: {path}",
                        message="File does not exist",
                    )

                st = resolved_path.stat()
                info = {
                    "path": normalized,
                    "name": resolved_path.name,
                    "type": "directory" if resolved_path.is_dir() else "file",
                    "size": st.st_size,
                    "size_human": self._human_size(st.st_size),
                    "created": st.st_ctime,
                    "modified": st.st_mtime,
                    "permissions": stat.filemode(st.st_mode),
                }

                return ToolResult(
                    success=True,
                    data=info,
                    message=f"File info for {path}",
                    metadata={"tool": "filesystem_browser", "action": "info"},
                )

            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown action: {action}. Use 'list' or 'info'.",
                    message="Invalid action",
                )

        except Exception as e:
            logger.error(f"Filesystem browser failed: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Filesystem browse failed: {e}",
            )

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 ** 2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 ** 3:
            return f"{size_bytes / 1024 ** 2:.1f} MB"
        else:
            return f"{size_bytes / 1024 ** 3:.1f} GB"
