"""
Environment Manager Tool
========================
Allows the agent to create virtual environments, install packages,
and manage Python dependencies dynamically.

Security layers (added 2026-06-27):
- Path traversal protection on env_name
- Package name validation (blocks known malicious patterns)
- Dangerous command interception in run_in_env
- Audit logging for all operations
"""

import os
import sys
import json
import logging
import subprocess
import venv
import shutil
import re
import time
from typing import Dict, Any, Optional, List
from pathlib import Path

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Base directory for virtual environments
ENVS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "envs")
TRUE_VALUES = {"1", "true", "yes", "on"}


def _execution_enabled() -> bool:
    """Environment mutation is available only in trusted local Developer Mode."""
    return os.environ.get("BRACHYBOT_ENABLE_ENV_MANAGER", "").lower() in TRUE_VALUES

# Audit log path. Keep audit output outside the package directory so read-only
# deployments still record operations.
_AUDIT_DIR = os.environ.get(
    "BRACHYBOT_AUDIT_DIR",
    os.path.join(os.path.expanduser("~"), ".brachybot", "audit"),
)
_AUDIT_LOG = os.path.join(_AUDIT_DIR, "env_manager.log")


def _audit(action: str, detail: str, env_name: str = ""):
    """Append an audit entry. Never raises."""
    try:
        os.makedirs(_AUDIT_DIR, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] action={action} env={env_name!r} detail={detail}\n"
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass  # audit failure must not block the operation


# ─── Path traversal guard ───────────────────────────────────────────
_ENV_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')


def _validate_env_name(name: str) -> Optional[str]:
    """Return None if valid, error message if invalid."""
    if not name:
        return "env_name is required"
    if not _ENV_NAME_RE.match(name):
        return (
            f"Invalid env_name '{name}'. "
            "Must be 1-64 chars: alphanumeric, dot, hyphen, underscore. "
            "Must start with alphanumeric."
        )
    # Resolve the path and ensure it stays inside ENVS_DIR
    resolved = (Path(ENVS_DIR) / name).resolve()
    allowed_root = Path(ENVS_DIR).resolve()
    if os.path.commonpath((str(resolved), str(allowed_root))) != str(allowed_root):
        return "env_name resolves outside the allowed directory"
    return None


# ─── Package validation ─────────────────────────────────────────────
# Allowed package patterns (safe packages)
ALLOWED_PACKAGE_PATTERNS = [
    "numpy", "scipy", "pandas", "matplotlib", "scikit-image", "scikit-learn",
    "SimpleITK", "nibabel", "pydicom", "torch", "tensorflow", "keras",
    "opencv-python", "Pillow", "scipy", "nibabel", "pydicom",
    "pymedphys", "pylinac", "dicompyler", "plotly", "seaborn",
    "scipy", "statsmodels", "sympy", "networkx",
    # Common medical/scientific packages
    "monai", "tqdm", "requests", "flask", "flask-cors", "openai",
    "anthropic", "transformers", "huggingface-hub", "safetensors",
    "accelerate", "datasets", "tokenizers", "sentencepiece",
    "einops", "timm", "lightning", "pytorch-lightning",
    "joblib", "threadpoolctl", "filelock", "fsspec",
    "pyyaml", "toml", "tomli", "click", "rich", "typer",
    "Pillow", "imageio", "tifffile", "lazy-loader",
    "networkx", "python-dateutil", "pytz", "tzdata",
    "contourpy", "cycler", "fontools", "kiwisolver",
    "pyparsing", "packaging", "platformdirs",
    # Web/network
    "httpx", "aiohttp", "beautifulsoup4", "lxml", "soupsieve",
    "urllib3", "certifi", "charset-normalizer", "idna",
    # Scientific
    "threadpoolctl", "llvmlite", "numba", "pooch",
    "more-itertools", "jinja2", "markupsafe",
    # Medical imaging
    "highdicom", "pylibjpeg", "python-gdcm", "rt-utils",
    "dicompyler-core", "pymedphys", "pylinac",
]

