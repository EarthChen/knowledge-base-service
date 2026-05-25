"""Verify _ALLOWED_PROPERTIES includes architecture layer fields."""

from store.falkordb_store import FalkorDBStore


def test_architecture_layer_in_allowed_properties() -> None:
    assert "wiki_architecture_layer" in FalkorDBStore._ALLOWED_PROPERTIES


def test_architecture_confidence_in_allowed_properties() -> None:
    assert "wiki_architecture_confidence" in FalkorDBStore._ALLOWED_PROPERTIES
