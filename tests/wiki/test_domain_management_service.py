"""Tests for DomainManagementService."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.domain_management_service import DomainManagementService


@pytest.fixture
def mock_wiki_store():
    store = AsyncMock()
    store.update_section_properties = AsyncMock(return_value=True)
    store.get_section_parent = AsyncMock(
        return_value="WikiSection:biz1:domain:parent_uid"
    )
    store.get_section_children = AsyncMock(return_value=[])
    store.get_section_descendants = AsyncMock(return_value=[])
    store.remove_has_child_edge = AsyncMock(return_value=True)
    store.reparent_children = AsyncMock(return_value=2)
    store.delete_wiki_section_cascade = AsyncMock(return_value=1)
    store.add_has_child_edge = AsyncMock()
    store.upsert_wiki_section = AsyncMock()
    store.update_module_business_domain = AsyncMock(return_value=True)
    store.update_descendant_pages_business_domain = AsyncMock(return_value=3)
    store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    return store


@pytest.fixture
def service(mock_wiki_store):
    return DomainManagementService(wiki_store=mock_wiki_store)

def _sec(slug: str) -> str:
    return f"WikiSection:biz1:domain:{slug}"


class TestRenameDomain:
    @pytest.mark.asyncio
    async def test_rename_success(self, service, mock_wiki_store):
        result = await service.rename_domain(
            "biz1", _sec("section1"), "New Title", "New desc"
        )
        assert result["success"] is True
        mock_wiki_store.update_section_properties.assert_called_once()
        call_props = mock_wiki_store.update_section_properties.call_args[0][1]
        assert call_props["title"] == "New Title"
        assert call_props["user_modified"] is True

    @pytest.mark.asyncio
    async def test_rename_rejects_root(self, service):
        with pytest.raises(ValueError, match="root"):
            await service.rename_domain(
                "biz1", "WikiSection:biz1:domain:__root__", "X"
            )

    @pytest.mark.asyncio
    async def test_rename_rejects_foreign_business(self, service):
        with pytest.raises(ValueError, match="does not belong"):
            await service.rename_domain(
                "biz1", "WikiSection:other_biz:domain:x", "X"
            )


class TestDeleteDomain:
    @pytest.mark.asyncio
    async def test_delete_promote_children(self, service, mock_wiki_store):
        mock_wiki_store.get_section_parent.return_value = _sec("parent_uid")
        result = await service.delete_domain(
            "biz1", _sec("section1"), promote_children=True
        )
        assert result["success"] is True
        mock_wiki_store.reparent_children.assert_called_once()
        mock_wiki_store.delete_wiki_section_cascade.assert_called_once_with(
            _sec("section1"), "business_domain",
        )

    @pytest.mark.asyncio
    async def test_delete_cascade(self, service, mock_wiki_store):
        result = await service.delete_domain(
            "biz1", _sec("section1"), promote_children=False
        )
        assert result["success"] is True
        mock_wiki_store.delete_wiki_section_cascade.assert_called_once_with(
            _sec("section1"), "business_domain",
        )

    @pytest.mark.asyncio
    async def test_delete_rejects_root(self, service):
        with pytest.raises(ValueError, match="root"):
            await service.delete_domain(
                "biz1", "WikiSection:biz1:domain:__root__"
            )


class TestMoveDomain:
    @pytest.mark.asyncio
    async def test_move_success(self, service, mock_wiki_store):
        mock_wiki_store.get_section_descendants.return_value = []
        mock_wiki_store.get_section_parent.return_value = _sec("old_parent")
        result = await service.move_domain(
            "biz1", _sec("section1"), _sec("target_parent")
        )
        assert result["success"] is True
        mock_wiki_store.remove_has_child_edge.assert_called_once()
        mock_wiki_store.add_has_child_edge.assert_called_once()

    @pytest.mark.asyncio
    async def test_move_rejects_self(self, service):
        with pytest.raises(ValueError, match="Cannot move"):
            await service.move_domain(
                "biz1", _sec("section1"), _sec("section1")
            )

    @pytest.mark.asyncio
    async def test_move_rejects_cycle(self, service, mock_wiki_store):
        mock_wiki_store.get_section_descendants.return_value = [_sec("target")]
        with pytest.raises(ValueError, match="subtree"):
            await service.move_domain("biz1", _sec("section1"), _sec("target"))

    @pytest.mark.asyncio
    async def test_move_rejects_foreign_target(self, service, mock_wiki_store):
        mock_wiki_store.get_section_descendants.return_value = []
        with pytest.raises(ValueError, match="does not belong"):
            await service.move_domain(
                "biz1",
                _sec("section1"),
                "WikiSection:other_biz:domain:parent",
            )


class TestMergeDomains:
    @pytest.mark.asyncio
    async def test_merge_success(self, service, mock_wiki_store):
        mock_wiki_store.get_section_descendants.return_value = []
        result = await service.merge_domains("biz1", _sec("source"), _sec("target"))
        assert result["success"] is True
        mock_wiki_store.reparent_children.assert_called_once()
        mock_wiki_store.delete_wiki_section_cascade.assert_called_once_with(
            _sec("source"), "business_domain",
        )
        mock_wiki_store.update_descendant_pages_business_domain.assert_called_once_with(
            _sec("target"), "target", "business_domain",
        )

    @pytest.mark.asyncio
    async def test_merge_rejects_same(self, service):
        with pytest.raises(ValueError, match="differ"):
            await service.merge_domains("biz1", _sec("same"), _sec("same"))

    @pytest.mark.asyncio
    async def test_merge_rejects_target_in_source_subtree(
        self, service, mock_wiki_store
    ):
        mock_wiki_store.get_section_descendants.return_value = [_sec("target")]
        with pytest.raises(ValueError, match="subtree"):
            await service.merge_domains("biz1", _sec("source"), _sec("target"))

    @pytest.mark.asyncio
    async def test_merge_rejects_root(self, service):
        with pytest.raises(ValueError, match="root"):
            await service.merge_domains(
                "biz1", "WikiSection:biz1:domain:__root__", _sec("target")
            )

    @pytest.mark.asyncio
    async def test_merge_rejects_foreign_source(self, service, mock_wiki_store):
        mock_wiki_store.get_section_descendants.return_value = []
        with pytest.raises(ValueError, match="does not belong"):
            await service.merge_domains(
                "biz1",
                "WikiSection:other_biz:domain:source",
                _sec("target"),
            )


class TestCreateSubdomain:
    @pytest.mark.asyncio
    async def test_create_success(self, service, mock_wiki_store):
        result = await service.create_subdomain("biz1", _sec("parent"), "New Sub")
        assert result["success"] is True
        assert "section_uid" in result
        mock_wiki_store.upsert_wiki_section.assert_called_once()
        mock_wiki_store.add_has_child_edge.assert_called_once()


class TestMoveModuleDomain:
    @pytest.mark.asyncio
    async def test_move_module_success(self, service, mock_wiki_store):
        result = await service.move_module_domain("biz1", "mod1", "new-domain")
        assert result["success"] is True
        mock_wiki_store.update_module_business_domain.assert_called_once()
