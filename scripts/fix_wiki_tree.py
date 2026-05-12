"""One-shot script to fix HAS_CHILD edges for business wiki pages.

Queries WikiPage nodes where repository = business_id and creates
missing HAS_CHILD edges from WikiSpace → WikiSection → WikiPage.

Usage:
    cd ~/review-bot/knowledge-base-service
    source .venv/bin/activate
    python scripts/fix_wiki_tree.py --business-id ultron
"""

from __future__ import annotations

import argparse
import asyncio
import sys

async def main(business_id: str) -> None:
    from core.config import FalkorDBConfig, get_settings
    from store.falkordb_store import FalkorDBStore

    settings = get_settings()
    store = FalkorDBStore(config=settings.falkordb)
    await store.connect()

    q_count = (
        "MATCH (wp:WikiPage) WHERE wp.repository = $biz "
        "RETURN count(wp) AS cnt"
    )
    r = store._graph.query(q_count, {"biz": business_id})
    page_count = r.result_set[0][0] if r.result_set else 0
    print(f"WikiPages with repository={business_id}: {page_count}")

    q_edges = (
        "MATCH (ws:WikiSpace {business_id: $biz})-[:HAS_CHILD]->(n) "
        "RETURN labels(n)[0] AS lbl, count(*) AS cnt"
    )
    r2 = store._graph.query(q_edges, {"biz": business_id})
    print(f"Existing HAS_CHILD from WikiSpace: {r2.result_set}")

    if page_count == 0:
        print("No WikiPages found. Nothing to fix.")
        return

    q_space = (
        "MATCH (ws:WikiSpace {business_id: $biz}) "
        "RETURN ws.uid AS uid"
    )
    r_space = store._graph.query(q_space, {"biz": business_id})
    if not r_space.result_set:
        print(f"No WikiSpace found for business_id={business_id}")
        return
    space_uid = r_space.result_set[0][0]
    print(f"WikiSpace uid: {space_uid}")

    q_sections = (
        "MATCH (ws:WikiSpace {business_id: $biz})-[:HAS_CHILD*1..2]->(sec:WikiSection) "
        "RETURN sec.uid AS uid, sec.title AS title"
    )
    r_sec = store._graph.query(q_sections, {"biz": business_id})
    sections = {row[1]: row[0] for row in (r_sec.result_set or []) if row[0] and row[1]}
    print(f"Found {len(sections)} WikiSections")

    q_pages = (
        "MATCH (wp:WikiPage {repository: $biz}) "
        "OPTIONAL MATCH (parent)-[:HAS_CHILD]->(wp) "
        "WITH wp, parent WHERE parent IS NULL "
        "RETURN wp.uid AS uid, wp.title AS title, wp.path AS path"
    )
    r_pages = store._graph.query(q_pages, {"biz": business_id})
    unlinked = r_pages.result_set or []
    print(f"Unlinked WikiPages (no HAS_CHILD pointing to them): {len(unlinked)}")

    if not unlinked:
        print("All pages already linked. Nothing to fix.")
        return

    infra_section_uid = None
    for title, uid in sections.items():
        if "infra" in title.lower() or "__root__" in title:
            infra_section_uid = uid
            break

    if not infra_section_uid:
        infra_section_uid = f"WikiSection:{business_id}:__unlinked__"
        create_q = (
            "MERGE (sec:WikiSection {uid: $uid}) "
            "SET sec.title = 'Unlinked Pages', sec.section_type = 'code_structure', "
            "sec.auto_generated = true "
            "WITH sec "
            "MATCH (ws:WikiSpace {business_id: $biz}) "
            "MERGE (ws)-[:HAS_CHILD {view_type: 'code_structure', sort_order: 999}]->(sec)"
        )
        store._graph.query(create_q, {"uid": infra_section_uid, "biz": business_id})
        print(f"Created fallback section: {infra_section_uid}")

    linked = 0
    for i, row in enumerate(unlinked):
        page_uid = row[0]
        if not page_uid:
            continue
        link_q = (
            "MATCH (sec:WikiSection {uid: $sec_uid}) "
            "MATCH (wp:WikiPage {uid: $page_uid}) "
            "MERGE (sec)-[:HAS_CHILD {view_type: 'code_structure', sort_order: $idx}]->(wp)"
        )
        try:
            store._graph.query(link_q, {
                "sec_uid": infra_section_uid,
                "page_uid": page_uid,
                "idx": i,
            })
            linked += 1
        except Exception as e:
            print(f"  Failed to link {page_uid}: {e}")

    print(f"\nFixed: linked {linked}/{len(unlinked)} pages to section {infra_section_uid}")

    r3 = store._graph.query(q_edges, {"biz": business_id})
    print(f"Updated HAS_CHILD from WikiSpace: {r3.result_set}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-id", default="ultron")
    args = parser.parse_args()
    asyncio.run(main(args.business_id))
