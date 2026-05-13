"""Tests for WikiPageAgent WorkingMemory and Agent loop."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.page_agent import (
    SINGLE_RESULT_LIMIT,
    ToolResult,
    WikiPageAgent,
    WorkingMemory,
)


class TestWorkingMemory:
    def test_incorporate_call_chain(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="query_call_chain", data={
                "chains": [{"entry": "A.foo", "chain": ["A.foo", "B.bar"], "depth": 1}]
            })
        ])
        assert len(wm.discovered_call_chains) == 1

    def test_incorporate_callers(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="query_callers", data={
                "callers": [{"caller_name": "X", "target_name": "Y"}]
            })
        ])
        assert len(wm.discovered_callers) == 1

    def test_incorporate_implementations(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="query_implementations", data={
                "implementations": [{"impl_name": "FooImpl", "interface_name": "IFoo"}]
            })
        ])
        assert len(wm.discovered_implementations) == 1
        assert "FooImpl implements IFoo" in wm.discovered_implementations[0]

    def test_incorporate_snippet(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="read_source_snippet", data={
                "snippet": "public void save() { db.insert(); }",
                "func_name": "save"
            })
        ])
        assert len(wm.code_snippets) == 1
        assert "save" in wm.code_snippets[0]

    def test_max_total_chars_enforced(self):
        wm = WorkingMemory()
        for i in range(100):
            wm.incorporate([
                ToolResult(tool="read_source_snippet", data={
                    "snippet": "x" * 200, "func_name": f"func{i}"
                })
            ])
        text = wm.to_prompt_section()
        assert len(text) <= WorkingMemory.MAX_TOTAL_CHARS + 500

    def test_to_prompt_section_format(self):
        wm = WorkingMemory()
        wm.discovered_call_chains.append("A → B → C")
        wm.resolved_gaps.append("gap1 resolved")
        text = wm.to_prompt_section()
        assert "A → B → C" in text
        assert "gap1" in text

    def test_empty_working_memory(self):
        wm = WorkingMemory()
        text = wm.to_prompt_section()
        assert isinstance(text, str)

    def test_new_fields_exist(self):
        wm = WorkingMemory()
        assert hasattr(wm, "wiki_references")
        assert hasattr(wm, "search_findings")
        assert isinstance(wm.wiki_references, list)
        assert isinstance(wm.search_findings, list)

    def test_max_total_chars_200k(self):
        assert WorkingMemory.MAX_TOTAL_CHARS == 200_000

    def test_merge_combines_all_fields(self):
        wm1 = WorkingMemory()
        wm1.code_snippets.append("[ModA]\ncode_a")
        wm1.discovered_call_chains.append("A → B")

        wm2 = WorkingMemory()
        wm2.code_snippets.append("[ModB]\ncode_b")
        wm2.discovered_call_chains.append("C → D")
        wm2.discovered_callers.append("X → Y")

        wm1.merge(wm2)

        assert len(wm1.code_snippets) == 2
        assert len(wm1.discovered_call_chains) == 2
        assert len(wm1.discovered_callers) == 1
        assert "[ModB]\ncode_b" in wm1.code_snippets

    def test_merge_deduplicates_code_snippets_by_module_prefix(self):
        wm1 = WorkingMemory()
        wm1.code_snippets.append("[ModA]\nold_code")
        wm1.code_snippets.append("[ModB]\ncode_b")

        wm2 = WorkingMemory()
        wm2.code_snippets.append("[ModA]\nnew_code")

        wm1.merge(wm2)

        mod_a_snippets = [s for s in wm1.code_snippets if s.startswith("[ModA]")]
        assert len(mod_a_snippets) == 1
        assert "new_code" in mod_a_snippets[0]
        assert len(wm1.code_snippets) == 2

    def test_merge_deduplicates_call_chains(self):
        wm1 = WorkingMemory()
        wm1.discovered_call_chains.append("A → B → C")

        wm2 = WorkingMemory()
        wm2.discovered_call_chains.append("A → B → C")
        wm2.discovered_call_chains.append("D → E")

        wm1.merge(wm2)

        assert len(wm1.discovered_call_chains) == 2
        assert "A → B → C" in wm1.discovered_call_chains
        assert "D → E" in wm1.discovered_call_chains

    def test_merge_enforces_limit(self):
        wm1 = WorkingMemory()
        wm1.code_snippets.extend([f"[Mod{i}]\n{'x' * 1000}" for i in range(100)])

        wm2 = WorkingMemory()
        wm2.code_snippets.extend([f"[Mod{i+100}]\n{'y' * 1000}" for i in range(100)])

        wm1.merge(wm2)

        total = wm1._total_chars()
        assert total <= WorkingMemory.MAX_TOTAL_CHARS

    def test_incorporate_read_code(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="read_code", data={
                "name": "processOrder",
                "code": "public void processOrder() { /* long code */ }",
            })
        ])
        assert len(wm.code_snippets) == 1
        assert "processOrder" in wm.code_snippets[0]

    def test_incorporate_read_code_ambiguous(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="read_code", data={
                "name": "save",
                "ambiguous": True,
                "matches": [
                    {"name": "save", "code": "void save(Order o) {}", "file": "Order.java"},
                    {"name": "save", "code": "void save(User u) {}", "file": "User.java"},
                ],
            })
        ])
        assert len(wm.code_snippets) == 2
        assert "Order.java" in wm.code_snippets[0]
        assert "User.java" in wm.code_snippets[1]

    def test_incorporate_read_file(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="read_file", data={
                "file_path": "config/app.yaml",
                "content": "server:\n  port: 8080",
            })
        ])
        assert len(wm.code_snippets) == 1
        assert "config/app.yaml" in wm.code_snippets[0]

    def test_incorporate_search_entities(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="search_entities", data={
                "results": [
                    {"name": "OrderService", "type": "Class", "file": "a.java"},
                    {"name": "save", "type": "Function", "file": "b.java"},
                ],
                "total": 2,
            })
        ])
        assert len(wm.search_findings) == 2

    def test_incorporate_read_wiki_page(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="read_wiki_page", data={
                "title": "订单处理",
                "content": "本文档描述了订单处理的完整流程...",
            })
        ])
        assert len(wm.wiki_references) == 1
        assert "订单处理" in wm.wiki_references[0]

    def test_incorporate_semantic_search(self):
        wm = WorkingMemory()
        wm.incorporate([
            ToolResult(tool="semantic_search", data={
                "results": [
                    {"title": "OrderService", "file_path": "a.java", "source": "code"},
                ]
            })
        ])
        assert len(wm.search_findings) == 1

    def test_working_memory_respects_max_total_chars(self):
        wm = WorkingMemory()
        for i in range(200):
            wm.incorporate([
                ToolResult(tool="read_code", data={
                    "name": f"func{i}",
                    "code": "x" * 200,
                })
            ])
        assert wm._total_chars() <= WorkingMemory.MAX_TOTAL_CHARS

    def test_to_prompt_section_includes_new_fields(self):
        wm = WorkingMemory()
        wm.wiki_references.append("[订单] 内容摘要")
        wm.search_findings.append("[code] OrderService: 处理订单")
        text = wm.to_prompt_section()
        assert "订单" in text
        assert "OrderService" in text


class TestWikiPageAgent:
    @pytest.mark.asyncio
    async def test_no_gaps_returns_original(self):
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs)
        content = "No gaps here. ## 业务概述\nSome content."
        result = await agent.enrich(content, domain_name="test")
        assert result == content

    @pytest.mark.asyncio
    async def test_with_gaps_calls_llm(self):
        llm = MagicMock()
        llm.complete_with_tools = AsyncMock(return_value={
            "content": "Enriched content without gaps.",
            "tool_calls": None,
        })
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs)
        content = "## 业务概述\n<!-- CONTEXT_GAP: missing order flow -->"
        result = await agent.enrich(content, domain_name="test")
        llm.complete_with_tools.assert_called()
        assert result == "Enriched content without gaps."

    @pytest.mark.asyncio
    async def test_max_rounds_enforced(self):
        llm = MagicMock()
        call_count = 0

        async def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "content": None,
                "tool_calls": [{"function": {"name": "query_callers", "arguments": '{"name":"X"}'}, "id": f"c{call_count}"}],
            }

        llm.complete_with_tools = mock_complete
        llm.generate = AsyncMock(return_value="fallback content")
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        agent = WikiPageAgent(llm, gs)
        content = "<!-- CONTEXT_GAP: x -->"
        result = await agent.enrich(content, domain_name="test")
        assert call_count <= agent.max_rounds

    @pytest.mark.asyncio
    async def test_tool_execution_failure_continues(self):
        llm = MagicMock()
        call_count = 0

        async def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "content": None,
                    "tool_calls": [{"function": {"name": "query_callers", "arguments": '{"name":"X"}'}, "id": "c1"}],
                }
            return {"content": "final result", "tool_calls": None}

        llm.complete_with_tools = mock_complete
        gs = MagicMock()
        gs.execute_query = AsyncMock(side_effect=Exception("db down"))
        agent = WikiPageAgent(llm, gs)
        content = "<!-- CONTEXT_GAP: something -->"
        result = await agent.enrich(content, domain_name="test")
        assert result == "final result"

    @pytest.mark.asyncio
    async def test_read_code_returns_snippet(self):
        llm = MagicMock()
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[
            {"name": "processOrder", "file": "OrderService.java",
             "start_line": 10, "end_line": 50, "snippet": "public void processOrder() { /* code */ }",
             "type": "Function"}
        ]))
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("read_code", {"entity_name": "processOrder"})
        assert result["name"] == "processOrder"
        assert result["code"] == "public void processOrder() { /* code */ }"
        assert result["file"] == "OrderService.java"

    @pytest.mark.asyncio
    async def test_read_code_max_chars(self):
        llm = MagicMock()
        gs = MagicMock()
        long_code = "x" * 5000
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[
            {"name": "big", "file": "a.java", "start_line": 1, "end_line": 200,
             "snippet": long_code, "type": "Function"}
        ]))
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("read_code", {"entity_name": "big", "max_chars": 100})
        assert len(result["code"]) <= 100

    @pytest.mark.asyncio
    async def test_read_code_not_found(self):
        llm = MagicMock()
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("read_code", {"entity_name": "nonexistent"})
        assert result["code"] == ""

    @pytest.mark.asyncio
    async def test_read_code_ambiguous_multiple_matches(self):
        llm = MagicMock()
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[
            {"name": "save", "file": "OrderService.java", "start_line": 10,
             "end_line": 20, "snippet": "void save(Order o) {}", "type": "Function"},
            {"name": "save", "file": "UserService.java", "start_line": 5,
             "end_line": 15, "snippet": "void save(User u) {}", "type": "Function"},
        ]))
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("read_code", {"entity_name": "save"})
        assert result["ambiguous"] is True
        assert len(result["matches"]) == 2
        assert result["matches"][0]["file"] == "OrderService.java"
        assert result["matches"][1]["file"] == "UserService.java"

    @pytest.mark.asyncio
    async def test_read_code_invalid_max_chars(self):
        llm = MagicMock()
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[
            {"name": "foo", "file": "a.java", "start_line": 1, "end_line": 5,
             "snippet": "x" * 100, "type": "Function"},
        ]))
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("read_code", {"entity_name": "foo", "max_chars": "not_a_number"})
        assert len(result["code"]) <= SINGLE_RESULT_LIMIT

    @pytest.mark.asyncio
    async def test_read_file_success(self, tmp_path):
        test_file = tmp_path / "config" / "app.yaml"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("server:\n  port: 8080\n  host: localhost\n")
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs, repo_path=str(tmp_path))
        result = await agent._execute_tool("read_file", {"file_path": "config/app.yaml"})
        assert "server:" in result["content"]
        assert result["file_path"] == "config/app.yaml"

    @pytest.mark.asyncio
    async def test_read_file_path_traversal_blocked(self, tmp_path):
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs, repo_path=str(tmp_path))
        result = await agent._execute_tool("read_file", {"file_path": "../../etc/passwd"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_file_no_repo_path(self):
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("read_file", {"file_path": "any.txt"})
        assert "error" in result
        assert "unavailable" in result["error"]

    @pytest.mark.asyncio
    async def test_read_file_absolute_path_rejected(self):
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs, repo_path="/tmp/repo")
        result = await agent._execute_tool("read_file", {"file_path": "/etc/passwd"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_file_end_line_less_than_start(self, tmp_path):
        test_file = tmp_path / "data.txt"
        test_file.write_text("\n".join(f"line {i}" for i in range(1, 51)))
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs, repo_path=str(tmp_path))
        result = await agent._execute_tool("read_file", {
            "file_path": "data.txt", "start_line": 10, "end_line": 5
        })
        assert "line 10" in result["content"]
        assert result["start_line"] == 10

    @pytest.mark.asyncio
    async def test_read_file_too_large(self, tmp_path):
        test_file = tmp_path / "huge.bin"
        test_file.write_text("x" * (3 * 1024 * 1024))
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs, repo_path=str(tmp_path))
        result = await agent._execute_tool("read_file", {"file_path": "huge.bin"})
        assert "error" in result
        assert "too large" in result["error"]

    @pytest.mark.asyncio
    async def test_read_file_line_range(self, tmp_path):
        test_file = tmp_path / "code.py"
        lines = [f"line {i}" for i in range(1, 21)]
        test_file.write_text("\n".join(lines))
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs, repo_path=str(tmp_path))
        result = await agent._execute_tool("read_file", {
            "file_path": "code.py", "start_line": 5, "end_line": 10
        })
        assert "line 5" in result["content"]
        assert "line 10" in result["content"]

    @pytest.mark.asyncio
    async def test_search_entities_by_name(self):
        llm = MagicMock()
        gs = MagicMock()
        empty = MagicMock(data=[])
        class_hit = MagicMock(data=[
            {"name": "OrderService", "type": "Class", "file": "a.java", "signature": "", "docstring": "Handles orders"},
        ])
        gs.execute_query = AsyncMock(side_effect=[empty, class_hit, empty])
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("search_entities", {"keyword": "Order"})
        assert result["total"] == 1
        assert result["results"][0]["name"] == "OrderService"

    @pytest.mark.asyncio
    async def test_search_entities_per_label_queries(self):
        """Verify search_entities calls graph once per label (Function, Class, Module)."""
        llm = MagicMock()
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[
            {"name": "OrderService", "type": "Class", "file": "a.java", "signature": "", "docstring": ""},
        ]))
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("search_entities", {"keyword": "Order"})
        assert gs.execute_query.call_count == 3
        assert result["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_entities_truncated_flag(self):
        llm = MagicMock()
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[
            {"name": f"fn{i}", "type": "Function", "file": "a.java", "signature": "", "docstring": ""}
            for i in range(5)
        ]))
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("search_entities", {"keyword": "fn", "limit": 5})
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_search_entities_empty(self):
        llm = MagicMock()
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("search_entities", {"keyword": "xyz"})
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_read_wiki_page_from_existing(self):
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs)
        agent._existing_pages = [
            {"title": "订单处理", "path": "/wiki/order", "content": "订单处理流程..."},
        ]
        result = await agent._execute_tool("read_wiki_page", {"query": "订单"})
        assert result["title"] == "订单处理"
        assert "订单处理流程" in result["content"]

    @pytest.mark.asyncio
    async def test_read_wiki_page_from_graph(self):
        llm = MagicMock()
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[
            {"title": "支付模块", "path": "/wiki/payment", "content": "支付逻辑..."}
        ]))
        agent = WikiPageAgent(llm, gs)
        agent._existing_pages = None
        result = await agent._execute_tool("read_wiki_page", {"query": "payment"})
        assert result["title"] == "支付模块"

    @pytest.mark.asyncio
    async def test_read_wiki_page_not_found(self):
        llm = MagicMock()
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        agent = WikiPageAgent(llm, gs)
        agent._existing_pages = []
        result = await agent._execute_tool("read_wiki_page", {"query": "nonexistent"})
        assert result.get("content", "") == ""

    @pytest.mark.asyncio
    async def test_semantic_search_success(self):
        llm = MagicMock()
        gs = MagicMock()
        mock_search = MagicMock()
        mock_search.search_with_context = AsyncMock(return_value={
            "results": [
                {"entity_name": "OrderService", "score": 0.92, "source_type": "code",
                 "file_path": "a.java"},
            ],
            "confidence": 0.9,
        })
        agent = WikiPageAgent(llm, gs, search_service=mock_search)
        result = await agent._execute_tool("semantic_search", {"query": "order processing"})
        assert len(result["results"]) >= 1

    @pytest.mark.asyncio
    async def test_semantic_search_unavailable(self):
        llm = MagicMock()
        gs = MagicMock()
        agent = WikiPageAgent(llm, gs)
        result = await agent._execute_tool("semantic_search", {"query": "test"})
        assert "error" in result
        assert "unavailable" in result["error"]

    def test_agent_tools_contains_new_tools(self):
        from wiki.page_agent import AGENT_TOOLS

        tool_names = {t["function"]["name"] for t in AGENT_TOOLS}
        assert "read_code" in tool_names
        assert "read_file" in tool_names
        assert "search_entities" in tool_names
        assert "read_wiki_page" in tool_names
        assert "semantic_search" in tool_names

    @pytest.mark.asyncio
    async def test_max_tool_calls_limit(self):
        llm = MagicMock()
        call_count = 0

        async def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "content": None,
                "tool_calls": [
                    {"function": {"name": "search_entities", "arguments": '{"keyword":"x"}'}, "id": f"c{call_count}"},
                    {"function": {"name": "search_entities", "arguments": '{"keyword":"y"}'}, "id": f"d{call_count}"},
                    {"function": {"name": "search_entities", "arguments": '{"keyword":"z"}'}, "id": f"e{call_count}"},
                ],
            }

        llm.complete_with_tools = mock_complete
        llm.generate = AsyncMock(return_value="fallback")
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        agent = WikiPageAgent(llm, gs)
        content = "<!-- CONTEXT_GAP: test -->"
        await agent.enrich(content, domain_name="test")
        assert call_count <= agent.max_rounds


class TestWikiPageAgentConstruction:
    def test_default_max_rounds(self):
        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        assert agent.max_rounds == 6

    def test_default_max_tool_calls(self):
        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        assert agent.max_tool_calls == 30

    def test_custom_max_rounds(self):
        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock(), max_rounds=20)
        assert agent.max_rounds == 20

    def test_custom_max_tool_calls(self):
        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock(), max_tool_calls=100)
        assert agent.max_tool_calls == 100


class TestEnrichInterface:
    @pytest.mark.asyncio
    async def test_enrich_accepts_focus_modules(self):
        """enrich() should accept focus_modules without TypeError."""
        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(return_value={
            "content": "# Enriched content\n\nModuleA details.",
            "tool_calls": None,
        })
        mock_graph = MagicMock()
        agent = WikiPageAgent(llm=mock_llm, graph_store=mock_graph)
        result = await agent.enrich(
            "# Test\ncontent",
            focus_modules=["ModuleA", "ModuleB"],
        )
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_enrich_accepts_quality_report(self):
        """enrich() should accept quality_report without TypeError."""
        from wiki.quality_report import QualityReport
        report = QualityReport(
            coverage=0.5,
            citation_density=0.2,
            context_gap_count=1,
            uncovered_modules=["ModuleC"],
        )
        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(return_value={
            "content": "# Enriched\nModuleC details.",
            "tool_calls": None,
        })
        mock_graph = MagicMock()
        agent = WikiPageAgent(llm=mock_llm, graph_store=mock_graph)
        result = await agent.enrich(
            "# Test\ncontent",
            quality_report=report,
        )
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_enrich_accepts_domain_name(self):
        """enrich() should accept domain_name without TypeError."""
        mock_llm = MagicMock()
        mock_llm.complete_with_tools = AsyncMock(return_value={
            "content": "# Content",
            "tool_calls": None,
        })
        mock_graph = MagicMock()
        agent = WikiPageAgent(llm=mock_llm, graph_store=mock_graph)
        result = await agent.enrich(
            "# Test\ncontent",
            domain_name="用户管理",
        )
        assert isinstance(result, str)


class TestExplore:
    @pytest.mark.asyncio
    async def test_explore_returns_working_memory(self):
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        mock_llm.complete_with_tools = AsyncMock(side_effect=[
            {
                "tool_calls": [
                    {
                        "id": "tc1",
                        "function": {
                            "name": "query_module_detail",
                            "arguments": '{"name": "ModA"}',
                        },
                    }
                ],
                "content": None,
            },
            {"tool_calls": None, "content": "done exploring"},
        ])

        agent = WikiPageAgent(mock_llm, mock_graph, max_rounds=10, max_tool_calls=100)
        agent._execute_tool = AsyncMock(return_value={
            "name": "ModA",
            "summary": "Module A handles user requests",
            "methods": [{"name": "handle"}],
        })

        memory = await agent.explore(
            module_names=["ModA"],
            domain_name="test-domain",
            baseline_context="ModA is a controller.",
        )

        assert isinstance(memory, WorkingMemory)
        agent._execute_tool.assert_called()

    @pytest.mark.asyncio
    async def test_explore_discards_llm_text(self):
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        mock_llm.complete_with_tools = AsyncMock(side_effect=[
            {
                "tool_calls": [
                    {
                        "id": "tc1",
                        "function": {
                            "name": "read_code",
                            "arguments": '{"name": "ModA.handle"}',
                        },
                    }
                ],
                "content": "Let me analyze ModA...",
            },
            {"tool_calls": None, "content": "Here is a complete wiki page about ModA..."},
        ])

        agent = WikiPageAgent(mock_llm, mock_graph, max_rounds=10, max_tool_calls=100)
        agent._execute_tool = AsyncMock(return_value={
            "name": "ModA.handle",
            "code": "public void handle() { service.process(); }",
        })

        memory = await agent.explore(
            module_names=["ModA"],
            domain_name="test-domain",
            baseline_context="baseline",
        )

        assert isinstance(memory, WorkingMemory)
        assert len(memory.code_snippets) >= 1

    @pytest.mark.asyncio
    async def test_explore_with_focus_modules(self):
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        mock_llm.complete_with_tools = AsyncMock(return_value={
            "tool_calls": None,
            "content": "done",
        })

        agent = WikiPageAgent(mock_llm, mock_graph, max_rounds=10, max_tool_calls=100)

        memory = await agent.explore(
            module_names=["ModA", "ModB"],
            domain_name="test-domain",
            baseline_context="baseline",
            focus_modules=["ModB"],
        )

        all_content = " ".join(
            str(m.get("content", "")) for m in mock_llm.complete_with_tools.call_args_list[0][0][0]
            if isinstance(m, dict)
        )
        assert "ModB" in all_content


class TestExplorePrompt:
    def test_explore_prompt_has_no_json_output_requirement(self):
        from wiki.agent_prompts import AGENT_EXPLORE_SYSTEM

        formatted = AGENT_EXPLORE_SYSTEM.format(max_rounds=10)
        assert "domain_summary" not in formatted
        assert "core_modules" not in formatted
        assert '"code_snippets"' not in formatted

    def test_explore_prompt_instructs_tool_only(self):
        from wiki.agent_prompts import AGENT_EXPLORE_SYSTEM

        formatted = AGENT_EXPLORE_SYSTEM.format(max_rounds=10)
        assert "工具" in formatted
        assert "不要输出" in formatted or "只需调用工具" in formatted


class TestWrite:
    @pytest.mark.asyncio
    async def test_write_returns_content_from_memory(self):
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        expected_content = (
            "## 概述\n\nModA 是用户管理控制器。\n\n"
            "## 核心业务流程\n\n调用链 A → B → C。\n\n"
            "```java\npublic void handle() {}\n```\n"
        )
        mock_llm.generate = AsyncMock(return_value=expected_content)

        agent = WikiPageAgent(mock_llm, mock_graph)

        memory = WorkingMemory()
        memory.discovered_call_chains.append("A → B → C")
        memory.code_snippets.append("[ModA]\npublic void handle() {}")

        result = await agent.write(
            domain_name="test-domain",
            baseline_context="ModA is a controller.",
            memory=memory,
        )

        assert isinstance(result, str)
        assert len(result) > 100
        mock_llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_does_not_call_tools(self):
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        mock_llm.generate = AsyncMock(
            return_value="## 概述\n\nContent here.\n\n" * 5,
        )
        mock_llm.complete_with_tools = AsyncMock()

        agent = WikiPageAgent(mock_llm, mock_graph)

        memory = WorkingMemory()
        memory.code_snippets.append("[ModA]\nsome code")

        await agent.write(
            domain_name="test-domain",
            baseline_context="baseline",
            memory=memory,
        )

        mock_llm.complete_with_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_strips_artifacts(self):
        mock_llm = MagicMock()
        mock_graph = MagicMock()

        raw_output = (
            "让我基于工作记忆生成文档...\n"
            "## 概述\n\nModA 处理用户请求。\n\n"
            "## 核心流程\n\nA 调用 B。\n\n"
        )
        mock_llm.generate = AsyncMock(return_value=raw_output)

        agent = WikiPageAgent(mock_llm, mock_graph)
        memory = WorkingMemory()
        memory.code_snippets.append("[ModA]\ncode")

        result = await agent.write(
            domain_name="test-domain",
            baseline_context="baseline",
            memory=memory,
        )

        assert not result.startswith("让我")
        assert "## 概述" in result


class TestWritePrompt:
    def test_write_prompt_has_length_constraint(self):
        from wiki.agent_prompts import AGENT_WRITE_SYSTEM

        assert "2-3 段" in AGENT_WRITE_SYSTEM or "至少" in AGENT_WRITE_SYSTEM

    def test_write_prompt_has_core_constraints(self):
        from wiki.agent_prompts import AGENT_WRITE_SYSTEM

        assert "100% 代码溯源" in AGENT_WRITE_SYSTEM
        assert "CONTEXT_GAP" in AGENT_WRITE_SYSTEM


class TestToolTiering:
    def test_tool_tiers_cover_all_tools(self):
        """T1 + T2 + T3 should contain all AGENT_TOOLS."""
        from wiki.page_agent import AGENT_TOOLS, AGENT_TOOLS_T1, AGENT_TOOLS_T2, AGENT_TOOLS_T3

        all_tiered_names = {t["function"]["name"] for t in AGENT_TOOLS_T1 + AGENT_TOOLS_T2 + AGENT_TOOLS_T3}
        all_names = {t["function"]["name"] for t in AGENT_TOOLS}
        assert all_tiered_names == all_names

    def test_t1_contains_core_tools(self):
        from wiki.page_agent import AGENT_TOOLS_T1

        t1_names = {t["function"]["name"] for t in AGENT_TOOLS_T1}
        assert "query_module_detail" in t1_names
        assert "read_code" in t1_names
        assert "query_call_chain" in t1_names

    def test_t3_contains_supplementary_tools(self):
        from wiki.page_agent import AGENT_TOOLS_T3

        t3_names = {t["function"]["name"] for t in AGENT_TOOLS_T3}
        assert "grep_code" in t3_names
        assert "list_files" in t3_names
        assert "delegate_submodule" in t3_names

    def test_get_tools_round_1_returns_t1_only(self):
        from wiki.page_agent import AGENT_TOOLS_T1, WikiPageAgent

        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        tools = agent._get_tools_for_round(1, has_empty_results=False)
        assert len(tools) == len(AGENT_TOOLS_T1)

    def test_get_tools_round_3_returns_t1_t2(self):
        from wiki.page_agent import AGENT_TOOLS_T1, AGENT_TOOLS_T2, WikiPageAgent

        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        tools = agent._get_tools_for_round(3, has_empty_results=False)
        assert len(tools) == len(AGENT_TOOLS_T1) + len(AGENT_TOOLS_T2)

    def test_get_tools_round_5_returns_all(self):
        from wiki.page_agent import AGENT_TOOLS, WikiPageAgent

        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        tools = agent._get_tools_for_round(5, has_empty_results=False)
        assert len(tools) == len(AGENT_TOOLS)

    def test_get_tools_empty_results_unlocks_all(self):
        from wiki.page_agent import AGENT_TOOLS, WikiPageAgent

        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())
        tools = agent._get_tools_for_round(1, has_empty_results=True)
        assert len(tools) == len(AGENT_TOOLS)

    def test_get_tools_empty_results_with_prefilled_memory(self):
        """Pre-filled memory should NOT prevent empty-results tool unlock."""
        from wiki.page_agent import AGENT_TOOLS, WikiPageAgent, WorkingMemory

        agent = WikiPageAgent(llm=MagicMock(), graph_store=MagicMock())

        memory = WorkingMemory()
        memory.code_snippets.append("[func @ file.java]\npublic void foo() {}")
        assert memory._total_chars() > 0
        assert memory._tool_contributed_chars == 0

        has_empty = True and memory._tool_contributed_chars == 0
        tools = agent._get_tools_for_round(1, has_empty)
        assert len(tools) == len(AGENT_TOOLS)
