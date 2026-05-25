"""
LLM Router
==========
Routes requests to the appropriate LLM based on task requirements.
"""

import os
import logging
from typing import Dict, List, Optional, Any

from .base import BaseLLM, LLMResponse

logger = logging.getLogger(__name__)


class LLMRouter:
    """
    Routes LLM requests to appropriate providers.

    Supports:
    - Automatic selection based on task type
    - Provider fallback chains
    - Cost/latency optimization
    """

    def __init__(self, config: Dict[str, Dict] = None):
        self.providers: Dict[str, BaseLLM] = {}
        self.config = config or {}
        self.default_provider = None
        self._initialize_providers()

    def _initialize_providers(self):
        """Initialize all configured LLM providers."""
        for name, cfg in self.config.items():
            if not cfg.get("enabled", True):
                continue
            try:
                llm = self._create_llm(name, cfg)
                if llm:
                    self.providers[name] = llm
                    logger.info(f"Initialized LLM provider: {name} ({cfg.get('model', 'unknown')})")
            except Exception as e:
                logger.warning(f"Failed to initialize {name}: {e}")

        if not self.providers and os.environ.get("OPENAI_API_KEY"):
            try:
                from .openai_llm import OpenAILLM
                self.providers["openai"] = OpenAILLM()
                self.default_provider = "openai"
            except Exception as e:
                logger.warning(f"Auto-config failed: {e}")

        if not self.default_provider and self.providers:
            self.default_provider = next(iter(self.providers))

    def _create_llm(self, name: str, cfg: Dict) -> Optional[BaseLLM]:
        """Create an LLM instance from config."""
        if name == "openai":
            from ..providers.openai_llm import OpenAILLM
            return OpenAILLM(
                api_key=cfg.get("api_key", os.environ.get("OPENAI_API_KEY", "")),
                model=cfg.get("model", "gpt-4o"),
            )
        elif name == "anthropic":
            from ..providers.anthropic_llm import AnthropicLLM
            return AnthropicLLM(
                api_key=cfg.get("api_key", os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")),
                model=cfg.get("model", os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")),
                base_url=cfg.get("base_url", os.environ.get("ANTHROPIC_BASE_URL", None)),
            )
        elif name == "local":
            from ..providers.local_llm import LocalLLM
            return LocalLLM(
                base_url=cfg.get("base_url", "http://localhost:8000/v1"),
                model=cfg.get("model", "qwen2.5-14b-instruct"),
            )
        elif name == "ollama":
            from ..providers.local_llm import OllamaLLM
            return OllamaLLM(
                base_url=cfg.get("base_url", "http://localhost:11434"),
                model=cfg.get("model", "qwen2.5:14b"),
            )
        elif name == "azure_openai":
            from ..providers.openai_llm import OpenAILLM
            llm = OpenAILLM(
                api_key=cfg.get("api_key", os.environ.get("AZURE_OPENAI_KEY", "")),
                model=cfg.get("model", "gpt-4o"),
            )
            llm.base_url = cfg.get("endpoint", os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
            return llm
        elif name == "qwen":
            from ..providers.qwen_llm import QwenLLM
            return QwenLLM(
                api_key=cfg.get("api_key", os.environ.get("DASHSCOPE_API_KEY", "")),
                model=cfg.get("model", "qwen-plus"),
                base_url=cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            )
        elif name == "kimi":
            from ..providers.kimi_llm import KimiLLM
            return KimiLLM(
                api_key=cfg.get("api_key", os.environ.get("MOONSHOT_API_KEY", "")),
                model=cfg.get("model", "kimi-k2.6"),
                base_url=cfg.get("base_url", "https://api.moonshot.cn/v1"),
            )
        elif name == "minimax":
            from ..providers.minimax_llm import MiniMaxLLM
            return MiniMaxLLM(
                api_key=cfg.get("api_key", os.environ.get("MINIMAX_API_KEY", "")),
                model=cfg.get("model", "minimax-m2.7-20260318"),
                base_url=cfg.get("base_url", "https://api.minimax.chat/v1"),
            )
        elif name == "tencent":
            from ..providers.tencent_llm import TencentLLM
            return TencentLLM(
                api_key=cfg.get("api_key", os.environ.get("TENCENT_API_KEY", "")),
                model=cfg.get("model", "hy3-preview"),
                base_url=cfg.get("base_url", "https://api.hunyuan.cloud.tencent.com/v1"),
            )
        elif name == "glm":
            from ..providers.glm_llm import GLMLLM
            return GLMLLM(
                api_key=cfg.get("api_key", os.environ.get("ZHIPU_API_KEY", "")),
                model=cfg.get("model", "glm-4-flash"),
                base_url=cfg.get("base_url", "https://open.bigmodel.cn/api/paas/v4"),
            )
        elif name == "gemini":
            from ..providers.gemini_llm import GeminiLLM
            return GeminiLLM(
                api_key=cfg.get("api_key", os.environ.get("GOOGLE_API_KEY", "")),
                model=cfg.get("model", "gemini-2.0-flash"),
                base_url=cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta"),
            )
        elif name == "groq":
            from ..providers.groq_llm import GroqLLM
            return GroqLLM(
                api_key=cfg.get("api_key", os.environ.get("GROQ_API_KEY", "")),
                model=cfg.get("model", "llama-3.3-70b-versatile"),
                base_url=cfg.get("base_url", "https://api.groq.com/openai/v1"),
            )
        elif name == "grok":
            from ..providers.grok_llm import GrokLLM
            return GrokLLM(
                api_key=cfg.get("api_key", os.environ.get("XAI_API_KEY", "")),
                model=cfg.get("model", "grok-3"),
                base_url=cfg.get("base_url", "https://api.x.ai/v1"),
            )
        elif name == "mimo":
            from ..providers.mimo_llm import MimoLLM
            return MimoLLM(
                api_key=cfg.get("api_key", os.environ.get("MIMO_API_KEY", "")),
                model=cfg.get("model", "mimo-4"),
                base_url=cfg.get("base_url", "https://api.mimo.ai/v1"),
            )
        elif name == "deepseek":
            from ..providers.deepseek_llm import DeepSeekLLM
            return DeepSeekLLM(
                api_key=cfg.get("api_key", os.environ.get("DEEPSEEK_API_KEY", "")),
                model=cfg.get("model", "deepseek-v4-flash"),
                base_url=cfg.get("base_url", "https://api.deepseek.com/v1"),
            )
        elif name == "openrouter":
            from ..providers.openrouter_llm import OpenRouterLLM
            return OpenRouterLLM(
                api_key=cfg.get("api_key", os.environ.get("OPENROUTER_API_KEY", "")),
                model=cfg.get("model", "hy3-preview"),
                base_url=cfg.get("base_url", "https://openrouter.ai/api/v1"),
            )
        return None

    def chat(
        self,
        prompt: str,
        system: str = "",
        provider: str = None,
        tools: List[Dict] = None,
        task_type: str = "general",
        **kwargs
    ) -> LLMResponse:
        """Send chat request to the appropriate LLM."""
        llm = self._select_llm(provider, task_type)
        if not llm:
            return LLMResponse(content="Error: No LLM provider available", finish_reason="error")
        try:
            return llm.chat(prompt=prompt, system=system, tools=tools, **kwargs)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")

    def chat_messages(
        self,
        messages: List[Dict],
        provider: str = None,
        tools: List[Dict] = None,
        task_type: str = "general",
        **kwargs
    ) -> LLMResponse:
        """Send chat request with message history."""
        llm = self._select_llm(provider, task_type)
        if not llm:
            return LLMResponse(content="Error: No LLM provider available", finish_reason="error")
        try:
            return llm.chat_messages(messages=messages, tools=tools, **kwargs)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return LLMResponse(content=f"Error: {str(e)}", finish_reason="error")

    def chat_messages_stream(
        self,
        messages: List[Dict],
        provider: str = None,
        tools: List[Dict] = None,
        task_type: str = "general",
        **kwargs
    ):
        """Streaming version that yields text chunks."""
        llm = self._select_llm(provider, task_type)
        if not llm:
            yield {"type": "error", "content": "Error: No LLM provider available"}
            return
        try:
            yield from llm.chat_messages_stream(messages=messages, tools=tools, **kwargs)
        except Exception as e:
            logger.error(f"LLM stream call failed: {e}")
            yield {"type": "error", "content": f"Error: {str(e)}"}

    def _select_llm(self, provider: str, task_type: str) -> Optional[BaseLLM]:
        """Select the best LLM for the task."""
        if provider and provider in self.providers:
            return self.providers[provider]
        if self.default_provider in self.providers:
            return self.providers[self.default_provider]
        return next(iter(self.providers.values())) if self.providers else None

    def register(self, name: str, llm: BaseLLM):
        """Register an LLM provider."""
        self.providers[name] = llm
        if not self.default_provider:
            self.default_provider = name

    def list_providers(self) -> List[Dict]:
        """List all available providers."""
        return [
            {"name": name, "model": llm.default_model if hasattr(llm, 'default_model') else "unknown"}
            for name, llm in self.providers.items()
        ]

    @property
    def available(self) -> List[str]:
        return list(self.providers.keys())