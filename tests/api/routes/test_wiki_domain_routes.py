"""Tests for wiki domain management API routes."""
import pytest
from unittest.mock import AsyncMock, patch


def _biz_sec(business_id: str, slug: str) -> str:
    return f"WikiSection:{business_id}:domain:{slug}"


@pytest.fixture
def mock_domain_service():
    svc = AsyncMock()
    s1 = _biz_sec("biz1", "s1")
    p2 = _biz_sec("biz1", "p2")
    s_new = _biz_sec("biz1", "s_new")
    t1 = _biz_sec("biz1", "t1")
    svc.rename_domain = AsyncMock(return_value={"success": True, "section_uid": s1})
    svc.delete_domain = AsyncMock(return_value={"success": True, "section_uid": s1})
    svc.create_subdomain = AsyncMock(
        return_value={"success": True, "section_uid": s_new}
    )
    svc.move_domain = AsyncMock(
        return_value={
            "success": True,
            "section_uid": s1,
            "new_parent_uid": p2,
        }
    )
    svc.merge_domains = AsyncMock(return_value={"success": True, "target_uid": t1})
    svc.move_module_domain = AsyncMock(
        return_value={"success": True, "module_uid": "m1", "domain": "d1"}
    )
    return svc


class TestRenameDomainRoute:
    @pytest.mark.asyncio
    async def test_rename_success(self, mock_domain_service):
        from api.routes.wiki_domain_routes import rename_domain, UpdateDomainBody
        body = UpdateDomainBody(title="New Title")
        with patch("api.routes.wiki_domain_routes._get_domain_service", return_value=mock_domain_service):
            result = await rename_domain(
                _biz_sec("biz1", "s1"), body, business_id="biz1"
            )
        assert result["success"] is True
        mock_domain_service.rename_domain.assert_called_once()


class TestDeleteDomainRoute:
    @pytest.mark.asyncio
    async def test_delete_success(self, mock_domain_service):
        from api.routes.wiki_domain_routes import delete_domain
        with patch("api.routes.wiki_domain_routes._get_domain_service", return_value=mock_domain_service):
            result = await delete_domain(
                _biz_sec("biz1", "s1"), promote_children=True, business_id="biz1"
            )
        assert result["success"] is True
        mock_domain_service.delete_domain.assert_called_once()


class TestMoveDomainRoute:
    @pytest.mark.asyncio
    async def test_move_success(self, mock_domain_service):
        from api.routes.wiki_domain_routes import move_domain, MoveDomainBody
        body = MoveDomainBody(target_parent_uid=_biz_sec("biz1", "p2"))
        with patch("api.routes.wiki_domain_routes._get_domain_service", return_value=mock_domain_service):
            result = await move_domain(
                _biz_sec("biz1", "s1"), body, business_id="biz1"
            )
        assert result["success"] is True
        mock_domain_service.move_domain.assert_called_once()


class TestMergeDomainsRoute:
    @pytest.mark.asyncio
    async def test_merge_success(self, mock_domain_service):
        from api.routes.wiki_domain_routes import merge_domains, MergeDomainBody
        body = MergeDomainBody(
            source_uid=_biz_sec("biz1", "src"),
            target_uid=_biz_sec("biz1", "tgt"),
        )
        with patch("api.routes.wiki_domain_routes._get_domain_service", return_value=mock_domain_service):
            result = await merge_domains(body, business_id="biz1")
        assert result["success"] is True
        mock_domain_service.merge_domains.assert_called_once()


class TestCreateSubdomainRoute:
    @pytest.mark.asyncio
    async def test_create_success(self, mock_domain_service):
        from api.routes.wiki_domain_routes import create_subdomain, CreateSubdomainBody
        body = CreateSubdomainBody(title="Sub Domain")
        with patch("api.routes.wiki_domain_routes._get_domain_service", return_value=mock_domain_service):
            result = await create_subdomain(
                _biz_sec("biz1", "p1"), body, business_id="biz1"
            )
        assert result["success"] is True
        mock_domain_service.create_subdomain.assert_called_once()


class TestMoveModuleDomainRoute:
    @pytest.mark.asyncio
    async def test_move_module_success(self, mock_domain_service):
        from api.routes.wiki_domain_routes import move_module_domain, MoveModuleDomainBody
        body = MoveModuleDomainBody(module_uid="m1", target_domain="d1")
        with patch("api.routes.wiki_domain_routes._get_domain_service", return_value=mock_domain_service):
            result = await move_module_domain(body, business_id="biz1")
        assert result["success"] is True
        mock_domain_service.move_module_domain.assert_called_once()
