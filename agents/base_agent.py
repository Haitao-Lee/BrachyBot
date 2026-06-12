"""
Base Agent for Multi-Agent System
==================================
Provides the abstract base class for all specialized agents.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType, Priority
)

logger = logging.getLogger(__name__)

# Load prompts from config
try:
    from config.prompts.multi_agent import get_prompt
    _PROMPTS_AVAILABLE = True
except ImportError:
    _PROMPTS_AVAILABLE = False
    logger.warning("Multi-agent prompts not available")


class BaseAgent(ABC):
    """
    Abstract base class for all agents in the multi-agent system.

    Each agent has:
    - A specific role (AgentRole)
    - A process method to handle messages
    - Message history for context
    - Optional LLM callback for AI capabilities
    """

    def __init__(self, role: AgentRole, llm_callback: Optional[Callable] = None):
        self.role = role
        self.llm_callback = llm_callback
        self.message_history: List[AgentMessage] = []
        self._processed_count = 0
        self._error_count = 0
        logger.info(f"Initialized {self.__class__.__name__} (role={role.value})")

    @abstractmethod
    async def process(self, message: AgentMessage) -> AgentResponse:
        """
        Process an incoming message and return a response.

        Args:
            message: The incoming message to process

        Returns:
            AgentResponse with the result
        """
        pass

    async def handle_message(self, message: AgentMessage) -> AgentResponse:
        """
        Handle an incoming message with error handling and logging.

        Args:
            message: The incoming message

        Returns:
            AgentResponse
        """
        self.message_history.append(message)
        self._processed_count += 1

        try:
            response = await self.process(message)
            logger.debug(
                f"{self.role.value} processed message {message.message_id}: "
                f"success={response.success}, confidence={response.confidence:.2f}"
            )
            return response
        except Exception as e:
            self._error_count += 1
            logger.error(f"{self.role.value} failed to process message: {e}")
            return AgentResponse(
                agent_role=self.role,
                success=False,
                result=None,
                confidence=0.0,
                reasoning=f"Error: {str(e)}",
                warnings=[str(e)]
            )

    def create_message(self, receiver: AgentRole, content: Any,
                      message_type: MessageType = MessageType.REQUEST,
                      priority: Priority = Priority.NORMAL,
                      metadata: Dict = None) -> AgentMessage:
        """
        Create a new message from this agent.

        Args:
            receiver: Target agent role
            content: Message content
            message_type: Type of message
            priority: Message priority
            metadata: Additional metadata

        Returns:
            AgentMessage
        """
        return AgentMessage(
            sender=self.role,
            receiver=receiver,
            message_type=message_type,
            content=content,
            priority=priority,
            metadata=metadata or {}
        )

    def get_stats(self) -> Dict:
        """Get agent statistics."""
        return {
            "role": self.role.value,
            "processed_count": self._processed_count,
            "error_count": self._error_count,
            "history_size": len(self.message_history),
            "success_rate": (
                (self._processed_count - self._error_count) / self._processed_count
                if self._processed_count > 0 else 0.0
            ),
        }

    def clear_history(self):
        """Clear message history."""
        self.message_history.clear()
        self._processed_count = 0
        self._error_count = 0


class LLMCapableAgent(BaseAgent):
    """
    Agent with LLM capabilities for natural language understanding and generation.
    """

    def __init__(self, role: AgentRole, llm_callback: Optional[Callable] = None):
        super().__init__(role, llm_callback)
        self._llm_call_count = 0
        self._system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        """Load system prompt from config/prompts/multi_agent/."""
        if _PROMPTS_AVAILABLE:
            # Map agent role to prompt name
            prompt_map = {
                AgentRole.ROUTER: "router",
                AgentRole.PLAN_REVIEWER: "plan_reviewer",
                AgentRole.FACT_CHECKER: "fact_checker",
                AgentRole.SAFETY_GUARDIAN: "safety_guardian",
            }
            prompt_name = prompt_map.get(self.role)
            if prompt_name:
                return get_prompt(prompt_name)
        return ""

    async def call_llm(self, prompt: str, system_prompt: str = None,
                      temperature: float = 0.3) -> str:
        """
        Call the LLM with a prompt.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt (overrides loaded prompt)
            temperature: LLM temperature

        Returns:
            LLM response text
        """
        if not self.llm_callback:
            raise RuntimeError(f"LLM callback not set for {self.role.value}")

        self._llm_call_count += 1

        # Use provided system_prompt, or fall back to loaded prompt
        effective_system_prompt = system_prompt or self._system_prompt

        if effective_system_prompt:
            full_prompt = f"System: {effective_system_prompt}\n\nUser: {prompt}"
        else:
            full_prompt = prompt

        try:
            response = self.llm_callback(full_prompt)
            return response
        except Exception as e:
            logger.error(f"LLM call failed for {self.role.value}: {e}")
            raise

    def get_stats(self) -> Dict:
        """Get agent statistics including LLM usage."""
        stats = super().get_stats()
        stats["llm_calls"] = self._llm_call_count
        return stats
