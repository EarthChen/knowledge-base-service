from __future__ import annotations

import json
from typing import Any

from core.log import get_logger
from llm.base_provider import LLMPortBridge
from llm.provider_factory import LLMProviderFactory
from store.settings_store import SettingsStore
from wiki.llm_port import LLMPort

log = get_logger(__name__)


class ModelStrategy:
    def __init__(
        self,
        settings_store: SettingsStore,
        provider_factory: LLMProviderFactory,
        default_provider: str,
        default_model: str,
    ) -> None:
        self._store = settings_store
        self._factory = provider_factory
        self._default_provider = default_provider
        self._default_model = default_model

    async def resolve(
        self,
        task_type: str,
        complexity_override: tuple[str, str] | None = None,
        *,
        complexity_metrics: Any | None = None,
    ) -> tuple[str, str]:
        raw = await self._store.get(f"llm.strategy.{task_type}")
        if raw:
            try:
                cfg = json.loads(raw)
                return str(cfg["provider"]), str(cfg["model"])
            except (json.JSONDecodeError, KeyError, TypeError):
                log.warning("model_strategy_bad_setting", task_type=task_type, raw=repr(raw)[:200])
        if complexity_override:
            return complexity_override[0], complexity_override[1]
        if complexity_metrics is not None:
            strategy = getattr(complexity_metrics, "recommended_strategy", None)
            if strategy is not None:
                resolved_task = getattr(strategy, "model_task_type", None)
                if resolved_task and resolved_task != task_type:
                    raw2 = await self._store.get(f"llm.strategy.{resolved_task}")
                    if raw2:
                        try:
                            cfg2 = json.loads(raw2)
                            return str(cfg2["provider"]), str(cfg2["model"])
                        except (json.JSONDecodeError, KeyError, TypeError):
                            log.warning("model_strategy_bad_setting", task_type=resolved_task, raw=raw2[:200])
        return self._default_provider, self._default_model

    async def get_llm_port(self, task_type: str) -> LLMPort:
        provider_name, model = await self.resolve(task_type)
        provider = self._factory.get_provider(provider_name)
        return _LLMPortWithDefault(LLMPortBridge(provider), default_model=model)


class _LLMPortWithDefault:
    """Wraps LLMPortBridge so routed model is injected when callers omit it."""

    def __init__(self, inner: LLMPortBridge, *, default_model: str) -> None:
        self._inner = inner
        self._default_model = default_model

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        m = model or self._default_model
        return await self._inner.generate(
            prompt,
            system,
            model=m,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        kwargs.setdefault("model", self._default_model)
        return await self._inner.complete(messages, **kwargs)

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ):
        kwargs.setdefault("model", self._default_model)
        async for chunk in self._inner.complete_stream(messages, **kwargs):
            yield chunk
