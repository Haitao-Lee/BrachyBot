"""
LLM Router
==========
Routes requests to the appropriate LLM based on task requirements.

Capabilities:
- Task-type → provider policy: each task (planning, chat, code, extraction)
  can map to a preferred provider, with a fallback chain
- Provider fallback chain: on error, automatically try the next provider
- Per-call / per-provider stats: tracks latency, error count, last-used time
- Cost & capability metadata: providers declare cost-per-1k tokens,
  max context, supports_streaming, supports_tools
"""

import os
import time
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Any, Iterable

from .base import BaseLLM, LLMResponse

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Per-task-type routing policies.
# Order matters: first provider is preferred, the rest form a fallback chain.
# A name not in ``providers`` is silently skipped at lookup time.
# ----------------------------------------------------------------------
DEFAULT_TASK_POLICY: Dict[str, List[str]] = {
    "planning":     ["anthropic", "openai", "kimi", "qwen", "deepseek", "glm"],
    "code":         ["anthropic", "deepseek", "openai", "kimi", "qwen", "glm"],
    "chat":         ["anthropic", "kimi", "qwen", "openai", "minimax", "deepseek"],
    "extraction":   ["glm", "qwen", "deepseek", "anthropic", "openai"],
    "reflection":   ["anthropic", "kimi", "deepseek", "openai"],
    "clinical":     ["anthropic", "openai", "kimi", "qwen", "deepseek"],
    "summarization":["glm", "qwen", "deepseek", "anthropic", "openai"],
    "general":      ["anthropic", "openai", "kimi", "qwen", "deepseek", "glm"],
}

# Tasks that, if they fail, should NOT be silently retried with a different
# model — failure here indicates a real problem (bad schema, missing tool).
# The router will still surface the error normally.
NO_FALLBACK_TASKS = {"final_judgment"}


