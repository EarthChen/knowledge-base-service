"""Tests for @function_tool decorator (Layer 2a)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.agents.context import RunContext, WikiDeps


class TestFunctionToolDecorator:
    def test_decorator_attaches_tool_def(self):
        from wiki.agents.tool_decorator import function_tool

        @function_tool(tier=2)
        async def my_tool(name: str, limit: int = 10) -> dict:
            """Search for entities by name."""
            return {"results": []}

        assert hasattr(my_tool, "_tool_def")
        td = my_tool._tool_def
        assert td.name == "my_tool"
        assert td.tier == 2
        assert "Search for entities" in td.description

    def test_custom_name_and_description(self):
        from wiki.agents.tool_decorator import function_tool

        @function_tool(name="custom_name", description="Custom desc", tier=3)
        async def some_func(query: str) -> dict:
            """This docstring is ignored."""
            return {}

        td = some_func._tool_def
        assert td.name == "custom_name"
        assert td.description == "Custom desc"
        assert td.tier == 3

    def test_parameters_schema_inferred(self):
        from wiki.agents.tool_decorator import function_tool

        @function_tool()
        async def search(keyword: str, limit: int = 5, exact: bool = False) -> dict:
            """Search entities."""
            return {}

        params = search._tool_def.parameters
        assert params["type"] == "object"
        assert "keyword" in params["properties"]
        assert "limit" in params["properties"]
        assert "exact" in params["properties"]
        assert "keyword" in params["required"]
        assert "limit" not in params["required"]
        assert "exact" not in params["required"]

    def test_skips_self_and_ctx_params(self):
        from wiki.agents.tool_decorator import function_tool

        class FakeAgent:
            @function_tool()
            async def query_detail(self, name: str, ctx: RunContext) -> dict:
                """Query detail."""
                return {}

        params = FakeAgent.query_detail._tool_def.parameters
        assert "self" not in params["properties"]
        assert "ctx" not in params["properties"]
        assert "name" in params["properties"]
        assert params["required"] == ["name"]

    def test_type_to_json_schema_basic_types(self):
        from wiki.agents.tool_decorator import function_tool

        @function_tool()
        async def typed_tool(
            s: str, i: int, f: float, b: bool, items: list[str] = None
        ) -> dict:
            """Typed."""
            return {}

        props = typed_tool._tool_def.parameters["properties"]
        assert props["s"]["type"] == "string"
        assert props["i"]["type"] == "integer"
        assert props["f"]["type"] == "number"
        assert props["b"]["type"] == "boolean"
        assert props["items"]["type"] == "array"


class TestFunctionToolHandler:
    @pytest.mark.asyncio
    async def test_handler_unpacks_args(self):
        """The decorated function should be callable with (args_dict, ctx)."""
        from wiki.agents.tool_decorator import function_tool

        @function_tool()
        async def add(a: int, b: int) -> dict:
            """Add two numbers."""
            return {"sum": a + b}

        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))
        result = await add._tool_def.handler({"a": 3, "b": 4}, ctx)
        assert result == {"sum": 7}

    @pytest.mark.asyncio
    async def test_handler_works_without_ctx(self):
        """Handler should also work when called without ctx (legacy path)."""
        from wiki.agents.tool_decorator import function_tool

        @function_tool()
        async def greet(name: str) -> dict:
            """Greet."""
            return {"greeting": f"Hello {name}"}

        result = await greet._tool_def.handler({"name": "World"})
        assert result == {"greeting": "Hello World"}

    @pytest.mark.asyncio
    async def test_method_handler_via_collect_tools(self):
        """Decorated methods receive self correctly when collected."""
        from wiki.agents.tool_decorator import function_tool, collect_tools

        class MyAgent:
            def __init__(self):
                self.data = "agent_data"

            @function_tool()
            async def get_data(self, key: str) -> dict:
                """Get data."""
                return {"key": key, "data": self.data}

        agent = MyAgent()
        tools = collect_tools(agent)
        assert len(tools) == 1
        result = await tools[0].handler({"key": "x"})
        assert result == {"key": "x", "data": "agent_data"}


class TestCtxInjection:
    @pytest.mark.asyncio
    async def test_function_tool_passes_ctx_to_handler(self):
        """When function has ctx param, decorator passes ctx through."""
        from wiki.agents.tool_decorator import function_tool

        received: list = []

        @function_tool()
        async def with_ctx(name: str, ctx: RunContext) -> dict:
            """Tool with ctx."""
            received.append(ctx)
            return {"name": name, "biz": ctx.deps.business_id}

        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock(), business_id="b1"))
        result = await with_ctx._tool_def.handler({"name": "test"}, ctx)
        assert result == {"name": "test", "biz": "b1"}
        assert received[0] is ctx

    @pytest.mark.asyncio
    async def test_function_tool_no_ctx_still_works(self):
        """When function has no ctx param, ctx is not injected."""
        from wiki.agents.tool_decorator import function_tool

        @function_tool()
        async def no_ctx(name: str) -> dict:
            """No ctx."""
            return {"name": name}

        ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))
        result = await no_ctx._tool_def.handler({"name": "x"}, ctx)
        assert result == {"name": "x"}

    @pytest.mark.asyncio
    async def test_collect_tools_passes_ctx(self):
        """collect_tools bound handlers should inject ctx when method accepts it."""
        from wiki.agents.tool_decorator import function_tool, collect_tools

        class Agent:
            @function_tool()
            async def with_ctx(self, q: str, ctx: RunContext) -> dict:
                """With ctx."""
                return {"q": q, "store": ctx.deps.graph_store}

        agent = Agent()
        tools = collect_tools(agent)
        ctx = RunContext(deps=WikiDeps(graph_store="gs_mock"))
        result = await tools[0].handler({"q": "hi"}, ctx)
        assert result == {"q": "hi", "store": "gs_mock"}


class TestAutoRegistration:
    def test_collect_decorated_tools(self):
        """collect_tools should find all @function_tool decorated methods."""
        from wiki.agents.tool_decorator import function_tool, collect_tools

        class MyAgent:
            @function_tool(tier=1)
            async def tool_a(self, name: str) -> dict:
                """Tool A."""
                return {}

            @function_tool(tier=2)
            async def tool_b(self, query: str, limit: int = 10) -> dict:
                """Tool B."""
                return {}

            async def not_a_tool(self):
                pass

        agent = MyAgent()
        tools = collect_tools(agent)
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"tool_a", "tool_b"}
