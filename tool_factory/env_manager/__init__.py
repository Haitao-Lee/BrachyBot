"""
Environment Manager Tool
========================
Allows the agent to create virtual environments, install packages,
and manage Python dependencies dynamically.
"""

import os
import sys
import json
import logging
import subprocess
import venv
import shutil
from typing import Dict, Any, Optional, List
from pathlib import Path

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Base directory for virtual environments
ENVS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "envs")
os.makedirs(ENVS_DIR, exist_ok=True)

# Allowed package patterns (safe packages)
ALLOWED_PACKAGE_PATTERNS = [
    "numpy", "scipy", "pandas", "matplotlib", "scikit-image", "scikit-learn",
    "SimpleITK", "nibabel", "pydicom", "torch", "tensorflow", "keras",
    "opencv-python", "Pillow", "scipy", "nibabel", "pydicom",
    "pymedphys", "pylinac", "dicompyler", "plotly", "seaborn",
    "scipy", "statsmodels", "sympy", "networkx",
]

# Blocked packages (potentially dangerous)
BLOCKED_PACKAGES = [
    "os", "sys", "subprocess", "shutil",  # These are stdlib, not pip packages
    "hacking", "exploit", "attack",  # Security-related
]


class EnvManagerTool(BaseTool):
    """Manage Python virtual environments and install packages."""

    name = "env_manager"
    description = """Create virtual environments, install Python packages, and manage dependencies.
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

    def _get_env_path(self, env_name: str) -> Path:
        """Get the path for a virtual environment."""
        return Path(ENVS_DIR) / env_name

    def _validate_package_name(self, package: str) -> bool:
        """Validate package name is safe."""
        package_lower = package.strip().lower().split("=")[0].split(">")[0].split("<")[0]

        # Check blocked packages
        for blocked in BLOCKED_PACKAGES:
            if blocked in package_lower:
                return False

        return True

    def _create_env(self, env_name: str, python_version: Optional[str] = None) -> ToolResult:
        """Create a new virtual environment."""
        env_path = self._get_env_path(env_name)

        if env_path.exists():
            return ToolResult(
                success=False,
                error=f"Environment '{env_name}' already exists",
                message=f"Environment '{env_name}' already exists at {env_path}"
            )

        try:
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
            if not self._validate_package_name(pkg):
                invalid_pkgs.append(pkg)

        if invalid_pkgs:
            return ToolResult(
                success=False,
                error=f"Invalid packages: {', '.join(invalid_pkgs)}",
                message=f"The following packages are not allowed: {', '.join(invalid_pkgs)}"
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

    def _delete_env(self, env_name: str) -> ToolResult:
        """Delete a virtual environment."""
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
        env_path = self._get_env_path(env_name)

        if not env_path.exists():
            return ToolResult(
                success=False,
                error=f"Environment '{env_name}' not found",
                message=f"Environment '{env_name}' not found"
            )

        # Get python path
        if sys.platform == "win32":
            python_path = env_path / "Scripts" / "python.exe"
        else:
            python_path = env_path / "bin" / "python"

        try:
            # Run command using the environment's python
            cmd = [str(python_path), "-c", command]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            return ToolResult(
                success=result.returncode == 0,
                data={
                    "env_name": env_name,
                    "stdout": result.stdout[-2000:],
                    "stderr": result.stderr[-1000:],
                    "returncode": result.returncode,
                },
                message=f"Command executed in '{env_name}'" + (" successfully" if result.returncode == 0 else " with errors"),
            )

        except Exception as e:
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
            # Use pip to uninstall
            env_path = self._get_env_path(env_name)
            if sys.platform == "win32":
                pip_path = env_path / "Scripts" / "pip.exe"
            else:
                pip_path = env_path / "bin" / "pip"
            pkg_list = [p.strip() for p in packages.split(",")]
            try:
                result = subprocess.run(
                    [str(pip_path), "uninstall", "-y"] + pkg_list,
                    capture_output=True, text=True, timeout=60
                )
                return ToolResult(
                    success=result.returncode == 0,
                    message=f"Uninstalled packages from '{env_name}'" if result.returncode == 0 else "Uninstall failed",
                    data={"stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]}
                )
            except Exception as e:
                return ToolResult(success=False, error=str(e), message=f"Failed to uninstall from '{env_name}'")

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
