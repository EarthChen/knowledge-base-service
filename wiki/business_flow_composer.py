"""Generates business flow overview pages from community clusters."""
from __future__ import annotations

from typing import Any

from core.log import get_logger
from wiki.models import (
    PageType,
    WikiConfig,
    WikiPage,
    WikiPageMetadata,
    WikiPageSummary,
)

log = get_logger(__name__)

_FLOW_SYSTEM_PROMPT = (
    "You are writing a business flow overview for a software project. "
    "Given a cluster of related code components, explain what business purpose they serve, "
    "how they interact, and create a Mermaid sequence or flowchart diagram showing the flow. "
    "Output Markdown with sections: ## Business Purpose, ## Component Interactions, ## Flow Diagram."
)


class BusinessFlowPageComposer:
    def __init__(self, llm: Any, community_service: Any) -> None:
        self._llm = llm
        self._community_service = community_service

    async def compose_flows(
        self,
        repository: str,
        summary_index: dict[str, WikiPageSummary],
        uid_to_path: dict[str, str],
        config: WikiConfig,
        min_community_size: int = 3,
    ) -> list[WikiPage]:
        community_data = await self._community_service.get_cached(repository)
        communities = community_data.get("communities", [])

        pages: list[WikiPage] = []
        for community in communities:
            if community.get("size", 0) < min_community_size:
                continue
            raw_members = community.get("members", [])
            member_uids = [
                str(m) if isinstance(m, str) else str(m.get("uid", "")) if isinstance(m, dict) else str(m)
                for m in raw_members
            ]
            member_uids = [u for u in member_uids if u]
            member_summaries = [
                summary_index[uid_to_path[uid]]
                for uid in member_uids
                if uid in uid_to_path and uid_to_path[uid] in summary_index
            ]
            if not member_summaries:
                continue
            page = await self._compose_single_flow(
                community, member_summaries, member_uids, config, len(pages),
            )
            pages.append(page)
        log.info("business_flows_composed", repository=repository, count=len(pages))
        return pages

    async def _compose_single_flow(
        self,
        community: dict[str, Any],
        member_summaries: list[WikiPageSummary],
        member_uids: list[str],
        config: WikiConfig,
        flow_index: int,
    ) -> WikiPage:
        members_ctx = "\n".join(
            f"- **{s.title}** ({s.importance_tier.value if s.importance_tier else 'unknown'}): {s.summary}"
            for s in member_summaries
        )
        prompt = (
            f"## Community #{community.get('id', flow_index)} ({len(member_summaries)} components)\n\n"
            f"### Members:\n{members_ctx}\n\n"
            "Analyze these components and generate a business flow overview."
        )
        if self._llm:
            description = (await self._llm.generate(prompt, system=_FLOW_SYSTEM_PROMPT)).strip()
        else:
            description = f"Business flow containing: {', '.join(s.title for s in member_summaries)}"

        path = f"flows/business-flow-{flow_index}.md"
        title = (
            f"Business Flow: {member_summaries[0].title} and related"
            if member_summaries
            else f"Business Flow #{flow_index}"
        )

        page = WikiPage(
            path=path,
            title=title,
            page_type=PageType.BUSINESS_FLOW,
            content=f"# {title}\n\n{description}",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(
                node_count=len(member_summaries),
                edge_count=0,
                generation_mode=config.mode,
            ),
        )
        page._member_uids = member_uids  # type: ignore[attr-defined]
        return page
