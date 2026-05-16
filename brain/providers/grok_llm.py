"""
Grok LLM Provider
=================
xAI's Grok models.
"""

import os
from typing import List, Dict, Any, Optional

from ..core.base import BaseLLM, LLMResponse


class GrokLLM(BaseLLM):
    """Grok model provider using xAI API."""

    SUPPORTED_MODELS = {
        "grok-3": "Latest flagship model (2025)",
        "grok-3-beta": "Beta version of latest flagship",
        "grok-2-1212": "December 2024 model",
        "grok-2-0805": "August 2024 model",
        "grok-2": "Latest stable Grok-2",
        "grok-1": "Original Grok-1 model",
        "grok-1.5-vision": "Vision capability",
        "grok-1.5": "Enhanced original model",
    }

    def __init__(
        self,
        api_key: str = None,
        model: str = "grok-3",
        base_url: str = "https://api.x.ai/v1",
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return f"grok-{self.model}"

    @property
    def default_model(self) -> str:
        return "grok-3"

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

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
