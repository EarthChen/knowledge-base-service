from __future__ import annotations

from typing import Any

from wiki.cypher_queries import MODULE_CALLEES_CY, MODULE_CALLERS_CY, MODULE_KEY_METHODS_CY


class ModuleEnricher:
    """Bulk-fetch module signals (key_methods, callers, callees, fan_in/out) and cache results."""

    def __init__(self, graph_store: Any) -> None:
        self._store = graph_store
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._fetched_keys: set[tuple[str, str]] = set()

    async def enrich(
        self, repos: list[str], names: list[str]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        needed = {(r, n) for r in repos for n in names} - self._fetched_keys
        if not needed:
            return self._cache

        unique_repos = list({r for r, _ in needed})
        unique_names = list({n for _, n in needed})
        params = {"repos": unique_repos, "names": unique_names}

        methods_result = await self._store.execute_query(MODULE_KEY_METHODS_CY, params)
        callees_result = await self._store.execute_query(MODULE_CALLEES_CY, params)
        callers_result = await self._store.execute_query(MODULE_CALLERS_CY, params)

        for row in methods_result.data or []:
            key = (row["repo"], row["module_name"])
            self._cache.setdefault(key, {})["key_methods"] = row.get("key_methods", [])

        for row in callees_result.data or []:
            key = (row["repo"], row["source"])
            entry = self._cache.setdefault(key, {})
            entry["callees"] = row.get("callees", [])
            entry["fan_out"] = row.get("fan_out", 0)

        for row in callers_result.data or []:
            key = (row["repo"], row["target"])
            entry = self._cache.setdefault(key, {})
            entry["callers"] = row.get("callers", [])
            entry["fan_in"] = row.get("fan_in", 0)

        self._fetched_keys.update(needed)
        return self._cache

    def get(self, repo: str, name: str) -> dict[str, Any]:
        return self._cache.get((repo, name), {})
