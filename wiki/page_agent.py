"""Agent framework for enriching wiki pages with CONTEXT_GAP remediation."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.log import get_logger

if TYPE_CHECKING:
    from wiki.domain_doc_agent import DomainTopicOutline
from wiki.agents.base_agent import GenericAgent
from wiki.agents.memory import AgentMemory
from wiki.agents.tool_decorator import function_tool
from wiki.content_guards import strip_meta_sections as _cg_strip_meta
from wiki.context_gap import CONTEXT_GAP_DETECT_RE as _CONTEXT_GAP_RE
from wiki.structured_output import WikiPageOutput, render_wiki_page

log = get_logger(__name__)

_THINKING_PREFIX_RE = re.compile(
    r"^(我需要|让我|从工作记忆|需要先|接下来我|首先我|I need to|Let me|根据您提供)",
)
_TOOL_JSON_BLOCK_RE = re.compile(
    r"```json\s*\{[\s\S]*?\"tools\"[\s\S]*?\}\s*```",
    re.MULTILINE,
)
_FIRST_HEADING_RE = re.compile(r"^(#{1,3}\s)", re.MULTILINE)
_MARKDOWN_FENCE_WRAP_RE = re.compile(
    r"^```(?:markdown|md)\s*\n([\s\S]*?)```\s*$",
)
_AGENT_SUGGESTION_RE = re.compile(
    r"(请依次执行以下工具调用|请补充代码扫描数据|建议下一步操作|suggest.*next.*step)",
    re.IGNORECASE,
)
# Lines containing LLM meta-text that should never appear in final wiki output
_LLM_META_LINE_RE = re.compile(
    r"(此处信息待补充|需进一步调用\s*read_code|具体实现细节暂未在上下文中提供"
    r"|_No graph relationships were summarized|更多内容请查看子页面"
    r"|当前上下文中?未提供|不生成流程图|信息待补充[:：]"
    r"|未获取到上述方法的具体实现|无法确认其是否涉及"
    r"|参考数据不足[，,]不生成图|需进一步调用\s*\w+\s*补充"
    r"|暂未在上下文中提供|未在上下文.*展开)",
)
_TOOL_INVOCATION_LINE_RE = re.compile(
    r"((?:我|接下来|然后)?(?:使用|调用|通过)\s*(?:read_code|query_module_detail|search_entities|"
    r"query_call_chain|query_callers|query_callees|query_domain_dependencies|"
    r"grep_code|list_files|read_file|semantic_search|read_wiki_page|"
    r"query_implementations|delegate_submodule)"
    r"(?:\s*\(.*?\))?\s*(?:查看|获取|搜索|读取|查询|来|以)?.*)",
    re.IGNORECASE,
)
_JSON_PREAMBLE_RE = re.compile(
    r"^##\s*当前\s*Wiki\s*页面[^\n]*\n\{[\s\S]*?\"executive_summary\"[\s\S]*?\}\s*\n",
    re.MULTILINE,
)
SINGLE_RESULT_LIMIT = 6000


def strip_agent_artifacts(text: str) -> str:
    """Remove LLM agent thinking/reasoning text and inline tool-call JSON from wiki content."""
    if not text or not text.strip():
        return ""
    stripped = _TOOL_JSON_BLOCK_RE.sub("", text)
    stripped = stripped.strip()
    # Strip LLM meta sections early
    stripped = _cg_strip_meta(stripped)

    # Strip outer ```markdown ... ``` fence wrapping the entire content
    m = _MARKDOWN_FENCE_WRAP_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    elif stripped.startswith("```markdown\n") or stripped.startswith("```md\n"):
        fence_end = stripped.find("\n")
        tail_fence = stripped.rfind("\n```")
        if tail_fence > fence_end:
            stripped = stripped[fence_end + 1:tail_fence].strip()

    # Strip JSON preamble like: ## 当前 Wiki 页面（域: ...）\n{"executive_summary": "..."}
    stripped = _JSON_PREAMBLE_RE.sub("", stripped)
    stripped = re.sub(
        r"^\{[^}]*\"executive_summary\"[^}]*\"content\":\s*\"",
        "", stripped,
    )

    if _THINKING_PREFIX_RE.match(stripped):
        m = _FIRST_HEADING_RE.search(stripped)
        if m:
            stripped = stripped[m.start():]
        else:
            stripped = ""

    # If output is mostly agent suggestions (not wiki content), discard
    if stripped and _AGENT_SUGGESTION_RE.search(stripped):
        heading_m = _FIRST_HEADING_RE.search(stripped)
        if heading_m:
            stripped = stripped[heading_m.start():]
        else:
            lines = stripped.split("\n")
            content_lines = [
                ln for ln in lines
                if not _AGENT_SUGGESTION_RE.search(ln)
                and not ln.strip().startswith("```plaintext")
            ]
            stripped = "\n".join(content_lines).strip()

    # Remove lines containing LLM meta-text artifacts
    if stripped and _LLM_META_LINE_RE.search(stripped):
        lines = stripped.split("\n")
        stripped = "\n".join(
            ln for ln in lines if not _LLM_META_LINE_RE.search(ln)
        ).strip()

    # Remove lines containing tool invocation descriptions
    if stripped and _TOOL_INVOCATION_LINE_RE.search(stripped):
        lines = stripped.split("\n")
        stripped = "\n".join(
            ln for ln in lines if not _TOOL_INVOCATION_LINE_RE.search(ln)
        ).strip()

    # Fix code fence issues: remove stray ```markdown fences
    stripped = re.sub(r"^```markdown\s*$", "", stripped, flags=re.MULTILINE)

    # Fix unclosed code fences: ensure even count
    fence_count = len(re.findall(r"```", stripped))
    if fence_count % 2 != 0:
        lines = stripped.split("\n")
        # Stack-based pairing: track opening fence line indices
        stack: list[int] = []
        unmatched_closes: list[int] = []
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("```") and s != "```":
                stack.append(i)
            elif s == "```":
                if stack:
                    stack.pop()
                else:
                    unmatched_closes.append(i)
        # Remove unmatched closing fences
        for idx in reversed(unmatched_closes):
            lines[idx] = ""
        # Add closing fences for remaining unclosed openers
        if stack:
            lines.append("```")
        stripped = "\n".join(lines).strip()
        # Final safety: if still odd, just append a closing fence
        if len(re.findall(r"```", stripped)) % 2 != 0:
            stripped += "\n```"

    # Strip fabricated metadata (handles bold markers, blockquotes, emoji variants)
    stripped = re.sub(
        r"^[>\s]*(?:📌|📝|🛠️?)\s*\**(?:维护人|维护团队|开发团队|负责团队|负责人|版本|联系人|"
        r"最后更新|Last Updated|更新时间|模块路径)\**[：:].*$",
        "",
        stripped,
        flags=re.MULTILINE,
    )
    # Strip fabricated "相关文档" sections with fake wiki links
    stripped = re.sub(
        r"^## 相关文档\s*\n(?:[-*]\s*\[.+?\]\(https?://wiki\.internal[^\)]*\)\s*\n?)*",
        "",
        stripped,
        flags=re.MULTILINE,
    )
    # Strip remaining 📌/📝/🛠️ lines (catch-all)
    stripped = re.sub(r"^[>\s]*[📌📝🛠️].+$", "", stripped, flags=re.MULTILINE)

    # Collapse multiple blank lines
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)

    return stripped.strip()

_GREP_MAX_FILE_SIZE = 512 * 1024  # 512 KB
MAX_GREP_FILES = 500
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


_MODULE_PREFIX_RE = re.compile(r"^\[([^\]]+)\]")


@dataclass
class WorkingMemory(AgentMemory):
    facts: list[str] = field(default_factory=list)
    discovered_call_chains: list[str] = field(default_factory=list)
    discovered_implementations: list[str] = field(default_factory=list)
    discovered_callers: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)
    resolved_gaps: list[str] = field(default_factory=list)
    wiki_references: list[str] = field(default_factory=list)
    search_findings: list[str] = field(default_factory=list)
    discovered_entity_uids: set[str] = field(default_factory=set)
    _tool_contributed_chars: int = 0
    relevant_modules: set[str] = field(default_factory=set)
    topic_outline: DomainTopicOutline | None = None

    MAX_TOTAL_CHARS = 200_000

    def incorporate(self, results: list[ToolResult]) -> None:
        valid_results = [
            r for r in results
            if not (isinstance(r.data, dict) and "error" in r.data)
        ]
        for r in valid_results:
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
                        self._extract_uid(m)
                else:
                    code = str(data.get("code", "") or "")
                    name = str(data.get("name", "") or "")
                    if code:
                        self.code_snippets.append(f"[{name}]\n{code[:SINGLE_RESULT_LIMIT]}")
                    self._extract_uid(data)
            elif tool == "read_file":
                content = str(data.get("content", "") or "")
                path = str(data.get("file_path", "") or "")
                if content:
                    self.code_snippets.append(f"[{path}]\n{content[:SINGLE_RESULT_LIMIT]}")
            elif tool == "search_entities":
                items = data.get("results", [])
                for item in items[:8]:
                    if isinstance(item, dict):
                        self.search_findings.append(
                            f"{item.get('type', '')} {item.get('name', '')} ({item.get('file', '')})"
                        )
                        self._extract_uid(item)
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
            elif tool == "query_module_detail":
                summary = str(data.get("summary", "") or "")
                name = str(data.get("name", "") or "")
                methods = data.get("methods", [])
                if summary:
                    entry = f"{name}: {summary}"
                    if methods:
                        method_names = [str(m.get("name", "")) for m in methods[:8]]
                        entry += f" [methods: {', '.join(method_names)}]"
                    self.discovered_call_chains.append(entry)
                self._extract_uid(data)
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
        self._tool_contributed_chars += sum(len(str(r.data)) for r in valid_results if r.data)
        self._dedup_snippets()
        self._enforce_limit()

    def _extract_uid(self, data: dict[str, Any], key: str = "uid") -> None:
        """Extract and store a non-empty uid from tool result data."""
        uid = str(data.get(key, "") or "").strip()
        if uid:
            self.discovered_entity_uids.add(uid)

    def _dedup_snippets(self) -> None:
        """Deduplicate code_snippets by entity name, keeping the longest version."""
        if len(self.code_snippets) <= 1:
            return
        seen: dict[str, int] = {}
        drop: set[int] = set()
        for i, snippet in enumerate(self.code_snippets):
            m = _MODULE_PREFIX_RE.match(snippet)
            if not m:
                continue
            name = m.group(1).strip()
            if not name:
                continue
            if name in seen:
                existing_idx = seen[name]
                if len(snippet) > len(self.code_snippets[existing_idx]):
                    drop.add(existing_idx)
                    seen[name] = i
                else:
                    drop.add(i)
            else:
                seen[name] = i
        if drop:
            self.code_snippets = [
                s for i, s in enumerate(self.code_snippets) if i not in drop
            ]

    def _enforce_limit(self) -> None:
        total = self._total_chars()
        if total <= self.MAX_TOTAL_CHARS:
            return

        def _relevance(entry: str) -> int:
            if not self.relevant_modules:
                return 1
            entry_lower = entry.lower()
            for mod in self.relevant_modules:
                mod_lower = mod.lower()
                if mod_lower in entry_lower:
                    return 2
                parts = mod_lower.replace(".", " ").replace("_", " ").split()
                if any(p in entry_lower for p in parts if len(p) > 3):
                    return 1
            return 0

        all_lists = [
            self.code_snippets,
            self.discovered_callers,
            self.discovered_implementations,
            self.discovered_call_chains,
            self.resolved_gaps,
            self.wiki_references,
            self.search_findings,
        ]

        while total > self.MAX_TOTAL_CHARS:
            removed = False
            for lst in all_lists:
                for i, entry in enumerate(lst):
                    if _relevance(entry) == 0:
                        total -= len(entry)
                        del lst[i]
                        removed = True
                        break
                if removed:
                    break
            if not removed:
                break

        while total > self.MAX_TOTAL_CHARS:
            removed = False
            for lst in all_lists:
                if lst:
                    total -= max(len(lst[0]), 1)
                    del lst[0]
                    removed = True
                    break
            if not removed:
                break

    def merge(self, other: AgentMemory) -> None:
        """Merge supplemental exploration results, deduplicate, enforce limits."""
        if not isinstance(other, WorkingMemory):
            return

        incoming_prefixes: set[str] = set()
        for snippet in other.code_snippets:
            m = _MODULE_PREFIX_RE.match(snippet)
            if m:
                incoming_prefixes.add(m.group(1))

        if incoming_prefixes:
            self.code_snippets = [
                s for s in self.code_snippets
                if not ((_m := _MODULE_PREFIX_RE.match(s)) and _m.group(1) in incoming_prefixes)
            ]
        self.code_snippets.extend(other.code_snippets)

        existing_chains = set(self.discovered_call_chains)
        self.discovered_call_chains.extend(
            c for c in other.discovered_call_chains if c not in existing_chains
        )

        self.discovered_implementations.extend(other.discovered_implementations)
        self.discovered_callers.extend(other.discovered_callers)
        self.resolved_gaps.extend(other.resolved_gaps)
        self.wiki_references.extend(other.wiki_references)
        self.search_findings.extend(other.search_findings)

        for field_name in [
            "facts",
            "structural_patterns",
            "topic_findings",
        ]:
            existing = getattr(self, field_name, [])
            incoming = getattr(other, field_name, [])
            for item in incoming:
                if item not in existing:
                    existing.append(item)

        self.discovered_entity_uids |= other.discovered_entity_uids

        self._tool_contributed_chars += other._tool_contributed_chars

        self._enforce_limit()

    def slice(self, keys: set[str]) -> AgentMemory:
        """Return a new WorkingMemory with only the specified fields populated."""
        new = WorkingMemory()
        for key in keys:
            if hasattr(self, key) and hasattr(new, key):
                setattr(new, key, copy.deepcopy(getattr(self, key)))
        return new

    def inject_findings(self, findings: list[str]) -> None:
        """Inject findings from L3 compression into facts, deduplicating."""
        for finding in findings:
            if finding not in self.facts:
                self.facts.append(finding)

    def slice_for_modules(self, modules: set[str]) -> WorkingMemory:
        """Create a filtered copy containing only entries relevant to given modules."""
        module_lower = {m.lower() for m in modules}

        def _matches(entry: str) -> bool:
            m = _MODULE_PREFIX_RE.match(entry)
            if m:
                prefix = m.group(1).strip()
                name = prefix.split(" @ ")[0].strip() if " @ " in prefix else prefix
                return name.lower() in module_lower
            entry_lower = entry.lower()
            return any(mod in entry_lower for mod in module_lower)

        sliced = WorkingMemory()
        sliced.code_snippets = [s for s in self.code_snippets if _matches(s)]
        sliced.discovered_call_chains = [
            c for c in self.discovered_call_chains
            if any(m.lower() in c.lower() for m in modules)
        ]
        sliced.discovered_implementations = [
            i for i in self.discovered_implementations
            if any(m.lower() in i.lower() for m in modules)
        ]
        sliced.discovered_callers = [
            c for c in self.discovered_callers
            if any(m.lower() in c.lower() for m in modules)
        ]
        sliced.search_findings = list(self.search_findings)
        sliced.wiki_references = list(self.wiki_references)
        sliced.relevant_modules = modules
        return sliced

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

    def to_prompt(self, max_chars: int | None = None) -> str:
        text = self.to_prompt_section()
        if max_chars is not None and len(text) > max_chars:
            return text[:max_chars]
        return text

    def to_prompt_section(self) -> str:
        sections: list[str] = []
        if self.facts:
            sections.append("### 关键发现")
            sections.extend(f"- {f}" for f in self.facts)
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


_AGENT_SYSTEM = """你是一个代码知识库 Agent。你的任务是通过调用 tools 来补充 Wiki 页面中标记为 CONTEXT_GAP 的缺失信息。

