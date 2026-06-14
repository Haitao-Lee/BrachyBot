"""
Local LLM Providers (vLLM, Ollama, etc.)
"""

import os
import time
import json
from typing import Dict, List, Optional

from ..core.base import BaseLLM, LLMResponse


class LocalLLM(BaseLLM):
    """Local OpenAI-compatible LLM server (vLLM, LMDeploy, etc.)."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000/v1",
        model: str = "qwen2.5-14b-instruct",
        timeout: int = 120,
        max_retries: int = 3,
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def name(self) -> str:
        return "local"

    @property
    def default_model(self) -> str:
        return "qwen2.5-14b-instruct"

    def get_models(self) -> List[str]:
        if not self.base_url:
            return [self.model]
        try:
            import requests
            resp = requests.get(f"{self.base_url}/v1/models", timeout=5)
            if resp.status_code == 200:
                return [m["id"] for m in resp.json().get("data", [])]
        except Exception:
            pass
        return [self.model]

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError:
            return LLMResponse(content="Error: openai package not installed", finish_reason="error")

        start_time = time.time()
        base_url = self.base_url or "http://localhost:8000/v1"

        try:
            client = OpenAI(
                base_url=base_url,
                api_key="not-needed",
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


class OllamaLLM(LocalLLM):
    """Ollama local LLM server."""

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def default_model(self) -> str:
        return "qwen2.5:14b"

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        try:
            import requests
        except ImportError:
            return LLMResponse(content="Error: requests package not installed", finish_reason="error")

        start_time = time.time()
        base_url = self.base_url or "http://localhost:11434"

        ollama_messages = []
        for msg in messages:
            if msg["role"] == "system":
                ollama_messages.append({"role": "system", "content": msg["content"]})
            elif msg["role"] == "user":
                ollama_messages.append({"role": "user", "content": msg["content"]})
            elif msg["role"] == "assistant":
                ollama_messages.append({"role": "assistant", "content": msg["content"]})

        request_kwargs = {
            "model": kwargs.get("model", self.model),
            "messages": ollama_messages,
            "stream": False,
        }

        if tools:
            request_kwargs["tools"] = [self._convert_tool_to_ollama(t) for t in tools]

        try:
            resp = requests.post(
                f"{base_url}/api/chat",
                json=request_kwargs,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return LLMResponse(content=f"Ollama error: {resp.status_code} - {resp.text}", finish_reason="error")
            data = resp.json()
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")

        latency_ms = (time.time() - start_time) * 1000
        content = data.get("message", {}).get("content", "")

        tool_calls = []
        if data.get("message", {}).get("tool_calls"):
            for tc in data["message"]["tool_calls"]:
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                })

        usage = {"eval_count": data.get("eval_count", 0)}

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=data.get("model", self.model),
            latency_ms=latency_ms,
            finish_reason=data.get("done_reason", "stop"),
        )

    def _convert_tool_to_ollama(self, tool: Dict) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "parameters": tool["function"]["parameters"],
            }
        }