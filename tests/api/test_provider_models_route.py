from __future__ import annotations

from api.routes.provider_routes import provider_router


def test_models_route_registered():
    routes = [r.path for r in provider_router.routes]
    assert "/api/v1/llm/providers/{name}/models" in routes
