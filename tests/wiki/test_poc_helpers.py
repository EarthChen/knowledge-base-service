"""Tests for POC helper functions."""
import pytest
import sys
from pathlib import Path

# scripts/ is not a package, add to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


class TestBuildStructuredBaseline:
    def test_separates_entry_modules(self):
        from poc_agent_wiki import build_structured_baseline

        modules = ["UserController", "UserService", "UserRepository", "PaymentHandler"]
        result = build_structured_baseline("user-management", modules, {})
        assert "入口模块" in result
        assert "UserController" in result
        assert "PaymentHandler" in result

    def test_includes_domain_name(self):
        from poc_agent_wiki import build_structured_baseline

        result = build_structured_baseline("payment", ["PayService"], {})
        assert "payment" in result

    def test_includes_module_summaries(self):
        from poc_agent_wiki import build_structured_baseline

        summaries = {"UserService": "Handles user CRUD operations"}
        result = build_structured_baseline("user", ["UserService"], summaries)
        assert "Handles user CRUD" in result


class TestSelectPocDomain:
    def test_selects_medium_domain(self):
        from poc_agent_wiki import select_poc_domain

        domains = {
            "tiny": ["A", "B"],
            "medium": ["C", "D", "E", "F", "G", "H", "I"],
            "huge": [f"M{i}" for i in range(50)],
        }
        name, modules = select_poc_domain(domains)
        assert name == "medium"
        assert len(modules) == 7

    def test_prefers_domain_with_controller(self):
        from poc_agent_wiki import select_poc_domain

        domains = {
            "no-entry": ["ServiceA", "ServiceB", "RepoA", "RepoB", "UtilA"],
            "has-entry": ["FooController", "FooService", "FooRepo", "FooDTO", "FooMapper"],
        }
        name, _ = select_poc_domain(domains)
        assert name == "has-entry"
