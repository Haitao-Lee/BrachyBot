"""
OpenAI LLM Provider
====================
OpenAI's GPT series models.
"""

import os
import time
import json
from typing import Dict, List, Optional

from ..core.base import BaseLLM, LLMResponse


class OpenAILLM(BaseLLM):
    """OpenAI GPT models provider."""

    SUPPORTED_MODELS = {
        "gpt-5.5-pro": "Latest flagship Pro (May 2026), 1M context",
        "gpt-5.5": "Latest flagship (May 2026), 1M context",
        "gpt-5.4-pro": "GPT-5.4 Pro (Mar 2026)",
        "gpt-5.4": "GPT-5.4 (Mar 2026)",
        "gpt-5.4-mini": "GPT-5.4 Mini (Mar 2026)",
        "gpt-5.4-nano": "GPT-5.4 Nano (Mar 2026)",
        "gpt-5.3-chat": "GPT-5.3 Chat (Mar 2026)",
        "gpt-5.3-codex": "GPT-5.3 Codex (Feb 2026)",
        "gpt-5.2-pro": "GPT-5.2 Pro (Dec 2025)",
        "gpt-5.2": "GPT-5.2 (Dec 2025)",
        "gpt-5.1-codex": "GPT-5.1 Codex (Nov 2025)",
        "gpt-5.1-chat": "GPT-5.1 Chat (Nov 2025)",
        "gpt-5.1": "GPT-5.1 (Nov 2025)",
        "gpt-5-mini": "GPT-5 Mini (Aug 2025)",
        "gpt-5": "GPT-5 (Aug 2025)",
        "o3": "o3 reasoning model (Apr 2025)",
        "o4-mini": "o4-mini compact reasoning (Apr 2025)",
        "gpt-4.1": "GPT-4.1 (Apr 2025), 1M context",
        "gpt-4.1-mini": "GPT-4.1 Mini (Apr 2025)",
        "gpt-4.1-nano": "GPT-4.1 Nano (Apr 2025)",
        "gpt-4o": "GPT-4o (May 2024), legacy",
        "gpt-4o-mini": "GPT-4o Mini (Jul 2024), legacy",
    }

    def __init__(
        self,
        api_key: str = None,
        model: str = "gpt-5.5",
        base_url: str = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return "gpt-5.5"

    def get_models(self) -> List[str]:
        return list(self.SUPPORTED_MODELS.keys())

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError:
            return LLMResponse(content="Error: openai package not installed", finish_reason="error")

        start_time = time.time()
        api_key = self.api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return LLMResponse(content="Error: No API key provided", finish_reason="error")

        client_kwargs = {"api_key": api_key, "timeout": self.timeout}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        try:
            client = OpenAI(**client_kwargs)
        except Exception as e:
            return LLMResponse(content=f"Error creating client: {str(e)}", finish_reason="error")

        request_kwargs = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.0),
            "max_tokens": kwargs.get("max_tokens", 8192),
        }

        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = "auto"

        try:
            response = client.chat.completions.create(**request_kwargs)
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")

        latency_ms = (time.time() - start_time) * 1000
        choice = response.choices[0]
        content = choice.message.content or ""

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = tc.function.arguments
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": args,
                })

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=response.model,
            latency_ms=latency_ms,
            finish_reason=choice.finish_reason,
        )


class AzureOpenAILLM(OpenAILLM):
    """Azure OpenAI Service provider."""

    def __init__(
        self,
        api_key: str = None,
        model: str = "gpt-4o",
        base_url: str = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        **kwargs
    ):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                        timeout=timeout, max_retries=max_retries, **kwargs)

    @property
    def name(self) -> str:
        return "azure_openai"

    @property
    def default_model(self) -> str:
        return "gpt-4o"

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            from openai import AzureOpenAI
        except ImportError:
            return LLMResponse(content="Error: openai package not installed", finish_reason="error")

        start_time = time.time()
        api_key = self.api_key or os.environ.get("AZURE_OPENAI_KEY", "")
        endpoint = self.base_url or os.environ.get("AZURE_OPENAI_ENDPOINT", "")

        try:
            client = AzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version=kwargs.get("api_version", "2024-02-01"),
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        except Exception as e:
            return LLMResponse(content=f"Error creating client: {str(e)}", finish_reason="error")

        request_kwargs = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.0),
            "max_tokens": kwargs.get("max_tokens", 8192),
        }

        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = "auto"

        try:
            response = client.chat.completions.create(**request_kwargs)
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")

        latency_ms = (time.time() - start_time) * 1000
        choice = response.choices[0]
        content = choice.message.content or ""

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = tc.function.arguments
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": args,
                })

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=response.model,
            latency_ms=latency_ms,
            finish_reason=choice.finish_reason,
        )
