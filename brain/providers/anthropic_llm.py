"""
Anthropic Claude LLM Provider
=============================
Anthropic's Claude series models.
"""

import os
import time
import json
from typing import Dict, List

from ..core.base import BaseLLM, LLMResponse


class AnthropicLLM(BaseLLM):
    """Anthropic Claude models provider."""

    SUPPORTED_MODELS = {
        "claude-opus-4-20250514": "Claude Opus 4 (May 2025)",
        "claude-sonnet-4-20250514": "Claude Sonnet 4 (May 2025)",
        "claude-4.7-opus-20260416": "Claude Opus 4.7 (Apr 2026)",
        "claude-4.6-sonnet-20260217": "Claude Sonnet 4.6 (Feb 2026)",
        "claude-3.5-sonnet-latest": "Claude 3.5 Sonnet",
        "claude-3-opus": "Claude 3 Opus",
        "claude-3-sonnet": "Claude 3 Sonnet",
        "claude-3-haiku": "Claude 3 Haiku fast",
    }

    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-sonnet-4-20250514",
        base_url: str = None,
        timeout: float = 120.0,
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return "claude-sonnet-4-20250514"

    def get_models(self) -> List[str]:
        return list(self.SUPPORTED_MODELS.keys())

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            from anthropic import Anthropic
        except ImportError:
            return LLMResponse(content="Error: anthropic package not installed", finish_reason="error")

        start_time = time.time()
        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return LLMResponse(content="Error: No API key provided", finish_reason="error")

        client_kwargs = {"api_key": api_key, "timeout": self.timeout}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        try:
            client = Anthropic(**client_kwargs)
        except Exception as e:
            return LLMResponse(content=f"Error creating client: {str(e)}", finish_reason="error")

        system_msg = ""
        filtered_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                filtered_messages.append({"role": msg["role"], "content": msg["content"]})

        request_kwargs = {
            "model": kwargs.get("model", self.model),
            "messages": filtered_messages,
            "temperature": kwargs.get("temperature", 0.0),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if system_msg:
            request_kwargs["system"] = system_msg

        if tools:
            request_kwargs["tools"] = [self._convert_tool(t) for t in tools]

        try:
            response = client.messages.create(**request_kwargs)
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")

        latency_ms = (time.time() - start_time) * 1000
        content = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })

        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=response.model,
            latency_ms=latency_ms,
            finish_reason=response.stop_reason,
        )

    def _convert_tool(self, tool: Dict) -> Dict:
        """Convert OpenAI-style tool to Anthropic format."""
        return {
            "name": tool["function"]["name"],
            "description": tool["function"].get("description", ""),
            "input_schema": tool["function"]["parameters"],
        }
