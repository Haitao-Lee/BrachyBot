"""
Communication Module
====================
Inter-agent communication infrastructure.
"""

from .protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    Priority, RoutingDecision, ExecutionPlan, ReviewResult, GateResult
)
from .message_bus import MessageBus

__all__ = [
    "AgentRole",
    "AgentMessage",
    "AgentResponse",
    "MessageType",
    "Priority",
    "RoutingDecision",
    "ExecutionPlan",
    "ReviewResult",
    "GateResult",
    "MessageBus",
]
