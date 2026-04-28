import pytest
from unittest.mock import AsyncMock

from wiki.incremental_diff import WikiDiff, compute_wiki_diff


def test_wiki_diff_empty():
    diff = WikiDiff(changed_uids=set(), affected_parents=set(), affected_communities=set())
    assert diff.is_empty
    assert diff.total_affected == 0


def test_wiki_diff_total_affected():
    diff = WikiDiff(
        changed_uids={"a", "b"},
        affected_parents={"p1"},
        affected_communities={1},
    )
    assert not diff.is_empty
    assert diff.total_affected == 3


def test_wiki_diff_includes_community():
    diff = WikiDiff(
        changed_uids={"a"},
        affected_parents=set(),
        affected_communities={0, 2},
    )
    assert len(diff.affected_communities) == 2


@pytest.mark.asyncio
async def test_compute_wiki_diff_no_changes():
    store = AsyncMock()
    store.execute_query = AsyncMock(side_effect=[type("R", (), {"data": []})()])
    diff = await compute_wiki_diff(store, "test-repo", since_version=0)
    assert diff.is_empty


@pytest.mark.asyncio
async def test_compute_wiki_diff_with_changes_and_parents():
    store = AsyncMock()
    store.execute_query = AsyncMock(
        side_effect=[
            type("R", (), {"data": [["uid:Class:Foo"]]})(),
            type("R", (), {"data": [["uid:Module:api"]]})(),
            type("R", (), {"data": [[0]]})(),
        ]
    )
    diff = await compute_wiki_diff(store, "test-repo", since_version=0)
    assert diff.changed_uids == {"uid:Class:Foo"}
    assert diff.affected_parents == {"uid:Module:api"}
    assert diff.affected_communities == {0}


@pytest.mark.asyncio
async def test_compute_wiki_diff_changes_no_parents():
    store = AsyncMock()
    store.execute_query = AsyncMock(
        side_effect=[
            type("R", (), {"data": [["uid:Class:Foo"]]})(),
            type("R", (), {"data": []})(),
            type("R", (), {"data": []})(),
        ]
    )
    diff = await compute_wiki_diff(store, "test-repo", since_version=0)
    assert diff.changed_uids == {"uid:Class:Foo"}
    assert diff.affected_parents == set()
    assert diff.affected_communities == set()
