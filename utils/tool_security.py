"""Server-owned path containment for case tools; not a Python sandbox."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import os

_scope = ContextVar("brachybot_tool_scope", default=None)
EXECUTION_TOOLS = frozenset({"code_executor", "code_writer", "write_tool", "create_tool", "tool_creator", "self_evolve", "evolve", "shell_executor", "env_manager"})
_PATH_FIELDS = frozenset({"path", "file_path", "image_path", "ct_image_path", "ct_path", "label_path", "ctv_mask_path", "oar_mask_path", "mask_path", "output_path", "output_dir", "input_path", "original_ct_path", "intra_op_ct_path", "dicom_path", "paths", "files", "file_paths", "input_files", "dicom_files"})


@contextmanager
def tool_scope(config=None):
    # Nested calls inherit the caller; tool arguments cannot install a scope.
    root = (config or {}).get("_workspace_root")
    token = _scope.set(Path(root).resolve()) if root else None
    try:
        yield
    finally:
        if token is not None:
            _scope.reset(token)


def workspace_root():
    return _scope.get()


def checked_path(value, *, root=None):
    boundary = Path(root).resolve() if root is not None else workspace_root()
    path = Path(os.fspath(value)).expanduser().resolve()
    if boundary is not None and path != boundary and boundary not in path.parents:
        raise PermissionError("Tool path is outside the authenticated case workspace")
    if boundary is not None and path.is_file() and path.stat().st_nlink > 1:
        raise PermissionError("Hard-linked tool files are not accepted in web case workspaces")
    return path


def validate_tool_paths(name, params, *, config=None):
    with tool_scope(config):
        if workspace_root() is None:
            return
        if name in EXECUTION_TOOLS:
            raise PermissionError("Developer execution tools are disabled in web case agents")
        def validate_file(value):
            path = checked_path(value)
            if path.is_file() and str(path).lower().endswith((".nii", ".nii.gz", ".mha", ".mhd", ".nrrd", ".nhdr", ".dcm", ".dicom")):
                # Inspect the header before legacy tool implementations decode
                # pixels. This also checks detached sidecar references.
                from utils.image_limits import image_header
                image_header(path)
        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    is_path = key in _PATH_FIELDS or str(key).endswith(("_path", "_dir", "_paths", "_dirs"))
                    if is_path and isinstance(item, (str, os.PathLike)) and item:
                        validate_file(item)
                    elif is_path and isinstance(item, (list, tuple)):
                        for entry in item:
                            if isinstance(entry, (str, os.PathLike)) and entry:
                                validate_file(entry)
                            elif isinstance(entry, (dict, list, tuple)):
                                visit(entry)
                    elif isinstance(item, (dict, list, tuple)):
                        visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)
        visit(params)


def output_directory(category, fallback):
    root = workspace_root()
    path = checked_path(root / "artifacts" / category) if root else Path(fallback)
    path.mkdir(parents=True, exist_ok=True)
    return path
