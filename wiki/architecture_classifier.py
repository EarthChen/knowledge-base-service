"""Multi-signal weighted voting classifier for Module-level architecture layers."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.config import AppWikiFlags
from core.log import get_logger

if TYPE_CHECKING:
    from llm.provider import LLMProvider
    from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)

LAYERS = ("api", "service", "data", "infrastructure")

_ENRICHER_TO_CLASSIFIER: dict[str, str] = {
    "presentation": "api",
    "rpc": "api",
    "business": "service",
    "data_access": "data",
    "model": "data",
    "infrastructure": "infrastructure",
    "messaging": "infrastructure",
    "testing": "infrastructure",
    "util": "infrastructure",
}

ENRICHER_LAYERS = tuple(_ENRICHER_TO_CLASSIFIER.keys())

_LLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "layer": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["layer"],
}


@dataclass
class LayerVote:
    layer: str
    confidence: float
    signal: str


@dataclass
class LayerResult:
    layer: str
    confidence: float
    votes: list[LayerVote]


class ArchitectureLayerClassifier:
    """Classify modules into api / service / data / infrastructure via weighted signals."""

    SIGNAL_WEIGHTS = {"annotation": 0.4, "topology": 0.3, "path_pattern": 0.2, "llm": 0.1}

    def __init__(
        self,
        config: AppWikiFlags,
        graph_store: FalkorDBStore,
        llm: LLMProvider | None = None,
        budget_resolver: Any | None = None,
    ) -> None:
        self._patterns = config.architecture_layer_patterns
        self._store = graph_store
        self._llm = llm
        self._budget_resolver = budget_resolver

    async def classify_module(self, module_name: str, module_path: str) -> LayerResult:
        votes: list[LayerVote] = [
            await self._vote_by_annotations(module_name),
            await self._vote_by_topology(module_name),
            self._vote_by_path(module_path),
        ]
        result = self._aggregate(votes)

        if result.confidence < 0.5 and self._llm is not None:
            llm_vote = await self._vote_by_llm(module_name, module_path, votes)
            votes.append(llm_vote)
            result = self._aggregate(votes)

        return result

    async def _vote_by_annotations(self, module_name: str) -> LayerVote:
        query = """
        MATCH (m:Module {name: $name})-[:CONTAINS]->(c:Class)
        RETURN c.architecture_layer AS layer
        """
        result = await self._store.execute_query(query, {"name": module_name})
        rows = getattr(result, "data", None) or []

        mapped: list[str] = []
        for row in rows:
            raw = row.get("layer")
            if not raw or raw == "unknown":
                continue
            classifier_layer = _ENRICHER_TO_CLASSIFIER.get(str(raw))
            if classifier_layer:
                mapped.append(classifier_layer)

        if not mapped:
            return LayerVote(layer="unknown", confidence=0.0, signal="annotation")

        counts = Counter(mapped)
        best_layer, best_count = counts.most_common(1)[0]
        confidence = best_count / len(mapped)
        confidence = min(confidence, min(1.0, len(mapped) / 3))
        return LayerVote(layer=best_layer, confidence=confidence, signal="annotation")

    async def _vote_by_topology(self, module_name: str) -> LayerVote:
        fan_in_query = """
        MATCH (m:Module {name: $name})-[:CONTAINS]->(f:Function)
        OPTIONAL MATCH (ext:Function)-[:CALLS]->(f)
        WHERE NOT (m)-[:CONTAINS]->(ext)
        RETURN count(DISTINCT ext) AS fan_in
        """
        fan_out_query = """
        MATCH (m:Module {name: $name})-[:CONTAINS]->(f:Function)
        OPTIONAL MATCH (f)-[:CALLS]->(ext:Function)
        WHERE NOT (m)-[:CONTAINS]->(ext)
        RETURN count(DISTINCT ext) AS fan_out
        """
        fan_in_result = await self._store.execute_query(fan_in_query, {"name": module_name})
        fan_out_result = await self._store.execute_query(fan_out_query, {"name": module_name})

        fan_in_rows = getattr(fan_in_result, "data", None) or []
        fan_out_rows = getattr(fan_out_result, "data", None) or []
        fan_in = int((fan_in_rows[0] if fan_in_rows else {}).get("fan_in") or 0)
        fan_out = int((fan_out_rows[0] if fan_out_rows else {}).get("fan_out") or 0)

        total = fan_in + fan_out
        if total < 3:
            return LayerVote(layer="unknown", confidence=0.0, signal="topology")

        ratio_in = fan_in / total
        if ratio_in > 0.7:
            layer = "api"
        elif ratio_in < 0.3:
            layer = "data"
        else:
            layer = "service"

        confidence = min(1.0, total / 10)
        return LayerVote(layer=layer, confidence=confidence, signal="topology")

    def _vote_by_path(self, module_path: str) -> LayerVote:
        lower = module_path.lower()
        for layer, patterns in self._patterns.items():
            if any(p in lower for p in patterns):
                return LayerVote(layer=layer, confidence=0.8, signal="path_pattern")
        return LayerVote(layer="unknown", confidence=0.0, signal="path_pattern")

    async def _vote_by_llm(
        self,
        module_name: str,
        module_path: str,
        prior_votes: list[LayerVote],
    ) -> LayerVote:
        if self._llm is None:
            return LayerVote(layer="unknown", confidence=0.0, signal="llm")

        prior_summary = [(v.signal, v.layer, v.confidence) for v in prior_votes]
        prompt = (
            f'Classify the architecture layer of module "{module_name}" (path: {module_path}).\n'
            f"Prior signals: {prior_summary}\n"
            f"Choose exactly one: {', '.join(LAYERS)}.\n"
            'Return JSON: {"layer": "...", "reason": "..."}'
        )
        messages = [{"role": "user", "content": prompt}]

        try:
            from wiki.token_budget import resolve_max_tokens

            max_tokens = resolve_max_tokens(self._budget_resolver, "arch_classify")
            response = await self._llm.complete_json(messages, _LLM_SCHEMA, max_tokens=max_tokens)
            layer = str(response.get("layer") or "").lower()
            if layer not in LAYERS:
                return LayerVote(layer="unknown", confidence=0.0, signal="llm")
            return LayerVote(layer=layer, confidence=0.6, signal="llm")
        except Exception:
            log.warning(
                "architecture_classifier_llm_failed",
                module_name=module_name,
                exc_info=True,
            )
            return LayerVote(layer="unknown", confidence=0.0, signal="llm")

    def _aggregate(self, votes: list[LayerVote]) -> LayerResult:
        scores: dict[str, float] = defaultdict(float)
        for vote in votes:
            if vote.layer != "unknown":
                weight = self.SIGNAL_WEIGHTS.get(vote.signal, 0.0)
                scores[vote.layer] += weight * vote.confidence

        if not scores:
            return LayerResult(layer="service", confidence=0.0, votes=votes)

        best_layer = max(scores, key=scores.get)
        total_weight = sum(
            self.SIGNAL_WEIGHTS.get(vote.signal, 0.0)
            for vote in votes
            if vote.layer != "unknown"
        )
        confidence = scores[best_layer] / total_weight if total_weight > 0 else 0.0
        return LayerResult(layer=best_layer, confidence=confidence, votes=votes)
