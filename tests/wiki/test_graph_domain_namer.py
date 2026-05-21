from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.graph_domain_namer import GraphDomainNamer


class TestNameCommunity:
    @pytest.mark.asyncio
    async def test_names_family_modules_correctly(self):
        """Given Family* modules, LLM returns family-related naming."""
        mock_llm = MagicMock()
        # Mock the LLM to return a JSON string
        mock_llm.generate = AsyncMock(
            return_value='{"slug": "family-system", "display_name": "家族系统", "description": "家族管理"}'
        )

        namer = GraphDomainNamer(mock_llm)
        result = await namer.name_community(["FamilyWebService", "FamilyMoa", "FamilyDao"])

        assert result["slug"] == "family-system"
        assert result["display_name"] == "家族系统"
        assert "description" in result

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        """When LLM fails, falls back to slug from first module name."""
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM error"))

        namer = GraphDomainNamer(mock_llm)
        result = await namer.name_community(["FamilyWebService", "FamilyMoa"])

        assert "slug" in result
        assert result["slug"]  # not empty
        assert "display_name" in result

    @pytest.mark.asyncio
    async def test_no_llm_uses_fallback(self):
        """When llm is None, use fallback naming."""
        namer = GraphDomainNamer(None)
        result = await namer.name_community(["IntimacyService", "IntimacyDao"])

        assert "slug" in result
        assert result["slug"]

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json_uses_fallback(self):
        """When LLM returns non-JSON, fallback is used."""
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="not valid json at all")

        namer = GraphDomainNamer(mock_llm)
        result = await namer.name_community(["UserService", "UserDao"])

        assert "slug" in result
        assert result["slug"]


class TestNameCommunitiesBatch:
    @pytest.mark.asyncio
    async def test_names_multiple_communities(self):
        """Batch naming returns results for each community in order."""
        mock_llm = MagicMock()
        responses = [
            '{"slug": "family-system", "display_name": "家族系统", "description": "d1"}',
            '{"slug": "intimacy", "display_name": "亲密关系", "description": "d2"}',
        ]
        mock_llm.generate = AsyncMock(side_effect=responses)

        namer = GraphDomainNamer(mock_llm)
        results = await namer.name_communities_batch(
            [
                ["FamilyWebService", "FamilyMoa"],
                ["IntimacyService", "IntimacyDao"],
            ]
        )

        assert len(results) == 2
        assert results[0]["slug"] == "family-system"
        assert results[1]["slug"] == "intimacy"


class TestNameCommunityWithInfos:
    @pytest.mark.asyncio
    async def test_name_with_module_infos(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value='{"slug": "intimacy", "display_name": "亲密关系", "description": "desc"}')
        namer = GraphDomainNamer(llm)
        result = await namer.name_community(
            module_infos=[
                {"name": "IntimacyService", "path": "intimacy/service/", "summary": "亲密关系核心服务"},
                {"name": "ClosedFriendHandler", "path": "closedfriend/handler/", "summary": "私密好友圈管理"},
            ],
        )
        assert result["slug"] == "intimacy"
        assert result["display_name"] == "亲密关系"
        prompt_arg = llm.generate.call_args[0][0]
        assert "IntimacyService" in prompt_arg
        assert "intimacy/service/" in prompt_arg
        assert "亲密关系核心服务" in prompt_arg

    @pytest.mark.asyncio
    async def test_backward_compat_module_names(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value='{"slug": "test", "display_name": "测试", "description": ""}')
        namer = GraphDomainNamer(llm)
        result = await namer.name_community(module_names=["FooService", "BarHandler"])
        assert result["slug"] == "test"
