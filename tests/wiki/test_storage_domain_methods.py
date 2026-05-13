import pytest
from unittest.mock import AsyncMock, MagicMock


class TestStorageDomainMethods:
    """Test domain management storage methods.
    
    These tests mock the graph store to verify the correct Cypher queries
    are executed and results are properly transformed.
    """

    @pytest.fixture
    def mock_graph_store(self):
        store = AsyncMock()
        store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        return store

    @pytest.mark.asyncio
    async def test_list_domain_anchors(self, mock_graph_store):
        """list_domain_anchors should return domains with slug + display_name."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        
        mock_graph_store.execute_query.return_value = MagicMock(data=[
            {"slug": "gift-system", "display_name": "礼物系统", "module_count": 5}
        ])
        result = await p.list_domain_anchors("biz1")
        assert len(result) == 1
        assert result[0]["slug"] == "gift-system"
        assert result[0]["display_name"] == "礼物系统"

    @pytest.mark.asyncio
    async def test_upsert_domain_anchor(self, mock_graph_store):
        """upsert_domain_anchor should MERGE a DomainAnchor node."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        
        await p.upsert_domain_anchor("biz1", "gift-system", "礼物系统")
        mock_graph_store.execute_query.assert_called_once()
        call_args = mock_graph_store.execute_query.call_args
        cypher = call_args[0][0] if call_args[0] else call_args[1].get("query", "")
        assert "MERGE" in cypher

    @pytest.mark.asyncio
    async def test_delete_domain_anchor(self, mock_graph_store):
        """delete_domain_anchor should DETACH DELETE the anchor."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        
        await p.delete_domain_anchor("biz1", "gift-system")
        mock_graph_store.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_pin_module_to_domain(self, mock_graph_store):
        """pin_module_to_domain should scope via DomainAnchor.business_id."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        
        await p.pin_module_to_domain("biz1", "com.example.Svc", "gift-system")
        mock_graph_store.execute_query.assert_called_once()
        call_args = mock_graph_store.execute_query.call_args
        cypher = call_args[0][0] if call_args[0] else call_args[1].get("query", "")
        assert "domain_pinned" in cypher
        assert "business_id" in cypher or "bid" in str(call_args)

    @pytest.mark.asyncio
    async def test_unpin_module(self, mock_graph_store):
        """unpin_module should scope via DomainAnchor.business_id."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        
        await p.unpin_module("biz1", "com.example.Svc")
        mock_graph_store.execute_query.assert_called_once()
        call_args = mock_graph_store.execute_query.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params.get("bid") == "biz1"

    @pytest.mark.asyncio
    async def test_list_pinned_modules(self, mock_graph_store):
        """list_pinned_modules should scope via DomainAnchor.business_id."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        
        mock_graph_store.execute_query.return_value = MagicMock(data=[
            {"module_name": "com.example.Svc", "domain_slug": "gift-system"}
        ])
        result = await p.list_pinned_modules("biz1")
        assert len(result) == 1
        assert result[0]["module_name"] == "com.example.Svc"
        call_args = mock_graph_store.execute_query.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params.get("bid") == "biz1"

    @pytest.mark.asyncio
    async def test_list_domain_modules(self, mock_graph_store):
        """list_domain_modules should return modules for a specific domain."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)

        mock_graph_store.execute_query.return_value = MagicMock(data=[
            {"name": "PaymentService", "repository": "my-repo", "path": "src/pay", "pinned": True},
            {"name": "OrderService", "repository": "my-repo", "path": "src/order", "pinned": False},
        ])

        result = await p.list_domain_modules("biz1", "payment")
        assert len(result) == 2
        assert result[0]["name"] == "PaymentService"
        assert result[0]["pinned"] is True
        mock_graph_store.execute_query.assert_called_once()
        call_args = mock_graph_store.execute_query.call_args
        params = call_args[0][1]
        assert params["bid"] == "biz1"
        assert params["slug"] == "payment"

    @pytest.mark.asyncio
    async def test_rename_domain(self, mock_graph_store):
        """rename_domain should update DomainAnchor slug and Module.domain_slug."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)

        mock_graph_store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[{"cnt": 1}]),
                MagicMock(data=[{"cnt": 0}]),
                MagicMock(),
                MagicMock(),
            ]
        )

        ok = await p.rename_domain("biz1", "old-slug", "new-slug", "New Display")
        assert ok is True
        assert mock_graph_store.execute_query.call_count == 4

        update_anchor = mock_graph_store.execute_query.call_args_list[2]
        assert "SET d.slug = $new" in update_anchor[0][0]

        update_modules = mock_graph_store.execute_query.call_args_list[3]
        assert update_modules[0][1]["old"] == "old-slug"
        assert update_modules[0][1]["new"] == "new-slug"

    @pytest.mark.asyncio
    async def test_rename_domain_not_found(self, mock_graph_store):
        """rename_domain returns False when old_slug does not exist."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        mock_graph_store.execute_query = AsyncMock(
            return_value=MagicMock(data=[{"cnt": 0}]),
        )
        ok = await p.rename_domain("biz1", "missing", "new-slug", "X")
        assert ok is False
        mock_graph_store.execute_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rename_domain_collision(self, mock_graph_store):
        """rename_domain raises when new_slug is already taken."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        mock_graph_store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[{"cnt": 1}]),
                MagicMock(data=[{"cnt": 1}]),
            ]
        )
        with pytest.raises(ValueError, match="already exists"):
            await p.rename_domain("biz1", "old-slug", "taken-slug", "Display")
        assert mock_graph_store.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_save_domain_classification_clears_stale_edges(self, mock_graph_store):
        """save_domain_classification should clear old BELONGS_TO_DOMAIN before linking."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        
        mapping = {
            "gift-system": {
                "slug": "gift-system",
                "display_name": "礼物系统",
                "modules": [("repo1", "com.example.GiftSvc")]
            }
        }
        await p.save_domain_classification("biz1", mapping)
        # First call: clear stale edges; then upsert + link
        assert mock_graph_store.execute_query.call_count >= 2
        first_cypher = mock_graph_store.execute_query.call_args_list[0][0][0]
        assert "DELETE" in first_cypher

    @pytest.mark.asyncio
    async def test_save_domain_classification_empty_mapping(self, mock_graph_store):
        """save_domain_classification with empty mapping should not crash."""
        from wiki.persistence import WikiPersistence
        p = WikiPersistence(mock_graph_store)
        
        await p.save_domain_classification("biz1", {})
        # No modules → no clear call needed, no upsert calls
        assert mock_graph_store.execute_query.call_count == 0

    def test_sanitize_business_id_path_traversal(self):
        """business_id with path traversal chars should be sanitized."""
        from wiki.persistence import WikiPersistence
        result = WikiPersistence._sanitize_business_id("../../../etc")
        assert ".." not in result and "/" not in result
        assert WikiPersistence._sanitize_business_id("normal-biz_1") == "normal-biz_1"
        assert WikiPersistence._sanitize_business_id("biz/secret") == "biz_secret"
