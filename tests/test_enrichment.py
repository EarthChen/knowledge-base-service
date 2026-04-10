import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_llm():
    from llm.provider import LLMProvider
    llm = MagicMock(spec=LLMProvider)
    llm.complete = AsyncMock(return_value="此函数处理用户登录验证，属于用户认证业务领域。")
    return llm


class TestCodeSummaryEnricher:
    @pytest.mark.asyncio
    async def test_enrich_single_function(self, mock_llm):
        from indexer.enrichment import CodeSummaryEnricher
        enricher = CodeSummaryEnricher(llm=mock_llm)
        items = [
            {
                "name": "authenticate",
                "signature": "def authenticate(username, password)",
                "docstring": "Authenticate user",
                "code_snippet": "def authenticate(username, password): ...",
                "file": "auth/service.py",
            }
        ]
        results = await enricher.enrich_batch(items)
        assert len(results) == 1
        assert len(results[0]) > 0
        mock_llm.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrich_batch_groups_by_file(self, mock_llm):
        from indexer.enrichment import CodeSummaryEnricher
        enricher = CodeSummaryEnricher(llm=mock_llm)
        items = [
            {"name": "func_a", "signature": "", "docstring": "", "code_snippet": "", "file": "a.py"},
            {"name": "func_b", "signature": "", "docstring": "", "code_snippet": "", "file": "a.py"},
            {"name": "func_c", "signature": "", "docstring": "", "code_snippet": "", "file": "b.py"},
        ]
        results = await enricher.enrich_batch(items)
        assert len(results) == 3
        assert all(r != "" for r in results)

    @pytest.mark.asyncio
    async def test_enrich_handles_llm_failure(self, mock_llm):
        from indexer.enrichment import CodeSummaryEnricher
        mock_llm.complete = AsyncMock(side_effect=Exception("LLM error"))
        enricher = CodeSummaryEnricher(llm=mock_llm)
        items = [
            {"name": "func_a", "signature": "", "docstring": "", "code_snippet": "", "file": "a.py"},
        ]
        results = await enricher.enrich_batch(items)
        assert len(results) == 1
        assert results[0] == ""

    @pytest.mark.asyncio
    async def test_enrich_single(self, mock_llm):
        from indexer.enrichment import CodeSummaryEnricher
        enricher = CodeSummaryEnricher(llm=mock_llm)
        result = await enricher.enrich_single(
            {"name": "func", "signature": "def func()", "docstring": "", "code_snippet": "", "file": "x.py"}
        )
        assert len(result) > 0
