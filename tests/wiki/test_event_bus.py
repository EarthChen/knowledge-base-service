import asyncio
import builtins
import threading

import pytest

from wiki.event_bus import WikiEvent, WikiEventBus


@pytest.mark.asyncio
async def test_publish_snapshots_subscribers_before_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """publish must copy _subscribers before iterating (copy-on-iterate)."""
    bus = WikiEventBus()
    bus.subscribe()
    snapshots: list[list[object]] = []
    real_list = list

    def tracking_list(obj: object) -> list[object]:
        if obj is bus._subscribers:
            snapshots.append(real_list(obj))
        return real_list(obj)

    monkeypatch.setattr(builtins, "list", tracking_list)
    await bus.publish(WikiEvent(event_type="test", repository="r"))
    assert len(snapshots) == 1


@pytest.mark.asyncio
async def test_concurrent_subscribe_unsubscribe_during_publish() -> None:
    """Subscribe/unsubscribe from other threads during publish must not raise RuntimeError."""
    bus = WikiEventBus()
    held = [bus.subscribe() for _ in range(5)]
    stop = threading.Event()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def subscribe_loop() -> None:
        while not stop.is_set():
            try:
                q = bus.subscribe()
                bus.unsubscribe(q)
            except RuntimeError as exc:
                with lock:
                    errors.append(exc)
                return

    sub_threads = [threading.Thread(target=subscribe_loop) for _ in range(2)]
    for t in sub_threads:
        t.start()

    event = WikiEvent(event_type="test", repository="r")
    for _ in range(50):
        await bus.publish(event)

    stop.set()
    for t in sub_threads:
        t.join(timeout=2)

    for q in held:
        bus.unsubscribe(q)

    assert not errors, f"RuntimeError during concurrent publish: {errors}"


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
async def test_full_queue_drops_oldest_event() -> None:
    bus = WikiEventBus()
    q = bus.subscribe()
    for i in range(100):
        await bus.publish(WikiEvent(event_type="test", repository="r", data={"i": i}))
    await bus.publish(WikiEvent(event_type="overflow", repository="r", data={"i": 100}))
    assert q in bus._subscribers
    assert q.qsize() == 100
    first = q.get_nowait()
    assert first.data.get("i") == 1


@pytest.mark.asyncio
async def test_shutdown() -> None:
    bus = WikiEventBus()
    bus.subscribe()
    await bus.shutdown()
    assert len(bus._subscribers) == 0


@pytest.mark.asyncio
async def test_shutdown_sends_close_event() -> None:
    bus = WikiEventBus()
    q = bus.subscribe()
    await bus.shutdown()
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    close_events = [e for e in events if e is not None and e.event_type == "close"]
    assert len(close_events) == 1
    assert close_events[0].data.get("reason") == "server_shutdown"


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
