from __future__ import annotations

import logging
import re
from typing import Any

from wiki.rag.protocol import Chunk, RetrievalScope

logger = logging.getLogger(__name__)

_GRAPH_STOP_WORDS: frozenset[str] = frozenset({
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "done",
    "for",
    "from",
    "handle",
    "he",
    "her",
    "him",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "might",
    "must",
    "my",
    "of",
    "on",
    "or",
    "our",
    "should",
    "she",
    "that",
    "the",
    "their",
    "them",
    "then",
    "these",
    "they",
    "this",
    "those",
    "to",
    "too",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
    "you",
    "your",
})

_MAX_ENTITY_LOOKUPS = 3

_PASCAL_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)*\b")
_CAMEL_RE = re.compile(r"\b[a-z][a-z0-9]*[A-Z][a-zA-Z0-9]*\b")
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_WORD_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_]*\b")


def _format_cypher_row(row: dict[str, Any]) -> str:
    """Format a Cypher result row as readable text for retrieval chunks."""
    if not isinstance(row, dict):
        return str(row)
    typ = str(row.get("type") or "").strip()
    name = str(row.get("name") or "").strip()
    file = str(row.get("file") or "").strip()
    line_raw = row.get("line", row.get("start_line"))
    line: int | None
    if line_raw is None or (isinstance(line_raw, str) and not line_raw.strip()):
        line = None
    else:
        try:
            line = int(line_raw)
        except (TypeError, ValueError):
            line = None
    sig_raw = row.get("signature")
    sig = str(sig_raw).strip() if sig_raw is not None else ""

    head_parts: list[str] = []
    if typ:
        head_parts.append(f"[{typ}]")
    if name:
        head_parts.append(name)
    head = " ".join(head_parts) if head_parts else (name or typ or str(row))

    loc = ""
    if file or line is not None:
        lnum = line if line is not None else 0
        loc = f" ({file}:{lnum})" if file else f" (:{lnum})"

    if sig:
        return f"{head}{loc} - {sig}"
    return f"{head}{loc}".strip()


