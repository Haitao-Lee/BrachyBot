"""
GLM LLM Provider
================
Zhipu AI's ChatGLM series models.
"""

import os
from typing import List, Dict, Any, Optional

from ..core.base import BaseLLM, LLMResponse


class GLMLLM(BaseLLM):
    """GLM model provider using OpenAI-compatible API."""

    SUPPORTED_MODELS = {
        "glm-4-flash": "Latest fast model (2025)",
        "glm-4-plus": "Enhanced capability model",
        "glm-4": "Standard flagship model",
        "glm-4v-flash": "Vision model fast version",
        "glm-4v-plus": "Vision model enhanced",
        "glm-3-turbo": "Fast turbo model",
        "chatglm3-6b": "Open source 6B model",
        "glm-z1-9b": "Reasoning model 9B",
        "glm-z1-32b": "Reasoning model 32B",
    }

    def __init__(
        self,
        api_key: str = None,
        model: str = "glm-4-flash",
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("ZHIPU_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return f"glm-{self.model}"

    @property
    def default_model(self) -> str:
        return "glm-4-flash"

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
