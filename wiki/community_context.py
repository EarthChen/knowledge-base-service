"""Community detection result formatting and cache-friendly helpers for wiki generation."""

from __future__ import annotations

from typing import Any


def format_communities_markdown(detect_result: dict[str, Any], *, max_communities: int = 20) -> str:
    """Serialize CommunityDetector output into Markdown for LLM / overview context."""
    communities = list(detect_result.get("communities") or [])
    if not communities:
        return ""
    lines: list[str] = [
        "## Code Module Communities (from graph analysis)",
        "",
        "The following module clusters were detected from code dependency analysis. "
        "Use them as non-binding boundaries for documentation sections.",
        "",
    ]
    for i, c in enumerate(communities[:max_communities], start=1):
        label = str(c.get("label") or f"cluster-{i}")
        size = c.get("size", 0)
        coh = c.get("cohesion")
        coh_s = f"{float(coh):.4f}" if isinstance(coh, (int, float)) else "n/a"
        members = list(c.get("members") or [])
        core = [str(m.get("name") or "") for m in members[:8] if m.get("name")]
        block = (
            f"### Community {i}: {label} ({int(size)} entities)\n"
            f"- Cohesion: {coh_s}\n"
            f"- Entities: {', '.join(core) or '(none)'}\n"
        )
        lines.append(block)
    return "\n".join(lines).rstrip() + "\n"


async def get_repository_index_fingerprint(store: Any, repository: str) -> str:
    """Return a short cache key; must change when repo graph index metadata changes."""
    r = await store.execute_query(
        "MATCH (n) WHERE n.repository = $repo "
        "RETURN count(n) AS cnt, max(n.indexed_at) AS mx",
        {"repo": repository},
    )
    rows = getattr(r, "data", None) or []
    row: dict[str, Any] = {}
    if rows:
        r0 = rows[0]
        row = r0 if isinstance(r0, dict) else {}
    cnt = int(row.get("cnt") or 0)
    mx = row.get("mx")
    return f"{repository}:{cnt}:{mx!s}"


class CachedCommunityService:
    def __init__(self, store: Any, detector: Any) -> None:
        self._store = store
        self._detector = detector
        self._cache: dict[str, dict[str, Any]] = {}

    def clear_repository(self, repository: str) -> None:
        self._cache = {k: v for k, v in self._cache.items() if not k.startswith(f"{repository}::")}

    async def get_cached(self, repository: str) -> dict[str, Any]:
        fp = await get_repository_index_fingerprint(self._store, repository)
        key = f"{repository}::{fp}"
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        out = await self._detector.detect(repository=repository)
        self._cache[key] = out
        return out
