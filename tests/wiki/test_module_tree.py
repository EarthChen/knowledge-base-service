import pytest
from wiki.models.module_tree import ModuleNode, ModuleTree


def test_module_node_is_leaf_when_no_children():
    node = ModuleNode(
        canonical_key="src-auth",
        entity_uids=["uid1", "uid2"],
        file_paths=["src/auth/login.py"],
    )
    assert node.is_leaf() is True


def test_module_node_is_not_leaf_with_children():
    child = ModuleNode(
        canonical_key="src-auth-login",
        entity_uids=["uid1"],
        file_paths=["src/auth/login.py"],
    )
    parent = ModuleNode(
        canonical_key="src-auth",
        entity_uids=["uid1", "uid2"],
        file_paths=["src/auth/login.py", "src/auth/register.py"],
        children=[child],
    )
    assert parent.is_leaf() is False


def test_module_tree_topological_order_leaves_first():
    leaf_a = ModuleNode(canonical_key="a", entity_uids=["u1"], file_paths=["a.py"])
    leaf_b = ModuleNode(canonical_key="b", entity_uids=["u2"], file_paths=["b.py"])
    parent = ModuleNode(
        canonical_key="root",
        entity_uids=["u1", "u2"],
        file_paths=["a.py", "b.py"],
        children=[leaf_a, leaf_b],
    )
    tree = ModuleTree(roots=[parent], repo_id="test-repo")
    order = tree.topological_order()
    keys = [n.canonical_key for n in order]
    assert keys.index("a") < keys.index("root")
    assert keys.index("b") < keys.index("root")


def test_module_tree_all_nodes_returns_all():
    leaf = ModuleNode(canonical_key="leaf", entity_uids=["u1"], file_paths=["a.py"])
    root = ModuleNode(
        canonical_key="root",
        entity_uids=["u1"],
        file_paths=["a.py"],
        children=[leaf],
    )
    tree = ModuleTree(roots=[root], repo_id="test-repo")
    all_nodes = tree.all_nodes()
    assert len(all_nodes) == 2
    assert {n.canonical_key for n in all_nodes} == {"root", "leaf"}


def test_module_tree_to_dict_roundtrip():
    leaf = ModuleNode(canonical_key="leaf", entity_uids=["u1"], file_paths=["a.py"])
    root = ModuleNode(
        canonical_key="root",
        entity_uids=["u1"],
        file_paths=["a.py"],
        children=[leaf],
    )
    tree = ModuleTree(roots=[root], repo_id="test-repo")
    data = tree.to_dicts()
    restored = ModuleTree.from_dicts(data, repo_id="test-repo")
    assert len(restored.roots) == 1
    assert restored.roots[0].canonical_key == "root"
    assert len(restored.roots[0].children) == 1
    assert restored.roots[0].children[0].canonical_key == "leaf"