# Blocked packages (potentially dangerous or known malicious)
BLOCKED_PACKAGES = [
    # stdlib names that aren't real pip packages
    "os", "sys", "subprocess", "shutil", "socket", "ctypes",
    # Known malicious or dangerous packages
    "hacking", "exploit", "attack", "malware", "virus", "trojan",
    "backdoor", "keylogger", "ransomware",
    # Typosquatting of popular packages
    "reqeusts", "reqeust", "beutifulsoup", "beatifulsoup",
    "pillow-simd",  # not the real Pillow
    # Packages that can execute arbitrary code on install
    "setup-cfg",  # not a real package
]

# Dangerous command patterns for run_in_env
_DANGEROUS_CMD_PATTERNS = [
    r'rm\s+-rf\s+/',           # rm -rf /
    r'rm\s+-rf\s+~',           # rm -rf ~
    r'rm\s+-rf\s+\*',          # rm -rf *
    r'mkfs\.',                 # mkfs (format disk)
    r'dd\s+if=.*of=/dev/',     # dd to device
    r'>\s*/dev/sd',            # overwrite disk device
    r'chmod\s+777\s+/',        # chmod 777 /
    r'wget.*\|\s*sh',          # download and execute
    r'curl.*\|\s*sh',          # download and execute
    r'curl.*\|\s*bash',        # download and execute
    r'wget.*\|\s*bash',        # download and execute
    r'eval\s*\(',              # eval() in Python
    r'exec\s*\(',              # exec() in Python
    r'__import__\s*\(',        # __import__() bypass
    r'importlib\.import_module',  # dynamic import bypass
]

_DANGEROUS_CMD_RE = re.compile('|'.join(_DANGEROUS_CMD_PATTERNS), re.IGNORECASE)


