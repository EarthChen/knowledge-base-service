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
    async def test_returns_empty_when_no_repositories(self):
        store = AsyncMock()
        diff = await compute_domain_diff(store, "ultron", repositories=[])
        assert diff.is_empty is True
        assert diff.total_changed == 0
        store.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_hash_mismatch(self):
        store = AsyncMock()
        store.execute_query = AsyncMock(
            return_value=MagicMock(data=[])
        )
        diff = await compute_domain_diff(store, "ultron", repositories=["svc-a"])
        assert diff.is_empty is True
        assert diff.total_changed == 0
        store.execute_query.assert_called_once()
        call_args = store.execute_query.call_args
        assert call_args.args[1] == {"repos": ["svc-a"]}
        assert "code_hash" in call_args.args[0]
        assert "wiki_code_hash" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_reads_positional_rows_when_data_is_none(self):
        store = AsyncMock()
        row_result = MagicMock(spec=["data", "raw", "result_set"])
        row_result.data = None
        row_result.result_set = None
        row_result.raw = [["m-uid", "Name", "Billing"]]
        store.execute_query = AsyncMock(return_value=row_result)
        diff = await compute_domain_diff(store, "ultron", repositories=["r1"])
        assert diff.total_changed == 1
        assert diff.affected_domains == ["Billing"]
        assert diff.changed_module_uids == ["m-uid"]
        store = AsyncMock()
        store.execute_query = AsyncMock(
            return_value=MagicMock(data=[
                {"uid": "Module:UserController:0", "name": "UserController", "domain": "用户管理"},
                {"uid": "Module:UserService:0", "name": "UserService", "domain": "用户管理"},
                {"uid": "Module:MsgHandler:0", "name": "MsgHandler", "domain": "消息处理"},
            ])
        )
        diff = await compute_domain_diff(store, "ultron", repositories=["svc-a"])
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
        diff = await compute_domain_diff(store, "ultron", repositories=["svc-a"])
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
        diff = await compute_domain_diff(store, "ultron", repositories=["svc-a"])
        assert len(diff.affected_domains) == 1