## 执行步骤
1. 分析页面中每个 CONTEXT_GAP 标记，确定需要查询的具体信息
2. 按以下优先级使用工具：
   - `read_code` / `query_module_detail` — 获取缺失的实现细节
   - `query_call_chain` / `query_callers` — 获取缺失的调用关系
   - `search_entities` / `semantic_search` — 发现相关但未被索引的实体
3. 当获得足够信息后，输出补充后的完整页面（去掉已解决的 CONTEXT_GAP 标记）
4. 无法通过工具解决的 gap 保留原始标记

## 质量约束
- 补充内容必须 100% 来源于工具查询结果，**绝对禁止编造**
- 不要自行生成 `source://` 链接，系统会自动注入
- 补充的段落应与原有内容风格一致，使用中文撰写
- 嵌入代码片段时使用带语言标记的代码块（如 ```java），不超过 15 行

## 输出要求
直接输出完整的 Wiki 页面 Markdown 内容（不要 JSON 包装）。
"""


class WikiPageAgent(GenericAgent):
    _MAX_HISTORY_MESSAGES = 30
    _MAX_DELEGATION_DEPTH = 2
    _MAX_DELEGATIONS_PER_AGENT = 3

    def __init__(
        self,
        llm: Any,
        graph_store: Any,
        *,
        repo_path: str | None = None,
        search_service: Any | None = None,
        max_rounds: int = 6,
        max_tool_calls: int = 30,
        content_language: str = "简体中文",
    ) -> None:
        super().__init__(llm, max_rounds=max_rounds, max_tool_calls=max_tool_calls)
        self._graph = graph_store
        self._repo_path = repo_path
        self._search_service = search_service
        self._existing_pages: list[dict] | None = None
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls
        self.content_language = content_language

        from wiki.agents.context import WikiDeps

        self._deps = WikiDeps(
            graph_store=graph_store,
            search_service=search_service,
            repo_path=repo_path,
        )

        self._register_tools()

    def _register_tools(self) -> None:
        """Register all @function_tool decorated methods into ToolRegistry."""
        from wiki.agents.tool_decorator import collect_tools

        for td in collect_tools(self):
            self._tool_registry.register(td)

    def create_memory(self) -> WorkingMemory:
        return WorkingMemory()

    def incorporate(self, tool_name: str, result: dict[str, Any], memory: Any) -> None:
        if isinstance(memory, WorkingMemory):
            memory.incorporate([ToolResult(tool=tool_name, data=result)])

    def memory_to_prompt(self, memory: Any) -> str:
        if isinstance(memory, WorkingMemory):
            return memory.to_prompt_section()
        return str(memory)

    def _get_tools_for_round(self, round_num: int, has_empty_results: bool) -> list[dict]:
        return self._tool_registry.get_tools_for_round(round_num, has_empty_results)

    async def enrich(
        self,
        content: str,
        *,
        focus_modules: list[str] | None = None,
        quality_report: Any | None = None,
        domain_name: str | None = None,
        existing_pages: list[dict] | None = None,
    ) -> str:
        domain_label = "" if domain_name is None else domain_name
        gaps = _CONTEXT_GAP_RE.findall(content)
        has_quality_feedback = quality_report is not None or focus_modules is not None
        if not gaps and not has_quality_feedback:
            return content

        self._existing_pages = existing_pages
        memory = WorkingMemory()

        user_prompt = self._build_user_prompt(
            content, gaps, memory, domain_label,
            focus_modules=focus_modules,
            quality_report=quality_report,
        )

        nudge_msg = (
            "你还没有使用工具查询信息。请先使用 read_code 获取关键方法实现，再输出完整页面。"
        )

        async def _nudge_hook(round_num: int, text: str | None, total_calls: int) -> str | None:
            if text:
                cleaned = strip_agent_artifacts(str(text))
                if cleaned and (total_calls >= 1 or round_num >= 2):
                    return None
                if cleaned and total_calls == 0 and round_num < 2:
                    return nudge_msg
                if not cleaned:
                    log.warning("agent_output_was_pure_thinking", domain=domain_label)
            return None

        async def _fallback_hook(mem: Any) -> str | None:
            try:
                fallback = await self._llm.generate(
                    prompt=self._build_user_prompt(
                        content, gaps, mem if isinstance(mem, WorkingMemory) else memory,
                        domain_label,
                        focus_modules=focus_modules,
                        quality_report=quality_report,
                    ),
                    system=_AGENT_SYSTEM,
                )
                cleaned = strip_agent_artifacts(fallback)
                if cleaned:
                    return cleaned
                log.warning("agent_fallback_was_pure_thinking", domain=domain_label)
            except Exception:
                log.warning("agent_fallback_failed", exc_info=True)
            return None

        from wiki.agents.runner import LoopConfig, LoopHooks, run_agent_loop

        loop_result = await run_agent_loop(
            self,
            system_prompt=_AGENT_SYSTEM,
            user_prompt=user_prompt,
            memory=memory,
            config=LoopConfig(
                max_rounds=self.max_rounds,
                max_tool_calls=self.max_tool_calls,
                max_history_messages=self._MAX_HISTORY_MESSAGES,
                detect_repeated_calls=True,
                hooks=LoopHooks(
                    on_no_tool_calls=_nudge_hook,
                    on_loop_complete=_fallback_hook,
                ),
            ),
        )

        if loop_result.final_output:
            cleaned = strip_agent_artifacts(loop_result.final_output)
            if cleaned:
                return cleaned
        return content

    async def explore(
        self,
        module_names: list[str],
        domain_name: str,
        baseline_context: str,
        *,
        focus_modules: list[str] | None = None,
        memory: WorkingMemory | None = None,
        max_rounds: int | None = None,
    ) -> WorkingMemory:
        """Phase 1: Explore code via tools, accumulate structured findings.

        Delegates to the unified run_tool_loop with explore-specific config.
        LLM's text output is discarded — only tool results matter.
        """
        from wiki.agent_prompts import AGENT_EXPLORE_SYSTEM
        from wiki.agents.base_agent import RunConfig
        from wiki.agents.context import RunContext
        from wiki.agents.guardrails import PromptLengthGuardrail

        rounds = max_rounds if max_rounds is not None else self.max_rounds
        system = AGENT_EXPLORE_SYSTEM.format(max_rounds=rounds)
        user_prompt = await self._build_explore_user_prompt(
            module_names, domain_name, baseline_context, focus_modules,
        )

        if memory is None:
            memory = WorkingMemory()
        if not memory.relevant_modules and module_names:
            memory.relevant_modules = set(module_names)

        config = RunConfig(
            max_rounds=rounds,
            max_tool_calls=self.max_tool_calls,
            nudge_message="你还没有使用任何工具。请立即调用工具收集代码信息。",
            enable_early_stop=True,
            early_stop_max_empty=2,
            enable_context_trim=True,
            context_trim_max_chars=60000,
            context_trim_keep_recent=3,
            enable_compaction=True,
            compaction_model=None,
            compaction_interval=8,
            enable_post_call_guardrail=True,
            result_truncate_chars=0,
            input_guardrails=[PromptLengthGuardrail(max_chars=150_000)],
        )

        ctx = RunContext(deps=self._deps)
        memory = await self.run_tool_loop(
            system, user_prompt, memory, config=config, ctx=ctx
        )

        log.info(
            "explore_complete",
            domain=domain_name,
            memory_chars=memory._total_chars(),
        )
        return memory

    async def _build_explore_user_prompt(
        self,
        module_names: list[str],
        domain_name: str,
        baseline_context: str,
        focus_modules: list[str] | None = None,
    ) -> str:
        """Build user prompt for explore() phase."""
        entry_keywords = ("Controller", "Handler", "Consumer", "Listener", "Endpoint", "Resource")
        core_modules: list[str] = []
        other_modules: list[str] = []
        for m in module_names:
            if any(kw in m for kw in entry_keywords):
                core_modules.append(m)
            else:
                other_modules.append(m)

        parts = [
            "## 任务",
            f"为业务域「{domain_name}」收集完整的代码上下文信息。",
            "",
            f"## 域内模块清单（共 {len(module_names)} 个，必须全部探索）",
        ]
        if core_modules:
            parts.append("\n### 入口模块（优先查询调用链）")
            for i, m in enumerate(core_modules, 1):
                parts.append(f"{i}. `{m}`")
        if other_modules:
            parts.append("\n### 其他模块")
            for i, m in enumerate(other_modules, 1):
                parts.append(f"{i}. `{m}`")

        if baseline_context:
            parts.append(f"\n## 基线上下文\n{baseline_context[:8000]}")

        if focus_modules:
            parts.append(
                f"\n## 重点探索模块\n"
                f"你还需要重点探索以下模块：{', '.join(focus_modules)}"
            )

        if self._graph:
            languages = await self._detect_module_languages(module_names)
            if languages:
                concept_lines = [
                    f"- **{lang}**: {', '.join(concepts)}"
                    for lang, concepts in languages.items()
                    if concepts
                ]
                if concept_lines:
                    parts.append("\n## 语言特定概念（探索时关注）\n" + "\n".join(concept_lines))

        return "\n".join(parts)

    @staticmethod
    def _extension_for_path(file_path: str) -> str:
        normalized = file_path.replace("\\", "/").lower()
        for ext in (".d.ts", ".tsx", ".jsx", ".mjs", ".cjs", ".kts", ".g.dart"):
            if normalized.endswith(ext):
                return ext
        dot = normalized.rfind(".")
        return normalized[dot:] if dot != -1 else ""

    async def _detect_module_languages(self, module_names: list[str]) -> dict[str, list[str]]:
        """Detect languages from module file paths and return plugin concepts."""
        from indexer.languages import create_default_registry

        if not self._graph or not hasattr(self._graph, "execute_query"):
            return {}

        from wiki.cypher_queries import MODULE_PATHS_BATCH_CY

        sampled = module_names[:20]
        try:
            result = await self._graph.execute_query(MODULE_PATHS_BATCH_CY, {"names": sampled})
        except Exception:
            log.debug("module_paths_batch_query_failed", exc_info=True)
            return {}

        rows = getattr(result, "data", None) or []
        registry = create_default_registry()
        lang_concepts: dict[str, list[str]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            file_path = str(row.get("path", "") or "").strip()
            if not file_path:
                continue
            ext = self._extension_for_path(file_path)
            if not ext:
                continue
            plugin = registry.get_by_extension(ext)
            if plugin and plugin.name not in lang_concepts:
                lang_concepts[plugin.name] = plugin.concepts
        return lang_concepts

    async def write(
        self,
        domain_name: str,
        baseline_context: str,
        memory: WorkingMemory,
        *,
        module_names: list[str] | None = None,
        page_type: str = "domain_overview",
    ) -> str:
        """Phase 2: Generate wiki page from exploration results.

        Pure LLM.generate() — no tools, clean context.
        """
        from wiki.agent_prompts import get_write_system_prompt, get_write_topic_system_prompt

        if page_type == "topic":
            write_system_prompt = get_write_topic_system_prompt(self.content_language)
        else:
            write_system_prompt = get_write_system_prompt(self.content_language)
        memo_section = memory.to_prompt_section()
        is_chinese = "中文" in self.content_language or self.content_language in ("zh-CN", "zh")
        baseline_limit = 8000 if page_type == "topic" else 16000
        truncated_baseline = baseline_context[:baseline_limit]
        if is_chinese and page_type == "topic":
            user_prompt = (
                f"## 任务\n"
                f"基于以下探索结果，为业务域「{domain_name}」生成一篇聚焦主题的深度技术文档。\n\n"
                f"## 基线上下文\n{truncated_baseline}\n\n"
                f"## 探索结果（工作记忆）\n{memo_section}\n"
            )
        elif is_chinese:
            user_prompt = (
                f"## 任务\n"
                f"基于以下探索结果，为业务域「{domain_name}」生成一篇完整的 Wiki 页面。\n\n"
                f"## 基线上下文\n{truncated_baseline}\n\n"
                f"## 探索结果（工作记忆）\n{memo_section}\n"
            )
        else:
            user_prompt = (
                f"## Task\n"
                f"Based on the exploration results below, generate a complete Wiki page "
                f"for the \"{domain_name}\" business domain.\n\n"
                f"## Baseline Context\n{truncated_baseline}\n\n"
                f"## Exploration Findings (Working Memory)\n{memo_section}\n"
            )

        # Try structured output via complete_json (all languages)
        try:
            messages = [
                {"role": "system", "content": write_system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            data = await self._llm.complete_json(
                messages, WikiPageOutput.model_json_schema()
            )
            page_data = WikiPageOutput.model_validate(data)
            rendered = render_wiki_page(page_data)
            if rendered and len(rendered) > 200:
                return rendered
        except Exception:
            log.info("structured_output_fallback", domain=domain_name)

        # Fallback to plain text generation
        try:
            response = await self._llm.generate(
                prompt=user_prompt,
                system=write_system_prompt,
            )
            cleaned = strip_agent_artifacts(response) if response else ""
            if cleaned and len(cleaned) > 200:
                return cleaned
        except Exception:
            log.warning("write_llm_failed", domain=domain_name, exc_info=True)

        snippet_names = [
            m.split("]")[0].lstrip("[") for m in memory.code_snippets[:20]
        ]
        skel_modules = list(module_names) if module_names is not None else snippet_names
        return self._generate_skeleton(skel_modules, domain_name)

    async def generate(
        self,
        module_names: list[str],
        domain_name: str,
        baseline_context: dict[str, Any] | str | None = None,
        max_rounds: int = 10,
    ) -> str:
        """Agent-Driven: query context with tools and generate a full Wiki page.

        Backward-compatible wrapper: internally delegates to explore() + write().
        """
        if isinstance(baseline_context, dict):
            ctx_parts = []
            for key, val in baseline_context.items():
                val_str = str(val) if val else ""
                if val_str:
                    ctx_parts.append(f"- **{key}**: {val_str[:600]}")
            baseline_str = "\n".join(ctx_parts)[:8000]
        elif baseline_context:
            baseline_str = str(baseline_context)[:8000]
        else:
            baseline_str = ""

        try:
            memory = await self.explore(
                module_names=module_names,
                domain_name=domain_name,
                baseline_context=baseline_str,
                max_rounds=max_rounds,
            )
            content = await self.write(
                domain_name=domain_name,
                baseline_context=baseline_str,
                memory=memory,
                module_names=module_names,
            )
            return content
        except Exception:
            log.warning("agent_generate_failed", domain=domain_name, exc_info=True)
            return self._generate_skeleton(module_names, domain_name)

    async def repair(self, content: str, eval_result) -> str:
        """Repair content based on Evaluator feedback. No tool calls — pure LLM rewrite."""
        issues_text = "\n".join(
            f"- [{getattr(i, 'category', '?')}] {getattr(i, 'message', str(i))}"
            for i in (eval_result.issues or [])
        )
        suggestions_text = "\n".join(
            f"- {s}" for s in (eval_result.suggestions or [])
        )

        repair_prompt = (
            "以下 Wiki 页面有质量问题需要修正:\n\n"
            f"## 当前问题\n{issues_text}\n\n"
            f"## 修正建议\n{suggestions_text}\n\n"
            f"## 当前内容\n{content[:4000]}\n\n"
            "请修正上述问题, 输出完整的修正后页面。保持原有正确内容不变, 只修复指出的问题。"
        )

        try:
            response = await self._llm.generate(repair_prompt, system="")
            repaired = strip_agent_artifacts(response) if response else ""
            return repaired if len(repaired) > 200 else content
        except Exception:
            log.warning("repair_failed", exc_info=True)
            return content

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

    @staticmethod
    def _build_generate_user_prompt(
        module_names: list[str],
        domain_name: str,
        baseline_context: dict[str, Any] | str | None,
        max_rounds: int,
    ) -> str:
        """Build a structured user prompt for generate() mode."""
        # Separate entry modules from regular modules by naming convention
        entry_keywords = ("Controller", "Handler", "Consumer", "Listener", "Endpoint", "Resource")
        core_modules: list[str] = []
        other_modules: list[str] = []
        for m in module_names:
            if any(kw in m for kw in entry_keywords):
                core_modules.append(m)
            else:
                other_modules.append(m)

        parts = [
            "## 任务",
            f"为业务域「{domain_name}」生成一篇完整的 Wiki 页面。",
            "",
            f"## 域内模块清单（共 {len(module_names)} 个，必须全部覆盖）",
        ]
        if core_modules:
            parts.append("\n### 入口模块（优先查询调用链）")
            for i, m in enumerate(core_modules, 1):
                parts.append(f"{i}. `{m}`")
        if other_modules:
            parts.append("\n### 其他模块")
            for i, m in enumerate(other_modules, 1):
                parts.append(f"{i}. `{m}`")

        # Build baseline context
        if baseline_context:
            if isinstance(baseline_context, str):
                baseline_str = baseline_context[:8000]
            elif isinstance(baseline_context, dict):
                # Structured baseline: format key fields
                ctx_parts = []
                for key, val in baseline_context.items():
                    val_str = str(val) if val else ""
                    if val_str:
                        ctx_parts.append(f"- **{key}**: {val_str[:600]}")
                baseline_str = "\n".join(ctx_parts)[:8000]
            else:
                baseline_str = str(baseline_context)[:8000]
            parts.append(f"\n## 基线上下文\n{baseline_str}")

        explore_budget = max(1, int(max_rounds * 0.6))
        write_budget = max_rounds - explore_budget
        parts.extend([
            "",
            "## 执行要求",
            f"- 前 {explore_budget} 轮：使用工具收集信息（每个入口模块查调用链，每个核心模块查源码）",
            f"- 后 {write_budget} 轮：基于已收集信息生成完整 Markdown 页面",
            "- 必须嵌入 2-4 个关键代码片段（从 read_code 结果中选取）",
            "- 必须包含至少 1 个 Mermaid 图表（调用链序列图或架构流程图）",
        ])
        return "\n".join(parts)

    def _build_user_prompt(
        self,
        content: str,
        gaps: list[str],
        memory: WorkingMemory,
        domain_name: str,
        *,
        focus_modules: list[str] | None = None,
        quality_report: Any | None = None,
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
        parts.append("请使用 tools 查询缺失信息（如 read_code 获取关键方法实现），然后输出补充后的完整页面。")

        extra_context = ""
        if quality_report:
            extra_context += (
                "\n\n## Quality Report (current)\n"
                f"- Coverage: {quality_report.coverage:.1%}\n"
                f"- Citation density: {quality_report.citation_density:.2f}\n"
                f"- Context gaps: {quality_report.context_gap_count}\n"
            )
            if hasattr(quality_report, "uncovered_modules") and quality_report.uncovered_modules:
                extra_context += (
                    f"- Uncovered modules: {', '.join(quality_report.uncovered_modules)}\n"
                    "\nPrioritize covering uncovered modules and filling context gaps.\n"
                )

        if focus_modules:
            extra_context += f"\n\nFocus on these modules: {', '.join(focus_modules)}\n"

        if domain_name:
            extra_context += f"\n\nDomain: {domain_name}\n"

        return "\n".join(parts) + extra_context

    async def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        log.info("agent_tool_call", tool=tool_name, args_keys=list(args.keys()))
        data, _ = await self._tool_registry.dispatch(tool_name, args)
        return data

    @function_tool(
        name="delegate_submodule",
        tier=3,
        description=(
            "Use when the current module is too complex to document in one pass: "
            "delegate a sub-section to a specialized sub-agent. Returns the "
            "generated documentation for that sub-section."
        ),
    )
    async def delegate_submodule(
        self, entity_names: list[str], focus: str = ""
    ) -> dict[str, Any]:
        from wiki.agents.delegation import DelegationConfig, DelegationMode, execute_delegation

        entity_names = entity_names or []
        focus = focus or ""

        self._deps.delegation_count = getattr(self, "_delegation_count", 0)
        self._deps.delegation_depth = getattr(self, "_delegation_depth", 0)

        def _factory(child_deps):
            agent = WikiPageAgent(
                llm=self._llm,
                graph_store=child_deps.graph_store,
                repo_path=child_deps.repo_path,
                search_service=child_deps.search_service,
                max_rounds=self.max_rounds,
                max_tool_calls=self.max_tool_calls,
            )
            agent._existing_pages = self._existing_pages
            return agent

        domain = focus or ", ".join(entity_names[:3])

        config = DelegationConfig(
            mode=DelegationMode.SEEDED,
            max_depth=self._MAX_DELEGATION_DEPTH,
            max_count=self._MAX_DELEGATIONS_PER_AGENT,
            max_rounds=3,
            seed_memory_fields=["facts", "relevant_modules", "discovered_call_chains"],
        )

        result = await execute_delegation(
            config,
            factory=_factory,
            deps=self._deps,
            task_input={
                "module_names": entity_names,
                "domain_name": domain,
                "max_rounds": 3,
            },
            parent_memory=getattr(self, "_current_memory", None),
        )

        self._delegation_count = self._deps.delegation_count + 1

        if result.child_memory and hasattr(self, "_current_memory") and self._current_memory:
            self._current_memory.merge(result.child_memory)

        if "error" in result.metadata:
            return {"error": result.metadata["error"]}
        return {
            "delegated": True,
            "entity_names": entity_names,
            "focus": focus,
            "content": result.output,
        }

    @function_tool(
        name="read_code",
        tier=1,
        description=(
            f"Read source code for a function or class by name (up to {SINGLE_RESULT_LIMIT} chars). "
            "Use when you need to understand implementation details of a specific indexed entity."
        ),
    )
    async def read_code(
        self, entity_name: str, max_chars: int = SINGLE_RESULT_LIMIT
    ) -> dict[str, Any]:
        entity_name = str(entity_name or "")
        try:
            max_chars = max(0, min(int(max_chars or SINGLE_RESULT_LIMIT), 10000))
        except (TypeError, ValueError):
            max_chars = SINGLE_RESULT_LIMIT
        if not entity_name or not self._graph or not hasattr(self._graph, "execute_query"):
            return {"name": entity_name, "code": "", "file": "", "type": ""}
        repo_filter = self._repository_filter()
        if repo_filter:
            from wiki.cypher_queries import ENTITY_LOCATION_BY_REPO_CY

            result = await self._graph.execute_query(
                ENTITY_LOCATION_BY_REPO_CY, {"name": entity_name, "repo": repo_filter}
            )
        else:
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
                    "uid": str(row.get("uid", "") or ""),
                    "repository": str(row.get("repository", "") or ""),
                })
        if not matches:
            return {"name": entity_name, "code": "", "file": "", "type": ""}
        if len(matches) == 1:
            return matches[0]
        return {"name": entity_name, "matches": matches, "ambiguous": True}

    _MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

    @function_tool(
        name="read_file",
        tier=2,
        description=(
            "Read file content by relative path. Use for config files, non-indexed source, "
            "or any file not in the code graph (e.g. .yaml, .xml, .properties)."
        ),
    )
    async def read_file(
        self, file_path: str, start_line: int = 1, end_line: int = 0
    ) -> dict[str, Any]:
        from pathlib import Path

        file_path = str(file_path or "")
        start_line = max(1, int(start_line or 1))
        end_line = int(end_line or 0)
        if not end_line:
            end_line = start_line + 200
        if end_line < start_line:
            end_line = start_line + 200
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

    @function_tool(
        name="search_entities",
        tier=2,
        description=(
            "Search code entities by keyword in names and docstrings. "
            "Use when you don't know the exact name and need to discover related functions or classes."
        ),
    )
    async def search_entities(self, keyword: str, limit: int = 10) -> dict[str, Any]:
        keyword = str(keyword or "")
        limit = min(int(limit or 10), 20)
        if not keyword or not self._graph or not hasattr(self._graph, "execute_query"):
            return {"results": [], "total": 0}
        import asyncio

        from wiki.cypher_queries import SEARCH_ENTITY_LABELS, search_entity_cypher

        async def _search_label(label: str) -> list[dict[str, str]]:
            try:
                cy = search_entity_cypher(label)
                result = await self._graph.execute_query(
                    cy, {"keyword": keyword, "limit": limit}
                )
                rows = getattr(result, "data", None) or []
                label_results: list[dict[str, str]] = []
                for row in rows:
                    if isinstance(row, dict):
                        label_results.append({
                            "name": str(row.get("name", "") or ""),
                            "type": str(row.get("type", "") or ""),
                            "file": str(row.get("file", "") or ""),
                            "signature": str(row.get("signature", "") or ""),
                            "docstring": str(row.get("docstring", "") or ""),
                            "uid": str(row.get("uid", "") or ""),
                        })
                return label_results
            except Exception:
                log.warning("search_label_failed", label=label, keyword=keyword, exc_info=True)
                return []

        per_label_results = await asyncio.gather(
            *[_search_label(label) for label in SEARCH_ENTITY_LABELS]
        )
        results: list[dict[str, str]] = []
        for label_results in per_label_results:
            if len(results) >= limit:
                break
            for item in label_results:
                results.append(item)
                if len(results) >= limit:
                    break
        truncated = len(results) >= limit
        return {"results": results[:limit], "total": len(results), "truncated": truncated}

    @function_tool(
        name="read_wiki_page",
        tier=3,
        description=(
            "Read an existing wiki page by path or title keyword. "
            "Use to check what's already documented and avoid content duplication."
        ),
    )
    async def read_wiki_page(self, query: str) -> dict[str, Any]:
        query = str(query or "")
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

    def _repository_filter(self) -> str | None:
        """Derive graph/search repository id from the agent's repo path."""
        if not self._repo_path:
            return None
        from wiki.cross_repo_domain_planner import clean_repo_path

        repo = clean_repo_path(self._repo_path.strip())
        return repo or None

    @function_tool(
        name="semantic_search",
        tier=3,
        description=(
            "Semantic search across code and wiki using natural language. "
            "Use when keyword search fails and you need conceptual or fuzzy matching."
        ),
    )
    async def semantic_search(self, query: str, limit: int = 5) -> dict[str, Any]:
        query = str(query or "")
        limit = min(int(limit or 5), 10)
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
                repository=self._repository_filter(),
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

    @function_tool(
        name="list_files",
        tier=3,
        description=(
            "List files in a directory. Use when you need to explore project structure or "
            "find related config/resource files near a module."
        ),
    )
    async def list_files(self, directory: str, max_depth: int = 2) -> dict[str, Any]:
        from pathlib import Path

        directory = str(directory or "")
        max_depth = min(max(1, int(max_depth or 2)), 3)
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
        max_entries = 50

        def _walk(path: Path, depth: int) -> None:
            if depth > max_depth or len(files) >= max_entries:
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
                if len(files) >= max_entries:
                    return

        _walk(target, 1)
        return {
            "directory": directory,
            "files": files[:max_entries],
            "total": len(files),
            "truncated": len(files) >= max_entries,
        }

    @function_tool(
        name="grep_code",
        tier=3,
        description=(
            "Search for text patterns in source files. Use when you need to find specific "
            "string literals, error messages, constants, or usage patterns across the codebase."
        ),
    )
    async def grep_code(
        self, pattern: str, file_pattern: str = "", max_results: int = 10
    ) -> dict[str, Any]:
        from pathlib import Path

        pattern_str = str(pattern or "")
        file_pattern = str(file_pattern or "")
        try:
            max_results = min(max(1, int(max_results or 10)), 20)
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

        if ".." in glob_pattern or glob_pattern.startswith("/"):
            return {"error": "Invalid file_pattern: must not contain '..' or start with '/'"}

        files_scanned = 0
        for file_path in repo_root.rglob(glob_pattern):
            if len(matches) >= max_results:
                break
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in _GREP_BINARY_EXTENSIONS:
                continue
            files_scanned += 1
            if files_scanned > MAX_GREP_FILES:
                break
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

    @function_tool(
        name="query_module_detail",
        tier=1,
        description=(
            "Query detailed info about a module including methods and annotations. "
            "Use when you need to understand a module's internal structure."
        ),
    )
    async def query_module_detail(self, name: str) -> dict[str, Any]:
        name = str(name or "")
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

    @function_tool(
        name="query_callers",
        tier=1,
        description=(
            "Query which modules call the given module. "
            "Use when you need to understand who depends on a module."
        ),
    )
    async def query_callers(self, name: str) -> dict[str, Any]:
        name = str(name or "")
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

    @function_tool(
        name="query_callees",
        tier=1,
        description=(
            "Query which modules the given module calls. "
            "Use when you need to understand a module's outgoing dependencies."
        ),
    )
    async def query_callees(self, name: str) -> dict[str, Any]:
        name = str(name or "")
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

    @function_tool(
        name="query_implementations",
        tier=2,
        description=(
            "Query implementations of an interface. "
            "Use when you need to find concrete classes for an abstract interface."
        ),
    )
    async def query_implementations(self, interface: str) -> dict[str, Any]:
        interface = str(interface or "")
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

    @function_tool(
        name="query_call_chain",
        tier=1,
        description=(
            "Query method-level call chain starting from a module. "
            "Use when you need to trace execution flow across multiple modules."
        ),
    )
    async def query_call_chain(self, module_name: str) -> dict[str, Any]:
        module_name = str(module_name or "")
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

    @function_tool(
        name="query_domain_dependencies",
        tier=2,
        description=(
            "Query cross-domain call dependencies for a domain. Use when writing domain overviews "
            "to understand how this domain interacts with other domains."
        ),
    )
    async def query_domain_dependencies(self, domain_name: str) -> dict[str, Any]:
        domain_name = str(domain_name or "")
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
