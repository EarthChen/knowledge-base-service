"""Integration tests for two-phase cross-file graph building."""
import pytest
from indexer.code_graph_builder import CodeGraphBuilder
from indexer.tree_sitter_parser import TreeSitterParser
from store.schema import EdgeType, NodeLabel


@pytest.fixture
def java_builder():
    parser = TreeSitterParser(supported_languages=["java"])
    return CodeGraphBuilder(parser=parser, file_extensions={"java": [".java"]})


@pytest.fixture
def python_builder():
    parser = TreeSitterParser(supported_languages=["python"])
    return CodeGraphBuilder(parser=parser, file_extensions={"python": [".py"]})


class TestCrossFileCallsJava:
    def test_controller_to_service_call_edge(self, java_builder):
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
        all_nodes, all_edges = java_builder.build_from_files(files)

        cross_file_calls = [
            e for e in all_edges
            if e.edge_type == EdgeType.CALLS
            and e.properties.get("cross_file") is True
        ]
        assert len(cross_file_calls) >= 1, (
            f"Expected cross-file CALLS but got {len(cross_file_calls)}. "
            f"All CALLS edges: {[(e.source_uid, e.target_uid, e.properties) for e in all_edges if e.edge_type == EdgeType.CALLS]}"
        )


class TestCrossFileInherits:
    def test_cross_file_inherits_edge(self, java_builder):
        base_code = "package com.example;\npublic class BaseService {}\n"
        child_code = (
            "package com.example;\n"
            "import com.example.BaseService;\n"
            "public class UserService extends BaseService {}\n"
        )
        files = {
            "com/example/BaseService.java": base_code,
            "com/example/UserService.java": child_code,
        }
        _, all_edges = java_builder.build_from_files(files)
        inherits = [e for e in all_edges if e.edge_type == EdgeType.INHERITS]
        assert len(inherits) >= 1


class TestCrossFileCallsPython:
    def test_service_to_repository_call(self, python_builder):
        repo_code = "class UserRepository:\n    def find_by_id(self, uid):\n        pass\n"
        service_code = (
            "from repo import UserRepository\n\n"
            "class UserService:\n"
            "    def __init__(self):\n"
            "        self.repo = UserRepository()\n"
            "    def get_user(self, uid):\n"
            "        return self.repo.find_by_id(uid)\n"
        )
        files = {"repo.py": repo_code, "service.py": service_code}
        _, all_edges = python_builder.build_from_files(files)
        cross_calls = [
            e for e in all_edges
            if e.edge_type == EdgeType.CALLS and e.properties.get("cross_file") is True
        ]
        assert len(cross_calls) >= 1, (
            f"Expected cross-file CALLS from service to repository; got {len(cross_calls)}. "
            f"All CALLS: {[(e.source_uid, e.target_uid, e.properties) for e in all_edges if e.edge_type == EdgeType.CALLS]}"
        )


class TestCrossFileImplementsJava:
    def test_class_implements_interface_across_files(self, java_builder):
        iface_code = (
            "package com.example;\n"
            "public interface OrderRepository {\n"
            "    void save();\n"
            "}\n"
        )
        impl_code = (
            "package com.example;\n"
            "import com.example.OrderRepository;\n"
            "public class OrderRepositoryImpl implements OrderRepository {\n"
            "    public void save() {}\n"
            "}\n"
        )
        files = {
            "com/example/OrderRepository.java": iface_code,
            "com/example/OrderRepositoryImpl.java": impl_code,
        }
        _, all_edges = java_builder.build_from_files(files)
        implements = [e for e in all_edges if e.edge_type == EdgeType.IMPLEMENTS]
        assert len(implements) >= 1, (
            f"Expected cross-file IMPLEMENTS edge; got {len(implements)}"
        )


class TestBuildFromFilesMultiModule:
    """Layer 0: ensure two-phase build scales to a small multi-file batch."""

    def test_build_from_files_eight_python_modules(self, python_builder):
        files = {"mod0.py": "def f0():\n    pass\n"}
        for i in range(1, 8):
            files[f"mod{i}.py"] = (
                f"import mod{i - 1}\n\n"
                f"def f{i}():\n"
                f"    mod{i - 1}.f{i - 1}()\n"
            )

        nodes, edges = python_builder.build_from_files(files)
        assert len(files) == 8
        funcs = [n for n in nodes if n.label == NodeLabel.FUNCTION]
        assert len(funcs) >= 8
        assert len(edges) >= 1


class TestBackwardCompatibility:
    def test_same_file_calls_still_work(self, python_builder):
        code = "def a():\n    b()\n\ndef b():\n    pass\n"
        files = {"test.py": code}
        _, all_edges = python_builder.build_from_files(files)
        calls = [e for e in all_edges if e.edge_type == EdgeType.CALLS]
        assert len(calls) >= 1

    def test_build_from_file_unchanged(self, python_builder):
        code = "def a():\n    b()\n\ndef b():\n    pass\n"
        nodes, edges = python_builder.build_from_file("test.py", content=code)
        calls = [e for e in edges if e.edge_type == EdgeType.CALLS]
        assert len(calls) >= 1