def _graph_result_rows(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    data = getattr(result, "data", None)
    if data is not None:
        return list(data)
    rows = getattr(result, "rows", None)
    if rows is not None:
        return list(rows)
    return []


def extract_entity_candidates(query: str, *, max_lookups: int = _MAX_ENTITY_LOOKUPS) -> list[str]:
    """Pull entity-like tokens from a natural-language query (patterns + words, minus stop words)."""
    out: list[str] = []
    seen_lower: set[str] = set()

    def push(term: str) -> None:
        t = term.strip()
        if len(t) < 2:
            return
        tl = t.lower()
        if tl in _GRAPH_STOP_WORDS:
            return
        if tl in seen_lower:
            return
        seen_lower.add(tl)
        out.append(t)
        if len(out) >= max_lookups:
            return

    hits: list[tuple[int, str]] = []
    for rx in (_PASCAL_RE, _CAMEL_RE, _SNAKE_RE):
        for m in rx.finditer(query):
            hits.append((m.start(), m.group(0)))
    hits.sort(key=lambda x: x[0])
    for _, term in hits:
        push(term)
        if len(out) >= max_lookups:
            return out[:max_lookups]

    for m in _WORD_RE.finditer(query):
        push(m.group(0))
        if len(out) >= max_lookups:
            break
    return out[:max_lookups]


def _node_lookup_key(node: dict[str, Any]) -> str:
    name = str(node.get("name", "") or "")
    line = int(node.get("line", 0) or 0)
    return f"{name}:{line}"


def chunks_from_call_chain_result(chain_result: Any, *, relevance: float = 0.35) -> list[Chunk]:
    """Build Chunk lines like ``Caller calls Callee`` from GraphQueryService.find_call_chain output."""
    nodes = _graph_result_rows(chain_result)
    key_to_name = {_node_lookup_key(n): str(n.get("name", "") or "") for n in nodes}
    params = getattr(chain_result, "params", None) or {}
    if not isinstance(params, dict):
        params = {}
    edges = params.get("_edges") or []
    chunks: list[Chunk] = []
    seen_pairs: set[tuple[str, str]] = set()
    for e in edges:
        sk = str(e.get("source", "") or "")
        tk = str(e.get("target", "") or "")
        sn = key_to_name.get(sk, "")
        tn = key_to_name.get(tk, "")
        if not sn and ":" in sk:
            sn = sk.rsplit(":", 1)[0]
        if not tn and ":" in tk:
            tn = tk.rsplit(":", 1)[0]
        if not sn or not tn or sn == tn:
            continue
        pair = (sn, tn)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        chunks.append(
            Chunk(
                content=f"{sn} calls {tn}",
                source="graph",
                title="graph",
                relevance=relevance,
            ),
        )
    return chunks


class HybridGraphRetriever:
    """Wraps HybridQueryService + optional graph service as a Retriever."""

    def __init__(
        self,
        hybrid_service: Any,
        graph_service: Any | None = None,
        *,
        nl_cypher: Any | None = None,
    ) -> None:
        self._hybrid = hybrid_service
        self._graph = graph_service
        self._nl_cypher = nl_cypher

    async def _append_graph_chunks(
        self,
        query: str,
        chunks: list[Chunk],
        *,
        repository: str | None = None,
    ) -> None:
        if self._nl_cypher is not None and hasattr(self._nl_cypher, "query"):
            try:
                query_fn = self._nl_cypher.query
                payload = await query_fn(query, repository=repository)
                rows = payload.get("results") or []
                if rows:
                    for r in rows:
                        content = _format_cypher_row(r) if isinstance(r, dict) else str(r)
                        chunks.append(
                            Chunk(
                                content=content,
                                source="graph_cypher",
                                title="graph_cypher",
                                relevance=0.4,
                            ),
                        )
                    return
            except Exception:
                logger.debug("nl_cypher_retriever_failed", exc_info=True)

        if self._graph is None or not hasattr(self._graph, "find_entity"):
            return
        terms = extract_entity_candidates(query, max_lookups=_MAX_ENTITY_LOOKUPS)
        call_chained: set[str] = set()
        try:
            for term in terms:
                result = await self._graph.find_entity(term)
                for r in _graph_result_rows(result):
                    typ = ""
                    nm = ""
                    if not isinstance(r, dict):
                        content = str(r)
                    else:
                        nm = str(r.get("name", "") or "")
                        typ = str(r.get("type", "") or "")
                        sig = r.get("signature")
                        bits = [nm] if nm else []
                        if typ:
                            bits.append(f"({typ})")
                        if sig:
                            bits.append(str(sig))
                        content = " ".join(bits) if bits else str(r)
                    chunks.append(
                        Chunk(
                            content=content,
                            source="graph",
                            title="graph",
                            relevance=0.4,
                        ),
                    )
                    if typ not in ("Function", "Class"):
                        continue
                    if not nm or nm in call_chained:
                        continue
                    if not hasattr(self._graph, "find_call_chain"):
                        continue
                    call_chained.add(nm)
                    chain = await self._graph.find_call_chain(
                        nm,
                        depth=1,
                        direction="downstream",
                    )
                    chunks.extend(chunks_from_call_chain_result(chain))
        except Exception:
            logger.debug("graph_retriever_entity_lookup_failed", exc_info=True)

    async def retrieve(
        self,
        queries: list[str],
        scope: RetrievalScope,
        *,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        for query in queries:
            hybrid_results = await self._hybrid.search_with_context(
                query,
                limit=limit,
                repository=scope.repository,
            )
            if isinstance(hybrid_results, dict):
                rows = (
                    hybrid_results.get("semantic_matches")
                    or hybrid_results.get("results")
                    or []
                )
            else:
                rows = hybrid_results or []

            for r in rows:
                if isinstance(r, dict):
                    content = str(
                        r.get("content")
                        or r.get("summary")
                        or r.get("name")
                        or r
                    )
                    title = str(r.get("title") or r.get("name") or "")
                    rel = float(r.get("score", r.get("rrf_score", 0.5)) or 0.5)
                    path = str(r.get("path") or r.get("file") or "")
                else:
                    content = getattr(r, "content", str(r))
                    title = getattr(r, "title", "") or ""
                    rel = float(getattr(r, "score", 0.5) or 0.5)
                    path = getattr(r, "path", "") or ""
                chunks.append(
                    Chunk(
                        content=content,
                        source="wiki",
                        title=title,
                        relevance=rel,
                        metadata={"path": path},
                    )
                )

            await self._append_graph_chunks(query, chunks, repository=scope.repository)
        return chunks[:limit]
