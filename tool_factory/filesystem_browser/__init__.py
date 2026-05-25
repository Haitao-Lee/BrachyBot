"""
Filesystem Browser Tool
=======================
Allows the agent to list directories and inspect file metadata.
"""

import os
import stat
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".nii", ".nii.gz", ".dcm", ".dicom", ".mha", ".nrrd",
    ".json", ".txt", ".csv", ".xml", ".yaml", ".yml",
    ".py", ".md", ".log",
}


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
            # Security: prevent access to sensitive directories
            normalized = os.path.normpath(os.path.abspath(path))
            blocked_prefixes = ["/etc", "/proc", "/sys", "/dev", "/root/.ssh"]
            for prefix in blocked_prefixes:
                if normalized.startswith(prefix):
                    return ToolResult(
                        success=False,
                        error=f"Access denied: {prefix} is restricted",
                        message="Path access restricted for security",
                    )

            if action == "list":
                if not os.path.isdir(path):
                    return ToolResult(
                        success=False,
                        error=f"Not a directory: {path}",
                        message="Path is not a directory",
                    )

                entries = []
                try:
                    items = sorted(os.listdir(path))
                except PermissionError:
                    return ToolResult(
                        success=False,
                        error=f"Permission denied: {path}",
                        message="Cannot list directory",
                    )

                for item in items:
                    item_path = os.path.join(path, item)
                    try:
                        st = os.stat(item_path)
                        is_dir = os.path.isdir(item_path)
                        ext = os.path.splitext(item)[-1].lower()
                        if item.endswith(".gz"):
                            ext = ".gz"
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
                if not os.path.exists(path):
                    return ToolResult(
                        success=False,
                        error=f"File not found: {path}",
                        message="File does not exist",
                    )

                st = os.stat(path)
                info = {
                    "path": normalized,
                    "name": os.path.basename(path),
                    "type": "directory" if os.path.isdir(path) else "file",
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
