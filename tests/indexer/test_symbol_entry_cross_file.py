"""Tests for lightweight _SymbolEntry cross-file resolution memory optimization."""

from __future__ import annotations

import pytest

from indexer.code_graph_builder import CodeGraphBuilder, _SymbolEntry
from indexer.tree_sitter_parser import TreeSitterParser
from store.schema import EdgeType, GraphNode, NodeLabel


@pytest.fixture
def java_builder() -> CodeGraphBuilder:
    parser = TreeSitterParser(supported_languages=["java"])
    return CodeGraphBuilder(parser=parser, file_extensions={"java": [".java"]})


class TestSymbolEntry:
    def test_symbol_entry_holds_required_fields(self) -> None:
        entry = _SymbolEntry(
            uid="Class:com/example/UserService.java:UserService:1",
            name="UserService",
            fqn="com.example.UserService",
            label=NodeLabel.CLASS,
            file_path="com/example/UserService.java",
            language="java",
        )
        assert entry.uid == "Class:com/example/UserService.java:UserService:1"
        assert entry.name == "UserService"
        assert entry.fqn == "com.example.UserService"
        assert entry.label == NodeLabel.CLASS
        assert entry.file_path == "com/example/UserService.java"
        assert entry.language == "java"

    def test_symbol_entry_from_graph_node(self, java_builder: CodeGraphBuilder) -> None:
        nodes, _ = java_builder.build_from_file(
            "com/example/UserService.java",
            content="public class UserService { public void save() {} }\n",
        )
        class_nodes = [n for n in nodes if n.label == NodeLabel.CLASS]
        assert len(class_nodes) == 1
        entry = CodeGraphBuilder._symbol_entry_from_node(class_nodes[0])
        assert entry is not None
        assert entry.name == "UserService"
        assert entry.label == NodeLabel.CLASS
        assert entry.language == "java"
        assert entry.uid == class_nodes[0].uid


class TestSymbolEntryCrossFileResolution:
    def test_build_global_symbol_table_accepts_symbol_entries(
        self, java_builder: CodeGraphBuilder,
    ) -> None:
        service_nodes, _ = java_builder.build_from_file(
            "com/example/UserService.java",
            content="public class UserService { public void save() {} }\n",
        )
        controller_nodes, _ = java_builder.build_from_file(
            "com/example/UserController.java",
            content="public class UserController { public void create() {} }\n",
        )
        entries = [
            e
            for n in service_nodes + controller_nodes
            if (e := CodeGraphBuilder._symbol_entry_from_node(n)) is not None
        ]
        table = java_builder._build_global_symbol_table(entries)
        assert "java" in table
        java_table = table["java"]
        assert any("UserService" in k for k in java_table)
        assert any("UserController" in k for k in java_table)

    def test_cross_file_calls_via_symbol_entries(self, java_builder: CodeGraphBuilder) -> None:
        service_code = (
            "package com.example;\n"
            "public class UserService {\n"
            "    public void save() {}\n"
            "}\n"
        )
        controller_code = (
            "package com.example;\n"
            "import com.example.UserService;\n"
            "public class UserController {\n"
            "    private UserService userService;\n"
            "    public void create() {\n"
            "        userService.save();\n"
            "    }\n"
            "}\n"
        )
        files = {
            "com/example/UserService.java": service_code,
            "com/example/UserController.java": controller_code,
        }
        _, all_edges = java_builder.build_from_files(files)
        cross_file_calls = [
            e for e in all_edges
            if e.edge_type == EdgeType.CALLS
            and e.properties.get("cross_file") is True
        ]
        assert len(cross_file_calls) >= 1
