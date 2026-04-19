"""Bridges KnowledgeBaseService wiki components to the MCP ``WikiPipeline`` protocol."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from wiki.ask import WikiAskService
from wiki.models import PageType, WikiPage, WikiStructure, WikiStructureNode, parse_scope
from wiki.search import SearchResponse, WikiSearchService
from wiki.service import WikiService


def _search_response_to_dict(resp: SearchResponse) -> dict[str, Any]:
    return {
        "results": [asdict(r) for r in resp.results],
        "query_expansion": resp.query_expansion,
        "total": resp.total,
    }


def _structure_node_to_tree(node: WikiStructureNode) -> dict[str, Any]:
    return {
        "path": node.path or "/",
        "title": node.title,
        "page_type": node.page_type.value,
        "children": [_structure_node_to_tree(c) for c in node.children],
        "metadata": {"pages": 1 + sum(_count_tree_pages(c) for c in node.children)},
    }


def _count_tree_pages(node: WikiStructureNode) -> int:
    return 1 + sum(_count_tree_pages(c) for c in node.children)


def _bundle_to_structure(bundle: dict[str, Any]) -> WikiStructure:
    raw = bundle.get("structure") or {}
    repo = str(raw.get("repository") or "")
    root_raw = raw.get("root") or {}
    return WikiStructure(
        repository=repo,
        root=_dict_to_structure_node(root_raw),
        total_pages=int(raw.get("total_pages") or len(bundle.get("pages") or [])),
    )


def _dict_to_structure_node(data: dict[str, Any]) -> WikiStructureNode:
    children_raw = data.get("children") or []
    return WikiStructureNode(
        path=str(data.get("path", "")),
        title=str(data.get("title", "")),
        page_type=PageType(data.get("page_type", PageType.REPO_OVERVIEW.value)),
        children=[_dict_to_structure_node(c) for c in children_raw if isinstance(c, dict)],
    )


def _select_page_for_scope(bundle: dict[str, Any], scope: str) -> WikiPage | None:
    pages_raw = list(bundle.get("pages") or [])
    if not pages_raw:
        return None
    pages = [WikiPage.from_dict(p) for p in pages_raw]
    sp = parse_scope(scope)
    if sp.scope_type == "repo":
        for p in pages:
            if p.page_type == PageType.REPO_OVERVIEW:
                return p
        return pages[0]
    non_overview = [p for p in pages if p.page_type != PageType.REPO_OVERVIEW]
    if len(non_overview) == 1:
        return non_overview[0]
    if non_overview:
        return non_overview[0]
    return pages[0]


class WikiPipelineAdapter:
    """MCP wiki tools backed by :class:`WikiService`, :class:`WikiSearchService`, and optional :class:`WikiAskService`."""

    def __init__(
        self,
        wiki_service: WikiService,
        search: WikiSearchService,
        ask: WikiAskService | None,
    ) -> None:
        self._wiki = wiki_service
        self._search = search
        self._ask = ask

    async def generate_wiki(self, repository: str, scope: str, mode: str) -> list[WikiPage]:
        bundle = await self._wiki.generate(repository, scope, mode, "json")
        raw_pages = list(bundle.get("pages") or [])
        return [WikiPage.from_dict(p) for p in raw_pages]

    async def get_wiki_page(self, repository: str, scope: str) -> WikiPage | None:
        bundle = await self._wiki.generate(repository, scope, "structure", "json")
        return _select_page_for_scope(bundle, scope)

    async def list_wiki_pages(self, repository: str, scope: str | None) -> dict[str, Any]:
        scope_raw = (scope or "").strip() or "repo"
        bundle = await self._wiki.generate(repository, scope_raw, "structure", "json")
        structure = _bundle_to_structure(bundle)
        return {
            "repository": repository,
            "tree": _structure_node_to_tree(structure.root),
            "total_pages": structure.total_pages,
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
