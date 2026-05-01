from __future__ import annotations

import json

import pytest

from llm.base_provider import LLMPortBridge
from llm.provider_factory import LLMProviderFactory, ProviderConfig
from store.settings_store import SettingsStore
from wiki.model_strategy import ModelStrategy


class _StubProvider:
    @property
    def provider_name(self) -> str:
        return "stub"

    @property
    def supports_streaming(self) -> bool:
        return False

    @property
    def max_context_tokens(self) -> int:
        return 128000

    async def complete(self, messages, **kwargs):
        return "ok"

    async def complete_json(self, messages, schema, **kwargs):
        return {}

    async def complete_stream(self, messages, **kwargs):
        if False:
            yield ""

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_resolve_uses_db_strategy(tmp_path) -> None:
    db = str(tmp_path / "s.db")
    store = SettingsStore(db_path=db)
    await store.upsert(
        "llm.strategy.classification",
        json.dumps({"provider": "gateway", "model": "m-mini"}),
        "llm",
    )
    cfg = ProviderConfig(default_provider="gateway", providers={})
    factory = LLMProviderFactory(cfg, gateway_provider=_StubProvider())
    ms = ModelStrategy(
        store, factory, default_provider="gateway", default_model="m-default"
    )
    p, m = await ms.resolve("classification")
    assert p == "gateway"
    assert m == "m-mini"
