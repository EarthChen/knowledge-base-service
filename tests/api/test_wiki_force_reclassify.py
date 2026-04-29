import pytest
from api.models.wiki_models import BusinessWikiGenerateBody


def test_force_reclassify_default_false():
    body = BusinessWikiGenerateBody(business_id="default")
    assert body.force_reclassify is False


def test_force_reclassify_explicit_true():
    body = BusinessWikiGenerateBody(business_id="default", force_reclassify=True)
    assert body.force_reclassify is True
