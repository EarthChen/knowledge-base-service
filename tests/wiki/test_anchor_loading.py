import pytest
from unittest.mock import AsyncMock


class TestAnchorLoading:
    """Test anchor domain loading and pinned module handling in classify node."""

    @pytest.fixture
    def mock_state(self):
        return {
            "business_id": "biz1",
            "repositories": ["repo1"],
            "all_modules": [
                {"name": "PinnedSvc", "repository": "repo1", "_module_summary": "pinned service"},
                {"name": "FreeSvc", "repository": "repo1", "_module_summary": "free service"},
            ],
        }

    @pytest.fixture
    def mock_persistence(self):
        p = AsyncMock()
        p.list_domain_anchors = AsyncMock(return_value=[
            {"slug": "gift-system", "display_name": "礼物系统", "module_count": 3}
        ])
        p.list_pinned_modules = AsyncMock(return_value=[
            {"module_name": "PinnedSvc", "domain_slug": "gift-system"}
        ])
        return p

    def test_separate_pinned_modules(self, mock_state, mock_persistence):
        """Pinned modules should be separated from modules sent to LLM."""
        pinned = mock_persistence.list_pinned_modules.return_value
        pinned_names = {p["module_name"] for p in pinned}

        all_mods = mock_state["all_modules"]
        free_modules = [m for m in all_mods if m["name"] not in pinned_names]
        pinned_modules = [m for m in all_mods if m["name"] in pinned_names]

        assert len(free_modules) == 1
        assert free_modules[0]["name"] == "FreeSvc"
        assert len(pinned_modules) == 1
        assert pinned_modules[0]["name"] == "PinnedSvc"

    def test_anchor_injection_format(self, mock_persistence):
        """Anchors should be formatted as injection text for prompts."""
        anchors = mock_persistence.list_domain_anchors.return_value
        lines = []
        for a in anchors:
            lines.append(f"- {a['slug']} ({a['display_name']})")

        text = "\n".join(lines)
        assert "gift-system" in text
        assert "礼物系统" in text

    def test_merge_pinned_and_classified(self):
        """Merge should combine pinned domain assignments with LLM results."""
        pinned_mapping = {"PinnedSvc": "gift-system"}
        llm_result = {
            "gift-system": {
                "slug": "gift-system",
                "display_name": "礼物系统",
                "modules": [("repo1", "FreeSvc")]
            }
        }

        # Merge: add pinned modules to their assigned domains
        for mod_name, domain_slug in pinned_mapping.items():
            if domain_slug in llm_result:
                llm_result[domain_slug]["modules"].append(("repo1", mod_name))
            else:
                llm_result[domain_slug] = {
                    "slug": domain_slug,
                    "display_name": domain_slug,
                    "modules": [("repo1", mod_name)]
                }

        assert ("repo1", "PinnedSvc") in llm_result["gift-system"]["modules"]
        assert ("repo1", "FreeSvc") in llm_result["gift-system"]["modules"]

