"""
Integration Module
==================
Bridges brain system with tool_factory tools.
"""

from .integration import BrainToolBridge, get_bridge, initialize_brain_integration
from .enhanced_agent import EnhancedAgentIntegration

__all__ = [
    "BrainToolBridge",
    "get_bridge",
    "initialize_brain_integration",
    "EnhancedAgentIntegration",
]