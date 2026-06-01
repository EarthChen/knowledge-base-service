from __future__ import annotations


def test_reparent_moves_misplaced_module():
    from wiki.domain_semantic_clusterer import DomainSemanticClusterer

    clusterer = DomainSemanticClusterer.__new__(DomainSemanticClusterer)
    clusters = [
        {("repo", "FamilyTaskService"), ("repo", "FamilyRewardService"), ("repo", "FamilyManager")},
        {("repo", "RelationRankService"), ("repo", "RelationScoreDao"), ("repo", "RelationFamilyTaskService")},
    ]
    paths = {
        "FamilyTaskService": "src/family/FamilyTaskService.java",
        "FamilyRewardService": "src/family/FamilyRewardService.java",
        "FamilyManager": "src/family/FamilyManager.java",
        "RelationRankService": "src/relation/rank/RelationRankService.java",
        "RelationScoreDao": "src/relation/rank/RelationScoreDao.java",
        "RelationFamilyTaskService": "src/family/task/RelationFamilyTaskService.java",
    }
    result = clusterer._post_cluster_reparent(clusters, [], paths)
    # RelationFamilyTaskService should move to family cluster because:
    # 1. Its prefix ("relation") doesn't match family cluster's dominant prefix ("family")
    # 2. BUT its path ("src/family/task/...") matches family cluster's path pattern
    # Both conditions (prefix divergence + path affinity) must be met for reparenting
    family_cluster = next(c for c in result if ("repo", "FamilyTaskService") in c)
    assert ("repo", "RelationFamilyTaskService") in family_cluster


def test_reparent_no_move_when_no_clear_majority():
    from wiki.domain_semantic_clusterer import DomainSemanticClusterer

    clusterer = DomainSemanticClusterer.__new__(DomainSemanticClusterer)
    clusters = [
        {("repo", "AlphaService"), ("repo", "BetaHandler")},
        {("repo", "GammaDao"), ("repo", "DeltaManager")},
    ]
    paths = {}
    result = clusterer._post_cluster_reparent(clusters, [], paths)
    assert len(result[0]) == 2
    assert len(result[1]) == 2
