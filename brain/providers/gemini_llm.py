"""
Gemini LLM Provider
===================
Google's Gemini series models.
"""

import os
import re
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

    @staticmethod
    def _convert_messages(messages: List[Dict]) -> tuple[str, List[Dict]]:
        """Translate role-aware OpenAI blocks into Gemini content dictionaries."""
        system_parts = []
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    system_parts.extend(
                        str(block.get("text", "")) for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                continue

            parts = []
            if isinstance(content, str):
                parts.append({"text": content})
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        parts.append({"text": str(block)})
                    elif block.get("type") == "text":
                        parts.append({"text": str(block.get("text", ""))})
                    elif block.get("type") == "image_url":
                        image_url = str(block.get("image_url", {}).get("url", "") or "")
                        match = re.match(r"^data:([^;]+);base64,(.+)$", image_url, re.DOTALL)
                        if match:
                            mime_type, data_b64 = match.groups()
                            parts.append({"inline_data": {"mime_type": mime_type, "data": data_b64}})
            if parts:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        return "\n".join(part for part in system_parts if part), contents

    def _chat(self, messages: List[Dict], tools: List[Dict] = None, **kwargs) -> LLMResponse:
        start_time = time.time()
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            system_text, contents = self._convert_messages(messages)
            if tools:
                tools_dict = [{"function_declarations": [
                    {"name": t["function"]["name"], "description": t["function"].get("description", ""),
                     "parameters": t["function"].get("parameters", {"type": "object", "properties": {}})}
                    for t in tools
                ]}]
            else:
                tools_dict = None

            # system_instruction and tools are model/request parameters, not
            # generation sampling options in the google-generativeai SDK.
            model = genai.GenerativeModel(
                model_name=self.model,
                system_instruction=system_text or None,
                tools=tools_dict,
            )
            config_source = {**self.extra_kwargs, **kwargs}
            config_keys = {
                "candidate_count", "max_output_tokens", "response_mime_type",
                "stop_sequences", "temperature", "top_k", "top_p",
            }
            generation_config = {
                key: value for key, value in config_source.items()
                if key in config_keys and value is not None
            }

            response = model.generate_content(
                contents=contents,
                generation_config=genai.types.GenerationConfig(**generation_config) if generation_config else None,
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
