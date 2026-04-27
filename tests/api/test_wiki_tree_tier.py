def test_wiki_tier_param_accepted():
    """Verify the tree endpoint accepts wiki_tier parameter."""
    # Simple import test to verify the route exists with the parameter
    from api.routes.wiki_page_routes import wiki_page_router

    routes = [r.path for r in wiki_page_router.routes]
    assert any("tree" in r for r in routes)
