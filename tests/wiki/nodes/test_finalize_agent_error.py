from __future__ import annotations

import pytest


class TestFinalizeAgentErrorExemption:
    """Verify that agent_error pages are NOT hard-rejected by finalize."""

    def _build_page(self, *, gen_mode: str = "agent_error", content_len: int = 20) -> dict:
        """Build a minimal page dict that would normally trigger shell_domain_rejected."""
        return {
            "page_type": "domain_overview",
            "path": "test-domain/index",
            "title": "Test Domain",
            "content": "x" * content_len,
            "metadata": {"generation_mode": gen_mode},
        }

    @pytest.mark.asyncio
    async def test_agent_error_page_not_rejected(self):
        """Page with generation_mode=agent_error should not be hard-rejected."""
        from wiki.nodes.finalize import finalize_node

        page = self._build_page(gen_mode="agent_error", content_len=10)
        state = {
            "pages": [page],
            "repo_id": "test-repo",
            "config": {"content_language": "zh"},
        }
        result = await finalize_node(state)
        pages = result.get("pages", [])
        # The page must still exist and not be rejected
        assert len(pages) >= 1
        kept = [p for p in pages if p.get("path") == "test-domain/index"]
        assert len(kept) == 1
        assert kept[0].get("__rejected__") is not True
        assert kept[0].get("__degraded__") is True

    @pytest.mark.asyncio
    async def test_error_fallback_page_not_rejected(self):
        """Page with generation_mode=error_fallback should not be hard-rejected."""
        from wiki.nodes.finalize import finalize_node

        page = self._build_page(gen_mode="error_fallback", content_len=10)
        state = {
            "pages": [page],
            "repo_id": "test-repo",
            "config": {"content_language": "zh"},
        }
        result = await finalize_node(state)
        pages = result.get("pages", [])
        kept = [p for p in pages if p.get("path") == "test-domain/index"]
        assert len(kept) == 1
        assert kept[0].get("__rejected__") is not True
        assert kept[0].get("__degraded__") is True

    @pytest.mark.asyncio
    async def test_normal_short_page_still_rejected(self):
        """Normal short overview page without agent_error should still be hard-rejected."""
        from wiki.nodes.finalize import finalize_node

        page = {
            "page_type": "domain_overview",
            "path": "test-domain/index",
            "title": "Test Domain",
            "content": "x" * 10,
            "metadata": {},
        }
        state = {
            "pages": [page],
            "repo_id": "test-repo",
            "config": {"content_language": "zh"},
        }
        result = await finalize_node(state)
        pages = result.get("pages", [])
        kept = [p for p in pages if p.get("path") == "test-domain/index"]
        # Should be either rejected or have empty content
        if kept:
            assert kept[0].get("__rejected__") is True or kept[0].get("content") == ""
