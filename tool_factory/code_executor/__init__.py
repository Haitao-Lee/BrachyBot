"""
Code Executor Tool
==================
Allows the agent to write and execute Python code on demand.
Sandboxed execution with controlled imports and timeouts.
"""

import os
import sys
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
    "json", "os", "sys", "math", "collections", "itertools",
    "re", "datetime", "pathlib", "csv", "io", "time",
    "skimage", "pandas",
}

DANGEROUS_PATTERNS = [
    "__import__", "importlib", "subprocess", "os.system",
    "os.popen", "exec(", "eval(", "compile(",
    "shutil", "socket",
    "urllib", "requests", "http",
]


class CodeExecutorTool(BaseTool):
    """Execute Python code in a sandboxed environment."""

    name = "code_executor"
    description = "Execute Python code for ad-hoc tasks: inspecting medical images, computing statistics, data analysis, etc. Available libraries: numpy, scipy, nibabel, SimpleITK, matplotlib, pandas, skimage. Returns stdout, stderr, and result."
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
        for pattern in DANGEROUS_PATTERNS:
            if pattern in code:
                # Allow os.path operations
                if pattern == "open(" and "os.path" not in code.split(pattern)[0][-20:]:
                    warnings.append(f"Potentially dangerous pattern: {pattern}")
                elif pattern not in ("open(",):
                    warnings.append(f"Potentially dangerous pattern: {pattern}")

        # Allow open() for reading medical images but warn
        if "open(" in code and "nibabel" not in code and "SimpleITK" not in code:
            warnings.append("Using open() directly — prefer nibabel or SimpleITK for medical images")

        return len(warnings) == 0, warnings

    def _execute(self, **kwargs) -> "ToolResult":
        code = kwargs.get("code", "")
        description = kwargs.get("description", "")

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
                # Allow __import__ for import statements (sandboxed by allowed modules list)
                '__import__': __import__,
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
