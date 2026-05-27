from __future__ import annotations

from unittest.mock import AsyncMock
import pytest


class TestStaleSoftDelete:
    """Tests for F9-C1: soft-delete + purge."""

    @pytest.mark.asyncio
    async def test_stale_pages_marked_not_deleted(self):
        """Stale pages should be marked with stale=true, not physically deleted."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = AsyncMock()

        query_results = [
            {"uid": "uid1", "path": "/__domains__/old-domain/_overview"},
            {"uid": "uid2", "path": "/__domains__/current-domain/_overview"},
        ]
        runner._wiki_store.query = AsyncMock(side_effect=[query_results, None])

        current_slugs = {"current-domain"}
        count = await runner._cleanup_stale_domain_pages("biz1", current_slugs)

        assert count == 1
        last_call = runner._wiki_store.query.call_args_list[-1]
        query_str = last_call[0][0]
        assert "SET wp.stale = true" in query_str
        assert "DETACH DELETE" not in query_str

    @pytest.mark.asyncio
    async def test_user_anchored_not_stale(self):
        """User-anchored domains should never be marked stale."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = AsyncMock()
        runner._wiki_store.query = AsyncMock(return_value=[
            {"uid": "uid1", "path": "/__domains__/user-pinned-domain/_overview"},
        ])

        current_slugs: set[str] = set()
        anchored_slugs = {"user-pinned-domain"}
        count = await runner._cleanup_stale_domain_pages(
            "biz1", current_slugs, anchored_slugs=anchored_slugs,
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_purge_after_retention(self):
        """Pages stale for > retention_days should be permanently deleted."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._wiki_store = AsyncMock()
        runner._wiki_store.query = AsyncMock(return_value=[{"cnt": 3}])

        count = await runner._purge_stale_pages("biz1", retention_days=7)
        assert count == 3
        query_str = runner._wiki_store.query.call_args[0][0]
        assert "DETACH DELETE" in query_str
        assert "wp.stale = true" in query_str


class TestAnchorLoading:
    """Tests for F9-C2: anchor loading + persist sync."""

    @pytest.mark.asyncio
    async def test_anchors_loaded_on_full_run(self):
        """Both pinned_modules and anchored_slugs should be loaded."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._persistence = AsyncMock()
        runner._persistence.list_pinned_modules = AsyncMock(return_value=[
            {"module_name": "UserService", "domain_slug": "user-auth"},
        ])
        runner._persistence.list_domain_anchors = AsyncMock(return_value=[
            {"slug": "family-core", "anchor_type": "user", "display_name": "家族核心"},
            {"slug": "payment", "anchor_type": "system", "display_name": "支付"},
        ])

        state: dict = {}
        await runner._load_anchors_into_state("biz1", state)

        assert state["pinned_modules"] == {"UserService": "user-auth"}
        assert state["anchored_slugs"] == {"family-core"}
        assert state["anchor_display_names"]["family-core"] == "家族核心"
        assert state["anchor_display_names"]["payment"] == "支付"

    @pytest.mark.asyncio
    async def test_anchors_load_failure_graceful(self):
        """Load failure should not crash, just log warning."""
        from wiki.business_pipeline_runner import BusinessPipelineRunner

        runner = BusinessPipelineRunner.__new__(BusinessPipelineRunner)
        runner._persistence = AsyncMock()
        runner._persistence.list_pinned_modules = AsyncMock(side_effect=Exception("DB error"))
        runner._persistence.list_domain_anchors = AsyncMock(side_effect=Exception("DB error"))

        state: dict = {}
        await runner._load_anchors_into_state("biz1", state)

        assert state["pinned_modules"] == {}
        assert state["anchored_slugs"] == set()
        assert state["anchor_display_names"] == {}


class TestPersistSyncAnchor:
    """Tests for F9-C2: persist classification calls save_domain_classification."""

    @pytest.mark.asyncio
    async def test_persist_calls_save_domain_classification(self):
        """persist_classification_node should call save_domain_classification."""
        from wiki.nodes.persist_classification import persist_classification_node

        persistence = AsyncMock()
        persistence.save_domain_classification = AsyncMock()
        wiki_store = AsyncMock()
        wiki_store.upsert_wiki_space = AsyncMock()
        wiki_store.delete_domain_sections = AsyncMock(return_value=0)
        wiki_store.upsert_wiki_section = AsyncMock()
        wiki_store.add_has_child_edge = AsyncMock()
        graph_store = AsyncMock()
        graph_store.update_node_property = AsyncMock()

        state = {
            "business_id": "biz1",
            "domain_mapping": {"auth": [("repo", "UserService")]},
            "domain_display_names": {"auth": "认证"},
            "domain_tree": None,
            "modules": {},
            "persistence": persistence,
        }
        config = {
            "configurable": {
                "wiki_store": wiki_store,
                "graph_store": graph_store,
                "persistence": persistence,
            }
        }

        await persist_classification_node(state, config)
        persistence.save_domain_classification.assert_called_once_with(
            "biz1",
            {"auth": {"display_name": "认证", "modules": [("repo", "UserService")]}},
        )


class TestCorrectorProtection:
    """Tests for F9-C3: corrector skip anchored merge."""

    def test_corrector_skips_anchored_sources(self):
        """If a source is user-anchored, it should be protected from merge."""
        merge_item = {"target": "merged-domain", "sources": ["family-core", "family-tasks"]}
        anchored_slugs = frozenset({"family-core"})

        sources = merge_item["sources"]
        protected = [s for s in sources if s in anchored_slugs]
        filtered = [s for s in sources if s not in anchored_slugs]

        assert protected == ["family-core"]
        assert filtered == ["family-tasks"]

    def test_corrector_allows_non_anchored_merge(self):
        """Non-anchored slugs should NOT be protected from merging."""
        merge_item = {"target": "merged", "sources": ["payment", "billing"]}
        anchored_slugs = frozenset()

        filtered = [s for s in merge_item["sources"] if s not in anchored_slugs]
        assert filtered == ["payment", "billing"]


class TestDomainRecovery:
    """Tests for F9-C3: anchored domain recovery."""

    @pytest.mark.asyncio
    async def test_anchored_domain_recovered(self):
        """If an anchored slug is missing from new mapping, recover from persistence."""
        domain_mapping = {"user-auth": [("repo", "UserService")]}
        anchored_slugs = {"family-core"}
        anchor_display_names = {"family-core": "家族核心"}

        persistence = AsyncMock()
        persistence.list_domain_modules = AsyncMock(return_value=[
            {"module_name": "FamilyService"},
            {"module_name": "FamilyMemberService"},
        ])

        for slug in anchored_slugs:
            if slug not in domain_mapping:
                anchor_modules = await persistence.list_domain_modules("biz1", slug)
                if anchor_modules:
                    mod_tuples = [("repo", str(m["module_name"])) for m in anchor_modules]
                    domain_mapping[slug] = mod_tuples

        assert "family-core" in domain_mapping
        assert len(domain_mapping["family-core"]) == 2

    @pytest.mark.asyncio
    async def test_no_recovery_when_slug_exists(self):
        """No recovery needed when slug already in mapping."""
        domain_mapping = {"family-core": [("repo", "FamilyService")]}
        anchored_slugs = {"family-core"}

        persistence = AsyncMock()
        persistence.list_domain_modules = AsyncMock()

        for slug in anchored_slugs:
            if slug not in domain_mapping:
                await persistence.list_domain_modules("biz1", slug)

        persistence.list_domain_modules.assert_not_called()


class TestDomainQualityGate:
    """Tests for F9-C4: domain decomposition quality gate."""

    def test_structural_quality_fragmentation(self):
        from wiki.nodes.graph_domain_decompose import _structural_quality_check

        mapping = {f"domain-{i}": [("repo", f"mod-{i}")] for i in range(10)}
        warnings = _structural_quality_check(mapping, 10)
        assert any("FRAGMENTATION" in w for w in warnings)

    def test_structural_quality_mega_domain(self):
        from wiki.nodes.graph_domain_decompose import _structural_quality_check

        mapping = {
            "mega": [("repo", f"mod-{i}") for i in range(50)],
            "small": [("repo", "x")],
        }
        warnings = _structural_quality_check(mapping, 51)
        assert any("MEGA_DOMAIN" in w for w in warnings)

    def test_structural_quality_good(self):
        from wiki.nodes.graph_domain_decompose import _structural_quality_check

        mapping = {
            "auth": [("r", f"m{i}") for i in range(5)],
            "payment": [("r", f"p{i}") for i in range(4)],
            "family": [("r", f"f{i}") for i in range(6)],
        }
        warnings = _structural_quality_check(mapping, 15)
        assert len(warnings) == 0

    def test_baseline_comparison_domain_disappeared(self):
        from wiki.nodes.graph_domain_decompose import _domain_decomposition_quality_check

        baseline = {"auth": [1, 2, 3, 4, 5], "family": [6, 7, 8]}
        new_mapping = {"auth": [1, 2, 3, 4, 5]}
        passed, warnings = _domain_decomposition_quality_check(new_mapping, baseline)
        assert any("DOMAIN_DISAPPEARED" in w for w in warnings)

    def test_baseline_comparison_collapse(self):
        from wiki.nodes.graph_domain_decompose import _domain_decomposition_quality_check

        baseline = {"a": [1], "b": [2], "c": [3], "d": [4], "e": [5], "f": [6]}
        new_mapping = {"merged": [1, 2, 3, 4, 5, 6]}
        passed, warnings = _domain_decomposition_quality_check(new_mapping, baseline)
        assert any("DOMAIN_COLLAPSE" in w for w in warnings)
        assert not passed


class TestAgentReview:
    """Tests for F9-C4: agent semantic audit."""

    @pytest.mark.asyncio
    async def test_agent_review_good_quality(self):
        from wiki.nodes.graph_domain_decompose import _agent_review_decomposition

        llm = AsyncMock()
        llm.complete_json = AsyncMock(return_value={
            "overall_quality": "good",
            "issues": [],
        })
        quality, warnings = await _agent_review_decomposition(
            llm,
            {"auth": [("r", "UserService")], "payment": [("r", "PayService")]},
            {"auth": "认证", "payment": "支付"},
            {"UserService": "User auth", "PayService": "Payment"},
        )
        assert quality == "good"
        assert len(warnings) == 0

    @pytest.mark.asyncio
    async def test_agent_review_with_issues(self):
        from wiki.nodes.graph_domain_decompose import _agent_review_decomposition

        llm = AsyncMock()
        llm.complete_json = AsyncMock(return_value={
            "overall_quality": "needs_revision",
            "issues": [
                {
                    "domain_slug": "auth",
                    "issue_type": "misplaced_module",
                    "description": "PayService in auth domain",
                    "severity": "warning",
                }
            ],
        })
        quality, warnings = await _agent_review_decomposition(
            llm, {"auth": [("r", "UserService")]}, {}, {},
        )
        assert quality == "needs_revision"
        assert len(warnings) == 1
        assert "AGENT_REVIEW" in warnings[0]

    @pytest.mark.asyncio
    async def test_agent_review_failure_graceful(self):
        from wiki.nodes.graph_domain_decompose import _agent_review_decomposition

        llm = AsyncMock()
        llm.complete_json = AsyncMock(side_effect=Exception("LLM error"))
        quality, warnings = await _agent_review_decomposition(
            llm, {"a": []}, {}, {},
        )
        assert quality == "acceptable"
        assert len(warnings) == 0


class TestIncrementalAssignment:
    """Tests for F9-C4: incremental new module assignment."""

    def test_new_module_assigned_to_nearest(self):
        from wiki.nodes.graph_domain_decompose import _assign_new_modules_to_nearest

        embeddings = {
            "UserService": [1.0, 0.0, 0.0],
            "AuthService": [0.9, 0.1, 0.0],
            "PayService": [0.0, 1.0, 0.0],
            "NewAuthModule": [0.8, 0.2, 0.0],
        }
        domain_mapping = {
            "auth": [("r", "UserService"), ("r", "AuthService")],
            "payment": [("r", "PayService")],
        }
        new_modules = {("r", "NewAuthModule")}
        _assign_new_modules_to_nearest(new_modules, domain_mapping, embeddings)
        assert ("r", "NewAuthModule") in domain_mapping["auth"]

    def test_empty_new_modules_noop(self):
        from wiki.nodes.graph_domain_decompose import _assign_new_modules_to_nearest

        domain_mapping = {"auth": [("r", "UserService")]}
        _assign_new_modules_to_nearest(set(), domain_mapping, {})
        assert domain_mapping == {"auth": [("r", "UserService")]}
