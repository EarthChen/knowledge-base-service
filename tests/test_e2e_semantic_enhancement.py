"""End-to-end tests for semantic search enhancement features.

Tests the integration between new components:
- LLM Provider + Enrichment pipeline
- Business Flow Inferencer + Concept Extractor
- Enhanced Hybrid Search with reranking
- Deep Search Engine
- MCP tool manifest and routing
- HTTP API routes
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import LLMConfig, RerankConfig


class TestLLMEnrichmentPipeline:
    """Test the LLM enrichment pipeline end-to-end."""

    @pytest.mark.asyncio
    async def test_enrichment_updates_embedding_text(self):
        """Verify business_summary flows from enricher to embedding generator."""
        from indexer.embedding_generator import _format_code_text

        text_without = _format_code_text(
            "login", "def login(user, pwd)", "Login user", "def login(): pass"
        )
        text_with = _format_code_text(
            "login",
            "def login(user, pwd)",
            "Login user",
            "def login(): pass",
            business_summary="用户登录认证，属于用户认证模块",
        )

        assert "Business:" in text_with
        assert "用户登录认证" in text_with
        assert "Description:" not in text_with
        assert "Description:" in text_without

    @pytest.mark.asyncio
    async def test_enricher_to_indexer_integration(self):
        """Verify enricher results are passed through to indexer embedding items."""
        from indexer.enrichment import CodeSummaryEnricher
        from llm.provider import LLMProvider

        mock_llm = MagicMock(spec=LLMProvider)
        mock_llm.complete = AsyncMock(return_value="处理用户支付回调逻辑")
        enricher = CodeSummaryEnricher(llm=mock_llm)

        items = [
            {
                "name": "handle_payment",
                "signature": "def handle_payment()",
                "docstring": "",
                "code_snippet": (
                    "def handle_payment():\n"
                    "    validate()\n"
                    "    charge()\n"
                    "    notify()\n"
                    "    log()\n"
                    "    return ok\n"
                ),
                "file": "pay.py",
                "entity_kind": "function",
            },
        ]
        summaries = await enricher.enrich_batch(items)
        assert summaries[0] == "处理用户支付回调逻辑"


class TestBusinessSemanticGraph:
    """Test business semantic graph components integration."""

    @pytest.mark.asyncio
    async def test_flow_inferencer_produces_valid_structure(self):
        """Verify inferencer output matches expected schema."""
        from indexer.business_flow_inferencer import BusinessFlowInferencer
        from llm.provider import LLMProvider
        from store.falkordb_store import FalkorDBStore

        mock_llm = MagicMock(spec=LLMProvider)
        mock_llm.complete_json = AsyncMock(return_value={
            "flow_name": "用户注册",
            "description": "新用户注册流程",
            "category": "用户",
            "steps": [{"function": "register", "role": "entry_point", "order": 1}],
            "sub_flows": [],
        })
        mock_store = MagicMock(spec=FalkorDBStore)
        inferencer = BusinessFlowInferencer(llm=mock_llm, store=mock_store, business_flow_enabled=True)

        chain = [{"name": "register", "business_summary": "注册入口", "file": "auth.py"}]
        result = await inferencer.infer_from_chain(chain)

        assert result is not None
        assert result["flow_name"] == "用户注册"
        assert result["category"] == "用户"
        assert len(result["steps"]) == 1

    @pytest.mark.asyncio
    async def test_concept_extractor_produces_valid_structure(self):
        """Verify extractor output matches expected schema."""
        from indexer.concept_extractor import ConceptExtractor
        from llm.provider import LLMProvider

        mock_llm = MagicMock(spec=LLMProvider)
        mock_llm.complete_json = AsyncMock(return_value={
            "concepts": [{"name": "钱包", "description": "用户虚拟钱包", "aliases": ["wallet"], "category": "支付"}],
            "flows": [{"name": "充值", "description": "用户充值流程", "category": "支付"}],
        })
        extractor = ConceptExtractor(llm=mock_llm, concept_extraction_enabled=True)

        result = await extractor.extract("# 钱包系统\n支持用户充值和提现")
        assert len(result["concepts"]) == 1
        assert result["concepts"][0]["name"] == "钱包"
        assert len(result["flows"]) == 1


class TestSchemaExtensions:
    """Test schema extensions are consistent."""

    def test_all_new_node_labels_exist(self):
        from store.schema import NodeLabel
        assert hasattr(NodeLabel, "BUSINESS_FLOW")
        assert hasattr(NodeLabel, "BUSINESS_CONCEPT")
        assert NodeLabel.BUSINESS_FLOW == "BusinessFlow"
        assert NodeLabel.BUSINESS_CONCEPT == "BusinessConcept"

    def test_all_new_edge_types_exist(self):
        from store.schema import EdgeType
        assert hasattr(EdgeType, "IMPLEMENTS")
        assert hasattr(EdgeType, "RELATES_TO")
        assert hasattr(EdgeType, "PART_OF")
        assert hasattr(EdgeType, "CONCEPT_IN")

    def test_vector_index_covers_embeddable_types(self):
        from store.schema import VECTOR_INDEX_CONFIGS, NodeLabel
        labels = {c["label"] for c in VECTOR_INDEX_CONFIGS}
        assert NodeLabel.BUSINESS_FLOW in labels
        assert NodeLabel.BUSINESS_CONCEPT in labels
        assert NodeLabel.MODULE in labels
        assert NodeLabel.WIKI_PAGE in labels
        assert NodeLabel.WIKI_QA in labels
        assert len(VECTOR_INDEX_CONFIGS) == 9


class TestSearchEngineEnhancement:
    """Test search engine components integration."""

    def test_reranker_integration_with_business_summary(self):
        """Verify reranker considers business_summary in candidate text."""
        from query.reranker import Reranker

        text = Reranker._candidate_text({
            "name": "handle_payment",
            "business_summary": "处理支付回调",
            "signature": "def handle_payment()",
            "docstring": "Handle payment callback",
        })
        assert "处理支付回调" in text
        assert "handle_payment" in text

    @pytest.mark.asyncio
    async def test_deep_search_full_flow(self):
        """Test deep search delegates to IterativeRAGEngine (mocked)."""
        from query.deep_search import DeepSearchEngine

        mock_rag = MagicMock()
        mock_rag.arun = AsyncMock(
            return_value={
                "current_draft": "找到支付相关代码",
                "sse_events": [
                    {"type": "searching", "round": 1},
                    {"type": "done", "final_answer": "找到支付相关代码"},
                ],
                "round": 2,
                "confidence": 0.91,
            }
        )

        engine = DeepSearchEngine(rag_engine=mock_rag)
        result = await engine.search("支付相关代码在哪里？")

        assert result["analysis"] == "找到支付相关代码"
        assert result["code_locations"] == []
        assert len(result["search_trace"]) >= 2
        assert result["search_trace"][0]["stage"] == "searching"
        mock_rag.arun.assert_awaited_once()


class TestMCPToolManifest:
    """Test MCP tool manifest includes new tools."""

    def test_manifest_has_core_rag_tools(self):
        from api.mcp_server import MCP_TOOLS_MANIFEST
        names = {t["name"] for t in MCP_TOOLS_MANIFEST}
        assert "rag_query" in names
        assert "rag_graph" in names

    def test_rag_graph_includes_business_query_types(self):
        from api.mcp_server import MCP_TOOLS_MANIFEST
        graph_tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_graph")
        query_types = graph_tool["inputSchema"]["properties"]["query_type"]["enum"]
        assert "business_flow" in query_types
        assert "flows_for_function" in query_types
        assert "related_concepts" in query_types
        assert "explore_domain" in query_types
        assert "flow_dependencies" in query_types
        assert "blast_radius" in query_types

    def test_rag_query_tool_supports_entity_type_for_business_entities(self):
        from api.mcp_server import MCP_TOOLS_MANIFEST
        tool = next(t for t in MCP_TOOLS_MANIFEST if t["name"] == "rag_query")
        props = tool["inputSchema"]["properties"]
        assert "query" in props
        assert "entity_type" in props
        assert tool["inputSchema"]["required"] == ["query"]


class TestConfigExtensions:
    """Test configuration extensions."""

    def test_llm_config_defaults(self):
        config = LLMConfig()
        assert config.enabled is False
        assert config.model == "gpt-4o-mini"
        assert config.max_concurrent == 50

    def test_llm_config_accepts_max_concurrency_alias(self):
        assert LLMConfig.model_validate({"max_concurrency": 5}).max_concurrent == 5
        assert LLMConfig(max_concurrency=5).max_concurrent == 5
        assert LLMConfig(max_concurrent=7).max_concurrent == 7

    def test_settings_llm_max_concurrency_env_nested_alias(self, monkeypatch):
        monkeypatch.setenv("LLM__MAX_CONCURRENCY", "5")
        from core.config import Settings

        s = Settings(_env_file=None)
        assert s.llm.max_concurrent == 5

    def test_rerank_config_defaults(self):
        config = RerankConfig()
        assert config.enabled is False
        assert config.model_name == "BAAI/bge-reranker-v2-m3"
        assert config.batch_size == 32
