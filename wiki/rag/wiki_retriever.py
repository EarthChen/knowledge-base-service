from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core.log import get_logger
from wiki.rag.protocol import Chunk, RetrievalScope

log = get_logger(__name__)


@runtime_checkable
class _WikiSearchLike(Protocol):
    async def search(
        self,
        repository: str,
        query: str,
        mode: str = "hybrid",
        limit: int = 10,
        min_score: float = 0.0,
        *,
        scope: str | None = None,
    ) -> Any: ...


class WikiRetriever:
    def __init__(
        self,
        wiki_search: _WikiSearchLike,
        *,
        default_repository: str = "",
        search_mode: str = "hybrid",
    ) -> None:
        self._search = wiki_search
        self._default_repository = default_repository
        self._mode = search_mode

    def _repo(self, scope: RetrievalScope) -> str:
        return (scope.repository or self._default_repository or "").strip()

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        repo = self._repo(scope)
        if not repo:
            log.warning(
                "wiki_retriever_missing_repository",
                scope_type=scope.scope_type,
            )
            return []
        out: list[Chunk] = []
        seen: set[str] = set()
        for q in queries:
            if not q.strip():
                continue
            resp = await self._search.search(
                repo,
                q,
                mode=self._mode,
                limit=limit,
                min_score=0.0,
                scope=scope.page_path,
            )
            results = getattr(resp, "results", None) or []
            for sr in results:
                path = str(getattr(sr, "page_path", "") or "")
                if exclude_ids and path in exclude_ids:
                    continue
                key = path or str(getattr(sr, "title", ""))
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    Chunk(
                        content=str(getattr(sr, "snippet", "") or ""),
                        source=f"wiki:{path}",
                        title=str(getattr(sr, "title", "") or path),
                        relevance=float(getattr(sr, "score", 0.0) or 0.0),
                        metadata={"page_path": path, "mode": self._mode},
                    )
                )
                if len(out) >= limit:
                    return out
        return out
