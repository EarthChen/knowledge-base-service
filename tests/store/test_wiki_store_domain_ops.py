"""Tests for WikiStore domain management graph operations."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from store.wiki_store import WikiStore


@pytest.fixture
def mock_graph():
    graph = AsyncMock()
    graph.execute_query = AsyncMock()
    return graph


@pytest.fixture
def wiki_store(mock_graph):
    return WikiStore(mock_graph)


class TestRemoveHasChildEdge:
    @pytest.mark.asyncio
    async def test_removes_edge(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(data=[{"deleted": 1}])
        result = await wiki_store.remove_has_child_edge(
            parent_uid="parent1", child_uid="child1", view_type="business_domain",
        )
        assert result is True
        mock_graph.execute_query.assert_called_once()
        query = mock_graph.execute_query.call_args[0][0]
        assert "DELETE" in query
        assert "HAS_CHILD" in query

    @pytest.mark.asyncio
    async def test_returns_false_when_no_edge(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(data=[{"deleted": 0}])
        result = await wiki_store.remove_has_child_edge(
            parent_uid="parent1", child_uid="child1", view_type="business_domain",
        )
        assert result is False


class TestReparentChildren:
    @pytest.mark.asyncio
    async def test_reparents(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(data=[{"moved": 3}])
        result = await wiki_store.reparent_children(
            old_parent_uid="old", new_parent_uid="new", view_type="business_domain",
        )
        assert result == 3
        mock_graph.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_children(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(data=[])
        result = await wiki_store.reparent_children(
            old_parent_uid="old", new_parent_uid="new", view_type="business_domain",
        )
        assert result == 0


class TestDeleteWikiSectionCascade:
    @pytest.mark.asyncio
    async def test_deletes_root_and_optional_view_type_default(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(data=[{"deleted": 3}])
        result = await wiki_store.delete_wiki_section_cascade("section1")
        assert result == 3
        mock_graph.execute_query.assert_called_once()
        q, params = mock_graph.execute_query.call_args[0]
        assert "HAS_CHILD*0.." in q
        assert "DETACH DELETE d" in q
        assert params == {"uid": "section1", "vt": "business_domain"}

    @pytest.mark.asyncio
    async def test_deletes_passes_explicit_view_type(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(data=[{"deleted": 1}])
        result = await wiki_store.delete_wiki_section_cascade(
            "section1", view_type="other_view",
        )
        assert result == 1
        _q, params = mock_graph.execute_query.call_args[0]
        assert params["vt"] == "other_view"

    @pytest.mark.asyncio
    async def test_cascade_query_collects_self_and_descendants(self, wiki_store, mock_graph):
        """Pattern *0.. includes the source node plus all reachable HAS_CHILD nodes."""
        mock_graph.execute_query.return_value = MagicMock(data=[{"deleted": 1}])
        await wiki_store.delete_wiki_section_cascade("root_sec")
        q = mock_graph.execute_query.call_args[0][0]
        assert "MATCH (s {uid: $uid})-[:HAS_CHILD*0.. {view_type: $vt}]->(d)" in q
        assert "HAS_CHILD*0.." in q


class TestGetSectionParent:
    @pytest.mark.asyncio
    async def test_returns_parent_uid(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(
            data=[{"uid": "parent1"}],
        )
        result = await wiki_store.get_section_parent("child1", "business_domain")
        assert result == "parent1"

    @pytest.mark.asyncio
    async def test_returns_none_for_root(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(data=[])
        result = await wiki_store.get_section_parent("root1", "business_domain")
        assert result is None


class TestGetSectionChildren:
    @pytest.mark.asyncio
    async def test_returns_children(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(
            data=[
                {"uid": "c1", "title": "Child 1", "labels": ["WikiSection"]},
                {"uid": "c2", "title": "Child 2", "labels": ["WikiPage"]},
            ],
        )
        result = await wiki_store.get_section_children("parent1", "business_domain")
        assert len(result) == 2
        assert result[0]["uid"] == "c1"
        assert result[1]["title"] == "Child 2"


class TestGetSectionDescendants:
    @pytest.mark.asyncio
    async def test_returns_descendant_uids(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(
            data=[{"uid": "d1"}, {"uid": "d2"}],
        )
        result = await wiki_store.get_section_descendants("parent1", "business_domain")
        assert set(result) == {"d1", "d2"}
        q = mock_graph.execute_query.call_args[0][0]
        assert "HAS_CHILD*1.." in q
        assert "*1..10" not in q


class TestUpdateSectionProperties:
    @pytest.mark.asyncio
    async def test_updates(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(data=[{"updated": 1}])
        result = await wiki_store.update_section_properties(
            "section1", {"title": "New Title", "user_modified": True},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_empty_props(self, wiki_store, mock_graph):
        result = await wiki_store.update_section_properties("section1", {})
        assert result is False


class TestUpdateModuleBusinessDomain:
    @pytest.mark.asyncio
    async def test_updates(self, wiki_store, mock_graph):
        mock_graph.execute_query.return_value = MagicMock(data=[{"updated": 1}])
        result = await wiki_store.update_module_business_domain("mod1", "new-domain")
        assert result is True
