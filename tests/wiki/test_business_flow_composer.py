import pytest
from unittest.mock import AsyncMock

from wiki.business_flow_composer import BusinessFlowPageComposer
from wiki.models import ImportanceTier, PageType, WikiConfig, WikiPageSummary


@pytest.fixture
def mock_community_service():
    svc = AsyncMock()
    svc.get_cached.return_value = {
        "communities": [
            {
                "id": 0,
                "members": ["uid:Class:AuthService", "uid:Class:SessionManager", "uid:Class:TokenValidator"],
                "size": 3,
            },
            {
                "id": 1,
                "members": ["uid:Fn:helper"],
                "size": 1,
            },
        ]
    }
    return svc


@pytest.fixture
def summary_index():
    return {
        "classes/AuthService.md": WikiPageSummary(
            "uid:Class:AuthService",
            "AuthService",
            "classes/AuthService.md",
            "Handles user authentication and login.",
            ImportanceTier.CORE,
            PageType.CLASS_DETAIL,
        ),
        "classes/SessionManager.md": WikiPageSummary(
            "uid:Class:SessionManager",
            "SessionManager",
            "classes/SessionManager.md",
            "Manages user sessions and cookies.",
            ImportanceTier.STANDARD,
            PageType.CLASS_DETAIL,
        ),
        "classes/TokenValidator.md": WikiPageSummary(
            "uid:Class:TokenValidator",
            "TokenValidator",
            "classes/TokenValidator.md",
            "Validates JWT tokens.",
            ImportanceTier.STANDARD,
            PageType.CLASS_DETAIL,
        ),
    }


@pytest.mark.asyncio
async def test_compose_flows_generates_page_for_large_community(mock_community_service, summary_index):
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="## Authentication Flow\n\nThis flow handles user login...")

    composer = BusinessFlowPageComposer(llm, mock_community_service)
    config = WikiConfig(repository="test", mode="full")

    uid_to_path = {s.entity_uid: s.path for s in summary_index.values()}
    pages = await composer.compose_flows("test", summary_index, uid_to_path, config, min_community_size=2)
    assert len(pages) == 1
    assert pages[0].page_type == PageType.BUSINESS_FLOW
    llm.generate.assert_called_once()


@pytest.mark.asyncio
async def test_compose_flows_skips_small_community(mock_community_service, summary_index):
    llm = AsyncMock()
    composer = BusinessFlowPageComposer(llm, mock_community_service)
    config = WikiConfig(repository="test", mode="full")

    uid_to_path = {s.entity_uid: s.path for s in summary_index.values()}
    pages = await composer.compose_flows("test", summary_index, uid_to_path, config, min_community_size=5)
    assert len(pages) == 0
    llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_compose_flows_no_llm_generates_simple_page(mock_community_service, summary_index):
    composer = BusinessFlowPageComposer(None, mock_community_service)
    config = WikiConfig(repository="test", mode="full")

    uid_to_path = {s.entity_uid: s.path for s in summary_index.values()}
    pages = await composer.compose_flows("test", summary_index, uid_to_path, config, min_community_size=2)
    assert len(pages) == 1
    assert "AuthService" in pages[0].content


@pytest.mark.asyncio
async def test_compose_flows_stores_member_uids(mock_community_service, summary_index):
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="Flow description")
    composer = BusinessFlowPageComposer(llm, mock_community_service)
    config = WikiConfig(repository="test", mode="full")

    uid_to_path = {s.entity_uid: s.path for s in summary_index.values()}
    pages = await composer.compose_flows("test", summary_index, uid_to_path, config, min_community_size=2)
    assert hasattr(pages[0], "_member_uids")
    assert len(pages[0]._member_uids) == 3
