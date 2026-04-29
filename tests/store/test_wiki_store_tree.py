import pytest
from unittest.mock import AsyncMock, MagicMock
from store.wiki_store import WikiStore

@pytest.fixture
def mock_store():
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(result_set=[]))
    return WikiStore(store)

@pytest.mark.asyncio
async def test_upsert_wiki_space(mock_store):
    await mock_store.upsert_wiki_space("default", "Test Business", "desc")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "MERGE (ws:WikiSpace" in cypher
    assert "business_id" in cypher

@pytest.mark.asyncio
async def test_upsert_wiki_section(mock_store):
    await mock_store.upsert_wiki_section(
        uid="wsec:user-mgmt",
        title="用户管理",
        description="",
        section_type="business_domain",
        sort_order=1,
    )
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "MERGE (ws:WikiSection" in cypher

@pytest.mark.asyncio
async def test_add_has_child_edge(mock_store):
    await mock_store.add_has_child_edge(
        parent_uid="ws:default",
        parent_label="WikiSpace",
        child_uid="wsec:user-mgmt",
        child_label="WikiSection",
        view_type="business_domain",
        sort_order=1,
    )
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "HAS_CHILD" in cypher
    assert "view_type" in cypher

@pytest.mark.asyncio
async def test_add_wiki_reference_edge(mock_store):
    await mock_store.add_wiki_reference_edge(
        source_uid="WikiPage:repo:path1",
        target_uid="WikiPage:repo:path2",
        relation_type="calls",
        context="UserController calls UserService",
    )
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "WIKI_REFERENCES" in cypher
    assert "relation_type" in cypher

@pytest.mark.asyncio
async def test_add_has_child_edge_rejects_invalid_parent_label(mock_store):
    with pytest.raises(ValueError, match="Invalid parent_label"):
        await mock_store.add_has_child_edge(
            parent_uid="ws:default",
            parent_label="MaliciousLabel",
            child_uid="wsec:x",
            child_label="WikiSection",
            view_type="business_domain",
            sort_order=0,
        )

@pytest.mark.asyncio
async def test_add_has_child_edge_rejects_invalid_child_label(mock_store):
    with pytest.raises(ValueError, match="Invalid child_label"):
        await mock_store.add_has_child_edge(
            parent_uid="ws:default",
            parent_label="WikiSpace",
            child_uid="wsec:x",
            child_label="DROP_TABLE",
            view_type="business_domain",
            sort_order=0,
        )

@pytest.mark.asyncio
async def test_get_nested_tree(mock_store):
    mock_store._store.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[{"uid": "c1", "title": "A", "depth": 1}],
        ),
    )
    rows = await mock_store.get_nested_tree("WikiSection:root:domain:__root__", max_depth=3)
    assert rows == [{"uid": "c1", "title": "A", "depth": 1}]
    mock_store._store.execute_query.assert_awaited()
    call = mock_store._store.execute_query.call_args
    assert "HAS_CHILD" in call[0][0]


@pytest.mark.asyncio
async def test_get_nested_tree_with_view_type(mock_store):
    mock_store._store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    await mock_store.get_nested_tree(
        "WikiSection:root:domain:__root__",
        max_depth=2,
        view_type="business_domain",
    )
    cypher = mock_store._store.execute_query.call_args[0][0]
    assert "view_type" in cypher


@pytest.mark.asyncio
async def test_get_wiki_tree(mock_store):
    await mock_store.get_wiki_tree("default", "business_domain")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "HAS_CHILD" in cypher
    assert "view_type" in cypher

@pytest.mark.asyncio
async def test_get_wiki_page_references(mock_store):
    await mock_store.get_wiki_page_references("WikiPage:repo:path1")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "WIKI_REFERENCES" in cypher

@pytest.mark.asyncio
async def test_get_wiki_page_back_references(mock_store):
    await mock_store.get_wiki_page_back_references("WikiPage:repo:path1")
    call_args = mock_store._store.execute_query.call_args
    cypher = call_args[0][0]
    assert "WIKI_REFERENCES" in cypher
