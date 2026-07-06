"""
Shell Executor Tool
===================
Allows the agent to run shell commands for environment setup,
package installation, and system operations.
"""

import os
import sys
import json
import logging
import subprocess
import shlex
from typing import Dict, Any, Optional, List
from pathlib import Path

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

TRUE_VALUES = {"1", "true", "yes", "on"}


def _execution_enabled() -> bool:
    """Read the trusted-local toggle at execution time, not import time."""
    return os.environ.get("BRACHYBOT_ENABLE_SHELL_EXECUTOR", "").lower() in TRUE_VALUES

# Blocked commands for safety
BLOCKED_COMMANDS = [
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){", "fork",
    "chmod -R 777 /", "ssh", "scp", "ftp",
    "shutdown", "reboot", "halt", "poweroff", "init 0", "init 6",
]

# Allowed command patterns
ALLOWED_PATTERNS = [
    "python", "pip", "conda", "venv", "virtualenv",
    "ls", "cat", "head", "tail", "grep", "find", "echo",
    "pwd", "whoami", "date", "uname",
    "mkdir", "touch", "cp", "mv",
    "git", "svn",
    "curl", "wget",
]


class ShellExecutorTool(BaseTool):
    """Execute shell commands only in explicitly trusted local deployments."""

    name = "shell_executor"
    description = """Execute shell commands only when BRACHYBOT_ENABLE_SHELL_EXECUTOR=1.
Use only in trusted local environments for setup, diagnostics, and maintenance.
Commands are executed without shell expansion and must start with an allowed executable."""

    input_schema = {
        "command": {
            "type": "string",
            "description": "Shell command to execute"
        },
        "working_dir": {
            "type": "string",
            "description": "Working directory for the command (optional)"
        },
        "timeout": {
            "type": "integer",
            "description": "Timeout in seconds (default: 60)"
        },
        "env_vars": {
            "type": "object",
            "description": "Environment variables to set (optional)"
        },
    }
    output_schema = {
        "success": {"type": "boolean"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "returncode": {"type": "integer"},
    }

    def _validate_command(self, command: str) -> tuple:
        """Validate command is safe. Returns (is_safe, reason)."""
        command_lower = command.lower().strip()
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return False, f"Could not parse command: {exc}"

        if not parts:
            return False, "Empty command"

        executable = Path(parts[0]).name.lower()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        allowed = {p.lower() for p in ALLOWED_PATTERNS}
        if executable not in allowed:
            return False, f"Executable '{parts[0]}' is not allowlisted"

        shell_operators = {";", "&&", "||", "|", ">", "<", "2>", "&>"}
        if any(token in shell_operators or token.startswith("$(") or "`" in token for token in parts):
            return False, "Shell operators and command chaining are not allowed"

        # Check blocked commands
        for blocked in BLOCKED_COMMANDS:
            if blocked.lower() in command_lower:
                return False, f"Blocked command pattern: {blocked}"

        # Check for dangerous operations
        dangerous_patterns = [
            "rm -rf /", "rm -rf /*", "mkfs", "dd if=",
            "> /dev/sda", "chmod 777 /", ":(){",
        ]
        for pattern in dangerous_patterns:
            if pattern in command_lower:
                return False, f"Dangerous pattern detected: {pattern}"

        return True, ""

    def _execute(self, **kwargs) -> ToolResult:
        command = kwargs.get("command", "")
        working_dir = kwargs.get("working_dir", None)
        timeout = kwargs.get("timeout", 60)
        env_vars = kwargs.get("env_vars", None)

        if not command:
            return ToolResult(
                success=False,
                error="No command provided",
                message="shell_executor requires a 'command' parameter"
            )

        if not _execution_enabled():
            return ToolResult(
                success=False,
                error="shell_executor is disabled",
                message=(
                    "Shell execution is disabled by default. Set "
                    "BRACHYBOT_ENABLE_SHELL_EXECUTOR=1 only in a trusted local environment."
                ),
            )

        # Validate command
        is_safe, reason = self._validate_command(command)
        if not is_safe:
            return ToolResult(
                success=False,
                error=f"Command blocked: {reason}",
                message=f"Command blocked for safety: {reason}"
            )

        # Prepare environment
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        # Determine working directory
        cwd = working_dir if working_dir and os.path.isdir(working_dir) else os.getcwd()

        try:
            args = shlex.split(command)
            # Run command
            result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env,
            )

            # Truncate long outputs
            max_len = 5000
            stdout = result.stdout[:max_len] if len(result.stdout) > max_len else result.stdout
            stderr = result.stderr[:max_len] if len(result.stderr) > max_len else result.stderr

            if len(result.stdout) > max_len:
                stdout += "\n... (output truncated)"
            if len(result.stderr) > max_len:
                stderr += "\n... (output truncated)"

            return ToolResult(
                success=result.returncode == 0,
                data={
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": result.returncode,
                    "command": command,
                    "working_dir": cwd,
                },
                message=f"Command executed with return code {result.returncode}" +
                       (" successfully" if result.returncode == 0 else " with errors"),
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout} seconds",
                message=f"Command timed out: {command}"
            )
        except Exception as e:
            logger.error(f"Shell command failed: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Failed to execute command: {command}"
            )
