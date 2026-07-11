"""
Code Executor Tool
==================
Allows the agent to write and execute Python code on demand.
Restricted execution with controlled imports. This is a trusted-local
developer capability, not an operating-system sandbox or security boundary.
It is disabled unless BRACHYBOT_ENABLE_CODE_EXECUTOR=1 is explicitly set.
"""

import os
import ast
import json
import logging
import time
import traceback
import io
from contextlib import redirect_stdout, redirect_stderr
from typing import Dict, Any, Optional
from dataclasses import dataclass

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

ALLOWED_MODULES = {
    "numpy", "scipy", "nibabel", "SimpleITK", "matplotlib",
    "json", "math", "collections", "itertools",
    "re", "datetime", "csv", "time",
    "skimage", "pandas",
}

TRUE_VALUES = {"1", "true", "yes", "on"}


def _execution_enabled() -> bool:
    """Read the trusted-local toggle at execution time, not import time."""
    return os.environ.get("BRACHYBOT_ENABLE_CODE_EXECUTOR", "").lower() in TRUE_VALUES


class CodeExecutorTool(BaseTool):
    """Execute Python in a policy-limited, trusted-local process when enabled."""

    name = "code_executor"
    description = "Execute Python code for ad-hoc data analysis when BRACHYBOT_ENABLE_CODE_EXECUTOR=1. Available libraries: numpy, scipy, nibabel, SimpleITK, matplotlib, pandas, skimage. Returns stdout, stderr, and result."
    input_schema = {
        "code": {"type": "string", "description": "Python code to execute"},
        "description": {"type": "string", "description": "Brief description of what the code does"},
    }
    output_schema = {
        "success": {"type": "boolean"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "result": {"type": "string"},
    }

    def _sanitize_code(self, code: str) -> tuple:
        """Check for dangerous patterns. Returns (safe, warnings)."""
        warnings = []
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, [f"Syntax error: {exc}"]

        dangerous_names = {"__import__", "eval", "exec", "compile", "globals", "locals"}
        dangerous_attrs = {
            "os.system", "os.popen", "os.remove", "os.rmdir",
            "shutil.rmtree", "shutil.move", "socket.socket", "sys.modules",
        }

        def attr_path(node):
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in dangerous_names:
                    warnings.append(f"Potentially dangerous call: {node.func.id}")
                elif isinstance(node.func, ast.Attribute):
                    call_name = attr_path(node.func)
                    if call_name in dangerous_attrs:
                        warnings.append(f"Potentially dangerous call: {call_name}")
            elif isinstance(node, ast.Attribute):
                attr_name = attr_path(node)
                if attr_name in dangerous_attrs:
                    warnings.append(f"Potentially dangerous attribute: {attr_name}")

        return len(warnings) == 0, warnings

    def _safe_import(self, name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".", 1)[0]
        if root not in ALLOWED_MODULES:
            raise ImportError(f"Import of '{name}' is not allowed")
        return __import__(name, globals, locals, fromlist, level)

    def _execute(self, **kwargs) -> "ToolResult":
        code = kwargs.get("code", "")
        description = kwargs.get("description", "")

        if not _execution_enabled():
            return ToolResult(
                success=False,
                error="code_executor is disabled",
                message=(
                    "Code execution is disabled by default. Set "
                    "BRACHYBOT_ENABLE_CODE_EXECUTOR=1 only in a trusted local environment."
                ),
            )

        if not code:
            return ToolResult(
                success=False,
                error="No code provided",
                message="Code execution requires 'code' parameter",
            )

        try:
            safe, warnings = self._sanitize_code(code)
            if not safe:
                return ToolResult(
                    success=False,
                    error=f"Code contains potentially dangerous patterns: {'; '.join(warnings)}",
                    message="Code execution blocked for security reasons",
                )

            # Set up execution environment with safe builtins
            # Start with a minimal set of safe builtins
            safe_builtins = {
                'abs': abs, 'all': all, 'any': any, 'ascii': ascii, 'bin': bin,
                'bool': bool, 'bytearray': bytearray, 'bytes': bytes, 'chr': chr,
                'complex': complex, 'dict': dict, 'dir': dir, 'divmod': divmod,
                'enumerate': enumerate, 'filter': filter, 'float': float, 'format': format,
                'frozenset': frozenset, 'getattr': getattr, 'hasattr': hasattr,
                'hash': hash, 'hex': hex, 'id': id, 'int': int, 'isinstance': isinstance,
                'issubclass': issubclass, 'iter': iter, 'len': len, 'list': list,
                'map': map, 'max': max, 'min': min, 'next': next, 'object': object,
                'oct': oct, 'ord': ord, 'pow': pow, 'print': print, 'property': property,
                'range': range, 'repr': repr, 'reversed': reversed, 'round': round,
                'set': set, 'slice': slice, 'sorted': sorted, 'staticmethod': staticmethod,
                'str': str, 'sum': sum, 'super': super, 'tuple': tuple, 'type': type,
                'zip': zip, 'True': True, 'False': False, 'None': None,
                'Ellipsis': Ellipsis, 'NotImplemented': NotImplemented,
                # Allow imports only through the module allowlist above.
                '__import__': self._safe_import,
            }

            env = {"__builtins__": safe_builtins}

            # Pre-import allowed modules
            for mod_name in ALLOWED_MODULES:
                try:
                    mod = __import__(mod_name)
                    env[mod_name.split(".")[-1]] = mod
                    # Also import submodules
                    if mod_name == "numpy":
                        env["np"] = mod
                    elif mod_name == "scipy":
                        env["scipy"] = mod
                except ImportError:
                    pass

            # Capture output
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()

            start_time = time.time()
            try:
                with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                    exec(compile(code, "<brachybot_code>", "exec"), env)
            except Exception as e:
                stderr_buf.write(f"Runtime error: {e}\n{traceback.format_exc()}")

            elapsed = time.time() - start_time
            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue()

            # Truncate long outputs
            max_len = 4000
            if len(stdout) > max_len:
                stdout = stdout[:max_len] + "\n... (output truncated)"
            if len(stderr) > max_len:
                stderr = stderr[:max_len] + "\n... (output truncated)"

            return ToolResult(
                success=not stderr.strip(),
                data={
                    "stdout": stdout,
                    "stderr": stderr,
                    "elapsed_ms": round(elapsed * 1000, 1),
                },
                message=f"Code executed in {elapsed:.1f}s" + (f" — {description}" if description else ""),
                metadata={"tool": "code_executor", "description": description},
            )

        except Exception as e:
            logger.error(f"Code executor failed: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Code execution failed: {e}",
            )
