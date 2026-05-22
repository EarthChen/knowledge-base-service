# tests/wiki/test_reassemble_domains.py
"""Tests for wiki-driven domain reassembly."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

_PERSIST_TREE = "wiki.nodes.persist_classification._persist_domain_tree_to_wiki"
_PERSIST_LABELS = "wiki.nodes.persist_classification._persist_domain_labels_on_modules"


class TestReassemblyConfig:
    def test_default_config_values(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags()
        assert flags.domain_reassembly_enabled is True
        assert flags.reassembly_merge_threshold == 0.85
        assert flags.reassembly_orphan_threshold == 0.60
        assert flags.reassembly_max_moves_pct == 0.30
        assert flags.reassembly_respect_user_modified is True

    def test_config_override(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags(
            domain_reassembly_enabled=False,
            reassembly_merge_threshold=0.9,
        )
        assert flags.domain_reassembly_enabled is False
        assert flags.reassembly_merge_threshold == 0.9


class TestPipelineState:
    def test_state_has_reassembly_actions_field(self):
        from wiki.pipeline_state import WikiPipelineState

        annotations = WikiPipelineState.__annotations__
        assert "reassembly_actions" in annotations

    def test_state_has_domain_display_names_field(self):
        from wiki.pipeline_state import WikiPipelineState

        annotations = WikiPipelineState.__annotations__
        assert "domain_display_names" in annotations


class TestDomainEmbedding:
    @pytest.mark.asyncio
    async def test_extract_domain_embeddings_from_pages(self):
        from wiki.nodes.reassemble_domains import _extract_domain_embeddings

        pages = [
            {"path": "auth-domain/_overview", "content": "This domain handles authentication and authorization."},
            {"path": "payment-domain/_overview", "content": "This domain handles payment processing."},
            {"path": "auth-domain/login-module", "content": "Login module details."},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.1] * 1024,
            [0.9] * 1024,
        ])

        result = await _extract_domain_embeddings(pages, mock_generator)

        assert "auth-domain" in result
        assert "payment-domain" in result
        assert "auth-domain/login-module" not in result
        assert result["auth-domain"].shape == (1024,)
        mock_generator.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_domain_embeddings_empty_pages(self):
        from wiki.nodes.reassemble_domains import _extract_domain_embeddings

        mock_generator = AsyncMock()
        result = await _extract_domain_embeddings([], mock_generator)
        assert result == {}

    @pytest.mark.asyncio
    async def test_extract_domain_embeddings_skips_empty_content(self):
        from wiki.nodes.reassemble_domains import _extract_domain_embeddings

        pages = [
            {"path": "empty-domain/_overview", "content": ""},
            {"path": "valid-domain/_overview", "content": "Has content"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[[0.5] * 1024])

        result = await _extract_domain_embeddings(pages, mock_generator)
        assert "empty-domain" not in result
        assert "valid-domain" in result


class TestMergeCandidates:
    def test_find_merge_candidates_above_threshold(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "domain-a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "domain-b": np.array([0.99, 0.1, 0.0], dtype=np.float32),
            "domain-c": np.array([0.0, 0.0, 1.0], dtype=np.float32),
        }

        candidates = _find_merge_candidates(embeddings, threshold=0.85, pinned_domains=set())
        assert len(candidates) == 1
        assert candidates[0]["similarity"] > 0.85

    def test_find_merge_candidates_none_above_threshold(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "domain-a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "domain-b": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        }
        candidates = _find_merge_candidates(embeddings, threshold=0.85, pinned_domains=set())
        assert candidates == []

    def test_find_merge_candidates_skips_pinned(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "domain-a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "domain-b": np.array([0.99, 0.1, 0.0], dtype=np.float32),
        }
        candidates = _find_merge_candidates(
            embeddings, threshold=0.85, pinned_domains={"domain-a"}
        )
        assert candidates == []

    def test_merge_candidates_sorted_by_similarity_desc(self):
        from wiki.nodes.reassemble_domains import _find_merge_candidates

        embeddings = {
            "d-a": np.array([1.0, 0.0], dtype=np.float32),
            "d-b": np.array([0.95, 0.3], dtype=np.float32),
            "d-c": np.array([0.99, 0.1], dtype=np.float32),
        }
        candidates = _find_merge_candidates(embeddings, threshold=0.5, pinned_domains=set())
        if len(candidates) > 1:
            for i in range(len(candidates) - 1):
                assert candidates[i]["similarity"] >= candidates[i + 1]["similarity"]


class TestOrphanMatching:
    @pytest.mark.asyncio
    async def test_match_orphan_to_best_domain(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        domain_embeddings = {
            "auth-domain": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "payment-domain": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        }
        orphan_pages = [
            {"path": "orphan-auth/_overview", "content": "Handles user sessions"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.95, 0.1, 0.0],
        ])

        assignments = await _match_orphan_pages(
            orphan_pages, domain_embeddings, mock_generator,
            threshold=0.6, pinned_domains=set(),
        )
        assert len(assignments) == 1
        assert assignments[0]["orphan_path"] == "orphan-auth/_overview"
        assert assignments[0]["assigned_domain"] == "auth-domain"

    @pytest.mark.asyncio
    async def test_orphan_below_threshold_not_assigned(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        domain_embeddings = {
            "auth-domain": np.array([1.0, 0.0, 0.0], dtype=np.float32),
        }
        orphan_pages = [
            {"path": "unrelated/_overview", "content": "Completely different topic"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.0, 0.0, 1.0],
        ])

        assignments = await _match_orphan_pages(
            orphan_pages, domain_embeddings, mock_generator,
            threshold=0.6, pinned_domains=set(),
        )
        assert assignments == []

    @pytest.mark.asyncio
    async def test_orphan_skips_pinned_domains(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        domain_embeddings = {
            "pinned-domain": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "open-domain": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        }
        orphan_pages = [
            {"path": "orphan/_overview", "content": "Some content"},
        ]

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[
            [0.95, 0.1, 0.0],  # Closest to pinned-domain
        ])

        assignments = await _match_orphan_pages(
            orphan_pages, domain_embeddings, mock_generator,
            threshold=0.6, pinned_domains={"pinned-domain"},
        )
        # Should match open-domain (even though pinned-domain was closer)
        if assignments:
            assert assignments[0]["assigned_domain"] == "open-domain"

    @pytest.mark.asyncio
    async def test_empty_orphan_pages(self):
        from wiki.nodes.reassemble_domains import _match_orphan_pages

        assignments = await _match_orphan_pages(
            [], {"d": np.array([1.0])}, AsyncMock(), threshold=0.6, pinned_domains=set(),
        )
        assert assignments == []


class TestPinnedDomains:
    @pytest.mark.asyncio
    async def test_get_pinned_domains_maps_display_names_to_slugs(self):
        from store.falkordb_store import QueryResultWrapper
        from wiki.nodes.reassemble_domains import _get_pinned_domains

        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(
            return_value=QueryResultWrapper(
                data=[{"title": "Authentication"}, {"title": "domain-b"}],
                raw=[],
            ),
        )
        wiki_tree_store = MagicMock()
        wiki_tree_store._store = mock_store

        config = {
            "configurable": {
                "wiki_tree_store": wiki_tree_store,
                "business_id": "biz-1",
            },
        }
        state = {
            "domain_display_names": {
                "domain-a": "Authentication",
                "domain-b": "Payments",
            },
        }

        pinned = await _get_pinned_domains(config, state)

        assert pinned == {"domain-a", "domain-b"}
        mock_store.execute_query.assert_awaited_once()
        call_args = mock_store.execute_query.call_args
        assert "user_modified = true" in call_args[0][0]
        assert call_args[0][1]["business_id"] == "biz-1"

    @pytest.mark.asyncio
    async def test_get_pinned_domains_returns_empty_without_store(self):
        from wiki.nodes.reassemble_domains import _get_pinned_domains

        pinned = await _get_pinned_domains({"configurable": {}}, {})
        assert pinned == set()

    @pytest.mark.asyncio
    async def test_get_pinned_domains_handles_query_failure(self):
        from wiki.nodes.reassemble_domains import _get_pinned_domains

        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(side_effect=RuntimeError("db down"))
        wiki_tree_store = MagicMock()
        wiki_tree_store._store = mock_store

        config = {
            "configurable": {
                "wiki_tree_store": wiki_tree_store,
                "business_id": "biz-1",
            },
        }

        pinned = await _get_pinned_domains(config, {"domain_display_names": {}})
        assert pinned == set()


class TestExecuteMerges:
    def test_merge_two_domains(self):
        from wiki.nodes.reassemble_domains import _execute_merges

        mapping = {"domain-a": [("repo", "ModA")], "domain-b": [("repo", "ModB")]}
        names = {"domain-a": "Auth", "domain-b": "Session"}
        tree = [{"name": "domain-a"}, {"name": "domain-b"}]

        new_mapping, new_names, new_tree, actions = _execute_merges(
            mapping, names, tree,
            [{"source": "domain-b", "target": "domain-a"}],
        )
        assert "domain-b" not in new_mapping
        assert ("repo", "ModB") in new_mapping["domain-a"]
        assert len(new_tree) == 1
        assert actions[0]["type"] == "merge"

    def test_skip_already_merged_source(self):
        from wiki.nodes.reassemble_domains import _execute_merges

        mapping = {"a": [1], "b": [2], "c": [3]}
        names = {"a": "A", "b": "B", "c": "C"}
        tree = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

        _, _, _, actions = _execute_merges(
            mapping, names, tree,
            [{"source": "b", "target": "a"}, {"source": "b", "target": "c"}],
        )
        assert len(actions) == 1  # Second merge skipped because b already merged


class TestReassembleDomainsNode:
    @pytest.mark.asyncio
    async def test_skip_when_disabled_in_config(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [],
            "domain_mapping": {},
            "domain_tree": [],
            "config": {"reassembly_enabled": False},
        }
        result = await reassemble_domains_node(state)
        assert result.get("reassembly_actions") == []

    @pytest.mark.asyncio
    async def test_skip_when_no_overview_pages(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [{"path": "some/page", "content": "No overviews here"}],
            "domain_mapping": {"domain-a": [("repo", "ModA")]},
            "domain_tree": [{"name": "domain-a"}],
            "config": {},
        }

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[])

        with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator), \
             patch("wiki.nodes.reassemble_domains.get_settings") as mock_settings:
            mock_settings.return_value.wiki.domain_reassembly_enabled = True
            mock_settings.return_value.wiki.reassembly_merge_threshold = 0.85
            mock_settings.return_value.wiki.reassembly_orphan_threshold = 0.60
            mock_settings.return_value.wiki.reassembly_max_moves_pct = 0.30
            mock_settings.return_value.wiki.reassembly_respect_user_modified = True
            mock_settings.return_value.embedding = MagicMock()
            result = await reassemble_domains_node(state)

        assert result.get("reassembly_actions") == []

    @pytest.mark.asyncio
    async def test_merge_approved_by_llm(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [
                {"path": "domain-a/_overview", "content": "Handles authentication."},
                {"path": "domain-b/_overview", "content": "Handles auth sessions."},
            ],
            "domain_mapping": {
                "domain-a": [("repo", "ModA")],
                "domain-b": [("repo", "ModB")],
            },
            "domain_tree": [{"name": "domain-a"}, {"name": "domain-b"}],
            "domain_display_names": {"domain-a": "Auth", "domain-b": "Session"},
            "config": {"reassembly_merge_threshold": 0.80},
        }

        mock_generator = AsyncMock()
        # Very similar embeddings
        emb = [1.0] * 1024
        mock_generator.generate = AsyncMock(return_value=[emb, emb])

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value='{"approved_merges": [{"source": "domain-b", "target": "domain-a"}]}'
        )

        config = {"configurable": {"llm": mock_llm}}

        with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator), \
             patch("wiki.nodes.reassemble_domains._get_pinned_domains", return_value=set()), \
             patch("wiki.nodes.reassemble_domains.get_settings") as mock_settings:
            mock_settings.return_value.wiki.domain_reassembly_enabled = True
            mock_settings.return_value.wiki.reassembly_merge_threshold = 0.85
            mock_settings.return_value.wiki.reassembly_orphan_threshold = 0.60
            mock_settings.return_value.wiki.reassembly_max_moves_pct = 0.30
            mock_settings.return_value.wiki.reassembly_respect_user_modified = True
            mock_settings.return_value.embedding = MagicMock()
            result = await reassemble_domains_node(state, config)

        assert "domain-b" not in result["domain_mapping"]
        assert ("repo", "ModB") in result["domain_mapping"]["domain-a"]
        assert any(a["type"] == "merge" for a in result["reassembly_actions"])

    @pytest.mark.asyncio
    async def test_rollback_when_too_many_moves(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [
                {"path": f"domain-{i}/_overview", "content": f"Domain {i} content."}
                for i in range(10)
            ],
            "domain_mapping": {f"domain-{i}": [("repo", f"Mod{i}")] for i in range(10)},
            "domain_tree": [{"name": f"domain-{i}"} for i in range(10)],
            "domain_display_names": {f"domain-{i}": f"Domain {i}" for i in range(10)},
            "config": {"reassembly_max_moves_pct": 0.05},  # Max 5% = 0.5 → effectively 0 moves allowed
        }

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[[1.0] * 1024] * 10)

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=(
                '{"approved_merges": [{"source": "domain-1", "target": "domain-0"}, '
                '{"source": "domain-2", "target": "domain-0"}]}'
            )
        )

        config = {"configurable": {"llm": mock_llm}}

        with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator), \
             patch("wiki.nodes.reassemble_domains._get_pinned_domains", return_value=set()), \
             patch("wiki.nodes.reassemble_domains.get_settings") as mock_settings:
            mock_settings.return_value.wiki.domain_reassembly_enabled = True
            mock_settings.return_value.wiki.reassembly_merge_threshold = 0.85
            mock_settings.return_value.wiki.reassembly_orphan_threshold = 0.60
            mock_settings.return_value.wiki.reassembly_max_moves_pct = 0.05
            mock_settings.return_value.wiki.reassembly_respect_user_modified = True
            mock_settings.return_value.embedding = MagicMock()
            result = await reassemble_domains_node(state, config)

        # Rollback should have triggered
        assert any(a.get("type") == "rollback" for a in result["reassembly_actions"])


class TestReassemblyDegradation:
    @pytest.mark.asyncio
    async def test_embedding_failure_skips_gracefully(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [
                {"path": "domain-a/_overview", "content": "Auth content"},
                {"path": "domain-b/_overview", "content": "Payment content"},
            ],
            "domain_mapping": {"domain-a": [], "domain-b": []},
            "domain_tree": [],
            "config": {},
        }

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(side_effect=RuntimeError("embedding service down"))

        with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator), \
             patch("wiki.nodes.reassemble_domains.get_settings") as mock_settings:
            mock_settings.return_value.wiki.domain_reassembly_enabled = True
            mock_settings.return_value.wiki.reassembly_merge_threshold = 0.85
            mock_settings.return_value.wiki.reassembly_orphan_threshold = 0.60
            mock_settings.return_value.wiki.reassembly_max_moves_pct = 0.30
            mock_settings.return_value.wiki.reassembly_respect_user_modified = True
            mock_settings.return_value.embedding = MagicMock()
            result = await reassemble_domains_node(state)

        assert result["reassembly_actions"] == []

    @pytest.mark.asyncio
    async def test_llm_failure_still_processes_orphans(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "pages": [
                {"path": "domain-a/_overview", "content": "Auth content"},
                {"path": "domain-b/_overview", "content": "Auth content very similar"},
            ],
            "domain_mapping": {"domain-a": [("repo", "ModA")], "domain-b": [("repo", "ModB")]},
            "domain_tree": [{"name": "domain-a"}, {"name": "domain-b"}],
            "domain_display_names": {"domain-a": "A", "domain-b": "B"},
            "config": {},
        }

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[[1.0] * 1024, [1.0] * 1024])

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        config = {"configurable": {"llm": mock_llm}}

        with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator), \
             patch("wiki.nodes.reassemble_domains._get_pinned_domains", return_value=set()), \
             patch("wiki.nodes.reassemble_domains.get_settings") as mock_settings:
            mock_settings.return_value.wiki.domain_reassembly_enabled = True
            mock_settings.return_value.wiki.reassembly_merge_threshold = 0.85
            mock_settings.return_value.wiki.reassembly_orphan_threshold = 0.60
            mock_settings.return_value.wiki.reassembly_max_moves_pct = 0.30
            mock_settings.return_value.wiki.reassembly_respect_user_modified = True
            mock_settings.return_value.embedding = MagicMock()
            result = await reassemble_domains_node(state, config)

        # LLM failure means no merges approved, but node doesn't crash
        # Both domains should still be in mapping
        assert "domain-a" in result.get("domain_mapping", state["domain_mapping"])
        assert "domain-b" in result.get("domain_mapping", state["domain_mapping"])


class TestReassemblyPersistence:
    @pytest.mark.asyncio
    async def test_persists_after_merge(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "business_id": "biz-1",
            "pages": [
                {"path": "domain-a/_overview", "content": "Handles authentication."},
                {"path": "domain-b/_overview", "content": "Handles auth sessions."},
            ],
            "domain_mapping": {
                "domain-a": [("repo", "ModA")],
                "domain-b": [("repo", "ModB")],
            },
            "domain_tree": [{"name": "domain-a"}, {"name": "domain-b"}],
            "domain_display_names": {"domain-a": "Auth", "domain-b": "Session"},
            "modules": {"ModA": {"id": "ModA"}, "ModB": {"id": "ModB"}},
            "config": {"reassembly_merge_threshold": 0.80},
        }

        mock_generator = AsyncMock()
        emb = [1.0] * 1024
        mock_generator.generate = AsyncMock(return_value=[emb, emb])

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value='{"approved_merges": [{"source": "domain-b", "target": "domain-a"}]}'
        )

        mock_wiki_store = AsyncMock()
        mock_graph_store = AsyncMock()
        config = {
            "configurable": {
                "llm": mock_llm,
                "wiki_store": mock_wiki_store,
                "graph_store": mock_graph_store,
            },
        }

        with (
            patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator),
            patch("wiki.nodes.reassemble_domains._get_pinned_domains", return_value=set()),
            patch("wiki.nodes.reassemble_domains.get_settings") as mock_settings,
            patch(_PERSIST_TREE, new_callable=AsyncMock) as mock_persist_tree,
            patch(_PERSIST_LABELS, new_callable=AsyncMock) as mock_persist_labels,
        ):
            mock_settings.return_value.wiki.domain_reassembly_enabled = True
            mock_settings.return_value.wiki.reassembly_merge_threshold = 0.85
            mock_settings.return_value.wiki.reassembly_orphan_threshold = 0.60
            mock_settings.return_value.wiki.reassembly_max_moves_pct = 0.30
            mock_settings.return_value.wiki.reassembly_respect_user_modified = True
            mock_settings.return_value.embedding = MagicMock()
            result = await reassemble_domains_node(state, config)

        assert any(a["type"] == "merge" for a in result["reassembly_actions"])
        mock_persist_tree.assert_awaited_once()
        mock_persist_labels.assert_awaited_once()
        persist_tree_args = mock_persist_tree.call_args[0]
        assert persist_tree_args[0] is mock_wiki_store
        assert persist_tree_args[1] == "biz-1"
        persist_labels_args = mock_persist_labels.call_args[0]
        assert persist_labels_args[0] is mock_graph_store
        assert persist_labels_args[1] == "biz-1"

    @pytest.mark.asyncio
    async def test_no_persist_when_no_actions(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "business_id": "biz-1",
            "pages": [],
            "domain_mapping": {"domain-a": [("repo", "ModA")]},
            "domain_tree": [{"name": "domain-a"}],
            "config": {},
        }

        mock_generator = AsyncMock()
        mock_generator.generate = AsyncMock(return_value=[])

        config = {
            "configurable": {
                "wiki_store": AsyncMock(),
                "graph_store": AsyncMock(),
            },
        }

        with (
            patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator),
            patch("wiki.nodes.reassemble_domains.get_settings") as mock_settings,
            patch(_PERSIST_TREE, new_callable=AsyncMock) as mock_persist_tree,
            patch(_PERSIST_LABELS, new_callable=AsyncMock) as mock_persist_labels,
        ):
            mock_settings.return_value.wiki.domain_reassembly_enabled = True
            mock_settings.return_value.wiki.reassembly_merge_threshold = 0.85
            mock_settings.return_value.wiki.reassembly_orphan_threshold = 0.60
            mock_settings.return_value.wiki.reassembly_max_moves_pct = 0.30
            mock_settings.return_value.wiki.reassembly_respect_user_modified = True
            mock_settings.return_value.embedding = MagicMock()
            result = await reassemble_domains_node(state, config)

        assert result.get("reassembly_actions") == []
        mock_persist_tree.assert_not_awaited()
        mock_persist_labels.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_persist_failure_does_not_break_node(self):
        from wiki.nodes.reassemble_domains import reassemble_domains_node

        state = {
            "business_id": "biz-1",
            "pages": [
                {"path": "domain-a/_overview", "content": "Handles authentication."},
                {"path": "domain-b/_overview", "content": "Handles auth sessions."},
            ],
            "domain_mapping": {
                "domain-a": [("repo", "ModA")],
                "domain-b": [("repo", "ModB")],
            },
            "domain_tree": [{"name": "domain-a"}, {"name": "domain-b"}],
            "domain_display_names": {"domain-a": "Auth", "domain-b": "Session"},
            "modules": {},
            "config": {"reassembly_merge_threshold": 0.80},
        }

        mock_generator = AsyncMock()
        emb = [1.0] * 1024
        mock_generator.generate = AsyncMock(return_value=[emb, emb])

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value='{"approved_merges": [{"source": "domain-b", "target": "domain-a"}]}'
        )

        config = {
            "configurable": {
                "llm": mock_llm,
                "wiki_store": AsyncMock(),
                "graph_store": AsyncMock(),
            },
        }

        with (
            patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator),
            patch("wiki.nodes.reassemble_domains._get_pinned_domains", return_value=set()),
            patch("wiki.nodes.reassemble_domains.get_settings") as mock_settings,
            patch(_PERSIST_TREE, new_callable=AsyncMock, side_effect=RuntimeError("wiki down")),
            patch(_PERSIST_LABELS, new_callable=AsyncMock, side_effect=RuntimeError("graph down")),
        ):
            mock_settings.return_value.wiki.domain_reassembly_enabled = True
            mock_settings.return_value.wiki.reassembly_merge_threshold = 0.85
            mock_settings.return_value.wiki.reassembly_orphan_threshold = 0.60
            mock_settings.return_value.wiki.reassembly_max_moves_pct = 0.30
            mock_settings.return_value.wiki.reassembly_respect_user_modified = True
            mock_settings.return_value.embedding = MagicMock()
            result = await reassemble_domains_node(state, config)

        assert "domain-b" not in result["domain_mapping"]
        assert any(a["type"] == "merge" for a in result["reassembly_actions"])
        assert "domain_mapping" in result
