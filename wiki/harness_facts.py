"""Gathered facts storage and tiered distill logic for Wiki generation harness."""
from __future__ import annotations

from dataclasses import dataclass, field

from wiki.harness_router import CONTEXT_BUDGETS


@dataclass
class Fact:
    source: str
    content: str
    section: str
    char_count: int = 0


@dataclass
class GatheredFacts:
    facts: dict[str, list[Fact]] = field(default_factory=dict)
    total_chars: int = 0

    def add(self, section: str, source: str, content: str) -> None:
        if section not in self.facts:
            self.facts[section] = []
        fact = Fact(source=source, content=content, section=section, char_count=len(content))
        self.facts[section].append(fact)
        self.total_chars += len(content)

    def distill(
        self,
        complexity_level: str = "moderate",
        domain_summaries: list[str] | None = None,
    ) -> str:
        """Distill gathered facts into generation context using tiered budgets."""
        if not self.facts:
            return ""

        budget = CONTEXT_BUDGETS[complexity_level]
        max_chars = budget["max_chars_per_section"]

        sections: list[str] = []
        for section_name, fact_list in self.facts.items():
            combined = "\n".join(f.content for f in fact_list)
            if len(combined) > max_chars:
                combined = combined[:max_chars] + "\n[...truncated]"
            sections.append(f"## {section_name}\n{combined}")

        result = "\n\n".join(sections)

        if domain_summaries:
            cross_ref = "\n".join(domain_summaries)
            result = f"## 相关域参考\n{cross_ref}\n\n{result}"

        return result
