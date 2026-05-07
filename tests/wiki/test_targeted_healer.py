"""Tests for wiki.targeted_healer.TargetedHealer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from wiki.models import PageType, WikiPage, WikiPageMetadata
from wiki.targeted_healer import TargetedHealer


def _page(content: str) -> WikiPage:
    return WikiPage(
        path="/wiki/demo",
        title="Demo",
        page_type=PageType.TOPIC,
        content=content,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


@pytest.fixture
def healer() -> TargetedHealer:
    return TargetedHealer()


class TestApplyPatches:
    def test_replace_insert_append_sequence(self, healer: TargetedHealer) -> None:
        content = "## First\nOld first body.\n\n## Second\nOld second.\n\n## Third\nEnd.\n"
        patches = [
            {"action": "replace_section", "target_heading": "First", "content": "Replaced.\n"},
            {"action": "insert_after", "target_heading": "Third", "content": "Inserted block."},
            {"action": "append", "target_heading": "", "content": "### Footer\nTrailing."},
        ]
        got = healer._apply_patches(content, patches)
        assert "Replaced." in got
        assert "## First\nReplaced.\n\n" in got
        assert "Old second" in got  # untouched section body
        assert "## Third\n\n\nInserted block.\n\nEnd.\n" in got.replace("\r", "")
        assert "Trailing." in got

    def test_missing_heading_safe_skip_replace(self, healer: TargetedHealer) -> None:
        content = "## A\nx\n"
        patches = [{"action": "replace_section", "target_heading": "Missing", "content": "nope"}]
        assert healer._apply_patches(content, patches) == content

    def test_append_preserves_prior_newlines_trim(self, healer: TargetedHealer) -> None:
        content = "## A\nx"
        got = healer._apply_patches(
            content,
            [{"action": "append", "target_heading": "", "content": "\nTail\n"}],
        )
        assert got.endswith("Tail\n")


class TestReplaceSection:
    def test_replace_between_same_level_only(self, healer: TargetedHealer) -> None:
        md = "## Main\nBODY\n### Sub stays\nstill here\n\n## Next\noutside\n"
        got = healer._replace_section(md, "## Main", "NEWBODY\n### Sub stays\nstill here")
        assert got.startswith("## Main\nNEWBODY\n### Sub stays\nstill here")
        assert "## Next\noutside\n" in got


class TestParseResponse:
    def test_plain_json(self, healer: TargetedHealer) -> None:
        blob = '{"patches": [{"action": "append", "content": "hi"}]}'
        out = healer._parse_response(blob)
        assert out == {"patches": [{"action": "append", "content": "hi"}]}

    def test_fenced_json(self, healer: TargetedHealer) -> None:
        raw = "```json\n" + '{"patches": [{"action": "append", "target_heading": "", "content": "x"}]}' + "\n```"
        out = healer._parse_response(raw)
        assert out and len(out["patches"]) == 1

    def test_prefix_noise_then_json_object(self, healer: TargetedHealer) -> None:
        raw = "Here:\n{\"patches\": []}"
        out = healer._parse_response(raw)
        assert out == {"patches": []}

    def test_invalid_returns_none(self, healer: TargetedHealer) -> None:
        assert healer._parse_response("not json {{{") is None
        assert healer._parse_response("") is None


@pytest.mark.asyncio
class TestHeal:
    async def test_heal_success_returns_patched_page(self, healer: TargetedHealer) -> None:
        page = _page("## Foo\nOriginal.\n")
        patch_json = json.dumps(
            {"patches": [{"action": "replace_section", "target_heading": "Foo", "content": "Patched.\n"}]}
        )
        mock_llm = AsyncMock(spec=["generate", "complete_json"])
        mock_llm.complete_json = AsyncMock(return_value=json.loads(patch_json))
        got = await healer.heal(page, "hints", mock_llm, "ctx")
        assert got is not None
        assert got.content.strip() == "## Foo\nPatched."
        mock_llm.complete_json.assert_awaited_once()
        mock_llm.generate.assert_not_called()

    async def test_heal_returns_none_when_llm_raises(self, healer: TargetedHealer) -> None:
        page = _page("# x")
        mock_llm = AsyncMock(spec=["generate", "complete_json"])
        mock_llm.complete_json = AsyncMock(side_effect=RuntimeError("boom"))

        got = await healer.heal(page, "hints", mock_llm, "")
        assert got is None


@pytest.mark.asyncio
async def test_heal_passes_max_tokens(healer: TargetedHealer) -> None:
    page = _page("## A\nb")
    mock_llm = AsyncMock(spec=["generate", "complete_json"])
    mock_llm.complete_json = AsyncMock(
        return_value={"patches": [{"action": "append", "content": "."}]}
    )
    await healer.heal(page, "h", mock_llm, "d", max_tokens=777)
    _args, kw = mock_llm.complete_json.call_args
    assert kw.get("max_tokens") == 777
