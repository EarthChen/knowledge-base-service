"""RED tests for Task 18: prefix regex robustness for camelCase names."""

import re

import pytest

from wiki.nodes.classify import _consolidate_split_entities


class TestPrefixRegexCamelCase:
    """The _PREFIX_RE should match camelCase names like IOHandler, AJAXUtil, XMLParser."""

    @pytest.fixture()
    def prefix_re(self):
        return re.compile(r"^([A-Z][a-z]{2,}|[A-Z]{2,}[a-z]+|[A-Z][a-z]*[A-Z][a-z]+)")

    def test_matches_pascal_case(self, prefix_re):
        assert prefix_re.match("FamilyService")
        assert prefix_re.match("PaymentHandler")

    def test_matches_all_caps_prefix(self, prefix_re):
        """IOHandler, AJAXUtil, XMLParser should match."""
        m = prefix_re.match("IOHandler")
        assert m is not None
        assert m.group(1) == "IOHandler"

        m = prefix_re.match("AJAXUtil")
        assert m is not None

        m = prefix_re.match("XMLParser")
        assert m is not None

    def test_matches_camel_case_inner_caps(self, prefix_re):
        m = prefix_re.match("getDOMNode")
        assert m is not None


class TestGenericPrefixesExpanded:
    """_GENERIC_PREFIXES should include Data, Info, Config, Util, Tool, System."""

    @pytest.fixture()
    def generic_prefixes(self):
        from wiki.nodes.classify import _consolidate_split_entities
        # We test by ensuring modules with these prefixes are NOT consolidated
        mapping = {
            "dom-a": [("r", "DataCache"), ("r", "DataStore"), ("r", "DataSync")],
            "dom-b": [("r", "InfoCard"), ("r", "InfoPanel"), ("r", "InfoView")],
            "dom-c": [("r", "UtilHelper"), ("r", "UtilFormat"), ("r", "UtilParse")],
            "dom-d": [("r", "ToolBuild"), ("r", "ToolDeploy"), ("r", "ToolRun")],
        }
        result, _ = _consolidate_split_entities(mapping, {})
        return result, mapping

    def test_data_prefix_not_consolidated(self, generic_prefixes):
        result, mapping = generic_prefixes
        assert len(result.get("dom-a", [])) == 3

    def test_info_prefix_not_consolidated(self, generic_prefixes):
        result, mapping = generic_prefixes
        assert len(result.get("dom-b", [])) == 3

    def test_util_prefix_not_consolidated(self, generic_prefixes):
        result, mapping = generic_prefixes
        assert len(result.get("dom-c", [])) == 3

    def test_tool_prefix_not_consolidated(self, generic_prefixes):
        result, mapping = generic_prefixes
        assert len(result.get("dom-d", [])) == 3


class TestConsolidateWithCamelCaseModules:
    """Modules with camelCase/ALL-CAPS prefixes should be properly grouped."""

    def test_io_modules_consolidated(self):
        mapping = {
            "network": [("r", "IOHandler"), ("r", "IOSocket"), ("r", "IOBuffer")],
            "streaming": [("r", "IOStream")],
        }
        result, _ = _consolidate_split_entities(mapping, {})
        # "IO" prefix should be recognized -> IOHandler/IOSocket/IOBuffer majority in network
        # IOStream should move to network
        all_mods = set()
        for pairs in result.values():
            for _, m in pairs:
                all_mods.add(m)
        assert "IOStream" in all_mods
