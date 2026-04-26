"""Tests for claim extraction from wiki content."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.claim_extractor import ExtractedClaim, extract_claims, _parse_claims_json


def test_parse_claims_json_array() -> None:
    raw = json.dumps(
        [
            {"claim_text": "Method X returns Y", "subject_entity": "Foo"},
        ],
    )
    out = _parse_claims_json(raw)
    assert len(out) == 1
    assert out[0].claim_text == "Method X returns Y"
    assert out[0].subject_entity == "Foo"


@pytest.mark.asyncio
async def test_extract_claims_invokes_llm() -> None:
    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value=json.dumps(
            [{"claim_text": "A", "subject_entity": "E"}],
        ),
    )
    out = await extract_claims(llm, "# Title\n\nBody.", "en")
    assert out == [ExtractedClaim(claim_text="A", subject_entity="E")]
