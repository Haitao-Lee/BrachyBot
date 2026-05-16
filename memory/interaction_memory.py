"""
Interaction Memory
================
Stores and retrieves conversation history and tool call patterns.
Forms the foundation for self-evolution.
"""

import os
import json
import time
import copy
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict, Counter


@dataclass
class ToolCall:
    """Record of a single tool invocation."""
    tool_name: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    success: bool
    execution_time: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "ToolCall":
        return cls(**d)


@dataclass
class ConversationTurn:
    """A single conversation turn (user message + agent response)."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    tool_calls: List[ToolCall] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ConversationTurn":
        return cls(
            role=d["role"],
            content=d["content"],
            timestamp=d.get("timestamp", time.time()),
            tool_calls=[ToolCall.from_dict(tc) for tc in d.get("tool_calls", [])],
        )


class InteractionMemory:
    """
    Stores interaction history and extracts patterns.

    Tracks:
    - Conversation turns
    - Tool call sequences
    - Success/failure patterns
    - Session context
    """

    def __init__(self, session_id: str = "default", storage_dir: str = None):
        self.session_id = session_id
        self.storage_dir = storage_dir or os.path.join(
            os.path.dirname(__file__), "data", session_id
        )
        os.makedirs(self.storage_dir, exist_ok=True)

        self.conversation: List[ConversationTurn] = []
        self.tool_call_history: List[ToolCall] = []
        self.session_start = time.time()

        self._load_session()

    def add_turn(self, role: str, content: str, tool_calls: List[ToolCall] = None):
        """Add a conversation turn."""
        turn = ConversationTurn(role=role, content=content, tool_calls=tool_calls or [])
        self.conversation.append(turn)

        for tc in turn.tool_calls:
            self.tool_call_history.append(tc)

        self._save_session()

    def add_tool_call(self, tool_name: str, inputs: Dict, outputs: Dict,
                      success: bool, execution_time: float):
        """Add a tool call record."""
        tc = ToolCall(
            tool_name=tool_name,
            inputs=self._sanitize(inputs),
            outputs=self._sanitize(outputs),
            success=success,
            execution_time=execution_time,
        )
        self.tool_call_history.append(tc)
        self._save_session()

    def get_recent_conversation(self, n: int = 10) -> List[ConversationTurn]:
        """Get the n most recent conversation turns."""
        return self.conversation[-n:]

    def get_tool_sequence(self, n: int = 5) -> List[str]:
        """Get the n most recent tool calls as a sequence of names."""
        return [tc.tool_name for tc in self.tool_call_history[-n:]]

    def get_tool_usage_stats(self) -> Dict[str, int]:
        """Get frequency of each tool usage."""
        return dict(Counter(tc.tool_name for tc in self.tool_call_history))

    def get_success_rate(self, tool_name: str = None) -> float:
        """Get success rate for a tool or all tools."""
        if tool_name:
            calls = [tc for tc in self.tool_call_history if tc.tool_name == tool_name]
        else:
            calls = self.tool_call_history

        if not calls:
            return 0.0
        return sum(1 for tc in calls if tc.success) / len(calls)

    def get_avg_execution_time(self, tool_name: str = None) -> float:
        """Get average execution time for a tool."""
        if tool_name:
            calls = [tc for tc in self.tool_call_history if tc.tool_name == tool_name]
        else:
            calls = self.tool_call_history

        if not calls:
            return 0.0
        return sum(tc.execution_time for tc in calls) / len(calls)

    def extract_tool_patterns(self, min_occurrences: int = 2) -> List[List[str]]:
        """Extract recurring tool call sequences."""
        sequences = []
        for i in range(len(self.tool_call_history) - 1):
            seq = [self.tool_call_history[i].tool_name]
            for j in range(i + 1, len(self.tool_call_history)):
                if self.tool_call_history[j].success:
                    seq.append(self.tool_call_history[j].tool_name)
                else:
                    break
                if len(seq) >= 3:
                    break

            if len(seq) >= 2:
                sequences.append(seq)

        pattern_counts = Counter(tuple(s) for s in sequences)
        return [list(k) for k, v in pattern_counts.items() if v >= min_occurrences]

    def get_session_summary(self) -> Dict:
        """Get a summary of the current session."""
        return {
            "session_id": self.session_id,
            "session_duration_min": (time.time() - self.session_start) / 60,
            "total_turns": len(self.conversation),
            "total_tool_calls": len(self.tool_call_history),
            "tool_usage": self.get_tool_usage_stats(),
            "overall_success_rate": self.get_success_rate(),
        }

    def _sanitize(self, data: Dict) -> Dict:
        """Remove large/unserializable fields."""
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                if isinstance(v, dict):
                    sanitized[k] = {kk: vv for kk, vv in v.items()
                                   if str(type(vv)) not in ['<class numpy', '<class torch', '<class SimpleITK']}
                elif isinstance(v, (list, tuple)):
                    sanitized[k] = str(v)[:200] if len(str(v)) > 200 else v
                else:
                    sanitized[k] = v
        return sanitized

    def _load_session(self):
        """Load session data from disk."""
        session_file = os.path.join(self.storage_dir, "session.json")
        if os.path.exists(session_file):
            try:
                with open(session_file, "r") as f:
                    data = json.load(f)
                self.conversation = [ConversationTurn.from_dict(t) for t in data.get("conversation", [])]
                self.tool_call_history = [ToolCall.from_dict(tc) for tc in data.get("tool_history", [])]
                self.session_start = data.get("session_start", time.time())
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_session(self):
        """Save session data to disk."""
        session_file = os.path.join(self.storage_dir, "session.json")
        data = {
            "session_id": self.session_id,
            "session_start": self.session_start,
            "conversation": [t.to_dict() for t in self.conversation],
            "tool_history": [tc.to_dict() for tc in self.tool_call_history],
        }
        with open(session_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def export(self, path: str = None) -> str:
        """Export session to JSON file."""
        if path is None:
            path = os.path.join(self.storage_dir, f"export_{int(time.time())}.json")

        data = {
            "session_id": self.session_id,
            "export_time": time.time(),
            "session_start": self.session_start,
            "conversation": [t.to_dict() for t in self.conversation],
            "tool_history": [tc.to_dict() for tc in self.tool_call_history],
            "summary": self.get_session_summary(),
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        return path