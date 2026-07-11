"""
OpenRouter LLM Provider
======================
Unified API access to all models via OpenRouter.
Supports the latest models from OpenRouter rankings.
"""

import os
import logging
import time
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

from ..core.base import BaseLLM, LLMResponse


class OpenRouterLLM(BaseLLM):
    """
    OpenRouter provider for unified LLM access.

    OpenRouter provides a single API endpoint to access models from:
    - Anthropic (Claude)
    - OpenAI (GPT-4, GPT-5)
    - Google (Gemini)
    - DeepSeek
    - Meta (Llama)
    - And 100+ other providers

    Top models on OpenRouter:
    1. Tencent hy3-preview
    2. Claude Opus 4.7
    3. Claude Sonnet 4.6
    4. Kimi K2.6
    5. DeepSeek V4 Flash
    6. Gemini 3 Flash
    7. DeepSeek V3.2
    8. DeepSeek V4 Pro
    9. MiniMax M2.7
    10. And many more
    """

    SUPPORTED_MODELS = {
        # Top OpenRouter models
        "hy3-preview": {"name": "Tencent hy3-preview", "provider": "openrouter"},
        "claude-opus-4.7": {"name": "Claude Opus 4.7", "provider": "anthropic"},
        "claude-sonnet-4.6": {"name": "Claude Sonnet 4.6", "provider": "anthropic"},
        "kimi-k2.6": {"name": "Kimi K2.6", "provider": "moonshot"},
        "deepseek-v4-flash": {"name": "DeepSeek V4 Flash", "provider": "deepseek"},
        "gemini-3-flash": {"name": "Gemini 3 Flash", "provider": "google"},
        "deepseek-v3.2": {"name": "DeepSeek V3.2", "provider": "deepseek"},
        "deepseek-v4-pro": {"name": "DeepSeek V4 Pro", "provider": "deepseek"},
        "minimax-m2.7": {"name": "MiniMax M2.7", "provider": "minimax"},
        # GPT-5 series
        "gpt-5.5-pro": {"name": "GPT-5.5 Pro", "provider": "openai"},
        "gpt-5.5": {"name": "GPT-5.5", "provider": "openai"},
        "gpt-5.4-pro": {"name": "GPT-5.4 Pro", "provider": "openai"},
        "gpt-5.4": {"name": "GPT-5.4", "provider": "openai"},
        "gpt-5.4-mini": {"name": "GPT-5.4 Mini", "provider": "openai"},
        "gpt-5.3-pro": {"name": "GPT-5.3 Pro", "provider": "openai"},
        "gpt-5.3": {"name": "GPT-5.3", "provider": "openai"},
        "gpt-5.3-mini": {"name": "GPT-5.3 Mini", "provider": "openai"},
        "gpt-5.2": {"name": "GPT-5.2", "provider": "openai"},
        "gpt-5.1": {"name": "GPT-5.1", "provider": "openai"},
        "gpt-5": {"name": "GPT-5", "provider": "openai"},
        "gpt-5-mini": {"name": "GPT-5 Mini", "provider": "openai"},
        # o-series reasoning models
        "o3": {"name": "OpenAI o3", "provider": "openai"},
        "o4-mini": {"name": "OpenAI o4-mini", "provider": "openai"},
        # GPT-4.1 series
        "gpt-4.1": {"name": "GPT-4.1", "provider": "openai"},
        "gpt-4.1-mini": {"name": "GPT-4.1 Mini", "provider": "openai"},
        "gpt-4.1-nano": {"name": "GPT-4.1 Nano", "provider": "openai"},
        # Claude models
        "claude-opus-4": {"name": "Claude Opus 4", "provider": "anthropic"},
        "claude-sonnet-4": {"name": "Claude Sonnet 4", "provider": "anthropic"},
        "claude-3-opus": {"name": "Claude 3 Opus", "provider": "anthropic"},
        "claude-3-sonnet": {"name": "Claude 3 Sonnet", "provider": "anthropic"},
        # Gemini models
        "gemini-2.0-flash": {"name": "Gemini 2.0 Flash", "provider": "google"},
        "gemini-2.5-pro": {"name": "Gemini 2.5 Pro", "provider": "google"},
        "gemini-3-pro": {"name": "Gemini 3 Pro", "provider": "google"},
        # Llama models
        "llama-4-405b": {"name": "Llama 4 405B", "provider": "meta"},
        "llama-4-70b": {"name": "Llama 4 70B", "provider": "meta"},
        "llama-3.3-70b": {"name": "Llama 3.3 70B", "provider": "meta"},
        "llama-3.1-405b": {"name": "Llama 3.1 405B", "provider": "meta"},
        # Other top models
        "qwq-32b": {"name": "Qwen QwQ 32B", "provider": "qwen"},
        "glm-z1-32b": {"name": "GLM Z1 32B", "provider": "zhipu"},
        "grok-3": {"name": "Grok 3", "provider": "xai"},
        "grok-4.3": {"name": "Grok 4.3", "provider": "xai"},
    }

    DEFAULT_MODEL = "hy3-preview"
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        base_url: str = None,
        max_retries: int = 3,
        timeout: int = 120,
    ):
        if not HAS_OPENAI:
            raise ImportError("OpenAI package required for OpenRouter. Install: pip install openai")

        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ValueError("OpenRouter API key required. Set OPENROUTER_API_KEY environment variable or pass api_key.")

        self.model = model or os.environ.get("OPENROUTER_MODEL", self.DEFAULT_MODEL)
        self.base_url = base_url or self.BASE_URL
        self.max_retries = max_retries
        self.timeout = timeout

        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=max_retries,
            timeout=timeout,
        )

        logger.info(f"Initialized OpenRouter LLM with model: {self.model}")

    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def default_model(self) -> str:
        return self.DEFAULT_MODEL

    def chat(
        self,
        prompt: str,
        system: str = "",
        tools: List[Dict] = None,
        **kwargs
    ) -> LLMResponse:
        """Send chat request via OpenRouter."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        return self._chat(messages, tools, **kwargs)

    def chat_messages(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
        **kwargs
    ) -> LLMResponse:
        """Send chat request with message history via OpenRouter."""
        return self._chat(messages, tools, **kwargs)

    def chat_messages_stream(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
        **kwargs
    ):
        """Streaming version that yields text chunks as they arrive."""
        import time
        start_time = time.time()
        try:
            chat_kwargs = {
                "model": self.model,
                "messages": messages,
                "stream": True,
            }

            if tools:
                chat_kwargs["tools"] = self._format_tools(tools)
                chat_kwargs["tool_choice"] = "auto"

            extra_headers = kwargs.pop("extra_headers", None)
            if extra_headers:
                chat_kwargs["extra_headers"] = extra_headers

            response = self.client.chat.completions.create(**chat_kwargs, **kwargs)

            full_content = ""
            tool_calls = []
            finish_reason = None
            usage = {}

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta

                    # Handle tool calls in streaming mode
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            if tc.index >= len(tool_calls):
                                tool_calls.append({
                                    "id": tc.id or "",
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name or "",
                                        "arguments": tc.function.arguments or "",
                                    }
                                })
                            else:
                                if tc.function.name:
                                    tool_calls[tc.index]["function"]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls[tc.index]["function"]["arguments"] += tc.function.arguments

                    # Handle content streaming
                    if delta.content:
                        full_content += delta.content
                        yield delta.content

                if chunk.choices and chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason

                if chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }

            latency_ms = (time.time() - start_time) * 1000

            # Yield final metadata
            yield {
                "type": "final",
                "content": full_content,
                "finish_reason": finish_reason,
                "tool_calls": tool_calls if tool_calls else None,
                "usage": usage,
                "latency_ms": latency_ms,
                "model": getattr(response, 'model', self.model),
            }

        except Exception as e:
            logger.error(f"OpenRouter stream error: {e}")
            yield {
                "type": "error",
                "content": f"Error: {str(e)}",
                "finish_reason": "error",
            }

    def _chat(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
        **kwargs
    ) -> LLMResponse:
        """Internal chat implementation."""
        start_time = time.time()
        try:
            chat_kwargs = {
                "model": self.model,
                "messages": messages,
            }

            if tools:
                chat_kwargs["tools"] = self._format_tools(tools)
                chat_kwargs["tool_choice"] = "auto"

            extra_headers = kwargs.pop("extra_headers", None)
            if extra_headers:
                chat_kwargs["extra_headers"] = extra_headers

            response = self.client.chat.completions.create(**chat_kwargs, **kwargs)

            choice = response.choices[0]
            content = choice.message.content or ""

            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            latency_ms = (time.time() - start_time) * 1000

            if choice.finish_reason == "tool_calls" and hasattr(choice.message, 'tool_calls'):
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in choice.message.tool_calls
                ]
                return LLMResponse(
                    content=content,
                    finish_reason="tool_calls",
                    tool_calls=tool_calls,
                    usage=usage,
                    model=response.model,
                    latency_ms=latency_ms,
                )

            return LLMResponse(
                content=content,
                finish_reason=choice.finish_reason,
                usage=usage,
                model=response.model,
                latency_ms=latency_ms,
            )

        except Exception as e:
            logger.error(f"OpenRouter chat error: {e}")
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")

    def _format_tools(self, tools: List[Dict]) -> List[Dict]:
        """Format tools for OpenRouter API."""
        formatted = []
        for tool in tools:
            if "type" in tool and tool["type"] == "function":
                formatted.append(tool)
            elif "name" in tool:
                formatted.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                    }
                })
        return formatted

    @property
    def supported_models(self) -> Dict[str, Dict]:
        """Return supported models dictionary."""
        return self.SUPPORTED_MODELS

    def list_models(self) -> List[str]:
        """List available model IDs."""
        return list(self.SUPPORTED_MODELS.keys())

    def get_model_info(self, model: str = None) -> Dict:
        """Get information about a specific model."""
        model = model or self.model
        return self.model_info(model)

    @classmethod
    def model_info(cls, model: str) -> Dict:
        """Inspect static model metadata without constructing a provider."""
        return cls.SUPPORTED_MODELS.get(model, {"name": model, "provider": "unknown"})
