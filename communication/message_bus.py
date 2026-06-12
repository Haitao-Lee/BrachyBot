"""
Message Bus for Multi-Agent Communication
==========================================
Centralized message routing and history tracking.
Inspired by event-driven architectures in OpenCode and CrewAI.
"""

import asyncio
import logging
from typing import Dict, List, Callable, Optional
from collections import defaultdict
from .protocol import AgentMessage, AgentRole, MessageType

logger = logging.getLogger(__name__)


class MessageBus:
    """
    Centralized message bus for inter-agent communication.

    Features:
    - Publish/subscribe pattern
    - Message history tracking
    - Async message handling
    - Priority-based routing
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[AgentMessage] = []
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._message_count = 0

    def subscribe(self, message_type_or_role: str, handler: Callable):
        """
        Subscribe to messages of a specific type or from a specific role.

        Args:
            message_type_or_role: MessageType value or AgentRole value
            handler: Async callable to handle the message
        """
        self._subscribers[message_type_or_role].append(handler)
        logger.debug(f"Subscribed to '{message_type_or_role}': {handler.__name__}")

    def unsubscribe(self, message_type_or_role: str, handler: Callable):
        """Unsubscribe a handler from a message type."""
        if handler in self._subscribers[message_type_or_role]:
            self._subscribers[message_type_or_role].remove(handler)

    async def publish(self, message: AgentMessage) -> List[any]:
        """
        Publish a message to all subscribers.

        Args:
            message: The message to publish

        Returns:
            List of handler results
        """
        self._history.append(message)
        self._message_count += 1

        results = []

        # Notify subscribers of message type
        for handler in self._subscribers.get(message.message_type.value, []):
            try:
                result = await handler(message)
                results.append(result)
            except Exception as e:
                logger.error(f"Handler {handler.__name__} failed: {e}")

        # Notify subscribers of receiver role
        for handler in self._subscribers.get(message.receiver.value, []):
            try:
                result = await handler(message)
                results.append(result)
            except Exception as e:
                logger.error(f"Handler {handler.__name__} failed: {e}")

        # Notify wildcard subscribers
        for handler in self._subscribers.get("*", []):
            try:
                result = await handler(message)
                results.append(result)
            except Exception as e:
                logger.error(f"Handler {handler.__name__} failed: {e}")

        return results

    async def request(self, message: AgentMessage, timeout: float = 30.0) -> Optional[AgentMessage]:
        """
        Send a request and wait for a response.

        Args:
            message: The request message
            timeout: Timeout in seconds

        Returns:
            Response message or None if timeout
        """
        # Create a future for the response
        future = asyncio.get_event_loop().create_future()
        self._pending_responses[message.message_id] = future

        # Publish the request
        await self.publish(message)

        try:
            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.warning(f"Request {message.message_id} timed out after {timeout}s")
            return None
        finally:
            self._pending_responses.pop(message.message_id, None)

    async def respond(self, original_message: AgentMessage, response_content: any,
                     agent_role: AgentRole, success: bool = True):
        """
        Send a response to a request.

        Args:
            original_message: The original request message
            response_content: The response content
            agent_role: The role of the responding agent
            success: Whether the request was successful
        """
        response = AgentMessage(
            sender=agent_role,
            receiver=original_message.sender,
            message_type=MessageType.RESPONSE,
            content=response_content,
            parent_id=original_message.message_id,
            metadata={"success": success}
        )

        # Resolve the pending future
        future = self._pending_responses.get(original_message.message_id)
        if future and not future.done():
            future.set_result(response)

        # Also publish the response
        await self.publish(response)

    def get_history(self, agent_role: Optional[AgentRole] = None,
                   message_type: Optional[MessageType] = None,
                   limit: int = 100) -> List[AgentMessage]:
        """
        Get message history with optional filters.

        Args:
            agent_role: Filter by agent role (sender or receiver)
            message_type: Filter by message type
            limit: Maximum number of messages to return

        Returns:
            List of messages matching the filters
        """
        messages = self._history

        if agent_role:
            messages = [m for m in messages
                       if m.sender == agent_role or m.receiver == agent_role]

        if message_type:
            messages = [m for m in messages if m.message_type == message_type]

        return messages[-limit:]

    def get_stats(self) -> Dict:
        """Get message bus statistics."""
        return {
            "total_messages": self._message_count,
            "history_size": len(self._history),
            "pending_responses": len(self._pending_responses),
            "subscribers": {k: len(v) for k, v in self._subscribers.items()},
        }

    def clear_history(self):
        """Clear message history."""
        self._history.clear()
        self._message_count = 0
