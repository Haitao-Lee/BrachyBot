"""
MiniMax LLM Provider
====================
MiniMax's models.
"""

import os
import logging
from typing import List, Dict, Any, Optional

from ..core.base import BaseLLM, LLMResponse

logger = logging.getLogger(__name__)


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
        import time
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                # openai imported inside try: if missing, ImportError propagates
                # to the outer except Exception (line 108). The except
                # openai.RateLimitError (line 99) is safe because openai is in
                # requirements.txt 鈥?if somehow missing, the ImportError hits
                # first and we never reach the RateLimitError handler.
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

                start_time = time.time()
                response = client.chat.completions.create(**chat_kwargs)

                return LLMResponse(
                    content=response.choices[0].message.content or "",
                    # Nested format: {"function": {"name", "arguments"}}.
                    # Consumers in agent_runtime.llm_runtime handle both flat and nested formats.
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
            except openai.RateLimitError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Rate limit hit, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Rate limit exceeded after {max_retries} retries")
                    return LLMResponse(content="Error: Rate limit exceeded. Please try again later.", finish_reason="error")
            except Exception as e:
                return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")

    def chat_messages_stream(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
        **kwargs
    ):
        """Streaming version that yields text chunks."""
        import time
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                # Same as _chat: openai imported inside try for graceful fallback.
                import openai
                client = openai.OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )

                chat_kwargs = {"model": self.model, "messages": messages, "stream": True}
                if tools:
                    chat_kwargs["tools"] = tools
                chat_kwargs.update(self.extra_kwargs)
                chat_kwargs.update(kwargs)

                full_content = ""
                tool_calls = []
                finish_reason = None
                usage_data = {}

                stream = client.chat.completions.create(**chat_kwargs)

                for chunk in stream:
                    # Extract usage from final chunk if available (OpenAI-compatible)
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

                    # Handle text content
                    if delta.content:
                        full_content += delta.content
                        yield delta.content

                    # Handle tool calls
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            # Extend tool_calls list if needed
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

                # Yield final metadata
                yield {
                    "type": "final",
                    "content": full_content,
                    "finish_reason": finish_reason or "stop",
                    "tool_calls": tool_calls if tool_calls else None,
                    "usage": usage_data,
                }
                return  # Success, exit retry loop

            except openai.RateLimitError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Rate limit hit in stream, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Rate limit exceeded in stream after {max_retries} retries")
                    yield {"type": "error", "content": "Error: Rate limit exceeded. Please try again later."}
                    return
            except Exception as e:
                yield {"type": "error", "content": f"Error: {str(e)}"}
                return