class LLMRouter:
    """
    Routes LLM requests to appropriate providers.

    Supports:
    - Automatic selection based on task type
    - Provider fallback chains
    - Cost/latency tracking and reporting
    """

    def __init__(self, config: Dict[str, Dict] = None, task_policy: Dict[str, List[str]] = None):
        self.providers: Dict[str, BaseLLM] = {}
        self.config = config or {}
        self.default_provider = None
        # Per-task-type fallback chain; merged with default policy
        self.task_policy: Dict[str, List[str]] = {
            **DEFAULT_TASK_POLICY,
            **(task_policy or {}),
        }
        # Per-provider capability / cost metadata. Filled lazily by
        # ``register`` / ``_initialize_providers``; callers may set
        # ``router.provider_meta[name]`` after registration to override.
        self.provider_meta: Dict[str, Dict[str, Any]] = {}
        # Per-provider rolling stats: total calls, errors, total latency, last error
        self._stats: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"calls": 0, "errors": 0, "latency_ms_sum": 0.0, "last_error": ""}
        )
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
                    # Record cost / capability metadata if the config provides it
                    self.provider_meta[name] = {
                        "cost_per_1k_input_usd": cfg.get("cost_per_1k_input_usd", 0.0),
                        "cost_per_1k_output_usd": cfg.get("cost_per_1k_output_usd", 0.0),
                        "max_context_tokens": cfg.get("max_context_tokens", 0),
                        "supports_streaming": cfg.get("supports_streaming", True),
                        "supports_tools": cfg.get("supports_tools", True),
                        "model": cfg.get("model", "unknown"),
                    }
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
        # Generic OpenAI-compatible provider: works with ANY vendor
        # that exposes /v1/chat/completions (MiniMax, DeepSeek, Qwen,
        # Kimi, GLM, MiMo, Groq, OpenRouter, custom proxies, etc.)
        if cfg.get("type") == "openai_compat":
            from ..providers.generic_openai_compat import GenericOpenAICompatLLM
            return GenericOpenAICompatLLM(
                api_key=cfg.get("api_key", ""),
                model=cfg.get("model", "gpt-4o"),
                base_url=cfg.get("base_url", "https://api.openai.com/v1"),
                timeout=cfg.get("timeout", 120.0),
                max_retries=cfg.get("max_retries", 3),
            )

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
        allow_fallback: bool = True,
        **kwargs
    ) -> LLMResponse:
        """Send chat request to the appropriate LLM, with optional fallback.

        Args:
            allow_fallback: if False, only the explicitly-selected provider
                            is tried; useful for tasks where the wrong model
                            would produce subtly wrong output (e.g. clinical
                            judgment, replanning).
        """
        names = self._resolve_provider_order(provider, task_type, allow_fallback)
        if not names:
            return LLMResponse(content="Error: No LLM provider available", finish_reason="error")

        last_err: Optional[Exception] = None
        for name in names:
            llm = self.providers.get(name)
            if llm is None:
                continue
            t0 = time.time()
            try:
                response = llm.chat(prompt=prompt, system=system, tools=tools, **kwargs)
                self._record_stats(name, ok=True, latency_ms=(time.time() - t0) * 1000)
                # Tag the response with the actual provider used
                if not getattr(response, "model", None) or not response.model:
                    try:
                        response.model = name
                    except Exception:
                        pass
                return response
            except Exception as e:
                last_err = e
                self._record_stats(name, ok=False, latency_ms=(time.time() - t0) * 1000, error=str(e))
                logger.warning(f"LLM call to {name!r} failed: {e}")
                if not allow_fallback:
                    break
        return LLMResponse(
            content=f"Error: All providers failed. Last error: {last_err}",
            finish_reason="error",
        )

    def chat_messages(
        self,
        messages: List[Dict],
        provider: str = None,
        tools: List[Dict] = None,
        task_type: str = "general",
        allow_fallback: bool = True,
        **kwargs
    ) -> LLMResponse:
        """Send chat request with message history."""
        names = self._resolve_provider_order(provider, task_type, allow_fallback)
        if not names:
            return LLMResponse(content="Error: No LLM provider available", finish_reason="error")

        last_err: Optional[Exception] = None
        for name in names:
            llm = self.providers.get(name)
            if llm is None:
                continue
            t0 = time.time()
            try:
                response = llm.chat_messages(messages=messages, tools=tools, **kwargs)
                self._record_stats(name, ok=True, latency_ms=(time.time() - t0) * 1000)
                if not getattr(response, "model", None) or not response.model:
                    try:
                        response.model = name
                    except Exception:
                        pass
                return response
            except Exception as e:
                last_err = e
                self._record_stats(name, ok=False, latency_ms=(time.time() - t0) * 1000, error=str(e))
                logger.warning(f"LLM call_messages to {name!r} failed: {e}")
                if not allow_fallback:
                    break
        return LLMResponse(
            content=f"Error: All providers failed. Last error: {last_err}",
            finish_reason="error",
        )

    def chat_messages_stream(
        self,
        messages: List[Dict],
        provider: str = None,
        tools: List[Dict] = None,
        task_type: str = "general",
        **kwargs
    ):
        """Streaming version that yields text chunks.

        For streaming we do NOT chain fallbacks (would corrupt the stream);
        the first reachable provider in the policy is used.
        """
        names = self._resolve_provider_order(provider, task_type, allow_fallback=True)
        if not names:
            yield {"type": "error", "content": "Error: No LLM provider available"}
            return
        llm = None
        for name in names:
            if name in self.providers:
                llm = self.providers[name]
                break
        if llm is None:
            yield {"type": "error", "content": "Error: No LLM provider available"}
            return

        t0 = time.time()
        try:
            if hasattr(llm, 'chat_messages_stream'):
                yield from llm.chat_messages_stream(messages=messages, tools=tools, **kwargs)
            else:
                # Fallback to non-streaming — yield only the final dict
                # (content is included in the dict; yielding it separately causes double content)
                response = llm._chat(messages, tools=tools, **kwargs)
                yield {
                    "type": "final",
                    "content": response.content or "",
                    "finish_reason": response.finish_reason,
                    "tool_calls": response.tool_calls if response.tool_calls else None,
                    "usage": response.usage,
                }
            self._record_stats(name, ok=True, latency_ms=(time.time() - t0) * 1000)
        except Exception as e:
            self._record_stats(name, ok=False, latency_ms=(time.time() - t0) * 1000, error=str(e))
            logger.error(f"LLM stream call failed: {e}")
            yield {"type": "error", "content": f"Error: {str(e)}"}

    # ------------------------------------------------------------------
    # Provider selection & stats helpers
    # ------------------------------------------------------------------

    def _resolve_provider_order(
        self,
        explicit_provider: Optional[str],
        task_type: str,
        allow_fallback: bool,
    ) -> List[str]:
        """Return ordered list of provider names to try for this call.

        Order:
          1. ``explicit_provider`` if given and registered
          2. Task policy chain for ``task_type`` (if available)
          3. ``default_provider`` (if set)
        """
        chain: List[str] = []
        if explicit_provider and explicit_provider in self.providers:
            chain.append(explicit_provider)
            if not allow_fallback:
                return chain

        if task_type in self.task_policy:
            for name in self.task_policy[task_type]:
                if name in self.providers and name not in chain:
                    chain.append(name)

        if not chain and self.default_provider in self.providers:
            chain.append(self.default_provider)

        if not chain and self.providers:
            chain.append(next(iter(self.providers)))

        return chain

    def _select_llm(self, provider: str, task_type: str) -> Optional[BaseLLM]:
        """Legacy single-provider selector used by callers that don't want fallback."""
        if provider and provider in self.providers:
            return self.providers[provider]
        if task_type in self.task_policy:
            for name in self.task_policy[task_type]:
                if name in self.providers:
                    return self.providers[name]
        if self.default_provider in self.providers:
            return self.providers[self.default_provider]
        return next(iter(self.providers.values())) if self.providers else None

    def _record_stats(self, name: str, ok: bool, latency_ms: float = 0.0, error: str = ""):
        s = self._stats[name]
        s["calls"] += 1
        if not ok:
            s["errors"] += 1
            s["last_error"] = error[:200]
        s["latency_ms_sum"] += float(latency_ms)

    def get_stats(self) -> Dict[str, Dict[str, float]]:
        """Return per-provider rolling stats (calls, errors, avg latency, last error)."""
        out: Dict[str, Dict[str, float]] = {}
        for name, s in self._stats.items():
            calls = s["calls"] or 1
            out[name] = {
                "calls": float(s["calls"]),
                "errors": float(s["errors"]),
                "error_rate": s["errors"] / calls,
                "avg_latency_ms": s["latency_ms_sum"] / calls,
                "last_error": s["last_error"],
            }
        return out

    def register(self, name: str, llm: BaseLLM, meta: Optional[Dict[str, Any]] = None):
        """Register an LLM provider.

        Args:
            name: provider key (used in task policy chains).
            llm: the provider instance.
            meta: optional capability/cost metadata (``cost_per_1k_input_usd``,
                  ``max_context_tokens``, ``supports_streaming``, etc.).
        """
        self.providers[name] = llm
        if meta:
            self.provider_meta[name] = {**self.provider_meta.get(name, {}), **meta}
        if not self.default_provider:
            self.default_provider = name

    def set_task_policy(self, task_type: str, providers: Iterable[str]):
        """Override the fallback chain for a given task type.

        Pass an empty list to use the default chain at call time.
        """
        self.task_policy[task_type] = list(providers)

    def list_providers(self) -> List[Dict]:
        """List all available providers with metadata."""
        out: List[Dict] = []
        for name, llm in self.providers.items():
            row = {
                "name": name,
                "model": llm.default_model if hasattr(llm, 'default_model') else "unknown",
            }
            row.update(self.provider_meta.get(name, {}))
            stats = self.get_stats().get(name, {})
            if stats:
                row["calls"] = int(stats["calls"])
                row["error_rate"] = round(stats["error_rate"], 3)
                row["avg_latency_ms"] = round(stats["avg_latency_ms"], 1)
            out.append(row)
        return out

    @property
    def available(self) -> List[str]:
        return list(self.providers.keys())