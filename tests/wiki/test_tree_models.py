from wiki.models import (
    PageType,
    ScopeParam,
    WikiSectionNode,
    WikiSpaceNode,
    parse_scope,
)


def test_wiki_space_node_creation():
    node = WikiSpaceNode(
        uid="ws:default",
        business_id="default",
        title="Test Business",
        description="Test description",
    )
    assert node.business_id == "default"
    assert node.title == "Test Business"


def test_wiki_section_node_creation():
    node = WikiSectionNode(
        uid="wsec:user-mgmt",
        title="用户管理",
        description="User management domain",
        section_type="business_domain",
        sort_order=1,
    )
    assert node.section_type == "business_domain"
    assert node.auto_generated is True


def test_wiki_section_node_defaults():
    node = WikiSectionNode(
        uid="wsec:test",
        title="Test",
        description="",
        section_type="code_module",
        sort_order=0,
    )
    assert node.icon is None
    assert node.auto_generated is True


def test_page_type_domain_overview():
    assert PageType.DOMAIN_OVERVIEW == "domain_overview"


def test_page_type_business_flow():
    assert PageType.BUSINESS_FLOW == "business_flow"


def test_page_type_index():
    assert PageType.INDEX == "index"


def test_scope_param_business():
    scope = parse_scope("business")
    assert isinstance(scope, ScopeParam)
    assert scope.scope_type == "business"
    assert scope.value is None
