import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPersistClassificationNode:
    """Test the intermediate persistence node for domain classification."""

    @pytest.fixture
    def mock_state(self):
        return {
            "business_id": "biz1",
            "domain_mapping": {
                "gift-system": {
                    "slug": "gift-system",
                    "display_name": "礼物系统",
                    "modules": [("repo1", "GiftSvc"), ("repo1", "GiftDao")],
                },
                "im-messaging": {
                    "slug": "im-messaging",
                    "display_name": "IM消息",
                    "modules": [("repo1", "MsgSvc")],
                },
            },
            "persistence": AsyncMock(),
        }

    @pytest.mark.asyncio
    async def test_persist_saves_mapping(self, mock_state):
        """The node should save domain_mapping via persistence."""
        from wiki.nodes.persist_classification import persist_classification_node

        result = await persist_classification_node(mock_state)
        mock_state["persistence"].save_domain_classification.assert_called_once_with(
            "biz1", mock_state["domain_mapping"]
        )
        assert result.get("classification_persisted") is True

    @pytest.mark.asyncio
    async def test_persist_handles_missing_persistence(self):
        """When persistence is not available, node should continue gracefully."""
        from wiki.nodes.persist_classification import persist_classification_node

        state = {
            "business_id": "biz1",
            "domain_mapping": {"test": {"slug": "test", "modules": []}},
        }
        result = await persist_classification_node(state)
        # Should not raise, classification_persisted should be False or missing
        assert result.get("classification_persisted") is not True

    @pytest.mark.asyncio
    async def test_persist_handles_empty_mapping(self, mock_state):
        """Empty domain_mapping should be handled gracefully."""
        from wiki.nodes.persist_classification import persist_classification_node

        mock_state["domain_mapping"] = {}
        result = await persist_classification_node(mock_state)
        # Should still call save with empty mapping
        assert result is not None

    @pytest.mark.asyncio
    async def test_persist_handles_save_error(self, mock_state):
        """If save fails, the node should log and continue."""
        from wiki.nodes.persist_classification import persist_classification_node

        mock_state["persistence"].save_domain_classification.side_effect = Exception("DB error")
        result = await persist_classification_node(mock_state)
        # Should not raise
        assert result.get("classification_persisted") is not True
