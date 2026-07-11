"""
Base Interfaces
===============
Abstract base classes for the brain system components.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Any, Optional
import json

if TYPE_CHECKING:
    from .tool_registry import ToolRegistry


@dataclass
class LLMResponse:
    """Standardized response from an LLM."""
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    model: str = ""
    latency_ms: float = 0.0
    finish_reason: str = "stop"

    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class BaseLLM(ABC):
    """Abstract base for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        pass

    @abstractmethod
    def _chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None, **kwargs) -> LLMResponse:
        pass

    def chat(self, prompt: str, system: str = "", tools: List[Dict] = None, **kwargs) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self._chat(messages, tools=tools, **kwargs)

    def chat_messages(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        return self._chat(messages, tools=tools, **kwargs)


class BaseDecider(ABC):
    """
    Abstract base for role-specific LLM decision modules.

    Each decider is specialized for a specific decision task:
    - PlannerDecider: Generate tool-chain execution plans
    - ClinicalDecider: Clinical indicator assessment and weighting
    - QualityDecider: Plan quality scoring
    """

    def __init__(self, llm: BaseLLM):
        self.llm = llm

    @abstractmethod
    def decide(self, task: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Make a decision based on task and context."""
        pass

    def _build_messages(self, system: str, user_content: Any) -> List[Dict]:
        """Build message list for LLM."""
        if isinstance(user_content, str):
            return [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
        return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user_content) if not isinstance(user_content, list) else user_content}]


class BasePlanner(ABC):
    """
    Abstract base for tool-chain planners.

    Generates structured execution plans from natural language tasks.
    """

    def __init__(self, llm: BaseLLM, tool_registry: "ToolRegistry"):
        self.llm = llm
        self.tool_registry = tool_registry

    @abstractmethod
    def plan(self, task: str, rag_text: str = "", **kwargs) -> List[Dict[str, Any]]:
        """
        Generate an execution plan for the given task.

        Returns a list of steps, each containing:
        - id: step ID (1-based)
        - tool: list of tool IDs to call
        - action: description of the action
        - action_type: "quantitative" or "qualitative"
        - input_type: list of input step IDs (0 for raw input)
        - output_type: "intermediate result" or "final indicator"
        - output_path: path to save output
        """
        pass


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    id: int
    tool: List[int]
    action: str
    action_type: str  # "quantitative" or "qualitative"
    input_type: List[int]
    output_type: str  # "intermediate result" or "final indicator"
    output_path: str = "result.json"

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tool": self.tool,
            "action": self.action,
            "action_type": self.action_type,
            "input_type": self.input_type,
            "output_type": self.output_type,
            "output_path": self.output_path,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "PlanStep":
        return cls(
            id=int(d["id"]),
            tool=[int(t) for t in d.get("tool", [])],
            action=str(d.get("action", "")),
            action_type=str(d.get("action_type", "quantitative")),
            input_type=[int(i) for i in d.get("input_type", [])],
            output_type=str(d.get("output_type", "intermediate result")),
            output_path=str(d.get("output_path", "result.json")),
        )
