from __future__ import annotations

import json

import pytest

from services.settings_service import SENSITIVE_KEYS
from store.settings_store import SettingsStore


def test_llm_providers_key_is_sensitive() -> None:
    assert "llm.providers" in SENSITIVE_KEYS


@pytest.mark.asyncio
async def test_llm_providers_stored_and_retrievable(tmp_path) -> None:
    db = str(tmp_path / "x.db")
    store = SettingsStore(db_path=db)
    payload = json.dumps({"openai": {"api_key": "sk-secret", "base_url": "https://api.openai.com/v1"}})
    await store.upsert("llm.providers", payload, "llm")
    raw = await store.get("llm.providers")
    assert raw is not None
    data = json.loads(raw)
    assert data["openai"]["api_key"] == "sk-secret"
