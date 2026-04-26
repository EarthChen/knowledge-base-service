from wiki.tree_builder import WikiTreeBuilder


def test_generate_page_path_simple():
    builder = WikiTreeBuilder()
    path = builder.generate_page_path(
        domain="用户管理",
        repository="user-service",
        entity_name="UserController",
    )
    assert path == "/用户管理/user-service/UserController"


def test_generate_page_path_domain_overview():
    builder = WikiTreeBuilder()
    path = builder.generate_page_path(
        domain="用户管理",
        repository=None,
        entity_name=None,
        is_overview=True,
    )
    assert path == "/用户管理/_overview"


def test_generate_page_path_flow():
    builder = WikiTreeBuilder()
    path = builder.generate_page_path(
        domain="用户管理",
        repository=None,
        entity_name="用户注册流程",
        is_flow=True,
    )
    assert path == "/用户管理/用户注册流程/_flow"


def test_generate_section_uid():
    builder = WikiTreeBuilder()
    uid = builder.generate_section_uid("default", "用户管理")
    assert uid == "WikiSection:default:用户管理"


def test_generate_domain_and_repo_section_uid():
    builder = WikiTreeBuilder()
    assert builder.generate_domain_section_uid("b", "Dom") == "WikiSection:b:domain:Dom"
    assert builder.generate_repo_section_uid("b", "svc") == "WikiSection:b:repo:svc"


def test_generate_space_uid():
    builder = WikiTreeBuilder()
    uid = builder.generate_space_uid("default")
    assert uid == "WikiSpace:default"


def test_detect_naming_conflict():
    builder = WikiTreeBuilder()
    pages = [
        {"repository": "user-service", "entity_name": "UserService"},
        {"repository": "auth-service", "entity_name": "UserService"},
    ]
    conflicts = builder.detect_naming_conflicts(pages)
    assert "UserService" in conflicts
    assert set(conflicts["UserService"]) == {"user-service", "auth-service"}


def test_no_naming_conflict():
    builder = WikiTreeBuilder()
    pages = [
        {"repository": "user-service", "entity_name": "UserController"},
        {"repository": "auth-service", "entity_name": "AuthController"},
    ]
    conflicts = builder.detect_naming_conflicts(pages)
    assert len(conflicts) == 0


def test_detect_naming_conflicts_dedupes_duplicate_repo_entries():
    builder = WikiTreeBuilder()
    pages = [
        {"repository": "repo-a", "entity_name": "OrderService"},
        {"repository": "repo-a", "entity_name": "OrderService"},
        {"repository": "repo-b", "entity_name": "OrderService"},
    ]
    conflicts = builder.detect_naming_conflicts(pages)
    assert conflicts == {"OrderService": ["repo-a", "repo-b"]}


def test_content_hash():
    builder = WikiTreeBuilder()
    h1 = builder.compute_content_hash("hello world")
    h2 = builder.compute_content_hash("hello world")
    h3 = builder.compute_content_hash("different content")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex
