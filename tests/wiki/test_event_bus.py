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
