import auth as auth_module
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _open_access_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_token_registry", {})


def test_mcp_tool_list_returns_tools():
    from main import create_app
    app = create_app()
    app.state.wiki_store = MagicMock()
    
    client = TestClient(app)
    resp = client.get("/api/v1/mcp/tools/list")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert len(data["tools"]) >= 5
