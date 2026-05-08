"""LLM-powered semantic diagram generation for wiki pages.

Generates Mermaid diagrams (sequence, state, flowchart, architecture) by analyzing
entity_digest context and producing business-logic-level visuals.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.log import get_logger
from store.schema import EdgeType
from wiki.data_collector import PageData
from wiki.models import DiagramType, PageType, WikiDiagram

if TYPE_CHECKING:
    from wiki.llm_port import LLMPort

log = get_logger(__name__)

_MAX_MERMAID_LINES = 80

VALID_MERMAID_STARTS = frozenset({
    "sequenceDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "flowchart",
    "graph",
    "classDiagram",
})

_SYSTEM_PROMPT = (
    "You are a software architecture diagramming expert. "
    "Generate valid Mermaid syntax only. "
    "No markdown fences, no explanatory text. Return ONLY the Mermaid code.\n\n"
    "CRITICAL CONSTRAINT: All participant names and node labels MUST come from "
    "the entity names provided in the context below. Do NOT invent services, "
    "components, or systems that are not listed in the provided entities. "
    "If the provided context is insufficient for a meaningful diagram, "
    "output exactly: NO_DIAGRAM\n\n"
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

_STATE_USER_PROMPT = """\
Based on the following entity analysis, generate a Mermaid stateDiagram-v2 \
capturing meaningful states and transitions implied by state-related behavior.

Entity: {name}

Context:
{entity_digest}

Requirements:
1. Use stateDiagram-v2 syntax only
2. Model dominant lifecycle states (3-8 states)
3. Label transitions with the triggering action or event where possible
4. Include [*] for initial/final where appropriate

Return ONLY the Mermaid code starting with "stateDiagram-v2"."""

_DATAFLOW_USER_PROMPT = """\
Based on the following entity analysis, generate a Mermaid flowchart describing \
the data processing pipeline (inputs, transformations, outputs).

Entity: {name}

Context:
{entity_digest}

Requirements:
1. Use flowchart syntax (e.g. flowchart TD or LR)
2. Show stages as nodes and data movement as edges
3. Keep to roughly 5-12 nodes
4. Prefer short node labels

Return ONLY the Mermaid code starting with "flowchart"."""

_ARCHITECTURE_USER_PROMPT = """\
Based on the following overview context, generate a Mermaid graph diagram \
(graph TD) showing services or components and their dependency / interaction edges.

Scope: {name}

Context:
{entity_digest}

Requirements:
1. Use graph TD (or graph LR if clearer)
2. Nodes represent services, modules, or bounded contexts
3. Edges show calls, data flow, or dependency direction
4. Keep to roughly 5-12 nodes

