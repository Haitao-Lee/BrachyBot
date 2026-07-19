"""
Anthropic Claude LLM Provider
=============================
Anthropic's Claude series models.
"""

import os
import time
import json
import logging
import re
from typing import Dict, List

from ..core.base import BaseLLM, LLMResponse

logger = logging.getLogger(__name__)


class AnthropicLLM(BaseLLM):
    """Anthropic Claude models provider."""

    SUPPORTED_MODELS = {
        "claude-opus-4-20250514": "Claude Opus 4 (May 2025)",
        "claude-sonnet-4-20250514": "Claude Sonnet 4 (May 2025)",
        "claude-4.7-opus-20260416": "Claude Opus 4.7 (Apr 2026)",
        "claude-4.6-sonnet-20260217": "Claude Sonnet 4.6 (Feb 2026)",
        "claude-3.5-sonnet-latest": "Claude 3.5 Sonnet",
        "claude-3-opus": "Claude 3 Opus",
        "claude-3-sonnet": "Claude 3 Sonnet",
        "claude-3-haiku": "Claude 3 Haiku fast",
    }

    @staticmethod
    def _convert_content_to_anthropic(content):
        """Translate OpenAI-style multimodal blocks into Anthropic content blocks."""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content)

        blocks = []
        for block in content:
            if not isinstance(block, dict):
                text = str(block).strip()
                if text:
                    blocks.append({"type": "text", "text": text})
                continue

            block_type = block.get("type")
            if block_type == "text":
                text = str(block.get("text", "")).strip()
                if text:
                    blocks.append({"type": "text", "text": text})
                continue

            if block_type == "image_url":
                image_url = str(block.get("image_url", {}).get("url", "") or "")
                match = re.match(r"^data:(image/[^;]+);base64,(.+)$", image_url, re.DOTALL)
                if match:
                    media_type, b64_data = match.groups()
                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_data,
                        }
                    })

        if not blocks:
            return ""
        return blocks

    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-sonnet-4-20250514",
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
        self.max_retries = min(max(int(max_retries), 0), 2)
        self.extra_kwargs = kwargs
        self._client = None
        self._client_key = None

    def _get_client(self, api_key: str):
        """Reuse the Anthropic HTTP client and its connection pool."""
        from anthropic import Anthropic

        key = (api_key, self.base_url, self.timeout)
        if self._client is None or self._client_key != key:
            client_kwargs = {"api_key": api_key, "timeout": self.timeout}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self._client = Anthropic(**client_kwargs)
            self._client_key = key
        return self._client

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return "claude-sonnet-4-20250514"

    def get_models(self) -> List[str]:
        return list(self.SUPPORTED_MODELS.keys())

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            from anthropic import Anthropic
        except ImportError:
            return LLMResponse(content="Error: anthropic package not installed", finish_reason="error")

        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        if not api_key:
            return LLMResponse(content="Error: No API key provided", finish_reason="error")

        try:
            client = self._get_client(api_key)
        except Exception as e:
            return LLMResponse(content=f"Error creating client: {str(e)}", finish_reason="error")

        system_msg = ""
        filtered_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                filtered_messages.append({"role": msg["role"], "content": msg["content"]})

        # Convert OpenAI-style tool messages to Anthropic format
        filtered_messages = self._convert_messages_to_anthropic(filtered_messages)

        request_kwargs = {
            "model": kwargs.get("model", self.model),
            "messages": filtered_messages,
            "temperature": kwargs.get("temperature", 0.0),
            "max_tokens": kwargs.get("max_tokens", 8192),
        }

        if system_msg:
            request_kwargs["system"] = system_msg

        if tools:
            request_kwargs["tools"] = [self._convert_tool(t) for t in tools]

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range(self.max_retries + 1):
            start_time = time.time()
            try:
                response = client.messages.create(**request_kwargs)
                break
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                # Check for rate limit / RPM errors
                is_rate_limit = any(x in error_str for x in ["rate_limit", "429", "too many requests", "rpm", "overloaded"])
                is_retryable = any(x in error_str for x in ["timeout", "connection", "503", "502", "500", "overloaded"])

                if (is_rate_limit or is_retryable) and attempt < self.max_retries:
                    wait_time = min(2 ** attempt * 2, 30)  # 2s, 4s, 8s, max 30s
                    logger.warning(f"Anthropic API error (attempt {attempt+1}/{self.max_retries+1}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Anthropic API call failed after {attempt+1} attempts: {e}")
                    return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")
        else:
            return LLMResponse(content=f"Error: {str(last_error)}", finish_reason="error")

        latency_ms = (time.time() - start_time) * 1000
        content = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })

        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=response.model,
            latency_ms=latency_ms,
            finish_reason=response.stop_reason,
        )

    def _convert_messages_to_anthropic(self, messages: List[Dict]) -> List[Dict]:
        """Convert OpenAI-style messages (with 'tool' role) to Anthropic format."""
        converted = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "tool":
                # OpenAI 'tool' role -> Anthropic 'user' with tool_result block
                # Find the preceding assistant message to get tool_use_id
                tool_use_id = msg.get("tool_call_id", f"tool_{i}")

                # Look back for the assistant message with tool_use
                for j in range(len(converted) - 1, -1, -1):
                    if converted[j]["role"] == "assistant":
                        c = converted[j]["content"]
                        if isinstance(c, list):
                            for block in c:
                                if block.get("type") == "tool_use":
                                    tool_use_id = block["id"]
                                    break
                        break

                # If previous message is user, create new assistant+user pair
                if converted and converted[-1]["role"] == "user":
                    converted.append({
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": tool_use_id, "name": "unknown", "input": {}}]
                    })

                converted.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": str(content)}]
                })
            elif role == "assistant":
                # Check if content looks like a tool_call block (our custom format)
                if isinstance(content, str) and "```tool_call" in content:
                    # Parse tool calls from our custom format
                    tool_uses = []
                    import re
                    pattern = r'```tool_call\s*\n(.*?)\n```'
                    matches = re.findall(pattern, content, re.DOTALL)
                    for idx, match in enumerate(matches):
                        try:
                            tc = json.loads(match.strip())
                            if isinstance(tc, list):
                                for t in tc:
                                    tool_uses.append({
                                        "type": "tool_use",
                                        "id": t.get("id", f"tool_{i}_{idx}"),
                                        "name": t.get("tool", "unknown"),
                                        "input": t.get("params", {}),
                                    })
                            elif isinstance(tc, dict):
                                tool_uses.append({
                                    "type": "tool_use",
                                    "id": tc.get("id", f"tool_{i}_{idx}"),
                                    "name": tc.get("tool", "unknown"),
                                    "input": tc.get("params", {}),
                                })
                        except json.JSONDecodeError:
                            pass

                    if tool_uses:
                        # Extract any text before/after tool calls
                        text_parts = re.sub(pattern, '', content, flags=re.DOTALL).strip()
                        blocks = []
                        if text_parts:
                            blocks.append({"type": "text", "text": text_parts})
                        blocks.extend(tool_uses)
                        converted.append({"role": "assistant", "content": blocks})
                    else:
                        converted.append({
                            "role": "assistant",
                            "content": self._convert_content_to_anthropic(content),
                        })
                else:
                    converted.append({
                        "role": "assistant",
                        "content": self._convert_content_to_anthropic(content),
                    })
            else:
                converted.append({
                    "role": role,
                    "content": self._convert_content_to_anthropic(content),
                })

            i += 1

        return converted

    def _convert_tool(self, tool: Dict) -> Dict:
        """Convert OpenAI-style tool to Anthropic format."""
        return {
            "name": tool["function"]["name"],
            "description": tool["function"].get("description", ""),
            "input_schema": tool["function"]["parameters"],
        }

    def chat_messages_stream(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
        **kwargs
    ):
        """Streaming version that yields text chunks as they arrive."""
        try:
            from anthropic import Anthropic
        except ImportError:
            yield {"type": "error", "content": "Error: anthropic package not installed"}
            return

        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        if not api_key:
            yield {"type": "error", "content": "Error: No API key provided"}
            return

        try:
            client = self._get_client(api_key)
        except Exception as e:
            yield {"type": "error", "content": f"Error creating client: {str(e)}"}
            return

        system_msg = ""
        filtered_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                filtered_messages.append({"role": msg["role"], "content": msg["content"]})

        filtered_messages = self._convert_messages_to_anthropic(filtered_messages)

        request_kwargs = {
            "model": kwargs.get("model", self.model),
            "messages": filtered_messages,
            "temperature": kwargs.get("temperature", 0.0),
            "max_tokens": kwargs.get("max_tokens", 8192),
            "stream": True,
        }

        if system_msg:
            request_kwargs["system"] = system_msg

        if tools:
            request_kwargs["tools"] = [self._convert_tool(t) for t in tools]

        start_time = time.time()
        full_content = ""
        tool_calls = []
        finish_reason = None
        usage_data = {}

        try:
            # Use raw stream instead of high-level helper for better compatibility
            stream = client.messages.create(**request_kwargs)

            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        full_content += event.delta.text
                        yield event.delta.text
                    elif event.delta.type == "input_json_delta":
                        # Accumulate tool call arguments
                        if tool_calls:
                            tool_calls[-1]["arguments"] += event.delta.partial_json
                elif event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        tool_calls.append({
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "arguments": "",
                        })
                elif event.type == "message_delta":
                    if event.delta.stop_reason:
                        finish_reason = event.delta.stop_reason
                    # Extract usage from message_delta if available
                    if hasattr(event, 'usage') and event.usage:
                        usage_data = {
                            "input_tokens": getattr(event.usage, 'input_tokens', 0) or 0,
                            "output_tokens": getattr(event.usage, 'output_tokens', 0) or 0,
                            "total_tokens": (getattr(event.usage, 'input_tokens', 0) or 0) +
                                           (getattr(event.usage, 'output_tokens', 0) or 0),
                        }

            latency_ms = (time.time() - start_time) * 1000

            # Parse tool call arguments
            for tc in tool_calls:
                try:
                    tc["arguments"] = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    tc["arguments"] = {}

            yield {
                "type": "final",
                "content": full_content,
                "finish_reason": finish_reason,
                "tool_calls": tool_calls if tool_calls else None,
                "usage": usage_data,
                "latency_ms": latency_ms,
            }

        except Exception as e:
            logger.error(f"Anthropic stream error: {e}")
            # Fallback to non-streaming if stream fails
            try:
                logger.info("Falling back to non-streaming chat...")
                request_kwargs.pop("stream", None)
                response = client.messages.create(**request_kwargs)
                content = ""
                for block in response.content:
                    if block.type == "text":
                        content += block.text
                
                yield {
                    "type": "final",
                    "content": content,
                    "finish_reason": response.stop_reason,
                    "tool_calls": [],
                    "usage": {
                        "prompt_tokens": response.usage.input_tokens,
                        "completion_tokens": response.usage.output_tokens,
                        "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                    },
                    "latency_ms": (time.time() - start_time) * 1000,
                }
            except Exception as fallback_e:
                logger.error(f"Fallback also failed: {fallback_e}")
                yield {"type": "error", "content": f"Error: {str(e)}"}
