"""
Groq LLM Provider
================
Groq's LLaMA models via Groq API.
"""

import os
import time
from typing import List, Dict, Any, Optional

from ..core.base import BaseLLM, LLMResponse


class GroqLLM(BaseLLM):
    """Groq LLaMA provider using OpenAI-compatible API."""

    SUPPORTED_MODELS = {
        "llama-3.3-70b-versatile": "Latest flagship LLaMA (Dec 2024)",
        "llama-3.1-70b-versatile": "70B versatile model",
        "llama-3.1-8b-instant": "Fast 8B model",
        "llama3-70b": "Original 70B model",
        "llama3-8b": "Original 8B model",
        "mixtral-8x7b-32768": "Mixture of experts model",
        "gemma2-9b-it": "Google's Gemma 2 9B instruction-tuned",
    }

    def __init__(
        self,
        api_key: str = None,
        model: str = "llama-3.3-70b-versatile",
        base_url: str = "https://api.groq.com/openai/v1",
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return f"groq-{self.model}"

    @property
    def default_model(self) -> str:
        return "llama-3.3-70b-versatile"

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
