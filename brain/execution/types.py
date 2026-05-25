"""
Shared Execution Types
======================
Common enums and dataclasses used by both PlanExecutor and CaseExecutor.
Eliminates duplication between plan_executor.py and case_executor.py.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ExecutionStatus(Enum):
    """Standard execution status for all plan/step results."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class BaseStepResult:
    """Base step result shared across executors."""
    status: ExecutionStatus
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
