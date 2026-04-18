"""Factory for creating LLM providers with a simple fallback chain."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from llm.azure_provider import AzureOpenAIProvider
from llm.base_provider import BaseLLMProvider
from llm.custom_provider import CustomOpenAIProvider
from llm.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    default_provider: str = "gateway"  # "gateway" | "openai" | "azure" | "custom"
    fallback_provider: str | None = None
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)


class LLMProviderFactory:
    """Factory for creating LLM providers with fallback chain."""

    def __init__(
        self,
        config: ProviderConfig,
        gateway_provider: BaseLLMProvider | None = None,
    ) -> None:
        self._config = config
        self._providers: dict[str, BaseLLMProvider] = {}
        if gateway_provider:
            self._providers["gateway"] = gateway_provider

    def get_provider(self, name: str | None = None) -> BaseLLMProvider:
        """Get provider by name, or default."""
        target = name or self._config.default_provider
        if target not in self._providers:
            self._providers[target] = self._create(target)
        return self._providers[target]

    def list_providers(self) -> list[str]:
        """List available provider names."""
        available = set(self._providers.keys())
        available.update(self._config.providers.keys())
        if "gateway" not in available:
            available.add("gateway")
        return sorted(available)

    async def complete_with_fallback(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Try default provider, fallback on failure for transport-level errors."""
        try:
            return await self.get_provider().complete(messages, **kwargs)
        except (
            httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException,
            ConnectionError, TimeoutError,
        ) as exc:
            if self._config.fallback_provider:
                logger.warning(
                    "Primary provider '%s' failed (%s), falling back to '%s'",
                    self._config.default_provider,
                    exc,
                    self._config.fallback_provider,
                )
                return await self.get_provider(self._config.fallback_provider).complete(messages, **kwargs)
            raise

    def _create(self, name: str) -> BaseLLMProvider:
        """Create a provider by name from config."""
        if name == "gateway":
            raise ValueError(
                "Gateway provider is not registered. Pass gateway_provider to LLMProviderFactory(...)."
            )
        if name not in self._config.providers:
            raise ValueError(
                f"Provider '{name}' not configured. Available: {self.list_providers()}"
            )
        cfg = self._config.providers[name]
        if name == "openai":
            return OpenAIProvider(
                api_key=cfg["api_key"],
                model=cfg.get("model", "gpt-4o"),
                base_url=cfg.get("base_url", "https://api.openai.com/v1"),
                max_concurrent=cfg.get("max_concurrent", 10),
                timeout=cfg.get("timeout", 30),
                retry_count=cfg.get("retry_count", 3),
                temperature=cfg.get("temperature", 0.1),
                max_context_tokens=cfg.get("max_context_tokens", 128000),
            )
        if name == "azure":
            return AzureOpenAIProvider(
                api_key=cfg["api_key"],
                resource_name=cfg["resource_name"],
                deployment_name=cfg["deployment_name"],
                api_version=cfg.get("api_version", "2024-02-15-preview"),
                max_concurrent=cfg.get("max_concurrent", 10),
                timeout=cfg.get("timeout", 30),
                retry_count=cfg.get("retry_count", 3),
                temperature=cfg.get("temperature", 0.1),
                max_context_tokens=cfg.get("max_context_tokens", 128000),
            )
        if name == "custom":
            return CustomOpenAIProvider(
                base_url=cfg["base_url"],
                api_key=cfg.get("api_key", ""),
                model=cfg.get("model", "default"),
                max_concurrent=cfg.get("max_concurrent", 10),
                timeout=cfg.get("timeout", 60),
                retry_count=cfg.get("retry_count", 3),
                temperature=cfg.get("temperature", 0.1),
                max_context_tokens=cfg.get("max_context_tokens", 32000),
            )
        raise ValueError(f"Unknown provider type: {name}")

    async def close_all(self) -> None:
        for p in self._providers.values():
            await p.close()
