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
import re
import uuid
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
        session_id: str = None,
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session_id = self._sanitize_session_id(
            session_id or os.environ.get("OPENCODE_SESSION_ID", "")
        )
        # OpenCode Go requires a stable conversation identifier.  Keep a
        # generated value on this provider instance when the caller did not
        # supply the workspace/session id, so retries and streaming use the
        # same routing key rather than creating a new conversation each time.
        self._opencode_session_id = (
            self.session_id or uuid.uuid4().hex
            if self._is_opencode_go_endpoint(base_url)
            else ""
        )
        # Keep retries bounded so a transient provider outage cannot hold a
        # clinical turn for an unbounded amount of time.
        self.max_retries = min(max(int(max_retries), 0), 2)
        self.extra_kwargs = kwargs
        self._client = None
        self._client_key = None

    @staticmethod
    def _sanitize_session_id(value: str) -> str:
        """Keep provider headers printable and bounded without exposing data."""
        cleaned = re.sub(r"[^A-Za-z0-9._:-]+", "-", str(value or "").strip())
        return cleaned[:128]

    @staticmethod
    def _is_opencode_go_endpoint(base_url: str) -> bool:
        value = str(base_url or "").lower()
        return "opencode.ai" in value and "/zen/go" in value

    def _default_headers(self) -> Dict[str, str]:
        if not self._is_opencode_go_endpoint(self.base_url):
            return {}
        return {
            "user-agent": "BrachyBot/1.0",
            "x-opencode-session": self._opencode_session_id,
        }

    def _get_client(self):
        """Reuse one OpenAI client so its HTTP connection pool is reused."""
        import openai

        default_headers = self._default_headers()
        key = (
            self.api_key,
            self.base_url,
            self.timeout,
            tuple(sorted(default_headers.items())),
        )
        if self._client is None or self._client_key != key:
            self._client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                default_headers=default_headers or None,
            )
            self._client_key = key
        return self._client

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
            self._record_llm_error("openai package not installed")
            return LLMResponse(content="Error: openai package not installed", finish_reason="error")

        if not self.api_key:
            self._record_llm_error("no API key provided")
            return LLMResponse(content="Error: No API key provided", finish_reason="error")

        for attempt in range(self.max_retries + 1):
            start_time = time.time()
            try:
                client = self._get_client()

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

                self._record_llm_success()
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
                    self._record_llm_error(e)
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
            self._record_llm_error("openai package not installed")
            yield {"type": "error", "content": "Error: openai package not installed"}
            return

        if not self.api_key:
            self._record_llm_error("no API key provided")
            yield {"type": "error", "content": "Error: No API key provided"}
            return

        for attempt in range(self.max_retries + 1):
            start_time = time.time()
            try:
                client = self._get_client()

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

                self._record_llm_success()
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
                    self._record_llm_error(e)
                    yield {"type": "error", "content": f"Error: {str(e)}"}
                    return
