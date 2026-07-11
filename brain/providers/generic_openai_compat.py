"""
Generic OpenAI-Compatible LLM Provider
======================================
Works with ANY LLM vendor that exposes an OpenAI-compatible
/v1/chat/completions endpoint. Just set base_url, api_key, and model.

Examples:
  - MiniMax:    base_url="https://api.minimax.chat/v1"
  - DeepSeek:   base_url="https://api.deepseek.com/v1"
  - Qwen:       base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
  - Kimi:       base_url="https://api.moonshot.cn/v1"
  - GLM:        base_url="https://open.bigmodel.cn/api/paas/v4"
  - Groq:       base_url="https://api.groq.com/openai/v1"
  - OpenRouter: base_url="https://openrouter.ai/api/v1"
  - Any proxy:  base_url="https://your-proxy.com/v1"
"""

import os
import time
import json
import logging
from typing import Dict, List, Optional

from ..core.base import BaseLLM, LLMResponse

logger = logging.getLogger(__name__)


class GenericOpenAICompatLLM(BaseLLM):
    """Universal provider for any OpenAI-compatible API endpoint."""

    def __init__(
        self,
        api_key: str = None,
        model: str = "gpt-4o",
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 120.0,
        max_retries: int = 3,
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return f"generic({self.model})"

    @property
    def default_model(self) -> str:
        return self.model

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            import openai
        except ImportError:
            return LLMResponse(content="Error: openai package not installed", finish_reason="error")

        if not self.api_key:
            return LLMResponse(content="Error: No API key provided", finish_reason="error")

        client_kwargs = {"api_key": self.api_key, "base_url": self.base_url, "timeout": self.timeout}

        for attempt in range(self.max_retries + 1):
            start_time = time.time()
            try:
                client = openai.OpenAI(**client_kwargs)

                request_kwargs = {
                    "model": kwargs.get("model", self.model),
                    "messages": messages,
                    "temperature": kwargs.get("temperature", 0.0),
                    "max_tokens": kwargs.get("max_tokens", 8192),
                }
                if tools:
                    request_kwargs["tools"] = tools
                    request_kwargs["tool_choice"] = "auto"

                response = client.chat.completions.create(**request_kwargs)

                latency_ms = (time.time() - start_time) * 1000
                choice = response.choices[0]
                content = choice.message.content or ""

                tool_calls = []
                if choice.message.tool_calls:
                    for tc in choice.message.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                        except (json.JSONDecodeError, TypeError):
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
                    model=getattr(response, "model", self.model),
                    latency_ms=latency_ms,
                    finish_reason=choice.finish_reason or "stop",
                )

            except Exception as e:
                error_str = str(e).lower()
                is_retryable = any(x in error_str for x in [
                    "rate_limit", "429", "too many requests", "rpm",
                    "timeout", "connection", "503", "502", "500", "overloaded",
                ])
                if is_retryable and attempt < self.max_retries:
                    wait_time = min(2 ** attempt * 2, 30)
                    logger.warning(f"Generic OpenAI-compat error (attempt {attempt+1}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Generic OpenAI-compat call failed: {e}")
                    return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")

        return LLMResponse(content="Error: retry loop exhausted", finish_reason="error")

    def chat_messages_stream(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
        **kwargs
    ):
        """Streaming version that yields text chunks."""
        try:
            import openai
        except ImportError:
            yield {"type": "error", "content": "Error: openai package not installed"}
            return

        if not self.api_key:
            yield {"type": "error", "content": "Error: No API key provided"}
            return

        client_kwargs = {"api_key": self.api_key, "base_url": self.base_url, "timeout": self.timeout}

        for attempt in range(self.max_retries + 1):
            start_time = time.time()
            try:
                client = openai.OpenAI(**client_kwargs)

                request_kwargs = {
                    "model": kwargs.get("model", self.model),
                    "messages": messages,
                    "temperature": kwargs.get("temperature", 0.0),
                    "max_tokens": kwargs.get("max_tokens", 8192),
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                if tools:
                    request_kwargs["tools"] = tools
                    request_kwargs["tool_choice"] = "auto"

                stream = client.chat.completions.create(**request_kwargs)

                full_content = ""
                tool_calls = []
                finish_reason = None
                usage_data = {}

                for chunk in stream:
                    if hasattr(chunk, 'usage') and chunk.usage:
                        usage_data = {
                            "prompt_tokens": getattr(chunk.usage, 'prompt_tokens', 0) or 0,
                            "completion_tokens": getattr(chunk.usage, 'completion_tokens', 0) or 0,
                            "total_tokens": getattr(chunk.usage, 'total_tokens', 0) or 0,
                        }

                    if not chunk.choices:
                        continue

                    choice = chunk.choices[0]
                    delta = choice.delta

                    if delta.content:
                        full_content += delta.content
                        yield delta.content

                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            while len(tool_calls) <= tc_delta.index:
                                tool_calls.append({
                                    "id": "",
                                    "function": {"name": "", "arguments": ""}
                                })
                            tc = tool_calls[tc_delta.index]
                            if tc_delta.id:
                                tc["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tc["function"]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tc["function"]["arguments"] += tc_delta.function.arguments

                    if choice.finish_reason:
                        finish_reason = choice.finish_reason

                latency_ms = (time.time() - start_time) * 1000

                # Parse tool call arguments
                parsed_tool_calls = None
                if tool_calls:
                    parsed_tool_calls = []
                    for tc in tool_calls:
                        try:
                            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                        except (json.JSONDecodeError, TypeError):
                            args = tc["function"]["arguments"]
                        parsed_tool_calls.append({
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "arguments": args,
                        })

                yield {
                    "type": "final",
                    "content": full_content,
                    "finish_reason": finish_reason or "stop",
                    "tool_calls": parsed_tool_calls,
                    "usage": usage_data,
                    "latency_ms": latency_ms,
                }
                return

            except Exception as e:
                error_str = str(e).lower()
                is_retryable = any(x in error_str for x in [
                    "rate_limit", "429", "too many requests", "rpm",
                    "timeout", "connection", "503", "502", "500", "overloaded",
                ])
                if is_retryable and attempt < self.max_retries:
                    wait_time = min(2 ** attempt * 2, 30)
                    logger.warning(f"Generic stream error (attempt {attempt+1}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Generic stream failed: {e}")
                    yield {"type": "error", "content": f"Error: {str(e)}"}
                    return
