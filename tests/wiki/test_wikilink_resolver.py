from wiki.wikilink_resolver import resolve_wikilinks


def test_resolves_known_entity():
    entity_index = {"AuthService": "/wiki/auth/AuthService"}
    content = "This module depends on [[AuthService]] for token validation."
    result = resolve_wikilinks(content, entity_index)
    assert "[AuthService](/wiki/auth/AuthService)" in result
    assert "[[AuthService]]" not in result


def test_preserves_unknown_entity():
    content = "Uses [[UnknownThing]] for something."
    result = resolve_wikilinks(content, {})
    assert "UnknownThing" in result
    assert "[[" not in result


def test_multiple_links():
    index = {"Auth": "/wiki/Auth", "DB": "/wiki/DB"}
    content = "Uses [[Auth]] and [[DB]] together."
    result = resolve_wikilinks(content, index)
    assert "[Auth](/wiki/Auth)" in result
    assert "[DB](/wiki/DB)" in result


def test_empty_content():
    result = resolve_wikilinks("", {})
    assert result == ""
