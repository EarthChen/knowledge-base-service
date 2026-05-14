"""Session-backed service for streaming wiki page edits."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from store.session_store import Session, SessionTurn
from wiki.agents.edit_agent import EditEventQueue, WikiEditAgent

from core.log import get_logger

log = get_logger(__name__)


class WikiEditService:
    def __init__(
        self,
        session_store: Any,
        llm: Any,
        graph: Any = None,
    ) -> None:
        self._session_store = session_store
        self._llm = llm
        self._graph = graph

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
        await self._session_store.delete(session_id)

    async def send_message(self, session_id: str, prompt: str) -> EditEventQueue:
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError("session not found")

        queue: EditEventQueue = EditEventQueue()
        agent = WikiEditAgent(self._llm, graph=self._graph)
        conversation_history = [
            {"role": t.role, "content": t.content} for t in session.turns
        ]
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
            session.turns.append(SessionTurn(role="assistant", content=content))
            await self._session_store.save(session)

        asyncio.create_task(_run())
        return queue

    async def apply_edit(self, session_id: str) -> dict[str, Any]:
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError("session not found")
        return {
            "page_uid": session.metadata["page_uid"],
            "content": session.metadata["current_content"],
        }
