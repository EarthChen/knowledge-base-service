"""Tests for domain-level incremental diff computation."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.incremental_diff import DomainDiff, compute_domain_diff


class TestDomainDiff:
    def test_is_empty_when_no_changes(self):
        diff = DomainDiff(affected_domains=[], changed_module_uids=[], total_changed=0)
        assert diff.is_empty is True

    def test_is_not_empty_with_changes(self):
        diff = DomainDiff(
            affected_domains=["用户管理"],
            changed_module_uids=["Module:UserController:0"],
            total_changed=1,
        )
        assert diff.is_empty is False

    def test_affected_domains_list(self):
        diff = DomainDiff(
            affected_domains=["用户管理", "消息处理"],
            changed_module_uids=["m1", "m2", "m3"],
            total_changed=3,
        )
        assert len(diff.affected_domains) == 2
        assert "用户管理" in diff.affected_domains


class TestComputeDomainDiff:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_hash_mismatch(self):
        store = AsyncMock()
        store.execute_query = AsyncMock(
            return_value=MagicMock(data=[])
        )
        diff = await compute_domain_diff(store, "ultron")
        assert diff.is_empty is True
        assert diff.total_changed == 0

    @pytest.mark.asyncio
    async def test_identifies_affected_domains_from_changed_modules(self):
        store = AsyncMock()
        store.execute_query = AsyncMock(
            return_value=MagicMock(data=[
                {"uid": "Module:UserController:0", "name": "UserController", "domain": "用户管理"},
                {"uid": "Module:UserService:0", "name": "UserService", "domain": "用户管理"},
                {"uid": "Module:MsgHandler:0", "name": "MsgHandler", "domain": "消息处理"},
            ])
        )
        diff = await compute_domain_diff(store, "ultron")
        assert diff.total_changed == 3
        assert set(diff.affected_domains) == {"用户管理", "消息处理"}

    @pytest.mark.asyncio
    async def test_modules_without_domain_still_counted(self):
        store = AsyncMock()
        store.execute_query = AsyncMock(
            return_value=MagicMock(data=[
                {"uid": "Module:Orphan:0", "name": "Orphan", "domain": ""},
            ])
        )
        diff = await compute_domain_diff(store, "ultron")
        assert diff.total_changed == 1
        assert diff.affected_domains == []

    @pytest.mark.asyncio
    async def test_deduplicates_domains(self):
        store = AsyncMock()
        store.execute_query = AsyncMock(
            return_value=MagicMock(data=[
                {"uid": "m1", "name": "A", "domain": "X"},
                {"uid": "m2", "name": "B", "domain": "X"},
                {"uid": "m3", "name": "C", "domain": "X"},
            ])
        )
        diff = await compute_domain_diff(store, "ultron")
        assert len(diff.affected_domains) == 1
