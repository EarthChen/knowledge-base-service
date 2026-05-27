"""Tests for Java primitive / reserved keyword slug denylist."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.graph_domain_namer import GraphDomainNamer
from wiki.nodes.classify import _ensure_ascii_keys
from wiki.nodes.domain_filters import is_denied_slug


class TestIsDeniedSlug:
    def test_abs_denied(self) -> None:
        assert is_denied_slug("abs") is True

    def test_long_denied(self) -> None:
        assert is_denied_slug("long") is True

    def test_long_case_insensitive(self) -> None:
        assert is_denied_slug("Long") is True

    def test_family_system_allowed(self) -> None:
        assert is_denied_slug("family-system") is False

    def test_user_profile_allowed(self) -> None:
        assert is_denied_slug("user-profile") is False


class TestEnsureAsciiKeysDenylist:
    def test_denied_ascii_slug_replaced(self) -> None:
        mapping = {"long": [("repo", "LongService")]}
        display = {"long": "长整型"}
        result_mapping, _ = _ensure_ascii_keys(mapping, display)
        assert "long" not in result_mapping
        keys = list(result_mapping.keys())
        assert len(keys) == 1
        assert keys[0] != "long"


class TestGraphDomainNamerDenylist:
    @pytest.mark.asyncio
    async def test_denied_llm_slug_gets_suffix(self) -> None:
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(
            return_value='{"slug": "long", "display_name": "长整型", "description": "desc"}'
        )
        namer = GraphDomainNamer(mock_llm)
        result = await namer.name_community(["LongService", "LongDao"])
        assert result["slug"] == "long-domain"
        assert result["display_name"] == "长整型"
