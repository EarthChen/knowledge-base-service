from __future__ import annotations

from api.routes.business_routes import router


class TestBusinessCRUD:
    def test_router_has_list_endpoint(self):
        paths = [r.path for r in router.routes]
        assert "/businesses" in paths or any("/businesses" in str(r.path) for r in router.routes)

    def test_router_has_create_endpoint(self):
        methods = []
        for r in router.routes:
            if hasattr(r, "methods"):
                methods.extend(r.methods)
        assert "POST" in methods
