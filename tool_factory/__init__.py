"""
Tool Factory Base Module
========================
Abstract base class for all brachytherapy planning tools.
Each tool wraps existing functionality into a standardized interface
that can be called by the LLM Agent system.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import logging
import time

logger = logging.getLogger(__name__)


class ToolResult:
    """Standardized result object returned by all tools."""
    
    def __init__(
        self,
        success: bool,
        data: Any = None,
        message: str = "",
        metadata: Optional[Dict] = None,
        error: Optional[str] = None,
        execution_time: float = 0.0,
    ):
        self.success = success
        self.data = data
        self.message = message
        self.metadata = metadata or {}
        self.error = error
        self.execution_time = execution_time
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "message": self.message,
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
