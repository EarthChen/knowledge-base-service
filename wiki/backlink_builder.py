"""Generates bidirectional backlinks using batch-loaded graph relationships."""
from __future__ import annotations

from typing import Any

from core.log import get_logger
from wiki.models import WikiPage
from wiki.wikilink_cache import WikiLinkCache

log = get_logger(__name__)


class BacklinkBuilder:
    async def build_backlinks(
        self,
        pages: list[WikiPage],
        graph: Any,
        wikilink_cache: WikiLinkCache,
        repository: str,
    ) -> None:
        """Append 'Referenced by' sections to each page in-place using batch query."""
        referrer_index = await graph.find_all_referrers_batch(repository)
        uid_to_path: dict[str, str] = {}
        for page in pages:
            uid = getattr(page, "_source_entity_uid", "")
            if uid:
                uid_to_path[uid] = page.path

        modified_count = 0
        for page in pages:
            uid = getattr(page, "_source_entity_uid", "")
            if not uid:
                continue
            referrer_uids = referrer_index.get(uid, [])
            backlinks = []
            for ref_uid in referrer_uids:
                ref_path = uid_to_path.get(ref_uid)
                if ref_path:
                    ref_title = wikilink_cache.get_title_for_path(ref_path)
                    if ref_title:
                        backlinks.append(f"- [[{ref_title}]]")
            if backlinks:
                page.content += "\n\n## Referenced by\n\n" + "\n".join(sorted(set(backlinks)))
                modified_count += 1

        log.info("backlinks_built", repository=repository, pages_modified=modified_count)
