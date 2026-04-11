import pytest
from unittest.mock import AsyncMock, MagicMock


class TestTrivialEntityFilter:
    def test_skips_init_and_accessor(self) -> None:
        from indexer.enrichment import is_trivial_enrichment_entity

        assert is_trivial_enrichment_entity(
            {
                "name": "__init__",
                "signature": "",
                "code_snippet": "many\nlines\nhere\nstill\nskipped",
                "entity_kind": "function",
            }
        )
        assert is_trivial_enrichment_entity(
            {
                "name": "get_user",
                "signature": "",
                "code_snippet": "many\nlines\nhere\nstill\nskipped",
                "entity_kind": "function",
            }
        )
        assert not is_trivial_enrichment_entity(
            {
                "name": "process_order",
                "signature": "",
                "code_snippet": "\n".join([f"  x{i}" for i in range(5)]),
                "entity_kind": "function",
            }
        )
        assert not is_trivial_enrichment_entity(
            {
                "name": "Tiny",
                "signature": "",
                "code_snippet": "  x",
                "entity_kind": "class",
            }
        )


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
                "code_snippet": (
                    "def authenticate(username, password):\n"
                    "    if not username:\n"
                    "        return False\n"
                    "    if not password:\n"
                    "        return False\n"
                    "    return check_db(username, password)\n"
                ),
                "file": "auth/service.py",
                "entity_kind": "function",
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
            {
                "name": "func_a",
                "signature": "",
                "docstring": "",
                "code_snippet": "\n".join([f"    line_{i}()" for i in range(5)]),
                "file": "a.py",
                "entity_kind": "function",
            },
            {
                "name": "func_b",
                "signature": "",
                "docstring": "",
                "code_snippet": "\n".join([f"    line_{i}()" for i in range(5)]),
                "file": "a.py",
                "entity_kind": "function",
            },
            {
                "name": "func_c",
                "signature": "",
                "docstring": "",
                "code_snippet": "\n".join([f"    line_{i}()" for i in range(5)]),
                "file": "b.py",
                "entity_kind": "function",
            },
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
            {
                "name": "func_a",
                "signature": "",
                "docstring": "",
                "code_snippet": "\n".join([f"    line_{i}()" for i in range(5)]),
                "file": "a.py",
                "entity_kind": "function",
            },
        ]
        results = await enricher.enrich_batch(items)
        assert len(results) == 1
        assert results[0] == ""

    @pytest.mark.asyncio
    async def test_enrich_single(self, mock_llm):
        from indexer.enrichment import CodeSummaryEnricher
        enricher = CodeSummaryEnricher(llm=mock_llm)
        result = await enricher.enrich_single(
            {
                "name": "func",
                "signature": "def func()",
                "docstring": "",
                "code_snippet": "\n".join([f"    x_{i}()" for i in range(5)]),
                "file": "x.py",
                "entity_kind": "function",
            }
        )
        assert len(result) > 0
