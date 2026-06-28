"""
Mimo LLM Provider
================
Mimo AI's models.
"""

import os
from typing import List, Dict, Any, Optional

from ..core.base import BaseLLM, LLMResponse


class MimoLLM(BaseLLM):
    """Mimo model provider using OpenAI-compatible API."""

    SUPPORTED_MODELS = {
        "mimo-4": "Latest flagship model",
        "mimo-3": "Previous generation",
        "mimo-pro": "Professional tier model",
        "mimo-flash": "Fast response model",
    }

    def __init__(
        self,
        api_key: str = None,
        model: str = "mimo-4",
        base_url: str = "https://api.mimo.ai/v1",
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("MIMO_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return f"mimo-{self.model}"

    @property
    def default_model(self) -> str:
        return "mimo-4"

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

            chat_kwargs = {}


            chat_kwargs.update(self.extra_kwargs)


            chat_kwargs.update(kwargs)


            chat_kwargs["model"] = self.model


            chat_kwargs["messages"] = messages


            if tools:


                chat_kwargs["tools"] = tools

            start_time = time.time()


            response = client.chat.completions.create(**chat_kwargs)

            return LLMResponse(
                content=response.choices[0].message.content or "",
                # Nested format: {"function": {"name", "arguments"}}.
                    # Consumers handle both flat and nested. See AgenticSys.py:4098-4119.
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
                latency_ms=(time.time() - start_time) * 1000,
                finish_reason=response.choices[0].finish_reason or "stop",
            )
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")