class EnvManagerTool(BaseTool):
    """Manage Python virtual environments and install packages."""

    name = "env_manager"
    description = """Manage isolated Python environments when BRACHYBOT_ENABLE_ENV_MANAGER=1 in trusted local Developer Mode.
Capabilities:
- create_env: Create a new virtual environment
- install: Install packages using pip
- uninstall: Uninstall packages
- list_envs: List all virtual environments
- list_packages: List installed packages in an environment
- delete_env: Delete a virtual environment
- run_in_env: Run a command in a specific environment"""

    input_schema = {
        "action": {
            "type": "string",
            "description": "Action to perform: create_env, install, uninstall, list_envs, list_packages, delete_env, run_in_env",
            "enum": ["create_env", "install", "uninstall", "list_envs", "list_packages", "delete_env", "run_in_env"]
        },
        "env_name": {
            "type": "string",
            "description": "Name of the virtual environment"
        },
        "packages": {
            "type": "string",
            "description": "Package(s) to install/uninstall (comma-separated for multiple)"
        },
        "command": {
            "type": "string",
            "description": "Command to run in the environment (for run_in_env action)"
        },
        "python_version": {
            "type": "string",
            "description": "Python version for new environment (default: current)"
        },
    }
    output_schema = {
        "success": {"type": "boolean"},
        "message": {"type": "string"},
        "data": {"type": "object"},
    }

    def is_available(self) -> bool:
        return _execution_enabled()

    def _get_env_path(self, env_name: str) -> Path:
        """Get the path for a virtual environment."""
        return Path(ENVS_DIR) / env_name

    def _validate_package_name(self, package: str) -> Optional[str]:
        """Validate package name. Return None if valid, error message if invalid."""
        # Strip version specifiers: numpy==1.24.0 -> numpy
        pkg_base = package.strip().lower().split("=")[0].split(">")[0].split("<")[0].split("!")[0].split("[")[0]
        pkg_base = pkg_base.replace("-", "_").replace(".", "_")  # normalize

        # Check blocked packages (exact match after normalization)
        for blocked in BLOCKED_PACKAGES:
            blocked_norm = blocked.replace("-", "_").replace(".", "_")
            if pkg_base == blocked_norm:
                return f"Package '{package}' is blocked (known dangerous or not a real pip package)"

        # Check for suspicious patterns in the full specifier
        full = package.strip().lower()
        # Block URL-based installs (pip install https://...)
        if full.startswith(("http://", "https://", "git+", "svn+", "hg+")):
            return f"URL-based package installs are not allowed: '{package}'"
        # Block local path installs
        if full.startswith(("/", "./", "../", "~/")):
            return f"Local path installs are not allowed: '{package}'"
        # Block --extra-index-url or --index-url (could point to malicious index)
        if "--" in full:
            return f"pip flags in package name are not allowed: '{package}'"

        allowed = {
            item.lower().replace("-", "_").replace(".", "_")
            for item in ALLOWED_PACKAGE_PATTERNS
        }
        configured = os.environ.get("BRACHYBOT_ENV_PACKAGE_ALLOWLIST", "")
        allowed.update(
            item.strip().lower().replace("-", "_").replace(".", "_")
            for item in configured.split(",") if item.strip()
        )
        if pkg_base not in allowed:
            return (
                f"Package '{package}' is not allowlisted. Add its canonical name to "
                "BRACHYBOT_ENV_PACKAGE_ALLOWLIST in trusted Developer Mode."
            )

        return None  # valid

    def _create_env(self, env_name: str, python_version: Optional[str] = None) -> ToolResult:
        """Create a new virtual environment."""
        # Validate env_name
        err = _validate_env_name(env_name)
        if err:
            _audit("create_env_blocked", err, env_name)
            return ToolResult(success=False, error=err, message=err)

        env_path = self._get_env_path(env_name)

        if python_version:
            current = f"{sys.version_info.major}.{sys.version_info.minor}"
            requested = str(python_version).strip()
            if requested not in {current, f"python{current}"}:
                return ToolResult(
                    success=False,
                    error=f"Requested Python {requested} is unavailable",
                    message=f"This manager creates environments with the running Python {current}.",
                )

        if env_path.exists():
            return ToolResult(
                success=False,
                error=f"Environment '{env_name}' already exists",
                message=f"Environment '{env_name}' already exists at {env_path}"
            )

        try:
            Path(ENVS_DIR).mkdir(parents=True, exist_ok=True)
            # Create virtual environment
            builder = venv.EnvBuilder(
                system_site_packages=False,
                clear=True,
                with_pip=True,
                upgrade_deps=True,
            )
            builder.create(str(env_path))

            # Get python path in venv
            if sys.platform == "win32":
                python_path = env_path / "Scripts" / "python.exe"
                pip_path = env_path / "Scripts" / "pip.exe"
            else:
                python_path = env_path / "bin" / "python"
                pip_path = env_path / "bin" / "pip"

            # Upgrade pip
            subprocess.run(
                [str(python_path), "-m", "pip", "install", "--upgrade", "pip"],
                capture_output=True,
                text=True,
                timeout=60
            )

            return ToolResult(
                success=True,
                data={
                    "env_name": env_name,
                    "env_path": str(env_path),
                    "python_path": str(python_path),
                    "pip_path": str(pip_path),
                },
                message=f"Virtual environment '{env_name}' created successfully",
            )

        except Exception as e:
            logger.error(f"Failed to create environment: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Failed to create environment '{env_name}'"
            )

    def _install_packages(self, env_name: str, packages: str) -> ToolResult:
        """Install packages in a virtual environment."""
        err = _validate_env_name(env_name)
        if err:
            return ToolResult(success=False, error=err, message=err)

        env_path = self._get_env_path(env_name)

        if not env_path.exists():
            return ToolResult(
                success=False,
                error=f"Environment '{env_name}' not found",
                message=f"Environment '{env_name}' not found. Create it first with create_env action."
            )

        # Parse packages
        pkg_list = [p.strip() for p in packages.split(",") if p.strip()]

        # Validate packages
        invalid_pkgs = []
        for pkg in pkg_list:
            err = self._validate_package_name(pkg)
            if err:
                invalid_pkgs.append(err)

        if invalid_pkgs:
            _audit("install_blocked", "; ".join(invalid_pkgs), env_name)
            return ToolResult(
                success=False,
                error=f"Package validation failed",
                message=f"Blocked: {'; '.join(invalid_pkgs)}"
            )

        # Get pip path
        if sys.platform == "win32":
            pip_path = env_path / "Scripts" / "pip.exe"
        else:
            pip_path = env_path / "bin" / "pip"

        if not pip_path.exists():
            return ToolResult(
                success=False,
                error="pip not found in environment",
                message="pip not found in virtual environment"
            )

        try:
            # Install packages
            cmd = [str(pip_path), "install"] + pkg_list
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )

            if result.returncode == 0:
                _audit("install_ok", f"packages={pkg_list}", env_name)
                return ToolResult(
                    success=True,
                    data={
                        "env_name": env_name,
                        "packages": pkg_list,
                        "output": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
                    },
                    message=f"Successfully installed {len(pkg_list)} package(s) in '{env_name}'",
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.stderr[-1000:] if result.stderr else "Installation failed",
                    message=f"Failed to install packages in '{env_name}'",
                    data={"stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]}
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error="Installation timed out (5 minutes)",
                message="Package installation timed out"
            )
        except Exception as e:
            logger.error(f"Failed to install packages: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Failed to install packages in '{env_name}'"
            )

    def _list_envs(self) -> ToolResult:
        """List all virtual environments."""
        envs = []

        if os.path.exists(ENVS_DIR):
            for item in os.listdir(ENVS_DIR):
                env_path = Path(ENVS_DIR) / item
                if env_path.is_dir():
                    # Check if it's a valid venv
                    if sys.platform == "win32":
                        python_exists = (env_path / "Scripts" / "python.exe").exists()
                    else:
                        python_exists = (env_path / "bin" / "python").exists()

                    if python_exists:
                        envs.append({
                            "name": item,
                            "path": str(env_path),
                            "size_mb": round(sum(f.stat().st_size for f in env_path.rglob("*") if f.is_file()) / (1024*1024), 2)
                        })

        return ToolResult(
            success=True,
            data={"envs": envs, "count": len(envs)},
            message=f"Found {len(envs)} virtual environment(s)",
        )

    def _list_packages(self, env_name: str) -> ToolResult:
        """List packages installed in an environment."""
        err = _validate_env_name(env_name)
        if err:
            return ToolResult(success=False, error=err, message=err)

        env_path = self._get_env_path(env_name)

        if not env_path.exists():
            return ToolResult(
                success=False,
                error=f"Environment '{env_name}' not found",
                message=f"Environment '{env_name}' not found"
            )

        # Get pip path
        if sys.platform == "win32":
            pip_path = env_path / "Scripts" / "pip.exe"
        else:
            pip_path = env_path / "bin" / "pip"

        try:
            result = subprocess.run(
                [str(pip_path), "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                packages = json.loads(result.stdout)
                return ToolResult(
                    success=True,
                    data={"env_name": env_name, "packages": packages},
                    message=f"Found {len(packages)} packages in '{env_name}'",
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.stderr,
                    message=f"Failed to list packages in '{env_name}'"
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Failed to list packages in '{env_name}'"
            )

    def _uninstall_packages(self, env_name: str, packages: str) -> ToolResult:
        """Uninstall validated packages from an existing managed environment."""
        err = _validate_env_name(env_name)
        if err:
            return ToolResult(success=False, error=err, message=err)
        pkg_list = [item.strip() for item in packages.split(",") if item.strip()]
        invalid = [error for item in pkg_list if (error := self._validate_package_name(item))]
        if invalid:
            return ToolResult(success=False, error="; ".join(invalid), message="Package validation failed")
        env_path = self._get_env_path(env_name)
        pip_path = env_path / ("Scripts/pip.exe" if sys.platform == "win32" else "bin/pip")
        if not pip_path.exists():
            return ToolResult(success=False, error="Managed environment or pip not found", message=f"Environment '{env_name}' is unavailable")
        try:
            result = subprocess.run(
                [str(pip_path), "uninstall", "-y", *pkg_list],
                capture_output=True,
                text=True,
                timeout=60,
            )
            _audit("uninstall", f"packages={pkg_list} returncode={result.returncode}", env_name)
            return ToolResult(
                success=result.returncode == 0,
                error=result.stderr[-1000:] if result.returncode else None,
                message=(f"Uninstalled packages from '{env_name}'" if result.returncode == 0 else "Uninstall failed"),
                data={"stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), message=f"Failed to uninstall from '{env_name}'")

    def _delete_env(self, env_name: str) -> ToolResult:
        """Delete a virtual environment."""
        err = _validate_env_name(env_name)
        if err:
            return ToolResult(success=False, error=err, message=err)

        env_path = self._get_env_path(env_name)

        if not env_path.exists():
            return ToolResult(
                success=False,
                error=f"Environment '{env_name}' not found",
                message=f"Environment '{env_name}' not found"
            )

        try:
            shutil.rmtree(str(env_path))
            return ToolResult(
                success=True,
                data={"env_name": env_name, "path": str(env_path)},
                message=f"Virtual environment '{env_name}' deleted successfully",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Failed to delete environment '{env_name}'"
            )

    def _run_in_env(self, env_name: str, command: str) -> ToolResult:
        """Run a command in a virtual environment."""
        err = _validate_env_name(env_name)
        if err:
            return ToolResult(success=False, error=err, message=err)

        env_path = self._get_env_path(env_name)

        if not env_path.exists():
            return ToolResult(
                success=False,
                error=f"Environment '{env_name}' not found",
                message=f"Environment '{env_name}' not found"
            )

        # Dangerous command check (log + block, don't silently allow)
        if _DANGEROUS_CMD_RE.search(command):
            _audit("run_in_env_BLOCKED", f"Dangerous command pattern: {command[:200]}", env_name)
            return ToolResult(
                success=False,
                error="Command blocked by security policy",
                message=(
                    "This command matches a dangerous pattern and was blocked. "
                    "If this is intentional, the command must be restructured."
                ),
                data={"blocked_command": command[:500]}
            )

        # Get python path
        if sys.platform == "win32":
            python_path = env_path / "Scripts" / "python.exe"
        else:
            python_path = env_path / "bin" / "python"

        _audit("run_in_env", f"cmd={command[:200]}", env_name)

        try:
            # Run command using the environment's python
            cmd = [str(python_path), "-c", command]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2 minutes (increased from 60s)
            )

            return ToolResult(
                success=result.returncode == 0,
                data={
                    "env_name": env_name,
                    "stdout": result.stdout[-5000:],
                    "stderr": result.stderr[-2000:],
                    "returncode": result.returncode,
                },
                message=f"Command executed in '{env_name}'" + (" successfully" if result.returncode == 0 else " with errors"),
            )

        except subprocess.TimeoutExpired:
            _audit("run_in_env_TIMEOUT", f"cmd={command[:200]}", env_name)
            return ToolResult(
                success=False,
                error="Command timed out (120 seconds)",
                message=f"Command timed out in '{env_name}'"
            )
        except Exception as e:
            _audit("run_in_env_ERROR", f"{type(e).__name__}: {e}", env_name)
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Failed to run command in '{env_name}'"
            )

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        env_name = kwargs.get("env_name", "")
        packages = kwargs.get("packages", "")
        command = kwargs.get("command", "")
        python_version = kwargs.get("python_version")

        if not _execution_enabled():
            return ToolResult(
                success=False,
                error="env_manager is disabled",
                message=(
                    "Environment management is disabled by default. Set "
                    "BRACHYBOT_ENABLE_ENV_MANAGER=1 only in trusted local Developer Mode."
                ),
            )

        if not action:
            return ToolResult(
                success=False,
                error="No action specified",
                message="Please specify an action: create_env, install, uninstall, list_envs, list_packages, delete_env, run_in_env"
            )

        if action == "create_env":
            if not env_name:
                return ToolResult(success=False, error="env_name required", message="env_name is required for create_env")
            return self._create_env(env_name, python_version)

        elif action == "install":
            if not env_name:
                return ToolResult(success=False, error="env_name required", message="env_name is required for install")
            if not packages:
                return ToolResult(success=False, error="packages required", message="packages is required for install")
            return self._install_packages(env_name, packages)

        elif action == "uninstall":
            if not env_name:
                return ToolResult(success=False, error="env_name required", message="env_name is required for uninstall")
            if not packages:
                return ToolResult(success=False, error="packages required", message="packages is required for uninstall")
            return self._uninstall_packages(env_name, packages)

        elif action == "list_envs":
            return self._list_envs()

        elif action == "list_packages":
            if not env_name:
                return ToolResult(success=False, error="env_name required", message="env_name is required for list_packages")
            return self._list_packages(env_name)

        elif action == "delete_env":
            if not env_name:
                return ToolResult(success=False, error="env_name required", message="env_name is required for delete_env")
            return self._delete_env(env_name)

        elif action == "run_in_env":
            if not env_name:
                return ToolResult(success=False, error="env_name required", message="env_name is required for run_in_env")
            if not command:
                return ToolResult(success=False, error="command required", message="command is required for run_in_env")
            return self._run_in_env(env_name, command)

        else:
            return ToolResult(
                success=False,
                error=f"Unknown action: {action}",
                message=f"Unknown action '{action}'. Valid actions: create_env, install, uninstall, list_envs, list_packages, delete_env, run_in_env"
            )
