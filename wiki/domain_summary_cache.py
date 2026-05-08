"""Domain Summary Cache for cross-domain knowledge sharing."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DomainSummaryCard:
    domain_name: str
    module_names: list[str]
    entry_points: list[str]
    responsibilities: str
    depends_on: list[str] = field(default_factory=list)
    generated_at: str = ""
    content_hash: str = ""


def extract_summary_card(
    domain: str, modules: list[str], content: str,
) -> DomainSummaryCard:
    """Extract a summary card from generated wiki content. Deterministic."""
    overview_match = re.search(
        r"##?\s*概述\s*\n(.*?)(?=\n##|\Z)", content, re.S,
    )
    responsibilities = overview_match.group(1).strip()[:200] if overview_match else ""

    entry_points = modules[:3]

    content_hash = hashlib.md5(content.encode()).hexdigest()

    return DomainSummaryCard(
        domain_name=domain,
        module_names=modules,
        entry_points=entry_points,
        responsibilities=responsibilities,
        depends_on=[],
        generated_at=datetime.now().isoformat(),
        content_hash=content_hash,
    )
