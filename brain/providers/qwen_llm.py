"""
Qwen LLM Provider
==================
Alibaba's Qwen series models.
"""

import os
import time
from typing import List, Dict, Any, Optional

from ..core.base import BaseLLM, LLMResponse


class QwenLLM(BaseLLM):
    """Qwen model provider using OpenAI-compatible API."""

    SUPPORTED_MODELS = {
        "qwen-plus": "Latest flagship model with strong reasoning",
        "qwen-max": "Most capable model for complex tasks",
        "qwen-turbo": "Fast response speed for simple tasks",
        "qwen-flash": "Ultra-fast model with lower latency",
        "qwen-vl-plus": "Vision-language model for images",
        "qwen-vl-max": "Enhanced vision-language model",
        "qwen-long": "Long context model (1M tokens)",
        "qwen-coder-plus": "Specialized for code tasks",
        "qwq-32b": "Thinking model with reasoning capabilities",
        "qvq-72b": "Vision reasoning model",
    }

    def __init__(
        self,
        api_key: str = None,
        model: str = "qwen-plus",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return f"qwen-{self.model}"

    @property
    def default_model(self) -> str:
        return "qwen-plus"

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        start_time = time.time()
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

            response = client.chat.completions.create(**chat_kwargs)

            latency_ms = (time.time() - start_time) * 1000

            return LLMResponse(
                content=response.choices[0].message.content or "",
                # Nested format: {"function": {"name", "arguments"}}.
                # Consumers (AgenticSys.py:4098-4119) handle both flat and nested formats.
                # OpenAI provider uses flat {"id", "name", "arguments"} instead.
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
                latency_ms=latency_ms,
                finish_reason=response.choices[0].finish_reason or "stop",
            )
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")
