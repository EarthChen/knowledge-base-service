from __future__ import annotations


def test_build_file_tree_context_basic():
    from wiki.graph_domain_namer import _build_file_tree_context

    modules = [
        {"name": "RelationRankService", "path": "src/relation/rank/RelationRankService.java"},
        {"name": "RelationRankDao", "path": "src/relation/rank/RelationRankDao.java"},
        {"name": "RelationScoreCalc", "path": "src/relation/rank/RelationScoreCalc.java"},
    ]
    result = _build_file_tree_context(modules)
    assert "src/relation/rank" in result
    assert "RelationRankService.java" in result


def test_build_file_tree_context_empty():
    from wiki.graph_domain_namer import _build_file_tree_context

    result = _build_file_tree_context([])
    assert result == ""


def test_build_file_tree_context_no_paths():
    from wiki.graph_domain_namer import _build_file_tree_context

    modules = [{"name": "Foo", "path": ""}]
    result = _build_file_tree_context(modules)
    assert result == ""


def test_topology_label_majority():
    from wiki.graph_domain_namer import _topology_label

    modules = [
        {"name": "RelationRankService", "path": "src/relation/rank/RelationRankService.java"},
        {"name": "RelationRankDao", "path": "src/relation/rank/RelationRankDao.java"},
        {"name": "RelationScoreCalc", "path": "src/relation/score/RelationScoreCalc.java"},
        {"name": "UserProfileHelper", "path": "src/user/UserProfileHelper.java"},
    ]
    result = _topology_label(modules)
    assert result["slug_hint"] == "relation"
    assert result["confidence"] >= 0.7


def test_topology_label_no_majority():
    from wiki.graph_domain_namer import _topology_label

    modules = [
        {"name": "AlphaService", "path": "a/AlphaService.java"},
        {"name": "BetaHandler", "path": "b/BetaHandler.java"},
        {"name": "GammaDao", "path": "c/GammaDao.java"},
    ]
    result = _topology_label(modules)
    assert result["slug_hint"] == ""
    assert result["confidence"] < 0.4
