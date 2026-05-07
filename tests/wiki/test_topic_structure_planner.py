"""Tests for TopicBasedStructurePlanner."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from wiki.topic_structure_planner import TopicBasedStructurePlanner, TopicPage


@pytest.fixture
def llm() -> AsyncMock:
    return AsyncMock(spec=["generate"])


@pytest.fixture
def planner(llm: AsyncMock) -> TopicBasedStructurePlanner:
    return TopicBasedStructurePlanner(llm)


DOMAIN_MAPPING = {
    "UserManagement": [("repo-a", "UserService"), ("repo-a", "AuthModule")],
    "OrderSystem": [("repo-b", "OrderController"), ("repo-b", "PaymentGateway")],
    "Infrastructure": [("repo-a", "Utils"), ("repo-b", "Config")],
}

MODULE_METADATA = {
    ("repo-a", "UserService"): {"summary": "Handles user CRUD"},
    ("repo-a", "AuthModule"): {"summary": "Authentication logic"},
    ("repo-b", "OrderController"): {"summary": "Order REST API"},
    ("repo-b", "PaymentGateway"): {"summary": "Payment processing"},
    ("repo-a", "Utils"): {"summary": "Utility functions"},
    ("repo-b", "Config"): {"summary": "Configuration management"},
}

IMPORTANCE_TIERS = {
    "UserService": "core",
    "AuthModule": "standard",
    "OrderController": "core",
    "PaymentGateway": "standard",
    "Utils": "skeleton",
    "Config": "skeleton",
}


def _valid_llm_response() -> str:
    return json.dumps([
        {
            "title": "User & Authentication",
            "description": "User management and authentication system",
            "modules": [["repo-a", "UserService"], ["repo-a", "AuthModule"]],
            "sub_topics": [
                {
                    "title": "User CRUD",
                    "description": "User create, read, update, delete operations",
                    "modules": [["repo-a", "UserService"]],
                },
                {
                    "title": "Auth Flow",
                    "description": "Login and token management",
                    "modules": [["repo-a", "AuthModule"]],
                },
            ],
        },
        {
            "title": "Order & Payment",
            "description": "E-commerce order processing",
            "modules": [["repo-b", "OrderController"], ["repo-b", "PaymentGateway"]],
            "sub_topics": [],
        },
        {
            "title": "Infrastructure",
            "description": "Shared utilities and configuration",
            "modules": [["repo-a", "Utils"], ["repo-b", "Config"]],
            "sub_topics": [],
        },
    ])


@pytest.mark.asyncio
async def test_plan_returns_topic_pages(planner: TopicBasedStructurePlanner, llm: AsyncMock) -> None:
    llm.generate = AsyncMock(return_value=_valid_llm_response())
    pages = await planner.plan(DOMAIN_MAPPING, MODULE_METADATA, IMPORTANCE_TIERS)

    assert isinstance(pages, list)
    assert len(pages) == 3
    assert all(isinstance(p, TopicPage) for p in pages)
    assert pages[0].title == "User & Authentication"
    assert len(pages[0].sub_topics) == 2


@pytest.mark.asyncio
async def test_plan_assigns_all_modules(planner: TopicBasedStructurePlanner, llm: AsyncMock) -> None:
    llm.generate = AsyncMock(return_value=_valid_llm_response())
    pages = await planner.plan(DOMAIN_MAPPING, MODULE_METADATA, IMPORTANCE_TIERS)

    all_modules: set[tuple[str, str]] = set()
    for p in pages:
        all_modules.update(p.covered_modules)
        for sp in p.sub_topics:
            all_modules.update(sp.covered_modules)

    expected = {
        ("repo-a", "UserService"), ("repo-a", "AuthModule"),
        ("repo-b", "OrderController"), ("repo-b", "PaymentGateway"),
        ("repo-a", "Utils"), ("repo-b", "Config"),
    }
    assert all_modules == expected


@pytest.mark.asyncio
async def test_fallback_on_invalid_json(planner: TopicBasedStructurePlanner, llm: AsyncMock) -> None:
    llm.generate = AsyncMock(return_value="not valid json at all{{")
    pages = await planner.plan(DOMAIN_MAPPING, MODULE_METADATA, IMPORTANCE_TIERS)

    assert isinstance(pages, list)
    assert len(pages) > 0
    all_modules: set[tuple[str, str]] = set()
    for p in pages:
        all_modules.update(p.covered_modules)
    assert len(all_modules) >= len(DOMAIN_MAPPING)


@pytest.mark.asyncio
async def test_fallback_on_llm_exception(planner: TopicBasedStructurePlanner, llm: AsyncMock) -> None:
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
    pages = await planner.plan(DOMAIN_MAPPING, MODULE_METADATA, IMPORTANCE_TIERS)

    assert isinstance(pages, list)
    assert len(pages) > 0


@pytest.mark.asyncio
async def test_target_pages_passed_to_prompt(planner: TopicBasedStructurePlanner, llm: AsyncMock) -> None:
    llm.generate = AsyncMock(return_value=_valid_llm_response())
    await planner.plan(DOMAIN_MAPPING, MODULE_METADATA, IMPORTANCE_TIERS, target_pages=(20, 40))

    prompt = llm.generate.call_args[0][0]
    assert "20" in prompt and "40" in prompt
