"""Structured reasoning path for wiki Q&A and deep search provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningStage:
    """One retrieval stage in a reasoning path."""

    stage_name: str
    retriever: str  # "vector", "fts", "graph", "graph_path", "wiki_search", etc.
    entity_hits: list[str] = field(default_factory=list)
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningPath:
    """Ordered sequence of retrieval stages that built the answer context."""

    stages: list[ReasoningStage] = field(default_factory=list)
    answer_entities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": [
                {
                    "stage_name": s.stage_name,
                    "retriever": s.retriever,
                    "entity_hits": s.entity_hits,
                    "score": s.score,
                    "metadata": s.metadata,
                }
                for s in self.stages
            ],
            "answer_entities": self.answer_entities,
        }


def extract_entities_in_answer(answer_text: str, candidate_names: list[str]) -> list[str]:
    """Post-process: find which candidate entity names appear in the answer text."""
    if not answer_text or not candidate_names:
        return []
    found = []
    seen = set()
    for name in sorted(set(candidate_names), key=len, reverse=True):
        if name and name not in seen and name in answer_text:
            found.append(name)
            seen.add(name)
    return found


def merge_reasoning_paths(*paths: ReasoningPath) -> ReasoningPath:
    """Merge multiple reasoning paths into one (e.g. from search + graph + ask)."""
    merged = ReasoningPath()
    for p in paths:
        merged.stages.extend(p.stages)
        for e in p.answer_entities:
            if e not in merged.answer_entities:
                merged.answer_entities.append(e)
    return merged
