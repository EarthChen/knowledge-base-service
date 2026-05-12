import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


class TestDomainAPIEndpoints:
    """Test domain management REST API endpoints."""

    @pytest.fixture
    def mock_persistence(self):
        p = AsyncMock()
        p.list_domain_anchors = AsyncMock(return_value=[
            {"slug": "gift-system", "display_name": "礼物系统", "module_count": 5}
        ])
        p.upsert_domain_anchor = AsyncMock()
        p.delete_domain_anchor = AsyncMock()
        p.pin_module_to_domain = AsyncMock()
        p.unpin_module = AsyncMock()
        p.list_pinned_modules = AsyncMock(return_value=[
            {"module_name": "GiftSvc", "domain_slug": "gift-system"}
        ])
        p.get_checkpoint_info = AsyncMock(return_value={
            "business_id": "biz1",
            "last_modified": 1234567890.0,
            "size_bytes": 1024,
        })
        p.delete_checkpoint = AsyncMock()
        return p

    def test_list_domains_endpoint_exists(self):
        """Verify the list domains endpoint is registered."""
        from api.routes.wiki_page_routes import router
        paths = [r.path for r in router.routes]
        # Should have a domain listing endpoint
        assert any("domains" in p for p in paths if isinstance(p, str))

    def test_checkpoint_endpoint_exists(self):
        """Verify the checkpoint endpoint is registered."""
        from api.routes.wiki_page_routes import router
        paths = [r.path for r in router.routes]
        assert any("checkpoint" in p for p in paths if isinstance(p, str))
