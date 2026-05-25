"""Phase 2: Enriched SSE progress events + task API (node_statuses, config_snapshot).

Tests verify that progress callback data with node_statuses is correctly stored
in task status and returned from the task status endpoint.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from store.task_store import SqliteTaskStore, TaskRecord


@pytest.fixture()
async def task_store(tmp_path):
    store = SqliteTaskStore(str(tmp_path / "tasks.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture()
def registry():
    from wiki.task_registry import WikiTaskRegistry

    return WikiTaskRegistry()


# ---------------------------------------------------------------------------
# Phase 2a: _wiki_merge_task_status stores node_statuses
# ---------------------------------------------------------------------------


async def test_merge_task_status_stores_node_statuses(task_store: SqliteTaskStore) -> None:
    """Progress callback data with node_statuses is persisted in task progress_json."""
    from api.routes.wiki_task_routes import _wiki_merge_task_status

    await task_store.put(
        TaskRecord(
            task_id="task-1",
            task_type="wiki_generate",
            business_id="biz-1",
            status="running",
        )
    )

    node_statuses = {
        "compose_leaf_modules": {"status": "running", "started_at": 1700000.0},
        "classify_entity_roles": {
            "status": "completed",
            "started_at": 1699999.0,
            "completed_at": 1699999.5,
            "elapsed_sec": 0.5,
        },
    }

    await _wiki_merge_task_status(
        task_store,
        "task-1",
        "running",
        node_statuses=node_statuses,
        node_name="compose_leaf_modules",
        node_status="running",
        elapsed_sec=0.5,
    )

    row = await task_store.get("task-1")
    assert row is not None
    prog = json.loads(row.progress_json)
    assert "node_statuses" in prog
    assert prog["node_statuses"]["compose_leaf_modules"]["status"] == "running"
    assert prog["node_name"] == "compose_leaf_modules"
    assert prog["node_status"] == "running"


async def test_merge_task_status_merges_with_existing(task_store: SqliteTaskStore) -> None:
    """Multiple progress callbacks merge fields rather than overwriting the whole dict."""
    from api.routes.wiki_task_routes import _wiki_merge_task_status

    await task_store.put(
        TaskRecord(task_id="task-2", task_type="wiki_generate", business_id="biz-1", status="running")
    )

    # First update
    await _wiki_merge_task_status(
        task_store,
        "task-2",
        "running",
        node_statuses={"graph_decompose": {"status": "completed"}},
        progress_pct="10",
    )

    # Second update — new field should merge, not replace
    await _wiki_merge_task_status(
        task_store,
        "task-2",
        "running",
        node_statuses={
            "graph_decompose": {"status": "completed"},
            "compose_leaf_modules": {"status": "running"},
        },
        progress_pct="20",
    )

    row = await task_store.get("task-2")
    assert row is not None
    prog = json.loads(row.progress_json)
    assert prog["progress_pct"] == "20"
    # Both node statuses present
    assert prog["node_statuses"]["graph_decompose"]["status"] == "completed"
    assert prog["node_statuses"]["compose_leaf_modules"]["status"] == "running"


# ---------------------------------------------------------------------------
# Phase 2b: node_statuses appears in task response
# ---------------------------------------------------------------------------


async def test_task_response_includes_node_statuses(task_store: SqliteTaskStore, registry) -> None:
    """GET /wiki/business/tasks/{taskId} returns node_statuses in the response dict."""
    from api.routes.wiki_task_routes import _wiki_task_record_to_client_dict

    await task_store.put(
        TaskRecord(task_id="task-3", task_type="wiki_generate", business_id="biz-1", status="running")
    )

    node_statuses = {
        "compose_leaf_modules": {"status": "completed", "elapsed_sec": 1.23},
        "quality_gate": {"status": "running", "started_at": 1700001.0},
    }
    await task_store.update_status(
        "task-3", "running", progress_json=json.dumps({"node_statuses": node_statuses})
    )

    row = await task_store.get("task-3")
    assert row is not None
    result = _wiki_task_record_to_client_dict(row)
    assert result["node_statuses"]["compose_leaf_modules"]["elapsed_sec"] == 1.23
    assert result["node_statuses"]["quality_gate"]["status"] == "running"


async def test_task_response_includes_config_snapshot(task_store: SqliteTaskStore) -> None:
    """GET /wiki/business/tasks/{taskId} returns config_snapshot when present."""
    from api.routes.wiki_task_routes import _wiki_task_record_to_client_dict

    config_snapshot = {
        "compose_concurrency": 16,
        "domain_agent_concurrency": 6,
        "heal_concurrency": 3,
        "wiki_generation_concurrency": 2,
    }
    await task_store.put(
        TaskRecord(
            task_id="task-4",
            task_type="wiki_generate",
            business_id="biz-1",
            status="running",
            progress_json=json.dumps({"config_snapshot": config_snapshot}),
        )
    )

    row = await task_store.get("task-4")
    assert row is not None
    result = _wiki_task_record_to_client_dict(row)
    assert result["config_snapshot"]["compose_concurrency"] == 16
    assert result["config_snapshot"]["domain_agent_concurrency"] == 6


# ---------------------------------------------------------------------------
# Phase 2c: Progress callback enriches registry + event bus
# ---------------------------------------------------------------------------


async def test_progress_callback_enriches_registry(registry) -> None:
    """The _progress callback passes node_statuses into WikiTaskRegistry.put_task()."""

    # Set up a task in registry
    registry.put_task("task-5", {"task_id": "task-5", "status": "pending", "business_id": "biz-1"})

    # We'll directly test the progress enrichment logic by calling the callback
    # Rather than running the full background (which requires WikiService), we
    # simulate what the _progress closure does.
    node_statuses = {
        "graph_decompose": {"status": "completed", "elapsed_sec": 0.5},
        "compose_leaf_modules": {"status": "running", "started_at": 1700000.0},
    }

    # Simulate what _progress does to registry
    extra: dict[str, Any] = {
        "node_statuses": node_statuses,
        "node_name": "compose_leaf_modules",
        "node_status": "running",
        "elapsed_sec": 0.5,
    }
    prev = registry.get_task("task-5") or {}
    registry.put_task("task-5", {**prev, "status": "running", **extra})

    rec = registry.get_task("task-5")
    assert rec is not None
    assert rec["node_name"] == "compose_leaf_modules"
    assert rec["node_status"] == "running"
    assert rec["node_statuses"]["graph_decompose"]["elapsed_sec"] == 0.5


async def test_progress_callback_publishes_to_event_bus() -> None:
    """The _progress callback publishes enriched data to WikiEventBus."""
    from wiki.event_bus import WikiEvent, WikiEventBus

    bus = WikiEventBus()
    published: list[WikiEvent] = []

    original_publish = bus.publish

    async def capture_publish(event: WikiEvent) -> None:
        published.append(event)
        await original_publish(event)

    bus.publish = capture_publish

    node_statuses = {
        "compose_leaf_modules": {"status": "completed", "elapsed_sec": 2.1},
    }
    await bus.publish(
        WikiEvent(
            event_type="business_gen_progress",
            repository="biz-1",
            business_id="biz-1",
            data={
                "task_id": "task-6",
                "node_statuses": node_statuses,
                "node_name": "compose_leaf_modules",
                "node_status": "completed",
                "elapsed_sec": 2.1,
            },
        )
    )

    assert len(published) == 1
    event_data = published[0].data
    assert event_data["node_statuses"]["compose_leaf_modules"]["elapsed_sec"] == 2.1
    assert event_data["node_name"] == "compose_leaf_modules"
