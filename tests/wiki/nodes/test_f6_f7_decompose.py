"""Tests for F6 (shell collapse + infra reclassification) and F7 (garbage slug fix)."""

from __future__ import annotations

from core.config import get_settings
from wiki.nodes.graph_domain_decompose import (
    _collapse_empty_shells,
    _is_infra_slug,
    _is_low_quality_slug,
    _review_subdomain_placement,
)


def _node(
    name: str,
    *,
    modules: list[str] | None = None,
    children: list[dict] | None = None,
    display_name: str | None = None,
    has_overview: bool = False,
) -> dict:
    n: dict = {
        "name": name,
        "display_name": display_name or name,
        "modules": modules if modules is not None else [],
        "children": children or [],
    }
    if has_overview:
        n["has_overview"] = True
    return n


class TestInfraSlugKeywords:
    def test_infra_slug_detected_type_mapping(self) -> None:
        keywords = get_settings().wiki.infrastructure_slug_keywords
        assert "type-mapping" in keywords
        modules = [("repo", "DataTypeMappingHandler")]
        assert _is_infra_slug("data-type-mapping", modules, keywords)

    def test_infra_slug_detected_mybatis(self) -> None:
        keywords = get_settings().wiki.infrastructure_slug_keywords
        assert "mybatis" in keywords
        modules = [("repo", "MybatisInterceptor")]
        assert _is_infra_slug("mybatis-config", modules, keywords)


class TestCollapseMultiChildShells:
    def test_collapse_multi_child_shell_sections(self) -> None:
        parent = _node(
            "parent-real",
            modules=["m1", "m2", "m3"],
            children=[
                _node(
                    "shell-container",
                    children=[
                        _node("child-one", modules=["a", "b", "c"]),
                        _node("child-two", modules=["d", "e", "f"]),
                    ],
                ),
            ],
        )
        result = _collapse_empty_shells([parent])
        assert len(result) == 1
        parent_out = result[0]
        assert parent_out["name"] == "parent-real"
        child_names = [c["name"] for c in parent_out["children"]]
        assert "shell-container" not in child_names
        assert "child-one" in child_names
        assert "child-two" in child_names

    def test_collapse_keeps_non_shell_sections(self) -> None:
        parent = _node(
            "overview-domain",
            has_overview=True,
            children=[
                _node("child-one", modules=["a", "b", "c"]),
                _node("child-two", modules=["d", "e", "f"]),
            ],
        )
        result = _collapse_empty_shells([parent])
        assert len(result) == 1
        assert result[0]["name"] == "overview-domain"
        assert len(result[0]["children"]) == 2


class TestLowQualitySlug:
    def test_long_slug_detected_as_low_quality(self) -> None:
        slug = "family-square-back-door-serv-family-at-grou"
        assert _is_low_quality_slug(slug)

    def test_short_clean_slug_not_flagged(self) -> None:
        assert not _is_low_quality_slug("family-system")

    def test_camel_case_slug_detected(self) -> None:
        assert _is_low_quality_slug("familySquare-back-door")


class TestInfraReparent:
    def test_infra_reparented_to_root(self) -> None:
        keywords = get_settings().wiki.infrastructure_slug_keywords
        tree = [
            _node(
                "family-task",
                modules=["m1", "m2", "m3"],
                children=[_node("data-type-mapping", modules=["t1", "t2"])],
            ),
        ]
        _review_subdomain_placement(tree, infrastructure_keywords=keywords)
        root_names = [n["name"] for n in tree]
        assert "data-type-mapping" in root_names
        family = next(n for n in tree if n["name"] == "family-task")
        child_names = [c["name"] for c in family.get("children", [])]
        assert "data-type-mapping" not in child_names