Return ONLY the Mermaid code starting with "graph"."""

_MIN_CALLS_MODULE = 3
_MIN_CALLS_CLASS = 2
_MIN_METHODS_CLASS = 5

_STATE_KEYWORDS = frozenset({
    "state", "status", "transition", "setstate", "updatestatus",
    "phase", "stage", "workflow", "step",
})
_FLOW_KEYWORDS = frozenset({
    "transform", "process", "pipeline", "convert", "parse",
    "serialize", "deserialize", "map", "filter", "reduce",
})


def _display_name(uid: str) -> str:
    parts = uid.rsplit(":", 2)
    if len(parts) >= 3:
        return str(parts[-2])
    return uid


class SemanticDiagramGenerator:
    __slots__ = ("_llm",)

    def __init__(self, llm: "LLMPort | None") -> None:
        self._llm = llm

    def _should_generate(
        self, page_data: PageData, page_type: PageType, mode: str,
    ) -> bool:
        if mode != "full" or self._llm is None:
            return False
        if page_type in (PageType.DOMAIN_OVERVIEW, PageType.REPO_OVERVIEW, PageType.TOPIC):
            return True
        call_edges = sum(1 for e in page_data.edges if e.edge_type == EdgeType.CALLS)
        if page_type == PageType.MODULE_OVERVIEW:
            return call_edges >= _MIN_CALLS_MODULE
        if page_type == PageType.CLASS_DETAIL:
            method_count = len(getattr(page_data, "methods", []) or [])
            return method_count >= _MIN_METHODS_CLASS and call_edges >= _MIN_CALLS_CLASS
        return False

    def _build_entity_digest(self, page_data: PageData) -> str:
        parts: list[str] = []
        n = page_data.node
        for key in ("name", "path", "fqn", "signature", "docstring", "business_summary", "description"):
            val = n.properties.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val)
        for m in page_data.methods:
            for key in ("name", "signature", "docstring", "business_summary"):
                val = m.properties.get(key)
                if isinstance(val, str) and val.strip():
                    parts.append(val)
        for ch in page_data.children[:30]:
            parts.append(str(ch.properties.get("name", ch.uid)))
            sig = ch.properties.get("signature")
            if isinstance(sig, str) and sig.strip():
                parts.append(sig)
        for e in page_data.edges[:40]:
            parts.append(e.edge_type.value)
            parts.append(_display_name(e.target_uid))
            parts.append(_display_name(e.source_uid))
        return "\n".join(parts)

    def build_entity_digest(self, page_data: PageData) -> str:
        """Build a text digest of page data for diagram generation prompts."""
        return self._build_entity_digest(page_data)

    def decide_diagram_types(self, page_data: PageData, page_type: PageType) -> list[DiagramType]:
        """Decide which semantic diagram kinds to generate for this page."""
        types: list[DiagramType] = [DiagramType.SEQUENCE_DIAGRAM]
        blob = self._build_entity_digest(page_data).lower()
        if any(kw in blob for kw in _STATE_KEYWORDS):
            types.append(DiagramType.STATE)
        if any(kw in blob for kw in _FLOW_KEYWORDS):
            types.append(DiagramType.DATA_FLOW)
        if page_type in (PageType.DOMAIN_OVERVIEW, PageType.REPO_OVERVIEW):
            types.append(DiagramType.ARCHITECTURE)
        return types

    def _build_sequence_prompt(self, page_data: PageData, page_type: PageType, entity_digest: str) -> str:
        name = page_data.node.properties.get("name", page_data.node.uid)
        if page_type in (PageType.MODULE_OVERVIEW, PageType.DOMAIN_OVERVIEW, PageType.REPO_OVERVIEW):
            template = _MODULE_USER_PROMPT
        else:
            template = _CLASS_USER_PROMPT
        return template.replace("{name}", str(name)).replace("{entity_digest}", entity_digest)

    @staticmethod
    def sanitize_mermaid_output(raw: str) -> str | None:
        """Strip markdown fences and validate Mermaid header / size bounds."""
        return SemanticDiagramGenerator._validate_and_clean(raw)

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
    def _infer_sequence_title(page_type: PageType) -> str:
        if page_type == PageType.MODULE_OVERVIEW:
            return "Module interaction flow"
        if page_type in (PageType.DOMAIN_OVERVIEW, PageType.REPO_OVERVIEW):
            return "Overview interaction flow"
        return "Class interaction flow"

    async def generate_state_diagram(
        self, name: str, entity_digest: str, llm: "LLMPort",
    ) -> WikiDiagram | None:
        prompt = _STATE_USER_PROMPT.replace("{name}", str(name)).replace("{entity_digest}", entity_digest)
        raw = await llm.generate(prompt, system=_SYSTEM_PROMPT)
        cleaned = self.sanitize_mermaid_output(raw)
        if cleaned is None:
            log.warning("semantic_diagram_invalid_mermaid", diagram_kind="state", entity=name)
            return None
        return WikiDiagram(
            diagram_type=DiagramType.STATE,
            content=cleaned,
            title="State transitions",
        )

    async def generate_dataflow_diagram(
        self, name: str, entity_digest: str, llm: "LLMPort",
    ) -> WikiDiagram | None:
        prompt = _DATAFLOW_USER_PROMPT.replace("{name}", str(name)).replace("{entity_digest}", entity_digest)
        raw = await llm.generate(prompt, system=_SYSTEM_PROMPT)
        cleaned = self.sanitize_mermaid_output(raw)
        if cleaned is None:
            log.warning("semantic_diagram_invalid_mermaid", diagram_kind="data_flow", entity=name)
            return None
        return WikiDiagram(
            diagram_type=DiagramType.DATA_FLOW,
            content=cleaned,
            title="Data processing flow",
        )

    async def generate_architecture_diagram(
        self, name: str, entity_digest: str, llm: "LLMPort",
    ) -> WikiDiagram | None:
        prompt = _ARCHITECTURE_USER_PROMPT.replace("{name}", str(name)).replace("{entity_digest}", entity_digest)
        raw = await llm.generate(prompt, system=_SYSTEM_PROMPT)
        cleaned = self.sanitize_mermaid_output(raw)
        if cleaned is None:
            log.warning("semantic_diagram_invalid_mermaid", diagram_kind="architecture", entity=name)
            return None
        return WikiDiagram(
            diagram_type=DiagramType.ARCHITECTURE,
            content=cleaned,
            title="Architecture overview",
        )

    async def _generate_sequence_diagram(
        self, page_data: PageData, page_type: PageType, entity_digest: str,
    ) -> WikiDiagram | None:
        assert self._llm is not None
        prompt = self._build_sequence_prompt(page_data, page_type, entity_digest)
        raw = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)
        cleaned = self.sanitize_mermaid_output(raw)
        if cleaned is None:
            entity_name = page_data.node.properties.get("name", page_data.node.uid)
            log.warning("semantic_diagram_invalid_mermaid", diagram_kind="sequence", entity=entity_name)
            return None
        title = self._infer_sequence_title(page_type)
        return WikiDiagram(
            diagram_type=DiagramType.SEQUENCE_DIAGRAM,
            content=cleaned,
            title=title,
        )

    async def generate_for_page(
        self,
        page_data: PageData,
        page_type: PageType,
        entity_digest: str,
        mode: str,
    ) -> list[WikiDiagram]:
        if not self._should_generate(page_data, page_type, mode):
            return []
        assert self._llm is not None
        name = page_data.node.properties.get("name", page_data.node.uid)
        kinds = self.decide_diagram_types(page_data, page_type)
        diagrams: list[WikiDiagram] = []
        for kind in kinds:
            try:
                if kind == DiagramType.SEQUENCE_DIAGRAM:
                    seq = await self._generate_sequence_diagram(page_data, page_type, entity_digest)
                    if seq is not None:
                        diagrams.append(seq)
                elif kind == DiagramType.STATE:
                    st = await self.generate_state_diagram(name, entity_digest, self._llm)
                    if st is not None:
                        diagrams.append(st)
                elif kind == DiagramType.DATA_FLOW:
                    df = await self.generate_dataflow_diagram(name, entity_digest, self._llm)
                    if df is not None:
                        diagrams.append(df)
                elif kind == DiagramType.ARCHITECTURE:
                    arch = await self.generate_architecture_diagram(name, entity_digest, self._llm)
                    if arch is not None:
                        diagrams.append(arch)
            except Exception:
                log.warning("semantic_diagram_kind_failed", diagram_kind=kind.value, exc_info=True)
        return diagrams

    async def generate(
        self,
        page_data: PageData,
        page_type: PageType,
        entity_digest: str,
        mode: str,
    ) -> list[WikiDiagram]:
        return await self.generate_for_page(page_data, page_type, entity_digest, mode)
