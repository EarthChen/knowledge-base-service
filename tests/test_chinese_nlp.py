"""Chinese NLP preprocessing for hybrid query and wiki search."""

from query.hybrid_query import _extract_identifiers
from wiki.search import _extract_entity_names


def test_chinese_query_produces_tokens() -> None:
    q = "如何在用户登录后刷新会话令牌"
    ids = _extract_identifiers(q)
    assert len(ids) >= 2
    assert any("登录" in t or "会话" in t or "刷新" in t for t in ids)


def test_mixed_chinese_english_preserves_code_identifiers() -> None:
    q = "查找 UserService.authenticate 与用户登录的关系"
    ids = _extract_identifiers(q)
    assert any("UserService" in t or "authenticate" in t for t in ids)
    assert any("\u4e00" <= t[0] <= "\u9fff" for t in ids if t)


def test_pure_english_query_unchanged_pattern() -> None:
    q = "find the UserService authenticate method for login"
    ids = _extract_identifiers(q)
    assert "UserService" in ids
    assert "authenticate" in ids


def test_wiki_entity_names_chinese() -> None:
    q = "架构层与 OrderService 的关系"
    names = _extract_entity_names(q)
    assert "OrderService" in names
    assert len(names) >= 2


def test_wiki_entity_names_english_only() -> None:
    q = "FooBar and com.example.api.Handler"
    names = _extract_entity_names(q)
    assert any("FooBar" in n for n in names)
    assert any("com.example.api.Handler" in n for n in names)
