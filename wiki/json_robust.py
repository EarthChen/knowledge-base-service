"""Robust JSON parsing with 3-level repair strategy.

Level 1: json.loads — direct parse
Level 2: json_repair.repair_json — auto-fix (trailing comma, unclosed brackets)
Level 3: LLM fix via OutputFixingParser (agent loop)
"""
from __future__ import annotations

import json
import re
from typing import Any

from json_repair import repair_json

from core.log import get_logger

log = get_logger(__name__)


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\s*\n?", "", text, count=1)
        text = re.sub(r"\n?```\s*$", "", text, count=1)
    return text.strip()


def parse_json_robust_sync(raw: str) -> dict | list | None:
    """Parse JSON with Level 1 + Level 2 repair (sync, no LLM)."""
    text = _strip_fences(raw)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, (dict, list)):
            log.info("json_auto_repaired", strategy="json-repair")
            return repaired
    except Exception:
        log.debug("json_repair_level2_failed", exc_info=True)

    return None


async def parse_json_robust(
    raw: str,
    llm: Any | None = None,
) -> dict | list | None:
    """Parse JSON with 3-level repair strategy.

    Args:
        raw: Raw LLM output string.
        llm: Optional LangChain ChatModel for Level 3 LLM fix.
    """
    text = _strip_fences(raw)
    result = parse_json_robust_sync(text)
    if result is not None:
        return result

    if llm is not None:
        try:
            from langchain.output_parsers import OutputFixingParser
            from langchain_core.output_parsers import JsonOutputParser

            fixing_parser = OutputFixingParser.from_llm(
                parser=JsonOutputParser(), llm=llm, max_retries=2
            )
            result = await fixing_parser.aparse(text)
            log.info("json_llm_fixed", strategy="OutputFixingParser")
            return result
        except Exception as e:
            log.warning("json_all_retries_exhausted", error=str(e)[:200])

    return None
