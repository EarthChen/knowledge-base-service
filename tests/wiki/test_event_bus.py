import asyncio

import pytest

from wiki.event_bus import WikiEvent, WikiEventBus


@pytest.mark.asyncio
async def test_publish_subscribe() -> None:
    bus = WikiEventBus()
    q = bus.subscribe()
    await bus.publish(WikiEvent(event_type="lint_complete", repository="repo1", data={"issues": 0}))
    event = q.get_nowait()
    assert event is not None
    assert event.event_type == "lint_complete"
    assert event.repository == "repo1"
    bus.unsubscribe(q)


@pytest.mark.asyncio
async def test_full_queue_removes_subscriber() -> None:
    bus = WikiEventBus()
    q = bus.subscribe()
    for i in range(100):
        await bus.publish(WikiEvent(event_type="test", repository="r", data={"i": i}))
    await bus.publish(WikiEvent(event_type="overflow", repository="r"))
    assert q not in bus._subscribers


@pytest.mark.asyncio
async def test_shutdown() -> None:
    bus = WikiEventBus()
    bus.subscribe()
    await bus.shutdown()
    assert len(bus._subscribers) == 0


@pytest.mark.asyncio
async def test_stream_emits_heartbeat_on_queue_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wiki.event_bus._STREAM_QUEUE_GET_TIMEOUT_SEC", 0.05)
    bus = WikiEventBus()

    async def collect_one() -> WikiEvent:
        async for ev in bus.stream():
            return ev
        raise AssertionError("stream ended without event")

    task = asyncio.create_task(collect_one())
    await asyncio.sleep(0.12)
    await bus.shutdown()
    hb = await asyncio.wait_for(task, timeout=2.0)
    assert hb.event_type == "heartbeat"
    assert hb.repository == ""
    assert hb.data == {}


@pytest.mark.asyncio
async def test_stream_heartbeat_respects_business_id_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wiki.event_bus._STREAM_QUEUE_GET_TIMEOUT_SEC", 0.05)
    bus = WikiEventBus()
    bid = "biz-42"

    async def collect_one() -> WikiEvent:
        async for ev in bus.stream(bid):
            return ev
        raise AssertionError("stream ended without event")

    task = asyncio.create_task(collect_one())
    hb = await asyncio.wait_for(task, timeout=2.0)
    await bus.shutdown()
    assert hb.business_id == bid
