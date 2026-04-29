"""tests/wiki/test_business_domain_injection.py"""


class TestBusinessDomainProperty:
    def test_update_business_domain_allowed(self):
        """business_domain should be in allowed properties for update_node_property."""
        from store.falkordb_store import FalkorDBStore
        assert "business_domain" in FalkorDBStore._ALLOWED_PROPERTIES
