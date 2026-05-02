from __future__ import annotations

from core.log import get_logger
from wiki.rag.protocol import Chunk, RetrievalScope

log = get_logger(__name__)


class CodeRetriever:
    def __init__(self, hybrid, *, repository_hint: str | None = None):
        self._hybrid = hybrid
        self._repository_hint = repository_hint

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        out: list[Chunk] = []
        seen: set[str] = set()
        repo = (scope.repository or self._repository_hint or "").strip() or None
        for q in queries:
            if not q.strip():
                continue
            try:
                payload = await self._hybrid.search_with_context(
                    q, k=min(limit, 20), limit=limit, offset=0, repository=repo
                )
            except Exception as exc:
                log.warning("code_retriever_hybrid_failed", error=str(exc))
                continue
            rows = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                path = str(row.get("file") or row.get("path") or "")
                name = str(row.get("name") or path)
                uid = f"{path}:{name}"
                if exclude_ids and uid in exclude_ids:
                    continue
                if uid in seen:
                    continue
                seen.add(uid)
                score = row.get("rrf_score", row.get("score", 0.0))
                try:
                    rel = float(score) if score is not None else 0.0
                except (TypeError, ValueError):
                    rel = 0.0
                summary = str(row.get("summary") or row.get("snippet") or "")
                out.append(
                    Chunk(
                        content=summary,
                        source=f"code:{path}",
                        title=name,
                        relevance=rel,
                        metadata={"row": row},
                    )
                )
                if len(out) >= limit:
                    return out
        return out
