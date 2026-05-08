"""Agent framework for enriching wiki pages with CONTEXT_GAP remediation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger
from wiki.context_gap import CONTEXT_GAP_DETECT_RE as _CONTEXT_GAP_RE

log = get_logger(__name__)

_THINKING_PREFIX_RE = re.compile(
    r"^(我需要|让我|从工作记忆|需要先|接下来我|首先我|I need to|Let me)",
)
_TOOL_JSON_BLOCK_RE = re.compile(
    r"```json\s*\{[\s\S]*?\"tools\"[\s\S]*?\}\s*```",
    re.MULTILINE,
)
_FIRST_HEADING_RE = re.compile(r"^(#{1,3}\s)", re.MULTILINE)
SINGLE_RESULT_LIMIT = 4000


def strip_agent_artifacts(text: str) -> str:
    """Remove LLM agent thinking/reasoning text and inline tool-call JSON from wiki content."""
    if not text or not text.strip():
        return ""
    stripped = _TOOL_JSON_BLOCK_RE.sub("", text)
    stripped = stripped.strip()
    if _THINKING_PREFIX_RE.match(stripped):
        m = _FIRST_HEADING_RE.search(stripped)
        if m:
            stripped = stripped[m.start():]
        else:
            stripped = ""
    return stripped.strip()

_GREP_MAX_FILE_SIZE = 512 * 1024  # 512 KB
_GREP_BINARY_EXTENSIONS = {
    ".jar",
    ".class",
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".zip",
    ".tar",
    ".gz",
    ".png",
    ".jpg",
    ".gif",
    ".ico",
    ".woff",
    ".ttf",
}


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
    wiki_references: list[str] = field(default_factory=list)
    search_findings: list[str] = field(default_factory=list)

    MAX_TOTAL_CHARS = 50000

    def incorporate(self, results: list[ToolResult]) -> None:
        for r in results:
            tool = r.tool
            data = r.data
            if tool == "read_code":
                if data.get("ambiguous"):
                    for m in data.get("matches", []):
                        code = str(m.get("code", "") or "")
                        name = str(m.get("name", "") or "")
                        fpath = str(m.get("file", "") or "")
                        if code:
                            self.code_snippets.append(f"[{name} @ {fpath}]\n{code[:SINGLE_RESULT_LIMIT]}")
                else:
                    code = str(data.get("code", "") or "")
                    name = str(data.get("name", "") or "")
                    if code:
                        self.code_snippets.append(f"[{name}]\n{code[:SINGLE_RESULT_LIMIT]}")
            elif tool == "read_file":
                content = str(data.get("content", "") or "")
                path = str(data.get("file_path", "") or "")
                if content:
                    self.code_snippets.append(f"[{path}]\n{content[:SINGLE_RESULT_LIMIT]}")
            elif tool == "search_entities":
                items = data.get("results", [])
                for item in items[:5]:
                    if isinstance(item, dict):
                        self.search_findings.append(
                            f"{item.get('type', '')} {item.get('name', '')} ({item.get('file', '')})"
                        )
            elif tool == "read_wiki_page":
                content = str(data.get("content", "") or "")
                title = str(data.get("title", "") or "")
                if content:
                    self.wiki_references.append(f"[{title}] {content[:2000]}")
            elif tool == "semantic_search":
                items = data.get("results", [])
                for item in items[:3]:
                    if isinstance(item, dict):
                        self.search_findings.append(
                            f"[{item.get('source', '')}] {item.get('title', '')} ({item.get('file_path', '')})"
                        )
            elif tool == "list_files":
                files = data.get("files", [])
                if files:
                    listing = "\n".join(f"  {f}" for f in files[:30])
                    self.search_findings.append(f"[{data.get('directory', '')}]\n{listing}")
            elif tool == "grep_code":
                matches = data.get("matches", [])
                for m in matches[:5]:
                    if isinstance(m, dict):
                        self.search_findings.append(
                            f"[grep:{m.get('file', '')}:{m.get('line', '')}] "
                            f"{str(m.get('content', '') or '')[:200]}"
                        )
            elif tool == "query_call_chain":
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
            elif tool == "query_domain_dependencies":
                deps = data.get("outgoing", [])
                for d in deps[:5]:
                    if isinstance(d, dict):
                        self.discovered_call_chains.append(
                            f"{data.get('domain', '')} → {d.get('target_domain', '')}: {d.get('via', '')}"
                        )
                incoming = data.get("incoming", [])
                for d in incoming[:5]:
                    if isinstance(d, dict):
                        self.discovered_callers.append(
                            f"{d.get('source_domain', '')} → {data.get('domain', '')}: {d.get('via', '')}"
                        )
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
                self.wiki_references,
                self.search_findings,
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
            self.wiki_references,
            self.search_findings,
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
        if self.wiki_references:
            sections.append("### 已引用的 Wiki 页面")
            sections.extend(self.wiki_references)
        if self.search_findings:
            sections.append("### 搜索发现")
            sections.extend(f"- {f}" for f in self.search_findings)
        if not sections:
            return "（工作记忆为空）"
        return "\n".join(sections)


AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_module_detail",
            "description": (
                "Query detailed info about a module including methods and annotations. "
                "Use when you need to understand a module's internal structure."
            ),
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
            "description": (
                "Query which modules call the given module. "
                "Use when you need to understand who depends on a module."
            ),
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
            "description": (
                "Query which modules the given module calls. "
                "Use when you need to understand a module's outgoing dependencies."
            ),
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
            "description": (
                "Query implementations of an interface. "
                "Use when you need to find concrete classes for an abstract interface."
            ),
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
            "description": (
                "Query method-level call chain starting from a module. "
                "Use when you need to trace execution flow across multiple modules."
            ),
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
            "name": "query_domain_dependencies",
            "description": (
                "Query cross-domain call dependencies for a domain. Use when writing domain overviews "
                "to understand how this domain interacts with other domains."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain_name": {"type": "string", "description": "Domain name to query dependencies for"},
                },
                "required": ["domain_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_code",
            "description": (
                "Read source code for a function or class by name (up to 3000 chars). "
                "Use when you need to understand implementation details of a specific indexed entity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "Function or class name"},
                    "max_chars": {"type": "integer", "description": "Max characters to return (default 3000)"},
                },
                "required": ["entity_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read file content by relative path. Use for config files, non-indexed source, "
                "or any file not in the code graph (e.g. .yaml, .xml, .properties)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path from repository root"},
                    "start_line": {"type": "integer", "description": "Start line (1-based, default 1)"},
                    "end_line": {"type": "integer", "description": "End line (default start+100)"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entities",
            "description": (
                "Search code entities by keyword in names and docstrings. "
                "Use when you don't know the exact name and need to discover related functions or classes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Keyword to search for (case-insensitive)"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_wiki_page",
            "description": (
                "Read an existing wiki page by path or title keyword. "
                "Use to check what's already documented and avoid content duplication."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Page path or title keyword"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": (
                "Semantic search across code and wiki using natural language. "
                "Use when keyword search fails and you need conceptual or fuzzy matching."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query"},
                    "limit": {"type": "integer", "description": "Max results (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files in a directory. Use when you need to explore project structure or "
                "find related config/resource files near a module."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Relative directory path from repo root (e.g. 'src/main/java/com/payment')",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Max directory depth to traverse (default 2, max 3)",
                    },
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_code",
            "description": (
                "Search for text patterns in source files. Use when you need to find specific "
                "string literals, error messages, constants, or usage patterns across the codebase."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Text or regex pattern to search for",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": (
                            "Glob pattern to filter files (e.g. '*.java', '*.py'). "
                            "Default: all text files."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max matching lines to return (default 10, max 20)",
                    },
                },
                "required": ["pattern"],
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
    MAX_ROUNDS = 6
    MAX_TOOL_CALLS = 15
    _MAX_HISTORY_MESSAGES = 30

    def __init__(
        self,
        llm: Any,
        graph_store: Any,
        *,
        repo_path: str | None = None,
        search_service: Any | None = None,
    ) -> None:
        self._llm = llm
        self._graph = graph_store
        self._repo_path = repo_path
        self._search_service = search_service
        self._existing_pages: list[dict] | None = None

    async def enrich(
        self,
        content: str,
        *,
        domain_name: str = "",
        existing_pages: list[dict] | None = None,
    ) -> str:
        gaps = _CONTEXT_GAP_RE.findall(content)
        if not gaps:
            return content

        self._existing_pages = existing_pages
        memory = WorkingMemory()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _AGENT_SYSTEM},
            {"role": "user", "content": self._build_user_prompt(content, gaps, memory, domain_name)},
        ]

        total_tool_calls = 0
        for round_num in range(self.MAX_ROUNDS):
            try:
                response = await self._llm.complete_with_tools(messages, AGENT_TOOLS)
            except Exception:
                log.warning("agent_llm_call_failed", round=round_num, exc_info=True)
                break

            tool_calls = response.get("tool_calls")
            text_content = response.get("content")

            if not tool_calls:
                if text_content:
                    cleaned = strip_agent_artifacts(str(text_content))
                    if cleaned:
                        return cleaned
                    log.warning("agent_output_was_pure_thinking", domain=domain_name)
                    break
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

            total_tool_calls += len(tool_calls)
            if total_tool_calls >= self.MAX_TOOL_CALLS:
                log.info("agent_max_tool_calls_reached", total=total_tool_calls)
                break

            memory.incorporate(tool_results)
            if len(messages) > self._MAX_HISTORY_MESSAGES:
                messages = [
                    {"role": "system", "content": _AGENT_SYSTEM},
                    {"role": "user", "content": self._build_user_prompt(content, gaps, memory, domain_name)},
                ]
                log.info("agent_history_compressed", round=round_num)

        try:
            fallback = await self._llm.generate(
                prompt=self._build_user_prompt(content, gaps, memory, domain_name),
                system=_AGENT_SYSTEM,
            )
            cleaned = strip_agent_artifacts(fallback)
            if cleaned:
                return cleaned
            log.warning("agent_fallback_was_pure_thinking", domain=domain_name)
            return content
        except Exception:
            log.warning("agent_fallback_failed", exc_info=True)
            return content

    async def generate(
        self,
        module_names: list[str],
        domain_name: str,
        baseline_context: dict[str, Any],
        max_rounds: int = 10,
    ) -> str:
        """Agent-Driven: query context with tools and generate a full Wiki page."""
        from wiki.agent_prompts import AGENT_GENERATE_SYSTEM

        system = AGENT_GENERATE_SYSTEM.format(max_rounds=max_rounds)
        modules_desc = ", ".join(module_names)
        baseline_str = str(baseline_context)[:2000]

        user_prompt = (
            f"为以下模块生成 Wiki 页面:\n"
            f"域名: {domain_name}\n"
            f"模块: {modules_desc}\n"
            f"基线上下文: {baseline_str}\n\n"
            f"请使用工具查询更多信息后生成完整页面。"
        )

        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ]

            total_tool_calls = 0
            for round_num in range(max_rounds):
                try:
                    response = await self._llm.complete_with_tools(messages, AGENT_TOOLS)
                except Exception:
                    log.warning("agent_generate_llm_failed", round=round_num, exc_info=True)
                    break

                tool_calls = response.get("tool_calls")
                text_content = response.get("content")

                if not tool_calls:
                    if text_content:
                        cleaned = strip_agent_artifacts(str(text_content))
                        if cleaned and len(cleaned) > 200:
                            return cleaned
                    break

                messages.append(response)
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "")
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    result_data = await self._execute_tool(tool_name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result_data, ensure_ascii=False, default=str)[:SINGLE_RESULT_LIMIT],
                    })

                total_tool_calls += len(tool_calls)
                if total_tool_calls >= self.MAX_TOOL_CALLS:
                    break

                if len(messages) > self._MAX_HISTORY_MESSAGES:
                    messages = [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt + "\n\n请基于已有信息直接生成完整页面。"},
                    ]

            # Final attempt: ask LLM to generate with accumulated context
            fallback = await self._llm.generate(
                prompt=user_prompt + "\n\n请基于已有信息直接生成完整 Wiki 页面。",
                system=system,
            )
            cleaned = strip_agent_artifacts(fallback)
            if cleaned and len(cleaned) > 200:
                return cleaned

        except Exception:
            log.warning("agent_generate_failed", domain=domain_name, exc_info=True)

        return self._generate_skeleton(module_names, domain_name)

    def _generate_skeleton(self, module_names: list[str], domain_name: str) -> str:
        """Generate minimal page skeleton when agent fails."""
        modules_list = "\n".join(f"- `{m}`" for m in module_names)
        return (
            f"# {domain_name}\n\n"
            f"## 概述\n\n{domain_name} 包含以下模块:\n{modules_list}\n\n"
            f"<!-- CONTEXT_GAP: Agent 生成失败，需要手动补充内容 -->\n\n"
            f"## 核心业务流程\n\n"
            f"<!-- CONTEXT_GAP: 调用链数据未能获取 -->\n\n"
            f"## 关键实现\n\n"
            f"<!-- CONTEXT_GAP: 代码实现细节未能获取 -->\n\n"
            f"## 依赖关系\n\n"
            f"<!-- CONTEXT_GAP: 依赖关系数据未能获取 -->\n"
        )

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
            if tool_name == "read_code":
                return await self._tool_read_code(args)
            elif tool_name == "read_file":
                return await self._tool_read_file(args)
            elif tool_name == "search_entities":
                return await self._tool_search_entities(args)
            elif tool_name == "read_wiki_page":
                return await self._tool_read_wiki_page(args)
            elif tool_name == "semantic_search":
                return await self._tool_semantic_search(args)
            elif tool_name == "list_files":
                return await self._tool_list_files(args)
            elif tool_name == "grep_code":
                return await self._tool_grep_code(args)
            elif tool_name == "query_module_detail":
                return await self._tool_query_module_detail(args)
            elif tool_name == "query_callers":
                return await self._tool_query_callers(args)
            elif tool_name == "query_callees":
                return await self._tool_query_callees(args)
            elif tool_name == "query_implementations":
                return await self._tool_query_implementations(args)
            elif tool_name == "query_call_chain":
                return await self._tool_query_call_chain(args)
            elif tool_name == "query_domain_dependencies":
                return await self._tool_query_domain_dependencies(args)
            elif tool_name == "read_source_snippet":
                return await self._tool_read_source_snippet(args)
            else:
                return {"error": f"unknown tool: {tool_name}"}
        except Exception as e:
            log.warning("agent_tool_failed", tool=tool_name, error=str(e))
            return {"error": str(e)}

    async def _tool_read_code(self, args: dict[str, Any]) -> dict[str, Any]:
        entity_name = str(args.get("entity_name", ""))
        try:
            max_chars = max(0, min(int(args.get("max_chars", 3000) or 3000), 10000))
        except (TypeError, ValueError):
            max_chars = 3000
        if not entity_name or not self._graph or not hasattr(self._graph, "execute_query"):
            return {"name": entity_name, "code": "", "file": "", "type": ""}
        from wiki.cypher_queries import ENTITY_LOCATION_CY

        result = await self._graph.execute_query(ENTITY_LOCATION_CY, {"name": entity_name})
        rows = getattr(result, "data", None) or []
        matches: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                snippet = str(row.get("snippet", "") or "")
                matches.append({
                    "name": str(row.get("name", "") or ""),
                    "type": str(row.get("type", "") or ""),
                    "file": str(row.get("file", "") or ""),
                    "start_line": int(row.get("start_line", 0) or 0),
                    "end_line": int(row.get("end_line", 0) or 0),
                    "code": snippet[:max_chars],
                })
        if not matches:
            return {"name": entity_name, "code": "", "file": "", "type": ""}
        if len(matches) == 1:
            return matches[0]
        return {"name": entity_name, "matches": matches, "ambiguous": True}

    _MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

    async def _tool_read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        from pathlib import Path

        file_path = str(args.get("file_path", ""))
        start_line = max(1, int(args.get("start_line", 1) or 1))
        end_line = int(args.get("end_line", 0) or 0)
        if not end_line:
            end_line = start_line + 100
        if end_line < start_line:
            end_line = start_line + 100
        if not file_path or file_path.startswith("/"):
            return {"error": "missing or absolute file_path"}
        if not self._repo_path:
            return {"error": "file reading unavailable"}
        repo_root = Path(self._repo_path).resolve()
        target = (repo_root / file_path).resolve()
        if not target.is_relative_to(repo_root):
            return {"error": "path traversal not allowed"}
        if not target.is_file():
            return {"error": f"file not found: {file_path}"}
        try:
            file_size = target.stat().st_size
            if file_size > self._MAX_FILE_SIZE:
                return {"error": f"file too large: {file_size} bytes (max {self._MAX_FILE_SIZE})"}
            all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(all_lines)
            selected = all_lines[max(0, start_line - 1):end_line]
            content = "\n".join(selected)
            return {
                "file_path": file_path,
                "start_line": start_line,
                "end_line": min(end_line, total_lines),
                "content": content[: SINGLE_RESULT_LIMIT],
                "total_lines": total_lines,
            }
        except OSError as e:
            return {"error": f"read failed: {e}"}

    async def _tool_search_entities(self, args: dict[str, Any]) -> dict[str, Any]:
        keyword = str(args.get("keyword", ""))
        limit = min(int(args.get("limit", 10) or 10), 20)
        if not keyword or not self._graph or not hasattr(self._graph, "execute_query"):
            return {"results": [], "total": 0}
        from wiki.cypher_queries import SEARCH_ENTITY_LABELS, search_entity_cypher

        results: list[dict[str, str]] = []
        for label in SEARCH_ENTITY_LABELS:
            if len(results) >= limit:
                break
            per_label_limit = limit - len(results)
            cy = search_entity_cypher(label)
            result = await self._graph.execute_query(cy, {"keyword": keyword, "limit": per_label_limit})
            rows = getattr(result, "data", None) or []
            for row in rows:
                if isinstance(row, dict):
                    results.append({
                        "name": str(row.get("name", "") or ""),
                        "type": str(row.get("type", "") or ""),
                        "file": str(row.get("file", "") or ""),
                        "signature": str(row.get("signature", "") or ""),
                        "docstring": str(row.get("docstring", "") or ""),
                    })
        truncated = len(results) >= limit
        return {"results": results[:limit], "total": len(results), "truncated": truncated}

    async def _tool_read_wiki_page(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", ""))
        if not query:
            return {"title": "", "path": "", "content": ""}
        if self._existing_pages:
            q_lower = query.lower()
            for page in self._existing_pages:
                if not isinstance(page, dict):
                    continue
                title = str(page.get("title", "") or "")
                path = str(page.get("path", "") or "")
                content = str(page.get("content", "") or "")
                if q_lower in title.lower() or q_lower in path.lower():
                    return {"title": title, "path": path, "content": content[: SINGLE_RESULT_LIMIT]}
        if self._graph and hasattr(self._graph, "execute_query"):
            from wiki.cypher_queries import WIKI_PAGE_BY_QUERY_CY

            result = await self._graph.execute_query(
                WIKI_PAGE_BY_QUERY_CY, {"query": query, "content_max_chars": SINGLE_RESULT_LIMIT},
            )
            rows = getattr(result, "data", None) or []
            for row in rows:
                if isinstance(row, dict):
                    return {
                        "title": str(row.get("title", "") or ""),
                        "path": str(row.get("path", "") or ""),
                        "content": str(row.get("content", "") or ""),
                    }
        return {"title": "", "path": "", "content": ""}

    async def _tool_semantic_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", ""))
        limit = min(int(args.get("limit", 5) or 5), 10)
        if not query:
            return {"results": []}
        if not self._search_service:
            return {"error": "semantic search unavailable"}
        try:
            raw = await self._search_service.search_with_context(
                query,
                k=limit,
                expand_depth=1,
                include_callers=False,
                include_callees=False,
                use_query_expansion=False,
            )
            hits = raw.get("results", [])
            results = []
            for hit in hits[:limit]:
                if isinstance(hit, dict):
                    results.append({
                        "title": str(hit.get("entity_name", "") or hit.get("name", "") or ""),
                        "file_path": str(hit.get("file_path", "") or ""),
                        "source": str(hit.get("source_type", "code") or "code"),
                        "score": float(hit.get("score", 0) or 0),
                    })
            return {"results": results}
        except Exception as e:
            log.warning("semantic_search_failed", error=str(e))
            return {"error": str(e)}

    async def _tool_list_files(self, args: dict[str, Any]) -> dict[str, Any]:
        from pathlib import Path

        directory = str(args.get("directory", ""))
        max_depth = min(max(1, int(args.get("max_depth", 2) or 2)), 3)
        if not directory or directory.startswith("/"):
            return {"error": "missing or absolute directory path"}
        if not self._repo_path:
            return {"error": "file listing unavailable"}
        repo_root = Path(self._repo_path).resolve()
        target = (repo_root / directory).resolve()
        if not target.is_relative_to(repo_root):
            return {"error": "path traversal not allowed"}
        if not target.is_dir():
            return {"error": f"not a directory: {directory}"}

        files: list[str] = []
        _MAX_ENTRIES = 50

        def _walk(path: Path, depth: int) -> None:
            if depth > max_depth or len(files) >= _MAX_ENTRIES:
                return
            try:
                entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            except PermissionError:
                return
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                rel = str(entry.relative_to(repo_root))
                if entry.is_dir():
                    files.append(rel + "/")
                    _walk(entry, depth + 1)
                else:
                    files.append(rel)
                if len(files) >= _MAX_ENTRIES:
                    return

        _walk(target, 1)
        return {
            "directory": directory,
            "files": files[:_MAX_ENTRIES],
            "total": len(files),
            "truncated": len(files) >= _MAX_ENTRIES,
        }

    async def _tool_grep_code(self, args: dict[str, Any]) -> dict[str, Any]:
        from pathlib import Path

        pattern_str = str(args.get("pattern", ""))
        file_pattern = str(args.get("file_pattern", "") or "")
        try:
            max_results = min(max(1, int(args.get("max_results", 10) or 10)), 20)
        except (TypeError, ValueError):
            max_results = 10

        if not pattern_str:
            return {"error": "missing pattern"}
        if not self._repo_path:
            return {"error": "grep unavailable"}

        repo_root = Path(self._repo_path).resolve()
        try:
            regex = re.compile(pattern_str, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern_str), re.IGNORECASE)

        matches: list[dict[str, Any]] = []
        glob_pattern = file_pattern if file_pattern else "*"

        for file_path in repo_root.rglob(glob_pattern):
            if len(matches) >= max_results:
                break
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in _GREP_BINARY_EXTENSIONS:
                continue
            if any(part.startswith(".") for part in file_path.parts):
                continue
            try:
                if file_path.stat().st_size > _GREP_MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            for line_num, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    rel_path = str(file_path.relative_to(repo_root))
                    matches.append({
                        "file": rel_path,
                        "line": line_num,
                        "content": line.strip()[:300],
                    })
                    if len(matches) >= max_results:
                        break

        return {
            "pattern": pattern_str,
            "matches": matches,
            "total": len(matches),
            "truncated": len(matches) >= max_results,
        }

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

    async def _tool_query_domain_dependencies(self, args: dict[str, Any]) -> dict[str, Any]:
        domain_name = str(args.get("domain_name", ""))
        if not domain_name or not self._graph:
            return {"error": "missing domain_name or graph"}

        # Query outgoing: modules in this domain that call modules in other domains
        outgoing_cy = (
            "MATCH (caller)-[:CALLS]->(callee) "
            "WHERE caller.business_domain = $domain AND callee.business_domain <> $domain "
            "AND callee.business_domain IS NOT NULL "
            "RETURN DISTINCT callee.business_domain AS target_domain, "
            "caller.name AS caller_name, callee.name AS callee_name "
            "LIMIT 20"
        )
        # Query incoming: modules in other domains that call modules in this domain
        incoming_cy = (
            "MATCH (caller)-[:CALLS]->(callee) "
            "WHERE callee.business_domain = $domain AND caller.business_domain <> $domain "
            "AND caller.business_domain IS NOT NULL "
            "RETURN DISTINCT caller.business_domain AS source_domain, "
            "caller.name AS caller_name, callee.name AS callee_name "
            "LIMIT 20"
        )

        outgoing: list[dict[str, str]] = []
        incoming: list[dict[str, str]] = []

        try:
            out_result = await self._graph.execute_query(outgoing_cy, {"domain": domain_name})
            for row in (getattr(out_result, "data", None) or []):
                if isinstance(row, dict):
                    outgoing.append({
                        "target_domain": str(row.get("target_domain", "") or ""),
                        "via": f"{row.get('caller_name', '')} → {row.get('callee_name', '')}",
                    })
        except Exception:
            log.warning("query_domain_deps_outgoing_failed", domain=domain_name, exc_info=True)

        try:
            in_result = await self._graph.execute_query(incoming_cy, {"domain": domain_name})
            for row in (getattr(in_result, "data", None) or []):
                if isinstance(row, dict):
                    incoming.append({
                        "source_domain": str(row.get("source_domain", "") or ""),
                        "via": f"{row.get('caller_name', '')} → {row.get('callee_name', '')}",
                    })
        except Exception:
            log.warning("query_domain_deps_incoming_failed", domain=domain_name, exc_info=True)

        return {"domain": domain_name, "outgoing": outgoing[:15], "incoming": incoming[:15]}

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
