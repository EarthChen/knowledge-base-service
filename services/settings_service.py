"""Configuration management service merging DB, env, and defaults."""

from __future__ import annotations

from typing import Any

from core.config import Settings, get_settings
from core.log import get_logger
from services.settings_crypto import decrypt_value, encrypt_value, mask_value
from store.settings_store import SettingsStore

log = get_logger(__name__)

SENSITIVE_KEYS = frozenset({
    "falkordb.password",
    "falkordb_password",
    "llm.api_key",
    "llm.providers",
    "git.gitlab_token",
    "git.github_token",
    "wiki.git_token",
    "api_token",
})


def _flatten_settings(settings: Settings) -> dict[str, tuple[str, str]]:
    """Flatten Settings into {dotted_key: (value_str, category)}."""
    result: dict[str, tuple[str, str]] = {}

    for k in ("host", "port", "log_level", "rate_limit_rpm", "require_auth"):
        result[k] = (str(getattr(settings, k, "")), "system")

    result["falkordb_password"] = (str(settings.falkordb_password), "storage")

    config_map = {
        "falkordb": ("storage", settings.falkordb),
        "embedding": ("embedding", settings.embedding),
        "llm": ("llm", settings.llm),
        "wiki": ("wiki_features", settings.wiki),
        "hybrid_search": ("search", settings.hybrid_search),
        "rerank": ("search", settings.rerank),
        "git": ("git", settings.git),
    }

    for prefix, (category, cfg) in config_map.items():
        for field_name, _ in cfg.__class__.model_fields.items():
            key = f"{prefix}.{field_name}"
            val = getattr(cfg, field_name, "")
            if isinstance(val, dict):
                val = str(val)
            elif isinstance(val, (list, tuple)):
                val = ",".join(str(v) for v in val)
            else:
                val = str(val)
            cat = category
            if prefix == "wiki":
                if "git" in field_name:
                    cat = "wiki_git"
                elif field_name.endswith("_enabled") and not any(
                    x in field_name for x in ("rag_", "enrichment_", "cot_", "code_budget_")
                ):
                    cat = "wiki_features"
                else:
                    cat = "wiki_generation"
            result[key] = (val, cat)

    return result


def get_valid_keys() -> frozenset[str]:
    return frozenset(_flatten_settings(get_settings()).keys())


def _build_key_category_map() -> dict[str, str]:
    """Map each valid key to its correct category."""
    return {key: cat for key, (_, cat) in _flatten_settings(get_settings()).items()}


def _refresh_llm_max_concurrent(new_limit: int) -> None:
    """Apply a new LLM HTTP concurrency limit to all live gateway providers."""
    from api import kb_state
    from llm.provider import LLMProvider

    container = kb_state._container
    if container is None or container.registry is None:
        log.debug("llm_concurrency_refresh_skipped", reason="container_not_ready")
        return

    updated = 0
    for svc in container.registry._services.values():
        provider = svc.llm_provider
        if isinstance(provider, LLMProvider):
            provider.update_concurrency(new_limit)
            updated += 1
    log.info("llm_concurrency_refreshed", new_limit=new_limit, providers_updated=updated)


class SettingsService:
    def __init__(self, store: SettingsStore) -> None:
        self._store = store

    async def get_all_merged(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Return all settings merged from DB/env/defaults, grouped by category.

        Returns: {category: {key: {value, source, sensitive}}}
        """
        defaults = _flatten_settings(get_settings())
        db_overrides = await self._store.get_all()
        db_flat: dict[str, str] = {}
        for cat_settings in db_overrides.values():
            db_flat.update(cat_settings)

        result: dict[str, dict[str, dict[str, Any]]] = {}
        for key, (default_val, category) in defaults.items():
            is_sensitive = key in SENSITIVE_KEYS

            if key in db_flat:
                raw_val = db_flat[key]
                if is_sensitive:
                    try:
                        raw_val = decrypt_value(raw_val)
                    except Exception:
                        raw_val = ""
                        log.warning("failed_to_decrypt_setting", key=key)
                source = "db"
                display_val = mask_value(raw_val) if is_sensitive else raw_val
            else:
                source = "default"
                display_val = mask_value(default_val) if is_sensitive and default_val else default_val

            if category not in result:
                result[category] = {}
            result[category][key] = {
                "value": display_val,
                "source": source,
                "sensitive": is_sensitive,
            }

        return result

    async def get_category(self, category: str) -> dict[str, dict[str, Any]]:
        merged = await self.get_all_merged()
        return merged.get(category, {})

    async def update_settings(self, updates: list[dict[str, str]]) -> None:
        """Update settings. Encrypts sensitive values before storage."""
        valid = get_valid_keys()
        key_to_category = _build_key_category_map()
        items = []
        has_concurrency_change = False
        llm_max_concurrent: int | None = None
        for u in updates:
            key = u["key"]
            if key not in valid:
                raise ValueError(f"Unknown setting key: {key}")
            value = u["value"]
            category = key_to_category.get(key, "system")
            if key in SENSITIVE_KEYS:
                value = encrypt_value(value)
            items.append({"key": key, "value": value, "category": category})
            if key.startswith("wiki.") and key.endswith("_concurrency"):
                has_concurrency_change = True
            if key == "llm.max_concurrent":
                llm_max_concurrent = int(value)
        await self._store.upsert_batch(items)
        if has_concurrency_change:
            from wiki.pipeline_concurrency import PipelineConcurrency
            PipelineConcurrency.refresh()
            log.info("pipeline_concurrency_refreshed", trigger="settings_update")
        if llm_max_concurrent is not None:
            _refresh_llm_max_concurrent(llm_max_concurrent)

    async def delete_setting(self, key: str) -> bool:
        return await self._store.delete(key)
