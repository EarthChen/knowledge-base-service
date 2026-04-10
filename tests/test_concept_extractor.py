import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_llm():
    from llm.provider import LLMProvider

    llm = MagicMock(spec=LLMProvider)
    llm.complete_json = AsyncMock(
        return_value={
            "concepts": [
                {
                    "name": "私信",
                    "description": "用户间的即时消息",
                    "aliases": ["IM消息", "direct_message"],
                    "category": "社交",
                },
            ],
            "flows": [
                {
                    "name": "发送私信",
                    "description": "用户发送私信给另一个用户",
                    "category": "社交",
                },
            ],
        }
    )
    return llm


class TestConceptExtractor:
    @pytest.mark.asyncio
    async def test_extract_from_document(self, mock_llm):
        from indexer.concept_extractor import ConceptExtractor

        extractor = ConceptExtractor(llm=mock_llm)
        result = await extractor.extract("# 私信系统\n用户可以通过私信功能发送即时消息...")
        assert len(result["concepts"]) == 1
        assert result["concepts"][0]["name"] == "私信"
        assert "IM消息" in result["concepts"][0]["aliases"]
        assert len(result["flows"]) == 1

    @pytest.mark.asyncio
    async def test_handles_empty_document(self, mock_llm):
        from indexer.concept_extractor import ConceptExtractor

        extractor = ConceptExtractor(llm=mock_llm)
        result = await extractor.extract("")
        assert len(result["concepts"]) == 0
        assert len(result["flows"]) == 0
        mock_llm.complete_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self, mock_llm):
        from indexer.concept_extractor import ConceptExtractor

        mock_llm.complete_json = AsyncMock(side_effect=Exception("fail"))
        extractor = ConceptExtractor(llm=mock_llm)
        result = await extractor.extract("some content")
        assert result == {"concepts": [], "flows": []}

    @pytest.mark.asyncio
    async def test_extract_batch(self, mock_llm):
        from indexer.concept_extractor import ConceptExtractor

        extractor = ConceptExtractor(llm=mock_llm)
        docs = [{"content": "doc1 content"}, {"content": "doc2 content"}]
        results = await extractor.extract_batch(docs)
        assert len(results) == 2
        assert mock_llm.complete_json.call_count == 2
