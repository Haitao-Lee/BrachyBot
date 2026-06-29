"""
Tool Factory Base Module
========================
Abstract base class for all brachytherapy planning tools.
Each tool wraps existing functionality into a standardized interface
that can be called by the LLM Agent system.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Dict, Optional
import logging
import sys
import time

logger = logging.getLogger(__name__)


class ToolResult:
    """Standardized result object returned by all tools.

    Fields:
        success: Whether the tool executed successfully
        data: Raw data (for programmatic use)
        message: Machine-readable summary (for LLM context, logging)
        display: Human-readable markdown (for user-facing response)
        metadata: Additional structured data
        error: Error message if failed
        execution_time: Time taken in seconds
    """

    def __init__(
        self,
        success: bool,
        data: Any = None,
        message: str = "",
        display: str = "",
        metadata: Optional[Dict] = None,
        error: Optional[str] = None,
        execution_time: float = 0.0,
    ):
        self.success = success
        self.data = data
        self.message = message
        self.display = display
        self.metadata = metadata or {}
        self.error = error
        self.execution_time = execution_time

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "message": self.message,
            "display": self.display,
            "metadata": self.metadata,
            "error": self.error,
            "execution_time": self.execution_time,
        }

    def __repr__(self):
        status = "SUCCESS" if self.success else "FAILED"
        return f"ToolResult({status}: {self.message})"


class BaseTool(ABC):
    """
    Abstract base class for all brachytherapy planning tools.
    
    Subclasses must implement:
        - name: Unique tool identifier
        - description: Human-readable description for LLM understanding
        - input_schema: Expected input parameters
        - output_schema: Expected output format
        - execute(): Core tool logic
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this tool."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM understanding."""
        pass
    
    @property
    def input_schema(self) -> Dict:
        """JSON Schema describing expected input parameters."""
        return {}
    
    @property
    def output_schema(self) -> Dict:
        """JSON Schema describing the output format."""
        return {}
    
    def validate_input(self, **kwargs) -> bool:
        """Validate input parameters against the input schema."""
        required = self.input_schema.get("required", [])
        for param in required:
            if param not in kwargs:
                raise ValueError(f"Missing required parameter: {param}")
        return True

    @contextmanager
    def _operation_tracker(self):
        """Best-effort hook for web/server.py shutdown protection."""
        ctx = None
        entered = False
        try:
            import builtins
            tracker = getattr(builtins, "track_operation", None)
            if callable(tracker):
                ctx = tracker(self.name)
                ctx.__enter__()
                entered = True
        except Exception as e:
            logger.debug(f"Operation tracking unavailable for {self.name}: {e}")
            ctx = None

        try:
            yield
        except Exception:
            if entered and ctx is not None:
                try:
                    ctx.__exit__(*sys.exc_info())
                except Exception as e:
                    logger.debug(f"Operation tracking exit failed for {self.name}: {e}")
            raise
        else:
            if entered and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception as e:
                    logger.debug(f"Operation tracking exit failed for {self.name}: {e}")
    
    def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with validation and timing.
        
        Args:
            **kwargs: Tool-specific parameters
            
        Returns:
            ToolResult with execution outcome
        """
        start_time = time.time()
        try:
            with self._operation_tracker():
                self.validate_input(**kwargs)
                logger.info(f"Executing tool: {self.name}")
                result = self._execute(**kwargs)
            result.execution_time = time.time() - start_time
            logger.info(f"Tool {self.name} completed in {result.execution_time:.2f}s")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Tool {self.name} failed: {str(e)}")
            return ToolResult(
                success=False,
                error=str(e),
                message=f"Tool execution failed: {str(e)}",
                execution_time=execution_time,
            )
    
    @abstractmethod
    def _execute(self, **kwargs) -> ToolResult:
        """Core tool implementation to be overridden by subclasses."""
        pass
    
    def __repr__(self):
        return f"Tool({self.name}: {self.description})"


class SegmentationTool(BaseTool):
    """Base class for segmentation tools. Provides standard display format."""

    def _make_segmentation_display(self, result: ToolResult, title: str, **metrics) -> None:
        """Set result.display with standard segmentation table format.

        Args:
            result: The ToolResult to set display on
            title: Display title (e.g., "CTV Segmentation", "OAR Segmentation")
            **metrics: Key-value pairs for the metrics table
        """
        lines = [f"## 🎯 {title}"]
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        for k, v in metrics.items():
            if isinstance(v, float):
                lines.append(f"| {k} | {v:.1f} |")
            elif isinstance(v, int):
                lines.append(f"| {k} | {v:,} |")
            else:
                lines.append(f"| {k} | {v} |")
        lines.append("")
        lines.append("✅ Results displayed in the Viewer panel.")
        result.display = "\n".join(lines)


class AnalysisTool(BaseTool):
    """Base class for analysis tools. Provides standard display format."""

    def _make_analysis_display(self, result: ToolResult, title: str, params: dict) -> None:
        """Set result.display with standard analysis table format."""
        lines = [f"## 🔍 {title}"]
        lines.append("")
        lines.append("| Parameter | Value |")
        lines.append("|-----------|-------|")
        for k, v in params.items():
            lines.append(f"| {k} | {v} |")
        result.display = "\n".join(lines)
