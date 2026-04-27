from unittest.mock import MagicMock
from wiki.models import ImportanceTier


def _make_service(core=20000, standard=8000, skeleton=1000):
    from wiki.service import WikiService
    wiki_cfg = MagicMock()
    wiki_cfg.core_code_budget = core
    wiki_cfg.standard_code_budget = standard
    wiki_cfg.skeleton_code_budget = skeleton
    svc = WikiService.__new__(WikiService)
    svc._wiki_cfg = wiki_cfg
    return svc


def test_budget_for_tier_default_multiplier():
    svc = _make_service()
    assert svc._budget_for_tier(ImportanceTier.CORE) == 20000
    assert svc._budget_for_tier(ImportanceTier.STANDARD) == 8000
    assert svc._budget_for_tier(ImportanceTier.SKELETON) == 1000


def test_budget_for_tier_with_multiplier():
    svc = _make_service()
    assert svc._budget_for_tier(ImportanceTier.CORE, multiplier=1.5) == 30000
    assert svc._budget_for_tier(ImportanceTier.STANDARD, multiplier=2.0) == 16000
    assert svc._budget_for_tier(ImportanceTier.SKELETON, multiplier=0.5) == 500


def test_budget_for_tier_none_tier():
    svc = _make_service()
    assert svc._budget_for_tier(None, multiplier=1.0) == 8000
