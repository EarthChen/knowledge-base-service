"""Bridges KnowledgeBaseService wiki components to the MCP ``WikiPipeline`` protocol."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from store.wiki_store import WikiStore
from wiki.ask import WikiAskService
from wiki.models import PageType, WikiPage, WikiPageMetadata, parse_scope
from wiki.search import SearchResponse, WikiSearchService
from wiki.service import WikiService

if TYPE_CHECKING:
    from store.falkordb_store import FalkorDBStore


def _search_response_to_dict(resp: SearchResponse) -> dict[str, Any]:
    return {
        "results": [asdict(r) for r in resp.results],
        "query_expansion": resp.query_expansion,
        "total": resp.total,
    }


def _class_scope_simple_name(fqn: str) -> str:
    base = fqn.split("#", 1)[0]
    return base.rsplit(".", 1)[-1] if base else ""


def _slugify_module_path(path: str) -> str:
    """Apply the same slugification as ``wiki/composer.py::_wiki_path``."""
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", path.strip("/"))


def _wiki_page_props_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    wp = row.get("wp")
    if wp is None:
        return None
    if hasattr(wp, "properties"):
        return dict(wp.properties)
    if isinstance(wp, dict):
        return wp
    return None


def _wiki_page_from_graph(props: dict[str, Any]) -> WikiPage:
    return WikiPage(
        path=str(props["path"]),
        title=str(props["title"]),
        page_type=PageType(str(props["page_type"])),
        content=str(props.get("content", "")),
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(
            node_count=0,
            edge_count=0,
            generation_mode="structure",
            fallback_tier=None,
            generated_at=str(props["generated_at"]) if props.get("generated_at") is not None else None,
        ),
    )


def _tree_pages_count(children: list[dict[str, Any]]) -> int:
    return 1 + sum(c["metadata"]["pages"] for c in children)


def _row_to_leaf_tree_node(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": row.get("path") or "/",
        "title": row.get("title") or "",
        "page_type": str(row.get("page_type") or ""),
        "children": [],
        "metadata": {"pages": 1},
    }


def _flat_wiki_rows_to_tree(repository: str, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    total = len(rows)
    if total == 0:
        return (
            {
                "path": "/",
                "title": repository,
                "page_type": PageType.REPO_OVERVIEW.value,
                "children": [],
                "metadata": {"pages": 0},
            },
            0,
        )
    root_idx: int | None = None
    for i, r in enumerate(rows):
        if str(r.get("page_type")) == PageType.REPO_OVERVIEW.value:
            root_idx = i
            break
    if root_idx is not None:
        root_row = rows[root_idx]
        rest = [r for j, r in enumerate(rows) if j != root_idx]
    else:
        root_row = rows[0]
        rest = list(rows[1:])
    rest_sorted = sorted(rest, key=lambda r: str(r.get("path") or ""))
    children = [_row_to_leaf_tree_node(r) for r in rest_sorted]
    return (
        {
            "path": root_row.get("path") or "/",
            "title": root_row.get("title") or "",
            "page_type": str(root_row.get("page_type") or ""),
            "children": children,
            "metadata": {"pages": _tree_pages_count(children)},
        },
        total,
    )


class WikiPipelineAdapter:
    """MCP wiki tools backed by :class:`WikiService`, :class:`WikiSearchService`, and optional :class:`WikiAskService`."""

    def __init__(
        self,
        wiki_service: WikiService,
        search: WikiSearchService,
        ask: WikiAskService | None,
        store: FalkorDBStore | None = None,
        wiki_store: WikiStore | None = None,
    ) -> None:
        self._wiki = wiki_service
        self._search = search
        self._ask = ask
        self._store = store
        self._wiki_store = wiki_store or (WikiStore(store) if store is not None else None)

    async def generate_wiki(self, repository: str, scope: str, mode: str) -> list[WikiPage]:
        bundle = await self._wiki.generate(repository, scope, mode, "json")
        raw_pages = list(bundle.get("pages") or [])
        return [WikiPage.from_dict(p) for p in raw_pages]

    async def get_wiki_page(self, repository: str, scope: str) -> WikiPage | None:
        if self._wiki_store is None:
            return None
        sp = parse_scope(scope)
        if sp.scope_type == "repo":
            result = await self._wiki_store.get_wiki_page_repo_overview(repository)
        elif sp.scope_type == "module":
            slug = _slugify_module_path(sp.value or "")
            result = await self._wiki_store.get_wiki_page_module(repository, slug)
        else:
            name = _class_scope_simple_name(sp.value or "")
            result = await self._wiki_store.get_wiki_page_class(repository, name)
        if not result.data:
            return None
        props = _wiki_page_props_from_row(result.data[0])
        if not props:
            return None
        return _wiki_page_from_graph(props)

    async def list_wiki_pages(self, repository: str, scope: str | None) -> dict[str, Any]:
        if self._wiki_store is None:
            tree, n = _flat_wiki_rows_to_tree(repository, [])
            return {"repository": repository, "tree": tree, "total_pages": n}

        if scope and scope.strip() and scope.strip() != "repo":
            sp = parse_scope(scope.strip())
            if sp.scope_type == "module":
                slug = _slugify_module_path(sp.value or "")
                prefix = f"modules/{slug}"
                result = await self._wiki_store.list_wiki_pages_module_prefix(repository, prefix)
            elif sp.scope_type == "class":
                name = _class_scope_simple_name(sp.value or "")
                result = await self._wiki_store.list_wiki_pages_class_contains(repository, name)
            else:
                result = await self._wiki_store.list_wiki_pages_all(repository)
        else:
            result = await self._wiki_store.list_wiki_pages_all(repository)
        rows = list(result.data)
        tree, total = _flat_wiki_rows_to_tree(repository, rows)
        return {
            "repository": repository,
            "tree": tree,
            "total_pages": total,
        }

    async def search_wiki(
        self,
        repository: str,
        query: str,
        mode: str = "hybrid",
        limit: int = 10,
        min_score: float = 0.0,
        scope: str | None = None,
    ) -> dict[str, Any]:
        resp = await self._search.search(
            repository,
            query,
            mode=mode,
            limit=limit,
            min_score=min_score,
            scope=scope,
        )
        return _search_response_to_dict(resp)

    async def ask_about_code(
        self,
        repository: str,
        question: str,
        scope: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        if self._ask is None:
            return {
                "content": (
                    "Wiki Q&A requires a configured language model. "
                    "Enable LLM in the knowledge base service settings."
                ),
                "sources": [],
                "conversation_id": "",
                "tokens_used": 0,
            }
        ask_resp = await self._ask.ask(
            repository=repository,
            question=question,
            scope=scope,
            conversation_id=conversation_id,
        )
        return {
            "content": ask_resp.content,
            "sources": [asdict(s) for s in ask_resp.sources],
            "conversation_id": ask_resp.conversation_id,
            "tokens_used": ask_resp.tokens_used,
        }
