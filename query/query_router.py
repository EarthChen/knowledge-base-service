"""Route natural-language queries to hybrid search weighting strategies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from wiki.ask import detect_question_type

# Align with hybrid_query identifier / FQN heuristics for code-like queries.
_FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*(?:\([^)]*\))?)?"
)
_CAMEL_TOKEN_RE = re.compile(
    r"\b(?:[a-z]+(?:[A-Z][a-zA-Z0-9]*)+|[A-Z][a-z]+(?:[A-Z][a-zA-Z0-9]*)+)\b"
)


@dataclass
class SearchStrategy:
    keyword_weight: float
    semantic_weight: float
    expand_graph: bool
    entity_priority: list[str] = field(default_factory=list)
    query_type: str = "general"


def _looks_code_like(query: str) -> bool:
    """True when the query resembles code identifiers (FQN, camelCase, PascalCase)."""
    if not query or not query.strip():
        return False
    if _FQN_RE.search(query):
        return True
    return bool(_CAMEL_TOKEN_RE.search(query))


def _base_strategy(query_type: str) -> SearchStrategy:
    """Map keyword intent label to default fusion weights (before code-like tuning)."""
    if query_type == "concept":
        return SearchStrategy(
            keyword_weight=0.5,
            semantic_weight=1.5,
            expand_graph=True,
            entity_priority=[],
            query_type=query_type,
        )
    if query_type == "flow":
        return SearchStrategy(
            keyword_weight=1.0,
            semantic_weight=1.0,
            expand_graph=True,
            entity_priority=["Function"],
            query_type=query_type,
        )
    if query_type == "relation":
        return SearchStrategy(
            keyword_weight=1.5,
            semantic_weight=1.0,
            expand_graph=True,
            entity_priority=[],
            query_type=query_type,
        )
    if query_type == "impact":
        return SearchStrategy(
            keyword_weight=1.5,
            semantic_weight=0.5,
            expand_graph=True,
            entity_priority=[],
            query_type=query_type,
        )
    # general (default balanced)
    return SearchStrategy(
        keyword_weight=1.5,
        semantic_weight=1.0,
        expand_graph=True,
        entity_priority=[],
        query_type="general",
    )


_CODE_LIKE_KW_BOOST = 1.25


def route_query(query: str) -> SearchStrategy:
    """Classify ``query`` and return hybrid-search fusion parameters."""
    intent = detect_question_type(query)
    strategy = _base_strategy(intent)
    if _looks_code_like(query):
        strategy.keyword_weight = min(strategy.keyword_weight * _CODE_LIKE_KW_BOOST, 3.0)
    return strategy
