import pytest
from unittest.mock import AsyncMock


class TestPersistClassificationNode:
    """Test the intermediate persistence node for domain classification."""

    @pytest.fixture
    def mock_wiki_store(self):
        store = AsyncMock()
        store.upsert_wiki_space = AsyncMock()
        store.upsert_wiki_section = AsyncMock()
        store.add_has_child_edge = AsyncMock()
        store.persist_pipeline_domain_tree = AsyncMock()
        return store

    @pytest.fixture
    def mock_graph_store(self):
        store = AsyncMock()
        store.update_node_property = AsyncMock()
        return store

    @pytest.fixture
    def mock_state(self):
        return {
            "business_id": "biz1",
            "domain_mapping": {
                "gift-system": [("repo1", "GiftSvc"), ("repo1", "GiftDao")],
                "im-messaging": [("repo1", "MsgSvc")],
            },
            "domain_display_names": {
                "gift-system": "礼物系统",
                "im-messaging": "IM消息",
            },
            "modules": {
                "repo1": [
                    {"uid": "Module:repo1:GiftSvc", "label": "Module", "properties": {"name": "GiftSvc"}},
                    {"uid": "Module:repo1:GiftDao", "label": "Module", "properties": {"name": "GiftDao"}},
                    {"uid": "Module:repo1:MsgSvc", "label": "Module", "properties": {"name": "MsgSvc"}},
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_persist_creates_wiki_sections(self, mock_state, mock_wiki_store, mock_graph_store):
        """The node should create WikiSpace + WikiSection for each domain."""
        from wiki.nodes.persist_classification import persist_classification_node

        config = {"configurable": {"wiki_store": mock_wiki_store, "graph_store": mock_graph_store}}
        result = await persist_classification_node(mock_state, config)

        mock_wiki_store.upsert_wiki_space.assert_called_once()
        assert mock_wiki_store.upsert_wiki_section.call_count >= 2
        assert result.get("classification_persisted") is True

    @pytest.mark.asyncio
    async def test_persist_flat_domains_creates_has_child_edges(self, mock_state, mock_wiki_store, mock_graph_store):
        """Flat domain mapping should create HAS_CHILD edges from space to sections."""
        from wiki.nodes.persist_classification import persist_classification_node

        config = {"configurable": {"wiki_store": mock_wiki_store, "graph_store": mock_graph_store}}
        await persist_classification_node(mock_state, config)

        edge_calls = mock_wiki_store.add_has_child_edge.call_args_list
        parent_uids = [c.kwargs.get("parent_uid") for c in edge_calls]
        assert any("WikiSpace:biz1" in (uid or "") for uid in parent_uids)

    @pytest.mark.asyncio
    async def test_persist_nested_tree_creates_root_section(self, mock_state, mock_wiki_store, mock_graph_store):
        """Nested domain tree should create __root__ section and recurse."""
        from wiki.nodes.persist_classification import persist_classification_node

        mock_state["domain_tree"] = [
            {
                "name": "gift-system",
                "slug": "gift-system",
                "display_name": "礼物系统",
                "description": "",
                "modules": ["GiftSvc", "GiftDao"],
                "children": [],
            },
            {
                "name": "im-messaging",
                "slug": "im-messaging",
                "display_name": "IM消息",
                "description": "",
                "modules": ["MsgSvc"],
                "children": [],
            },
        ]

        config = {"configurable": {"wiki_store": mock_wiki_store, "graph_store": mock_graph_store}}
        await persist_classification_node(mock_state, config)

        section_calls = mock_wiki_store.upsert_wiki_section.call_args_list
        titles = [c.kwargs.get("title") for c in section_calls]
        assert "__root__" in titles
        assert "礼物系统" in titles
        assert "IM消息" in titles

    @pytest.mark.asyncio
    async def test_persist_sets_module_domain_labels(self, mock_state, mock_wiki_store, mock_graph_store):
        """Module nodes should have business_domain property set."""
        from wiki.nodes.persist_classification import persist_classification_node

        config = {"configurable": {"wiki_store": mock_wiki_store, "graph_store": mock_graph_store}}
        await persist_classification_node(mock_state, config)

        assert mock_graph_store.update_node_property.call_count >= 3

    @pytest.mark.asyncio
    async def test_persist_handles_no_wiki_store(self, mock_state):
        """When wiki_store is not available, node should continue gracefully."""
        from wiki.nodes.persist_classification import persist_classification_node

        result = await persist_classification_node(mock_state)
        assert result.get("classification_persisted") is False

    @pytest.mark.asyncio
    async def test_persist_handles_empty_mapping(self):
        """Empty domain_mapping should return early."""
        from wiki.nodes.persist_classification import persist_classification_node

        state = {"business_id": "biz1", "domain_mapping": {}}
        result = await persist_classification_node(state)
        assert result.get("classification_persisted") is False

    @pytest.mark.asyncio
    async def test_persist_handles_wiki_store_error(self, mock_state, mock_wiki_store, mock_graph_store):
        """If wiki_store fails, the node should log and continue."""
        from wiki.nodes.persist_classification import persist_classification_node

        mock_wiki_store.upsert_wiki_space.side_effect = Exception("DB error")
        config = {"configurable": {"wiki_store": mock_wiki_store, "graph_store": mock_graph_store}}
        result = await persist_classification_node(mock_state, config)
        assert result is not None
