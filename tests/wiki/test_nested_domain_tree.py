"""tests/wiki/test_nested_domain_tree.py"""

import json

import pytest

from wiki.dependency_graph import (
    DomainNode,
    HierarchicalDecomposer,
    ModuleGraph,
    ModuleInfo,
)


class _MockLLM:
    def __init__(self, response: str):
        self._response = response

    async def generate(self, prompt: str, system: str = "") -> str:
        return self._response


class TestHierarchicalDecomposer:
    @pytest.mark.asyncio
    async def test_single_pass_returns_domain_tree(self):
        llm_response = json.dumps(
            {
                "domains": [
                    {
                        "name": "User Management",
                        "description": "User related",
                        "modules": ["UserController", "UserService"],
                        "children": [],
                    },
                    {
                        "name": "Data Access",
                        "description": "DB layer",
                        "modules": ["UserRepository"],
                        "children": [],
                    },
                ]
            }
        )
        mock_llm = _MockLLM(llm_response)
        modules = [
            ModuleInfo(name="UserController", path="uc.py", uid="1", semantic_roles=["http_controller"]),
            ModuleInfo(name="UserService", path="us.py", uid="2"),
            ModuleInfo(name="UserRepository", path="ur.py", uid="3"),
        ]
        graph = ModuleGraph(modules=modules, edges=[], entry_points=["UserController"])
        decomposer = HierarchicalDecomposer(llm=mock_llm, max_depth=3, min_modules_for_nesting=2)
        result = await decomposer.decompose(modules, graph)
        # Single-module "Data Access" merges into the most similar large sibling
        assert len(result) == 1
        assert result[0].name == "user-management"
        assert "UserController" in result[0].modules
        assert "UserRepository" in result[0].modules

    @pytest.mark.asyncio
    async def test_json_parse_failure_returns_uncategorized(self):
        mock_llm = _MockLLM("not valid json at all")
        modules = [ModuleInfo(name="A", path="a.py", uid="1")]
        graph = ModuleGraph(modules=modules, edges=[], entry_points=[])
        decomposer = HierarchicalDecomposer(llm=mock_llm)
        result = await decomposer.decompose(modules, graph)
        assert len(result) == 1
        assert result[0].name == "Uncategorized"
        assert "A" in result[0].modules

    @pytest.mark.asyncio
    async def test_nested_children_parsed(self):
        llm_response = json.dumps(
            {
                "domains": [
                    {
                        "name": "Platform",
                        "modules": [],
                        "children": [
                            {"name": "Auth", "modules": ["AuthService"], "children": []},
                            {"name": "User", "modules": ["UserService"], "children": []},
                        ],
                    }
                ]
            }
        )
        mock_llm = _MockLLM(llm_response)
        modules = [
            ModuleInfo(name="AuthService", path="a.py", uid="1"),
            ModuleInfo(name="UserService", path="u.py", uid="2"),
        ]
        graph = ModuleGraph(modules=modules, edges=[], entry_points=[])
        decomposer = HierarchicalDecomposer(llm=mock_llm)
        result = await decomposer.decompose(modules, graph)
        assert len(result) == 1
        assert result[0].name == "platform"
        assert len(result[0].children) == 2

    @pytest.mark.asyncio
    async def test_batch_strategy_for_large_module_set(self):
        llm_response = json.dumps({"domains": [{"name": "All", "modules": [], "children": []}]})
        mock_llm = _MockLLM(llm_response)
        modules = [ModuleInfo(name=f"m{i}", path=f"m{i}.py", uid=str(i)) for i in range(300)]
        graph = ModuleGraph(modules=modules, edges=[], entry_points=[])
        decomposer = HierarchicalDecomposer(llm=mock_llm, max_tokens_per_batch=10_000)
        result = await decomposer.decompose(modules, graph)
        assert isinstance(result, list)


class TestDomainNode:
    def test_domain_node_creation(self):
        node = DomainNode(
            name="Auth",
            description="Authentication domain",
            modules=["AuthService", "TokenService"],
            children=[DomainNode(name="OAuth", modules=["OAuthProvider"])],
        )
        assert node.name == "Auth"
        assert len(node.children) == 1
        assert node.children[0].name == "OAuth"
