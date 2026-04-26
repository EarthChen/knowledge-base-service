import asyncio
import pytest
from api.request_context import (
    get_current_business,
    get_current_request_id,
    reset_current_business,
    reset_current_request_id,
    set_current_business,
    set_current_request_id,
)


def test_default_business_id():
    assert get_current_business() == "default"


def test_default_request_id():
    assert get_current_request_id() == ""


def test_set_and_get_business():
    token = set_current_business("acme")
    assert get_current_business() == "acme"
    reset_current_business(token)
    assert get_current_business() == "default"


def test_set_and_get_request_id():
    token = set_current_request_id("req-42")
    assert get_current_request_id() == "req-42"
    reset_current_request_id(token)
    assert get_current_request_id() == ""


@pytest.mark.asyncio
async def test_context_isolated_across_tasks():
    """Concurrent tasks should not see each other's context."""
    results = []

    async def worker(biz: str):
        set_current_business(biz)
        await asyncio.sleep(0.01)
        results.append(get_current_business())

    await asyncio.gather(worker("alpha"), worker("beta"))
    assert set(results) == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_request_id_isolated_across_tasks():
    """Concurrent tasks should not see each other's request_id."""
    results = []

    async def worker(rid: str):
        set_current_request_id(rid)
        await asyncio.sleep(0.01)
        results.append(get_current_request_id())

    await asyncio.gather(worker("rid-a"), worker("rid-b"))
    assert set(results) == {"rid-a", "rid-b"}
