"""Tests for call-relationship based Mermaid diagram injection."""

from __future__ import annotations

from wiki.nodes.domain_compose import _domain_call_edges, _inject_dependency_diagram


class TestInjectDependencyDiagram:
    def test_call_edges_produce_real_relationships(self) -> None:
        modules = ["AuthSvc", "UserSvc", "NotifySvc"]
        call_edges = [("AuthSvc", "UserSvc"), ("UserSvc", "NotifySvc"), ("AuthSvc", "NotifySvc")]
        result = _inject_dependency_diagram("# Overview\n", modules, call_edges=call_edges)
        assert "M0 --> M1" in result
        assert "M1 --> M2" in result
        assert "M0 --> M2" in result
        assert "M0 --> M1 --> M2" not in result.replace("M0 --> M2", "")

    def test_without_call_edges_falls_back_to_linear_chain(self) -> None:
        modules = ["A", "B", "C"]
        result = _inject_dependency_diagram("# Overview\n", modules)
        assert "M0 --> M1" in result
        assert "M1 --> M2" in result
        assert "M0 --> M2" not in result

    def test_empty_matching_edges_falls_back_to_linear_chain(self) -> None:
        modules = ["A", "B", "C"]
        call_edges = [("X", "Y")]
        result = _inject_dependency_diagram("# Overview\n", modules, call_edges=call_edges)
        assert "M0 --> M1" in result
        assert "M1 --> M2" in result

    def test_skips_self_loops_and_deduplicates(self) -> None:
        modules = ["A", "B"]
        call_edges = [("A", "A"), ("A", "B"), ("A", "B")]
        result = _inject_dependency_diagram("# Overview\n", modules, call_edges=call_edges)
        assert result.count("M0 --> M1") == 1
        assert "M0 --> M0" not in result

    def test_existing_mermaid_not_overwritten(self) -> None:
        content = "# Doc\n\n```mermaid\ngraph TD\n    X-->Y\n```\n"
        result = _inject_dependency_diagram(content, ["A", "B"], call_edges=[("A", "B")])
        assert result == content

    def test_single_module_no_diagram(self) -> None:
        result = _inject_dependency_diagram("# Overview\n", ["OnlyOne"])
        assert "## Architecture" not in result


class TestDomainCallEdges:
    def test_extracts_edges_for_domain_modules(self) -> None:
        module_names = ["PaySvc", "BillSvc"]
        all_edges = [
            {
                "source_repo": "repo-a",
                "source": "PaySvc",
                "target_repo": "repo-b",
                "target": "BillSvc",
                "source_key": "repo-a|PaySvc",
                "target_key": "repo-b|BillSvc",
                "weight": 3,
            },
            {
                "source_repo": "repo-x",
                "source": "Other",
                "target_repo": "repo-y",
                "target": "Else",
                "source_key": "repo-x|Other",
                "target_key": "repo-y|Else",
                "weight": 1,
            },
        ]
        edges = _domain_call_edges(module_names, all_edges)
        assert edges == [("PaySvc", "BillSvc")]

    def test_includes_edge_when_one_endpoint_in_domain(self) -> None:
        module_names = ["PaySvc"]
        all_edges = [
            {
                "source": "PaySvc",
                "target": "ExternalSvc",
            },
        ]
        edges = _domain_call_edges(module_names, all_edges)
        assert edges == [("PaySvc", "ExternalSvc")]
