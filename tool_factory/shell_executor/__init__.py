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

# Blocked commands for safety
BLOCKED_COMMANDS = [
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){", "fork",
    "chmod -R 777 /", "wget", "curl", "ssh", "scp", "ftp",
    "shutdown", "reboot", "halt", "poweroff", "init 0", "init 6",
]

# Allowed command patterns
ALLOWED_PATTERNS = [
    "python", "pip", "conda", "venv", "virtualenv",
    "ls", "cat", "head", "tail", "grep", "find", "echo",
    "pwd", "whoami", "date", "uname",
    "mkdir", "touch", "cp", "mv",
    "git", "svn",
]


class ShellExecutorTool(BaseTool):
    """Execute shell commands in a controlled environment."""

    name = "shell_executor"
    description = """Execute shell commands for environment setup and system operations.
Useful for: installing packages, creating virtual environments, managing files, running scripts.
Returns stdout, stderr, and return code."""

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
            # Run command
            result = subprocess.run(
                command,
                shell=True,
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
