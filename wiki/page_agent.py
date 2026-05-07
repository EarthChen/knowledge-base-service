"""Agent framework for enriching wiki pages with CONTEXT_GAP remediation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_CONTEXT_GAP_RE = re.compile(r"<!--\s*CONTEXT_GAP:\s*(.+?)\s*-->")


@dataclass
class ToolResult:
    tool: str
    data: dict[str, Any]


@dataclass
class WorkingMemory:
    discovered_call_chains: list[str] = field(default_factory=list)
    discovered_implementations: list[str] = field(default_factory=list)
    discovered_callers: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)
    resolved_gaps: list[str] = field(default_factory=list)

    MAX_TOTAL_CHARS = 6000

    def incorporate(self, results: list[ToolResult]) -> None:
        for r in results:
            tool = r.tool
            data = r.data
            if tool == "query_call_chain":
                chains = data.get("chains", [])
                for c in chains:
                    entry = str(c.get("entry", "") or "")
                    chain_nodes = c.get("chain", [])
                    if isinstance(chain_nodes, list):
                        chain_str = " → ".join(str(n) for n in chain_nodes)
                    else:
                        chain_str = str(chain_nodes)
                    self.discovered_call_chains.append(f"{entry}: {chain_str}")
            elif tool == "query_callers":
                callers = data.get("callers", [])
                for c in callers:
                    caller = str(c.get("caller_name", "") or "")
                    target = str(c.get("target_name", "") or "")
                    if caller and target:
                        self.discovered_callers.append(f"{caller} → {target}")
            elif tool == "query_callees":
                callees = data.get("callees", [])
                for c in callees:
                    caller = str(c.get("caller_name", "") or "")
                    target = str(c.get("target_name", "") or "")
                    if caller and target:
                        self.discovered_callers.append(f"{caller} → {target}")
            elif tool == "query_implementations":
                impls = data.get("implementations", [])
                for imp in impls:
                    impl_name = str(imp.get("impl_name", "") or "")
                    intf_name = str(imp.get("interface_name", "") or "")
                    if impl_name and intf_name:
                        self.discovered_implementations.append(
                            f"{impl_name} implements {intf_name}"
                        )
            elif tool == "read_source_snippet":
                snippet = str(data.get("snippet", "") or "")
                func_name = str(data.get("func_name", "") or "")
                if snippet:
                    truncated = snippet[:400]
                    self.code_snippets.append(f"// {func_name}\n{truncated}")
            elif tool == "query_module_detail":
                summary = str(data.get("summary", "") or "")
                name = str(data.get("name", "") or "")
                methods = data.get("methods", [])
                if summary:
                    entry = f"{name}: {summary}"
                    if methods:
                        method_names = [str(m.get("name", "")) for m in methods[:5]]
                        entry += f" [methods: {', '.join(method_names)}]"
                    self.discovered_call_chains.append(entry)
        self._enforce_limit()

    def _enforce_limit(self) -> None:
        total = self._total_chars()
        while total > self.MAX_TOTAL_CHARS:
            removed = False
            for lst in [
                self.code_snippets,
                self.discovered_callers,
                self.discovered_implementations,
                self.discovered_call_chains,
                self.resolved_gaps,
            ]:
                if lst:
                    lst.pop(0)
                    removed = True
                    break
            if not removed:
                break
            total = self._total_chars()

    def _total_chars(self) -> int:
        total = 0
        for lst in [
            self.discovered_call_chains,
            self.discovered_implementations,
            self.discovered_callers,
            self.code_snippets,
            self.resolved_gaps,
        ]:
            total += sum(len(s) for s in lst)
        return total

    def to_prompt_section(self) -> str:
        sections: list[str] = []
        if self.discovered_call_chains:
            sections.append("### 已发现的调用链和模块信息")
            sections.extend(f"- {c}" for c in self.discovered_call_chains)
        if self.discovered_implementations:
            sections.append("### 已发现的接口实现")
            sections.extend(f"- {i}" for i in self.discovered_implementations)
        if self.discovered_callers:
            sections.append("### 已发现的调用关系")
            sections.extend(f"- {c}" for c in self.discovered_callers)
        if self.code_snippets:
            sections.append("### 已发现的代码片段")
            sections.extend(self.code_snippets)
        if self.resolved_gaps:
            sections.append("### 已解决的信息缺口")
            sections.extend(f"- {g}" for g in self.resolved_gaps)
        if not sections:
            return "（工作记忆为空）"
        return "\n".join(sections)


AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_module_detail",
            "description": "Query detailed info about a module including methods, annotations, summary",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Module name"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_callers",
            "description": "Query which modules call the given module",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Target module name"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_callees",
            "description": "Query which modules the given module calls",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Caller module name"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_implementations",
            "description": "Query implementations of an interface",
            "parameters": {
                "type": "object",
                "properties": {"interface": {"type": "string", "description": "Interface name"}},
                "required": ["interface"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_call_chain",
            "description": "Query method-level call chain starting from a module",
            "parameters": {
                "type": "object",
                "properties": {"module_name": {"type": "string", "description": "Entry module name"}},
                "required": ["module_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_source_snippet",
            "description": "Read source code snippet for a function",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Function or class name"},
                    "max_lines": {"type": "integer", "description": "Max lines to return", "default": 30},
                },
                "required": ["name"],
            },
        },
    },
]

_AGENT_SYSTEM = """你是一个代码知识库 Agent。你的任务是通过调用 tools 来补充 Wiki 页面中标记为 CONTEXT_GAP 的缺失信息。

