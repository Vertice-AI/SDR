from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import TenantNotFoundError
from app.main import create_app


def test_domain_error_vira_json_com_status_e_code() -> None:
    app: FastAPI = create_app()

    @app.get("/_boom")
    async def boom() -> None:
        raise TenantNotFoundError("tenant xyz não existe")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/_boom")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "tenant_not_found", "message": "tenant xyz não existe"}
    }
