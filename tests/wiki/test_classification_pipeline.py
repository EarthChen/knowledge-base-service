import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.domain_stabilizer import DomainStabilizer
from wiki.path_conventions import normalize_slug


class TestSlugConsistency:
    """Verify slug normalization is deterministic and stable."""

    def test_same_input_same_output(self):
        """Identical input should always produce identical slug."""
        for _ in range(100):
            assert normalize_slug("Gift System") == "gift-system"

    def test_similar_inputs_normalize(self):
        """Similar inputs should normalize to the same slug."""
        variants = ["gift system", "Gift System", "gift_system", "GIFT-SYSTEM"]
        slugs = {normalize_slug(v) for v in variants}
        assert len(slugs) == 1

    def test_slug_roundtrip(self):
        """Normalizing an already-normalized slug should be idempotent."""
        slug = normalize_slug("gift-system")
        assert normalize_slug(slug) == slug


class TestAnchorStability:
    """Verify anchor-based stability across classification runs."""

    @pytest.fixture
    def stabilizer(self):
        return DomainStabilizer(graph_store=None)

    def test_anchors_prevent_name_drift(self, stabilizer):
        """With anchors, the same domain should map to the same slug."""
        existing = [
            {"slug": "gift-system", "display_name": "礼物系统"},
            {"slug": "im-messaging", "display_name": "IM消息"},
        ]

        proposed1 = [
            {"slug": "gift-system", "display_name": "礼物系统"},
            {"slug": "im-messaging", "display_name": "IM消息"},
        ]
        result1 = stabilizer.stabilize_dual_sync(proposed1, existing)

        proposed2 = [
            {"slug": "gift-system", "display_name": "Gift System"},
            {"slug": "im-messaging", "display_name": "即时消息"},
        ]
        result2 = stabilizer.stabilize_dual_sync(proposed2, existing)

        assert set(result1.keys()) == set(result2.keys())
        assert result2["gift-system"]["display_name"] == "礼物系统"
        assert result2["im-messaging"]["display_name"] == "IM消息"

    def test_new_domain_added_to_existing(self, stabilizer):
        """A genuinely new domain should be added alongside existing ones."""
        existing = [{"slug": "gift-system", "display_name": "礼物系统"}]
        proposed = [
            {"slug": "gift-system", "display_name": "礼物系统"},
            {"slug": "payment", "display_name": "支付系统"},
        ]
        result = stabilizer.stabilize_dual_sync(proposed, existing)
        assert "gift-system" in result
        assert "payment" in result
        assert len(result) == 2


class TestPinnedModulePreservation:
    """Verify pinned modules survive classification changes."""

    def test_pinned_modules_skip_classification(self):
        """Pinned modules should be excluded from LLM classification."""
        all_modules = [
            {"name": "PinnedSvc", "repository": "r1"},
            {"name": "FreeSvc", "repository": "r1"},
            {"name": "AnotherSvc", "repository": "r1"},
        ]
        pinned = [
            {"module_name": "PinnedSvc", "domain_slug": "gift-system"},
        ]
        pinned_names = {p["module_name"] for p in pinned}

        free = [m for m in all_modules if m["name"] not in pinned_names]
        assert len(free) == 2
        assert all(m["name"] != "PinnedSvc" for m in free)

    def test_pinned_modules_merged_back(self):
        """Pinned modules should appear in final classification result."""
        llm_result = {
            "gift-system": {
                "slug": "gift-system",
                "display_name": "礼物系统",
                "modules": [("r1", "FreeSvc")],
            }
        }
        pinned_mapping = {"PinnedSvc": "gift-system"}

        for mod_name, domain_slug in pinned_mapping.items():
            if domain_slug in llm_result:
                llm_result[domain_slug]["modules"].append(("r1", mod_name))

        modules = llm_result["gift-system"]["modules"]
        names = [m[1] for m in modules]
        assert "PinnedSvc" in names
        assert "FreeSvc" in names


class TestPipelineIntegration:
    """End-to-end pipeline tests with mocked components."""

    @pytest.mark.asyncio
    async def test_persist_classification_node_saves(self):
        """persist_classification_node should save domain_mapping."""
        from wiki.nodes.persist_classification import persist_classification_node

        mock_persistence = AsyncMock()
        state = {
            "business_id": "biz1",
            "domain_mapping": {
                "gift-system": {
                    "slug": "gift-system",
                    "display_name": "礼物系统",
                    "modules": [("r1", "Svc")],
                }
            },
            "persistence": mock_persistence,
        }
        result = await persist_classification_node(state)
        assert result["classification_persisted"] is True
        mock_persistence.save_domain_classification.assert_called_once()

    @pytest.mark.asyncio
    async def test_checkpoint_lifecycle(self):
        """Checkpoint should be creatable, queryable, and deletable."""
        from wiki.persistence import WikiPersistence

        with tempfile.TemporaryDirectory() as tmpdir:
            p = WikiPersistence.__new__(WikiPersistence)
            p._store = AsyncMock()
            p._checkpoint_dir = tmpdir

            info = await p.get_checkpoint_info("test-biz")
            assert info is None

            db_path = os.path.join(tmpdir, "test-biz_wiki.db")
            with open(db_path, "w", encoding="utf-8") as f:
                f.write("checkpoint data")

            info = await p.get_checkpoint_info("test-biz")
            assert info is not None
            assert info["business_id"] == "test-biz"

            await p.delete_checkpoint("test-biz")
            info = await p.get_checkpoint_info("test-biz")
            assert info is None


class TestModuleEnricherIntegration:
    """Verify module enricher works with classify pipeline."""

    @pytest.mark.asyncio
    async def test_enricher_caches_across_calls(self):
        """ModuleEnricher should cache results and not re-query."""
        from wiki.module_enricher import ModuleEnricher

        mock_store = AsyncMock()
        mock_store.execute_query = AsyncMock(
            side_effect=[
                MagicMock(
                    data=[
                        {
                            "module_name": "Svc",
                            "repo": "r1",
                            "key_methods": ["handle", "process"],
                        }
                    ]
                ),
                MagicMock(data=[]),
                MagicMock(data=[]),
            ]
        )

        enricher = ModuleEnricher(mock_store)

        await enricher.enrich(["r1"], ["Svc"])
        first_count = mock_store.execute_query.call_count

        await enricher.enrich(["r1"], ["Svc"])
        assert mock_store.execute_query.call_count == first_count

    def test_enricher_get_returns_signals(self):
        """get() should return cached signals for known modules."""
        from wiki.module_enricher import ModuleEnricher

        enricher = ModuleEnricher(AsyncMock())
        enricher._cache[("r1", "Svc")] = {
            "key_methods": ["handle"],
            "callees": ["Dao"],
            "fan_out": 1,
        }

        signals = enricher.get("r1", "Svc")
        assert signals["key_methods"] == ["handle"]
        assert signals["callees"] == ["Dao"]
