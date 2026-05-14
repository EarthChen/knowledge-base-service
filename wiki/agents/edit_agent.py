"""Wiki-focused edit agent streaming events while editing page markdown."""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any

from wiki.agents.base_agent import GenericAgent, ToolDef
from wiki.agents.events import AgentEvent, ContentEvent, DoneEvent, ErrorEvent
from wiki.agents.section_utils import (
    Section,
    build_context_sections,
    locate_edit_sections,
    reassemble_page,
    split_page_into_sections,
)
from wiki.cypher_queries import METHODS_CY

from core.log import get_logger

log = get_logger(__name__)

SEARCH_ENTITIES_CY = """
MATCH (e)
WHERE e.name CONTAINS $query OR e.uid CONTAINS $query
RETURN e.uid AS uid, e.name AS name,
       labels(e)[0] AS label, coalesce(e.description, '') AS description
LIMIT $limit
""".strip()

MODULE_OUTGOING_DEPS_CY = """
MATCH (m:Module)-[:CALLS]->(dep:Module)
WHERE m.name = $module_name
RETURN dep.name AS name
LIMIT 20
""".strip()

MODULE_INCOMING_DEPS_CY = """
MATCH (caller:Module)-[:CALLS]->(m:Module)
WHERE m.name = $module_name
RETURN caller.name AS name
LIMIT 20
""".strip()

SEARCH_WIKI_PAGES_CY = """
MATCH (w:WikiPage)
WHERE toLower(coalesce(w.title, '')) CONTAINS toLower($query)
   OR toLower(coalesce(w.content, '')) CONTAINS toLower($query)
   OR coalesce(w.path, '') CONTAINS $query
RETURN w.title AS title, w.path AS path,
       left(coalesce(w.content, ''), 300) AS snippet
LIMIT $limit
""".strip()

READ_SOURCE_FILE_CY = """
MATCH (m:Module {file_path: $path})
RETURN m.file_path AS path, left(coalesce(m.source, m.code, ''), 6000) AS content
LIMIT 1
""".strip()

GET_CALL_CHAIN_CY = """
MATCH (f:Function {name: $func_name})-[:CALLS*1..3]->(callee:Function)
RETURN DISTINCT callee.name AS name, callee.file_path AS file_path
LIMIT 20
""".strip()

EDIT_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_entities",
            "description": (
                "Search graph entities whose name or uid contains a keyword. "
                "Use when you need to locate modules, classes, or other indexed nodes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword to match"},
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_module_detail",
            "description": (
                "Get methods and CALLS-module dependencies for a module by name. "
                "Use before editing wiki text about code structure."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "module_name": {
                        "type": "string",
                        "description": "Module name",
                    },
                },
                "required": ["module_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_wiki_pages",
            "description": (
                "Find other wiki pages matching title, path, or body text. "
                "Use for consistency and avoiding duplicate documentation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text"},
                    "limit": {"type": "integer", "description": "Max results (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_source_file",
            "description": "Read source code content for a file by its path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_call_chain",
            "description": (
                "Trace outgoing call chain from a function (up to 3 hops)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "func_name": {
                        "type": "string",
                        "description": "Function name to trace from",
                    },
                },
                "required": ["func_name"],
            },
        },
    },
]

_EDIT_AGENT_TOOL_TIERS: dict[str, int] = {
    "search_entities": 1,
    "query_module_detail": 1,
    "read_source_file": 1,
    "search_wiki_pages": 2,
    "get_call_chain": 2,
}

# Use section-tiered prompts only for large bodies to preserve prior small-page UX.
SECTIONED_PAGE_CHAR_THRESHOLD = 5_000


