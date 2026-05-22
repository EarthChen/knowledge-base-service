"""LLM-based extraction of declarative claims from wiki markdown."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass


class ExtractedClaim(BaseModel):
    claim_text: str
    subject_entity: str = Field(default="")


def _parse_claims_json(raw: str) -> list[ExtractedClaim]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[ExtractedClaim] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            out.append(ExtractedClaim.model_validate(item))
        except Exception:
            continue
    return out


async def extract_claims(llm: Any, page_markdown: str, language: str) -> list[ExtractedClaim]:
    if not page_markdown.strip():
        return []
    if llm is None or not hasattr(llm, "generate"):
        return []
    system = (
        "Reply with JSON only: an array of objects "
        '{"claim_text": string, "subject_entity": string}.'
    )
    system_json_object = (
        'Reply with JSON only: a JSON object '
        '{"claims": [{"claim_text": string, "subject_entity": string}, ...]}.'
    )
    prompt = (
        f"Language: {language}\n"
        "Extract short declarative factual claims (one sentence each) from this wiki page.\n"
        "Use subject_entity for the primary class/module/function the claim is about (short name or FQN).\n\n"
        f"---\n{page_markdown[:12000]}\n---\n"
    )
    if hasattr(llm, "complete_json"):
        messages = [
            {"role": "system", "content": system_json_object},
            {"role": "user", "content": prompt},
        ]
        try:
            parsed = await llm.complete_json(messages, {})  # type: ignore[union-attr]
        except (ValueError, Exception):
            return []
        if not isinstance(parsed, list):
            if isinstance(parsed, dict) and "claims" in parsed:
                parsed = parsed["claims"]
            else:
                return []
        if not isinstance(parsed, list):
            return []
    else:
        raw = (await llm.generate(prompt, system=system)).strip()  # type: ignore[union-attr]
        parsed = _parse_claims_json(raw)
        if not parsed:
            return []

    out: list[ExtractedClaim] = []
    for item in parsed:
        if isinstance(item, ExtractedClaim):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        try:
            out.append(ExtractedClaim.model_validate(item))
        except Exception:
            continue
    return out