规则：
1. 分析页面中的 CONTEXT_GAP 标记，确定需要查询的信息
2. 使用提供的 tools 查询缺失的上下文
3. 当你获得足够信息后，生成补充后的完整页面内容（去掉 CONTEXT_GAP 标记）
4. 如果某个 gap 无法通过 tools 解决，保留原始标记

输出要求：直接输出完整的 Wiki 页面 Markdown 内容（不需要 JSON 包装）。
"""


class WikiPageAgent:
    MAX_ROUNDS = 5

    def __init__(self, llm: Any, graph_store: Any) -> None:
        self._llm = llm
        self._graph = graph_store

    async def enrich(self, content: str, *, domain_name: str = "") -> str:
        gaps = _CONTEXT_GAP_RE.findall(content)
        if not gaps:
            return content

        memory = WorkingMemory()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _AGENT_SYSTEM},
            {"role": "user", "content": self._build_user_prompt(content, gaps, memory, domain_name)},
        ]

        for round_num in range(self.MAX_ROUNDS):
            try:
                response = await self._llm.complete_with_tools(
                    messages, AGENT_TOOLS,
                )
            except Exception:
                log.warning("agent_llm_call_failed", round=round_num, exc_info=True)
                break

            tool_calls = response.get("tool_calls")
            text_content = response.get("content")

            if not tool_calls:
                if text_content:
                    return str(text_content)
                break

            tool_results: list[ToolResult] = []
            messages.append(response)

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                result_data = await self._execute_tool(tool_name, args)
                tool_results.append(ToolResult(tool=tool_name, data=result_data))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result_data, ensure_ascii=False, default=str)[:2000],
                })

            memory.incorporate(tool_results)
            messages = [
                {"role": "system", "content": _AGENT_SYSTEM},
                {"role": "user", "content": self._build_user_prompt(content, gaps, memory, domain_name)},
            ]

        try:
            fallback = await self._llm.generate(
                prompt=self._build_user_prompt(content, gaps, memory, domain_name),
                system=_AGENT_SYSTEM,
            )
            return fallback
        except Exception:
            log.warning("agent_fallback_failed", exc_info=True)
            return content

    def _build_user_prompt(
        self, content: str, gaps: list[str], memory: WorkingMemory, domain_name: str,
    ) -> str:
        parts = [
            f"## 当前 Wiki 页面（域: {domain_name}）",
            content,
            "",
            "## 待解决的 CONTEXT_GAP",
        ]
        for i, gap in enumerate(gaps, 1):
            parts.append(f"{i}. {gap}")
        parts.append("")
        parts.append("## 工作记忆（之前查询的结果）")
        parts.append(memory.to_prompt_section())
        parts.append("")
        parts.append("请使用 tools 查询缺失信息，或直接输出补充后的完整页面。")
        return "\n".join(parts)

    async def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if tool_name == "query_module_detail":
                return await self._tool_query_module_detail(args)
            elif tool_name == "query_callers":
                return await self._tool_query_callers(args)
            elif tool_name == "query_callees":
                return await self._tool_query_callees(args)
            elif tool_name == "query_implementations":
                return await self._tool_query_implementations(args)
            elif tool_name == "query_call_chain":
                return await self._tool_query_call_chain(args)
            elif tool_name == "read_source_snippet":
                return await self._tool_read_source_snippet(args)
            else:
                return {"error": f"unknown tool: {tool_name}"}
        except Exception as e:
            log.warning("agent_tool_failed", tool=tool_name, error=str(e))
            return {"error": str(e)}

    async def _tool_query_module_detail(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", ""))
        if not name or not self._graph:
            return {"error": "missing name or graph"}
        from wiki.cypher_queries import METHODS_CY

        result = await self._graph.execute_query(METHODS_CY, {"names": [name]})
        rows = getattr(result, "data", None) or []
        methods = []
        for row in rows:
            if isinstance(row, dict):
                methods.append({
                    "name": str(row.get("func_name", "") or ""),
                    "signature": str(row.get("signature", "") or ""),
                    "file": str(row.get("file_path", "") or ""),
                })
        return {"name": name, "methods": methods[:20], "summary": ""}

    async def _tool_query_callers(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", ""))
        if not name or not self._graph:
            return {"error": "missing name or graph"}
        from wiki.cypher_queries import CALLERS_CY

        result = await self._graph.execute_query(CALLERS_CY, {"names": [name]})
        rows = getattr(result, "data", None) or []
        callers = []
        for row in rows:
            if isinstance(row, dict):
                callers.append({
                    "caller_name": str(row.get("caller_name", "") or ""),
                    "target_name": str(row.get("target_name", "") or ""),
                })
        return {"callers": callers[:15]}

    async def _tool_query_callees(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", ""))
        if not name or not self._graph:
            return {"error": "missing name or graph"}
        from wiki.cypher_queries import call_chain_cypher

        cy = call_chain_cypher(1)
        result = await self._graph.execute_query(cy, {"names": [name]})
        rows = getattr(result, "data", None) or []
        callees = []
        for row in rows:
            if isinstance(row, dict):
                callees.append({
                    "caller_name": str(row.get("caller", "") or ""),
                    "target_name": str(row.get("callee", "") or ""),
                })
        return {"callees": callees[:15]}

    async def _tool_query_implementations(self, args: dict[str, Any]) -> dict[str, Any]:
        interface = str(args.get("interface", ""))
        if not interface or not self._graph:
            return {"error": "missing interface or graph"}
        from wiki.cypher_queries import IMPLEMENTS_BY_INTERFACE_CY

        result = await self._graph.execute_query(IMPLEMENTS_BY_INTERFACE_CY, {"names": [interface]})
        rows = getattr(result, "data", None) or []
        impls = []
        for row in rows:
            if isinstance(row, dict):
                impls.append({
                    "impl_name": str(row.get("impl_name", "") or ""),
                    "interface_name": str(row.get("interface_name", "") or ""),
                })
        return {"implementations": impls[:10]}

    async def _tool_query_call_chain(self, args: dict[str, Any]) -> dict[str, Any]:
        module_name = str(args.get("module_name", ""))
        if not module_name or not self._graph:
            return {"error": "missing module_name or graph"}
        from wiki.call_chain_builder import CallChainBuilder

        builder = CallChainBuilder(self._graph)
        chains = await builder.build_chains([module_name], max_depth=3, max_chains=5)
        return {
            "chains": [
                {
                    "entry": f"{c.entry_module}.{c.entry_method}",
                    "chain": [f"{n.module_name}.{n.func_name}" for n in c.chain],
                    "depth": c.depth,
                }
                for c in chains
            ]
        }

    async def _tool_read_source_snippet(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", ""))
        if not name or not self._graph:
            return {"error": "missing name or graph"}
        from wiki.cypher_queries import SNIPPET_BY_FUNC_CY

        result = await self._graph.execute_query(SNIPPET_BY_FUNC_CY, {"names": [name]})
        rows = getattr(result, "data", None) or []
        for row in rows:
            if isinstance(row, dict):
                snippet = str(row.get("snippet", "") or "")
                if snippet:
                    return {
                        "func_name": str(row.get("func_name", "") or ""),
                        "snippet": snippet[:600],
                        "file": str(row.get("file_path", "") or ""),
                    }
        return {"func_name": name, "snippet": "", "file": ""}
