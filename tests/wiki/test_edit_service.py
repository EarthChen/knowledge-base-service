import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from store.session_store import Session, SessionTurn


@pytest.fixture
def mock_session_store():
    store = AsyncMock()
    store.get = AsyncMock(return_value=None)
    store.save = AsyncMock()
    store.delete = AsyncMock()
    return store


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete_with_tools = AsyncMock(return_value={"tool_calls": None})
    llm.generate = AsyncMock(return_value="# Edited content")
    return llm


@pytest.fixture
def mock_graph():
    graph = MagicMock()
    graph.update_wiki_page_content = AsyncMock(
        return_value={"ok": True, "page_uid": "p1", "version": 2, "previous_version": 1},
    )
    graph.execute_query = AsyncMock(
        return_value=MagicMock(data=[{"content": "# Old"}]),
    )
    return graph


@pytest.mark.asyncio
async def test_create_session(mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    session_id = await svc.create_session("page-1", "# Original")
    assert session_id is not None
    assert len(session_id) > 0
    mock_session_store.save.assert_called_once()


@pytest.mark.asyncio
async def test_get_session(mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService
    from store.session_store import Session
    mock_session_store.get.return_value = Session(
        session_id="s1", session_type="edit",
        metadata={"page_uid": "p1", "original_content": "# Old", "current_content": "# Old"},
    )
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    session = await svc.get_session("s1")
    assert session is not None
    assert session.metadata["page_uid"] == "p1"


@pytest.mark.asyncio
async def test_delete_session(mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    await svc.delete_session("s1")
    mock_session_store.delete.assert_called_once_with("s1")


@pytest.mark.asyncio
async def test_apply_edit(mock_session_store, mock_llm, mock_graph):
    from wiki.edit_service import WikiEditService
    from store.session_store import Session
    mock_session_store.get.return_value = Session(
        session_id="s1", session_type="edit",
        metadata={"page_uid": "p1", "original_content": "# Old", "current_content": "# New"},
    )
    svc = WikiEditService(
        session_store=mock_session_store, llm=mock_llm, graph=mock_graph,
    )
    result = await svc.apply_edit("s1")
    assert result["page_uid"] == "p1"
    assert result["content"] == "# New"
    mock_graph.execute_query.assert_awaited_once()
    mock_graph.update_wiki_page_content.assert_awaited_once_with(
        "p1", "# New", source="agent_edit",
    )


@pytest.mark.asyncio
async def test_apply_edit_not_found(mock_session_store, mock_llm, mock_graph):
    from wiki.edit_service import WikiEditService
    svc = WikiEditService(
        session_store=mock_session_store, llm=mock_llm, graph=mock_graph,
    )
    with pytest.raises(ValueError, match="not found"):
        await svc.apply_edit("nonexistent")
    mock_graph.update_wiki_page_content.assert_not_called()


@pytest.mark.asyncio
async def test_apply_edit_requires_graph(mock_session_store, mock_llm):
    from store.session_store import Session
    from wiki.edit_service import WikiEditService

    mock_session_store.get.return_value = Session(
        session_id="s1",
        session_type="edit",
        metadata={"page_uid": "p1", "original_content": "# Old", "current_content": "# New"},
    )
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm, graph=None)
    with pytest.raises(ValueError, match="graph store is required"):
        await svc.apply_edit("s1")


@pytest.mark.asyncio
async def test_send_message_registers_queue_and_tracked_task(mock_session_store, mock_llm):
    from store.session_store import Session
    from wiki.edit_service import WikiEditService

    mock_session_store.get.return_value = Session(
        session_id="s1",
        session_type="edit",
        turns=[],
        metadata={
            "page_uid": "p1",
            "original_content": "# Old",
            "current_content": "# Old",
        },
    )
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    queue = await svc.send_message("s1", "fix heading")
    assert len(svc._background_tasks) == 1
    popped = svc.get_event_queue("s1")
    assert popped is queue
    assert svc.get_event_queue("s1") is None
    pending = tuple(svc._background_tasks)[0]
    await pending


@pytest.mark.asyncio
async def test_delete_session_removes_pending_queue(mock_session_store, mock_llm):
    from wiki.agents.edit_agent import EditEventQueue
    from wiki.edit_service import WikiEditService

    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    svc._active_queues["s2"] = EditEventQueue()
    await svc.delete_session("s2")
    assert svc._active_queues.get("s2") is None
    mock_session_store.delete.assert_called_once_with("s2")


def _paired_turns(n_rounds: int) -> list[SessionTurn]:
    turns: list[SessionTurn] = []
    for i in range(n_rounds):
        turns.append(SessionTurn(role="user", content=f"u{i}"))
        turns.append(SessionTurn(role="assistant", content=f"a{i}"))
    return turns


@pytest.mark.asyncio
@patch("wiki.edit_service.WikiEditAgent")
async def test_send_message_truncates_assistant_turn(mock_agent_cls, mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService

    huge = "\n".join([f"## Section-{i}" for i in range(12)] + ["body " * 100])
    mock_agent_inst = MagicMock()
    mock_agent_cls.return_value = mock_agent_inst
    mock_agent_inst.run_edit_stream = AsyncMock(return_value=huge)

    mock_session_store.get.return_value = Session(
        session_id="s1",
        session_type="edit",
        turns=[],
        metadata={
            "page_uid": "p1",
            "original_content": "# Old",
            "current_content": "# Old",
        },
    )
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    await svc.send_message("s1", "go")
    pending = tuple(svc._background_tasks)[0]
    await pending

    saved: Session = mock_session_store.save.await_args.args[0]
    assistant = saved.turns[-1]
    assert assistant.role == "assistant"
    assert len(assistant.content) < len(huge)
    assert "Sections:" in assistant.content or "[Edited page -" in assistant.content
    assert saved.metadata["current_content"] == huge


@pytest.mark.asyncio
@patch("wiki.edit_service.WikiEditAgent")
async def test_send_message_compresses_history(mock_agent_cls, mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService

    turns = _paired_turns(5)
    mock_agent_inst = MagicMock()
    mock_agent_cls.return_value = mock_agent_inst
    mock_agent_inst.run_edit_stream = AsyncMock(return_value="# Out")

    mock_session_store.get.return_value = Session(
        session_id="s1",
        session_type="edit",
        turns=turns,
        metadata={
            "page_uid": "p1",
            "original_content": "# Old",
            "current_content": "# Body",
        },
    )
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    await svc.send_message("s1", "next")
    pending = tuple(svc._background_tasks)[0]
    await pending

    kwargs = mock_agent_inst.run_edit_stream.await_args.kwargs
    history = kwargs["conversation_history"]
    assert len(history) == 7
    assert history[0]["role"] == "system"
    assert "Earlier conversation summary" in history[0]["content"]
    tail = [{"role": t["role"], "content": t["content"]} for t in history[1:]]
    expected_tail = [
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
        {"role": "assistant", "content": "a3"},
        {"role": "user", "content": "u4"},
        {"role": "assistant", "content": "a4"},
    ]
    assert tail == expected_tail


class TestVersionConflict:
    @pytest.mark.asyncio
    async def test_apply_raises_on_content_mismatch(
        self, mock_session_store, mock_llm, mock_graph,
    ):
        from wiki.edit_service import WikiEditService

        mock_session_store.get.return_value = Session(
            session_id="s1",
            session_type="edit",
            metadata={
                "page_uid": "p1",
                "original_content": "foo",
                "current_content": "bar",
            },
        )
        mock_graph.execute_query = AsyncMock(
            return_value=MagicMock(data=[{"content": "changed"}]),
        )
        svc = WikiEditService(
            session_store=mock_session_store, llm=mock_llm, graph=mock_graph,
        )
        with pytest.raises(ValueError, match="modified since"):
            await svc.apply_edit("s1")
        mock_graph.update_wiki_page_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_succeeds_when_content_matches(
        self, mock_session_store, mock_llm, mock_graph,
    ):
        from wiki.edit_service import WikiEditService

        mock_session_store.get.return_value = Session(
            session_id="s1",
            session_type="edit",
            metadata={
                "page_uid": "p1",
                "original_content": "foo",
                "current_content": "# New",
            },
        )
        mock_graph.execute_query = AsyncMock(
            return_value=MagicMock(data=[{"content": "foo"}]),
        )
        svc = WikiEditService(
            session_store=mock_session_store, llm=mock_llm, graph=mock_graph,
        )
        out = await svc.apply_edit("s1")
        assert out["content"] == "# New"
        mock_graph.update_wiki_page_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_apply_raises_when_page_missing_in_graph(
        self, mock_session_store, mock_llm, mock_graph,
    ):
        from wiki.edit_service import WikiEditService

        mock_session_store.get.return_value = Session(
            session_id="s1",
            session_type="edit",
            metadata={
                "page_uid": "p1",
                "original_content": "foo",
                "current_content": "x",
            },
        )
        mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        svc = WikiEditService(
            session_store=mock_session_store, llm=mock_llm, graph=mock_graph,
        )
        with pytest.raises(ValueError, match="Wiki page not found"):
            await svc.apply_edit("s1")


class TestEditingStoreIntegration:
    @pytest.mark.asyncio
    @patch("wiki.edit_service.WikiEditAgent")
    async def test_send_message_calls_editing_heartbeat_when_store_configured(
        self, mock_agent_cls, mock_session_store, mock_llm,
    ):
        from wiki.edit_service import WikiEditService

        editing = AsyncMock()
        mock_agent_inst = MagicMock()
        mock_agent_cls.return_value = mock_agent_inst
        mock_agent_inst.run_edit_stream = AsyncMock(return_value="# Done")

        mock_session_store.get.return_value = Session(
            session_id="s1",
            session_type="edit",
            turns=[],
            metadata={
                "page_uid": "WikiPage:test",
                "original_content": "# Old",
                "current_content": "# Old",
            },
        )
        svc = WikiEditService(
            session_store=mock_session_store,
            llm=mock_llm,
            editing_store=editing,
        )
        await svc.send_message("s1", "go")
        editing.heartbeat.assert_awaited_once_with("WikiPage:test", "agent-s1")
        task = tuple(svc._background_tasks)[0]
        await task

    @pytest.mark.asyncio
    async def test_delete_session_calls_editing_stop_when_store_configured(
        self, mock_session_store, mock_llm,
    ):
        from wiki.edit_service import WikiEditService

        editing = AsyncMock()
        mock_session_store.get.return_value = Session(
            session_id="sx",
            session_type="edit",
            metadata={"page_uid": "WikiPage:z", "original_content": "a", "current_content": "a"},
        )
        svc = WikiEditService(
            session_store=mock_session_store,
            llm=mock_llm,
            editing_store=editing,
        )
        await svc.delete_session("sx")
        editing.stop.assert_awaited_once_with("WikiPage:z", "agent-sx")
        mock_session_store.delete.assert_called_once_with("sx")
