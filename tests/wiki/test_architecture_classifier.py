"""Tests for multi-signal architecture layer classifier."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import AppWikiFlags
from wiki.architecture_classifier import (
    ENRICHER_LAYERS,
    LAYERS,
    ArchitectureLayerClassifier,
    LayerResult,
    LayerVote,
    _ENRICHER_TO_CLASSIFIER,
)


@pytest.fixture
def config() -> AppWikiFlags:
    return AppWikiFlags()


@pytest.fixture
def store() -> MagicMock:
    mock = MagicMock()
    mock.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    return mock


@pytest.fixture
def classifier(config: AppWikiFlags, store: MagicMock) -> ArchitectureLayerClassifier:
    return ArchitectureLayerClassifier(config=config, graph_store=store)


class TestEnricherMapping:
    @pytest.mark.parametrize(
        ("enricher_layer", "classifier_layer"),
        [
            ("presentation", "api"),
            ("rpc", "api"),
            ("business", "service"),
            ("data_access", "data"),
            ("model", "data"),
            ("infrastructure", "infrastructure"),
            ("messaging", "infrastructure"),
            ("testing", "infrastructure"),
            ("util", "infrastructure"),
        ],
    )
    def test_enricher_to_classifier_mapping(self, enricher_layer: str, classifier_layer: str) -> None:
        assert _ENRICHER_TO_CLASSIFIER[enricher_layer] == classifier_layer

    def test_mapping_covers_all_enricher_layers(self) -> None:
        assert set(_ENRICHER_TO_CLASSIFIER.keys()) == set(ENRICHER_LAYERS)

    def test_classifier_layers(self) -> None:
        assert LAYERS == ("api", "service", "data", "infrastructure")


class TestAnnotationSignal:
    @pytest.mark.asyncio
    async def test_majority_vote(self, classifier: ArchitectureLayerClassifier, store: MagicMock) -> None:
        store.execute_query = AsyncMock(
            return_value=MagicMock(
                data=[
                    {"layer": "presentation"},
                    {"layer": "presentation"},
                    {"layer": "business"},
                ]
            )
        )
        vote = await classifier._vote_by_annotations("UserController")
        assert vote.layer == "api"
        assert vote.confidence > 0
        assert vote.signal == "annotation"

    @pytest.mark.asyncio
    async def test_no_classes_returns_unknown(self, classifier: ArchitectureLayerClassifier, store: MagicMock) -> None:
        store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        vote = await classifier._vote_by_annotations("EmptyModule")
        assert vote.layer == "unknown"
        assert vote.confidence == 0.0
        assert vote.signal == "annotation"

    @pytest.mark.asyncio
    async def test_annotation_small_sample_dampened(
        self, classifier: ArchitectureLayerClassifier, store: MagicMock
    ) -> None:
        """A single annotated class should not yield confidence 1.0."""
        store.execute_query = AsyncMock(return_value=MagicMock(data=[{"layer": "presentation"}]))
        vote = await classifier._vote_by_annotations("SingleClassModule")
        assert vote.layer == "api"
        assert vote.confidence < 1.0
        assert vote.confidence == pytest.approx(1 / 3)
        assert vote.signal == "annotation"


class TestTopologySignal:
    @pytest.mark.asyncio
    async def test_high_fan_in_returns_api(self, classifier: ArchitectureLayerClassifier, store: MagicMock) -> None:
        store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[{"fan_in": 8}]),
                MagicMock(data=[{"fan_out": 1}]),
            ]
        )
        vote = await classifier._vote_by_topology("ApiModule")
        assert vote.layer == "api"
        assert vote.confidence == pytest.approx(0.9)
        assert vote.signal == "topology"

    @pytest.mark.asyncio
    async def test_high_fan_out_returns_data(self, classifier: ArchitectureLayerClassifier, store: MagicMock) -> None:
        store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[{"fan_in": 1}]),
                MagicMock(data=[{"fan_out": 8}]),
            ]
        )
        vote = await classifier._vote_by_topology("DataModule")
        assert vote.layer == "data"
        assert vote.confidence == pytest.approx(0.9)
        assert vote.signal == "topology"

    @pytest.mark.asyncio
    async def test_low_total_returns_unknown(self, classifier: ArchitectureLayerClassifier, store: MagicMock) -> None:
        store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[{"fan_in": 1}]),
                MagicMock(data=[{"fan_out": 1}]),
            ]
        )
        vote = await classifier._vote_by_topology("IsolatedModule")
        assert vote.layer == "unknown"
        assert vote.confidence == 0.0
        assert vote.signal == "topology"

    @pytest.mark.asyncio
    async def test_balanced_returns_service(self, classifier: ArchitectureLayerClassifier, store: MagicMock) -> None:
        store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[{"fan_in": 4}]),
                MagicMock(data=[{"fan_out": 4}]),
            ]
        )
        vote = await classifier._vote_by_topology("ServiceModule")
        assert vote.layer == "service"
        assert vote.confidence == pytest.approx(0.8)
        assert vote.signal == "topology"


class TestPathPatternSignal:
    def test_api_path_match(self, classifier: ArchitectureLayerClassifier) -> None:
        vote = classifier._vote_by_path("src/main/java/com/app/controller/UserController.java")
        assert vote.layer == "api"
        assert vote.confidence == 0.8
        assert vote.signal == "path_pattern"

    def test_service_path_match(self, classifier: ArchitectureLayerClassifier) -> None:
        vote = classifier._vote_by_path("src/service/UserService.java")
        assert vote.layer == "service"
        assert vote.confidence == 0.8

    def test_data_path_match(self, classifier: ArchitectureLayerClassifier) -> None:
        vote = classifier._vote_by_path("src/repository/UserRepository.java")
        assert vote.layer == "data"
        assert vote.confidence == 0.8

    def test_infrastructure_path_match(self, classifier: ArchitectureLayerClassifier) -> None:
        vote = classifier._vote_by_path("src/config/AppConfig.java")
        assert vote.layer == "infrastructure"
        assert vote.confidence == 0.8

    def test_no_match_returns_unknown(self, classifier: ArchitectureLayerClassifier) -> None:
        vote = classifier._vote_by_path("src/xyz/Foo.java")
        assert vote.layer == "unknown"
        assert vote.confidence == 0.0

    def test_custom_config_override(self, store: MagicMock) -> None:
        cfg = AppWikiFlags(
            architecture_layer_patterns={
                "api": ["gateway/"],
                "service": [],
                "data": [],
                "infrastructure": [],
            }
        )
        clf = ArchitectureLayerClassifier(config=cfg, graph_store=store)
        vote = clf._vote_by_path("src/gateway/ApiGateway.java")
        assert vote.layer == "api"
        assert vote.confidence == 0.8


class TestAggregation:
    def test_weighted_voting_mixed_signals(self, classifier: ArchitectureLayerClassifier) -> None:
        votes = [
            LayerVote(layer="api", confidence=1.0, signal="annotation"),
            LayerVote(layer="service", confidence=1.0, signal="topology"),
            LayerVote(layer="api", confidence=0.8, signal="path_pattern"),
        ]
        result = classifier._aggregate(votes)
        assert result.layer == "api"
        assert result.confidence > 0
        assert result.votes == votes

    def test_all_unknown_returns_service_zero_confidence(self, classifier: ArchitectureLayerClassifier) -> None:
        votes = [
            LayerVote(layer="unknown", confidence=0.0, signal="annotation"),
            LayerVote(layer="unknown", confidence=0.0, signal="topology"),
            LayerVote(layer="unknown", confidence=0.0, signal="path_pattern"),
        ]
        result = classifier._aggregate(votes)
        assert result.layer == "service"
        assert result.confidence == 0.0


class TestLLMTiebreak:
    @pytest.mark.asyncio
    async def test_llm_triggered_when_low_confidence(
        self, config: AppWikiFlags, store: MagicMock
    ) -> None:
        llm = MagicMock()
        llm.complete_json = AsyncMock(return_value={"layer": "data", "reason": "repo pattern"})
        clf = ArchitectureLayerClassifier(config=config, graph_store=store, llm=llm)

        store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        result = await clf.classify_module("AmbiguousModule", "src/xyz/Foo.java")

        llm.complete_json.assert_awaited_once()
        assert any(v.signal == "llm" for v in result.votes)
        assert result.layer == "data"

    @pytest.mark.asyncio
    async def test_llm_not_triggered_when_high_confidence(
        self, config: AppWikiFlags, store: MagicMock
    ) -> None:
        llm = MagicMock()
        llm.complete_json = AsyncMock(return_value={"layer": "data", "reason": "should not run"})
        clf = ArchitectureLayerClassifier(config=config, graph_store=store, llm=llm)

        store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[{"layer": "presentation"}, {"layer": "presentation"}]),
                MagicMock(data=[{"fan_in": 8}]),
                MagicMock(data=[{"fan_out": 1}]),
            ]
        )
        result = await clf.classify_module("UserController", "src/controller/UserController.java")

        llm.complete_json.assert_not_awaited()
        assert not any(v.signal == "llm" for v in result.votes)
        assert result.layer == "api"
        assert result.confidence >= 0.5

    @pytest.mark.asyncio
    async def test_llm_exception_returns_unknown(self, config: AppWikiFlags, store: MagicMock) -> None:
        llm = MagicMock()
        llm.complete_json = AsyncMock(side_effect=RuntimeError("LLM down"))
        clf = ArchitectureLayerClassifier(config=config, graph_store=store, llm=llm)
        store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

        vote = await clf._vote_by_llm("Mod", "src/xyz/Foo.java", [])
        assert vote.layer == "unknown"
        assert vote.confidence == 0.0
        assert vote.signal == "llm"


class TestClassifyModule:
    @pytest.mark.asyncio
    async def test_classify_module_end_to_end(self, config: AppWikiFlags, store: MagicMock) -> None:
        store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[{"layer": "business"}, {"layer": "business"}]),
                MagicMock(data=[{"fan_in": 4}]),
                MagicMock(data=[{"fan_out": 4}]),
            ]
        )
        clf = ArchitectureLayerClassifier(config=config, graph_store=store)
        result = await clf.classify_module("UserService", "src/service/UserService.java")

        assert isinstance(result, LayerResult)
        assert result.layer == "service"
        assert result.confidence > 0
        assert len(result.votes) == 3
        assert {v.signal for v in result.votes} == {"annotation", "topology", "path_pattern"}


class TestBatchClassification:
    """Tests for batch classification (3 queries instead of 3*N)."""

    @pytest.mark.asyncio
    async def test_batch_annotations_single_query(
        self, config: AppWikiFlags, store: MagicMock
    ) -> None:
        """Batch annotations should issue ONE query for all modules."""
        store.execute_query = AsyncMock(
            return_value=MagicMock(data=[
                {"module_name": "UserCtrl", "layer": "presentation"},
                {"module_name": "UserCtrl", "layer": "presentation"},
                {"module_name": "UserRepo", "layer": "data_access"},
            ])
        )
        clf = ArchitectureLayerClassifier(config=config, graph_store=store)
        votes = await clf._batch_vote_by_annotations(["UserCtrl", "UserRepo", "EmptyMod"])

        # Only 1 query call
        assert store.execute_query.await_count == 1
        assert votes["UserCtrl"].layer == "api"
        assert votes["UserRepo"].layer == "data"
        assert votes["EmptyMod"].layer == "unknown"

    @pytest.mark.asyncio
    async def test_batch_topology_two_queries(
        self, config: AppWikiFlags, store: MagicMock
    ) -> None:
        """Batch topology should issue exactly 2 queries (fan_in + fan_out)."""
        store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(data=[
                    {"module_name": "ApiMod", "fan_in": 8},
                    {"module_name": "DataMod", "fan_in": 1},
                ]),
                MagicMock(data=[
                    {"module_name": "ApiMod", "fan_out": 1},
                    {"module_name": "DataMod", "fan_out": 8},
                ]),
            ]
        )
        clf = ArchitectureLayerClassifier(config=config, graph_store=store)
        fan_in_map, fan_out_map = await clf._batch_vote_by_topology(["ApiMod", "DataMod"])

        assert store.execute_query.await_count == 2
        assert fan_in_map["ApiMod"] == 8
        assert fan_out_map["DataMod"] == 8

    @pytest.mark.asyncio
    async def test_classify_modules_batch_end_to_end(
        self, config: AppWikiFlags, store: MagicMock
    ) -> None:
        """Full batch classification uses 3 total queries."""
        call_count = 0

        async def mock_query(query, params=None):
            nonlocal call_count
            call_count += 1
            if "architecture_layer" in query:
                return MagicMock(data=[
                    {"module_name": "UserService", "layer": "business"},
                    {"module_name": "UserService", "layer": "business"},
                ])
            elif "fan_in" in query.split("RETURN")[1]:
                return MagicMock(data=[
                    {"module_name": "UserService", "fan_in": 4},
                ])
            else:
                return MagicMock(data=[
                    {"module_name": "UserService", "fan_out": 4},
                ])

        store.execute_query = AsyncMock(side_effect=mock_query)
        clf = ArchitectureLayerClassifier(config=config, graph_store=store)
        results = await clf.classify_modules_batch([
            ("UserService", "src/service/UserService.java"),
        ])

        assert call_count == 3  # 1 annotation + 2 topology
        assert "UserService" in results
        assert results["UserService"].layer == "service"

    @pytest.mark.asyncio
    async def test_batch_empty_modules(
        self, config: AppWikiFlags, store: MagicMock
    ) -> None:
        """Empty input should return empty results without any queries."""
        clf = ArchitectureLayerClassifier(config=config, graph_store=store)
        results = await clf.classify_modules_batch([])

        assert results == {}
        store.execute_query.assert_not_awaited()

    def test_compute_topology_vote_high_fan_in(self) -> None:
        vote = ArchitectureLayerClassifier._compute_topology_vote(8, 1)
        assert vote.layer == "api"
        assert vote.confidence == pytest.approx(0.9)

    def test_compute_topology_vote_high_fan_out(self) -> None:
        vote = ArchitectureLayerClassifier._compute_topology_vote(1, 8)
        assert vote.layer == "data"
        assert vote.confidence == pytest.approx(0.9)

    def test_compute_topology_vote_balanced(self) -> None:
        vote = ArchitectureLayerClassifier._compute_topology_vote(4, 4)
        assert vote.layer == "service"

    def test_compute_topology_vote_low_total(self) -> None:
        vote = ArchitectureLayerClassifier._compute_topology_vote(1, 1)
        assert vote.layer == "unknown"
        assert vote.confidence == 0.0
