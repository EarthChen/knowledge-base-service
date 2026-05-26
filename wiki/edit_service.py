"""Session-backed service for streaming wiki page edits."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from core.log import get_logger
from store.session_store import Session, SessionTurn
from wiki.agents.edit_agent import EditEventQueue, WikiEditAgent

log = get_logger(__name__)


class WikiEditService:
    def __init__(
        self,
        session_store: Any,
        llm: Any,
        graph: Any = None,
        editing_store: Any | None = None,
    ) -> None:
        """``graph`` should be the KB wiki store (``kb.store``); required for :meth:`apply_edit`."""
        self._session_store = session_store
        self._llm = llm
        self._graph = graph
        self._editing_store = editing_store
        self._active_queues: dict[str, EditEventQueue] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    def get_event_queue(self, session_id: str) -> EditEventQueue | None:
        return self._active_queues.pop(session_id, None)

    async def create_session(self, page_uid: str, current_content: str) -> str:
        session_id = uuid.uuid4().hex
        session = Session(
            session_id=session_id,
            session_type="edit",
            turns=[],
            metadata={
                "page_uid": page_uid,
                "original_content": current_content,
                "current_content": current_content,
            },
        )
        await self._session_store.save(session)
        return session_id

    async def get_session(self, session_id: str) -> Session | None:
        return await self._session_store.get(session_id)

    async def delete_session(self, session_id: str) -> None:
        session = await self.get_session(session_id)
        self._active_queues.pop(session_id, None)
        if self._editing_store is not None and session is not None:
            page_uid = str(session.metadata.get("page_uid", ""))
            if page_uid:
                await self._editing_store.stop(page_uid, f"agent-{session_id}")
        await self._session_store.delete(session_id)

    async def send_message(self, session_id: str, prompt: str) -> EditEventQueue:
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError("session not found")

        page_uid = str(session.metadata.get("page_uid", ""))
        if self._editing_store is not None and page_uid:
            await self._editing_store.heartbeat(page_uid, f"agent-{session_id}")

        queue: EditEventQueue = EditEventQueue()
        self._active_queues[session_id] = queue
        agent = WikiEditAgent(self._llm, graph=self._graph)

        from wiki.agents.turn_compressor import compress_turns

        compressed = compress_turns(session.turns)
        conversation_history = [{"role": t.role, "content": t.content} for t in compressed]
        current = str(session.metadata.get("current_content", ""))

        async def _run() -> None:
            try:
                content = await agent.run_edit_stream(
                    prompt=prompt,
                    current_content=current,
                    conversation_history=conversation_history,
                    event_queue=queue,
                )
            except Exception:
                log.warning("wiki_edit_send_message_failed", exc_info=True)
                return

            session.metadata["current_content"] = content
            session.turns.append(SessionTurn(role="user", content=prompt))

            from wiki.agents.turn_compressor import truncate_assistant_turn

            session.turns.append(
                SessionTurn(role="assistant", content=truncate_assistant_turn(content))
            )
            await self._session_store.save(session)

        task = asyncio.create_task(_run())
        self._background_tasks.add(task)

        def _discard(t: asyncio.Task[None]) -> None:
            self._background_tasks.discard(t)

        task.add_done_callback(_discard)
        return queue

    async def apply_edit(self, session_id: str) -> dict[str, Any]:
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError("session not found")
        if self._graph is None:
            raise ValueError("graph store is required to apply wiki edits")
        updater = getattr(self._graph, "update_wiki_page_content", None)
        if updater is None:
            raise ValueError("graph store does not support update_wiki_page_content")
        page_uid = str(session.metadata["page_uid"])
        original_content = str(session.metadata.get("original_content", "") or "")

        current_page = await self._graph.execute_query(
            "MATCH (p:WikiPage {uid: $uid}) RETURN coalesce(p.content, '') AS content LIMIT 1",
            {"uid": page_uid},
        )
        current_rows = getattr(current_page, "data", None) or []
        if not current_rows:
            raise ValueError("Wiki page not found in graph")
        live_content = str(current_rows[0].get("content", "") or "")
        if live_content != original_content:
            raise ValueError(
                "Page has been modified since this edit session started. "
                "Please discard and create a new session.",
            )

        content = str(session.metadata["current_content"])
        update_out = await self._graph.update_wiki_page_content(
            page_uid,
            content,
            source="agent_edit",
        )
        out: dict[str, Any] = {"page_uid": page_uid, "content": content}
        out.update(update_out)
        return out
