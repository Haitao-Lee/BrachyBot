"""
MiniMax LLM Provider
====================
MiniMax's models.
"""

import os
from typing import List, Dict, Any, Optional

from ..core.base import BaseLLM, LLMResponse


class MiniMaxLLM(BaseLLM):
    """MiniMax model provider using OpenAI-compatible API."""

    SUPPORTED_MODELS = {
        "minimax-m2.7-20260318": "Latest MiniMax M2.7 (Mar 2026)",
        "MiniMax-text-01": "MiniMax Text 01 (2025)",
        "MiniMax-vl-01": "MiniMax Vision-Language 01",
        "abab6.5s-chat": "ABAB 6.5S fast MoE",
        "abab6.5-chat": "ABAB 6.5 MoE",
        "abab6-chat": "ABAB 6 previous generation",
    }

    def __init__(
        self,
        api_key: str = None,
        group_id: str = None,
        model: str = "minimax-m2.7-20260318",
        base_url: str = "https://api.minimax.chat/v1",
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.group_id = group_id or os.environ.get("MINIMAX_GROUP_ID", "")
        self.model = model
        self.base_url = base_url
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return f"minimax-{self.model}"

    @property
    def default_model(self) -> str:
        return "minimax-m2.7-20260318"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            import openai
            client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

            chat_kwargs = {"model": self.model, "messages": messages}
            if tools:
                chat_kwargs["tools"] = tools
            chat_kwargs.update(self.extra_kwargs)
            chat_kwargs.update(kwargs)

            response = client.chat.completions.create(**chat_kwargs)

            return LLMResponse(
                content=response.choices[0].message.content or "",
                tool_calls=[
                    {"function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in response.choices[0].message.tool_calls or []
                ] if response.choices[0].message.tool_calls else [],
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
                model=self.model,
                latency_ms=0.0,
                finish_reason=response.choices[0].finish_reason or "stop",
            )
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")
