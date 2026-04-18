"""P3 cross-track integration tests — webhook, scheduler lock, Ask/MCP graph tools, deprecations, config."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from starlette.testclient import TestClient

from api.routes.webhook_routes import init_webhook_state, webhook_router
from config import LLMConfig
from main import viewer_router
from wiki.mcp_tools import WikiMCPHandler
from wiki.scheduler.task_lock import TaskLock
from wiki.scheduler.wiki_scheduler import ScheduleConfig, WikiScheduler
from wiki.webhook.event_model import ChangedFile

_real_asyncio_sleep = asyncio.sleep


def _github_sig(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _minimal_github_push_payload() -> dict[str, Any]:
    return {
        "ref": "refs/heads/main",
        "before": "1111111111111111111111111111111111111111",
        "after": "2222222222222222222222222222222222222222222",
        "repository": {"full_name": "acme/widget"},
        "sender": {"login": "bot"},
        "commits": [{"added": [], "modified": ["pkg/handler.py", "pkg/service.py"], "removed": []}],
        "head_commit": {"timestamp": "2026-04-18T12:00:00Z"},
    }


@pytest.mark.asyncio
async def test_p3_webhook_full_chain_verify_incremental_port() -> None:
    """POST /hooks/github → verify signature → parse → debounce flush → updater.update(repository, changed_files)."""
    app = FastAPI()
    updater = AsyncMock()
    cfg = {
        "enabled": True,
        "debounce_seconds": 30,
        "auto_update_branches": ["main", "master"],
        "providers": {"github": {"secret": "gh-int-secret", "events": ["push"]}},
    }
    init_webhook_state(app, incremental_updater=updater, initial_config=cfg)
    app.include_router(webhook_router)

    payload = _minimal_github_push_payload()
    body = json.dumps(payload).encode()
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "delivery-p3-int",
        "X-Hub-Signature-256": _github_sig("gh-int-secret", body),
        "Content-Type": "application/json",
    }

    async def instant_debounce_sleep(_delay: float) -> None:
        await _real_asyncio_sleep(0)

    transport = ASGITransport(app=app)
    with patch("wiki.webhook.debounce.asyncio.sleep", side_effect=instant_debounce_sleep):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/v1/hooks/github", content=body, headers=headers)
            assert r.status_code == 202
            assert r.json()["status"] == "queued"
            await _real_asyncio_sleep(0.08)

    updater.update.assert_awaited_once()
    repo, changed_files = updater.update.await_args.args
    assert repo == "acme/widget"
    assert [cf.path for cf in changed_files] == ["pkg/handler.py", "pkg/service.py"]
    assert all(isinstance(cf, ChangedFile) for cf in changed_files)
    assert {cf.status for cf in changed_files} == {"modified"}


@pytest.mark.asyncio
async def test_p3_scheduler_skips_regenerate_when_task_lock_held() -> None:
    """When TaskLock already holds the repo, interval job must not call regenerate_fn."""
    task_lock = TaskLock(timeout_seconds=600)
    assert await task_lock.acquire("busy-repo") is True
    regen = AsyncMock()
    cfg = ScheduleConfig(
        schedule_type="interval",
        interval_hours=1,
        enabled_repositories=["busy-repo"],
    )
    scheduler = WikiScheduler(cfg, task_lock, regen)

    async def fake_sleep(delay: float) -> None:
        await _real_asyncio_sleep(0)

    with patch("wiki.scheduler.wiki_scheduler.asyncio.sleep", side_effect=fake_sleep):
        await scheduler.start()
        await _real_asyncio_sleep(0.15)
        await scheduler.stop()

    regen.assert_not_called()
    await task_lock.release("busy-repo")


@pytest.mark.asyncio
async def test_p3_agent_search_wiki_then_traverse_then_ask() -> None:
    """Simulated agent: search_wiki → traverse_call_chain (same repo / entity) → ask_about_code."""
    repo = "demo-repo"
    wiki_pipeline = AsyncMock()
    wiki_pipeline.search_wiki = AsyncMock(
        return_value={
            "results": [
                {
                    "title": "AuthService",
                    "page_path": "classes/AuthService.md",
                    "score": 0.9,
                }
            ],
            "total": 1,
        },
    )
    graph_port = AsyncMock()
    graph_port.traverse_call_chain = AsyncMock(
        return_value={
            "root": {"name": "AuthService", "type": "Class"},
            "chain": [],
            "total_nodes": 1,
        },
    )
    wiki_pipeline.ask_about_code = AsyncMock(
        return_value={"content": "AuthService delegates to TokenValidator.", "sources": []},
    )

    handler = WikiMCPHandler(pipeline=wiki_pipeline, graph=graph_port)

    search_out = await handler.handle_search_wiki({"repository": repo, "query": "authentication service"})
    assert "error" not in search_out
    top_title = search_out["results"][0]["title"]

    chain_out = await handler.handle_traverse_call_chain(
        {"repository": repo, "node_name": top_title, "direction": "callees"},
    )
    assert chain_out.get("total_nodes") == 1

    ask_out = await handler.handle_ask_about_code(
        {
            "repository": repo,
            "question": f"Summarize impact of {top_title} for callers.",
        },
    )
    assert ask_out.get("content")

    wiki_pipeline.search_wiki.assert_awaited()
    graph_port.traverse_call_chain.assert_awaited_once_with(
        repository=repo,
        node_name="AuthService",
        direction="callees",
        max_depth=3,
    )
    wiki_pipeline.ask_about_code.assert_awaited_once_with(
        repo,
        "Summarize impact of AuthService for callers.",
        None,
        None,
    )


@pytest.mark.asyncio
async def test_p3_pr_impact_pages_drive_search_wiki_queries() -> None:
    """analyze_pr_impact returns wiki paths; follow-up search_wiki queries align with those paths."""
    repo = "indexed-repo"
    wiki_pipeline = AsyncMock()
    wiki_pipeline.search_wiki = AsyncMock(return_value={"results": [], "total": 0})

    graph_port = AsyncMock()
    graph_port.analyze_pr_impact = AsyncMock(
        return_value={
            "affected_pages": [
                {
                    "wiki_page_path": "modules/auth/AuthService",
                    "impact_level": "high",
                    "reason": "direct",
                    "affected_entities": ["AuthService"],
                },
                {
                    "wiki_page_path": "classes/TokenValidator",
                    "impact_level": "medium",
                    "reason": "1-hop",
                    "affected_entities": ["TokenValidator"],
                },
            ],
            "summary": {"high_impact": 1, "medium_impact": 1, "total_affected_pages": 2},
        },
    )

    handler = WikiMCPHandler(pipeline=wiki_pipeline, graph=graph_port)
    impact = await handler.handle_analyze_pr_impact(
        {
            "repository": repo,
            "changed_files": [{"path": "src/Auth.java", "status": "modified"}],
        },
    )
    assert impact["summary"]["total_affected_pages"] == 2
    wiki_paths = [p["wiki_page_path"] for p in impact["affected_pages"]]
    assert wiki_paths == ["modules/auth/AuthService", "classes/TokenValidator"]

    for wp in wiki_paths:
        leaf = wp.split("/")[-1]
        await handler.handle_search_wiki({"repository": repo, "query": leaf})

    assert wiki_pipeline.search_wiki.await_count == 2
    queries = [c.args[1] for c in wiki_pipeline.search_wiki.await_args_list]
    assert set(queries) == {"AuthService", "TokenValidator"}
    graph_port.analyze_pr_impact.assert_awaited_once_with(
        repository=repo,
        changed_files=[{"path": "src/Auth.java", "status": "modified"}],
    )


def test_p3_removed_search_endpoints_return_404() -> None:
    """POST /search and /business/search were fully removed in P3 Track C."""
    app = FastAPI()
    app.include_router(viewer_router)
    client = TestClient(app)

    r1 = client.post("/api/v1/search", json={"query": "hello", "k": 5})
    assert r1.status_code in (404, 405)

    r2 = client.post("/api/v1/business/search", json={"query": "checkout"})
    assert r2.status_code in (404, 405)


def test_p3_llm_config_defaults_track_c(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default LLMConfig disables concept extraction and business flow indexing passes."""
    monkeypatch.delenv("LLM__CONCEPT_EXTRACTION_ENABLED", raising=False)
    monkeypatch.delenv("LLM__BUSINESS_FLOW_ENABLED", raising=False)

    cfg = LLMConfig()
    assert cfg.concept_extraction_enabled is False
    assert cfg.business_flow_enabled is False
