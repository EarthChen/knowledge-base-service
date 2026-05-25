"""Tests for domain tree deduplication."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from wiki.dependency_graph import DomainNode, deduplicate_domain_tree


def _dn(name: str, slug: str = "", children: list | None = None) -> DomainNode:
    return DomainNode(name=name, slug=slug or name, children=children or [])


class TestDeduplicateDomainTree:
    def test_removes_top_level_duplicate_when_also_child(self):
        tree = [
            _dn("A"),
            _dn("B", children=[_dn("A")]),
        ]
        result = deduplicate_domain_tree(tree)
        assert len(result) == 1
        assert result[0].name == "B"
        assert len(result[0].children) == 1
        assert result[0].children[0].name == "A"

    def test_removes_self_nesting(self):
        tree = [_dn("A", children=[_dn("A")])]
        result = deduplicate_domain_tree(tree)
        assert len(result) == 1
        assert result[0].name == "A"
        assert len(result[0].children) == 0

    def test_no_duplicates_unchanged(self):
        tree = [_dn("A"), _dn("B", children=[_dn("C")])]
        result = deduplicate_domain_tree(tree)
        assert len(result) == 2
        assert result[0].name == "A"
        assert result[1].name == "B"

    def test_deep_nesting_duplicate(self):
        tree = [
            _dn("A"),
            _dn("B", children=[_dn("C", children=[_dn("A")])]),
        ]
        result = deduplicate_domain_tree(tree)
        assert len(result) == 1
        assert result[0].name == "B"

    def test_empty_tree(self):
        assert deduplicate_domain_tree([]) == []

    def test_slug_based_dedup(self):
        tree = [
            _dn("Intimacy Tasks", slug="intimacy"),
            _dn("Relationship Mgmt", children=[_dn("Intimacy Ops", slug="intimacy")]),
        ]
        result = deduplicate_domain_tree(tree)
        assert len(result) == 1
        assert result[0].name == "Relationship Mgmt"



class TestLinkLayerDefensiveDedup:
    @pytest.mark.asyncio
    async def test_duplicate_overview_slug_logged(self):
        """Verify linker skips duplicate overview pages for the same slug."""
        from wiki.tree_linker import WikiTreeLinker

        mock_store = AsyncMock()
        mock_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        mock_store.upsert_wiki_section = AsyncMock(return_value=MagicMock(data=[]))
        mock_store.add_has_child_edge = AsyncMock(return_value=MagicMock(data=[]))

        mock_persistence = AsyncMock()
        mock_persistence.persist_pages_to_graph = AsyncMock()

        linker = WikiTreeLinker(
            store=None,
            wiki_store=mock_store,
            wiki_cfg=MagicMock(business_domain_infrastructure_label="infra"),
            persistence=mock_persistence,
        )

        from wiki.tree_builder import WikiTreeBuilder

        tree_builder = WikiTreeBuilder()

        tree = [
            DomainNode(name="dom-a", slug="dom-a", modules=["mod1"]),
            DomainNode(
                name="dom-b",
                slug="dom-b",
                children=[
                    DomainNode(name="dom-a-child", slug="dom-a", modules=["mod2"]),
                ],
            ),
        ]

        await linker.link_pages_to_nested_tree(
            business_id="biz1",
            domain_tree=tree,
            pages_by_entity_uid={},
            tree_builder=tree_builder,
        )

        if mock_persistence.persist_pages_to_graph.called:
            call_args = mock_persistence.persist_pages_to_graph.call_args
            pages = call_args[0][1] if call_args[0] else call_args[1].get("pages", [])
            dom_a_overviews = [p for p in pages if "dom-a" in p.path and "_overview" in p.path]
            assert len(dom_a_overviews) <= 1, (
                f"Overview for dom-a should be generated at most once, got {len(dom_a_overviews)}"
            )
