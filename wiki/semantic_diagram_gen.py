"""LLM-powered semantic diagram generation for wiki pages.

Generates Mermaid sequence diagrams by analyzing entity_digest context
and producing business-logic-level interaction diagrams.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from store.schema import EdgeType
from wiki.models import DiagramType, PageType, WikiDiagram

if TYPE_CHECKING:
    from wiki.composer import PageData
    from wiki.context import LLMPort

log = logging.getLogger(__name__)

_MAX_MERMAID_LINES = 80

VALID_MERMAID_STARTS = frozenset({
    "sequenceDiagram", "stateDiagram-v2", "stateDiagram",
    "flowchart", "graph", "classDiagram",
})

_SYSTEM_PROMPT = (
    "You are a software architecture diagramming expert. "
    "Generate valid Mermaid syntax only. "
    "No markdown fences, no explanatory text. Return ONLY the Mermaid code.\n\n"
    "Mermaid syntax rules:\n"
    "- Participant names must be simple identifiers (alphanumeric, no spaces, no special chars)\n"
    "- Use aliases for readable labels: participant SVC as ServiceLayer\n"
    "- Arrow messages can contain spaces and punctuation\n"
    "- Keep diagrams concise: 5-10 participants maximum\n"
)

_MODULE_USER_PROMPT = """\
Based on the following module analysis, generate a Mermaid sequence diagram \
showing the main calling flow between this module's key components.

Module: {name}

Key components and their relationships:
{entity_digest}

Generate a sequenceDiagram that shows:
1. The most important calling sequence (pick the primary use case)
2. Use descriptive messages on the arrows
3. Keep to 5-10 participants maximum
4. Use activate/deactivate for key participants

Example format:
sequenceDiagram
    participant C as Controller
    participant S as Service
    participant R as Repository
    C->>S: processRequest()
    activate S
    S->>R: fetchData()
    R-->>S: data
    S-->>C: result
    deactivate S

Return ONLY the Mermaid code starting with "sequenceDiagram"."""

_CLASS_USER_PROMPT = """\
Based on the following class analysis, generate a Mermaid sequence diagram \
showing the key method interaction flow within this class and its collaborators.

Class: {name}

Methods and relationships:
{entity_digest}

Generate a sequenceDiagram that shows:
1. The primary business workflow through this class's methods
2. How this class interacts with its dependencies
3. Use descriptive messages on the arrows
4. Keep to 5-8 participants maximum

Return ONLY the Mermaid code starting with "sequenceDiagram"."""

_MIN_CALLS_MODULE = 3
_MIN_CALLS_CLASS = 2
_MIN_METHODS_CLASS = 5


class SemanticDiagramGenerator:
    __slots__ = ("_llm",)

    def __init__(self, llm: "LLMPort | None") -> None:
        self._llm = llm

    def _should_generate(
        self, page_data: "PageData", page_type: PageType, mode: str,
    ) -> bool:
        if mode != "full" or self._llm is None:
            return False
        call_edges = sum(1 for e in page_data.edges if e.edge_type == EdgeType.CALLS)
        if page_type == PageType.MODULE_OVERVIEW:
            return call_edges >= _MIN_CALLS_MODULE
        if page_type == PageType.CLASS_DETAIL:
            method_count = len(getattr(page_data, "methods", []) or [])
            return method_count >= _MIN_METHODS_CLASS and call_edges >= _MIN_CALLS_CLASS
        return False

    def _build_prompt(
        self, page_data: "PageData", page_type: PageType, entity_digest: str,
    ) -> str:
        name = page_data.node.properties.get("name", page_data.node.uid)
        template = _MODULE_USER_PROMPT if page_type == PageType.MODULE_OVERVIEW else _CLASS_USER_PROMPT
        return template.replace("{name}", str(name)).replace("{entity_digest}", entity_digest)

    @staticmethod
    def _validate_and_clean(raw: str) -> str | None:
        if not raw or not raw.strip():
            return None
        text = raw.strip()
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl == -1:
                return None
            text = text[first_nl + 1:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        if not text:
            return None
        first_line = text.split("\n")[0].strip()
        if not any(first_line.startswith(p) for p in VALID_MERMAID_STARTS):
            return None
        if text.count("\n") + 1 > _MAX_MERMAID_LINES:
            return None
        return text

    @staticmethod
    def _infer_title(page_type: PageType) -> str:
        if page_type == PageType.MODULE_OVERVIEW:
            return "Module interaction flow"
        return "Class interaction flow"

    async def generate(
        self,
        page_data: "PageData",
        page_type: PageType,
        entity_digest: str,
        mode: str,
    ) -> list[WikiDiagram]:
        if not self._should_generate(page_data, page_type, mode):
            return []
        assert self._llm is not None
        try:
            prompt = self._build_prompt(page_data, page_type, entity_digest)
            raw = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)
            cleaned = self._validate_and_clean(raw)
            if cleaned is None:
                entity_name = page_data.node.properties.get("name", page_data.node.uid)
                log.info("semantic_diagram_invalid_mermaid", entity=entity_name)
                return []
            title = self._infer_title(page_type)
            return [
                WikiDiagram(
                    diagram_type=DiagramType.SEQUENCE_DIAGRAM,
                    content=cleaned,
                    title=title,
                )
            ]
        except Exception:
            log.debug("semantic_diagram_failed", exc_info=True)
            return []
