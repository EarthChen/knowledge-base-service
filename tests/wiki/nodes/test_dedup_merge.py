from __future__ import annotations


def test_slug_collision_merges_instead_of_suffix():
    from wiki.nodes.graph_domain_decompose import _dedup_parallel_naming_results

    results = [
        {"slug": "relation-rank", "display_name": "关系排名", "modules": ["RankService"]},
        {"slug": "relation-rank", "display_name": "关系排名服务", "modules": ["RankDao"]},
    ]
    deduped = _dedup_parallel_naming_results(results, [])
    assert len(deduped) == 1
    assert deduped[0]["slug"] == "relation-rank"
    assert "RankService" in deduped[0]["modules"]
    assert "RankDao" in deduped[0]["modules"]


def test_stem_suffix_merge():
    from wiki.nodes.graph_domain_decompose import _dedup_parallel_naming_results

    results = [
        {"slug": "quick-message", "display_name": "快捷消息", "modules": ["QuickMsg"]},
        {"slug": "quick-message-service", "display_name": "快捷消息服务", "modules": ["QuickMsgSvc"]},
    ]
    deduped = _dedup_parallel_naming_results(results, [])
    assert len(deduped) == 1
    assert deduped[0]["slug"] == "quick-message"


def test_collision_with_existing_slugs_uses_numeric():
    from wiki.nodes.graph_domain_decompose import _dedup_parallel_naming_results

    results = [
        {"slug": "auth", "display_name": "认证", "modules": ["AuthSvc"]},
    ]
    deduped = _dedup_parallel_naming_results(results, ["auth"])
    assert len(deduped) == 1
    assert deduped[0]["slug"] == "auth-2"


def test_no_collision_passes_through():
    from wiki.nodes.graph_domain_decompose import _dedup_parallel_naming_results

    results = [
        {"slug": "user-profile", "display_name": "用户资料", "modules": ["UserProfile"]},
        {"slug": "family-system", "display_name": "家族系统", "modules": ["FamilySvc"]},
    ]
    deduped = _dedup_parallel_naming_results(results, [])
    assert len(deduped) == 2
