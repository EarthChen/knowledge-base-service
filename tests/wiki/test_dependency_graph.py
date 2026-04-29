"""Tests for wiki.dependency_graph — module dependency graph and representation."""

from __future__ import annotations

from wiki.dependency_graph import ModuleDependencyGraph, ModuleGraph, ModuleInfo, ModuleEdge, ModuleReprBuilder, TokenBudget


class TestModuleDependencyGraph:
    def test_identify_entry_points_zero_indegree(self):
        graph_builder = ModuleDependencyGraph.__new__(ModuleDependencyGraph)
        modules = [
            ModuleInfo(name="Controller", path="c.py", uid="1"),
            ModuleInfo(name="Service", path="s.py", uid="2"),
            ModuleInfo(name="Repo", path="r.py", uid="3"),
        ]
        edges = [
            ModuleEdge(source="Controller", target="Service", edge_type="CALLS"),
            ModuleEdge(source="Service", target="Repo", edge_type="CALLS"),
        ]
        entry_points = graph_builder._identify_entry_points(modules, edges)
        assert "Controller" in entry_points
        assert "Service" not in entry_points

    def test_rpc_provider_is_entry_point(self):
        graph_builder = ModuleDependencyGraph.__new__(ModuleDependencyGraph)
        modules = [
            ModuleInfo(name="RpcImpl", path="rpc.py", uid="1", semantic_roles=["rpc_provider"]),
            ModuleInfo(name="Helper", path="h.py", uid="2"),
        ]
        entry_points = graph_builder._identify_entry_points(modules, [])
        assert "RpcImpl" in entry_points

    def test_name_hint_controller(self):
        graph_builder = ModuleDependencyGraph.__new__(ModuleDependencyGraph)
        modules = [ModuleInfo(name="UserController", path="uc.py", uid="1")]
        entry_points = graph_builder._identify_entry_points(modules, [])
        assert "UserController" in entry_points


class TestModuleReprBuilder:
    def test_p0_always_included(self):
        module = ModuleInfo(
            name="UserService",
            path="us.py",
            uid="1",
            semantic_roles=["service"],
            calls_out=["OrderService", "PaymentService"],
            called_by=["UserController"],
        )
        builder = ModuleReprBuilder()
        budget = TokenBudget(total=100, used=0)
        text = builder.build(module, budget)
        assert "UserService" in text
        assert "service" in text
        assert "OrderService" in text

    def test_rpc_interface_injected(self):
        module = ModuleInfo(
            name="UserProvider",
            path="up.py",
            uid="2",
            semantic_roles=["rpc_provider"],
            properties={"rpc_interface": "com.example.api.UserService"},
        )
        builder = ModuleReprBuilder()
        budget = TokenBudget(total=200, used=0)
        text = builder.build(module, budget)
        assert "com.example.api.UserService" in text

    def test_p1_included_when_budget_allows(self):
        module = ModuleInfo(name="Svc", path="s.py", uid="3", summary="Important service")
        builder = ModuleReprBuilder()
        budget = TokenBudget(total=500, used=0)
        text = builder.build(module, budget)
        assert "Important service" in text

    def test_p1_excluded_when_budget_tight(self):
        module = ModuleInfo(name="Svc", path="s.py", uid="3", summary="Important service")
        builder = ModuleReprBuilder()
        budget = TokenBudget(total=100, used=50)
        text = builder.build(module, budget)
        assert "Important service" not in text
