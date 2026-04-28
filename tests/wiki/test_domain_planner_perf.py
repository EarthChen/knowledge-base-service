"""Performance-oriented tests: streaming LLM bridge, sub-batching, parallel cross-repo classification."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from llm.base_provider import LLMPortBridge
from store.schema import GraphNode, NodeLabel
from wiki.business_domain_planner import BusinessDomainPlanner
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner


def _make_module(name: str, summary: str = "", repo: str = "test-repo") -> GraphNode:
    return GraphNode(
        uid=f"Module:{repo}:{name}",
        label=NodeLabel.MODULE,
        properties={"name": name, "business_summary": summary, "path": name},
    )


def _make_cross_module(name: str, repo_id: str, summary: str = "") -> GraphNode:
    props: dict[str, str] = {"name": name, "path": name}
    if summary:
        props["business_summary"] = summary
    return GraphNode(
        uid=f"Module:{repo_id}:{name}",
        label=NodeLabel.MODULE,
        properties=props,
    )


class _ChunkedStreamProvider:
    """Provider with complete_stream yielding chunks; used by LLMPortBridge tests."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self.complete_stream_calls = 0

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def max_context_tokens(self) -> int:
        return 128000

    async def complete(self, messages: list[dict[str, str]], **kwargs: object) -> str:
        raise AssertionError("non-streaming complete should not be used in this test")

    async def complete_json(self, messages: list[dict[str, str]], schema: dict, **kwargs: object) -> dict:
        raise NotImplementedError

    async def complete_stream(self, messages: list[dict[str, str]], **kwargs: object) -> AsyncIterator[str]:
        self.complete_stream_calls += 1
        for c in self._chunks:
            yield c

    async def close(self) -> None:
        pass


class _NoStreamProvider:
    """Provider without complete_stream — bridge should fall back to generate/complete."""

    async def complete(self, messages: list[dict[str, str]], **kwargs: object) -> str:
        return "merged"

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_generate_stream_collects_all_chunks() -> None:
    provider = _ChunkedStreamProvider(["{", '"d": ["a", "b"]', "}"])
    bridge = LLMPortBridge(provider)  # type: ignore[arg-type]
    out = await bridge.generate_stream("p", "sys")
    assert out == '{"d": ["a", "b"]}'
    assert provider.complete_stream_calls == 1


@pytest.mark.asyncio
async def test_generate_stream_fallback_to_generate() -> None:
    provider = _NoStreamProvider()
    bridge = LLMPortBridge(provider)  # type: ignore[arg-type]
    out = await bridge.generate_stream("hello", "")
    assert out == "merged"


@pytest.mark.asyncio
async def test_business_domain_planner_sub_batching() -> None:
    llm = AsyncMock()
    calls: list[str] = []

    async def generate(prompt: str, system: str = "") -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps({"A": [f"mod-{i:03d}" for i in range(100)]})
        if len(calls) == 2:
            return json.dumps({"B": [f"mod-{i:03d}" for i in range(100, 200)]})
        return "{}"

    llm.generate = AsyncMock(side_effect=generate)
    modules = [_make_module(f"mod-{i:03d}") for i in range(200)]
    planner = BusinessDomainPlanner(llm, sub_batch_size=100)
    result = await planner.classify("big-repo", modules)
    assert len(calls) == 2
    assert "A" in result and "B" in result
    assert len(result["A"]) == 100
    assert len(result["B"]) == 100


@pytest.mark.asyncio
async def test_business_domain_planner_streaming_preferred() -> None:
    class StreamLLM:
        async def generate_stream(self, prompt: str, system: str = "", **_kwargs: object) -> str:
            return json.dumps({"X": ["only"]})

        async def generate(self, prompt: str, system: str = "") -> str:
            raise AssertionError("generate should not be called when generate_stream exists")

    planner = BusinessDomainPlanner(StreamLLM(), sub_batch_size=500)
    result = await planner.classify("r1", [_make_module("only")])
    assert result["X"] == ["only"]


@pytest.mark.asyncio
async def test_cross_repo_parallel_classification() -> None:
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def generate(prompt: str, system: str = "") -> str:
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.08)
        finally:
            async with lock:
                active -= 1
        if "Per-repository domains" in prompt or "Merge these" in prompt:
            return json.dumps(
                {
                    "D": [["a", "m"], ["b", "m"], ["c", "m"]],
                }
            )
        return json.dumps({"D": ["m"]})

    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=generate)
    all_modules = {
        "a": [_make_cross_module("m", "a")],
        "b": [_make_cross_module("m", "b")],
        "c": [_make_cross_module("m", "c")],
    }
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=1, max_concurrency=3)
    await planner.classify("biz-par", all_modules)
    assert max_active >= 3


@pytest.mark.asyncio
async def test_cross_repo_per_repo_timeout() -> None:
    async def generate(prompt: str, system: str = "") -> str:
        if "Repository: slow-repo" in prompt:
            await asyncio.sleep(10.0)
            return json.dumps({"Z": ["x"]})
        if "Repository: fast-repo" in prompt:
            return json.dumps({"Z": ["y"]})
        if "Merge these" in prompt or "Per-repository domains" in prompt:
            return json.dumps(
                {
                    "Z": [["fast-repo", "y"]],
                    "__infrastructure__": [["slow-repo", "x"]],
                }
            )
        return json.dumps({"Z": []})

    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=generate)
    all_modules = {
        "slow-repo": [_make_cross_module("x", "slow-repo")],
        "fast-repo": [_make_cross_module("y", "fast-repo")],
    }
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=1, max_concurrency=2, classify_timeout=1)
    result = await planner.classify("biz-to", all_modules)
    infra_pairs = set(result.get("__infrastructure__", []))
    assert ("slow-repo", "x") in infra_pairs
    assert ("fast-repo", "y") in result.get("Z", [])


@pytest.mark.asyncio
async def test_cross_repo_classification_cache() -> None:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=json.dumps({"C": [["r1", "a"]]}),
    )
    all_modules = {"r1": [_make_cross_module("a", "r1", summary="s")]}
    planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=100, cache_ttl=3600)
    r1 = await planner.classify("biz-cache", all_modules)
    r2 = await planner.classify("biz-cache", all_modules)
    assert r1 == r2
    assert llm.generate.await_count == 1
