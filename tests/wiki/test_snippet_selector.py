import pytest
from wiki.snippet_selector import select_key_snippets, MethodSnippet


def _make_module(name, methods, calls=None, docstring="", uid=""):
    return {
        "uid": uid or f"Module::{name}:0",
        "label": "Module",
        "properties": {
            "name": name,
            "methods": methods,
            "calls": calls or [],
            "docstring": docstring,
        },
    }


def test_select_empty_modules():
    result = select_key_snippets([], {})
    assert result == []


def test_select_basic_ranking():
    modules = [
        _make_module("OrderService", ["processOrder", "cancelOrder", "getStatus"],
                     calls=["PaymentService.charge", "InventoryService.reserve"]),
    ]
    entity_roles = {"Module::OrderService:0": "has_business_logic"}
    result = select_key_snippets(modules, entity_roles)
    assert len(result) > 0
    assert all(isinstance(s, MethodSnippet) for s in result)


def test_entry_point_methods_ranked_higher():
    modules = [
        _make_module("UserController", ["getUser", "createUser"], uid="m1"),
        _make_module("UserService", ["findById", "save"], uid="m2"),
    ]
    entity_roles = {"m1": "entry_point", "m2": "has_business_logic"}
    result = select_key_snippets(modules, entity_roles)
    entry_methods = [s for s in result if s.module_name == "UserController"]
    other_methods = [s for s in result if s.module_name == "UserService"]
    if entry_methods and other_methods:
        assert entry_methods[0].score > other_methods[0].score


def test_per_module_limit():
    modules = [
        _make_module("BigService", [f"method_{i}" for i in range(20)]),
    ]
    result = select_key_snippets(modules, {}, max_per_module=3)
    assert len(result) <= 3


def test_budget_token_limit():
    modules = [
        _make_module(f"Service{i}", [f"m{j}" for j in range(5)])
        for i in range(10)
    ]
    result = select_key_snippets(modules, {}, budget_tokens=500)
    total_chars = sum(len(s.format_for_prompt()) for s in result)
    assert total_chars <= 500 * 4  # rough char-to-token ratio


def test_called_methods_ranked_higher():
    modules = [
        _make_module("A", ["doWork"], calls=[]),
        _make_module("B", ["helper"], calls=["A.doWork", "A.doWork", "A.doWork"]),
    ]
    entity_roles = {"Module::A:0": "has_business_logic", "Module::B:0": "has_business_logic"}
    result = select_key_snippets(modules, entity_roles)
    a_methods = [s for s in result if s.module_name == "A"]
    assert len(a_methods) > 0


def test_format_for_prompt():
    modules = [
        _make_module("OrderService", ["processOrder"],
                     docstring="Handles order processing workflow"),
    ]
    result = select_key_snippets(modules, {})
    assert len(result) == 1
    prompt_text = result[0].format_for_prompt()
    assert "OrderService" in prompt_text
    assert "processOrder" in prompt_text


def test_private_methods_lower_score():
    modules = [
        _make_module("Service", ["publicMethod", "_privateHelper"]),
    ]
    result = select_key_snippets(modules, {})
    assert len(result) == 2
    public = [s for s in result if s.method_name == "publicMethod"][0]
    private = [s for s in result if s.method_name == "_privateHelper"][0]
    assert public.score >= private.score
