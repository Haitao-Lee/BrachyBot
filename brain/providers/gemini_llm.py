"""
Gemini LLM Provider
===================
Google's Gemini series models.
"""

import os
import time
from typing import List, Dict, Any, Optional

from ..core.base import BaseLLM, LLMResponse


class GeminiLLM(BaseLLM):
    """Gemini model provider using Google AI API."""

    SUPPORTED_MODELS = {
        "gemini-3-flash-preview-20251217": "Latest Gemini 3 Flash (Dec 2025)",
        "gemini-2.5-flash": "Gemini 2.5 Flash (2025)",
        "gemini-2.5-pro": "Gemini 2.5 Pro most capable",
        "gemini-2.0-flash": "Gemini 2.0 Flash",
        "gemini-2.0-flash-lite": "Gemini 2.0 Flash Lite ultra fast",
        "gemini-1.5-flash": "Gemini 1.5 Flash",
        "gemini-1.5-pro": "Gemini 1.5 Pro high capability",
        "gemini-1.5-flash-8b": "Gemini 1.5 Flash 8B efficient",
        "gemini-exp-1206": "Experimental model",
    }

    def __init__(
        self,
        api_key: str = None,
        model: str = "gemini-2.0-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        **kwargs
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.extra_kwargs = kwargs

    @property
    def name(self) -> str:
        return f"gemini-{self.model}"

    @property
    def default_model(self) -> str:
        return "gemini-2.0-flash"

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        start_time = time.time()
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(model_name=self.model)

            system_text = ""
            contents = []
            for msg in messages:
                role = msg.get("role", "user")
                if role == "system":
                    system_text = msg.get("content", "")
                    continue
                parts = []
                if isinstance(msg.get("content"), str):
                    parts.append({"text": msg["content"]})
                elif isinstance(msg.get("content"), list):
                    for block in msg["content"]:
                        if block.get("type") == "text":
                            parts.append({"text": block.get("text", "")})
                        elif block.get("type") == "image_url":
                            image_url = block.get("image_url", {}).get("url", "")
                            if image_url.startswith("data:"):
                                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_url.split(",")[1]}})
                contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})

            generation_config = {}
            if system_text:
                generation_config["system_instruction"] = system_text
            if tools:
                tools_dict = [{"function_declarations": [
                    {"name": t["function"]["name"], "description": t["function"].get("description", ""),
                     "parameters": t["function"].get("parameters", {"type": "object", "properties": {}})}
                    for t in tools
                ]}]
                generation_config["tools"] = tools_dict

            generation_config.update(self.extra_kwargs)
            generation_config.update(kwargs)

            response = model.generate_content(
                contents=contents,
                generation_config=genai.types.GenerationConfig(**generation_config) if generation_config else None
            )

            latency_ms = (time.time() - start_time) * 1000

            usage = {}
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage = {
                    "prompt_tokens": response.usage_metadata.prompt_token_count,
                    "completion_tokens": response.usage_metadata.candidates_token_count,
                    "total_tokens": response.usage_metadata.total_token_count,
                }

            # Extract text content and tool calls from response parts
            content = ""
            tool_calls = []
            if hasattr(response, 'candidates') and response.candidates:
                parts = response.candidates[0].content.parts
                for part in parts:
                    if hasattr(part, 'text') and part.text:
                        content += part.text
                    elif hasattr(part, 'function_call') and part.function_call:
                        fc = part.function_call
                        tool_calls.append({
                            "id": f"gemini_{fc.name}_{len(tool_calls)}",
                            "name": fc.name,
                            "arguments": dict(fc.args) if hasattr(fc, 'args') and fc.args else {},
                        })
            # Fallback: response.text if no parts parsed
            if not content and not tool_calls:
                content = response.text or ""

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                usage=usage,
                model=self.model,
                latency_ms=latency_ms,
                finish_reason="stop",
            )
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")