class EditEventQueue:
    """Async queue of `AgentEvent` for wiki edit streaming."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AgentEvent] = asyncio.Queue()

    async def put(self, event: AgentEvent) -> None:
        await self._queue.put(event)

    async def get(self) -> AgentEvent:
        return await self._queue.get()


@dataclass
class EditWorkingMemory:
    """Budget-managed working memory for edit sessions."""

    focus_sections: list[str] = field(default_factory=list)
    context_sections: list[str] = field(default_factory=list)
    outline: list[str] = field(default_factory=list)
    tool_results: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    MAX_TOTAL_CHARS: int = 200_000
    SINGLE_TOOL_RESULT_LIMIT: int = 6_000

    def total_chars(self) -> int:
        total = sum(len(s) for s in self.focus_sections)
        total += sum(len(s) for s in self.context_sections)
        total += sum(len(s) for s in self.outline)
        limit = self.SINGLE_TOOL_RESULT_LIMIT
        for _, r in self.tool_results:
            total += len(
                json.dumps(r, ensure_ascii=False, default=str)[:limit]
            )
        return total

    def incorporate_tool_result(self, tool: str, data: dict[str, Any]) -> None:
        self.tool_results.append((tool, data))
        self._enforce_limit()

    def _enforce_limit(self) -> None:
        """Evict by priority: context_sections then tool_results (FIFO).

        ``focus_sections`` and ``outline`` are never dropped from memory.
        """
        while self.total_chars() > self.MAX_TOTAL_CHARS:
            if self.context_sections:
                self.context_sections.pop(0)
            elif self.tool_results:
                self.tool_results.pop(0)
            else:
                break


EditMemory = EditWorkingMemory  # backward compatibility


class WikiEditAgent(GenericAgent):
    """Edits wiki page body via optional tool loop + final generation."""

    def __init__(self, llm: Any, graph: Any = None, **kwargs: Any) -> None:
        super().__init__(llm, **kwargs)
        self._graph = graph
        if self._graph is not None:
            self._register_tools()

    def _register_tools(self) -> None:
        tool_handlers = {
            "search_entities": self._tool_search_entities,
            "query_module_detail": self._tool_query_module_detail,
            "search_wiki_pages": self._tool_search_wiki_pages,
            "read_source_file": self._tool_read_source_file,
            "get_call_chain": self._tool_get_call_chain,
        }
        for tool_schema in EDIT_AGENT_TOOLS:
            func_info = tool_schema["function"]
            name = func_info["name"]
            handler = tool_handlers.get(name)
            if handler is None:
                log.warning("wiki_edit_agent_tool_handler_missing", tool=name)
                continue
            self._tool_registry.register(
                ToolDef(
                    name=name,
                    description=func_info["description"],
                    parameters=func_info.get("parameters", {}),
                    handler=handler,
                    tier=_EDIT_AGENT_TOOL_TIERS.get(name, 1),
                )
            )

    async def _run_graph_query(self, cypher: str, params: dict[str, Any]) -> Any:
        if self._graph is None:
            return {"error": "graph unavailable"}
        ex = getattr(self._graph, "execute_query", None)
        if not callable(ex):
            return {"error": "graph unavailable"}
        try:
            pending = ex(cypher, params)
        except Exception as exc:
            log.warning("wiki_edit_agent_cypher_invoke_failed", exc_info=True)
            return {"error": str(exc)}
        if not inspect.isawaitable(pending):
            return {"error": "graph unavailable"}
        try:
            result = await pending
        except Exception as exc:
            log.warning("wiki_edit_agent_cypher_await_failed", exc_info=True)
            return {"error": str(exc)}
        return getattr(result, "data", None) or []

    async def _tool_search_entities(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        if not query:
            return {"error": "missing query"}
        try:
            limit = min(max(1, int(args.get("limit", 10) or 10)), 50)
        except (TypeError, ValueError):
            limit = 10
        raw = await self._run_graph_query(SEARCH_ENTITIES_CY, {"query": query, "limit": limit})
        if isinstance(raw, dict) and raw.get("error"):
            return raw
        rows: list[Any] = raw if isinstance(raw, list) else []
        results = []
        for row in rows:
            if isinstance(row, dict):
                results.append({
                    "uid": str(row.get("uid", "") or ""),
                    "name": str(row.get("name", "") or ""),
                    "label": str(row.get("label", "") or ""),
                    "description": str(row.get("description", "") or ""),
                })
        return {"results": results, "total": len(results)}

    async def _tool_query_module_detail(self, args: dict[str, Any]) -> dict[str, Any]:
        module_name = str(args.get("module_name", "")).strip()
        if not module_name:
            return {"error": "missing module_name"}
        methods_rows = await self._run_graph_query(METHODS_CY, {"names": [module_name]})
        if isinstance(methods_rows, dict) and methods_rows.get("error"):
            return methods_rows
        outgoing = await self._run_graph_query(
            MODULE_OUTGOING_DEPS_CY, {"module_name": module_name}
        )
        if isinstance(outgoing, dict) and outgoing.get("error"):
            return outgoing
        incoming = await self._run_graph_query(
            MODULE_INCOMING_DEPS_CY, {"module_name": module_name}
        )
        if isinstance(incoming, dict) and incoming.get("error"):
            return incoming

        methods: list[dict[str, str]] = []
        for row in methods_rows if isinstance(methods_rows, list) else []:
            if isinstance(row, dict):
                methods.append({
                    "name": str(row.get("func_name", "") or ""),
                    "signature": str(row.get("signature", "") or ""),
                    "file": str(row.get("file_path", "") or ""),
                })
        outgoing_names = [
            str(r.get("name", "") or "")
            for r in (outgoing if isinstance(outgoing, list) else [])
            if isinstance(r, dict) and str(r.get("name", "") or "")
        ]
        incoming_names = [
            str(r.get("name", "") or "")
            for r in (incoming if isinstance(incoming, list) else [])
            if isinstance(r, dict) and str(r.get("name", "") or "")
        ]
        return {
            "module_name": module_name,
            "methods": methods[:20],
            "outgoing_dependencies": outgoing_names,
            "incoming_dependencies": incoming_names,
        }

    async def _tool_search_wiki_pages(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        if not query:
            return {"error": "missing query"}
        try:
            limit = min(max(1, int(args.get("limit", 5) or 5)), 30)
        except (TypeError, ValueError):
            limit = 5
        raw = await self._run_graph_query(
            SEARCH_WIKI_PAGES_CY, {"query": query, "limit": limit}
        )
        if isinstance(raw, dict) and raw.get("error"):
            return raw
        rows: list[Any] = raw if isinstance(raw, list) else []
        pages = []
        for row in rows:
            if isinstance(row, dict):
                pages.append({
                    "title": str(row.get("title", "") or ""),
                    "path": str(row.get("path", "") or ""),
                    "snippet": str(row.get("snippet", "") or ""),
                })
        return {"pages": pages, "total": len(pages)}

    async def _tool_read_source_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = str(args.get("path", "")).strip()
        if not path:
            return {"error": "missing path"}
        raw = await self._run_graph_query(READ_SOURCE_FILE_CY, {"path": path})
        if isinstance(raw, dict) and raw.get("error"):
            return raw
        rows = raw if isinstance(raw, list) else []
        if not rows:
            return {"path": path, "content": "", "found": False}
        row = rows[0] if isinstance(rows[0], dict) else {}
        return {
            "path": str(row.get("path", "") or path),
            "content": str(row.get("content", "") or ""),
            "found": True,
        }

    async def _tool_get_call_chain(self, args: dict[str, Any]) -> dict[str, Any]:
        func_name = str(args.get("func_name", "")).strip()
        if not func_name:
            return {"error": "missing func_name"}
        raw = await self._run_graph_query(
            GET_CALL_CHAIN_CY, {"func_name": func_name}
        )
        if isinstance(raw, dict) and raw.get("error"):
            return raw
        rows = raw if isinstance(raw, list) else []
        callees = []
        for row in rows:
            if isinstance(row, dict):
                callees.append({
                    "name": str(row.get("name", "") or ""),
                    "file_path": str(row.get("file_path", "") or ""),
                })
        return {"func_name": func_name, "callees": callees, "total": len(callees)}

    @staticmethod
    def _body_under_section_heading(sec: Section, raw_llm_output: str) -> str:
        """Normalize LLM snippet to section body only (reassemble_page adds headings)."""
        text = raw_llm_output.strip()
        if not sec.heading:
            return text
        h = sec.heading.strip()
        lines = text.split("\n")
        if lines and lines[0].strip() == h:
            return "\n".join(lines[1:]).strip()
        return text

    def create_memory(self) -> EditWorkingMemory:
        return EditWorkingMemory()

    def incorporate(
        self, tool_name: str, result: dict[str, Any], memory: Any
    ) -> None:
        if not isinstance(memory, EditWorkingMemory):
            return
        memory.incorporate_tool_result(tool_name, result)

    def memory_to_prompt(self, memory: Any) -> str:
        if not isinstance(memory, EditWorkingMemory):
            return ""
        parts: list[str] = []
        if memory.context_sections:
            ctx = "\n\n".join(memory.context_sections)
            parts.append(f"## Adjacent sections (truncated)\n\n{ctx}")
        if memory.tool_results:
            tb: list[str] = ["## Tool results", ""]
            lim = memory.SINGLE_TOOL_RESULT_LIMIT
            for name, res in memory.tool_results:
                dumped = json.dumps(res, ensure_ascii=False, default=str)[:lim]
                tb.extend((f"### {name}", dumped))
            parts.append("\n".join(tb))
        return "\n\n".join(parts)

    def _build_system_prompt(self, current_content: str) -> str:
        return (
            "You are a wiki editor. Rewrite and improve the full page markdown "
            "according to the user's instruction. Preserve structure where "
            "appropriate. Output complete wiki markdown only, no preamble.\n\n"
            "## Current page\n\n"
            f"{current_content}"
        )

    def _build_system_prompt_sectioned(
        self,
        focus_texts: list[str],
        outline_texts: list[str],
    ) -> str:
        focus_block = "\n\n".join(focus_texts)
        outline_part = ""
        if outline_texts:
            outline_body = "\n".join(outline_texts).strip()
            if outline_body:
                outline_part = (
                    "\n\n## Other sections (headings only)\n\n" + outline_body
                )
        return (
            "You are a wiki editor. Edit ONLY the focused sections below "
            "according to the user's instruction. "
            "Output the edited sections maintaining their headings. "
            "Do NOT output the full page — only the sections shown under "
            "'Current page (focused sections)'.\n\n"
            "## Current page (focused sections)\n\n"
            f"{focus_block}"
            f"{outline_part}"
        )

    @staticmethod
    def _format_history(conversation_history: list[Any]) -> str:
        if not conversation_history:
            return ""
        parts: list[str] = []
        for item in conversation_history:
            if isinstance(item, dict):
                role = str(item.get("role", "user"))
                content = str(item.get("content", ""))
                parts.append(f"{role}: {content}")
            else:
                parts.append(str(item))
        return "\n\n".join(parts)

    def _build_tool_user_prompt(
        self, prompt: str, conversation_history: list[Any]
    ) -> str:
        hist = self._format_history(conversation_history)
        blocks = [f"## Instruction\n{prompt}"]
        if hist:
            blocks.append(f"## Prior conversation\n{hist}")
        return "\n\n".join(blocks)

    def _build_generation_user_prompt(
        self,
        prompt: str,
        conversation_history: list[Any],
        memory: EditWorkingMemory,
        *,
        sectioned: bool = False,
    ) -> str:
        mem = self.memory_to_prompt(memory)
        parts = [
            "## Instruction\n" + prompt,
        ]
        hist = self._format_history(conversation_history)
        if hist:
            parts.append("## Prior conversation\n" + hist)
        if mem:
            parts.append(mem)
        if sectioned:
            parts.append(
                "\nProduce markdown for ONLY the focused sections "
                "(with their headings). Do not repeat the rest of the page."
            )
        else:
            parts.append(
                "\nProduce the revised full markdown for the wiki page now."
            )
        return "\n\n".join(parts)

    async def run_edit_stream(
        self,
        prompt: str,
        current_content: str,
        conversation_history: list[Any],
        event_queue: EditEventQueue,
    ) -> str:
        async def _emit(event: AgentEvent) -> None:
            await event_queue.put(event)

        is_sectioned = len(current_content) > SECTIONED_PAGE_CHAR_THRESHOLD
        sections: list[Section] | None = None
        focus_indices: list[int] | None = None

        if is_sectioned:
            sections = split_page_into_sections(current_content)
            focus_indices = locate_edit_sections(sections, prompt)
            focus_texts, adjacent_texts, outline_texts = build_context_sections(
                sections, focus_indices
            )
            memory = EditWorkingMemory(
                focus_sections=focus_texts,
                context_sections=adjacent_texts,
                outline=outline_texts,
            )
            system_prompt = self._build_system_prompt_sectioned(
                focus_texts,
                outline_texts,
            )
        else:
            memory = EditWorkingMemory()
            system_prompt = self._build_system_prompt(current_content)
        user_for_tools = self._build_tool_user_prompt(prompt, conversation_history)

        try:
            if self._tool_registry.has_tools():
                await self.run_tool_loop(
                    system_prompt,
                    user_for_tools,
                    memory,
                    event_callback=_emit,
                )

            user_gen = self._build_generation_user_prompt(
                prompt, conversation_history, memory, sectioned=is_sectioned
            )
            text = await self._llm.generate(
                prompt=user_gen, system=system_prompt
            )

            if (
                is_sectioned
                and sections is not None
                and focus_indices is not None
            ):
                edited_map: dict[int, str] = {}
                output_secs = split_page_into_sections(text)
                for out_sec in output_secs:
                    oh = out_sec.heading.strip().lower()
                    for fi in sorted(set(focus_indices)):
                        if fi in edited_map:
                            continue
                        sec = sections[fi]
                        if sec.heading.strip().lower() != oh:
                            continue
                        edited_map[fi] = out_sec.body
                if focus_indices:
                    if not edited_map:
                        fi0 = sorted(focus_indices)[0]
                        edited_map[fi0] = self._body_under_section_heading(
                            sections[fi0], text
                        )
                text = reassemble_page(sections, edited_map)

            await _emit(ContentEvent(text=text))
            await _emit(DoneEvent(result=text))
            return text
        except Exception as exc:
            log.warning("run_edit_stream_failed", exc_info=True)
            await _emit(ErrorEvent(message=str(exc)))
            raise
