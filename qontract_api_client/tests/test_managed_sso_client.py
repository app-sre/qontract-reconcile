import asyncio
import json

import httpx2
import pytest
from clientele.http.httpx_backend import HttpxHTTPBackend

from qontract_api_client import client, schemas


@pytest.mark.parametrize("config", [None, {}, {"access.token.claim": "true"}])
def test_managed_sso_client_serializes_mapper_config(
    config: dict[str, str] | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapper = schemas.ProtocolMapperDesiredState.model_validate({
        "name": "full-name",
        "protocol_mapper": "oidc-full-name-mapper",
        **({"config": config} if config is not None else {}),
    })
    data = schemas.ManagedSsoClientReconcileRequest(
        desired_clients=[
            schemas.ManagedSsoClientDesiredState(
                client_id="test-client",
                keycloak_instance=schemas.KeycloakInstanceRef(
                    url="https://sso.example.com/realms/test",
                    initial_access_token=schemas.Secret(
                        secret_manager_url="https://vault.example.com",
                        path="test/iat",
                    ),
                ),
                oidc=schemas.OidcDesiredState(
                    redirect_uris=[], protocol_mappers=[mapper]
                ),
            )
        ]
    )

    def handle_request(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/integrations/managed-sso-client/reconcile"
        body = json.loads(request.content)
        assert body["dry_run"] is True
        desired = body["desired_clients"][0]
        assert desired["enabled"] is True
        assert desired["output"] is None
        assert desired["oidc"]["service_accounts_enabled"] is None
        assert desired["oidc"]["protocol_mappers"] == [
            {
                "name": "full-name",
                "protocol_mapper": "oidc-full-name-mapper",
                "config": config if config is not None else {},
                "protocol": "openid-connect",
            }
        ]
        return httpx2.Response(
            202, json={"id": "test-task", "status_url": "/test-task"}
        )

    backend = HttpxHTTPBackend({
        "base_url": "https://qapi.example.com",
        "transport": httpx2.MockTransport(handle_request),
    })
    monkeypatch.setattr(client.client.config, "http_backend", backend)

    async def send_request() -> None:
        try:
            response = await client.managed_sso_client(data=data)
            assert response.id == "test-task"
        finally:
            await backend.aclose()

    asyncio.run(send_request())
