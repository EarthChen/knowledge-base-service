import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPersistClassificationNode:
    """Test the intermediate persistence node for domain classification."""

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
            "persistence": AsyncMock(),
        }

    @pytest.mark.asyncio
    async def test_persist_saves_mapping(self, mock_state):
        """The node should transform domain_mapping and save via persistence."""
        from wiki.nodes.persist_classification import persist_classification_node

        result = await persist_classification_node(mock_state)
        call_args = mock_state["persistence"].save_domain_classification.call_args
        assert call_args[0][0] == "biz1"
        save_mapping = call_args[0][1]
        assert "gift-system" in save_mapping
        assert save_mapping["gift-system"]["display_name"] == "礼物系统"
        assert ("repo1", "GiftSvc") in save_mapping["gift-system"]["modules"]
        assert save_mapping["im-messaging"]["display_name"] == "IM消息"
        assert result.get("classification_persisted") is True

    @pytest.mark.asyncio
    async def test_persist_handles_missing_persistence(self):
        """When persistence is not available, node should continue gracefully."""
        from wiki.nodes.persist_classification import persist_classification_node

        state = {
            "business_id": "biz1",
            "domain_mapping": {"test": [("repo1", "A")]},
        }
        result = await persist_classification_node(state)
        assert result.get("classification_persisted") is not True

    @pytest.mark.asyncio
    async def test_persist_handles_empty_mapping(self, mock_state):
        """Empty domain_mapping should be handled gracefully."""
        from wiki.nodes.persist_classification import persist_classification_node

        mock_state["domain_mapping"] = {}
        result = await persist_classification_node(mock_state)
        assert result is not None

    @pytest.mark.asyncio
    async def test_persist_handles_save_error(self, mock_state):
        """If save fails, the node should log and continue."""
        from wiki.nodes.persist_classification import persist_classification_node

        mock_state["persistence"].save_domain_classification.side_effect = Exception("DB error")
        result = await persist_classification_node(mock_state)
        assert result.get("classification_persisted") is not True
