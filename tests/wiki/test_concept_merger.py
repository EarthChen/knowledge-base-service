import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.concept_merger import ConceptMerger, MergeCandidate


@pytest.mark.asyncio
async def test_finds_similar_entities_across_repos():
    mock_store = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = [
        {
            "a_uid": "WikiPage:repo1:AuthService",
            "b_uid": "WikiPage:repo2:AuthService",
            "a_title": "AuthService",
            "b_title": "AuthService",
            "similarity": 0.95,
        }
    ]
    mock_store.execute_query = AsyncMock(return_value=mock_result)

    merger = ConceptMerger(mock_store, similarity_threshold=0.9)
    candidates = await merger.find_candidates("biz-1")
    assert len(candidates) == 1
    assert candidates[0].similarity >= 0.9
    q, params = mock_store.execute_query.call_args[0]
    assert "WikiSpace" in q and "HAS_CHILD" in q
    assert "a.business_id" not in q
    assert "WikiSpace {business_id" in q
    assert params.get("biz") == "biz-1" and "max_pages" in params


@pytest.mark.asyncio
async def test_no_candidates_below_threshold():
    mock_store = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = [
        {
            "a_uid": "WikiPage:repo1:Utils",
            "b_uid": "WikiPage:repo2:Helpers",
            "a_title": "Utils",
            "b_title": "Helpers",
            "similarity": 0.5,
        }
    ]
    mock_store.execute_query = AsyncMock(return_value=mock_result)

    merger = ConceptMerger(mock_store, similarity_threshold=0.9)
    candidates = await merger.find_candidates("biz-1")
    assert len(candidates) == 0
    q, _ = mock_store.execute_query.call_args[0]
    assert "id(a)" not in q and "id(b)" not in q


def test_merge_candidate_dataclass():
    c = MergeCandidate(
        page_uid_a="a",
        page_uid_b="b",
        similarity=0.95,
        title_a="Auth",
        title_b="Auth",
    )
    assert c.similarity == 0.95
