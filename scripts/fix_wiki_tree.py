"""One-time repair: create HAS_CHILD edges from WikiSection to WikiPage.

Fixes orphaned WikiPage nodes that were persisted without tree structure edges.
"""

import sys
import time

import redis


def main() -> None:
    r = redis.Redis(host="localhost", port=6379)
    g = "kb_default"
    business_id = "default"

    result = r.execute_command(
        "GRAPH.QUERY", g,
        "MATCH (wp:WikiPage) "
        "RETURN wp.uid AS uid, wp.repository AS repo "
        "ORDER BY wp.repository, wp.path",
    )

    pages: list[tuple[str, str]] = []
    for row in result[1]:
        uid = row[0].decode() if isinstance(row[0], bytes) else str(row[0])
        repo = row[1].decode() if isinstance(row[1], bytes) else str(row[1]) if row[1] else ""
        pages.append((uid, repo))

    print(f"Total WikiPages: {len(pages)}")

    pages_by_repo: dict[str, list[str]] = {}
    for uid, repo in pages:
        if repo:
            pages_by_repo.setdefault(repo, []).append(uid)

    print(f"Repos to link: {len(pages_by_repo)}")
    t0 = time.time()

    # 1) code_structure: WikiSection:repo -> WikiPage
    code_linked = 0
    code_errors = 0
    for repo, page_uids in pages_by_repo.items():
        if repo == "default":
            continue
        section_uid = f"WikiSection:{business_id}:repo:{repo}"
        for idx, page_uid in enumerate(page_uids):
            try:
                q = (
                    f'CYPHER section_uid="{section_uid}" '
                    f'page_uid="{page_uid}" '
                    f"sort_order={idx} "
                    "MATCH (s:WikiSection {uid: $section_uid}) "
                    "MATCH (w:WikiPage {uid: $page_uid}) "
                    'MERGE (s)-[e:HAS_CHILD {view_type: "code_structure"}]->(w) '
                    "SET e.sort_order = $sort_order "
                    "RETURN type(e) AS rel"
                )
                r.execute_command("GRAPH.QUERY", g, q)
                code_linked += 1
            except Exception as e:
                code_errors += 1
                if code_errors <= 5:
                    print(f"  code_structure error [{repo}] {page_uid}: {e}")

    print(
        f"code_structure linked: {code_linked}, errors: {code_errors}, "
        f"elapsed: {time.time() - t0:.1f}s"
    )

    # 2) business_domain: WikiSection:domain:__infrastructure__ -> WikiPage
    t1 = time.time()
    domain_section_uid = f"WikiSection:{business_id}:domain:__infrastructure__"
    domain_linked = 0
    domain_errors = 0

    all_page_uids = [uid for uid, repo in pages if repo]
    for idx, page_uid in enumerate(all_page_uids):
        try:
            q = (
                f'CYPHER section_uid="{domain_section_uid}" '
                f'page_uid="{page_uid}" '
                f"sort_order={idx} "
                "MATCH (s:WikiSection {uid: $section_uid}) "
                "MATCH (w:WikiPage {uid: $page_uid}) "
                'MERGE (s)-[e:HAS_CHILD {view_type: "business_domain"}]->(w) '
                "SET e.sort_order = $sort_order "
                "RETURN type(e) AS rel"
            )
            r.execute_command("GRAPH.QUERY", g, q)
            domain_linked += 1
        except Exception as e:
            domain_errors += 1
            if domain_errors <= 5:
                print(f"  business_domain error {page_uid}: {e}")

    print(
        f"business_domain linked: {domain_linked}, errors: {domain_errors}, "
        f"elapsed: {time.time() - t1:.1f}s"
    )
    print(f"Total elapsed: {time.time() - t0:.1f}s")

    verify = r.execute_command(
        "GRAPH.QUERY", g,
        "MATCH ()-[e:HAS_CHILD]->() RETURN e.view_type AS vt, count(e) AS cnt",
    )
    print(f"Verification - HAS_CHILD counts: {verify[1]}")


if __name__ == "__main__":
    main()
