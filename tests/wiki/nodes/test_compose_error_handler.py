from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest


def _pages_from_result(result) -> list[dict]:
    if hasattr(result, "update"):
        return result.update.get("pages", [])
    return result.get("pages", [])


class TestComposeErrorFallbackSignature:
    """Bug 1: error_handler must accept error without default — LangGraph 1.2 injects it."""

    def test_signature_error_param_has_no_default(self):
        from wiki.nodes.compose_error_handler import compose_error_fallback

        sig = inspect.signature(compose_error_fallback)
        error_param = sig.parameters.get("error")
        assert error_param is not None, "compose_error_fallback must have 'error' parameter"
        assert error_param.default is inspect.Parameter.empty, (
            "error param must NOT have a default value (LangGraph won't inject if default exists)"
        )

    def test_no_unknown_compose_failure_in_source(self):
        from wiki.nodes import compose_error_handler

        source = inspect.getsource(compose_error_handler)
        assert "unknown compose failure" not in source, (
            "Must not fall back to 'unknown compose failure' — LangGraph injects real error"
        )


class TestComposeErrorFallbackPathFormat:
    """Auxiliary bug: skeleton pages must use /__domains__/{slug}/_overview format."""

    @pytest.mark.asyncio
    async def test_skeleton_uses_domain_overview_path(self):
        from wiki.nodes.compose_error_handler import compose_error_fallback
        from wiki.path_conventions import domain_overview_path

        state = {
            "pages": [],
            "domain_tree": [
                {
                    "slug": "family-ecosystem",
                    "name": "family-ecosystem",
                    "display_name": "家族生态",
                    "modules": ["FamA", "FamB"],
                },
            ],
        }

        fake_error = MagicMock()
        fake_error.error = TimeoutError("test timeout")

        result = await compose_error_fallback(state, error=fake_error)
        pages = _pages_from_result(result)

        skeleton = next((p for p in pages if "family" in p.get("path", "")), None)
        assert skeleton is not None, "Should produce skeleton for family-ecosystem"

        expected_path = domain_overview_path("family-ecosystem")
        assert skeleton["path"] == expected_path, (
            f"Expected path '{expected_path}', got '{skeleton['path']}'. "
            "Must use domain_overview_path(), not '{slug}/index'"
        )
        assert skeleton["path"].startswith("/__domains__/")
        assert skeleton["path"].endswith("/_overview")


class TestComposeErrorFallbackTraversal:
    """Auxiliary bug: traversal must be recursive, not just top-level domains."""

    @pytest.mark.asyncio
    async def test_nested_domains_produce_skeletons(self):
        from wiki.nodes.compose_error_handler import compose_error_fallback

        state = {
            "pages": [],
            "domain_tree": [
                {
                    "slug": "social",
                    "name": "social",
                    "display_name": "社交",
                    "modules": [],
                    "children": [
                        {
                            "slug": "social-chat",
                            "name": "social-chat",
                            "display_name": "社交聊天",
                            "modules": ["ChatA", "ChatB"],
                        },
                    ],
                },
            ],
        }

        fake_error = MagicMock()
        fake_error.error = TimeoutError("nested test")

        result = await compose_error_fallback(state, error=fake_error)
        pages = _pages_from_result(result)

        paths = [p["path"] for p in pages]
        assert any("social-chat" in p for p in paths), (
            "Sub-domain social-chat must get a skeleton page"
        )


class TestComposeErrorFallbackNodeErrorExtraction:
    """Real exception must be read from NodeError .error attribute."""

    @pytest.mark.asyncio
    async def test_extracts_inner_exception_from_node_error_wrapper(self):
        from wiki.nodes.compose_error_handler import compose_error_fallback

        state = {
            "pages": [],
            "domain_tree": [
                {"slug": "auth", "display_name": "认证", "modules": []},
            ],
        }

        inner = RuntimeError("agent exploded")
        fake_error = MagicMock()
        fake_error.error = inner

        result = await compose_error_fallback(state, error=fake_error)
        pages = _pages_from_result(result)

        assert len(pages) == 1
        assert "RuntimeError" in pages[0]["content"]
        assert "agent exploded" in pages[0]["content"]
        assert pages[0]["metadata"]["error_type"] == "RuntimeError"
        assert "agent exploded" in pages[0]["metadata"]["error_msg"]


class TestComposeErrorFallbackCommand:
    """Handler routes to quality_gate via Command."""

    @pytest.mark.asyncio
    async def test_returns_command_goto_quality_gate(self):
        from langgraph.types import Command

        from wiki.nodes.compose_error_handler import compose_error_fallback

        state = {
            "pages": [],
            "domain_tree": [{"slug": "x", "display_name": "X", "modules": []}],
        }
        fake_error = MagicMock()
        fake_error.error = TimeoutError("t")

        result = await compose_error_fallback(state, error=fake_error)

        assert isinstance(result, Command)
        assert result.goto == "quality_gate"


class TestComposeErrorFallbackBehavior:
    """Integration-style behavior tests."""

    @pytest.mark.asyncio
    async def test_produces_skeletons_for_missing_domains(self):
        from wiki.nodes.compose_error_handler import compose_error_fallback
        from wiki.path_conventions import domain_overview_path

        state = {
            "pages": [],
            "domain_tree": [
                {"slug": "family-ecosystem", "display_name": "家族生态", "modules": ["FamilyService"]},
                {"slug": "auth-system", "display_name": "认证系统", "modules": ["AuthController"]},
            ],
        }
        fake_error = MagicMock()
        fake_error.error = TimeoutError("agent stalled")

        result = await compose_error_fallback(state, error=fake_error)
        pages = _pages_from_result(result)

        assert len(pages) == 2
        paths = {p["path"] for p in pages}
        assert domain_overview_path("family-ecosystem") in paths
        assert domain_overview_path("auth-system") in paths

        family_page = next(p for p in pages if "family-ecosystem" in p["path"])
        assert family_page["metadata"]["generation_mode"] == "error_fallback"
        assert family_page["__degraded__"] is True
        assert "家族生态" in family_page["content"]
        assert "TimeoutError" in family_page["content"]

    @pytest.mark.asyncio
    async def test_skips_domains_that_already_have_pages(self):
        from wiki.nodes.compose_error_handler import compose_error_fallback
        from wiki.path_conventions import domain_overview_path

        existing_path = domain_overview_path("family-ecosystem")
        state = {
            "pages": [{"path": existing_path, "page_type": "domain_overview", "content": "# Real"}],
            "domain_tree": [
                {"slug": "family-ecosystem", "display_name": "家族生态", "modules": []},
                {"slug": "auth-system", "display_name": "认证系统", "modules": []},
            ],
        }
        fake_error = MagicMock()
        fake_error.error = TimeoutError()

        result = await compose_error_fallback(state, error=fake_error)
        pages = _pages_from_result(result)

        new_pages = [p for p in pages if p.get("__degraded__")]
        assert len(new_pages) == 1
        assert "auth-system" in new_pages[0]["path"]

    @pytest.mark.asyncio
    async def test_empty_domain_tree_produces_no_new_skeletons(self):
        from wiki.nodes.compose_error_handler import compose_error_fallback

        state = {"pages": [], "domain_tree": []}
        fake_error = MagicMock()
        fake_error.error = TimeoutError()

        result = await compose_error_fallback(state, error=fake_error)
        pages = _pages_from_result(result)

        assert pages == []
