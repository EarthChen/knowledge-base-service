"""Wiki-focused edit agent streaming events while editing page markdown."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from wiki.agents.base_agent import GenericAgent
from wiki.agents.events import AgentEvent, ContentEvent, DoneEvent, ErrorEvent

from core.log import get_logger

log = get_logger(__name__)


class EditEventQueue:
    """Async queue of `AgentEvent` for wiki edit streaming."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AgentEvent] = asyncio.Queue()

    async def put(self, event: AgentEvent) -> None:
        await self._queue.put(event)

    async def get(self) -> AgentEvent:
        return await self._queue.get()


@dataclass
class EditMemory:
    tool_results: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


class WikiEditAgent(GenericAgent):
    """Edits wiki page body via optional tool loop + final generation."""

    def __init__(self, llm: Any, graph: Any = None, **kwargs: Any) -> None:
        super().__init__(llm, **kwargs)
        self._graph = graph

    def create_memory(self) -> EditMemory:
        return EditMemory()

    def incorporate(
        self, tool_name: str, result: dict[str, Any], memory: Any
    ) -> None:
        if not isinstance(memory, EditMemory):
            return
        memory.tool_results.append((tool_name, result))

    def memory_to_prompt(self, memory: Any) -> str:
        if not isinstance(memory, EditMemory) or not memory.tool_results:
            return ""
        lines = ["## Tool results", ""]
        for name, res in memory.tool_results:
            lines.append(f"### {name}")
            lines.append(json.dumps(res, ensure_ascii=False, default=str))
        return "\n".join(lines)

    def _build_system_prompt(self, current_content: str) -> str:
        return (
            "You are a wiki editor. Rewrite and improve the full page markdown "
            "according to the user's instruction. Preserve structure where "
            "appropriate. Output complete wiki markdown only, no preamble.\n\n"
            "## Current page\n\n"
            f"{current_content}"
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
        memory: EditMemory,
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

        memory = self.create_memory()
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
                prompt, conversation_history, memory
            )
            text = await self._llm.generate(
                prompt=user_gen, system=system_prompt
            )

            await _emit(ContentEvent(text=text))
            await _emit(DoneEvent(result=text))
            return text
        except Exception as exc:
            log.warning("run_edit_stream_failed", exc_info=True)
            await _emit(ErrorEvent(message=str(exc)))
            raise
