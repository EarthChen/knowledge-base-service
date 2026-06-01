from __future__ import annotations


def test_common_camel_prefix_basic():
    from wiki.domain_doc_agent import _common_camel_prefix

    result = _common_camel_prefix(["RelationRankService", "RelationRankDao", "RelationRankCalc"])
    assert result == "RelationRank"


def test_common_camel_prefix_single_word():
    from wiki.domain_doc_agent import _common_camel_prefix

    result = _common_camel_prefix(["UserService", "UserDao"])
    assert result == ""


def test_common_camel_prefix_no_common():
    from wiki.domain_doc_agent import _common_camel_prefix

    result = _common_camel_prefix(["AlphaService", "BetaHandler"])
    assert result == ""


def test_common_camel_prefix_empty():
    from wiki.domain_doc_agent import _common_camel_prefix

    result = _common_camel_prefix([])
    assert result == ""
